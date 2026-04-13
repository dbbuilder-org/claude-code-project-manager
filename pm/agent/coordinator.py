"""Agent coordinator: orchestrates assess/execute/escalate across multiple projects.

Workflow:
1. For each project, run plan_project() (assess phase)
2. If should_auto_execute → run via AgentRunner
3. Otherwise → escalate via iMessage (or log if iMessage unavailable)
4. Record results in agent_runs table
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from .planner import AssessmentResult, plan_project
from .runner import AgentRunner, RunResult


# Maximum parallel projects to assess/run simultaneously
DEFAULT_MAX_WORKERS = 3

# Budget cap per project per coordinator run
DEFAULT_PROJECT_BUDGET = 1.00


@dataclass
class CoordinatorResult:
    """Summary of a coordinator run across multiple projects."""
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    assessments: list[AssessmentResult] = field(default_factory=list)
    executions: list[RunResult] = field(default_factory=list)
    escalations: list[AssessmentResult] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)

    @property
    def total_projects(self) -> int:
        return len(self.assessments)

    @property
    def auto_executed(self) -> int:
        return len([r for r in self.executions if r.status == "success"])

    @property
    def escalated(self) -> int:
        return len(self.escalations)

    def summary(self) -> str:
        duration = (
            (self.completed_at - self.started_at).total_seconds()
            if self.completed_at else 0
        )
        return (
            f"Coordinator run: {self.total_projects} projects assessed, "
            f"{self.auto_executed} auto-executed, "
            f"{self.escalated} escalated, "
            f"{len(self.errors)} errors "
            f"({duration:.0f}s)"
        )


class AgentCoordinator:
    """Orchestrates assess/execute/escalate for a set of projects."""

    def __init__(
        self,
        max_workers: int = DEFAULT_MAX_WORKERS,
        budget_per_project: float = DEFAULT_PROJECT_BUDGET,
        escalation_fn=None,
        dry_run: bool = False,
    ):
        """
        Args:
            max_workers: Max parallel projects processed simultaneously.
            budget_per_project: Max USD budget per project execution.
            escalation_fn: Callable(assessment) to notify user of blocked agents.
                           If None, escalations are logged only.
            dry_run: If True, assess but don't execute or escalate.
        """
        self.max_workers = max_workers
        self.budget_per_project = budget_per_project
        self.escalation_fn = escalation_fn
        self.dry_run = dry_run
        self._runner = AgentRunner(budget_usd=budget_per_project)

    def run(
        self,
        projects: list[dict],
        context_hint: Optional[str] = None,
    ) -> CoordinatorResult:
        """Run assess/execute/escalate for a list of projects.

        Args:
            projects: List of dicts with 'name' and 'path' keys.
            context_hint: Optional focus area hint passed to planner.

        Returns:
            CoordinatorResult summarizing all outcomes.
        """
        coord_result = CoordinatorResult()

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {
                pool.submit(
                    self._assess_and_act,
                    p["name"],
                    p["path"],
                    context_hint,
                ): p
                for p in projects
            }

            for future in as_completed(futures):
                project = futures[future]
                try:
                    assessment, run_result = future.result()
                    coord_result.assessments.append(assessment)
                    if run_result:
                        coord_result.executions.append(run_result)
                    elif not assessment.should_auto_execute and not self.dry_run:
                        coord_result.escalations.append(assessment)
                except Exception as e:
                    coord_result.errors.append({
                        "project": project.get("name"),
                        "error": str(e),
                    })

        coord_result.completed_at = datetime.utcnow()
        return coord_result

    def _assess_and_act(
        self,
        project_name: str,
        project_path: str,
        context_hint: Optional[str],
    ) -> tuple[AssessmentResult, Optional[RunResult]]:
        """Assess one project and either execute or escalate."""
        assessment = plan_project(project_path, project_name, context_hint)

        if self.dry_run:
            return assessment, None

        if assessment.should_auto_execute:
            run_result = self._runner.run(
                project_path=project_path,
                project_name=project_name,
                prompt=assessment.proposed_prompt,
                assessment=assessment,
            )
            return assessment, run_result

        # Needs escalation
        if self.escalation_fn:
            try:
                self.escalation_fn(assessment)
            except Exception:
                pass  # Escalation failure should not crash the coordinator

        return assessment, None
