"""Tests for pm/agent/memory.py — per-project agent context persistence."""

import json
import pytest
from datetime import datetime
from pathlib import Path

from pm.agent.memory import (
    AgentMemory,
    read_memory,
    append_run,
    clear_memory,
    _parse_memory,
    _write_memory,
)


# ---------------------------------------------------------------------------
# _parse_memory
# ---------------------------------------------------------------------------

class TestParseMemory:
    def test_empty_string_returns_empty(self):
        mem = _parse_memory("")
        assert mem.is_empty()
        assert mem.runs == 0

    def test_parses_frontmatter_fields(self):
        content = """\
---
last_run: 2026-04-10T02:00:00
runs: 5
total_cost_usd: 1.25
---

## What I've Done
- 2026-04-10: Fixed tests

## What I've Learned
- Uses SQLAlchemy

## Don't Repeat
- Already generated ROADMAP.md
"""
        mem = _parse_memory(content)
        assert mem.runs == 5
        assert mem.total_cost_usd == 1.25
        assert mem.last_run == datetime(2026, 4, 10, 2, 0, 0)

    def test_parses_done_section(self):
        content = """\
---
runs: 1
total_cost_usd: 0.5
---

## What I've Done
- 2026-04-09: Did task A
- 2026-04-10: Did task B
"""
        mem = _parse_memory(content)
        assert len(mem.done) == 2
        assert "Did task A" in mem.done[0]
        assert "Did task B" in mem.done[1]

    def test_parses_learned_section(self):
        content = """\
---
runs: 1
total_cost_usd: 0.0
---

## What I've Learned
- Uses FastAPI
- Postgres 15
"""
        mem = _parse_memory(content)
        assert "Uses FastAPI" in mem.learned
        assert "Postgres 15" in mem.learned

    def test_parses_dont_repeat_section(self):
        content = """\
---
runs: 2
total_cost_usd: 0.0
---

## Don't Repeat
- Already generated architecture doc
"""
        mem = _parse_memory(content)
        assert "Already generated architecture doc" in mem.dont_repeat

    def test_no_frontmatter_still_parses_sections(self):
        content = """\
## What I've Done
- Did something

## What I've Learned
- Something learned
"""
        mem = _parse_memory(content)
        assert len(mem.done) == 1
        assert len(mem.learned) == 1

    def test_invalid_frontmatter_values_ignored(self):
        content = """\
---
runs: not-a-number
total_cost_usd: bad
---
"""
        mem = _parse_memory(content)
        assert mem.runs == 0
        assert mem.total_cost_usd == 0.0


# ---------------------------------------------------------------------------
# AgentMemory.to_context_block
# ---------------------------------------------------------------------------

class TestToContextBlock:
    def test_empty_memory_returns_empty_string(self):
        mem = AgentMemory()
        assert mem.to_context_block() == ""

    def test_includes_done_items(self):
        mem = AgentMemory(done=["2026-04-10: Fixed tests"])
        block = mem.to_context_block()
        assert "Fixed tests" in block
        assert "Previously done" in block

    def test_includes_learned_items(self):
        mem = AgentMemory(learned=["Uses SQLAlchemy"])
        block = mem.to_context_block()
        assert "Uses SQLAlchemy" in block
        assert "Known about" in block

    def test_includes_dont_repeat(self):
        mem = AgentMemory(dont_repeat=["Already generated ROADMAP"])
        block = mem.to_context_block()
        assert "Already generated ROADMAP" in block
        assert "Do NOT repeat" in block

    def test_limits_done_to_last_10(self):
        done = [f"2026-04-{i:02d}: Task {i}" for i in range(1, 20)]
        mem = AgentMemory(done=done)
        block = mem.to_context_block()
        # Should include last 10
        assert "Task 19" in block
        assert "Task 10" in block
        # Should not include very old ones
        assert "Task 1\n" not in block

    def test_includes_run_stats(self):
        mem = AgentMemory(runs=3, total_cost_usd=0.75, done=["something"])
        block = mem.to_context_block()
        assert "3" in block
        assert "0.75" in block


# ---------------------------------------------------------------------------
# read_memory / _write_memory (file I/O)
# ---------------------------------------------------------------------------

class TestReadWriteMemory:
    def test_read_missing_file_returns_empty(self, tmp_path):
        mem = read_memory(tmp_path)
        assert mem.is_empty()
        assert mem.runs == 0

    def test_roundtrip_write_read(self, tmp_path):
        mem = AgentMemory(
            last_run=datetime(2026, 4, 10, 12, 0, 0),
            runs=3,
            total_cost_usd=0.90,
            done=["Did task A", "Did task B"],
            learned=["Uses pytest"],
            dont_repeat=["Already wrote ROADMAP"],
        )
        assert _write_memory(tmp_path, mem)

        mem2 = read_memory(tmp_path)
        assert mem2.runs == 3
        assert mem2.total_cost_usd == 0.90
        assert "Did task A" in mem2.done[0]
        assert "Uses pytest" in mem2.learned
        assert "Already wrote ROADMAP" in mem2.dont_repeat

    def test_write_creates_docs_directory(self, tmp_path):
        mem = AgentMemory(runs=1, done=["test"])
        assert _write_memory(tmp_path, mem)
        assert (tmp_path / "docs" / "AGENT-CONTEXT.md").exists()

    def test_read_unreadable_file_returns_empty(self, tmp_path, monkeypatch):
        # Create the file first
        docs = tmp_path / "docs"
        docs.mkdir()
        mem_file = docs / "AGENT-CONTEXT.md"
        mem_file.write_text("content")

        # Then make read_text raise
        def bad_read(*args, **kwargs):
            raise PermissionError("no read")

        monkeypatch.setattr(Path, "read_text", bad_read)
        mem = read_memory(tmp_path)
        assert mem.is_empty()


