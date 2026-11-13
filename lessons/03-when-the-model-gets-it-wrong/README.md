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

[TESTING.md](TESTING.md) walks through what each test checks and why.

Lessons 1 and 2 still apply. The live test is `test_live_4b_failures`: it needs Ollama with `qwen3:4b-instruct` at `http://localhost:11434/v1` (nothing to configure, it builds its own `Config`). It runs three small tasks and only asserts that each run ends with a known `stop_reason`; its value is the printed log of calls and results. Run it with `-s` to see them.

## Try it live

Use the 27B on LM Studio as usual and ask for something that cannot work. `/tmp/scratch` is the project from lesson 2; if you deleted it, run `uv run python scripts/make_fixture.py scratch /tmp/scratch` again.

```
uv run python -m agent ask "Read the file config/settings.yaml and summarise it." --root /tmp/scratch
uv run python -m agent log
```

The file is not there, so `read_file` returns `Error: file not found: config/settings.yaml` as the tool result. Find that message in the log, in the request after the call, and read what the model did with it. Then stop the server (or point `AGENT_BASE_URL` at a port nothing listens on) and run `ask` again to see `Model request failed: ...` and exit status 1.

### What happens when you run it, step by step

This follows one real run of

```
uv run python -m agent ask "Read the file config/settings.yaml and summarise it." --root /tmp/scratch
```

made on 2026-11-13 with a learner's own lesson 3 `agent/` (it passes this lesson's tests) and `qwen/qwen3.8-27b` in LM Studio. Every request, reply, tool result and token count below is copied from that run's log. Run it yourself and the model will word things differently, and may take a different route.

