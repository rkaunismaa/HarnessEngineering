# How the lesson 5 tests work

Lesson 5 has the most tests in the course. They come in two files and three styles:

- **`test_permissions.py`** tests the rules: pure checks on `PermissionPolicy.check(...)` that return ALLOW, ASK or DENY, then scripted runs through the `Agent`, then the folder boundary.
- **`test_sandbox.py`** first checks the exact `bwrap` command line you build, as a plain list compared to an expected list. Then the tests marked `sandbox` run **real bubblewrap** and check what a command inside it can and can't do.

Against the reference solution on this machine: 75 passed, 1 skipped. The skipped test is the one marked both `sandbox` and `live`.

```
uv run pytest lessons/05-permissions-and-sandboxing
uv run pytest lessons/05-permissions-and-sandboxing --impl solutions/05-permissions-and-sandboxing
uv run pytest lessons/05-permissions-and-sandboxing --live      # adds the network-on check
```

The root `conftest.py` decides whether the `sandbox` tests can run. Once per session it runs `bwrap` with the same flags the agent uses. If that fails (no bwrap, or a kernel that refuses unprivileged namespaces), every `sandbox` test is *skipped*, not failed. If they show as skipped on your machine, the sandbox isn't being tested.

## Part 1: the policy

The tests call `policy.check(tool, args)` directly and compare the result with `Decision.ALLOW`, `Decision.ASK` or `Decision.DENY`. No model and no agent are involved, so each rule can be pinned down on its own.

**Defaults**

- **`test_read_only_allowed`**: `read_file`, `list_files` and `search` are allowed with no rules at all, because they are flagged `read_only`.
- **`test_mutating_asks`**: `bash`, `edit_file` and `write_file` default to ASK.

**Order of precedence: deny beats everything**

- **`test_deny_beats_allow`**: the same rule in both lists gives DENY.
- **`test_deny_beats_read_only`**: `read_file(*.env)` in deny blocks reading `prod.env`, even though reading is normally free. `a.py` is still allowed.
- **`test_deny_beats_auto_approve`**: `auto_approve=True` (the "yes to everything" mode) still can't get past a deny rule.

**How rules match**

- **`test_allow_prefix_rule`**: `bash(pytest*)` allows `pytest -q` but not `python -m pytest`. A rule is a glob over the whole argument, so it matches from the start.
- **`test_allow_rule_is_case_sensitive`**: `PYTEST -q` doesn't match.
- **`test_allow_path_rule`**: `edit_file(src/*)` allows edits under `src/`, asks about `setup.py`, and doesn't cover `write_file`. A rule names one tool.
- **`test_bare_rule_matches_any_arguments`**: `write_file` with no parentheses matches any call to that tool.

**Shell operators can never be allowed by a rule**

