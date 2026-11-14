# Lesson 1 solution: what changed since lesson 0

This folder is the reference solution for [lesson 1](../../lessons/01-the-loop/README.md). This page compares its `agent/` package with the one in [`solutions/00-setup/agent/`](../00-setup/agent/), file by file. For each change it says what the code does, why it's written that way, and what it's meant to show you.

To run this solution without touching your own `agent/` folder, run commands from inside this folder (`cd solutions/01-the-loop`). `python -m agent` imports the `agent` package from the folder you're in. To run the lesson's tests against it: `uv run pytest lessons/01-the-loop --impl solutions/01-the-loop`, from the repository root.

## At a glance

| File | Lesson 0 | Lesson 1 | Status |
|---|---|---|---|
| `agent/__init__.py` | 1 line | 1 line | unchanged |
| `agent/config.py` | 67 lines | 67 lines | unchanged |
| `agent/client.py` | 61 lines | 61 lines | unchanged |
| `agent/__main__.py` | 37 lines | 72 lines | **changed**: adds the `ask` and `log` commands |
| `agent/loop.py` | | 64 lines | **new**: the agent loop |
| `agent/messages.py` | | 29 lines | **new**: turning replies into history entries; adding up token counts |
| `agent/tools/registry.py` | | 42 lines | **new**: what a tool is, and running one by name |
| `agent/tools/files.py` | | 33 lines | **new**: the `read_file` tool |
| `agent/tools/__init__.py` | | 14 lines | **new**: the default set of tools |
| `agent/workspace.py` | | 13 lines | **new**: the folder the agent works in |
| `agent/log.py` | | 56 lines | **new**: the request log, and printing it |

About 250 new lines in all, and nothing from lesson 0 was rewritten.

## What lesson 0 could do, and what it couldn't

Lesson 0 proved one thing: the model *can ask* for a tool. `smoke_test` (`agent/client.py`) sends one request with a `read_file` schema and checks that the reply contains a well-formed `read_file` call. Then it stops. Nothing reads the file, nothing tells the model what the file says, and the model never gives an answer.

That's the gap lesson 1 fills. **A model can't do anything by itself.** It can only write a message that says "please call `read_file` with these arguments". Something has to notice that request, run the function, send the result back, and ask the model again, over and over, until it answers in plain text. That something is the **loop**, and it's the core of every agent harness. Every later lesson in this course adds to it.

```
 lesson 0:   you ──> one request ──> model: "call read_file(notes.txt)"   ──> stop. Nobody runs it.

 lesson 1:   you ──> request ──> model: "call read_file(notes.txt)"
                                   │
                     harness runs read_file, adds the result to the history
                                   │
                     request again (the whole history) ──> model: "The second line is beta."  ──> print it
```

## What this lesson is meant to show you

Each new file exists to make one of these ideas concrete:

1. **The harness does the work; the model only asks.** The model never touches your files. `read_file` runs in your Python process, and the model only ever sees its *description* (the schema) and its *result* (a string).
2. **The server remembers nothing.** Every request sends the whole conversation again. The history lives in your program, in `Agent.messages`, and the token counts grow with every request.
3. **The message format is a contract.** Every tool call has an `id`, and its result must come back in a `tool` message carrying that same id. Leave one out, and the server rejects the next request with a `400`.
4. **What you send isn't all the server returns.** Replies carry extra fields, notably the model's thinking (`reasoning_content`). The harness chooses what to keep in the history (not the thinking) and what to keep in the log (everything).
5. **You need to be able to see what happened.** Every request and reply goes into a log file, and `python -m agent log` prints it in a readable form. When a model does something strange, the log is where you look first.

## File by file

### `agent/loop.py` (new): the loop

This is the heart of the lesson. It contains `TurnResult` and `Agent`.

