import pytest

from agent.loop import Agent, TurnResult
from agent.messages import Usage
from agent.tools import make_default_tools
from agent.workspace import Workspace
from testing.fake_model import FakeClient, call, reply


def make_agent(tmp_path, script, **kwargs):
    ws = Workspace(tmp_path)
    client = FakeClient(script)
    return Agent(client, "m", make_default_tools(ws), **kwargs), client


def test_single_tool_round_trip(tmp_path):
    (tmp_path / "a.txt").write_text("hello\n")
    agent, client = make_agent(tmp_path, [
        reply(tool_calls=[call("read_file", {"path": "a.txt"})]),
        reply(content="It says hello"),
    ])
    result = agent.run("what is in a.txt?")
    assert isinstance(result, TurnResult)
    assert result.final_text == "It says hello"
    assert result.turns == 2
    assert result.error is None
    assert client.requests[1]["messages"][-1] == {
        "role": "tool", "tool_call_id": "call_1", "content": "     1\thello"}


def test_request_shape(tmp_path):
    agent, client = make_agent(tmp_path, [reply(content="hi")], system="be brief")
    agent.run("hello")
    req = client.requests[0]
    assert req["model"] == "m"
    assert req["messages"][0] == {"role": "system", "content": "be brief"}
    assert req["messages"][1] == {"role": "user", "content": "hello"}
    assert req["tools"][0]["function"]["name"] == "read_file"


def test_two_tool_calls_in_one_reply(tmp_path):
    (tmp_path / "a.txt").write_text("AAA\n")
    (tmp_path / "b.txt").write_text("BBB\n")
    agent, client = make_agent(tmp_path, [
        reply(tool_calls=[call("read_file", {"path": "a.txt"}),
                          call("read_file", {"path": "b.txt"})]),
        reply(content="done"),
    ])
    agent.run("read both")
    tail = client.requests[1]["messages"][-3:]
    assert tail[0]["role"] == "assistant" and len(tail[0]["tool_calls"]) == 2
    assert tail[1] == {"role": "tool", "tool_call_id": "call_1", "content": "     1\tAAA"}
    assert tail[2] == {"role": "tool", "tool_call_id": "call_2", "content": "     1\tBBB"}


def test_no_tool_call_ends_turn(tmp_path):
    agent, client = make_agent(tmp_path, [reply(content="hi")])
    result = agent.run("hello")
    assert result.turns == 1
    assert result.stop_reason == "done"
    assert len(client.requests) == 1


def test_none_content_with_no_tools(tmp_path):
    agent, _ = make_agent(tmp_path, [reply(content=None)])
    assert agent.run("hello").final_text == ""


def test_empty_content_with_no_tools(tmp_path):
    agent, _ = make_agent(tmp_path, [reply(content="")])
    assert agent.run("hello").final_text == ""


def test_reasoning_not_in_history(tmp_path):
    agent, _ = make_agent(tmp_path, [reply(content="ok", reasoning="x")])
    agent.run("hello")
    assert agent.messages[-1]["role"] == "assistant"
    assert all("reasoning_content" not in m for m in agent.messages)


def test_assistant_message_with_tool_calls_is_plain_dict(tmp_path):
    agent, _ = make_agent(tmp_path, [
        reply(tool_calls=[call("read_file", {"path": "missing.txt"})]),
        reply(content="gone"),
    ])
    agent.run("go")
    assistant = agent.messages[1]
    assert assistant["role"] == "assistant"
    assert assistant["tool_calls"] == [{
        "id": "call_1", "type": "function",
        "function": {"name": "read_file", "arguments": '{"path": "missing.txt"}'}}]
    assert agent.messages[2]["content"] == "Error: file not found: missing.txt"


def test_usage_summed(tmp_path):
    (tmp_path / "a.txt").write_text("x\n")
    agent, _ = make_agent(tmp_path, [
        reply(tool_calls=[call("read_file", {"path": "a.txt"})],
              prompt_tokens=100, completion_tokens=20),
        reply(content="ok", prompt_tokens=100, completion_tokens=20),
    ])
    assert agent.run("go").usage == Usage(200, 40)


def test_history_persists_across_runs(tmp_path):
    agent, client = make_agent(tmp_path, [reply(content="one"), reply(content="two")])
    agent.run("first")
    agent.run("second")
    sent = client.requests[1]["messages"]
    assert [m["content"] for m in sent] == ["first", "one", "second"]


def test_read_file_offset_limit(tmp_path):
    (tmp_path / "f.txt").write_text("".join(f"line{i}\n" for i in range(1, 6)))
    tools = make_default_tools(Workspace(tmp_path))
    out = tools.dispatch("read_file", '{"path": "f.txt", "offset": 2, "limit": 2}')
    assert out == "     2\tline2\n     3\tline3"


def test_read_file_is_read_only_and_registered(tmp_path):
    tools = make_default_tools(Workspace(tmp_path))
    assert tools.names() == ["read_file"]
    assert tools.get("read_file").read_only is True
    schema = tools.schemas()[0]
    assert schema["type"] == "function"
    assert set(schema["function"]) == {"name", "description", "parameters"}


def test_workspace_resolve(tmp_path):
    ws = Workspace(tmp_path)
    assert ws.root == tmp_path.resolve()
    assert ws.resolve("a/b.txt") == tmp_path.resolve() / "a" / "b.txt"


@pytest.mark.live
def test_live_read_file(tmp_path):
    from agent.client import make_client
    from agent.config import load_config
    (tmp_path / "secret.txt").write_text("The magic word is pineapple.\n")
    config = load_config()
    agent = Agent(make_client(config), config.model, make_default_tools(Workspace(tmp_path)))
    result = agent.run("Read secret.txt and tell me the magic word.")
    assert result.stop_reason in {"done", "error"}
    assert "pineapple" in result.final_text.lower()
