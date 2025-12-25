"""Smoke tests for CLI entry points.

Verifies that scripts start up without crashing and properly validate arguments.
"""

import subprocess
import sys


class TestCLISmoke:
    """Verify CLI scripts don't crash on startup and require correct args."""

    def test_main_module_requires_url_and_event(self) -> None:
        """Main module should require --url and --event arguments."""
        result = subprocess.run(
            [sys.executable, "-m", "pretix_race"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2  # argparse exit code for missing required args
        assert "--url" in result.stderr
        assert "--event" in result.stderr
        assert "required" in result.stderr

    def test_main_module_help_works(self) -> None:
        """Main module --help should work."""
        result = subprocess.run(
            [sys.executable, "-m", "pretix_race", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "usage:" in result.stdout.lower()
        assert "--url" in result.stdout
        assert "--event" in result.stdout

    def test_test_handoff_requires_url_and_event(self) -> None:
        """test_handoff module should require --url and --event arguments."""
        result = subprocess.run(
            [sys.executable, "-m", "pretix_race.test_handoff"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2
        assert "--url" in result.stderr
        assert "--event" in result.stderr
        assert "required" in result.stderr

    def test_test_handoff_help_works(self) -> None:
        """test_handoff module --help should work."""
        result = subprocess.run(
            [sys.executable, "-m", "pretix_race.test_handoff", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "usage:" in result.stdout.lower()
        assert "--url" in result.stdout
        assert "--event" in result.stdout
        assert "--simulate" in result.stdout

    def test_browser_handoff_importable(self) -> None:
        """browser_handoff module should import without side effects.

        This module is interactive so we can't run it, but we can verify
        it imports cleanly.
        """
        result = subprocess.run(
            [sys.executable, "-c", "from pretix_race import browser_handoff"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert result.stderr == ""


class TestCLIImportable:
    """Verify all modules can be imported without side effects."""

    def test_config_importable(self) -> None:
        """Config module should import cleanly."""
        from pretix_race import config

        assert hasattr(config, "Config")
        assert hasattr(config, "DEFAULT_CONFIG")

    def test_parser_importable(self) -> None:
        """Parser module should import cleanly."""
        from pretix_race import parser

        assert hasattr(parser, "parse_secondhand_page")

    def test_session_importable(self) -> None:
        """Session module should import cleanly."""
        from pretix_race import session

        assert hasattr(session, "SecondhandSession")

    def test_monitor_importable(self) -> None:
        """Monitor module should import cleanly."""
        from pretix_race import monitor

        assert hasattr(monitor, "SecondhandMonitor")

    def test_handoff_importable(self) -> None:
        """Handoff module should import cleanly."""
        from pretix_race import handoff

        assert hasattr(handoff, "export_cookies_json")

    def test_browser_handoff_importable(self) -> None:
        """Browser handoff module should import cleanly."""
        from pretix_race import browser_handoff

        assert hasattr(browser_handoff, "handoff_with_playwright")
