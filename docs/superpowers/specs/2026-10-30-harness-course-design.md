# Course Design: Build Your Own Agentic Coding Harness

Date: 2026-10-30
Status: approved 2026-10-30

## Intent

A self-paced course, for one learner, on building an agentic coding harness
from scratch in Python: the kind of program Claude Code is. The point is
**understanding how it works from the inside**, not shipping a product. By the end
the learner has written every part of a small working coding agent themselves and knows why
each part exists.

The course was requested from Claude Code specifically, so it should draw on how
Claude Code actually behaves, and be current (late 2026) and accurate.

**Finish line:** the learner's agent, running on a local model, fixes a planted bug in a
small Python project on its own, and the learner can measure how often it succeeds.

## The learner

- Comfortable with Python. Has used LLM APIs a lot, so the course skips API basics
  and starts at the agent loop.
- Wants to write the code themselves. Lessons **describe** each piece and give a spec
  and tests; the learner writes it; reference solutions exist to check against.
- Wants to **see the raw traffic**: exactly what is sent to the model and what comes
  back. This is a core value of the course, not a nice-to-have.

## Goals

1. The learner builds a working coding agent, lesson by lesson, that ends up able to fix a
   real bug in a small Python project.
2. Each lesson teaches one part of a harness and why it exists.
3. Every request and response is visible: through LM Studio's developer log and
   through the harness's own request log (built in lesson 1).
4. Each lesson explains how Claude Code handles the same problem, labeled by how
   sure the claim is (see Accuracy policy).
5. Local-model weaknesses (bad tool calls, small context, ignored instructions) are
   treated as teaching material, not hidden.

## Non-goals

- MCP, hooks, plugins, IDE integration, a GUI. At most a short "where to go next"
  note at the end.
- Support for many providers. One OpenAI-compatible endpoint, configurable URL.
- Production-grade sandboxing (containers, seccomp profiles, network proxies). The
  course builds a small bubblewrap sandbox (lesson 5) and stops there.
- Teaching LLM API basics.

## Anti-goals (would make this a failure even if it technically works)

- **Using an agent framework** (LangChain, LlamaIndex, agent SDKs, etc.). They hide
  exactly the parts the learner is trying to learn. Only the `openai` client package talks
  to the model.
- **Stating guesses about Claude Code's internals as fact.**
- **Handing over finished code in the lesson text.** Lessons may show small snippets
  to illustrate an API shape or a format, but not the implementation the learner is meant
  to write.
- **Tests that need the live model to pass.** Lesson completion must not depend on a
  nondeterministic model. Live-model checks are separate and optional.
- Outdated content: model names, API shapes, or Claude Code behavior from a year
  ago presented as current.

## Constraints and environment (verified on the learner's machine, 2026-10-30)

- Ubuntu 22.04, Python 3.10.12 (system), `uv` available. GPUs: RTX 4090 (24 GB) and
  RTX 2070 Super (8 GB). 62 GB RAM.
- Bubblewrap (`/usr/bin/bwrap`) is installed and is the course's sandbox. Docker is
  installed too but is not used. Verified 2026-10-30: unprivileged `bwrap` with
  `--ro-bind / /` and `--unshare-net` runs, blocks writes to the home directory, and
  blocks access to localhost.
- **Main server: LM Studio**, OpenAI-compatible API at `http://localhost:1234/v1`.
  Main model: `qwen/qwen3.8-27b` (Q4_K_M, 17.7 GB), loaded with 32K context.
  LM Studio currently splits it across both GPUs (~16.6 GB / ~6.5 GB).
- **Weak test model: Ollama**, `http://localhost:11434/v1`, model
  `qwen3:4b-instruct`. Used deliberately to expose where the harness breaks.
- **Optional comparison model:** `recursivesi/flint` (40B MoE, ~2.5B active,
  released 2026-10-21, 24 GB). Does not fit on the 4090 with context; used only as
  an optional comparison in the capstone.
- A live test (2026-10-30) confirmed: the model returns proper `tool_calls` with
  `finish_reason: "tool_calls"`; `function.arguments` is a JSON **string**; the
  model's thinking arrives in a separate `reasoning_content` field; a one-line
  prompt with one tool cost 329 prompt tokens. Lessons should use these real
  observations.
- LM Studio is shipping a new separate agent app, "Bionic". Its pages do not say
  LM Studio or its server is deprecated, but the course must not depend on anything
  LM Studio-specific beyond the OpenAI-compatible endpoint and its developer log.
  Switching servers is a config change.
