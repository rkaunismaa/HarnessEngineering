# Lesson 6: The system prompt

Start from your lesson 5 code, or copy `solutions/05-permissions-and-sandboxing/agent` into `agent/`.

## Why this exists

So far the agent has run with no system message at all (`Agent(..., system=None)`). The model gets the tool schemas and your question, and has to guess everything else: where it is, what day it is, whether this is a git repo, how this team likes its code, and how to use the tools well.

A system prompt is a message that goes first in every request. It is the one place where you, the harness author, talk to the model before the user does. Three things follow from that:

- **It is built from parts, not written once.** Some parts are fixed (the role, the tool rules). Some are measured when the agent starts (working directory, date, git state, the tool names). Some come from the project (an instructions file). Treat the prompt as the output of a function, and test that function.
- **It is paid for on every request.** The prompt is resent with each model call, and your context is 32K tokens. Every sentence has to earn its place. Measured with the reference prompt on the 27B: with and without it, the same one-word request differs by **153 prompt tokens** (1123 without, 1276 with; the six tool schemas are in both). A project `AGENTS.md` with one sentence added 20 more. Ten kilobytes of project instructions, the cap you will set, is on the order of 2,500 tokens, which is about 8% of the window gone before the first question.
- **Wording matters, and not evenly.** A small model follows a short, concrete, positive rule ("read a file before you edit it") more reliably than a long list of "never"s. Rules that describe something the model already does anyway change nothing (see *Try it live*). Rules that ask for a visible extra step often do change behavior, for a model big enough to follow them (see *Break it*).

Two further design points:

- **Environment lines beat questions.** If the model needs the working directory, a one-line fact costs fewer tokens than a `bash pwd` round trip.
- **Project instructions are the user's, not yours.** Teams already keep "how we work here" in a file in the repository. Loading it means the user does not have to repeat it in every prompt. Cap its size: the file is untrusted input that arrives in the most privileged position in the request. It can make the agent worse, and a long one crowds out the task.

## How Claude Code does it

