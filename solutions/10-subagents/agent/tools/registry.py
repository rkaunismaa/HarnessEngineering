"""Tool definitions and the registry the loop dispatches through."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Iterable


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

    def subset(self, names: Iterable[str]) -> "ToolRegistry":
        """A new registry with only the named tools (names that don't exist are skipped).
        The Tool objects are shared with this registry."""
        sub = ToolRegistry()
        for name in names:
            tool = self.get(name)
            if tool is not None:
                sub.register(tool)
        return sub

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
    """Check ``args`` against a tool's JSON schema; return one message per problem.
    Understands types, ``enum``, and arrays of objects (``items``); nothing more."""
    properties = schema.get("properties", {})
    errors = [f"missing required parameter '{p}'"
              for p in schema.get("required", []) if p not in args]
    errors += [f"unknown parameter '{k}'" for k in args if k not in properties]
    for k, value in args.items():
        if k in properties:
            errors += _check_value(properties[k], value, f"parameter '{k}'", k)
    return errors


def _check_value(spec: dict, value, label: str, path: str) -> list[str]:
    """Problems with one value. ``label`` names it at the top level (``parameter 'x'``),
    ``path`` names it inside arrays and objects (``todos[1].status``)."""
    expected = spec.get("type")
    check = _JSON_TYPES.get(expected)
    if check is not None and not check(value):
        return [f"{label} must be {expected}"]
    if "enum" in spec and value not in spec["enum"]:
        return [f"{label} must be one of {', '.join(str(v) for v in spec['enum'])}"]
    errors: list[str] = []
    if expected == "array" and "items" in spec:
        for i, item in enumerate(value):
            where = f"{path}[{i}]"
            errors += _check_value(spec["items"], item, where, where)
    elif expected == "object" and "properties" in spec:
        errors += [f"{path}: missing required parameter '{p}'"
                   for p in spec.get("required", []) if p not in value]
        for name, sub in spec["properties"].items():
            if name in value:
                where = f"{path}.{name}"
                errors += _check_value(sub, value[name], where, where)
    return errors
