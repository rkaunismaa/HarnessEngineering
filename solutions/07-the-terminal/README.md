# Lesson 7 solution: what changed since lesson 6

This folder is the reference solution for [lesson 7](../../lessons/07-the-terminal/README.md). This page compares its `agent/` package with the one in [`solutions/06-the-system-prompt/agent/`](../06-the-system-prompt/agent/), file by file. For each change it says what the code does, why it's written that way, and what it's meant to show you.

To run this solution without touching your own `agent/` folder, run commands from inside this folder (`cd solutions/07-the-terminal`). `python -m agent` imports the `agent` package from the folder you're in. To run the lesson's tests against it: `uv run pytest lessons/07-the-terminal --impl solutions/07-the-terminal`, from the repository root.

## At a glance

| File | Lesson 6 | Lesson 7 | Status |
|---|---|---|---|
| `agent/stream.py` | | 65 lines | **new**: assembles a streamed reply into one message |
| `agent/events.py` | | 18 lines | **new**: the callbacks the loop reports progress through |
| `agent/cli.py` | | 105 lines | **new**: the interactive terminal, `python -m agent chat` |
| `agent/loop.py` | 128 lines | 200 lines | **changed**: streaming, events, and a safe stop on Ctrl-C |
| `agent/log.py` | 56 lines | 61 lines | **changed**: `format_entry` understands streamed log entries |
| `agent/__main__.py` | 113 lines | 137 lines | **changed**: the `chat` command; `ask` and `chat` share one builder |
| everything else | | | unchanged |

## What lesson 6 could do, and what it couldn't

Lesson 6's `ask` printed nothing until the whole run was over. With a 27B model on local hardware, that can be tens of seconds of blank screen, and you can't tell a slow model from a stuck one. You couldn't see which tools it was calling, and you couldn't stop it except by killing the program. Each `ask` was also a single question: there was no way to carry on a conversation.

## What this lesson is meant to show you

1. **Streaming gives the same message, in pieces.** With `stream=True`, the server sends small chunks as it generates them. You show them as they arrive, then put them back together into exactly the assistant message a normal request returns. The rest of the loop doesn't know the difference.
2. **Streamed tool calls arrive in fragments.** A call's arguments come as pieces of a JSON string, and two calls' pieces can be interleaved. They have to be joined by the call's `index`. Servers also split them differently.
3. **The loop reports; the UI decides how to show it.** The loop calls a small `events` object, and the terminal display is one implementation of it. The loop stays free of `print` calls, and tests can watch it without a screen.
4. **Stopping is easy; stopping safely isn't.** Ctrl-C can arrive anywhere. Afterwards, the history must still be one the server will accept, or every later request fails.

## File by file

### `agent/stream.py` (new): putting a streamed reply back together

`accumulate(chunks, events)` reads the chunk stream and returns `(message_dict, usage, finish_reason)`. The message has exactly the shape lesson 1's `message_to_dict` produces, so the rest of the loop can't tell the two kinds of request apart.

```python
for chunk in chunks:
    if chunk.usage:                    # arrives in a trailing chunk whose `choices` is empty
        state.usage = Usage(chunk.usage.prompt_tokens, chunk.usage.completion_tokens)
    if not chunk.choices:
        continue
    delta = chunk.choices[0].delta
    reasoning = getattr(delta, "reasoning_content", None)
    if reasoning:
        events.on_reasoning(reasoning)
    if delta.content:
        state.text.append(delta.content)
        events.on_text(delta.content)
    for tc in delta.tool_calls or []:
        call = state.calls.setdefault(tc.index, {
            "id": "", "type": "function", "function": {"name": "", "arguments": ""}})
        if tc.id:
            call["id"] = tc.id
        if tc.function:
            if tc.function.name:
                call["function"]["name"] += tc.function.name
            if tc.function.arguments:
                call["function"]["arguments"] += tc.function.arguments
    ...
```

**Why each part is there:**

