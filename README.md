# Harness Engineering: build a coding agent

A course where you build a coding agent, lesson by lesson, with no agent framework: the `openai` package is the only thing that talks to the model. A coding agent is a **harness** (loop, tools, permissions, context management) wrapped around a language model. You write the harness, run it against a model on your own machine, and measure whether it works.

Each lesson explains one problem, how Claude Code deals with it, and what to build. Tests tell you when your code matches the spec. By the end you have a working agent with file editing, a permission system and sandbox, a system prompt, a streaming terminal UI, context management, plans, subagents and a headless mode, and an eval that measures its success rate on a bug-fixing task.

## Prerequisites

- Python 3.10 or newer, and [uv](https://docs.astral.sh/uv/).
- Comfort reading and writing Python (dataclasses, argparse, subprocess, pytest). No machine-learning background needed.
- A local model server speaking the OpenAI chat-completions API with tool calling:
  - **LM Studio** at `http://localhost:1234/v1` with `qwen/qwen3.8-27b` loaded at a 32K context. This is the default in `agent/config.py` (lesson 0) and the model every "what we measured" number comes from. A GPU with about 24 GB of memory (the author used a 4090) runs it at a usable speed.
  - **Ollama** at `http://localhost:11434/v1` with `qwen3:4b-instruct` (`ollama pull qwen3:4b-instruct`) as the weak model for the "Break it" exercises. Point the agent at it with `AGENT_BASE_URL` and `AGENT_MODEL`.
  - Other models work if they support tool calls, but the numbers in the lessons will differ.
- **bubblewrap** (`bwrap`) for the sandbox in lessons 5 and 11: `sudo apt install bubblewrap` on Debian/Ubuntu. Check that it works unprivileged:

  ```
  bwrap --ro-bind / / --dev /dev --unshare-all true && echo sandbox ok
  ```

  Without it, the sandbox tests are skipped and `python -m agent run` and `eval` refuse to start.

## Setup

```
uv sync
```

Your code goes in `agent/` at the repository root (it starts as a docstring). Start with [`lessons/00-setup`](lessons/00-setup/README.md).

## How the lessons work

1. Read the lesson's `README.md`. Its sections are always the same: **Why this exists** (the problem), **How Claude Code does it** (how a production agent handles it), **What you'll build** (the spec: modules, signatures, exact strings), **Tests**, **Try it live**, **Break it** (an exercise with the weak 4B model) and **Extras**.
2. Write the code in `agent/`. Each lesson starts from your previous lesson's code. If you got stuck, copy `solutions/<previous lesson>/agent` into `agent/`.
3. Run the lesson's tests until they pass. They use a scripted fake model (`testing/fake_model.py`), so they are fast and need no server.
4. Run the live exercise against the real model and look at what happens. The lessons record what the author saw on 2026-10-30 so you can compare.

The README describes what to build and never contains the implementation. The reference solutions in `solutions/` are there to unblock you and to check your reading of the spec; try the lesson first.

### Accuracy labels

Every claim about Claude Code in a lesson carries one of three labels:

- **Documented**: stated on a page under <https://code.claude.com/docs/>, linked from the claim and checked on the date given.
- **Observed**: seen by running Claude Code, not written in the docs. It may change between versions.
- **Design note**: the course's own reasoning about the problem. It is not a statement about how Claude Code works.

When the source was unclear, the weaker label was used.

## Running tests

```
uv run pytest                                        # every lesson against your agent/ (no model server needed)
uv run pytest --impl solutions/11-capstone          # every lesson against the final solution: checks your setup
uv run pytest lessons/01-the-loop                    # one lesson, against your agent/
uv run pytest lessons/01-the-loop --impl solutions/01-the-loop   # against a reference solution
uv run pytest --live                                 # also run tests that need a live model server
uv run python scripts/check_solutions.py [--upto NN] # check every solution against every earlier lesson
```

- `--impl PATH` picks the directory whose `agent` package the tests import (default: this repository, i.e. your code).
- Tests marked `live` need a running model server and run only with `--live`.
- Tests marked `sandbox` need a working bubblewrap and are skipped without it.
- Plain `uv run pytest` runs every lesson's tests against your `agent/`, so it fails until you have finished every lesson. While you work, run one lesson at a time. To check that your setup works, run `uv run pytest --impl solutions/11-capstone`, which should pass.
- Each lesson's tests pass against that lesson's solution and every later one: a later lesson extends the agent without breaking what an earlier lesson's tests check. `scripts/check_solutions.py` verifies this for every lesson and solution.
- `scripts/run_solution.py <solution-dir> <agent args...>` runs the CLI of a reference solution (for example `uv run python scripts/run_solution.py solutions/11-capstone eval --n 3`) without touching your `agent/`.

## Lessons

| # | Lesson | You build |
|---|---|---|
| 0 | [Setup](lessons/00-setup/README.md) | Config, an OpenAI client, and a smoke test that proves the model emits a well-formed tool call. |
| 1 | [The loop](lessons/01-the-loop/README.md) | The agent loop, a tool registry, a workspace, `read_file`, and a request log. |
| 2 | [Tools](lessons/02-tools/README.md) | `list_files`, `search` and `bash`, with output truncation and error messages a model can act on. |
| 3 | [When the model gets it wrong](lessons/03-when-the-model-gets-it-wrong/README.md) | Argument validation, unknown-tool handling, repeated-call detection and recovery from server errors. |
| 4 | [Editing files](lessons/04-editing-files/README.md) | `edit_file` and `write_file`, with read-before-edit tracking. |
| 5 | [Permissions and sandboxing](lessons/05-permissions-and-sandboxing/README.md) | Project-folder confinement, allow/ask/deny rules, an approver, and a bubblewrap sandbox for shell commands. |
| 6 | [The system prompt](lessons/06-the-system-prompt/README.md) | A system prompt with environment facts, git state and project instructions. |
| 7 | [The terminal](lessons/07-the-terminal/README.md) | Streaming output, events, cancellation and an interactive REPL. |
| 8 | [Context](lessons/08-context/README.md) | Token estimates, trimming old tool results, and compaction when the window fills. |
| 9 | [Plans and checking work](lessons/09-plans-and-checking-work/README.md) | A todo tool and a verify step that checks the model's work before it stops. |
| 10 | [Subagents](lessons/10-subagents/README.md) | A tool that runs a task in a fresh context and returns only the answer. |
| 11 | [Capstone](lessons/11-capstone/README.md) | A headless mode and an eval that measures the agent's success rate on a planted bug. |

## Layout

```
agent/                 your package (starts empty)
lessons/NN-name/       README.md and tests/ for each lesson
solutions/NN-name/     reference `agent/` package as it stands at the end of lesson NN
testing/               the scripted fake model the tests use
scripts/               check_solutions.py, run_solution.py
capstone/              the buggy project and the hidden-test checker used by lesson 11
```
