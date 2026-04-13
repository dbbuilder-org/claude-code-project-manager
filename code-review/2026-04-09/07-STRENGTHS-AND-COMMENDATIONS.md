# 07 — Strengths & Commendations: Project Manager

| Field | Value |
|-------|-------|
| Date | 2026-04-09 |

---

### S-01: Excellent test isolation infrastructure

`tests/conftest.py` uses two `autouse=True` fixtures that automatically isolate every test:
- `isolated_database` resets module-level SQLAlchemy globals and creates a fresh in-memory DB per test
- `skip_temp_check` disables the temp-dir scan guard without requiring each test to know about it

This means 300 tests run without any risk of contaminating the production database and without complex setup boilerplate per test. This is the right architecture for a tool that manages real files.

---

### S-02: Parser test coverage at 97%

`pm/scanner/parser.py` has 97% coverage across 434 lines of regex-heavy extraction logic. The tests cover edge cases including malformed markdown, mixed checkbox styles, nested sections, decision point detection, and multi-method completion percentage extraction. This is an area that would normally accumulate silent regression bugs; the tests prevent that.

---

### S-03: Health and urgency scoring are well-modeled

`pm/database/models.py`'s `health_score` and `urgency_score` properties are clean, self-contained, and well-tested. The 7-factor health model (completion, CLAUDE.md presence, progress files, recent activity, no pending decisions, clean git, known type) captures real project health signals. The urgency model correctly handles the overdue case (+50 points) and grades deadline proximity in useful bands.

---

### S-04: Terminal module is a genuine shared abstraction

`pm/terminal.py` cleanly separates iTerm2 vs Terminal.app differences behind a common interface (`launch_single`, `launch_batch`, `build_command`). The AppleScript generation functions return strings (testable) rather than executing directly, and the `_escape_applescript` helper prevents the most common injection vector. The CLI, dashboard, and scripts all use this shared module.

---

### S-05: Two-way PM-STATUS.md sync design

The concept of syncing project metadata bidirectionally between SQLite and flat-file YAML frontmatter is the right design for a tool that lives in a developer's filesystem. It means: (a) metadata survives if the DB is deleted, (b) you can set priority via text editor, and (c) metadata travels with the project if you move/copy it. The implementation in `pm/metadata.py` handles the edge cases of missing files and partial frontmatter gracefully.

---

### S-06: Rich CLI output is polished and production-quality

The CLI uses Rich tables, panels, progress bars, and color-coded severity throughout. The project status table with completion bars, flag indicators (⚠️ decision, ● dirty, 📄 CLAUDE.md), and category color-coding is genuinely useful at a glance. The urgency table with red/yellow deadline styling is actionable.

---

### S-07: Real-filesystem test fixtures

Test fixtures create real directories, real files, and real SQLite databases rather than mocking them. This catches actual filesystem interactions (permission errors, path traversal, wrong working directory) that mocks would miss. `sample_project_dir`, `sample_python_project`, `clients_container` are well-structured and reusable.

---

### S-08: Headless executor design is forward-compatible

`pm/docgen/executor.py` is cleanly designed: it takes `(project_path, prompt, output_file, budget, tools, timeout)` and returns a `DocResult` dataclass. It handles all subprocess failure modes (non-zero exit, timeout, `FileNotFoundError`) and the `run_batch_generation` function uses `ThreadPoolExecutor` with a `progress_callback` — this is exactly the interface the agent orchestrator will need to extend.

---

### S-09: Stale detection and interactive action prompts are complete and useful

`pm stale --action` provides a genuinely useful workflow: list stale projects, then interactively pick an action for each (Archive, Move Forward, Pivot, Plan, Combine, Replace). Each action writes appropriate notes/metadata and syncs to PM-STATUS.md. This is the kind of tool that gets used rather than abandoned.

---

### S-10: iMessage channel integration is well-positioned

The decision to use `imessage@claude-plugins-official` rather than building a custom bridge is correct. The plugin polls `chat.db` locally (no external service), uses AppleScript for outbound (no API tokens), and the access control system (allowlist, pairing codes, group opt-in) is appropriate for a personal tool. The `cci` alias design (opt-in rather than always-on) prevents the multiple-session echo issue.