- **Documented** ([How Claude remembers your project](https://code.claude.com/docs/en/memory)): `CLAUDE.md` files are markdown files of persistent instructions that Claude reads at the start of every session. They can live in several places: `~/.claude/CLAUDE.md` for you across all projects, `./CLAUDE.md` or `./.claude/CLAUDE.md` for the project, `./CLAUDE.local.md` for personal, uncommitted preferences, and (on Linux) `/etc/claude-code/CLAUDE.md` for an organization. Files in the directory above the working directory are loaded too and concatenated, not overridden; files in subdirectories load on demand when Claude reads a file there.
- **Documented** (same page): a `CLAUDE.md` can import other files with `@path/to/import` syntax. Relative paths resolve against the file that contains the import, and imports can nest to a maximum depth of four hops. The page says the files should stay short ("target under 200 lines") because longer files consume more context.
- **Documented** (same page): "CLAUDE.md content is delivered as a user message after the system prompt, not as part of the system prompt itself." Your harness puts the instructions in the system message. That is a different choice, not a copy of this one (see the design note below).
- **Documented** (same page, section *AGENTS.md*): Claude Code can read `AGENTS.md` as project instructions, but only as a fallback. By default it reads `AGENTS.md` when there is no `CLAUDE.md` (or `CLAUDE.local.md`) in the working directory or above it. If both exist, it reads the `CLAUDE.md` files only. A setting called `claude-md-and-agents-md` loads both. The page says reading `AGENTS.md` directly needs Claude Code v2.1.277 or later.
- **Observed**: Claude Code's own system prompt carries environment details: the working directory, whether it is a git repository, the platform, the shell, the OS version, the date, and the model name and ID. That is where this lesson's `# Environment` section comes from. (This is what Claude Code's system prompt looks like to the model in a session; it is not described on the memory page, and it may change between versions.)
- **Design note**: `AGENTS.md` is a convention several coding agents share, so this course prefers it. **That is the opposite order from Claude Code's default**, which prefers `CLAUDE.md`. The course picks `AGENTS.md` first because it is the tool-neutral name. If you want Claude Code's behavior, swap the two names in `INSTRUCTION_FILES`. The course also reads only one file, from the project root, and does not follow imports, walk up directories or load subdirectory files. Putting the text in the system message, rather than in a user message after it, is also a design choice; with a small model the system message is the place it pays most attention to, though this course has not measured that.

## What you'll build

One new module, `agent/prompt.py`, and one change in the `ask` command. Tests: `lessons/06-the-system-prompt/tests/test_prompt.py`.

**Constants**

- `INSTRUCTION_FILES = ("AGENTS.md", "CLAUDE.md")`
- `MAX_INSTRUCTIONS_CHARS = 10_000`

**`load_project_instructions(root: Path) -> tuple[str, str] | None`**

Look in `root` (only there) for each name in `INSTRUCTION_FILES`, in order. Return `(filename, text)` for the first that exists, or `None`. The text is cut with lesson 2's `truncate(text, MAX_INSTRUCTIONS_CHARS)`. A file with bad UTF-8 must not crash it.

**`git_summary(root: Path) -> str`**

Runs `git status --porcelain -b` in `root` on the host (not inside the sandbox) with a short timeout. It never raises. It returns:

- `"not a git repository"` when git exits non-zero
- `"git not available"` when git cannot be run (not installed, or it times out)
- otherwise `f"branch {name}, {n} changed file(s)"`, where `n` counts the status lines after the first and `name` comes from the first line, the one that starts `## `. That line has several shapes you must handle: `main`, `main...origin/main [ahead 1]` (the name is what comes before `...`), `No commits yet on main` (a new repository: the name is `main`), and `HEAD (no branch)` (detached HEAD: write `(detached HEAD)` as the name).

**`build_system_prompt(ws: Workspace, tools: ToolRegistry, *, now: datetime | None = None, extra: str | None = None) -> str`**

Sections, in this order, separated by blank lines:

1. A one-sentence role.
2. `# Using tools`, a short list of rules: find things with `search` and `list_files` rather than `bash`; read a file before editing it; keep edits small; take one step at a time.
3. `# Environment`, with exactly these line prefixes:
   `Working directory: {root}`, `Platform: {sys.platform}`, `Date: {YYYY-MM-DD}`, `Git: {git_summary}`, `Tools: {comma-separated tool names}`. `now` defaults to the current time; tests pass a fixed one.
4. `# Project instructions (from {filename})` followed by the text, only when `load_project_instructions` found something. With no file, the heading is absent.
5. `extra`, last, when given.

The exact wording of the role and rules is yours; the tests check the structure and that the rules name `search`, `list_files` and `bash`. Keep the whole thing short. The reference prompt is 517 characters without project instructions.

**CLI.** `ask` builds the registry first and passes `system=build_system_prompt(ws, tools)` to `Agent`.

## Tests

```
uv run pytest lessons/06-the-system-prompt                   # against your agent/
uv run pytest lessons/06-the-system-prompt --impl solutions/06-the-system-prompt
uv run pytest lessons/06-the-system-prompt --live            # + a model follows AGENTS.md
```

[TESTING.md](TESTING.md) walks through what each test checks and why.

Lessons 1 to 5 still apply. The tests check, among other things, the environment lines with a fixed date, `AGENTS.md` winning over `CLAUDE.md`, `CLAUDE.md` working alone, no instructions section when neither exists, truncation, `git_summary` in a real temporary repository (untracked file, clean after a commit, detached HEAD, and git missing), and that `extra` comes last. The live test puts `End every answer with the word BANANA.` in `AGENTS.md` and expects the 27B's answer to end with it.

## Try it live

Make a scratch project and give it instructions:

```
mkdir -p ~/scratch6 && cd ~/scratch6 && git init -q -b main && echo "remember the milk" > notes.txt
echo "End every answer with the word BANANA." > AGENTS.md
cd -    # back to the repository root
uv run python -m agent ask "What does notes.txt say?" --root ~/scratch6
```

What the reference run printed: the file's content, then `BANANA` on its own line. The 4B (`AGENT_BASE_URL=http://localhost:11434/v1 AGENT_MODEL=qwen3:4b-instruct AGENT_API_KEY=ollama`) did the same in 3 of 3 runs; with the prompt left out it never added the word (3 of 3). So a one-line instruction file reaches even the small model.

Now the cost. Send a one-word message to your model with and without the system message and compare `usage.prompt_tokens`. The reference prompt, in a git repo with the six tools, added 153 tokens. Adding `AGENTS.md` with that one sentence added 20 more.

**The exercise: change one rule, run the same task twice, compare logs.** Pick a task that takes a couple of requests, for example, in a folder with a few `.py` files, *"Which file defines compute_total? Answer with the path only."* Run it twice with your prompt as is and read the two logs with `python -m agent log`. Then add one rule to `# Using tools` and run it twice again:

> Before you answer, open the file you found with `read_file` to confirm.

What happened in the reference runs on the 27B: without the rule, one `search` call and the answer (2 requests), both times. With the rule, 3 requests both times: once a second `search` for the name, once the `read_file` the rule asked for. So the rule changed behavior, but not exactly the way it was written. Compare your logs for the number of requests, the tool calls and their arguments, and the prompt-token column, which grew by the cost of the new line on every request.

A rule can also do nothing. A first attempt reversed the existing rule (*"To find things, use `bash` with grep or find."*). The 27B and the 4B both kept calling `search`, in all 8 runs. The tool's own schema was a stronger signal than one sentence in the prompt.

## Break it

Run the same exercise on the 4B. In the reference runs the added `read_file` rule did nothing: in 2 of 2 runs with the rule, the 4B made one `search` call and answered, exactly as without it. The 27B followed the rule in both of its runs, though not by calling `read_file` each time. Write down what you see on your machine: for a small model, a rule that asks for an extra step is a suggestion, and you cannot tell from the prompt text which rules it will honor. You find out by running the task and reading the log.

A second thing to try: put two contradictory instructions in `AGENTS.md` (*"Always answer in one word."* and *"Always explain your reasoning in detail."*) and run the same question five times on each model. Look at whether the answers agree with each other and which instruction wins. This lesson does not give a result for it; run it and see.

## Extras

- Walk up from `root` and load instruction files from parent directories too, ordering them from the outermost down.
- Support `@path` imports in the instructions file, with a depth limit, and refuse paths outside the project using `Workspace.resolve`.
- Add `--system-extra TEXT` to `ask`, passed as `extra`.
- Deliver the instructions as a first user message instead of in the system message, as Claude Code does, and run the BANANA test both ways on the 4B.
- Add the model name to the `# Environment` section.
