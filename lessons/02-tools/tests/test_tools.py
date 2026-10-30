import time

import pytest

from agent.tools import make_default_tools
from agent.tools.registry import Tool, ToolRegistry, truncate
from agent.workspace import Workspace


def tools_for(tmp_path, **kwargs):
    return make_default_tools(Workspace(tmp_path), **kwargs)


def run(registry, name, **args):
    import json
    return registry.dispatch(name, json.dumps(args))


def test_truncate_exact():
    assert truncate("a" * 30, limit=10) == "aaaaa\n[... 20 characters truncated ...]\naaaaa"
    assert truncate("short", limit=10) == "short"
    assert truncate("a" * 10, limit=10) == "a" * 10


def test_dispatch_truncates():
    registry = ToolRegistry()
    registry.register(Tool("big", "d", {"type": "object", "properties": {}},
                           lambda: "x" * 50_000))
    result = registry.dispatch("big", "{}")
    assert len(result) < 20_100
    assert "characters truncated" in result


def test_default_tool_names(tmp_path):
    registry = tools_for(tmp_path)
    assert {"read_file", "list_files", "search", "bash"} <= set(registry.names())
    assert registry.get("list_files").read_only is True
    assert registry.get("search").read_only is True


def test_list_files_skips_git_and_sorts(tmp_path):
    for rel in ["b.txt", "a.txt", "sub/c.txt", ".git/config", "node_modules/x.js",
                "pkg/__pycache__/m.pyc", ".venv/lib.py"]:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
    assert run(tools_for(tmp_path), "list_files").splitlines() == ["a.txt", "b.txt", "sub/c.txt"]


def test_list_files_glob(tmp_path):
    for rel in ["a.py", "b.txt", "src/c.py", "src/d.md"]:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
    registry = tools_for(tmp_path)
    assert run(registry, "list_files", pattern="**/*.py").splitlines() == ["a.py", "src/c.py"]
    assert run(registry, "list_files", path="src").splitlines() == ["src/c.py", "src/d.md"]


def test_list_files_caps_at_500(tmp_path):
    for i in range(503):
        (tmp_path / f"f{i:04}.txt").write_text("x")
    lines = run(tools_for(tmp_path), "list_files").splitlines()
    assert len(lines) == 501
    assert lines[-1] == "[3 more files not shown]"


def test_search_matches_format(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("import os\n\ndef foo():\n    pass\n")
    (tmp_path / "b.txt").write_text("nothing here\n")
    assert run(tools_for(tmp_path), "search", pattern=r"def \w+").splitlines() == \
        ["src/a.py:3: def foo():"]


def test_search_glob_and_path(tmp_path):
    (tmp_path / "a.py").write_text("needle\n")
    (tmp_path / "a.txt").write_text("needle\n")
    registry = tools_for(tmp_path)
    assert run(registry, "search", pattern="needle", glob="*.py") == "a.py:1: needle"


def test_search_glob_without_slash_matches_any_depth(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "deep.py").write_text("needle\n")
    (tmp_path / "pkg" / "deep.txt").write_text("needle\n")
    assert run(tools_for(tmp_path), "search", pattern="needle", glob="*.py") == \
        "pkg/deep.py:1: needle"


def test_search_caps_matches(tmp_path):
    (tmp_path / "a.txt").write_text("hit\n" * 205)
    lines = run(tools_for(tmp_path), "search", pattern="hit").splitlines()
    assert len(lines) == 201
    assert lines[-1] == "[5 more matches not shown]"


def test_search_invalid_regex(tmp_path):
    result = run(tools_for(tmp_path), "search", pattern="(unclosed")
    assert result.startswith("Error: invalid regular expression: ")


def test_search_no_matches(tmp_path):
    (tmp_path / "a.txt").write_text("hello\n")
    assert run(tools_for(tmp_path), "search", pattern="zzz") == "No matches."


def test_search_skips_binary(tmp_path):
    (tmp_path / "bin.dat").write_bytes(b"\xff\xfe\x00needle")
    (tmp_path / "ok.txt").write_text("needle\n")
    assert run(tools_for(tmp_path), "search", pattern="needle") == "ok.txt:1: needle"


def test_read_file_binary_returns_error(tmp_path):
    (tmp_path / "bin.dat").write_bytes(b"\xff\xfe\x00")
    assert run(tools_for(tmp_path), "read_file", path="bin.dat") == \
        "Error: bin.dat is not a UTF-8 text file."


def test_bash_exit_code(tmp_path):
    assert run(tools_for(tmp_path), "bash", command="echo hi; exit 3") == "hi\n\n[exit code: 3]"


def test_bash_runs_in_workspace_and_combines_stderr(tmp_path):
    result = run(tools_for(tmp_path), "bash", command="pwd; echo oops >&2")
    assert str(tmp_path.resolve()) in result
    assert "oops" in result
    assert result.endswith("[exit code: 0]")


def test_bash_timeout(tmp_path):
    start = time.monotonic()
    result = run(tools_for(tmp_path), "bash", command="echo start; sleep 10", timeout=1)
    assert time.monotonic() - start < 3
    assert "start" in result
    assert "[timed out after 1s]" in result


def test_bash_huge_output_is_truncated_by_dispatch(tmp_path):
    result = run(tools_for(tmp_path), "bash", command="yes | head -c 200000")
    assert "characters truncated" in result
    assert len(result) < 20_200


def test_bash_declined(tmp_path):
    asked = []

    def confirm(command):
        asked.append(command)
        return False

    registry = tools_for(tmp_path, confirm_bash=confirm)
    result = run(registry, "bash", command="touch marker.txt")
    assert result == "Error: the user declined to run this command."
    assert asked == ["touch marker.txt"]
    assert not (tmp_path / "marker.txt").exists()


def test_bash_confirmed_runs(tmp_path):
    registry = tools_for(tmp_path, confirm_bash=lambda c: True)
    assert run(registry, "bash", command="echo ok") == "ok\n\n[exit code: 0]"


@pytest.mark.live
def test_live_finds_function(tmp_path):
    from agent.client import make_client
    from agent.config import load_config
    from agent.loop import Agent
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "util.py").write_text("def helper():\n    return 1\n")
    (tmp_path / "app" / "billing.py").write_text(
        "def compute_invoice_total(items):\n    return sum(items)\n")
    (tmp_path / "app" / "main.py").write_text("print('hi')\n")
    config = load_config()
    agent = Agent(make_client(config), config.model,
                  make_default_tools(Workspace(tmp_path), confirm_bash=lambda c: False))
    result = agent.run("Which file defines the function compute_invoice_total? "
                       "Answer with the file path.")
    assert result.stop_reason in {"done", "error"}
    assert "billing.py" in result.final_text
