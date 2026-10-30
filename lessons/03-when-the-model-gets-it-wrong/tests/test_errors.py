import json

import pytest

from agent.loop import Agent
from agent.tools import make_default_tools
from agent.tools.registry import Tool, ToolRegistry
from agent.workspace import Workspace
from testing.fake_model import FakeClient, call, connection_error, reply

LOOP_MESSAGE = "Error: you have made this exact call 3 times in a row. Try a different approach."


def make_agent(tmp_path, script, **kwargs):
    ws = Workspace(tmp_path)
    client = FakeClient(script)
    return Agent(client, "m", make_default_tools(ws), **kwargs), client


def tool_results(agent):
    return [m["content"] for m in agent.messages if m["role"] == "tool"]


def small_registry(fn=None):
    registry = ToolRegistry()
    registry.register(Tool(
        "add", "Add numbers.",
        {"type": "object",
         "properties": {"a": {"type": "integer"}, "b": {"type": "integer"},
                        "label": {"type": "string"}},
         "required": ["a"]},
        fn or (lambda a, b=0, label="": str(a + b))))
    return registry


def test_unknown_tool():
    registry = small_registry()
    assert registry.dispatch("nope", "{}") == "Error: unknown tool 'nope'. Available tools: add"


def test_unknown_tool_lists_all_names(tmp_path):
    registry = make_default_tools(Workspace(tmp_path))
    result = registry.dispatch("grep", "{}")
    assert result == ("Error: unknown tool 'grep'. Available tools: "
                      + ", ".join(registry.names()))


def test_bad_json():
    result = small_registry().dispatch("add", '{"a": 1,')
    assert result.startswith("Error: arguments were not valid JSON (")
    assert result.endswith("). Send the arguments as a JSON object.")


def test_bad_json_exact_message():
    with pytest.raises(json.JSONDecodeError) as info:
        json.loads("{nope")
    result = small_registry().dispatch("add", "{nope")
    assert result == (f"Error: arguments were not valid JSON ({info.value.msg}). "
                      "Send the arguments as a JSON object.")


@pytest.mark.parametrize("raw", ["[1, 2]", '"text"', "3", "null"])
def test_arguments_not_object(raw):
    assert small_registry().dispatch("add", raw) == "Error: arguments must be a JSON object."


def test_missing_required():
    assert small_registry().dispatch("add", "{}") == "Error: missing required parameter 'a'"


def test_wrong_type():
    assert (small_registry().dispatch("add", '{"a": "5"}')
            == "Error: parameter 'a' must be integer")


def test_bool_is_not_integer():
    assert (small_registry().dispatch("add", '{"a": true}')
            == "Error: parameter 'a' must be integer")


def test_unknown_param():
    assert small_registry().dispatch("add", '{"a": 1, "c": 2}') == "Error: unknown parameter 'c'"


def test_several_errors_joined():
    result = small_registry().dispatch("add", '{"b": "x", "c": 1}')
    assert result == ("Error: missing required parameter 'a'; unknown parameter 'c'; "
                      "parameter 'b' must be integer")


def test_validate_args_types():
    from agent.tools.registry import validate_args
    schema = {"type": "object", "required": [],
              "properties": {"s": {"type": "string"}, "i": {"type": "integer"},
                             "n": {"type": "number"}, "b": {"type": "boolean"},
                             "a": {"type": "array"}, "o": {"type": "object"}}}
    assert validate_args(schema, {"s": "x", "i": 1, "n": 1.5, "b": False,
                                  "a": [], "o": {}}) == []
    assert validate_args(schema, {"n": 2}) == []  # an int is a valid number
    assert validate_args(schema, {"n": True}) == ["parameter 'n' must be number"]
    assert validate_args(schema, {"s": 1, "a": {}, "o": []}) == [
        "parameter 's' must be string", "parameter 'a' must be array",
        "parameter 'o' must be object"]
    assert validate_args(schema, {"i": 1.5, "b": 0}) == [
        "parameter 'i' must be integer", "parameter 'b' must be boolean"]


