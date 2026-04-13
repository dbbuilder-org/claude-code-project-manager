"""Tests for Tier 1 features: Tags, Activity Digest, Stale Detection, Run Prompt."""

import json
import pytest
from datetime import datetime, date, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

from click.testing import CliRunner
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pm.cli import main
from pm.database.models import Base, Project, ScanHistory, init_db, get_session
from pm.digest import week_to_date_range, digest_by_project, digest_by_day


@pytest.fixture
def cli_runner():
    return CliRunner()


@pytest.fixture(autouse=True)
def no_reinit_db():
    """Prevent CLI commands from re-initializing the database over the test fixture.

    The conftest isolated_database fixture already sets up a temp DB.
    Without this patch, CLI commands call init_db() with the default path,
    which overrides the test database and reads from production.
    """
    with patch("pm.cli.init_db"):
        yield


@pytest.fixture
def populated_db(isolated_database):
    """Populate DB with projects for tag/stale/digest tests."""
    session = get_session()

    projects = [
        Project(
            id="/test/proj-alpha",
            path="/test/proj-alpha",
            name="proj-alpha",
            project_type="node",
            category="client",
            client_name="Acme Corp",
            completion_pct=80.0,
            last_activity=datetime.utcnow() - timedelta(days=2),
            last_commit_date=datetime.utcnow() - timedelta(days=1),
            last_commit_msg="feat: add login",
            current_status="In progress",
            has_claude_md=True,
            has_todo=True,
            priority=2,
            tags=json.dumps(["mobile", "ios"]),
        ),
        Project(
            id="/test/proj-beta",
            path="/test/proj-beta",
            name="proj-beta",
            project_type="python",
            category="internal",
            completion_pct=30.0,
            last_activity=datetime.utcnow() - timedelta(days=60),
            last_commit_date=datetime.utcnow() - timedelta(days=60),
            last_commit_msg="fix: minor",
            current_status="Stalled",
            priority=3,
            tags=json.dumps(["mobile"]),
        ),
        Project(
            id="/test/proj-gamma",
            path="/test/proj-gamma",
            name="proj-gamma",
            project_type="rust",
            category="tool",
            completion_pct=95.0,
            last_activity=datetime.utcnow() - timedelta(days=1),
            last_commit_date=datetime.utcnow() - timedelta(days=1),
            last_commit_msg="chore: cleanup",
            current_status="Nearly done",
            has_claude_md=True,
            priority=4,
        ),
        Project(
            id="/test/proj-archived",
            path="/test/proj-archived",
            name="proj-archived",
            project_type="node",
            category="internal",
            last_activity=datetime.utcnow() - timedelta(days=120),
            archived=True,
            priority=3,
        ),
        Project(
            id="/test/proj-someday",
            path="/test/proj-someday",
            name="proj-someday",
            project_type="python",
            category="internal",
            last_activity=datetime.utcnow() - timedelta(days=90),
            priority=5,
        ),
    ]

    for p in projects:
        session.add(p)
    session.commit()
    session.close()
    return isolated_database


@pytest.fixture
def db_with_history(populated_db):
    """Add scan history records for digest tests."""
    session = get_session()

    now = datetime.utcnow()
    # proj-alpha: scanned twice in the past week
    session.add(ScanHistory(
        project_id="/test/proj-alpha",
        scanned_at=now - timedelta(days=3),
        completion_pct=70.0,
        items_total=10, items_complete=7, items_in_progress=1, items_pending=2,
    ))
    session.add(ScanHistory(
        project_id="/test/proj-alpha",
        scanned_at=now - timedelta(days=1),
        completion_pct=80.0,
        items_total=10, items_complete=8, items_in_progress=1, items_pending=1,
    ))

    # proj-gamma: scanned once
    session.add(ScanHistory(
        project_id="/test/proj-gamma",
        scanned_at=now - timedelta(days=1),
        completion_pct=95.0,
        items_total=20, items_complete=19, items_in_progress=0, items_pending=1,
    ))

    # proj-beta: scanned 60 days ago (outside default week range but useful for custom range)
    session.add(ScanHistory(
        project_id="/test/proj-beta",
        scanned_at=now - timedelta(days=60),
        completion_pct=25.0,
    ))
    session.add(ScanHistory(
        project_id="/test/proj-beta",
        scanned_at=now - timedelta(days=55),
        completion_pct=30.0,
    ))

    session.commit()
    session.close()
    return populated_db