- **`test_shell_operators_exact`** pins the list: `;  &&  ||  |  `` ` ``  $(  >  <  newline  &`.
- **`test_operators_never_auto_allowed`** is parametrized over ten commands, such as `git status && rm -rf x` and `git status > important.txt`. Even with the rules `bash(git status*)` and bare `bash`, each one is ASK, while a plain `git status -s` is ALLOW. Without this check, an allow rule for `git status*` would also allow `git status; rm -rf ~`.
- **`test_background_operator_not_allowed`**: `pytest -q & rm -rf x`, with a single `&`.
- **`test_operators_still_hit_deny_rules`**: the operator check only stops an *allow*. A deny rule like `bash(*rm -rf*)` still applies to `ls && rm -rf x`.
- **`test_auto_approve`**: with no deny rules, auto-approve allows everything, operators included. That is what the flag means.

**"Always" answers**

- **`test_remember_escapes_glob_chars`**: answering "always" to `ls *.py` stores a rule that matches *exactly* `ls *.py`, with the `*` escaped. Otherwise approving `ls *.py` once would also approve `ls *.py; rm x`. The test checks both: `ls a.py` and `ls *.py; rm x` still ASK.
- **`test_remember_non_bash_is_bare_tool_name`**: for other tools, "always" approves the tool for any arguments.

## Part 2: path rules see the real path

A rule like `read_file(secrets/*)` is useless if `./secrets/key` or `x/../secrets/key` gets past it. When the policy is given the workspace, it matches rules against the *normalized* path, relative to the project root:

- **`test_path_rules_use_normalized_path`**: `src/../setup.py` is really `setup.py`, so ASK. `./src/app.py` and the absolute path to `src/app.py` both match `src/*`.
- **`test_deny_path_rule_not_bypassed_by_spelling`** tries four spellings of `secrets/key`; all are denied.
- **`test_deny_path_rule_through_symlink`**: `public` is a symlink to `secrets`, so `public/key` is denied too. Symlinks are resolved first.
- **`test_outside_path_never_allowed`**: even a rule allowing all of `write_file` doesn't allow `../x`. It gets ASK and never ALLOW, because paths outside the project are never auto-allowed.
- **`test_without_workspace_rules_see_raw_argument`** shows the other case: without a workspace, rules match the raw string, so `./secrets/key` slips past. That's why the next test exists.
- **`test_agent_uses_workspace_for_path_rules`**: the `Agent` really does pass its workspace in, end to end. A scripted `read_file("./secrets/key")` is denied.

## Part 3: the agent asks, and obeys

These use `FakeClient` scripts with a `permissions=` policy and an `approver=` function standing in for you at the terminal. The approver returns `"yes"`, `"no"` or `"always"`.

- **`test_agent_without_policy_runs_everything`**: with no policy, behavior is unchanged from lesson 4, so the earlier lessons' tests keep passing.
- **`test_agent_denied_result`**: one reply with two calls. `touch made.txt` goes to the approver, who says no. `rm -rf x` hits a deny rule, so the approver is never asked. The results are the two different messages: "the user denied" and "blocked by a deny rule". The approver saw exactly one question, and `made.txt` doesn't exist.
- **`test_agent_approved_runs`**: "yes" runs the call.
- **`test_agent_yes_does_not_remember`**: "yes" applies once. The same call again is asked again (two questions).
- **`test_agent_always_then_no_prompt`**: "always" on the first edit means the second edit isn't asked about. One question, and both edits are on disk.
- **`test_agent_no_approver`**: a policy that says ASK, with nobody to ask, refuses the call and says so. This is the headless case lesson 11 needs.
- **`test_agent_read_only_needs_no_approver`**: reads still work with no approver.
- **`test_agent_bad_arguments_skip_approval`**: broken JSON, an unknown tool and a missing parameter are rejected *before* anyone is asked. Nobody should be asked to approve a call that can't run.
- **`test_denied_calls_count_for_loop_detection`**: three denied calls in a row trigger lesson 3's loop guard.

## Part 4: staying inside the project folder

- **`test_path_outside_project`**: every file tool refuses `../x` with `Error: ../x is outside the project folder.`, and so does an absolute path outside. `write_file` really didn't write: the test checks that `../y` doesn't exist. A `list_files` glob of `../*` doesn't leak outside names.
- **`test_resolve_raises`**: `Workspace.resolve` raises `PathOutsideProject` for `../x` and `/etc/hostname`, and normalizes `sub/../a.txt`.
- **`test_sibling_with_same_prefix_is_outside`**: `/…/proj2` is *not* inside `/…/proj`. Comparing strings with `startswith` gets this wrong; comparing path parts gets it right.
- **`test_symlink_escape`** and **`test_symlink_escape_not_listed_or_searched`**: a symlink inside the project that points outside can't be read, and `list_files` and `search` skip it. The test plants `password=hunter2` outside and checks it never shows up.
- **`test_edit_same_file_via_dotdot_spelling`**: the lesson 4 read record still matches across spellings.
- **`test_cli_ask_flags`**: `--allow` can be repeated, and `--sandbox`/`--no-sandbox` parse to `True`/`False`. Leaving both out gives `None`, meaning "use the sandbox if bwrap works".

## Part 5: the sandbox command line (no bwrap needed)

`build_bwrap_argv(command, cwd, root, config)` returns a list. These tests compare it with an expected list, so they run anywhere:

- **`test_argv_exact`** pins the whole command. Reading it from left to right:
  - new namespaces for everything, and the sandbox dies with its parent;
  - the whole filesystem mounted read-only;
  - fresh `/dev`, `/proc`, `/tmp` and `/run`;
  - the project, and each extra writable folder, bound read-write;
  - the host socket variables unset;
  - `cd` into the working folder, then `bash -c <command>`.
- **`test_argv_network_flag`**: network on only adds `--share-net` right after `--unshare-all`. Otherwise the lists are identical.
- **`test_tmpfs_before_root_bind`**: when the project lives under `/tmp` (as pytest's `tmp_path` does), the empty `/tmp` must be mounted *before* the project is bound. In the other order, the empty `/tmp` would hide the project.
- **`test_paths_under_run_refused`**: a project or extra folder under `/run` or `/var/run` raises `ValueError`. Binding it would undo the `/run` tmpfs that hides host sockets.
- **`test_command_is_one_argument`**: the model's command is passed as a single argument to `bash -c`, never split up, so quoting inside it can't change the bwrap options.
- **`test_disabled_sandbox_runs_plain`**, **`test_run_shell_plain`** and **`test_sandbox_available_returns_bool`**: with the sandbox off, commands run directly (writing next to the project works). Timeouts give exit code `None`.

## Part 6: real bubblewrap (marked `sandbox`)

These start real sandboxes and test their effects, not the command line:

- **`test_real_write_inside_ok`**: writing in the project works, and `pwd` is the project folder.
- **`test_real_write_outside_blocked`**: writing `~/.harness_sandbox_probe` fails with `Read-only file system`, and the file doesn't exist afterwards.
- **`test_real_tmp_is_private`**: writing to `/tmp` succeeds inside the sandbox but never reaches the real `/tmp`.
- **`test_real_extra_writable`**: an `extra_writable` folder really is writable.
- **`test_real_no_network`**: a Python socket connect to `127.0.0.1:1234` (LM Studio) fails. **`test_real_network_allowed`** (also `live`) checks that it succeeds with `network=True`, which needs LM Studio's server running.
- **`test_real_root_under_tmp_visible`**: the real effect of the mount-order rule above.
- **`test_real_timeout_kills_sandboxed_command`** and **`test_real_exit_code_passes_through`**: the timeout and exit code still work through bwrap.

### Escapes found in review

These were added after the course review found a sandboxed command could reach the host through sockets:

- **`test_real_dbus_session_socket_unreachable`** and **`test_real_docker_socket_hidden`** try to connect to the D-Bus session socket and `/var/run/docker.sock`. Through either one, a process can ask something outside the sandbox to act for it. Each test skips itself if this machine doesn't have that socket.
- **`test_real_host_socket_env_unset`**: `SSH_AUTH_SOCK`, `DBUS_SESSION_BUS_ADDRESS` and `XDG_RUNTIME_DIR` are empty inside. `monkeypatch.setenv` sets them for this test only.
- **`test_real_systemd_run_fails`**: `systemd-run --user` would ask the host's systemd to run a command *outside* the sandbox. It must fail, and the file it tried to create must not exist.

### Background processes

- **`test_real_background_process_dies_with_call`**: a command starts a fully detached `sleep 30` and returns. Within a second, that process must be gone, because the sandbox's process namespace dies with the call.
- **`test_plain_background_job_does_not_block`** and **`test_plain_background_job_in_group_is_killed`** cover the unsandboxed case. A detached child can survive, but must not keep the call waiting. An ordinary background job is killed with its process group.

These tests find their process by a unique name set with `exec -a`, so they can't mistake an unrelated process for it. A `finally:` block kills anything left over even when the test fails.
