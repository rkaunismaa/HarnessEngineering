# How the lesson 3 tests work

Against the reference solution: 27 passed, 1 skipped (the live test). The count includes four runs of one parametrized test. The live test passes too with `--live` (4.6 s against the 4B in Ollama).

```
uv run pytest lessons/03-when-the-model-gets-it-wrong
uv run pytest lessons/03-when-the-model-gets-it-wrong --impl solutions/03-when-the-model-gets-it-wrong
uv run pytest lessons/03-when-the-model-gets-it-wrong --live -s -k 4b    # see the 4B's calls
```

## The big picture

Lessons 1 and 2 tested the happy path. Lesson 3's tests deliberately feed your harness **bad input**, the kind real models produce:

- a call to a tool that doesn't exist;
- arguments that are broken JSON, or JSON of the wrong shape or types;
- a tool that crashes;
- a model that repeats the same call forever;
- a server that goes away mid-run.

Every test checks the same promise: **the harness turns the problem into a clear message for the model, or stops cleanly, and the history stays valid.** Nothing is allowed to escape as an exception and crash the run.

The tests come at this from two levels:

```
 dispatch level (no model, no loop)            agent level (FakeClient + loop)
 ----------------------------------            -------------------------------
 registry.dispatch("add", '{"a": 1,')          script: [broken call, fixed call, answer]
   -> "Error: arguments were not valid         agent.run(...)
       JSON (...)..."                            -> the error reached the model,
                                                    and it recovered
```

## The helpers

```python
def small_registry(fn=None):
    registry = ToolRegistry()
    registry.register(Tool("add", "Add numbers.",
        {"type": "object",
         "properties": {"a": {"type": "integer"}, "b": {"type": "integer"},
                        "label": {"type": "string"}},
         "required": ["a"]},
        fn or (lambda a, b=0, label="": str(a + b))))
    return registry
```

`small_registry` builds a registry with one made-up tool, `add`, with a known schema: `a` is a required integer, and `b` and `label` are optional. With a fixed schema, the validation tests can use exact error messages without depending on your real tools. Passing `fn` swaps in a function that crashes.

`make_agent` is the same as in lesson 1. `tool_results(agent)` pulls the content of every `tool` message out of the history, in order.

## One test, step by step: `test_error_fed_back_and_model_recovers`

This is the whole lesson in one test: a model makes a mistake, the harness tells it, and it fixes itself.

```python
def test_error_fed_back_and_model_recovers(tmp_path):
    (tmp_path / "a.txt").write_text("hello\n")
    agent, client = make_agent(tmp_path, [
        reply(tool_calls=[call("read_file", '{"path": "a.txt"')]),   # 1: broken JSON (no closing brace)
        reply(tool_calls=[call("read_file", {"path": "a.txt"})]),    # 2: the same call, fixed
        reply(content="hello"),                                      # 3: the answer
    ])
    result = agent.run("read a.txt")
```

`call()` JSON-encodes a dict, but passes a string through unchanged. That's how the first reply carries broken JSON. Here is what the reference solution's loop did, as recorded by `FakeClient`.

**Request 0** sends just the user message. Reply 1 asks for `read_file` with the arguments string `'{"path": "a.txt"'`.

**The harness tries to run it.** `dispatch` calls `json.loads` on the arguments, which raises `JSONDecodeError`. Lesson 3's `dispatch` catches that and returns a message instead:

```
Error: arguments were not valid JSON (Expecting ',' delimiter). Send the arguments as a JSON object.
```

The text in brackets is Python's own reason. The last sentence tells the model what to do. The loop appends it as an ordinary `tool` message.

**Request 1** has 3 messages, and its last one is that error:

```json
{"role": "tool", "tool_call_id": "call_1",
 "content": "Error: arguments were not valid JSON (Expecting ',' delimiter). Send the arguments as a JSON object."}
```

Reply 2 is the corrected call. It runs normally and returns `     1\thello`.

**Request 2** has 5 messages and ends with the real file content. Reply 3 is the answer, so the loop stops. The final history:

