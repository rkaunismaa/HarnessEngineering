# Lesson 2 solution: what changed since lesson 1

This folder is the reference solution for [lesson 2](../../lessons/02-tools/README.md). This page compares its `agent/` package with the one in [`solutions/01-the-loop/agent/`](../01-the-loop/agent/), file by file. For each change it says what the code does, why it's written that way, and what it's meant to show you.

To run this solution without touching your own `agent/` folder, run commands from inside this folder (`cd solutions/02-tools`). `python -m agent` imports the `agent` package from the folder you're in. To run the lesson's tests against it: `uv run pytest lessons/02-tools --impl solutions/02-tools`, from the repository root.

## At a glance

| File | Lesson 1 | Lesson 2 | Status |
|---|---|---|---|
| `agent/tools/files.py` | 33 lines | 142 lines | **changed**: `list_files` and `search` added; `read_file` rejects non-UTF-8 files |
| `agent/tools/shell.py` | | 76 lines | **new**: the `bash` tool |
| `agent/tools/registry.py` | 42 lines | 54 lines | **changed**: `truncate`, and `dispatch` applies it to every result |
| `agent/tools/__init__.py` | 14 lines | 21 lines | **changed**: registers four tools, takes `confirm_bash` |
| `agent/__main__.py` | 72 lines | 79 lines | **changed**: asks you before every `bash` command |
| `agent/loop.py`, `messages.py`, `log.py`, `workspace.py`, `config.py`, `client.py`, `__init__.py` | | | unchanged |

**The loop didn't change at all.** Lesson 1's `Agent` gets three new tools without a single edit, because it only ever talks to the `ToolRegistry`. That's the payoff of the registry design from lesson 1.

## What lesson 1 could do, and what it couldn't

Lesson 1's agent could read a file, but only one it already knew the name of. It couldn't find out which files exist, look for where a function is defined, or run anything. A coding agent needs to do all three.

And its one tool had no limits. A `read_file` of a 5 MB log would put all 5 MB into the history, to be sent again with every later request, in a 32K-token window. One call like that ends the session.

## What this lesson is meant to show you

1. **Adding a tool is easy; making it work well with a model is the real job.** Each tool here is a short function. Most of the thought goes into what it returns, how much, and how it's described.
2. **The description is the interface.** The model never sees your code, only the name, the description and the parameter schema. The descriptions here say what each tool returns and when to use it *instead of* its neighbours ("use search to find what files contain").
3. **Every result must be capped.** A result is re-sent on every later request. `truncate` keeps the start and the end of anything over 20,000 characters, since errors are usually at the end.
4. **Schemas cost tokens on every request.** With four tools, the prompt for a trivial question went from 375 tokens to 832 on the 27B. That cost is paid before the model does anything, every time.
5. **Running commands is dangerous.** `bash` runs with your permissions, in your files. Until lesson 5's sandbox, the only safety is that you're asked first.

## File by file

### `agent/tools/files.py` (changed): finding things

Two new tools, plus a fix to `read_file`.

**`list_files(pattern="**/*", path=".")`** answers "what exists?":

```python
def list_files(pattern: str = "**/*", path: str = ".") -> str:
    base = ws.resolve(path)
    if not base.is_dir():
        return f"Error: directory not found: {path}"
    files = [_rel(ws, p) for p in _files_under(base, pattern)]
    out = files[:MAX_FILES]
    if len(files) > MAX_FILES:
        out.append(f"[{len(files) - MAX_FILES} more files not shown]")
    return "\n".join(out) if out else "No files found."
```

- **Files only, as paths relative to the project root, sorted.** The model can pass any of those paths straight to `read_file`. Sorting makes the output the same every time, which helps both the tests and the model.
- **`SKIP_DIRS`** (`.git`, `.venv`, `__pycache__`, `node_modules`) are left out. They can hold thousands of files the model never needs, and listing them would waste the whole cap.
- **At most `MAX_FILES` (500), then a note saying how many were left out.** The note matters: without it, the model would think it had seen everything.
- **An empty result says `No files found.`** An empty string looks like a broken tool to a model.

**`search(pattern, path=".", glob=None)`** answers "where is this?":

- **`pattern` is a Python regular expression**, so the model can search for `def compute_\w+` as well as plain text.
- **Each match is `path:lineno: line`.** The model gets the file *and* the line number, so it can go straight to `read_file` with an `offset`.
- **A `glob` with no `/` (like `*.py`) matches at any depth.** This was a real bug found on the first live run: `*.py` only matched the top folder, so the 4B's perfectly sensible `glob="*.py"` found nothing. A model can't tell a tool bug from an empty result, so the tool has to behave the way the model expects.
- **Files that aren't UTF-8 are skipped** instead of stopping the search.
- **Capped at `MAX_MATCHES` (200), with a note.** **A bad regex returns `Error: invalid regular expression: ...`**, and no matches returns `No matches.`.

**`read_file` now reads with `encoding="utf-8"`** and returns `Error: <path> is not a UTF-8 text file.` for binary files, instead of raising. In lesson 1, reading a `.png` would have crashed the run.

**`_rel` and `_files_under`** are shared helpers: one turns a path into the root-relative form, the other walks a folder with `SKIP_DIRS` applied and sorts the result.

