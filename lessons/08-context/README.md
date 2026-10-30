# Lesson 8: Context

Start from your lesson 7 code, or copy `solutions/07-the-terminal/agent` into `agent/`.

## Why this exists

The model sees the whole conversation on every request, and the window is small: 32K tokens on the local setup this course uses. The system prompt and tool schemas already take about a thousand of those (a one-word reply measured `prompt_tokens=1129` in lesson 7), and every tool result stays in the history for the rest of the session.

A real run against LM Studio (27B), asking for the last line of four 300-line files one after another, with no trimming, logged these `prompt_tokens` for consecutive requests:

```
1142  ->  6364  ->  6459  ->  6549  ->  ...
```

One `read_file` of a 300-line file cost about 5,200 tokens. Four of them would be around 21K of a 32K window, and that is a small task. When the window is full the server rejects the request. Observed with LM Studio 0.4.27 when sending a prompt of about 60K tokens to the 32K model:

- The HTTP status is 400 and the SDK raises `openai.BadRequestError`.
- `str(exc)` is only `Error code: 400`. The wording is in `exc.body`, a plain string here: `Engine protocol predict request returned 400: {"error":{"code":400,"message":"request (60052 tokens) exceeds the available context size (32768 tokens), try increasing it","type":"exceed_context_size_error","n_prompt_tokens":60052,"n_ctx":32768}}`. The same text is in `exc.response.text`.
- So the check "does the message mention context" has to look at the body and the response text as well as `str(exc)`. A prompt of about 30K tokens was accepted, so the server did not silently truncate: it either serves the request or rejects it.

The lesson has two layers. First, stay away from the limit: drop what the model no longer needs. Second, if the limit is hit anyway, shrink the history once and retry.

### What to keep and what to drop

- **Tool results are the bulk** and age fastest. A file the model read ten steps ago is rarely needed verbatim; if it is, the model can read it again. So old, long tool results are replaced by a one-line note and everything else stays.
- **Never separate a tool result from its assistant message.** A `tool` message answers a `tool_call_id` from an assistant message just before it. Cut the history between them and the model sees a result for a call it never made. (LM Studio and Ollama both accepted such a history without an error when tried, so the server will not warn you; the model just has less to go on.) Cutting must land on a `user` or `assistant` message.
- **Keep the system prompt** and the most recent messages: the model needs the instructions and the work in progress.
- **Summarize the middle.** Goals, decisions, files touched and current state fit in a few hundred tokens. The cost is detail. Observed with the 27B at a deliberately tiny window: after one compaction the summary said "the returned content was no longer available" for a file, and the model went to re-read the file with `tail` instead. Summaries of summaries drift further. Plan for that: keep exact names and error messages in the summary prompt, and let the model re-read files.
- **Trimming is permanent.** The agent stores the trimmed history back, so the model never sees the dropped text again and the saved tokens stay saved. The alternative is to trim a copy for each request and keep the full text in `agent.messages`; that keeps the data for logs or undo but you re-pay the trimming work every request and the history still grows. Compaction also replaces the history.

### Counting tokens

`usage.prompt_tokens` from the server is the ground truth, and it is what the next decision is based on. Tokenizers differ between model families: Qwen's tokenizer is not tiktoken, so a library count would be wrong anyway. When you must guess (no usage yet, or text added since the last response), the estimate is characters divided by four. Treat it as a fallback only.

## How Claude Code does it

