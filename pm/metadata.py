"""PM-STATUS.md file handling for two-way metadata sync."""

import json
import re
from pathlib import Path
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field


PM_STATUS_FILENAME = "PM-STATUS.md"


@dataclass
class ProjectMetadata:
    """Project metadata from PM-STATUS.md file."""
    priority: int = 3
    deadline: Optional[datetime] = None
    target_date: Optional[datetime] = None
    tags: list[str] = field(default_factory=list)
    client_name: Optional[str] = None
    budget_hours: Optional[float] = None
    hours_logged: float = 0
    archived: bool = False
    notes: str = ""

    # Source tracking
    source_file: Optional[str] = None


def read_pm_status(project_path: Path) -> Optional[ProjectMetadata]:
    """Read PM-STATUS.md from project directory.

    File format:
    ```
    ---
    priority: 2
    deadline: 2025-02-15
    target_date: 2025-03-01
    tags: [mobile, ios]
    client: Acme Corp
    budget_hours: 40
    hours_logged: 12
    archived: false
    ---

    # Notes

    Free-form notes here...
    ```
    """
    status_file = project_path / PM_STATUS_FILENAME
    if not status_file.exists():
        return None

    try:
        content = status_file.read_text()
    except Exception:
        return None

    return parse_pm_status(content, str(status_file))


def parse_pm_status(content: str, source_file: str = None) -> ProjectMetadata:
    """Parse PM-STATUS.md content."""
    metadata = ProjectMetadata(source_file=source_file)

    # Extract YAML frontmatter
    frontmatter_match = re.match(r'^---\s*\n(.*?)\n---\s*\n?(.*)', content, re.DOTALL)

    if frontmatter_match:
        yaml_content = frontmatter_match.group(1)
        notes_content = frontmatter_match.group(2).strip()

        # Parse YAML-like frontmatter (simple key: value parsing)
        for line in yaml_content.split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            if ':' in line:
                key, value = line.split(':', 1)
                key = key.strip().lower()
                value = value.strip()

                if key == 'priority':
                    try:
                        metadata.priority = int(value)
                    except ValueError:
                        # Handle text priorities
                        priority_map = {'critical': 1, 'high': 2, 'normal': 3, 'low': 4, 'someday': 5}
                        metadata.priority = priority_map.get(value.lower(), 3)

                elif key == 'deadline':
                    metadata.deadline = _parse_date(value)

                elif key == 'target_date' or key == 'target':
                    metadata.target_date = _parse_date(value)

                elif key == 'tags':
                    metadata.tags = _parse_list(value)

                elif key == 'client' or key == 'client_name':
                    metadata.client_name = value if value and value != 'null' else None

                elif key == 'budget_hours' or key == 'budget':
                    try:
                        metadata.budget_hours = float(value) if value else None
                    except ValueError:
                        pass

                elif key == 'hours_logged' or key == 'hours':
                    try:
                        metadata.hours_logged = float(value) if value else 0
                    except ValueError:
                        pass

                elif key == 'archived':
                    metadata.archived = value.lower() in ('true', 'yes', '1')

        # Notes is everything after frontmatter
        metadata.notes = notes_content
    else:
        # No frontmatter, entire content is notes
        metadata.notes = content.strip()

    return metadata


def write_pm_status(project_path: Path, metadata: ProjectMetadata) -> bool:
    """Write PM-STATUS.md to project directory.

    Returns True if successful.
    """
    status_file = project_path / PM_STATUS_FILENAME

    # Build YAML frontmatter
    lines = ['---']

    # Priority
    priority_labels = {1: 'critical', 2: 'high', 3: 'normal', 4: 'low', 5: 'someday'}
    lines.append(f"priority: {metadata.priority}  # {priority_labels.get(metadata.priority, 'normal')}")

    # Deadline
    if metadata.deadline:
        lines.append(f"deadline: {metadata.deadline.strftime('%Y-%m-%d')}")

    # Target date
    if metadata.target_date:
        lines.append(f"target_date: {metadata.target_date.strftime('%Y-%m-%d')}")

    # Tags
    if metadata.tags:
        lines.append(f"tags: [{', '.join(metadata.tags)}]")

    # Client
    if metadata.client_name:
        lines.append(f"client: {metadata.client_name}")

    # Budget hours
    if metadata.budget_hours:
        lines.append(f"budget_hours: {metadata.budget_hours}")

    # Hours logged
    if metadata.hours_logged:
        lines.append(f"hours_logged: {metadata.hours_logged}")

    # Archived
    if metadata.archived:
        lines.append("archived: true")

    lines.append('---')
    lines.append('')

    # Notes section
    if metadata.notes:
        lines.append(metadata.notes)
    else:
        lines.append('# Project Notes')
        lines.append('')
        lines.append('Add project-specific notes, context, and decisions here.')
        lines.append('')

    content = '\n'.join(lines)

    try:
        status_file.write_text(content)
        return True
    except Exception as e:
        return False


def sync_to_file(project_path: Path, **kwargs) -> bool:
    """Update PM-STATUS.md with new values, preserving existing notes.

    Usage:
        sync_to_file(path, priority=1, deadline=datetime(...))
    """
    # Read existing or create new
    existing = read_pm_status(project_path)
    if existing is None:
        existing = ProjectMetadata()

    # Update with new values
    for key, value in kwargs.items():
        if hasattr(existing, key):
            setattr(existing, key, value)

    return write_pm_status(project_path, existing)


def _parse_date(value: str) -> Optional[datetime]:
    """Parse date string in various formats."""
    if not value or value.lower() in ('null', 'none', ''):
        return None

    formats = ['%Y-%m-%d', '%Y/%m/%d', '%m/%d/%Y', '%d-%m-%Y']
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _parse_list(value: str) -> list[str]:
    """Parse list value like '[a, b, c]' or 'a, b, c'."""
    value = value.strip()
    if value.startswith('[') and value.endswith(']'):
        value = value[1:-1]

    items = [item.strip().strip('"\'') for item in value.split(',')]
    return [item for item in items if item]
