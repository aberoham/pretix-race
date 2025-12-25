"""Tests for headless mode and cross-platform support."""

import subprocess
import sys

import pytest


class TestHeadlessConfig:
    """Test headless mode configuration."""

    def test_config_headless_default_false(self) -> None:
        """Config.headless should default to False."""
        from pretix_race.config import Config

        config = Config()
        assert config.headless is False

    def test_config_headless_can_be_set(self) -> None:
        """Config.headless can be set to True."""
        from pretix_race.config import Config

        config = Config(headless=True)
        assert config.headless is True

    def test_config_webhook_url_default_none(self) -> None:
        """Config.webhook_url should default to None."""
        from pretix_race.config import Config

        config = Config()
        assert config.webhook_url is None

    def test_config_webhook_url_can_be_set(self) -> None:
        """Config.webhook_url can be set."""
        from pretix_race.config import Config

        config = Config(webhook_url="https://example.com/notify")
        assert config.webhook_url == "https://example.com/notify"


class TestPlatformDetection:
    """Test platform-specific defaults."""

    def test_user_agent_matches_platform(self) -> None:
        """User agent should match the current platform."""
        import platform as stdlib_platform

        from pretix_race.config import _default_user_agent

        ua = _default_user_agent()
        system = stdlib_platform.system()

        if system == "Darwin":
            assert "Macintosh" in ua
        elif system == "Linux":
            assert "Linux" in ua
        elif system == "Windows":
            assert "Windows" in ua

    def test_sec_ch_ua_platform_matches_system(self) -> None:
        """Sec-CH-UA-Platform should match the system."""
        import platform as stdlib_platform

        from pretix_race.config import _default_sec_ch_ua_platform

        sec_platform = _default_sec_ch_ua_platform()
        system = stdlib_platform.system()

        if system == "Darwin":
            assert "macOS" in sec_platform
        elif system == "Linux":
            assert "Linux" in sec_platform
        elif system == "Windows":
            assert "Windows" in sec_platform


class TestHeadlessCLI:
    """Test CLI headless mode flags."""

    def test_cli_accepts_headless_flag(self) -> None:
        """CLI should accept --headless flag."""
        result = subprocess.run(
            [sys.executable, "-m", "pretix_race", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "--headless" in result.stdout

    def test_cli_accepts_webhook_flag(self) -> None:
        """CLI should accept --webhook flag."""
        result = subprocess.run(
            [sys.executable, "-m", "pretix_race", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "--webhook" in result.stdout


class TestWebhook:
    """Test webhook functionality."""

    def test_webhook_not_sent_when_url_none(self) -> None:
        """Webhook should not be sent when webhook_url is None."""
        from pretix_race.config import Config
        from pretix_race.monitor import SecondhandMonitor

        config = Config(
            base_url="https://example.com",
            event_slug="test",
            webhook_url=None,
        )
        monitor = SecondhandMonitor(config)

        # Should return False immediately when no webhook configured
        result = monitor._send_webhook(event="test")
        assert result is False
