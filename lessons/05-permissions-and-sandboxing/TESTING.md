# How the lesson 5 tests work

Against the reference solution on this machine: 75 passed, 1 skipped. The skipped test needs `--live`, and it passes too when run that way.

```
uv run pytest lessons/05-permissions-and-sandboxing
uv run pytest lessons/05-permissions-and-sandboxing --impl solutions/05-permissions-and-sandboxing
uv run pytest lessons/05-permissions-and-sandboxing --live      # adds the network-on check
```

## The big picture

Lesson 5 puts three separate layers between the model and your machine. Each one has its own tests:

```
 model asks for a call
        |
        v
 1. PermissionPolicy.check(tool, args)  ->  ALLOW / ASK / DENY       (test_permissions.py, parts 1-3)
        |   ASK -> the approver (you) says yes / no / always
        v
 2. Workspace.resolve(path)             ->  refuses paths outside the project   (part 4)
        |
        v
 3. bash runs inside bubblewrap         ->  read-only filesystem, no network,   (test_sandbox.py)
                                            no host sockets
```

- **Layer 1 decides whether a call runs at all.** It checks deny rules, then allow rules, then the tool's `read_only` flag.
- **Layer 2 stops file tools from leaving the project folder,** however the path is spelled.
- **Layer 3 limits what a shell command can do even after it's allowed.** Rules can't predict what a command like `python setup.py` will do, so the sandbox limits the damage instead.

Three styles of test go with them:

| Style | How it works | Needs |
|---|---|---|
| **Pure decisions** | `policy.check(tool, args)` and compare with `Decision.ALLOW` / `ASK` / `DENY` | nothing |
| **Scripted agent runs** | `FakeClient` script, a `permissions=` policy, and an `approver=` function standing in for you | nothing |
| **Real sandbox** (marked `sandbox`) | start real `bwrap` and check what a command inside it could do | a working bubblewrap |

The root `conftest.py` checks once per run whether `bwrap` works, using the same flags as the agent. If it doesn't, every `sandbox` test is **skipped**, not failed. If they show as skipped on your machine, the sandbox isn't being tested.

## Layer 1, decisions only

The reference solution gave these answers for a policy with `allow=["bash(git status*)"]` and `deny=["bash(rm *)", "read_file(secrets/*)"]`:

| Call | Decision | Why |
|---|---|---|
| `read_file(a.py)` | ALLOW | read-only tools are allowed by default |
| `read_file(./secrets/key)` | DENY | the deny rule matches the *normalized* path `secrets/key` |
| `bash(git status -s)` | ALLOW | matches the allow rule |
| `bash(git status; rm -rf x)` | ASK | contains `;`, and shell operators can never be auto-allowed |
| `bash(rm -rf build)` | DENY | deny beats everything |
| `bash(ls)` | ASK | no rule; bash isn't read-only |
| `edit_file(a.txt, ...)` | ASK | no rule; edits aren't read-only |
| `write_file(../x)` | ASK | outside the project is never auto-allowed |

The tests in parts 1 and 2 of `test_permissions.py` each pin down one row of logic like these:

**Defaults and precedence**

- **`test_read_only_allowed`** and **`test_mutating_asks`**: the defaults shown above.
- **`test_deny_beats_allow`**, **`test_deny_beats_read_only`**, **`test_deny_beats_auto_approve`**: a deny rule wins over an allow rule, over the read-only default, and over "yes to everything".

**How rules match**

- **`test_allow_prefix_rule`**: `bash(pytest*)` allows `pytest -q`, not `python -m pytest`. A rule is a glob over the whole argument, matched from the start.
- **`test_allow_rule_is_case_sensitive`**: `PYTEST -q` doesn't match.
- **`test_allow_path_rule`**: `edit_file(src/*)` covers edits under `src/` and nothing else, and doesn't cover `write_file`. A rule names one tool.
- **`test_bare_rule_matches_any_arguments`**: `write_file` with no parentheses matches any call to it.

**Shell operators**

