"""Terminal detection and AppleScript generation for iTerm2 and Terminal.app.

Provides a shared module so that CLI, dashboard, and shell scripts all use
the same detection logic and AppleScript templates.
"""

import enum
import subprocess
from pathlib import Path


class TerminalApp(enum.Enum):
    """Supported terminal applications."""
    ITERM2 = "iterm2"
    TERMINAL = "terminal"


def detect_terminal(force_terminal: bool = False) -> TerminalApp:
    """Detect which terminal to use.

    Args:
        force_terminal: If True, always return Terminal.app regardless of
            iTerm2 availability.

    Returns:
        TerminalApp.ITERM2 if iTerm2 is installed (and not forced),
        TerminalApp.TERMINAL otherwise.
    """
    if force_terminal:
        return TerminalApp.TERMINAL
    if Path("/Applications/iTerm.app").exists():
        return TerminalApp.ITERM2
    return TerminalApp.TERMINAL


def ensure_running(terminal: TerminalApp) -> None:
    """Ensure the chosen terminal application is running.

    For iTerm2: checks if the process is running and opens it if not.
    For Terminal.app: no-op (macOS always has it available).
    """
    if terminal == TerminalApp.ITERM2:
        try:
            result = subprocess.run(
                ["osascript", "-e",
                 'tell application "System Events" to (name of processes) contains "iTerm2"'],
                capture_output=True, text=True
            )
            if "true" not in result.stdout.lower():
                subprocess.run(["open", "-a", "iTerm"], check=False)
                import time
                time.sleep(2)
        except Exception:
            pass


def _escape_applescript(text: str) -> str:
    """Escape and sanitize a string for use in AppleScript string literals.

    Strips control characters that could break out of the string context
    (newlines, carriage returns, null bytes) before escaping backslashes
    and double-quotes.
    """
    # Strip characters that allow AppleScript injection via string termination
    text = text.replace("\x00", "").replace("\r", "").replace("\n", " ")
    return text.replace("\\", "\\\\").replace('"', '\\"')


# ── iTerm2 AppleScript generators ──────────────────────────────────────────


def launch_single_iterm(path: str, name: str, command: str) -> str:
    """Generate AppleScript to launch a single session in a PM window in iTerm2.

    Finds an existing PM window (by "PM:" prefix) and adds a tab, or creates
    a new window if none exists.
    """
    session_name = _escape_applescript(f"PM: {name}")
    cmd_text = _escape_applescript(command)

    return f'''tell application "System Events"
    set frontApp to name of first application process whose frontmost is true
end tell
tell application "iTerm"
    set pmWindow to missing value
    repeat with w in windows
        repeat with t in tabs of w
            repeat with s in sessions of t
                if name of s starts with "PM:" then
                    set pmWindow to w
                    exit repeat
                end if
            end repeat
            if pmWindow is not missing value then exit repeat
        end repeat
        if pmWindow is not missing value then exit repeat
    end repeat
    if pmWindow is missing value then
        create window with default profile
        set pmWindow to current window
        tell current session of pmWindow
            set name to "{session_name}"
            write text "{cmd_text}"
        end tell
    else
        tell pmWindow
            create tab with default profile
            tell current session
                set name to "{session_name}"
                write text "{cmd_text}"
            end tell
        end tell
    end if
end tell
tell application frontApp to activate'''


def launch_batch_iterm(projects: list[tuple[str, str, str]]) -> str:
    """Generate AppleScript to launch multiple projects as tabs in one iTerm2 window.

    Args:
        projects: List of (path, name, command) tuples.

    Returns:
        AppleScript string that creates a window and adds a tab per project.
    """
    if not projects:
        return ""

    parts = [
        'tell application "System Events"',
        '    set frontApp to name of first application process whose frontmost is true',
        'end tell',
        'tell application "iTerm"',
        '    create window with default profile',
        '    set pmWin to current window',
    ]

    for i, (path, name, command) in enumerate(projects):
        session_name = _escape_applescript(f"PM: {name}")
        cmd_text = _escape_applescript(command)

        if i == 0:
            parts.append('    tell current session of pmWin')
            parts.append(f'        set name to "{session_name}"')
            parts.append(f'        write text "{cmd_text}"')
            parts.append('    end tell')
        else:
            parts.append('    delay 0.3')
            parts.append('    tell pmWin')
            parts.append('        create tab with default profile')
            parts.append('        tell current session')
            parts.append(f'            set name to "{session_name}"')
            parts.append(f'            write text "{cmd_text}"')
            parts.append('        end tell')
            parts.append('    end tell')

    parts.append('end tell')
    parts.append('tell application frontApp to activate')
    return '\n'.join(parts)


