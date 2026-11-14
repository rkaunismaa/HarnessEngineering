# Lesson 11 solution: what changed since lesson 10

This folder is the reference solution for [lesson 11](../../lessons/11-capstone/README.md), the capstone. This page compares its `agent/` package with the one in [`solutions/10-subagents/agent/`](../10-subagents/agent/), file by file. For each change it says what the code does, why it's written that way, and what it's meant to show you.

To run this solution without touching your own `agent/` folder, use `uv run python scripts/run_solution.py solutions/11-capstone <command>` from the repository root, or run commands from inside this folder (`cd solutions/11-capstone`). `python -m agent` imports the `agent` package from the folder you're in. To run the lesson's tests against it: `uv run pytest lessons/11-capstone --impl solutions/11-capstone`, from the repository root.

## At a glance

| File | Lesson 10 | Lesson 11 | Status |
|---|---|---|---|
| `agent/headless.py` | | 75 lines | **new**: run one task with nobody at the keyboard, and report what happened |
| `agent/eval.py` | | 70 lines | **new**: run a task many times on fresh copies of a project, check each, and count |
| `agent/__main__.py` | 159 lines | 267 lines | **changed**: the `run` and `eval` commands |
| everything else | | | unchanged |

**Nothing inside the agent changed.** The loop, the tools, the policy, the sandbox and the context manager are lesson 10's. The capstone is about *driving* the agent and *measuring* it.

The lesson also provides two things outside `agent/`: a project to work on, `capstone/buggy_project/` (a small personal-finance library with a date-range bug in two functions), and a checker, `capstone/eval/check.py`, with hidden tests the agent never sees.

## What lesson 10 could do, and what it couldn't

By lesson 10 the agent is complete. But "does it work?" had only ever been answered by running it once and reading what it did. One good run feels like success, and one bad run feels like failure. Neither says how *often* it works, and a model that chooses its own tool calls gives a different run every time.

Every run also needed a person: to approve calls, and to judge the result.

## What this lesson is meant to show you

1. **Headless means every call is allowed, so the sandbox is the only safety.** That's why `run` refuses to start without one, and works on a copy of your project, never the project itself.
2. **A single run is an anecdote; measure a rate.** Run the same task `n` times on fresh copies, and report "7 of 10", with the turns, tokens and seconds each run cost.
3. **Check the result, not the agent's claim.** The checker runs the visible tests, runs hidden tests, and fails any run that changed the tests. Without that last rule, deleting the failing test would be a winning strategy.
4. **Change one thing at a time.** A number is useful for comparing: another model, another prompt, the verify step on or off.
5. **The rate says how often; the log says why.** Every run keeps its own request log, so a failure can be read from the top.

## File by file

### `agent/headless.py` (new): one task, no questions

```python
def run_task(task, root, config, *, client=None, require_sandbox=True,
             verify_command=None, max_turns=50, log=None) -> RunReport:
    if require_sandbox and not sandbox_available():
        raise SandboxUnavailable(...)
    ws = Workspace(Path(root).resolve(), sandbox=SandboxConfig(enabled=require_sandbox))
    ...
    permissions = PermissionPolicy(auto_approve=True)
    tools = make_default_tools(ws, client=client, model=config.model, log=log,
                               context_window=config.context_window, permissions=permissions)
    agent = Agent(client, config.model, tools, system=build_system_prompt(ws, tools), log=log,
                  max_turns=max_turns, permissions=permissions, workspace=ws, stream=False,
                  context=ContextManager(config.context_window),
                  verify=_make_verify(ws, verify_command) if verify_command else None,
                  sampling=config.sampling())
    start = time.monotonic()
    result = agent.run(task)
    return RunReport(...)
```

**What it does:** builds the same agent `ask` does, with every lesson's features, but with nobody to ask. It runs the task in `root` and returns a `RunReport`: `stop_reason`, `final_text`, `turns`, `prompt_tokens`, `completion_tokens`, `duration_s`, `log_path` and `verified`.

**Why it's written this way:**

