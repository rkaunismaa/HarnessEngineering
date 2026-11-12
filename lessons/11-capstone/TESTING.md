# How the lesson 11 tests work

Against the reference solution: 16 passed, 1 skipped (the live test). The live test passes too with `--live` (42.6 s against the 27B).

```
uv run pytest lessons/11-capstone
uv run pytest lessons/11-capstone --impl solutions/11-capstone
uv run pytest lessons/11-capstone --live -s -k capstone_once
uv run pytest capstone/eval                  # the checker's own tests (see the end)
```

## Where the code lives

Every function and class this walkthrough names is defined in one of the files below. Paths under `agent/` are relative to your own package; the reference versions are the same files under `solutions/11-capstone/agent/`.

| File | What's in it that this walkthrough uses |
|---|---|
| `agent/__main__.py` | `build_parser`, `main` |
| `agent/eval.py` | `EvalReport`, `EvalReport.mean_prompt_tokens`, `EvalReport.mean_turns`, `EvalReport.success_rate`, `run_eval` |
| `agent/headless.py` | `DEFAULT_VERIFY_COMMAND`, `run_task`, `RunReport`, `SandboxUnavailable` |
| `agent/sandbox.py` | `sandbox_available` |
| `agent/tools/files.py` | `edit_file` (defined inside `make_edit_file`), `list_files` (defined inside `make_list_files`), `read_file` (defined inside `make_read_file`), `search` (defined inside `make_search`) |
| `agent/tools/shell.py` | `bash` (defined inside `make_bash`) |
| `agent/tools/todo.py` | `todo_write` (defined inside `make_todo_write`) |

The test helpers come from:

| File | Helpers used |
|---|---|
| `capstone/eval/check.py` | `check_fix` |
| `testing/fake_model.py` | `call`, `FakeClient`, `reply` |

<details><summary>Which test file each test is in</summary>

| Test file | Tests |
|---|---|
| `lessons/11-capstone/tests/test_eval.py` | 7 tests: `test_cli_eval_refuses_existing_run_dirs`, `test_each_run_gets_its_own_log`, `test_empty_report`, `test_eval_check_receives_workdir_and_original`, `test_eval_copies_and_never_touches_project`, `test_eval_success_rate`, `test_live_capstone_once` |
| `lessons/11-capstone/tests/test_headless.py` | 10 tests: `test_cli_has_run_and_eval_options`, `test_cli_run_refuses_without_sandbox`, `test_cli_run_works_on_a_copy`, `test_default_verify_command_uses_this_python`, `test_max_turns_reported`, `test_requires_sandbox`, `test_run_task_with_fake`, `test_verify_command_used`, `test_verify_failure_reported`, `test_verify_runs_in_sandbox` |
| `capstone/eval/test_check.py` | 8 tests: `test_added_test_file_detected`, `test_agent_code_cannot_write_outside_workdir`, `test_deleting_failing_test_detected`, `test_fix_in_periods_fails`, `test_fix_in_report_passes`, `test_fixing_only_monthly_totals_fails`, `test_refuses_to_run_unsandboxed`, `test_unfixed_fails` |

</details>

## The big picture

Lesson 11 turns the agent into two new things:

- **`run_task`**: one unattended run. No person, no approvals, so it is sandboxed. It returns a `RunReport`.
- **`run_eval`**: the same task run *n* times, each on a fresh copy of the project, each scored by a checker. It returns a success rate and averages.

The tests check the **machinery** around a run, using scripted models: copying, counting, logging, the sandbox requirement and the command line. They deliberately **don't** check whether a real model can fix the capstone bug. That is what the evaluation itself measures, and a test that required success would just be a flaky eval.

```
 run_eval(project, task, n, check=..., client_factory=...)
   for i in range(n):
     copy project -> work/run-0i              (never touch the original)
     run_task(task, copy, client=client_factory())
        -> the agent loop, in the sandbox, with a verify command
        -> RunReport(stop_reason, final_text, turns, tokens, duration, log_path, verified)
     check(copy, original) -> passed?        (the real checker runs the hidden tests)
   -> EvalReport(success_rate, mean_turns, mean_prompt_tokens, ...)
```

