"""Tests that run linting and type checking."""

import subprocess


def test_ruff_lint() -> None:
    """Ensure code passes ruff linting."""
    result = subprocess.run(
        ["uv", "run", "ruff", "check", "src/pretix_race/"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"ruff check failed:\n{result.stdout}\n{result.stderr}"


def test_mypy_typecheck() -> None:
    """Ensure code passes mypy type checking."""
    result = subprocess.run(
        ["uv", "run", "mypy", "src/pretix_race/"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"mypy failed:\n{result.stdout}\n{result.stderr}"
