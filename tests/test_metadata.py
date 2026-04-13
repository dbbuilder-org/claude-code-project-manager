"""Tests for pm/metadata.py — PM-STATUS.md two-way sync."""

import os
import pytest
from pathlib import Path
from datetime import datetime

from pm.metadata import (
    PM_STATUS_FILENAME,
    ProjectMetadata,
    parse_pm_status,
    read_pm_status,
    write_pm_status,
    sync_to_file,
    _parse_date,
    _parse_list,
)


# ---------------------------------------------------------------------------
# _parse_date
# ---------------------------------------------------------------------------

class TestParseDate:
    def test_iso_format(self):
        d = _parse_date("2025-12-31")
        assert d == datetime(2025, 12, 31)

    def test_slash_format(self):
        d = _parse_date("2025/12/31")
        assert d == datetime(2025, 12, 31)

    def test_us_format(self):
        d = _parse_date("12/31/2025")
        assert d == datetime(2025, 12, 31)

    def test_dmy_format(self):
        d = _parse_date("31-12-2025")
        assert d == datetime(2025, 12, 31)

    def test_empty_string_returns_none(self):
        assert _parse_date("") is None

    def test_null_keyword(self):
        assert _parse_date("null") is None
        assert _parse_date("none") is None
        assert _parse_date("NONE") is None

    def test_garbage_returns_none(self):
        assert _parse_date("not-a-date") is None


# ---------------------------------------------------------------------------
# _parse_list
# ---------------------------------------------------------------------------

class TestParseList:
    def test_bracket_list(self):
        assert _parse_list("[mobile, ios]") == ["mobile", "ios"]

    def test_plain_csv(self):
        assert _parse_list("a, b, c") == ["a", "b", "c"]

    def test_single_item(self):
        assert _parse_list("solo") == ["solo"]

    def test_quoted_items(self):
        assert _parse_list('["foo", "bar"]') == ["foo", "bar"]

    def test_empty_string(self):
        assert _parse_list("") == []

    def test_empty_brackets(self):
        assert _parse_list("[]") == []


# ---------------------------------------------------------------------------
# parse_pm_status
# ---------------------------------------------------------------------------

MINIMAL_FRONTMATTER = """\
---
priority: 2
---
"""

FULL_FRONTMATTER = """\
---
priority: high
deadline: 2025-06-30
target_date: 2025-05-01
tags: [mobile, ios]
client: Acme Corp
budget_hours: 40
hours_logged: 12.5
archived: true
---

# Project Notes

Some free-form notes here.
More context on line two.
"""

NO_FRONTMATTER = "Just some notes without frontmatter.\nSecond line."


class TestParsePmStatus:
    def test_minimal_frontmatter(self):
        m = parse_pm_status(MINIMAL_FRONTMATTER)
        assert m.priority == 2
        assert m.deadline is None
        assert m.notes == ""

    def test_full_frontmatter(self):
        m = parse_pm_status(FULL_FRONTMATTER)
        assert m.priority == 2  # "high" maps to 2
        assert m.deadline == datetime(2025, 6, 30)
        assert m.target_date == datetime(2025, 5, 1)
        assert m.tags == ["mobile", "ios"]
        assert m.client_name == "Acme Corp"
        assert m.budget_hours == 40.0
        assert m.hours_logged == 12.5
        assert m.archived is True
        assert "free-form notes" in m.notes

    def test_no_frontmatter(self):
        m = parse_pm_status(NO_FRONTMATTER)
        assert m.priority == 3  # default
        assert m.notes == NO_FRONTMATTER.strip()

    def test_text_priority_critical(self):
        m = parse_pm_status("---\npriority: critical\n---\n")
        assert m.priority == 1

    def test_text_priority_someday(self):
        m = parse_pm_status("---\npriority: someday\n---\n")
        assert m.priority == 5

    def test_text_priority_unknown_defaults_to_normal(self):
        m = parse_pm_status("---\npriority: weird\n---\n")
        assert m.priority == 3

    def test_invalid_priority_int_defaults_to_normal(self):
        # non-numeric, non-keyword value
        m = parse_pm_status("---\npriority: ???\n---\n")
        assert m.priority == 3

    def test_archived_false_variants(self):
        for val in ("false", "no", "0"):
            m = parse_pm_status(f"---\narchived: {val}\n---\n")
            assert m.archived is False

    def test_archived_true_variants(self):
        for val in ("true", "yes", "1"):
            m = parse_pm_status(f"---\narchived: {val}\n---\n")
            assert m.archived is True

    def test_target_alias(self):
        m = parse_pm_status("---\ntarget: 2025-09-01\n---\n")
        assert m.target_date == datetime(2025, 9, 1)

    def test_client_name_alias(self):
        m = parse_pm_status("---\nclient_name: Beta Corp\n---\n")
        assert m.client_name == "Beta Corp"

    def test_budget_alias(self):
        m = parse_pm_status("---\nbudget: 80\n---\n")
        assert m.budget_hours == 80.0

    def test_hours_alias(self):
        m = parse_pm_status("---\nhours: 5.5\n---\n")
        assert m.hours_logged == 5.5

    def test_null_client_name(self):
        m = parse_pm_status("---\nclient: null\n---\n")
        assert m.client_name is None

    def test_source_file_stored(self):
        m = parse_pm_status(MINIMAL_FRONTMATTER, source_file="/some/path.md")
        assert m.source_file == "/some/path.md"

    def test_bad_budget_ignored(self):
        m = parse_pm_status("---\nbudget_hours: notanumber\n---\n")
        assert m.budget_hours is None

    def test_bad_hours_defaults_to_zero(self):
        m = parse_pm_status("---\nhours_logged: notanumber\n---\n")
        assert m.hours_logged == 0


