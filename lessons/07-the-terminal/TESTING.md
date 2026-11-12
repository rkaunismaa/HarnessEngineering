# How the lesson 7 tests work

Against the reference solution: 29 passed, 1 skipped (the live test). The live test passes too with `--live` (1.3 s against the 27B). There are three test files: `test_stream.py`, `test_interrupt.py` and `test_chat.py`.

```
uv run pytest lessons/07-the-terminal
uv run pytest lessons/07-the-terminal --impl solutions/07-the-terminal
uv run pytest lessons/07-the-terminal --live -s -k live
```

## The big picture

Lesson 7 adds three things that seem impossible to test without a person at a terminal:

| Feature | The problem | What the tests do instead |
|---|---|---|
| **Streaming** | a real reply arrives as dozens of small chunks from a server | `to_chunks(reply(...))` turns a scripted reply into a chunk list, shaped like LM Studio's; some tests write chunks by hand |
| **Ctrl-C** | needs a human pressing keys at the right moment | the test raises `KeyboardInterrupt` itself, from inside a tool or a chunk generator, at exactly the moment it wants |
| **The terminal UI** | `rich` draws on a screen, input comes from a keyboard | `rich` writes into an in-memory string, and "typed" input comes from a list |

One idea makes all three possible: **events**. The loop never prints anything itself. It calls methods on an `AgentEvents` object (`on_text`, `on_reasoning`, `on_tool_call`, `on_tool_result`), and whoever owns the object decides what to do:

```
                                  ┌─> ConsoleEvents  (the real CLI: draws on the screen)
 loop ── events.on_text("Hel") ───┤
                                  └─> Recorder       (the tests: appends ("text", "Hel") to a list)
```

## What a stream looks like

This is the chunk list `to_chunks` makes from one scripted reply, with reasoning `"hmm"`, content `"Hi!"`, one `read_file` call and `text_chunk_size=5`:

```
 0: role='assistant'
 1: reasoning='hmm'
 2: content='Hi!'
 3: tool_call[index=0, id='call_1', name='read_file', arguments+='']
 4: tool_call[index=0, arguments+='{"pat']
 5: tool_call[index=0, arguments+='h": "']
 6: tool_call[index=0, arguments+='a.txt']
 7: tool_call[index=0, arguments+='"}']
 8: finish='tool_calls'
 9: choices=[]  usage=50/5
```

This is the same shape LM Studio sends:

- The **first chunk for a tool call** carries its `index`, `id` and `name` with empty arguments.
- **Later chunks for that call** carry only the `index` and a *piece* of the arguments string. No piece is valid JSON on its own.
- **The last chunk has `choices == []`** and carries only the token counts.

`accumulate(chunks, events)` must put this back together. On the reference solution it fired the events `[('reasoning', 'hmm'), ('text', 'Hi!')]` as the chunks went by, and returned:

```python
message == {"role": "assistant", "content": "Hi!",
            "tool_calls": [{"id": "call_1", "type": "function",
                            "function": {"name": "read_file", "arguments": "{\"path\": \"a.txt\"}"}}]}
usage == Usage(prompt_tokens=50, completion_tokens=5)
finish == "tool_calls"
```

That is exactly the dict `message_to_dict` would have made from a non-streamed reply, with the arguments pieces joined and reasoning left out.

## `test_stream.py`: putting chunks back together

A `Recorder` subclass of `AgentEvents` saves every callback as a tuple, such as `("text", "Hell")`, and `rec.of("text")` returns just one kind.

**`accumulate` on its own**

- **`test_base_events_are_noops`**: the base class's methods exist and do nothing, so the loop can always call them.
- **`test_accumulate_text`**: "Hello there, friend" in 4-character chunks. The message comes back whole, and `on_text` fired **more than once**: text must be shown as it arrives, not at the end.
- **`test_accumulate_tool_call_fragments`**: arguments split into at least four pieces must join back into the original dict.
- **`test_accumulate_two_tool_calls_interleaved_indexes`** builds chunks by hand so the pieces of two calls *alternate*: index 0, 1, 1, 0. Each call must still get its own arguments, keyed by `index`. Code that appends to "the last call seen" fails here.
- **`test_accumulate_reasoning_events`**: reasoning goes to `on_reasoning`, and isn't stored in the message.
- **`test_accumulate_first_chunk_with_role_and_reasoning_together`**: LM Studio really does put `role` and the first reasoning piece in one chunk. Code that skips "the role chunk" loses that piece.
- **`test_accumulate_usage_last_chunk`**: the token counts are in a chunk with `choices == []`. Indexing `choices[0]` on it crashes.

