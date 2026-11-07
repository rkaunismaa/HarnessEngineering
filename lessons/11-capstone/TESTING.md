# How the lesson 11 tests work

Lesson 11 turns the agent into something that runs unattended (`run_task`) and something that measures itself (`run_eval`). The tests check the *machinery* around a run with scripted models: copying, counting, logging, the sandbox requirement and the command line. They don't check whether a real model can fix the bug. That is what the evaluation itself measures, so a test that required success would just be a flaky eval. Against the reference solution: 16 passed, 1 skipped (the live test).

```
uv run pytest lessons/11-capstone
uv run pytest lessons/11-capstone --impl solutions/11-capstone
uv run pytest capstone/eval                  # the checker's own tests (see the end)
```

Two pytest tools appear more often here than before:

- **`monkeypatch.setattr(module, "name", replacement)`** swaps one function for the duration of a test, then puts it back. The tests use it to pretend bwrap is missing, or to replace `run_task` with a stub.
- **`capsys`** captures what the command line prints, so a test can check the error message.

## `test_headless.py`: one unattended run

`run_task(task, root, config, client=..., verify_command=..., require_sandbox=..., max_turns=...)` returns a `RunReport`. The tests pass `client=FakeClient(...)`; the real CLI leaves it out and builds one from the config.

**The sandbox is required by default**

- **`test_requires_sandbox`** patches `sandbox_available` to return `False`. `run_task` then raises `SandboxUnavailable` rather than quietly running an unattended model with full access. With `require_sandbox=False` you opt out, and it runs. Most other tests opt out so they also pass on machines without bwrap.
- **`test_cli_run_refuses_without_sandbox`**: from the command line, `run` exits with 1 and the error names the flag that overrides it, `--unsafe-no-sandbox`. The flag's name says what you're giving up.

**What a report contains**

- **`test_run_task_with_fake`**: the scripted model writes `a.txt`, then says "All done." The test checks:
  - The **file really exists** with content `hi`. In headless mode there's nobody to approve, so writes are allowed without asking. That's the reason the sandbox is required.
  - The report has `stop_reason`, `final_text`, `turns == 2`, and tokens summed across both requests (250 prompt, 15 completion). `verified is None` because no check command was given.
  - **Each run writes its own log file** with two entries, and the report has its path.
  - **The system prompt was sent.** Headless runs use lesson 6's prompt too.
- **`test_max_turns_reported`**: a model that never stops ends with `max_turns` after 2 turns.

