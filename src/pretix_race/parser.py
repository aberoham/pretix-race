"""HTML parser for secondhand ticket listings."""

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag

CSRF_PATTERN = re.compile(r'name="csrfmiddlewaretoken" value="([^"]*)"')

# Fast path patterns for ticket detection
BUY_FORM_PATTERN = re.compile(
    r'<form[^>]*method="post"[^>]*action="([^"]*secondhand/buy/[^"]*)"[^>]*>'
    r'[^<]*<input[^>]*name="csrfmiddlewaretoken"[^>]*value="([^"]*)"',
    re.IGNORECASE | re.DOTALL,
)
# Extract ticket info from panel structure
# Anchors on "panel panel-default" to skip "How it works" panel (panel-info)
TICKET_PANEL_PATTERN = re.compile(
    r'<div class="panel panel-default">'                        # Anchor: ticket panels only
    r'.*?<h3 class="panel-title">([^<]+)</h3>'                  # Group 1: ticket type
    r'.*?<h2 class="text-primary">([^<]+)</h2>'                 # Group 2: price
    r'.*?<form[^>]*action="([^"]*secondhand/buy/[^"]*)"[^>]*>'  # Group 3: form action
    r'.*?name="csrfmiddlewaretoken"[^>]*value="([^"]*)"',       # Group 4: CSRF token
    re.IGNORECASE | re.DOTALL,
)


@dataclass
class TicketListing:
    """Represents a secondhand ticket available for purchase."""

    ticket_type: str
    price: str
    form_action: str
    form_data: dict[str, str]
    raw_html: str


@dataclass
class ParseResult:
    """Result of parsing the secondhand page."""

    tickets_available: bool
    listings: list[TicketListing]
    csrf_token: str | None
    error_message: str | None


def parse_secondhand_page(html: str) -> ParseResult:
    """Parse secondhand marketplace page for ticket listings.

    Args:
        html: Raw HTML content of the page

    Returns:
        ParseResult with ticket availability and listings
    """
    # FAST PATH 1: Check for "No tickets" marker before expensive parsing
    if "No tickets available" in html:
        # Extract CSRF token via regex (fast)
        match = CSRF_PATTERN.search(html)
        csrf_token = match.group(1) if match else None

        return ParseResult(
            tickets_available=False,
            listings=[],
            csrf_token=csrf_token,
            error_message=None,
        )

    # FAST PATH 2: Check for buy forms via regex (avoids BeautifulSoup)
    if "/secondhand/buy/" in html:
        listings = _extract_listings_fast(html)
        if listings:
            csrf_token = listings[0].form_data.get("csrfmiddlewaretoken")
            return ParseResult(
                tickets_available=True,
                listings=listings,
                csrf_token=csrf_token,
                error_message=None,
            )

    # SLOW PATH: Markup changed or complex structure - parse fully
    soup = BeautifulSoup(html, "lxml")

    # Extract CSRF token from various possible locations
    csrf_token = _extract_csrf_token(soup)

    # Check for "no tickets" message (double check via DOM)
    no_tickets_div = soup.find("div", class_="alert-warning")
    if no_tickets_div and "No tickets available" in no_tickets_div.get_text():
        return ParseResult(
            tickets_available=False,
            listings=[],
            csrf_token=csrf_token,
            error_message=None,
        )

    # Look for ticket listings
    listings = _extract_listings(soup)

    return ParseResult(
        tickets_available=len(listings) > 0,
        listings=listings,
        csrf_token=csrf_token,
        error_message=None,
    )


def _extract_listings_fast(html: str) -> list[TicketListing]:
    """Extract ticket listings using regex (fast path).

    This avoids BeautifulSoup parsing for the common case where
    the HTML structure matches the expected pretix format.
    """
    listings: list[TicketListing] = []

    # Try to match full panel structure (ticket type, price, form)
    for match in TICKET_PANEL_PATTERN.finditer(html):
        ticket_type = match.group(1).strip()
        price = match.group(2).strip()
        form_action = match.group(3)
        csrf_token = match.group(4)

        listings.append(TicketListing(
            ticket_type=ticket_type,
            price=price,
            form_action=form_action,
            form_data={"csrfmiddlewaretoken": csrf_token},
            raw_html="",
        ))

    # If panel pattern didn't match, try simpler form-only pattern
    if not listings:
        for match in BUY_FORM_PATTERN.finditer(html):
            form_action = match.group(1)
            csrf_token = match.group(2)

            listings.append(TicketListing(
                ticket_type="Ticket",
                price="Unknown",
                form_action=form_action,
                form_data={"csrfmiddlewaretoken": csrf_token},
                raw_html="",
            ))

    return listings


