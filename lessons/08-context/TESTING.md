# How the lesson 8 tests work

Against the reference solution: 20 passed, 1 skipped (the live test). The live test passes too with `--live` (0.6 s against LM Studio).

```
uv run pytest lessons/08-context
uv run pytest lessons/08-context --impl solutions/08-context
uv run pytest lessons/08-context --live -s -k live
```

## Where the code lives

Every function and class this walkthrough names is defined in one of the files below. Paths under `agent/` are relative to your own package; the reference versions are the same files under `solutions/08-context/agent/`.

| File | What's in it that this walkthrough uses |
|---|---|
| `agent/cli.py` | `ConsoleEvents.on_compact` |
| `agent/context.py` | `compact`, `ContextManager`, `ContextManager.needs_compaction`, `error_text`, `estimate_tokens`, `is_context_overflow`, `split_index`, `trim_old_tool_results` |
| `agent/events.py` | `AgentEvents.on_compact` |
| `agent/loop.py` | `Agent.run` |
| `agent/tools/files.py` | `read_file` (defined inside `make_read_file`) |

The test helpers come from:

| File | Helpers used |
|---|---|
| `testing/fake_model.py` | `call`, `FakeClient`, `reply` |

<details><summary>Which test file each test is in</summary>

| Test file | Tests |
|---|---|
| `lessons/08-context/tests/test_context.py` | 21 tests: `test_agent_compacts_when_over_threshold`, `test_agent_trims_old_tool_results_permanently`, `test_agent_without_context_never_compacts`, `test_compact_keeps_tool_pairs`, `test_compact_merges_into_user_message`, `test_compact_shape`, `test_compact_with_nothing_to_summarize_makes_no_call`, `test_compact_without_system_message`, `test_console_events_print_compaction`, `test_context_overflow_retry`, `test_context_overflow_twice_errors`, `test_error_text_does_not_repeat_the_body`, `test_estimate_tokens`, `test_live_overflow_message`, `test_needs_compaction_uses_usage_then_estimate`, `test_other_bad_requests_are_not_retried`, `test_overflow_is_detected_in_the_body_not_just_str`, `test_overflow_without_context_manager_is_an_error`, `test_split_never_on_tool_message`, `test_streaming_usage_feeds_the_manager`, `test_trim_keeps_recent_and_small` |

</details>

## The big picture

The model can only read so much at once: 32,768 tokens with this course's LM Studio setup. Every request sends the whole history (lesson 1), so a long session eventually doesn't fit. Lesson 8 shrinks the history in two ways:

1. **Trimming.** Old, large tool results are replaced with a one-line note, such as `[old tool result removed: 1000 characters]`. This is cheap, needs no model, and is done before every request.
2. **Compacting.** When the history is near the limit, the older part is sent to the model with a request to summarize it. The summary then replaces that part.

The tests never fill a real 32K window. Instead they:

- **build long conversations out of plain dicts** (`convo(...)`);
- **use a tiny window**, such as `ContextManager(1000)`, so a scripted reply claiming `prompt_tokens=900` counts as "nearly full";
- **script the summary**: the summarization request is just another `FakeClient` request, so one script can include it in the middle of a run.

## The made-up conversation

```python
def convo(n_pairs=6, big="x" * 1000):
    """system, then n_pairs of (user, assistant-with-tool-call, tool result)."""
```

`convo(5)` is 16 messages. Its roles by index (s = system, u = user, a = assistant, t = tool):

```
0:s  1:u 2:a 3:t  4:u 5:a 6:t  7:u 8:a 9:t  10:u 11:a 12:t  13:u 14:a 15:t
```

Each tool result is 1,000 `x` characters, and the whole thing estimates at 1,562 tokens. The pattern is fixed, so tests can work out which index holds which role. `summary_reply()` is a scripted reply whose content is `SUMMARY TEXT`.

## The building blocks, with real output

**`estimate_tokens(messages)`** is `ceil(len(json.dumps(messages)) / 4)`, about four characters per token. `test_estimate_tokens` pins that formula. It's rough, but it only has to answer "are we near the limit?" for a request that hasn't been sent yet.

**`trim_old_tool_results(messages, keep_recent=6, min_chars=500)`.** On `convo(5)`, the reference solution kept the last 6 messages and replaced the three older tool results:

```
system, user, assistant, [old tool result removed: 1000 characters],
user, assistant, [old tool result removed: 1000 characters],
user, assistant, [old tool result removed: 1000 characters],
user, assistant, xxxx...(1000),   user, assistant, xxxx...(1000)      <- last 6, untouched
```

`test_trim_keeps_recent_and_small` checks four things:

- **The input list isn't modified.** A new list comes back, and the original still holds the full text.
- **The last 6 messages are identical.**
- **Small results stay**, even when old.
- **Tool-call ids and user messages are unchanged.** Only the content of old, large results is replaced, so the history stays valid.

**`split_index(messages, keep)`** picks where "old" (to be summarized) ends and "recent" (to be kept) begins. On `convo(5)`:

| `keep` | Natural start (16 − keep) | Role there | Result |
|---|---|---|---|
| 3 | 13 | user | 13 |
| 4 | 12 | **tool** | moves back to **11** (assistant) |
| 6 | 10 | user | 10 |

It never splits on a `tool` message, because that would separate a result from the call it answers. It never goes below 1, which protects the system message. `test_split_never_on_tool_message` tries every `keep` from 0 to 11.

## One test, step by step: `test_agent_compacts_when_over_threshold`

**Code this test exercises:** `Agent.run` in `agent/loop.py`; `ContextManager.needs_compaction` in `agent/context.py`; `split_index` in `agent/context.py`; `compact` in `agent/context.py`; `AgentEvents.on_compact` in `agent/events.py`; `read_file` (defined inside `make_read_file`) in `agent/tools/files.py`.

This is the whole mechanism inside a real agent run:

```python
def test_agent_compacts_when_over_threshold(tmp_path):
    (tmp_path / "a.txt").write_text("hello")
    rec = Recorder()
    script = [reply(tool_calls=[call("read_file", {"path": "a.txt"})], prompt_tokens=900),  # 1
              summary_reply(),                                                            # 2
              reply(content="done", prompt_tokens=300)]                                   # 3
    agent, client = make_agent(tmp_path, script, ContextManager(1000, keep_recent=2),
                               events=rec)
    result = agent.run("look at a.txt")
```

The agent has a system prompt (`"sys"`) and a `ContextManager` with a window of 1,000 tokens. It compacts above 80%, so above 800 tokens. The reference solution made three requests:

**Request 0** (normal, with tools): roles `['system', 'user']`. The reply asks for `read_file` and *reports* `prompt_tokens=900`. The manager stores that as `last_prompt_tokens = 900`. The tool runs, and the history is now system, user, assistant, tool.

**Before the next request** the agent asks `needs_compaction(...)`. 900 is over 800, so it compacts. `split_index(..., keep=2)` keeps the last two messages (the assistant call and its tool result) and summarizes the older part, which is the user's question.

**Request 1** (the summary request): **no `tools` key**, because the model should write text, not call tools. Roles `['system', 'user']`. These are the *summarizer's* system prompt, and one user message holding the old conversation written out as text. On `convo(5)` that text begins:

```
user: question 0

assistant:
[called read_file({})]

tool: xxxxxxxx...
```

The reply is `SUMMARY TEXT`. The summary becomes a user message, `[Summary of earlier conversation]\nSUMMARY TEXT`, placed right after the system message. `on_compact(before, after)` fires with the estimated token counts.

**Request 2** (normal, with tools): roles `['system', 'user', 'assistant', 'tool']`: the system message, the summary, and the two kept messages. The reply is `done` with `prompt_tokens=300`.

The final history is much shorter, and its user message is now the summary:

```
('system', 'sys')
('user', '[Summary of earlier conversation]\nSUMMARY TEXT')
('assistant', None)            <- the read_file call, kept
('tool', '     1\thello')      <- its result, kept
('assistant', 'done')
```

The test checks each request in turn:

```python
    assert len(client.requests) == 3
    assert "tools" in client.requests[0]
    assert "tools" not in client.requests[1]                 # the summary request
    assert "tools" in client.requests[2]
    assert "SUMMARY TEXT" not in json.dumps(client.requests[1])
    assert any("[Summary of earlier conversation]" in str(m.get("content"))
               for m in client.requests[2]["messages"])
    assert len(rec.compactions) == 1
```

## The rest of `compact`

