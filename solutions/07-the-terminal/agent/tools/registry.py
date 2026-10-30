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
        """Run a tool call and return text for the model. Never raises: every problem
        becomes an ``Error: ...`` string the model can read and react to."""
        return truncate(self._dispatch(name, raw_arguments))

    def _dispatch(self, name: str, raw_arguments: str) -> str:
        tool = self.get(name)
        if tool is None:
            return (f"Error: unknown tool '{name}'. "
                    f"Available tools: {', '.join(self.names())}")
        try:
            args = json.loads(raw_arguments)
        except json.JSONDecodeError as exc:
            return (f"Error: arguments were not valid JSON ({exc.msg}). "
                    "Send the arguments as a JSON object.")
        if not isinstance(args, dict):
            return "Error: arguments must be a JSON object."
        errors = validate_args(tool.parameters, args)
        if errors:
            return "Error: " + "; ".join(errors)
        try:
            return str(tool.fn(**args))
        except Exception as exc:
            return f"Error: {type(exc).__name__}: {exc}"


_JSON_TYPES = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
}


def validate_args(schema: dict, args: dict) -> list[str]:
    """Check ``args`` against a tool's JSON schema; return one message per problem."""
    properties = schema.get("properties", {})
    errors = [f"missing required parameter '{p}'"
              for p in schema.get("required", []) if p not in args]
    errors += [f"unknown parameter '{k}'" for k in args if k not in properties]
    for k, value in args.items():
        expected = properties.get(k, {}).get("type")
        check = _JSON_TYPES.get(expected)
        if check is not None and not check(value):
            errors.append(f"parameter '{k}' must be {expected}")
    return errors
