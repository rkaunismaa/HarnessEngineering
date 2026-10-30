import json
import os

import pytest

from agent.loop import Agent
from agent.permissions import Decision, PermissionPolicy, SHELL_OPERATORS
from agent.tools import make_default_tools
from agent.workspace import PathOutsideProject, Workspace
from testing.fake_model import FakeClient, call, reply

DENIED_BY_RULE = "Error: this call is blocked by a deny rule."
DENIED_BY_USER = "Error: the user denied this tool call."
NO_APPROVER = "Error: this call needs approval but no approver is available."
LOOP_MESSAGE = "Error: you have made this exact call 3 times in a row. Try a different approach."


def tools_for(tmp_path):
    return make_default_tools(Workspace(tmp_path))


def run(registry, name, **args):
    return registry.dispatch(name, json.dumps(args))


def tool_results(agent):
    return [m["content"] for m in agent.messages if m["role"] == "tool"]


def make_agent(tmp_path, script, **kwargs):
    client = FakeClient(script)
    return Agent(client, "m", tools_for(tmp_path), **kwargs), client


# --- PermissionPolicy.check ------------------------------------------------

def test_shell_operators_exact():
    assert SHELL_OPERATORS == (";", "&&", "||", "|", "`", "$(", ">", "<", "\n", "&")


def test_read_only_allowed(tmp_path):
    tools = tools_for(tmp_path)
    policy = PermissionPolicy()
    for name in ("read_file", "list_files", "search"):
        assert policy.check(tools.get(name), {"path": "a.txt", "pattern": "x"}) == Decision.ALLOW


def test_mutating_asks(tmp_path):
    tools = tools_for(tmp_path)
    policy = PermissionPolicy()
    assert policy.check(tools.get("bash"), {"command": "ls"}) == Decision.ASK
    assert policy.check(tools.get("edit_file"),
                        {"path": "a.txt", "old_string": "a", "new_string": "b"}) == Decision.ASK
    assert policy.check(tools.get("write_file"), {"path": "a.txt", "content": ""}) == Decision.ASK


def test_deny_beats_allow(tmp_path):
    tools = tools_for(tmp_path)
    policy = PermissionPolicy(allow=["bash(rm*)"], deny=["bash(rm*)"])
    assert policy.check(tools.get("bash"), {"command": "rm -rf build"}) == Decision.DENY


def test_deny_beats_read_only(tmp_path):
    tools = tools_for(tmp_path)
    policy = PermissionPolicy(deny=["read_file(*.env)"])
    assert policy.check(tools.get("read_file"), {"path": "prod.env"}) == Decision.DENY
    assert policy.check(tools.get("read_file"), {"path": "a.py"}) == Decision.ALLOW


def test_deny_beats_auto_approve(tmp_path):
    tools = tools_for(tmp_path)
    policy = PermissionPolicy(deny=["write_file"], auto_approve=True)
    assert policy.check(tools.get("write_file"), {"path": "a", "content": ""}) == Decision.DENY


def test_allow_prefix_rule(tmp_path):
    tools = tools_for(tmp_path)
    policy = PermissionPolicy(allow=["bash(pytest*)"])
    assert policy.check(tools.get("bash"), {"command": "pytest -q"}) == Decision.ALLOW
    assert policy.check(tools.get("bash"), {"command": "python -m pytest"}) == Decision.ASK


def test_allow_rule_is_case_sensitive(tmp_path):
    tools = tools_for(tmp_path)
    policy = PermissionPolicy(allow=["bash(pytest*)"])
    assert policy.check(tools.get("bash"), {"command": "PYTEST -q"}) == Decision.ASK


def test_allow_path_rule(tmp_path):
    tools = tools_for(tmp_path)
    policy = PermissionPolicy(allow=["edit_file(src/*)"])
    edit = tools.get("edit_file")
    assert policy.check(edit, {"path": "src/app.py", "old_string": "a",
                               "new_string": "b"}) == Decision.ALLOW
    assert policy.check(edit, {"path": "setup.py", "old_string": "a",
                               "new_string": "b"}) == Decision.ASK
    # a rule for one tool does not cover another
    assert policy.check(tools.get("write_file"),
                        {"path": "src/app.py", "content": ""}) == Decision.ASK


def test_bare_rule_matches_any_arguments(tmp_path):
    tools = tools_for(tmp_path)
    policy = PermissionPolicy(allow=["write_file"])
    assert policy.check(tools.get("write_file"), {"path": "x/y", "content": ""}) == Decision.ALLOW


