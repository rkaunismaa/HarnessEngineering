# Lesson 7: The terminal

Start from your lesson 6 code, or copy `solutions/06-the-system-prompt/agent` into `agent/`.

## Why this exists

`ask` prints nothing until the whole run is over. With a 27B model on local hardware that can be tens of seconds of a blank screen, and you cannot tell a slow model from a stuck one. This lesson makes the agent visible and stoppable:

- **Streaming.** With `stream=True` the server sends the reply in small chunks as it generates them. You show text (and the model's reasoning) as it arrives, and you assemble the chunks into the same assistant message you would have received in one piece.
- **Events.** The loop reports what it is doing through a small callback object, so the terminal UI is separate from the loop and tests can watch the loop without a screen.
- **Interrupts.** A person must be able to stop a turn that is going the wrong way. Stopping is easy; leaving the conversation in a state the server will accept afterwards is the part that needs care.

### Streamed tool calls

A streamed reply is a sequence of chunks, each with a `delta`. Text arrives as `delta.content` pieces. Reasoning, on servers that send it, arrives as `delta.reasoning_content` (an extra attribute, not part of the SDK's declared fields, so read it with `getattr`). Tool calls are the tricky part:

- The first delta for a call carries its `index`, `id` and `function.name`, with empty `arguments`.
- Later deltas for that call carry only the `index` and a **fragment** of the arguments string. Concatenate the fragments in arrival order; the result is the JSON string.
- Two calls in one reply have different `index` values. Fragments may interleave, so key everything by `index`, never by "the call I saw last", and never by `id` (fragments do not repeat it).
- Servers differ. Observed on the same prompt: LM Studio (27B) sent one `{` / `"path":"` / `.` / `"` / `}` fragment per chunk; Ollama (4B) sent the whole arguments string in a single delta. Code that works for one and not the other is wrong.

Observed from LM Studio 0.4.27:

- Usage arrives only if you ask for it with `stream_options={"include_usage": True}`, in an extra trailing chunk whose `choices` is `[]`. The chunk before it carries `finish_reason`. So guard `if chunk.choices` before indexing, and read `chunk.usage` from any chunk. A live run returned `prompt_tokens=1129, completion_tokens=25` for a one-word reply, so the agent does not need to estimate in streaming mode. (Lesson 8 still needs estimates for the request it has not sent yet.)
- The first chunk can carry `role` together with the first `reasoning_content` delta. Do not assume the role chunk is empty.
- Tool-only replies have content `""`, not `None`. Treat both as "no text".

### After an interrupt

Ctrl-C raises `KeyboardInterrupt` in your code, wherever it happens to be: mid-stream, mid-tool, or between the two. The history must be valid for the next request:

- **Mid-stream.** The reply was never added to the history. Drop what arrived. (The text on screen stays on screen; the model will not see it.) The user's message is still in the history.
- **Mid-tool.** The assistant message with its tool calls is already in the history, and some of its calls have results and some do not. Chat servers require every `tool_call_id` in an assistant message to be answered by a `tool` message before the next non-tool message. If one is missing, the next request is rejected or the chat template misbehaves, and the session is stuck with a poisoned history. So every call without a result gets `{"role": "tool", "tool_call_id": id, "content": "Error: interrupted by the user."}`. The model then also knows what happened.

## How Claude Code does it

- **Documented** ([Interactive mode, keyboard shortcuts](https://code.claude.com/docs/en/interactive-mode), checked): `Esc` is "Interrupt Claude": it stops "the current response or tool call mid-turn so you can redirect. Claude keeps the work done so far." `Ctrl+C` "interrupts a running operation"; with nothing running the first press clears the prompt input and a second press exits. Your harness differs slightly: Ctrl-C at the prompt quits at once, and it keeps no work from an interrupted reply.
- **Observed**: Claude Code shows each tool call and its result as it happens, and collapses long outputs rather than printing them in full. Your `preview` does the same for results (first few lines plus "N more lines"). The model still receives the full result.

## What you'll build

New: `agent/events.py`, `agent/stream.py`, `agent/cli.py`. Changed: `agent/loop.py`, `agent/log.py`, `agent/__main__.py`. Tests: `lessons/07-the-terminal/tests/`.

**`AgentEvents`** (`events.py`): a base class whose methods do nothing: `on_text(delta: str)`, `on_reasoning(delta: str)`, `on_tool_call(name: str, arguments: str)`, `on_tool_result(name: str, result: str)`. `arguments` is the raw JSON string.

**`accumulate(chunks, events) -> (message, usage, finish_reason)`** (`stream.py`): consume an iterable of `ChatCompletionChunk`. `message` has the shape `message_to_dict` produces (`role`, `content`, and `tool_calls` only when there are some; no reasoning). `content` is `None` when no text arrived. `usage` is a `Usage` or `None` if no chunk carried it. Tool calls are assembled by `index` and returned in index order. Call `on_text` / `on_reasoning` once per delta, as it arrives.

**`Agent(..., events: AgentEvents | None = None, stream: bool = False)`**:

- `stream=True` adds `stream=True, stream_options={"include_usage": True}` to the request and uses `accumulate`. `TurnResult.usage` is filled from the streamed usage. With `stream=False` nothing changes. The same script must give the same `agent.messages` either way.
- `on_tool_call` fires before each call is handled and `on_tool_result` after, in both modes, including for calls that are refused (denied, unknown tool, loop guard).
- The log's `response` for a streamed request is `{"streamed": True, "message": ..., "usage": ..., "finish_reason": ...}`. If the stream is interrupted, it is logged with whatever had arrived and `"interrupted": True`. Update `format_entry` so `python -m agent log` can print streamed entries.
- `KeyboardInterrupt` while streaming or while a tool runs makes `run` return `stop_reason == "interrupted"` after repairing the history as above. Do not install your own signal handler; the default behavior of Ctrl-C is what you want. The next `run` works.

**`python -m agent chat [--root DIR] [--sandbox/--no-sandbox] [--allow RULE]`** (`cli.py`, `__main__.py`): a REPL built with `rich`.

- Streams text as it arrives; shows reasoning dimmed (`/reasoning` toggles it); puts reasoning, text and tool lines on separate lines.
- Prints each tool call, then a short preview of its result.
- Ctrl-C during a turn interrupts that turn and returns to the prompt. Ctrl-C at the prompt, end of input, or `/exit` quits.
- `ask` and `chat` share the same agent setup (sandbox, permissions, system prompt, log).
- Provide `preview(text, max_lines=3, max_chars=200)`, `ConsoleEvents(console)` and `chat_loop(agent, events, console, read_input=None)` so the loop can be tested with scripted input.

## Tests

```
uv run pytest lessons/07-the-terminal                   # against your agent/
uv run pytest lessons/07-the-terminal --impl solutions/07-the-terminal
```

The tests use `to_chunks` from `testing/fake_model.py` to turn a scripted reply into a chunk stream, and raise `KeyboardInterrupt` from a tool function or a chunk iterator to simulate Ctrl-C. `test_live_stream_usage` needs `--live`.

## Try it live

```
uv run python -m agent chat --root .
```

Ask something that needs a tool, for example "read nums.txt and tell me the last line" in a directory with a 300-line `nums.txt`. What was seen with the 27B: the reasoning scrolls by dimmed first, then `> list_files {}` with a three-line preview and "(3 more lines)", then `> read_file {...}` with "... (297 more lines)", then the answer. Type `/reasoning` and ask again to hide the reasoning. Ask for a long essay and press Ctrl-C after a couple of seconds: you get `Interrupted.` and a fresh prompt, and the next question works. (Tested without a terminal by sending a real SIGINT two seconds into a live stream: `run` returned `interrupted`, the history held only the user message, and the following `run` returned "Hello.".) Whether the server stops generating when the client disconnects is up to the server; this was not checked.

## Break it

In `accumulate`, change the arguments handling from appending (`+=`) to assigning (`=`) each delta's arguments. Run the tests: `test_accumulate_tool_call_fragments` fails. Then think about why Ollama with the 4B would have kept working: it sends the whole arguments string in one delta (see above), so assigning gives the right answer. LM Studio with the 27B sends the string in fragments, so you end up with only the last fragment (`}`), which is not valid JSON, and the tool call comes back as an `Error: arguments were not valid JSON` result. A bug that only appears on one server is the reason the fake splits arguments into fragments.

## Extras

- Show a running token count while streaming from the usage chunk.
- Save and resume a session from the log.
- Render the final answer as markdown once it is complete.
- Handle a second Ctrl-C within a second as "quit".
