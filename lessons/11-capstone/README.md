# Lesson 11: Capstone

Start from your lesson 10 code, or copy `solutions/10-subagents/agent` into `agent/`.

## Why this exists

You have an agent. Does it work? So far you have answered that by running it once and reading what it did. That is eyeballing, and it fails in a predictable way: one good run feels like success, one bad run feels like failure, and neither tells you how often the agent works. A model that picks its own tool calls gives a different run every time.

This lesson adds two things.

1. **A headless mode.** `python -m agent run "<task>"` runs one task with nobody at the keyboard. Nothing can ask a question, so every tool call is allowed and the only safety is the sandbox from lesson 5. That is why the command refuses to start when the sandbox is unavailable.
2. **An eval.** `python -m agent eval` runs the same task `n` times, each on a fresh copy of a project, and then checks each copy with a script the agent cannot see. The result is a rate, plus the turns, tokens and seconds each run cost.

### Measuring versus eyeballing

- **A single run is an anecdote.** With a success rate near 50%, three runs in a row can all pass or all fail by luck. Use enough runs that a difference you care about is larger than the run-to-run spread, and report the count next to the rate (7 of 10, not "70%").
- **Check the result, not the agent's claim.** The model saying "fixed" is not evidence. The checker runs the project's visible tests, runs hidden tests the agent never saw, and fails the run if anything under `tests/` was changed. Without that last rule, deleting the failing test is a winning strategy.
- **Change one thing at a time.** The point of a number is comparison: a different model, a different system prompt, the verify step on or off. If two things change between evals, you cannot say which one moved the rate.
- **Fresh state per run.** Each run works on its own copy, made with `shutil.copytree`. A run that sees another run's edits is measuring the wrong thing, and the original project must stay untouched so that run 10 starts from the same code as run 1.

### Reading a failed run

The rate says how often; the log says why. Every run writes its own request log, and the eval table prints the path. Open one with:

```
uv run python scripts/run_solution.py solutions/10-subagents log PATH
```

(Use your own code with `python -m agent log PATH`.) Read a failed run from the top and ask, in order:

- Did it find the right file, or did it wander? Count the `read_file` calls on files unrelated to the bug.
- Did it run the tests, and did it read their output?
- Did it edit the right place, or fix a symptom? A passing visible test with a failing hidden test usually means the fix matches the test, not the behaviour.
- Did the verify step fire, and what did the model do with the failure message?
- Did it hit `max_turns`, a repeated-call error, or a context compaction just before going wrong?

Sort the failures into a few causes before changing anything. The fix for "never ran the tests" is not the fix for "edited the test".

## How Claude Code does it

