"""Progress document parser - extracts state from TODO.md, PROGRESS.md, etc."""

import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class ItemStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    BLOCKED = "blocked"


class ItemPriority(Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class ProgressItem:
    """A single task/item from a progress document."""
    content: str
    status: ItemStatus
    priority: Optional[ItemPriority] = None
    source_file: Optional[str] = None
    line_number: Optional[int] = None
    item_type: str = "task"  # 'task', 'phase', 'milestone', 'decision'


@dataclass
class DecisionPoint:
    """A pending decision from the progress document."""
    question: str
    options: list[str] = field(default_factory=list)
    recommendation: Optional[str] = None
    source_file: Optional[str] = None


@dataclass
class ProjectProgress:
    """Parsed progress state for a project."""
    # Overall progress
    completion_pct: Optional[float] = None
    total_items: int = 0
    completed_items: int = 0

    # Current state
    current_phase: Optional[str] = None
    current_status: Optional[str] = None
    current_focus: Optional[str] = None
    last_updated: Optional[str] = None

    # Next actions
    next_action: Optional[str] = None
    next_steps: list[str] = field(default_factory=list)

    # Items
    items: list[ProgressItem] = field(default_factory=list)

    # Decision points
    decisions: list[DecisionPoint] = field(default_factory=list)
    has_pending_decision: bool = False

    # Raw sections
    sections: dict[str, str] = field(default_factory=dict)


class ProgressParser:
    """Parser for progress documents (TODO.md, PROGRESS.md, etc.)."""

    # Patterns for extracting progress info
    COMPLETION_PATTERNS = [
        r'(\d+)\s*(?:of|/)\s*(\d+).*(?:complete|done|finished)',  # "6 of 8 complete"
        r'(?:complete|done|finished).*?(\d+)\s*(?:of|/)\s*(\d+)',  # "complete: 6/8"
        r'(\d+(?:\.\d+)?)\s*%',  # "75%"
    ]

    PHASE_PATTERNS = [
        r'(?:current\s+)?phase[:\s]+([^\n]+)',
        r'##\s*(?:phase\s+)?(\d+(?:\.\d+)?[:\s]+[^\n]+)',
        r'\*\*(?:current\s+)?phase\*\*[:\s]+([^\n]+)',
    ]

    STATUS_PATTERNS = [
        r'\*\*status\*\*[:\s]+([^\n]+)',
        r'status[:\s]+([^\n]+)',
    ]

    FOCUS_PATTERNS = [
        r'\*\*current\s+focus\*\*[:\s]+([^\n]+)',
        r'current\s+focus[:\s]+([^\n]+)',
    ]

    NEXT_STEP_PATTERNS = [
        r'(?:next\s+step|immediate\s+next)[:\s]+([^\n]+)',
        r'\*\*next\s+step\*\*[:\s]+([^\n]+)',
    ]

    UPDATED_PATTERNS = [
        r'\*\*last\s+updated\*\*[:\s]+([^\n]+)',
        r'last\s+updated[:\s]+([^\n]+)',
    ]

    # Status indicators in text
    STATUS_INDICATORS = {
        '✅': ItemStatus.COMPLETE,
        '✓': ItemStatus.COMPLETE,
        '☑': ItemStatus.COMPLETE,
        'COMPLETE': ItemStatus.COMPLETE,
        '⏳': ItemStatus.IN_PROGRESS,
        '🔄': ItemStatus.IN_PROGRESS,
        'IN PROGRESS': ItemStatus.IN_PROGRESS,
        'IN_PROGRESS': ItemStatus.IN_PROGRESS,
        '⬜': ItemStatus.PENDING,
        '⏸️': ItemStatus.PENDING,
        'NOT STARTED': ItemStatus.PENDING,
        'PENDING': ItemStatus.PENDING,
        '🔴': ItemStatus.BLOCKED,
        '❌': ItemStatus.BLOCKED,
        'BLOCKED': ItemStatus.BLOCKED,
    }

    PRIORITY_INDICATORS = {
        'CRITICAL': ItemPriority.CRITICAL,
        'HIGH': ItemPriority.HIGH,
        'MEDIUM': ItemPriority.MEDIUM,
        'LOW': ItemPriority.LOW,
        'IMMEDIATE': ItemPriority.CRITICAL,
    }

    def __init__(self):
        pass

    def parse_file(self, file_path: Path) -> ProjectProgress:
        """Parse a single progress file."""
        if not file_path.exists():
            return ProjectProgress()

        content = file_path.read_text(encoding='utf-8', errors='ignore')
        return self.parse_content(content, source_file=file_path.name)

    def parse_content(self, content: str, source_file: Optional[str] = None) -> ProjectProgress:
        """Parse progress document content."""
        progress = ProjectProgress()
        content_lower = content.lower()

        # Extract completion percentage
        progress.completion_pct = self._extract_completion(content)

        # Extract current phase
        progress.current_phase = self._extract_pattern(content, self.PHASE_PATTERNS)

        # Extract status
        progress.current_status = self._extract_pattern(content, self.STATUS_PATTERNS)

        # Extract focus
        progress.current_focus = self._extract_pattern(content, self.FOCUS_PATTERNS)

        # Extract next step
        progress.next_action = self._extract_pattern(content, self.NEXT_STEP_PATTERNS)

        # Extract last updated
        progress.last_updated = self._extract_pattern(content, self.UPDATED_PATTERNS)

        # Extract checkbox items
        progress.items = self._extract_checkboxes(content, source_file)

        # Calculate completion from checkboxes if not found
        if progress.completion_pct is None and progress.items:
            completed = sum(1 for i in progress.items if i.status == ItemStatus.COMPLETE)
            total = len(progress.items)
            if total > 0:
                progress.completion_pct = (completed / total) * 100
                progress.total_items = total
                progress.completed_items = completed

        # Extract decision points
        progress.decisions = self._extract_decisions(content, source_file)
        progress.has_pending_decision = len(progress.decisions) > 0

        # Extract next steps section
        progress.next_steps = self._extract_next_steps(content)

        # Extract major sections
        progress.sections = self._extract_sections(content)

        return progress

    def parse_project(self, project_path: Path) -> ProjectProgress:
        """Parse all progress files for a project and merge."""
        progress_files = [
            'TODO.md', 'PROGRESS.md', 'ROADMAP.md', 'STATUS.md',
            'DEVELOPMENT-STATUS.md', 'FUTURE.md'
        ]

        merged = ProjectProgress()

        for pf in progress_files:
            file_path = project_path / pf
            if file_path.exists():
                parsed = self.parse_file(file_path)
                merged = self._merge_progress(merged, parsed)

        return merged

    def _extract_completion(self, content: str) -> Optional[float]:
        """Extract completion percentage from content."""
        for pattern in self.COMPLETION_PATTERNS:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                groups = match.groups()
                if len(groups) == 2:
                    # X of Y format
                    try:
                        done = int(groups[0])
                        total = int(groups[1])
                        if total > 0:
                            return (done / total) * 100
                    except ValueError:
                        continue
                elif len(groups) == 1:
                    # Percentage format
                    try:
                        return float(groups[0])
                    except ValueError:
                        continue
        return None

    def _extract_pattern(self, content: str, patterns: list[str]) -> Optional[str]:
        """Extract first match from a list of patterns."""
        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE | re.MULTILINE)
            if match:
                return match.group(1).strip()
        return None

    def _extract_checkboxes(self, content: str, source_file: Optional[str] = None) -> list[ProgressItem]:
        """Extract checkbox items (- [ ] and - [x])."""
        items = []
        lines = content.split('\n')

        for line_num, line in enumerate(lines, 1):
            # Match checkbox pattern
            match = re.match(r'^[\s-]*\[([ xX✓✅])\]\s+(.+)$', line)
            if match:
                checked = match.group(1).lower() not in [' ', '']
                text = match.group(2).strip()

                # Determine status
                status = ItemStatus.COMPLETE if checked else ItemStatus.PENDING

                # Check for status indicators in text
                for indicator, ind_status in self.STATUS_INDICATORS.items():
                    if indicator in text.upper():
                        status = ind_status
                        break

                # Check for priority
                priority = None
                for indicator, ind_priority in self.PRIORITY_INDICATORS.items():
                    if indicator in text.upper():
                        priority = ind_priority
                        break

                items.append(ProgressItem(
                    content=text,
                    status=status,
                    priority=priority,
                    source_file=source_file,
                    line_number=line_num,
                ))

        return items

    def _extract_decisions(self, content: str, source_file: Optional[str] = None) -> list[DecisionPoint]:
        """Extract decision points (Option A/B sections)."""
        decisions = []

        # Look for "Option A:", "Option B:" patterns
        option_pattern = r'###?\s*Option\s+([A-Z])[:\s]+([^\n]+)'
        matches = list(re.finditer(option_pattern, content, re.IGNORECASE))

        if len(matches) >= 2:
            # Group options together
            options = [f"Option {m.group(1)}: {m.group(2).strip()}" for m in matches]

            # Look for recommendation
            rec_pattern = r'(?:recommend|recommended|current recommendation)[:\s]+([^\n]+)'
            rec_match = re.search(rec_pattern, content, re.IGNORECASE)
            recommendation = rec_match.group(1).strip() if rec_match else None

            # Look for decision question
            question_pattern = r'(?:decision\s+point|what\'s\s+next)[:\s]+([^\n]+)'
            q_match = re.search(question_pattern, content, re.IGNORECASE)
            question = q_match.group(1).strip() if q_match else "Choose an approach"

            decisions.append(DecisionPoint(
                question=question,
                options=options,
                recommendation=recommendation,
                source_file=source_file,
            ))

        return decisions

    def _extract_next_steps(self, content: str) -> list[str]:
        """Extract next steps from a dedicated section."""
        steps = []

        # Find "Next Steps" or "Immediate Next Steps" section
        section_pattern = r'###?\s*(?:Immediate\s+)?Next\s+Steps?\s*\n((?:[-*]\s+[^\n]+\n?)+)'
        match = re.search(section_pattern, content, re.IGNORECASE)

        if match:
            section = match.group(1)
            for line in section.split('\n'):
                line = line.strip()
                if line.startswith(('-', '*')):
                    steps.append(line.lstrip('-* ').strip())

        return steps[:5]  # Limit to 5

    def _extract_sections(self, content: str) -> dict[str, str]:
        """Extract major markdown sections."""
        sections = {}

        # Split by ## headers
        parts = re.split(r'^##\s+', content, flags=re.MULTILINE)

        for part in parts[1:]:  # Skip content before first ##
            lines = part.split('\n')
            if lines:
                title = lines[0].strip()
                body = '\n'.join(lines[1:]).strip()
                # Clean up title
                title_clean = re.sub(r'[^\w\s]', '', title).strip().lower().replace(' ', '_')
                if title_clean:
                    sections[title_clean] = body[:500]  # Limit size

        return sections

    def _merge_progress(self, base: ProjectProgress, new: ProjectProgress) -> ProjectProgress:
        """Merge two progress objects, preferring non-None values."""
        # Prefer higher completion percentage
        if new.completion_pct is not None:
            if base.completion_pct is None or new.completion_pct > base.completion_pct:
                base.completion_pct = new.completion_pct
                base.total_items = new.total_items
                base.completed_items = new.completed_items

        # Prefer non-None values for text fields
        if new.current_phase:
            base.current_phase = new.current_phase
        if new.current_status:
            base.current_status = new.current_status
        if new.current_focus:
            base.current_focus = new.current_focus
        if new.next_action:
            base.next_action = new.next_action
        if new.last_updated:
            base.last_updated = new.last_updated

        # Merge items
        base.items.extend(new.items)

        # Merge decisions
        base.decisions.extend(new.decisions)
        base.has_pending_decision = len(base.decisions) > 0

        # Merge next steps
        seen = set(base.next_steps)
        for step in new.next_steps:
            if step not in seen:
                base.next_steps.append(step)
                seen.add(step)

        # Merge sections
        base.sections.update(new.sections)

        return base


def parse_progress(project_path: Path) -> ProjectProgress:
    """Convenience function to parse project progress."""
    parser = ProgressParser()
    return parser.parse_project(project_path)
