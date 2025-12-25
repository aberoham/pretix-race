"""Test script to verify cookie handoff to Chrome works.

This simulates finding tickets and tests the full handoff flow:
1. Make a real request to establish session
2. Export cookies to file
3. Open Chrome with a verification URL
4. You can verify cookies are present in Chrome DevTools
"""

import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from .config import Config, DEFAULT_CONFIG
from .session import SecondhandSession
from .handoff import export_cookies_netscape, print_manual_instructions


def test_handoff(open_browser: bool = True) -> None:
    """Test the cookie handoff flow."""
    config = DEFAULT_CONFIG

    print("=" * 60)
    print("COOKIE HANDOFF TEST")
    print("=" * 60)
    print()

    # Step 1: Establish real session
    print("[1/4] Establishing session with live site...")
    session = SecondhandSession(config)

    try:
        response = session.get(config.secondhand_url)
        print(f"      Status: {response.status_code}")
        print(f"      Cookies received: {list(session.state.cookies.keys())}")

        if not session.state.cookies:
            print("      WARNING: No cookies received!")
            return

        # Step 2: Export cookies
        print()
        print("[2/4] Exporting cookies...")
        response_dir = Path("live-responses")
        response_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        cookie_file = response_dir / f"cookies_{timestamp}.txt"
        session.export_cookies_netscape(cookie_file)
        print(f"      Exported to: {cookie_file}")
        print()
        print("      Cookie file contents:")
        print("      " + "-" * 40)
        for line in cookie_file.read_text().split("\n"):
            if line and not line.startswith("#"):
                print(f"      {line}")
        print("      " + "-" * 40)

        # Step 3: Also export as JSON for easier inspection
        json_file = response_dir / f"cookies_{timestamp}.json"
        from .handoff import export_cookies_json
        export_cookies_json(session.state.cookies, json_file, config.domain)
        print(f"      Also exported JSON to: {json_file}")

        # Step 4: Open Chrome
        print()
        if open_browser:
            print("[3/4] Opening Chrome with test URL...")
            # Use the secondhand page itself as the test URL
            test_url = config.secondhand_url

            try:
                subprocess.run(
                    ["open", "-a", "Google Chrome", test_url],
                    check=True,
                )
                print(f"      Opened: {test_url}")
            except subprocess.CalledProcessError:
                print("      Failed to open Chrome")
        else:
            print("[3/4] Skipping browser open (--no-browser flag)")

        # Step 5: Verification instructions
        print()
        print("[4/4] Verification steps:")
        print("      " + "-" * 40)
        print("      1. In Chrome, open DevTools (Cmd+Option+I)")
        print("      2. Go to Application > Cookies")
        print(f"      3. Look for {config.domain}")
        print("      4. Verify __QXSESSION cookie matches:")
        print()
        for name, value in session.state.cookies.items():
            print(f"         {name}: {value}")
        print()
        print("      If cookies DON'T match, you need to import them.")
        print("      The cookies were exported to:")
        print(f"         {cookie_file}")
        print()

        # Print curl command for verification
        print("      To verify session works via curl:")
        cookie_str = "; ".join(f"{k}={v}" for k, v in session.state.cookies.items())
        print(f'      curl -H "Cookie: {cookie_str}" "{config.secondhand_url}" | grep -o "No tickets available"')
        print()

        print("=" * 60)
        print("TEST COMPLETE")
        print("=" * 60)

    finally:
        session.close()


def send_test_imessage(recipient: str) -> bool:
    """Send a test iMessage to verify the alert works."""
    print(f"Sending test iMessage to {recipient}...")

    script = f'''
    tell application "Messages"
        set targetService to 1st account whose service type = iMessage
        set targetBuddy to participant "{recipient}" of targetService
        send "🧪 TEST: Secondhand Monitor iMessage alert is working!" to targetBuddy
    end tell
    '''

    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            print("iMessage sent successfully!")
            return True
        else:
            print(f"iMessage failed: {result.stderr.strip()}")
            return False
    except subprocess.TimeoutExpired:
        print("iMessage timed out")
        return False
    except Exception as e:
        print(f"iMessage error: {e}")
        return False


