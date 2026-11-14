# Lesson 8 solution: what changed since lesson 7

This folder is the reference solution for [lesson 8](../../lessons/08-context/README.md). This page compares its `agent/` package with the one in [`solutions/07-the-terminal/agent/`](../07-the-terminal/agent/), file by file. For each change it says what the code does, why it's written that way, and what it's meant to show you.

To run this solution without touching your own `agent/` folder, run commands from inside this folder (`cd solutions/08-context`). `python -m agent` imports the `agent` package from the folder you're in. To run the lesson's tests against it: `uv run pytest lessons/08-context --impl solutions/08-context`, from the repository root.

## At a glance

| File | Lesson 7 | Lesson 8 | Status |
|---|---|---|---|
| `agent/context.py` | | 146 lines | **new**: estimating tokens, trimming old results, summarising the history, and the `ContextManager` that decides when |
| `agent/loop.py` | 200 lines | 243 lines | **changed**: prepares the history before each request; compacts and retries once if the server says it's too long |
| `agent/events.py` | 18 lines | 21 lines | **changed**: an `on_compact` event |
| `agent/cli.py` | 105 lines | 110 lines | **changed**: shows a line when the history is compacted |
| `agent/__main__.py` | 137 lines | 139 lines | **changed**: every agent gets a `ContextManager` for the configured window |
| everything else | | | unchanged |

## What lesson 7 could do, and what it couldn't

Lesson 7 made long sessions possible, with `chat`, and that exposed the next limit. The model sees the whole conversation on every request, and the window is 32K tokens. The system prompt and tool schemas already take about 1,100 of those, and every tool result stays in the history for the rest of the session.

One real run, reading four 300-line files one after another, went `1142 -> 6364 -> 6459 -> 6549 -> ...` prompt tokens: each `read_file` cost about 5,200 tokens, for good. A few more files and the server rejects the next request with a `400`. In lesson 7 that became `stop_reason="error"`, and the session was over: every later request would be rejected too, because the history only grows.

## What this lesson is meant to show you

1. **The context window is a budget, and tool results are most of the spending.** A file the model read ten steps ago is rarely needed word for word, and the model can read it again if it is.
2. **Two layers: stay under the limit, and recover if you hit it.** Before each request, drop what the model no longer needs. If the server still says it's too long, shrink the history once and try again.
3. **The history's structure must survive.** A `tool` result must never lose the assistant message whose call it answers. Cutting has to land on a `user` or `assistant` message.
4. **Summarising loses detail.** A summary keeps goals, decisions and files, but not exact text. After a compaction the model sometimes has to re-read a file. That's the cost of continuing at all.
5. **Count with the server's numbers.** `usage.prompt_tokens` is exact. A local estimate (characters ÷ 4) is only for text the server hasn't counted yet.

## File by file

### `agent/context.py` (new): the parts

**`estimate_tokens(messages)`** is `ceil(len(json.dumps(messages)) / 4)`. It's crude, and that's fine: it's only used for text the server hasn't counted yet. A tokenizer library wouldn't be better, because Qwen's tokenizer isn't the one those libraries use.

**`trim_old_tool_results(messages, keep_recent=6, min_chars=500)`**, the cheap layer:

```python
cutoff = len(messages) - keep_recent
for i, msg in enumerate(messages):
    content = msg.get("content")
    if (i < cutoff and msg.get("role") == "tool" and isinstance(content, str)
            and len(content) > min_chars):
        msg = {**msg, "content": f"[old tool result removed: {len(content)} characters]"}
    out.append(msg)
```

- **Only `tool` results**, only **older than the last six messages**, and only **longer than 500 characters**. Your messages, the model's messages, and short results like `Edited calc.py (1 replacement).` all stay.
- **The message stays; only its text is replaced.** So the `tool_call_id` pairing is intact, and the note tells the model something was there, and how big it was, so it knows it can read the file again.
- **It returns a new list** and never changes the messages it was given. The loop decides whether to keep the result.
- **No model request needed.** It's run before every request, so it has to be free.

**`split_index(messages, keep_recent)`** decides where the kept part of the history starts when compacting: `keep_recent` messages from the end, then moved **backwards** until it lands on a `user` or `assistant` message. It never starts on a `tool` message, so a result always keeps the call it answers. It never moves into the system message, and it always keeps at least one message.

**`compact(messages, client, model, keep_recent, log)`**, the expensive layer:

1. Keep the system message (if there is one) and everything from `split_index` on.
2. Turn the part in between into a plain-text transcript (`_transcript`): one line per message, each cut to `MAX_MESSAGE_CHARS` (2,000), tool calls written as `[called read_file({...})]`, and the whole thing cut to its last `MAX_TRANSCRIPT_CHARS` (60,000 characters). The summary request must fit in the window too, or it would fail for the very reason it's being made.
3. Send that transcript to the model **with no tools**, under `SUMMARY_PROMPT`. The prompt asks for the user's goals, decisions and why, files read, created or changed, and what remains, **keeping exact file names, commands and error messages**.
4. Put the summary back as a user message starting `[Summary of earlier conversation]`. **If the kept part already starts with a user message, the summary goes in front of its text instead.** Two user messages in a row confuse some chat templates.

