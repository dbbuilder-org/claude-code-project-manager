"""Per-project agent memory: reads/writes docs/AGENT-CONTEXT.md.

Each project can have a persistent context file that agents read before
assessing (to avoid repeating work) and append to after executing (to
record what was done and learned).

File format:
    ---
    last_run: 2026-04-10T02:00:00
    runs: 5
    total_cost_usd: 1.25
    ---

    ## What I've Done
    - 2026-04-10: Fixed failing tests ...

    ## What I've Learned
    - Uses SQLAlchemy with migration system in models.py

    ## Don't Repeat
    - Already generated ROADMAP.md on 2026-04-09 — still current
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


MEMORY_FILENAME = "docs/AGENT-CONTEXT.md"
_DATE_FMT = "%Y-%m-%dT%H:%M:%S"


@dataclass
class AgentMemory:
    """Parsed content of a project's AGENT-CONTEXT.md file."""
    last_run: Optional[datetime] = None
    runs: int = 0
    total_cost_usd: float = 0.0

    done: list[str] = field(default_factory=list)       # What the agent has done
    learned: list[str] = field(default_factory=list)    # Observations about the codebase
    dont_repeat: list[str] = field(default_factory=list)  # Actions to skip

    # Raw notes section (anything not in recognised sections)
    extra: str = ""

    def is_empty(self) -> bool:
        return not self.done and not self.learned and not self.dont_repeat

    def to_context_block(self) -> str:
        """Render a concise context block for inclusion in the assess prompt."""
        if self.is_empty():
            return ""

        lines = ["=== Agent Memory ==="]

        if self.done:
            lines.append("Previously done:")
            for item in self.done[-10:]:   # Last 10 entries
                lines.append(f"  • {item}")

        if self.learned:
            lines.append("Known about this codebase:")
            for item in self.learned[-8:]:
                lines.append(f"  • {item}")

        if self.dont_repeat:
            lines.append("Do NOT repeat:")
            for item in self.dont_repeat[-5:]:
                lines.append(f"  • {item}")

        if self.runs:
            lines.append(f"(Total agent runs: {self.runs}, cost: ${self.total_cost_usd:.2f})")

        lines.append("=== End Memory ===")
        return "\n".join(lines)


def read_memory(project_path: Path) -> AgentMemory:
    """Read AGENT-CONTEXT.md from a project directory.

    Returns an empty AgentMemory if the file doesn't exist or can't be parsed.
    """
    mem_file = project_path / MEMORY_FILENAME
    if not mem_file.exists():
        return AgentMemory()

    try:
        content = mem_file.read_text()
    except Exception:
        return AgentMemory()

    return _parse_memory(content)


def append_run(
    project_path: Path,
    action_summary: str,
    learned: Optional[list[str]] = None,
    dont_repeat: Optional[list[str]] = None,
    cost_usd: float = 0.0,
) -> bool:
    """Append a completed run to AGENT-CONTEXT.md.

    Creates the file (and docs/ directory) if it doesn't exist.

    Args:
        project_path: Project root directory.
        action_summary: One-line summary of what the agent did.
        learned: Optional new observations about the codebase.
        dont_repeat: Optional items that should not be re-done.
        cost_usd: Cost of this run in USD.

    Returns:
        True if the file was written successfully.
    """
    mem = read_memory(project_path)

    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    mem.last_run = now
    mem.runs += 1
    mem.total_cost_usd = round(mem.total_cost_usd + cost_usd, 4)
    mem.done.append(f"{date_str}: {action_summary}")

    if learned:
        for item in learned:
            if item and item not in mem.learned:
                mem.learned.append(item)

    if dont_repeat:
        for item in dont_repeat:
            if item and item not in mem.dont_repeat:
                mem.dont_repeat.append(item)

    return _write_memory(project_path, mem)


def clear_memory(project_path: Path) -> bool:
    """Delete AGENT-CONTEXT.md for a project.

    Returns True if deleted (or didn't exist), False on error.
    """
    mem_file = project_path / MEMORY_FILENAME
    try:
        mem_file.unlink(missing_ok=True)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_memory(content: str) -> AgentMemory:
    mem = AgentMemory()

    # Extract YAML frontmatter
    fm_match = re.match(r'^---\s*\n(.*?)\n---\s*\n?(.*)', content, re.DOTALL)
    if fm_match:
        yaml_str = fm_match.group(1)
        body = fm_match.group(2)

        for line in yaml_str.splitlines():
            line = line.strip()
            if not line:
                continue
            if ':' not in line:
                continue
            key, _, val = line.partition(':')
            key = key.strip().lower()
            val = val.strip()

            if key == 'last_run':
                try:
                    mem.last_run = datetime.strptime(val, _DATE_FMT)
                except ValueError:
                    pass
            elif key == 'runs':
                try:
                    mem.runs = int(val)
                except ValueError:
                    pass
            elif key == 'total_cost_usd':
                try:
                    mem.total_cost_usd = float(val)
                except ValueError:
                    pass
    else:
        body = content

    # Parse sections
    current_section = None
    extra_lines = []

    for line in body.splitlines():
        stripped = line.strip()
        header = stripped.lower()

        if header in ("## what i've done", "## what i've done"):
            current_section = "done"
        elif header == "## what i've learned":
            current_section = "learned"
        elif header == "## don't repeat":
            current_section = "dont_repeat"
        elif stripped.startswith("## "):
            current_section = "extra"
        elif stripped.startswith("- ") or stripped.startswith("• "):
            item = stripped.lstrip("-• ").strip()
            if item:
                if current_section == "done":
                    mem.done.append(item)
                elif current_section == "learned":
                    mem.learned.append(item)
                elif current_section == "dont_repeat":
                    mem.dont_repeat.append(item)
                else:
                    extra_lines.append(line)
        elif current_section == "extra" and stripped:
            extra_lines.append(line)

    mem.extra = "\n".join(extra_lines).strip()
    return mem


def _write_memory(project_path: Path, mem: AgentMemory) -> bool:
    """Write AgentMemory to docs/AGENT-CONTEXT.md atomically."""
    mem_file = project_path / MEMORY_FILENAME
    tmp = mem_file.with_suffix('.tmp')

    # Ensure docs/ directory exists
    try:
        mem_file.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        return False

    lines = ['---']
    if mem.last_run:
        lines.append(f"last_run: {mem.last_run.strftime(_DATE_FMT)}")
    lines.append(f"runs: {mem.runs}")
    lines.append(f"total_cost_usd: {mem.total_cost_usd}")
    lines.append('---')
    lines.append('')

    lines.append("## What I've Done")
    for item in mem.done:
        lines.append(f"- {item}")
    lines.append('')

    lines.append("## What I've Learned")
    for item in mem.learned:
        lines.append(f"- {item}")
    lines.append('')

    lines.append("## Don't Repeat")
    for item in mem.dont_repeat:
        lines.append(f"- {item}")
    lines.append('')

    if mem.extra:
        lines.append(mem.extra)
        lines.append('')

    content = '\n'.join(lines)

    import os
    try:
        tmp.write_text(content)
        os.replace(tmp, mem_file)
        return True
    except Exception:
        tmp.unlink(missing_ok=True)
        return False
