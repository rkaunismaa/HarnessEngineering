# How the lesson 2 tests work

Against the reference solution: 20 passed, 1 skipped (the live test). The live test passes too when run with `--live` (2.7 s against the 27B).

```
uv run pytest lessons/02-tools                               # your agent/
uv run pytest lessons/02-tools --impl solutions/02-tools     # the reference solution
uv run pytest lessons/02-tools --live                        # includes the real-model test
```

## The big picture

Lesson 1's tests needed a fake model, because the loop is what talks to the model. Lesson 2 adds three tools (`list_files`, `search`, `bash`), and a tool doesn't talk to the model at all: it takes arguments and returns a string. So almost every test here leaves the model and the loop out entirely:

```
 test code                              your code                          the real world
 ---------                              ---------                          --------------
 builds files in tmp_path  ---------------------------------------------->  a temporary folder
 run(registry, "search", pattern=...)
   = registry.dispatch("search", '{"pattern": ...}')
                                        dispatch -> search(...) ------------>  reads the files
                                        truncate(result)
 compares the returned string  <-------- "src/a.py:3: def foo():"
```

Everything here is real: real files in a real temporary folder, and real shell commands for `bash`. Only the model is missing, and the test plays its part by choosing the arguments.

## The two helpers

```python
def tools_for(tmp_path, **kwargs):
    return make_default_tools(Workspace(tmp_path), **kwargs)

def run(registry, name, **args):
    import json
    return registry.dispatch(name, json.dumps(args))
```

`run` turns ordinary keyword arguments into a JSON **string** before calling `dispatch`, because that's how arguments arrive from a model (lesson 1: `arguments` is a string). So this:

```python
run(registry, "search", pattern=r"def \w+")
```

calls `registry.dispatch("search", '{"pattern": "def \\\\w+"}')`. That is the same code path a real tool call takes, minus the loop.

## One test, step by step: `test_list_files_skips_git_and_sorts`

```python
def test_list_files_skips_git_and_sorts(tmp_path):
    for rel in ["b.txt", "a.txt", "sub/c.txt", ".git/config", "node_modules/x.js",
                "pkg/__pycache__/m.pyc", ".venv/lib.py"]:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
    assert run(tools_for(tmp_path), "list_files").splitlines() == ["a.txt", "b.txt", "sub/c.txt"]
```

**1. Arrange.** pytest creates an empty folder and passes it in as `tmp_path`. The loop creates seven files: three real ones, and four in folders a project is full of but a model should never be shown (`.git`, `node_modules`, `__pycache__`, `.venv`).

**2. Build the tools.** `tools_for(tmp_path)` builds a `Workspace` on that folder and a registry with all four tools. On the reference solution, `registry.names()` is `['read_file', 'list_files', 'search', 'bash']`.

**3. Act.** `run(..., "list_files")` with no arguments sends the string `'{}'` to `dispatch`. `dispatch` looks up `list_files`, runs `json.loads('{}')` to get `{}`, and calls `list_files()` with its defaults (every file, from the project root). The solution returns exactly:

```
'a.txt\nb.txt\nsub/c.txt'
```

Paths are relative to the project, sorted, one per line, and the four junk folders are gone. `dispatch` then passes the string through `truncate`, which leaves it alone because it's short.

**4. Assert.** `.splitlines()` turns that into `["a.txt", "b.txt", "sub/c.txt"]`, which must equal the expected list exactly. One `node_modules/x.js` in the output fails the test, and so does unsorted output.

Most tests in this file have the same four steps: make files, build tools, call one tool, compare the exact string.

## What each group of tests pins down

The results quoted below are what the reference solution actually returned.

### Truncation: protecting the context window

| Test | Call | Result |
|---|---|---|
| `test_truncate_exact` | `truncate("a" * 30, limit=10)` | `'aaaaa\n[... 20 characters truncated ...]\naaaaa'`; text at or under the limit is unchanged |
| `test_dispatch_truncates` | a throwaway tool returning 50,000 characters | cut to under 20,100 characters, with the marker |
| `test_bash_huge_output_is_truncated_by_dispatch` | `bash("yes \| head -c 200000")` | 20,039 characters; the middle reads `...y\ny\n\n[... 180015 characters truncated ...]\n\n...` |

Truncation lives in `dispatch`, so no individual tool can forget it. It keeps the **head and the tail** because for command output the end (the error, the summary line) usually matters most.

### `list_files` and `search`

