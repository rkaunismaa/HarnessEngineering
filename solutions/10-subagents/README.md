# Lesson 10 solution: what changed since lesson 9

This folder is the reference solution for [lesson 10](../../lessons/10-subagents/README.md). This page compares its `agent/` package with the one in [`solutions/09-plans-and-checking-work/agent/`](../09-plans-and-checking-work/agent/), file by file. For each change it says what the code does, why it's written that way, and what it's meant to show you.

To run this solution without touching your own `agent/` folder, run commands from inside this folder (`cd solutions/10-subagents`). `python -m agent` imports the `agent` package from the folder you're in. To run the lesson's tests against it: `uv run pytest lessons/10-subagents --impl solutions/10-subagents`, from the repository root.

## At a glance

| File | Lesson 9 | Lesson 10 | Status |
|---|---|---|---|
| `agent/tools/subagent.py` | | 61 lines | **new**: the `subagent` tool, which runs a second agent |
| `agent/tools/registry.py` | 119 lines | 129 lines | **changed**: `ToolRegistry.subset`, a smaller registry with only some tools |
| `agent/tools/__init__.py` | 25 lines | 39 lines | **changed**: registers `subagent` when it's given a client and model |
| `agent/__main__.py` | 156 lines | 159 lines | **changed**: builds the client, log and policy once, and shares them with the tools |
| everything else | | | unchanged |

**The loop didn't change.** A subagent is just another `Agent`, built inside a tool's function. Everything the earlier lessons built (the loop guard, permissions, context management, logging) works for it as it is.

## What lesson 9 could do, and what it couldn't

Every file the model reads stays in its history, and every later request pays for it again. A question like "which function breaks the pattern?" makes the model read half a project, and the answer is one line. Lesson 8 shrank the history *after* it filled up, by summarising and losing detail. Nothing stopped it filling up in the first place.

## What this lesson is meant to show you

1. **Context isolation.** The parent hands a question to a second agent that starts with an empty history. However much the helper reads, the parent's history gets two entries: the `subagent` call, and the helper's answer.
2. **It isn't free.** The helper makes its own requests, each carrying its own growing history. Total tokens go up; the *parent's* tokens go down. In the lesson's measurements, a question that needed reading cut the parent's prompt tokens by two to four times, while the total across both agents stayed about the same or rose. A question one `search` could answer cost more with a helper.
3. **The helper knows nothing about the conversation.** The task has to stand on its own, and the tool's description says so.
4. **A helper must not be a way around the rules.** It gets only the read tools, can't start helpers of its own, and is bound by the parent's permission policy.
5. **Composition.** A new capability built from parts you already have, with no change to the loop.

## File by file

### `agent/tools/subagent.py` (new): a second agent, inside a tool

```python
def subagent(task: str) -> str:
    nonlocal runs
    runs += 1
    agent = Agent(client, model, tools.subset(SUBAGENT_TOOLS), system=SUBAGENT_SYSTEM,
                  max_turns=SUBAGENT_MAX_TURNS,
                  permissions=permissions, workspace=workspace,
                  log=log.with_agent(f"subagent-{runs}") if log else None,
                  context=ContextManager(context_window) if context_window else None)
    result = agent.run(task)
    if result.stop_reason == "max_turns":
        return f"Subagent stopped after {SUBAGENT_MAX_TURNS} turns without finishing."
    if result.stop_reason != "done":
        return f"Error: subagent failed: {result.error or result.stop_reason}"
    return truncate(result.final_text, SUBAGENT_MAX_ANSWER)
```

**What happens when the model calls `subagent(task=...)`:** the parent's loop is in the middle of running a tool call. The tool builds a brand-new `Agent` and calls its `run(task)`, which runs a complete loop of its own, with its own requests and tool calls. When the helper answers, that answer becomes the result of the parent's tool call, and the parent's loop carries on.

**Why each part is there:**

