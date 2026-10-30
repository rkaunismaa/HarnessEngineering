"""The default tool set."""
from __future__ import annotations

from typing import Callable

from ..workspace import Workspace
from .files import make_edit_file, make_list_files, make_read_file, make_search, make_write_file
from .registry import Tool, ToolRegistry
from .shell import make_bash
from .todo import make_todo_write

__all__ = ["Tool", "ToolRegistry", "make_default_tools"]


def make_default_tools(ws: Workspace, *,
                       confirm_bash: Callable[[str], bool] | None = None) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(make_read_file(ws))
    registry.register(make_list_files(ws))
    registry.register(make_search(ws))
    registry.register(make_edit_file(ws))
    registry.register(make_write_file(ws))
    registry.register(make_bash(ws, confirm_bash))
    registry.register(make_todo_write(ws))
    return registry
