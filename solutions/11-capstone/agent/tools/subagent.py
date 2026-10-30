"""The ``subagent`` tool: run a second agent with its own context and return its answer."""
from __future__ import annotations

from ..log import RequestLog
from ..workspace import Workspace
from .registry import Tool, ToolRegistry, truncate

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # permissions.py imports this package
    from ..permissions import PermissionPolicy

SUBAGENT_TOOLS = ("read_file", "list_files", "search")
SUBAGENT_MAX_TURNS = 20
SUBAGENT_MAX_ANSWER = 4000
SUBAGENT_SYSTEM = (
    "You are a search subagent. You can only read: you have read_file, list_files and "
    "search, and you cannot change anything. Find the answer to the task you are given. "
    "Answer concisely: name the files and line numbers that matter and quote only the "
    "lines needed. Do not paste whole files.")


def make_subagent_tool(client, model: str, tools: ToolRegistry, *,
                       log: RequestLog | None = None,
                       context_window: int | None = None,
                       permissions: PermissionPolicy | None = None,
                       workspace: Workspace | None = None) -> Tool:
    from ..context import ContextManager
    from ..loop import Agent  # imported here: loop.py imports this package

    runs = 0

    def subagent(task: str) -> str:
        nonlocal runs
        runs += 1
        agent = Agent(client, model, tools.subset(SUBAGENT_TOOLS), system=SUBAGENT_SYSTEM,
                      max_turns=SUBAGENT_MAX_TURNS,
                      permissions=permissions, workspace=workspace,
                      log=log.with_agent(f"subagent-{runs}") if log else None,
                      context=ContextManager(context_window) if context_window else None)
        result = agent.run(task)
        if result.stop_reason == "max_turns":
            return f"Subagent stopped after {SUBAGENT_MAX_TURNS} turns without finishing."
        if result.stop_reason != "done":
            return f"Error: subagent failed: {result.error or result.stop_reason}"
        return truncate(result.final_text, SUBAGENT_MAX_ANSWER)

    return Tool(
        name="subagent",
        description="Hand a search or reading task to a helper that works in its own fresh "
                    "context and can only read files (read_file, list_files, search). Only "
                    "its final answer comes back, so use it for questions like 'find where X "
                    "is defined' that would otherwise fill your history with file contents. "
                    "Describe the task completely: the helper cannot see this conversation.",
        parameters={"type": "object",
                    "properties": {"task": {"type": "string",
                                            "description": "What to find out, in full."}},
                    "required": ["task"]},
        fn=subagent,
        read_only=True,
    )
