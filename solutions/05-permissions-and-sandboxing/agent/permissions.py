"""Deciding whether a tool call may run: deny rules, read-only tools, allow rules, ask."""
from __future__ import annotations

import enum
import glob
from fnmatch import fnmatchcase
from typing import Callable

from .tools.registry import Tool
from .workspace import Workspace


class Decision(enum.Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


# Called with (tool name, arguments); returns "yes", "always" or "no".
Approver = Callable[[str, dict], str]

# A bash command containing any of these can do more than its first word says.
SHELL_OPERATORS = (";", "&&", "||", "|", "`", "$(", ">", "<", "\n", "&")

# The argument a rule's pattern is matched against, per tool. Other tools: bare rules only.
KEY_ARGUMENT = {"bash": "command", "read_file": "path", "edit_file": "path",
                "write_file": "path"}


def _parse(rule: str) -> tuple[str, str | None]:
    """"tool" -> ("tool", None); "tool(pattern)" -> ("tool", "pattern")."""
    if rule.endswith(")") and "(" in rule:
        name, _, pattern = rule[:-1].partition("(")
        return name, pattern
    return rule, None


PATH_TOOLS = {"read_file", "edit_file", "write_file"}


def _subject(tool: Tool, args: dict, ws: Workspace | None) -> tuple[str | None, bool]:
    """The text a rule pattern is matched against, and whether the call stays inside the
    project. For path tools with a workspace, that is the normalized path relative to the
    root (so ``./src/a.py``, ``src/x/../a.py`` and the absolute spelling are one path);
    a path that resolves outside the root is given as its absolute resolved form."""
    key = KEY_ARGUMENT.get(tool.name)
    value = args.get(key) if key else None
    if not isinstance(value, str):
        return None, True
    if ws is None or tool.name not in PATH_TOOLS:
        return value, True
    try:
        real = (ws.root / value).resolve()
    except (OSError, RuntimeError):  # e.g. a symlink loop: treat as outside, allow nothing
        return value, False
    if not ws.contains(real):
        return real.as_posix(), False
    return real.relative_to(ws.root).as_posix(), True


def rule_matches(rule: str, tool: Tool, subject: str | None) -> bool:
    name, pattern = _parse(rule)
    if name != tool.name:
        return False
    if pattern is None:
        return True
    return subject is not None and fnmatchcase(subject, pattern)


def has_shell_operator(command: str) -> bool:
    return any(op in command for op in SHELL_OPERATORS)


class PermissionPolicy:
    def __init__(self, allow: list[str] | None = None, deny: list[str] | None = None,
                 auto_approve: bool = False):
        self.allow = list(allow or [])
        self.deny = list(deny or [])
        self.auto_approve = auto_approve

    def check(self, tool: Tool, args: dict, ws: Workspace | None = None) -> Decision:
        """Decide one call. With ``ws``, path rules see the normalized root-relative path;
        without it they see the raw argument."""
        subject, inside = _subject(tool, args, ws)
        if any(rule_matches(r, tool, subject) for r in self.deny):
            return Decision.DENY
        if tool.read_only:
            return Decision.ALLOW
        command = args.get("command") if tool.name == "bash" else None
        compound = isinstance(command, str) and has_shell_operator(command)
        if inside and not compound and any(rule_matches(r, tool, subject) for r in self.allow):
            return Decision.ALLOW
        if self.auto_approve:
            return Decision.ALLOW
        return Decision.ASK

    def remember(self, tool: Tool, args: dict) -> None:
        """Allow this call from now on: the exact command for bash, the whole tool otherwise."""
        if tool.name == "bash" and isinstance(args.get("command"), str):
            rule = f"bash({glob.escape(args['command'])})"
        else:
            rule = tool.name
        if rule not in self.allow:
            self.allow.append(rule)