# ── Tag Model Tests ────────────────────────────────────────────────────────


class TestTagModel:
    """Tests for tag helpers on Project model."""

    def test_tags_list_empty(self, db_session):
        p = Project(id="/t/1", path="/t/1", name="p1")
        db_session.add(p)
        db_session.commit()
        assert p.tags_list == []

    def test_tags_list_with_data(self, db_session):
        p = Project(id="/t/1", path="/t/1", name="p1", tags=json.dumps(["a", "b"]))
        db_session.add(p)
        db_session.commit()
        assert p.tags_list == ["a", "b"]

    def test_add_tag(self, db_session):
        p = Project(id="/t/1", path="/t/1", name="p1")
        db_session.add(p)
        db_session.commit()
        p.add_tag("mobile")
        assert "mobile" in p.tags_list

    def test_add_tag_no_duplicate(self, db_session):
        p = Project(id="/t/1", path="/t/1", name="p1", tags=json.dumps(["mobile"]))
        db_session.add(p)
        db_session.commit()
        p.add_tag("mobile")
        assert p.tags_list.count("mobile") == 1

    def test_remove_tag(self, db_session):
        p = Project(id="/t/1", path="/t/1", name="p1", tags=json.dumps(["a", "b"]))
        db_session.add(p)
        db_session.commit()
        p.remove_tag("a")
        assert p.tags_list == ["b"]

    def test_remove_tag_not_present(self, db_session):
        p = Project(id="/t/1", path="/t/1", name="p1", tags=json.dumps(["a"]))
        db_session.add(p)
        db_session.commit()
        p.remove_tag("z")
        assert p.tags_list == ["a"]

    def test_all_tags_static(self, db_session):
        p1 = Project(id="/t/1", path="/t/1", name="p1", tags=json.dumps(["a", "b"]))
        p2 = Project(id="/t/2", path="/t/2", name="p2", tags=json.dumps(["b", "c"]))
        p3 = Project(id="/t/3", path="/t/3", name="p3")
        db_session.add_all([p1, p2, p3])
        db_session.commit()
        assert Project.all_tags(db_session) == ["a", "b", "c"]

    def test_all_tags_empty(self, db_session):
        p = Project(id="/t/1", path="/t/1", name="p1")
        db_session.add(p)
        db_session.commit()
        assert Project.all_tags(db_session) == []

    def test_tags_list_malformed_json(self, db_session):
        p = Project(id="/t/1", path="/t/1", name="p1", tags="not-json")
        db_session.add(p)
        db_session.commit()
        assert p.tags_list == []


# ── Stale Model Tests ──────────────────────────────────────────────────────


class TestStaleModel:
    """Tests for is_stale property on Project model."""

    def test_stale_old_project(self, db_session):
        p = Project(
            id="/t/1", path="/t/1", name="p1",
            last_activity=datetime.utcnow() - timedelta(days=45),
        )
        db_session.add(p)
        db_session.commit()
        assert p.is_stale is True

    def test_not_stale_recent(self, db_session):
        p = Project(
            id="/t/1", path="/t/1", name="p1",
            last_activity=datetime.utcnow() - timedelta(days=5),
        )
        db_session.add(p)
        db_session.commit()
        assert p.is_stale is False

    def test_not_stale_archived(self, db_session):
        p = Project(
            id="/t/1", path="/t/1", name="p1",
            last_activity=datetime.utcnow() - timedelta(days=90),
            archived=True,
        )
        db_session.add(p)
        db_session.commit()
        assert p.is_stale is False

    def test_not_stale_someday(self, db_session):
        p = Project(
            id="/t/1", path="/t/1", name="p1",
            last_activity=datetime.utcnow() - timedelta(days=90),
            priority=5,
        )
        db_session.add(p)
        db_session.commit()
        assert p.is_stale is False

    def test_stale_no_activity(self, db_session):
        p = Project(id="/t/1", path="/t/1", name="p1")
        db_session.add(p)
        db_session.commit()
        assert p.is_stale is True

    def test_stale_boundary_30_days(self, db_session):
        p = Project(
            id="/t/1", path="/t/1", name="p1",
            last_activity=datetime.utcnow() - timedelta(days=30),
        )
        db_session.add(p)
        db_session.commit()
        assert p.is_stale is True

    def test_not_stale_boundary_29_days(self, db_session):
        p = Project(
            id="/t/1", path="/t/1", name="p1",
            last_activity=datetime.utcnow() - timedelta(days=29),
        )
        db_session.add(p)
        db_session.commit()
        assert p.is_stale is False


