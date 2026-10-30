"""A scripted stand-in for ``openai.OpenAI`` used by every lesson test.

The builders return real ``openai`` response types so your code sees exactly the
attribute paths it would see from a live server.
"""
from __future__ import annotations

import copy
import json
import re
import time

import httpx2
import openai
from openai.types import CompletionUsage
from openai.types.chat import ChatCompletion, ChatCompletionChunk, ChatCompletionMessage
from openai.types.chat.chat_completion import Choice
from openai.types.chat.chat_completion_chunk import (
    Choice as ChunkChoice,
    ChoiceDelta,
    ChoiceDeltaToolCall,
    ChoiceDeltaToolCallFunction,
)
from openai.types.chat.chat_completion_message_tool_call import (
    ChatCompletionMessageToolCall,
    Function,
)

_URL = "http://fake/v1/chat/completions"
_AUTO_ID = re.compile(r"^call_\d+$")


def call(name: str, arguments: dict | str, id: str | None = None) -> dict:
    """One tool call spec. Dict arguments are JSON-encoded; a str is passed through as-is."""
    if not isinstance(arguments, str):
        arguments = json.dumps(arguments)
    return {"name": name, "arguments": arguments, "id": id}


def reply(
    content: str | None = None,
    tool_calls: list[dict] | None = None,
    reasoning: str | None = None,
    prompt_tokens: int = 100,
    completion_tokens: int = 20,
    finish_reason: str | None = None,
) -> ChatCompletion:
    """Build a ChatCompletion. Calls without an id get ``call_1``, ``call_2``, ... (renumbered
    across the whole script by FakeClient so ids stay unique). ``reasoning`` is stored in the
    message's extra field ``reasoning_content``."""
    tcs = [
        ChatCompletionMessageToolCall(
            id=spec.get("id") or f"call_{i + 1}",
            type="function",
            function=Function(name=spec["name"], arguments=spec["arguments"]),
        )
        for i, spec in enumerate(tool_calls or [])
    ] or None
    extra = {"reasoning_content": reasoning} if reasoning is not None else {}
    message = ChatCompletionMessage(role="assistant", content=content, tool_calls=tcs, **extra)
    if finish_reason is None:
        finish_reason = "tool_calls" if tcs else "stop"
    return ChatCompletion(
        id="chatcmpl-fake",
        object="chat.completion",
        created=int(time.time()),
        model="fake-model",
        choices=[Choice(index=0, finish_reason=finish_reason, message=message)],
        usage=CompletionUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
    )


def to_chunks(completion: ChatCompletion, text_chunk_size: int = 5) -> list[ChatCompletionChunk]:
    """Split a completion into streaming chunks: role, reasoning/content deltas, tool calls
    (first chunk carries index/id/name with empty arguments, then argument fragments), a chunk
    with ``finish_reason``, and finally a chunk with ``choices == []`` carrying ``usage`` (this
    is what real servers send; guard ``chunk.choices`` before indexing it)."""
    choice = completion.choices[0]
    msg = choice.message

    def chunk(delta: ChoiceDelta, finish: str | None = None) -> ChatCompletionChunk:
        return ChatCompletionChunk(
            id=completion.id,
            object="chat.completion.chunk",
            created=completion.created,
            model=completion.model,
            choices=[ChunkChoice(index=0, delta=delta, finish_reason=finish)],
        )

    def pieces(text: str) -> list[str]:
        return [text[i : i + text_chunk_size] for i in range(0, len(text), text_chunk_size)]

    out = [chunk(ChoiceDelta(role="assistant", content=""))]
    reasoning = getattr(msg, "reasoning_content", None)
    for p in pieces(reasoning or ""):
        out.append(chunk(ChoiceDelta(reasoning_content=p)))
    for p in pieces(msg.content or ""):
        out.append(chunk(ChoiceDelta(content=p)))
    for i, tc in enumerate(msg.tool_calls or []):
        out.append(chunk(ChoiceDelta(tool_calls=[ChoiceDeltaToolCall(
            index=i, id=tc.id, type="function",
            function=ChoiceDeltaToolCallFunction(name=tc.function.name, arguments=""),
        )])))
        for p in pieces(tc.function.arguments):
            out.append(chunk(ChoiceDelta(tool_calls=[ChoiceDeltaToolCall(
                index=i, function=ChoiceDeltaToolCallFunction(arguments=p),
            )])))
    out.append(chunk(ChoiceDelta(), finish=choice.finish_reason))
    # Real servers (OpenAI, LM Studio) send usage in one extra trailing chunk with NO choices.
    out.append(ChatCompletionChunk(
        id=completion.id, object="chat.completion.chunk", created=completion.created,
        model=completion.model, choices=[], usage=completion.usage,
    ))
    return out


def bad_request(message: str) -> openai.BadRequestError:
    request = httpx2.Request("POST", _URL)
    response = httpx2.Response(400, request=request, json={"error": {"message": message}})
    return openai.BadRequestError(message, response=response, body={"message": message})


def connection_error() -> openai.APIConnectionError:
    return openai.APIConnectionError(request=httpx2.Request("POST", _URL))


def _renumber(script: list) -> None:
    """Give auto-generated tool call ids (``call_N``) script-wide unique numbers."""
    n = 0
    for item in script:
        if isinstance(item, ChatCompletion):
            for tc in item.choices[0].message.tool_calls or []:
                if _AUTO_ID.match(tc.id):
                    n += 1
                    tc.id = f"call_{n}"
        elif isinstance(item, list):
            for ch in item:
                for choice in ch.choices:
                    for tc in choice.delta.tool_calls or []:
                        if tc.id and _AUTO_ID.match(tc.id):
                            n += 1
                            tc.id = f"call_{n}"


class _Completions:
    def __init__(self, client: "FakeClient"):
        self._client = client

    def create(self, **kwargs):
        c = self._client
        c.requests.append(copy.deepcopy(kwargs))
        if not c.script:
            raise AssertionError("FakeClient ran out of scripted responses")
        item = c.script.pop(0)
        if isinstance(item, Exception):
            raise item
        if kwargs.get("stream") and isinstance(item, ChatCompletion):
            return iter(to_chunks(item))
        if isinstance(item, list):
            return iter(item)
        return item


class _Chat:
    def __init__(self, client: "FakeClient"):
        self.completions = _Completions(client)


class FakeClient:
    """Drop-in for ``openai.OpenAI``: ``client.chat.completions.create(**kwargs)`` pops the next
    scripted item and records the request in ``.requests``."""

    def __init__(self, script: list[ChatCompletion | list[ChatCompletionChunk] | Exception]):
        self.script = list(script)
        _renumber(self.script)
        self.requests: list[dict] = []
        self.chat = _Chat(self)
