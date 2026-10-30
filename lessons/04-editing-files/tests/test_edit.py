import json
import os

import pytest

from agent.tools import make_default_tools
from agent.workspace import Workspace

NOT_READ = "Error: read the file with read_file before editing it."
CHANGED = "Error: the file changed on disk since you last read it. Read it again before editing."


def tools_for(tmp_path):
    return make_default_tools(Workspace(tmp_path), confirm_bash=lambda c: False)


def run(registry, name, **args):
    return registry.dispatch(name, json.dumps(args))


def edit(registry, path, old, new, **kw):
    return run(registry, "edit_file", path=path, old_string=old, new_string=new, **kw)


def test_tools_registered(tmp_path):
    names = tools_for(tmp_path).names()
    assert {"edit_file", "write_file"} <= set(names)


def test_edit_requires_read(tmp_path):
    (tmp_path / "a.txt").write_text("hello\n")
    registry = tools_for(tmp_path)
    assert edit(registry, "a.txt", "hello", "bye") == NOT_READ
    assert (tmp_path / "a.txt").read_text() == "hello\n"


def test_edit_unique_match(tmp_path):
    (tmp_path / "a.txt").write_text("one\ntwo\nthree\n")
    registry = tools_for(tmp_path)
    run(registry, "read_file", path="a.txt")
    assert edit(registry, "a.txt", "two", "2") == "Edited a.txt (1 replacement)."
    assert (tmp_path / "a.txt").read_text() == "one\n2\nthree\n"


def test_edit_same_file_via_different_spelling(tmp_path):
    (tmp_path / "a.txt").write_text("one\n")
    registry = tools_for(tmp_path)
    run(registry, "read_file", path="./a.txt")
    assert edit(registry, "a.txt", "one", "1") == "Edited a.txt (1 replacement)."


def test_edit_multiple_matches_error(tmp_path):
    (tmp_path / "a.txt").write_text("x\nx\nx\n")
    registry = tools_for(tmp_path)
    run(registry, "read_file", path="a.txt")
    assert edit(registry, "a.txt", "x", "y") == (
        "Error: old_string appears 3 times. Include more surrounding lines to make it "
        "unique, or set replace_all to true.")
    assert (tmp_path / "a.txt").read_text() == "x\nx\nx\n"


def test_edit_replace_all(tmp_path):
    (tmp_path / "a.txt").write_text("x\nx\nx\n")
    registry = tools_for(tmp_path)
    run(registry, "read_file", path="a.txt")
    assert edit(registry, "a.txt", "x", "y", replace_all=True) == "Edited a.txt (3 replacements)."
    assert (tmp_path / "a.txt").read_text() == "y\ny\ny\n"


def test_edit_not_found(tmp_path):
    (tmp_path / "a.txt").write_text("hello\n")
    registry = tools_for(tmp_path)
    run(registry, "read_file", path="a.txt")
    assert edit(registry, "a.txt", "nope", "x") == "Error: old_string was not found in the file."


def test_edit_same_strings(tmp_path):
    (tmp_path / "a.txt").write_text("hello\n")
    registry = tools_for(tmp_path)
    run(registry, "read_file", path="a.txt")
    assert edit(registry, "a.txt", "hello", "hello") == \
        "Error: old_string and new_string are the same."


def test_edit_missing_file(tmp_path):
    registry = tools_for(tmp_path)
    assert edit(registry, "nope.txt", "a", "b").startswith("Error:")


