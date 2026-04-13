"""Tests for pm/__main__.py entry point."""

import subprocess
import sys


def test_pm_main_help():
    """python -m pm --help exits 0 and shows usage."""
    result = subprocess.run(
        [sys.executable, "-m", "pm", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "Usage:" in result.stdout