# ── Digest Function Tests ─────────────────────────────────────────────────


class TestWeekToDateRange:
    """Tests for week_to_date_range()."""

    def test_returns_tuple_of_datetimes(self):
        start, end = week_to_date_range()
        assert isinstance(start, datetime)
        assert isinstance(end, datetime)

    def test_start_is_sunday(self):
        start, _ = week_to_date_range()
        # Sunday = weekday() 6
        assert start.weekday() == 6

    def test_start_is_midnight(self):
        start, _ = week_to_date_range()
        assert start.hour == 0
        assert start.minute == 0
        assert start.second == 0

    def test_end_is_today(self):
        _, end = week_to_date_range()
        assert end.date() == date.today()

    def test_end_is_end_of_day(self):
        _, end = week_to_date_range()
        assert end.hour == 23
        assert end.minute == 59

    def test_start_before_end(self):
        start, end = week_to_date_range()
        assert start <= end


class TestDigestByProject:
    """Tests for digest_by_project()."""

    def test_returns_results_with_history(self, db_with_history):
        session = get_session()
        now = datetime.utcnow()
        start = now - timedelta(days=7)
        end = now + timedelta(hours=1)

        results = digest_by_project(session, start, end)
        assert len(results) >= 1
        session.close()

    def test_completion_delta_calculated(self, db_with_history):
        session = get_session()
        now = datetime.utcnow()
        start = now - timedelta(days=7)
        end = now + timedelta(hours=1)

        results = digest_by_project(session, start, end)
        alpha = next((r for r in results if r["name"] == "proj-alpha"), None)
        assert alpha is not None
        assert alpha["completion_delta"] == 10.0  # 80 - 70
        session.close()

    def test_client_filter(self, db_with_history):
        session = get_session()
        now = datetime.utcnow()
        start = now - timedelta(days=7)
        end = now + timedelta(hours=1)

        results = digest_by_project(session, start, end, client_filter="Acme")
        assert all(r["client"] == "Acme Corp" for r in results)
        session.close()

    def test_client_filter_no_match(self, db_with_history):
        session = get_session()
        now = datetime.utcnow()
        start = now - timedelta(days=7)
        end = now + timedelta(hours=1)

        results = digest_by_project(session, start, end, client_filter="Nonexistent")
        assert results == []
        session.close()

    def test_empty_range(self, db_with_history):
        session = get_session()
        # Range far in the future
        start = datetime(2099, 1, 1)
        end = datetime(2099, 12, 31)

        results = digest_by_project(session, start, end)
        assert results == []
        session.close()

    def test_sorted_by_client_then_name(self, db_with_history):
        session = get_session()
        now = datetime.utcnow()
        start = now - timedelta(days=7)
        end = now + timedelta(hours=1)

        results = digest_by_project(session, start, end)
        if len(results) >= 2:
            for i in range(len(results) - 1):
                key_a = (results[i]["client"] or "zzz", results[i]["name"])
                key_b = (results[i + 1]["client"] or "zzz", results[i + 1]["name"])
                assert key_a <= key_b
        session.close()

    def test_result_fields(self, db_with_history):
        session = get_session()
        now = datetime.utcnow()
        start = now - timedelta(days=7)
        end = now + timedelta(hours=1)

        results = digest_by_project(session, start, end)
        if results:
            r = results[0]
            assert "name" in r
            assert "client" in r
            assert "completion_delta" in r
            assert "current_completion" in r
            assert "last_commit_msg" in r
            assert "current_status" in r
            assert "health" in r
            assert "scan_count" in r
        session.close()

    def test_includes_commit_only_projects(self, db_with_history):
        """Projects with recent commits but no scan history should appear."""
        session = get_session()
        # Add a project with a recent commit but no scan history
        p = Project(
            id="/test/commit-only",
            path="/test/commit-only",
            name="commit-only",
            last_commit_date=datetime.utcnow() - timedelta(hours=5),
            completion_pct=50.0,
        )
        session.add(p)
        session.commit()

        now = datetime.utcnow()
        start = now - timedelta(days=7)
        end = now + timedelta(hours=1)

        results = digest_by_project(session, start, end)
        names = [r["name"] for r in results]
        assert "commit-only" in names
        session.close()


