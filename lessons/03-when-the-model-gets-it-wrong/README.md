# Lesson 3: When the model gets it wrong

Start from your lesson 2 code, or copy `solutions/02-tools/agent` into `agent/`.

## Why this exists

Up to now the agent assumes the model behaves. A model does not. Over a long session it will eventually do each of these:

| Failure | What it looks like |
|---|---|
| Bad JSON | `arguments` is `{"path": "a.txt"` (cut off), or has a stray quote or curly quote. |
| Invented tool | A call to `edit_file` or `grep` when no such tool exists. |
| Missing or wrong parameters | No `pattern` for `search`, `limit: "10"` as a string, a parameter that does not exist. |
| Failing tool | A path that is not there, a regex that does not compile, a glob the tool rejects. |
| Repeating itself | The same call, with the same arguments, over and over, expecting a different answer. |
| Never stopping | A chain of reasonable-looking tool calls that never reaches a final answer. |
| A dead server | The request itself fails: connection refused, a 400, a timeout. |

The first four share one fix: **an error is a tool result**. If the harness raises, the session dies. If it returns `"Error: ..."` text as the result of that call, the model reads what went wrong on its next request and usually fixes it. The error text is written for the model, so it should say what was wrong and, where it can, what would be right (the unknown-tool error lists the tools that do exist).

The last three need limits in the loop: a cap on requests, a check for identical repeated calls, and a clean way out when the server fails.

## How Claude Code does it

- **Observed**: when a tool call is invalid or fails, Claude Code hands an error message back to the model as that call's result and the turn goes on; it does not stop the session. You can see this by asking it to read a file that does not exist and watching it report the error and try something else.
- **Design note**: how many times Claude Code retries a failed call, whether it detects repeated calls, and what limits it puts on a turn are internal details this course did not find documented. The limits here (`max_turns=50`, three identical calls in a row) are this course's choices, picked for a small local model, not a copy of anything.

## What you'll build

Extend your `agent/` package. Tests are in `lessons/03-when-the-model-gets-it-wrong/tests/`.

**`agent/tools/registry.py`**

`dispatch(name, raw_arguments) -> str` **never raises**. Every result, errors included, still goes through `truncate`. Checks run in this order and the first failure wins; the strings are exact:

| Situation | Result |
|---|---|
| Name not registered | `f"Error: unknown tool '{name}'. Available tools: {', '.join(names)}"` (`names` in registration order) |
| `raw_arguments` is not valid JSON | `f"Error: arguments were not valid JSON ({exc.msg}). Send the arguments as a JSON object."` where `exc` is the `json.JSONDecodeError` |
| JSON, but not an object (a list, string, number, `null`) | `"Error: arguments must be a JSON object."` |
| `validate_args` finds problems | `"Error: " + "; ".join(errors)` |
| The tool raises any `Exception` | `f"Error: {type(exc).__name__}: {exc}"` |

Because this covers every exception, the lesson 2 tools that still raised (for example `list_files` with an empty or absolute glob) now come back as `Error: ValueError: ...` text with no change to the tools themselves.

`validate_args(schema: dict, args: dict) -> list[str]` checks `args` against a tool's `parameters` schema and returns one message per problem, in this order: missing required parameters (in the order of `required`), then unknown parameters (in the order of `args`), then type problems (in the order of `args`).

- `f"missing required parameter '{p}'"`
- `f"unknown parameter '{k}'"`
- `f"parameter '{k}' must be {type}"` for a parameter whose schema `type` is `string`, `integer`, `number`, `boolean`, `array` or `object`. In JSON a boolean is not an integer or a number, so `true` fails for both, even though Python's `isinstance(True, int)` says otherwise. An `int` is a valid `number`. A parameter whose schema has no `type` is not checked.

**`agent/loop.py`**
- `Agent(..., max_turns: int = 50)`. `max_turns` counts model requests within one `run()`. When the limit is reached without a final answer, return `TurnResult(final_text="", stop_reason="max_turns", ...)`. Every tool call already made has its result in `messages`, so the history stays valid.
- `LOOP_THRESHOLD = 3`. Within one `run()`, when the same `(name, raw_arguments)` is requested for the 3rd consecutive time (counting calls inside a single reply too), do not execute it. The result is `"Error: you have made this exact call 3 times in a row. Try a different approach."` A 4th identical call gets the same message. Any different call resets the count.
- Any `openai.APIError` from `create` (this includes connection errors, which are a subclass) ends the run with `stop_reason="error"` and `error=f"Model request failed: {exc}"`, `final_text=""`. Nothing is appended for the failed request: the history still ends with the user message (or the last tool result), so the same agent can `run` again once the server is back. `turns` counts only requests that succeeded.

**`agent/__main__.py`**
- `ask` prints `error` (or a short note for `max_turns`) to stderr and exits with 1 instead of printing an empty answer.

