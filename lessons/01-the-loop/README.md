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

**Reasoning stays out of the history.** Qwen3 models "think" before answering; the server returns that in a separate field, `reasoning_content`. The Qwen3 model card (https://huggingface.co/Qwen/Qwen3-4B, "Best Practices") says the historical model output should only include the final output part and does not need to include the thinking content, and that its chat template does this itself. The Qwen3.8 template this course uses would actually write earlier thinking back into the prompt if you sent it (step 8 of the walkthrough below shows the setting), so leaving it out is the harness's decision. Re-sending thinking would also cost prompt tokens on every later request, in a 32K window. So the history keeps `role`, `content` and `tool_calls` only. The **request log** (below) keeps everything the server sent, reasoning included, so you can still read it.

**Two logs.** Your request log records what *your code* sent and received: JSON, one line per request. It is not what the model actually sees. The server applies the model's **chat template** to your `messages` and `tools`, producing one long prompt string with special tokens and the tool definitions written into it. LM Studio's developer log shows requests as the server saw them; find the prompt it rendered for one of your requests and compare it with your own log line. Seeing the template output once makes most "why did the model do that" questions easier. `lms log stream -s model --filter input,output` prints it in a terminal; steps 5 and 8 of the walkthrough below show real ones.

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

This section follows one real run of

```
uv run python -m agent ask "Read notes.txt and tell me the second line." --root /tmp/scratch1
```

through the reference solution (`solutions/01-the-loop`), against `qwen/qwen3.8-27b` in LM Studio. Every request, reply, id and token count below is copied from that run's log (2026-11-12). Your own run will have a different tool-call id and slightly different wording, but the same shape.

#### Where the code lives

Every function named below is in one of these files. The paths are relative to your `agent/` package; the reference versions are the same files under `solutions/01-the-loop/agent/`.

| File | Functions and classes used in this walkthrough |
|---|---|
| `agent/__main__.py` | `main`, `build_parser`, `_ask`, `_log` |
| `agent/config.py` | `Config`, `load_config`, `Config.sampling` |
| `agent/client.py` | `make_client` |
| `agent/workspace.py` | `Workspace`, `Workspace.resolve` |
| `agent/tools/__init__.py` | `make_default_tools` |
| `agent/tools/files.py` | `make_read_file`, and the `read_file` function defined inside it |
| `agent/tools/registry.py` | `Tool`, `ToolRegistry`, `ToolRegistry.get`, `ToolRegistry.schemas`, `ToolRegistry.dispatch` |
| `agent/loop.py` | `Agent`, `Agent.run`, `Agent._request`, `Agent._run_tool_call`, `TurnResult` |
| `agent/messages.py` | `message_to_dict`, `Usage` |
| `agent/log.py` | `RequestLog`, `RequestLog.for_session`, `RequestLog.record`, `read_log`, `latest_log`, `format_entry` |

#### The big picture first

Three parties are involved, and it helps to keep them apart:

- **You**, at the terminal. You type one command and later see one line of output.
- **The harness**: your Python code, `python -m agent`. It holds the conversation, runs tools and talks to the server. It is the only party that can touch files.
- **The model server**: LM Studio, at `http://localhost:1234/v1`. It receives a conversation, runs the model over it, and returns the model's next message. It **remembers nothing between requests**; each request must carry the whole conversation so far.

The model can't read `notes.txt` itself. All it can do is reply "please call `read_file` with `{"path": "notes.txt"}`". So answering this one question takes **two requests**:

```
 you          harness (your code)                          LM Studio (the model)
  |  ask "..."   |                                                  |
  |------------->|  request 1: [user question] + tool list          |
  |              |------------------------------------------------->|
  |              |  reply 1: "call read_file(notes.txt)"            |
  |              |<-------------------------------------------------|
  |              |  runs read_file itself, gets the file text       |
  |              |  request 2: [question, call, file text] + tools  |
  |              |------------------------------------------------->|
  |              |  reply 2: "The second line ... is beta."         |
  |              |<-------------------------------------------------|
  |  prints it   |                                                  |
  |<-------------|                                                  |
```

That repeat ("send, run any tools it asked for, send again") is the **loop**. Here is the reference loop from `agent/loop.py` (methods of the `Agent` class), with the step numbers used below:

```python
# agent/loop.py, class Agent
def run(self, user_message: str) -> TurnResult:
    self.messages.append({"role": "user", "content": user_message})          # step 4
    usage = Usage()
    turns = 0
    while True:
        completion = self._request()                                          # steps 5 and 8
        turns += 1
        if completion.usage:
            usage += Usage(completion.usage.prompt_tokens, completion.usage.completion_tokens)
        message = completion.choices[0].message
        self.messages.append(message_to_dict(message))                       # step 6
        if not message.tool_calls:                                            # step 9: no calls -> done
            return TurnResult(message.content or "", "done", turns, usage)
        for tc in message.tool_calls:                                         # step 7
            self.messages.append({"role": "tool", "tool_call_id": tc.id,
                                  "content": self._run_tool_call(tc)})

def _request(self):
    kwargs = {"model": self.model, "messages": self.messages,
              "tools": self.tools.schemas(), **self.sampling}
    start = time.monotonic()
    completion = self.client.chat.completions.create(**kwargs)               # the HTTP request
    if self.log:
        self.log.record(kwargs, completion.model_dump(), time.monotonic() - start)
    return completion

def _run_tool_call(self, tool_call) -> str:
    fn = tool_call.function
    return self.tools.dispatch(fn.name, fn.arguments)
```

Keep one variable in mind throughout: **`self.messages`**, the conversation history. It's a plain Python list of dicts, and the whole run is really just that list growing from one message to four.

#### Step 1. Python starts and finds your package

- `uv run` makes sure the project's virtual environment (`.venv`, with `openai` and `rich` installed) exists and is up to date, then runs the rest of the command with that environment's Python.
- `python -m agent` means "run the package `agent` as a program". Python looks for a folder called `agent/` in the current directory (that's why you run from the repo root), and runs the file `agent/__main__.py` inside it.
- At the bottom of that file, `raise SystemExit(main())` calls `main()` (also in `agent/__main__.py`). Whatever number `main()` returns becomes the process's exit code (0 means success).

#### Step 2. `argparse` works out what you asked for

`main()` calls `build_parser()` (both in `agent/__main__.py`), which builds a parser with three subcommands (`smoke`, `ask`, `log`) and gives it the words after `agent`:

```
["ask", "Read notes.txt and tell me the second line.", "--root", "/tmp/scratch1"]
```

The shell has already removed the quotes, so the question arrives as **one** word. The parser matches `ask`, and produces an object holding the results:

```python
args.prompt == "Read notes.txt and tell me the second line."
args.root   == "/tmp/scratch1"         # default "." if you leave --root out
args.func   == _ask                    # set by ask.set_defaults(func=_ask)
```

`main()` then calls `args.func(args)`, which is `_ask(args)`, defined in `agent/__main__.py`. This "store the function to call" trick is how one `main()` serves every subcommand.

#### Step 3. `_ask` builds the pieces and connects them

```python
# agent/__main__.py, inside _ask
config = load_config()
agent = Agent(make_client(config), config.model,
              make_default_tools(Workspace(Path(args.root))),
              log=RequestLog.for_session(config.log_dir),
              sampling=config.sampling())
```

Read it inside out:

- **`load_config()`** (`agent/config.py`) starts from the defaults in `Config`, applies `agent.json` if it exists, then any `AGENT_*` environment variables. With nothing set: `base_url="http://localhost:1234/v1"`, `model="qwen/qwen3.8-27b"`, `api_key="lm-studio"`, `log_dir=.agent/logs`.
- **`make_client(config)`** (`agent/client.py`) creates `openai.OpenAI(base_url=..., api_key=...)`. This is the official OpenAI library, pointed at LM Studio instead of OpenAI's servers. **Creating it sends nothing.** It only stores where to send requests later. LM Studio ignores the key, but the library insists on one.
- **`Workspace(Path("/tmp/scratch1"))`** (`agent/workspace.py`) stores the folder as an absolute path in `ws.root`. Its `resolve("notes.txt")` returns `/tmp/scratch1/notes.txt`. This is how a relative path from the model becomes a real file. (In this lesson, nothing stops `../something` from leaving the folder; lesson 5 adds that.)
- **`make_default_tools(ws)`** (`agent/tools/__init__.py`) creates a `ToolRegistry` (`agent/tools/registry.py`), a small dict-like object from tool names to `Tool` objects, and registers one tool, `read_file`. `read_file` is defined *inside* `make_read_file(ws)` in `agent/tools/files.py`, so it can use `ws` later without being passed it. A function that remembers a variable from where it was defined is called a **closure**.
- **`RequestLog.for_session(".agent/logs")`** (`agent/log.py`) creates the `.agent/logs` folder if needed and picks a file name from the current time (this run: `20261112-090820.jsonl`). Nothing is written yet. The path is relative to the folder you ran the command from (the repo root), not to `--root`, so logs collect in the course repo and the scratch project stays clean.
- **`config.sampling()`** (a method of `Config`, in `agent/config.py`) returns `{}` here, because no `temperature`, `top_p` or `seed` is set. An empty dict adds nothing to the requests, so LM Studio uses its own defaults.
- **`Agent(...)`** (`agent/loop.py`) just stores all of these on `self`. No `system` was given, so the history starts empty:

```python
self.messages == []
```

#### Step 4. The question goes into the history

`_ask` calls `agent.run("Read notes.txt and tell me the second line.")`. The first line of `Agent.run` (`agent/loop.py`) appends the question:

```python
self.messages == [
    {"role": "user", "content": "Read notes.txt and tell me the second line."},
]
```

`usage` starts at zero and `turns` at 0. Then the `while True:` loop starts.

#### Step 5. Request 1: the harness asks the model

`Agent._request` (`agent/loop.py`) builds the keyword arguments and passes them to `client.chat.completions.create(**kwargs)`. The library turns them into JSON and sends an HTTP `POST` to `http://localhost:1234/v1/chat/completions`. This is the request body from the log:

```json
{
  "model": "qwen/qwen3.8-27b",
  "messages": [
    {"role": "user", "content": "Read notes.txt and tell me the second line."}
  ],
  "tools": [
    {"type": "function",
     "function": {
       "name": "read_file",
       "description": "Read a text file. Returns numbered lines. Use offset (1-based line) and limit to read part of a large file.",
       "parameters": {
         "type": "object",
         "properties": {
           "path":   {"type": "string",  "description": "File path"},
           "offset": {"type": "integer", "description": "First line to read (1-based)"},
           "limit":  {"type": "integer", "description": "Maximum number of lines"}
         },
         "required": ["path"]}}}
  ]
}
```

The `tools` list comes from `ToolRegistry.schemas()` in `agent/tools/registry.py`. It is a *description* of the tool (its name, what it does and what arguments it takes, as a JSON Schema), not the tool itself. The model only ever sees this description. Your Python function stays on your machine.

**What LM Studio does with it:** it feeds `messages` and `tools` into the model's **chat template**, which writes them out as one long piece of text with special markers. That text was **382 tokens** long. The model reads it and generates a reply. Qwen thinks first, in a separate field. The call blocks (waits) until the reply is complete; this one took **0.99 s**.

**Inside LM Studio: the chat template.** A model doesn't really read "messages" or "tools". It reads one long sequence of tokens and predicts what comes next. So before anything is generated, LM Studio has to turn your JSON into text, and it has to be text laid out *exactly* the way the model saw during training, or it behaves worse. The model's makers ship that layout as a small program called the **chat template**, written in Jinja (a templating language). It's stored inside the model file itself: for this model it's the `tokenizer.chat_template` entry in `Qwen3.8-27B-Q4_K_M.gguf`, 173 lines long. Ollama and vLLM run the same kind of template.

You can watch the result. Run `lms log stream -s model --filter input,output` in a second terminal, then run the `ask` command. When the command was rerun on 2026-11-12, request 1 above became this text (copied from that log, nothing removed):

```text
<|im_start|>system
Reasoning effort is set to xhigh. Please think carefully through the task, validate key assumptions, consider plausible alternatives, and prioritize correctness, consistency, and clarity in the final answer.

# Tools

You have access to the following functions:

<tools>
{"type": "function", "function": {"name": "read_file", "description": "Read a text file. Returns numbered lines. Use offset (1-based line) and limit to read part of a large file.", "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "File path"}, "offset": {"type": "integer", "description": "First line to read (1-based)"}, "limit": {"type": "integer", "description": "Maximum number of lines"}}, "required": ["path"]}}}
</tools>

If you choose to call a function ONLY reply in the following format with NO suffix:

<tool_call>
<function=example_function_name>
<parameter=example_parameter_1>
value_1
</parameter>
<parameter=example_parameter_2>
This is the value for the second parameter
that can span
multiple lines
</parameter>
</function>
</tool_call>

<IMPORTANT>
Reminder:
- Function calls MUST follow the specified format: an inner <function=...></function> block must be nested within <tool_call></tool_call> XML tags
- Required parameters MUST be specified
- You may provide optional reasoning for your function call in natural language BEFORE the function call, but NOT after
- If there is no function call available, answer the question like normal with your current knowledge and do not tell the user about function calls
</IMPORTANT><|im_end|>
<|im_start|>user
Read notes.txt and tell me the second line.<|im_end|>
<|im_start|>assistant
<think>
```

Reading it from the top:

- **`<|im_start|>` and `<|im_end|>`** are *special tokens*: single tokens the model learned as "a message starts here" and "a message ends here". The word right after `<|im_start|>` is the role: `system`, `user` or `assistant`.
- **There's a system message you never sent.** Your request had no `system` message, but the template wrote one anyway. Its first line comes from a template setting called `reasoning_effort`, which defaults to `xhigh` when the request doesn't set it. (It could also be `medium` or `low`.)
- **Your `tools` list went into the system message**, under `# Tools`, inside `<tools>...</tools>`, one line of JSON per tool. Then come about 20 lines of instructions telling the model how to call a function. Together, these are most of the 382 tokens; the question itself is about a dozen. Lesson 2 adds tools, and every tool's line is sent again on every request.
- **The call format isn't JSON.** The model is told to write calls as `<tool_call><function=read_file><parameter=path>notes.txt</parameter></function></tool_call>`. That's the format this model family was trained on.
- **The prompt ends halfway through a message:** `<|im_start|>assistant` and then `<think>`. This is called the *generation prompt*. The model's job is to continue the text from there, so it starts by thinking.

The model then writes, one token at a time: its thinking, then `</think>`, then a `<tool_call>` block in the format above, then `<|im_end|>`. LM Studio reads that raw text back and *parses* it into the JSON you get. The thinking (the text before `</think>`) becomes `reasoning_content`. The `<tool_call>` block becomes an entry in `tool_calls`, with the parameters turned into the `arguments` JSON string and a random `id` that LM Studio makes up. What's left over becomes `content`, which is why `content` is `""` below. When a model or server gets this parsing wrong, you see "tool call" text inside `content` and an empty `tool_calls`. Lesson 3 deals with that.

**What comes back:** the library turns the JSON reply into a Python object, `completion`. The part that matters is `completion.choices[0]`:

```json
{
  "finish_reason": "tool_calls",
  "message": {
    "role": "assistant",
    "content": "",
    "reasoning_content": "The user is asking to read notes.txt and report the second line. Let me try reading the file.",
    "tool_calls": [
      {"id": "M3euI7RG61SZicwVEeGrNh1XcHvZMiLS",
       "type": "function",
       "function": {"name": "read_file", "arguments": "{\"path\":\"notes.txt\"}"}}
    ]
  }
}
```

and `completion.usage` is `prompt_tokens=382, completion_tokens=50`. Of those 50, 21 were reasoning. Points to notice:

- **`finish_reason: "tool_calls"`** means the model stopped because it wants a tool run.
- **`content` is `""`.** There's no text for you yet.
- **`arguments` is a string**, `"{\"path\":\"notes.txt\"}"`: JSON text inside JSON, not a dict. The harness must parse it.
- **The `id`** is a random string LM Studio made up. The harness must quote it back with the result.
- **`reasoning_content`** is the model's thinking. It's useful to read, but it won't be put into the history.

Before returning, `_request` writes the first log line by calling `RequestLog.record` (`agent/log.py`): the request dict, `completion.model_dump()` (the whole reply object converted to plain dicts, reasoning included), and the duration.

#### Step 6. The model's reply goes into the history

Back in `run`: `turns` becomes 1, and the token counts are added to `usage`. Then `message_to_dict(message)` (`agent/messages.py`) copies the parts of the reply worth keeping into a plain dict: `role`, `content`, and `tool_calls` with exactly `id`, `type`, `name` and `arguments`. It leaves out `reasoning_content` and the reply's other empty fields (`refusal`, `audio`, and so on). The history now holds two messages:

```python
self.messages == [
    {"role": "user", "content": "Read notes.txt and tell me the second line."},
    {"role": "assistant", "content": "",
     "tool_calls": [{"id": "M3euI7RG61SZicwVEeGrNh1XcHvZMiLS", "type": "function",
                     "function": {"name": "read_file", "arguments": "{\"path\":\"notes.txt\"}"}}]},
]
```

Why a plain dict and not the library's object? The history is sent back to the server next time, and written to logs. Plain dicts make that, and testing, simple.

`message.tool_calls` is not empty, so `if not message.tool_calls` is false and the loop does **not** return.

#### Step 7. The harness runs the tool

For each tool call (one here), `Agent._run_tool_call(tc)` (`agent/loop.py`) calls:

```python
self.tools.dispatch("read_file", "{\"path\":\"notes.txt\"}")
```

`ToolRegistry.dispatch` (`agent/tools/registry.py`) does three small things:

1. `tool = self.get("read_file")` finds the `Tool` object by name.
2. `args = json.loads('{"path":"notes.txt"}')` turns the string into the dict `{"path": "notes.txt"}`.
3. `tool.fn(**args)` calls the function with those as keyword arguments, so it is exactly `read_file(path="notes.txt")`. `offset` and `limit` keep their defaults, 1 and 2000.

Inside `read_file` (`agent/tools/files.py`), `ws.resolve("notes.txt")` (`agent/workspace.py`) gives `/tmp/scratch1/notes.txt`. The file exists, so it is read and split into lines: `["alpha", "beta", "gamma"]`. Each line gets a right-aligned number and a tab (`f"{n:>6}\t{line}"`), and the lines are joined with newlines:

```
     1	alpha
     2	beta
     3	gamma
```

The numbers let the model, and later the edit tool, talk about "line 2" reliably. The loop wraps the result in a `tool` message carrying **the same id** as the call, and appends it:

```python
self.messages == [
    {"role": "user", ...},
    {"role": "assistant", "content": "", "tool_calls": [{"id": "M3euI7RG...", ...}]},
    {"role": "tool", "tool_call_id": "M3euI7RG61SZicwVEeGrNh1XcHvZMiLS",
     "content": "     1\talpha\n     2\tbeta\n     3\tgamma"},
]
```

The id pairing is how the model knows which result belongs to which call. With two calls in one reply, it's the only way to tell them apart. If a tool call is left without an answer, the server rejects the next request with a 400 error (see "Break it" below).

The `for` loop ends and the `while True:` loop goes round again.

#### Step 8. Request 2: same question, more history

`_request` runs again. It builds the same kind of request, but `messages` is now the three-message list from step 7, and the `tools` list is sent again unchanged. The server keeps no memory of request 1: everything the model needs to know has to be in this request. That includes the original question, the fact that it asked for `read_file`, and the result.

The rendered prompt is now **439 tokens** (382 before, plus the tool call and the file text). The model reads it and answers in text, taking **0.945 s**:

```json
{
  "finish_reason": "stop",
  "message": {
    "role": "assistant",
    "content": "The second line of notes.txt is **beta**.",
    "reasoning_content": "The user asked for the second line of notes.txt. I read the file. The second line is \"beta\". I should give a brief answer.",
    "tool_calls": []
  }
}
```

with `prompt_tokens=439, completion_tokens=44` (30 of them reasoning). **`finish_reason: "stop"`** means the model finished on its own. `tool_calls` is an empty list here (another server might send `None`); `if not message.tool_calls` treats both as "no calls". A second line is written to the log.

**What the chat template made of request 2.** The text is the same as request 1 up to the question (the system message, the reasoning-effort line and the tool instructions are all repeated). After the question, it continued like this (from the same 2026-11-12 rerun):

```text
<|im_start|>user
Read notes.txt and tell me the second line.<|im_end|>
<|im_start|>assistant
<think>

</think>

<tool_call>
<function=read_file>
<parameter=path>
notes.txt
</parameter>
</function>
</tool_call><|im_end|>
<|im_start|>user
<tool_response>
1	alpha
     2	beta
     3	gamma
</tool_response><|im_end|>
<|im_start|>assistant
<think>
```

Four things to notice:

- **The thinking from request 1 isn't there.** The assistant turn has an empty `<think>` block, because your history doesn't keep `reasoning_content` (step 6). This template would have written it back in if you had sent it; its `preserve_thinking` setting is on by default. So keeping the thinking out is your harness's choice, and here it saved about 20 tokens. In a long session it saves thousands.
- **Your `arguments` string was turned back into the model's own format.** `"{\"path\":\"notes.txt\"}"` became a `<parameter=path>` block, the same way the model wrote it.
- **The tool result became a `user` message,** wrapped in `<tool_response>`. **The `tool_call_id` appears nowhere.** The model matches a result to its call by position: results follow the calls in the same order. The id is part of the HTTP API. The server checks it (that's where the `400` errors described at the top of this lesson come from), and your harness uses it, but the model never reads it.
- **The first line lost its leading spaces.** `read_file` returned `     1\talpha`, but the template trims the start and end of each message, so it became `1\talpha`. Here that doesn't matter. Just remember that the text the model reads isn't always exactly what you sent.

The model's raw output for this request (the `output` entry in the same log):

```text
The user is asking for the second line of notes.txt. I loaded it. The second line is "beta". Simple.
</think>

The second line of notes.txt is:

**beta**
```

LM Studio split it at `</think>`. The part before became `reasoning_content`, and the part after became `content`. There was no `<tool_call>` block, so `tool_calls` came back empty. (This rerun worded its answer slightly differently from the run in the JSON above. The same model can give different text each time.)

#### Step 9. No tool calls, so the loop ends

`turns` becomes 2, `usage` is updated, and the reply goes into the history, which now has its final four messages:

```python
self.messages == [
    {"role": "user", "content": "Read notes.txt and tell me the second line."},
    {"role": "assistant", "content": "", "tool_calls": [...read_file...]},
    {"role": "tool", "tool_call_id": "M3euI7RG...", "content": "     1\talpha\n..."},
    {"role": "assistant", "content": "The second line of notes.txt is **beta**."},
]
```

This time `message.tool_calls` is empty, so `run` returns a `TurnResult` (defined in `agent/loop.py`; `Usage` is in `agent/messages.py`):

```python
TurnResult(final_text="The second line of notes.txt is **beta**.",
           stop_reason="done", turns=2,
           usage=Usage(prompt_tokens=821, completion_tokens=94), error=None)
```

`prompt_tokens` is 382 + 439 = 821. The first request's text was processed twice: once on its own, and again inside the second request. That's the price of a server that remembers nothing. It grows with every turn of a long session, which is what lesson 8 deals with.

#### Step 10. The answer is printed and the program ends

`_ask` prints `result.final_text`:

```
The second line of notes.txt is **beta**.
```

The `**` is Markdown bold. The model writes Markdown, and `ask` prints the raw text; lesson 7 renders it. `_ask` returns 0, `main()` returns it, and `SystemExit(0)` ends the process with exit code 0.

When the process ends, the `Agent` object and its history are gone. **Only the log file remains.** Every `ask` starts a fresh conversation. (Lesson 7's `chat` keeps one `Agent` alive between questions instead.)

#### Afterwards: reading the log

`uv run python -m agent log` runs `_log` in `agent/__main__.py`. It finds the newest file in `.agent/logs` with `latest_log`, reads it with `read_log`, and prints a summary of each request with `format_entry` (all three in `agent/log.py`). For this run:

```
[main] 2026-11-12T09:08:21.619171  0.99s  1 messages  prompt=382 completion=50  finish=tool_calls
  reasoning: The user is asking to read notes.txt and report the second line. Let me try reading the file.
  tool call M3euI7RG61SZicwVEeGrNh1XcHvZMiLS: read_file({"path":"notes.txt"})
[main] 2026-11-12T09:08:22.564440  0.945s  3 messages  prompt=439 completion=44  finish=stop
  reasoning: The user asked for the second line of notes.txt. I read the file. The second line is "beta". I should give a brief answer.
  content: The second line of notes.txt is **beta**.
```

Each block is one request. "1 messages" and "3 messages" are how long the history was when that request was sent. The reasoning shows up here, though it was never sent back to the model. The log is the only place it's kept.

#### If something goes wrong

- **LM Studio's server isn't running:** step 5 raises `openai.APIConnectionError`. Nothing in lesson 1 catches it, so you see a traceback. Lesson 3 turns it into `stop_reason == "error"` with a readable message. To fix it: `lms server start`, or the Developer tab in LM Studio.
- **The model asks for a file that doesn't exist:** `read_file` returns the *string* `Error: file not found: <path>` as the tool result. The model reads that and usually says so in its answer. It's not an exception; telling the model what went wrong is better than crashing.
- **The model asks for only part of the file:** `{"path": "notes.txt", "offset": 2, "limit": 1}` is valid, and the result is just `     2\tbeta`. The 4B model did this in testing.

#### Words used above

| Term | Meaning here |
|---|---|
| **request / reply** | One HTTP call to LM Studio and its answer. One `ask` can make several. |
| **turn** | One request plus its reply. This run had 2. |
| **history** (`self.messages`) | The list of messages so far, sent in full with every request. |
| **tool schema** | The JSON description of a tool (name, description, parameters) sent to the model so it knows the tool exists. |
| **tool call** | The model's request to run a tool: a name, an arguments string and an id. |
| **tool result** | The `role: "tool"` message the harness sends back, with the call's id. |
| **chat template** | The model's own recipe for turning messages and tools into one prompt text. A Jinja program stored in the model file. The server applies it; your code never sees it, but `lms log stream -s model --filter input,output` shows the result. |
| **special token** | A token with a fixed meaning, such as `<\|im_start\|>` (a message starts) or `<\|im_end\|>` (it ends). |
| **generation prompt** | The `<\|im_start\|>assistant` (and `<think>`) that the template puts at the end of the prompt, so the model's next words are its reply. |
| **token** | The unit models read and write; very roughly ¾ of a word. **Prompt tokens** are what the model read; **completion tokens** are what it wrote, reasoning included. |
| **`finish_reason`** | Why the model stopped: `tool_calls` (wants a tool), `stop` (finished), `length` (ran out of room). |
| **`model_dump()`** | A method on the library's reply object that converts it into plain dicts and lists, so it can be saved as JSON. |
| **closure** | A function that remembers variables from where it was defined. `read_file` remembers `ws`. |

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