# ---------------------------------------------------------------------------
# append_run
# ---------------------------------------------------------------------------

class TestAppendRun:
    def test_append_creates_file(self, tmp_path):
        result = append_run(tmp_path, "Fixed tests")
        assert result
        assert (tmp_path / "docs" / "AGENT-CONTEXT.md").exists()

    def test_append_increments_run_count(self, tmp_path):
        append_run(tmp_path, "Run 1")
        append_run(tmp_path, "Run 2")
        mem = read_memory(tmp_path)
        assert mem.runs == 2

    def test_append_accumulates_cost(self, tmp_path):
        append_run(tmp_path, "Run 1", cost_usd=0.50)
        append_run(tmp_path, "Run 2", cost_usd=0.25)
        mem = read_memory(tmp_path)
        assert abs(mem.total_cost_usd - 0.75) < 0.001

    def test_append_adds_done_entry(self, tmp_path):
        append_run(tmp_path, "Wrote ARCHITECTURE.md")
        mem = read_memory(tmp_path)
        assert any("Wrote ARCHITECTURE.md" in d for d in mem.done)

    def test_append_adds_learned_items(self, tmp_path):
        append_run(tmp_path, "Something", learned=["Uses FastAPI", "Postgres 15"])
        mem = read_memory(tmp_path)
        assert "Uses FastAPI" in mem.learned
        assert "Postgres 15" in mem.learned

    def test_append_no_duplicate_learned(self, tmp_path):
        append_run(tmp_path, "Run 1", learned=["Uses FastAPI"])
        append_run(tmp_path, "Run 2", learned=["Uses FastAPI"])
        mem = read_memory(tmp_path)
        assert mem.learned.count("Uses FastAPI") == 1

    def test_append_adds_dont_repeat(self, tmp_path):
        append_run(tmp_path, "Generated ROADMAP", dont_repeat=["Already generated ROADMAP.md"])
        mem = read_memory(tmp_path)
        assert "Already generated ROADMAP.md" in mem.dont_repeat

    def test_append_preserves_existing_entries(self, tmp_path):
        append_run(tmp_path, "First run")
        append_run(tmp_path, "Second run")
        mem = read_memory(tmp_path)
        assert any("First run" in d for d in mem.done)
        assert any("Second run" in d for d in mem.done)


# ---------------------------------------------------------------------------
# clear_memory
# ---------------------------------------------------------------------------

class TestClearMemory:
    def test_clear_deletes_file(self, tmp_path):
        append_run(tmp_path, "Something")
        assert (tmp_path / "docs" / "AGENT-CONTEXT.md").exists()
        assert clear_memory(tmp_path)
        assert not (tmp_path / "docs" / "AGENT-CONTEXT.md").exists()

    def test_clear_nonexistent_returns_true(self, tmp_path):
        assert clear_memory(tmp_path)

    def test_after_clear_read_returns_empty(self, tmp_path):
        append_run(tmp_path, "Something")
        clear_memory(tmp_path)
        mem = read_memory(tmp_path)
        assert mem.is_empty()


# ---------------------------------------------------------------------------
# pm agent memory CLI command
# ---------------------------------------------------------------------------

class TestAgentMemoryCli:
    def test_memory_no_memory_shows_none_message(self, cli_runner, populated_db):
        from click.testing import CliRunner
        from pm.cli import main
        runner = CliRunner()
        result = runner.invoke(main, ["agent", "memory", "proj-a"])
        assert result.exit_code == 0
        assert "No agent memory" in result.output

    def test_memory_project_not_found(self, populated_db):
        from click.testing import CliRunner
        from pm.cli import main
        runner = CliRunner()
        result = runner.invoke(main, ["agent", "memory", "nonexistent-xyz"])
        assert result.exit_code != 0

    def test_memory_shows_content(self, tmp_path, populated_db):
        from click.testing import CliRunner
        from pm.cli import main
        from pm.database.models import get_session, Project

        # Create a real path and update the project
        real_path = tmp_path / "proj-a"
        real_path.mkdir()
        session = get_session()
        p = session.query(Project).filter_by(id="/test/proj-a").first()
        p.path = str(real_path)
        session.commit()
        session.close()

        append_run(real_path, "Fixed tests in test_auth.py")

        runner = CliRunner()
        result = runner.invoke(main, ["agent", "memory", "proj-a"])
        assert result.exit_code == 0
        assert "Fixed tests" in result.output

    def test_memory_clear_flag(self, tmp_path, populated_db):
        from click.testing import CliRunner
        from pm.cli import main
        from pm.database.models import get_session, Project

        real_path = tmp_path / "proj-b"
        real_path.mkdir()
        session = get_session()
        p = session.query(Project).filter_by(id="/test/proj-b").first()
        p.path = str(real_path)
        session.commit()
        session.close()

        append_run(real_path, "Did something")
        runner = CliRunner()
        result = runner.invoke(main, ["agent", "memory", "proj-b", "--clear"])
        assert result.exit_code == 0
        assert "Cleared" in result.output
        assert not (real_path / "docs" / "AGENT-CONTEXT.md").exists()


@pytest.fixture
def cli_runner():
    from click.testing import CliRunner
    return CliRunner()


@pytest.fixture
def populated_db(isolated_database):
    from pm.database.models import get_session, Project
    import json
    session = get_session()
    session.add(Project(
        id="/test/proj-a", path="/test/proj-a", name="proj-a",
        project_type="node", priority=3, tags=json.dumps(["mobile"]),
    ))
    session.add(Project(
        id="/test/proj-b", path="/test/proj-b", name="proj-b",
        project_type="python", priority=2,
    ))
    session.commit()
    session.close()
    return isolated_database
