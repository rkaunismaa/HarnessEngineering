"""The agent loop: ask the model, run the tools it requests, repeat."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass

import openai

from .log import RequestLog
from .messages import Usage, message_to_dict
from .permissions import Approver, Decision, PermissionPolicy
from .tools.registry import ToolRegistry, validate_args
from .workspace import Workspace


LOOP_THRESHOLD = 3
LOOP_MESSAGE = ("Error: you have made this exact call "
                f"{LOOP_THRESHOLD} times in a row. Try a different approach.")
DENIED_BY_RULE = "Error: this call is blocked by a deny rule."
DENIED_BY_USER = "Error: the user denied this tool call."
NO_APPROVER = "Error: this call needs approval but no approver is available."


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
                 permissions: PermissionPolicy | None = None, approver: Approver | None = None,
                 workspace: Workspace | None = None):
        self.client = client
        self.model = model
        self.tools = tools
        self.permissions = permissions  # None: every call runs (no permission checks)
        self.approver = approver
        self.workspace = workspace  # lets path rules match the normalized path
        self.log = log
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
                  "tools": self.tools.schemas()}
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
