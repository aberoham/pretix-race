"""Tests for HTML parser."""

from pathlib import Path

import pytest

from pretix_race.parser import _extract_listings_fast, find_marketplace_link, parse_secondhand_page


SAMPLE_DIR = Path(__file__).parent.parent / "sample-responses"


NO_TICKETS_HTML = """
<!DOCTYPE html>
<html>
<body>
<main id="content">
    <h2>Ticket Marketplace</h2>
    <form class="form-inline text-right" method="get">
        <select name="item"><option value="">All tickets</option></select>
        <select name="sort"><option value="price_asc">Price (Low to High)</option></select>
        <button type="submit">Apply</button>
    </form>
    <hr>
    <div class="alert alert-warning">
        No tickets available at the moment. Check back later!
    </div>
</main>
</body>
</html>
"""


def test_parse_no_tickets() -> None:
    """Test parsing page with no tickets available."""
    result = parse_secondhand_page(NO_TICKETS_HTML)

    assert result.tickets_available is False
    assert len(result.listings) == 0
    assert result.error_message is None


# Sample HTML when tickets might be available (hypothetical structure)
TICKETS_AVAILABLE_HTML = """
<!DOCTYPE html>
<html>
<body>
<main id="content">
    <h2>Ticket Marketplace</h2>
    <input type="hidden" name="csrfmiddlewaretoken" value="test-csrf-token-123">
    <form class="form-inline text-right" method="get">
        <select name="item"><option value="">All tickets</option></select>
        <button type="submit">Apply</button>
    </form>
    <hr>
    <div class="ticket-listing product-row">
        <h4 class="title">Ticket</h4>
        <span class="price">€180.00</span>
        <form method="post" action="/event/cart/add">
            <input type="hidden" name="csrfmiddlewaretoken" value="test-csrf-token-123">
            <input type="hidden" name="item_12345" value="1">
            <button type="submit">Buy</button>
        </form>
    </div>
</main>
</body>
</html>
"""


def test_parse_with_tickets() -> None:
    """Test parsing page with available tickets."""
    result = parse_secondhand_page(TICKETS_AVAILABLE_HTML)

    assert result.tickets_available is True
    assert len(result.listings) >= 1
    assert result.csrf_token == "test-csrf-token-123"


def test_csrf_extraction() -> None:
    """Test CSRF token extraction."""
    result = parse_secondhand_page(TICKETS_AVAILABLE_HTML)
    assert result.csrf_token == "test-csrf-token-123"


