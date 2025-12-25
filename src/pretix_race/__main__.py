"""CLI entry point for Pretix Secondhand Race Condition."""

import argparse
import sys

from .config import Config
from .monitor import SecondhandMonitor


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Monitor pretix secondhand ticket marketplace",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic monitoring
  pretix-race --url https://tickets.example.com --event myevent

  # Monitor with faster polling
  pretix-race --url https://tickets.example.com --event myevent --interval 10

  # Filter by item ID and sort by newest
  pretix-race --url https://tickets.example.com --event myevent --item 965 --sort newest

  # Send iMessage when tickets found
  pretix-race --url https://tickets.example.com --event myevent --imessage +1234567890
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
        "--imessage",
        type=str,
        metavar="RECIPIENT",
        help="Send iMessage alert to this phone/email when tickets found",
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
        imessage_recipient=args.imessage,
    )

    print("=" * 60)
    print("Pretix Secondhand Race Condition")
    print("=" * 60)
    print()
    print("Configuration:")
    print(f"  Target: {config.secondhand_url}")
    print(f"  Poll interval: {config.poll_interval_seconds}s")
    print(f"  Item filter: {config.item_filter or 'All tickets'}")
    print(f"  Sort order: {config.sort_order}")
    if config.imessage_recipient:
        print(f"  iMessage alerts: {config.imessage_recipient}")
    print()
    print("IMPORTANT: Be respectful of the site.")
    print("Many marketplaces warn: 'Please don't ruin a good thing.'")
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
