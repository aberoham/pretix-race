# pretix secondhand: race condition

## Project Overview
Python bot for monitoring pretix-based secondhand ticket marketplaces. Races to be first to detect available tickets, adds to cart, and hands off to browser via Playwright for checkout.

Should work with any pretix ticketing instance that has the secondhand resale module enabled.

### Modes of Operation
- **Interactive mode** (default): Opens a browser window for manual checkout completion
- **Headless mode** (`--headless`): No browser, outputs cookies/checkout URL for remote completion. Use this on Linux servers close to the target for minimal latency.

### Marketplace Discovery Flow
The monitor navigates naturally rather than hitting the marketplace URL directly:

1. **Visit main event page** (`/{event}/`) - establishes session like a real user
2. **Find "Marketplace" link** - parses HTML for links containing `secondhand/`
3. **Follow link to marketplace** - only proceeds if link is found
4. **Begin ticket polling** - monitors the discovered marketplace URL

If marketplace link is not found:
- With `--poll-inactive-marketplace N`: Polls event page every N seconds waiting for link to appear
- Without flag: Exits with message suggesting the flag

This approach avoids looking suspicious by going directly to deep marketplace URLs.

## Reference Source Code

The `reference/` directory contains upstream source code as git submodules:

- **`reference/pretix-swap`** - The [pretix-swap](https://github.com/rixx/pretix-swap) plugin by rixx. **Note:** This is NOT the secondhand marketplace plugin - it handles peer-to-peer ticket swapping (exchanging event dates) and cancelation requests between existing ticket holders. Kept as reference for understanding pretix plugin architecture and Django patterns.

- **`reference/pretix`** - The upstream [pretix](https://github.com/pretix/pretix) ticketing system. Useful for understanding core session handling, CSRF, checkout flow, and cart mechanics.

**Important:** The actual secondhand ticket marketplace (`/{event}/secondhand/` pages) appears to be a **bespoke/custom plugin** not available in open source. It allows ticket holders to list tickets for resale; buyers purchase directly and sellers are paid after the sale completes. The source code is not publicly available, so we infer behavior from HTML structure and HTTP responses.

To initialize submodules after cloning:
```bash
git submodule update --init --recursive
```

## Critical Implementation Details

### Cookie Handling
- **Session cookie**: `__QXSESSION` - regular cookie, can be set via JS
- **`__Host-` prefixed cookies**: `__Host-pretix_csrftoken`, `__Host-pretix_session`
  - CANNOT be set via `document.cookie` (browser security restriction)
  - CAN be set via `cookieStore.set()` API (modern browsers)
  - CANNOT have `domain` attribute in Playwright - use `url` instead
  - Playwright injects cookies at browser context level (before navigation)

### Playwright Setup
- **Browser preference**: Tries system Chrome first (`channel="chrome"`), falls back to bundled Chromium
- **Why**: Bundled Chromium can crash on macOS ARM (BUS_ADRALN signal)
- **Startup check**: Warns if Playwright/browsers not installed, falls back to manual cookie injection
- **Install**: `uv run playwright install chromium`

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

### Manual Cookie Fallback (Chrome Console)
If Playwright fails, paste this in Chrome DevTools Console:
```javascript
(async () => {
  await cookieStore.set({name: "__QXSESSION", value: "VALUE", path: "/", secure: true, sameSite: "lax"});
  await cookieStore.set({name: "__Host-pretix_csrftoken", value: "VALUE", path: "/", secure: true, sameSite: "lax"});
  await cookieStore.set({name: "__Host-pretix_session", value: "VALUE", path: "/", secure: true, sameSite: "lax"});
  location.reload();
})()
```
The script logs this fallback command with actual cookie values on every handoff attempt.

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
- Fallback `cookieStore.set()` script always logged (even on Playwright success)
- "Ticket unavailable" in page title = ticket already taken (race lost, not a bug)

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

reference/               # Git submodules (run: git submodule update --init)
├── pretix-swap/         # Peer-to-peer swap plugin (NOT the secondhand marketplace)
└── pretix/              # Upstream pretix ticketing system
```

## Key Commands
```bash
# Interactive mode (opens browser for checkout)
uv run pretix-race --url https://tickets.events.example.com --event EVENT_SLUG --interval 10 --imessage "+441234567890"

# Headless mode (for Linux servers, no browser)
uv run pretix-race --url https://tickets.events.example.com --event EVENT_SLUG --interval 10 --headless --webhook https://your-server.com/notify

# Test handoff with iMessage
uv run python -m pretix_race.test_handoff --simulate --imessage "+441234567890"
```

### Docker (Headless Server)
```bash
# Build
docker build -t pretix-race .

# Run headless on a Linux server
docker run --rm pretix-race \
  --url https://tickets.events.example.com \
  --event 99x1 \
  --webhook https://your-server.com/notify
```

### Webhook Payload
When tickets are found, webhook POSTs JSON:
```json
{
  "timestamp": "2038-01-19T03:14:07.999999",
  "target": "https://tickets.example.com/event/secondhand/",
  "event": "ticket_in_cart",
  "ticket": "Ticket – Type A",
  "price": "90.00 EUR",
  "checkout_url": "https://tickets.example.com/event/checkout/start",
  "cookies": {
    "__QXSESSION": "...",
    "__Host-pretix_csrftoken": "...",
    "__Host-pretix_session": "..."
  },
  "cookie_script": "(async () => { await cookieStore.set(...); location.reload(); })()"
}
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
- `tests/test_headless.py` - Headless mode, webhook, and platform detection tests

### Test Data: sample-responses/ vs live-responses/
**IMPORTANT**: Tests must ONLY use files from `sample-responses/`, never `live-responses/`.

- `sample-responses/` - Committed to repo, always available, scrubbed of identifying info
- `live-responses/` - Gitignored, created at runtime, will be EMPTY on fresh checkout

If you need to add a new test case based on a live response:
1. Copy the relevant file from `live-responses/` to `sample-responses/`
2. Scrub any identifying information (event names, URLs, dates, etc.)
3. Give it a descriptive name like `sample_<scenario>.html`
4. Reference it in tests via `SAMPLE_DIR / "sample_<scenario>.html"`

Never use `pytest.skip()` as a workaround for missing live data - this masks test gaps.

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
3. **Chromium crash (BUS_ADRALN)**: Bundled Playwright Chromium can crash on macOS ARM. Script now tries system Chrome first.

## Rate Limiting
- Server returns 429 for rate limiting
- Server returns 409 with `Retry-After` header for lock timeout
- Exponential backoff implemented: 30s, 60s, 120s, 240s, max 300s
- Jitter: ±20% of poll interval for human-like timing and to avoid thundering herds

## Race Condition Reality
This script is optimized for speed but cannot overcome physics:
- **Polling gap**: With a 15s interval, tickets can appear up to 14.99s before detection
- **Network latency**: Varies by location relative to the pretix server
- **Server-side race**: If someone else's request arrives at the server first, they win
- **"Ticket unavailable"**: This response means a genuine race loss, not a bug
- **Lower intervals help**: But be respectful - most sites warn against aggressive scraping

## Pretix secondhand Page Structure
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
