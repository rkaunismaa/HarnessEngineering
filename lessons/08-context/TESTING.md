# How the lesson 8 tests work

Lesson 8's tests build long conversations out of thin air, so they never have to fill a real 32K window. They test the context functions one at a time, then run scripted agents that cross the limit. A summary is just another scripted reply, so a single script can include the summarization request in the middle of a run. Against the reference solution: 20 passed, 1 skipped (the live test).

```
uv run pytest lessons/08-context
uv run pytest lessons/08-context --impl solutions/08-context
```

## The made-up conversation

```python
def convo(n_pairs=6, big="x" * 1000):
    # system, then n_pairs of (user, assistant-with-tool-call, tool result)
```

`convo(5)` is 16 messages: a system message, then five groups of user question, assistant tool call and 1,000-character tool result. The pattern is fixed, so the tests can work out which index holds which role. For example, index 12 is a `tool` message. `summary_reply()` is a scripted reply whose content is `SUMMARY TEXT`, for when the code asks the model to summarize.

## The building blocks

- **`test_estimate_tokens`** pins the estimate exactly: `ceil(len(json.dumps(messages)) / 4)`, about four characters per token. It's rough, but it only has to answer "are we near the limit?" for a request not sent yet.
- **`test_trim_keeps_recent_and_small`**: `trim_old_tool_results` replaces *old* tool results over 500 characters with `[old tool result removed: 1000 characters]`. It checks four things:
  - The **input list isn't modified**. The function returns a new list, and the test checks the original still holds the full text.
  - The **last 6 messages are untouched**.
  - **Small results are kept** even when old.
  - **Tool-call ids and user messages don't change**. Only the content of old, large tool results is replaced, so the history stays valid.
- **`test_split_never_on_tool_message`**: `split_index(msgs, keep)` picks where "old" ends and "recent" begins. It loops over every `keep` from 0 to 11. The split never lands on a `tool` message, because that would separate a result from the call it answers, and never before index 1, which protects the system message. For `keep=4` the natural split is index 12, a tool message, so it moves back to 11. Without a system message, the lowest possible split is 0.

## `compact`: summarizing the old part

- **`test_compact_shape`**: one summary request, *with no tools* (the model should write text, not call tools). The result is: the system message, then `{"role": "user", "content": "[Summary of earlier conversation]\nSUMMARY TEXT"}`, then the recent messages unchanged. The test also checks that the summary request really contained the old conversation (`"question 0"`), so the model had something to summarize.
- **`test_compact_merges_into_user_message`**: if the recent part starts with a user message, the summary is merged *into* it rather than placed before it. Two user messages in a row confuse some chat templates. The test checks no two adjacent messages are both `user`.
- **`test_compact_keeps_tool_pairs`**: for every `keep` from 1 to 11, every remaining `tool` message must answer a call that is still in the history.
- **`test_compact_without_system_message`**: with no system message, the summary becomes message 0.
- **`test_compact_with_nothing_to_summarize_makes_no_call`**: if everything is "recent", nothing changes, and the fake's empty script proves no request was made.

## When to compact

- **`test_needs_compaction_uses_usage_then_estimate`**: `ContextManager(1000)` compacts above 80%, so 800 tokens. Before any request, it estimates: 4,000 characters is about 1,000 tokens, which is over the threshold. Once a real `prompt_tokens` is known (`last_prompt_tokens`), it uses that instead: 790 is fine and 900 isn't. The server's real count beats the estimate whenever it's available.

## The agent compacts on its own

**`test_agent_compacts_when_over_threshold`** uses a three-reply script:

1. A tool call, with `prompt_tokens=900`. That's over 80% of 1,000.
2. `SUMMARY TEXT`, the reply to the summary request.
3. `done`.

The test checks every request in turn:

- **Request 0 and request 2** carry `tools`. These are the normal ones.
- **Request 1** has *no* `tools`. It's the summary request, and it doesn't contain the summary text yet.
- **Request 2's messages** contain `[Summary of earlier conversation]`.
- **`on_compact(before, after)`** fired once with token counts. That's how the terminal shows "compacted 9000 → 2000"; `test_console_events_print_compaction` checks the printing.

The other agent tests:

- **`test_agent_without_context_never_compacts`**: with no `ContextManager`, a reported 99,999 tokens changes nothing. Earlier lessons keep working.
- **`test_agent_trims_old_tool_results_permanently`**: trimming happens before each request and is stored back into `agent.messages`, not only applied to what's sent. Otherwise the same trimming would repeat every turn and the history would never shrink.
- **`test_streaming_usage_feeds_the_manager`**: the same script with `stream=True`. The summary request isn't streamed, and the token count from the last streamed reply (300) reaches the manager.

## When the server says "too long"

The estimate can be wrong, so the server may still reject a request. The tests script that rejection as an exception:

- **`test_context_overflow_retry`**: the server rejects with "context length exceeded". The agent compacts (a request with no tools) and retries, and the run ends with `done`.
- **`test_context_overflow_twice_errors`**: a second rejection after compacting ends with `stop_reason == "error"`, after exactly 3 requests. It retries once, not forever.
- **`test_overflow_is_detected_in_the_body_not_just_str`** uses an error shaped exactly like **LM Studio's real one**. `str(exc)` is only `"Error code: 400"`; the useful text ("exceeds the available context size (32768 tokens)") is in `exc.body`. An `is_context_overflow` that only checks `str(exc)` fails this test. The live test below captured the real shape. The error the agent reports must include the server's own words.
- **`test_error_text_does_not_repeat_the_body`**: when the message *and* the body both contain the details, `error_text` must say them once, not twice.
- **`test_other_bad_requests_are_not_retried`**: a different 400 ("invalid tool schema") isn't treated as overflow. One request, then an error.
- **`test_overflow_without_context_manager_is_an_error`**: with no manager, an overflow is just an error.

## The live test

`test_live_overflow_message` (run with `--live`) sends LM Studio a prompt far over 32K tokens and prints the real error. It passes if `is_context_overflow` recognizes it. It fails loudly if the server *accepts* the oversized prompt, because that would mean it silently dropped part of it, which is worse than an error. Run it with `-s` to see the error's exact text.
