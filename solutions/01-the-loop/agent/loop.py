"""The agent loop: ask the model, run the tools it requests, repeat."""
from __future__ import annotations

import time
from dataclasses import dataclass

from .log import RequestLog
from .messages import Usage, message_to_dict
from .tools.registry import ToolRegistry


@dataclass
class TurnResult:
    final_text: str
    stop_reason: str  # "done" in lesson 1
    turns: int
    usage: Usage
    error: str | None = None


class Agent:
    def __init__(self, client, model: str, tools: ToolRegistry, *,
                 system: str | None = None, log: RequestLog | None = None):
        self.client = client
        self.model = model
        self.tools = tools
        self.log = log
        self.messages: list[dict] = []
        if system:
            self.messages.append({"role": "system", "content": system})

    def run(self, user_message: str) -> TurnResult:
        self.messages.append({"role": "user", "content": user_message})
        usage = Usage()
        turns = 0
        while True:
            completion = self._request()
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

    def _request(self):
        """Make one model request and log it."""
        kwargs = {"model": self.model, "messages": self.messages,
                  "tools": self.tools.schemas()}
        start = time.monotonic()
        completion = self.client.chat.completions.create(**kwargs)
        if self.log:
            self.log.record(kwargs, completion.model_dump(), time.monotonic() - start)
        return completion

    def _run_tool_call(self, tool_call) -> str:
        """Run one tool call and return the result text."""
        fn = tool_call.function
        return self.tools.dispatch(fn.name, fn.arguments)