The start of the command is the same as in lesson 1, covered in its [step-by-step walkthrough](../01-the-loop/README.md#what-happens-when-you-run-ask-step-by-step): Python finds your package, `argparse` reads the arguments, and `_ask` builds the client, the tools and the `Agent`. This section picks up from there and concentrates on what's new: what happens to each tool call, and what happens when things fail.

#### Where the code lives

| File | What's in it that this walkthrough uses |
|---|---|
| `agent/__main__.py` | `_ask` |
| `agent/loop.py` | `Agent.run`, `Agent._request`, `Agent._run_tool_call`, `TurnResult`, `LOOP_THRESHOLD`, `LOOP_MESSAGE` |
| `agent/tools/registry.py` | `ToolRegistry.dispatch`, `ToolRegistry._dispatch`, `validate_args`, `truncate` |
| `agent/tools/files.py` | `read_file`, `list_files` and `search` (defined inside `make_read_file`, `make_list_files` and `make_search`) |
| `agent/client.py` | `make_client` |
| `agent/log.py` | `RequestLog.for_session`, `RequestLog.record` |

#### The big picture first

The file doesn't exist, so the task can't be done. The interesting part is what the harness does with that. Nothing raises; every problem becomes text the model reads on its next request:

```
 request 1  model: read_file(config/settings.yaml)
            tool:  "Error: file not found: config/settings.yaml"        <- an error, returned as the result
 request 2  model: "That exact path doesn't exist. Let me look for it."
                   list_files(**/settings*.yaml), list_files(**/*.yml), list_files(**/*.yaml)
            tools: "No files found." x 3
 request 3  model: list_files({}), search(".", glob=**/settings.*)
            tools: the five files in the project, "No matches."
 request 4  model: "The file config/settings.yaml does not exist in this project. ..."   <- final answer
```

Four requests, six tool calls, no crash. The model changed its approach after each result.

#### Step 1. `_ask` builds the agent

`_ask` (`agent/__main__.py`) builds the same `Agent` as in lesson 2, with the four tools and a `rich` prompt for `bash`. Two things are different now, both set inside `Agent.__init__` (`agent/loop.py`):

- **`max_turns`** is 50, the default. `run` makes at most 50 requests before giving up.
- **`_last_call` and `_repeats`** track the loop guard: the last `(tool name, arguments string)` and how many times in a row it has been asked for. `run` resets them to `None` and `0` at the start.

`RequestLog.for_session` (`agent/log.py`) picks a log file name from the current time, `.agent/logs/20261113-164750.jsonl`. The file itself isn't created until the first request is logged, which matters at the end of this walkthrough.

Then `agent.run(...)` appends the question and starts `while turns < self.max_turns:`. In lesson 1 this was `while True:`.

#### Step 2. Request 1: the model tries the obvious thing

`Agent._request` sends the question and the four tool schemas, inside a `try`. The `try` is new: if `create` raises an `openai.APIError`, `run` returns an error result instead of letting the exception end the program (step 8 shows this). This time the request succeeds. After **0.899 s**, with `prompt_tokens=840, completion_tokens=49` (19 of them reasoning), the reply is:

```json
{"role": "assistant", "content": "",
 "reasoning_content": "The user wants me to read config/settings.yaml and summarize it. Let's read the file.",
 "tool_calls": [{"id": "Tx6VRcurOX3LBnkdyVgHODLIAXR654aj", "type": "function",
                 "function": {"name": "read_file", "arguments": "{\"path\":\"config/settings.yaml\"}"}}]}
```

`turns` becomes 1, and the reply is stored (without the reasoning) by `message_to_dict` (`agent/messages.py`).

#### Step 3. The call goes through every check, and the tool reports the error

`run` hands the call to `Agent._run_tool_call` (`agent/loop.py`). This is where lesson 3's checks live, in two layers.

**The loop guard, in `_run_tool_call`.** It builds the key `("read_file", '{"path":"config/settings.yaml"}')`. That differs from `_last_call` (still `None`), so `_repeats` becomes 1. Only a count of `LOOP_THRESHOLD` (3) would stop the call, so it goes on to `self.tools.dispatch(...)`.

**`dispatch`, in `agent/tools/registry.py`.** `dispatch` calls `_dispatch` and passes whatever comes back through `truncate`. `_dispatch` runs its checks in order, and the first failure would become the result:

| Check | For this call | Result if it had failed |
|---|---|---|
| Is `read_file` registered? | yes | `Error: unknown tool '...'. Available tools: read_file, list_files, search, bash` |
| Is `{"path":"config/settings.yaml"}` valid JSON? | yes | `Error: arguments were not valid JSON (...). Send the arguments as a JSON object.` |
| Is it a JSON object? | yes, a dict | `Error: arguments must be a JSON object.` |
| `validate_args(schema, args)` | `[]`: `path` is present and a string | `Error: missing required parameter 'path'` and the like |
| Call `tool.fn(**args)` inside `try` | returned normally | `Error: <ExceptionType>: <message>` |

Every check passed, so `read_file` (defined inside `make_read_file` in `agent/tools/files.py`) ran. It resolved the path, found nothing there, and **returned** the string:

```
Error: file not found: config/settings.yaml
```

It returned that error, it didn't raise one. The `read_file` you wrote in lesson 1 already did that, so none of `_dispatch`'s error branches were needed for this call. They exist for the calls that *would* crash. If `read_file` had raised `FileNotFoundError` instead, lesson 2's `dispatch` would have let it end the whole program with a traceback. Lesson 3's `_dispatch` would turn it into `Error: FileNotFoundError: ...` and carry on.

Either way, the error text becomes an ordinary `tool` message:

```json
{"role": "tool", "tool_call_id": "Tx6VRcurOX3LBnkdyVgHODLIAXR654aj",
 "content": "Error: file not found: config/settings.yaml"}
```

The loop goes round again. Nothing about an error result is special to the loop: it's just text, sent on the next request like any other tool result.

#### Step 4. Request 2: the model reads the error and changes approach

The second request carries three messages: the question, the `read_file` call and the error. After **1.898 s** (`prompt_tokens=893, completion_tokens=119`), the reply has text *and* three tool calls:

```json
{"role": "assistant",
 "content": "That exact path doesn't exist. Let me look for it.",
 "reasoning_content": "The file doesn't exist at that path. Let me search for it.",
 "tool_calls": [
   {"id": "aOjPaXrkcu2VgpG7XcXNgryJotVajCY8", "function": {"name": "list_files", "arguments": "{\"pattern\":\"**/settings*.yaml\"}"}, ...},
   {"id": "60wH0L39EVJxeezQfKTMOUSi73IK0iGi", "function": {"name": "list_files", "arguments": "{\"pattern\":\"**/*.yml\"}"}, ...},
   {"id": "Bon4B1kvoaGqhFN6GiZKh8we0vIzMe5K", "function": {"name": "list_files", "arguments": "{\"pattern\":\"**/*.yaml\"}"}, ...}]}
```

Three new things show up here:

- **The model read the error.** Its reasoning says "The file doesn't exist at that path", and it stopped trying `read_file` and started looking for the file instead. That's what returning errors as results is for.
- **Text and tool calls in one reply.** `content` isn't empty this time, but `tool_calls` isn't either, so the loop keeps going. `run` only stops when there are *no* tool calls. The text stays in the history; it isn't printed to you.
- **Three calls in one reply.** The `for tc in message.tool_calls:` loop runs them in order, and each gets its own `tool` message with its own id. The loop guard counts calls, not replies. All three are `list_files`, but with different `arguments` strings, so each key differs from the one before and `_repeats` goes back to 1 each time. Only three *identical* calls in a row would trigger it.

Each `list_files` passed every `_dispatch` check and returned `No files found.`, so the history gets three `tool` messages saying exactly that.

#### Step 5. Request 3: widen the search

Seven messages go out now. After **2.015 s** (`prompt_tokens=1033, completion_tokens=100`):

```json
{"content": "No YAML files at all. Let me see what's actually in the project.",
 "tool_calls": [
   {"id": "6mM9l09gPBs70qugRytjxZoxWUnHD8dX", "function": {"name": "list_files", "arguments": "{}"}},
   {"id": "KF2j3KLJ8gNKDwsPZZXGccCv5zK1Z9xr", "function": {"name": "search", "arguments": "{\"pattern\":\".\",\"glob\":\"**/settings.*\"}"}}]}
```

- **`list_files({})`** passes `validate_args`. `list_files` has no required parameters, and an empty object has nothing unknown or of the wrong type. The defaults (`pattern="**/*"`, `path="."`) list everything:
  ```
  app/billing.py
  app/main.py
  app/util.py
  calc.py
  notes.txt
  ```
- **`search(".", glob="**/settings.*")`** looks for any character (`.`) in files named `settings.<something>` at any depth. The glob already has a `/`, so `search` uses it as it is. No such file exists, so the result is `No matches.`.

#### Step 6. Request 4: the answer

Ten messages go out. After **3.864 s** (`prompt_tokens=1147, completion_tokens=219`), the reply has `finish_reason: "stop"`, no tool calls, and this `content`:

```
The file `config/settings.yaml` does not exist in this project.

Here's what I checked:
- **`config/settings.yaml`** — not found (there is no `config/` directory at all).
- **Any `.yaml` or `.yml` file** anywhere in the project — none exist.
- **Any `settings.*` file** — none.

The only files currently present in the project are:
...
I can't summarise a file that isn't here. If you'd like, I can:
1. Create a starter `config/settings.yaml` template for you, or
2. Summarise one of the existing files (e.g. `app/main.py` or `notes.txt`) instead.
```

Every claim in it is backed by a tool result from steps 3–5. `run` returns:

```python
TurnResult(final_text="The file `config/settings.yaml` does not exist ...", stop_reason="done",
           turns=4, usage=Usage(prompt_tokens=3913, completion_tokens=487), error=None)
```

The prompt grew with each request: 840, 893, 1,033 and then 1,147 tokens, because every request re-sends the whole history.

#### Step 7. `_ask` prints the answer and exits with 0

`_ask` (`agent/__main__.py`) checks `stop_reason`:

```python
if result.stop_reason == "error":
    print(result.error, file=sys.stderr)
    return 1
if result.stop_reason == "max_turns":
    print(f"Stopped after {result.turns} requests without a final answer.", file=sys.stderr)
    return 1
print(result.final_text)
return 0
```

It's `"done"`, so the answer goes to stdout and the exit status is **0**. `"done"` means the model stopped calling tools and gave an answer. It doesn't mean the task succeeded: here the honest answer is "the file isn't there", and that's a good outcome. Only `error` and `max_turns` mean the harness itself didn't get to an answer.

`uv run python -m agent log` shows the four requests:

```
[main] 2026-11-13T16:47:50.953175  0.899s  1 messages  prompt=840 completion=49  finish=tool_calls
  reasoning: The user wants me to read config/settings.yaml and summarize it. Let's read the file.
  tool call Tx6VRcurOX3LBnkdyVgHODLIAXR654aj: read_file({"path":"config/settings.yaml"})
[main] 2026-11-13T16:47:52.851234  1.898s  3 messages  prompt=893 completion=119  finish=tool_calls
  reasoning: The file doesn't exist at that path. Let me search for it.
  content: That exact path doesn't exist. Let me look for it.
  tool call aOjPaXrkcu2VgpG7XcXNgryJotVajCY8: list_files({"pattern":"**/settings*.yaml"})
  tool call 60wH0L39EVJxeezQfKTMOUSi73IK0iGi: list_files({"pattern":"**/*.yml"})
  tool call Bon4B1kvoaGqhFN6GiZKh8we0vIzMe5K: list_files({"pattern":"**/*.yaml"})
[main] 2026-11-13T16:47:54.866857  2.015s  7 messages  prompt=1033 completion=100  finish=tool_calls
  reasoning: There are no YAML files at all. To figure out what's actually in the project, let me try checking the overall structure.
  content: No YAML files at all. Let me see what's actually in the project.
  tool call 6mM9l09gPBs70qugRytjxZoxWUnHD8dX: list_files({})
  tool call KF2j3KLJ8gNKDwsPZZXGccCv5zK1Z9xr: search({"pattern":".","glob":"**/settings.*"})
[main] 2026-11-13T16:47:58.731188  3.864s  10 messages  prompt=1147 completion=219  finish=stop
  reasoning: The file config/settings.yaml doesn't exist. Let me check the config directory.
  content: The file `config/settings.yaml` does not exist in this project.
  ...
```

The log shows the calls but not their results. To see the results, look at the `messages` in a later request in the `.jsonl` file: each result is there as a `tool` message. The last request's reasoning ("Let me check the config directory") doesn't match what the model then did, which was to answer. Reasoning is a hint at what the model is doing, not a record of it.

#### What didn't happen in this run

The 27B made well-formed calls every time: valid JSON, real tool names, correct parameters, no repeats. So `_dispatch`'s first four checks, its `except Exception`, the loop guard and `max_turns` all had nothing to do. That's normal for a strong model on an easy task. The "Break it" section below shows what the 4B did with the same prompt, and [TESTING.md](TESTING.md) shows each guard firing against scripted replies. They exist for the run where one bad call would otherwise end the session.

#### Step 8. The same command with no server

Now point the harness at a port where nothing is listening:

```
$ AGENT_BASE_URL=http://localhost:1/v1 uv run python -m agent ask "Read the file config/settings.yaml and summarise it." --root /tmp/scratch
Model request failed: Connection error.
$ echo $?
1
```

Here's what happened, in order:

1. **`_request` calls `create`**, and the `openai` library can't connect. Before giving up, the library itself tries again twice: `make_client` (`agent/client.py`) doesn't change its default of two retries. The whole command took **1.74 s**, startup included.
2. **The library raises `openai.APIConnectionError`.** That's a subclass of `openai.APIError`, so the `except openai.APIError as exc:` in `run` catches it.
3. **`run` returns at once**, with `TurnResult(final_text="", stop_reason="error", turns=0, usage=Usage(0, 0), error="Model request failed: Connection error.")`. `turns` is 0, because only requests that succeeded are counted. Nothing is added to `self.messages` for the failed request, so the history still ends with your question. The same `Agent` could call `run` again once the server is back.
4. **`_ask` sees `stop_reason == "error"`**, prints the error to **stderr** and returns 1. The exit status of 1 lets a script or a shell `&&` tell that it failed. Lesson 2's version would have died with a long traceback here instead.
5. **No log file was written.** `RequestLog.record` only runs after a request succeeds, and the file is only created on the first `record`. So `agent log` still shows the previous run.

A `max_turns` stop looks similar from outside: nothing on stdout, `Stopped after 50 requests without a final answer.` on stderr, and exit status 1. Unlike an error, every request it made is in the log.

#### If something goes wrong

- **A traceback instead of `Model request failed: ...`:** your `run` isn't catching `openai.APIError` around `_request`, or it's catching too narrow a type (`APIConnectionError` alone misses a `400`).
- **A traceback from inside a tool:** your `_dispatch` doesn't wrap `tool.fn(**args)` in `try`/`except Exception`.
- **The model keeps asking for the same thing until `max_turns`:** read its calls in the log. If the arguments are identical three times in a row and the third one still ran, the loop guard isn't counting right. It compares `(name, arguments string)` with the previous call, across replies too.
- **Exit status 0 with an empty answer:** `_ask` printed `final_text` without checking `stop_reason` first.

#### Words used above

| Term | Meaning here |
|---|---|
| **error result** | An `Error: ...` string returned as a tool's result, so the model can read what went wrong. |
| **`_dispatch` checks** | Unknown tool, bad JSON, not an object, `validate_args`, then the tool itself inside `try`. The first failure becomes the result. |
| **loop guard** | The check in `_run_tool_call` that refuses a third identical call in a row with `LOOP_MESSAGE`. |
| **`stop_reason`** | Why `run` returned: `done` (the model answered), `max_turns` (the request limit was hit), or `error` (a request to the server failed). |
| **exit status** | The number a program gives the shell when it ends: 0 for success, anything else for failure. `echo $?` prints it. |
| **stderr** | The second output stream, meant for errors. It shows in the terminal but isn't captured by `> file`. |

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
