"""Hooks the agent calls while it works, so a UI can show progress as it happens."""
from __future__ import annotations


class AgentEvents:
    """Subclass and override what you need. Every method does nothing by default."""

    def on_text(self, delta: str) -> None:
        """A piece of the assistant's reply text (streaming only)."""

    def on_reasoning(self, delta: str) -> None:
        """A piece of the model's reasoning (streaming only)."""

    def on_tool_call(self, name: str, arguments: str) -> None:
        """A tool call is about to be handled. ``arguments`` is the raw JSON string."""

    def on_tool_result(self, name: str, result: str) -> None:
        """A tool call finished (or was refused); ``result`` is what the model will see."""

    def on_compact(self, before: int, after: int) -> None:
        """The history was summarized: estimated tokens before and after."""

    def on_verify(self, passed: bool, output: str) -> None:
        """The automatic check ran after a reply without tool calls."""
