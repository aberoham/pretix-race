"""Configuration for the secondhand monitor."""

import platform
from dataclasses import dataclass, field
from urllib.parse import urlparse


def _default_user_agent() -> str:
    """Generate platform-appropriate user agent."""
    system = platform.system()
    if system == "Darwin":
        return (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/143.0.0.0 Safari/537.36"
        )
    elif system == "Windows":
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/143.0.0.0 Safari/537.36"
        )
    else:  # Linux and others
        return (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/143.0.0.0 Safari/537.36"
        )


def _default_sec_ch_ua_platform() -> str:
    """Generate platform-appropriate Sec-CH-UA-Platform header."""
    system = platform.system()
    if system == "Darwin":
        return '"macOS"'
    elif system == "Windows":
        return '"Windows"'
    else:
        return '"Linux"'


@dataclass(frozen=True)
class Config:
    """Monitor configuration."""

    # Site configuration - these must be provided
    base_url: str = "https://tickets.example.com"
    event_slug: str = "event"

    # Polling settings
    poll_interval_seconds: float = 15.0
    jitter_fraction: float = 0.20  # ±20% of poll interval for human-like timing
    backoff_max_seconds: float = 300.0

    # Filter preferences (empty = all tickets)
    item_filter: str = ""  # "965" for Ticket, "966" for Up-and-coming
    sort_order: str = "price_asc"

    # Response logging
    save_unusual_responses: bool = True
    response_log_dir: str = "live-responses"

    # Headless mode for servers without display
    headless: bool = False

    # Alerting - cross-platform options
    imessage_recipient: str | None = None  # Phone number or email for iMessage alerts (macOS only)
    webhook_url: str | None = None  # POST to this URL when tickets found (cross-platform)

    # Inactive marketplace polling (None = exit, int = poll interval in seconds)
    poll_inactive_interval: int | None = None

    # Platform-appropriate headers (auto-detected by default)
    user_agent: str = field(default_factory=_default_user_agent)
    sec_ch_ua: str = '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"'
    sec_ch_ua_mobile: str = "?0"
    sec_ch_ua_platform: str = field(default_factory=_default_sec_ch_ua_platform)

    @property
    def event_page_url(self) -> str:
        """Full URL to main event page."""
        return f"{self.base_url}/{self.event_slug}/"

    @property
    def secondhand_path(self) -> str:
        """Path to secondhand marketplace."""
        return f"/{self.event_slug}/secondhand/"

    @property
    def secondhand_url(self) -> str:
        """Full URL to secondhand marketplace (fallback, prefer discovered URL)."""
        return f"{self.base_url}{self.secondhand_path}"

    @property
    def cart_add_url(self) -> str:
        """Full URL to cart add endpoint."""
        return f"{self.base_url}/{self.event_slug}/cart/add"

    @property
    def checkout_url(self) -> str:
        """Full URL to checkout."""
        return f"{self.base_url}/{self.event_slug}/checkout/start"

    @property
    def domain(self) -> str:
        """Extract domain from base_url (e.g., 'tickets.example.com')."""
        return urlparse(self.base_url).netloc

    def get_poll_params(self) -> dict[str, str]:
        """Get query parameters for polling."""
        params: dict[str, str] = {}
        if self.item_filter:
            params["item"] = self.item_filter
        params["sort"] = self.sort_order
        return params


DEFAULT_CONFIG = Config()
