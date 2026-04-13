"""Agent runner: executes approved actions via headless Claude."""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .planner import AssessmentResult
from .memory import append_run

# Default tools for execution phase (broader than assess)
EXECUTE_TOOLS = ["Read", "Glob", "Grep", "Edit", "Write", "Bash"]

# Default execution budget
DEFAULT_BUDGET_USD = 1.00

# Default timeout for execution
DEFAULT_TIMEOUT_SECS = 300


@dataclass
class RunResult:
    """Result of an agent execution."""
    project_name: str
    project_path: str
    prompt: str
    status: str            # "success", "error", "timeout", "skipped"
    output: str
    duration_secs: float
    cost_usd: Optional[float] = None
    error: Optional[str] = None
    assessment: Optional[AssessmentResult] = None

    def to_dict(self) -> dict:
        return {
            "project_name": self.project_name,
            "project_path": self.project_path,
            "prompt": self.prompt[:200],
            "status": self.status,
            "output": self.output[:500],
            "duration_secs": self.duration_secs,
            "cost_usd": self.cost_usd,
            "error": self.error,
        }


class AgentRunner:
    """Runs headless Claude executions with configurable budget and tools."""

    def __init__(
        self,
        budget_usd: float = DEFAULT_BUDGET_USD,
        timeout_secs: int = DEFAULT_TIMEOUT_SECS,
        tools: Optional[list[str]] = None,
    ):
        self.budget_usd = budget_usd
        self.timeout_secs = timeout_secs
        self.tools = tools or EXECUTE_TOOLS

    def run(
        self,
        project_path: str,
        project_name: str,
        prompt: str,
        assessment: Optional[AssessmentResult] = None,
    ) -> RunResult:
        """Execute a prompt against a project using headless Claude.

        Args:
            project_path: Absolute path to project directory.
            project_name: Display name for the project.
            prompt: The prompt to execute.
            assessment: Optional assessment that led to this run.

        Returns:
            RunResult with status and output.
        """
        start = time.time()
        path = Path(project_path)

        cmd = [
            "claude",
            "--dangerously-skip-permissions",
            "--max-budget-usd", str(self.budget_usd),
            "--allowedTools", ",".join(self.tools),
            "-p", prompt,
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout_secs,
                cwd=str(path),
            )
            duration = time.time() - start

            if result.returncode == 0:
                # Persist what was done to project memory
                action_summary = (
                    assessment.proposed_action if assessment
                    else prompt[:120]
                )
                append_run(path, action_summary)

                return RunResult(
                    project_name=project_name,
                    project_path=project_path,
                    prompt=prompt,
                    status="success",
                    output=result.stdout,
                    duration_secs=duration,
                    assessment=assessment,
                )
            else:
                return RunResult(
                    project_name=project_name,
                    project_path=project_path,
                    prompt=prompt,
                    status="error",
                    output=result.stdout,
                    duration_secs=duration,
                    error=result.stderr[:500] if result.stderr else None,
                    assessment=assessment,
                )

        except subprocess.TimeoutExpired:
            return RunResult(
                project_name=project_name,
                project_path=project_path,
                prompt=prompt,
                status="timeout",
                output="",
                duration_secs=self.timeout_secs,
                error=f"Timed out after {self.timeout_secs}s",
                assessment=assessment,
            )
        except FileNotFoundError:
            return RunResult(
                project_name=project_name,
                project_path=project_path,
                prompt=prompt,
                status="error",
                output="",
                duration_secs=0,
                error="claude CLI not found — is it installed?",
                assessment=assessment,
            )
        except Exception as e:
            return RunResult(
                project_name=project_name,
                project_path=project_path,
                prompt=prompt,
                status="error",
                output="",
                duration_secs=time.time() - start,
                error=str(e),
                assessment=assessment,
            )
