# How the lesson 9 tests work

Lesson 9 has two features, and one test file for each. `test_todo.py` covers the plan the model keeps with `todo_write`. `test_verify.py` covers the automatic check that runs when the model says it's finished. For the check, the tests don't run real pytest: they pass the agent a scripted `verify` function that returns pass or fail in whatever order the test needs. Against the reference solution: 13 passed, 1 skipped (the live test).

```
uv run pytest lessons/09-plans-and-checking-work
uv run pytest lessons/09-plans-and-checking-work --impl solutions/09-plans-and-checking-work
```

## `test_todo.py`: the todo list

`todo_tool(tmp_path)` returns the workspace, the registry and the `todo_write` tool. The list is stored on the **workspace** (`ws.todos`), so the tests can read it directly after a call. `items(...)` is shorthand for building `{"content": ..., "status": ...}` dicts.

- **`test_todo_replace_and_render`**:
  - The tool exists and is `read_only`. It changes no files, so lesson 5's policy never asks you about it.
  - A three-item list comes back as `[x] write tests`, `[>] fix bug`, `[ ] run tests`, and is stored.
  - A second call with one item *replaces* the list rather than appending to it. The model resends the whole list every time, which keeps the tool simple and the model's view complete.
- **`test_todo_two_in_progress_error`**: two `in_progress` items give `Error: only one item can be in_progress at a time.`, and the stored list is unchanged (`keep me` is still there). A rejected call changes nothing.
- **`test_todo_bad_status`** shows the two layers of checking. Calling the tool's function *directly* with status `started` returns `Error: invalid status 'started'.`. Going through `dispatch`, the schema is checked first, and the error points at the exact item: `todos[1].status must be one of pending, in_progress, completed`.

### The validator grows

`todo_write` takes an array of objects, which lesson 3's `validate_args` didn't handle. **`test_validate_args_arrays_of_objects`** uses a made-up schema to pin the new messages:

| Input | Error |
|---|---|
| `{"todos": "x"}` | `parameter 'todos' must be array` |
| `{"todos": ["x"]}` | `todos[0] must be object` |
| item missing `status` | `todos[0]: missing required parameter 'status'` |
| `content` is a number | `todos[0].content must be string` |
| `mode: "c"` with `enum: ["a", "b"]` | `parameter 'mode' must be one of a, b` |
| `{}` | `missing required parameter 'todos'` (lesson 3's format, unchanged) |

Paths like `todos[0].content` tell the model exactly which item to fix.

- **`test_todo_schema_has_enum`**: the tool's schema lists the three statuses as an `enum` and requires both fields. That gives the model, and the validator, the allowed values.
- **`test_todo_through_agent_and_prompt`**: the system prompt mentions `todo_write`, and mentions testing. A scripted run through the `Agent` stores the list, and the tool result `[>] step` is in the history.

## `test_verify.py`: checking work before accepting "done"

```python
def scripted_verify(results):
    seen = []
    def verify():
        seen.append(1)
        return results[min(len(seen), len(results)) - 1]
    return verify, seen
```

Each call to `verify()` returns the next `(ok, output)` pair from the list, repeating the last one when it runs out. `len(seen)` is how many times it was called. The agent gets it as `verify=`. The real CLI passes a function that runs a shell command (`--verify "pytest -q"`); the tests pass this one.

- **`test_verify_pass_first_time`**: the model says done, the check passes, so `verified is True`, with one check and one request.
- **`test_verify_fail_then_fix`** is the main test. The script is: "all done", then a `write_file` call, then "really done". The check fails once ("1 test failed: test_x"), then passes. The test checks:
  - the result is `verified`, the final text is "really done", there were 2 checks, and `turns == 3`. The extra request caused by the check counts as a turn, so `max_turns` still limits it.
  - exactly one message was injected: a `user` message reading `[Automatic check failed]\n1 test failed: test_x\nFix the problem, then finish.`
  - the model's premature "all done" stays in the history, right before that message. Deleting it would hide from the model what it just claimed.
  - the next request ended with the injected message.
- **`test_verify_gives_up`**: the check never passes. By default it runs twice (one retry), then the run ends with `verified is False` but `stop_reason == "done"`, after two requests. The third scripted reply is never requested. The failure is reported, not hidden, and the agent doesn't loop forever.
- **`test_max_verify_attempts_and_counts_reset_per_run`**: with `max_verify_attempts=3`, three checks. A second `run` gets a fresh three (6 in total).
- **`test_verify_skipped_when_tool_calls_and_when_not_done`**: the check only runs when the model *finishes*, meaning a reply with no tool calls. A run stopped by `max_turns` isn't checked, and `verified is None`.
- **`test_no_verify_is_none`**: without `verify`, `verified is None`. A `TurnResult` built the old way, without that field, still works, so earlier code doesn't break.
- **`test_cli_verify_option`**: `--verify "echo oops; exit 3"` parses, and `_make_verify` turns it into a function. Running it gives `(False, output containing "oops")`. `true` gives `ok`.

`verified` has three values: `True` (checked and passed), `False` (checked and failed), and `None` (not checked). Lesson 11's evaluation reports them separately.

## The live test

`test_live_uses_todo` (run with `--live`) gives the 27B a three-step task with the real system prompt. It prints how many times the model called `todo_write` and the final list. It only requires the run to finish: whether a model *chooses* to plan is behavior to watch, not something to fail on. Run it with `-s` to see the numbers.
