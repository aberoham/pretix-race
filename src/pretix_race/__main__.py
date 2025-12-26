"""CLI entry point for pretix secondhand: race condition."""

import argparse
import sys

from .config import Config
from .monitor import SecondhandMonitor


def check_playwright_ready() -> tuple[bool, str]:
    """Check if Playwright is installed and has browsers available.

    Returns:
        Tuple of (is_ready, message)
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False, "Playwright package not installed. Run: uv add playwright"

    # Check if browser executable exists
    try:
        with sync_playwright() as p:
            # Get the executable path - this doesn't launch the browser
            executable = p.chromium.executable_path
            if not executable:
                return False, "Chromium not installed. Run: uv run playwright install chromium"
            # Check if the file actually exists
            from pathlib import Path

            if not Path(executable).exists():
                return False, f"Chromium executable not found at {executable}. Run: uv run playwright install chromium"
    except Exception as e:
        error_msg = str(e)
        if "Executable doesn't exist" in error_msg or "not found" in error_msg.lower():
            return False, "Chromium not installed. Run: uv run playwright install chromium"
        return False, f"Playwright error: {e}"

    return True, "Playwright ready"


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Monitor pretix secondhand ticket marketplace",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic monitoring (interactive mode, opens browser)
  pretix-race --url https://tickets.example.com --event myevent

  # Monitor with faster polling
  pretix-race --url https://tickets.example.com --event myevent --interval 10

  # Filter by item ID and sort by newest
  pretix-race --url https://tickets.example.com --event myevent --item 965 --sort newest

  # Send iMessage when tickets found (macOS only)
  pretix-race --url https://tickets.example.com --event myevent --imessage +1234567890

  # Headless mode for Linux servers (no display needed)
  pretix-race --url https://tickets.example.com --event myevent --headless

  # Headless with webhook notification
  pretix-race --url https://tickets.example.com --event myevent --headless --webhook https://your-server.com/notify
""",
    )

    parser.add_argument(
        "--url",
        type=str,
        required=True,
        metavar="BASE_URL",
        help="Base URL of the pretix site (e.g., https://tickets.example.com)",
    )
    parser.add_argument(
        "--event",
        type=str,
        required=True,
        metavar="SLUG",
        help="Event slug (e.g., myevent)",
    )

    parser.add_argument(
        "--interval",
        type=float,
        default=15.0,
        help="Polling interval in seconds (default: 15)",
    )
    parser.add_argument(
        "--item",
        type=str,
        default="",
        metavar="ID",
        help="Filter by item ID (find IDs in page source), empty=all (default: all)",
    )
    parser.add_argument(
        "--sort",
        choices=["price_asc", "price_desc", "newest", "oldest"],
        default="price_asc",
        help="Sort order (default: price_asc)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't add to cart, just notify",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run in headless mode (no display, for servers)",
    )
    parser.add_argument(
        "--imessage",
        type=str,
        metavar="RECIPIENT",
        help="Send iMessage alert to this phone/email when tickets found (macOS only)",
    )
    parser.add_argument(
        "--webhook",
        type=str,
        metavar="URL",
        help="POST JSON notification to this URL when tickets found",
    )
    parser.add_argument(
        "--poll-inactive-marketplace",
        type=int,
        metavar="SECONDS",
        default=None,
        help="If marketplace is inactive, poll every N seconds until it comes back (default: exit)",
    )

    args = parser.parse_args()

    # Validate interval
    if args.interval < 1:
        print("Warning: Polling interval below 5s may be considered aggressive.")
        print("The site warns against 'irresponsible scraping and botting'.")
        response = input("Continue anyway? [y/N] ")
        if response.lower() != "y":
            return 1

    config = Config(
        base_url=args.url.rstrip("/"),
        event_slug=args.event.strip("/"),
        poll_interval_seconds=args.interval,
        item_filter=args.item,
        sort_order=args.sort,
        headless=args.headless,
        imessage_recipient=args.imessage,
        webhook_url=args.webhook,
        poll_inactive_interval=args.poll_inactive_marketplace,
    )

    print("=" * 60)
    print("pretix secondhand: race condition")
    print("=" * 60)
    print()
    print("Configuration:")
    print(f"  Target: {config.secondhand_url}")
    print(f"  Poll interval: {config.poll_interval_seconds}s")
    print(f"  Item filter: {config.item_filter or 'All tickets'}")
    print(f"  Sort order: {config.sort_order}")
    print(f"  Mode: {'headless (server)' if config.headless else 'interactive (desktop)'}")
    if config.imessage_recipient:
        print(f"  iMessage alerts: {config.imessage_recipient}")
    if config.webhook_url:
        print(f"  Webhook: {config.webhook_url}")
    if config.poll_inactive_interval:
        print(f"  Inactive marketplace: poll every {config.poll_inactive_interval}s")
    print()
    print("IMPORTANT: Be respectful of the site.")
    print("Many marketplaces warn: 'Please don't ruin a good thing.'")
    print()

    # Check Playwright is ready for browser handoff
    playwright_ready, playwright_msg = check_playwright_ready()
    if playwright_ready:
        print(f"Browser handoff: {playwright_msg}")
    else:
        print(f"WARNING: {playwright_msg}")
        print("         Browser handoff will fall back to manual cookie injection.")
        print()
    print()

    monitor = SecondhandMonitor(config)

    try:
        monitor.run()
    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        monitor.session.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
