"""Tests for pm triage and pm agent costs commands."""

import json
import pytest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

from click.testing import CliRunner

from pm.cli import main
from pm.database.models import Project, AgentRun, get_session


@pytest.fixture
def cli_runner():
    return CliRunner()


@pytest.fixture
def decision_db(isolated_database):
    """DB with projects: some have pending decisions, some don't."""
    session = get_session()
    projects = [
        Project(
            id="/test/decision-a", path="/test/decision-a", name="decision-a",
            project_type="python", has_pending_decision=True, priority=2,
            archived=False,
        ),
        Project(
            id="/test/decision-b", path="/test/decision-b", name="decision-b",
            project_type="node", has_pending_decision=True, priority=3,
            archived=False,
        ),
        Project(
            id="/test/no-decision", path="/test/no-decision", name="no-decision",
            project_type="python", has_pending_decision=False, priority=3,
            archived=False,
        ),
        Project(
            id="/test/archived-dec", path="/test/archived-dec", name="archived-dec",
            project_type="python", has_pending_decision=True, archived=True,
        ),
    ]
    for p in projects:
        session.add(p)
    session.commit()
    session.close()
    return isolated_database


@pytest.fixture
def costs_db(isolated_database):
    """DB with projects and AgentRun records."""
    session = get_session()
    p = Project(
        id="/test/cost-proj", path="/test/cost-proj", name="cost-proj",
        project_type="python", client_name="Acme",
    )
    session.add(p)
    session.flush()

    now = datetime.utcnow()
    for i in range(3):
        run = AgentRun(
            project_id=p.id,
            started_at=now - timedelta(days=i),
            completed_at=now - timedelta(days=i) + timedelta(seconds=120),
            duration_secs=120.0,
            confidence=85,
            proposed_action="Fix tests",
            risk_level="safe",
            status="success",
            cost_usd=0.25,
        )
        session.add(run)
    session.commit()
    session.close()
    return isolated_database


# ---------------------------------------------------------------------------
# pm triage
# ---------------------------------------------------------------------------

class TestTriageCommand:
    def test_triage_no_decisions_empty_message(self, cli_runner, isolated_database):
        result = cli_runner.invoke(main, ["triage"])
        assert result.exit_code == 0
        assert "No projects" in result.output

    def test_triage_dry_run_lists_projects(self, cli_runner, decision_db):
        result = cli_runner.invoke(main, ["triage", "--dry-run"])
        assert result.exit_code == 0
        assert "decision-a" in result.output
        assert "decision-b" in result.output

    def test_triage_dry_run_excludes_archived(self, cli_runner, decision_db):
        result = cli_runner.invoke(main, ["triage", "--dry-run"])
        assert "archived-dec" not in result.output

    def test_triage_dry_run_excludes_no_decision(self, cli_runner, decision_db):
        result = cli_runner.invoke(main, ["triage", "--dry-run"])
        assert "no-decision" not in result.output

    @patch("pm.cli.subprocess.run")
    def test_triage_parses_json_recommendation(self, mock_run, cli_runner, decision_db):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "decision_summary": "Choose between PostgreSQL or SQLite",
                "recommended_option": "Option A",
                "recommendation": "PostgreSQL is the right choice for this workload.",
                "confidence": 82,
                "caveats": "",
            }),
            stderr="",
        )
        result = cli_runner.invoke(main, ["triage", "--limit", "1"])
        assert result.exit_code == 0
        assert "Option A" in result.output
        assert "82" in result.output

    @patch("pm.cli.subprocess.run")
    def test_triage_handles_timeout(self, mock_run, cli_runner, decision_db):
        import subprocess as sp
        mock_run.side_effect = sp.TimeoutExpired(cmd="claude", timeout=5)
        result = cli_runner.invoke(main, ["triage", "--limit", "1", "--timeout", "5"])
        assert result.exit_code == 0
        assert "Timed out" in result.output

    @patch("pm.cli.subprocess.run")
    def test_triage_handles_claude_not_found(self, mock_run, cli_runner, decision_db):
        mock_run.side_effect = FileNotFoundError()
        result = cli_runner.invoke(main, ["triage", "--limit", "2"])
        assert result.exit_code == 0
        assert "not found" in result.output

    @patch("pm.cli.subprocess.run")
    def test_triage_unparseable_output_graceful(self, mock_run, cli_runner, decision_db):
        mock_run.return_value = MagicMock(returncode=0, stdout="No JSON here", stderr="")
        result = cli_runner.invoke(main, ["triage", "--limit", "1"])
        assert result.exit_code == 0
        assert "Could not parse" in result.output

    @patch("pm.cli._send_imessage_triage")
    @patch("pm.cli.subprocess.run")
    def test_triage_imessage_flag_sends(self, mock_run, mock_imsg, cli_runner, decision_db):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "decision_summary": "Pick a database",
                "recommended_option": "Option B",
                "recommendation": "SQLite is sufficient.",
                "confidence": 75,
                "caveats": "",
            }),
            stderr="",
        )
        result = cli_runner.invoke(main, ["triage", "--limit", "1", "--imessage"])
        assert result.exit_code == 0
        mock_imsg.assert_called_once()

    @patch("pm.cli._send_imessage_triage")
    @patch("pm.cli.subprocess.run")
    def test_triage_imessage_failure_non_fatal(self, mock_run, mock_imsg, cli_runner, decision_db):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "decision_summary": "Pick a database",
                "recommended_option": "Option A",
                "recommendation": "PostgreSQL wins.",
                "confidence": 80,
                "caveats": "",
            }),
            stderr="",
        )
        mock_imsg.side_effect = Exception("osascript failed")
        result = cli_runner.invoke(main, ["triage", "--limit", "1", "--imessage"])
        assert result.exit_code == 0
        assert "iMessage failed" in result.output

    def test_triage_limit_respected(self, cli_runner, decision_db):
        result = cli_runner.invoke(main, ["triage", "--dry-run", "--limit", "1"])
        # Only 1 project should appear
        lines_with_bullet = [l for l in result.output.splitlines() if "•" in l]
        assert len(lines_with_bullet) == 1


