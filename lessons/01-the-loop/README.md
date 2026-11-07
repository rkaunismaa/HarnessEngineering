# Lesson 1: The loop

Start from your lesson 0 code, or copy `solutions/00-setup/agent` into `agent/`.

## Why this exists

The model cannot read a file. It can only emit a message that says "please call `read_file` with these arguments". The **loop** is the harness code that notices that, runs the function, tells the model the result, and asks again - until the model answers in plain text. Everything else in this course hangs off this loop.

Chat-completions messages have a `role`:

- `system`: instructions from the harness (optional; lesson 6 fills it in).
- `user`: what the person typed.
- `assistant`: what the model said. Its `content` may be text, empty, or `None`, and it may carry `tool_calls`, each with an `id`, a function `name`, and `arguments` (a JSON *string*, not a dict).
- `tool`: the harness's answer to one tool call. It must carry the `tool_call_id` of the call it answers. A request in which an assistant message has tool calls that no `tool` message follows is rejected: the server answers `400` (both LM Studio and Ollama did when this lesson was written). Servers were lenient about a *wrong* id - the model still answered correctly - but do not rely on that: the id pairing is the contract, and with two calls in one reply it is the only way to tell results apart.

Each response also has a `finish_reason`: `tool_calls` when the model wants tools run, `stop` when it finished, `length` when it ran out of tokens. Your loop in this lesson stops on "no tool calls in the reply"; later lessons will care about the other reasons.

