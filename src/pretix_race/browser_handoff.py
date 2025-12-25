"""Browser handoff using Playwright for proper cookie injection.

This solves the problem of transferring session cookies from
the Python requests session into a real Chrome browser.
"""

import subprocess


def handoff_with_playwright(
    cookies: dict[str, str],
    url: str,
    base_url: str,
    domain: str,
    keep_open: bool = True,
) -> bool:
    """Hand off session to Chrome via Playwright.

    This properly injects cookies before navigating, ensuring
    the browser has the same session as the Python monitor.

    Args:
        cookies: Dict of cookie name -> value
        url: URL to navigate to after injecting cookies
        base_url: Base URL of the site (e.g., https://tickets.example.com)
        domain: Domain for cookies (e.g., tickets.example.com)
        keep_open: If True, keeps browser open for user interaction

    Returns:
        True if successful
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright not installed. Run: uv add playwright && uv run playwright install chromium")
        return False

    with sync_playwright() as p:
        # Launch Chrome (not Chromium) if available, otherwise use Chromium
        try:
            browser = p.chromium.launch(
                channel="chrome",  # Use installed Chrome
                headless=False,    # Visible browser
            )
        except Exception:
            print("Chrome not found, using Chromium...")
            browser = p.chromium.launch(headless=False)

        context = browser.new_context()

        # Inject cookies BEFORE navigating
        # NOTE: __Host- prefixed cookies cannot have domain attribute
        cookie_list = []
        for name, value in cookies.items():
            if name.startswith("__Host-"):
                # __Host- cookies: use url (not domain), path is implicit
                cookie_list.append({
                    "name": name,
                    "value": value,
                    "url": f"{base_url}/",
                    "secure": True,
                    "httpOnly": True,
                })
            else:
                # Regular cookies: use domain + path
                cookie_list.append({
                    "name": name,
                    "value": value,
                    "domain": domain,
                    "path": "/",
                    "secure": True,
                    "httpOnly": True,
                })

        context.add_cookies(cookie_list)  # type: ignore[arg-type]
        print(f"Injected {len(cookie_list)} cookies")

        # Now navigate - the cookies will be sent with the request
        page = context.new_page()
        page.goto(url)
        print(f"Navigated to: {url}")

        if keep_open:
            print("\nBrowser is open. Press Enter to close...")
            input()

        browser.close()
        return True


def handoff_with_applescript(
    cookies: dict[str, str],
    url: str,
) -> bool:
    """Hand off session to Chrome via AppleScript (macOS only).

    This opens Chrome, navigates to the URL, then injects cookies
    via JavaScript in the console.

    Args:
        cookies: Dict of cookie name -> value
        url: URL to navigate to

    Returns:
        True if successful
    """
    # Build JavaScript to set cookies
    js_commands = []
    for name, value in cookies.items():
        js_commands.append(f'document.cookie = "{name}={value}; path=/; secure; SameSite=Lax";')

    js_code = " ".join(js_commands)

    # AppleScript to:
    # 1. Open Chrome with URL
    # 2. Wait for page load
    # 3. Execute JavaScript to set cookies
    # 4. Reload to apply cookies
    applescript = f'''
    tell application "Google Chrome"
        activate
        if (count windows) = 0 then
            make new window
        end if
        set URL of active tab of front window to "{url}"
        delay 2
        execute active tab of front window javascript "{js_code}"
        delay 0.5
        execute active tab of front window javascript "location.reload();"
    end tell
    '''

    try:
        subprocess.run(["osascript", "-e", applescript], check=True)
        print("Cookies injected via AppleScript")
        return True
    except subprocess.CalledProcessError as e:
        print(f"AppleScript failed: {e}")
        return False


def print_manual_cookie_instructions(cookies: dict[str, str], url: str) -> None:
    """Print instructions for manual cookie injection.

    Uses the cookieStore API which can set __Host- prefixed cookies
    (unlike document.cookie which cannot).
    """
    print("\n" + "=" * 60)
    print("MANUAL COOKIE INJECTION")
    print("=" * 60)
    print(f"\n1. Open Chrome and go to: {url}")
    print("\n2. Open DevTools: Cmd+Option+I (Mac) or F12 (Windows)")
    print("\n3. Go to Console tab and paste this single command:")
    print()

    # Build a single async IIFE that sets all cookies
    # cookieStore API can set __Host- cookies (document.cookie cannot)
    cookie_sets = []
    for name, value in cookies.items():
        cookie_sets.append(
            f'  await cookieStore.set({{name: "{name}", value: "{value}", '
            f'path: "/", secure: true, sameSite: "lax"}})'
        )
    script = "(async () => {\n" + ";\n".join(cookie_sets) + ";\n  location.reload();\n})()"
    print(script)

    print("\n(This uses cookieStore API which works with __Host- cookies)")
    print("\n" + "=" * 60)


# Quick test
if __name__ == "__main__":
    test_base_url = "https://tickets.example.com"
    test_domain = "tickets.example.com"
    test_cookies = {"__QXSESSION": "test123"}
    test_url = f"{test_base_url}/event/secondhand/"

    print("Testing cookie handoff methods...\n")

    print("Option 1: Manual (always works)")
    print_manual_cookie_instructions(test_cookies, test_url)

    print("\nOption 2: AppleScript (macOS)")
    response = input("Try AppleScript injection? [y/N] ")
    if response.lower() == "y":
        handoff_with_applescript(test_cookies, test_url)

    print("\nOption 3: Playwright (requires installation)")
    response = input("Try Playwright? [y/N] ")
    if response.lower() == "y":
        handoff_with_playwright(test_cookies, test_url, test_base_url, test_domain)