Two pytest tools appear more often here than before:

- **`monkeypatch.setattr(module, "name", replacement)`** swaps one function for the duration of a test, then puts it back. It's used to pretend bwrap is missing, or to replace `run_task` with a stub.
- **`capsys`** captures what the command line prints, so a test can check the error message.

## One test, step by step: `test_verify_command_used`

**Code this test exercises:** `run_task` in `agent/headless.py`; `RunReport` in `agent/headless.py`; `Agent.run` in `agent/loop.py`; `bash` (defined inside `make_bash`) in `agent/tools/shell.py`; `FakeClient` in `testing/fake_model.py`.

This test shows a whole unattended run with a real check command, but no test suite:

```python
def test_verify_command_used(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "ok.flag").write_text("")
    cmd = "test ! -e ok.flag"          # passes only when ok.flag does NOT exist
    client = FakeClient([
        reply(content="I think it is fixed."),
        reply(tool_calls=[call("bash", {"command": "rm ok.flag"})]),
        reply(content="Fixed now."),
    ])
    report = run_task("fix", root, config(tmp_path), client=client, require_sandbox=False,
                      verify_command=cmd)
```

`test ! -e ok.flag` is a shell command that exits 0 (success) only when `ok.flag` doesn't exist. So the "bug" is the file, and the "fix" is deleting it. Here is what happened when this ran on the reference solution (sandboxed, since bwrap works here).

**Setup.** `run_task` builds the full agent from lessons 1–10:

- the system prompt, which begins `You are a coding agent working in the user's project through the tools below.`;
- every tool;
- `auto_approve`, because nobody is there to say yes;
- the sandbox;
- a fresh log file;
- a `verify` function that runs `test ! -e ok.flag` in the project.

**Request 0.** The reply is `I think it is fixed.`, with no tool calls. The check runs, and `ok.flag` exists, so it fails. Its output is empty, so the injected message is:

```
[Automatic check failed]

Fix the problem, then finish.
```

**Request 1** ends with that message. The reply is `bash("rm ok.flag")`. It's auto-approved, runs in the sandbox, and deletes the file.

**Request 2.** The reply is `Fixed now.` The check runs again, and this time it passes.

`run_task` returned:

```python
RunReport(stop_reason='done', final_text='Fixed now.', turns=3,
          prompt_tokens=300, completion_tokens=60, duration_s=0.024,
          log_path=PosixPath('.../logs/20261112-093542.jsonl'), verified=True)
```

The test checks:

```python
    assert report.verified is True
    assert report.final_text == "Fixed now."
    assert report.turns == 3
    assert "[Automatic check failed]" in client.requests[1]["messages"][-1]["content"]
```

This is lesson 9's fix-check-retry cycle, now driven by a real shell command. In the real capstone, the command is `<this Python> -m pytest -q`.

## `test_headless.py`: one unattended run

### The sandbox is required by default

- **`test_requires_sandbox`** patches `sandbox_available` to return `False`. `run_task` then raises `SandboxUnavailable` rather than quietly running an unattended model with full access. With `require_sandbox=False` you opt out, and it runs. Most of these tests opt out so they also pass on machines without bwrap.
- **`test_cli_run_refuses_without_sandbox`**: from the command line, `run` exits with 1 and the error names the override flag, `--unsafe-no-sandbox`. The flag's name says what you're giving up.
- **`test_verify_runs_in_sandbox`** (marked `sandbox`): the check is `! touch /etc/harness-probe`, which can only succeed where `/etc` is read-only, which is inside the sandbox. The check runs project code (its tests), so it needs the same protection as the model's own commands.

### What a report contains

- **`test_run_task_with_fake`**: the scripted model writes `a.txt`, then says "All done." The test checks:
  - **The file really exists** with content `hi`. Writes are allowed without an approver, which is exactly why the sandbox is required.
  - **The report fields:** `turns == 2`, tokens summed across requests (250 prompt, 15 completion), `duration_s`, and `verified is None` (no check command given).
  - **The run's own log file** exists, with 2 entries.
  - **The system prompt was sent.** Headless runs use lesson 6's prompt too.
