# Lesson 9: Plans and checking work

Start from your lesson 8 code, or copy `solutions/08-context/agent` into `agent/`.

## Why this exists

Two things go wrong when a small model works on a task with several parts.

1. **It loses the thread.** After a dozen tool calls the original request is far back in the history. A model that wrote down its plan can look at the plan; a model that did not has to rebuild it from the transcript. The fix is cheap: give it a tool whose only job is to hold a list.
2. **It says "done" without having checked.** The loop in lesson 1 stops when a reply has no tool calls. Whatever the model claims in that reply is taken as true. On a real run (below) the 4B wrote "The fixes are correct and should pass all tests" about a project where half the tests still failed. Telling it in the prompt to run the tests is not enough, so the harness runs a check of its own, outside the model, and sends the result back if it fails.

Both are harness features, not model features. Neither makes the model smarter; they change what the model is told and when.

A real run of the 27B on LM Studio (create `a.txt`, create `b.txt`, then create `c.txt` from both) used `todo_write` 4 times in 7 requests: once to write the plan and then to move the `in_progress` marker, ending with all three items `completed`.

### The 4B with and without a check

The test project is a `utils.py` with six small functions, each with a bug (`mean` divides by `len + 1`, `median` ignores even lengths, `clamp` has its bounds swapped, `slugify` does not lowercase or use `-`, `parse_kv` returns a list instead of a dict, `chunk` drops the last piece), and a `test_utils.py` with 8 tests. The prompt was `The tests in this project fail. Fix the code so they all pass.` Model: Ollama `qwen3:4b-instruct`, sandbox on, three runs each, results measured by running `pytest` afterwards:

| | tests passing at the end | requests per run |
|---|---|---|
| without `--verify` | 4 of 8, in all three runs | 10, 11, 13 |
| with `--verify "python -m pytest -q"` | 8 of 8 (two runs), 7 of 8 (one run) | 18, 19, 19 |

- Without the check, each run ended with a confident summary. Two of the three said they could not run the tests. In all three the only command the model tried was `python test_utils.py`, which runs nothing, prints nothing and exits 0; those runs allowed only `bash(python -m pytest*)` without asking, and the model never tried that command. (The checked runs used the same rule; the harness ran pytest itself.)
- With the check, every run was sent back once with the real pytest output (the first failure message listed `test_clamp`, `test_slugify` and others by name) and fixed most or all of it. In the run that did not finish, the second check also failed and the harness gave up after `max_verify_attempts = 2` checks; it reports `verified=False` and the 7-of-8 state, which is better than saying nothing.
- The cost is requests: about 7 more per run here. Each check is one extra command plus the continuation.
- A first attempt with a two-bug project showed no difference: the 4B fixed both bugs without help in all six runs. The check only matters when the model would otherwise stop early. Three runs per side is not a benchmark; it is enough to see the shape of the effect.

## How Claude Code does it

