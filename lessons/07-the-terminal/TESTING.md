# How the lesson 7 tests work

Lesson 7 adds three things that are hard to test by hand: streaming, Ctrl-C, and a terminal UI. The tests handle each without a server, without a real keyboard and without a real terminal:

- **Streaming:** `to_chunks` turns a scripted reply into a stream of chunks. For full control, a test builds the chunks by hand.
- **Ctrl-C:** the test raises `KeyboardInterrupt` itself, from inside a tool or a chunk generator, at exactly the point it wants to test.
- **The terminal:** `rich` writes into an in-memory string instead of the screen, and your typed input comes from a list.

Against the reference solution: 29 passed, 1 skipped (the live test). There are three files: `test_stream.py`, `test_interrupt.py` and `test_chat.py`.

```
uv run pytest lessons/07-the-terminal
uv run pytest lessons/07-the-terminal --impl solutions/07-the-terminal
```

## `test_stream.py`: putting chunks back together

A `Recorder` subclass of `AgentEvents` saves every callback as a tuple, such as `("text", "Hell")` or `("tool_call", "read_file", '{"path": ...}')`. `rec.of("text")` returns just one kind. That lets a test check *what* was reported, *how many times*, and in what order.

**`accumulate` on its own**

- **`test_base_events_are_noops`**: the base class's methods exist and do nothing, so the loop can always call them.
- **`test_accumulate_text`**: "Hello there, friend" split into 4-character chunks. The message comes back whole, and `on_text` fired *more than once*. Text must be shown as it arrives, not once at the end.
- **`test_accumulate_tool_call_fragments`**: a tool call whose arguments are split into at least four fragments, like LM Studio sends them. The fragments joined must parse back into the original dict.
- **`test_accumulate_two_tool_calls_interleaved_indexes`** builds the chunks by hand so that the fragments of two calls *alternate*: index 0, index 1, index 1, index 0. Each call must still get its own arguments, keyed by `index`. Code that appends to "the last call seen" fails here.
- **`test_accumulate_reasoning_events`**: reasoning goes to `on_reasoning`, text to `on_text`, and the reasoning is *not* stored in the message, matching lesson 1.
- **`test_accumulate_first_chunk_with_role_and_reasoning_together`**: the first chunk carries both `role` and reasoning, which LM Studio really does. Code that skips the role chunk as empty loses the first piece of reasoning.
- **`test_accumulate_usage_last_chunk`**: the token counts arrive in a final chunk with `choices == []`. Your code must not index `choices[0]` on it.

**The agent in streaming mode**

- **`test_stream_agent_matches_nonstream`** is the key test. It runs the same script through two agents, one with `stream=False` and one with `stream=True`. The histories, final text, stop reason, turns and usage must all be *identical*. The request has `stream=True` and `stream_options={"include_usage": True}`. Streaming changes how the reply arrives, not what the loop does with it.
- **`test_nonstream_requests_have_no_stream_args`**: without streaming, neither key is sent.
- **`test_stream_request_carries_sampling`**: lesson 1's sampling settings are still sent when streaming.
- **`test_streamed_log_entry`**: a streamed request is logged as `{"streamed": True, "message": ..., "usage": ..., "finish_reason": ...}`, since there's no single response object to save.
- **`test_events_fire_for_tool_calls`** runs twice via `@pytest.mark.parametrize("stream", [False, True])`. Both modes report `tool_call` before `tool_result`, with the exact arguments string and result.
- **`test_events_fire_for_refused_calls`**: a call to an unknown tool still produces a `tool_result` event, so the screen shows every call, including the ones that failed.
- **`test_streamed_text_reaches_events_live`**: in a full agent run, text events arrive in pieces.

## `test_interrupt.py`: Ctrl-C without breaking the history

Here the registry has one tool, `work(tag)`. It records each tag it runs in the list `ran`, and raises `KeyboardInterrupt` when the tag equals `interrupt_on`. That simulates pressing Ctrl-C at the moment a particular call is running.

The helper `assert_valid_history` checks the rule servers enforce: every assistant message with tool calls is followed directly by one `tool` answer per call.

- **`test_interrupt_during_tool_repairs_history`**: the model asks for calls `a` and `b`, and Ctrl-C hits during `a`.
  - `run` returns `stop_reason == "interrupted"`, and `ran == ["a"]`: `b` never started.
  - Both calls get the answer `Error: interrupted by the user.` and the history is valid.
  - Then the test calls `run("try again")` on the same agent. It works, and the request it sent is valid too. This is the point of the repair: without it, every later request would be rejected.
- **`test_interrupt_keeps_results_of_calls_that_finished`**: Ctrl-C during `b` of `a, b, c`. `a` keeps its real result `ran a`; `b` and `c` get the interrupted message.
- **`test_interrupt_during_stream_drops_partial`**: the script's first item is a generator that yields four chunks of a reply and then raises `KeyboardInterrupt`. The history afterwards is just the user's message; the partial reply is thrown away. The next `run` works.
- **`test_interrupt_during_stream_is_logged`**: the cut-off request still appears in the log, marked `"interrupted": true`.

The `client.script[0] = broken()` line replaces the first scripted item with a generator after the `FakeClient` is built. `FakeClient` returns a list item as an iterator, so a generator works the same way. The generator controls exactly when the "Ctrl-C" happens.

## `test_chat.py`: the REPL without a terminal

```python
out = io.StringIO()
console = Console(file=out, width=80, force_terminal=False)
```

`rich` writes into the string `out` instead of the screen. `force_terminal=False` turns off colour codes, so the tests can search plain text.

`run_chat` passes `chat_loop` a `read_input` function that returns the next item from a list. If the item is the `KeyboardInterrupt` class, it raises it, simulating Ctrl-C at the prompt. At the end of the list it raises `EOFError`, like pressing Ctrl-D. This is why `chat_loop` takes `read_input=` as an argument: the real CLI uses the keyboard, and the tests use a list.

- **`test_preview_*`**: `preview` leaves short text alone, shows the first 3 lines of long output plus `47 more lines`, and cuts very long lines.
- **`test_chat_subcommand_is_parsed`**: `chat --root /tmp` parses.
- **`test_chat_streams_answer_and_shows_tool_call`**: input `"what is in a.txt?"`, then `/exit`. The output contains the tool call, the answer and the reasoning, and the exit code is 0.
- **`test_reasoning_toggle`**: `/reasoning` first, then a question. The reasoning text must *not* appear.
- **`test_reasoning_and_text_are_on_separate_lines`**: `"the thinking\nthe answer"`. The reasoning and the answer must not run together on one line.
- **`test_ctrl_c_at_prompt_and_eof_quit`**: Ctrl-C at the prompt exits with 0, and so does end of input.
- **`test_interrupted_turn_returns_to_prompt`**: the first request's "stream" raises `KeyboardInterrupt` immediately. The output shows `Interrupted`, the loop goes back to the prompt, and the second question gets its answer.
- **`test_format_entry_handles_streamed_entries`**: `python -m agent log` can print the new streamed log entries.

## The live test

`test_live_stream_usage` (run with `--live`) streams a one-word reply from the 27B in LM Studio. It checks that real token counts came back and at least one text event fired, and prints how many text and reasoning events arrived. Run it with `-s` to see how finely LM Studio splits a reply.