# ── Terminal.app AppleScript generators ────────────────────────────────────


def launch_single_terminal(path: str, name: str, command: str) -> str:
    """Generate AppleScript to launch a single session in Terminal.app.

    Opens a new Terminal.app window and runs the command.
    Terminal.app does not support named tabs or PM window detection.
    """
    cmd_text = _escape_applescript(command)

    return f'''tell application "Terminal"
    do script "{cmd_text}"
    activate
end tell'''


def launch_batch_terminal(projects: list[tuple[str, str, str]]) -> str:
    """Generate AppleScript to launch multiple projects in Terminal.app.

    Each project gets its own window (Terminal.app does not support
    programmatic tab grouping).

    Args:
        projects: List of (path, name, command) tuples.

    Returns:
        AppleScript string that opens one window per project.
    """
    if not projects:
        return ""

    parts = ['tell application "Terminal"']
    for path, name, command in projects:
        cmd_text = _escape_applescript(command)
        parts.append(f'    do script "{cmd_text}"')
        parts.append('    delay 0.5')
    parts.append('    activate')
    parts.append('end tell')
    return '\n'.join(parts)


# ── Convenience wrappers ───────────────────────────────────────────────────


def build_command(path: str, claude_args: str = "--dangerously-skip-permissions --continue") -> str:
    """Build the shell command string for launching Claude in a project.

    Args:
        path: Project directory path.
        claude_args: Arguments to pass to claude CLI.

    Returns:
        Shell command string (cd + transcript + claude).
    """
    return f"cd '{path}' && transcript && claude {claude_args}"


def launch_single(
    path: str,
    name: str,
    command: str,
    terminal: TerminalApp | None = None,
    force_terminal: bool = False,
) -> TerminalApp:
    """Detect terminal, generate script, and execute for a single project.

    Args:
        path: Project directory path.
        name: Project display name.
        command: Full shell command to run in the terminal.
        terminal: Pre-detected terminal (skips detection if provided).
        force_terminal: Force Terminal.app even if iTerm2 is available.

    Returns:
        The TerminalApp that was used.
    """
    if terminal is None:
        terminal = detect_terminal(force_terminal)

    ensure_running(terminal)

    if terminal == TerminalApp.ITERM2:
        script = launch_single_iterm(path, name, command)
    else:
        script = launch_single_terminal(path, name, command)

    subprocess.Popen(["osascript", "-e", script])
    return terminal


def launch_batch(
    projects: list[tuple[str, str, str]],
    terminal: TerminalApp | None = None,
    force_terminal: bool = False,
) -> TerminalApp:
    """Detect terminal, generate script, and execute for multiple projects.

    Args:
        projects: List of (path, name, command) tuples.
        terminal: Pre-detected terminal (skips detection if provided).
        force_terminal: Force Terminal.app even if iTerm2 is available.

    Returns:
        The TerminalApp that was used.
    """
    if not projects:
        return detect_terminal(force_terminal)

    if terminal is None:
        terminal = detect_terminal(force_terminal)

    ensure_running(terminal)

    if terminal == TerminalApp.ITERM2:
        script = launch_batch_iterm(projects)
    else:
        script = launch_batch_terminal(projects)

    subprocess.Popen(["osascript", "-e", script])
    return terminal


def is_shutdown_supported(terminal: TerminalApp | None = None) -> bool:
    """Check if graceful shutdown is supported for the given terminal.

    Only iTerm2 supports the PM shutdown workflow (finding named sessions,
    sending commands, closing tabs).

    Args:
        terminal: Terminal to check. If None, auto-detects.

    Returns:
        True if shutdown is supported (iTerm2 only).
    """
    if terminal is None:
        terminal = detect_terminal()
    return terminal == TerminalApp.ITERM2