- **`test_shell_operators_exact`** pins the list: `;  &&  ||  |  `` ` ``  $(  >  <  newline  &`.
- **`test_operators_never_auto_allowed`** runs ten commands like `git status && rm -rf x` against the allow rules `bash(git status*)` and bare `bash`. Each is ASK, while plain `git status -s` is ALLOW. Without this check, allowing `git status*` would also allow `git status; rm -rf ~`.
- **`test_background_operator_not_allowed`**: a single `&`.
- **`test_operators_still_hit_deny_rules`**: the operator check only blocks *allows*; deny rules still apply.
- **`test_auto_approve`**: with no deny rules, auto-approve allows everything, operators included.

**"Always" answers**

- **`test_remember_escapes_glob_chars`**: "always" for `ls *.py` stores a rule that matches exactly `ls *.py`, with the `*` escaped. Otherwise approving it once would also approve `ls *.py; rm x`.
- **`test_remember_non_bash_is_bare_tool_name`**: for other tools, "always" approves the tool with any arguments.

**Path rules see the real path (part 2)**

- **`test_path_rules_use_normalized_path`**: `src/../setup.py` is really `setup.py`, so ASK. `./src/app.py` and the absolute path both match `src/*`.
- **`test_deny_path_rule_not_bypassed_by_spelling`**: four spellings of `secrets/key`, all denied.
- **`test_deny_path_rule_through_symlink`**: `public` is a symlink to `secrets`, so `public/key` is denied.
- **`test_outside_path_never_allowed`**: even "allow every `write_file`" doesn't auto-allow `../x`.
- **`test_without_workspace_rules_see_raw_argument`**: without a workspace, rules match the raw string, so `./secrets/key` slips past. That's why the next test exists.
- **`test_agent_uses_workspace_for_path_rules`**: the `Agent` really passes its workspace to the policy. A scripted `read_file("./secrets/key")` is denied end to end.

## Layer 1 inside the agent, step by step: `test_agent_denied_result`

```python
def test_agent_denied_result(tmp_path):
    asked = []

    def approver(name, args):
        asked.append((name, args))
        return "no"

    agent, _ = make_agent(tmp_path, [
        reply(tool_calls=[call("bash", {"command": "touch made.txt"}),
                          call("bash", {"command": "rm -rf x"})]),
        reply(content="ok")],
        permissions=PermissionPolicy(deny=["bash(rm *)"]), approver=approver)
    result = agent.run("go")
```

The `approver` stands in for you at the terminal. It records every question and always answers `"no"`. Here is what happened on the reference solution.

**Reply 1 contains two calls.** For each one, the loop asks the policy *before* running anything:

- **`bash("touch made.txt")`**: no rule matches and bash isn't read-only, so ASK. The loop calls `approver("bash", {"command": "touch made.txt"})`, which returns `"no"`. The tool never runs.
- **`bash("rm -rf x")`**: the deny rule `bash(rm *)` matches, so DENY. The approver is **not** asked; there's no point asking about something that's forbidden anyway.

Each refusal becomes the call's tool result, with a different message so the model can tell them apart. The final history:

```json
{"role": "user", "content": "go"}
{"role": "assistant", "content": null, "tool_calls": [
   {"id": "call_1", ..., "arguments": "{\"command\": \"touch made.txt\"}"},
   {"id": "call_2", ..., "arguments": "{\"command\": \"rm -rf x\"}"}]}
{"role": "tool", "tool_call_id": "call_1", "content": "Error: the user denied this tool call."}
{"role": "tool", "tool_call_id": "call_2", "content": "Error: this call is blocked by a deny rule."}
{"role": "assistant", "content": "ok"}
```

The test then checks all three effects:

```python
    assert result.stop_reason == "done"
    assert tool_results(agent) == [DENIED_BY_USER, DENIED_BY_RULE]       # what the model was told
    assert asked == [("bash", {"command": "touch made.txt"})]            # you were asked once, about this
    assert not (tmp_path / "made.txt").exists()                          # and nothing ran
```

The other agent tests vary one thing each:

- **`test_agent_without_policy_runs_everything`**: no policy means lesson 4's behavior, so earlier lessons' tests keep passing.
- **`test_agent_approved_runs`**: "yes" runs the call.
- **`test_agent_yes_does_not_remember`**: "yes" is for this call only; the same call is asked about again.
- **`test_agent_always_then_no_prompt`**: "always" on the first edit means the second isn't asked about. One question, both edits on disk.
- **`test_agent_no_approver`**: ASK with nobody to ask refuses the call with `Error: this call needs approval but no approver is available.` This is the headless case lesson 11 needs.
- **`test_agent_read_only_needs_no_approver`**: reads still work with no approver.
- **`test_agent_bad_arguments_skip_approval`**: broken JSON, an unknown tool and a missing parameter are rejected *before* anyone is asked. Nobody should approve a call that can't run.
- **`test_denied_calls_count_for_loop_detection`**: three denied calls in a row trigger lesson 3's loop guard.

## Layer 2: staying inside the project folder (part 4)

On the reference solution, `read_file` with `../x` returns `Error: ../x is outside the project folder.`

- **`test_path_outside_project`**: every file tool refuses `../x`, and so does an absolute path outside. `write_file` really didn't write; the test checks that `../y` doesn't exist. A `list_files` glob of `../*` doesn't leak outside names.
- **`test_resolve_raises`**: `Workspace.resolve` raises `PathOutsideProject` for `../x` and `/etc/hostname`, and normalizes `sub/../a.txt`.
- **`test_sibling_with_same_prefix_is_outside`**: `/…/proj2` is not inside `/…/proj`. Comparing strings with `startswith` gets this wrong; comparing path parts gets it right.
- **`test_symlink_escape`** and **`test_symlink_escape_not_listed_or_searched`**: a symlink inside the project pointing outside can't be read, and `list_files` and `search` skip it. The test plants `password=hunter2` outside and checks it never shows up.
- **`test_edit_same_file_via_dotdot_spelling`**: lesson 4's tracker still matches across spellings.
- **`test_cli_ask_flags`**: `--allow` can be repeated, and `--sandbox`/`--no-sandbox` parse to `True`/`False`. Neither gives `None`, meaning "use the sandbox if bwrap works".

## Layer 3: the sandbox

### The command line, as a list (no bwrap needed)

`build_bwrap_argv(command, cwd, root, config)` returns a list, and these tests compare it with an expected list. For a project in a temporary folder, the solution built:

```
bwrap --unshare-all --die-with-parent --new-session        new namespaces for everything; dies with its parent
      --ro-bind / /                                        the whole filesystem, read-only
      --dev /dev --proc /proc                              fresh /dev and /proc
      --tmpfs /tmp --tmpfs /run                            empty, private /tmp and /run (hides host sockets)
      --bind /tmp/tmpqceiisuf /tmp/tmpqceiisuf             the project, writable (after the /tmp tmpfs!)
      --unsetenv DBUS_SESSION_BUS_ADDRESS --unsetenv SSH_AUTH_SOCK --unsetenv XDG_RUNTIME_DIR
      --chdir /tmp/tmpqceiisuf                             start in the project
      -- bash -c 'pytest -q'                               the model's command, as one argument
```

- **`test_argv_exact`** pins that whole list, plus two `extra_writable` folders.
- **`test_argv_network_flag`**: network on only adds `--share-net` after `--unshare-all`.
- **`test_tmpfs_before_root_bind`**: when the project is under `/tmp`, the empty `/tmp` must come *before* the project bind. In the other order it would hide the project.
- **`test_paths_under_run_refused`**: a project or extra folder under `/run` raises `ValueError`, because binding it would undo the `/run` tmpfs that hides host sockets.
- **`test_command_is_one_argument`**: the model's command is a single argument to `bash -c`, so quoting inside it can't change bwrap's options.
- **`test_disabled_sandbox_runs_plain`**, **`test_run_shell_plain`** and **`test_sandbox_available_returns_bool`**: with the sandbox off, commands run directly, and a timeout gives exit code `None`.

### Real bubblewrap (marked `sandbox`)

These start real sandboxes and check the effects. `run_shell` returns `(exit code, output)`. On this machine the reference solution gave:

| Command inside the sandbox | Result |
|---|---|
| `echo made > inside.txt && cat inside.txt` | `(0, 'made\n')`: the project is writable |
| `echo x > ~/.harness_sandbox_probe` | `(1, 'bash: line 1: ~/.harness_sandbox_probe: Read-only file system\n')` |
| a Python connect to `127.0.0.1:1234` | `(1, '... ConnectionRefusedError: [Errno 111] Connection refused\n')`, even though LM Studio *is* listening there |
| `echo "[$SSH_AUTH_SOCK][$DBUS_SESSION_BUS_ADDRESS][$XDG_RUNTIME_DIR]"` | `(0, '[][][]\n')` |

The tests:

- **`test_real_write_inside_ok`**, **`test_real_write_outside_blocked`**: the first two rows. The second also checks that the probe file doesn't exist afterwards.
- **`test_real_tmp_is_private`**: writing to `/tmp` works inside, but never reaches the real `/tmp`.
- **`test_real_extra_writable`**: an `extra_writable` folder really is writable.
- **`test_real_no_network`**: the third row. **`test_real_network_allowed`** (also `live`) checks that with `network=True` the same connect prints `CONNECTED`, so it needs LM Studio's server running.
- **`test_real_root_under_tmp_visible`**: the effect of the mount-order rule above.
- **`test_real_timeout_kills_sandboxed_command`** and **`test_real_exit_code_passes_through`**: the timeout and exit code still work through bwrap.

### Escapes found in review

These were added after the course review found a sandboxed command could reach the host through sockets:

- **`test_real_dbus_session_socket_unreachable`** and **`test_real_docker_socket_hidden`** try to connect to the D-Bus session socket and `/var/run/docker.sock`. Through either one, a process can ask something outside the sandbox to act for it. Each test skips itself if this machine doesn't have that socket.
- **`test_real_host_socket_env_unset`**: the fourth row of the table. `monkeypatch.setenv` sets the variables for this test only.
- **`test_real_systemd_run_fails`**: `systemd-run --user` would ask the host's systemd to run a command *outside* the sandbox. It must fail, and the file it tried to create must not exist.

### Background processes

- **`test_real_background_process_dies_with_call`**: a command starts a fully detached `sleep 30` and returns. Within a second, that process must be gone, because the sandbox's process namespace dies with the call.
- **`test_plain_background_job_does_not_block`** and **`test_plain_background_job_in_group_is_killed`**: without the sandbox, a detached child can survive but mustn't keep the call waiting, and an ordinary background job is killed with its process group.

These tests give their process a unique name with `exec -a` and look for it with `ps`, so an unrelated process can't be mistaken for it. A `finally:` block kills anything left over even when the test fails.

## If a test fails

- **A decision test fails:** print `policy.check(...)` for that case. Check the order (deny, then the operator check, then allow, then the read-only default), and whether the path was normalized first.
- **`test_agent_denied_result` asked the approver twice:** you ask before checking deny rules.
- **A sandbox test fails with a bwrap error:** run the exact argv from `test_argv_exact` by hand with `true` as the command; bwrap's own error message usually names the problem.
- **All `sandbox` tests are skipped:** bubblewrap isn't usable on this machine, so the sandbox layer isn't being tested at all.

## Words used above

| Term | Meaning here |
|---|---|
| **policy** | The allow and deny rules plus `auto_approve`; `check` returns a `Decision`. |
| **approver** | The function that asks you; returns `"yes"`, `"no"` or `"always"`. |
| **rule** | `tool(pattern)` or a bare `tool`; the pattern is a glob over the command or path. |
| **shell operator** | Something that joins or redirects commands (`;`, `&&`, `|`, `>`, …). |
| **normalized path** | The path after resolving `..`, `.` and symlinks, relative to the project root. |
| **bubblewrap (`bwrap`)** | A Linux tool that runs a command in its own namespaces, with a filesystem view you choose. |
| **namespace** | A kernel feature giving a process its own view of mounts, network, processes and so on. |
| **tmpfs** | An empty in-memory filesystem; mounted over `/tmp` and `/run` to hide the real ones. |
| **socket** | A connection point; Unix sockets in `/run` let processes ask host services to do things. |
