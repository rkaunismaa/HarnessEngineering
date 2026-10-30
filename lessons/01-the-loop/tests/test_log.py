import json
import os

from agent.__main__ import main
from agent.log import RequestLog, format_entry, latest_log, read_log
from agent.loop import Agent
from agent.tools import make_default_tools
from agent.workspace import Workspace
from testing.fake_model import FakeClient, call, reply


def run_logged(tmp_path, script, log):
    (tmp_path / "a.txt").write_text("hello\n")
    agent = Agent(FakeClient(script), "m", make_default_tools(Workspace(tmp_path)), log=log)
    agent.run("go")
    return agent


def test_log_written(tmp_path):
    log = RequestLog(tmp_path / "log.jsonl")
    run_logged(tmp_path, [reply(tool_calls=[call("read_file", {"path": "a.txt"})]),
                          reply(content="done")], log)
    lines = (tmp_path / "log.jsonl").read_text().splitlines()
    assert len(lines) == 2
    for line in lines:
        entry = json.loads(line)
        assert "messages" in entry["request"]
        assert "choices" in entry["response"]
        assert entry["agent"] == "main"
        assert entry["duration_s"] >= 0
        assert "ts" in entry
    assert "client" not in json.loads(lines[0])["request"]


def test_log_keeps_reasoning(tmp_path):
    log = RequestLog(tmp_path / "log.jsonl")
    run_logged(tmp_path, [reply(content="ok", reasoning="thinking hard")], log)
    assert "thinking hard" in (tmp_path / "log.jsonl").read_text()


def test_with_agent_shares_file(tmp_path):
    log = RequestLog(tmp_path / "log.jsonl")
    sub = log.with_agent("explorer")
    log.record({"messages": []}, {"choices": []}, 0.1)
    sub.record({"messages": []}, {"choices": []}, 0.2)
    entries = read_log(tmp_path / "log.jsonl")
    assert [e["agent"] for e in entries] == ["main", "explorer"]


def test_for_session_creates_timestamped_file(tmp_path):
    log = RequestLog.for_session(tmp_path / "logs")
    log.record({"messages": []}, {"choices": []}, 0.1)
    files = list((tmp_path / "logs").glob("*.jsonl"))
    assert len(files) == 1
    assert len(files[0].stem) == len("20261030-120000")


def test_latest_log_picks_newest(tmp_path):
    assert latest_log(tmp_path / "nope") is None
    old = tmp_path / "20260101-000000.jsonl"
    new = tmp_path / "20260102-000000.jsonl"
    old.write_text("")
    new.write_text("")
    os.utime(old, (2000, 2000))
    os.utime(new, (1000, 1000))  # name order and mtime disagree: newest by name wins
    assert latest_log(tmp_path) == new


def test_format_entry_shows_tool_calls(tmp_path):
    log = RequestLog(tmp_path / "log.jsonl")
    run_logged(tmp_path, [reply(tool_calls=[call("read_file", {"path": "a.txt"})]),
                          reply(content="done")], log)
    first, second = read_log(tmp_path / "log.jsonl")
    text = format_entry(first)
    assert "read_file" in text and "a.txt" in text
    assert "main" in text
    assert "done" in format_entry(second)


def test_log_subcommand_prints_entries(tmp_path, capsys):
    log = RequestLog(tmp_path / "log.jsonl")
    run_logged(tmp_path, [reply(content="the answer")], log)
    assert main(["log", str(tmp_path / "log.jsonl")]) == 0
    assert "the answer" in capsys.readouterr().out
