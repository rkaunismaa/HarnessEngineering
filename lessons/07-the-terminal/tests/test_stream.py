import json

import pytest

from agent.events import AgentEvents
from agent.loop import Agent
from agent.messages import Usage, message_to_dict
from agent.stream import accumulate
from agent.tools import make_default_tools
from agent.workspace import Workspace
from openai.types.chat import ChatCompletionChunk
from openai.types.chat.chat_completion_chunk import (
    Choice as ChunkChoice, ChoiceDelta, ChoiceDeltaToolCall, ChoiceDeltaToolCallFunction)
from testing.fake_model import FakeClient, call, reply, to_chunks


class Recorder(AgentEvents):
    def __init__(self):
        self.events = []

    def on_text(self, delta):
        self.events.append(("text", delta))

    def on_reasoning(self, delta):
        self.events.append(("reasoning", delta))

    def on_tool_call(self, name, arguments):
        self.events.append(("tool_call", name, arguments))

    def on_tool_result(self, name, result):
        self.events.append(("tool_result", name, result))

    def of(self, kind):
        return [e[1:] for e in self.events if e[0] == kind]


def chunk(delta, finish=None):
    return ChatCompletionChunk(id="x", object="chat.completion.chunk", created=0, model="m",
                               choices=[ChunkChoice(index=0, delta=delta, finish_reason=finish)])


def tc_delta(index, id=None, name=None, arguments=""):
    return ChoiceDeltaToolCall(index=index, id=id, type="function" if id else None,
                               function=ChoiceDeltaToolCallFunction(name=name, arguments=arguments))


def test_base_events_are_noops():
    events = AgentEvents()
    assert events.on_text("a") is None
    assert events.on_reasoning("a") is None
    assert events.on_tool_call("read_file", "{}") is None
    assert events.on_tool_result("read_file", "x") is None


def test_accumulate_text():
    rec = Recorder()
    chunks = to_chunks(reply(content="Hello there, friend"), text_chunk_size=4)
    message, usage, finish = accumulate(chunks, rec)
    assert message == {"role": "assistant", "content": "Hello there, friend"}
    assert "".join(d for (d,) in rec.of("text")) == "Hello there, friend"
    assert len(rec.of("text")) > 1  # delivered per delta, not once at the end
    assert finish == "stop"
    assert usage == Usage(100, 20)


def test_accumulate_tool_call_fragments():
    args = {"path": "some/long/file/name.txt", "offset": 10, "limit": 20}
    chunks = to_chunks(reply(tool_calls=[call("read_file", args)]), text_chunk_size=12)
    fragments = [c for c in chunks if c.choices and c.choices[0].delta.tool_calls
                 and c.choices[0].delta.tool_calls[0].function.arguments]
    assert len(fragments) >= 4
    message, _, finish = accumulate(chunks, Recorder())
    assert finish == "tool_calls"
    assert message["role"] == "assistant"
    assert not message["content"]
    [tc] = message["tool_calls"]
    assert tc["id"] == "call_1" and tc["type"] == "function"
    assert tc["function"]["name"] == "read_file"
    assert json.loads(tc["function"]["arguments"]) == args


def test_accumulate_two_tool_calls_interleaved_indexes():
    chunks = [
        chunk(ChoiceDelta(role="assistant", content="")),
        chunk(ChoiceDelta(tool_calls=[tc_delta(0, "call_a", "read_file")])),
        chunk(ChoiceDelta(tool_calls=[tc_delta(1, "call_b", "list_files")])),
        chunk(ChoiceDelta(tool_calls=[tc_delta(0, arguments='{"path"')])),
        chunk(ChoiceDelta(tool_calls=[tc_delta(1, arguments='{"path"')])),
        chunk(ChoiceDelta(tool_calls=[tc_delta(1, arguments=': "dir"}')])),
        chunk(ChoiceDelta(tool_calls=[tc_delta(0, arguments=': "a.txt"}')])),
        chunk(ChoiceDelta(), finish="tool_calls"),
    ]
    message, usage, finish = accumulate(chunks, Recorder())
    assert usage is None and finish == "tool_calls"
    first, second = message["tool_calls"]
    assert (first["id"], first["function"]["name"]) == ("call_a", "read_file")
    assert json.loads(first["function"]["arguments"]) == {"path": "a.txt"}
    assert (second["id"], second["function"]["name"]) == ("call_b", "list_files")
    assert json.loads(second["function"]["arguments"]) == {"path": "dir"}


def test_accumulate_reasoning_events():
    rec = Recorder()
    chunks = to_chunks(reply(content="42", reasoning="thinking hard"), text_chunk_size=5)
    message, _, _ = accumulate(chunks, rec)
    assert "".join(d for (d,) in rec.of("reasoning")) == "thinking hard"
    assert "".join(d for (d,) in rec.of("text")) == "42"
    assert message == {"role": "assistant", "content": "42"}  # reasoning is not kept