```json
{"role": "user", "content": "read a.txt"}
{"role": "assistant", "content": null, "tool_calls": [{"id": "call_1", ..., "arguments": "{\"path\": \"a.txt\""}]}
{"role": "tool", "tool_call_id": "call_1", "content": "Error: arguments were not valid JSON (Expecting ',' delimiter). Send the arguments as a JSON object."}
{"role": "assistant", "content": null, "tool_calls": [{"id": "call_2", ..., "arguments": "{\"path\": \"a.txt\"}"}]}
{"role": "tool", "tool_call_id": "call_2", "content": "     1\thello"}
{"role": "assistant", "content": "hello"}
```

and `run` returned `TurnResult(final_text='hello', stop_reason='done', turns=3, ...)`. The test checks four things:

```python
    assert result.stop_reason == "done"
    results = tool_results(agent)
    assert results[0].startswith("Error: arguments were not valid JSON")   # the error was a result
    assert results[1] == "     1\thello"                                   # the retry worked
    assert client.requests[1]["messages"][-1]["content"] == results[0]     # the model saw the error
```

The last line is the key one. The error went back to the model as **an ordinary tool message**, which is the whole recovery mechanism: no special channel, just a result that explains what went wrong.

## Errors in `dispatch`: each one becomes a message

These call `dispatch` directly and compare the exact string. The right-hand column is what the solution returned.

| Test | Input | Result |
|---|---|---|
| `test_unknown_tool` | tool `nope` | `Error: unknown tool 'nope'. Available tools: add` |
| `test_unknown_tool_lists_all_names` | `grep`, real registry | `Error: unknown tool 'grep'. Available tools: read_file, list_files, search, bash` |
| `test_bad_json`, `test_bad_json_exact_message` | `{"a": 1,` / `{nope` | `Error: arguments were not valid JSON (<reason>). Send the arguments as a JSON object.` |
| `test_arguments_not_object` (×4) | `[1, 2]`, `"text"`, `3`, `null` | `Error: arguments must be a JSON object.` |
| `test_missing_required` | `{}` | `Error: missing required parameter 'a'` |
| `test_wrong_type` | `{"a": "5"}` | `Error: parameter 'a' must be integer` |
| `test_bool_is_not_integer` | `{"a": true}` | the same; in Python `True` is an `int`, so this needs a special case |
| `test_unknown_param` | `{"a": 1, "c": 2}` | `Error: unknown parameter 'c'` |
| `test_several_errors_joined` | `{"b": "x", "c": 1}` | all three, joined with `; `: missing, then unknown, then wrong type |
| `test_tool_exception` | `add` raises `RuntimeError("disk on fire")` | `Error: RuntimeError: disk on fire` |

Some details worth noticing:

- **Listing the available tools** gives the model what it needs to correct itself. Small models often invent `grep` or `cat`.
- **`test_bad_json_exact_message`** doesn't hard-code Python's wording. It runs `json.loads("{nope")` itself, catches the error, and builds the expected text from `info.value.msg`. The test holds even if Python's wording changes.
- **Reporting every problem at once** (`test_several_errors_joined`) saves the model one round trip per mistake.
- **`test_validate_args_types`** tests the `validate_args(schema, args)` helper directly for all six JSON types. An `int` counts as a `number`, but `True` doesn't, and `0` is not a `boolean`.
- **`test_dispatch_never_raises_on_real_tools`** throws odd but plausible arguments at the real tools (`/etc/*`, `../outside`, `.`, a missing folder) and only checks that each result is a string. What matters is that nothing escapes as an exception.
- **`test_error_results_are_truncated`**: a 50,000-character error is truncated like any other result. Errors use up context too.

## Stopping a run that won't end

- **`test_max_turns`**: three replies that each ask for another call, with `max_turns=3`. The run stops with `stop_reason == "max_turns"` after exactly 3 requests. Each call uses a different `limit`, so the loop guard below doesn't trigger first.
- **`test_max_turns_default_is_50`** reads the default from your function signature with `inspect`.
- **`test_max_turns_keeps_history_valid`**: with `max_turns=1`, the run stops right after a reply that contained a tool call. Every `tool_call` id in the history must still have a `tool_call_id` answer. Servers reject a history with an unanswered call (lesson 1), so stopping mustn't leave one behind.

## The loop guard: the same call three times in a row

**`test_loop_detection`**: the model asks for `read_file(a.txt)` three times. The solution's three tool results were:

```
'     1\thello'
'     1\thello'
'Error: you have made this exact call 3 times in a row. Try a different approach.'
```

The test also proves the third call was refused *without running the tool*. It wraps the real tool function so it can count calls:

```python
tool.fn = lambda **kw: (reads.append(kw), original(**kw))[1]   # record, then run the real one
...
assert len(reads) == 2
```

(The tuple trick runs both expressions and returns the second, so a lambda can do two things.)

The other guard tests:

- **`test_loop_detection_needs_consecutive_calls`**: A, A, B, A, A never triggers it. A different call in between resets the count.
- **`test_loop_detection_counts_within_one_reply`**: three identical calls in *one* reply also count.
- **`test_loop_detection_applies_to_failing_calls`**: the same broken call three times triggers it too. A model stuck repeating a broken call is the most common loop.

## Server errors

The fake can *raise* instead of reply. A scripted `connection_error()` or `bad_request(...)` is raised from `create`, just as the real library would.

- **`test_connection_error`**: the solution returned `TurnResult(final_text='', stop_reason='error', turns=0, ..., error='Model request failed: Connection error.')`, and the history was just `[{'role': 'user', 'content': 'hi'}]`. Then the test gives the *same* agent a working client and runs again. It works, with roles `user, user, assistant`. A failed request doesn't break the session.
- **`test_api_error_mid_session_keeps_history_valid`**: request 1 works and its tool runs; request 2 fails with a 400 "context too long". The run stops with that text in `error` and `turns == 1`, and the history ends with the `tool` message, which is still a valid history.

## The live test

`test_live_4b_failures` (run with `--live`) points at **Ollama** with the small `qwen3:4b-instruct`. A small model is chosen because it's the kind that makes the mistakes this lesson handles. It runs three prompts and prints every call. The only assertion is that each run ends with one of the three stop reasons.

The 4B behaved well on 2026-11-12:

```
PROMPT: Which file defines compute_invoice_total? Answer with the path only.
  stop_reason=done turns=2
  CALL search({"pattern":"def compute_invoice_total","glob":"*.py"})
  RESULT 'app/billing.py:1: def compute_invoice_total(items):'
PROMPT: Read the file notes.txt and tell me what it says.
  stop_reason=done turns=2
  CALL read_file({"path":"notes.txt"})
  RESULT '     1\tremember the milk'
PROMPT: Count the lines of Python code in the project, using any tools you need.
  stop_reason=done turns=3
  CALL list_files({"pattern":"**/*.py","path":"."})
  RESULT 'app/billing.py'
  CALL search({"pattern":".*","path":".","glob":"**/*.py"})
  RESULT 'app/billing.py:1: def compute_invoice_total(items):\napp/billing.py:2:     return sum(items)'
```

Models vary from run to run. Other runs have shown invented tool names and bad arguments, which is why the test only requires that every run *ends*, and prints the rest for you to read. The third prompt is a nice example of a model improvising: there's no line-counting tool, so it searched for `.*` (every line) and counted the matches.

## If a test fails

- **An exact-message test fails:** pytest shows both strings. Compare punctuation and quotes. These messages are the model's only clue, so they're pinned word for word.
- **`test_loop_detection` fails on `len(reads) == 2`:** your guard replaces the *result* but still runs the tool. Check for the repeat before calling `dispatch`.
- **`test_max_turns_keeps_history_valid` fails:** you stop before answering the last reply's tool calls. Either run them, or don't append that assistant message.
- **A server-error test raises:** wrap the `create` call (in `_request` or `run`) and return a `TurnResult` with `stop_reason="error"`.

## Words used above

| Term | Meaning here |
|---|---|
| **validation** | Checking the arguments against the tool's JSON Schema before calling it. |
| **`JSONDecodeError`** | What `json.loads` raises on broken JSON; `.msg` is the reason. |
| **parametrize** | `@pytest.mark.parametrize` runs one test function once per input. |
| **loop guard** | Refusing the third identical call in a row. |
| **`max_turns`** | The most requests one `run` may make. |
| **`connection_error()` / `bad_request()`** | Helpers in `testing/fake_model.py` that build the real `openai` exception types for the fake to raise. |