# ---------------------------------------------------------------------------
# read_pm_status
# ---------------------------------------------------------------------------

class TestReadPmStatus:
    def test_returns_none_when_file_absent(self, tmp_path):
        assert read_pm_status(tmp_path) is None

    def test_reads_existing_file(self, tmp_path):
        (tmp_path / PM_STATUS_FILENAME).write_text(FULL_FRONTMATTER)
        m = read_pm_status(tmp_path)
        assert m is not None
        assert m.client_name == "Acme Corp"

    def test_source_file_set_to_absolute_path(self, tmp_path):
        (tmp_path / PM_STATUS_FILENAME).write_text(MINIMAL_FRONTMATTER)
        m = read_pm_status(tmp_path)
        assert m.source_file == str(tmp_path / PM_STATUS_FILENAME)

    def test_handles_unreadable_file(self, tmp_path, monkeypatch):
        """Returns None when file cannot be read."""
        status_file = tmp_path / PM_STATUS_FILENAME
        status_file.write_text(MINIMAL_FRONTMATTER)
        # Make read_text raise
        monkeypatch.setattr(Path, "read_text", lambda *a, **kw: (_ for _ in ()).throw(PermissionError("no")))
        assert read_pm_status(tmp_path) is None


# ---------------------------------------------------------------------------
# write_pm_status
# ---------------------------------------------------------------------------

class TestWritePmStatus:
    def _make_meta(self, **kwargs):
        m = ProjectMetadata()
        for k, v in kwargs.items():
            setattr(m, k, v)
        return m

    def test_writes_file(self, tmp_path):
        m = self._make_meta(priority=1)
        assert write_pm_status(tmp_path, m) is True
        assert (tmp_path / PM_STATUS_FILENAME).exists()

    def test_roundtrip_basic(self, tmp_path):
        m = self._make_meta(priority=2, notes="hello world")
        write_pm_status(tmp_path, m)
        m2 = read_pm_status(tmp_path)
        assert m2.priority == 2
        assert "hello world" in m2.notes

    def test_roundtrip_deadline(self, tmp_path):
        m = self._make_meta(deadline=datetime(2025, 12, 1))
        write_pm_status(tmp_path, m)
        m2 = read_pm_status(tmp_path)
        assert m2.deadline == datetime(2025, 12, 1)

    def test_roundtrip_tags(self, tmp_path):
        m = self._make_meta(tags=["api", "backend"])
        write_pm_status(tmp_path, m)
        m2 = read_pm_status(tmp_path)
        assert m2.tags == ["api", "backend"]

    def test_roundtrip_client(self, tmp_path):
        m = self._make_meta(client_name="Zeta Corp")
        write_pm_status(tmp_path, m)
        m2 = read_pm_status(tmp_path)
        assert m2.client_name == "Zeta Corp"

    def test_roundtrip_archived(self, tmp_path):
        m = self._make_meta(archived=True)
        write_pm_status(tmp_path, m)
        m2 = read_pm_status(tmp_path)
        assert m2.archived is True

    def test_atomic_write_no_tmp_left_on_success(self, tmp_path):
        m = self._make_meta()
        write_pm_status(tmp_path, m)
        assert not (tmp_path / "PM-STATUS.tmp").exists()

    def test_default_notes_placeholder_written(self, tmp_path):
        m = self._make_meta()  # notes=""
        write_pm_status(tmp_path, m)
        content = (tmp_path / PM_STATUS_FILENAME).read_text()
        assert "# Project Notes" in content

    def test_handles_write_failure(self, tmp_path, monkeypatch):
        """Returns False when write fails; no .tmp left behind."""
        def bad_write(self, content):
            raise OSError("disk full")
        monkeypatch.setattr(Path, "write_text", bad_write)
        m = self._make_meta()
        result = write_pm_status(tmp_path, m)
        assert result is False
        assert not (tmp_path / "PM-STATUS.tmp").exists()


# ---------------------------------------------------------------------------
# sync_to_file
# ---------------------------------------------------------------------------

class TestSyncToFile:
    def test_creates_file_when_absent(self, tmp_path):
        result = sync_to_file(tmp_path, priority=1)
        assert result is True
        m = read_pm_status(tmp_path)
        assert m.priority == 1

    def test_preserves_existing_notes(self, tmp_path):
        (tmp_path / PM_STATUS_FILENAME).write_text(
            "---\npriority: 3\n---\n\n# Notes\n\nKeep this note."
        )
        sync_to_file(tmp_path, priority=1)
        m = read_pm_status(tmp_path)
        assert m.priority == 1
        assert "Keep this note" in m.notes

    def test_updates_only_given_fields(self, tmp_path):
        m0 = ProjectMetadata(priority=2, client_name="Existing Client")
        write_pm_status(tmp_path, m0)
        sync_to_file(tmp_path, priority=4)
        m2 = read_pm_status(tmp_path)
        assert m2.priority == 4
        # client_name preserved from original file
        assert m2.client_name == "Existing Client"

    def test_ignores_unknown_kwargs(self, tmp_path):
        """sync_to_file must not crash on unknown field names."""
        result = sync_to_file(tmp_path, nonexistent_field="value")
        assert result is True