def _extract_csrf_token(soup: BeautifulSoup) -> str | None:
    """Extract CSRF token from page."""
    # Check meta tag
    meta = soup.find("meta", attrs={"name": "csrf-token"})
    if meta and isinstance(meta, Tag):
        content = meta.get("content")
        if isinstance(content, str):
            return content

    # Check hidden input
    csrf_input = soup.find("input", attrs={"name": "csrfmiddlewaretoken"})
    if csrf_input and isinstance(csrf_input, Tag):
        value = csrf_input.get("value")
        if isinstance(value, str):
            return value

    return None


def _extract_listings(soup: BeautifulSoup) -> list[TicketListing]:
    """Extract ticket listings from page.

    Note: The exact structure depends on the pretix secondhand plugin.
    This implementation looks for common patterns:
    - Forms with POST method containing ticket/item data
    - Buttons with "Buy" text
    - Product rows or ticket cards
    """
    listings: list[TicketListing] = []

    # Strategy 1: Look for forms with buy buttons
    forms = soup.find_all("form", method=lambda x: x and x.lower() == "post")
    for form in forms:
        if not isinstance(form, Tag):
            continue

        # Skip filter forms
        if "form-inline" in (form.get("class") or []):
            continue

        buy_button = form.find(
            ["button", "input"],
            string=lambda text: text and "buy" in text.lower() if text else False,
        )
        if not buy_button:
            # Also check for submit buttons
            buy_button = form.find("button", type="submit")
            if not buy_button:
                continue

        listing = _parse_form_listing(form)
        if listing:
            listings.append(listing)

    # Strategy 2: Look for ticket cards/rows with data attributes
    ticket_elements = soup.find_all(
        ["div", "article", "tr"],
        class_=lambda c: c
        and any(x in str(c).lower() for x in ["ticket", "listing", "product-row"]),
    )
    for elem in ticket_elements:
        if not isinstance(elem, Tag):
            continue

        # Find form within the element
        inner_form = elem.find("form")
        if inner_form and isinstance(inner_form, Tag):
            listing = _parse_form_listing(inner_form)
            if listing and listing not in listings:
                listings.append(listing)

    # Strategy 3: Look for standalone buy links/buttons with data attributes
    buy_links = soup.find_all("a", href=lambda h: h and "cart" in h.lower() if h else False)
    for link in buy_links:
        if not isinstance(link, Tag):
            continue
        href = link.get("href")
        if isinstance(href, str):
            listing = TicketListing(
                ticket_type="Unknown",
                price="Unknown",
                form_action=href,
                form_data={},
                raw_html=str(link),
            )
            listings.append(listing)

    return listings


def _parse_form_listing(form: Tag) -> TicketListing | None:
    """Parse a form element into a TicketListing."""
    action = form.get("action")
    if not isinstance(action, str):
        action = ""

    # Extract all hidden inputs and other form fields
    form_data: dict[str, str] = {}
    for inp in form.find_all("input"):
        if not isinstance(inp, Tag):
            continue
        name = inp.get("name")
        value = inp.get("value")
        if isinstance(name, str) and isinstance(value, str):
            form_data[name] = value

    # Try to extract ticket type and price from surrounding text
    ticket_type = "Ticket"
    price = "Unknown"

    # Look for price in the form or parent
    price_elem = form.find(class_=lambda c: c and "price" in str(c).lower())
    if price_elem:
        price = price_elem.get_text(strip=True)

    # Look for ticket type
    parent = form.parent
    if parent and isinstance(parent, Tag):
        type_elem = parent.find(["h3", "h4", "h5", "strong", "span"], class_=lambda c: c and "title" in str(c).lower())
        if type_elem:
            ticket_type = type_elem.get_text(strip=True)

    return TicketListing(
        ticket_type=ticket_type,
        price=price,
        form_action=action,
        form_data=form_data,
        raw_html=str(form)[:500],  # Truncate for logging
    )


def detect_rate_limit(html: str, status_code: int) -> tuple[bool, int | None]:
    """Detect rate limiting from response.

    Returns:
        Tuple of (is_rate_limited, retry_after_seconds)
    """
    if status_code == 429:
        # Try to parse Retry-After from page
        soup = BeautifulSoup(html, "lxml")
        # Look for any indication of wait time
        text = soup.get_text().lower()
        if "retry" in text or "wait" in text or "too many" in text:
            return True, 60  # Default 60 seconds
        return True, None

    if status_code == 503:
        return True, 30

    return False, None
