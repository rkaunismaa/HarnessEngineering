# How the lesson 9 tests work

Against the reference solution: 13 passed, 1 skipped (the live test). The live test passes too with `--live` (11.8 s against the 27B).

```
uv run pytest lessons/09-plans-and-checking-work
uv run pytest lessons/09-plans-and-checking-work --impl solutions/09-plans-and-checking-work
uv run pytest lessons/09-plans-and-checking-work --live -s -k live
```

## The big picture

Lesson 9 adds two independent features, with one test file each:

- **A plan the model keeps** (`todo_write`, in `test_todo.py`). The model writes its to-do list, and rewrites it as it goes. It's an ordinary tool, so it's tested like lesson 2's tools: call it through `dispatch` and compare the result.
- **A check before "done" is accepted** (`verify`, in `test_verify.py`). When the model says it's finished, the harness runs a check, usually the project's tests. If the check fails, the model is told so and keeps working.

For the check, the tests don't run real pytest. They pass the agent a scripted `verify` function that returns pass or fail in whatever order the test needs:

```
 model: "all done"  ──>  harness calls verify()  ──> (False, "1 test failed: test_x")
                                                        │
          ┌─────────────────────────────────────────────┘
          v
 harness adds a user message: "[Automatic check failed] ... Fix the problem, then finish."
 model fixes something, says "really done"  ──>  verify()  ──> (True, "ok")  ──>  run ends, verified=True
```

## `test_todo.py`: the to-do list

`todo_tool(tmp_path)` returns the workspace, the registry and the `todo_write` tool. The list is stored on the **workspace** (`ws.todos`), so tests can read it straight after a call. `items(...)` builds `{"content": ..., "status": ...}` dicts.

On the reference solution, this call:

```python
tools.dispatch("todo_write", json.dumps({"todos": [
    {"content": "write tests", "status": "completed"},
    {"content": "fix bug",     "status": "in_progress"},
    {"content": "run tests",   "status": "pending"}]}))
```

returned `'[x] write tests\n[>] fix bug\n[ ] run tests'`, and stored the three items in `ws.todos`.

- **`test_todo_replace_and_render`**:
  - The tool exists and is `read_only`. It changes no files, so lesson 5's policy never asks you about it.
  - The rendering is the output above.
  - A second call **replaces** the list rather than appending to it. The model resends the whole list every time, which keeps the tool simple and the model's view complete.
- **`test_todo_two_in_progress_error`**: two `in_progress` items give `Error: only one item can be in_progress at a time.`, and the stored list is unchanged. A rejected call changes nothing.
- **`test_todo_bad_status`** shows two layers of checking. Calling the tool's function *directly* with status `started` returns `Error: invalid status 'started'.`. Through `dispatch`, the schema is checked first, and the error points at the exact item: `Error: todos[1].status must be one of pending, in_progress, completed`.
- **`test_todo_schema_has_enum`**: the schema lists the three statuses as an `enum`, which tells both the model and the validator the allowed values.
- **`test_todo_through_agent_and_prompt`**: the system prompt mentions `todo_write` and testing, and a scripted agent run stores the list.

### The validator grows

`todo_write` takes an array of objects, which lesson 3's `validate_args` didn't handle. **`test_validate_args_arrays_of_objects`** pins the new messages with a made-up schema:

