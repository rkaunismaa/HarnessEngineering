# How the lesson 1 tests work

Lesson 1 uses the same machinery as lesson 0 (see [lesson 0's TESTING.md](../00-setup/TESTING.md)): `--impl` to pick the package and `FakeClient` for scripted replies. Two things are new. A script now has several replies, one per trip around the loop. And the tests look at the messages your loop sends on the second request, not just the first. Against the reference solution: 22 passed, 1 skipped (the live test).

```
uv run pytest lessons/01-the-loop                               # your agent/
uv run pytest lessons/01-the-loop --impl solutions/01-the-loop  # the reference solution
```

There are two test files: `test_loop.py` covers the loop and the `read_file` tool, and `test_log.py` covers the request log.

## The setup helper

```python
def make_agent(tmp_path, script, **kwargs):
    ws = Workspace(tmp_path)
    client = FakeClient(script)
    return Agent(client, "m", make_default_tools(ws), **kwargs), client
```

Only the model is fake. The tools are real: `read_file` really reads files, inside a `Workspace` rooted at pytest's `tmp_path`. A test writes a file there, scripts the model to ask for it, and your loop really opens it.

The helper returns the client too, so the test can look at `client.requests` afterwards.

## The main test: one full round trip

```python
def test_single_tool_round_trip(tmp_path):
    (tmp_path / "a.txt").write_text("hello\n")
    agent, client = make_agent(tmp_path, [
        reply(tool_calls=[call("read_file", {"path": "a.txt"})]),   # reply to request 1
        reply(content="It says hello"),                             # reply to request 2
    ])
    result = agent.run("what is in a.txt?")
```

Inside `agent.run`, this is what happens:

1. Your loop appends the user message and sends **request 1**. The fake records it and returns the first scripted reply, which asks for `read_file(a.txt)`.
2. Your loop appends that assistant message to the history and runs the tool for real, getting `"     1\thello"`. It appends `{"role": "tool", "tool_call_id": "call_1", "content": ...}`.
3. There was a tool call, so it loops and sends **request 2**. The fake returns "It says hello", which has no tool calls, so the loop stops.

Then the test checks the result and what was sent:

```python
    assert result.final_text == "It says hello"
    assert result.turns == 2                      # two requests
    assert client.requests[1]["messages"][-1] == {
        "role": "tool", "tool_call_id": "call_1", "content": "     1\thello"}
```

That last check is the key one: the last message in request 2 must be the tool result, with the matching id and the numbered-line content.

`FakeClient` saves a *deep copy* of each request's arguments. This matters because your loop keeps adding to the same `self.messages` list. Without the copy, `client.requests[0]["messages"]` would change after the fact and show the whole later conversation.

## What each group of tests pins down

**The request shape**

- **`test_request_shape`**: the system prompt is message 0, then the user message, with `model` and `tools` included.
- **`test_no_sampling_keys_by_default`**: with no sampling given, `temperature`, `top_p` and `seed` aren't in the request at all. The server's own defaults then apply.
- **`test_sampling_sent_on_every_request`**: a two-reply script with `sampling={...}`. The check loops over *both* requests, so it catches code that only adds the settings to the first one.

**The loop's control flow**

- **`test_two_tool_calls_in_one_reply`**: one reply holds two calls. The last three messages of request 2 must be the assistant message with both calls, then two `tool` messages in order, each with its own id (`call_1`, `call_2`; the fake numbers them automatically).
- **`test_no_tool_call_ends_turn`**: a text reply ends the turn after exactly one request. If your loop asked again, the fake would fail with "ran out of scripted responses".
- **`test_none_content_with_no_tools`** and **`test_empty_content_with_no_tools`**: servers send either `None` or `""` for "no text". Both must give `final_text == ""`.

**What goes into the history**

- **`test_reasoning_not_in_history`**: the scripted reply carries `reasoning_content`, and none of the stored messages may contain it. Qwen-style chat templates don't expect earlier reasoning to be sent back.
- **`test_assistant_message_with_tool_calls_is_plain_dict`**: the stored assistant message must be a plain dict with exactly this shape, not an SDK object. Its arguments stay a JSON *string*. It also checks a missing file: the tool result is `"Error: file not found: missing.txt"` rather than an exception. A tool error is something to tell the model, not a reason to crash the loop.
- **`test_usage_summed`**: the token counts from both replies are added up (100 + 100 prompt tokens, 20 + 20 completion tokens).
- **`test_history_persists_across_runs`**: calling `run` twice on the same `Agent` sends `["first", "one", "second"]` in request 2. Keeping the history is what makes it a conversation.

**The tool on its own (no model at all)**

- **`test_read_file_offset_limit`** calls `tools.dispatch(...)` directly with arguments as a JSON string, the way the model would send them, and checks the line-numbered slice.
- **`test_read_file_is_read_only_and_registered`** checks the registry. The tool is flagged `read_only`, which lesson 5's permissions use. The schema has exactly the keys the OpenAI format expects.
- **`test_workspace_resolve`** checks that the workspace turns relative paths into absolute ones under its root. Lesson 2 builds on this to stop paths from escaping the root.

## `test_log.py`

These tests attach a `RequestLog` to the agent, run a scripted conversation, and then read the JSONL file back:

- **`test_log_written`**: one line per request, two in this case. Each line has `request.messages`, `response.choices`, `agent: "main"`, `duration_s` and `ts`, and no `client` object leaked into the request.
- **`test_log_keeps_reasoning`**: reasoning is left out of the history but *kept* in the log. The log is where you go to see what the model was thinking.
- **`test_with_agent_shares_file`**: a log made with `log.with_agent("explorer")` writes to the same file, with a different `agent` label. Lesson 10's subagents use this.
- **`test_for_session_creates_timestamped_file`** and **`test_latest_log_picks_newest`**: the file naming. The newest log is chosen by *filename*, not file time; the test deliberately makes the two disagree.
- **`test_format_entry_shows_tool_calls`** checks the readable formatter.
- **`test_log_subcommand_prints_entries`** runs your command line as a function, `main(["log", path])`, and uses pytest's `capsys` to capture what it prints. Any subcommand can be tested this way without starting a new process.

## The live test

`test_live_read_file` (run with `--live`) writes `secret.txt` containing "The magic word is pineapple." It asks the real model through your real loop and checks that "pineapple" is in the answer. This is the first test where a model has to use a tool result to answer, which `smoke` never needed.
