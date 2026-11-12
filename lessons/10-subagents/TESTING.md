# How the lesson 10 tests work

Against the reference solution: 11 passed, 1 skipped (the live test). The live test passes too with `--live` (9.4 s against the 27B).

```
uv run pytest lessons/10-subagents
uv run pytest lessons/10-subagents --impl solutions/10-subagents
uv run pytest lessons/10-subagents --live -s -k live
```

## The big picture

A **subagent** is a second agent the main agent can start, through a tool called `subagent`, to do one search task. The helper:

- **starts with an empty history** (just its own system prompt and the task);
- **gets only the read tools** (`read_file`, `list_files`, `search`);
- **runs its own loop** until it has an answer;
- **returns only that answer**, which becomes the result of the parent's tool call.

The point is context. The helper might read ten files, but the parent pays only for a few lines of answer.

The tests rely on one trick: **the parent and the subagent share one `FakeClient`.** Every request either of them makes takes the next reply from the same script, and every request lands in the same `client.requests` list. So one script describes the whole run, parent and helper turns interleaved in the order they happen. The test can then look at each request and say whose it was and what it contained.

```
 script position   who asks     what the scripted reply says
 ---------------   --------     ----------------------------
 reply 0           parent   ->  "call subagent(task=...)"
 reply 1           subagent ->  "call read_file(a.py)"          <- the subagent's own loop
 reply 2           subagent ->  "parse is defined in a.py line 1"   (no tool calls: helper done)
 reply 3           parent   ->  "It is in a.py"                 <- parent's loop continues
```

## Reading a script

```python
def delegate(task="find the parser"):
    return reply(tool_calls=[call("subagent", {"task": task})])

def make(tmp_path, script, log=None):
    ws = Workspace(tmp_path)
    client = FakeClient(script)
    tools = make_default_tools(ws, client=client, model="m", log=log)
    return Agent(client, "m", tools, workspace=ws, log=log), client
```

`make_default_tools` only adds the `subagent` tool when it's given a `client` and `model`, because the helper needs them to make its own requests. Note that the *same* `client` goes to both the tools and the parent `Agent`.

## One test, step by step: `test_parent_sees_only_answer`

```python
def test_parent_sees_only_answer(tmp_path):
    (tmp_path / "a.py").write_text("def parse():\n    pass\n")
    script = [delegate(),
              reply(tool_calls=[call("read_file", {"path": "a.py"})]),
              reply(content="parse is defined in a.py line 1"),
              reply(content="It is in a.py")]
    agent, client = make(tmp_path, script)
    result = agent.run("go")
```

When the same script ran against the reference solution (with the task `"where is parse() defined?"`), `client.requests` held four requests:

```
request 0: 1 msgs  roles=['user']                                tools = all 8 (incl. subagent)   <- parent
request 1: 2 msgs  roles=['system', 'user']                      tools = read_file, list_files, search  <- subagent
request 2: 4 msgs  roles=['system', 'user', 'assistant', 'tool'] tools = read_file, list_files, search  <- subagent
request 3: 3 msgs  roles=['user', 'assistant', 'tool']           tools = all 8                    <- parent
```

**Request 0, the parent.** The parent sends `go` with all eight tools. The reply asks for `subagent(task="where is parse() defined?")`.

**The `subagent` tool runs.** It builds a *new* `Agent` with the same client, the read-only tools, and this system prompt:

```
You are a search subagent. You can only read: you have read_file, list_files and search, and you
cannot change anything. Find the answer to the task you are given. Answer concisely: name the files
and line numbers that matter and quote only the lines needed. Do not paste whole files.
```

Then it calls `helper.run(task)`. The parent's loop is waiting inside its tool call while this happens.

**Request 1, the subagent.** It sends just two messages: its system prompt and the task. None of the parent's conversation is included. The reply asks for `read_file(a.py)`, which runs and returns the file's text, including `def parse():`.

**Request 2, the subagent.** Four messages, including the file text. The reply is `parse is defined in a.py line 1`, with no tool calls, so the helper's loop ends. That text is returned as the result of the parent's `subagent` tool call.

**Request 3, the parent.** Three messages: `go`, its own `subagent` call, and that one-line result. The reply is `It is in a.py`, and the run ends. The parent's whole history:

```json
{"role": "user", "content": "go"}
{"role": "assistant", "content": null, "tool_calls": [{"id": "call_1", ... "subagent", "{\"task\": \"where is parse() defined?\"}"}]}
{"role": "tool", "tool_call_id": "call_1", "content": "parse is defined in a.py line 1"}
{"role": "assistant", "content": "It is in a.py"}
```

