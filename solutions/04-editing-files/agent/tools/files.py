"""File tools."""
from __future__ import annotations

import re
from pathlib import Path

from ..workspace import FileTracker, Workspace  # noqa: F401  (FileTracker re-exported)
from .registry import Tool

SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules"}
MAX_FILES = 500
MAX_MATCHES = 200


def _rel(ws: Workspace, p: Path) -> str:
    try:
        return p.relative_to(ws.root).as_posix()
    except ValueError:
        return p.as_posix()


def _files_under(base: Path, pattern: str):
    """Sorted files below ``base`` matching ``pattern``, skipping noise directories."""
    found = (p for p in base.glob(pattern)
             if p.is_file() and not SKIP_DIRS.intersection(p.relative_to(base).parts))
    return sorted(found, key=lambda p: p.relative_to(base).as_posix())


def make_read_file(ws: Workspace) -> Tool:
    def read_file(path: str, offset: int = 1, limit: int = 2000) -> str:
        p = ws.resolve(path)
        if not p.is_file():
            return f"Error: file not found: {path}"
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            return f"Error: {path} is not a UTF-8 text file."
        ws.tracker.mark_read(p)
        start = max(offset, 1) - 1
        chosen = lines[start:start + limit]
        return "\n".join(f"{n:>6}\t{line}" for n, line in enumerate(chosen, start + 1))

    return Tool(
        name="read_file",
        description="Read a text file. Returns numbered lines. Use offset (1-based line) "
                    "and limit to read part of a large file.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "offset": {"type": "integer", "description": "First line to read (1-based)"},
                "limit": {"type": "integer", "description": "Maximum number of lines"},
            },
            "required": ["path"],
        },
        fn=read_file,
        read_only=True,
    )


def make_list_files(ws: Workspace) -> Tool:
    def list_files(pattern: str = "**/*", path: str = ".") -> str:
        base = ws.resolve(path)
        if not base.is_dir():
            return f"Error: directory not found: {path}"
        files = [_rel(ws, p) for p in _files_under(base, pattern)]
        out = files[:MAX_FILES]
        if len(files) > MAX_FILES:
            out.append(f"[{len(files) - MAX_FILES} more files not shown]")
        return "\n".join(out) if out else "No files found."

    return Tool(
        name="list_files",
        description="List files (not directories) under a directory, one relative path per line, "
                    "sorted. Use pattern to filter, e.g. '**/*.py'. Skips .git, .venv, "
                    "__pycache__ and node_modules. Use this to find out what exists; use "
                    "search to find what files contain.",
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string",
                            "description": "Glob pattern relative to path (default '**/*')"},
                "path": {"type": "string",
                         "description": "Directory to list (default: the project root)"},
            },
        },
        fn=list_files,
        read_only=True,
    )


def make_search(ws: Workspace) -> Tool:
    def search(pattern: str, path: str = ".", glob: str | None = None) -> str:
        try:
            regex = re.compile(pattern)
        except re.error as e:
            return f"Error: invalid regular expression: {e}"
        base = ws.resolve(path)
        if base.is_file():
            files = [base]
        elif base.is_dir():
            if glob and "/" not in glob:
                glob = "**/" + glob  # '*.py' means .py files at any depth
            files = _files_under(base, glob or "**/*")
        else:
            return f"Error: path not found: {path}"
        matches: list[str] = []
        for f in files:
            try:
                text = f.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            rel = _rel(ws, f)
            for lineno, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    matches.append(f"{rel}:{lineno}: {line}")
        if not matches:
            return "No matches."
        out = matches[:MAX_MATCHES]
        if len(matches) > MAX_MATCHES:
            out.append(f"[{len(matches) - MAX_MATCHES} more matches not shown]")
        return "\n".join(out)

    return Tool(
        name="search",
        description="Search file contents with a Python regular expression. Returns lines as "
                    "'path:lineno: text'. Use glob (e.g. '*.py') to limit which files are "
                    "searched. Use this to find where something is defined or used; use "
                    "list_files to find files by name.",
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regular expression to look for"},
                "path": {"type": "string",
                         "description": "File or directory to search (default: the project root)"},
                "glob": {"type": "string",
                         "description": "Only search files matching this glob, e.g. '*.py'"},
            },
            "required": ["pattern"],
        },
        fn=search,
        read_only=True,
    )


def _read_exact(p: Path) -> str:
    """File text with line endings untouched (no newline translation)."""
    return p.read_bytes().decode("utf-8")


def make_edit_file(ws: Workspace) -> Tool:
    def edit_file(path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
        p = ws.resolve(path)
        if not p.is_file():
            return f"Error: file not found: {path}"
        problem = ws.tracker.check(p)
        if problem:
            return problem
        if old_string == new_string:
            return "Error: old_string and new_string are the same."
        try:
            text = _read_exact(p)
        except UnicodeDecodeError:
            return f"Error: {path} is not a UTF-8 text file."
        if "\r\n" in text:
            # the model writes "\n"; in a CRLF file every inserted line break must be "\r\n"
            if old_string not in text:
                old_string = old_string.replace("\r\n", "\n").replace("\n", "\r\n")
            new_string = new_string.replace("\r\n", "\n").replace("\n", "\r\n")
        count = text.count(old_string) if old_string else 0
        if count == 0:
            return "Error: old_string was not found in the file."
        if count > 1 and not replace_all:
            return (f"Error: old_string appears {count} times. Include more surrounding "
                    "lines to make it unique, or set replace_all to true.")
        updated = text.replace(old_string, new_string)
        p.write_bytes(updated.encode("utf-8"))
        ws.tracker.mark_read(p)
        return f"Edited {path} ({count} replacement{'s' if count != 1 else ''})."

    return Tool(
        name="edit_file",
        description="Edit a file by replacing an exact string. The file must have been read "
                    "with read_file first. old_string must match the file exactly (including "
                    "whitespace) and appear once, unless replace_all is true. Do not include "
                    "the line-number prefix from read_file output.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "old_string": {"type": "string", "description": "Exact text to replace"},
                "new_string": {"type": "string", "description": "Replacement text"},
                "replace_all": {"type": "boolean",
                                "description": "Replace every occurrence (default false)"},
            },
            "required": ["path", "old_string", "new_string"],
        },
        fn=edit_file,
    )


def make_write_file(ws: Workspace) -> Tool:
    def write_file(path: str, content: str) -> str:
        p = ws.resolve(path)
        if p.is_dir():
            return f"Error: {path} is a directory."
        existed = p.exists()
        if existed:
            problem = ws.tracker.check(p)
            if problem:
                return problem
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content.encode("utf-8"))
        ws.tracker.mark_read(p)
        return f"{'Wrote' if existed else 'Created'} {path}."

    return Tool(
        name="write_file",
        description="Create a new file, or overwrite an existing one with the full content. "
                    "An existing file must have been read with read_file first. To change part "
                    "of a file, use edit_file instead.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "content": {"type": "string", "description": "Complete new file content"},
            },
            "required": ["path", "content"],
        },
        fn=write_file,
    )
