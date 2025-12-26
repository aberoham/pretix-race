"""Main monitoring loop for secondhand tickets."""

import hashlib
import platform
import random
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx

from .config import Config, DEFAULT_CONFIG
from .parser import ParseResult, TicketListing, find_marketplace_link, parse_secondhand_page
from .session import SecondhandSession, RequestMetrics

# Expected content in "No tickets" page
NO_TICKETS_MARKER = "No tickets available at the moment"

# Messages displayed when marketplace is detected as inactive
MARKETPLACE_GONE_MESSAGES = [
    # Dark humor / self-deprecating
    "And thus, the marketplace has vanished. This is why we can't have nice things.",
    "The commons have been tragicked. Someone went and ruined it for everyone.",
    "Congratulations, fellow scrapers. We collectively destroyed it.",
    "Fun detected. Fun eliminated. Marketplace status: inactive.",
    "They took their ball and went home. Fair enough, honestly.",
    "Somewhere, a sysadmin is muttering 'this is why we can't have nice things.'",
    # Philosophical / reflective
    "What we obtain too cheap, we esteem too lightly. - Thomas Paine (probably about F5 keys)",
    "The tragedy of the commons plays out again. Garrett Hardin would be unsurprised.",
    "In the end, we are all just visitors in the marketplace of life.",
    "Perhaps the real tickets were the friends we made along the way. (They weren't.)",
    "Every shared resource contains the seeds of its own destruction.",
    "The marketplace has closed. Sometimes the only winning move is not to play.",
]

# Patterns for dynamic content to strip before hashing
DYNAMIC_PATTERNS = [
    re.compile(r'data-now="[^"]*"'),  # Unix timestamp
    re.compile(r'name="csrfmiddlewaretoken" value="[^"]*"'),  # CSRF token
    re.compile(r'\?version=[a-f0-9-]+'),  # Cache-busting versions
]