- Model, base URL, and API key (a dummy string for local servers) come from config
  (env vars, optionally a small config file). No hard-coded model names in the learner's
  code paths.

## Decided by the learner

- Audience: just the learner.
- Purpose: understanding from the inside.
- Language: Python.
- Local model via LM Studio as the main server (because they can watch traffic there),
  with Ollama for the weak 4B model.
- Model: Qwen3.8-27B.
- Lesson style: described, not given; the learner writes it; reference solutions provided.
- Capstone: agent fixes a bug in a small Python project.
- The lesson outline below.
- Location: this folder, git-initialized; this document at this path.
- Sandboxing: lesson 5 builds a bubblewrap sandbox for the `bash` tool, and the
  capstone's unattended runs use it.

## Claude's calls (the learner can override)

- `openai` Python package (2.x) as the only model client.
- `uv`-managed project venv; dependencies kept minimal: `openai`, `pytest`, `rich`
  (terminal output). Anything else needs a reason in the lesson.
- Request logging starts in lesson 1, not later.
- Hooks and MCP are left out.
- The 27B is the default; the 4B shows up as a "break it" experiment in lessons.

## Course outline

| # | Lesson | Learner builds | Key ideas |
|---|--------|-----------|-----------|
| 0 | Setup | Config loading; a smoke test that the server answers and makes a tool call | What a harness is: model + loop + tools + context + permissions. OpenAI-compatible endpoints. Where LM Studio's developer log is. |
| 1 | The loop | Send messages, run requested tool calls, append results, repeat until the model stops. One tool: `read_file`. Request log: every request and response written to a file (JSONL), plus a small command to view a session's log. | Message roles, `tool_call_id` pairing, `finish_reason`. Compare your log with LM Studio's log: the server turns messages + tools into one prompt via the chat template. |
| 2 | Tools | `list_files`/glob, `search` (grep), `bash` (with timeout). A tool registry: name, description, JSON schema, function. Output truncation. | Writing tool descriptions the model follows. Why tool output must be capped. Fixed token cost of tool definitions. |
| 3 | When the model gets it wrong | Validation of tool calls; errors fed back to the model as tool results; a max-turns limit; loop detection (same call repeated). | Malformed JSON args, unknown tools, missing params, infinite loops. Run against the 4B and catalog the failures from the logs. |
| 4 | Editing files | `edit_file` (exact find-and-replace; must match exactly once), `write_file`; require a file to have been read before it is edited; detect the file changing since it was read. | Why exact-match edits beat whole-file rewrites (cost, safety, reviewability). |
| 5 | Permissions and sandboxing | Approval prompts before risky tools; allow rules (e.g. by tool, by command prefix); "yes / yes always / no"; keep file tools inside the project folder. A bubblewrap sandbox for the `bash` tool: the filesystem is visible read-only, only the project folder (and a temp dir) is writable, network optionally cut off. A setting turns the sandbox on/off. | Read-only vs. mutating tools. Why prefix rules alone can't make bash safe (pipes, `&&`, scripts the agent writes). Why OS-level sandboxing is the real answer; what bubblewrap does and doesn't protect against. Tests must be able to check the sandbox's command construction without bwrap, plus a few marked tests that really run bwrap. |
| 6 | The system prompt | System prompt assembled from parts: role, tool-use rules, environment info (cwd, OS, date, git status), and a project instructions file (an `AGENTS.md`/`CLAUDE.md`-style file) loaded from the project. | Why wording matters; measure a prompt change by its effect in logs. |
| 7 | The terminal | Streaming responses (including tool-call deltas assembled across chunks), live display of tool calls and results, showing or hiding reasoning, Ctrl-C to interrupt a turn without killing the session. | Streaming tool-call assembly; what to do with the conversation after an interrupt. |
| 8 | Context | Track token use (from the server's `usage` field; estimates where needed); trim large old tool results; when near the limit, summarize older history with the model and continue (compaction). | 32K is small; what to keep vs. drop; why tokenizers differ between models. |
| 9 | Plans and checking work | A to-do tool the model uses to track multi-step work; a rule/prompt that the agent runs tests before declaring it is done. | Keeping a weak model on track; verification. |
| 10 | Subagents | A tool that starts a fresh agent loop with its own context and limited tools (e.g. read-only search) and returns only its final answer. | Context isolation; cost vs. benefit. |
| 11 | Capstone | A non-interactive mode (`run "<task>"` with auto-approve inside a throwaway copy, with the lesson 5 sandbox required on — the eval refuses to run with it off) and an eval script: copy the buggy project, run the agent, check the hidden tests pass and the test files are unchanged, repeat N=10, report success rate, tokens, time. | Measuring an agent instead of eyeballing it. Use the request logs to diagnose failed runs. Optional: compare 27B vs. 4B vs. Flint. |

Lesson content within each row is the intent; the builder may reorder small items
between adjacent lessons if a dependency demands it, and should say so.

`bash` exists from lesson 2 but the sandbox arrives in lesson 5. Lessons 2–4 must
say so plainly: their live exercises run in a scratch copy of a sample project,
and the learner watches each command (the loop can print and confirm commands
before running them). This is Claude's call.

## What each lesson contains

1. **Why this exists** — the problem this part of a harness solves.
2. **How Claude Code does it** — labeled per the Accuracy policy.
3. **The spec** — what to build, including the exact public interface the tests use
   (module, function/class names, signatures, behavior). The spec defines *what*,
   not *how*.
4. **Tests** — a pytest file the learner runs to know they're done.
5. **Try it live** — a short exercise with the real 27B model, and a "break it" exercise
   with the 4B, looking at the request log.
6. **Extras** — optional extensions.

Target size per lesson: a focused sitting or two (roughly 1–3 hours). Builder's call.

## Code layout

```
README.md                  course index, setup, how to run tests
lessons/NN-<name>/README.md  lesson text
lessons/NN-<name>/tests/     that lesson's tests
agent/                     the learner's package; grows across lessons (starts as a near-empty skeleton)
solutions/NN-<name>/agent/ complete reference package as of the end of lesson NN
capstone/buggy_project/    the small Python project with the planted bug
capstone/eval/             (or part of lesson 11) eval harness pieces the learner doesn't need to write
testing/                   shared test helpers, including the fake model
docs/                      this design and later plans
```

- Tests import from `agent` by default. There must be a simple way to run a
  lesson's tests against a reference solution instead (e.g. an env var or pytest
  option pointing at `solutions/NN-*/`), so the reference solutions are verified to
  pass their own tests.
