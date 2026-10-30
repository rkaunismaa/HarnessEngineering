"""Message and token-usage helpers."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(self.prompt_tokens + other.prompt_tokens,
                     self.completion_tokens + other.completion_tokens)


def message_to_dict(msg) -> dict:
    """Turn an SDK assistant message into a plain dict for the history.

    ``reasoning_content`` is deliberately not kept.
    """
    out: dict = {"role": "assistant", "content": msg.content}
    if msg.tool_calls:
        out["tool_calls"] = [
            {"id": tc.id, "type": "function",
             "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
            for tc in msg.tool_calls
        ]
    return out
