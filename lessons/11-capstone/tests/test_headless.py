import sys

import pytest

import agent.headless as headless
from agent.config import Config
from agent.headless import RunReport, SandboxUnavailable, run_task
from agent.log import read_log
from testing.fake_model import FakeClient, call, reply


def config(tmp_path):
    return Config(log_dir=tmp_path / "logs")


def test_requires_sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(headless, "sandbox_available", lambda: False)
    with pytest.raises(SandboxUnavailable):
        run_task("do it", tmp_path, config(tmp_path), client=FakeClient([]))
    # opting out of the requirement runs anyway
    report = run_task("do it", tmp_path, config(tmp_path), client=FakeClient([reply(content="ok")]),
                      require_sandbox=False)
    assert report.stop_reason == "done"


def test_run_task_with_fake(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    client = FakeClient([
        reply(tool_calls=[call("write_file", {"path": "a.txt", "content": "hi"})],
              prompt_tokens=100, completion_tokens=10),
        reply(content="All done.", prompt_tokens=150, completion_tokens=5),
    ])
    report = run_task("make a.txt", root, config(tmp_path), client=client, require_sandbox=False)
    assert isinstance(report, RunReport)
    assert (root / "a.txt").read_text() == "hi"
    assert report.stop_reason == "done"
    assert report.final_text == "All done."
    assert report.turns == 2
    assert (report.prompt_tokens, report.completion_tokens) == (250, 15)
    assert report.duration_s >= 0
    assert report.verified is None  # no verify command: no check ran
    assert report.log_path is not None and report.log_path.is_file()
    assert len(read_log(report.log_path)) == 2
    # permission prompts are off: the write ran without an approver
    assert client.requests[0]["messages"][0]["role"] == "system"


def test_verify_command_used(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "ok.flag").write_text("")
    # fails the first time (flag exists), the model removes it, passes the second time
    cmd = "test ! -e ok.flag"
    client = FakeClient([
        reply(content="I think it is fixed."),
        reply(tool_calls=[call("bash", {"command": "rm ok.flag"})]),
        reply(content="Fixed now."),
    ])
    report = run_task("fix", root, config(tmp_path), client=client, require_sandbox=False,
                      verify_command=cmd)
    assert report.verified is True
    assert report.final_text == "Fixed now."
    assert report.turns == 3
    assert "[Automatic check failed]" in client.requests[1]["messages"][-1]["content"]


def test_verify_failure_reported(tmp_path):
    client = FakeClient([reply(content="done"), reply(content="done again")])
    report = run_task("x", tmp_path, config(tmp_path), client=client, require_sandbox=False,
                      verify_command="false")
    assert report.verified is False


def test_max_turns_reported(tmp_path):
    loop = reply(tool_calls=[call("list_files", {})])
    report = run_task("x", tmp_path, config(tmp_path), client=FakeClient([loop, loop, loop]),
                      require_sandbox=False, max_turns=2)
    assert report.stop_reason == "max_turns"
    assert report.turns == 2


@pytest.mark.sandbox
def test_verify_runs_in_sandbox(tmp_path):
    # the sandbox has a read-only filesystem outside the project, so this check can only pass
    # if it runs inside it
    client = FakeClient([reply(content="done")])
    report = run_task("x", tmp_path, config(tmp_path), client=client,
                      verify_command="! touch /etc/harness-probe 2>/dev/null")
    assert report.verified is True


def test_default_verify_command_uses_this_python():
    assert headless.DEFAULT_VERIFY_COMMAND == f"{sys.executable} -m pytest -q"


def test_cli_run_refuses_without_sandbox(tmp_path, monkeypatch, capsys):
    import agent.__main__ as cli
    monkeypatch.setattr(headless, "sandbox_available", lambda: False)
    assert cli.main(["run", "do it", "--root", str(tmp_path)]) == 1
    assert "--unsafe-no-sandbox" in capsys.readouterr().err


def test_cli_has_run_and_eval_options():
    import agent.__main__ as cli
    args = cli.build_parser().parse_args(["eval", "--n", "3"])
    assert args.n == 3 and args.project == "capstone/buggy_project"
    assert args.checker == "capstone/eval/check.py"
    assert "failing test" in args.task
    args = cli.build_parser().parse_args(["run", "t", "--unsafe-no-sandbox"])
    assert args.unsafe_no_sandbox is True