def test_tool_exception():
    def boom(a):
        raise RuntimeError("disk on fire")
    assert small_registry(boom).dispatch("add", '{"a": 1}') == "Error: RuntimeError: disk on fire"


def test_dispatch_never_raises_on_real_tools(tmp_path):
    registry = make_default_tools(Workspace(tmp_path))
    cases = [("list_files", {"pattern": ""}), ("list_files", {"pattern": "/etc/*"}),
             ("search", {"pattern": "x", "glob": "/etc/*"}), ("search", {"pattern": "x", "glob": ""}),
             ("read_file", {"path": "missing.txt"}), ("read_file", {"path": "../outside"}),
             ("read_file", {"path": "."}), ("list_files", {"path": "nope"})]
    for name, args in cases:
        result = registry.dispatch(name, json.dumps(args))
        assert isinstance(result, str)


def test_error_results_are_truncated():
    def boom(a):
        raise RuntimeError("x" * 50_000)
    result = small_registry(boom).dispatch("add", '{"a": 1}')
    assert result.startswith("Error: RuntimeError: ")
    assert "characters truncated" in result
    assert len(result) < 20_100


def test_error_fed_back_and_model_recovers(tmp_path):
    (tmp_path / "a.txt").write_text("hello\n")
    agent, client = make_agent(tmp_path, [
        reply(tool_calls=[call("read_file", '{"path": "a.txt"')]),
        reply(tool_calls=[call("read_file", {"path": "a.txt"})]),
        reply(content="hello"),
    ])
    result = agent.run("read a.txt")
    assert result.stop_reason == "done"
    results = tool_results(agent)
    assert results[0].startswith("Error: arguments were not valid JSON")
    assert results[1] == "     1\thello"
    # the error reached the model as an ordinary tool message
    assert client.requests[1]["messages"][-1]["content"] == results[0]


def test_max_turns(tmp_path):
    (tmp_path / "a.txt").write_text("x\n")
    agent, client = make_agent(tmp_path, [
        reply(tool_calls=[call("read_file", {"path": "a.txt", "limit": i})]) for i in (1, 2, 3)
    ], max_turns=3)
    result = agent.run("loop forever")
    assert result.stop_reason == "max_turns"
    assert result.final_text == ""
    assert result.turns == 3
    assert len(client.requests) == 3


def test_max_turns_default_is_50():
    import inspect
    assert inspect.signature(Agent.__init__).parameters["max_turns"].default == 50


def test_max_turns_keeps_history_valid(tmp_path):
    (tmp_path / "a.txt").write_text("x\n")
    agent, client = make_agent(tmp_path, [
        reply(tool_calls=[call("read_file", {"path": "a.txt"})]),
        reply(content="ok"),
    ], max_turns=1)
    assert agent.run("go").stop_reason == "max_turns"
    # every tool call in history has its result
    ids = [tc["id"] for m in agent.messages if m.get("tool_calls") for tc in m["tool_calls"]]
    answered = [m["tool_call_id"] for m in agent.messages if m["role"] == "tool"]
    assert ids == answered


def test_loop_detection(tmp_path):
    (tmp_path / "a.txt").write_text("hello\n")
    agent, client = make_agent(tmp_path, [
        reply(tool_calls=[call("read_file", {"path": "a.txt"})]) for _ in range(3)
    ] + [reply(content="giving up")])
    reads = []
    tool = agent.tools.get("read_file")
    original = tool.fn
    tool.fn = lambda **kw: (reads.append(kw), original(**kw))[1]
    result = agent.run("read it")
    assert result.stop_reason == "done"
    results = tool_results(agent)
    assert results[2] == LOOP_MESSAGE
    assert results[0] == results[1] == "     1\thello"
    assert len(reads) == 2


