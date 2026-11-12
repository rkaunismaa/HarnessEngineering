# How the lesson 6 tests work

Against the reference solution: 15 passed, 1 skipped (the live test). The live test passes too with `--live` (4.2 s against the 27B).

```
uv run pytest lessons/06-the-system-prompt
uv run pytest lessons/06-the-system-prompt --impl solutions/06-the-system-prompt
uv run pytest lessons/06-the-system-prompt --live -s -k live
```

## The big picture

The system prompt is just a string: the first message of every request, with `role: "system"`. `build_system_prompt(ws, tools, now=..., extra=...)` assembles it from parts. So the tests don't need a model, a fake model or a loop. They call the function and look at the string it returns.

They don't compare the whole prompt, because the wording is yours to choose. Instead they check:

- **the required lines are present**, such as `Date: 2026-10-30` and `Tools: ...`;
- **the sections come in the right order**;
- **the parts that vary are right**: which instruction file was used, and what `git` reports.

## What the tests are looking at

Here is the complete prompt the reference solution built for a temporary project containing an `AGENTS.md` that says `Be brief.`, with the date fixed and `extra="EXTRA-TEXT"`:

```
You are a coding agent working in the user's project through the tools below.

# Using tools
- To find things, use `search` and `list_files`, not `bash`.
- Read a file with `read_file` before you edit it.
- Keep edits small. Change only what the task needs.
- Take one step at a time and check each result before the next.

# Environment
Working directory: /tmp/proj-tcwg2jo8
Platform: linux
Date: 2026-10-30
Git: not a git repository
Tools: read_file, list_files, search, edit_file, write_file, bash

# Project instructions (from AGENTS.md)
Be brief.

EXTRA-TEXT
```

Each part of it is pinned by a test:

| Part | Where it comes from | Test |
|---|---|---|
| The first line (the role) | fixed text | `test_sections_in_order`: something must come before `# Using tools` |
| `# Using tools` | fixed advice | `test_tool_rules_mention_search_and_list_files`: mentions `search`, `list_files`, `bash` |
| `Working directory`, `Platform`, `Date` | `ws.root`, `sys.platform`, the `now` argument | `test_environment_lines` |
| `Git: ...` | `git_summary(ws.root)` | the `test_git_summary_*` tests |
| `Tools: ...` | `tools.names()` | `test_tools_listed` |
| `# Project instructions (from AGENTS.md)` | `load_project_instructions(ws.root)` | the instruction-file tests |
| `EXTRA-TEXT` | the `extra` argument | `test_extra_is_last` |

## Fixing the date so the output is predictable

```python
NOW = datetime(2026, 10, 30)

def build(tmp_path, **kwargs):
    ws = Workspace(tmp_path)
    return build_system_prompt(ws, make_default_tools(ws), now=NOW, **kwargs)
```

The prompt includes today's date, which would make the output different every day. So `build_system_prompt` takes `now=`: the real CLI leaves it out and gets the current time, and the tests pass a fixed date. It's the same trick as lesson 0's `env=` and `file=`: anything that varies goes in as an argument.

## One test, step by step: `test_sections_in_order`

```python
def test_sections_in_order(tmp_path):
    (tmp_path / "AGENTS.md").write_text("Be brief.")
    prompt = build(tmp_path, extra="EXTRA-TEXT")
    positions = [prompt.index(s) for s in
                 ("# Using tools", "# Environment", "# Project instructions", "EXTRA-TEXT")]
    assert positions == sorted(positions)
    assert prompt.index("# Using tools") > 0  # a role section comes first
```

1. **Arrange.** Write `AGENTS.md` so the instructions section appears.
2. **Act.** Build the prompt; it's exactly the one shown above.
3. **Find each heading.** `prompt.index(s)` returns the character position where `s` first appears, and raises `ValueError` if it's missing, which also fails the test. For the prompt above the four positions increase down the page: `# Using tools` near the top, `EXTRA-TEXT` at the end.
4. **Assert the order.** If the positions are already sorted, the sections are in order. A prompt with `# Environment` above `# Using tools` would give an unsorted list.
5. **Assert a role line exists.** `# Using tools` must not be at position 0, so *something* (the "You are a coding agent..." line) comes first.

