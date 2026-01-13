"""Generate context-aware continue prompts for Claude Code."""

from dataclasses import dataclass
from typing import Optional
from pathlib import Path
from enum import Enum

from ..scanner.parser import ProjectProgress, ItemStatus, DecisionPoint


class PromptMode(Enum):
    SIMPLE = "simple"  # Just resume
    CONTEXT = "context"  # Include parsed state
    DECISION = "decision"  # Surface decision points


@dataclass
class ContinuePrompt:
    """Generated continue prompt for a project."""
    mode: PromptMode
    command: str  # The actual command to run
    prompt_text: Optional[str] = None  # Text to send after resuming
    has_decision: bool = False
    decision: Optional[DecisionPoint] = None


class ContinuePromptGenerator:
    """Generates smart continue prompts based on project state."""

    def __init__(self):
        pass

    def generate(
        self,
        project_path: Path,
        project_name: str,
        progress: ProjectProgress,
        mode: PromptMode = PromptMode.CONTEXT
    ) -> ContinuePrompt:
        """Generate a continue prompt for a project."""

        # If there's a decision point, use decision mode
        if progress.has_pending_decision and progress.decisions:
            return self._generate_decision_prompt(project_path, project_name, progress)

        # Generate based on mode
        if mode == PromptMode.SIMPLE:
            return self._generate_simple(project_path)
        else:
            return self._generate_context(project_path, project_name, progress)

    def _generate_simple(self, project_path: Path) -> ContinuePrompt:
        """Generate a simple resume command."""
        return ContinuePrompt(
            mode=PromptMode.SIMPLE,
            command=f"cd {project_path} && claude --resume",
        )

    def _generate_context(
        self,
        project_path: Path,
        project_name: str,
        progress: ProjectProgress
    ) -> ContinuePrompt:
        """Generate a context-aware continue prompt."""
        parts = []

        # Project context
        parts.append(f"Continuing work on {project_name}.")

        # Current state
        if progress.current_phase:
            parts.append(f"Current phase: {progress.current_phase}")

        if progress.completion_pct is not None:
            parts.append(f"Progress: {progress.completion_pct:.0f}% complete")

        if progress.current_focus:
            parts.append(f"Focus: {progress.current_focus}")

        # Next action
        if progress.next_action:
            parts.append(f"\nNext action: {progress.next_action}")
        elif progress.next_steps:
            parts.append("\nNext steps:")
            for step in progress.next_steps[:3]:
                parts.append(f"  - {step}")

        # Pending items
        pending_items = [i for i in progress.items if i.status == ItemStatus.PENDING]
        in_progress_items = [i for i in progress.items if i.status == ItemStatus.IN_PROGRESS]

        if in_progress_items:
            parts.append("\nIn progress:")
            for item in in_progress_items[:3]:
                parts.append(f"  - {item.content}")

        # Reference files
        ref_files = []
        if progress.items:
            source_files = set(i.source_file for i in progress.items if i.source_file)
            ref_files.extend(source_files)

        if ref_files:
            parts.append(f"\nRelevant files: {', '.join(ref_files)}")

        prompt_text = "\n".join(parts)

        # Build command
        # Use -p for headless with prompt, or --resume for interactive
        command = f"cd {project_path} && claude --resume"

        return ContinuePrompt(
            mode=PromptMode.CONTEXT,
            command=command,
            prompt_text=prompt_text,
        )

    def _generate_decision_prompt(
        self,
        project_path: Path,
        project_name: str,
        progress: ProjectProgress
    ) -> ContinuePrompt:
        """Generate a prompt that surfaces a pending decision."""
        decision = progress.decisions[0]  # First decision

        parts = []
        parts.append(f"Continuing work on {project_name}.")
        parts.append(f"\n⚠️ DECISION REQUIRED: {decision.question}")
        parts.append("\nOptions:")
        for opt in decision.options:
            parts.append(f"  - {opt}")

        if decision.recommendation:
            parts.append(f"\n📌 Recommendation: {decision.recommendation}")

        parts.append("\nPlease confirm which option to proceed with, or provide your preference.")

        prompt_text = "\n".join(parts)

        return ContinuePrompt(
            mode=PromptMode.DECISION,
            command=f"cd {project_path} && claude --resume",
            prompt_text=prompt_text,
            has_decision=True,
            decision=decision,
        )

    def generate_batch_script(
        self,
        projects: list[tuple[Path, str, ProjectProgress]],
        parallel: int = 1
    ) -> str:
        """Generate a batch script to continue multiple projects."""
        lines = ["#!/bin/bash", "", "# Auto-generated continue script", ""]

        if parallel > 1:
            lines.append(f"# Running {len(projects)} projects with {parallel} parallel")
            lines.append("")

        for i, (path, name, progress) in enumerate(projects):
            prompt = self.generate(path, name, progress, PromptMode.CONTEXT)

            lines.append(f"# Project {i+1}: {name}")
            if prompt.prompt_text:
                # Escape for shell
                escaped = prompt.prompt_text.replace("'", "'\\''")
                lines.append(f"# Context: {progress.current_phase or 'N/A'}")

            if parallel > 1:
                lines.append(f"({prompt.command}) &")
                if (i + 1) % parallel == 0:
                    lines.append("wait")
            else:
                lines.append(prompt.command)

            lines.append("")

        if parallel > 1:
            lines.append("wait")
            lines.append('echo "All projects started"')

        return "\n".join(lines)


def generate_continue_prompt(
    project_path: Path,
    project_name: str,
    progress: ProjectProgress,
    mode: PromptMode = PromptMode.CONTEXT
) -> ContinuePrompt:
    """Convenience function to generate a continue prompt."""
    generator = ContinuePromptGenerator()
    return generator.generate(project_path, project_name, progress, mode)