def test_simulated_ticket_found(imessage_recipient: str | None = None) -> None:
    """Simulate what happens when a ticket is found.

    This tests the full flow including cookie injection via Playwright.
    """
    print("=" * 60)
    print("SIMULATED TICKET DETECTION TEST")
    print("=" * 60)
    print()

    config = DEFAULT_CONFIG
    session = SecondhandSession(config)
    num_steps = 6 if imessage_recipient else 5

    try:
        # Establish real session first
        print(f"[1/{num_steps}] Establishing real session...")
        response = session.get(config.secondhand_url)
        cookies = session.get_cookies_for_chrome()
        print(f"      Got session: {list(cookies.keys())}")
        for name, value in cookies.items():
            print(f"      {name}: {value}")

        # Simulate finding a ticket
        print()
        print(f"[2/{num_steps}] Simulating ticket detection...")
        print("      (In real scenario, parser would find ticket listings)")

        # Trigger macOS notification
        print()
        print(f"[3/{num_steps}] Triggering macOS notification...")
        try:
            script = 'display notification "Test: Simulated ticket found!" with title "Tickets Available!" sound name "Glass"'
            subprocess.run(["osascript", "-e", script], check=True)
            print("      Notification sent!")
        except Exception as e:
            print(f"      Notification failed: {e}")

        # iMessage alert (if recipient provided)
        step = 4
        if imessage_recipient:
            print()
            print(f"[{step}/{num_steps}] Sending iMessage alert...")
            send_test_imessage(imessage_recipient)
            step += 1

        # Export cookies (backup)
        print()
        print(f"[{step}/{num_steps}] Exporting session cookies (backup)...")
        response_dir = Path("live-responses")
        response_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        cookie_file = response_dir / f"cookies_{timestamp}.txt"
        session.export_cookies_netscape(cookie_file)
        print(f"      Exported to: {cookie_file}")
        step += 1

        # Open browser with Playwright
        print()
        print(f"[{step}/{num_steps}] Opening browser with Playwright...")
        test_url = config.secondhand_url

        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            # Launch visible browser
            browser = p.chromium.launch(headless=False)
            context = browser.new_context()

            # Inject cookies BEFORE navigating
            # NOTE: __Host- prefixed cookies MUST NOT have domain attribute!
            cookie_list = []
            for name, value in cookies.items():
                if name.startswith("__Host-"):
                    # __Host- cookies: use url (not domain), path is implicit
                    cookie_list.append({
                        "name": name,
                        "value": value,
                        "url": f"{config.base_url}/",
                        "secure": True,
                        "httpOnly": True,
                    })
                else:
                    # Regular cookies: use domain + path
                    cookie_list.append({
                        "name": name,
                        "value": value,
                        "domain": config.domain,
                        "path": "/",
                        "secure": True,
                        "httpOnly": True,
                    })
            context.add_cookies(cookie_list)
            print(f"      Injected {len(cookie_list)} cookies")

            # Navigate - cookies are already set
            page = context.new_page()
            page.goto(test_url)
            print(f"      Browser opened: {test_url}")

            # Verify cookies were set
            print()
            print("      " + "-" * 40)
            print("      VERIFICATION:")
            print("      Open DevTools (Cmd+Option+I) > Application > Cookies")
            print("      The __QXSESSION should match:")
            for name, value in cookies.items():
                print(f"         {name}: {value}")
            print("      " + "-" * 40)

            print()
            print("=" * 60)
            print("Browser is open. Press Enter to close...")
            print("=" * 60)
            input()

            browser.close()

        print()
        print("SIMULATION COMPLETE")

    finally:
        session.close()


def main() -> int:
    """Run handoff tests."""
    import argparse

    parser = argparse.ArgumentParser(description="Test cookie handoff to Chrome")
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Simulate full ticket detection flow with notification",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Don't open Chrome (just export cookies)",
    )
    parser.add_argument(
        "--imessage",
        type=str,
        metavar="RECIPIENT",
        help="Test iMessage alert to this phone/email",
    )

    args = parser.parse_args()

    if args.simulate:
        test_simulated_ticket_found(imessage_recipient=args.imessage)
    else:
        test_handoff(open_browser=not args.no_browser)

    return 0


if __name__ == "__main__":
    sys.exit(main())
