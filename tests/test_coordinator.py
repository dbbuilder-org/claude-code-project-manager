"""Tests for pm/agent/coordinator.py — batch assess/execute orchestration."""

import pytest
from unittest.mock import patch, MagicMock

from pm.agent.coordinator import AgentCoordinator, CoordinatorResult
from pm.agent.planner import AssessmentResult
from pm.agent.runner import RunResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_assessment(project_name="proj", confidence=85, risk_level="safe", **kwargs):
    """confidence=85 + risk_level='safe' → should_auto_execute=True."""
    defaults = dict(
        project_name=project_name,
        project_path=f"/tmp/{project_name}",
        confidence=confidence,
        risk_level=risk_level,
        proposed_action="run tests",
        proposed_prompt="pytest",
        reasoning="tests look fine",
        error=None,
    )
    defaults.update(kwargs)
    return AssessmentResult(**defaults)


def make_run_result(status="success", project_name="proj"):
    return RunResult(
        project_name=project_name,
        project_path=f"/tmp/{project_name}",
        prompt="pytest",
        status=status,
        cost_usd=0.05,
        duration_secs=10.0,
        output="done",
    )


PROJECTS = [
    {"name": "proj-a", "path": "/tmp/proj-a"},
    {"name": "proj-b", "path": "/tmp/proj-b"},
    {"name": "proj-c", "path": "/tmp/proj-c"},
]


# ---------------------------------------------------------------------------
# CoordinatorResult properties
# ---------------------------------------------------------------------------

class TestCoordinatorResult:
    def test_total_projects(self):
        r = CoordinatorResult()
        r.assessments = [make_assessment(), make_assessment()]
        assert r.total_projects == 2

    def test_auto_executed_counts_successes(self):
        r = CoordinatorResult()
        r.executions = [
            make_run_result("success"),
            make_run_result("error"),
            make_run_result("success"),
        ]
        assert r.auto_executed == 2

    def test_escalated(self):
        r = CoordinatorResult()
        r.escalations = [make_assessment(), make_assessment()]
        assert r.escalated == 2

    def test_summary_contains_key_numbers(self):
        r = CoordinatorResult()
        r.assessments = [make_assessment()]
        r.executions = [make_run_result()]
        from datetime import datetime, timezone
        r.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        summary = r.summary()
        assert "1 projects assessed" in summary
        assert "1 auto-executed" in summary


# ---------------------------------------------------------------------------
# AgentCoordinator.run — basic behavior
# ---------------------------------------------------------------------------

class TestCoordinatorRun:
    @patch("pm.agent.coordinator.plan_project")
    @patch.object(AgentCoordinator, "_assess_and_act")
    def test_returns_coordinator_result(self, mock_act, mock_plan):
        mock_act.return_value = (make_assessment(), make_run_result())
        coord = AgentCoordinator(max_workers=1)
        result = coord.run([PROJECTS[0]])
        assert isinstance(result, CoordinatorResult)
        assert result.completed_at is not None

    @patch.object(AgentCoordinator, "_assess_and_act")
    def test_processes_all_projects(self, mock_act):
        mock_act.return_value = (make_assessment(), make_run_result())
        coord = AgentCoordinator(max_workers=2)
        result = coord.run(PROJECTS)
        assert len(result.assessments) == 3

    @patch.object(AgentCoordinator, "_assess_and_act")
    def test_collects_executions(self, mock_act):
        mock_act.return_value = (make_assessment(), make_run_result())
        coord = AgentCoordinator(max_workers=1)
        result = coord.run(PROJECTS[:2])
        assert len(result.executions) == 2

    @patch.object(AgentCoordinator, "_assess_and_act")
    def test_records_errors(self, mock_act):
        mock_act.side_effect = RuntimeError("subprocess failed")
        coord = AgentCoordinator(max_workers=1)
        result = coord.run([PROJECTS[0]])
        assert len(result.errors) == 1
        assert result.errors[0]["project"] == "proj-a"

    @patch.object(AgentCoordinator, "_assess_and_act")
    def test_partial_failure_continues(self, mock_act):
        """One project failing should not prevent the others from running."""
        def act_side_effect(name, path, hint):
            if name == "proj-b":
                raise RuntimeError("failed")
            return make_assessment(project_name=name), make_run_result(project_name=name)

        mock_act.side_effect = act_side_effect
        coord = AgentCoordinator(max_workers=1)
        result = coord.run(PROJECTS)
        assert len(result.assessments) == 2  # proj-a and proj-c succeeded
        assert len(result.errors) == 1
        assert result.errors[0]["project"] == "proj-b"


# ---------------------------------------------------------------------------
# AgentCoordinator._assess_and_act
# ---------------------------------------------------------------------------

class TestAssessAndAct:
    @patch("pm.agent.coordinator.plan_project")
    def test_dry_run_does_not_execute(self, mock_plan):
        mock_plan.return_value = make_assessment()
        coord = AgentCoordinator(dry_run=True)
        with patch.object(coord._runner, "run") as mock_run:
            assessment, run_result = coord._assess_and_act("proj-a", "/tmp/proj-a", None)
            mock_run.assert_not_called()
        assert run_result is None

    @patch("pm.agent.coordinator.plan_project")
    def test_auto_execute_calls_runner(self, mock_plan):
        mock_plan.return_value = make_assessment()
        coord = AgentCoordinator(dry_run=False)
        with patch.object(coord._runner, "run", return_value=make_run_result()) as mock_run:
            assessment, run_result = coord._assess_and_act("proj-a", "/tmp/proj-a", None)
            mock_run.assert_called_once()
        assert run_result is not None

    @patch("pm.agent.coordinator.plan_project")
    def test_low_confidence_does_not_execute(self, mock_plan):
        mock_plan.return_value = make_assessment(confidence=50)
        coord = AgentCoordinator(dry_run=False)
        with patch.object(coord._runner, "run") as mock_run:
            assessment, run_result = coord._assess_and_act("proj-a", "/tmp/proj-a", None)
            mock_run.assert_not_called()
        assert run_result is None

    @patch("pm.agent.coordinator.plan_project")
    def test_escalation_fn_called_when_not_auto_execute(self, mock_plan):
        mock_plan.return_value = make_assessment(project_name="proj-a", confidence=50)
        escalations = []
        coord = AgentCoordinator(escalation_fn=escalations.append)
        coord._assess_and_act("proj-a", "/tmp/proj-a", None)
        assert len(escalations) == 1
        assert escalations[0].project_name == "proj-a"

    @patch("pm.agent.coordinator.plan_project")
    def test_escalation_failure_does_not_crash(self, mock_plan):
        mock_plan.return_value = make_assessment(confidence=50)
        def bad_escalation(a):
            raise RuntimeError("iMessage down")
        coord = AgentCoordinator(escalation_fn=bad_escalation)
        # Should not raise
        assessment, run_result = coord._assess_and_act("proj-a", "/tmp/proj-a", None)
        assert run_result is None

    @patch("pm.agent.coordinator.plan_project")
    def test_context_hint_passed_to_planner(self, mock_plan):
        mock_plan.return_value = make_assessment()
        coord = AgentCoordinator(dry_run=True)
        coord._assess_and_act("proj-a", "/tmp/proj-a", "fix failing tests")
        mock_plan.assert_called_once_with("/tmp/proj-a", "proj-a", "fix failing tests")