class TestDigestByDay:
    """Tests for digest_by_day()."""

    def test_returns_results(self, db_with_history):
        session = get_session()
        now = datetime.utcnow()
        start = now - timedelta(days=7)
        end = now + timedelta(hours=1)

        results = digest_by_day(session, start, end)
        assert len(results) >= 1
        session.close()

    def test_sorted_by_date(self, db_with_history):
        session = get_session()
        now = datetime.utcnow()
        start = now - timedelta(days=7)
        end = now + timedelta(hours=1)

        results = digest_by_day(session, start, end)
        dates = [r["date"] for r in results]
        assert dates == sorted(dates)
        session.close()

    def test_result_fields(self, db_with_history):
        session = get_session()
        now = datetime.utcnow()
        start = now - timedelta(days=7)
        end = now + timedelta(hours=1)

        results = digest_by_day(session, start, end)
        if results:
            r = results[0]
            assert "date" in r
            assert "day_name" in r
            assert "project_names" in r
            assert "project_count" in r
            assert isinstance(r["project_names"], list)
            assert r["project_count"] == len(r["project_names"])
        session.close()

    def test_empty_range(self, db_with_history):
        session = get_session()
        start = datetime(2099, 1, 1)
        end = datetime(2099, 12, 31)

        results = digest_by_day(session, start, end)
        assert results == []
        session.close()

    def test_day_name_populated(self, db_with_history):
        session = get_session()
        now = datetime.utcnow()
        start = now - timedelta(days=7)
        end = now + timedelta(hours=1)

        results = digest_by_day(session, start, end)
        valid_days = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"}
        for r in results:
            assert r["day_name"] in valid_days
        session.close()


# ── CLI Tag Commands ───────────────────────────────────────────────────────


