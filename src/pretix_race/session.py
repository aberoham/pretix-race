"""HTTP session management with cookie persistence."""

import sys
import time
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from .config import Config, DEFAULT_CONFIG


# HTTP/2 servers typically limit streams per connection (e.g., 1000)
# When this limit is reached, we get a graceful GOAWAY and need to reconnect
MAX_REQUESTS_BEFORE_RECONNECT = 950  # Proactive reconnect before server limit


@dataclass
class RequestMetrics:
    """Timing metrics for a single request."""

    status_code: int
    ttfb_ms: float  # Time to first byte
    ttlb_ms: float  # Time to last byte (total)
    content_length: int
    content_encoding: str  # Track compression type


@dataclass
class SessionState:
    """Tracks session state including cookies and CSRF token."""

    cookies: dict[str, str] = field(default_factory=dict)
    csrf_token: str | None = None
    last_request_time: float = 0.0
    consecutive_errors: int = 0
    request_count: int = 0


class SecondhandSession:
    """Manages HTTP session for secondhand marketplace."""

    def __init__(self, config: Config = DEFAULT_CONFIG) -> None:
        self.config = config
        self.state = SessionState()
        self._client: httpx.Client | None = None

    def _get_client(self) -> httpx.Client:
        """Get or create HTTP client.

        Uses exact Chrome 143 headers to match real browser fingerprint.
        """
        if self._client is None:
            # Connection pool: keep connections alive between polls
            limits = httpx.Limits(
                max_connections=10,
                max_keepalive_connections=5,
                keepalive_expiry=60.0,  # Keep alive for 60s (longer than poll interval)
            )
            self._client = httpx.Client(
                headers={
                    # Exact Chrome headers (order matters for fingerprinting)
                    "User-Agent": self.config.user_agent,
                    "sec-ch-ua": self.config.sec_ch_ua,
                    "sec-ch-ua-mobile": self.config.sec_ch_ua_mobile,
                    "sec-ch-ua-platform": self.config.sec_ch_ua_platform,
                    "Accept": (
                        "text/html,application/xhtml+xml,application/xml;q=0.9,"
                        "image/avif,image/webp,image/apng,*/*;q=0.8,"
                        "application/signed-exchange;v=b3;q=0.7"
                    ),
                    # Note: httpx handles gzip/deflate/br, but not zstd
                    # We request what Chrome does, server will pick what it supports
                    "Accept-Encoding": "gzip, deflate, br, zstd",
                    "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
                    "Upgrade-Insecure-Requests": "1",
                    "sec-fetch-dest": "document",
                    "sec-fetch-mode": "navigate",
                    "sec-fetch-site": "none",
                    "sec-fetch-user": "?1",
                    "priority": "u=0, i",
                },
                follow_redirects=True,
                timeout=httpx.Timeout(10.0, connect=5.0),  # Aggressive: 5s connect, 10s total
                http2=True,  # Use HTTP/2 for faster multiplexing
                limits=limits,
            )
        return self._client

    def _get_cookie_header(self) -> str | None:
        """Build Cookie header from stored cookies."""
        if not self.state.cookies:
            return None
        return "; ".join(f"{k}={v}" for k, v in self.state.cookies.items())

    def get(
        self, url: str, params: dict[str, str] | None = None
    ) -> tuple[httpx.Response, RequestMetrics]:
        """Perform GET request with session cookies.

        Handles HTTP/2 connection limits by reconnecting transparently.

        Returns:
            Tuple of (response, metrics)
        """
        # Proactively reconnect before hitting server's stream limit
        if self.state.request_count > 0 and self.state.request_count % MAX_REQUESTS_BEFORE_RECONNECT == 0:
            self._reconnect("proactive refresh")

        return self._do_get(url, params, retry_on_disconnect=True)

    def _do_get(
        self,
        url: str,
        params: dict[str, str] | None = None,
        retry_on_disconnect: bool = True,
    ) -> tuple[httpx.Response, RequestMetrics]:
        """Internal GET implementation with optional retry on disconnect."""
        client = self._get_client()

        headers: dict[str, str] = {"Referer": self.config.secondhand_url}

        # Send stored cookies with request
        cookie_header = self._get_cookie_header()
        if cookie_header:
            headers["Cookie"] = cookie_header

        # Time the request
        start_time = time.perf_counter()

        try:
            # Use stream to measure TTFB vs TTLB
            with client.stream("GET", url, params=params, headers=headers) as response:
                ttfb = (time.perf_counter() - start_time) * 1000  # First byte received
                content = response.read()  # Read full body
                ttlb = (time.perf_counter() - start_time) * 1000  # Last byte received
        except Exception as e:
            # Handle HTTP/2 connection termination (GOAWAY)
            if retry_on_disconnect and self._is_connection_terminated_error(e):
                self._reconnect("GOAWAY received")
                # Retry once with fresh connection
                return self._do_get(url, params, retry_on_disconnect=False)
            raise

        self.state.request_count += 1
        self._update_cookies(response)
        self.state.last_request_time = time.time()

        # Track content encoding (what compression the server used)
        content_encoding = response.headers.get("content-encoding", "none")

        metrics = RequestMetrics(
            status_code=response.status_code,
            ttfb_ms=ttfb,
            ttlb_ms=ttlb,
            content_length=len(content),
            content_encoding=content_encoding,
        )

        return response, metrics

    def post(
        self, url: str, data: dict[str, Any], headers: dict[str, str] | None = None
    ) -> httpx.Response:
        """Perform POST request with session cookies and CSRF token.

        Handles HTTP/2 connection limits by reconnecting transparently.
        """
        return self._do_post(url, data, headers, retry_on_disconnect=True)

    def _do_post(
        self,
        url: str,
        data: dict[str, Any],
        headers: dict[str, str] | None = None,
        retry_on_disconnect: bool = True,
    ) -> httpx.Response:
        """Internal POST implementation with optional retry on disconnect."""
        client = self._get_client()

        post_headers: dict[str, str] = {
            "Referer": self.config.secondhand_url,
            "Origin": self.config.base_url,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        if headers:
            post_headers.update(headers)

        # Send stored cookies with request
        cookie_header = self._get_cookie_header()
        if cookie_header:
            post_headers["Cookie"] = cookie_header

        # Add CSRF token if we have one
        if self.state.csrf_token and "csrfmiddlewaretoken" not in data:
            data["csrfmiddlewaretoken"] = self.state.csrf_token

        try:
            response = client.post(url, data=data, headers=post_headers)
        except Exception as e:
            # Handle HTTP/2 connection termination (GOAWAY)
            if retry_on_disconnect and self._is_connection_terminated_error(e):
                self._reconnect("GOAWAY received")
                # Retry once with fresh connection
                return self._do_post(url, data, headers, retry_on_disconnect=False)
            raise

        self._update_cookies(response)
        self.state.last_request_time = time.time()

        return response

    def _update_cookies(self, response: httpx.Response) -> None:
        """Update stored cookies from response."""
        for cookie in response.cookies.jar:
            self.state.cookies[cookie.name] = cookie.value

    def update_csrf_token(self, token: str) -> None:
        """Update CSRF token from parsed HTML."""
        self.state.csrf_token = token

    def export_cookies_netscape(self, filepath: Path) -> None:
        """Export cookies in Netscape format for browser import."""
        lines = ["# Netscape HTTP Cookie File"]

        for name, value in self.state.cookies.items():
            # Format: domain, flag, path, secure, expiry, name, value
            line = f"{self.config.domain}\tTRUE\t/\tTRUE\t0\t{name}\t{value}"
            lines.append(line)

        filepath.write_text("\n".join(lines))

    def get_cookies_for_chrome(self) -> dict[str, str]:
        """Get cookies dict for Chrome automation."""
        return self.state.cookies.copy()

    def record_error(self) -> None:
        """Record a consecutive error for backoff calculation."""
        self.state.consecutive_errors += 1

    def reset_errors(self) -> None:
        """Reset error counter on successful request."""
        self.state.consecutive_errors = 0

    def get_backoff_seconds(self) -> float:
        """Calculate backoff time based on consecutive errors."""
        if self.state.consecutive_errors == 0:
            return self.config.poll_interval_seconds

        # Exponential backoff: 30s, 60s, 120s, 240s, max 300s
        backoff = min(
            30 * (2 ** (self.state.consecutive_errors - 1)),
            self.config.backoff_max_seconds,
        )
        return backoff

    def _reconnect(self, reason: str = "connection limit") -> None:
        """Close and recreate HTTP client for fresh connection.

        This is called proactively before hitting server limits or
        reactively when we receive a GOAWAY frame.
        """
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{timestamp}] RECONNECTING: {reason} (req #{self.state.request_count})")
        sys.stdout.flush()

        if self._client:
            try:
                self._client.close()
            except Exception:
                pass  # Ignore close errors
            self._client = None
        # Client will be recreated on next request via _get_client()

    def _is_connection_terminated_error(self, error: Exception) -> bool:
        """Check if error is an HTTP/2 connection termination (GOAWAY).

        HTTP/2 servers send GOAWAY with error_code=0 (NO_ERROR) when they
        want to gracefully close the connection, often after reaching
        their max streams per connection limit.
        """
        error_str = str(error)
        # h2 library's ConnectionTerminated error
        if "ConnectionTerminated" in error_str:
            return True
        # httpx wraps this as RemoteProtocolError
        if isinstance(error, httpx.RemoteProtocolError):
            return True
        return False

    def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            self._client.close()
            self._client = None

    def __enter__(self) -> "SecondhandSession":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