**Reasoning stays out of the history.** Qwen3 models "think" before answering; the server returns that in a separate field, `reasoning_content`. The Qwen3 model card (https://huggingface.co/Qwen/Qwen3-4B, "Best Practices") says the historical model output should only include the final output part and does not need to include the thinking content, and that its chat template does this itself. Re-sending thinking would also cost prompt tokens on every later request, in a 32K window. So the history keeps `role`, `content` and `tool_calls` only. The **request log** (below) keeps everything the server sent, reasoning included, so you can still read it.

**Two logs.** Your request log records what *your code* sent and received: JSON, one line per request. It is not what the model actually sees. The server applies the model's **chat template** to your `messages` and `tools`, producing one long prompt string with special tokens and the tool definitions written into it. LM Studio's developer log shows requests as the server saw them; find the prompt it rendered for one of your requests and compare it with your own log line. Seeing the template output once makes most "why did the model do that" questions easier.

## How Claude Code does it

- **Observed**: Claude Code's file-reading tool returns numbered lines in the style of `cat -n` and takes `offset` and `limit` arguments. The 2000-line default your tool uses is what this course observed in its output; the current tools reference (https://code.claude.com/docs/en/tools-reference, checked 2026-10-30) documents `offset`/`limit` paging but describes the cap as a token and file-size limit (25,000 tokens, 256 KB), so treat the line count as a course choice.
- **Design note**: the loop shape - request, run every tool call in the reply in order, append results, request again until the reply has no tool calls - is the same shape every tool-using chat agent has. The details Claude Code adds around it (permissions, hooks, context management) are what the following lessons build.

## What you'll build

Add to your `agent/` package. Tests are in `lessons/01-the-loop/tests/`.

**`agent/workspace.py`**
- `Workspace(root: Path)`: `.root` is the resolved absolute path; `.resolve(path: str) -> Path` joins a relative path onto `root`.

**`agent/messages.py`**
- `Usage(prompt_tokens=0, completion_tokens=0)`: dataclass supporting `+`.
- `message_to_dict(msg) -> dict`: the SDK's assistant message as a plain dict: `{"role": "assistant", "content": ...}` plus `"tool_calls": [{"id", "type": "function", "function": {"name", "arguments"}}]` only when there are tool calls. Content stays as the server sent it (`None` or `""`); `reasoning_content` is dropped.

**`agent/tools/registry.py`**
- `Tool`: dataclass `name`, `description`, `parameters` (JSON schema), `fn: Callable[..., str]`, `read_only: bool = False`.
- `ToolRegistry`: `register(tool)`, `get(name) -> Tool | None`, `names()`, `schemas()` (each `{"type": "function", "function": {"name", "description", "parameters"}}`), `dispatch(name, raw_arguments: str) -> str` which does `json.loads` on the argument string and calls `fn(**args)`.

**`agent/tools/files.py`** and **`agent/tools/__init__.py`**
- The `read_file(path, offset=1, limit=2000)` tool, `read_only=True`. Output is one line per file line, formatted `f"{n:>6}\t{line}"` with 1-based `n`, joined by newlines; `offset` is the first line, `limit` the count. A missing file returns `"Error: file not found: <path>"` (a string, not an exception).
- `make_default_tools(ws: Workspace, **kwargs) -> ToolRegistry` returns a registry holding `read_file`. Later lessons add tools and use the keyword arguments.

**`agent/log.py`**
- `RequestLog(path, agent="main")`: `record(request: dict, response: dict, duration_s: float)` appends one JSON line `{"ts" (ISO-8601), "agent", "duration_s", "request", "response"}`. `request` is the keyword arguments you passed to the client; `response` is `completion.model_dump()`. The client object is never logged.
- `RequestLog.for_session(log_dir)` creates `log_dir/YYYYmmdd-HHMMSS.jsonl`; `with_agent(name)` returns a log writing to the same file under a different `agent` name.
- `read_log(path) -> list[dict]`, `latest_log(log_dir) -> Path | None` (newest file; `None` if there is none), `format_entry(entry) -> str` (a readable summary: agent, timing, token counts, finish reason, reasoning, content and each tool call by name and arguments).

**`agent/loop.py`**
- `TurnResult`: `final_text: str`, `stop_reason: str` (`"done"` in this lesson), `turns: int`, `usage: Usage`, `error: str | None = None`.
- `Agent(client, model, tools, *, system=None, log=None, sampling=None)` with `.messages` (starts with the system message if given) and `run(user_message) -> TurnResult`. Each request sends `model`, `messages` and `tools=tools.schemas()`, plus every key in `sampling` (a dict such as `config.sampling()`; `None` or `{}` adds nothing). Later lessons keep adding keyword arguments after these. Every tool call in a reply is run in order and answered with `{"role": "tool", "tool_call_id": id, "content": result}`. The run ends when a reply has no tool calls; `final_text` is that reply's content, or `""` when the content is `None` or empty. Usage is summed over all requests. History persists between `run` calls.
- Structure `run` so that "make one request" and "run one tool call" are separate methods. Later lessons hook into each.

**`agent/__main__.py`** (extend the lesson 0 parser)
- `python -m agent ask "<prompt>" [--root DIR]`: run the agent with `config`'s model and `sampling=config.sampling()`, work in `--root` (default `.`), write a session log under `config.log_dir`, print the final text.
- `python -m agent log [PATH]`: print `format_entry` for every line of the log (default: `latest_log(config.log_dir)`) using `rich`; print the text literally, not as rich markup.

## Tests

```
uv run pytest lessons/01-the-loop                                # against your agent/
uv run pytest lessons/01-the-loop --impl solutions/01-the-loop   # against the reference solution
uv run pytest lessons/01-the-loop --live                         # includes the real-model test
```

[TESTING.md](TESTING.md) walks through what each test checks and how the scripted fake model drives your loop.

## Try it live

From the repository root, make a scratch copy of the small practice project and ask about a file in it (`--root` keeps the agent out of the course repository):

```
uv run python scripts/make_fixture.py scratch /tmp/scratch1
uv run python -m agent ask "Read notes.txt and tell me the second line." --root /tmp/scratch1
uv run python -m agent log
```

Reference run (`qwen/qwen3.8-27b` on LM Studio): two requests, about a second each. The first reply had `finish=tool_calls` and a `read_file({"path":"notes.txt"})` call; the second had `finish=stop` and the answer. Prompt tokens went 382 -> 439 (the tool definition and system-less prompt cost most of the first 382). The log shows the model's reasoning for each request, as a sentence or two; none of it is in `agent.messages`. Tool-call ids are random strings from the server, not `call_1`.

Now open LM Studio's developer log, find the matching request, and locate the rendered prompt. Find where your `read_file` schema appears in it, and where the tool result was placed.

### What happens when you run `ask`, step by step

This follows `uv run python -m agent ask "Read notes.txt and tell me the second line." --root /tmp/scratch1` through the reference solution. Your code should do the same things in the same order.

**1. Startup.** `uv run` starts the project's Python. `python -m agent` runs `agent/__main__.py`, which calls `main()`.

**2. Parsing the command line.** `argparse` matches the subcommand `ask`, takes the quoted text as `args.prompt` and `/tmp/scratch1` as `args.root`, and calls `_ask(args)`. Without `--root`, the default is `.`, the folder you ran the command from.

**3. Building the pieces.** `_ask` builds four objects and hands them to an `Agent`:

```python
config = load_config()                                   # defaults < agent.json < AGENT_* env vars
agent = Agent(make_client(config), config.model,         # OpenAI client pointed at LM Studio
              make_default_tools(Workspace(Path(args.root))),
              log=RequestLog.for_session(config.log_dir),
              sampling=config.sampling())
```

- **The workspace.** `Workspace("/tmp/scratch1")` stores the resolved absolute path. Every path the model gives a tool is joined onto it, so `notes.txt` means `/tmp/scratch1/notes.txt`. (In this lesson that's all it does. A path like `../x` would still get out; lesson 5 closes that.)
- **The tools.** `make_default_tools` builds a `ToolRegistry` holding one tool, `read_file`. The tool is a closure that remembers the workspace.
- **The log.** `RequestLog.for_session(".agent/logs")` creates the folder and picks a file name from the current time, such as `.agent/logs/20261107-142530.jsonl`. `log_dir` is relative to the folder you ran the command from (the repo root), not to `--root`. The log stays with the course, and the scratch folder stays clean.
- **Sampling.** `config.sampling()` is `{}` unless you set `temperature`, `top_p` or `seed`. Then the server's defaults apply.
- **The history.** `agent.messages` starts empty, because there's no system prompt until lesson 6.

**4. `agent.run(prompt)` adds the user message** to the history. The loop begins.

**5. Request 1.** `_request` sends this to `POST http://localhost:1234/v1/chat/completions`:

```json
{"model": "qwen/qwen3.8-27b",
 "messages": [{"role": "user", "content": "Read notes.txt and tell me the second line."}],
 "tools": [{"type": "function", "function": {"name": "read_file",
            "description": "Read a text file. Returns numbered lines. ...",
            "parameters": {"type": "object", "properties": {"path": ..., "offset": ..., "limit": ...},
                           "required": ["path"]}}}]}
```

LM Studio renders this into Qwen's chat template, with the tool schema written into the prompt text (382 prompt tokens in the reference run). The model reasons briefly, then asks for the tool. The reply is:

- `finish_reason: "tool_calls"`
- `content`: empty
- `reasoning_content`: a sentence or two
- `tool_calls`: one call, with an id that is a random string from the server, `function.name` of `read_file`, and `function.arguments` of the *string* `'{"path": "notes.txt"}'`

`_request` writes one line to the log: the request it sent, `completion.model_dump()` (reasoning included), and how long the request took.

**6. Back in the loop.** The reply's token counts are added to the running `Usage`, and `turns` becomes 1. `message_to_dict` turns the SDK message into a plain dict, dropping `reasoning_content`, and appends it to the history. The reply has tool calls, so the loop doesn't stop.

**7. Running the tool.** For each call (one here), `_run_tool_call` calls `tools.dispatch("read_file", '{"path": "notes.txt"}')`. That calls `json.loads` on the arguments string, then `read_file(path="notes.txt")`. The tool resolves `/tmp/scratch1/notes.txt`, reads it, and numbers the lines:

```
     1	alpha
     2	beta
     3	gamma
```

The loop appends `{"role": "tool", "tool_call_id": "<the same id>", "content": "     1\talpha\n     2\tbeta\n     3\tgamma"}`. The id is what tells the model which call this result belongs to. A model may also ask for only the line it needs (`offset=2, limit=1`). The 4B did that in testing, and the result is then just `     2\tbeta`.

**8. Request 2.** The loop goes round again and sends the whole history: the user message, the assistant's tool call, and the tool result. The same tools are sent again; every request is complete on its own, and the server remembers nothing between them. The prompt grew to 439 tokens. This time the model answers in text, along the lines of "The second line of notes.txt is **beta**.", with `finish_reason: "stop"` and no tool calls. A second log line is written.

**9. The loop ends.** The reply has no tool calls, so `run` returns:

```python
TurnResult(final_text="The second line ... beta ...", stop_reason="done", turns=2,
           usage=Usage(prompt_tokens=382 + 439, completion_tokens=...), error=None)
```

`usage` is summed over both requests. The first request's prompt is paid for again inside the second. This is why long sessions get expensive and lesson 8 exists.

**10. Output.** `_ask` prints `final_text` and returns 0. `raise SystemExit(main())` makes that the exit code. The history (`agent.messages`, four messages) disappears when the process exits; only the log file remains.

**Afterwards.** `uv run python -m agent log` finds the newest file in `.agent/logs` and prints one summary per line: agent name, time, duration, message count, token counts, `finish`, the reasoning, and the tool call or content. You'll see the reasoning there even though it was never in the history.

**If the server isn't running,** step 5 raises `openai.APIConnectionError`. In this lesson nothing catches it, so you get a traceback. Lesson 3 turns it into a clean `stop_reason == "error"`.

## Break it

Run the loop over the real server with part of the protocol removed. Write a throwaway script (not part of the agent) that sends this to the model with `tools=` set:

1. a user message, then an assistant message with a `read_file` tool call, and **no** following `tool` message;
2. the same, but with a `tool` message whose `tool_call_id` does not match the call.

Observed here with both `qwen/qwen3.8-27b` (LM Studio) and `qwen3:4b-instruct` (Ollama): case 1 fails with HTTP `400` (Ollama's message: "Cannot continue an assistant message that contains tool calls."); case 2 was accepted and the model answered correctly. Write down what you learn: the error comes from the server's validation, and it arrives as an exception from the client call - your loop in this lesson does not handle it yet.

Also try the 4B model on the happy path (`AGENT_BASE_URL=http://localhost:11434/v1 AGENT_MODEL=qwen3:4b-instruct`). In testing it handled one file, a missing file, and several files in one reply without trouble: it read `notes.txt` with `offset=2, limit=1` on its own and reported missing files correctly. The weak-model failures start in the next lessons, when there are more tools to choose between.

## Extras

- Add a `max_turns` guard of your own and see what a model that never stops would do to it (lesson 3 adds this properly).
- Print token usage after each `ask`, and compare it with the numbers in LM Studio's log.
- Make `format_entry` show the last message of the request too, so a log line is readable on its own.
