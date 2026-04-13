# Testing Review

| Field | Value |
|-------|-------|
| Date | 2026-04-12 |
| Reviewer | Chris Therriault |
| Commit | 310999f |
| Test Count | 479 (479 passed, 0 failed) |
| Overall Coverage | 75% |

## Summary

| Severity | Count |
|----------|-------|
| HIGH | 0 |
| MEDIUM | 3 |
| LOW | 2 |

The test suite is healthy: 479 tests pass with no failures, overall coverage hits the 75% CI threshold, and the distribution spans unit, integration, and CLI tests. The gaps are concentrated in the agent subsystem (`escalation.py` at 29%, `coordinator.py` at 44%, `planner.py` at 47%) and the CLI's shutdown/launch/scheduling paths which require macOS-specific subprocess mocking.

---

## Coverage by File

| Module | Stmts | Miss | Coverage | Note |
|--------|-------|------|----------|------|
| `pm/cli.py` | 1694 | 534 | **68%** | Launch, shutdown, schedule paths mostly uncovered |
| `pm/agent/escalation.py` | 92 | 65 | **29%** | Lowest coverage in codebase |
| `pm/agent/coordinator.py` | 68 | 38 | **44%** | ThreadPoolExecutor paths untested |
| `pm/agent/planner.py` | 62 | 33 | **47%** | Actual Claude invocation paths untested |
| `pm/agent/runner.py` | 47 | 21 | **55%** | Execute phase paths untested |
| `pm/terminal.py` | 92 | 12 | 87% | Sleep/delay paths untested |
| `pm/scanner/detector.py` | 116 | 23 | 80% | Git-heavy paths |
| `pm/database/models.py` | 265 | 30 | 89% | Migration edge cases |
| `pm/agent/memory.py` | 168 | 16 | 90% | Good |
| `pm/docgen/executor.py` | 57 | 4 | 93% | Near-complete |
| `pm/metadata.py` | 136 | 4 | 97% | Excellent |
| `pm/scanner/parser.py` | 199 | 7 | 96% | Excellent |
| `pm/brief.py` | 153 | 40 | 74% | iMessage and edge formatting paths |
| `pm/digest.py` | 56 | 0 | **100%** | Complete |
| `pm/docgen/templates.py` | 26 | 0 | **100%** | Complete |
| `pm/generator/prompts.py` | 92 | 0 | **100%** | Complete |

---

### TST-001: `pm/agent/escalation.py` at 29% Coverage

| Field | Value |
|-------|-------|
| Severity | MEDIUM |
| Location | `pm/agent/escalation.py:50–203` |
| Effort | 5 SP |

**Description:** The escalation module handles iMessage send and reply polling — a real-time, side-effectful system that is difficult to test without mocking. Currently only the `EscalationResult` dataclass and module imports are exercised. The core functions are untested:

- `escalate_for_decision()` (line 55–97) — sends message, creates poll loop
- `wait_for_reply()` (line 110–134) — polls chat.db with timeout
- `_send_imessage()` (line 149–167) — AppleScript subprocess (SEC-001 gap also lives here)
- `poll_for_reply()` (line 175–203) — reads iMessage DB

**Recommendation:** Add mocked subprocess tests for `_send_imessage`:
```python
@patch("pm.agent.escalation.subprocess.run")
def test_send_imessage_escapes_quotes(mock_run, ...):
    mock_run.return_value = MagicMock(returncode=0)
    _send_imessage("+1234567890", 'say "hello"')
    script = mock_run.call_args[0][0][2]  # osascript -e <script>
    assert '\\"hello\\"' in script  # quotes escaped
```
For `wait_for_reply` and `poll_for_reply`, mock the SQLite `chat.db` connection with a temporary in-memory DB or fixture. This is where SEC-001 fix can also be verified.

---

### TST-002: `pm/agent/coordinator.py` at 44% — ThreadPoolExecutor Paths Untested

| Field | Value |
|-------|-------|
| Severity | MEDIUM |
| Location | `pm/agent/coordinator.py:42–163` |
| Effort | 3 SP |