@pytest.mark.parametrize("command", [
    "git status && rm -rf x", "git status; rm -rf x", "git status || rm -rf x",
    "git status | sh", "git status `rm -rf x`", "git status $(rm -rf x)",
    "git status > important.txt", "git status < /dev/null", "git status\nrm -rf x",
    "git status & rm -rf x",
])
def test_operators_never_auto_allowed(tmp_path, command):
    tools = tools_for(tmp_path)
    policy = PermissionPolicy(allow=["bash(git status*)", "bash"])
    assert policy.check(tools.get("bash"), {"command": command}) == Decision.ASK
    assert policy.check(tools.get("bash"), {"command": "git status -s"}) == Decision.ALLOW


def test_background_operator_not_allowed(tmp_path):
    tools = tools_for(tmp_path)
    policy = PermissionPolicy(allow=["bash(pytest*)"])
    assert policy.check(tools.get("bash"), {"command": "pytest -q & rm -rf x"}) == Decision.ASK


def test_operators_still_hit_deny_rules(tmp_path):
    tools = tools_for(tmp_path)
    policy = PermissionPolicy(deny=["bash(*rm -rf*)"])
    assert policy.check(tools.get("bash"), {"command": "ls && rm -rf x"}) == Decision.DENY


def test_auto_approve(tmp_path):
    tools = tools_for(tmp_path)
    policy = PermissionPolicy(auto_approve=True)
    assert policy.check(tools.get("bash"), {"command": "ls && rm -rf x"}) == Decision.ALLOW
    assert policy.check(tools.get("write_file"), {"path": "a", "content": ""}) == Decision.ALLOW


def test_remember_escapes_glob_chars(tmp_path):
    tools = tools_for(tmp_path)
    bash = tools.get("bash")
    policy = PermissionPolicy()
    policy.remember(bash, {"command": "ls *.py"})
    assert policy.check(bash, {"command": "ls *.py"}) == Decision.ALLOW
    assert policy.check(bash, {"command": "ls a.py"}) == Decision.ASK
    assert policy.check(bash, {"command": "ls *.py; rm x"}) == Decision.ASK


def test_remember_non_bash_is_bare_tool_name(tmp_path):
    tools = tools_for(tmp_path)
    policy = PermissionPolicy()
    policy.remember(tools.get("edit_file"), {"path": "a.txt", "old_string": "a", "new_string": "b"})
    assert policy.check(tools.get("edit_file"),
                        {"path": "other.txt", "old_string": "x", "new_string": "y"}) == Decision.ALLOW


# --- Path rules see the normalized path -------------------------------------

def test_path_rules_use_normalized_path(tmp_path):
    ws = Workspace(tmp_path)
    tools = make_default_tools(ws)
    edit = tools.get("edit_file")
    policy = PermissionPolicy(allow=["edit_file(src/*)"])
    e = {"old_string": "a", "new_string": "b"}
    assert policy.check(edit, {"path": "src/../setup.py", **e}, ws) == Decision.ASK
    assert policy.check(edit, {"path": "./src/app.py", **e}, ws) == Decision.ALLOW
    assert policy.check(edit, {"path": str(tmp_path / "src" / "app.py"), **e}, ws) == \
        Decision.ALLOW


def test_deny_path_rule_not_bypassed_by_spelling(tmp_path):
    ws = Workspace(tmp_path)
    read = make_default_tools(ws).get("read_file")
    policy = PermissionPolicy(deny=["read_file(secrets/*)"])
    for path in ["secrets/key", "./secrets/key", "x/../secrets/key",
                 str(tmp_path / "secrets" / "key")]:
        assert policy.check(read, {"path": path}, ws) == Decision.DENY, path
    assert policy.check(read, {"path": "src/key"}, ws) == Decision.ALLOW


def test_deny_path_rule_through_symlink(tmp_path):
    (tmp_path / "secrets").mkdir()
    os.symlink(tmp_path / "secrets", tmp_path / "public")
    ws = Workspace(tmp_path)
    read = make_default_tools(ws).get("read_file")
    policy = PermissionPolicy(deny=["read_file(secrets/*)"])
    assert policy.check(read, {"path": "public/key"}, ws) == Decision.DENY


