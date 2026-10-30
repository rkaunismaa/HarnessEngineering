"""File tools."""
from __future__ import annotations

from ..workspace import Workspace
from .registry import Tool


def make_read_file(ws: Workspace) -> Tool:
    def read_file(path: str, offset: int = 1, limit: int = 2000) -> str:
        p = ws.resolve(path)
        if not p.is_file():
            return f"Error: file not found: {path}"
        lines = p.read_text().splitlines()
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
