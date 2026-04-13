"""Two-phase agent planner: Assess (read-only) then decide Execute or Escalate.

Phase 1 — Assess:
  Run Claude with read-only tools to understand project state.
  Returns confidence score (0–100) and proposed action.

Phase 2 — Execute or Escalate:
  confidence >= 80 + safe action  → execute autonomously
  otherwise                       → escalate via iMessage
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .memory import read_memory


# Tools allowed during the assess phase (read-only)
ASSESS_TOOLS = ["Read", "Glob", "Grep"]

# Maximum cost for the assess phase
ASSESS_BUDGET_USD = 0.25

# Confidence threshold for autonomous execution
AUTO_EXECUTE_THRESHOLD = 80


@dataclass
class AssessmentResult:
    """Result of an agent assessment phase."""
    project_name: str
    project_path: str
    confidence: int           # 0-100
    proposed_action: str      # human-readable description
    proposed_prompt: str      # the prompt to execute if approved
    reasoning: str            # why this action was chosen
    risk_level: str           # "safe", "moderate", "risky"
    duration_secs: float = 0.0
    raw_output: str = ""
    error: Optional[str] = None

    @property
    def should_auto_execute(self) -> bool:
        """True if confidence is high enough and risk is low enough for autonomous execution."""
        return (
            self.confidence >= AUTO_EXECUTE_THRESHOLD
            and self.risk_level == "safe"
            and self.error is None
        )

    def to_dict(self) -> dict:
        return {
            "project_name": self.project_name,
            "project_path": self.project_path,
            "confidence": self.confidence,
            "proposed_action": self.proposed_action,
            "proposed_prompt": self.proposed_prompt,
            "reasoning": self.reasoning,
            "risk_level": self.risk_level,
            "duration_secs": self.duration_secs,
            "error": self.error,
            "should_auto_execute": self.should_auto_execute,
        }


_ASSESS_SYSTEM_PROMPT = """\
You are an intelligent project manager assessing a software project.
Your job is to:
1. Read the project's current state (CLAUDE.md, TODO.md, PROGRESS.md, recent git log)
2. Identify the single most impactful next action
3. Return a JSON assessment

Output ONLY valid JSON in this exact format:
{
  "confidence": <integer 0-100>,
  "proposed_action": "<one-sentence description of the action>",
  "proposed_prompt": "<the exact prompt to run next>",
  "reasoning": "<2-3 sentences explaining why>",
  "risk_level": "<safe|moderate|risky>"
}

Risk level guidelines:
- safe: documentation, analysis, read-only operations, minor fixes
- moderate: refactoring, adding tests, non-breaking changes
- risky: schema changes, dependency upgrades, architecture changes

Be conservative with confidence. Only give 80+ if you are very sure this is the right action
and the codebase state is clear.
"""


def plan_project(
    project_path: str,
    project_name: str,
    context_hint: Optional[str] = None,
    timeout: int = 120,
) -> AssessmentResult:
    """Run the assess phase for a project.

    Uses read-only Claude tools to understand current state and propose next action.

    Args:
        project_path: Absolute path to the project directory.
        project_name: Display name for the project.
        context_hint: Optional hint about what kind of work to focus on.
        timeout: Seconds before giving up on the assess phase.

    Returns:
        AssessmentResult with confidence score and proposed action.
    """
    start = time.time()
    path = Path(project_path)

    focus = f"\nFocus area: {context_hint}" if context_hint else ""

    # Inject agent memory so the planner knows what's already been done
    memory = read_memory(path)
    memory_block = memory.to_context_block()
    memory_section = f"\n\n{memory_block}" if memory_block else ""

    user_prompt = (
        f"Assess this project and propose the next action.\n"
        f"Project: {project_name}\n"
        f"Path: {project_path}{focus}{memory_section}\n\n"
        f"Read CLAUDE.md, TODO.md, PROGRESS.md (if they exist), and run: "
        f"git log --oneline -10 (if git is available).\n"
        f"Return ONLY the JSON assessment."
    )

    cmd = [
        "claude",
        "--dangerously-skip-permissions",
        "--max-budget-usd", str(ASSESS_BUDGET_USD),
        "--allowedTools", ",".join(ASSESS_TOOLS),
        "--system-prompt", _ASSESS_SYSTEM_PROMPT,
        "-p", user_prompt,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(path),
        )
        raw = result.stdout.strip()
        duration = time.time() - start

        # Extract JSON from output (Claude may wrap it in markdown)
        json_str = _extract_json(raw)

        if not json_str:
            return AssessmentResult(
                project_name=project_name,
                project_path=project_path,
                confidence=0,
                proposed_action="Unable to parse assessment",
                proposed_prompt="",
                reasoning=f"Could not extract JSON from output: {raw[:200]}",
                risk_level="risky",
                duration_secs=duration,
                raw_output=raw,
                error="JSON parse failed",
            )

        data = json.loads(json_str)
        return AssessmentResult(
            project_name=project_name,
            project_path=project_path,
            confidence=int(data.get("confidence", 0)),
            proposed_action=data.get("proposed_action", ""),
            proposed_prompt=data.get("proposed_prompt", ""),
            reasoning=data.get("reasoning", ""),
            risk_level=data.get("risk_level", "risky"),
            duration_secs=duration,
            raw_output=raw,
        )

    except subprocess.TimeoutExpired:
        return AssessmentResult(
            project_name=project_name,
            project_path=project_path,
            confidence=0,
            proposed_action="Timed out",
            proposed_prompt="",
            reasoning=f"Assessment timed out after {timeout}s",
            risk_level="risky",
            duration_secs=timeout,
            error="timeout",
        )
    except FileNotFoundError:
        return AssessmentResult(
            project_name=project_name,
            project_path=project_path,
            confidence=0,
            proposed_action="Claude CLI not found",
            proposed_prompt="",
            reasoning="claude CLI not installed or not in PATH",
            risk_level="risky",
            duration_secs=0,
            error="claude not found",
        )
    except Exception as e:
        return AssessmentResult(
            project_name=project_name,
            project_path=project_path,
            confidence=0,
            proposed_action="Error",
            proposed_prompt="",
            reasoning=str(e),
            risk_level="risky",
            duration_secs=time.time() - start,
            error=str(e),
        )


def _extract_json(text: str) -> Optional[str]:
    """Extract JSON object from text that may contain markdown fencing."""
    import re
    # Try to find a JSON block
    match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if match:
        return match.group(1)
    # Try raw JSON object
    match = re.search(r'(\{[^{}]*"confidence"[^{}]*\})', text, re.DOTALL)
    if match:
        return match.group(1)
    return None
