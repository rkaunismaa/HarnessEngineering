"""Assemble a streamed chat completion into one assistant message."""
from __future__ import annotations

from typing import Iterable

from openai.types.chat import ChatCompletionChunk

from .events import AgentEvents
from .messages import Usage


class _Partial:
    """What has been received so far; also builds the final message dict."""

    def __init__(self) -> None:
        self.text: list[str] = []
        self.calls: dict[int, dict] = {}
        self.usage: Usage | None = None
        self.finish_reason: str | None = None

    def message(self) -> dict:
        out: dict = {"role": "assistant", "content": "".join(self.text) or None}
        if self.calls:
            out["tool_calls"] = [self.calls[i] for i in sorted(self.calls)]
        return out


def accumulate(chunks: Iterable[ChatCompletionChunk],
               events: AgentEvents) -> tuple[dict, Usage | None, str | None]:
    """Consume a chunk stream; return ``(message_dict, usage, finish_reason)``.

    The message has the same shape ``message_to_dict`` produces. If the stream is cut short by
    ``KeyboardInterrupt``, the exception carries what arrived as ``exc.partial`` (a ``_Partial``).
    """
    state = _Partial()
    try:
        for chunk in chunks:
            if chunk.usage:  # arrives in a trailing chunk whose ``choices`` is empty
                state.usage = Usage(chunk.usage.prompt_tokens, chunk.usage.completion_tokens)
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                events.on_reasoning(reasoning)
            if delta.content:
                state.text.append(delta.content)
                events.on_text(delta.content)
            for tc in delta.tool_calls or []:
                call = state.calls.setdefault(tc.index, {
                    "id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                if tc.id:
                    call["id"] = tc.id
                if tc.function:
                    if tc.function.name:
                        call["function"]["name"] += tc.function.name
                    if tc.function.arguments:
                        call["function"]["arguments"] += tc.function.arguments
            if choice.finish_reason:
                state.finish_reason = choice.finish_reason
    except KeyboardInterrupt as exc:
        exc.partial = state  # type: ignore[attr-defined]
        raise
    return state.message(), state.usage, state.finish_reason
