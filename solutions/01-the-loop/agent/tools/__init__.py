"""The default tool set."""
from __future__ import annotations

from ..workspace import Workspace
from .files import make_read_file
from .registry import Tool, ToolRegistry

__all__ = ["Tool", "ToolRegistry", "make_default_tools"]


def make_default_tools(ws: Workspace, **kwargs) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(make_read_file(ws))
    return registry
