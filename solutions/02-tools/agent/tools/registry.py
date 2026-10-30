"""Tool definitions and the registry the loop dispatches through."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable


MAX_TOOL_OUTPUT = 20_000


def truncate(text: str, limit: int = MAX_TOOL_OUTPUT) -> str:
    """Keep the first and last ``limit // 2`` characters of an over-long result."""
    if len(text) <= limit:
        return text
    half = limit // 2
    removed = len(text) - 2 * half
    return f"{text[:half]}\n[... {removed} characters truncated ...]\n{text[len(text) - half:]}"


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict  # JSON schema
    fn: Callable[..., str]
    read_only: bool = False


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def schemas(self) -> list[dict]:
        return [{"type": "function",
                 "function": {"name": t.name, "description": t.description,
                              "parameters": t.parameters}}
                for t in self._tools.values()]

    def dispatch(self, name: str, raw_arguments: str) -> str:
        tool = self.get(name)
        if tool is None:
            return f"Error: unknown tool: {name}"
        args = json.loads(raw_arguments)
        return truncate(tool.fn(**args))
