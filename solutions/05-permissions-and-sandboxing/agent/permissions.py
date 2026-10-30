"""Deciding whether a tool call may run: deny rules, read-only tools, allow rules, ask."""
from __future__ import annotations

import enum
import glob
from fnmatch import fnmatchcase
from typing import Callable

from .tools.registry import Tool


class Decision(enum.Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


# Called with (tool name, arguments); returns "yes", "always" or "no".
Approver = Callable[[str, dict], str]

# A bash command containing any of these can do more than its first word says.
SHELL_OPERATORS = (";", "&&", "||", "|", "`", "$(", ">", "<", "\n")

# The argument a rule's pattern is matched against, per tool. Other tools: bare rules only.
KEY_ARGUMENT = {"bash": "command", "read_file": "path", "edit_file": "path",
                "write_file": "path"}


def _parse(rule: str) -> tuple[str, str | None]:
    """"tool" -> ("tool", None); "tool(pattern)" -> ("tool", "pattern")."""
    if rule.endswith(")") and "(" in rule:
        name, _, pattern = rule[:-1].partition("(")
        return name, pattern
    return rule, None


def rule_matches(rule: str, tool: Tool, args: dict) -> bool:
    name, pattern = _parse(rule)
    if name != tool.name:
        return False
    if pattern is None:
        return True
    key = KEY_ARGUMENT.get(tool.name)
    value = args.get(key) if key else None
    return isinstance(value, str) and fnmatchcase(value, pattern)


def has_shell_operator(command: str) -> bool:
    return any(op in command for op in SHELL_OPERATORS)


class PermissionPolicy:
    def __init__(self, allow: list[str] | None = None, deny: list[str] | None = None,
                 auto_approve: bool = False):
        self.allow = list(allow or [])
        self.deny = list(deny or [])
        self.auto_approve = auto_approve

    def check(self, tool: Tool, args: dict) -> Decision:
        if any(rule_matches(r, tool, args) for r in self.deny):
            return Decision.DENY
        if tool.read_only:
            return Decision.ALLOW
        command = args.get("command") if tool.name == "bash" else None
        compound = isinstance(command, str) and has_shell_operator(command)
        if not compound and any(rule_matches(r, tool, args) for r in self.allow):
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