**The agent in streaming mode**

- **`test_stream_agent_matches_nonstream`** is the key test. The same script runs through two agents, one with `stream=False` and one with `stream=True`. Their histories, final text, stop reason, turns and usage must be **identical**. The streamed request also has `stream=True` and `stream_options={"include_usage": True}`. Streaming changes how the reply arrives, never what the loop does with it.
- **`test_nonstream_requests_have_no_stream_args`**: without streaming, neither key is sent.
- **`test_stream_request_carries_sampling`**: lesson 1's sampling settings are still sent when streaming.
- **`test_streamed_log_entry`**: a streamed request is logged as `{"streamed": True, "message": ..., "usage": ..., "finish_reason": ...}`, since there's no single reply object to save.
- **`test_events_fire_for_tool_calls`** runs twice (`stream` False and True): `tool_call` fires before `tool_result`, with the exact arguments and result.
- **`test_events_fire_for_refused_calls`**: an unknown tool still produces a `tool_result` event, so the screen shows every call, including failed ones.
- **`test_streamed_text_reaches_events_live`**: in a full agent run, text events arrive in pieces.

## One test, step by step: `test_interrupt_during_tool_repairs_history`

The tool in `test_interrupt.py` is `work(tag)`. It records each tag in the list `ran`, and raises `KeyboardInterrupt` when the tag equals `interrupt_on`. That's "you pressed Ctrl-C while this particular call was running".

```python
def test_interrupt_during_tool_repairs_history():
    tools, ran = make_tools(interrupt_on="a")
    client = FakeClient([
        reply(tool_calls=[call("work", {"tag": "a"}), call("work", {"tag": "b"})]),
        reply(content="recovered"),
    ])
    agent = Agent(client, "m", tools)
    result = agent.run("go")
```

**The first `run`.** The reply asks for `work(a)` and `work(b)`. The assistant message goes into the history, then `work(a)` starts and raises `KeyboardInterrupt`. At that moment the history ends with an assistant message holding **two calls and no answers**, the exact state lesson 1 showed the server rejects with a 400.

The solution catches the interrupt, adds the missing answers, and returns `stop_reason == "interrupted"`. `ran == ['a']`, so `b` never started. The history afterwards:

```json
{"role": "user", "content": "go"}
{"role": "assistant", "content": null, "tool_calls": [{"id": "call_1", ... "work" {"tag": "a"}}, {"id": "call_2", ... "work" {"tag": "b"}}]}
{"role": "tool", "tool_call_id": "call_1", "content": "Error: interrupted by the user."}
{"role": "tool", "tool_call_id": "call_2", "content": "Error: interrupted by the user."}
```

Both calls are answered, so the history is valid again, and the model will see what happened.

**The second `run`.** `agent.run("try again")` sends messages with roles `['user', 'assistant', 'tool', 'tool', 'user']`, which the server accepts, and returns `done` with `"recovered"`.

The test checks each of these:

```python
    assert result.stop_reason == "interrupted"
    assert ran == ["a"]                                      # the second call never ran
    assert [(m["tool_call_id"], m["content"]) for m in tool_messages(agent.messages)] == [
        ("call_1", INTERRUPTED), ("call_2", INTERRUPTED)]
    assert_valid_history(agent.messages)                     # every call answered
    result = agent.run("try again")
    assert result.stop_reason == "done" and result.final_text == "recovered"
    assert_valid_history(client.requests[1]["messages"])     # and what was sent is valid too
```

`assert_valid_history` checks the server's rule directly: every assistant message with tool calls is followed by one `tool` answer per call.

The other interrupt tests:

- **`test_interrupt_keeps_results_of_calls_that_finished`**: Ctrl-C during `b` of `a, b, c`. `a` keeps its real result `ran a`; `b` and `c` get the interrupted message.
- **`test_interrupt_during_stream_drops_partial`**: the scripted "reply" is a generator that yields four chunks, then raises `KeyboardInterrupt`. Afterwards the history is just the user message, with the half-received reply thrown away, and the next `run` works.
- **`test_interrupt_during_stream_is_logged`**: the cut-off request is still in the log, with `"interrupted": true`.

`client.script[0] = broken()` replaces the first scripted item with that generator. `FakeClient` returns a list item as an iterator, so a generator works the same way, and the generator decides exactly when the "Ctrl-C" happens.

## `test_chat.py`: the REPL without a terminal

```python
out = io.StringIO()
console = Console(file=out, width=80, force_terminal=False)
```

`rich` writes into the string `out` instead of the screen. `force_terminal=False` turns off colour codes, so the tests can search plain text.

`run_chat` passes `chat_loop` a `read_input` function that returns the next item from a list:

- **a string** is a line you "typed";
- **the `KeyboardInterrupt` class** is raised, which is Ctrl-C at the prompt;
- **the end of the list** raises `EOFError`, which is Ctrl-D.

That's why `chat_loop` takes `read_input=`: the real CLI uses the keyboard, and the tests use a list.

- **`test_preview_*`**: `preview` leaves short text alone, shows 3 lines of long output plus `47 more lines`, and cuts very long lines.
- **`test_chat_subcommand_is_parsed`**: `chat --root /tmp` parses.
- **`test_chat_streams_answer_and_shows_tool_call`**: you type a question, then `/exit`. The output contains the tool call, the answer and the reasoning, and the exit code is 0.
- **`test_reasoning_toggle`**: `/reasoning` first, then a question; the reasoning text must *not* appear.
- **`test_reasoning_and_text_are_on_separate_lines`**: the output contains `"the thinking\nthe answer"`. Reasoning and answer mustn't run together on one line.
- **`test_ctrl_c_at_prompt_and_eof_quit`**: Ctrl-C at the prompt and end of input both exit with 0.
- **`test_interrupted_turn_returns_to_prompt`**: the first request's stream raises at once. The output shows `Interrupted`, the loop goes back to the prompt, and the second question gets its answer.
- **`test_format_entry_handles_streamed_entries`**: `python -m agent log` can print streamed log entries.

## The live tests

`test_live_stream_usage` (run with `--live`) streams a one-word reply from the 27B and checks that real token counts came back. On 2026-11-12:

```
stop=done usage=Usage(prompt_tokens=1129, completion_tokens=26) text='pong' text events=1 reasoning events=21
```

The model produced 21 reasoning pieces and then the answer `pong` in one piece. That's why reasoning is shown dimmed as it streams: on a short answer, most of the waiting is thinking. (`-k live` also selects `test_streamed_text_reaches_events_live`, an ordinary fake-model test with "live" in its name; it doesn't need a server.)

## If a test fails

- **`test_stream_agent_matches_nonstream` fails:** print both `agent.messages` lists and compare. The usual difference is `content` being `""` in one and `None` in the other, or a missing `tool_calls` key.
- **An interleaved-index test fails:** key the calls being assembled by `delta.tool_calls[i].index`, not by arrival order.
- **An interrupt test leaves an unanswered call:** catch `KeyboardInterrupt` around the tool loop, and answer every call that has no result yet.
- **A chat test hangs:** your `chat_loop` reads input some way other than `read_input`.

## Words used above

| Term | Meaning here |
|---|---|
| **streaming** | Receiving a reply in pieces as it's generated (`stream=True`). |
| **chunk / delta** | One piece of a stream; `delta` holds what's new in it. |
| **`index`** | Which tool call a delta belongs to, when a reply has several. |
| **events** | The `AgentEvents` callbacks the loop calls instead of printing. |
| **`KeyboardInterrupt`** | The exception Python raises when you press Ctrl-C. |
| **REPL** | Read-eval-print loop: the `chat` prompt that reads a line, answers, and repeats. |
| **`StringIO`** | An in-memory text file; `rich` writes into it in the tests. |
| **generator** | A function with `yield` that produces values one at a time, and can raise partway through. |
