"""The agent loop: ask the model, run the tools it requests, repeat."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Callable

import openai

from openai.types.chat import ChatCompletionMessageToolCall
from openai.types.chat.chat_completion_message_tool_call import Function

from .context import (ContextManager, compact, error_text, estimate_tokens,
                      is_context_overflow, trim_old_tool_results)
from .events import AgentEvents
from .log import RequestLog
from .messages import Usage, message_to_dict
from .permissions import Approver, Decision, PermissionPolicy
from .stream import accumulate
from .tools.registry import ToolRegistry, truncate, validate_args
from .workspace import Workspace


LOOP_THRESHOLD = 3
LOOP_MESSAGE = ("Error: you have made this exact call "
                f"{LOOP_THRESHOLD} times in a row. Try a different approach.")
DENIED_BY_RULE = "Error: this call is blocked by a deny rule."
DENIED_BY_USER = "Error: the user denied this tool call."
NO_APPROVER = "Error: this call needs approval but no approver is available."
INTERRUPTED = "Error: interrupted by the user."
CHECK_FAILED = "[Automatic check failed]\n{output}\nFix the problem, then finish."


@dataclass
class TurnResult:
    final_text: str
    stop_reason: str  # "done", "max_turns", "error" or "interrupted"
    turns: int
    usage: Usage
    error: str | None = None
    verified: bool | None = None  # the last automatic check passed; None: no check ran


class Agent:
    def __init__(self, client, model: str, tools: ToolRegistry, *,
                 system: str | None = None, log: RequestLog | None = None, max_turns: int = 50,
                 permissions: PermissionPolicy | None = None, approver: Approver | None = None,
                 workspace: Workspace | None = None,
                 events: AgentEvents | None = None, stream: bool = False,
                 context: ContextManager | None = None,
                 verify: Callable[[], tuple[bool, str]] | None = None,
                 max_verify_attempts: int = 2,
                 sampling: dict | None = None):
        self.client = client
        self.model = model
        self.tools = tools
        self.permissions = permissions  # None: every call runs (no permission checks)
        self.approver = approver
        self.workspace = workspace  # lets path rules match the normalized path
        self.log = log
        self.sampling = dict(sampling or {})  # temperature, top_p, seed; empty: server defaults
        self.events = events or AgentEvents()
        self.stream = stream
        self.context = context  # None: the history is sent as it is
        self.max_turns = max_turns
        self.verify = verify  # None: a reply without tool calls ends the run unchecked
        self.max_verify_attempts = max_verify_attempts
        self._last_call: tuple[str, str] | None = None
        self._repeats = 0
        self.messages: list[dict] = []
        if system:
            self.messages.append({"role": "system", "content": system})

    def run(self, user_message: str) -> TurnResult:
        self.messages.append({"role": "user", "content": user_message})
        usage = Usage()
        turns = 0
        failed_checks = 0
        verified: bool | None = None
        self._last_call, self._repeats = None, 0
        try:
            while turns < self.max_turns:
                try:
                    message, tool_calls, turn_usage = self._ask_model()
                except openai.APIError as exc:
                    return TurnResult("", "error", turns, usage, f"Model request failed: {error_text(exc)}")
                turns += 1
                if turn_usage:
                    usage += turn_usage
                self.messages.append(message)
                if not tool_calls:
                    if self.verify is None:
                        return TurnResult(message["content"] or "", "done", turns, usage)
                    verified, output = self.verify()
                    self.events.on_verify(verified, output)
                    if verified:
                        break
                    failed_checks += 1
                    if failed_checks >= self.max_verify_attempts:
                        break
                    self.messages.append({"role": "user",
                                          "content": CHECK_FAILED.format(output=truncate(output))})
                    continue
                for tc in tool_calls:
                    self.messages.append({"role": "tool", "tool_call_id": tc.id,
                                          "content": self._run_tool_call(tc)})
            else:
                return TurnResult("", "max_turns", turns, usage, verified=verified)
            return TurnResult(message["content"] or "", "done", turns, usage, verified=verified)
        except KeyboardInterrupt:
            self._repair_history()
            return TurnResult("", "interrupted", turns, usage)

    def _ask_model(self):
        """One model request. Returns ``(message_dict, tool_calls, usage or None)``. With a
        context manager: old tool results are trimmed and the history compacted first, and a
        context-overflow rejection is answered by compacting and asking once more."""
        if self.context is None:
            return self._ask_once()
        self._prepare_context()
        try:
            return self._ask_once()
        except openai.BadRequestError as exc:
            if not is_context_overflow(exc):
                raise
            self._compact()
            return self._ask_once()

    def _prepare_context(self) -> None:
        ctx = self.context
        before = estimate_tokens(self.messages)
        trimmed = trim_old_tool_results(self.messages, ctx.keep_recent)
        if trimmed != self.messages:  # permanent: the model never sees the dropped text again
            self.messages = trimmed
            ctx.shrank(before - estimate_tokens(trimmed), len(trimmed))
        if ctx.needs_compaction(self.messages):
            self._compact()

    def _compact(self) -> None:
        before = estimate_tokens(self.messages)
        log = self.log.with_agent("compact") if self.log else None
        self.messages = compact(self.messages, self.client, self.model,
                                self.context.keep_recent, log=log)
        self.context.reset()
        self.events.on_compact(before, estimate_tokens(self.messages))

    def _ask_once(self):
        sent = len(self.messages)
        if not self.stream:
            completion = self._request()
            message = completion.choices[0].message
            usage = completion.usage
            result = (message_to_dict(message), message.tool_calls or [],
                      Usage(usage.prompt_tokens, usage.completion_tokens) if usage else None)
        else:
            message, usage = self._request_stream()
            tool_calls = [ChatCompletionMessageToolCall(
                id=tc["id"], type="function",
                function=Function(name=tc["function"]["name"],
                                  arguments=tc["function"]["arguments"]))
                for tc in message.get("tool_calls", [])]
            result = (message, tool_calls, usage)
        if self.context:
            usage = result[2]
            self.context.observe(usage.prompt_tokens if usage else None, sent)
        return result

    def _repair_history(self) -> None:
        """After an interrupt: answer every tool call that has no result, so the history is
        valid for the next request. (A partially streamed reply was never added.)"""
        for i in range(len(self.messages) - 1, -1, -1):
            msg = self.messages[i]
            if msg["role"] == "assistant":
                answered = {m["tool_call_id"] for m in self.messages[i + 1:]
                            if m["role"] == "tool"}
                for tc in msg.get("tool_calls") or []:
                    if tc["id"] not in answered:
                        self.messages.append({"role": "tool", "tool_call_id": tc["id"],
                                              "content": INTERRUPTED})
                return

    def _request(self):
        """Make one model request and log it."""
        kwargs = {"model": self.model, "messages": self.messages,
                  "tools": self.tools.schemas(), **self.sampling}
        start = time.monotonic()
        completion = self.client.chat.completions.create(**kwargs)
        if self.log:
            self.log.record(kwargs, completion.model_dump(), time.monotonic() - start)
        return completion

    def _request_stream(self):
        """One streamed model request: returns ``(message_dict, usage or None)``."""
        kwargs = {"model": self.model, "messages": self.messages,
                  "tools": self.tools.schemas(), **self.sampling, "stream": True,
                  "stream_options": {"include_usage": True}}
        start = time.monotonic()
        try:
            message, usage, finish = accumulate(self.client.chat.completions.create(**kwargs),
                                                self.events)
        except KeyboardInterrupt as exc:
            partial = getattr(exc, "partial", None)
            if self.log:
                self.log.record(kwargs, {"streamed": True, "interrupted": True,
                                         "message": partial.message() if partial else None,
                                         "usage": None, "finish_reason": None},
                                time.monotonic() - start)
            raise
        if self.log:
            self.log.record(kwargs, {"streamed": True, "message": message,
                                     "usage": None if usage is None else vars(usage),
                                     "finish_reason": finish}, time.monotonic() - start)
        return message, usage

    def _run_tool_call(self, tool_call) -> str:
        """Run one tool call, telling the events about it, and return the result text."""
        fn = tool_call.function
        self.events.on_tool_call(fn.name, fn.arguments)
        result = self._execute_tool_call(tool_call)
        self.events.on_tool_result(fn.name, result)
        return result

    def _execute_tool_call(self, tool_call) -> str:
        """A call identical to the previous ``LOOP_THRESHOLD - 1`` calls is refused instead of
        executed."""
        fn = tool_call.function
        key = (fn.name, fn.arguments)
        self._repeats = self._repeats + 1 if key == self._last_call else 1
        self._last_call = key
        if self._repeats >= LOOP_THRESHOLD:
            return LOOP_MESSAGE
        refusal = self._permission_refusal(fn.name, fn.arguments)
        if refusal:
            return refusal
        return self.tools.dispatch(fn.name, fn.arguments)

    def _permission_refusal(self, name: str, raw_arguments: str) -> str | None:
        """None if the call may run; otherwise the error result to send instead. Calls that
        dispatch would reject anyway (unknown tool, bad arguments) are left to dispatch."""
        if self.permissions is None:
            return None
        tool = self.tools.get(name)
        if tool is None:
            return None
        try:
            args = json.loads(raw_arguments)
        except json.JSONDecodeError:
            return None
        if not isinstance(args, dict) or validate_args(tool.parameters, args):
            return None
        decision = self.permissions.check(tool, args, self.workspace)
        if decision == Decision.ALLOW:
            return None
        if decision == Decision.DENY:
            return DENIED_BY_RULE
        if self.approver is None:
            return NO_APPROVER
        answer = self.approver(name, args)
        if answer == "always":
            self.permissions.remember(tool, args)
            return None
        if answer == "yes":
            return None
        return DENIED_BY_USER