def test_accumulate_first_chunk_with_role_and_reasoning_together():
    rec = Recorder()
    chunks = [
        chunk(ChoiceDelta(role="assistant", content="", reasoning_content="hm")),
        chunk(ChoiceDelta(content="ok")),
        chunk(ChoiceDelta(), finish="stop"),
    ]
    message, _, _ = accumulate(chunks, rec)
    assert rec.of("reasoning") == [("hm",)]
    assert message["content"] == "ok"


def test_accumulate_usage_last_chunk():
    chunks = to_chunks(reply(content="hi", prompt_tokens=321, completion_tokens=7))
    assert chunks[-1].choices == []
    _, usage, finish = accumulate(chunks, Recorder())
    assert usage == Usage(321, 7)
    assert finish == "stop"


def make_agent(tmp_path, script, **kwargs):
    ws = Workspace(tmp_path)
    client = FakeClient(script)
    return Agent(client, "m", make_default_tools(ws), **kwargs), client


SCRIPT = lambda: [  # noqa: E731
    reply(content="Let me look.", tool_calls=[call("read_file", {"path": "a.txt"}),
                                              call("list_files", {})],
          reasoning="I should read it", prompt_tokens=50, completion_tokens=5),
    reply(content="It says hello", prompt_tokens=80, completion_tokens=6),
]


def test_stream_request_carries_sampling(tmp_path):
    (tmp_path / "a.txt").write_text("hello\n")
    agent, client = make_agent(tmp_path, SCRIPT(), stream=True, sampling={"top_p": 0.9})
    agent.run("go")
    assert all(req["top_p"] == 0.9 and req["stream"] for req in client.requests)


def test_stream_agent_matches_nonstream(tmp_path):
    (tmp_path / "a.txt").write_text("hello\n")
    plain, _ = make_agent(tmp_path, SCRIPT())
    streamed, client = make_agent(tmp_path, SCRIPT(), stream=True)
    r1, r2 = plain.run("go"), streamed.run("go")
    assert streamed.messages == plain.messages
    assert (r2.final_text, r2.stop_reason, r2.turns) == (r1.final_text, r1.stop_reason, r1.turns)
    assert r2.usage == r1.usage == Usage(130, 11)
    assert client.requests[0]["stream"] is True
    assert client.requests[0]["stream_options"] == {"include_usage": True}


def test_nonstream_requests_have_no_stream_args(tmp_path):
    agent, client = make_agent(tmp_path, [reply(content="hi")])
    agent.run("hello")
    assert "stream" not in client.requests[0]
    assert "stream_options" not in client.requests[0]


def test_streamed_log_entry(tmp_path):
    from agent.log import RequestLog, read_log
    log = RequestLog(tmp_path / "log.jsonl")
    agent, _ = make_agent(tmp_path, [reply(content="hi there")], stream=True, log=log)
    agent.run("hello")
    [entry] = read_log(log.path)
    assert entry["response"] == {
        "streamed": True, "message": {"role": "assistant", "content": "hi there"},
        "usage": {"prompt_tokens": 100, "completion_tokens": 20}, "finish_reason": "stop"}


@pytest.mark.parametrize("stream", [False, True])
def test_events_fire_for_tool_calls(tmp_path, stream):
    (tmp_path / "a.txt").write_text("hello\n")
    rec = Recorder()
    agent, _ = make_agent(tmp_path, [
        reply(tool_calls=[call("read_file", {"path": "a.txt"})]),
        reply(content="done"),
    ], events=rec, stream=stream)
    agent.run("go")
    assert rec.of("tool_call") == [("read_file", '{"path": "a.txt"}')]
    assert rec.of("tool_result") == [("read_file", "     1\thello")]
    kinds = [e[0] for e in rec.events]
    assert kinds.index("tool_call") < kinds.index("tool_result")


def test_events_fire_for_refused_calls(tmp_path):
    rec = Recorder()
    agent, _ = make_agent(tmp_path, [
        reply(tool_calls=[call("nope", {})]), reply(content="ok")], events=rec)
    agent.run("go")
    [(name, result)] = rec.of("tool_result")
    assert name == "nope" and result.startswith("Error: unknown tool")


def test_streamed_text_reaches_events_live(tmp_path):
    rec = Recorder()
    agent, _ = make_agent(tmp_path, [reply(content="abcdefghijkl")], events=rec, stream=True)
    agent.run("go")
    assert len(rec.of("text")) > 1


@pytest.mark.live
def test_live_stream_usage(tmp_path):
    from agent.client import make_client
    from agent.config import Config
    config = Config(base_url="http://localhost:1234/v1", model="qwen/qwen3.8-27b",
                    api_key="lm-studio")
    rec = Recorder()
    ws = Workspace(tmp_path)
    agent = Agent(make_client(config), config.model, make_default_tools(ws), events=rec,
                  stream=True, max_turns=3)
    result = agent.run("Reply with the single word: pong")
    print(f"\nstop={result.stop_reason} usage={result.usage} text={result.final_text!r} "
          f"text events={len(rec.of('text'))} reasoning events={len(rec.of('reasoning'))}")
    assert result.stop_reason in {"done", "max_turns", "error"}
    assert result.stop_reason == "done"
    assert result.usage.prompt_tokens > 0 and result.usage.completion_tokens > 0
    assert len(rec.of("text")) >= 1
