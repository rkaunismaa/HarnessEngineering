import json

import openai
import pytest

from testing.fake_model import (
    FakeClient,
    bad_request,
    call,
    connection_error,
    reply,
    to_chunks,
)


def test_reply_with_tool_call_shape():
    c = reply(tool_calls=[call("read_file", {"path": "a.txt"})])
    m = c.choices[0].message
    assert c.choices[0].finish_reason == "tool_calls"
    assert m.tool_calls[0].function.name == "read_file"
    assert json.loads(m.tool_calls[0].function.arguments) == {"path": "a.txt"}


def test_reply_defaults_and_usage():
    c = reply(content="hi", prompt_tokens=7, completion_tokens=3)
    assert c.choices[0].finish_reason == "stop"
    assert c.choices[0].message.content == "hi"
    assert c.choices[0].message.tool_calls is None
    assert c.usage.prompt_tokens == 7
    assert c.usage.completion_tokens == 3
    assert c.usage.total_tokens == 10


def test_reasoning_is_extra_field():
    m = reply(content="hi", reasoning="thinking").choices[0].message
    assert m.reasoning_content == "thinking"


def test_string_arguments_pass_through():
    c = reply(tool_calls=[call("t", "{not json")])
    assert c.choices[0].message.tool_calls[0].function.arguments == "{not json"


def test_client_assigns_sequential_ids():
    fc = FakeClient([reply(tool_calls=[call("a", {}), call("b", {})])])
    r = fc.chat.completions.create(model="m", messages=[])
    assert [t.id for t in r.choices[0].message.tool_calls] == ["call_1", "call_2"]


def test_explicit_id_is_kept():
    c = reply(tool_calls=[call("a", {}, id="abc")])
    assert c.choices[0].message.tool_calls[0].id == "abc"


def test_client_records_and_pops():
    fc = FakeClient([reply(content="one"), reply(content="two")])
    msgs = [{"role": "user", "content": "x"}]
    r = fc.chat.completions.create(model="m", messages=msgs)
    assert r.choices[0].message.content == "one"
    assert fc.requests[0]["model"] == "m"
    msgs.append({"role": "assistant", "content": "later mutation"})
    assert len(fc.requests[0]["messages"]) == 1  # deep copy
    assert fc.chat.completions.create(model="m", messages=[]).choices[0].message.content == "two"


def test_client_exhausted():
    with pytest.raises(AssertionError, match="ran out"):
        FakeClient([]).chat.completions.create(model="m", messages=[])


def test_stream_reassembles():
    full = reply(
        content="hello streaming world",
        reasoning="let me think",
        tool_calls=[call("read_file", {"path": "a.txt"}), call("bash", {"command": "ls"})],
        prompt_tokens=11,
        completion_tokens=5,
    )
    fc = FakeClient([full])
    chunks = list(fc.chat.completions.create(model="m", messages=[], stream=True))
    assert len(chunks) > 3
    text, reasoning = "", ""
    calls = {}
    for ch in chunks[:-2]:
        d = ch.choices[0].delta
        text += d.content or ""
        reasoning += getattr(d, "reasoning_content", None) or ""
        for tc in d.tool_calls or []:
            slot = calls.setdefault(tc.index, {"id": None, "name": None, "args": ""})
            slot["id"] = tc.id or slot["id"]
            slot["name"] = tc.function.name or slot["name"]
            slot["args"] += tc.function.arguments or ""
        assert ch.choices[0].finish_reason is None
    assert text == "hello streaming world"
    assert reasoning == "let me think"
    assert calls[0]["id"] == "call_1" and calls[0]["name"] == "read_file"
    assert json.loads(calls[0]["args"]) == {"path": "a.txt"}
    assert json.loads(calls[1]["args"]) == {"command": "ls"}
    assert chunks[-2].choices[0].finish_reason == "tool_calls"
    usage_chunk = chunks[-1]  # like real servers: usage rides on a trailing chunk with no choices
    assert usage_chunk.choices == []
    assert usage_chunk.usage.prompt_tokens == 11
    assert usage_chunk.usage.completion_tokens == 5


def test_tool_call_first_chunk_has_empty_arguments():
    chunks = to_chunks(reply(tool_calls=[call("read_file", {"path": "a.txt"})]))
    first = next(c.choices[0].delta.tool_calls[0] for c in chunks
                 if c.choices and c.choices[0].delta.tool_calls)
    assert (first.index, first.id, first.function.name, first.function.arguments) == (
        0, "call_1", "read_file", "")


def test_prebuilt_chunk_list_is_returned_for_streaming():
    chunks = to_chunks(reply(content="abc"))
    fc = FakeClient([chunks])
    assert list(fc.chat.completions.create(model="m", messages=[], stream=True)) == chunks


def test_scripted_exception_is_raised():
    fc = FakeClient([connection_error()])
    with pytest.raises(openai.APIConnectionError):
        fc.chat.completions.create(model="m", messages=[])


def test_bad_request_error():
    fc = FakeClient([bad_request("context length exceeded")])
    with pytest.raises(openai.BadRequestError) as ei:
        fc.chat.completions.create(model="m", messages=[])
    assert ei.value.status_code == 400
    assert "context length exceeded" in str(ei.value)
