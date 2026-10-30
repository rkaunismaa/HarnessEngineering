"""Keeping the conversation inside the context window."""
from __future__ import annotations

import json
import math
import time

from .tools.registry import truncate

SUMMARY_PREFIX = "[Summary of earlier conversation]\n"
SUMMARY_PROMPT = (
    "You are summarizing the earlier part of a conversation between a user and a coding "
    "agent, so the agent can continue the work from your summary alone. Write a concise "
    "summary covering: the user's goals; decisions made and why; files read, created or "
    "changed; the current state of the work and what remains to be done. Keep exact file "
    "names, commands and error messages that matter. Reply with the summary only.")
MAX_TRANSCRIPT_CHARS = 60_000  # keep the summary request itself well inside the window
MAX_MESSAGE_CHARS = 2_000


def error_text(exc) -> str:
    """Everything an API error says, each piece once. Usually ``str(exc)`` already contains the
    body; LM Studio's is just ``Error code: 400``, with the wording only in the parsed ``body``
    and the raw response text."""
    text = str(exc)
    extras = [str(getattr(exc, "body", "") or "")]
    try:
        extras.append(exc.response.text)
    except Exception:
        pass
    for extra in extras:
        if extra and extra not in text:
            text = f"{text} {extra}"
    return text


def is_context_overflow(exc) -> bool:
    """Did the server reject the request for being larger than its context window?"""
    return "context" in error_text(exc).lower()


def estimate_tokens(messages: list[dict]) -> int:
    """A rough count: about four characters per token. ``usage`` from the server is exact."""
    return math.ceil(len(json.dumps(messages)) / 4)


def trim_old_tool_results(messages: list[dict], keep_recent: int = 6,
                          min_chars: int = 500) -> list[dict]:
    """A new list in which long tool results older than the last ``keep_recent`` messages are
    replaced by a one-line note. The input list and its messages are not modified."""
    cutoff = len(messages) - keep_recent
    out = []
    for i, msg in enumerate(messages):
        content = msg.get("content")
        if (i < cutoff and msg.get("role") == "tool" and isinstance(content, str)
                and len(content) > min_chars):
            msg = {**msg, "content": f"[old tool result removed: {len(content)} characters]"}
        out.append(msg)
    return out


def split_index(messages: list[dict], keep_recent: int) -> int:
    """Where the kept tail starts: ``keep_recent`` messages from the end, moved backward until
    it is a user or assistant message, so a tool result never loses its assistant message."""
    low = 1 if messages and messages[0].get("role") == "system" else 0
    i = max(low, min(len(messages) - 1, len(messages) - keep_recent))  # keep at least one
    while i > low and messages[i].get("role") not in ("user", "assistant"):
        i -= 1
    return i


def _transcript(messages: list[dict]) -> str:
    lines = []
    for msg in messages:
        text = msg.get("content") or ""
        if isinstance(text, list):
            text = json.dumps(text)
        for tc in msg.get("tool_calls") or []:
            fn = tc["function"]
            text += f"\n[called {fn['name']}({fn['arguments']})]"
        lines.append(f"{msg['role']}: {truncate(text, MAX_MESSAGE_CHARS)}")
    out = "\n\n".join(lines)
    if len(out) > MAX_TRANSCRIPT_CHARS:
        out = "[earlier part omitted]\n" + out[-MAX_TRANSCRIPT_CHARS:]
    return out


def compact(messages: list[dict], client, model: str, keep_recent: int = 6,
            log=None) -> list[dict]:
    """Replace the older part of the conversation with a model-written summary.

    ``messages[0]`` is kept when it is the system message. Everything between it and
    ``split_index`` is summarized by one request without tools (logged to ``log`` if given).
    If the first kept message is from the user, the summary is put in front of its text."""
    head = messages[:1] if messages and messages[0].get("role") == "system" else []
    i = split_index(messages, keep_recent)
    old = messages[len(head):i]
    if not old:
        return list(messages)
    request = {"model": model, "messages": [
        {"role": "system", "content": SUMMARY_PROMPT},
        {"role": "user", "content": _transcript(old)}]}
    start = time.monotonic()
    completion = client.chat.completions.create(**request)
    if log:
        log.record(request, completion.model_dump(), time.monotonic() - start)
    text = (completion.choices[0].message.content or "").strip()
    tail = list(messages[i:])
    if tail and tail[0].get("role") == "user":
        tail[0] = {**tail[0], "content": f"{SUMMARY_PREFIX}{text}\n\n{tail[0]['content']}"}
        return head + tail
    return head + [{"role": "user", "content": SUMMARY_PREFIX + text}] + tail


class ContextManager:
    def __init__(self, window: int, threshold: float = 0.8, keep_recent: int = 6):
        self.window = window
        self.threshold = threshold
        self.keep_recent = keep_recent
        self.last_prompt_tokens: int | None = None
        self._counted: int | None = None  # messages the last request contained

    def observe(self, prompt_tokens: int | None, message_count: int) -> None:
        """Record the server's prompt token count for a request that had ``message_count``
        messages. ``None`` (no usage reported) goes back to estimating."""
        self.last_prompt_tokens = prompt_tokens
        self._counted = message_count

    def needs_compaction(self, messages: list[dict]) -> bool:
        if self.last_prompt_tokens is None:
            used = estimate_tokens(messages)
        else:
            counted = len(messages) if self._counted is None else self._counted
            used = self.last_prompt_tokens
            if len(messages) > counted:
                used += estimate_tokens(messages[counted:])
        return used > self.threshold * self.window

    def shrank(self, tokens_saved_estimate: int, new_count: int) -> None:
        """The history was trimmed: the last exact count is now too high by about this much."""
        if self.last_prompt_tokens is not None:
            self.last_prompt_tokens = max(0, self.last_prompt_tokens - tokens_saved_estimate)
            self._counted = new_count

    def reset(self) -> None:
        """The history was replaced (compacted): there is no exact count until the next reply."""
        self.last_prompt_tokens = None
        self._counted = None