- **Documented** ([Tools reference](https://code.claude.com/docs/en/tools-reference), checked): Claude Code has task-tracking tools. `TaskCreate` creates "a new task in the task list", `TaskGet` retrieves details, `TaskList` lists all tasks "with their current status", and `TaskUpdate` "updates task status, dependencies, details, or deletes tasks". `TodoWrite` ("manages the session task checklist") is the older tool and is "disabled by default in favor of" the four Task tools; `CLAUDE_CODE_ENABLE_TASKS=0` re-enables it. Which model gets which tools by default depends on the model; see the "Task tool availability" section of that page. Your `todo_write` is the `TodoWrite` shape: one tool that replaces the whole list. The newer tools instead let the model create and update tasks one at a time and track dependencies, which you do not build here.
- **Documented** ([Hooks reference](https://code.claude.com/docs/en/hooks), checked): hooks are commands Claude Code runs on events. The `Stop` hook fires "when Claude finishes responding". A hook that exits with code 2, or prints JSON with `"decision": "block"` and a `reason`, prevents Claude from stopping, and the reason is sent back so the conversation continues; exiting 0 without a decision lets it stop. A Stop hook that runs your tests is the same idea as `verify`. Hooks are outside this course, so that is all the lesson says about them.
- **Design note**: `verify` is a Python callback on `Agent`, not a configurable hook system. It runs once per reply without tool calls and only decides between "stop" and "send this text back". The attempt limit exists because a check that can never pass (a flaky test, a broken environment) would otherwise loop until `max_turns`.

## What you'll build

New: `agent/tools/todo.py`. Changed: `agent/workspace.py`, `agent/tools/registry.py`, `agent/tools/__init__.py`, `agent/loop.py`, `agent/events.py`, `agent/prompt.py`, `agent/cli.py`, `agent/__main__.py`. Tests: `lessons/09-plans-and-checking-work/tests/`.

**`Workspace.todos: list[dict]`**: starts as `[]`. Each item is `{"content": str, "status": str}`.

**`todo_write(todos: list[dict]) -> str`** (a `Tool` with `read_only=True`, since it changes only harness state, and registered by `make_default_tools`):
- `status` is `"pending"`, `"in_progress"` or `"completed"`. The schema uses `items` (an object with required `content` and `status`) and an `enum` for `status`.
- A status outside the three: `f"Error: invalid status '{s}'."`. More than one `in_progress`: `"Error: only one item can be in_progress at a time."`. After either error `ws.todos` is unchanged. (When the call comes through the registry, the enum check in `validate_args` reports a bad status first, with the message below; the tool's own message covers direct calls.)
- Success replaces `ws.todos` with the new list and returns one line per item: `[x] content` for completed, `[>] content` for in_progress, `[ ] content` for pending.

**`validate_args` additions** (lesson 3's messages stay as they were). It now understands `enum`, `items` for arrays, and `properties`/`required` for objects inside arrays. It is not a general JSON-schema validator. New messages, where the path names the value (`todos[1].status`):
- Top-level enum: `parameter 'mode' must be one of a, b`.
- Array item of the wrong type: `todos[0] must be object`.
- Field of the wrong type: `todos[0].content must be string`.
- Field outside the enum: `todos[1].status must be one of pending, in_progress, completed`.
- Missing field: `todos[0]: missing required parameter 'status'`.
- A wrong top-level type keeps the old format: `parameter 'todos' must be array`.

**`Agent(..., verify: Callable[[], tuple[bool, str]] | None = None, max_verify_attempts: int = 2)`**:
- With `verify=None` nothing changes and `TurnResult.verified` is `None`.
- When a reply has no tool calls (after it is appended to the history) and `verify` is set: call it and tell `events.on_verify(passed, output)`. If it passed, finish with `verified=True`. If it failed and fewer than `max_verify_attempts` checks have failed in this `run`, append `{"role": "user", "content": f"[Automatic check failed]\n{output}\nFix the problem, then finish."}` (the output cut with `truncate`) and ask the model again. Otherwise finish with `verified=False`. Either way `stop_reason` is `"done"`.
- Failures are counted per `run()`, so each user message gets a fresh budget. Requests made after a failed check count toward `turns` and `max_turns`. If `max_turns` runs out after a failed check, the result is `"max_turns"` with `verified=False`.
- `TurnResult` gains `verified: bool | None = None`. It has a default so older constructions still work.

**`AgentEvents.on_verify(passed: bool, output: str)`**: does nothing by default. The chat UI prints `Check passed.` or `Check failed:` and a preview of the output. It also prints the full result of `todo_write` (instead of a three-line preview), so the list is visible as it changes.

**`build_system_prompt`** gains two rules in the tool section: for work with several steps, keep a list with `todo_write` (send the whole list each time; one item `in_progress`); and before finishing a code change, run the tests.

**CLI**: `ask` and `chat` take `--verify COMMAND`. The check runs `COMMAND` with `run_shell(ws, COMMAND, timeout=300)` (inside the sandbox when it is enabled); it passes when the exit code is 0, and the output sent back is the command's output followed by `[exit code: N]` (or `[timed out after 300s]`).

## Tests

```
uv run pytest lessons/09-plans-and-checking-work                   # against your agent/
uv run pytest lessons/09-plans-and-checking-work --impl solutions/09-plans-and-checking-work
```

The verify tests use a scripted client and a scripted `verify` function, so the number of requests in a script is part of the test. `test_live_uses_todo` needs `--live`: it runs a three-step task on the 27B, asserts only that the run finishes, and prints whether and how often `todo_write` was used.

## Try it live

Make a copy of the six-bug project described above and run the agent with a check:

```
uv run python scripts/make_fixture.py six-bugs /tmp/bugs9
uv run python -m agent chat --root /tmp/bugs9 --verify "python -m pytest -q"
```

`fixtures/six-bugs` is rebuilt from the description above: the same six bugs and eight tests, but not byte for byte the project the numbers came from (6 of its 8 tests fail before any fix), so expect your counts to differ.

Ask for a change that touches several things. Watch for the magenta list after each `todo_write` and for `Check failed:` followed by pytest's output. The failure text appears in `python -m agent log` as the last user message of the next request.

## Break it

Use the 4B (`AGENT_BASE_URL=http://localhost:11434/v1 AGENT_MODEL=qwen3:4b-instruct AGENT_CONTEXT_WINDOW=16384`) on a fresh copy of the six-bug project (`uv run python scripts/make_fixture.py six-bugs /tmp/bugs9b`). Run `ask "The tests in this project fail. Fix the code so they all pass."` three times without `--verify`, then three times with it, and run `pytest` yourself after each run. Expect the unchecked runs to end with a summary that sounds sure of itself while tests still fail, and the checked runs to be sent back at least once. Then compare `max_verify_attempts` values: it is the number of failed checks after which the harness gives up, so 1 means one check and no retry, the default 2 allows one retry, and 3 allows two. See how often one retry is enough, and make `verify` always return `(False, "no")` to see the run stop after `max_verify_attempts` checks with `verified=False`.

Try the same with only one or two bugs: if the 4B fixes everything unaided, the check costs a command and changes nothing. That is the right outcome.

## Extras

- Make the check run only when files were changed during the run.
- Show `ws.todos` in the system prompt (or re-inject it after a compaction) so the plan survives context trimming.
- Add `TaskCreate`/`TaskUpdate`-style tools: one item at a time, with an id.
- Let `ask` exit with a non-zero code when `verified` is `False`.
