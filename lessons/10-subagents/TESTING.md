# How the lesson 10 tests work

The key to lesson 10's tests is that the parent agent and its subagent **share one `FakeClient`**. Every request either of them makes takes the next reply from the same script. So one script describes the whole run, parent and helper turns interleaved in the order they happen, and `client.requests` shows every request from both. The tests use that to check what each one sent, and that nothing leaked between them. Against the reference solution: 11 passed, 1 skipped (the live test).

```
uv run pytest lessons/10-subagents
uv run pytest lessons/10-subagents --impl solutions/10-subagents
```

## Reading a script

```python
def delegate(task="find the parser"):
    return reply(tool_calls=[call("subagent", {"task": task})])

script = [delegate(),                   # request 0: parent -> calls subagent
          reply(content="found"),       # request 1: subagent -> answers at once
          reply(content="ok")]          # request 2: parent -> final answer
```

Inside the parent's tool call, the subagent runs its *own* loop with the same client. It uses up replies until it gives an answer with no tool calls. Then the parent's loop continues with the next reply. `make(...)` builds the tools with `client=` and `model=`, which is what turns the `subagent` tool on.

## The tool set

- **`test_registry_subset`**: `tools.subset([...])` returns a new registry with only the names you list. Unknown names are skipped. The `Tool` objects are *shared*, not copied, and the original registry is unchanged. That's how the subagent gets a read-only toolbox.
- **`test_subagent_registered_only_with_client`**: without a client there is no `subagent` tool. With one, it exists and is `read_only`, since it can only use read tools.
- **`test_subagent_gets_only_read_tools`** looks at all three requests. The parent's first request offers `subagent`. The subagent's request offers exactly `SUBAGENT_TOOLS`, with no `bash`, no edits and no `subagent`, so helpers can't start more helpers. The parent's next request still offers everything.

## Separate contexts

- **`test_subagent_fresh_context`**: the parent already has an earlier exchange in its history. The subagent's first request has exactly **two** messages: its own system prompt and the task, word for word. None of the parent's conversation is sent. That's the point of a subagent: it starts with an empty context.
- **`test_parent_sees_only_answer`** is the main test. The script is: parent delegates, subagent reads `a.py`, subagent answers, parent answers. It checks both directions:
  - The parent's history has **one** tool result, the subagent's answer. The text of `a.py` (`def parse`) appears nowhere in the parent's messages.
  - The subagent *did* read it: `def parse` is in request 2, which belongs to the subagent.
  - The parent's `turns == 2`. The subagent's requests don't count against the parent.

  This is the context saving in action: the parent pays for one short answer instead of every file the helper read.

## Logging, limits and errors

- **`test_subagent_log_tag`**: two delegations in one run produce log entries tagged `main, subagent-1, main, subagent-2, main`. They all go to one file, so `python -m agent log` shows the whole run in order, with each helper numbered. This uses the `with_agent` method lesson 1 tested.
- **`test_subagent_max_turns_message`**: the subagent keeps calling `list_files` until it hits `SUBAGENT_MAX_TURNS`. The parent gets the result `Subagent stopped after N turns without finishing.` The request count is exactly 1 + N + 1, so the limit is enforced precisely.
- **`test_subagent_answer_truncated`**: a 10,000-character answer is cut to about `SUBAGENT_MAX_ANSWER`, keeping the start and the end. An overly long helper answer would undo the context saving.
- **`test_subagent_error`**: the subagent's request fails with a connection error. The parent gets the tool result `Error: subagent failed: ...` and carries on to its own answer. The helper's failure is reported to the parent model, and the parent's run continues.
- **`test_subagent_empty_task_is_a_schema_error`**: `{}` is rejected by lesson 3's validator before any helper starts.

## Permissions carry over

**`test_subagent_obeys_parent_deny_rules`**: the parent's policy denies `read_file(.env)`, and the subagent tries to read `.env`. The result it gets (the last message of request 2) is `Error: this call is blocked by a deny rule.`, and `hunter2` never appears anywhere. Without this, delegating to a helper would be a way around every deny rule. The tools are built with `permissions=policy` so the subagent tool can pass the policy on.

## The live test

`test_live_subagent_search` (run with `--live`) builds a three-file project and asks the 27B to *use the subagent* to find `frobnicate_widget`. It prints how many subagent calls were made, and passes if `helpers.py` is in the answer. The log is written next to the temporary folder, so you can inspect the interleaved `main` and `subagent-1` entries afterwards with `python -m agent log <file>`.