- **Tool calls are kept by `index`.** The first piece of a call carries its `index`, `id` and name. Later pieces carry only the `index` and a fragment of the arguments. If there are two calls, their fragments can arrive mixed together. Keying by "the call seen last", or by `id` (which later pieces don't repeat), would mix them up.
- **Fragments are joined in arrival order.** LM Studio sent the 27B's arguments one small piece per chunk (`{`, `"path":"`, ...); Ollama sent the 4B's in one piece. This code handles both, because it never assumes how many pieces there are.
- **`getattr(delta, "reasoning_content", None)`**: reasoning isn't one of the `openai` library's declared fields, so it's read defensively. A server that doesn't send it is fine.
- **`if not chunk.choices: continue`**: usage comes in an extra last chunk with an empty `choices` list, and only if the request asks for it (`stream_options={"include_usage": True}`).
- **`content` is `None` when no text arrived**, matching non-streamed replies.
- **An interrupt keeps what arrived.** If Ctrl-C stops the stream, the exception is given the partial state as `exc.partial` before being raised again, so the loop can log what came in. It still isn't added to the history.

### `agent/events.py` (new): the callbacks

```python
class AgentEvents:
    def on_text(self, delta: str) -> None: ...
    def on_reasoning(self, delta: str) -> None: ...
    def on_tool_call(self, name: str, arguments: str) -> None: ...
    def on_tool_result(self, name: str, result: str) -> None: ...
```

Every method does nothing by default. A display overrides the ones it needs, and tests can record them. The loop always has an events object (`events or AgentEvents()`), so it never has to check for `None`. Lessons 8 and 9 add more events here (compaction, verify results).

### `agent/loop.py` (changed): streaming, events and interrupts

**One request, either way.** The loop now calls `_ask_model`, which returns `(message_dict, tool_calls, usage)` whether or not it streamed:

- **Not streaming:** `_request` as before, then `message_to_dict`.
- **Streaming:** `_request_stream` sends the same request with `"stream": True` and `"stream_options": {"include_usage": True}`, and passes the chunks to `accumulate`. The assembled tool calls are turned back into the library's own `ChatCompletionMessageToolCall` objects, so `_run_tool_call` gets the same kind of object either way.

`stream=False` is the default, so `ask` and all the earlier tests behave exactly as before. Only `chat` streams.

**Events around every tool call.** `_run_tool_call` is now a wrapper:

```python
def _run_tool_call(self, tool_call) -> str:
    fn = tool_call.function
    self.events.on_tool_call(fn.name, fn.arguments)
    result = self._execute_tool_call(tool_call)
    self.events.on_tool_result(fn.name, result)
    return result
```

`_execute_tool_call` is lesson 5's code, unchanged: the loop guard, the permission check, then `dispatch`. Splitting it out means **every** result is reported, including refusals and loop-guard errors, because the event wraps all of them.

**Ctrl-C.** The whole loop in `run` is inside `try: ... except KeyboardInterrupt:`. On an interrupt, `_repair_history` runs, and `run` returns `stop_reason="interrupted"`:

```python
def _repair_history(self) -> None:
    for i in range(len(self.messages) - 1, -1, -1):
        msg = self.messages[i]
        if msg["role"] == "assistant":
            answered = {m["tool_call_id"] for m in self.messages[i + 1:] if m["role"] == "tool"}
            for tc in msg.get("tool_calls") or []:
                if tc["id"] not in answered:
                    self.messages.append({"role": "tool", "tool_call_id": tc["id"],
                                          "content": INTERRUPTED})
            return
```

There are two cases:

- **Interrupted mid-stream.** The partial reply was never added to the history, so there's nothing to repair. The history still ends with your message (or the last tool result). The text you saw on screen stays there, but the model won't see it.
- **Interrupted while a tool ran.** The assistant message with its tool calls is already in the history, and some calls have no result yet. The server rejects any request where a tool call has no matching `tool` message, so the session would be stuck. `_repair_history` finds the last assistant message and gives every unanswered call the result `Error: interrupted by the user.`. The history is valid again, and the model knows what happened.

**Streamed log entries.** A streamed request has no single reply object to save, so `_request_stream` logs the assembled message, its usage and its finish reason under `"streamed": True`. An interrupted stream is logged too, marked `"interrupted": True`, with whatever had arrived.

### `agent/log.py` (changed): reading streamed entries

`format_entry` checks for `"streamed"` and reads the assembled message from there instead of from `choices[0]`. An interrupted request shows `finish=interrupted`. `python -m agent log` works the same for both kinds of request.

### `agent/cli.py` (new): the terminal

**`ConsoleEvents`** is the events implementation for the terminal, using `rich`:

- **Text** is printed as it arrives, with no newline, so it builds up on one line.
- **Reasoning** is printed dimmed, and can be hidden with `/reasoning`.
- **Each tool call** is one bold line: `> read_file {"path":"notes.txt"}`.
- **Each result** is shown as a short `preview`: the first 3 lines, cut at 200 characters, then `... (N more lines)`. **The model still gets the full result**; only the screen shows less.
- **`_mid_line`** tracks whether a line was left unfinished, so text, reasoning and tool lines never run together.
- **`markup=False` and `escape`** everywhere model text is printed. Text like `[bold]` or `[/]` from a model, or from a file, is shown literally instead of being treated as formatting (or crashing `rich`).

**`chat_loop(agent, events, console)`** reads a line, runs the agent on it, and repeats:

- **One `Agent` for the whole session.** Its history is kept between `run` calls (it has been since lesson 1), so each question continues the conversation.
- **Ctrl-C during a turn** interrupts that turn. The loop prints `Interrupted.` and waits for your next line. **Ctrl-C at the prompt**, end of input (Ctrl-D), `/exit` or `/quit` end the session.
- **Errors and `max_turns`** are reported in colour, and the session carries on.
- **Every turn ends with its token count**, so you can watch a long conversation get more expensive.
- **`read_input`** can be replaced, so the tests can drive a whole chat session from a list of lines.

### `agent/__main__.py` (changed): `chat`, and one builder for both commands

`_build_agent(args, **agent_kwargs)` holds what `_ask` used to do: the sandbox check, the workspace, the tools, the system prompt, the log and the permission policy. Both commands use it, so `ask` and `chat` can't drift apart. `chat` adds `events=ConsoleEvents(console)` and `stream=True`. `_add_agent_options` gives both commands the same `--root`, `--sandbox` and `--allow` options.

## What's still missing, and which lesson adds it

| Gap in this version | What goes wrong | Fixed in |
|---|---|---|
| A chat session's history grows without limit | a long session runs out of context, and the server rejects the next request | lesson 8 |
| An interrupted reply's text is thrown away | the model doesn't know what it was saying when you stopped it | not in this course (Claude Code keeps the work done so far) |
| `ask` doesn't stream | still a blank screen until the end | by design: `ask` is for scripts; use `chat` to watch |

## Seeing it work

From inside this folder:

```
uv run python ../../scripts/make_fixture.py scratch /tmp/scratch7
uv run python -m agent chat --root /tmp/scratch7
```

Ask something that takes a few tool calls ("What does calc.py print? Check by running it."). Watch the reasoning stream dimmed, each tool call appear as a line, and a short preview of each result. Then ask a follow-up that only makes sense with the history ("And what would it print with 5 added to the second list?"). Press Ctrl-C partway through a turn to see `Interrupted.`, then carry on. The lesson's README shows streamed chunks from both servers. [TESTING.md](../../lessons/07-the-terminal/TESTING.md) walks through the interrupt tests chunk by chunk.
