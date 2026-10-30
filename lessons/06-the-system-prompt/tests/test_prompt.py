import subprocess
import sys
from datetime import datetime

import pytest

from agent.prompt import (INSTRUCTION_FILES, MAX_INSTRUCTIONS_CHARS, build_system_prompt,
                          git_summary, load_project_instructions)
from agent.tools import make_default_tools
from agent.workspace import Workspace

NOW = datetime(2026, 10, 30)


def build(tmp_path, **kwargs):
    ws = Workspace(tmp_path)
    return build_system_prompt(ws, make_default_tools(ws), now=NOW, **kwargs)


def test_instruction_files_constants():
    assert INSTRUCTION_FILES == ("AGENTS.md", "CLAUDE.md")
    assert MAX_INSTRUCTIONS_CHARS == 10_000


def test_environment_lines(tmp_path):
    prompt = build(tmp_path)
    assert "# Environment" in prompt
    assert f"Working directory: {tmp_path.resolve()}" in prompt
    assert f"Platform: {sys.platform}" in prompt
    assert "Date: 2026-10-30" in prompt
    assert "Git: not a git repository" in prompt


def test_sections_in_order(tmp_path):
    (tmp_path / "AGENTS.md").write_text("Be brief.")
    prompt = build(tmp_path, extra="EXTRA-TEXT")
    positions = [prompt.index(s) for s in
                 ("# Using tools", "# Environment", "# Project instructions", "EXTRA-TEXT")]
    assert positions == sorted(positions)
    assert prompt.index("# Using tools") > 0  # a role section comes first


def test_tools_listed(tmp_path):
    ws = Workspace(tmp_path)
    tools = make_default_tools(ws)
    prompt = build_system_prompt(ws, tools, now=NOW)
    assert f"Tools: {', '.join(tools.names())}" in prompt


def test_tool_rules_mention_search_and_list_files(tmp_path):
    section = build(tmp_path).split("# Using tools")[1].split("# Environment")[0]
    assert "search" in section and "list_files" in section and "bash" in section


def test_agents_md_preferred_over_claude_md(tmp_path):
    (tmp_path / "AGENTS.md").write_text("from agents")
    (tmp_path / "CLAUDE.md").write_text("from claude")
    assert load_project_instructions(tmp_path) == ("AGENTS.md", "from agents")
    prompt = build(tmp_path)
    assert "# Project instructions (from AGENTS.md)" in prompt
    assert "from agents" in prompt
    assert "from claude" not in prompt


def test_claude_md_used_alone(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("only claude")
    assert load_project_instructions(tmp_path) == ("CLAUDE.md", "only claude")
    assert "# Project instructions (from CLAUDE.md)\n" in build(tmp_path)


def test_no_instructions_section_when_absent(tmp_path):
    assert load_project_instructions(tmp_path) is None
    assert "# Project instructions" not in build(tmp_path)


def test_instructions_truncated(tmp_path):
    (tmp_path / "AGENTS.md").write_text("x" * (MAX_INSTRUCTIONS_CHARS * 3))
    _, text = load_project_instructions(tmp_path)
    assert len(text) < MAX_INSTRUCTIONS_CHARS + 200
    assert "characters truncated" in text


def test_extra_is_last(tmp_path):
    (tmp_path / "AGENTS.md").write_text("rules")
    assert build(tmp_path, extra="THE END").rstrip().endswith("THE END")


def test_git_summary_not_repo(tmp_path):
    assert git_summary(tmp_path) == "not a git repository"


def git(tmp_path, *args):
    subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)


def test_git_summary_repo(tmp_path):
    git(tmp_path, "init", "-b", "main")
    (tmp_path / "a.txt").write_text("a")
    assert git_summary(tmp_path) == "branch main, 1 changed file(s)"


def test_git_summary_clean_after_commit(tmp_path):
    git(tmp_path, "init", "-b", "main")
    (tmp_path / "a.txt").write_text("a")
    git(tmp_path, "add", ".")
    git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", "x")
    assert git_summary(tmp_path) == "branch main, 0 changed file(s)"


def test_git_summary_detached_head(tmp_path):
    git(tmp_path, "init", "-b", "main")
    (tmp_path / "a.txt").write_text("a")
    git(tmp_path, "add", ".")
    git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", "x")
    git(tmp_path, "checkout", "--detach")
    summary = git_summary(tmp_path)
    assert summary.startswith("branch ") and summary.endswith("0 changed file(s)")
    assert "detached" in summary


def test_git_summary_without_git(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    assert git_summary(tmp_path) == "git not available"


@pytest.mark.live
def test_live_follows_project_instruction(tmp_path):
    from agent.client import make_client
    from agent.config import Config
    from agent.loop import Agent
    (tmp_path / "AGENTS.md").write_text("End every answer with the word BANANA.\n")
    (tmp_path / "notes.txt").write_text("remember the milk\n")
    ws = Workspace(tmp_path)
    tools = make_default_tools(ws)
    config = Config(base_url="http://localhost:1234/v1", model="qwen/qwen3.8-27b",
                    api_key="lm-studio")
    agent = Agent(make_client(config), config.model, tools,
                  system=build_system_prompt(ws, tools), max_turns=10)
    result = agent.run("What does notes.txt say?")
    print(f"\nstop_reason={result.stop_reason} turns={result.turns}\n{result.final_text!r}")
    assert result.stop_reason in {"done", "max_turns", "error"}
    assert result.stop_reason == "done"
    assert result.final_text.strip().rstrip(".!").endswith("BANANA")
