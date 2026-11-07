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
