# Lesson 2: Tools

Start from your lesson 1 code, or copy `solutions/01-the-loop/agent` into `agent/`.

## Why this exists

With only `read_file`, the model can look at a file it already knows the name of. A coding agent also has to find things (`list_files`, `search`) and run things (`bash`). Adding tools is easy; making them work well with a model is the real job, and three things matter:

- **Descriptions are the interface.** The model never sees your code, only the tool's name, its description and its parameter schema. A tool that says "Search." gets used differently from one that says what it returns and when to prefer it over a neighbour.
- **Output must be capped.** A tool result goes into the history and is re-sent on every later request, in a 32K window. One `cat` of a big log can fill the window and end the session. Cap every result, keeping the start and the end (errors are usually at the end).
- **Schemas cost tokens on every request.** Each tool you add is written into the prompt by the chat template. More tools means less room for work, and more choices for a weak model to get wrong.

## How Claude Code does it

- **Documented**: a shell command runs under a timeout; the default is two minutes and the ceiling is ten minutes, both configurable. Checked 2026-10-30: https://code.claude.com/docs/en/tools-reference ("Timeout and output limits"). Your `bash` uses a much smaller 30 s default because a local model's commands are mostly quick and a hang costs you a long wait.
- **Documented**: when a command's output is very large, Claude Code does not put all of it in the conversation. Roughly the first 30,000 characters come back inline by default; past that the model gets the path of a file holding the output plus a short preview and reads or searches the file if it needs more. Same page. Your lesson-2 cap is simpler: it keeps head and tail and drops the middle. Saving the full output to a file is a good extra (below).
- **Documented**: Claude Code can load some tool definitions only on demand. A `ToolSearch` tool "searches for and loads deferred tools when tool search is enabled", and the MCP page says tool search is on by default for MCP servers (https://code.claude.com/docs/en/tools-reference and https://code.claude.com/docs/en/mcp, "Scale with MCP tool search"; the pages checked do not say whether built-in tools are deferred, so this course only claims it for MCP tools). The point is the one in the live exercise below: schemas have a fixed token cost, so tools you rarely need should not pay it on every request.

## What you'll build

Extend your `agent/` package. Tests are in `lessons/02-tools/tests/`.

**`agent/tools/registry.py`**
- `MAX_TOOL_OUTPUT = 20_000`.
- `truncate(text: str, limit: int = MAX_TOOL_OUTPUT) -> str`: unchanged when `len(text) <= limit`. Otherwise the first `limit // 2` characters, then `f"\n[... {n} characters truncated ...]\n"` where `n` is the number of characters removed, then the last `limit // 2` characters.
- `dispatch` truncates every result. (Nothing else about `dispatch` changes in this lesson.)

**`agent/tools/files.py`**
- `read_file` on a file that is not valid UTF-8 returns `"Error: <path> is not a UTF-8 text file."`, not an exception.
- `list_files(pattern="**/*", path=".")`, `read_only=True`: files only (no directories), as paths relative to the project root with `/` separators, sorted. `pattern` is a glob relative to `path`. Skips anything inside `.git`, `.venv`, `__pycache__` or `node_modules`. At most 500 paths; if there are more, a last line `f"[{k} more files not shown]"`.
- `search(pattern, path=".", glob=None)`, `read_only=True`: `pattern` is a Python `re` regular expression. Output is one line per matching line, `f"{relpath}:{lineno}: {line}"` (relpath relative to the project root), for files under `path` (a directory or a single file), with the same directory skips. A `glob` without a `/` (such as `*.py`) matches at any depth. Files that are not valid UTF-8 are skipped. At most 200 matches, then `f"[{k} more matches not shown]"`. An invalid regex returns `"Error: invalid regular expression: <message>"`; no matches returns `"No matches."`.

**`agent/tools/shell.py`**
- `bash(command, timeout=30)`: runs `bash -c command` with the project root as working directory, stdout and stderr combined. The result is `f"{output}\n[exit code: {code}]"`, so `echo hi; exit 3` gives `"hi\n\n[exit code: 3]"`.
- On timeout, kill the command **and everything it started** (run it in its own process group; killing only the shell leaves a child such as `sleep` holding the output pipe open and your call hangs), and return `f"{partial_output}\n[timed out after {timeout}s]"`.
- Do not hold unbounded output in memory: `yes` will print gigabytes in 30 seconds. Keep a bounded amount; `dispatch` does the final truncation.
- Structure it around a private helper that runs a command and returns `(exit code or None on timeout, output)`; lesson 5 builds on that.

**`agent/tools/__init__.py`**
- `make_default_tools(ws, *, confirm_bash: Callable[[str], bool] | None = None)` registers, in this order, `read_file`, `list_files`, `search`, `bash`. If `confirm_bash` is given and returns `False` for a command, `bash` returns `"Error: the user declined to run this command."` and does not run it.

**`agent/__main__.py`**
- `ask` passes a `rich` yes/no prompt (default no) as `confirm_bash`, so every command is shown to you before it runs.

**Warning: `bash` is not sandboxed.** Until lesson 5 it runs with your permissions in your files. A model can and will try `rm`, `git reset`, `pip install`. Run live exercises in a scratch copy of a project, not in this repository or anything you care about, and read each command before you answer `y`. Known gap: a command that starts a background job (`cmd &`) keeps the `bash` call open until that job exits, so a server or a `sleep` started that way blocks the agent; lesson 5 fixes this. Until then, answer `n` to such commands.

## Tests

```
uv run pytest lessons/02-tools                               # against your agent/
uv run pytest lessons/02-tools --impl solutions/02-tools     # against the reference solution
uv run pytest lessons/02-tools --live                        # includes the real-model test
```

[TESTING.md](TESTING.md) walks through what each test checks and why.

Lesson 1's tests still apply (one of them was loosened to check that `read_file` is registered, not that it is the only tool).

### What happens when you run `uv run pytest lessons/02-tools --live`, step by step

This walks through one real run of that command, made on 2026-11-13 against the `agent/` package in the repository root (a learner's own lesson 2 code), with `qwen/qwen3.8-27b` loaded in LM Studio. The request and reply data below were recorded during that run. Your numbers and the model's exact wording will differ a little from run to run.

[TESTING.md](TESTING.md) explains what each test checks. This section follows the *command*: how pytest finds your code, which tests talk to the model and which don't, and exactly what passes between the live test and LM Studio.

#### Where the code lives

| File | What's in it that this walkthrough uses |
|---|---|
| `conftest.py` (repo root) | `pytest_addoption`, `pytest_configure`, `pytest_collection_modifyitems` |
| `pyproject.toml` | the `[tool.pytest.ini_options]` settings |
| `lessons/02-tools/tests/test_tools.py` | the 21 tests, plus the helpers `tools_for` and `run` |
| `agent/config.py` | `load_config`, `Config` |
| `agent/client.py` | `make_client` |
| `agent/workspace.py` | `Workspace` |
| `agent/tools/__init__.py` | `make_default_tools` |
| `agent/tools/registry.py` | `ToolRegistry.schemas`, `ToolRegistry.dispatch`, `truncate` |
| `agent/tools/files.py` | `search` (defined inside `make_search`) |
| `agent/loop.py` | `Agent.run`, `Agent._request`, `Agent._run_tool_call`, `TurnResult` |
| `agent/messages.py` | `message_to_dict` |

#### The big picture first

```
 uv run pytest lessons/02-tools --live
   │
   ├─ conftest.py: "--live was given, so don't skip live tests"; "test the agent/ in the repo root"
   │
   ├─ 20 offline tests ── call your tools directly, in temporary folders ── no model involved
   │
   └─ 1 live test ───── builds a tiny project, runs your Agent ──────────── 2 requests to LM Studio
                            request 1: question + 4 tool schemas  ──>  "call search(...)"
                            your search() runs on your machine
                            request 2: question + call + result  ──>  "`app/billing.py`"
```

Of the 21 tests, only one ever talks to the model. Everything else tests your tools as ordinary Python functions. That's why the whole run took **2.57 s**.

#### Step 1. `uv` starts pytest

`uv run` makes sure the project's virtual environment (`.venv`) matches `pyproject.toml` and `uv.lock`, installing anything missing, and then runs `pytest` from that environment. Everything after `pytest` is passed to pytest as its arguments: the folder `lessons/02-tools` and the option `--live`.

#### Step 2. pytest reads its settings and the root `conftest.py`

pytest finds `pyproject.toml` and reads `[tool.pytest.ini_options]`:

```toml
addopts = "--import-mode=importlib --ignore=capstone/eval/hidden_tests"
pythonpath = ["."]
```

Then it loads `conftest.py` from the repository root. pytest loads any file with that name automatically and calls the functions in it that have special names, called **hooks**. Lesson 0's [TESTING.md](../00-setup/TESTING.md) explains them in detail. Here's what each one does in this run:

- **`pytest_addoption`** teaches pytest two new options, `--impl` and `--live`. Without it, `--live` would be an "unrecognized arguments" error.
- **`pytest_configure`** decides which `agent` package the tests will import. You didn't pass `--impl`, so it uses the default, the repository root. It removes any `agent` modules Python had already imported and puts the root at the front of `sys.path`. From now on, `import agent` finds **your** `agent/` folder, not one of the folders under `solutions/`. To test the reference solution instead, you'd add `--impl solutions/02-tools`.

#### Step 3. pytest collects the tests

pytest looks inside `lessons/02-tools` for files named `test_*.py` and finds one, `tests/test_tools.py`. To see what's in it, pytest has to **import** it, which runs its top lines:

```python
from agent.tools import make_default_tools
from agent.tools.registry import Tool, ToolRegistry, truncate
from agent.workspace import Workspace
```

These are your own modules. If one of these names is missing from your code, the run stops here with a collection error and no test runs at all. In this run they all imported fine, and pytest found every function whose name starts with `test`:

```
collected 21 items
```

#### Step 4. `--live` decides what gets skipped

Next pytest calls the third hook, **`pytest_collection_modifyitems`**. It looks at each collected test's markers. Only `test_live_finds_function` has one, `@pytest.mark.live`:

- **With `--live`** (this run), nothing is skipped.
- **Without it**, the hook adds a skip marker to the live test, and the run ends `20 passed, 1 skipped`. Running `uv run pytest lessons/02-tools -rs` shows why: `SKIPPED [1] lessons/02-tools/tests/test_tools.py:164: needs --live`.

No test in this lesson is marked `sandbox`, so the bubblewrap check in that hook never runs.

#### Step 5. The 20 offline tests run

pytest runs the tests in the order they appear in the file. Each test that takes a `tmp_path` parameter gets a **fresh empty folder**. pytest sees the parameter's name and creates the folder, so tests can create files freely without touching your project or each other. Most of these tests build a registry with `tools_for(tmp_path)`, which calls `make_default_tools(Workspace(tmp_path))`, and then call a tool with `run(registry, "search", pattern=...)`. That goes through `ToolRegistry.dispatch` exactly as the model's calls do: a JSON arguments string, then truncation of the result.

| Group | Tests | Time in this run |
|---|---|---|
| `truncate` and `dispatch` | `test_truncate_exact`, `test_dispatch_truncates`, `test_default_tool_names` | under 5 ms each |
| `list_files` | `test_list_files_skips_git_and_sorts`, `test_list_files_glob`, `test_list_files_caps_at_500` | the 500 test took **0.03 s**: it writes 503 files first |
| `search` | 7 tests, from `test_search_matches_format` to `test_search_skips_binary` | under 5 ms each |
| `read_file` | `test_read_file_binary_returns_error` | under 5 ms |
| `bash` | `test_bash_exit_code`, `test_bash_runs_in_workspace_and_combines_stderr`, `test_bash_timeout`, `test_bash_huge_output_is_truncated_by_dispatch`, `test_bash_declined`, `test_bash_confirmed_runs` | the timeout test took **1.00 s** |

`test_bash_timeout` is the only slow one, and on purpose. It runs `echo start; sleep 10` with `timeout=1`, and passes only if your `bash` comes back within 3 seconds, with `start` in the output and `[timed out after 1s]` at the end. A `bash` that kills only the shell, not the `sleep`, would hang for the full 10 seconds and fail.

None of these tests make a network request. They'd pass with LM Studio switched off.

#### Step 6. The live test builds a small project

`test_live_finds_function` is the last test in the file. It's the only one that uses a real model, and it reaches it the same way `python -m agent ask` does:

```python
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
```

- **The project** is three small files in `tmp_path`. Only `app/billing.py` contains the answer.
- **`load_config()`** (`agent/config.py`) starts from the built-in defaults, then reads `agent.json` if there is one, then `AGENT_*` environment variables. This run had neither, so it used the defaults: `base_url` `http://localhost:1234/v1` and `model` `qwen/qwen3.8-27b`. To run the live test against Ollama instead, set `AGENT_BASE_URL` and `AGENT_MODEL` before the command.
- **`make_client(config)`** (`agent/client.py`) makes the `openai` client pointed at LM Studio.
- **`confirm_bash=lambda c: False`** answers "no" to every `bash` command the model asks for. A test can't stop and wait for you to type `y`, and it shouldn't run commands a model chose. If the model tries `bash`, it gets `Error: the user declined to run this command.` and has to use another tool.
- **No `log` is passed**, so nothing is written to `.agent/logs`. The data below came from a small recorder wrapped around `client.chat.completions.create` for this walkthrough. It isn't part of the test.

Then `agent.run(...)` (`agent/loop.py`) puts the question in `self.messages` and starts the loop you wrote in lesson 1.

#### Step 7. Request 1: the question and four tool schemas

`Agent._request` (`agent/loop.py`) sends:

```json
{
  "model": "qwen/qwen3.8-27b",
  "messages": [
    {"role": "user", "content": "Which file defines the function compute_invoice_total? Answer with the file path."}
  ],
  "tools": [ read_file, list_files, search, bash ]
}
```

The `tools` list comes from `ToolRegistry.schemas()` (`agent/tools/registry.py`), in the order `make_default_tools` registered them. It's four schemas now, not one:

<details><summary>The four tool schemas, exactly as sent</summary>

```json
[
 {"type": "function", "function": {"name": "read_file",
   "description": "Read a text file. Returns numbered lines. Use offset (1-based line) and limit to read part of a large file.",
   "parameters": {"type": "object", "properties": {
     "path": {"type": "string", "description": "File path"},
     "offset": {"type": "integer", "description": "First line to read (1-based)"},
     "limit": {"type": "integer", "description": "Maximum number of lines"}},
     "required": ["path"]}}},
 {"type": "function", "function": {"name": "list_files",
   "description": "List files (not directories) under a directory, one relative path per line, sorted. Use pattern to filter, e.g. '**/*.py'. Skips .git, .venv, __pycache__ and node_modules. Use this to find out what exists; use search to find what files contain.",
   "parameters": {"type": "object", "properties": {
     "pattern": {"type": "string", "description": "Glob pattern relative to path (default '**/*')"},
     "path": {"type": "string", "description": "Directory to list (default: the project root)"}}}}},
 {"type": "function", "function": {"name": "search",
   "description": "Search file contents with a Python regular expression. Returns lines as 'path:lineno: text'. Use glob (e.g. '*.py') to limit which files are searched. Use this to find where something is defined or used; use list_files to find files by name.",
   "parameters": {"type": "object", "properties": {
     "pattern": {"type": "string", "description": "Regular expression to look for"},
     "path": {"type": "string", "description": "File or directory to search (default: the project root)"},
     "glob": {"type": "string", "description": "Only search files matching this glob, e.g. '*.py'"}},
     "required": ["pattern"]}}},
 {"type": "function", "function": {"name": "bash",
   "description": "Run a shell command with bash in the project root. Returns combined stdout and stderr followed by the exit code. Commands that run longer than timeout seconds (default 30) are killed. Use it for running tests and other programs; prefer read_file, list_files and search for looking at files.",
   "parameters": {"type": "object", "properties": {
     "command": {"type": "string", "description": "The command line to run"},
     "timeout": {"type": "integer", "description": "Seconds before the command is killed (default 30)"}},
     "required": ["command"]}}}
]
```

</details>

LM Studio writes all four into the prompt through the chat template (lesson 1, step 5, shows what that text looks like). The prompt came to **844 tokens**. In lesson 1, with only `read_file`, a similar question cost 382. Almost all of the difference is the three new schemas, and it's paid again on every request.

The reply came back after **0.908 s**:

```json
{
  "finish_reason": "tool_calls",
  "message": {
    "role": "assistant",
    "content": "",
    "reasoning_content": "The user is asking which file defines the function `compute_invoice_total`. Let's search for it.",
    "tool_calls": [
      {"id": "tfDqqcuVWocbVPUc9JDexF3PUFAKO0zF", "type": "function",
       "function": {"name": "search", "arguments": "{\"pattern\":\"def compute_invoice_total\"}"}}
    ]
  }
}
```

with `prompt_tokens=844, completion_tokens=51` (20 of them reasoning). The model had four tools and picked `search`, with a regular expression that matches the definition, not the uses. Nothing in the question told it that `search` exists. It learned that from the schema's description: "Use this to find where something is defined or used". It left out `path` and `glob`, so both take their defaults.

#### Step 8. Your `search` runs

`Agent.run` stores the reply with `message_to_dict` (`agent/messages.py`), sees a tool call, and calls `Agent._run_tool_call`, which calls `ToolRegistry.dispatch("search", '{"pattern":"def compute_invoice_total"}')`:

1. **`dispatch`** (`agent/tools/registry.py`) finds the `search` tool, turns the arguments string into `{"pattern": "def compute_invoice_total"}` with `json.loads`, and calls the tool's function with it.
2. **`search`** (defined inside `make_search` in `agent/tools/files.py`) compiles the pattern with `re.compile`. `path` defaults to `"."`, which `ws.resolve` turns into the `tmp_path` folder. There's no `glob`, so it looks at every file under that folder. It reads `app/billing.py`, `app/main.py` and `app/util.py`, and checks each line against the pattern. One line matches.
3. **The result** is one line in the `path:lineno: text` format, with the path relative to the project root:
   ```
   app/billing.py:1: def compute_invoice_total(items):
   ```
4. **`truncate`** (`agent/tools/registry.py`) leaves it unchanged: it's far below `MAX_TOOL_OUTPUT` (20,000 characters).

The loop appends it to the history as a `tool` message carrying the call's id.

#### Step 9. Request 2: the answer

The second request sends the same four schemas and a three-message history:

```json
[
  {"role": "user", "content": "Which file defines the function compute_invoice_total? Answer with the file path."},
  {"role": "assistant", "content": "", "tool_calls": [{"id": "tfDqqcuVWocbVPUc9JDexF3PUFAKO0zF", "type": "function",
     "function": {"name": "search", "arguments": "{\"pattern\":\"def compute_invoice_total\"}"}}]},
  {"role": "tool", "tool_call_id": "tfDqqcuVWocbVPUc9JDexF3PUFAKO0zF",
   "content": "app/billing.py:1: def compute_invoice_total(items):"}
]
```

The prompt was **902 tokens**, 58 more than request 1. The reply came back after **0.544 s**:

```json
{
  "finish_reason": "stop",
  "message": {
    "role": "assistant",
    "content": "`app/billing.py`",
    "reasoning_content": "The function is defined in app/billing.py.",
    "tool_calls": []
  }
}
```

with `prompt_tokens=902, completion_tokens=20` (10 reasoning). There are no tool calls, so `Agent.run` returns:

```python
TurnResult(final_text="`app/billing.py`", stop_reason="done", turns=2,
           usage=Usage(prompt_tokens=1746, completion_tokens=71))
```

The model never read a file. The `search` result already held the answer, so the whole job took two requests, and `bash` was never asked for.

#### Step 10. The test's checks

```python
assert result.stop_reason in {"done", "error"}
assert "billing.py" in result.final_text
```

- **`stop_reason`** is `"done"`. `"error"` is also allowed because from lesson 3 on, the same test runs against an agent that reports a server failure as `stop_reason="error"` instead of raising. In lesson 2 a failure raises, so this check only matters later.
- **`"billing.py" in final_text`** passes. The check looks for `billing.py` anywhere in the answer, not an exact match, because a model can wrap it in backticks (as here), add `app/`, or write a sentence around it.

The test took **1.48 s**: 0.91 s and 0.54 s for the two requests, plus building the client and the project.

#### Step 11. pytest reports

```
lessons/02-tools/tests/test_tools.py .....................               [100%]
============================== 21 passed in 2.57s ==============================
```

Each `.` is one passing test, in file order, and the last one is the live test. `-v` prints each test's name instead of a dot, and `--durations=0` adds the timing list used above.

#### If something goes wrong

- **LM Studio isn't running, or `base_url` is wrong.** The 20 offline tests still pass, and the live test fails inside `Agent._request` with `openai.APIConnectionError: Connection error.`. Running only the live test with `-k live` and `AGENT_BASE_URL=http://localhost:1/v1` really did end `1 failed, 20 deselected`. Start the server with `lms server start`, or check `AGENT_BASE_URL`.
- **A collection error and nothing runs:** one of the three `from agent... import` lines at the top of `test_tools.py` failed, because a name is missing or misspelled in your package. The traceback names it.
- **`test_bash_timeout` takes 10 seconds and fails:** your timeout killed only `bash`, and `sleep` kept the output pipe open. Start the command in its own process group and kill the whole group (see "What you'll build").
- **The live test fails on `"billing.py" in result.final_text`:** pytest prints the model's actual answer. Run `pytest lessons/02-tools --live -k live -s` again, and pass a `RequestLog` to the `Agent` in a copy of the test if you want to see every request. The model may have called a tool with bad arguments, or one of your tools may have returned something wrong. Read the call and the result before blaming the model (see "Break it").
- **You meant to test the reference solution:** add `--impl solutions/02-tools`. Without it, the command always tests your own `agent/`.

#### Words used above

| Term | Meaning here |
|---|---|
| **collection** | pytest finding test files and importing them to list their `test*` functions. Nothing runs yet. |
| **hook** | A function with a special name in `conftest.py` that pytest calls at a fixed point in the run. |
| **marker** | A label on a test, such as `@pytest.mark.live`, that hooks can read. Here it's what `--live` switches on. |
| **`tmp_path`** | A fresh empty folder pytest creates for one test, because the test asks for a parameter with that name. |
| **offline test** | A test that never contacts a model server. 20 of the 21 here. |
| **live test** | A test that sends real requests to the model, so its result can vary from run to run. Skipped unless you pass `--live`. |
| **`--impl`** | The `conftest.py` option that picks which folder's `agent` package is tested. It defaults to the repository root. |

## Try it live

From the repository root, make a scratch project (`app/util.py`, `app/billing.py`, `app/main.py` and two small files):

```
uv run python scripts/make_fixture.py scratch /tmp/scratch
```

**1. What the schemas cost.** Send "Say hi." with only `read_file` registered, then with all four tools, and compare `prompt_tokens` (a throwaway script is fine). Reference numbers:

| model | 1 tool | 4 tools |
|---|---|---|
| `qwen/qwen3.8-27b` (LM Studio) | 375 | 832 |
| `qwen3:4b-instruct` (Ollama) | 215 | 671 |

About 450 tokens for three more tools, paid on every request of every session, before the model has done anything. The `bash` description and the optional-parameter schemas are the heavy part.

**2. Find a function.** `uv run python -m agent ask "Which file defines the function compute_invoice_total?" --root /tmp/scratch`, then `uv run python -m agent log`. Reference run: `qwen/qwen3.8-27b` made one call, `search({"pattern":"def compute_invoice_total"})`, then answered `app/billing.py`. Two requests, no `bash`.

**3. Read the log for tool choice.** Notice which tool the model picked and what arguments it wrote. When it picks wrong, the cause is almost always in the description it was given, which is the next exercise.

## Break it

Replace the descriptions of `search`, `list_files` and `bash` with one word each ("Search.", "List.", "Run.") and delete the descriptions of their parameters. Then run these prompts with the 4B model (`AGENT_BASE_URL=http://localhost:11434/v1 AGENT_MODEL=qwen3:4b-instruct`) and with the 27B, with and without your clear descriptions:

- "Find every line in the project that mentions billing, and tell me how many there are."
- "List the Python files under app/ and say how many there are."

Observed here:

- `qwen3:4b-instruct`, clear descriptions: `search({"pattern":"billing","glob":"*"})`, and a correct answer. Vague descriptions: `list_files({"pattern":".*"})` for the first prompt, answering "I couldn't find any files in the project"; for the second, `list_files({"pattern":"app/*.py","path":"/"})` (a path of `/`, outside the project) and "no Python files". Wrong tool, then wrong arguments, then a confident wrong answer.
- `qwen/qwen3.8-27b`, vague descriptions: it recovered and reached the right answer, but by a longer route: `list_files`, `search`, three `read_file` calls and a `bash` `grep` (declined) where the clear version used `search` and one `read_file`. A strong model hides a vague description by spending requests; a weak one does not.

On the first lesson-2 run the 4B model told us something else: `search` with `glob="*.py"` found nothing, because a glob like `*.py` was applied to the top directory only. The model was right and the tool was wrong; this is why `glob` without a `/` must match at any depth. Tool bugs look like model failures in the log, so read the call and the result before blaming the model.

Also try `bash` with `yes | head -c 200000` and then `sleep 100`, and watch the cap and the timeout work.

## Extras

- When output is truncated, write the full text to a file under `.agent/` and mention its path in the truncation marker, so the model can `read_file` or `search` the rest.
- Give `list_files` and `search` a `.gitignore`-aware skip list instead of the fixed one.
- Add a `max_results` or `context_lines` option to `search`; check what it does to the schema's token cost.
- Make `bash` strip ANSI escape codes from the output.
