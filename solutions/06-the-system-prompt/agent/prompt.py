"""The system prompt, built from parts: role, tool rules, environment, project instructions."""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from .tools.registry import ToolRegistry, truncate
from .workspace import Workspace

INSTRUCTION_FILES = ("AGENTS.md", "CLAUDE.md")
MAX_INSTRUCTIONS_CHARS = 10_000

ROLE = "You are a coding agent working in the user's project through the tools below."

TOOL_RULES = """\
# Using tools
- To find things, use `search` and `list_files`, not `bash`.
- Read a file with `read_file` before you edit it.
- Keep edits small. Change only what the task needs.
- Take one step at a time and check each result before the next."""


def load_project_instructions(root: Path) -> tuple[str, str] | None:
    """(filename, text) of the first instruction file found in ``root``, text truncated."""
    for name in INSTRUCTION_FILES:
        path = Path(root) / name
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            return name, truncate(text, MAX_INSTRUCTIONS_CHARS)
    return None


def git_summary(root: Path) -> str:
    """One line about the repository at ``root``. Never raises."""
    try:
        proc = subprocess.run(["git", "status", "--porcelain", "-b"], cwd=root,
                              capture_output=True, text=True, timeout=5,
                              env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
    except (OSError, subprocess.SubprocessError):
        return "git not available"
    if proc.returncode != 0:
        return "not a git repository"
    lines = proc.stdout.splitlines()
    header = lines[0][3:] if lines and lines[0].startswith("## ") else ""
    changed = len(lines) - 1 if header else len(lines)
    for prefix in ("No commits yet on ", "Initial commit on "):
        if header.startswith(prefix):
            header = header[len(prefix):]
    if header.startswith("HEAD (no branch)"):
        name = "(detached HEAD)"
    else:
        name = header.split("...")[0].split(" [")[0] or "(unknown)"
    return f"branch {name}, {changed} changed file(s)"


def build_system_prompt(ws: Workspace, tools: ToolRegistry, *,
                        now: datetime | None = None, extra: str | None = None) -> str:
    now = now or datetime.now()
    parts = [ROLE, TOOL_RULES, "\n".join([
        "# Environment",
        f"Working directory: {ws.root}",
        f"Platform: {sys.platform}",
        f"Date: {now:%Y-%m-%d}",
        f"Git: {git_summary(ws.root)}",
        f"Tools: {', '.join(tools.names())}",
    ])]
    found = load_project_instructions(ws.root)
    if found:
        parts.append(f"# Project instructions (from {found[0]})\n{found[1]}")
    if extra:
        parts.append(extra)
    return "\n\n".join(parts) + "\n"
