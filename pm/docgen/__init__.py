"""Document generation system using headless Claude Code."""

from .templates import DocTemplate, BUILTIN_TEMPLATES, get_template
from .context import ProjectContext, build_context
from .executor import run_doc_generation, run_batch_generation, DocResult

__all__ = [
    "DocTemplate",
    "BUILTIN_TEMPLATES",
    "get_template",
    "ProjectContext",
    "build_context",
    "run_doc_generation",
    "run_batch_generation",
    "DocResult",
]