Most tests here are this simple: build, then check with `in`, `index` or `startswith`.

## What each group of tests pins down

### The structure

- **`test_instruction_files_constants`**: instruction files are looked for in the order `AGENTS.md`, then `CLAUDE.md`, capped at 10,000 characters.
- **`test_environment_lines`**: the `# Environment` section's four lines. `tmp_path` isn't a git repository, so `Git: not a git repository`.
- **`test_tools_listed`**: the `Tools:` line is built from the registry's actual names, so it can't go out of date when you add a tool.
- **`test_tool_rules_mention_search_and_list_files`** cuts out the `# Using tools` section with `split` and checks it gives advice about the tools. It doesn't check the wording. ("Use search, not `bash grep`" is what stops small models shelling out for everything.)
- **`test_extra_is_last`**: `extra` text is at the very end. Later lessons use `extra` for task-specific instructions, so they come after the general rules they refine.

### Project instructions (`AGENTS.md` / `CLAUDE.md`)

- **`test_agents_md_preferred_over_claude_md`**: with both present, `load_project_instructions` returns `("AGENTS.md", "from agents")`. The heading names the file, and the `CLAUDE.md` text isn't included at all. One file, not both.
- **`test_claude_md_used_alone`**: `CLAUDE.md` is used when it's the only one.
- **`test_no_instructions_section_when_absent`**: no file means `None` and no empty heading.
- **`test_instructions_truncated`**: a 30,000-character file is cut to about 10,000, with lesson 2's truncation marker. A huge file shouldn't eat the context window on every request.

### `git_summary`

These create real git repositories in `tmp_path` with a small `git(...)` helper:

| Test | Setup | Result |
|---|---|---|
| `test_git_summary_not_repo` | nothing | `not a git repository` |
| `test_git_summary_repo` | `git init -b main`, one new file | `branch main, 1 changed file(s)` |
| `test_git_summary_clean_after_commit` | after committing | `branch main, 0 changed file(s)` |
| `test_git_summary_detached_head` | `git checkout --detach` | starts `branch `, says `detached` |
| `test_git_summary_without_git` | `PATH` with no `git` on it | `git not available` |

- **The commit passes `-c user.name=t -c user.email=t@t`**, so the test works on a machine with no git identity set up.
- **`monkeypatch.setenv("PATH", str(tmp_path))`** points `PATH` at an empty folder for that one test, so `git` can't be found. The prompt builder runs on every start, so it mustn't crash on a machine without git.

## The live test

`test_live_follows_project_instruction` (run with `--live`) writes an `AGENTS.md` saying "End every answer with the word BANANA.", then asks the 27B about `notes.txt` with the real system prompt. It passes if the answer ends with `BANANA`. An instruction the model never sees can't be followed, so this is direct evidence that the file reached it. On 2026-11-12:

```
stop_reason=done turns=3
'notes.txt contains a single line:\n\n> remember the milk\n\nBANANA'
```

## If a test fails

- **`ValueError: substring not found`:** a heading is missing or spelled differently. The tests look for `# Using tools`, `# Environment` and `# Project instructions` exactly.
- **The date test fails:** you call `datetime.now()` even when `now` is passed in.
- **A git test fails:** run the same commands by hand in a scratch folder and compare `git status --porcelain` with your count.

## Words used above

| Term | Meaning here |
|---|---|
| **system prompt** | The `role: "system"` message at the start of every request; the harness's standing instructions. |
| **`AGENTS.md` / `CLAUDE.md`** | A file in the project with instructions for coding agents; one is included in the prompt. |
| **`extra`** | Extra text a caller adds at the end, such as a headless task's rules. |
| **`monkeypatch`** | A pytest fixture that changes something (here an environment variable) for one test and restores it afterwards. |
| **detached HEAD** | A git state with no current branch, after checking out a commit directly. |
