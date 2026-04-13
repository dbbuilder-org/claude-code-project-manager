"""Tests for pm.terminal module — detection, script generation, shutdown support."""

from unittest.mock import patch

from pm.terminal import (
    TerminalApp,
    detect_terminal,
    is_shutdown_supported,
    build_command,
    launch_single_iterm,
    launch_single_terminal,
    launch_batch_iterm,
    launch_batch_terminal,
)


# ── detect_terminal ────────────────────────────────────────────────────────


class TestDetectTerminal:
    def test_force_terminal_returns_terminal(self):
        """--terminal flag should always return Terminal.app."""
        result = detect_terminal(force_terminal=True)
        assert result == TerminalApp.TERMINAL

    @patch("pm.terminal.Path")
    def test_iterm_installed(self, mock_path_cls):
        """When /Applications/iTerm.app exists, return ITERM2."""
        instance = mock_path_cls.return_value
        instance.exists.return_value = True
        result = detect_terminal(force_terminal=False)
        assert result == TerminalApp.ITERM2

    @patch("pm.terminal.Path")
    def test_iterm_not_installed(self, mock_path_cls):
        """When /Applications/iTerm.app does not exist, return TERMINAL."""
        instance = mock_path_cls.return_value
        instance.exists.return_value = False
        result = detect_terminal(force_terminal=False)
        assert result == TerminalApp.TERMINAL


# ── is_shutdown_supported ──────────────────────────────────────────────────


class TestIsShutdownSupported:
    def test_iterm2_supported(self):
        assert is_shutdown_supported(TerminalApp.ITERM2) is True

    def test_terminal_not_supported(self):
        assert is_shutdown_supported(TerminalApp.TERMINAL) is False


# ── build_command ──────────────────────────────────────────────────────────


class TestBuildCommand:
    def test_default_args(self):
        cmd = build_command("/path/to/project")
        assert "cd '/path/to/project'" in cmd
        assert "transcript" in cmd
        assert "--dangerously-skip-permissions --continue" in cmd

    def test_custom_args(self):
        cmd = build_command("/path", claude_args="--resume")
        assert "cd '/path'" in cmd
        assert "--resume" in cmd
        assert "--dangerously-skip-permissions" not in cmd


# ── AppleScript generation ─────────────────────────────────────────────────


class TestITermSingleScript:
    def test_contains_iterm(self):
        script = launch_single_iterm("/proj", "myproj", "cd /proj && claude")
        assert "iTerm" in script

    def test_contains_pm_prefix(self):
        script = launch_single_iterm("/proj", "myproj", "cd /proj && claude")
        assert "PM: myproj" in script

    def test_contains_write_text(self):
        script = launch_single_iterm("/proj", "myproj", "cd /proj && claude")
        assert "write text" in script

    def test_preserves_focus(self):
        script = launch_single_iterm("/proj", "myproj", "cd /proj && claude")
        assert "frontApp" in script
        assert "activate" in script


class TestTerminalSingleScript:
    def test_contains_terminal(self):
        script = launch_single_terminal("/proj", "myproj", "cd /proj && claude")
        assert "Terminal" in script

    def test_contains_do_script(self):
        script = launch_single_terminal("/proj", "myproj", "cd /proj && claude")
        assert "do script" in script

    def test_no_pm_prefix(self):
        """Terminal.app doesn't support session naming."""
        script = launch_single_terminal("/proj", "myproj", "cd /proj && claude")
        assert "PM:" not in script


class TestITermBatchScript:
    def test_empty_returns_empty(self):
        assert launch_batch_iterm([]) == ""

    def test_contains_create_tab(self):
        projects = [
            ("/p1", "proj1", "cd /p1 && claude"),
            ("/p2", "proj2", "cd /p2 && claude"),
        ]
        script = launch_batch_iterm(projects)
        assert "create tab" in script

    def test_contains_multiple_pm_names(self):
        projects = [
            ("/p1", "proj1", "cd /p1 && claude"),
            ("/p2", "proj2", "cd /p2 && claude"),
        ]
        script = launch_batch_iterm(projects)
        assert "PM: proj1" in script
        assert "PM: proj2" in script

    def test_single_project_no_create_tab(self):
        """A single project doesn't need create tab (uses the initial session)."""
        projects = [("/p1", "proj1", "cd /p1 && claude")]
        script = launch_batch_iterm(projects)
        assert "create tab" not in script

    def test_contains_iterm(self):
        projects = [("/p1", "proj1", "cmd1"), ("/p2", "proj2", "cmd2")]
        script = launch_batch_iterm(projects)
        assert "iTerm" in script


class TestTerminalBatchScript:
    def test_empty_returns_empty(self):
        assert launch_batch_terminal([]) == ""

    def test_multiple_do_script(self):
        projects = [
            ("/p1", "proj1", "cd /p1 && claude"),
            ("/p2", "proj2", "cd /p2 && claude"),
        ]
        script = launch_batch_terminal(projects)
        assert script.count("do script") == 2

    def test_no_create_tab(self):
        """Terminal.app cannot create tabs programmatically."""
        projects = [
            ("/p1", "proj1", "cmd1"),
            ("/p2", "proj2", "cmd2"),
        ]
        script = launch_batch_terminal(projects)
        assert "create tab" not in script

    def test_contains_terminal(self):
        projects = [("/p1", "proj1", "cmd1")]
        script = launch_batch_terminal(projects)
        assert "Terminal" in script


# ── TerminalApp enum ───────────────────────────────────────────────────────


class TestTerminalAppEnum:
    def test_values(self):
        assert TerminalApp.ITERM2.value == "iterm2"
        assert TerminalApp.TERMINAL.value == "terminal"