The test checks both directions:

```python
    assert result.final_text == "It is in a.py"
    tool_msgs = [m for m in agent.messages if m["role"] == "tool"]
    assert [m["content"] for m in tool_msgs] == ["parse is defined in a.py line 1"]   # only the answer
    assert not any("def parse" in json.dumps(m) for m in agent.messages)            # never the file
    assert result.turns == 2                                                        # parent's requests only
    assert any("def parse" in json.dumps(m) for m in client.requests[2]["messages"])  # but the helper read it
```

The file's text is in the subagent's request 2 and nowhere in the parent's history. That's the context saving, proven.

## What each test pins down

### The tool set

- **`test_registry_subset`**: `tools.subset([...])` returns a new registry with only the listed names, skipping unknown ones. The `Tool` objects are *shared*, not copied, and the original registry is unchanged.
- **`test_subagent_registered_only_with_client`**: no client means no `subagent` tool. With one, the tool exists and is `read_only`, since it can only read.
- **`test_subagent_gets_only_read_tools`**: in the request listing above, request 1 offers exactly `SUBAGENT_TOOLS`. There's no `bash`, no edits and no `subagent`, so helpers can't start more helpers. The parent's next request still offers everything.

### Separate contexts

- **`test_subagent_fresh_context`**: the parent already has an earlier exchange in its history. The subagent's first request still has exactly two messages, its system prompt and the task word for word.

### Logging, limits and errors

- **`test_subagent_log_tag`**: two delegations in one run give log entries tagged `main, subagent-1, main, subagent-2, main`, all in one file, so `python -m agent log` shows the run in order. This uses the `with_agent` method lesson 1 tested.
- **`test_subagent_max_turns_message`**: the helper keeps calling `list_files` until it hits `SUBAGENT_MAX_TURNS`. The parent gets `Subagent stopped after N turns without finishing.`, and the request count is exactly 1 + N + 1.
- **`test_subagent_answer_truncated`**: a 10,000-character answer is cut to about `SUBAGENT_MAX_ANSWER`, keeping the start and the end. A huge helper answer would undo the saving.
- **`test_subagent_error`**: the helper's request fails with a connection error. The parent gets the tool result `Error: subagent failed: ...` and carries on to its own answer.
- **`test_subagent_empty_task_is_a_schema_error`**: `{}` is rejected by lesson 3's validator before any helper starts.

### Permissions carry over

**`test_subagent_obeys_parent_deny_rules`**: the parent's policy denies `read_file(.env)`, and the helper tries to read `.env`. The result it gets (the last message of request 2) is `Error: this call is blocked by a deny rule.`, and the secret `hunter2` appears nowhere. Without this, delegating would be a way around every deny rule. The tools are built with `permissions=policy` so the `subagent` tool can pass it on.

## The live test

`test_live_subagent_search` (run with `--live`) builds a three-file project and asks the 27B to *use the subagent* to find `frobnicate_widget`. On 2026-11-12:

```
stop=done turns=2 subagent calls=1
answer='`frobnicate_widget` is defined in **`helpers.py`** (line 5):\n\n```python\ndef frobnicate_widget():\n    return 2\n```'
```

The parent made 2 requests: one to delegate, one to answer. The helper's requests aren't counted in `turns`. The log is written next to the temporary folder, so `python -m agent log <file>` shows the interleaved `main` and `subagent-1` entries.

## If a test fails

- **"FakeClient ran out of scripted responses":** your helper used more replies than the script gives it, often because it doesn't stop on a reply with no tool calls, or because the parent didn't wait for it.
- **The helper's request includes the parent's messages:** you passed the parent's history, or reused the parent `Agent`. Build a new one.
- **`turns` is 4 instead of 2:** you added the helper's turns to the parent's.
- **The deny-rule test leaks `hunter2`:** the helper's `Agent` was built without the parent's `permissions`.

## Words used above

| Term | Meaning here |
|---|---|
| **subagent / helper** | A second `Agent` started by the `subagent` tool, with its own history and read-only tools. |
| **parent** | The main agent, whose tool call started the helper. |
| **`subset`** | A registry method returning a smaller registry with only the named tools. |
| **shared client** | One `FakeClient` used by both agents, so one script covers the whole run. |
| **`SUBAGENT_TOOLS` / `SUBAGENT_MAX_TURNS` / `SUBAGENT_MAX_ANSWER`** | Constants for the helper's tools, turn limit, and answer length. |