| Test | Situation | Exact result |
|---|---|---|
| `test_default_tool_names` | names and flags | includes all four; `list_files` and `search` are `read_only` |
| `test_list_files_glob` | `pattern="**/*.py"`; `path="src"` | `a.py`, `src/c.py`; `src/c.py`, `src/d.md` (still relative to the root) |
| `test_list_files_caps_at_500` | 503 files | 500 names + `[3 more files not shown]` |
| `test_search_matches_format` | `pattern=r"def \w+"` | `'src/a.py:3: def foo():'`: path, 1-based line number, line |
| `test_search_glob_and_path` | `glob="*.py"` | only the `.py` match |
| `test_search_glob_without_slash_matches_any_depth` | `glob="*.py"`, file at `pkg/deep.py` | found; models write `*.py` expecting that |
| `test_search_caps_matches` | 205 hits | 200 lines + `[5 more matches not shown]` |
| `test_search_invalid_regex` | `pattern="(unclosed"` | `'Error: invalid regular expression: missing ), unterminated subpattern at position 0'` |
| `test_search_no_matches` | nothing matches | `'No matches.'`, never `''` |
| `test_search_skips_binary` | a non-UTF-8 file | skipped |
| `test_read_file_binary_returns_error` | `read_file` on it | `'Error: bin.dat is not a UTF-8 text file.'` |

Three habits show up across this table:

- **The model is told when a list is incomplete** ("3 more files not shown") instead of silently losing files.
- **"Nothing" is said in words.** An empty string is ambiguous to a model; `No matches.` isn't.
- **Mistakes come back as strings that start with `Error:`**, not as exceptions. The model reads the error and can try again. Lesson 3 makes this a rule for every tool.

### `bash`

These run real commands in `tmp_path`:

| Test | Command | Exact result |
|---|---|---|
| `test_bash_exit_code` | `echo hi; exit 3` | `'hi\n\n[exit code: 3]'` |
| `test_bash_runs_in_workspace_and_combines_stderr` | `pwd; echo oops >&2` | the project path and `oops`, ending `[exit code: 0]` |
| `test_bash_timeout` | `echo start; sleep 10`, `timeout=1` | `'start\n\n[timed out after 1s]'`, returned after 1.00 s |
| `test_bash_confirmed_runs` | `echo ok`, confirm says yes | `'ok\n\n[exit code: 0]'` |
| `test_bash_declined` | `touch marker.txt`, confirm says no | `'Error: the user declined to run this command.'` |

- **The exit code is always reported**, because "did it work?" is the first thing the model needs to know.
- **stderr is included**, because that's where error messages go.
- **The timeout test times the call itself** (it must return in under 3 s). An implementation that waits the full 10 seconds before reporting a timeout fails, even if its message is right.

**`test_bash_declined` checks three different things:**

```python
def confirm(command):
    asked.append(command)
    return False

registry = tools_for(tmp_path, confirm_bash=confirm)
result = run(registry, "bash", command="touch marker.txt")
assert result == "Error: the user declined to run this command."   # what the model is told
assert asked == ["touch marker.txt"]                                 # you were asked, about exactly this
assert not (tmp_path / "marker.txt").exists()                       # and it really didn't run
```

The last line matters most. A tool that printed the refusal but ran the command anyway would pass the first two checks, and only the file system shows the truth.

`confirm_bash` is passed in as a function for the same reason lesson 0 passes `env=` and `file=`. The real CLI passes one that asks you at the terminal; the tests pass one that answers instantly. Lesson 5 replaces this yes/no question with permission rules.

## The live test

`test_live_finds_function` (run with `--live`) builds a three-file `app/` folder and asks the real model which file defines `compute_invoice_total`. It passes if `billing.py` appears in the answer. `confirm_bash` always answers no, so the model has to use `list_files`, `search` or `read_file` rather than shell commands. It prints nothing; it passed in 2.7 s against `qwen/qwen3.8-27b`.

## If a test fails

- **A list comparison fails:** pytest prints both lists. Look for junk folders that weren't skipped, missing sorting, or absolute paths where relative ones were expected.
- **The timeout test fails on time:** your `bash` probably waits for the process to finish before checking the timeout. Use `subprocess.run(..., timeout=...)` and catch `TimeoutExpired`, keeping the output collected so far.
- **`test_bash_declined` fails on the file check:** you call `confirm_bash` but run the command regardless of its answer.

## Words used above

| Term | Meaning here |
|---|---|
| **registry** | The `ToolRegistry`: the tools by name, plus `dispatch`. |
| **`dispatch(name, raw_arguments)`** | Finds the tool, parses the JSON arguments string, calls the function, truncates the result. |
| **glob** | A filename pattern: `*.py`, or `**/*.py` for any depth. |
| **regex** | A regular expression, the pattern language `search` uses (`def \w+`). |
| **stderr** | The second output stream of a command, where error messages usually go. |
| **exit code** | The number a command ends with; 0 means success. |
| **`tmp_path`** | A new empty folder pytest creates for each test. |
