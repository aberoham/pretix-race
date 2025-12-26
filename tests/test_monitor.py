"""Tests for monitor module."""

import subprocess
import sys
from pathlib import Path

import pytest

from pretix_race.config import Config
from pretix_race.monitor import (
    MARKETPLACE_GONE_MESSAGES,
    MARKETPLACE_INACTIVE_MARKER,
    NO_TICKETS_MARKER,
)
from pretix_race.parser import parse_secondhand_page


SAMPLE_DIR = Path(__file__).parent.parent / "sample-responses"


def test_no_tickets_marker_matches_sample() -> None:
    """Verify NO_TICKETS_MARKER detects no-tickets in captured sample."""
    sample_file = SAMPLE_DIR / "sample_no-tickets_http200.html"
    html = sample_file.read_text()

    assert NO_TICKETS_MARKER in html


def test_marketplace_inactive_marker_matches_sample() -> None:
    """Verify MARKETPLACE_INACTIVE_MARKER detects inactive marketplace.

    When the secondhand marketplace is inactive, the server redirects to the
    main event page. The title contains 'Ticket marketplace is not currently active'.
    """
    sample_file = SAMPLE_DIR / "sample_marketplace_inactive.html"
    html = sample_file.read_text()

    assert MARKETPLACE_INACTIVE_MARKER in html


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


class TestPollInactiveMarketplace:
    """Test poll inactive marketplace feature."""

    def test_config_poll_inactive_interval_default_none(self) -> None:
        """Config.poll_inactive_interval should default to None."""
        config = Config()
        assert config.poll_inactive_interval is None

    def test_config_poll_inactive_interval_can_be_set(self) -> None:
        """Config.poll_inactive_interval can be set to an integer."""
        config = Config(poll_inactive_interval=120)
        assert config.poll_inactive_interval == 120

    def test_cli_accepts_poll_inactive_marketplace_flag(self) -> None:
        """CLI should accept --poll-inactive-marketplace flag."""
        result = subprocess.run(
            [sys.executable, "-m", "pretix_race", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "--poll-inactive-marketplace" in result.stdout

    def test_marketplace_gone_messages_exist(self) -> None:
        """Verify MARKETPLACE_GONE_MESSAGES list has entries."""
        assert len(MARKETPLACE_GONE_MESSAGES) >= 10
        # Verify messages are non-empty strings
        for msg in MARKETPLACE_GONE_MESSAGES:
            assert isinstance(msg, str)
            assert len(msg) > 10