class TestTagsCLI:
    """Tests for pm tags CLI commands."""

    def test_tags_list_empty(self, cli_runner, isolated_database):
        result = cli_runner.invoke(main, ["tags", "list"])
        assert result.exit_code == 0
        assert "No tags found" in result.output

    def test_tags_list_with_data(self, cli_runner, populated_db):
        result = cli_runner.invoke(main, ["tags", "list"])
        assert result.exit_code == 0
        assert "mobile" in result.output
        assert "ios" in result.output

    def test_tags_add(self, cli_runner, populated_db):
        result = cli_runner.invoke(main, ["tags", "add", "proj-gamma", "new-tag", "--no-sync"])
        assert result.exit_code == 0
        assert "Added tag" in result.output
        assert "new-tag" in result.output

    def test_tags_add_project_not_found(self, cli_runner, populated_db):
        result = cli_runner.invoke(main, ["tags", "add", "nonexistent", "tag1", "--no-sync"])
        assert result.exit_code == 0
        assert "not found" in result.output

    def test_tags_remove(self, cli_runner, populated_db):
        result = cli_runner.invoke(main, ["tags", "remove", "proj-alpha", "ios", "--no-sync"])
        assert result.exit_code == 0
        assert "Removed tag" in result.output

    def test_tags_remove_not_present(self, cli_runner, populated_db):
        result = cli_runner.invoke(main, ["tags", "remove", "proj-alpha", "nonexistent", "--no-sync"])
        assert result.exit_code == 0
        assert "not on" in result.output

    def test_tags_remove_project_not_found(self, cli_runner, populated_db):
        result = cli_runner.invoke(main, ["tags", "remove", "nonexistent", "tag1", "--no-sync"])
        assert result.exit_code == 0
        assert "not found" in result.output

    def test_tags_bulk_by_names(self, cli_runner, populated_db):
        result = cli_runner.invoke(main, [
            "tags", "bulk", "web-tag", "proj-alpha", "proj-gamma", "--no-sync"
        ])
        assert result.exit_code == 0
        assert "Applied tag" in result.output

    def test_tags_bulk_by_filter(self, cli_runner, populated_db):
        result = cli_runner.invoke(main, [
            "tags", "bulk", "client-tag", "--filter", "type:client", "--no-sync"
        ])
        assert result.exit_code == 0
        assert "Applied tag" in result.output

    def test_tags_bulk_no_args(self, cli_runner, populated_db):
        result = cli_runner.invoke(main, ["tags", "bulk", "some-tag", "--no-sync"])
        assert result.exit_code == 0
        assert "Specify" in result.output

    def test_tags_add_persists(self, cli_runner, populated_db):
        """Verify that adding a tag persists to DB."""
        cli_runner.invoke(main, ["tags", "add", "proj-gamma", "persist-test", "--no-sync"])
        # Check in DB
        session = get_session()
        p = session.query(Project).filter_by(name="proj-gamma").first()
        assert "persist-test" in p.tags_list
        session.close()


# ── CLI Digest Commands ────────────────────────────────────────────────────


