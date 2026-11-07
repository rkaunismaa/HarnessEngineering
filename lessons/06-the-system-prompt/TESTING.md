# How the lesson 6 tests work

Lesson 6's tests check `build_system_prompt` and its two helpers as ordinary functions that return strings. There's no model and no loop. The tests look for required lines and headings, and check that the sections come in the right order. The prompt's actual wording is yours to write. Against the reference solution: 15 passed, 1 skipped (the live test).

```
uv run pytest lessons/06-the-system-prompt
uv run pytest lessons/06-the-system-prompt --impl solutions/06-the-system-prompt
```

## Fixing the date so the output is predictable

```python
NOW = datetime(2026, 10, 30)

def build(tmp_path, **kwargs):
    ws = Workspace(tmp_path)
    return build_system_prompt(ws, make_default_tools(ws), now=NOW, **kwargs)
```

The prompt includes today's date, which would make the output different every day. So `build_system_prompt` takes a `now=` argument: the real CLI leaves it out and gets the current time, and the tests pass a fixed date. It's the same trick as lesson 0's `env=` and `file=`. Anything that varies goes in as an argument.

The tests mostly check that a string is `in` the prompt, rather than comparing the whole prompt, so you can write your own instructions without breaking them.

## The prompt's structure

- **`test_instruction_files_constants`**: the instruction files are looked for in the order `AGENTS.md`, then `CLAUDE.md`, capped at 10,000 characters.
- **`test_environment_lines`**: an `# Environment` section with the working directory, `sys.platform`, `Date: 2026-10-30`, and `Git: not a git repository` (`tmp_path` isn't a repository).
- **`test_sections_in_order`** finds the position of each heading with `prompt.index(...)` and checks they are sorted: `# Using tools`, then `# Environment`, then `# Project instructions`, then the `extra` text. It also requires that something comes *before* `# Using tools` (a role section saying what the agent is).
- **`test_tools_listed`**: a `Tools: read_file, list_files, ...` line, built from the registry's actual names, so it can't fall out of date when you add a tool.
- **`test_tool_rules_mention_search_and_list_files`** cuts out just the `# Using tools` section and checks it mentions `search`, `list_files` and `bash`. It doesn't check the wording; it checks that you gave advice about the tools. ("Use search instead of `bash grep`" is what makes small models stop shelling out for everything.)
- **`test_extra_is_last`**: `extra` text comes at the very end. Later lessons use `extra` for task-specific instructions, so they come after the general rules they refine.

## Project instructions (`AGENTS.md` / `CLAUDE.md`)

- **`test_agents_md_preferred_over_claude_md`**: with both files present, `load_project_instructions` returns `("AGENTS.md", "from agents")`. The heading names the file it came from, and the `CLAUDE.md` text isn't included at all. One file, not both.
- **`test_claude_md_used_alone`**: `CLAUDE.md` is used when it's the only one.
- **`test_no_instructions_section_when_absent`**: no file means the function returns `None` and there's no empty heading.
- **`test_instructions_truncated`**: a 30,000-character file is cut to about 10,000 using the same truncation marker as lesson 2. A huge file shouldn't eat the context window on every request.

## `git_summary`

These tests create real git repositories in `tmp_path`, using the small `git(...)` helper:

- **`test_git_summary_not_repo`** returns `not a git repository`.
- **`test_git_summary_repo`**: after `git init -b main` and one untracked file, `branch main, 1 changed file(s)`.
- **`test_git_summary_clean_after_commit`**: after committing, `0 changed file(s)`. The commit passes `-c user.name=t -c user.email=t@t`, so it works even on a machine with no git identity configured.
- **`test_git_summary_detached_head`**: after `git checkout --detach` there's no branch name. The summary must still start with `branch ` and say `detached`, not crash or print an empty name.
- **`test_git_summary_without_git`**: `monkeypatch.setenv("PATH", str(tmp_path))` sets `PATH` to a folder with no `git` in it, for this test only. The result must be `git not available`, not an exception. The prompt builder runs on every start, so it can't fail on a machine without git.

## The live test

`test_live_follows_project_instruction` (run with `--live`) writes an `AGENTS.md` saying "End every answer with the word BANANA.", then asks the 27B in LM Studio about `notes.txt`. It passes if the answer ends with `BANANA` (ignoring a final `.` or `!`). An instruction the model never sees can't be followed, so this proves the file actually reached it. It is a direct check that the project instructions get through.

```
uv run pytest lessons/06-the-system-prompt --live -s -k live
```
