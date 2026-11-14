# Lesson 9 solution: what changed since lesson 8

This folder is the reference solution for [lesson 9](../../lessons/09-plans-and-checking-work/README.md). This page compares its `agent/` package with the one in [`solutions/08-context/agent/`](../08-context/agent/), file by file. For each change it says what the code does, why it's written that way, and what it's meant to show you.

To run this solution without touching your own `agent/` folder, run commands from inside this folder (`cd solutions/09-plans-and-checking-work`). `python -m agent` imports the `agent` package from the folder you're in. To run the lesson's tests against it: `uv run pytest lessons/09-plans-and-checking-work --impl solutions/09-plans-and-checking-work`, from the repository root.

## At a glance

| File | Lesson 8 | Lesson 9 | Status |
|---|---|---|---|
| `agent/tools/todo.py` | | 51 lines | **new**: the `todo_write` tool, the model's own plan |
| `agent/tools/registry.py` | 96 lines | 119 lines | **changed**: `validate_args` understands `enum` and arrays of objects |
| `agent/tools/__init__.py` | 23 lines | 25 lines | **changed**: registers `todo_write` |
| `agent/workspace.py` | 71 lines | 72 lines | **changed**: holds the plan, `ws.todos` |
| `agent/loop.py` | 243 lines | 265 lines | **changed**: an optional check before "done" is accepted |
| `agent/__main__.py` | 139 lines | 156 lines | **changed**: `--verify COMMAND` |
| `agent/prompt.py` | 75 lines | 77 lines | **changed**: two more tool rules: plan with `todo_write`, run the tests |
| `agent/events.py` | 21 lines | 24 lines | **changed**: an `on_verify` event |
| `agent/cli.py` | 110 lines | 122 lines | **changed**: shows the plan, and each check's result |
| everything else | | | unchanged |

Two independent features, each touching several files: **a plan the model keeps**, and **a check the harness runs**.

## What lesson 8 could do, and what it couldn't

Lesson 8's agent could keep going for a long time without running out of context. Two things still went wrong on tasks with several parts:

1. **The model lost the thread.** After a dozen tool calls, your request is far back in the history, or summarised away. A model that wrote down a plan can look at it; one that didn't has to rebuild it from the transcript.
2. **The model said "done" without checking.** Since lesson 1, the loop stops when a reply has no tool calls, and whatever that reply claims is taken as true. In one real run, the 4B wrote "The fixes are correct and should pass all tests" about a project where half the tests still failed.

## What this lesson is meant to show you

1. **A tool can be just memory.** `todo_write` changes no files. It holds a list, and returns it, so the plan sits in the history where the model will see it.
2. **Don't take the model's word for it.** The harness can run its own check, such as the project's tests, outside the model, when the model says it's finished. If the check fails, the model gets the real output and keeps working.
3. **Both are harness features, not model features.** Neither makes the model smarter. They change what the model is told, and when. In the lesson's measurements, the check took the 4B from 4 of 8 tests passing to 8 of 8 in two runs out of three, at the cost of about 7 more requests.
4. **Report the outcome honestly.** `verified` says whether the check passed, failed, or never ran. A run that gave up after failed checks says so, instead of ending with a confident summary.

## File by file

### `agent/tools/todo.py` (new): the plan

```python
def todo_write(todos: list[dict]) -> str:
    for t in todos:
        if t["status"] not in STATUSES:
            return f"Error: invalid status '{t['status']}'."
    if sum(t["status"] == "in_progress" for t in todos) > 1:
        return "Error: only one item can be in_progress at a time."
    ws.todos = [{"content": t["content"], "status": t["status"]} for t in todos]
    return render(ws.todos)
```

and a call returns the list, marked up:

```
[x] write tests
[>] fix bug
[ ] run tests
```

**Why it's written this way:**

- **The model sends the whole list every time, and it replaces the old one.** There's no "add item" or "tick item 3". One operation is easier for a small model to get right, and the latest result always shows the complete plan.
- **At most one item `in_progress`.** It makes the model say what it's doing *now*. Two are refused, and the old list is kept: a refused call changes nothing.
- **The result is the rendered list**, so the plan appears in the history as a tool result, right where the model reads.
- **It's stored on the workspace** (`ws.todos`), next to the read tracker, so the CLI and the tests can read it.
- **`read_only=True`**, although it "writes". It changes only the harness's own state, not your files, so lesson 5's policy doesn't need to ask you about it.
- **The description says when not to use it:** "Skip it for simple one-step requests." Planning costs requests.
- **The status check inside the function is a second layer.** Called through `dispatch`, the schema's `enum` catches a bad status first, with a more exact message (below). The function's own check covers direct calls.

### `agent/tools/registry.py` (changed): checking nested arguments

`todo_write` takes an array of objects, each with a `status` from a fixed list. Lesson 3's `validate_args` only checked the top-level types. The new `_check_value` goes inside:

```python
if check is not None and not check(value):
    return [f"{label} must be {expected}"]
if "enum" in spec and value not in spec["enum"]:
    return [f"{label} must be one of {', '.join(str(v) for v in spec['enum'])}"]
if expected == "array" and "items" in spec:
    for i, item in enumerate(value):
        ...  # check each item, as todos[0], todos[1], ...
elif expected == "object" and "properties" in spec:
    ...  # required fields, then each field, as todos[0].status
```