### `agent/tools/shell.py` (new): running commands

```python
def bash(command: str, timeout: int = 30) -> str:
    if confirm is not None and not confirm(command):
        return "Error: the user declined to run this command."
    code, output = _run(ws, command, timeout)
    if code is None:
        return f"{output}\n[timed out after {timeout}s]"
    return f"{output}\n[exit code: {code}]"
```

**What it does:** runs `bash -c <command>` in the project root, with stdout and stderr combined, and returns the output followed by the exit code.

**Why it's written this way:**

- **The exit code is always in the result** (`[exit code: 3]`). Many commands fail silently, printing nothing, and only the exit code says what happened. Tests, `grep` and compilers all report through it.
- **stdout and stderr are combined**, in the order they were printed, because that's what a person sees in a terminal, and error messages make sense next to the output before them.
- **A timeout (30 s by default) kills the command *and everything it started*.** `start_new_session=True` puts the command in its own process group, and `os.killpg` kills the whole group. Killing only `bash` would leave a child like `sleep` holding the output pipe open, and the call would hang anyway. `test_bash_timeout` checks exactly this.
- **Output is read in a background thread and capped at `MAX_CAPTURE` (1 MB).** `yes` can print gigabytes in 30 seconds. The reader keeps a bounded amount and throws the rest away, but keeps reading so the command doesn't block on a full pipe. `dispatch` then cuts what the model sees down to 20,000 characters.
- **`stdin=subprocess.DEVNULL`**, so a command that waits for input gets end-of-file instead of hanging, waiting for a keyboard nobody is at.
- **`confirm` is called first.** If it says no, the command never runs, and the model is told so in plain words. The tool itself doesn't know how to ask you; `__main__.py` gives it a function that does. The tests give it `lambda c: False` or `lambda c: True`.
- **`_run` is a separate helper** returning `(exit code or None, output)`. Lesson 5 builds on it, wrapping the command in a sandbox.

**Deliberately naive for now:** there's no sandbox, so an approved command can do anything you can. And a background job (`cmd &`) keeps the call open until the job ends, because it still holds the output pipe. Lesson 5 fixes both.

### `agent/tools/registry.py` (changed): the output cap

```python
MAX_TOOL_OUTPUT = 20_000

def truncate(text: str, limit: int = MAX_TOOL_OUTPUT) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    removed = len(text) - 2 * half
    return f"{text[:half]}\n[... {removed} characters truncated ...]\n{text[len(text) - half:]}"
```

`dispatch` now returns `truncate(tool.fn(**args))`, so **every** tool's result is capped in one place. A tool written later can't forget to.

- **Head and tail, not just the head.** A failing test run prints its summary and the error at the end. Keeping only the start would throw away the part that matters most.
- **The marker says how much was removed.** The model knows the result is incomplete and roughly by how much, so it can ask for a smaller piece (`offset`/`limit`, a narrower `search`).
- **20,000 characters** is roughly 5,000 tokens: big enough for a useful file or test run, small enough that a few of them fit in a 32K window.

### `agent/tools/__init__.py` (changed): four tools

`make_default_tools` registers `read_file`, `list_files`, `search` and `bash`, in that order, which is also the order the schemas appear in each request. Lesson 1's catch-all `**kwargs` is replaced by a real keyword argument, `confirm_bash`, which is passed on to `make_bash`. The read-only tools come first; `bash` is the only one that can change anything.

### `agent/__main__.py` (changed): asking you first

```python
def _confirm_bash(command: str) -> bool:
    return Confirm.ask(f"Run this command?\n  {escape(command)}\n", console=Console(), default=False)
```

`_ask` passes this as `confirm_bash`, so every command the model wants to run is shown to you, and runs only if you answer `y`. **The default is no**: pressing Enter declines. `escape` stops `rich` from treating text in the command, such as `[red]`, as formatting, so you see exactly what will run.

## What's still missing, and which lesson adds it

| Gap in this version | What goes wrong | Fixed in |
|---|---|---|
| `dispatch` raises on bad JSON or wrong arguments; tools can still raise (`list_files` with an absolute glob) | one bad call ends the session with a traceback | lesson 3 |
| No limit on requests; no check for repeated calls | a confused model can loop forever | lesson 3 |
| No way to edit a file except through `bash` | edits are blind and unchecked | lesson 4 |
| `bash` isn't sandboxed; background jobs hang the call | an approved command can damage anything you own | lesson 5 |
| Asking is all-or-nothing for `bash` only | no rules like "always allow `pytest`", no protection for other tools | lesson 5 |

## Seeing it work

From inside this folder:

```
uv run python ../../scripts/make_fixture.py scratch /tmp/scratch
uv run python -m agent ask "Which file defines the function compute_invoice_total?" --root /tmp/scratch
uv run python -m agent log
```

On the 27B, the reference run made one `search({"pattern":"def compute_invoice_total"})` call and answered `app/billing.py`, in two requests. The lesson's README has [a step-by-step walkthrough](../../lessons/02-tools/README.md#what-happens-when-you-run-uv-run-pytest-lessons02-tools---live-step-by-step) of the lesson's tests, including that same question asked by the live test. Its "Break it" section shows what happens to a small model when the descriptions are vague. [TESTING.md](../../lessons/02-tools/TESTING.md) explains each test.