The summary request is logged under the agent name `compact`, using `with_agent`, which lesson 1 added for exactly this kind of thing. `python -m agent log` shows it in order with the rest.

**`error_text(exc)` and `is_context_overflow(exc)`.** LM Studio's overflow error is a `400` whose `str(exc)` is just `Error code: 400`. The useful text, `request (60052 tokens) exceeds the available context size (32768 tokens)`, is only in `exc.body` and in the response text. `error_text` collects all of it, each piece once. `is_context_overflow` then looks for the word `context`. The loop also uses `error_text` for every error message now, so a `400` says *why*.

**`ContextManager(window, threshold=0.8, keep_recent=6)`** decides **when** to compact:

```python
def needs_compaction(self, messages):
    if self.last_prompt_tokens is None:
        used = estimate_tokens(messages)
    else:
        counted = len(messages) if self._counted is None else self._counted
        used = self.last_prompt_tokens
        if len(messages) > counted:
            used += estimate_tokens(messages[counted:])
    return used > self.threshold * self.window
```

- **It starts from the server's exact count for the last request** (`observe` records it), and only estimates the messages added since: the reply and any tool results. Most of the number is exact, and the guess covers only the new part.
- **80% of the window**, not 100%, because the reply needs room too, and the estimate can be low.
- **`shrank` and `reset`** keep the count honest after the history changes. Trimming lowers the last count by the estimated saving. Compacting replaces the history, so there's no exact count until the next reply.

### `agent/loop.py` (changed): preparing each request

`_ask_model` now wraps the request (renamed `_ask_once`) in two steps:

```python
if self.context is None:
    return self._ask_once()
self._prepare_context()
try:
    return self._ask_once()
except openai.BadRequestError as exc:
    if not is_context_overflow(exc):
        raise
    self._compact()
    return self._ask_once()
```

- **`_prepare_context`** trims old tool results, then compacts if `needs_compaction` says so.
- **Trimming is permanent.** The trimmed list is stored back in `self.messages`, so the dropped text never costs tokens again. The full text is still in the request log.
- **If the server rejects the request anyway**, as context overflow, the loop compacts and tries **once** more. If that fails too, the error goes up to `run` as before and ends the turn with `stop_reason="error"`. Retrying forever would just repeat the failure.
- **A `400` for any other reason** isn't treated as overflow. It's raised again unchanged.
- **`_ask_once` calls `context.observe`** after each reply, with the server's prompt-token count and the number of messages that request carried.
- **`_compact` reports `on_compact(before, after)`**, with estimated token counts, so the terminal can tell you it happened.
- **No `context` means no change at all**, so the earlier lessons' tests behave as before.

### `agent/events.py`, `agent/cli.py` (changed): seeing it happen

A new event, `on_compact(before, after)`, does nothing by default. `ConsoleEvents` prints it as a yellow line:

```
Context compacted: about 27410 -> 3105 tokens.
```

(Those numbers are only an example.) Compaction changes what the model knows, so you should see when it happens: if the model suddenly re-reads a file, this line explains why.

### `agent/__main__.py` (changed): every agent gets a manager

`_build_agent` passes `context=ContextManager(config.context_window)`. `context_window` has been in `Config` since lesson 0 (32,768 by default, or `AGENT_CONTEXT_WINDOW`). Set it to the window the model was actually **loaded** with. Setting it larger than that means the server rejects requests before the harness ever decides to compact.

## What's still missing, and which lesson adds it

| Gap in this version | What goes wrong | Fixed in |
|---|---|---|
| Summaries lose detail, and summaries of summaries drift | after a compaction or two, the model may misremember what a file said | not in this course; the model can re-read |
| A whole single result can still be huge | one 20,000-character result plus a big history can overflow before trimming applies | partly lesson 2's cap; partly by design |
| No way to say what a summary must keep | Claude Code's `/compact <focus>` has no equivalent | not in this course |
| Searching through many files fills the context fast | each search result stays until it's old enough to trim | lesson 10 (subagents) |

## Seeing it work

From inside this folder, set a deliberately small window so compaction happens quickly:

```
uv run python ../../scripts/make_fixture.py scratch /tmp/scratch8
AGENT_CONTEXT_WINDOW=4000 uv run python -m agent chat --root /tmp/scratch8
```

Ask it to read several files one after another, and watch for `Context compacted: ...`. Then `uv run python -m agent log` shows the `compact` request and its summary between the `main` requests. The lesson's README has the real overflow error and a compaction run. [TESTING.md](../../lessons/08-context/TESTING.md) walks through the compaction test message by message.