def test_outside_path_never_allowed(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    ws = Workspace(root)
    write = make_default_tools(ws).get("write_file")
    policy = PermissionPolicy(allow=["write_file", "write_file(*)"])
    assert policy.check(write, {"path": "../x", "content": ""}, ws) == Decision.ASK
    assert policy.check(write, {"path": "a/b.txt", "content": ""}, ws) == Decision.ALLOW


def test_without_workspace_rules_see_raw_argument(tmp_path):
    read = tools_for(tmp_path).get("read_file")
    policy = PermissionPolicy(deny=["read_file(secrets/*)"])
    assert policy.check(read, {"path": "secrets/key"}) == Decision.DENY
    assert policy.check(read, {"path": "./secrets/key"}) == Decision.ALLOW


def test_agent_uses_workspace_for_path_rules(tmp_path):
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets" / "key").write_text("hunter2\n")
    ws = Workspace(tmp_path)
    client = FakeClient([reply(tool_calls=[call("read_file", {"path": "./secrets/key"})]),
                         reply(content="ok")])
    agent = Agent(client, "m", make_default_tools(ws), workspace=ws,
                  permissions=PermissionPolicy(deny=["read_file(secrets/*)"]))
    agent.run("go")
    assert tool_results(agent) == [DENIED_BY_RULE]


# --- Agent integration -----------------------------------------------------

def test_agent_without_policy_runs_everything(tmp_path):
    agent, _ = make_agent(tmp_path, [
        reply(tool_calls=[call("bash", {"command": "touch made.txt"})]), reply(content="ok")])
    agent.run("go")
    assert (tmp_path / "made.txt").exists()


def test_agent_denied_result(tmp_path):
    asked = []

    def approver(name, args):
        asked.append((name, args))
        return "no"

    agent, _ = make_agent(tmp_path, [
        reply(tool_calls=[call("bash", {"command": "touch made.txt"}),
                          call("bash", {"command": "rm -rf x"})]),
        reply(content="ok")],
        permissions=PermissionPolicy(deny=["bash(rm *)"]), approver=approver)
    result = agent.run("go")
    assert result.stop_reason == "done"
    assert tool_results(agent) == [DENIED_BY_USER, DENIED_BY_RULE]
    assert asked == [("bash", {"command": "touch made.txt"})]
    assert not (tmp_path / "made.txt").exists()


def test_agent_approved_runs(tmp_path):
    agent, _ = make_agent(tmp_path, [
        reply(tool_calls=[call("bash", {"command": "echo hi"})]), reply(content="ok")],
        permissions=PermissionPolicy(), approver=lambda name, args: "yes")
    agent.run("go")
    assert tool_results(agent) == ["hi\n\n[exit code: 0]"]


def test_agent_yes_does_not_remember(tmp_path):
    asked = []
    agent, _ = make_agent(tmp_path, [
        reply(tool_calls=[call("bash", {"command": "echo hi"})]),
        reply(tool_calls=[call("bash", {"command": "echo hi"})]), reply(content="ok")],
        permissions=PermissionPolicy(),
        approver=lambda name, args: (asked.append(name), "yes")[1])
    agent.run("go")
    assert len(asked) == 2


def test_agent_no_approver(tmp_path):
    agent, _ = make_agent(tmp_path, [
        reply(tool_calls=[call("write_file", {"path": "a.txt", "content": "x"})]),
        reply(content="ok")], permissions=PermissionPolicy())
    agent.run("go")
    assert tool_results(agent) == [NO_APPROVER]
    assert not (tmp_path / "a.txt").exists()


def test_agent_read_only_needs_no_approver(tmp_path):
    (tmp_path / "a.txt").write_text("hello\n")
    agent, _ = make_agent(tmp_path, [
        reply(tool_calls=[call("read_file", {"path": "a.txt"})]), reply(content="ok")],
        permissions=PermissionPolicy())
    agent.run("go")
    assert tool_results(agent) == ["     1\thello"]


def test_agent_always_then_no_prompt(tmp_path):
    (tmp_path / "a.txt").write_text("one two\n")
    asked = []

    def approver(name, args):
        asked.append(name)
        return "always"

    agent, _ = make_agent(tmp_path, [
        reply(tool_calls=[call("read_file", {"path": "a.txt"})]),
        reply(tool_calls=[call("edit_file", {"path": "a.txt", "old_string": "one",
                                             "new_string": "1"})]),
        reply(tool_calls=[call("edit_file", {"path": "a.txt", "old_string": "two",
                                             "new_string": "2"})]),
        reply(content="done")],
        permissions=PermissionPolicy(), approver=approver)
    agent.run("go")
    assert asked == ["edit_file"]
    assert (tmp_path / "a.txt").read_text() == "1 2\n"


def test_agent_bad_arguments_skip_approval(tmp_path):
    asked = []
    agent, _ = make_agent(tmp_path, [
        reply(tool_calls=[call("bash", '{"command":'), call("nope", {}), call("bash", {})]),
        reply(content="ok")],
        permissions=PermissionPolicy(), approver=lambda n, a: (asked.append(n), "yes")[1])
    agent.run("go")
    results = tool_results(agent)
    assert results[0].startswith("Error: arguments were not valid JSON")
    assert results[1].startswith("Error: unknown tool 'nope'")
    assert results[2] == "Error: missing required parameter 'command'"
    assert asked == []


def test_denied_calls_count_for_loop_detection(tmp_path):
    c = call("bash", {"command": "rm -rf x"})
    agent, _ = make_agent(tmp_path, [reply(tool_calls=[c, c, c]), reply(content="ok")],
                          permissions=PermissionPolicy(deny=["bash"]))
    agent.run("go")
    assert tool_results(agent) == [DENIED_BY_RULE, DENIED_BY_RULE, LOOP_MESSAGE]


# --- Staying inside the project -------------------------------------------

def test_path_outside_project(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    (tmp_path / "x").write_text("secret\n")
    tools = tools_for(root)
    assert run(tools, "read_file", path="../x") == "Error: ../x is outside the project folder."
    assert run(tools, "write_file", path="../y", content="z") == \
        "Error: ../y is outside the project folder."
    assert not (tmp_path / "y").exists()
    assert run(tools, "edit_file", path="../x", old_string="secret", new_string="s") == \
        "Error: ../x is outside the project folder."
    assert run(tools, "list_files", path="..") == "Error: .. is outside the project folder."
    assert run(tools, "search", pattern="secret", path="../x") == \
        "Error: ../x is outside the project folder."
    assert run(tools, "read_file", path=str(tmp_path / "x")) == \
        f"Error: {tmp_path / 'x'} is outside the project folder."
    assert "x" not in run(tools, "list_files", pattern="../*")


def test_resolve_raises(tmp_path):
    ws = Workspace(tmp_path)
    with pytest.raises(PathOutsideProject):
        ws.resolve("../x")
    with pytest.raises(PathOutsideProject):
        ws.resolve("/etc/hostname")
    assert ws.resolve(".") == tmp_path.resolve()
    assert ws.resolve("sub/../a.txt") == tmp_path.resolve() / "a.txt"
    assert ws.resolve(str(tmp_path / "a.txt")) == tmp_path.resolve() / "a.txt"


def test_sibling_with_same_prefix_is_outside(tmp_path):
    (tmp_path / "proj").mkdir()
    (tmp_path / "proj2").mkdir()
    ws = Workspace(tmp_path / "proj")
    with pytest.raises(PathOutsideProject):
        ws.resolve("../proj2/a.txt")


def test_symlink_escape(tmp_path):
    os.symlink("/etc", tmp_path / "inside")
    tools = tools_for(tmp_path)
    assert run(tools, "read_file", path="inside/hostname") == \
        "Error: inside/hostname is outside the project folder."


def test_symlink_escape_not_listed_or_searched(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("password=hunter2\n")
    root = tmp_path / "proj"
    root.mkdir()
    (root / "ok.txt").write_text("password=fine\n")
    os.symlink(outside, root / "link")
    os.symlink(outside / "secret.txt", root / "leak.txt")
    tools = tools_for(root)
    assert "hunter2" not in run(tools, "search", pattern="password")
    listed = run(tools, "list_files")
    assert "secret.txt" not in listed and "leak.txt" not in listed
    assert "ok.txt" in listed


def test_edit_same_file_via_dotdot_spelling(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.txt").write_text("one\n")
    tools = tools_for(tmp_path)
    run(tools, "read_file", path="sub/../a.txt")
    assert run(tools, "edit_file", path="a.txt", old_string="one", new_string="1") == \
        "Edited a.txt (1 replacement)."


# --- CLI flags ---------------------------------------------------------------

def test_cli_ask_flags():
    from agent.__main__ import build_parser
    args = build_parser().parse_args(
        ["ask", "hi", "--allow", "bash(pytest*)", "--allow", "edit_file", "--no-sandbox"])
    assert args.allow == ["bash(pytest*)", "edit_file"]
    assert args.sandbox is False
    args = build_parser().parse_args(["ask", "hi"])
    assert args.allow == []
    assert args.sandbox is None  # decided at run time: on when bwrap is usable
    assert build_parser().parse_args(["ask", "hi", "--sandbox"]).sandbox is True
