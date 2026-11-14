# Lesson 3 solution: what changed since lesson 2

This folder is the reference solution for [lesson 3](../../lessons/03-when-the-model-gets-it-wrong/README.md). This page compares its `agent/` package with the one in [`solutions/02-tools/agent/`](../02-tools/agent/), file by file. For each change it says what the code does, why it's written that way, and what it's meant to show you.

To run this solution without touching your own `agent/` folder, run commands from inside this folder (`cd solutions/03-when-the-model-gets-it-wrong`). `python -m agent` imports the `agent` package from the folder you're in. To run the lesson's tests against it: `uv run pytest lessons/03-when-the-model-gets-it-wrong --impl solutions/03-when-the-model-gets-it-wrong`, from the repository root.

## At a glance

| File | Lesson 2 | Lesson 3 | Status |
|---|---|---|---|
| `agent/tools/registry.py` | 54 lines | 96 lines | **changed**: `dispatch` never raises; `validate_args` checks arguments against the schema |
| `agent/loop.py` | 64 lines | 85 lines | **changed**: a request limit, a repeated-call guard, and server errors caught |
| `agent/__main__.py` | 79 lines | 86 lines | **changed**: `ask` reports failures on stderr and exits with 1 |
| everything else | | | unchanged |

**No tool changed.** All the new safety lives in two places every call already passes through: `dispatch` and the loop. That's why it protects every tool, including ones written later.

## What lesson 2 could do, and what it couldn't

Lesson 2's agent worked as long as the model behaved and the server stayed up. But a model doesn't always behave. Over a long session it will eventually send cut-off JSON, call a tool that doesn't exist, leave out a required parameter, repeat the same call over and over, or keep calling tools without ever answering. And servers go down.

In lesson 2, each of those either **crashed the run with a traceback** (bad JSON, a tool that raises, a server error) or **ran forever** (a model that never stops calling tools). A crash loses the whole session, including all the work the model had done so far.

## What this lesson is meant to show you

1. **An error is a tool result.** If the harness raises, the session dies. If it returns `Error: ...` text as that call's result, the model reads it on its next request and usually fixes the problem. So the error text is written *for the model*: it says what was wrong and, where it can, what would be right.
2. **Validate before running.** Checking the arguments against the tool's own schema catches wrong types and missing or made-up parameters with a clear message, before the tool fails in a confusing way.
3. **A loop needs limits.** A cap on requests and a check for identical repeated calls make sure every run ends.
4. **A failed run must end cleanly.** A server error becomes `stop_reason="error"` with a message. The history stays valid, so the same agent can carry on when the server is back.

## File by file

### `agent/tools/registry.py` (changed): `dispatch` never raises

`dispatch` is now a thin wrapper, `truncate(self._dispatch(...))`, so errors are capped too. `_dispatch` runs these checks in order, and the first failure becomes the result:

| Situation | Result returned to the model |
|---|---|
| The tool name isn't registered | `Error: unknown tool 'grep'. Available tools: read_file, list_files, search, bash` |
| `arguments` isn't valid JSON | `Error: arguments were not valid JSON (Expecting ',' delimiter). Send the arguments as a JSON object.` |
| Valid JSON, but not an object (a list, a string, `null`) | `Error: arguments must be a JSON object.` |
| `validate_args` finds problems | `Error: missing required parameter 'pattern'; unknown parameter 'regex'` |
| The tool itself raises anything | `Error: ValueError: <message>` |

**Why each message is written the way it is:**

