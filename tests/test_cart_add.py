"""Tests for cart add functionality."""

from pathlib import Path

import httpx
import pytest
import respx

from pretix_race.config import Config
from pretix_race.session import SecondhandSession


SAMPLE_DIR = Path(__file__).parent.parent / "sample-responses"


# Test data - using example URLs
BUY_URL = "https://tickets.example.com/event/secondhand/buy/5g07vpf0krq5sl0e/"
CHECKOUT_URL = "https://tickets.example.com/event/checkout/questions/?"
SECONDHAND_URL = "https://tickets.example.com/event/secondhand/?sort=price_asc"
CSRF_TOKEN = "cwrf2tTu6fqmTsAO4qNCjlFe6KYfuBTjJFVx12GzDAhsfKD7we5FGAfIMwnhg7Q1"


class TestSessionPost:
    """Test session POST behavior with mocked HTTP."""

    @respx.mock
    def test_cookies_sent_in_header(self) -> None:
        """Verify session cookies are sent with POST requests."""
        # Setup mock
        route = respx.post(BUY_URL).mock(
            return_value=httpx.Response(200, text="OK")
        )

        # Create session with cookies
        session = SecondhandSession()
        session.state.cookies = {
            "__QXSESSION": "test-session-id",
            "__Host-pretix_csrftoken": "test-csrf",
        }

        # Make request
        session.post(BUY_URL, {"csrfmiddlewaretoken": CSRF_TOKEN})

        # Verify cookies were sent
        assert route.called
        request = route.calls.last.request
        cookie_header = request.headers.get("cookie", "")
        assert "__QXSESSION=test-session-id" in cookie_header
        assert "__Host-pretix_csrftoken=test-csrf" in cookie_header

        session.close()

    @respx.mock
    def test_csrf_token_added_to_form_data(self) -> None:
        """Verify CSRF token is auto-added if not in form data."""
        route = respx.post(BUY_URL).mock(
            return_value=httpx.Response(200, text="OK")
        )

        session = SecondhandSession()
        session.state.csrf_token = "stored-csrf-token"

        # POST without csrf in form data
        session.post(BUY_URL, {"other_field": "value"})

        # Verify CSRF was added
        assert route.called
        request = route.calls.last.request
        body = request.content.decode()
        assert "csrfmiddlewaretoken=stored-csrf-token" in body
        assert "other_field=value" in body

        session.close()

    @respx.mock
    def test_csrf_token_not_overwritten(self) -> None:
        """Verify explicit CSRF token is not overwritten by stored one."""
        route = respx.post(BUY_URL).mock(
            return_value=httpx.Response(200, text="OK")
        )

        session = SecondhandSession()
        session.state.csrf_token = "stored-csrf-token"

        # POST with explicit csrf in form data
        session.post(BUY_URL, {"csrfmiddlewaretoken": "explicit-token"})

        # Verify explicit token was used
        assert route.called
        request = route.calls.last.request
        body = request.content.decode()
        assert "csrfmiddlewaretoken=explicit-token" in body
        assert "stored-csrf-token" not in body

        session.close()

    @respx.mock
    def test_response_cookies_extracted(self) -> None:
        """Verify cookies from response are stored in session."""
        respx.post(BUY_URL).mock(
            return_value=httpx.Response(
                200,
                text="OK",
                headers={"Set-Cookie": "new_cookie=new_value; Path=/"},
            )
        )

        session = SecondhandSession()
        session.post(BUY_URL, {"csrfmiddlewaretoken": CSRF_TOKEN})

        assert "new_cookie" in session.state.cookies
        assert session.state.cookies["new_cookie"] == "new_value"

        session.close()


