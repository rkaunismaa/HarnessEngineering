from agent.loop import Agent
from agent.tools import make_default_tools
from agent.workspace import Workspace
from testing.fake_model import FakeClient, call, reply

PREFIX = "[Automatic check failed]\n"


def make(tmp_path, script, verify=None, **kw):
    ws = Workspace(tmp_path)
    client = FakeClient(script)
    return Agent(client, "m", make_default_tools(ws), workspace=ws, verify=verify, **kw), client


def scripted_verify(results):
    seen = []

    def verify():
        seen.append(1)
        return results[min(len(seen), len(results)) - 1]
    return verify, seen


def test_verify_pass_first_time(tmp_path):
    verify, seen = scripted_verify([(True, "ok")])
    agent, client = make(tmp_path, [reply(content="done")], verify=verify)
    result = agent.run("go")
    assert result.verified is True and result.stop_reason == "done"
    assert len(seen) == 1 and len(client.requests) == 1


def test_verify_fail_then_fix(tmp_path):
    verify, seen = scripted_verify([(False, "1 test failed: test_x"), (True, "ok")])
    script = [reply(content="all done"),
              reply(tool_calls=[call("write_file", {"path": "f.txt", "content": "fixed"})]),
              reply(content="really done")]
    agent, client = make(tmp_path, script, verify=verify)
    result = agent.run("go")
    assert result.verified is True and result.stop_reason == "done"
    assert result.final_text == "really done" and len(seen) == 2
    assert result.turns == 3  # verify-driven continuations count as requests
    injected = [m for m in agent.messages if m["role"] == "user" and m["content"] != "go"]
    assert injected == [{"role": "user", "content":
                         "[Automatic check failed]\n1 test failed: test_x\n"
                         "Fix the problem, then finish."}]
    # the failed reply stays in the history, before the injected message
    i = agent.messages.index(injected[0])
    assert agent.messages[i - 1] == {"role": "assistant", "content": "all done"}
    # the model saw the message on its next request
    assert client.requests[1]["messages"][-1]["content"].startswith(PREFIX)


def test_verify_gives_up(tmp_path):
    verify, seen = scripted_verify([(False, "still broken")])
    script = [reply(content="done 1"), reply(content="done 2"), reply(content="never asked")]
    agent, client = make(tmp_path, script, verify=verify)
    result = agent.run("go")
    assert result.verified is False and result.stop_reason == "done"
    assert len(seen) == 2 and len(client.requests) == 2
    assert result.final_text == "done 2"
    assert sum(m["role"] == "user" and m["content"].startswith(PREFIX) for m in agent.messages) == 1


def test_max_verify_attempts_and_counts_reset_per_run(tmp_path):
    verify, seen = scripted_verify([(False, "bad")])
    agent, _ = make(tmp_path, [reply(content="a")] * 6, verify=verify, max_verify_attempts=3)
    assert agent.run("one").verified is False and len(seen) == 3
    assert agent.run("two").verified is False and len(seen) == 6  # a fresh budget per run


def test_verify_skipped_when_tool_calls_and_when_not_done(tmp_path):
    verify, seen = scripted_verify([(True, "ok")])
    script = [reply(tool_calls=[call("list_files", {})]), reply(content="done")]
    agent, _ = make(tmp_path, script, verify=verify)
    agent.run("go")
    assert len(seen) == 1  # only the reply without tool calls is checked
    agent, _ = make(tmp_path, [reply(tool_calls=[call("list_files", {})])], verify=verify,
                    max_turns=1)
    result = agent.run("go")
    assert result.stop_reason == "max_turns" and len(seen) == 1 and result.verified is None


def test_no_verify_is_none(tmp_path):
    agent, client = make(tmp_path, [reply(content="done")])
    result = agent.run("go")
    assert result.verified is None and result.stop_reason == "done"
    from agent.loop import TurnResult
    from agent.messages import Usage
    assert TurnResult("x", "done", 1, Usage()).verified is None  # old constructions still work


def test_cli_verify_option(tmp_path):
    from agent.__main__ import _make_verify, build_parser
    args = build_parser().parse_args(["ask", "hi", "--verify", "echo oops; exit 3"])
    assert args.verify == "echo oops; exit 3"
    assert build_parser().parse_args(["chat"]).verify is None
    ok, output = _make_verify(Workspace(tmp_path), args.verify)()
    assert ok is False and "oops" in output
    ok, _ = _make_verify(Workspace(tmp_path), "true")()
    assert ok is True