- **Errors name the exact item.** `Error: todos[1].status must be one of pending, in_progress, completed` tells the model which of five items to fix.
- **`enum`** lists the only allowed values, which both the model (in the schema) and the validator read.
- **Lesson 3's messages for top-level problems are unchanged** (`missing required parameter 'todos'`), so the earlier tests still pass.
- **It handles only what the tools use**: types, `enum`, `items` and nested `properties`. It isn't a full JSON Schema validator.

### `agent/loop.py` (changed): a check before "done"

`Agent` takes two new arguments: `verify`, a function returning `(passed, output)`, and `max_verify_attempts` (default 2). When a reply has no tool calls:

```python
if self.verify is None:
    return TurnResult(message["content"] or "", "done", turns, usage)
verified, output = self.verify()
self.events.on_verify(verified, output)
if verified:
    break
failed_checks += 1
if failed_checks >= self.max_verify_attempts:
    break
self.messages.append({"role": "user",
                      "content": CHECK_FAILED.format(output=truncate(output))})
continue
```

with `CHECK_FAILED` being:

```
[Automatic check failed]
<the check's output>
Fix the problem, then finish.
```

**Why it's written this way:**

- **The check runs only when the model *finishes***: a reply with no tool calls. Not after every edit. That's the moment the model claims the work is done.
- **The model's "done" stays in the history**, and the failure comes after it as a new user message. Deleting the claim would hide from the model what it just said.
- **The real output goes back, capped with `truncate`**, so the model sees the actual failing test names and errors, not a summary.
- **It gives up after `max_verify_attempts` failed checks** (2 by default), and the run ends with `stop_reason="done"` and `verified=False`. A model that can't fix it shouldn't be kept looping, and the failure is reported, not hidden.
- **Each continuation is a normal request**, so it counts towards `max_turns`.
- **`TurnResult.verified` has three values:** `True` (checked and passed), `False` (checked and failed), and `None` (no check ran, or the run stopped at `max_turns`, before the model finished). Lesson 11's evaluation reports them separately.
- **No `verify` means lesson 8's behaviour, exactly.**

### `agent/__main__.py` (changed): `--verify`

```python
def _make_verify(ws: Workspace, command: str):
    def verify() -> tuple[bool, str]:
        code, output = run_shell(ws, command, timeout=300)
        if code is None:
            return False, f"{output}\n[timed out after 300s]"
        return code == 0, f"{output}\n[exit code: {code}]"
    return verify
```

`--verify "python -m pytest -q"` (on `ask` and `chat`) builds a check from a shell command. It **passes when the command exits with 0**, and its output is what the model sees when it fails.

- **It uses `run_shell`, from lesson 5**, so the check runs in the same sandbox as the model's own commands.
- **It doesn't go through the permission policy.** You typed the command yourself, on the command line.
- **The timeout is 300 seconds,** not `bash`'s 30, because a test suite can be slow.
- **The loop only sees `verify()`.** A test can pass a scripted function, and lesson 11 builds a different one.

### `agent/prompt.py` (changed): two more rules

```
- For work with several steps, keep a list with `todo_write`: send the whole list each time, with one item `in_progress` and finished items `completed`.
- Before you finish a code change, run the tests.
```

The first tells the model the tool exists and how to use it. The second asks for a check the model makes itself. It isn't enough on its own (that's why `--verify` exists), but it costs one line.

### `agent/events.py`, `agent/cli.py` (changed): seeing the plan and the check

- **`on_verify(passed, output)`** is a new event. The terminal prints `Check passed.` in green, or `Check failed:` and a short preview of the output.
- **A `todo_write` result is printed in full, in magenta**, not as the usual 3-line preview. The plan is short, and seeing it is the point.

### `agent/workspace.py` (changed): `ws.todos`

One line: `self.todos: list[dict] = []`. The workspace already held the per-session state the tools share (the tracker, the sandbox settings), so the plan goes there too.

## What's still missing, and which lesson adds it

| Gap in this version | What goes wrong | Fixed in |
|---|---|---|
| A model may simply not plan | in the lesson's live test, the 27B finished a three-step task without calling `todo_write` at all | by design: the tool makes planning possible, not compulsory |
| The check is only as good as the command | a check that tests the wrong thing passes wrong work | your job; lesson 11 adds hidden tests the model can't see |
| Searching a big project fills the context | each search and read stays in the history | lesson 10 |
| No way to run tasks unattended and measure the results | — | lesson 11 |

## Seeing it work

The lesson's README describes a test project with six buggy functions. With any project that has failing tests, from inside this folder:

```
uv run python -m agent ask "The tests in this project fail. Fix the code so they all pass." \
    --root <your project> --verify "python -m pytest -q" --allow 'bash(python -m pytest*)'
```

Watch for `[Automatic check failed]` in the log, and what the model did next. Run `chat` instead of `ask` to see the plan in magenta whenever the model updates it. The lesson's README has measured runs of the 4B with and without `--verify`. [TESTING.md](../../lessons/09-plans-and-checking-work/TESTING.md) walks through a scripted fail-then-fix run message by message.
