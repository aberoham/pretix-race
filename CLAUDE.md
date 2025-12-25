# Pretix Secondhand Race Condition

## Project Overview
Python script for monitoring pretix-based secondhand ticket marketplaces. Races to be first to detect available tickets, adds to cart, and hands off to browser via Playwright for checkout.

Should work with any pretix instance that has the secondhand resale module enabled.

## Critical Implementation Details

### Cookie Handling
- **Session cookie**: `__QXSESSION` - regular cookie, can be set via JS
- **`__Host-` prefixed cookies**: `__Host-pretix_csrftoken`, `__Host-pretix_session`
  - CANNOT be set via JavaScript (browser security)
  - CANNOT have `domain` attribute in Playwright - use `url` instead
  - Must be injected via Playwright before navigation

### Playwright Cookie Injection (CRITICAL)
```python
# CORRECT - for __Host- cookies, use url NOT domain
if name.startswith("__Host-"):
    cookie_list.append({
        "name": name,
        "value": value,
        "url": "https://tickets.example.com/",  # NOT domain!
        "secure": True,
        "httpOnly": True,
    })
else:
    cookie_list.append({
        "name": name,
        "value": value,
        "domain": "tickets.example.com",
        "path": "/",
        "secure": True,
        "httpOnly": True,
    })
```

### Cart Add Flow
1. Parse HTML for form with `method="post"` and "Buy" button
2. Extract unique `form_action` URL (e.g., `/{event}/secondhand/buy/{listing_id}/`)
3. Extract `csrfmiddlewaretoken` from hidden input
4. POST to form_action with cookies + CSRF token
5. If successful, server redirects to `/checkout/` - follow this URL
6. If redirects back to `/secondhand/` - cart add FAILED (ticket taken)

### HTML Parsing (Fast Path)
The parser uses regex for speed with BeautifulSoup fallback:
- `TICKET_PANEL_PATTERN` - anchored on `panel panel-default` class to skip info panels
- Extracts: ticket_type, price, form_action, csrf_token
- Falls back to BeautifulSoup if HTML structure changes

### Speed Optimizations
- Cart add happens FIRST, notifications LATER
- HTTP/2 enabled for multiplexing
- Connection keepalive: 60s (longer than poll interval)
- Timeout: 5s connect, 10s total

### Debugging
- Unusual HTML responses saved to `live-responses/`
- Cart add requests/responses saved to `live-responses/cart_add_*.txt`
- Cookies saved to timestamped files: `live-responses/cookies_YYYYMMDD_HHMMSS.txt`

## File Structure
```
src/pretix_race/
├── __main__.py      # CLI entry point
├── config.py        # Configuration dataclass
├── session.py       # HTTP session with cookie persistence
├── parser.py        # HTML parsing for ticket listings
├── monitor.py       # Main monitoring loop
├── test_handoff.py  # Test cookie handoff to browser
└── browser_handoff.py  # Playwright/AppleScript handoff utilities
```

## Key Commands
```bash
# Run monitor (configure URL in config or via args)
uv run pretix-race --url https://tickets.events.example.com --event 99x1 --interval 5 --imessage "+441234567890"

# Test handoff with iMessage
uv run python -m pretix_race.test_handoff --simulate --imessage "+441234567890"
```

## Testing
```bash
# Run all tests
uv run pytest

# Run with verbose output
uv run pytest -v

# Run specific test file
uv run pytest tests/test_cart_add.py

# Run specific test
uv run pytest -k "test_cookies_sent_in_header"
```

### Test Files
- `tests/test_parser.py` - HTML parsing tests, fast path regex validation
- `tests/test_monitor.py` - Monitor tests using sample files from `sample-responses/`
- `tests/test_cart_add.py` - Cart add, POST behavior, checkout page validation

### Mocking HTTP
Uses `respx` for mocking `httpx` requests:
```python
import respx
import httpx

@respx.mock
def test_example() -> None:
    respx.post("https://example.com/api").mock(
        return_value=httpx.Response(200, text="OK")
    )
    # ... test code
```

## Known Issues & Fixes
1. **Playwright error "Cookie should have either url or path"**: Don't mix `url` and `path` for `__Host-` cookies
2. **Cart shows empty after "success"**: Check redirect URL - if it goes back to `/secondhand/` instead of `/checkout/`, the add failed

## Rate Limiting
- Server returns 429 for rate limiting
- Server returns 409 with `Retry-After` header for lock timeout
- Exponential backoff implemented: 30s, 60s, 120s, 240s, max 300s
- Jitter: ±20% of poll interval for human-like timing and to avoid thundering herds

## Pretix Secondhand Page Structure
Key HTML elements the parser looks for:
- `<div class="panel panel-default">` - ticket listing container
- `<h3 class="panel-title">` - ticket type (e.g., "Ticket – Standard")
- `<h2 class="text-primary">` - price
- `<form method="post" action="...secondhand/buy/...">` - buy form
- `<input name="csrfmiddlewaretoken">` - CSRF token

Checkout success indicators:
- URL contains `/checkout/`
- Page title contains "Step 1 of"
- "Your cart" panel visible with ticket