| Setting | Value | Why |
|---|---|---|
| a **new** `Agent` for each call | | an empty history: it sees only its own system prompt and the task, none of the parent's conversation |
| `tools.subset(SUBAGENT_TOOLS)` | `read_file`, `list_files`, `search` | it can't change anything, so delegating can't be used to make changes nobody watched; and **no `subagent`**, so helpers can't start helpers |
| `system=SUBAGENT_SYSTEM` | "You are a search subagent... Answer concisely: name the files and line numbers that matter and quote only the lines needed. Do not paste whole files." | a long answer would bring the file contents back into the parent and undo the saving |
| `max_turns=SUBAGENT_MAX_TURNS` | 20 | a lower limit than the parent's 50: a search that hasn't finished in 20 requests is going badly |
| `permissions=permissions` | the parent's policy | the parent's deny rules apply to the helper, so `read_file(.env)` denied for the parent is denied for the helper too |
| `log.with_agent(f"subagent-{runs}")` | `subagent-1`, `subagent-2`, ... | the same log file, labelled, so `python -m agent log` shows parent and helper requests in the order they happened |
| `context=ContextManager(...)` | the same window | a helper reading many files can be compacted too |
| `truncate(..., SUBAGENT_MAX_ANSWER)` | 4,000 characters | if the helper ignores "answer concisely", the parent still gets a bounded result, start and end kept |

- **The client and model are the parent's.** Both agents talk to the same server and model.
- **There's no approver.** The helper only has read-only tools, which lesson 5's policy allows without asking. Only a deny rule can stop one, and that needs no approver.
- **Failures become results, as everywhere since lesson 3.** A helper that runs out of requests, or whose request fails, gives the parent a clear message. The parent can try something else, or answer from what it has.
- **The tool is `read_only=True`**, since everything it can do is read. The policy runs it without asking you.
- **`from ..loop import Agent` is inside the function** because `loop.py` imports the tools package. Importing at the top would be a circular import.
- **The description tells the parent when to use it** ("questions like 'find where X is defined' that would otherwise fill your history") and the one rule that matters most: "Describe the task completely: the helper cannot see this conversation."

### `agent/tools/registry.py` (changed): `subset`

```python
def subset(self, names: Iterable[str]) -> "ToolRegistry":
    sub = ToolRegistry()
    for name in names:
        tool = self.get(name)
        if tool is not None:
            sub.register(tool)
    return sub
```

A new registry with only the named tools. The `Tool` objects are **shared, not copied**, so the helper's `read_file` is the parent's `read_file`, working in the same `Workspace`, with the same read tracker and the same path check. Unknown names are skipped, and the original registry is unchanged.

### `agent/tools/__init__.py` (changed): registering it

`make_default_tools` takes new keyword arguments: `client`, `model`, `log`, `context_window` and `permissions`. **The `subagent` tool is only added when `client` and `model` are given**, because the helper needs them to make its own requests. Every earlier test calls `make_default_tools(ws)` without them, and gets exactly the lesson 9 tool set.

`make_subagent_tool` is passed the registry itself, after the other seven tools are in it. That's what `subset` picks from.

### `agent/__main__.py` (changed): one client, one log, one policy

```python
client = make_client(config)
log = RequestLog.for_session(config.log_dir)
permissions = PermissionPolicy(allow=args.allow)
tools = make_default_tools(ws, client=client, model=config.model, log=log,
                           context_window=config.context_window, permissions=permissions)
```

These three used to be created inside the `Agent(...)` call. Now they're made first, because the tools need them too, and the **same objects** go to both the tools and the parent `Agent`:

- **one client**: one connection to the server;
- **one log**: one file, with every agent's requests in order;
- **one policy**: an "always" you give the parent also applies to the helper, and so does a deny rule.

## What's still missing, and which lesson adds it

| Gap in this version | What goes wrong | Fixed in |
|---|---|---|
| The parent decides when to delegate | a model may delegate easy questions (pure overhead) or never delegate at all | by design: the model chooses |
| Helpers run one at a time | two independent searches can't run side by side | not in this course |
| Helpers can only read | no helper to make edits or run tests | by design, for safety |
| No way to run many tasks unattended and compare results | — | lesson 11 |

## Seeing it work

From inside this folder:

```
uv run python ../../scripts/make_fixture.py scratch /tmp/scratch10
uv run python -m agent ask "Use the subagent to find which file defines compute_invoice_total, and tell me the line." --root /tmp/scratch10
uv run python -m agent log
```

The log shows `[main]` and `[subagent-1]` entries interleaved: the parent's request that called `subagent`, the helper's requests, then the parent's request with the helper's answer. The lesson's README has the token measurements with and without a helper. [TESTING.md](../../lessons/10-subagents/TESTING.md) walks through four requests of one scripted run, showing that the file's text reaches the helper and never the parent.
