```
                  __
    ___  _______ / /_(_)_ __      .------------------------.
   / _ \/ __/ -_) __/ /\ \ /     (  |                  (●) )
  / .__/_/  \__/\__/_//_\_\       '------------------------'
 /_/
 ██████   █████   ██████ ███████      ██████  ██████  ███   ██ ██████  ██ ████████ ██  ██████  ███   ██
 ██   ██ ██   ██ ██      ██          ██      ██    ██ ████  ██ ██   ██ ██    ██    ██ ██    ██ ████  ██
 ██████  ███████ ██      █████       ██      ██    ██ ██ ██ ██ ██   ██ ██    ██    ██ ██    ██ ██ ██ ██
 ██   ██ ██   ██ ██      ██          ██      ██    ██ ██  ████ ██   ██ ██    ██    ██ ██    ██ ██  ████
 ██   ██ ██   ██  ██████ ███████      ██████  ██████  ██   ███ ██████  ██    ██    ██  ██████  ██   ███
```

# pretix secondhand: race condition

Races a pretix-based secondhand ticket marketplace, automatically adds tickets to cart as soon as available, and hands off to your browser for checkout. Optionally sends iMessage alerts.

## Features

- Gentle polling with both session ID and HTTP/2 connection reuse
- Configurable interval with ±20% jitter for slightly random timing
- Automatic cart add with browser handoff via Playwright
- Graceful backoff on rate limits or errors
- Waits for inactive marketplaces to come back online (`--poll-inactive-marketplace`)
- Optional iMessage alerts (macOS only)

## Requirements

- macOS (pull requests for other platforms welcome)
- Python 3.11+
- [uv](https://github.com/astral-sh/uv) package manager

## Setup

```bash
uv sync
uv run playwright install chromium
```

## Usage

```bash
# Basic monitoring (15s default interval)
uv run pretix-race --url https://tickets.example.com --event myevent

# Faster polling with iMessage alerts
uv run pretix-race --url https://tickets.example.com --event myevent \
    --interval 5 --imessage "+441234567890"
```

Run `uv run pretix-race --help` for all options.

## Testing

```bash
# Run unit tests
uv run pytest

# Test browser handoff flow
uv run python -m pretix_race.test_handoff --simulate
```

## Notes

Interesting hints on scaling pretix instances, including its global lock [https://docs.pretix.eu/self-hosting/scaling/](https://docs.pretix.eu/self-hosting/scaling/). 

## License

MIT