- **`test_compact_shape`**: one summary request with no tools. The result is the system message, then the summary, then the recent messages unchanged. The summary request really contained the old conversation (`"question 0"`).
- **`test_compact_merges_into_user_message`**: if the recent part *starts* with a user message, the summary is merged into it rather than placed before it. Two user messages in a row confuse some chat templates. The test checks that no two adjacent messages are both `user`.
- **`test_compact_keeps_tool_pairs`**: for every `keep` from 1 to 11, every remaining `tool` message answers a call that's still there.
- **`test_compact_without_system_message`**: with no system message, the summary becomes message 0.
- **`test_compact_with_nothing_to_summarize_makes_no_call`**: if everything is "recent", nothing changes. The fake's empty script proves no request was made.

## When to compact

**`test_needs_compaction_uses_usage_then_estimate`**, with `ContextManager(1000)`:

- **Before any request, it estimates.** 4,000 characters is about 1,000 tokens, which is over 800, so it compacts; `"hi"` doesn't.
- **Once a real count is known, it uses that instead.** `last_prompt_tokens = 790` means no; 900 means yes. The server's real count beats the estimate whenever there is one.

The other agent tests:

- **`test_console_events_print_compaction`**: the terminal prints both numbers.
- **`test_agent_without_context_never_compacts`**: with no manager, a reported 99,999 tokens changes nothing, so earlier lessons keep working.
- **`test_agent_trims_old_tool_results_permanently`**: trimming is stored back into `agent.messages`, not only applied to what's sent. Otherwise the history would never actually shrink.
- **`test_streaming_usage_feeds_the_manager`**: the same flow with `stream=True`. The summary request isn't streamed, and the final streamed token count (300) reaches the manager.

## When the server says "too long"

The estimate can be wrong, so the server may still reject a request. The tests script that rejection as an exception.

This is the error LM Studio actually returned to the live test on 2026-11-12:

```
str(exc) = "Error code: 400"
exc.body = 'Engine protocol predict request returned 400: {"error":{"code":400,"message":"request (60052
            tokens) exceeds the available context size (32768 tokens), try increasing it",
            "type":"exceed_context_size_error","n_prompt_tokens":60052,"n_ctx":32768}}'
```

`str(exc)` says nothing useful; the details are only in `exc.body`. The tests build an error of exactly this shape (`lm_studio_overflow()`).

- **`test_context_overflow_retry`**: rejected with "context length exceeded". The agent compacts (one request with no tools), retries, and the run ends `done`.
- **`test_context_overflow_twice_errors`**: a second rejection after compacting ends with `stop_reason == "error"` after exactly 3 requests. It retries once, not forever.
- **`test_overflow_is_detected_in_the_body_not_just_str`**: an `is_context_overflow` that only looks at `str(exc)` fails here. The error the agent reports must include the server's words ("exceeds the available context size").
- **`test_error_text_does_not_repeat_the_body`**: when the message and the body both contain the details, `error_text` says them once.
- **`test_other_bad_requests_are_not_retried`**: a different 400 ("invalid tool schema") isn't treated as overflow. One request, then an error.
- **`test_overflow_without_context_manager_is_an_error`**: with no manager, an overflow is just an error.

## The live test

`test_live_overflow_message` (run with `--live`) sends LM Studio a prompt of about 60,000 tokens, far over 32K, prints the real error (shown above), and checks that `is_context_overflow` recognizes it. It fails loudly if the server *accepts* the prompt, because that would mean it silently dropped part of it, which is worse than an error.

## If a test fails

- **Request counts are off by one:** you compact at the wrong moment. The check happens *before* sending a request, using the last reply's real `prompt_tokens`.
- **The summary request has `tools`:** build its kwargs separately; don't reuse `_request`.
- **A tool-pairs test fails:** your split landed on a `tool` message. Move the split back to the assistant message that made the call.
- **The overflow isn't detected:** look in `exc.body` (it may be a string or a dict) as well as `str(exc)`.

## Words used above

| Term | Meaning here |
|---|---|
| **context window** | The most tokens a model can read in one request (32,768 here). |
| **trimming** | Replacing old, large tool results with a short note. |
| **compacting** | Replacing the older part of the history with a model-written summary. |
| **threshold** | The fraction of the window that triggers compaction (0.8). |
| **`keep_recent`** | How many of the newest messages are always kept as they are. |
| **split index** | Where the old part ends and the kept part begins. |
| **overflow** | The server rejecting a request as too long for the window. |