```python
def run(self, user_message: str) -> TurnResult:
    self.messages.append({"role": "user", "content": user_message})
    usage = Usage()
    turns = 0
    while True:
        completion = self._request()
        turns += 1
        if completion.usage:
            usage += Usage(completion.usage.prompt_tokens, completion.usage.completion_tokens)
        message = completion.choices[0].message
        self.messages.append(message_to_dict(message))
        if not message.tool_calls:
            return TurnResult(message.content or "", "done", turns, usage)
        for tc in message.tool_calls:
            self.messages.append({"role": "tool", "tool_call_id": tc.id,
                                  "content": self._run_tool_call(tc)})
```

**What it does:** add your message to the history, then repeat: send everything, store the reply, and stop if the reply has no tool calls. Otherwise run each tool call and store each result, then go round again.

**Why it's written this way:**

- **`self.messages` belongs to the `Agent`, not to `run`.** The history outlives one call to `run`, so a second `run` continues the same conversation. That's what lets later lessons build an interactive chat (lesson 7) on the same class.
- **The stop condition is "no tool calls", not `finish_reason == "stop"`.** A reply that has tool calls always needs its tools run, whatever else it says. Checking the calls themselves is the simplest rule that's always right. `if not message.tool_calls` treats both `None` and `[]` as "none", because different servers send different ones.
- **Every call in a reply is run, in order.** A model can ask for several tools at once. Each one gets its own `tool` message with its own `tool_call_id`, which is the only way the server can pair results with calls.
- **`message.content or ""`** because a final reply's content can be `None` on some servers. `TurnResult.final_text` is always a string.
- **Token usage is summed across requests.** It shows the cost of re-sending the history: the second request's prompt is bigger than the first's, because it carries the whole first exchange again.

**`_request` and `_run_tool_call` are separate methods** on purpose. The README asks for them because later lessons hook in exactly there:

| Method | What it does in lesson 1 | What later lessons add there |
|---|---|---|
| `_request` | builds the request, calls `client.chat.completions.create`, logs it | error handling (3), streaming (7), compacting the history when it's too long (8) |
| `_run_tool_call` | `self.tools.dispatch(name, arguments)` | the repeated-call guard (3), the permission check and approval prompt (5) |

**Fields that aren't used yet:** `TurnResult.error` is always `None`, and `stop_reason` is always `"done"`. Lesson 3 adds `"max_turns"` and `"error"`. The `system` argument to `Agent` is accepted but nothing passes it; lesson 6 builds the system prompt. They're in the shape now so later lessons can fill them in without changing every caller and test.

### `agent/messages.py` (new): what goes into the history

```python
def message_to_dict(msg) -> dict:
    out: dict = {"role": "assistant", "content": msg.content}
    if msg.tool_calls:
        out["tool_calls"] = [
            {"id": tc.id, "type": "function",
             "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
            for tc in msg.tool_calls
        ]
    return out
```

**What it does:** turns the `openai` library's reply object into a plain dict holding only `role`, `content` and (when there are any) `tool_calls`.

**Why:**

- **The reasoning is left out deliberately.** Qwen models put their thinking in `reasoning_content`. Sending it back on every later request would cost prompt tokens in a 32K window, and the Qwen3 model card advises leaving it out. It's not lost: the log keeps the full reply.
- **The library's object carries many other fields** (`refusal`, `audio`, `function_call`, and more), mostly empty. Copying only what the API needs keeps the history small, easy to read, and safe to turn into JSON for the log and the tests.
- **`content` is kept exactly as sent** (`None` or `""`), not cleaned up. The history should record what the server said.
- **`"tool_calls"` is only added when there are some.** A plain answer then looks like every other assistant message, `{"role": "assistant", "content": "..."}`, which is what the tests expect.

`Usage` is a small frozen dataclass with `+`, so the loop can write `usage += Usage(...)`.

### `agent/tools/registry.py` (new): what a tool is

```python
@dataclass
class Tool:
    name: str
    description: str
    parameters: dict  # JSON schema
    fn: Callable[..., str]
    read_only: bool = False
```

A `Tool` puts the two halves of a tool side by side: what the **model** sees (`name`, `description`, `parameters`) and what the **harness** runs (`fn`). `ToolRegistry` holds tools by name:

- **`schemas()`** builds the `tools` list sent with every request, in the format the API expects. Lesson 0's `READ_FILE_TOOL` was this same structure, written out by hand.
- **`dispatch(name, raw_arguments)`** finds the tool, turns the arguments string into a dict with `json.loads`, and calls `fn(**args)`. The model sends arguments as JSON *text*, not a dict, so `dispatch` has to parse it. Lesson 0's `smoke_test` did the same check by hand.

**Why a registry, not a bare function:** the loop doesn't need to know which tools exist. Lesson 2 adds three more tools and the loop doesn't change at all. `read_only` isn't used yet; lesson 5's permission policy uses it to let reading tools run without asking you.

**Deliberately naive for now:** `dispatch` trusts the model. Bad JSON, or a parameter `fn` doesn't accept, raises an exception that ends the whole run. Lesson 3 makes `dispatch` never raise, turning every problem into an `Error: ...` string the model can read and fix. An unknown tool name already returns an error string here, because that one was easy.

### `agent/tools/files.py` (new): `read_file`

```python
def make_read_file(ws: Workspace) -> Tool:
    def read_file(path: str, offset: int = 1, limit: int = 2000) -> str:
        p = ws.resolve(path)
        if not p.is_file():
            return f"Error: file not found: {path}"
        lines = p.read_text().splitlines()
        start = max(offset, 1) - 1
        chosen = lines[start:start + limit]
        return "\n".join(f"{n:>6}\t{line}" for n, line in enumerate(chosen, start + 1))
    ...
```

**What it does:** returns the file's lines, numbered like `cat -n` (`     2\tbeta`), optionally just part of the file.

**Why:**

- **A closure over `ws`.** `make_read_file` builds the function, which remembers the workspace it was made with. The model sends only `path`; it never has to know (or choose) the project folder.
- **Line numbers** let the model say "line 2" and later read just part of a file. That matters once files are long, and in lesson 4, when the model needs to point at exactly what to edit.
- **`offset` and `limit`** let a large file be read in pieces instead of all at once. Every result is re-sent on every later request, so a whole file costs tokens over and over.
- **A missing file returns a string, not an exception.** The model reads `Error: file not found: ...` and can try another path. This is the first example of the rule lesson 3 makes general: an error is a tool result.
- **The schema is richer than lesson 0's.** The smoke test's `READ_FILE_TOOL` had only `path`, and is still used unchanged by `smoke`. The real tool also describes `offset` and `limit`, and says that it returns numbered lines, because the description is all the model learns about the tool.

**Deliberately naive for now:** no limit on output size (lesson 2 adds `truncate`), no error for non-UTF-8 files (lesson 2), and paths aren't kept inside the project (lesson 5).

### `agent/tools/__init__.py` (new): the default tool set

```python
def make_default_tools(ws: Workspace, **kwargs) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(make_read_file(ws))
    return registry
```

One place that decides which tools the agent has. It's a single tool today. `**kwargs` is accepted and ignored so that later lessons can add options here (`confirm_bash` in lesson 2, `client` and `model` for the subagent in lesson 10) without breaking code that calls it the lesson 1 way.

### `agent/workspace.py` (new): the project folder

```python
class Workspace:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def resolve(self, path: str) -> Path:
        return self.root / path
```

**What it does:** remembers the folder the agent works in (`--root`), as an absolute path, and joins the model's relative paths onto it.

**Why a class for two lines:** every file tool needs the same root, and later lessons hang more state on it: the read tracker (lesson 4), the sandbox settings and the "stay inside the project" check (lesson 5), and the to-do list (lesson 9). Passing one `Workspace` around now means none of those later changes touch the tools' signatures.

**Deliberately naive for now:** `resolve` doesn't stop `../` or absolute paths from reaching outside the project. Lesson 5 makes it refuse them.

### `agent/log.py` (new): the request log

`RequestLog.record` appends one line of JSON per request: the time, the agent's name, the duration, exactly what was sent (`request`, the keyword arguments given to `create`), and the full reply (`completion.model_dump()`, reasoning included). `for_session` names a new file after the current time in `config.log_dir` (`.agent/logs/` by default). `read_log`, `latest_log` and `format_entry` read the file back and summarise each line.

