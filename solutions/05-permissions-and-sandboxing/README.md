# Lesson 5 solution: what changed since lesson 4

This folder is the reference solution for [lesson 5](../../lessons/05-permissions-and-sandboxing/README.md). This page compares its `agent/` package with the one in [`solutions/04-editing-files/agent/`](../04-editing-files/agent/), file by file. For each change it says what the code does, why it's written that way, and what it's meant to show you.

To run this solution without touching your own `agent/` folder, run commands from inside this folder (`cd solutions/05-permissions-and-sandboxing`). `python -m agent` imports the `agent` package from the folder you're in. To run the lesson's tests against it: `uv run pytest lessons/05-permissions-and-sandboxing --impl solutions/05-permissions-and-sandboxing`, from the repository root.

## At a glance

| File | Lesson 4 | Lesson 5 | Status |
|---|---|---|---|
| `agent/permissions.py` | | 104 lines | **new**: allow and deny rules, and the decision for each call |
| `agent/sandbox.py` | | 60 lines | **new**: the bubblewrap command line, and a check that it works here |
| `agent/loop.py` | 85 lines | 128 lines | **changed**: every call is checked against the policy, and you're asked when needed |
| `agent/workspace.py` | 50 lines | 71 lines | **changed**: paths must stay inside the project; the workspace carries the sandbox settings |
| `agent/tools/files.py` | 231 lines | 246 lines | **changed**: every file tool turns an outside path into an error |
| `agent/tools/shell.py` | 76 lines | 88 lines | **changed**: runs commands in the sandbox; background jobs no longer hang the call |
| `agent/__main__.py` | 86 lines | 110 lines | **changed**: a general approval prompt, plus `--allow` and `--sandbox` |
| everything else | | | unchanged |

## What lesson 4 could do, and what it couldn't

Lesson 4's agent could run any command and change any file the model named. Two things stood between the model and your machine:

- **`confirm_bash` asked about every command.** That's safe, and tiring. By the tenth "yes", you stop reading. And it only covered `bash`: `edit_file` and `write_file` ran without asking at all.
- **Nothing else.** An approved command ran with all your permissions, could reach the network, and could leave background processes running. `edit_file("../other-project/settings.py", ...)` worked, because `Workspace.resolve` just joined paths.

## What this lesson is meant to show you

1. **Two layers, because neither is enough alone.** *Permissions* decide whether a call runs. The *sandbox* limits what a `bash` command can do once it runs, and assumes some approved command will turn out to be bad.
2. **Reading is cheap to allow; changing things isn't.** `read_file`, `list_files` and `search` run without asking. `edit_file`, `write_file` and `bash` ask by default. The model mostly reads, so this removes most prompts at no cost.
3. **A prefix rule can't make `bash` safe.** `bash(pytest*)` also matches `pytest && rm -rf ~`. So allow rules never match a command with shell operators. Even then, `pytest` runs `conftest.py`, which the agent can edit. An allow rule saves you being asked; it isn't a security boundary.
4. **A read-only filesystem isn't the whole story.** Unix sockets are doors to programs outside the sandbox (D-Bus, Docker, ssh-agent). The sandbox hides them, as far as this course knows how.
5. **Know what the sandbox doesn't do.** It doesn't stop reads. A sandboxed `cat ~/.ssh/config` works. And it only covers `bash`: the file tools are kept inside the project by `Workspace.resolve`.

## File by file

### `agent/permissions.py` (new): deciding each call

A **rule** is either a tool name (`edit_file`) or a tool name with a pattern (`bash(pytest*)`, `read_file(.env)`). `KEY_ARGUMENT` says which argument the pattern is matched against: `command` for `bash`, and `path` for the file tools. Tools not in that table only match bare rules.

`PermissionPolicy.check(tool, args, ws)` returns `Decision.ALLOW`, `DENY` or `ASK`, in this order:

```python
subject, inside = _subject(tool, args, ws)
if any(rule_matches(r, tool, subject) for r in self.deny):
    return Decision.DENY
if tool.read_only:
    return Decision.ALLOW
command = args.get("command") if tool.name == "bash" else None
compound = isinstance(command, str) and has_shell_operator(command)
if inside and not compound and any(rule_matches(r, tool, subject) for r in self.allow):
    return Decision.ALLOW
if self.auto_approve:
    return Decision.ALLOW
return Decision.ASK
```

**Why this order:**

- **Deny comes first, before the read-only shortcut.** A rule like `read_file(.env)` must block a read, even though reading is otherwise always allowed.
- **Read-only tools are allowed next**, using the `read_only` flag that has been on `Tool` since lesson 1, unused until now.
- **Allow rules only apply inside the project and only to simple commands.** A path rule never allows an edit outside the root. `has_shell_operator` looks for `;`, `&&`, `||`, `|`, a backtick, `$(`, `>`, `<`, a newline and `&`. Any of these means the command line can do more than its first word says, so it always goes to you.
- **`auto_approve`** means "say yes to everything that isn't denied". It's for headless runs (lesson 11) where nobody is there to ask. Deny rules still apply.
- **Anything else is `ASK`.** The safe default.