- **`PermissionPolicy(auto_approve=True)`, and no approver.** There's no one to answer a prompt, so every call that isn't denied is allowed (lesson 5's `auto_approve` was added for this). The same policy goes to the tools, so the subagent gets it too.
- **The sandbox is required.** `run_task` raises `SandboxUnavailable` rather than run with everything allowed *and* no sandbox. Running without one takes an explicit `require_sandbox=False`, which only `--unsafe-no-sandbox` passes.
- **`stream=False`**: there's no screen to stream to.
- **A verify command gives `verified`.** `_make_verify` runs the command through `run_shell`, in the sandbox, with a 300-second timeout. A timeout counts as a failure.
- **It works in `root` itself.** Making a copy is the caller's job: `run` and `eval` each do it their own way.
- **It returns a report, not printed text.** The CLI prints it, the eval collects it, and the tests check it.
- **`DEFAULT_TASK`** is the capstone's task: "The test suite has a failing test. Find the cause and fix it in the source code. Do not modify the tests."

### `agent/eval.py` (new): the same task, many times

```python
for i in range(n):
    workdir = workdir_base / f"run-{i:02d}"
    shutil.copytree(project, workdir,
                    ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    report = run_task(task, workdir, config, client=client_factory(),
                      verify_command=verify_command,
                      log=RequestLog(log_dir / f"{stamp}-run-{i:02d}.jsonl"))
    runs.append(RunOutcome(i, report, check(workdir, project), workdir))
return EvalReport(runs)
```

**Why it's written this way:**

- **A fresh copy for every run** (`run-00`, `run-01`, ...). A run that could see another run's edits would be measuring the wrong thing. The original `project` is never touched, so run 10 starts from exactly the same code as run 1.
- **A new client for each run** (`client_factory()`), so nothing carries over from one run to the next.
- **One log file per run**, named with a shared timestamp and the run number, so a failed run's log is easy to find.
- **The check is a function passed in**, `check(workdir, original)`. The eval doesn't know what success means for this task. The capstone's checker decides.
- **The checker runs after the agent has finished**, on files the agent can no longer change.
- **`EvalReport`** gives `success_rate`, `mean_turns`, `mean_prompt_tokens` and `mean_duration_s`. The cost of a run matters as much as whether it passed.
- **The runs happen one after another.** Running them side by side would be faster, but on one local GPU they would just slow each other down, and their timings would no longer be comparable.

### `agent/__main__.py` (changed): `run` and `eval`

**`python -m agent run "<task>" --root DIR`** runs one task headless:

- **It copies `DIR` to a new temporary folder first** (leaving out `.git`, `__pycache__` and `.pytest_cache`), and works there. With every call allowed, the agent can't damage your project, and you can see what it changed with the `diff -r` command it prints.
- **The verify step is on by default** (`--verify` defaults to `pytest -q`), since nobody is there to check the result.
- **Without a sandbox it refuses**, deletes the copy, and explains. `--unsafe-no-sandbox` overrides that, with a warning.
- **The answer goes to stdout, and a one-line summary to stderr:** stop reason, turns, tokens, seconds, `verified` and the log's path. The exit status is 0 only for `done`.

**`python -m agent eval`** runs the capstone by default: `--project capstone/buggy_project`, `--checker capstone/eval/check.py`, `--n 10`, and the default task and verify command.

- **The checker is loaded from a file** (`_load_checker`, which imports the file and takes its `check_fix`). You can point the same eval at another project and checker without changing the code.
- **It refuses a `--workdir-base` that already holds runs** from an earlier eval, so old copies can't be mistaken for new ones.
- **It needs the sandbox**, for the agent and for the checker, which runs the agent's code too.
- **It prints one line per run**, then the totals:

```
run  result   turns   tokens  secs  log
  0  pass        12    48210    95  .agent/logs/20261112-...-run-00.jsonl
  1  tests!       9    35102    71  ...
...
success: 7/10 (70%)  mean turns: 11.4  mean prompt tokens: 41210  mean seconds: 88
```

(That table is only an example of the layout.) `tests!` marks a run that changed the tests, which is a failure however the tests then came out. A run that ended other than `done` shows its stop reason too.

## What's still missing

This is the end of the course. The gaps that remain are the ones the earlier lessons named:

| Gap | Where it was discussed |
|---|---|
| The sandbox doesn't stop reads, and isn't production isolation | lesson 5 |
| Summaries lose detail | lesson 8 |
| One task, one project, one checker: a single number for a narrow job | this lesson: build more tasks before trusting a rate |
| Runs happen one at a time | by design, on one local GPU |
| No retries for temporary server errors | lesson 3's extras |

## Seeing it work

From the repository root:

```
uv run python scripts/run_solution.py solutions/11-capstone run "The test suite has a failing test. Find the cause and fix it in the source code. Do not modify the tests." --root capstone/buggy_project
uv run python scripts/run_solution.py solutions/11-capstone eval --n 3
```

The first runs the task once and prints where the result is. The second runs it three times and prints the table. Then open a failed run's log with `uv run python scripts/run_solution.py solutions/11-capstone log PATH`, and read it with the questions in the lesson's README ("Reading a failed run"). [TESTING.md](../../lessons/11-capstone/TESTING.md) has a request-by-request table of a real capstone run.
