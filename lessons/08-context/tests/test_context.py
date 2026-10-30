import json
import math

import pytest

from agent.context import (ContextManager, compact, error_text, estimate_tokens, is_context_overflow,
                           split_index, trim_old_tool_results)
from agent.events import AgentEvents
from agent.loop import Agent
from agent.tools import make_default_tools
from agent.workspace import Workspace
from testing.fake_model import FakeClient, bad_request, call, reply


def convo(n_pairs=6, big="x" * 1000):
    """system, then n_pairs of (user, assistant-with-tool-call, tool result)."""
    msgs = [{"role": "system", "content": "sys"}]
    for i in range(n_pairs):
        msgs.append({"role": "user", "content": f"question {i}"})
        msgs.append({"role": "assistant", "content": None, "tool_calls": [
            {"id": f"c{i}", "type": "function",
             "function": {"name": "read_file", "arguments": "{}"}}]})
        msgs.append({"role": "tool", "tool_call_id": f"c{i}", "content": big})
    return msgs


def summary_reply(text="SUMMARY TEXT"):
    return reply(content=text)


def test_estimate_tokens():
    msgs = [{"role": "user", "content": "hello"}]
    assert estimate_tokens(msgs) == math.ceil(len(json.dumps(msgs)) / 4)
    assert estimate_tokens([]) == 1  # "[]" is two characters


def test_trim_keeps_recent_and_small():
    msgs = convo(4)
    out = trim_old_tool_results(msgs, keep_recent=6, min_chars=500)
    assert out is not msgs and msgs[3]["content"] == "x" * 1000  # input untouched
    assert len(out) == len(msgs)
    old_tools = [m for m in out[:-6] if m["role"] == "tool"]
    assert old_tools and all(m["content"] == "[old tool result removed: 1000 characters]"
                             for m in old_tools)
    assert out[-6:] == msgs[-6:]  # recent messages are kept as they were
    # small results are kept even when old
    small = convo(4, big="tiny")
    assert trim_old_tool_results(small) == small
    # non-tool messages and tool-call ids are untouched
    assert [m.get("tool_call_id") for m in out] == [m.get("tool_call_id") for m in msgs]
    assert [m["content"] for m in out if m["role"] == "user"] == \
           [m["content"] for m in msgs if m["role"] == "user"]


def test_split_never_on_tool_message():
    msgs = convo(5)
    for keep in range(0, 12):
        i = split_index(msgs, keep)
        assert i >= 1
        assert i == 1 or msgs[i]["role"] in ("user", "assistant")
    # len 16, keep 4 -> start 12 is a tool message? index 12 = (12-1)%3 == 2 -> tool; moves back
    assert msgs[12]["role"] == "tool"
    assert split_index(msgs, 4) == 11
    # with no system message the lower bound is 0
    assert split_index(msgs[1:], 100) == 0


def test_compact_shape():
    msgs = convo(5)
    client = FakeClient([summary_reply()])
    out = compact(msgs, client, "m", keep_recent=4)
    [req] = client.requests
    assert "tools" not in req and req["model"] == "m"
    assert out[0] == msgs[0]
    assert out[1]["role"] == "user"
    assert out[1]["content"] == "[Summary of earlier conversation]\nSUMMARY TEXT"
    i = split_index(msgs, 4)
    assert out[2:] == msgs[i:]
    assert len(out) < len(msgs)
    # the summarization request actually carries the old conversation
    assert "question 0" in json.dumps(req["messages"])


def test_compact_merges_into_user_message():
    msgs = convo(5)
    # keep_recent=5: start 11 -> tool, back to 10 (assistant); keep_recent=3: start 13 = user
    i = split_index(msgs, 3)
    assert msgs[i]["role"] == "user"
    client = FakeClient([summary_reply()])
    out = compact(msgs, client, "m", keep_recent=3)
    assert out[0]["role"] == "system"
    assert out[1]["role"] == "user"
    assert out[1]["content"].startswith("[Summary of earlier conversation]\nSUMMARY TEXT")
    assert msgs[i]["content"] in out[1]["content"]
    assert out[2:] == msgs[i + 1:]
    roles = [m["role"] for m in out]
    assert all(not (a == b == "user") for a, b in zip(roles, roles[1:]))


