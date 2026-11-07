# How the lesson 2 tests work

Lesson 2's tests mostly don't involve a model at all, scripted or real. They test the tools directly: a test builds a small file tree in `tmp_path`, calls a tool the way the loop would, and compares the exact text it returns. Against the reference solution: 20 passed, 1 skipped (the live test).

```
uv run pytest lessons/02-tools                               # your agent/
uv run pytest lessons/02-tools --impl solutions/02-tools     # the reference solution
```

## The two helpers

```python
def tools_for(tmp_path, **kwargs):
    return make_default_tools(Workspace(tmp_path), **kwargs)

def run(registry, name, **args):
    return registry.dispatch(name, json.dumps(args))
```

`run` turns keyword arguments into a JSON *string* before calling `dispatch`, because that is how the arguments arrive from the model. So `run(registry, "search", pattern="needle", glob="*.py")` exercises the same path as a real tool call, minus the loop.

Most checks compare the whole output to an exact string. The output format is part of the contract: it's what the model reads, and a stable, compact format (`path:line: text`, `[exit code: 3]`) is easier for a model to use than a varying one.

## Truncation: protecting the context window

- **`test_truncate_exact`** pins the exact shape: keep the first and last `limit // 2` characters with a marker in between, `aaaaa\n[... 20 characters truncated ...]\naaaaa`. Text at or under the limit is returned unchanged. That covers the edge case where the length equals the limit.
- **`test_dispatch_truncates`** registers a throwaway tool that returns 50,000 characters and checks that `dispatch` cuts it. Truncation lives in `dispatch`, not in each tool, so no tool can forget it.
- **`test_bash_huge_output_is_truncated_by_dispatch`** checks the same thing end to end with `yes | head -c 200000`.

Why keep the head *and* the tail? For command output, the end (the error, the summary line) is usually what matters most.

## `list_files` and `search`

- **`test_default_tool_names`**: the registry has at least `read_file`, `list_files`, `search` and `bash`. The two new read-only tools are flagged `read_only`; `bash` is not.
- **`test_list_files_skips_git_and_sorts`** creates `.git/`, `node_modules/`, `__pycache__/` and `.venv/` alongside real files. Only the real files come back, sorted, as relative paths. Without the filter, one `node_modules` would fill the context.
- **`test_list_files_glob`**: `pattern="**/*.py"` filters, and `path="src"` lists a subfolder. The paths are still relative to the workspace root, not to `src`.
- **`test_list_files_caps_at_500`**: 503 files give 500 lines plus `[3 more files not shown]`. The model is told the list is incomplete instead of silently missing files.
- **`test_search_matches_format`**: a regex search returns `src/a.py:3: def foo():`, with the path, a 1-based line number and the line text.
- **`test_search_glob_and_path`** and **`test_search_glob_without_slash_matches_any_depth`**: `glob="*.py"` limits the search to Python files, and a glob with no `/` matches at any depth (`pkg/deep.py`). Models write `*.py` expecting that.
- **`test_search_caps_matches`**: 205 hits give 200 lines plus `[5 more matches not shown]`.
- **`test_search_invalid_regex`**: `(unclosed` returns `Error: invalid regular expression: ...` instead of raising. Small models write broken regexes. An error string lets the model fix its call; an exception would end the run (lesson 3 adds a safety net for that).
- **`test_search_no_matches`**: the result is `No matches.`, never an empty string. An empty result is ambiguous to a model.
- **`test_search_skips_binary`** and **`test_read_file_binary_returns_error`**: a file that isn't valid UTF-8 is skipped by `search`, and `read_file` returns `Error: bin.dat is not a UTF-8 text file.`.

## `bash`

These tests run real shell commands inside `tmp_path`:

- **`test_bash_exit_code`**: `echo hi; exit 3` returns `hi\n\n[exit code: 3]`. The exit code is always reported, because "did it work?" is the first thing the model needs to know.
- **`test_bash_runs_in_workspace_and_combines_stderr`**: `pwd` shows the workspace folder, and stderr (`oops`) is included in the result. Error messages go to stderr, so dropping it would hide exactly what the model needs.
- **`test_bash_timeout`**: `echo start; sleep 10` with `timeout=1` must return in under 3 seconds. The result keeps the output so far (`start`) and adds `[timed out after 1s]`. The test times the call itself, so an implementation that waits the full 10 seconds fails.
- **`test_bash_declined`**: `confirm_bash` is a function the tool calls before running anything. Here it records the command and returns `False`. The test checks three things: the result is `Error: the user declined to run this command.`, the function was asked about exactly `touch marker.txt`, and `marker.txt` was *not* created. Checking the filesystem proves the command didn't run, not just that the message looked right.
- **`test_bash_confirmed_runs`**: with `confirm_bash=lambda c: True`, the command runs.

Passing `confirm_bash` in as a function is the same pattern as lesson 0's `env=` and `file=`. The real CLI passes a function that asks you at the terminal; the tests pass one that answers instantly. Lesson 5 replaces this yes/no question with permission rules.

## The live test

`test_live_finds_function` (run with `--live`) builds a three-file `app/` folder and asks the real model which file defines `compute_invoice_total`. It passes if `billing.py` appears in the answer. `confirm_bash` always answers no, so the model has to use `list_files`, `search` or `read_file` to find it rather than shell commands.
