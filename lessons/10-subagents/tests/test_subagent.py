import json

import pytest

from agent.log import RequestLog, read_log
from agent.loop import Agent
from agent.tools import make_default_tools
from agent.tools.registry import ToolRegistry
from agent.tools.subagent import (SUBAGENT_MAX_ANSWER, SUBAGENT_MAX_TURNS, SUBAGENT_TOOLS,
                                  make_subagent_tool)
from agent.workspace import Workspace
from testing.fake_model import FakeClient, call, connection_error, reply


def delegate(task="find the parser"):
    return reply(tool_calls=[call("subagent", {"task": task})])


def make(tmp_path, script, log=None):
    ws = Workspace(tmp_path)
    client = FakeClient(script)
    tools = make_default_tools(ws, client=client, model="m", log=log)
    return Agent(client, "m", tools, workspace=ws, log=log), client


def tool_names(request):
    return [t["function"]["name"] for t in request["tools"]]


def test_registry_subset():
    ws = Workspace(".")
    tools = make_default_tools(ws)
    sub = tools.subset(["read_file", "search", "no_such_tool"])
    assert isinstance(sub, ToolRegistry)
    assert sub.names() == ["read_file", "search"]  # missing names are skipped
    assert sub.get("read_file") is tools.get("read_file")  # the Tool objects are shared
    assert "bash" in tools.names()  # the original is unchanged


def test_subagent_registered_only_with_client(tmp_path):
    ws = Workspace(tmp_path)
    assert "subagent" not in make_default_tools(ws).names()
    tool = make_default_tools(ws, client=FakeClient([]), model="m").get("subagent")
    assert tool is not None and tool.read_only is True


def test_subagent_gets_only_read_tools(tmp_path):
    agent, client = make(tmp_path, [delegate(), reply(content="found"), reply(content="ok")])
    agent.run("go")
    parent_first, sub_first, parent_second = client.requests
    assert "subagent" in tool_names(parent_first)
    assert tool_names(sub_first) == list(SUBAGENT_TOOLS)
    assert "subagent" in tool_names(parent_second)  # the parent keeps its own tools


def test_subagent_fresh_context(tmp_path):
    agent, client = make(tmp_path, [delegate("where is parse() defined?"),
                                    reply(content="found"), reply(content="ok")])
    agent.messages.append({"role": "user", "content": "earlier chat"})
    agent.messages.append({"role": "assistant", "content": "earlier answer"})
    agent.run("go")
    sub_first = client.requests[1]
    assert len(sub_first["messages"]) == 2
    system, task = sub_first["messages"]
    assert system["role"] == "system" and system["content"]
    assert task == {"role": "user", "content": "where is parse() defined?"}


def test_parent_sees_only_answer(tmp_path):
    (tmp_path / "a.py").write_text("def parse():\n    pass\n")
    script = [delegate(),
              reply(tool_calls=[call("read_file", {"path": "a.py"})]),
              reply(content="parse is defined in a.py line 1"),
              reply(content="It is in a.py")]
    agent, client = make(tmp_path, script)
    result = agent.run("go")
    assert result.final_text == "It is in a.py"
    tool_msgs = [m for m in agent.messages if m["role"] == "tool"]
    assert [m["content"] for m in tool_msgs] == ["parse is defined in a.py line 1"]
    # the subagent's own read_file call never reached the parent's history
    assert not any("def parse" in json.dumps(m) for m in agent.messages)
    # the parent's usage counts only its own requests
    assert result.turns == 2
    # the subagent did read the file in its own history (second subagent request)
    assert any("def parse" in json.dumps(m) for m in client.requests[2]["messages"])


def test_subagent_log_tag(tmp_path):
    log = RequestLog(tmp_path / "log.jsonl")
    script = [delegate(), reply(content="one"), delegate("again"), reply(content="two"),
              reply(content="done")]
    agent, _ = make(tmp_path, script, log=log)
    agent.run("go")
    tags = [e["agent"] for e in read_log(log.path)]
    assert tags == ["main", "subagent-1", "main", "subagent-2", "main"]


def test_subagent_max_turns_message(tmp_path):
    looping = [reply(tool_calls=[call("list_files", {"path": "."})])
               for _ in range(SUBAGENT_MAX_TURNS)]
    agent, client = make(tmp_path, [delegate(), *looping, reply(content="gave up")])
    agent.run("go")
    tool_msg = [m for m in agent.messages if m["role"] == "tool"][0]["content"]
    assert tool_msg == f"Subagent stopped after {SUBAGENT_MAX_TURNS} turns without finishing."
    assert len(client.requests) == 1 + SUBAGENT_MAX_TURNS + 1


def test_subagent_answer_truncated(tmp_path):
    agent, _ = make(tmp_path, [delegate(), reply(content="x" * 10_000), reply(content="ok")])
    agent.run("go")
    tool_msg = [m for m in agent.messages if m["role"] == "tool"][0]["content"]
    assert "characters truncated" in tool_msg
    assert len(tool_msg) < SUBAGENT_MAX_ANSWER + 100
    assert tool_msg.startswith("x" * 100) and tool_msg.endswith("x" * 100)


def test_subagent_error(tmp_path):
    agent, _ = make(tmp_path, [delegate(), connection_error(), reply(content="ok")])
    agent.run("go")
    tool_msg = [m for m in agent.messages if m["role"] == "tool"][0]["content"]
    assert tool_msg.startswith("Error: subagent failed: ")


def test_subagent_empty_task_is_a_schema_error(tmp_path):
    ws = Workspace(tmp_path)
    tools = make_default_tools(ws, client=FakeClient([]), model="m")
    assert tools.dispatch("subagent", "{}") == "Error: missing required parameter 'task'"


@pytest.mark.live
def test_live_subagent_search(tmp_path):
    from agent.client import make_client
    from agent.config import Config
    from agent.prompt import build_system_prompt
    (tmp_path / "app.py").write_text("from helpers import x\nprint(x())\n")
    (tmp_path / "helpers.py").write_text("def x():\n    return 1\n\n\ndef frobnicate_widget():\n    return 2\n")
    (tmp_path / "notes.txt").write_text("nothing here\n")
    config = Config(base_url="http://localhost:1234/v1", model="qwen/qwen3.8-27b",
                    api_key="lm-studio")
    ws = Workspace(tmp_path)
    client = make_client(config)
    log = RequestLog(tmp_path.parent / f"{tmp_path.name}-log.jsonl")
    tools = make_default_tools(ws, client=client, model=config.model, log=log)
    agent = Agent(client, config.model, tools, system=build_system_prompt(ws, tools),
                  workspace=ws, log=log, max_turns=12)
    result = agent.run("Use the subagent tool to find where frobnicate_widget is defined, "
                       "then tell me the file name.")
    used = [tc for m in agent.messages if m["role"] == "assistant"
            for tc in m.get("tool_calls") or [] if tc["function"]["name"] == "subagent"]
    print(f"\nstop={result.stop_reason} turns={result.turns} subagent calls={len(used)} "
          f"answer={result.final_text!r}")
    assert result.stop_reason == "done"
    assert "helpers.py" in result.final_text