def test_compact_keeps_tool_pairs():
    msgs = convo(6)
    for keep in range(1, 12):
        out = compact(msgs, FakeClient([summary_reply()]), "m", keep_recent=keep)
        ids = {tc["id"] for m in out if m["role"] == "assistant"
               for tc in m.get("tool_calls") or []}
        assert all(m["tool_call_id"] in ids for m in out if m["role"] == "tool")


def test_compact_without_system_message():
    msgs = convo(5)[1:]
    client = FakeClient([summary_reply()])
    out = compact(msgs, client, "m", keep_recent=4)
    assert out[0]["role"] == "user" and "SUMMARY TEXT" in out[0]["content"]
    assert "question 0" in json.dumps(client.requests[0]["messages"])


def test_compact_with_nothing_to_summarize_makes_no_call():
    msgs = convo(1)
    client = FakeClient([])
    assert compact(msgs, client, "m", keep_recent=6) == msgs
    assert client.requests == []


def test_needs_compaction_uses_usage_then_estimate():
    msgs = convo(2)
    cm = ContextManager(1000)
    assert cm.last_prompt_tokens is None
    assert cm.needs_compaction([{"role": "user", "content": "x" * 4000}])  # estimate > 800
    assert not cm.needs_compaction([{"role": "user", "content": "hi"}])
    cm.last_prompt_tokens = 790
    assert not cm.needs_compaction(msgs[:1])
    cm.last_prompt_tokens = 900
    assert cm.needs_compaction(msgs[:1])


class Recorder(AgentEvents):
    def __init__(self):
        self.compactions = []

    def on_compact(self, before, after):
        self.compactions.append((before, after))


def make_agent(tmp_path, script, context, **kw):
    client = FakeClient(script)
    agent = Agent(client, "m", make_default_tools(Workspace(tmp_path)), system="sys",
                  context=context, **kw)
    return agent, client


def test_agent_compacts_when_over_threshold(tmp_path):
    (tmp_path / "a.txt").write_text("hello")
    rec = Recorder()
    script = [reply(tool_calls=[call("read_file", {"path": "a.txt"})], prompt_tokens=900),
              summary_reply(), reply(content="done", prompt_tokens=300)]
    agent, client = make_agent(tmp_path, script, ContextManager(1000, keep_recent=2),
                               events=rec)
    result = agent.run("look at a.txt")
    assert result.stop_reason == "done"
    assert len(client.requests) == 3
    assert "tools" in client.requests[0]
    assert "tools" not in client.requests[1]  # the summary request
    assert "tools" in client.requests[2]
    assert "SUMMARY TEXT" not in json.dumps(client.requests[1])
    assert any("[Summary of earlier conversation]" in str(m.get("content"))
               for m in client.requests[2]["messages"])
    assert len(rec.compactions) == 1
    before, after = rec.compactions[0]
    assert before > 0 and after > 0
    assert any("[Summary" in str(m["content"]) for m in agent.messages)


def test_console_events_print_compaction():
    import io
    from rich.console import Console
    from agent.cli import ConsoleEvents
    out = io.StringIO()
    ConsoleEvents(Console(file=out, width=80)).on_compact(9000, 2000)
    assert "9000" in out.getvalue() and "2000" in out.getvalue()


def test_agent_without_context_never_compacts(tmp_path):
    script = [reply(content="ok", prompt_tokens=99999)]
    agent, client = make_agent(tmp_path, script, None)
    assert agent.run("hi").stop_reason == "done"
    assert len(client.requests) == 1


def test_agent_trims_old_tool_results_permanently(tmp_path):
    agent, client = make_agent(tmp_path, [reply(content="ok")], ContextManager(10**6))
    agent.messages = convo(5)
    agent.run("next")
    sent = client.requests[0]["messages"]
    assert any(str(m.get("content")).startswith("[old tool result removed") for m in sent)
    assert any(str(m.get("content")).startswith("[old tool result removed")
               for m in agent.messages)


def test_streaming_usage_feeds_the_manager(tmp_path):
    (tmp_path / "a.txt").write_text("hello")
    cm = ContextManager(1000, keep_recent=2)
    script = [reply(tool_calls=[call("read_file", {"path": "a.txt"})], prompt_tokens=900),
              summary_reply(), reply(content="done", prompt_tokens=300)]
    agent, client = make_agent(tmp_path, script, cm, stream=True)
    agent.run("look")
    assert len(client.requests) == 3 and "tools" not in client.requests[1]
    assert "stream" not in client.requests[1]  # the summary is not streamed
    assert cm.last_prompt_tokens == 300


def long_history():
    return convo(5)


