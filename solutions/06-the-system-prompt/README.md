# Lesson 6 solution: what changed since lesson 5

This folder is the reference solution for [lesson 6](../../lessons/06-the-system-prompt/README.md). This page compares its `agent/` package with the one in [`solutions/05-permissions-and-sandboxing/agent/`](../05-permissions-and-sandboxing/agent/), file by file. For each change it says what the code does, why it's written that way, and what it's meant to show you.

To run this solution without touching your own `agent/` folder, run commands from inside this folder (`cd solutions/06-the-system-prompt`). `python -m agent` imports the `agent` package from the folder you're in. To run the lesson's tests against it: `uv run pytest lessons/06-the-system-prompt --impl solutions/06-the-system-prompt`, from the repository root.

## At a glance

| File | Lesson 5 | Lesson 6 | Status |
|---|---|---|---|
| `agent/prompt.py` | | 75 lines | **new**: builds the system prompt from parts |
| `agent/__main__.py` | 110 lines | 113 lines | **changed**: `ask` passes the system prompt to the `Agent` |
| everything else | | | unchanged |

The smallest change in the course, in lines of code. `Agent` has accepted a `system` argument since lesson 1, and put it first in `self.messages`. Nothing passed one until now.

## What lesson 5 could do, and what it couldn't

Lesson 5's agent ran with no system message at all. The model got the tool schemas and your question, and had to guess everything else: which folder it's in, what day it is, whether this is a git repository, how this team likes its code, and how to use the tools well. Anything it needed to know, it had to find out with tool calls, or get wrong.

## What this lesson is meant to show you

1. **A system prompt is built, not written.** Some parts are fixed (the role, the tool rules). Some are measured when the agent starts (the working directory, the date, the git state, the tool names). One comes from the project (an `AGENTS.md` or `CLAUDE.md`). So it's the output of a function, and the function can be tested.
2. **It's paid for on every request.** It's sent first, every time. The reference prompt adds about 153 prompt tokens to each request on the 27B. Every sentence has to earn its place.
3. **A fact beats a question.** One line saying `Working directory: /home/you/project` costs fewer tokens than the model running `pwd` and reading the result.
4. **Project instructions are the user's, and untrusted.** They arrive in the most trusted position in the request, so their size is capped, and they can make the agent worse as easily as better.
5. **Wording matters, unevenly.** Short, concrete, positive rules work best. A rule that describes what the model already does changes nothing.

## File by file

### `agent/prompt.py` (new): the prompt, in parts

`build_system_prompt(ws, tools, *, now=None, extra=None)` joins up to five sections, separated by blank lines:

```python
parts = [ROLE, TOOL_RULES, "\n".join([
    "# Environment",
    f"Working directory: {ws.root}",
    f"Platform: {sys.platform}",
    f"Date: {now:%Y-%m-%d}",
    f"Git: {git_summary(ws.root)}",
    f"Tools: {', '.join(tools.names())}",
])]
found = load_project_instructions(ws.root)
if found:
    parts.append(f"# Project instructions (from {found[0]})\n{found[1]}")
if extra:
    parts.append(extra)
return "\n\n".join(parts) + "\n"
```

The sections, in order:

| Section | Where it comes from | Why it's there |
|---|---|---|
| **Role**: "You are a coding agent working in the user's project through the tools below." | fixed (`ROLE`) | one sentence of context; anything longer costs tokens on every request |
| **`# Using tools`**: four rules | fixed (`TOOL_RULES`) | the habits that matter most for this harness (below) |
| **`# Environment`**: directory, platform, date, git, tool names | measured at start-up | facts the model would otherwise spend tool calls finding out, or guess |
| **`# Project instructions (from AGENTS.md)`** | the project's own file, if there is one | "how we work here", without you repeating it in every prompt |
| **`extra`** | the caller | room for later lessons to add a section without editing this function |

**The four tool rules,** and why each one earns its tokens:

```
# Using tools
- To find things, use `search` and `list_files`, not `bash`.
- Read a file with `read_file` before you edit it.
- Keep edits small. Change only what the task needs.
- Take one step at a time and check each result before the next.
```