**Description:** The coordinator's `run_batch_generation()` and `run_batch_assess_execute()` use `ThreadPoolExecutor` for parallel project processing. The untested lines (42–163) include the executor loop, per-project result collection, and error aggregation. No test exercises the threading behavior, which means race conditions or result-merging bugs in batch runs would not be caught.

**Recommendation:** Add tests that mock `planner.assess()` and `runner.execute()` to return canned results, then assert the coordinator aggregates them correctly:
```python
@patch("pm.agent.coordinator.run_assessment")
def test_batch_assess_returns_all_results(mock_assess, ...):
    mock_assess.return_value = AssessmentResult(confidence=85, ...)
    results = run_batch_assess_execute(projects, dry_run=True)
    assert len(results) == len(projects)
```

---

### TST-003: `pm/cli.py` Launch/Shutdown/Schedule Paths at 68%

| Field | Value |
|-------|-------|
| Severity | MEDIUM |
| Location | `pm/cli.py:1639–1764` (shutdown), `pm/cli.py:1860–2000` (schedule) |
| Effort | 5 SP |

**Description:** The `pm launch` and `pm shutdown` commands' iTerm2 paths (lines 1639–1764) and the `pm schedule install/uninstall/status` commands (lines 1860–2000) are uncovered. These paths involve `subprocess.run(["osascript", ...])` and launchd plist file I/O — both are straightforwardly mockable.

The `pm dashboard` command (lines 432–440) is entirely untested.

**Recommendation:**
1. Add a `test_launch_dry_run()` test that patches `subprocess.run` and asserts `--dry-run` prints without calling osascript.
2. Add `test_schedule_install_creates_plist()` that patches `subprocess.run` and checks plist file creation in a `tmp_path`.
3. Add `test_schedule_status_not_installed()` that asserts correct output when the plist doesn't exist.

---

### TST-004: No Mutation Tests for `_escape_applescript`

| Field | Value |
|-------|-------|
| Severity | LOW |
| Location | `tests/test_terminal.py` |
| Effort | 1 SP |

**Description:** `pm/terminal.py:87%` coverage is good, but the uncovered lines 42–54 include the `_start_iterm2_if_needed()` helper. More importantly, there are no tests specifically for injection edge cases in `_escape_applescript` (e.g., null bytes, carriage returns, mixed escape sequences). The SEC-001 finding highlights that a similar function in `cli.py` has no escaping at all — the tests don't catch this because they don't exercise the triage iMessage path.

**Recommendation:** Add parameterized edge-case tests for `_escape_applescript`:
```python
@pytest.mark.parametrize("input,expected", [
    ('say "hello"', 'say \\"hello\\"'),
    ("line1\nline2", "line1 line2"),
    ("path\\file", "path\\\\file"),
    ("\x00null", "null"),
])
def test_escape_applescript_edge_cases(input, expected):
    assert _escape_applescript(input) == expected
```

---

### TST-005: `pm/brief.py` at 74% — iMessage Formatting Paths Untested

| Field | Value |
|-------|-------|
| Severity | LOW |
| Location | `pm/brief.py:76–84,113–125,233–252` |
| Effort | 2 SP |

**Description:** The `format_brief_imessage()` function (and surrounding formatting helpers) has several branches uncovered — specifically the "all clear" path when no items exist, and the multi-section formatting when overdue + stale + decisions all have entries simultaneously.

**Recommendation:** Add unit tests for `format_brief_imessage` with mocked `BriefData` objects exercising each combination of populated/empty sections.

---

## Test Infrastructure Strengths

- **`isolated_database` fixture** (in `conftest.py`) correctly uses an in-memory SQLite engine separate from the production `~/.pm/projects.db` — no test pollution risk.
- **`no_reinit_db` autouse fixture** patches `init_db` globally, preventing test setup from touching the real database.
- **`CliRunner` usage** is consistent across all CLI test files — commands are tested through the Click interface, not by calling Python functions directly.
- **CI pipeline** runs on `macos-latest` with Python 3.12, which matches the production environment — no cross-platform coverage gap.
- **Coverage threshold enforced at 75%** in CI (`--cov-fail-under=75`).