**`_subject` normalises paths before matching.** For the file tools, the pattern is matched against the path *relative to the root*, after resolving `..` and symlinks. So `./src/a.py`, `src/x/../a.py` and the absolute spelling are all `src/a.py`. Otherwise `read_file(./.env)` would slip past a `read_file(.env)` deny rule. A path that resolves outside the project is given in its absolute form, and `inside` is `False`.

**`remember(tool, args)`** is what `a` (always) does. For `bash` it adds a rule for **this exact command**, with any `*`, `?` or `[` escaped by `glob.escape` so they match literally. For other tools it allows the whole tool. "Always" for `bash` never turns into a wildcard.

Rules are matched with `fnmatchcase`: shell-style wildcards, and case matters.

### `agent/sandbox.py` (new): the bubblewrap command line

`build_bwrap_argv(command, cwd, root, cfg)` returns the list of arguments that runs `bash -c command` inside bubblewrap:

```python
argv = ["bwrap", "--unshare-all"]
if cfg.network:
    argv.append("--share-net")
argv += ["--die-with-parent", "--new-session",
         "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
         "--tmpfs", "/tmp", "--tmpfs", "/run", "--bind", str(root), str(root)]
...
for var in _HOST_SOCKET_VARS:
    argv += ["--unsetenv", var]
argv += ["--chdir", str(cwd), "--", "bash", "-c", command]
```

| Argument | What it does | Why |
|---|---|---|
| `--unshare-all` | new namespaces for everything: mounts, network, process ids, and more | the command gets its own view of the system |
| `--share-net` (only if `network=True`) | keeps your network | off by default; the live test turns it on |
| `--die-with-parent` | the sandbox dies if the harness does | no orphaned commands |
| `--new-session` | a new terminal session | the command can't push keystrokes into your terminal |
| `--ro-bind / /` | the whole filesystem, read-only | writes outside the project fail with `Read-only file system` |
| `--dev`, `--proc` | fresh, private `/dev` and `/proc` | the command sees only its own processes |
| `--tmpfs /tmp`, `--tmpfs /run` | empty, private `/tmp` and `/run` | hides the D-Bus and Docker sockets (`/var/run` is usually a link to `/run`) and sockets in `/tmp` |
| `--bind <root> <root>` | the project folder, writable | the one place the command may change |
| `--unsetenv DBUS_SESSION_BUS_ADDRESS SSH_AUTH_SOCK XDG_RUNTIME_DIR` | removes those variables | programs aren't told where host sockets are |

**The order matters.** Later mounts are layered on top of earlier ones. The private `/tmp` comes *before* the project bind, so a project under `/tmp` stays visible. A project under `/run` would be hidden by the private `/run`, so `build_bwrap_argv` refuses that with a `ValueError` rather than build a sandbox where the project disappears.

**`sandbox_available()`** doesn't just check that `bwrap` is installed. It runs a real sandbox with these exact flags, for the command `true`. Some systems allow a simple `bwrap` but refuse `--unshare-all`, and the only reliable test is to try.

`SandboxConfig` has three settings: `enabled`, `network` (off) and `extra_writable` (more folders to bind writable; empty by default).

### `agent/workspace.py` (changed): staying inside the project

```python
def resolve(self, path: str) -> Path:
    p = (self.root / path).resolve()
    if not self.contains(p):
        raise PathOutsideProject(str(path))
    return p
```

- **`resolve` now resolves fully**: `..` is collapsed and symlinks are followed. Then `contains` checks that the result is the root or below it. In lesson 4, `resolve` just joined the paths, so `../x` and `/etc/passwd` both worked.
- **Following symlinks matters.** A symlink inside the project that points outside is caught, because the check is on where the path really leads.
- **It raises instead of returning an error string**, because `resolve` is called from many places. Each tool converts the exception, with one wrapper (below).
- **The workspace also carries `sandbox`**, the `SandboxConfig` (or `None`), since `bash` already gets the workspace.

### `agent/tools/files.py` (changed): outside paths become errors

```python
def _inside_project(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs) -> str:
        try:
            return fn(*args, **kwargs)
        except PathOutsideProject as exc:
            return f"Error: {exc.path} is outside the project folder."
    return wrapper
```

All five file tools are registered as `fn=_inside_project(...)`. One wrapper gives them the same behaviour and the same message, and no tool's own code had to change. `_files_under` also drops anything that really lives outside the project, so a symlink out of the project, or a `../` in a glob pattern, can't make `list_files` or `search` look outside.

### `agent/tools/shell.py` (changed): commands in the sandbox

`_run` is renamed to `run_shell` (the `--verify` check added in lesson 9 calls it directly) and picks its command line from the workspace:

```python
if ws.sandbox is not None and ws.sandbox.enabled:
    argv = build_bwrap_argv(command, ws.root, ws.root, ws.sandbox)
else:
    argv = ["bash", "-c", command]
```

**The background-job fix.** In lesson 4, a command like `server &` kept the call open until that job ended, because the job still held the output pipe. Now the process group is killed **after every command**, not only on timeout. Anything a command left running in the background is cleaned up when the call returns. In the sandbox, the process-id namespace already ends everything when the command exits, even processes that left the group with `setsid`. The reader thread closes the pipe itself, and `run_shell` waits at most 2 seconds for it, so a process that escaped can't make the call hang.

`bash` still accepts a `confirm` function, but `ask` no longer passes one. Asking is now the policy's job.

### `agent/loop.py` (changed): the policy is checked before every call

`_run_tool_call` now has three steps: the repeated-call guard (lesson 3), then `_permission_refusal`, then `dispatch`.

```python
decision = self.permissions.check(tool, args, self.workspace)
if decision == Decision.ALLOW:
    return None
if decision == Decision.DENY:
    return DENIED_BY_RULE
if self.approver is None:
    return NO_APPROVER
answer = self.approver(name, args)
if answer == "always":
    self.permissions.remember(tool, args)
    return None
if answer == "yes":
    return None
return DENIED_BY_USER
```

- **A refusal is an error result**, like everything since lesson 3: `Error: this call is blocked by a deny rule.`, `Error: the user denied this tool call.`, or `Error: this call needs approval but no approver is available.`. The model reads it and tries something else.
- **Calls `dispatch` would reject anyway are passed straight to `dispatch`.** An unknown tool or bad JSON gets `dispatch`'s more useful error message, and you aren't asked to approve a call that can't run.
- **No `permissions` means no checks.** `Agent(..., permissions=None)` behaves exactly as in lesson 4, which keeps the earlier lessons' tests working.
- **The `Agent` gets the `workspace`** so `check` can normalise paths.
- **The approver is a plain function** `(tool name, args) -> "yes" | "always" | "no"`. The loop doesn't know how you're asked. The CLI gives it a terminal prompt; the tests give it a scripted answer.

### `agent/__main__.py` (changed): one prompt for every tool

```python
def _approve(name: str, args: dict) -> str:
    console = Console()
    shown = args.get("command") if name == "bash" else args
    console.print(f"[bold]{escape(name)}[/bold] wants to run:\n  {escape(str(shown))}")
    try:
        answer = Prompt.ask(escape("[y]es / [a]lways / [n]o"), choices=["y", "a", "n"],
                            default="n", show_choices=False, console=console)
    except (EOFError, KeyboardInterrupt):  # no one to answer: refuse
        return "no"
    return {"y": "yes", "a": "always"}.get(answer, "no")
```

- **It replaces `_confirm_bash`** and covers every tool the policy asks about, not just `bash`. For `bash` it shows the command itself; for other tools, the arguments.
- **The default is still no.** Pressing Enter, reaching the end of input, or Ctrl-C all refuse.
- **`--allow RULE`** (repeatable) passes allow rules to the policy: `--allow 'bash(pytest*)'`.
- **`--sandbox` / `--no-sandbox`.** With neither, the sandbox is used when `sandbox_available()` says it works. Otherwise `ask` prints `Warning: running bash commands without a sandbox.` and carries on. `--sandbox` makes a missing sandbox an error instead.

## What's still missing, and which lesson adds it

| Gap in this version | What goes wrong | Fixed in |
|---|---|---|
| The sandbox doesn't stop reads | a sandboxed command can print `~/.ssh/config` or a nearby `.env` | not in this course; your approval is the protection (the lesson's extras suggest hiding `~/.ssh` and similar folders) |
| Same kernel, same user, no resource limits | a fork bomb still works; unknown sockets elsewhere are still reachable | not in this course |
| Everything in the project is writable, including `.git/hooks` | a hook the agent writes runs *outside* the sandbox the next time you commit | not in this course; check `git status` |
| Allow and deny rules only come from the command line | no saved per-project settings | not in this course (an extra in the lesson) |
| The model isn't told about the sandbox | it explains a refused network connection as "no server is running" | partly lesson 6 (the system prompt) |

## Seeing it work

From inside this folder:

```
mkdir -p ~/scratch5
uv run python -m agent ask "Use bash to create the file ~/.harness_probe.txt containing the word hi. Then tell me exactly what happened." --root ~/scratch5
```

Answer `y`. The command runs in the sandbox and fails with `Read-only file system`, and `~/.harness_probe.txt` is never created. The lesson's README walks through this and two more experiments [step by step](../../lessons/05-permissions-and-sandboxing/README.md#what-happens-when-you-run-them-step-by-step): an allow rule that doesn't apply because the command has newlines in it, and a read that the sandbox doesn't stop. [TESTING.md](../../lessons/05-permissions-and-sandboxing/TESTING.md) shows the real `bwrap` checks the tests run.
