"""Document template definitions for headless Claude Code generation."""

from dataclasses import dataclass, field
from typing import Optional

from .context import ProjectContext


@dataclass
class DocTemplate:
    """A document generation template.

    Each template defines a prompt structure, output location, budget cap,
    and allowed tools for a specific type of document generation.
    """

    id: str
    name: str
    description: str
    output_filename: str
    output_dir: str  # Relative to project root
    max_budget_usd: float
    allowed_tools: list[str] = field(default_factory=list)
    prompt_template: str = ""

    def render(self, ctx: ProjectContext) -> str:
        """Render the prompt with project-specific context.

        Args:
            ctx: ProjectContext with project metadata.

        Returns:
            The fully rendered prompt string to send to Claude.
        """
        return self.prompt_template.format(
            name=ctx.name,
            path=ctx.path,
            project_type=ctx.project_type,
            category=ctx.category,
            completion_pct=ctx.completion_pct,
            current_phase=ctx.current_phase,
            next_action=ctx.next_action,
            git_branch=ctx.git_branch,
            git_dirty=ctx.git_dirty,
            last_commit_msg=ctx.last_commit_msg,
            has_claude_md=ctx.has_claude_md,
            has_todo=ctx.has_todo,
            has_progress=ctx.has_progress,
            health_score=ctx.health_score,
            urgency_score=ctx.urgency_score,
            priority=ctx.priority,
            deadline=ctx.deadline or "None set",
            tags=", ".join(ctx.tags) if ctx.tags else "None",
            notes=ctx.notes or "None",
        )

    @property
    def output_path(self) -> str:
        """Relative output path from project root."""
        if self.output_dir == ".":
            return self.output_filename
        return f"{self.output_dir}/{self.output_filename}"


# Read-only tools safe for document generation
READ_ONLY_TOOLS = ["Read", "Glob", "Grep"]
READ_ONLY_TOOLS_WITH_WEB = ["Read", "Glob", "Grep", "WebSearch"]


# --- Built-in Templates ---

_ROADMAP_TEMPLATE = DocTemplate(
    id="roadmap",
    name="Roadmap & TODO",
    description="Analyze codebase and produce a phased roadmap with task checklists",
    output_filename="ROADMAP.md",
    output_dir="docs",
    max_budget_usd=0.50,
    allowed_tools=READ_ONLY_TOOLS,
    prompt_template="""\
You are analyzing the project at the current working directory.

Project: {name}
Type: {project_type}
Category: {category}
Current phase: {current_phase}
Completion: {completion_pct:.0f}%
Next action: {next_action}
Priority: {priority}
Deadline: {deadline}

Read the codebase structure, existing documentation (README.md, CLAUDE.md, \
TODO.md, PROGRESS.md if they exist), and source code to understand the project.

Generate a comprehensive ROADMAP.md with:
1. **Project Overview** - One paragraph summary of what this project does
2. **Current State** - What's been built, what works, completion status
3. **Phase Breakdown** - Numbered phases with task checklists (- [ ] / - [x])
4. **Dependencies & Blockers** - What blocks progress
5. **Timeline Estimate** - Relative sizing (small/medium/large per phase)

Format as clean Markdown. Use checkbox syntax for tasks.
Be specific to THIS codebase - reference actual files, modules, and features.
Do NOT include generic boilerplate.
Output ONLY the markdown content, no preamble.""",
)

_ARCHITECTURE_TEMPLATE = DocTemplate(
    id="architecture",
    name="Architecture Overview",
    description="Map out architecture, dependencies, and data flow",
    output_filename="ARCHITECTURE.md",
    output_dir="docs",
    max_budget_usd=0.50,
    allowed_tools=READ_ONLY_TOOLS,
    prompt_template="""\
You are analyzing the project at the current working directory.

Project: {name}
Type: {project_type}
Category: {category}

Read the codebase structure, configuration files, and source code to understand \
the architecture.

Generate an ARCHITECTURE.md with:
1. **Overview** - What this project does and its high-level architecture
2. **Directory Structure** - Key directories and their purposes
3. **Core Components** - Main modules/classes and their responsibilities
4. **Data Flow** - How data moves through the system
5. **Dependencies** - External libraries and services used
6. **Configuration** - Environment variables, config files
7. **Entry Points** - How the application starts, CLI commands, API routes

Format as clean Markdown with diagrams using code blocks where helpful.
Be specific to THIS codebase - reference actual files and modules.
Output ONLY the markdown content, no preamble.""",
)

_CODE_REVIEW_TEMPLATE = DocTemplate(
    id="code-review",
    name="Code Review",
    description="Code quality assessment with security, patterns, and improvement suggestions",
    output_filename="CODE-REVIEW.md",
    output_dir="docs",
    max_budget_usd=0.75,
    allowed_tools=READ_ONLY_TOOLS,
    prompt_template="""\
You are performing a code review of the project at the current working directory.

Project: {name}
Type: {project_type}
Category: {category}
Health Score: {health_score}/100

Read the source code thoroughly. Focus on the main source files, not tests or configs.

Generate a CODE-REVIEW.md with:
1. **Summary** - Overall code quality assessment (Good/Fair/Needs Work)
2. **Strengths** - What the code does well
3. **Issues Found** - Organized by severity:
   - **Critical** - Security vulnerabilities, data loss risks
   - **High** - Bugs, race conditions, error handling gaps
   - **Medium** - Code smells, duplication, poor naming
   - **Low** - Style issues, missing docs, minor improvements
4. **Patterns & Anti-Patterns** - Design patterns used and any anti-patterns found
5. **Recommendations** - Top 5 actionable improvements, ordered by impact

For each issue, include:
- File path and line reference
- Description of the problem
- Suggested fix

Be specific and constructive. Reference actual code.
Output ONLY the markdown content, no preamble.""",
)

