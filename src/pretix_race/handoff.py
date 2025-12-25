"""Chrome session handoff utilities."""

import json
from pathlib import Path


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