- **The unknown-tool error lists the tools that do exist.** A model that called `grep` can see `search` in the list and switch to it. Lesson 2's message was just `Error: unknown tool: grep`.
- **The JSON error includes the parser's own message** (`exc.msg`) and says what to send instead.
- **`validate_args` reports every problem at once**, joined with `; `, so the model can fix them all in one go instead of one per request.
- **The catch-all `except Exception` comes last** and wraps only `tool.fn(**args)`. Bugs in a tool, and tools that still raise (such as lesson 2's `list_files` with an absolute glob), now come back as text, without changing the tools. `str(...)` makes sure a tool returning something other than a string can't break the history either.

**`validate_args(schema, args)`** checks the arguments against the tool's `parameters` schema and returns a list of messages, in a fixed order: missing required parameters, then unknown parameters, then wrong types.

```python
_JSON_TYPES = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    ...
}
```

The `not isinstance(v, bool)` matters. In Python, `True` is an `int`, but in JSON a boolean is neither an integer nor a number, so `{"limit": true}` must fail. A parameter with no `type` in its schema isn't checked at all.

**Why validate when the tool would fail anyway:** the tool's failure would say something like `TypeError: read_file() got an unexpected keyword argument 'file'`, which is written for Python programmers. `unknown parameter 'file'` is written for the model, and comes from the same schema the model was given.

### `agent/loop.py` (changed): limits, and a clean exit

Three additions.

**1. A request limit.** `while True:` became `while turns < self.max_turns:`, with `max_turns=50` by default. When the limit is reached, `run` returns `TurnResult("", "max_turns", ...)`. Every tool call made so far already has its result in the history, so the history stays valid. 50 is this course's choice for a small local model, not a copy of anyone else's number.

**2. A repeated-call guard,** in `_run_tool_call`:

```python
key = (fn.name, fn.arguments)
self._repeats = self._repeats + 1 if key == self._last_call else 1
self._last_call = key
if self._repeats >= LOOP_THRESHOLD:
    return LOOP_MESSAGE
return self.tools.dispatch(fn.name, fn.arguments)
```

- **The third identical call in a row isn't run.** Its result is `Error: you have made this exact call 3 times in a row. Try a different approach.` The model gets an error result like any other, so the history stays valid, and it's pushed to change course.
- **"Identical" means the same name and the same arguments *string*.** It's simple, and catches the common case: a model stuck sending the exact same call, expecting a different answer.
- **It counts calls, not replies**, so three identical calls inside one reply count too. Any different call resets the count, and so does each new `run`.
- **It lives in `_run_tool_call`**, one of the two hooks lesson 1 set up for exactly this.

**3. Server errors are caught:**

```python
try:
    completion = self._request()
except openai.APIError as exc:
    return TurnResult("", "error", turns, usage, f"Model request failed: {exc}")
```

- **`openai.APIError` covers connection failures, timeouts and HTTP errors** like a `400`, since they're all subclasses. Other exceptions are bugs in the harness, and should still show a traceback.
- **Nothing is added to the history for a failed request.** The history still ends with the user message, or the last tool result, so it's valid. The same `Agent` can `run` again once the server is back.
- **`turns` counts only requests that succeeded.**
- **`TurnResult.error`**, unused since lesson 1, now holds the message.

### `agent/__main__.py` (changed): failures look like failures

```python
if result.stop_reason == "error":
    print(result.error, file=sys.stderr)
    return 1
if result.stop_reason == "max_turns":
    print(f"Stopped after {result.turns} requests without a final answer.", file=sys.stderr)
    return 1
```

In lesson 2, `ask` printed an empty answer and exited with 0 in these cases, or crashed. Now a failure prints a reason to **stderr** and exits with **1**, so a script, or `&&` in a shell, can tell it failed. `"done"` still exits with 0, even when the answer is "I couldn't find that file": the model answered, and that's a success for the harness.

## What's still missing, and which lesson adds it

| Gap in this version | What goes wrong | Fixed in |
|---|---|---|
| The repeated-call guard only sees *identical* calls | a model alternating between two calls, or changing one character each time, isn't caught; `max_turns` is the only backstop | not in this course |
| No retries for temporary server errors | one dropped connection ends the run (the `openai` library itself retries twice first) | not in this course (an extra in the lesson) |
| No editing tools | — | lesson 4 |
| No sandbox or permission rules | an approved `bash` command can do anything you can | lesson 5 |
| No system prompt | the model doesn't know these rules exist until it breaks one | lesson 6 |

## Seeing it work

From inside this folder:

```
uv run python ../../scripts/make_fixture.py scratch /tmp/scratch
uv run python -m agent ask "Read the file config/settings.yaml and summarise it." --root /tmp/scratch
AGENT_BASE_URL=http://localhost:1/v1 uv run python -m agent ask "anything" --root /tmp/scratch; echo "exit status $?"
```

The first command asks for a file that doesn't exist: watch the model read `Error: file not found: ...` and look elsewhere. The second points at a port nothing listens on, and prints `Model request failed: Connection error.` with exit status 1. The lesson's README walks through both [step by step](../../lessons/03-when-the-model-gets-it-wrong/README.md#what-happens-when-you-run-it-step-by-step), and its "Break it" section shows the guards against the 4B model. [TESTING.md](../../lessons/03-when-the-model-gets-it-wrong/TESTING.md) shows each guard firing against scripted replies.