- **`search` and `list_files`, not `bash`:** those tools are read-only, so lesson 5's policy runs them without asking you, and their output is capped and formatted for the model. `bash grep` would ask you every time.
- **Read before edit:** `edit_file` refuses an edit to an unread file anyway (lesson 4). Saying so up front saves the model a refused call.
- **Small edits, one step at a time:** a small model does better with a short, positive instruction than a list of "never"s.

**Why the parts are built this way:**

- **The date and the time are parameters** (`now`), so the tests can fix them. A prompt that changes every second can't be compared with an expected string.
- **The tool names come from the registry**, not a hand-written list. If lesson 9 adds `todo_write`, the prompt mentions it without anyone editing it.
- **`extra` is a hook for later lessons**, so they can add a section without changing this function's signature.

**`git_summary(root)`** turns `git status --porcelain -b` into one line: `branch main, 2 changed file(s)`, or `not a git repository`, or `git not available`.

- **It never raises.** A missing `git`, a folder that isn't a repository, or a slow disk (`timeout=5`) all give a short line instead of a crash at start-up.
- **`GIT_OPTIONAL_LOCKS=0`** stops `git status` from taking the repository's lock. Otherwise starting the agent could make a `git commit` you're running at the same moment fail.
- **It handles the awkward cases:** a new repository with no commits (`No commits yet on main`) and a detached `HEAD`.
- **One line, not the whole status.** The model can run `git status` itself when it needs the detail. The prompt only says whether there's anything to look at.

**`load_project_instructions(root)`** looks for `AGENTS.md`, then `CLAUDE.md`, **only in the project root**, and returns `(filename, text)` for the first one found.

- **`AGENTS.md` first**, because it's the name several coding agents share. Claude Code's default is the other way round; swap the two names in `INSTRUCTION_FILES` to match it.
- **Capped at `MAX_INSTRUCTIONS_CHARS` (10,000)** with lesson 2's `truncate`. Ten kilobytes is roughly 2,500 tokens, about 8% of a 32K window, before the first question.
- **`errors="replace"`**, so a file with bad UTF-8 can't stop the agent starting.
- **One file, no imports, no searching parent folders.** Simple enough to test completely. The lesson's README says what Claude Code does differently.
- **The heading names the file** (`(from AGENTS.md)`), so you and the model can see where an instruction came from.

### `agent/__main__.py` (changed): passing it in

```python
tools = make_default_tools(ws)
agent = Agent(make_client(config), config.model, tools,
              system=build_system_prompt(ws, tools),
              ...)
```

The tools are now built first and kept in a variable, because the prompt needs their names. `build_system_prompt` runs once, when `ask` starts. The prompt doesn't change during a run, even if the git state does. Changing it mid-session would change the start of every request, so the model would see a different conversation each time.

## What's still missing, and which lesson adds it

| Gap in this version | What goes wrong | Fixed in |
|---|---|---|
| Only one instructions file, only in the root | instructions in a subfolder or your home folder are ignored | not in this course (Claude Code loads several) |
| The prompt doesn't mention the sandbox | the model still explains a refused network connection with a wrong story | not in this course (try adding a line, and measure it) |
| No plan or progress tracking | on a long task the model loses track of what it has done | lesson 9 |
| The prompt is built for `ask` only | a chat session needs the same prompt kept across many turns | lesson 7 |

## Seeing it work

From inside this folder, print the prompt the agent would use for any folder:

```
uv run python -c "from pathlib import Path; from agent.prompt import build_system_prompt; from agent.tools import make_default_tools; from agent.workspace import Workspace; ws = Workspace(Path('.')); print(build_system_prompt(ws, make_default_tools(ws)))"
```

Then put an `AGENTS.md` with one sentence in a scratch project, run `ask` there, and find the `# Project instructions` section in the first request in the log. The lesson's README measures what the prompt costs and what changes the model's behaviour. [TESTING.md](../../lessons/06-the-system-prompt/TESTING.md) shows the full prompt the reference solution builds.
