# iTerm2 Window Isolation

## Problem

All iTerm2 launch paths used `tell current window` + `create tab`, which hijacked whatever window the user was actively working in. Launching PM sessions would inject tabs into your working terminal window.

## Solution

Three behaviors now enforced across all launch paths:

1. **Dedicated PM window** — First launch always creates a new window
2. **Tabs in PM window** — Subsequent launches add tabs to the existing PM window (never other windows)
3. **No focus stealing** — The frontmost app is saved and restored after iTerm operations

### Session naming convention

All PM sessions are named `PM: <project-name>`. This prefix is used to identify the PM window when adding subsequent tabs.

### Focus preservation pattern

Every AppleScript block wraps iTerm operations with:

```applescript
tell application "System Events"
    set frontApp to name of first application process whose frontmost is true
end tell
-- ... iTerm operations ...
tell application frontApp to activate
```

## Files changed

### `pm/cli.py` — `pm launch` command

- Builds a single AppleScript for all projects instead of one per project
- Creates one new window, first project uses its initial session, rest add tabs
- Window reference (`pmWin`) is held for the entire script so tabs go to the right place

### `dashboard/app.py` — `launch_claude()` and `launch_batch()`

- `launch_claude(path, name)` — Called for individual project launches from the dashboard. Searches all iTerm windows for any session starting with `PM:`. If found, adds a tab to that window. If not found, creates a new PM window.
- `launch_batch(paths_names)` — Called for multi-select launches. Builds a single AppleScript creating one window with all tabs (same pattern as CLI).

### `scripts/claude-launch.sh` — Standalone launcher

- `launch_project()` — Creates a new PM window (used for first/single project). Names session `PM: <name>`.
- `launch_project_in_window()` — New function. Finds existing PM window by searching for `PM:` sessions, adds a tab to it. Falls back to new window if PM window not found.
- Batch (`--batch`) and filter (`--filter`) modes use `launch_project` for the first project, then `launch_project_in_window` for the rest.

## Launch paths summary

| Entry point | Single project | Multiple projects |
|---|---|---|
| `pm launch myproject` | New PM window | New PM window + tabs |
| `pm launch 10` | New PM window | New PM window + tabs |
| Dashboard "Launch" button | Find PM window or create new | Single AppleScript, one window |
| `claude-launch.sh proj` | New PM window | N/A |
| `claude-launch.sh --batch` | New PM window (first) | Tabs in PM window (rest) |
| `claude-launch.sh --filter` | New PM window (first) | Tabs in PM window (rest) |
