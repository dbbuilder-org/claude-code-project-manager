"""Tests for dashboard helper functions extracted from dashboard/app.py.

These test the business logic helpers that manage DB updates and PM-STATUS.md sync,
without importing the Streamlit UI layer (which requires a running Streamlit server).
"""

import json
import pytest
from datetime import datetime, date, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

from pm.database.models import Project, get_session


# ---------------------------------------------------------------------------
# Import helpers directly from dashboard module without triggering Streamlit
# ---------------------------------------------------------------------------

def _import_helpers():
    """Import dashboard helper functions without initializing Streamlit UI."""
    import importlib
    import sys
    # Stub streamlit before import so the module-level st.set_page_config() doesn't crash
    st_mock = MagicMock()
    st_mock.session_state = {}
    sys.modules.setdefault("streamlit", st_mock)
    sys.modules.setdefault("pandas", MagicMock())
    # Import only the module; don't call any st.* at import time via the mock
    import dashboard.app as app
    return app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def populated_db(isolated_database):
    """Add test projects to the isolated DB."""
    session = get_session()
    projects = [
        Project(
            id="/test/proj-a",
            path="/test/proj-a",
            name="proj-a",
            project_type="node",
            category="client",
            client_name="Acme",
            priority=3,
            notes="original notes",
            tags=json.dumps(["mobile"]),
            completion_pct=50.0,
        ),
        Project(
            id="/test/proj-b",
            path="/test/proj-b",
            name="proj-b",
            project_type="python",
            category="internal",
            priority=2,
            tags=json.dumps(["backend", "api"]),
        ),
    ]
    for p in projects:
        session.add(p)
    session.commit()
    session.close()
    return isolated_database


# ---------------------------------------------------------------------------
# _save_tags
# ---------------------------------------------------------------------------

class TestSaveTags:
    @patch("dashboard.app.sync_project_to_file")
    def test_save_tags_updates_db(self, mock_sync, populated_db):
        app = _import_helpers()
        app._save_tags("/test/proj-a", "/test/proj-a", ["mobile", "new-tag"])
        session = get_session()
        p = session.query(Project).filter_by(id="/test/proj-a").first()
        assert "new-tag" in p.tags_list
        session.close()

    @patch("dashboard.app.sync_project_to_file")
    def test_save_tags_replaces_existing(self, mock_sync, populated_db):
        app = _import_helpers()
        app._save_tags("/test/proj-a", "/test/proj-a", ["only-this"])
        session = get_session()
        p = session.query(Project).filter_by(id="/test/proj-a").first()
        assert p.tags_list == ["only-this"]
        session.close()

    @patch("dashboard.app.sync_project_to_file")
    def test_save_tags_calls_sync(self, mock_sync, populated_db):
        app = _import_helpers()
        app._save_tags("/test/proj-a", "/test/proj-a", ["tag1"])
        mock_sync.assert_called_once()

    @patch("dashboard.app.sync_project_to_file")
    def test_save_tags_project_not_found_no_crash(self, mock_sync, populated_db):
        app = _import_helpers()
        # Should silently do nothing for unknown ID
        app._save_tags("nonexistent-id", "/nonexistent", ["tag"])
        mock_sync.assert_not_called()


# ---------------------------------------------------------------------------
# _save_metadata
# ---------------------------------------------------------------------------

class TestSaveMetadata:
    @patch("dashboard.app.sync_project_to_file")
    def test_save_metadata_updates_priority(self, mock_sync, populated_db):
        app = _import_helpers()
        app._save_metadata("/test/proj-a", 1, None, None, "updated notes")
        session = get_session()
        p = session.query(Project).filter_by(id="/test/proj-a").first()
        assert p.priority == 1
        session.close()

    @patch("dashboard.app.sync_project_to_file")
    def test_save_metadata_updates_notes(self, mock_sync, populated_db):
        app = _import_helpers()
        app._save_metadata("/test/proj-a", 3, None, None, "new notes text")
        session = get_session()
        p = session.query(Project).filter_by(id="/test/proj-a").first()
        assert p.notes == "new notes text"
        session.close()

    @patch("dashboard.app.sync_project_to_file")
    def test_save_metadata_with_deadline(self, mock_sync, populated_db):
        app = _import_helpers()
        d = date(2025, 12, 31)
        app._save_metadata("/test/proj-a", 2, d, None, "")
        session = get_session()
        p = session.query(Project).filter_by(id="/test/proj-a").first()
        assert p.deadline is not None
        assert p.deadline.date() == d
        session.close()

    @patch("dashboard.app.sync_project_to_file")
    def test_save_metadata_clears_deadline(self, mock_sync, populated_db):
        """Setting deadline=None should clear it."""
        app = _import_helpers()
        # First set a deadline
        app._save_metadata("/test/proj-a", 3, date(2025, 6, 1), None, "")
        # Then clear it
        app._save_metadata("/test/proj-a", 3, None, None, "")
        session = get_session()
        p = session.query(Project).filter_by(id="/test/proj-a").first()
        assert p.deadline is None
        session.close()

    @patch("dashboard.app.sync_project_to_file")
    def test_save_metadata_calls_sync(self, mock_sync, populated_db):
        app = _import_helpers()
        app._save_metadata("/test/proj-a", 3, None, None, "")
        mock_sync.assert_called_once()

    @patch("dashboard.app.sync_project_to_file")
    def test_save_metadata_project_not_found_no_crash(self, mock_sync, populated_db):
        app = _import_helpers()
        app._save_metadata("nonexistent-id", 3, None, None, "")
        mock_sync.assert_not_called()