- Each lesson's tests should also pass against later solutions (lessons build up;
  later lessons shouldn't break earlier interfaces without the lesson saying so).
- The learner can start any lesson by copying the previous lesson's solution into `agent/`.

## Testing approach

- **Fake model:** a provided test helper that stands in for the `openai` client and
  returns scripted responses (including tool calls, malformed tool calls, streaming
  chunks, and `usage` numbers). The learner's code must accept an injected client so tests
  can use it. This is a requirement on the specs from lesson 1 on.
- Default `pytest` runs need no server and are deterministic.
- **Live checks** are marked (e.g. `@pytest.mark.live`) and skipped unless asked for.
- Reference solutions must pass all non-live tests for their lesson and all earlier
  lessons.

## Capstone project

- A small, self-contained Python project (a few modules, a few hundred lines) with
  its own pytest suite. One planted bug that makes at least one test fail.
- The bug should require reading more than one file to find, but be fixable in a
  few lines, so that a 27B model has a realistic but not guaranteed chance. The
  eval's success rate is supposed to be informative, neither 0% nor 100%.
- The checker uses tests the agent doesn't see (or verifies the visible tests were
  not edited), so "delete the failing test" doesn't count as a fix.
- Builder picks the project's subject and the bug.

## Accuracy policy

Every "How Claude Code does it" claim carries one of these labels:

- **Documented** — stated in Anthropic's public Claude Code docs; link to the page.
  Verify against the current docs when writing.
- **Observed** — visible from Claude Code's own behavior or tool definitions (for
  example: its edit tool requires the text being replaced to match exactly once, and
  a file must be read before it is edited). Describe what is visible; don't infer
  the code behind it.
- **Design note** — a reasonable way to build it, not a claim about Claude Code.

When unsure, use the weaker label. Facts about the local setup (model behavior,
token counts, response shapes) should come from actually running against the model,
not memory.

## Left to the builder

- Exact wording, length, and examples of each lesson.
- Exact interfaces in each spec, within the constraints above.
- Request log format details and the viewer command's form.
- How token estimates are made where `usage` isn't available.
- How `reasoning_content` is handled in history (the lesson should explain the
  trade-off and pick a default).
- Whether to pin the model to the 4090 only (measure speed first).
- Capstone project subject and bug.
- Prompt and permission-rule formats.