def test_edit_detects_external_change(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("hello\n")
    registry = tools_for(tmp_path)
    run(registry, "read_file", path="a.txt")
    st = p.stat()
    p.write_text("hello world\n")
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    assert edit(registry, "a.txt", "hello", "bye") == CHANGED
    assert p.read_text() == "hello world\n"
    # reading again clears it
    run(registry, "read_file", path="a.txt")
    assert edit(registry, "a.txt", "hello", "bye") == "Edited a.txt (1 replacement)."


def test_edit_ignores_touch_without_content_change(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("hello\n")
    registry = tools_for(tmp_path)
    run(registry, "read_file", path="a.txt")
    st = p.stat()
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    assert edit(registry, "a.txt", "hello", "bye") == "Edited a.txt (1 replacement)."


def test_edit_detects_deleted_file(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("hello\n")
    registry = tools_for(tmp_path)
    run(registry, "read_file", path="a.txt")
    p.unlink()
    assert edit(registry, "a.txt", "hello", "bye").startswith("Error:")


def test_edit_then_edit_again_without_reread_ok(tmp_path):
    (tmp_path / "a.txt").write_text("one two\n")
    registry = tools_for(tmp_path)
    run(registry, "read_file", path="a.txt")
    assert edit(registry, "a.txt", "one", "1") == "Edited a.txt (1 replacement)."
    assert edit(registry, "a.txt", "two", "2") == "Edited a.txt (1 replacement)."
    assert (tmp_path / "a.txt").read_text() == "1 2\n"


def test_write_new_file_creates_dirs(tmp_path):
    registry = tools_for(tmp_path)
    assert run(registry, "write_file", path="deep/er/new.txt", content="hi\n") == \
        "Created deep/er/new.txt."
    assert (tmp_path / "deep/er/new.txt").read_text() == "hi\n"


def test_write_existing_requires_read(tmp_path):
    (tmp_path / "a.txt").write_text("old\n")
    registry = tools_for(tmp_path)
    assert run(registry, "write_file", path="a.txt", content="new\n") == NOT_READ
    assert (tmp_path / "a.txt").read_text() == "old\n"
    run(registry, "read_file", path="a.txt")
    assert run(registry, "write_file", path="a.txt", content="new\n") == "Wrote a.txt."
    assert (tmp_path / "a.txt").read_text() == "new\n"
    # a write counts as a read: a follow-up edit needs no re-read
    assert edit(registry, "a.txt", "new", "newer") == "Edited a.txt (1 replacement)."


def test_write_created_file_can_be_edited(tmp_path):
    registry = tools_for(tmp_path)
    run(registry, "write_file", path="n.txt", content="abc\n")
    assert edit(registry, "n.txt", "abc", "xyz") == "Edited n.txt (1 replacement)."


def test_edit_preserves_trailing_newline_and_crlf(tmp_path):
    crlf = tmp_path / "crlf.txt"
    crlf.write_bytes(b"one\r\ntwo\r\nthree\r\n")
    nonl = tmp_path / "nonl.txt"
    nonl.write_bytes(b"one\ntwo")
    registry = tools_for(tmp_path)
    run(registry, "read_file", path="crlf.txt")
    run(registry, "read_file", path="nonl.txt")
    assert edit(registry, "crlf.txt", "two", "2") == "Edited crlf.txt (1 replacement)."
    assert crlf.read_bytes() == b"one\r\n2\r\nthree\r\n"
    assert edit(registry, "nonl.txt", "two", "2") == "Edited nonl.txt (1 replacement)."
    assert nonl.read_bytes() == b"one\n2"


def test_read_file_output_unchanged(tmp_path):
    (tmp_path / "a.txt").write_text("a\nb\n")
    assert run(tools_for(tmp_path), "read_file", path="a.txt") == "     1\ta\n     2\tb"


@pytest.mark.live
def test_live_edit(tmp_path):
    from agent.client import make_client
    from agent.config import Config
    from agent.loop import Agent
    target = tmp_path / "greeting.py"
    target.write_text('def greet(name):\n    return "Helo, " + name\n')
    config = Config(base_url="http://localhost:1234/v1", model="qwen/qwen3.8-27b",
                    api_key="lm-studio")
    agent = Agent(make_client(config), config.model, tools_for(tmp_path), max_turns=12)
    result = agent.run("greeting.py has a typo in the greeting word. Fix it using edit_file.")
    print(f"\nstop_reason={result.stop_reason} turns={result.turns}")
    for m in agent.messages:
        for tc in m.get("tool_calls") or []:
            print(f"  CALL {tc['function']['name']}({tc['function']['arguments']})")
        if m["role"] == "tool":
            print(f"  RESULT {m['content'][:200]!r}")
    assert result.stop_reason in {"done", "max_turns", "error"}
    assert "Hello, " in target.read_text()
