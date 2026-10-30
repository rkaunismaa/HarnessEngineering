# Lesson 10: Subagents

Start from your lesson 9 code, or copy `solutions/09-plans-and-checking-work/agent` into `agent/`.

## Why this exists

Every file the model reads stays in its history, and every later request pays for it again. A question like "which function breaks the pattern?" makes the model read half a project, and the answer is one line. Lesson 8 shrank the history after the fact. A subagent avoids filling it in the first place: the parent hands the question to a second agent that has its own empty history, and only that agent's final answer comes back.

That is **context isolation**. The parent's history gets two entries, the `subagent` call and its answer, however much the helper read.

It is not free. The helper still makes its own requests, each carrying its own growing history, and it starts with no knowledge of the conversation, so the task you give it must stand alone. Total tokens go up; the parent's tokens, and the parent's chance of running out of window, go down. Whether that trade is worth it depends on the task.

Measured on the 27B (LM Studio), a project of 8 modules with 25 small functions each (about 200 lines per file), parent `prompt_tokens` summed from the request log. Two runs per cell; the numbers vary run to run because the model chooses its own tool calls.

| task | | parent prompt tokens | helper prompt tokens | total |
|---|---|---|---|---|
| "Find where `compute_invoice_total` is defined." (one `search` finds it) | without `subagent` | 3,159 / 4,937 | none | 3,159 / 4,937 |
| | with `subagent` | 5,637 / 5,682 | 2,804 / 2,738 | 8,441 / 8,420 |
| "One function breaks the pattern `total = a + b * N`; which one?" (the model must read files) | without `subagent` | 35,653 / 15,692 | none | 35,653 / 15,692 |
| | with `subagent` | 9,065 / 7,481 | 30,135 / 39,964 | 39,200 / 47,445 |

- When one `search` call answers the question, delegating is pure overhead: the parent's own count went up, because it still made a request to call the helper and another to read the answer, and the helper paid for its own system prompt and requests on top.
- When the answer needs reading, the parent's count fell by a factor of two to four (35,653 to 9,065; 15,692 to 7,481) and its history stayed small. The total across both agents was about the same or higher (35,653 vs 39,200; 15,692 vs 47,445). You pay for isolation in total tokens and in time.
- Two runs per cell is an illustration, not a benchmark. The spread is large (35,653 vs 15,692 for the same unaided task), because one run read more files than the other.

### Why the helper gets fewer tools

The helper gets `read_file`, `list_files` and `search` only: no `edit_file`, `write_file`, `bash`, `todo_write`, or `subagent`.

- **Safety.** Its tool calls run without the permission checks and prompts the parent uses (it is built without a `PermissionPolicy` or approver). That is only acceptable because every tool it has is read-only.
- **No runaway recursion.** A helper that can start helpers can spend unbounded requests. Without `subagent` in its set the depth is exactly one.
- **No hidden side effects.** The parent sees only an answer. If the helper had changed a file, nothing in the parent's history would say so.
- **Focus.** A model with three tools and a short system prompt picks among three tools. Fewer choices is also a small-model reliability feature.

## How Claude Code does it