## Tests

```
uv run pytest lessons/03-when-the-model-gets-it-wrong                               # against your agent/
uv run pytest lessons/03-when-the-model-gets-it-wrong --impl solutions/03-when-the-model-gets-it-wrong
uv run pytest lessons/03-when-the-model-gets-it-wrong --live                        # prints a 4B run, see below
```

Lessons 1 and 2 still apply. The live test is `test_live_4b_failures`: it needs Ollama with `qwen3:4b-instruct` at `http://localhost:11434/v1` (nothing to configure, it builds its own `Config`). It runs three small tasks and only asserts that each run ends with a known `stop_reason`; its value is the printed log of calls and results. Run it with `-s` to see them.

## Try it live

Use the 27B on LM Studio as usual and ask for something that cannot work:

```
uv run python -m agent ask "Read the file config/settings.yaml and summarise it." --root /tmp/scratch
uv run python -m agent log
```

The file is not there, so `read_file` returns `Error: file not found: config/settings.yaml` as the tool result. Find that message in the log, in the request after the call, and read what the model did with it. Then stop the server (or point `AGENT_BASE_URL` at a port nothing listens on) and run `ask` again to see `Model request failed: ...` and exit status 1.

## Break it

A 4B model is supposed to be the one that fails, so go and look. These are runs of `qwen3:4b-instruct` through Ollama (`AGENT_BASE_URL=http://localhost:11434/v1 AGENT_MODEL=qwen3:4b-instruct`), with the lesson 2 tools and `max_turns=12`, in a scratch project with `app/billing.py`, `app/util.py` and `notes.txt`. Run your own and compare.

**What did not happen.** On ordinary tasks (find a function, read a file, count files, run a command that is declined) the 4B produced well-formed calls with valid arguments every time. In about 25 runs it never sent invalid JSON, never invented a tool name or omitted a required parameter. When asked to call `edit_file`, which does not exist, it answered in text that the tool was not available, without calling it. So the harness's error strings are insurance you will mostly not see used with this model on easy work. Do not take that as a reason to skip them: one bad call with no handler ends a session, and weaker models, longer sessions and more tools make it more likely.

**What did happen.**

- *Tool errors as results, and the model reading them.* Told to read `config/settings.yaml` ("it exists, keep trying other paths, never give up"), the model got `Error: file not found: config/settings.yaml`, then tried `list_files` with `config/*.yaml`, then `**/config/*.yaml`, then gave up with a text answer saying the file could not be found. Five runs of this prompt all ended `done` in 5 or 6 requests. The error text was enough for it to change approach.
- *Near-repeats.* In that same run it sent `list_files({"pattern":"config/*.yaml"})` twice in a row and `list_files({"pattern":"**/config/*.yaml"})` twice in a row, which is below the threshold of three, so the guard stayed quiet. The loop check never fired in any live run. Its job is the worse day, and its test uses a scripted model.
- *Garbled arguments that are still valid JSON.* With `max_turns=3` on the same prompt, one run produced `list_files({"path":"config”, "})`, with a curly quote that put junk inside the string, and the tool answered `Error: directory not found: config”, `. The next call repeated the mistake with `"./”, "`. The arguments were valid JSON, so `validate_args` had nothing to say; the error came from the tool, and the model could not repair it before the limit. The run ended with `stop_reason == "max_turns"` and an empty `final_text`. This is why `max_turns` exists: nothing else would have ended that run.
- *A wrong answer with no error at all.* Asked which functions in the project are never called, the 4B searched for `read_file`, `list_files` and `bash` (names it took from its own tool list), got `No matches.` three times, and concluded "none of the functions in the project are ever called". No guard in this lesson can catch that. An error string only helps when something visibly fails.

**Exercises.**

1. Run `ask` with the config prompt above against the 4B and watch the log for each `Error:` result and what the next call changed.
2. Set `max_turns=3` and run it again. See `max_turns` in the result.
3. In a throwaway script, wrap `ToolRegistry.dispatch` so the first call of a run gets `raw_arguments` cut off halfway, and see whether the 4B recovers from the bad-JSON message. This is fault injection, not something the model did by itself.
4. Make the loop guard fire against a real model: register a tool that always returns `Error: try again later` and tell the model to keep calling it until it works.

## Extras

- Add a hint to the loop message: include the call that was repeated, so the model sees what to avoid.
- Tell the model how many requests it has left when it is about to hit `max_turns`, and give it one last request with no tools to summarise where it got to.
- Retry transient server errors (connection reset, HTTP 5xx) a couple of times with a short delay before giving up; do not retry a 400.
- Suggest corrections in `unknown tool`: if the name is close to a real one, say "did you mean `read_file`?".
- Count how often each error type happens across runs and print a summary at the end of a session.