- **`test_verify_failure_reported`**: the check is `false`, which always fails, so `verified is False`.
- **`test_max_turns_reported`**: a model that never stops ends with `max_turns` after 2 turns.
- **`test_default_verify_command_uses_this_python`**: on this machine the default is `/home/rob/PythonEnvironments/HarnessEngineering/.venv/bin/python3 -m pytest -q`, the course's own Python. A bare `pytest` might find a different install on `PATH`, or none.

### The command line

- **`test_cli_has_run_and_eval_options`**: `eval` defaults to the capstone project and checker, and its task mentions "failing test". `run` *requires* `--root`, so you always say which project it may change.
- **`test_cli_run_works_on_a_copy`** replaces `run_task` with a stub that records the folder it was given and edits `lib.py` there. The test then checks that:
  - the folder was a fresh copy named `harness-run-...`, not your project;
  - your `lib.py` is unchanged, and the copy has the edit;
  - `__pycache__` wasn't copied;
  - the copy's path was printed at least twice, at the start and the end, so you can find the result.

  `tempfile.tempdir` is patched so the copy lands inside `tmp_path` and is cleaned up with it.

## `test_eval.py`: many runs, counted

`run_eval(project, task, n, config, check=..., workdir_base=..., client_factory=...)`:

- **`client_factory`** is a function returning a **new** client for each run. Each scripted run needs a fresh script; a shared one would run out after the first run.
- **`check`** is the real `capstone/eval/check.py` in normal use. The tests pass a lambda returning a small `Check` object with whatever `passed` value they want.
- **The `no_sandbox_needed` fixture** has `autouse=True`, so it applies to every test in the file. It wraps `run_task` so these tests don't need bwrap.

A 3-run eval on the reference solution, with checks returning pass, fail, pass, gave:

```
success_rate 0.667   mean_turns 2.0   mean_prompt_tokens 200.0
  run-00  lib.py='2\n'  passed True
  run-01  lib.py='2\n'  passed False
  run-02  lib.py='2\n'  passed True
original lib.py: 'X = 1\n'
```

Each copy got the model's edit; the original never did. The tests pin exactly that:

- **`test_eval_copies_and_never_touches_project`** hashes every file name and file content before and after (`tree_hash`); the two hashes must be equal. It also checks that the copies are `run-00`, `run-01`, each has the edit, and none has `__pycache__`. An eval that changed its own input would corrupt every later run.
- **`test_eval_success_rate`**: pass, fail, pass, fail gives `success_rate == 0.5`. Every scripted run is 2 turns at 100 prompt tokens per request, so the means are exact: `mean_turns == 2`, `mean_prompt_tokens == 200`.
- **`test_eval_check_receives_workdir_and_original`**: the check gets the copy *and* the original, which is how the checker detects edited tests.
- **`test_each_run_gets_its_own_log`**: three runs, three different log files.
- **`test_cli_eval_refuses_existing_run_dirs`**: if `run-00` already exists, `eval` exits with 1 and mentions `--workdir-base`. It never mixes a new run into an old folder.
- **`test_empty_report`**: zero runs gives a success rate of 0.0, not a division by zero.

## The live test

`test_live_capstone_once` (marked `live` and `sandbox`) does one real attempt. It copies `capstone/buggy_project`, runs the 27B on it with the default check, scores the copy with the real checker, and prints the result. The assertions only require that the run finished and the checker answered; whether the model succeeded is printed, not asserted. On 2026-11-12 it succeeded:

```
stop=done turns=12 prompt=35657 completion=1863 42s verified=True passed=True
```

That run's log shows the whole course at work, request by request:

| # | Prompt tokens | What the model asked for | Course feature |
|---|---|---|---|
| 0 | 1,663 | `list_files`, and `todo_write` with a plan | lessons 2, 9 |
| 1 | 1,873 | `bash: python -m pytest tests/ -x -q` | lesson 2; runs in the sandbox (lesson 5) |
| 2–4 | 2,184–2,881 | `read_file` on `report.py`, `periods.py`, both test files | lesson 1 |
| 5 | 3,710 | `search("month_range")` | lesson 2 |
| 6 | 3,866 | two `edit_file` calls; **both** returned `Error: old_string was not found in the file.` | lesson 4 |
| 7 | 3,643 | `read_file("ledger/report.py")` again, to see the exact text | recovering from the error (lesson 3) |
| 8 | 3,433 | two `edit_file` calls; both `Edited ledger/report.py (1 replacement).` | lesson 4 |
| 9 | 3,281 | `bash: python -m pytest tests/ -q`, giving `13 passed` | lesson 2 |
| 10 | 3,367 | `todo_write` marking the plan done | lesson 9 |
| 11 | 3,149 | the answer, explaining the root cause | — then lesson 9's check ran and passed |

Three things to notice:

- **The failed edits weren't a crash.** They came back as errors, the model re-read the file, and its second attempt matched. That's lessons 3 and 4 working together.
- **It fixed both copies of the bug.** It edited the boundary check in both `monthly_totals` and `month_summary` (its final message misnames the second one as `monthly_total`), so the hidden test that catches a half-fix passed.
- **The prompt size went *down* from request 7.** That's lesson 8's trimming replacing old file contents with short notes.

The model's final answer began:

> Fixed. All 13 tests now pass. **Root cause:** `ledger/periods.py:month_range()` is documented to return `(first_day, last_day)` with *both ends inclusive* ... but `ledger/report.py` treated the second value as an *exclusive* boundary (`start <= t.date < end`).

## The checker's own tests (`capstone/eval/test_check.py`)

The checker decides what counts as success, so it has tests of its own. Each copies the buggy project, applies a specific "fix" by text replacement, and checks the verdict:

| Test | What's done to the copy | Verdict |
|---|---|---|
| `test_unfixed_fails` | nothing | fail; the output names `test_includes_last_day_of_month` |
| `test_fix_in_report_passes` | `< end` → `<= end` in *both* places in `report.py` | pass |
| `test_fixing_only_monthly_totals_fails` | only the first of the two places | fail; the hidden `test_summary_counts_last_day` catches it |
| `test_fix_in_periods_fails` | extend the period end by a day in `periods.py` | fail; the visible test passes, but with `< end` the first day of the next month is now counted, which hidden tests such as `test_next_month_first_day_excluded` catch |
| `test_deleting_failing_test_detected` | delete the failing test | `tests_modified`, and fail |
| `test_added_test_file_detected` | add a test file | `tests_modified` |

The second and third rows are why the bug was duplicated. A fix that only touches the place the visible test reaches looks right, but the hidden tests catch it.

The last two tests protect the checker itself:

- **`test_agent_code_cannot_write_outside_workdir`**: the checker *imports and runs* the agent's code, which could be malicious. This test plants code in `ledger/__init__.py` that tries to write files outside the copy. They must not appear, and the check must still finish with a normal verdict.
- **`test_refuses_to_run_unsandboxed`**: without bubblewrap, the checker raises an error instead of running untrusted code directly.

## If a test fails

- **`SandboxUnavailable` in a test that should run:** that test (or the `no_sandbox_needed` fixture) should pass `require_sandbox=False`. Check that your `run_task` accepts it.
- **`test_eval_copies_and_never_touches_project` fails on the hash:** something wrote into the original, often `__pycache__` created by running Python in the original folder. Copy first, run in the copy.
- **"FakeClient ran out of scripted responses" in an eval test:** you built one client for all runs. Call `client_factory()` once per run.
- **The live run fails:** read its log with `python -m agent log <log_path>`; the report prints the path.

## Words used above

| Term | Meaning here |
|---|---|
| **headless** | Running with no person present: no approvals, no terminal UI. |
| **`RunReport`** | The result of one `run_task`: stop reason, text, turns, tokens, duration, log path, `verified`. |
| **eval** | Running the same task several times on fresh copies and counting successes. |
| **checker** | `capstone/eval/check.py`: runs the hidden tests on a copy and checks the visible tests weren't changed. |
| **hidden tests** | Tests the agent never sees, which catch fixes that only satisfy the visible test. |
| **`client_factory`** | A function that returns a new client per run. |
| **`autouse` fixture** | A pytest fixture that applies to every test in the file without being named. |