class SecondhandMonitor:
    """Monitors secondhand marketplace and handles ticket acquisition."""

    def __init__(self, config: Config = DEFAULT_CONFIG) -> None:
        self.config = config
        self.session = SecondhandSession(config)
        self._running = False
        self._baseline_hash: str | None = None
        self._response_dir: Path | None = None
        self._imessage_sent = False  # Only alert once
        self._marketplace_url: str | None = None  # Discovered from event page

    def run(self) -> None:
        """Main monitoring loop."""
        self._running = True
        self._log("Starting secondhand monitor...")
        jitter_pct = int(self.config.jitter_fraction * 100)
        self._log(f"Polling interval: {self.config.poll_interval_seconds}s (±{jitter_pct}% jitter)")

        # Setup response logging directory
        if self.config.save_unusual_responses:
            self._response_dir = Path(self.config.response_log_dir).expanduser()
            self._response_dir.mkdir(parents=True, exist_ok=True)
            self._log(f"Unusual responses saved to: {self._response_dir}")

        self._log("-" * 95)

        # Step 1: Discover marketplace via event page
        if not self._discover_marketplace():
            # Marketplace not found on event page
            if self.config.poll_inactive_interval:
                # Wait for marketplace link to appear
                self._log("")
                self._log("=" * 60)
                self._log("MARKETPLACE NOT YET AVAILABLE")
                self._log("=" * 60)
                message = random.choice(MARKETPLACE_GONE_MESSAGES)
                self._log(f'"{message}"')
                self._log("")
                jitter_pct = int(self.config.jitter_fraction * 100)
                self._log(f"Waiting for marketplace link to appear (checking every {self.config.poll_inactive_interval}s ±{jitter_pct}%)...")
                if not self._poll_for_marketplace_link():
                    self.session.close()
                    return  # User cancelled or error
            else:
                # Exit with helpful message
                self._log("")
                self._log("Marketplace link not found on event page.")
                self._log("TIP: Use --poll-inactive-marketplace N to wait for it to appear.")
                self.session.close()
                return

        # Step 2: Marketplace discovered, log session info
        self._log(f"Monitoring marketplace: {self._marketplace_url}")
        session_cookie = self.session.state.cookies.get("__QXSESSION", "N/A")
        self._log(f"Session established: __QXSESSION={session_cookie}")
        self._log("-" * 95)
        self._log("REQ# | STATUS | TTFB    | TTLB    | SIZE    | SESSION                          | RESULT")
        self._log("-" * 95)

        while self._running:
            try:
                result = self._poll_once()

                if result and result.tickets_available:
                    self._handle_tickets_found(result)

                # Wait for next poll with random jitter (human-like timing)
                base_wait = self.session.get_backoff_seconds()
                jitter_range = base_wait * self.config.jitter_fraction
                wait_time = base_wait + random.uniform(-jitter_range, jitter_range)

                if base_wait != self.config.poll_interval_seconds:
                    self._log(f"Backing off: waiting {wait_time:.1f}s")
                time.sleep(wait_time)

            except KeyboardInterrupt:
                self._log("\nStopping monitor...")
                self._running = False
            except Exception as e:
                self._log(f"Error during poll: {e}")
                self.session.record_error()
                time.sleep(self.session.get_backoff_seconds())

        self.session.close()

    def _poll_once(self) -> ParseResult | None:
        """Perform a single poll of the marketplace."""
        params = self.config.get_poll_params()

        # Use discovered marketplace URL
        if not self._marketplace_url:
            self._log("ERROR: No marketplace URL discovered")
            return None

        try:
            response, metrics = self.session.get(self._marketplace_url, params=params)

            # Get session cookie for logging
            session_cookie = self.session.state.cookies.get("__QXSESSION", "N/A")
            req_num = self.session.state.request_count
            response_text = response.text

            # Determine result string and check for unusual responses
            is_unusual = False
            if response.status_code != 200:
                result_str = f"HTTP {response.status_code}"
                is_unusual = True
            else:
                # Parse the page
                parse_result = parse_secondhand_page(response_text)
                if parse_result.tickets_available:
                    result_str = f"TICKETS FOUND ({len(parse_result.listings)})"
                    is_unusual = True  # Always save ticket pages!
                elif self._is_baseline_response(response_text):
                    result_str = "No tickets"
                else:
                    # Response differs from baseline - save it
                    result_str = "No tickets (UNUSUAL)"
                    is_unusual = True

            # Log metrics for this request
            self._log_request(req_num, metrics, session_cookie, result_str)

            # Save unusual responses for inspection
            if is_unusual and self._response_dir:
                self._save_response(req_num, response.status_code, response_text)

            # Handle error status codes
            retry_after_header = response.headers.get("Retry-After")
            if retry_after_header:
                try:
                    wait_seconds = int(retry_after_header)
                except ValueError:
                    wait_seconds = 60
                self._log(f"  └─ Retry-After header: waiting {wait_seconds}s")
                self.session.record_error()
                time.sleep(wait_seconds)
                return None

            if response.status_code == 429:
                self._log("  └─ Rate limited! Waiting 60s")
                self.session.record_error()
                time.sleep(60)
                return None

            if response.status_code == 409:
                self._log("  └─ Server busy! Waiting 5s")
                time.sleep(5)
                return None

            if response.status_code == 503:
                self._log("  └─ Service unavailable! Waiting 30s")
                self.session.record_error()
                time.sleep(30)
                return None

            if response.status_code != 200:
                self.session.record_error()
                return None

            # Update CSRF token if found
            if parse_result.csrf_token:
                self.session.update_csrf_token(parse_result.csrf_token)

            self.session.reset_errors()
            return parse_result

        except Exception as e:
            self._log(f"Request error: {e}")
            self.session.record_error()
            return None

    def _is_baseline_response(self, html: str) -> bool:
        """Check if response matches baseline 'No tickets' page.

        Strips dynamic content (timestamps, CSRF tokens) before comparing
        to avoid false positives from page metadata changes.
        """
        # Must have the "No tickets" message
        if NO_TICKETS_MARKER not in html:
            return False

        # Strip dynamic content before hashing
        normalized = html
        for pattern in DYNAMIC_PATTERNS:
            normalized = pattern.sub("", normalized)

        content_hash = hashlib.md5(normalized.encode()).hexdigest()

        # Set baseline on first request
        if self._baseline_hash is None:
            self._baseline_hash = content_hash
            self._log(f"  └─ Baseline hash set: {content_hash[:8]}")
            return True

        # Compare against baseline
        return content_hash == self._baseline_hash

    def _save_response(self, req_num: int, status_code: int, html: str) -> None:
        """Save unusual response HTML for later inspection."""
        if not self._response_dir:
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"response_{timestamp}_req{req_num}_http{status_code}.html"
        filepath = self._response_dir / filename

        try:
            filepath.write_text(html, encoding="utf-8")
            self._log(f"  └─ Saved response: {filename}")
        except Exception as e:
            self._log(f"  └─ Failed to save response: {e}")

    def _log_request(
        self, req_num: int, metrics: RequestMetrics, session: str, result: str
    ) -> None:
        """Log a single request with metrics."""
        # Format: REQ# | STATUS | TTFB | TTLB | SIZE | SESSION | RESULT
        line = (
            f"{req_num:4d} | "
            f"{metrics.status_code:6d} | "
            f"{metrics.ttfb_ms:6.0f}ms | "
            f"{metrics.ttlb_ms:6.0f}ms | "
            f"{metrics.content_length:6d}B | "
            f"{session[:32]:32s} | "
            f"{result}"
        )
        self._log(line)

    def _handle_tickets_found(self, result: ParseResult) -> None:
        """Handle the discovery of available tickets."""
        self._log("!" * 50)
        self._log(f"TICKETS FOUND! ({len(result.listings)} available)")
        self._log("!" * 50)

        # SPEED IS CRITICAL - add to cart FIRST, notify AFTER
        if result.listings:
            # Log what we found (brief)
            listing = result.listings[0]
            self._log(f"Grabbing: {listing.ticket_type} - {listing.price}")

            # ADD TO CART IMMEDIATELY
            success, redirect_url = self._add_to_cart(listing)

            if success:
                # Now notify (cart is secured)
                self._notify_desktop("Tickets Found!", "Added to cart - CHECKOUT NOW!")
                self._send_imessage(
                    f"🎫 TICKET IN CART! Go to checkout NOW! {redirect_url}"
                )
                self._send_webhook(
                    event="ticket_in_cart",
                    ticket=listing.ticket_type,
                    price=listing.price,
                    checkout_url=redirect_url,
                    cookies=self.session.get_cookies_for_chrome(),
                    cookie_script=self._build_cookie_script(self.session.get_cookies_for_chrome()),
                )
                self._handoff_to_browser(redirect_url)
                self._running = False
            else:
                # Failed - notify and retry
                self._notify_desktop("Tickets", "Cart add failed, retrying...")
                self._log("Failed to add to cart, will retry...")

                # Log other available tickets
                for i, other in enumerate(result.listings[1:], 2):
                    self._log(f"  Also available: {other.ticket_type} - {other.price}")

    def _add_to_cart(self, listing: TicketListing) -> tuple[bool, str | None]:
        """Attempt to add a ticket to cart.

        Returns:
            Tuple of (success, redirect_url) - redirect_url is where to go next
        """
        self._log(f"Adding to cart: {listing.ticket_type}")

        try:
            # Determine the cart add URL
            if listing.form_action.startswith("http"):
                url = listing.form_action
            elif listing.form_action.startswith("/"):
                url = f"{self.config.base_url}{listing.form_action}"
            else:
                url = self.config.cart_add_url

            self._log(f"  POST → {url}")
            self._log(f"  Form data: {listing.form_data}")

            # POST the form data
            response = self.session.post(url, listing.form_data)

            # Save detailed request/response for debugging
            self._save_cart_request(url, listing.form_data, response)

            final_url = str(response.url)
            self._log(f"  Response: HTTP {response.status_code} → {final_url}")

            # Check if we actually landed on checkout or got redirected back
            if "checkout" in final_url:
                self._log("Added to cart successfully!")
                return True, final_url
            elif "secondhand" in final_url:
                # Redirected back to secondhand page = ticket was taken
                self._log("  Cart add FAILED: ticket already taken (redirected to /secondhand/)")
                return False, None
            elif response.status_code in (200, 302):
                # Got 200/302 but not checkout or secondhand - unclear state
                self._log(f"  WARNING: Unexpected redirect to {final_url}")
                return False, None
            else:
                self._log(f"Cart add failed: HTTP {response.status_code}")
                return False, None

        except Exception as e:
            self._log(f"Cart add error: {e}")
            return False, None

    def _save_cart_request(self, url: str, form_data: dict[str, str], response: "httpx.Response") -> None:
        """Save detailed cart request/response for debugging."""
        if not self._response_dir:
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = self._response_dir / f"cart_add_{timestamp}.txt"

        try:
            lines = [
                "=" * 60,
                "CART ADD REQUEST/RESPONSE DEBUG",
                "=" * 60,
                "",
                "REQUEST:",
                f"  URL: {url}",
                "  Method: POST",
                "",
                "  Cookies sent:",
            ]
            for name, value in self.session.state.cookies.items():
                lines.append(f"    {name}={value}")

            lines.extend([
                "",
                "  Form data:",
            ])
            for name, value in form_data.items():
                lines.append(f"    {name}={value}")

            lines.extend([
                "",
                "RESPONSE:",
                f"  Status: {response.status_code}",
                f"  Final URL: {response.url}",
                "",
                "  Response headers:",
            ])
            for name, value in response.headers.items():
                lines.append(f"    {name}: {value}")

            lines.extend([
                "",
                "  Set-Cookie headers:",
            ])
            for cookie in response.cookies.jar:
                lines.append(f"    {cookie.name}={cookie.value}")

            lines.extend([
                "",
                "  Response body:",
                "-" * 40,
                response.text if response.text else "(empty)",
                "-" * 40,
            ])

            filepath.write_text("\n".join(lines), encoding="utf-8")
            self._log(f"  Debug saved: {filepath.name}")

        except Exception as e:
            self._log(f"  Failed to save debug: {e}")

    def _handoff_to_browser(self, redirect_url: str | None = None) -> None:
        """Export session and optionally open browser.

        In headless mode: just outputs cookies and checkout URL.
        In interactive mode: opens browser with Playwright.
        """
        cookies = self.session.get_cookies_for_chrome()
        checkout_url = redirect_url or self.config.checkout_url

        # Always log session cookies and script (terminal history)
        self._log("=" * 50)
        self._log("SESSION COOKIES:")
        for name, value in cookies.items():
            self._log(f"  {name}={value}")
        self._log("")
        self._log("CHECKOUT URL:")
        self._log(f"  {checkout_url}")
        self._log("")
        self._log("COOKIE INJECTION (paste in Chrome Console):")
        self._log(self._build_cookie_script(cookies))
        self._log("=" * 50)

        # Export cookies to timestamped file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if self._response_dir:
            cookie_file = self._response_dir / f"cookies_{timestamp}.txt"
        else:
            cookie_file = Path("live-responses") / f"cookies_{timestamp}.txt"
            cookie_file.parent.mkdir(parents=True, exist_ok=True)
        self.session.export_cookies_netscape(cookie_file)
        self._log(f"Cookies saved to: {cookie_file}")

        if self.config.headless:
            # Headless mode: no browser, just output
            self._log("")
            self._log("=" * 50)
            self._log("HEADLESS MODE - CHECKOUT IN CART")
            self._log("=" * 50)
            self._log("Use the cookies above to complete checkout from another machine.")
            return

        # Interactive mode: open browser with Playwright
        self._log("Opening browser with Playwright...")
        success = self._handoff_with_playwright(cookies, checkout_url)

        if not success:
            self._print_manual_cookie_instructions(cookies)

    def _handoff_with_playwright(
        self, cookies: dict[str, str], url: str
    ) -> bool:
        """Open browser with cookies injected via Playwright.

        Playwright injects cookies BEFORE navigating, so the first
        request already has the correct session.

        Only called in interactive (non-headless) mode.
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self._log("Playwright not installed!")
            return False

        try:
            with sync_playwright() as p:
                # Try system Chrome first (more stable), fall back to bundled Chromium
                try:
                    browser = p.chromium.launch(channel="chrome", headless=False)
                    self._log("Using system Chrome")
                except Exception:
                    self._log("System Chrome not found, using bundled Chromium")
                    browser = p.chromium.launch(headless=False)

                context = browser.new_context()

                # Inject cookies BEFORE navigating
                # NOTE: __Host- prefixed cookies MUST NOT have domain attribute!
                cookie_list = []
                for name, value in cookies.items():
                    if name.startswith("__Host-"):
                        # __Host- cookies: use url (not domain), path is implicit
                        cookie_list.append({
                            "name": name,
                            "value": value,
                            "url": f"{self.config.base_url}/",
                            "secure": True,
                            "httpOnly": True,
                        })
                    else:
                        # Regular cookies: use domain + path
                        cookie_list.append({
                            "name": name,
                            "value": value,
                            "domain": self.config.domain,
                            "path": "/",
                            "secure": True,
                            "httpOnly": True,
                        })
                context.add_cookies(cookie_list)  # type: ignore[arg-type]
                self._log(f"Injected {len(cookie_list)} cookies")

                # Navigate - cookies are already set
                page = context.new_page()
                page.goto(url)
                self._log(f"Browser opened: {url}")

                # Keep browser open for user interaction
                self._log("")
                self._log("=" * 50)
                self._log("BROWSER IS OPEN - COMPLETE CHECKOUT NOW!")
                self._log("=" * 50)
                self._log("Press Enter here when done to close browser...")
                input()

                browser.close()
                return True

        except Exception as e:
            self._log(f"Playwright error: {e}")
            return False

    def _build_cookie_script(self, cookies: dict[str, str]) -> str:
        """Build JavaScript to set cookies via cookieStore API.

        Uses the cookieStore API which can set __Host- prefixed cookies
        (unlike document.cookie which cannot).
        """
        cookie_sets = []
        for name, value in cookies.items():
            cookie_sets.append(
                f'  await cookieStore.set({{name: "{name}", value: "{value}", '
                f'path: "/", secure: true, sameSite: "lax"}})'
            )
        return "(async () => {\n" + ";\n".join(cookie_sets) + ";\n  location.reload();\n})()"

    def _print_manual_cookie_instructions(self, cookies: dict[str, str]) -> None:
        """Print instructions for manual cookie injection."""
        self._log("\n" + "=" * 50)
        self._log("MANUAL COOKIE INJECTION REQUIRED")
        self._log("=" * 50)
        self._log("1. In Chrome, open DevTools (Cmd+Option+I)")
        self._log("2. Go to Console tab")
        self._log("3. Paste and run this single command:")
        self._log("")
        self._log(self._build_cookie_script(cookies))
        self._log("")
        self._log("(This uses cookieStore API which works with __Host- cookies)")

    def _notify_desktop(self, title: str, message: str) -> None:
        """Send desktop notification (cross-platform)."""
        if platform.system() == "Darwin":
            try:
                script = f'display notification "{message}" with title "{title}" sound name "Glass"'
                subprocess.run(["osascript", "-e", script], check=False)
            except Exception:
                pass
        elif platform.system() == "Linux":
            # Try notify-send (requires libnotify)
            try:
                subprocess.run(
                    ["notify-send", "-u", "critical", title, message],
                    check=False,
                    capture_output=True,
                )
            except Exception:
                pass  # notify-send not available (headless server)
        # Windows: could add toast notification, but not a priority

    def _send_imessage(self, message: str) -> bool:
        """Send iMessage alert (only once per session).

        Returns True if message was sent successfully.
        """
        if not self.config.imessage_recipient:
            return False

        if self._imessage_sent:
            self._log("iMessage already sent this session, skipping")
            return False

        recipient = self.config.imessage_recipient
        self._log(f"Sending iMessage to {recipient}...")

        # Escape quotes in message
        safe_message = message.replace('"', '\\"')

        script = f'''
        tell application "Messages"
            set targetService to 1st account whose service type = iMessage
            set targetBuddy to participant "{recipient}" of targetService
            send "{safe_message}" to targetBuddy
        end tell
        '''

        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                self._log("iMessage sent successfully!")
                self._imessage_sent = True
                return True
            else:
                self._log(f"iMessage failed: {result.stderr.strip()}")
                return False
        except subprocess.TimeoutExpired:
            self._log("iMessage timed out")
            return False
        except Exception as e:
            self._log(f"iMessage error: {e}")
            return False

    def _send_webhook(self, **kwargs: str | dict[str, str] | None) -> bool:
        """Send webhook notification (cross-platform).

        Posts JSON payload to configured webhook URL.
        Includes cookies and cookie_script for completing checkout remotely.

        Returns True if webhook was sent successfully.
        """
        if not self.config.webhook_url:
            return False

        self._log(f"Sending webhook to {self.config.webhook_url}...")

        payload = {
            "timestamp": datetime.now().isoformat(),
            "target": self._marketplace_url or self.config.secondhand_url,
            **{k: v for k, v in kwargs.items() if v is not None},
        }

        try:
            import httpx

            response = httpx.post(
                self.config.webhook_url,
                json=payload,
                timeout=10.0,
            )
            if response.status_code < 300:
                self._log("Webhook sent successfully!")
                return True
            else:
                self._log(f"Webhook failed: HTTP {response.status_code}")
                return False
        except Exception as e:
            self._log(f"Webhook error: {e}")
            return False

    def _log(self, message: str) -> None:
        """Log a message with timestamp."""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{timestamp}] {message}")
        sys.stdout.flush()

    def _discover_marketplace(self) -> bool:
        """Navigate to main event page and find marketplace link.

        Returns True if marketplace found (URL stored in self._marketplace_url),
        False otherwise.
        """
        self._log(f"Checking event page: {self.config.event_page_url}")
        try:
            response, metrics = self.session.get(self.config.event_page_url)

            if response.status_code != 200:
                self._log(f"Event page returned HTTP {response.status_code}")
                return False

            marketplace_url = find_marketplace_link(response.text, self.config.base_url)

            if marketplace_url:
                self._marketplace_url = marketplace_url
                self._log(f"Found marketplace: {marketplace_url}")
                return True

            self._log("Marketplace link not found on event page")
            return False

        except Exception as e:
            self._log(f"Failed to fetch event page: {e}")
            return False

    def _poll_for_marketplace_link(self) -> bool:
        """Poll event page until marketplace link appears.

        Uses poll_inactive_interval with jitter. Returns True when marketplace
        is found (URL stored in self._marketplace_url), False if cancelled.
        """
        poll_count = 0
        while self._running:
            try:
                # Wait with jitter (same as normal polling)
                base_wait = float(self.config.poll_inactive_interval or 120)
                jitter_range = base_wait * self.config.jitter_fraction
                wait_time = base_wait + random.uniform(-jitter_range, jitter_range)
                time.sleep(wait_time)

                poll_count += 1

                # Check event page for marketplace link
                response, metrics = self.session.get(self.config.event_page_url)

                if response.status_code != 200:
                    self._log(f"  [{poll_count}] HTTP {response.status_code} - still checking...")
                    continue

                marketplace_url = find_marketplace_link(response.text, self.config.base_url)

                if not marketplace_url:
                    session_cookie = self.session.state.cookies.get("__QXSESSION", "N/A")
                    self._log(f"  [{poll_count}] Not yet available [session: {session_cookie[:16]}...]")
                    continue

                # Marketplace link found!
                self._marketplace_url = marketplace_url
                self._log("")
                self._log("=" * 60)
                self._log("MARKETPLACE IS NOW AVAILABLE!")
                self._log("=" * 60)
                self._log(f"Found: {marketplace_url}")
                self._log("Resuming normal monitoring...")
                self._log("")
                return True

            except KeyboardInterrupt:
                self._log("\nStopping monitor...")
                self._running = False
                return False
            except Exception as e:
                self._log(f"  [{poll_count}] Error: {e}")
                self.session.record_error()

        return False

    def stop(self) -> None:
        """Stop the monitor."""
        self._running = False
