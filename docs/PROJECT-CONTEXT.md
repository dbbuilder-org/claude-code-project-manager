# Project Context

**Last Updated:** 2026-02-06

## Session Summary

Implemented iTerm2 → Terminal.app fallback support for all terminal launch functionality.

### Changes Made

**New Module: `pm/terminal.py`**
- `TerminalApp` enum (ITERM2, TERMINAL)
- `detect_terminal(force_terminal=False)` — checks for `/Applications/iTerm.app`
- AppleScript generators for both iTerm2 and Terminal.app (single + batch)
- `launch_single()`, `launch_batch()`, `is_shutdown_supported()` convenience wrappers
- `build_command()` for constructing cd + transcript + claude commands

**Updated Files:**
- `dashboard/app.py` — Replaced 80+ lines of inline AppleScript with `pm.terminal` calls
- `pm/cli.py` — Replaced 4 AppleScript blocks, added `--terminal` flag, added shutdown guard
- `scripts/claude-launch.sh` — Added shell-level detection and Terminal.app functions
- `dashboard-test.sh` — Added iTerm2/Terminal.app detection branch
- `CLAUDE.md` — Added Terminal Support documentation section

**Tests:**
- Created `tests/test_terminal.py` with 24 tests
- Fixed 8 pre-existing test failures in `test_cli.py` and `test_e2e.py`
- All 300 tests passing

### Created Skill
- `/save-exit` skill at `~/.claude/skills/save-exit.md`

## Current State

- Terminal fallback fully implemented and tested
- All tests passing (300/300)
- Code ready for commit

## Next Steps

- Consider removing the duplicate first `launch` command (line 389) since the second one overwrites it
- Test Terminal.app fallback on a machine without iTerm2 installed