_TEST_COVERAGE_TEMPLATE = DocTemplate(
    id="test-coverage",
    name="Test Coverage Analysis",
    description="Assess test gaps and suggest tests to write",
    output_filename="TEST-COVERAGE.md",
    output_dir="docs",
    max_budget_usd=0.50,
    allowed_tools=READ_ONLY_TOOLS,
    prompt_template="""\
You are analyzing test coverage for the project at the current working directory.

Project: {name}
Type: {project_type}

Read the test files and source code to assess test coverage.

Generate a TEST-COVERAGE.md with:
1. **Test Summary** - Test framework used, number of test files, test structure
2. **Coverage Assessment** - Which modules/functions have tests and which don't
3. **Critical Gaps** - Untested code paths that could cause bugs:
   - Business logic without tests
   - Error handling paths not tested
   - Edge cases not covered
4. **Suggested Tests** - Specific tests to write, organized by priority:
   - For each suggestion, include the test name, what it tests, and a brief \
description of the test approach
5. **Test Quality** - Assessment of existing test quality (assertions, mocking, etc.)

Be specific to THIS codebase - reference actual files and functions.
Output ONLY the markdown content, no preamble.""",
)

_NEXT_PHASE_TEMPLATE = DocTemplate(
    id="next-phase",
    name="Next Phase Plan",
    description="Plan the next development phase based on current state",
    output_filename="NEXT-PHASE.md",
    output_dir="docs",
    max_budget_usd=0.50,
    allowed_tools=READ_ONLY_TOOLS,
    prompt_template="""\
You are planning the next development phase for the project at the current \
working directory.

Project: {name}
Type: {project_type}
Current phase: {current_phase}
Completion: {completion_pct:.0f}%
Next action: {next_action}
Priority: {priority}
Deadline: {deadline}
Notes: {notes}

Read the codebase, existing docs (TODO.md, PROGRESS.md, ROADMAP.md), and source \
code to understand what's been done and what comes next.

Generate a NEXT-PHASE.md with:
1. **Current State Summary** - Where the project stands right now
2. **Next Phase Goals** - 3-5 concrete goals for the next phase
3. **Task Breakdown** - Detailed task list with checkboxes (- [ ])
4. **Technical Approach** - How to implement the key tasks
5. **Risks & Mitigations** - What could go wrong and how to prevent it
6. **Definition of Done** - Clear criteria for phase completion

Tasks should be small enough to complete in a single session.
Be specific to THIS codebase.
Output ONLY the markdown content, no preamble.""",
)

_STATUS_REPORT_TEMPLATE = DocTemplate(
    id="status-report",
    name="Status Report",
    description="Current state summary for stakeholders",
    output_filename="STATUS-REPORT.md",
    output_dir="docs",
    max_budget_usd=0.25,
    allowed_tools=READ_ONLY_TOOLS,
    prompt_template="""\
You are generating a status report for the project at the current working directory.

Project: {name}
Type: {project_type}
Category: {category}
Current phase: {current_phase}
Completion: {completion_pct:.0f}%
Health Score: {health_score}/100
Priority: {priority}
Deadline: {deadline}
Git branch: {git_branch}
Uncommitted changes: {git_dirty}
Last commit: {last_commit_msg}
Tags: {tags}

Read the codebase and any existing documentation to understand the current state.

Generate a STATUS-REPORT.md with:
1. **Executive Summary** - 2-3 sentence overview
2. **Progress** - What's been completed, with percentage
3. **Current Work** - What's actively being worked on
4. **Blockers** - Any issues preventing progress
5. **Next Steps** - Immediate next actions (3-5 items)
6. **Metrics** - Health score, completion %, any relevant numbers

Keep it concise - this is for quick stakeholder review.
Output ONLY the markdown content, no preamble.""",
)

_WEEKLY_SUMMARY_TEMPLATE = DocTemplate(
    id="weekly-summary",
    name="Weekly Summary",
    description="Cross-project weekly summary (multi-project)",
    output_filename="weekly-{date}.md",
    output_dir="reports",
    max_budget_usd=1.00,
    allowed_tools=READ_ONLY_TOOLS_WITH_WEB,
    prompt_template="""\
You are generating a weekly project portfolio summary.

This is a cross-project summary. The following project data is provided:

{notes}

Generate a weekly summary report with:
1. **Executive Summary** - 2-3 sentence overview of the portfolio
2. **Key Achievements** - What was accomplished across projects this week
3. **Active Projects** - Brief status of each active project
4. **Attention Needed** - Projects with low health, overdue deadlines, or blockers
5. **Priorities for Next Week** - Top 5 items to focus on
6. **Metrics** - Average health, completion trends, project counts

Format as clean Markdown.
Output ONLY the markdown content, no preamble.""",
)


# Registry of all built-in templates
BUILTIN_TEMPLATES: dict[str, DocTemplate] = {
    t.id: t
    for t in [
        _ROADMAP_TEMPLATE,
        _ARCHITECTURE_TEMPLATE,
        _CODE_REVIEW_TEMPLATE,
        _TEST_COVERAGE_TEMPLATE,
        _NEXT_PHASE_TEMPLATE,
        _STATUS_REPORT_TEMPLATE,
        _WEEKLY_SUMMARY_TEMPLATE,
    ]
}


def get_template(template_id: str) -> Optional[DocTemplate]:
    """Look up a template by ID.

    Args:
        template_id: The template identifier (e.g. "roadmap", "architecture").

    Returns:
        The DocTemplate if found, None otherwise.
    """
    return BUILTIN_TEMPLATES.get(template_id)