# ---------------------------------------------------------------------------
# _bulk_apply_tag
# ---------------------------------------------------------------------------

class TestBulkApplyTag:
    @patch("dashboard.app.sync_project_to_file")
    def test_bulk_apply_tag_adds_to_all(self, mock_sync, populated_db):
        app = _import_helpers()
        app._bulk_apply_tag(["/test/proj-a", "/test/proj-b"], "bulk-tag")
        session = get_session()
        pa = session.query(Project).filter_by(id="/test/proj-a").first()
        pb = session.query(Project).filter_by(id="/test/proj-b").first()
        assert "bulk-tag" in pa.tags_list
        assert "bulk-tag" in pb.tags_list
        session.close()

    @patch("dashboard.app.sync_project_to_file")
    def test_bulk_apply_tag_no_duplicate(self, mock_sync, populated_db):
        """Applying a tag that already exists should not create duplicates."""
        app = _import_helpers()
        app._bulk_apply_tag(["/test/proj-a"], "mobile")  # already has "mobile"
        session = get_session()
        p = session.query(Project).filter_by(id="/test/proj-a").first()
        assert p.tags_list.count("mobile") == 1
        session.close()

    @patch("dashboard.app.sync_project_to_file")
    def test_bulk_apply_tag_empty_list(self, mock_sync, populated_db):
        app = _import_helpers()
        app._bulk_apply_tag([], "some-tag")
        mock_sync.assert_not_called()

    @patch("dashboard.app.sync_project_to_file")
    def test_bulk_apply_tag_skips_not_found(self, mock_sync, populated_db):
        app = _import_helpers()
        # Mix of valid and invalid IDs — should process valid ones and skip invalid
        app._bulk_apply_tag(["/test/proj-a", "nonexistent"], "tag")
        session = get_session()
        p = session.query(Project).filter_by(id="/test/proj-a").first()
        assert "tag" in p.tags_list
        session.close()


# ---------------------------------------------------------------------------
# _run_prompt_on_project
# ---------------------------------------------------------------------------

class TestRunPromptOnProject:
    @patch("dashboard.app.subprocess.run")
    def test_run_prompt_success(self, mock_run, populated_db):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="Analysis complete.", stderr=""
        )
        app = _import_helpers()
        result = app._run_prompt_on_project("/test/proj-a", "proj-a", "Summarize")
        assert result["status"] == "success"
        assert "Analysis complete" in result["output"]
        # Cleanup transcript
        import shutil
        from pathlib import Path
        td = Path(__file__).parent.parent / "transcripts" / "proj-a"
        shutil.rmtree(td, ignore_errors=True)

    @pytest.fixture(autouse=True)
    def cleanup_transcripts(self):
        yield
        import shutil
        from pathlib import Path
        shutil.rmtree(Path(__file__).parent.parent / "transcripts" / "proj-a", ignore_errors=True)

    @patch("dashboard.app.subprocess.run")
    def test_run_prompt_error(self, mock_run, populated_db):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="Something failed"
        )
        app = _import_helpers()
        result = app._run_prompt_on_project("/test/proj-a", "proj-a", "Do something")
        assert result["status"] == "error"
        assert "Something failed" in result["output"]

    @patch("dashboard.app.subprocess.run")
    def test_run_prompt_timeout(self, mock_run, populated_db):
        import subprocess as sp
        mock_run.side_effect = sp.TimeoutExpired(cmd="claude", timeout=5)
        app = _import_helpers()
        result = app._run_prompt_on_project("/test/proj-a", "proj-a", "Slow", timeout_secs=5)
        assert result["status"] == "timeout"
        assert "TIMEOUT" in result["output"]

    @patch("dashboard.app.subprocess.run")
    def test_run_prompt_claude_not_found(self, mock_run, populated_db):
        mock_run.side_effect = FileNotFoundError()
        app = _import_helpers()
        result = app._run_prompt_on_project("/test/proj-a", "proj-a", "Hello")
        assert result["status"] == "error"
        assert "not found" in result["output"]

    @patch("dashboard.app.subprocess.run")
    def test_run_prompt_creates_transcript(self, mock_run, populated_db):
        mock_run.return_value = MagicMock(returncode=0, stdout="Output text", stderr="")
        app = _import_helpers()
        result = app._run_prompt_on_project("/test/proj-a", "proj-a", "Test")
        assert "transcript_file" in result
        assert result["transcript_file"].endswith(".md")

    @patch("dashboard.app.subprocess.run")
    def test_run_prompt_empty_output_status(self, mock_run, populated_db):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        app = _import_helpers()
        result = app._run_prompt_on_project("/test/proj-a", "proj-a", "Empty")
        assert result["status"] == "empty"