- **Documented** ([Manage costs](https://code.claude.com/docs/en/costs), checked): Claude Code has auto-compaction, "which summarizes conversation history when approaching context limits", and a `/compact` command; `/compact Focus on code samples and API usage` tells it what to preserve, and a "Compact instructions" section in `CLAUDE.md` does the same. `/clear` starts fresh and `/context` shows what is using space.
- **Observed**: when a long Claude Code conversation grows, its earlier turns are replaced by a summary and work continues from that summary. Your `compact` does the same in a smaller form: no custom focus instructions and no re-injection of project files.

## What you'll build

New: `agent/context.py`. Changed: `agent/loop.py`, `agent/events.py`, `agent/cli.py`, `agent/__main__.py`. Tests: `lessons/08-context/tests/`.

**`estimate_tokens(messages) -> int`**: `math.ceil(len(json.dumps(messages)) / 4)`.

**`trim_old_tool_results(messages, keep_recent=6, min_chars=500) -> list[dict]`**: returns a new list; the input is not changed. A `tool` message that is not among the last `keep_recent` messages and whose content is longer than `min_chars` gets the content `[old tool result removed: N characters]` (`N` is the original length). Everything else is passed through.

**`split_index(messages, keep_recent) -> int`**: start at `len(messages) - keep_recent` (at least one message is kept), never below the first message after the system message; move backward until the message there is a `user` or `assistant` message. With a system message first the lower bound is 1, without one it is 0.

**`compact(messages, client, model, keep_recent=6, log=None) -> list[dict]`**:
- The head is `messages[:1]` if that message's role is `system`, else empty. The part to summarize is everything between the head and `split_index`. If that part is empty, return the messages unchanged and make no request.
- One request to `client.chat.completions.create(model=..., messages=...)` with **no `tools`** and no streaming. It carries a fixed summarization instruction (goals, decisions, files touched, current state) and the old messages rendered as text, each cut with `truncate`, and the whole text capped so the summary request cannot itself overflow. If `log` is given, the request is recorded in it.
- Result: head, then the summary, then the kept tail. The summary is `{"role": "user", "content": "[Summary of earlier conversation]\n" + text}`. If the first kept message is a `user` message, the summary text is put in front of that message's content instead, so there are never two user messages in a row.
- Every remaining `tool` message keeps its assistant message.

**`ContextManager(window, threshold=0.8, keep_recent=6)`**: `last_prompt_tokens: int | None`, updated after every main request from the response's `usage` (streamed or not; `None` when the server sent none). `needs_compaction(messages)` compares `threshold * window` with `last_prompt_tokens` plus `estimate_tokens` of the messages added since that request, or with `estimate_tokens(messages)` when there is no usage yet. After you trim or compact, the old count is stale: lower it by the estimated saving after a trim and forget it after a compaction.

**`is_context_overflow(exc)`**: true when `"context"` appears, ignoring case, in `str(exc)`, the error body or the response text. Use the same text in the `Model request failed: ...` error message so a failure says what the server said, not just `Error code: 400`. This refines lesson 3's `f"Model request failed: {exc}"`. Add the body or response text only when `str(exc)` does not already contain it; for most errors `str(exc)` already includes the body, and repeating it makes the message noisy.

**`AgentEvents.on_compact(before: int, after: int)`**: a new method that does nothing by default; estimated tokens before and after a compaction.

**`Agent(..., context: ContextManager | None = None)`**:
- With `context=None` nothing changes.
- Before each request: replace `self.messages` with the trimmed list, then compact if `needs_compaction`, calling `events.on_compact`.
- The summary request goes through the same client and is written to the same request log with agent name `compact`, so `python -m agent log` shows it.
- A `BadRequestError` for which `is_context_overflow` is true: compact, fire `on_compact`, retry once. A second failure (or any other error) returns `stop_reason == "error"` as before.

**CLI**: `ask` and `chat` build the agent with `ContextManager(config.context_window)`. The chat UI prints one line when `on_compact` fires.

## Tests

```
uv run pytest lessons/08-context --impl agent-or-solution-dir
```

For the reference solution: `uv run pytest lessons/08-context --impl solutions/08-context`. The unit tests build histories by hand; the agent tests use a scripted client where a summary is just another scripted reply (so the number and order of requests in a script is part of the test). `test_live_overflow_message` needs `--live`: it sends about 60K tokens to the 32K model, prints the real error and checks that `is_context_overflow` matches it.

## Try it live

```
uv run python -m agent chat --root .
```

To see compaction without writing 30K tokens, set a small window: `AGENT_CONTEXT_WINDOW=1500 uv run python -m agent chat`. Ask for the last line of a few 300-line files one by one. Each turn prints `Context compacted: about N -> M tokens.`, and `python -m agent log` shows `[compact]` entries with no tools in them. With the default window and 300-line files, watch the `prompt_tokens` in the log: on the run above the count fell from 6487 to 1372 in one step, when old file contents were replaced by notes, and stayed near 1,500 afterwards.

A window of 1500 is far too small for real use (compaction ran on almost every request and the summaries kept losing the file contents); it is only there to make the mechanism visible.

## Break it

In `split_index`, remove the loop that moves backward off `tool` messages. Run the tests: `test_split_never_on_tool_message` and `test_compact_keeps_tool_pairs` fail. Then try the broken history against the 4B: an `[Summary...]` user message followed straight away by a `tool` message with an unknown `tool_call_id` and a new user message. Neither LM Studio's 27B nor Ollama's 4B rejected it; the 4B answered that it could not find the file the summary talked about. A bug that the server does not report is the reason the test inspects the message list itself.

## Extras

- Let `/compact` (with optional focus text) trigger a compaction by hand in the chat UI.
- Keep a file of the dropped tool results so the model can ask for one back.
- Re-inject the project instructions after a compaction.
- Make the summary prompt configurable.