**The check command (lesson 9's verify, as a shell command)**

- **`test_verify_command_used`** uses a check that passes only when a file is *absent*: `test ! -e ok.flag`. Before the run, the flag file exists.
  - The model says "I think it is fixed." The check fails, and the `[Automatic check failed]` message goes back to the model.
  - The model runs `rm ok.flag`, says "Fixed now.", and the check passes.
  - So `verified is True` and `turns == 3`. This is the whole fix-check-retry cycle, using a real shell command and no test suite.
- **`test_verify_failure_reported`**: the check is `false`, which always fails, so `verified is False`.
- **`test_verify_runs_in_sandbox`** (marked `sandbox`): the check is `! touch /etc/harness-probe`, which can only succeed where `/etc` is read-only, which is inside the sandbox. The check command runs project code (its tests), so it needs the same protection as the model's own commands.
- **`test_default_verify_command_uses_this_python`**: the default check is `<this Python> -m pytest -q`, not bare `pytest`. A bare `pytest` might find a different install on `PATH`, or none.

**The command line**

- **`test_cli_has_run_and_eval_options`**: `eval` defaults to the capstone project and checker, and its task mentions "failing test". `run` *requires* `--root`, so you always say which project it may change.
- **`test_cli_run_works_on_a_copy`** replaces `run_task` with a stub that records the folder it was given and edits `lib.py` there. The test then checks that:
  - the folder was a fresh copy named `harness-run-...`, not your project;
  - your original `lib.py` is unchanged and the copy has the edit;
  - `__pycache__` wasn't copied;
  - the copy's path was printed at least twice, at the start and at the end, so you can find the result.

  `tempfile.tempdir` is patched so the copy lands inside `tmp_path` and is cleaned up with it.

## `test_eval.py`: many runs, counted

`run_eval(project, task, n, config, check=..., workdir_base=..., client_factory=...)` runs the task `n` times, each in its own copy, and scores each run with `check(workdir, original)`.

- **`client_factory`**: a function that returns a *new* client for each run. Each scripted run needs its own fresh script; a shared one would run out after the first run.
- **`check`**: the real one is `capstone/eval/check.py`. The tests pass a lambda that returns a small `Check` object with whatever `passed` value they want.
- **The `no_sandbox_needed` fixture** has `autouse=True`, so it applies to every test in the file. It wraps `run_task` so these tests don't need bwrap.

The tests:

- **`test_eval_copies_and_never_touches_project`** hashes every file name and file content in the project before and after (`tree_hash`); the two hashes must be equal. It also checks that:
  - the copies are named `run-00`, `run-01`;
  - each copy has the model's edit (`lib.py` is `2`);
  - no copy has `__pycache__`.

  An eval that changed its own input would corrupt every later run.
- **`test_eval_success_rate`**: checks returning pass, fail, pass, fail give `success_rate == 0.5`. Every scripted run uses 2 turns and 100 prompt tokens per request, so the means are exact: `mean_turns == 2` and `mean_prompt_tokens == 200`.
- **`test_eval_check_receives_workdir_and_original`**: the check gets the copy *and* the original. The original is how the checker detects edited tests.
- **`test_each_run_gets_its_own_log`**: three runs, three different log files, so you can read any single run on its own.
- **`test_cli_eval_refuses_existing_run_dirs`**: if `run-00` already exists, `eval` exits with 1 and the error mentions `--workdir-base`. It never mixes a new run into an old folder.
- **`test_empty_report`**: zero runs gives a success rate of 0.0, not a division-by-zero error.

## The live test

`test_live_capstone_once` (marked `live` and `sandbox`) does one real attempt. It copies `capstone/buggy_project`, runs the 27B on it with the default check, scores the copy with the real checker, and prints turns, tokens, time, `verified` and `passed`. The assertions only require that the run finished and the checker returned a result. Whether the model succeeded is printed, not asserted.

```
uv run pytest lessons/11-capstone --live -s -k capstone_once
```

## The checker's own tests (`capstone/eval/test_check.py`)

The checker decides what counts as a success, so it has tests of its own. Each one copies the buggy project, applies a specific "fix" by text replacement, and checks the verdict:

| Test | What's done to the copy | Verdict |
|---|---|---|
| `test_unfixed_fails` | nothing | fail; the output names the failing test |
| `test_fix_in_report_passes` | `< end` → `<= end` in *both* places in `report.py` | pass |
| `test_fixing_only_monthly_totals_fails` | only the first of the two places | fail; the hidden test `test_summary_counts_last_day` catches it |
| `test_fix_in_periods_fails` | extend the period end by a day in `periods.py` | fail; the visible test passes, but with `< end` the first day of the next month is now counted, which hidden tests such as `test_next_month_first_day_excluded` catch |
| `test_deleting_failing_test_detected` | delete the failing test | `tests_modified`, and fail |
| `test_added_test_file_detected` | add a test file | `tests_modified` |

The second and third rows are why the bug was duplicated. A fix that only touches the place the visible test reaches looks right but is caught by the hidden tests.

The last two tests protect the checker itself:

- **`test_agent_code_cannot_write_outside_workdir`**: the checker *imports and runs* the agent's code, which could be malicious. This test plants code in `ledger/__init__.py` that tries to write files outside the copy. The files must not appear, and the check must still finish with a normal verdict.
- **`test_refuses_to_run_unsandboxed`**: without bubblewrap, the checker raises an error instead of running untrusted code directly.