| Input | Error |
|---|---|
| `{"todos": "x"}` | `parameter 'todos' must be array` |
| `{"todos": ["x"]}` | `todos[0] must be object` |
| an item missing `status` | `todos[0]: missing required parameter 'status'` |
| `content` is a number | `todos[0].content must be string` |
| `mode: "c"` with `enum: ["a", "b"]` | `parameter 'mode' must be one of a, b` |
| `{}` | `missing required parameter 'todos'` (lesson 3's format, unchanged) |

Paths like `todos[0].content` tell the model exactly which item to fix.

## `test_verify.py`: checking work before accepting "done"

```python
def scripted_verify(results):
    seen = []
    def verify():
        seen.append(1)
        return results[min(len(seen), len(results)) - 1]
    return verify, seen
```

Each call to `verify()` returns the next `(ok, output)` pair, repeating the last one when the list runs out. `len(seen)` says how many times it ran. The agent gets it as `verify=`. The real CLI passes a function that runs a shell command (`--verify "pytest -q"`).

### One test, step by step: `test_verify_fail_then_fix`

```python
def test_verify_fail_then_fix(tmp_path):
    verify, seen = scripted_verify([(False, "1 test failed: test_x"), (True, "ok")])
    script = [reply(content="all done"),
              reply(tool_calls=[call("write_file", {"path": "f.txt", "content": "fixed"})]),
              reply(content="really done")]
    agent, client = make(tmp_path, script, verify=verify)
    result = agent.run("go")
```

Here is what the reference solution did.

**Request 0** sends the user message `go`. The reply is `all done`, with no tool calls. In lesson 1 that would end the run.

**The check runs.** Instead of returning, the loop calls `verify()`, which gives `(False, "1 test failed: test_x")`. The model's "all done" **stays in the history**, followed by a new user message written by the harness:

```
[Automatic check failed]
1 test failed: test_x
Fix the problem, then finish.
```

**Request 1** carries that message last. The reply is a `write_file` call, which runs: `Created f.txt.`

**Request 2** gets the reply `really done`. The check runs again, gives `(True, "ok")`, and the run ends.

The final history:

```json
{"role": "user", "content": "go"}
{"role": "assistant", "content": "all done"}
{"role": "user", "content": "[Automatic check failed]\n1 test failed: test_x\nFix the problem, then finish."}
{"role": "assistant", "content": null, "tool_calls": [{"id": "call_1", ... "write_file" ...}]}
{"role": "tool", "tool_call_id": "call_1", "content": "Created f.txt."}
{"role": "assistant", "content": "really done"}
```

and `run` returned `TurnResult(final_text='really done', stop_reason='done', turns=3, ..., verified=True)`.

The test checks:

- **The outcome:** `verified is True`, the final text is `really done`, the check ran 2 times, and `turns == 3`. The extra request caused by the check counts as a turn, so `max_turns` still limits it.
- **Exactly one message was injected,** with that exact text.
- **The premature "all done" is still there, directly before it.** Deleting it would hide from the model what it just claimed.
- **The model saw the message:** request 1's last message starts with `[Automatic check failed]`.

### The other verify tests

- **`test_verify_pass_first_time`**: the check passes at once, so `verified is True`, with one check and one request.
- **`test_verify_gives_up`**: the check never passes. With the default `max_verify_attempts=2`, the run ends after two checks and two requests with `verified is False`, but `stop_reason == "done"`. The third scripted reply is never requested. The failure is reported, not hidden, and the agent doesn't loop forever.
- **`test_max_verify_attempts_and_counts_reset_per_run`**: with `max_verify_attempts=3` there are three checks, and a second `run` gets a fresh three (6 in total).
- **`test_verify_skipped_when_tool_calls_and_when_not_done`**: the check only runs when the model *finishes*, meaning a reply with no tool calls. A run stopped by `max_turns` isn't checked, and `verified is None`.
- **`test_no_verify_is_none`**: without `verify`, `verified is None`. A `TurnResult` built the old way, without that field, still works.
- **`test_cli_verify_option`**: `--verify "echo oops; exit 3"` parses, and `_make_verify` turns it into a function returning `(False, output containing "oops")`. `true` gives `ok`.

`verified` has three values: `True` (checked and passed), `False` (checked and failed), and `None` (not checked). Lesson 11's evaluation reports them separately.

## The live test

`test_live_uses_todo` (run with `--live`) gives the 27B a three-step task (create `a.txt`, then `b.txt`, then `c.txt` from both) with the real system prompt. It prints how many times the model called `todo_write`. On 2026-11-12:

```
stop=done turns=5 todo_write calls=0 final todos=[]
```

The model did the task in 5 turns **without making a plan at all**. That's why the test only requires the run to finish: whether a model *chooses* to plan depends on the model and the task. The tool makes planning possible; it doesn't force it. In the lesson 11 capstone run, the same model did call `todo_write`, at the start and again before finishing, on a harder task.

## If a test fails

- **The injected message is wrong:** the exact format is `[Automatic check failed]\n<output>\nFix the problem, then finish.`
- **The run loops past two checks:** count failed checks per `run` and stop at `max_verify_attempts`.
- **`verified` is `False` instead of `None` after `max_turns`:** only set it when a check actually ran.
- **A validator test fails on a path:** build paths as you recurse: `todos[0]`, then `todos[0].status`.

## Words used above

| Term | Meaning here |
|---|---|
| **`todo_write`** | The tool the model uses to write (and rewrite) its plan. |
| **status** | `pending` (`[ ]`), `in_progress` (`[>]`) or `completed` (`[x]`). |
| **`enum`** | A JSON Schema list of the only allowed values. |
| **verify** | The check run when the model says it's finished; returns `(ok, output)`. |
| **injected message** | A user-role message written by the harness, not by you. |
| **`verified`** | `True` / `False` / `None`: passed, failed, or not checked. |