def test_loop_detection_needs_consecutive_calls(tmp_path):
    (tmp_path / "a.txt").write_text("hello\n")
    (tmp_path / "b.txt").write_text("world\n")
    a = call("read_file", {"path": "a.txt"})
    b = call("read_file", {"path": "b.txt"})
    agent, _ = make_agent(tmp_path, [
        reply(tool_calls=[a]), reply(tool_calls=[a]), reply(tool_calls=[b]),
        reply(tool_calls=[a]), reply(tool_calls=[a]), reply(content="done"),
    ])
    agent.run("go")
    assert LOOP_MESSAGE not in tool_results(agent)


def test_loop_detection_counts_within_one_reply(tmp_path):
    (tmp_path / "a.txt").write_text("hello\n")
    c = call("read_file", {"path": "a.txt"})
    agent, _ = make_agent(tmp_path, [reply(tool_calls=[c, c, c]), reply(content="ok")])
    agent.run("go")
    assert tool_results(agent)[2] == LOOP_MESSAGE


def test_loop_detection_applies_to_failing_calls(tmp_path):
    bad = call("read_file", '{"path":')
    agent, _ = make_agent(tmp_path, [reply(tool_calls=[bad]) for _ in range(3)]
                          + [reply(content="ok")])
    agent.run("go")
    results = tool_results(agent)
    assert results[0].startswith("Error: arguments were not valid JSON")
    assert results[2] == LOOP_MESSAGE


def test_connection_error(tmp_path):
    agent, client = make_agent(tmp_path, [connection_error()])
    result = agent.run("hi")
    assert result.stop_reason == "error"
    assert "Model request failed" in result.error
    assert result.error.startswith("Model request failed: ")
    assert result.final_text == ""
    assert agent.messages[-1]["role"] == "user"
    # the same agent works again with a working server
    agent.client = FakeClient([reply(content="back")])
    again = agent.run("hi again")
    assert again.stop_reason == "done"
    assert again.final_text == "back"
    assert [m["role"] for m in agent.messages] == ["user", "user", "assistant"]


def test_api_error_mid_session_keeps_history_valid(tmp_path):
    from testing.fake_model import bad_request
    (tmp_path / "a.txt").write_text("hello\n")
    agent, _ = make_agent(tmp_path, [
        reply(tool_calls=[call("read_file", {"path": "a.txt"})]),
        bad_request("context too long"),
    ])
    result = agent.run("read a.txt")
    assert result.stop_reason == "error"
    assert "context too long" in result.error
    assert agent.messages[-1]["role"] == "tool"
    assert result.turns == 1


@pytest.mark.live
def test_live_4b_failures(tmp_path):
    from agent.client import make_client
    from agent.config import Config
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "billing.py").write_text(
        "def compute_invoice_total(items):\n    return sum(items)\n")
    (tmp_path / "notes.txt").write_text("remember the milk\n")
    config = Config(base_url="http://localhost:11434/v1", model="qwen3:4b-instruct",
                    api_key="ollama")
    prompts = [
        "Which file defines compute_invoice_total? Answer with the path only.",
        "Read the file notes.txt and tell me what it says.",
        "Count the lines of Python code in the project, using any tools you need.",
    ]
    for prompt in prompts:
        agent = Agent(make_client(config), config.model,
                      make_default_tools(Workspace(tmp_path), confirm_bash=lambda c: False),
                      max_turns=10)
        result = agent.run(prompt)
        assert result.stop_reason in {"done", "max_turns", "error"}
        print(f"\nPROMPT: {prompt}\n  stop_reason={result.stop_reason} turns={result.turns}")
        for m in agent.messages:
            if m["role"] == "assistant" and m.get("tool_calls"):
                for tc in m["tool_calls"]:
                    print(f"  CALL {tc['function']['name']}({tc['function']['arguments']})")
            if m["role"] == "tool":
                print(f"  RESULT {m['content'][:200]!r}")