# ---------------------------------------------------------------------------
# pm agent costs
# ---------------------------------------------------------------------------

class TestAgentCostsCommand:
    def test_costs_no_runs_empty_message(self, cli_runner, isolated_database):
        result = cli_runner.invoke(main, ["agent", "costs"])
        assert result.exit_code == 0
        assert "No agent runs" in result.output

    def test_costs_shows_project_name(self, cli_runner, costs_db):
        result = cli_runner.invoke(main, ["agent", "costs"])
        assert result.exit_code == 0
        assert "cost-proj" in result.output

    def test_costs_shows_run_count(self, cli_runner, costs_db):
        result = cli_runner.invoke(main, ["agent", "costs"])
        assert "3" in result.output  # 3 runs

    def test_costs_shows_total_cost(self, cli_runner, costs_db):
        result = cli_runner.invoke(main, ["agent", "costs"])
        # 3 runs * $0.25 = $0.75
        assert "0.75" in result.output

    def test_costs_shows_client_name(self, cli_runner, costs_db):
        result = cli_runner.invoke(main, ["agent", "costs"])
        assert "Acme" in result.output

    def test_costs_respects_days_filter(self, cli_runner, costs_db):
        # Filter to 0 days back — should find nothing
        result = cli_runner.invoke(main, ["agent", "costs", "--days", "0"])
        assert result.exit_code == 0
        # Either empty message or empty table
        assert "No agent runs" in result.output or "cost-proj" not in result.output

    def test_costs_shows_totals_line(self, cli_runner, costs_db):
        result = cli_runner.invoke(main, ["agent", "costs"])
        assert "Total:" in result.output

    def test_costs_budget_alert_threshold(self, isolated_database):
        """Weekly spend > $10 should show a warning."""
        session = get_session()
        p = Project(id="/test/big-spender", path="/test/big-spender", name="big-spender")
        session.add(p)
        session.flush()
        now = datetime.utcnow()
        # 7 days, $2/day = $14/week — exceeds $10 threshold
        for i in range(7):
            session.add(AgentRun(
                project_id=p.id,
                started_at=now - timedelta(days=i),
                duration_secs=120,
                status="success",
                cost_usd=2.0,
            ))
        session.commit()
        session.close()

        runner = CliRunner()
        result = runner.invoke(main, ["agent", "costs", "--days", "7"])
        assert "weekly spend" in result.output.lower() or "⚠" in result.output
