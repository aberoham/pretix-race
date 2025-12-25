"""Tests for monitor module."""

import pytest
from pathlib import Path

from pretix_race.monitor import NO_TICKETS_MARKER
from pretix_race.parser import parse_secondhand_page


SAMPLE_DIR = Path(__file__).parent.parent / "sample-responses"


def test_no_tickets_marker_matches_sample() -> None:
    """Verify NO_TICKETS_MARKER detects no-tickets in captured sample."""
    sample_file = SAMPLE_DIR / "sample_no-tickets_http200.html"
    html = sample_file.read_text()

    assert NO_TICKETS_MARKER in html


class TestTicketSamples:
    """Tests for parsing ticket samples with CSRF and cart URLs."""

    @pytest.mark.parametrize("filename", [
        "sample_ticket_type_a.html",
        "sample_ticket_type_b.html",
        "sample_ticket_type_a_2.html",
    ])
    def test_csrf_token_extracted(self, filename: str) -> None:
        """Verify CSRF token is extracted from ticket samples."""
        html = (SAMPLE_DIR / filename).read_text()
        result = parse_secondhand_page(html)

        assert result.csrf_token is not None
        assert len(result.csrf_token) > 20  # CSRF tokens are long

    @pytest.mark.parametrize("filename", [
        "sample_ticket_type_a.html",
        "sample_ticket_type_b.html",
        "sample_ticket_type_a_2.html",
    ])
    def test_tickets_detected(self, filename: str) -> None:
        """Verify tickets are detected in samples."""
        html = (SAMPLE_DIR / filename).read_text()
        result = parse_secondhand_page(html)

        assert result.tickets_available is True
        assert len(result.listings) >= 1

    @pytest.mark.parametrize("filename", [
        "sample_ticket_type_a.html",
        "sample_ticket_type_b.html",
        "sample_ticket_type_a_2.html",
    ])
    def test_form_action_extracted(self, filename: str) -> None:
        """Verify cart add URL (form action) is extracted."""
        html = (SAMPLE_DIR / filename).read_text()
        result = parse_secondhand_page(html)

        assert len(result.listings) >= 1
        listing = result.listings[0]

        # Form action should be the buy URL
        assert "/secondhand/buy/" in listing.form_action
        assert listing.form_action.startswith("https://") or listing.form_action.startswith("/")

    @pytest.mark.parametrize("filename", [
        "sample_ticket_type_a.html",
        "sample_ticket_type_b.html",
        "sample_ticket_type_a_2.html",
    ])
    def test_form_data_has_csrf(self, filename: str) -> None:
        """Verify form data includes CSRF token."""
        html = (SAMPLE_DIR / filename).read_text()
        result = parse_secondhand_page(html)

        assert len(result.listings) >= 1
        listing = result.listings[0]

        assert "csrfmiddlewaretoken" in listing.form_data
        assert len(listing.form_data["csrfmiddlewaretoken"]) > 20
