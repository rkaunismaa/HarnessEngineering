from agent.loop import Agent
from agent.tools.registry import Tool, ToolRegistry
from openai.types.chat import ChatCompletionChunk
from testing.fake_model import FakeClient, call, reply, to_chunks

INTERRUPTED = "Error: interrupted by the user."


def make_tools(*, interrupt_on=None):
    ran = []

    def fn(tag):
        ran.append(tag)
        if tag == interrupt_on:
            raise KeyboardInterrupt
        return f"ran {tag}"

    tools = ToolRegistry()
    tools.register(Tool("work", "do work", {"type": "object", "properties": {
        "tag": {"type": "string"}}, "required": ["tag"]}, fn))
    return tools, ran


def tool_messages(messages):
    return [m for m in messages if m["role"] == "tool"]


def assert_valid_history(messages):
    """Every assistant tool call is answered by a tool message before anything else."""
    for i, m in enumerate(messages):
        if m["role"] == "assistant" and m.get("tool_calls"):
            ids = [tc["id"] for tc in m["tool_calls"]]
            answered = [x["tool_call_id"] for x in messages[i + 1:i + 1 + len(ids)]
                        if x["role"] == "tool"]
            assert sorted(answered) == sorted(ids)


def test_interrupt_during_tool_repairs_history():
    tools, ran = make_tools(interrupt_on="a")
    client = FakeClient([
        reply(tool_calls=[call("work", {"tag": "a"}), call("work", {"tag": "b"})]),
        reply(content="recovered"),
    ])
    agent = Agent(client, "m", tools)
    result = agent.run("go")
    assert result.stop_reason == "interrupted"
    assert ran == ["a"]  # the second call never ran
    assert [(m["tool_call_id"], m["content"]) for m in tool_messages(agent.messages)] == [
        ("call_1", INTERRUPTED), ("call_2", INTERRUPTED)]
    assert_valid_history(agent.messages)

    result = agent.run("try again")
    assert result.stop_reason == "done" and result.final_text == "recovered"
    sent = client.requests[1]["messages"]
    assert_valid_history(sent)
    assert sent[-1] == {"role": "user", "content": "try again"}


def test_interrupt_keeps_results_of_calls_that_finished():
    tools, _ = make_tools(interrupt_on="b")
    client = FakeClient([reply(tool_calls=[call("work", {"tag": "a"}),
                                           call("work", {"tag": "b"}),
                                           call("work", {"tag": "c"})])])
    agent = Agent(client, "m", tools)
    assert agent.run("go").stop_reason == "interrupted"
    assert [(m["tool_call_id"], m["content"]) for m in tool_messages(agent.messages)] == [
        ("call_1", "ran a"), ("call_2", INTERRUPTED), ("call_3", INTERRUPTED)]


def test_interrupt_during_stream_drops_partial():
    tools, _ = make_tools()

    def broken():
        chunks = to_chunks(reply(content="This reply is cut off midway"), text_chunk_size=4)
        yield from chunks[:4]
        raise KeyboardInterrupt

    client = FakeClient([[], reply(content="fresh start")])
    client.script[0] = broken()
    agent = Agent(client, "m", tools, stream=True)
    result = agent.run("go")
    assert result.stop_reason == "interrupted"
    assert agent.messages == [{"role": "user", "content": "go"}]  # nothing partial kept
    result = agent.run("again")
    assert result.stop_reason == "done" and result.final_text == "fresh start"
    assert client.requests[1]["messages"][-1] == {"role": "user", "content": "again"}


def test_interrupt_during_stream_is_logged(tmp_path):
    from agent.log import RequestLog, read_log
    tools, _ = make_tools()

    def broken():
        yield from to_chunks(reply(content="partial reply"), text_chunk_size=4)[:3]
        raise KeyboardInterrupt

    client = FakeClient([[]])
    client.script[0] = broken()
    log = RequestLog(tmp_path / "log.jsonl")
    Agent(client, "m", tools, stream=True, log=log).run("go")
    [entry] = read_log(log.path)
    assert entry["response"]["interrupted"] is True
    assert entry["response"]["streamed"] is True