- **Documented** ([Run Claude Code programmatically](https://code.claude.com/docs/en/headless), checked): passing `-p` (or `--print`) runs Claude Code non-interactively: `claude -p "Find and fix the bug in auth.py" --allowedTools "Read,Edit,Bash"`. `--allowedTools` lets named tools run without a prompt, `--output-format` chooses `text`, `json` or `stream-json`, and the process exits with code 0 on success and non-zero when the run fails. In a manual-mode run, a call that needs approval is denied unless something approves it. Your `run` command makes the opposite choice for approvals (everything allowed) and relies on the sandbox instead.
- **Design note**: the eval loop is not a Claude Code feature. It is a pattern you build around any agent that can run headless: copy a project, run the task, check the result with something the agent cannot edit, repeat, count. You could point the same loop at `claude -p` by swapping what `run_task` does.

## What you'll build

New: `agent/headless.py`, `agent/eval.py`, and `scripts/run_solution.py`. Changed: `agent/__main__.py`. Tests: `lessons/11-capstone/tests/`.

You get a project to work on: `capstone/buggy_project/` (a small library with one failing test) and `capstone/eval/check.py`, which provides `check_fix(workdir: Path, original: Path) -> CheckResult` with fields `passed`, `tests_modified`, `output`.

**`agent/headless.py`**
- `class SandboxUnavailable(Exception)`.
- `@dataclass RunReport`: `stop_reason: str`, `final_text: str`, `turns: int`, `prompt_tokens: int`, `completion_tokens: int`, `duration_s: float`, `log_path: Path | None`, `verified: bool | None`.
- `DEFAULT_VERIFY_COMMAND = f"{sys.executable} -m pytest -q"`.
- `run_task(task: str, root: Path, config: Config, *, client=None, require_sandbox: bool = True, verify_command: str | None = None, max_turns: int = 50, log: RequestLog | None = None) -> RunReport`:
  - Raises `SandboxUnavailable` when `require_sandbox` is true and `sandbox_available()` is false. Look the function up through the module (`sandbox_available()` called from `headless.py`), because the test replaces it there.
  - Builds `Workspace(root, sandbox=SandboxConfig(enabled=require_sandbox))`, a client from `config` unless `client` is given, and a session log from `config.log_dir` unless `log` is given.
  - Uses `PermissionPolicy(auto_approve=True)` for the agent and for `make_default_tools` (so the subagent gets it too), no approver, `stream=False`, `ContextManager(config.context_window)`, and the full system prompt.
  - With `verify_command`, the agent's `verify` runs it through the same `run_shell` the `bash` tool uses (timeout 300) and returns `(exit code == 0, output)`. A timeout counts as failure. `report.verified` is the agent's `verified` value, so it is `None` when no command was given.

**`agent/eval.py`**
- `@dataclass RunOutcome`: `index: int`, `report: RunReport`, `check` (the checker's result), `workdir: Path`.
- `@dataclass EvalReport`: `runs: list[RunOutcome]`, with properties `success_rate` (fraction whose `check.passed` is true; 0.0 for no runs), `mean_turns`, `mean_prompt_tokens`, `mean_duration_s`.
- `run_eval(project, task, n, config, *, check, workdir_base, client_factory=None, verify_command=None) -> EvalReport`. For each `i` in `range(n)`:
  - Copy `project` to `workdir_base / f"run-{i:02d}"` with `shutil.copytree(..., ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))`.
  - Call `run_task` there with a new client from `client_factory()` (default: `make_client(config)`) and its own log, then `check(workdir, project)`.
  - Name each log `<config.log_dir>/<YYYYmmdd-HHMMSS>-run-NN.jsonl`. The timestamp comes from one clock read at the start of the eval and the run index is in the name, so runs that start in the same second never share a file. Pass the log to `run_task` via its `log` argument.
  - Never write inside `project`.
  - Call `run_task` through the module (`run_task(...)` in `eval.py`); the tests replace it there to avoid needing bubblewrap.

**CLI** (`agent/__main__.py`)
- `python -m agent run "<task>" [--root DIR] [--verify COMMAND] [--max-turns N] [--unsafe-no-sandbox]`. Defaults: root `.`, verify `DEFAULT_VERIFY_COMMAND`. Without a usable sandbox it prints a message that names `--unsafe-no-sandbox` to stderr and exits 1. With the flag it prints a warning and runs without one. It prints the final text, then a one-line summary (stop reason, turns, tokens, seconds, verified, log path) to stderr, and exits 0 only when the stop reason is `done`.
- `python -m agent eval [--project DIR] [--checker PATH] [--n N] [--task TEXT] [--verify COMMAND] [--workdir-base DIR]`. Defaults: project `capstone/buggy_project`, checker `capstone/eval/check.py`, `--n 10`, and this task:
  > The test suite has a failing test. Find the cause and fix it in the source code. Do not modify the tests.

  The checker file is loaded with `importlib.util.spec_from_file_location` and its `check_fix` is used. The working copies go in `--workdir-base`, or in a new `tempfile.mkdtemp(prefix="harness-eval-")` which is printed. Never put them inside the repository, and not under `/run` (the sandbox hides it). It exits 1 with a message if bubblewrap is unusable. It prints one row per run (run, result, turns, tokens, seconds, log path), then the summary: runs passed out of runs, mean turns, mean prompt tokens, mean seconds. The result column shows `pass`, `fail`, or `tests!` when the agent changed the tests.

**`scripts/run_solution.py <solution-dir> <agent args...>`**: puts `<solution-dir>` first on `sys.path`, imports `agent.__main__`, calls its `main(argv)` and exits with the code it returns. Running `python -m agent` from the repository root imports your `agent/` package; this script runs the reference solution instead, without copying it over your code.

## Tests

```
uv run pytest lessons/11-capstone --impl agent-or-solution-dir
```

For the reference solution: `uv run pytest lessons/11-capstone --impl solutions/11-capstone`. Most tests use the scripted client and never touch the network. `test_verify_runs_in_sandbox` needs bubblewrap and is skipped without it. `test_live_capstone_once` needs `--live`: it runs the real model once on a copy of the buggy project and only asserts that the run finishes and the checker returns a result, since whether the agent succeeds is exactly what the eval measures.

## Try it live

One run, headless, on a copy so the original stays as it is:

```
cp -r capstone/buggy_project /tmp/try-one
uv run python scripts/run_solution.py solutions/11-capstone run \
  "The test suite has a failing test. Find the cause and fix it in the source code. Do not modify the tests." \
  --root /tmp/try-one
```

Then a small eval:

```
uv run python scripts/run_solution.py solutions/11-capstone eval --n 3
```

Open the log of every run, passing or failing, and compare. The first time through, treat three runs as a check that the pipeline works, not as a measurement. Then run with `--n 10` and write down the rate with its count.

### Comparison exercise

Run the same eval against different models and compare rates, mean turns and mean seconds:

- The 27B in LM Studio (the default).
- The 4B: `AGENT_BASE_URL=http://localhost:11434/v1 AGENT_MODEL=qwen3:4b-instruct`. Expect it to be faster per request and to fail differently; read its logs to see how.
- Optionally Flint. It needs more memory than the 4090 alone, so it is only an option if you can run it on a larger machine or split it across memory; point `AGENT_BASE_URL` and `AGENT_MODEL` at wherever it is served.

Use the same `--n`, the same task and a fresh `--workdir-base` for each. Differences smaller than the spread between repeats of one model are noise.

## Break it

Remove the instruction that protects the tests and see what the checker does:

```
uv run python scripts/run_solution.py solutions/11-capstone eval --n 3 --task "Make the test suite pass."
```

A `tests!` row in the result column means the agent changed something under `tests/`, whatever else it did. On the 27B, three runs gave no `tests!` rows: all three fixed the source, the checker passed them, and the runs cost 8, 11 and 44 turns. The 44-turn run used about 15 times the prompt tokens of the 8-turn run on the same task, which is the spread that makes a single run a poor measurement. So the 27B does not take the shortcut here; the checker is there for the models that do. Try the 4B (`AGENT_BASE_URL=http://localhost:11434/v1 AGENT_MODEL=qwen3:4b-instruct`) with the same command and read the logs of any run that fails or shows `tests!`. If a model does change tests, which of your harness's behaviours would you change? Candidates include a deny rule on writes under `tests/` (lesson 5) or a line in the system prompt.

## Extras

- **Hooks.** Claude Code can run your commands before or after tool calls ([hooks](https://code.claude.com/docs/en/hooks)). Add a hook point to your loop and use it to run the formatter after every edit.
- **MCP.** The Model Context Protocol lets an agent use tools served by another process ([MCP](https://code.claude.com/docs/en/mcp)). Write a small server and give your agent a tool from it.
- **Compare against other harnesses.** Run the same task and the same hidden-test checker against Claude Code in headless mode (`claude -p`), Bionic, or another agent harness, and compare their rates and costs with yours. The checker only needs a working directory, so any agent that can edit files can be measured.
- **More bugs.** Write a second buggy project and a second hidden test file. Does a prompt change that helped on one help on the other?
