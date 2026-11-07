# How the lesson 3 tests work

Lesson 3's tests deliberately feed your harness bad input: a call to a tool that doesn't exist, broken JSON, wrong argument types, a tool that crashes, a model that repeats itself forever, and a server that goes away. Every test checks the same promise: the harness turns the problem into a clear message for the model, or stops cleanly, and the history stays valid. Against the reference solution: 27 passed, 1 skipped (the live test). The count includes four runs of one parametrized test.

```
uv run pytest lessons/03-when-the-model-gets-it-wrong
uv run pytest lessons/03-when-the-model-gets-it-wrong --impl solutions/03-when-the-model-gets-it-wrong
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

`small_registry` builds a registry with one made-up tool, `add`, with a known schema. That lets the validation tests use exact error messages without depending on your real tools. Passing `fn` swaps in a function that crashes.

`make_agent` is the same as in lesson 1. `tool_results(agent)` pulls the content of every `tool` message out of the history, in order.

## Errors in `dispatch`: each one becomes a message

All of these call `registry.dispatch(name, raw_json)` directly and compare the exact returned string:

| Test | Input | Expected result |
|---|---|---|
| `test_unknown_tool` | tool `nope` | `Error: unknown tool 'nope'. Available tools: add` |
| `test_unknown_tool_lists_all_names` | `grep` on the real registry | the same message, listing *all* your tools |
| `test_bad_json`, `test_bad_json_exact_message` | `{"a": 1,` and `{nope` | `Error: arguments were not valid JSON (<reason>). Send the arguments as a JSON object.` |
| `test_arguments_not_object` (×4) | `[1, 2]`, `"text"`, `3`, `null` | `Error: arguments must be a JSON object.` |
| `test_missing_required` | `{}` | `Error: missing required parameter 'a'` |
| `test_wrong_type` | `{"a": "5"}` | `Error: parameter 'a' must be integer` |
| `test_bool_is_not_integer` | `{"a": true}` | the same; in Python `True` is an `int`, so this needs a special case |
| `test_unknown_param` | `{"a": 1, "c": 2}` | `Error: unknown parameter 'c'` |
| `test_several_errors_joined` | `{"b": "x", "c": 1}` | all three problems, joined with `; ` |
| `test_tool_exception` | `add` raises `RuntimeError("disk on fire")` | `Error: RuntimeError: disk on fire` |

Some details worth noticing:

- **Listing the available tools** in the unknown-tool error gives the model what it needs to correct itself. Small models often invent `grep` or `cat`.
- **`test_bad_json_exact_message`** doesn't hard-code the parser's wording. It runs `json.loads("{nope")` itself, catches the error, and builds the expected text from `info.value.msg`. The test then holds even if Python's wording changes.
- **`test_several_errors_joined`** pins the order: missing, then unknown, then wrong type. Reporting every problem at once saves the model a round trip per mistake.
- **`test_validate_args_types`** tests the `validate_args(schema, args)` helper directly for all six JSON types. It covers the tricky cases: an `int` counts as a `number`, but `True` doesn't, and `0` is not a `boolean`.

Two further checks:

- **`test_dispatch_never_raises_on_real_tools`** throws odd but plausible arguments at the real tools: an empty glob, `/etc/*`, `../outside`, `.`, a missing folder. It only asserts that each result is a string. The exact text doesn't matter here; what matters is that nothing escapes as an exception.
- **`test_error_results_are_truncated`**: a 50,000-character exception message still goes through truncation. Errors take up context too.

## The loop: errors reach the model and it recovers

**`test_error_fed_back_and_model_recovers`** uses a three-reply script:

1. A call with broken JSON (`'{"path": "a.txt"'`, missing its closing brace).
2. The same call, fixed.
3. The answer.

It checks two things. The first tool result is the JSON error and the second is the file content. And `client.requests[1]["messages"][-1]` is exactly that error message: it went back to the model as an ordinary `tool` message. That is the whole recovery mechanism. The model sees what went wrong and tries again.

## Stopping a run that won't end

- **`test_max_turns`**: three replies that each ask for another tool call, with `max_turns=3`. The run stops with `stop_reason == "max_turns"` after exactly 3 requests. Each call uses a different `limit`, so the loop guard below doesn't trigger first.
- **`test_max_turns_default_is_50`** reads the default from your function's signature with `inspect`.
- **`test_max_turns_keeps_history_valid`**: with `max_turns=1`, the run stops right after the first reply, which contained a tool call. The test collects every `tool_call` id and every `tool_call_id` answer in the history, and requires the two lists to be equal. Servers reject a history in which a tool call has no answer, so stopping must not leave one behind.

## The loop guard: the same call three times in a row

- **`test_loop_detection`**: the model asks for `read_file(a.txt)` three times, then gives up. The test wraps the real tool's function so it can count how often the tool *actually* ran:
  ```python
  tool.fn = lambda **kw: (reads.append(kw), original(**kw))[1]
  ```
  The first two results are the file content. The third is the loop message, and `len(reads) == 2`: the third call was refused without running the tool.
- **`test_loop_detection_needs_consecutive_calls`**: the sequence A, A, B, A, A never triggers the guard. A different call in between resets the count.
- **`test_loop_detection_counts_within_one_reply`**: three identical calls inside *one* reply also count.
- **`test_loop_detection_applies_to_failing_calls`**: the same broken-JSON call three times also triggers it. A model stuck repeating a broken call is the most common loop.

## Server errors

- **`test_connection_error`** scripts an exception (`connection_error()`) instead of a reply. The fake *raises* it from `create`, just as the real SDK would. The run returns `stop_reason == "error"` with `error` starting `Model request failed: `, and the last message in the history is still the user's. Then the test swaps in a working client on the *same* agent and runs again. It must work, with roles `user, user, assistant`. A failed request doesn't break the session.
- **`test_api_error_mid_session_keeps_history_valid`**: the first request works and its tool runs. The second request fails with a 400 "context too long" (`bad_request(...)`). The run stops with the error text, `turns == 1`, and the history ends with the `tool` message, which is still a valid history.

## The live test

`test_live_4b_failures` (run with `--live`) points at **Ollama** with the small `qwen3:4b-instruct`, not LM Studio. That model is chosen because it makes the mistakes this lesson handles. It runs three prompts and prints every call and result. The only assertion is that each run ends with one of the three stop reasons; it never crashes.

This test exists for you to read the output: use `-s` to see the printed calls and results.

```
uv run pytest lessons/03-when-the-model-gets-it-wrong --live -s -k 4b
```