class TestExtractListingsFast:
    """Tests for the fast-path regex extraction.

    These tests verify _extract_listings_fast() works correctly on real
    sample HTML, ensuring the regex patterns match the actual pretix format.
    """

    @pytest.mark.parametrize("filename,expected_ticket_type,expected_price", [
        ("sample_ticket_type_a.html", "Ticket – Type A", "190.00 EUR"),
        ("sample_ticket_type_b.html", "Ticket – Type B", "220.00 EUR"),
        ("sample_ticket_type_a_2.html", "Ticket – Type A", "190.00 EUR"),
    ])
    def test_extracts_ticket_info_from_samples(
        self, filename: str, expected_ticket_type: str, expected_price: str
    ) -> None:
        """Verify fast path extracts ticket type and price from real samples."""
        html = (SAMPLE_DIR / filename).read_text()

        listings = _extract_listings_fast(html)

        assert len(listings) >= 1
        listing = listings[0]
        assert listing.ticket_type == expected_ticket_type
        assert listing.price == expected_price

    @pytest.mark.parametrize("filename", [
        "sample_ticket_type_a.html",
        "sample_ticket_type_b.html",
        "sample_ticket_type_a_2.html",
    ])
    def test_extracts_form_action_from_samples(self, filename: str) -> None:
        """Verify fast path extracts buy URL from real samples."""
        html = (SAMPLE_DIR / filename).read_text()

        listings = _extract_listings_fast(html)

        assert len(listings) >= 1
        listing = listings[0]
        assert "/secondhand/buy/" in listing.form_action
        # Should be full URL or path
        assert listing.form_action.startswith("https://") or listing.form_action.startswith("/")

    @pytest.mark.parametrize("filename", [
        "sample_ticket_type_a.html",
        "sample_ticket_type_b.html",
        "sample_ticket_type_a_2.html",
    ])
    def test_extracts_csrf_token_from_samples(self, filename: str) -> None:
        """Verify fast path extracts CSRF token from real samples."""
        html = (SAMPLE_DIR / filename).read_text()

        listings = _extract_listings_fast(html)

        assert len(listings) >= 1
        listing = listings[0]
        assert "csrfmiddlewaretoken" in listing.form_data
        # CSRF tokens are typically 64 chars
        assert len(listing.form_data["csrfmiddlewaretoken"]) >= 20

    def test_returns_empty_for_no_tickets_page(self) -> None:
        """Verify fast path returns empty list when no tickets available."""
        html = (SAMPLE_DIR / "sample_no-tickets_http200.html").read_text()

        listings = _extract_listings_fast(html)

        assert listings == []

    def test_fast_path_matches_slow_path_count(self) -> None:
        """Verify fast path finds same number of listings as full parser."""
        html = (SAMPLE_DIR / "sample_ticket_type_a.html").read_text()

        fast_listings = _extract_listings_fast(html)
        full_result = parse_secondhand_page(html)

        assert len(fast_listings) == len(full_result.listings)

    def test_fast_path_form_action_matches_slow_path(self) -> None:
        """Verify fast path extracts same form_action as full parser."""
        html = (SAMPLE_DIR / "sample_ticket_type_a.html").read_text()

        fast_listings = _extract_listings_fast(html)
        full_result = parse_secondhand_page(html)

        assert len(fast_listings) >= 1
        assert len(full_result.listings) >= 1
        assert fast_listings[0].form_action == full_result.listings[0].form_action


class TestFindMarketplaceLink:
    """Tests for marketplace link detection on event pages."""

    def test_finds_marketplace_link_absolute_url(self) -> None:
        """Verify find_marketplace_link finds absolute marketplace URLs."""
        html = (SAMPLE_DIR / "sample_event_page.html").read_text()

        result = find_marketplace_link(html, "https://tickets.example.com")

        assert result is not None
        assert "secondhand/" in result
        assert result.startswith("https://")

    def test_returns_none_when_no_marketplace_link(self) -> None:
        """Verify find_marketplace_link returns None when no link present."""
        html = (SAMPLE_DIR / "sample_event_page_no_marketplace.html").read_text()

        result = find_marketplace_link(html, "https://tickets.example.com")

        assert result is None

    def test_resolves_relative_url(self) -> None:
        """Verify find_marketplace_link resolves relative URLs."""
        html = '<a href="/event/secondhand/">Marketplace</a>'

        result = find_marketplace_link(html, "https://tickets.example.com")

        assert result == "https://tickets.example.com/event/secondhand/"

    def test_handles_absolute_url_without_base(self) -> None:
        """Verify absolute URLs work even without base_url."""
        html = '<a href="https://tickets.example.com/event/secondhand/">Marketplace</a>'

        result = find_marketplace_link(html, "")

        assert result == "https://tickets.example.com/event/secondhand/"

    def test_ignores_non_secondhand_links(self) -> None:
        """Verify other links are not matched."""
        html = '<a href="/event/merch/">Merch</a><a href="/event/faq/">FAQ</a>'

        result = find_marketplace_link(html, "https://tickets.example.com")

        assert result is None

    def test_sample_event_page_has_marketplace_link(self) -> None:
        """Verify sample_event_page.html contains a valid marketplace link."""
        html = (SAMPLE_DIR / "sample_event_page.html").read_text()

        result = find_marketplace_link(html, "https://tickets.example.com")

        assert result is not None
        assert result == "https://tickets.example.com/event/secondhand/"
