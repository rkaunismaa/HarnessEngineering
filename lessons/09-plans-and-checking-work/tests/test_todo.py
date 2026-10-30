import json

import pytest

from agent.loop import Agent
from agent.tools import make_default_tools
from agent.tools.registry import validate_args
from agent.workspace import Workspace
from testing.fake_model import FakeClient, call, reply


def todo_tool(tmp_path):
    ws = Workspace(tmp_path)
    tools = make_default_tools(ws)
    return ws, tools, tools.get("todo_write")


def items(*pairs):
    return [{"content": c, "status": s} for c, s in pairs]


def test_todo_replace_and_render(tmp_path):
    ws, tools, tool = todo_tool(tmp_path)
    assert tool is not None and tool.read_only is True
    assert ws.todos == []
    first = items(("write tests", "completed"), ("fix bug", "in_progress"), ("run tests", "pending"))
    out = tools.dispatch("todo_write", json.dumps({"todos": first}))
    assert out.splitlines() == ["[x] write tests", "[>] fix bug", "[ ] run tests"]
    assert ws.todos == first
    second = items(("only one", "pending"))
    out = tools.dispatch("todo_write", json.dumps({"todos": second}))
    assert out == "[ ] only one"
    assert ws.todos == second  # replaced, not appended


def test_todo_two_in_progress_error(tmp_path):
    ws, tools, _ = todo_tool(tmp_path)
    ws.todos = items(("keep me", "pending"))
    bad = items(("a", "in_progress"), ("b", "in_progress"))
    out = tools.dispatch("todo_write", json.dumps({"todos": bad}))
    assert out == "Error: only one item can be in_progress at a time."
    assert ws.todos == items(("keep me", "pending"))  # a rejected list changes nothing


def test_todo_bad_status(tmp_path):
    ws, tools, tool = todo_tool(tmp_path)
    # The tool itself checks too (it can be called directly) ...
    assert tool.fn(todos=items(("a", "started"))) == "Error: invalid status 'started'."
    assert ws.todos == []
    # ... but through dispatch the schema's enum is checked first, with a path to the item.
    out = tools.dispatch("todo_write", json.dumps({"todos": items(("a", "pending"), ("b", "started"))}))
    assert out == "Error: todos[1].status must be one of pending, in_progress, completed"


SCHEMA = {
    "type": "object",
    "properties": {"todos": {"type": "array", "items": {
        "type": "object",
        "properties": {"content": {"type": "string"},
                       "status": {"type": "string", "enum": ["pending", "done"]}},
        "required": ["content", "status"]}},
        "mode": {"type": "string", "enum": ["a", "b"]}},
    "required": ["todos"],
}


def test_validate_args_arrays_of_objects():
    ok = {"todos": [{"content": "x", "status": "done"}]}
    assert validate_args(SCHEMA, ok) == []
    assert validate_args(SCHEMA, {"todos": "x"}) == ["parameter 'todos' must be array"]
    assert validate_args(SCHEMA, {"todos": ["x"]}) == ["todos[0] must be object"]
    assert validate_args(SCHEMA, {"todos": [{"content": "x"}]}) == \
        ["todos[0]: missing required parameter 'status'"]
    assert validate_args(SCHEMA, {"todos": [{"content": 1, "status": "done"}]}) == \
        ["todos[0].content must be string"]
    assert validate_args(SCHEMA, {"todos": [], "mode": "c"}) == \
        ["parameter 'mode' must be one of a, b"]
    # earlier formats are unchanged
    assert validate_args(SCHEMA, {}) == ["missing required parameter 'todos'"]


def test_todo_schema_has_enum(tmp_path):
    _, tools, tool = todo_tool(tmp_path)
    item = tool.parameters["properties"]["todos"]["items"]
    assert item["properties"]["status"]["enum"] == ["pending", "in_progress", "completed"]
    assert set(item["required"]) == {"content", "status"}


def test_todo_through_agent_and_prompt(tmp_path):
    from agent.prompt import build_system_prompt
    ws, tools, _ = todo_tool(tmp_path)
    prompt = build_system_prompt(ws, tools)
    assert "todo_write" in prompt and "test" in prompt.lower()
    todos = items(("step", "in_progress"))
    client = FakeClient([reply(tool_calls=[call("todo_write", {"todos": todos})]),
                         reply(content="ok")])
    agent = Agent(client, "m", tools, workspace=ws)
    result = agent.run("plan it")
    assert result.stop_reason == "done" and ws.todos == todos
    assert agent.messages[-2]["content"] == "[>] step"


@pytest.mark.live
def test_live_uses_todo(tmp_path):
    from agent.client import make_client
    from agent.config import Config
    from agent.prompt import build_system_prompt
    config = Config(base_url="http://localhost:1234/v1", model="qwen/qwen3.8-27b",
                    api_key="lm-studio")
    ws = Workspace(tmp_path)
    tools = make_default_tools(ws)
    agent = Agent(make_client(config), config.model, tools, system=build_system_prompt(ws, tools),
                  workspace=ws, max_turns=15)
    result = agent.run("Do three things in order: create a.txt containing 'one', create b.txt "
                       "containing 'two', then create c.txt containing the contents of a.txt "
                       "and b.txt joined by a space.")
    used = [m for m in agent.messages if m["role"] == "assistant"
            for tc in m.get("tool_calls") or [] if tc["function"]["name"] == "todo_write"]
    print(f"\nstop={result.stop_reason} turns={result.turns} todo_write calls={len(used)} "
          f"final todos={ws.todos}")
    assert result.stop_reason in {"done", "max_turns", "error"}
    assert result.stop_reason == "done"
