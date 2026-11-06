"""The agent loop: ask the model, run the tools it requests, repeat."""
from __future__ import annotations

import time
from dataclasses import dataclass

import openai

from .log import RequestLog
from .messages import Usage, message_to_dict
from .tools.registry import ToolRegistry


LOOP_THRESHOLD = 3
LOOP_MESSAGE = ("Error: you have made this exact call "
                f"{LOOP_THRESHOLD} times in a row. Try a different approach.")


@dataclass
class TurnResult:
    final_text: str
    stop_reason: str  # "done", "max_turns" or "error"
    turns: int
    usage: Usage
    error: str | None = None


class Agent:
    def __init__(self, client, model: str, tools: ToolRegistry, *,
                 system: str | None = None, log: RequestLog | None = None, max_turns: int = 50,
                 sampling: dict | None = None):
        self.client = client
        self.model = model
        self.tools = tools
        self.log = log
        self.sampling = dict(sampling or {})  # temperature, top_p, seed; empty: server defaults
        self.max_turns = max_turns
        self._last_call: tuple[str, str] | None = None
        self._repeats = 0
        self.messages: list[dict] = []
        if system:
            self.messages.append({"role": "system", "content": system})

    def run(self, user_message: str) -> TurnResult:
        self.messages.append({"role": "user", "content": user_message})
        usage = Usage()
        turns = 0
        self._last_call, self._repeats = None, 0
        while turns < self.max_turns:
            try:
                completion = self._request()
            except openai.APIError as exc:
                return TurnResult("", "error", turns, usage, f"Model request failed: {exc}")
            turns += 1
            if completion.usage:
                usage += Usage(completion.usage.prompt_tokens, completion.usage.completion_tokens)
            message = completion.choices[0].message
            self.messages.append(message_to_dict(message))
            if not message.tool_calls:
                return TurnResult(message.content or "", "done", turns, usage)
            for tc in message.tool_calls:
                self.messages.append({"role": "tool", "tool_call_id": tc.id,
                                      "content": self._run_tool_call(tc)})
        return TurnResult("", "max_turns", turns, usage)

    def _request(self):
        """Make one model request and log it."""
        kwargs = {"model": self.model, "messages": self.messages,
                  "tools": self.tools.schemas(), **self.sampling}
        start = time.monotonic()
        completion = self.client.chat.completions.create(**kwargs)
        if self.log:
            self.log.record(kwargs, completion.model_dump(), time.monotonic() - start)
        return completion

    def _run_tool_call(self, tool_call) -> str:
        """Run one tool call and return the result text. A call identical to the previous
        ``LOOP_THRESHOLD - 1`` calls is refused instead of executed."""
        fn = tool_call.function
        key = (fn.name, fn.arguments)
        self._repeats = self._repeats + 1 if key == self._last_call else 1
        self._last_call = key
        if self._repeats >= LOOP_THRESHOLD:
            return LOOP_MESSAGE
        return self.tools.dispatch(fn.name, fn.arguments)