- **Observed**: Claude Code has an Agent tool that starts a subagent of a named type. The types include a read-only "Explore" agent for searching a codebase, a general-purpose agent, and a "Plan" agent. Each runs with its own context and hands back a final report to the main conversation. (Seen in use; the tool's exact name and parameters can differ between versions.)
- **Documented** ([Sub-agents](https://code.claude.com/docs/en/sub-agents), checked): custom subagents are Markdown files with YAML frontmatter, stored in `.claude/agents/` for a project or `~/.claude/agents/` for all projects. The frontmatter has a required `name` and `description` ("when Claude should delegate to this subagent") and optional fields such as `tools`, `disallowedTools`, `model` and `maxTurns`; the Markdown body is the subagent's system prompt. The same page says each subagent "runs in its own context window with a custom system prompt, specific tool access, and independent permissions", and describes the built-in Explore subagent as "a fast, read-only agent optimized for searching and analyzing codebases".
- **Design note**: your `subagent` has one fixed type, a read-only searcher. Claude Code lets you define many, with their own prompts, tool lists and models. The idea you build is the same: fresh history, restricted tools, a final answer as the only thing that returns.

## What you'll build

New: `agent/tools/subagent.py`. Changed: `agent/tools/registry.py`, `agent/tools/__init__.py`, `agent/__main__.py`. Tests: `lessons/10-subagents/tests/`.

**`ToolRegistry.subset(names: Iterable[str]) -> ToolRegistry`**: a new registry holding only the named tools, in the order given. Names that do not exist are skipped silently. The `Tool` objects are shared with the original, not copied, so the helper's `read_file` uses the same `Workspace` and `FileTracker` as the parent's. The original registry is unchanged.

**`agent/tools/subagent.py`**:
- `SUBAGENT_TOOLS = ("read_file", "list_files", "search")`, `SUBAGENT_MAX_TURNS = 20`, `SUBAGENT_MAX_ANSWER = 4000`.
- `make_subagent_tool(client, model: str, tools: ToolRegistry, *, log: RequestLog | None = None, context_window: int | None = None) -> Tool`. The tool is named `subagent`, takes one required string `task`, and has `read_only=True` (it asks nothing of the user itself; the helper's tools are all read-only).
- Each call builds a fresh `Agent` with `tools.subset(SUBAGENT_TOOLS)`, `max_turns=SUBAGENT_MAX_TURNS`, and no `permissions`, `approver`, `events`, `stream`, `verify` or `workspace`. With `context_window` given it also gets its own new `ContextManager(context_window)`; otherwise no context manager.
- Its system prompt is this text exactly:
  > You are a search subagent. You can only read: you have read_file, list_files and search, and you cannot change anything. Find the answer to the task you are given. Answer concisely: name the files and line numbers that matter and quote only the lines needed. Do not paste whole files.
- Its history is `[system, user(task)]` and nothing else: two messages in its first request. The parent's conversation is not passed.
- With a `log`, the helper logs through `log.with_agent(f"subagent-{k}")`, where `k` counts from 1 per tool instance (per `make_subagent_tool` call), so the second delegation in a session is `subagent-2` in `python -m agent log`.
- Results:
  - `stop_reason == "done"`: `truncate(final_text, SUBAGENT_MAX_ANSWER)`.
  - `"max_turns"`: `f"Subagent stopped after {SUBAGENT_MAX_TURNS} turns without finishing."`
  - anything else: `f"Error: subagent failed: {error}"`, with the `Agent`'s own error message.
- The parent's registry still applies its usual validation: a call without `task` gives `Error: missing required parameter 'task'`.
- Import `Agent` inside `make_subagent_tool`, not at the top of the module. `loop.py` imports the `tools` package, and `tools/__init__.py` imports this module, so a top-level import is circular.

**`make_default_tools(ws, *, confirm_bash=None, client=None, model=None, log=None, context_window=None)`**: registers `subagent` only when both `client` and `model` are given. It is registered last, and the helper's tool set comes from the registry as it is when called.

**CLI**: `_build_agent` creates the client and the request log once and passes `client`, `model`, `log` and `context_window=config.context_window` to `make_default_tools`, so `ask` and `chat` offer `subagent` and the log shows both agents' requests in one file.

The tool description is what makes the model use it. Say what it is for (searches that would otherwise fill the history), that it can only read, and that it cannot see the conversation, so the `task` must be complete.

## Tests

```
uv run pytest lessons/10-subagents --impl agent-or-solution-dir
```

For the reference solution: `uv run pytest lessons/10-subagents --impl solutions/10-subagents`. The subagent's requests come from the same scripted client as the parent's, in order: a script reads parent, helper, ..., parent, and the tests assert on `client.requests` by position. `test_live_subagent_search` needs `--live`: the 27B is asked to use `subagent` to find where a function is defined and the answer must name the right file. On the reference solution it used one delegation and finished in two parent requests.

## Try it live

Make a project with a few larger files and ask something that needs reading:

```
uv run python -m agent ask --root ../some-project "Use the subagent tool to find which module defines a function that does X, then tell me the module."
uv run python -m agent log
```

In the log, the lines tagged `[main]` are the parent and `[subagent-1]` the helper. Compare the `prompt=` numbers: the parent's stay small. Run it again without mentioning the subagent and see whether the model delegates by itself (in the runs above it searched directly).

## Break it

Use the 4B (`AGENT_BASE_URL=http://localhost:11434/v1 AGENT_MODEL=qwen3:4b-instruct`) on the "which function breaks the pattern" project above, with the prompt ending "Use the subagent tool for the search." Read the log: does it call `subagent`, does the `task` stand alone, and is the answer right?

What happened in three runs: the 4B did call `subagent` every time, with the parent making 3, 3 and 8 requests (5,047 to 30,878 parent prompt tokens). In at least two of the three runs the final answer said no function broke the pattern, which is wrong (`func_5_13` in `module_5.py`). The harness did its part, but a helper's answer is only as good as the helper's model, and the parent trusts it: one run kept reading files itself after the helper reported, which is how it reached 30K. Isolation protects the parent's context, not the parent's judgment. Try rewording the tool description to ask for evidence (file, line, quoted code) and see whether the answers become checkable.

## Extras

- Let the parent pick a type of helper: add a second tool set with `bash` for a "run the tests and report" helper (then it needs a permission policy).
- Run two helpers at once with threads and give each a different question.
- Give the helper a smaller `max_turns` and see what a too-small budget does to answers.
- Let the helper take `context_window` from the parent's `ContextManager` and see when it compacts.
