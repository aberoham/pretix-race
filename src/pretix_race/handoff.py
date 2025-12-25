"""Chrome session handoff utilities."""

import json
import subprocess
import tempfile
from pathlib import Path


def export_cookies_netscape(cookies: dict[str, str], filepath: Path, domain: str) -> None:
    """Export cookies in Netscape format.

    This format is compatible with many browser extensions and tools.
    """
    lines = [
        "# Netscape HTTP Cookie File",
        "# https://curl.se/docs/http-cookies.html",
        "",
    ]

    for name, value in cookies.items():
        # Format: domain, subdomain_flag, path, secure, expiry, name, value
        # Using TRUE for subdomain (include subdomains)
        # Using TRUE for secure (HTTPS only)
        # Using 0 for expiry (session cookie)
        line = f"{domain}\tTRUE\t/\tTRUE\t0\t{name}\t{value}"
        lines.append(line)

    filepath.write_text("\n".join(lines))


def export_cookies_json(cookies: dict[str, str], filepath: Path, domain: str) -> None:
    """Export cookies as JSON for programmatic use."""
    cookie_list = []

    for name, value in cookies.items():
        cookie_list.append(
            {
                "domain": domain,
                "name": name,
                "value": value,
                "path": "/",
                "secure": True,
                "httpOnly": True,
            }
        )

    filepath.write_text(json.dumps(cookie_list, indent=2))


def open_chrome_with_url(url: str) -> bool:
    """Open Chrome with the specified URL on macOS."""
    try:
        subprocess.run(
            ["open", "-a", "Google Chrome", url],
            check=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def open_chrome_with_cookies(url: str, cookies: dict[str, str]) -> bool:
    """Open Chrome with cookies injected via temporary profile.

    Note: This creates a temporary Chrome profile with the cookies.
    The user may need to copy cookies to their main profile.
    """
    # Create temporary directory for Chrome profile
    with tempfile.TemporaryDirectory(prefix="secondhand_chrome_") as tmpdir:
        profile_dir = Path(tmpdir)

        # Export cookies
        cookie_file = profile_dir / "cookies.txt"
        export_cookies_netscape(cookies, cookie_file)

        # Try to open Chrome
        # Note: Chrome doesn't directly support cookie files on launch
        # The user will need to import manually or use an extension
        return open_chrome_with_url(url)


def print_manual_instructions(cookies: dict[str, str], checkout_url: str) -> None:
    """Print instructions for manual cookie import."""
    print("\n" + "=" * 60)
    print("MANUAL BROWSER SETUP")
    print("=" * 60)
    print()
    print("Option 1: Use browser developer tools")
    print("-" * 40)
    print("1. Open Chrome and navigate to:")
    print(f"   {checkout_url}")
    print("2. Open DevTools (Cmd+Option+I)")
    print("3. Go to Application > Cookies")
    print("4. Add/modify these cookies:")
    print()
    for name, value in cookies.items():
        print(f"   {name}: {value}")
    print()
    print("Option 2: Use EditThisCookie extension")
    print("-" * 40)
    print("1. Install 'EditThisCookie' from Chrome Web Store")
    print("2. Navigate to the ticket site")
    print("3. Click the extension icon")
    print("4. Import cookies from the exported file")
    print()
    print("Option 3: Use curl to verify session")
    print("-" * 40)
    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
    print(f'curl -H "Cookie: {cookie_str}" "{checkout_url}"')
    print()