def test_context_overflow_retry(tmp_path):
    rec = Recorder()
    script = [bad_request("context length exceeded"), summary_reply(), reply(content="ok")]
    agent, client = make_agent(tmp_path, script, ContextManager(10**6, keep_recent=4),
                               events=rec)
    agent.messages = long_history()
    result = agent.run("go on")
    assert result.stop_reason == "done" and result.final_text == "ok"
    assert len(client.requests) == 3
    assert "tools" not in client.requests[1]
    assert len(rec.compactions) == 1


def test_context_overflow_twice_errors(tmp_path):
    script = [bad_request("context length exceeded"), summary_reply(),
              bad_request("context length exceeded")]
    agent, client = make_agent(tmp_path, script, ContextManager(10**6, keep_recent=4))
    agent.messages = long_history()
    result = agent.run("go on")
    assert result.stop_reason == "error" and "context" in result.error
    assert len(client.requests) == 3


LM_STUDIO_BODY = ('Engine protocol predict request returned 400: {"error":{"code":400,"message":'
                  '"request (60052 tokens) exceeds the available context size (32768 tokens), '
                  'try increasing it","type":"exceed_context_size_error"}}')


def lm_studio_overflow():
    """Shaped like the real thing: str(exc) says nothing, the wording is in ``body``."""
    import httpx2
    import openai
    response = httpx2.Response(400, request=httpx2.Request("POST", "http://fake/v1"),
                               json={"error": LM_STUDIO_BODY})
    return openai.BadRequestError("Error code: 400", response=response, body=LM_STUDIO_BODY)


def test_overflow_is_detected_in_the_body_not_just_str(tmp_path):
    exc = lm_studio_overflow()
    assert "context" not in str(exc).lower() and is_context_overflow(exc)
    assert not is_context_overflow(bad_request("invalid tool schema"))
    script = [exc, summary_reply(), reply(content="ok")]
    agent, client = make_agent(tmp_path, script, ContextManager(10**6, keep_recent=4))
    agent.messages = long_history()
    assert agent.run("go").stop_reason == "done"
    # a failed request reports what the server said, not just "Error code: 400"
    agent2, _ = make_agent(tmp_path, [lm_studio_overflow(), summary_reply(),
                                      lm_studio_overflow()],
                           ContextManager(10**6, keep_recent=4))
    agent2.messages = long_history()
    assert "exceeds the available context size" in agent2.run("go").error


def test_error_text_does_not_repeat_the_body():
    import httpx2
    import openai
    body = {"error": {"message": "no such model: zzz-unique"}}
    response = httpx2.Response(404, request=httpx2.Request("POST", "http://fake/v1"), json=body)
    exc = openai.NotFoundError("Error code: 404 - " + str(body), response=response, body=body)
    assert error_text(exc).count("zzz-unique") == 1
    assert error_text(lm_studio_overflow()).count("exceeds the available context size") == 1


def test_other_bad_requests_are_not_retried(tmp_path):
    agent, client = make_agent(tmp_path, [bad_request("invalid tool schema")],
                               ContextManager(10**6))
    assert agent.run("hi").stop_reason == "error"
    assert len(client.requests) == 1


def test_overflow_without_context_manager_is_an_error(tmp_path):
    agent, client = make_agent(tmp_path, [bad_request("context length exceeded")], None)
    assert agent.run("hi").stop_reason == "error"
    assert len(client.requests) == 1


@pytest.mark.live
def test_live_overflow_message(tmp_path):
    import openai
    from agent.client import make_client
    from agent.config import Config
    config = Config(base_url="http://localhost:1234/v1", model="qwen/qwen3.8-27b",
                    api_key="lm-studio")
    client = make_client(config)
    huge = "the quick brown fox jumps over the lazy dog. " * 6000  # far over 32K tokens
    agent = Agent(client, config.model, make_default_tools(Workspace(tmp_path)),
                  context=ContextManager(config.context_window))
    try:
        client.chat.completions.create(model=config.model, max_tokens=8,
                                       messages=[{"role": "user", "content": huge}])
    except openai.BadRequestError as exc:
        print(f"\nREAL OVERFLOW: str={exc!s} body={exc.body!r}")
        assert is_context_overflow(exc)
        return
    except openai.APIError as exc:
        pytest.fail(f"not a BadRequestError: {type(exc).__name__}: {exc}")
    pytest.fail("server accepted an oversized prompt (silently truncated?)")
