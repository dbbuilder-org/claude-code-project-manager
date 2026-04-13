"""Headless Claude Code execution engine for document generation."""

import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional


@dataclass
class DocResult:
    """Result of a document generation run."""

    project_name: str
    template_id: str
    output_path: Optional[Path]
    status: str  # "success", "error", "timeout"
    duration_secs: float = 0.0
    error_message: str = ""
    file_size_bytes: int = 0


def run_doc_generation(
    project_path: Path,
    prompt: str,
    output_file: Path,
    max_budget_usd: float = 0.50,
    allowed_tools: Optional[list[str]] = None,
    timeout: int = 300,
    permission_mode: str = "readonly",
) -> DocResult:
    """Run headless Claude Code to generate a document.

    Executes `claude -p` as a subprocess with the given prompt, captures
    stdout as the generated document, and writes it to output_file.

    Args:
        project_path: Working directory for Claude (the project root).
        prompt: The fully rendered prompt to send to Claude.
        output_file: Where to write the generated document.
        max_budget_usd: Cost cap for this invocation.
        allowed_tools: List of tools Claude can use (e.g. ["Read", "Glob", "Grep"]).
        timeout: Maximum seconds to wait for completion.
        permission_mode: "readonly" (default) or "acceptEdits" or
                         "bypassPermissions" (use --dangerously-skip-permissions).

    Returns:
        DocResult with status, duration, and output path.
    """
    project_name = project_path.name
    template_id = output_file.stem.lower()
    start_time = time.time()

    # Build command
    cmd = [
        "claude",
        "-p", prompt,
        "--output-format", "text",
        "--max-budget-usd", str(max_budget_usd),
    ]

    # Permission mode
    if permission_mode == "bypassPermissions":
        cmd.append("--dangerously-skip-permissions")
    else:
        cmd.extend(["--permission-mode", permission_mode])

    if allowed_tools:
        cmd.extend(["--allowedTools", ",".join(allowed_tools)])

    try:
        result = subprocess.run(
            cmd,
            cwd=str(project_path),
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        duration = time.time() - start_time

        if result.returncode != 0:
            error_msg = result.stderr.strip() if result.stderr else f"Exit code {result.returncode}"
            return DocResult(
                project_name=project_name,
                template_id=template_id,
                output_path=None,
                status="error",
                duration_secs=duration,
                error_message=error_msg,
            )

        content = result.stdout.strip()
        if not content:
            return DocResult(
                project_name=project_name,
                template_id=template_id,
                output_path=None,
                status="error",
                duration_secs=duration,
                error_message="Claude returned empty output",
            )

        # Ensure output directory exists
        output_file.parent.mkdir(parents=True, exist_ok=True)

        # Write the generated document
        output_file.write_text(content)
        file_size = output_file.stat().st_size

        return DocResult(
            project_name=project_name,
            template_id=template_id,
            output_path=output_file,
            status="success",
            duration_secs=duration,
            file_size_bytes=file_size,
        )

    except subprocess.TimeoutExpired:
        duration = time.time() - start_time
        return DocResult(
            project_name=project_name,
            template_id=template_id,
            output_path=None,
            status="timeout",
            duration_secs=duration,
            error_message=f"Timed out after {timeout}s",
        )

    except FileNotFoundError:
        duration = time.time() - start_time
        return DocResult(
            project_name=project_name,
            template_id=template_id,
            output_path=None,
            status="error",
            duration_secs=duration,
            error_message="'claude' command not found. Is Claude Code CLI installed?",
        )

    except Exception as e:
        duration = time.time() - start_time
        return DocResult(
            project_name=project_name,
            template_id=template_id,
            output_path=None,
            status="error",
            duration_secs=duration,
            error_message=str(e),
        )


def run_batch_generation(
    tasks: list[dict],
    max_workers: int = 3,
    progress_callback: Optional[Callable[[DocResult], None]] = None,
) -> list[DocResult]:
    """Run document generation for multiple projects in parallel.

    Args:
        tasks: List of dicts with keys:
            - project_path (Path)
            - prompt (str)
            - output_file (Path)
            - max_budget_usd (float, optional)
            - allowed_tools (list[str], optional)
            - timeout (int, optional)
        max_workers: Maximum parallel workers.
        progress_callback: Called with each DocResult as it completes.

    Returns:
        List of DocResult for all tasks.
    """
    results = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for task in tasks:
            future = executor.submit(
                run_doc_generation,
                project_path=task["project_path"],
                prompt=task["prompt"],
                output_file=task["output_file"],
                max_budget_usd=task.get("max_budget_usd", 0.50),
                allowed_tools=task.get("allowed_tools"),
                timeout=task.get("timeout", 300),
                permission_mode=task.get("permission_mode", "readonly"),
            )
            futures[future] = task

        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            if progress_callback:
                progress_callback(result)

    return results
