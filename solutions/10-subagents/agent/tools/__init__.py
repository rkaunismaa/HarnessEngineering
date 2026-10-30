"""The default tool set."""
from __future__ import annotations

from typing import Callable

from ..log import RequestLog
from ..workspace import Workspace
from .files import make_edit_file, make_list_files, make_read_file, make_search, make_write_file
from .registry import Tool, ToolRegistry
from .shell import make_bash
from .subagent import make_subagent_tool
from .todo import make_todo_write

__all__ = ["Tool", "ToolRegistry", "make_default_tools"]


def make_default_tools(ws: Workspace, *,
                       confirm_bash: Callable[[str], bool] | None = None,
                       client=None, model: str | None = None, log: RequestLog | None = None,
                       context_window: int | None = None) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(make_read_file(ws))
    registry.register(make_list_files(ws))
    registry.register(make_search(ws))
    registry.register(make_edit_file(ws))
    registry.register(make_write_file(ws))
    registry.register(make_bash(ws, confirm_bash))
    registry.register(make_todo_write(ws))
    if client is not None and model:
        registry.register(make_subagent_tool(client, model, registry, log=log,
                                             context_window=context_window))
    return registry