**Why:**

- **Your program is the only place the full conversation exists.** The server keeps nothing, so if you don't record it, it's gone. When a run goes wrong, the log answers "what did the model see, and what did it say?"
- **JSON Lines (one object per line)** can be appended to without reading the file, and survives a crash partway through a run.
- **The full reply goes in the log, not just the history's version.** The reasoning that `message_to_dict` drops is exactly what you want to read when you're working out why the model did something.
- **`with_agent(name)`** writes to the same file under a different label. Lesson 1 only has `main`. Lesson 10's subagents use it, so one file shows parent and helper requests in order.

### `agent/__main__.py` (changed): two new commands

`smoke` is unchanged. Two subcommands are added:

```python
def _ask(args) -> int:
    config = load_config()
    agent = Agent(make_client(config), config.model,
                  make_default_tools(Workspace(Path(args.root))),
                  log=RequestLog.for_session(config.log_dir), sampling=config.sampling())
    result = agent.run(args.prompt)
    print(result.final_text)
    return 0
```

- **`python -m agent ask "<prompt>" [--root DIR]`** connects all the new pieces: the client and config from lesson 0, the workspace, the tools, a fresh session log, and the `Agent`. Then it runs the prompt and prints the answer. `sampling=config.sampling()` passes on the `temperature`, `top_p` and `seed` settings that lesson 0's `Config` already had. An empty dict sends nothing, so the server's defaults apply.
- **`python -m agent log [PATH]`** prints `format_entry` for each line of a log, the latest one by default. It uses `rich` with `markup=False`, so text like `[main]` or a model's `[bold]` is printed literally rather than treated as formatting.

**Deliberately naive for now:** `_ask` always exits with `0`. If the server is down, the run raises and you get a traceback. Lesson 3 adds `stop_reason == "error"` and exit status 1.

### Unchanged: `config.py`, `client.py`, `__init__.py`

Lesson 0 already had everything the loop needs from them: `load_config` for the server address, model name, log folder and sampling settings, and `make_client` for the `openai` client. Building the loop on top of them, without changing them, shows that lesson 0's job (talking to the server) and lesson 1's job (running a conversation) are separate.

## What's still missing, and which lesson adds it

The lesson 1 solution is the smallest loop that works. These gaps are deliberate, so that each one can be seen on its own when a later lesson fixes it:

| Gap in this version | What goes wrong | Fixed in |
|---|---|---|
| Only one tool | the model can't list files, search, or run anything | lesson 2 |
| No cap on tool output | one huge file fills the context window | lesson 2 |
| `dispatch` raises on bad arguments | one malformed call ends the session with a traceback | lesson 3 |
| `while True:` with no limit | a model that keeps calling tools keeps the loop going forever | lesson 3 |
| A server error is a traceback | `ask` crashes instead of reporting the error | lesson 3 |
| No way to change files | — | lesson 4 |
| Paths can leave the project; no permissions | the model can read anything your user account can | lesson 5 |
| No system prompt | the model knows nothing about its job or the project | lesson 6 |
| The history grows without limit | long sessions run out of context | lesson 8 |

## Seeing it work

From inside this folder:

```
mkdir -p /tmp/scratch1 && printf 'alpha\nbeta\ngamma\n' > /tmp/scratch1/notes.txt
uv run python -m agent ask "Read notes.txt and tell me the second line." --root /tmp/scratch1
uv run python -m agent log
```

The log shows two requests: one ending in a `read_file` call (`finish=tool_calls`), and one ending in the answer (`finish=stop`), with the prompt tokens higher the second time. The lesson's README walks through that exact run [step by step](../../lessons/01-the-loop/README.md#what-happens-when-you-run-ask-step-by-step), including what LM Studio's chat template turns each request into. [TESTING.md](../../lessons/01-the-loop/TESTING.md) shows how the tests drive this loop with a scripted fake model, with no server at all.