class TestDigestCLI:
    """Tests for pm digest CLI command."""

    def test_digest_default(self, cli_runner, db_with_history):
        result = cli_runner.invoke(main, ["digest"])
        assert result.exit_code == 0
        # Should show either activity table or "No activity"
        assert "Activity" in result.output or "No activity" in result.output

    def test_digest_by_day(self, cli_runner, db_with_history):
        result = cli_runner.invoke(main, ["digest", "--by-day"])
        assert result.exit_code == 0
        assert "Activity" in result.output or "No activity" in result.output

    def test_digest_custom_range(self, cli_runner, db_with_history):
        # Use a range that covers the test history data (past 90 days)
        start = (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d")
        end = (datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%d")
        result = cli_runner.invoke(main, ["digest", "-s", start, "-e", end])
        assert result.exit_code == 0
        assert "Activity" in result.output

    def test_digest_with_client_filter(self, cli_runner, db_with_history):
        start = (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d")
        end = (datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%d")
        result = cli_runner.invoke(main, ["digest", "-s", start, "-e", end, "--client", "Acme"])
        assert result.exit_code == 0

    def test_digest_empty_range(self, cli_runner, db_with_history):
        result = cli_runner.invoke(main, ["digest", "-s", "2099-01-01", "-e", "2099-12-31"])
        assert result.exit_code == 0
        assert "No activity" in result.output


# ── CLI Stale Commands ─────────────────────────────────────────────────────


class TestStaleCLI:
    """Tests for pm stale CLI command."""

    def test_stale_default(self, cli_runner, populated_db):
        result = cli_runner.invoke(main, ["stale"])
        assert result.exit_code == 0
        # proj-beta is stale (60 days), should appear
        assert "proj-beta" in result.output

    def test_stale_excludes_archived(self, cli_runner, populated_db):
        result = cli_runner.invoke(main, ["stale"])
        assert result.exit_code == 0
        assert "proj-archived" not in result.output

    def test_stale_excludes_someday(self, cli_runner, populated_db):
        result = cli_runner.invoke(main, ["stale"])
        assert result.exit_code == 0
        assert "proj-someday" not in result.output

    def test_stale_custom_days(self, cli_runner, populated_db):
        # With threshold of 90 days, proj-beta (60 days) should NOT be stale
        result = cli_runner.invoke(main, ["stale", "--days", "90"])
        assert result.exit_code == 0
        assert "proj-beta" not in result.output or "No stale" in result.output

    def test_stale_low_threshold_captures_more(self, cli_runner, populated_db):
        # With 1-day threshold, most projects should be stale except very recent
        result = cli_runner.invoke(main, ["stale", "--days", "1"])
        assert result.exit_code == 0
        # proj-beta and proj-alpha (2 days) should both be stale
        assert "proj-beta" in result.output

    @patch("pm.cli._sync_project")
    def test_stale_action_archive(self, mock_sync, cli_runner, populated_db):
        """Test stale --action with archive choice."""
        result = cli_runner.invoke(
            main, ["stale", "--action"],
            input="1\nNo longer needed\ns\n"  # archive first, skip rest
        )
        assert result.exit_code == 0
        assert "Archived" in result.output

    def test_stale_action_skip(self, cli_runner, populated_db):
        """Test stale --action with skip choice."""
        result = cli_runner.invoke(
            main, ["stale", "--action"],
            input="s\n"
        )
        assert result.exit_code == 0

    @patch("pm.cli._sync_project")
    def test_stale_action_move_forward(self, mock_sync, cli_runner, populated_db):
        """Test stale --action with move forward choice."""
        result = cli_runner.invoke(
            main, ["stale", "--action"],
            input="2\nFinish the refactoring\n2\ns\n"
        )
        assert result.exit_code == 0
        assert "Updated" in result.output

    @patch("pm.cli._sync_project")
    def test_stale_action_pivot(self, mock_sync, cli_runner, populated_db):
        """Test stale --action with pivot choice."""
        result = cli_runner.invoke(
            main, ["stale", "--action"],
            input="3\nSwitch to new approach\ns\n"
        )
        assert result.exit_code == 0
        assert "Updated notes" in result.output


# ── CLI Run Prompt Commands ────────────────────────────────────────────────


class TestRunPromptCLI:
    """Tests for pm run CLI command."""

    def test_run_project_not_found(self, cli_runner, populated_db):
        result = cli_runner.invoke(main, ["run", "nonexistent", "hello"])
        assert result.exit_code == 0
        assert "not found" in result.output

    @patch("pm.cli.subprocess.run")
    def test_run_success(self, mock_run, cli_runner, populated_db, temp_dir):
        """Test successful prompt run."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Here is the architecture summary...",
            stderr="",
        )
        result = cli_runner.invoke(main, ["run", "proj-alpha", "Summarize the architecture"])
        assert result.exit_code == 0
        assert "Running prompt" in result.output
        assert "Transcript saved" in result.output

    @patch("pm.cli.subprocess.run")
    def test_run_error(self, mock_run, cli_runner, populated_db):
        """Test prompt run with error."""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Something went wrong",
        )
        result = cli_runner.invoke(main, ["run", "proj-alpha", "Do something"])
        assert result.exit_code == 0
        assert "Error" in result.output or "Transcript saved" in result.output

    @patch("pm.cli.subprocess.run")
    def test_run_timeout(self, mock_run, cli_runner, populated_db):
        """Test prompt run with timeout."""
        import subprocess as real_subprocess
        mock_run.side_effect = real_subprocess.TimeoutExpired(cmd="claude", timeout=5)
        result = cli_runner.invoke(main, ["run", "proj-alpha", "Slow prompt", "--timeout", "5"])
        assert result.exit_code == 0
        assert "Timed out" in result.output or "Transcript saved" in result.output

    @patch("pm.cli.subprocess.run")
    def test_run_claude_not_found(self, mock_run, cli_runner, populated_db):
        """Test prompt run when claude CLI is not installed."""
        mock_run.side_effect = FileNotFoundError()
        result = cli_runner.invoke(main, ["run", "proj-alpha", "Hello"])
        assert result.exit_code == 0
        assert "not found" in result.output

    @patch("pm.cli.subprocess.run")
    def test_run_creates_transcript(self, mock_run, cli_runner, populated_db, temp_dir):
        """Test that transcript file is created."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Result text",
            stderr="",
        )
        result = cli_runner.invoke(main, ["run", "proj-alpha", "Test prompt"])
        assert "Transcript saved" in result.output

    @patch("pm.cli.subprocess.run")
    def test_run_custom_budget(self, mock_run, cli_runner, populated_db):
        """Test custom budget parameter."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="Result", stderr=""
        )
        result = cli_runner.invoke(main, [
            "run", "proj-alpha", "Test", "--budget", "1.00"
        ])
        assert result.exit_code == 0
        assert "$1.00" in result.output

    @patch("pm.cli.subprocess.run")
    def test_run_custom_tools(self, mock_run, cli_runner, populated_db):
        """Test custom tools parameter."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="Result", stderr=""
        )
        result = cli_runner.invoke(main, [
            "run", "proj-alpha", "Test", "--tools", "Read,Glob,WebSearch"
        ])
        assert result.exit_code == 0
        assert "Read, Glob, WebSearch" in result.output


# ── CLI Transcripts Command ────────────────────────────────────────────────


class TestTranscriptsCLI:
    """Tests for pm transcripts CLI command."""

    def test_transcripts_no_dir(self, cli_runner, isolated_database):
        result = cli_runner.invoke(main, ["transcripts"])
        assert result.exit_code == 0
        assert "No transcripts" in result.output or "Transcript" in result.output

    def test_transcripts_with_files(self, cli_runner, populated_db, temp_dir):
        """Test transcripts when files exist."""
        import shutil

        transcript_dir = Path(__file__).parent.parent / "transcripts" / "proj-alpha"
        transcript_dir.mkdir(parents=True, exist_ok=True)
        transcript_file = transcript_dir / "20260201-120000.md"
        transcript_file.write_text(
            "# Prompt Run: proj-alpha\n\n"
            "- **Status:** success\n"
            "- **Duration:** 5.0s\n"
        )

        try:
            result = cli_runner.invoke(main, ["transcripts"])
            assert result.exit_code == 0
        finally:
            shutil.rmtree(transcript_dir, ignore_errors=True)


# ── Tag + Stale Integration ────────────────────────────────────────────────


class TestIntegration:
    """Integration tests combining multiple features."""

    def test_tag_then_list(self, cli_runner, populated_db):
        """Add a tag then verify it appears in list."""
        cli_runner.invoke(main, ["tags", "add", "proj-gamma", "integration-test", "--no-sync"])
        result = cli_runner.invoke(main, ["tags", "list"])
        assert "integration-test" in result.output

    def test_bulk_tag_then_list(self, cli_runner, populated_db):
        """Bulk add tags then verify counts."""
        cli_runner.invoke(main, [
            "tags", "bulk", "bulk-test", "proj-alpha", "proj-gamma", "--no-sync"
        ])
        result = cli_runner.invoke(main, ["tags", "list"])
        assert "bulk-test" in result.output

    @patch("pm.cli._sync_project")
    def test_stale_archive_removes_from_stale(self, mock_sync, cli_runner, populated_db):
        """Archive a stale project, then verify it no longer appears."""
        # Archive proj-beta via stale --action
        cli_runner.invoke(
            main, ["stale", "--action"],
            input="1\nDone with it\n"
        )
        # Check it's gone from stale list
        result = cli_runner.invoke(main, ["stale"])
        assert "proj-beta" not in result.output or "No stale" in result.output

    def test_digest_and_stale_no_conflict(self, cli_runner, db_with_history):
        """Run both digest and stale commands in sequence."""
        r1 = cli_runner.invoke(main, ["digest"])
        assert r1.exit_code == 0

        r2 = cli_runner.invoke(main, ["stale"])
        assert r2.exit_code == 0