class TestCartAddSuccessDetection:
    """Test the success/failure detection logic based on final URL.

    These tests verify the URL-based logic that determines if cart add succeeded.
    The actual _add_to_cart method checks response.url after redirects.
    """

    def test_checkout_url_indicates_success(self) -> None:
        """URL containing 'checkout' means cart add succeeded."""
        assert "checkout" in CHECKOUT_URL

    def test_secondhand_url_indicates_failure(self) -> None:
        """URL containing 'secondhand' means ticket was taken."""
        assert "secondhand" in SECONDHAND_URL
        assert "checkout" not in SECONDHAND_URL

    @respx.mock
    def test_post_follows_redirects_to_checkout(self) -> None:
        """Verify POST follows redirect chain to checkout URL."""
        # Mock initial POST returning 302 redirect
        respx.post(BUY_URL).mock(
            return_value=httpx.Response(
                302,
                headers={"Location": CHECKOUT_URL},
            )
        )
        # Mock the redirect target
        respx.get(CHECKOUT_URL).mock(
            return_value=httpx.Response(200, text="Checkout page")
        )

        session = SecondhandSession()
        response = session.post(BUY_URL, {"csrfmiddlewaretoken": CSRF_TOKEN})

        # httpx follows redirects, final URL should be checkout
        assert str(response.url) == CHECKOUT_URL

        session.close()

    @respx.mock
    def test_post_follows_redirects_back_to_secondhand(self) -> None:
        """Verify POST follows redirect back to secondhand (ticket taken)."""
        # Mock POST returning redirect back to secondhand
        respx.post(BUY_URL).mock(
            return_value=httpx.Response(
                302,
                headers={"Location": SECONDHAND_URL},
            )
        )
        # Mock the redirect target
        respx.get(SECONDHAND_URL).mock(
            return_value=httpx.Response(200, text="No tickets")
        )

        session = SecondhandSession()
        response = session.post(BUY_URL, {"csrfmiddlewaretoken": CSRF_TOKEN})

        # Final URL should be secondhand (failure case)
        assert "secondhand" in str(response.url)

        session.close()


class TestCartAddFormData:
    """Test form data construction for cart add requests."""

    @respx.mock
    def test_form_data_sent_correctly(self) -> None:
        """Verify all form data is sent in POST body."""
        route = respx.post(BUY_URL).mock(
            return_value=httpx.Response(200)
        )

        session = SecondhandSession()
        form_data = {
            "csrfmiddlewaretoken": CSRF_TOKEN,
            "item_12345": "1",
        }
        session.post(BUY_URL, form_data)

        request = route.calls.last.request
        body = request.content.decode()
        assert f"csrfmiddlewaretoken={CSRF_TOKEN}" in body
        assert "item_12345=1" in body

        session.close()

    @respx.mock
    def test_content_type_is_form_urlencoded(self) -> None:
        """Verify Content-Type header is set correctly."""
        route = respx.post(BUY_URL).mock(
            return_value=httpx.Response(200)
        )

        session = SecondhandSession()
        session.post(BUY_URL, {"csrfmiddlewaretoken": CSRF_TOKEN})

        request = route.calls.last.request
        assert "application/x-www-form-urlencoded" in request.headers.get("content-type", "")

        session.close()


class TestCheckoutPageValidation:
    """Tests for checkout page content validation.

    These tests verify that the checkout page has expected markers,
    providing secondary validation beyond just URL-based detection.
    """

    @pytest.fixture
    def checkout_html(self) -> str:
        """Load the checkout success sample HTML."""
        return (SAMPLE_DIR / "sample_checkout_success_http200.html").read_text()

    def test_checkout_page_has_step_indicator(self, checkout_html: str) -> None:
        """Checkout page should show step progress (Step 1 of N)."""
        # Generic: any pretix checkout starts at Step 1
        assert "Step 1 of" in checkout_html

    def test_checkout_page_has_checkout_heading(self, checkout_html: str) -> None:
        """Checkout page should have Checkout heading."""
        assert "Checkout" in checkout_html

    def test_checkout_page_has_cart_panel(self, checkout_html: str) -> None:
        """Checkout page should show cart with items."""
        assert "Your cart" in checkout_html

    def test_checkout_page_shows_ticket_in_cart(self, checkout_html: str) -> None:
        """Checkout page cart should contain a ticket."""
        # Generic: just check for "Ticket", not specific sub-type
        assert "Ticket" in checkout_html

    def test_checkout_page_has_checkout_steps_nav(self, checkout_html: str) -> None:
        """Checkout page should have step navigation."""
        assert "checkout-flow" in checkout_html
        # These are standard pretix checkout steps
        assert "Your information" in checkout_html
        assert "Payment" in checkout_html

    def test_checkout_page_has_email_form(self, checkout_html: str) -> None:
        """Checkout page should have email input for contact info."""
        assert 'name="email"' in checkout_html

    def test_checkout_page_has_continue_button(self, checkout_html: str) -> None:
        """Checkout page should have continue button."""
        assert "Continue" in checkout_html

    def test_checkout_page_has_cart_reservation_timer(self, checkout_html: str) -> None:
        """Checkout page should show cart reservation countdown."""
        assert "reserved for you" in checkout_html
