# Harness Engineering Course Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a 12-lesson course (lessons 0–11) in which the learner writes a local-model coding agent in Python, with a spec and tests for each lesson, a verified reference solution for each lesson, and a capstone eval.

**Architecture:** One `agent` package grows across lessons. The learner writes theirs in `agent/`; each lesson's reference solution is a complete snapshot in `solutions/NN-<name>/agent/`. Every lesson's tests import `agent`, and a root `conftest.py` decides which implementation gets imported (`--impl`). Tests use a scripted fake of the `openai` client built from real `openai` types, so they are deterministic and need no server.

**Tech Stack:** Python ≥3.10 (system 3.10.12), `uv`, `openai` 2.x (2.24.0 installed), `pytest`, `rich`, bubblewrap (`/usr/bin/bwrap`). Live model: LM Studio at `http://localhost:1234/v1`, `qwen/qwen3.8-27b`, 32K context. Weak model: Ollama at `http://localhost:11434/v1`, `qwen3:4b-instruct`.

**Spec:** `docs/superpowers/specs/2026-10-30-harness-course-design.md` (approved 2026-10-30). Read it before any task.

## Global Constraints

- No agent frameworks. The `openai` package is the only thing that talks to the model.
- Runtime dependencies: `openai>=2.0`, `rich`. Dev: `pytest`. Anything else needs a written reason in the lesson.
- `requires-python = ">=3.10"`. No `tomllib`, no 3.11+ syntax (`except*`, `Self`, etc.).
- No hard-coded model name or URL in agent code paths; they come from `Config`.
- Default `pytest` runs need no model server and are deterministic. Live tests are `@pytest.mark.live` and run only with `--live`. Real-bubblewrap tests are `@pytest.mark.sandbox` and are skipped when `bwrap` isn't usable.
- Lesson text describes; it does not contain the implementation. Small snippets of API shapes or formats are fine.
- Every "How Claude Code does it" claim is labeled **Documented** (with a link to the current page under `https://code.claude.com/docs/`, fetched and checked during the task), **Observed**, or **Design note**. When unsure, use the weaker label.
- Refer to the learner as "you" in lesson text. No name, no gendered pronouns.
- Every reference solution passes its own lesson's tests and every earlier lesson's tests (checked by `scripts/check_solutions.py`).
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Work on the current branch (`master`, a brand-new repo). Do not push; the user decides about pushing.

## Review Focus

1. **Binary or non-UTF-8 file passed to `read_file`/`search`** → `read_file` returns an `Error:` string; `search` skips the file. No crash. (Test in Task 4.)
2. **`bash` command that hangs or prints megabytes** → killed at the timeout with partial output and a `[timed out after Ns]` marker; output capped by truncation. (Test in Task 4.)
3. **Model server unreachable or erroring mid-session** → `Agent.run` returns `stop_reason="error"` with a readable message; history keeps the user message and stays valid for a retry. (Test in Task 5.)
4. **Symlink inside the project pointing outside it** → `Workspace.resolve` follows it and refuses. (Test in Task 7.)
5. **Server rejects a request for exceeding the context window** → compact once and retry; if it fails again, `stop_reason="error"`. (Test in Task 10.)

---

## File Structure

```
pyproject.toml                       uv project; pytest config (markers, --import-mode=importlib)
conftest.py                          --impl / --live options, sys.path switch, marker skips
README.md                            course index, setup, how to run tests
testing/__init__.py
testing/fake_model.py                FakeClient + response builders (provided to learner)
testing/test_fake_model.py           tests for the fake itself
scripts/check_solutions.py           runs lesson NN tests against solutions NN..11
agent/__init__.py                    learner's skeleton (docstring only)
lessons/NN-<name>/README.md          lesson text
lessons/NN-<name>/tests/test_*.py    lesson tests (file names unique across lessons)
solutions/NN-<name>/agent/...        reference package snapshot at end of lesson NN
capstone/buggy_project/              the planted-bug project (Task 13)
capstone/eval/check.py               provided checker
capstone/eval/hidden_tests/          tests the agent never sees
```

Lesson directory names (used everywhere): `00-setup`, `01-the-loop`, `02-tools`, `03-when-the-model-gets-it-wrong`, `04-editing-files`, `05-permissions-and-sandboxing`, `06-the-system-prompt`, `07-the-terminal`, `08-context`, `09-plans-and-checking-work`, `10-subagents`, `11-capstone`.

Reference package modules (introduced in the lesson shown):

| Module | Lesson | Responsibility |
|---|---|---|
| `agent/config.py` | 0 | `Config`, `load_config` |
| `agent/client.py` | 0 | `make_client`, `smoke_test` |
| `agent/__main__.py` | 0 | argparse CLI; subcommands added per lesson |
| `agent/log.py` | 1 | `RequestLog`, `read_log`, `latest_log`, `format_entry` |
| `agent/messages.py` | 1 | `message_to_dict`, `Usage` |
| `agent/tools/registry.py` | 1 | `Tool`, `ToolRegistry`, `truncate` (L2), validation (L3) |
| `agent/workspace.py` | 1 | `Workspace` |
| `agent/tools/files.py` | 1 | `read_file` (L1), `list_files`, `search` (L2), `edit_file`, `write_file`, `FileTracker` (L4) |
| `agent/tools/shell.py` | 2 | `bash` |
| `agent/tools/__init__.py` | 1 | `make_default_tools` |
| `agent/loop.py` | 1 | `Agent`, `TurnResult` |
| `agent/permissions.py` | 5 | `PermissionPolicy`, `Decision`, `Approver` |
| `agent/sandbox.py` | 5 | `SandboxConfig`, `build_bwrap_argv`, `sandbox_available` |
| `agent/prompt.py` | 6 | `build_system_prompt`, `load_project_instructions`, `git_summary` |
| `agent/events.py` | 7 | `AgentEvents` |
| `agent/stream.py` | 7 | `accumulate` |
| `agent/cli.py` | 7 | REPL (`chat`) |
| `agent/context.py` | 8 | `ContextManager`, `estimate_tokens`, `trim_old_tool_results`, `split_index`, `compact` |
| `agent/tools/todo.py` | 9 | `todo_write` |
| `agent/tools/subagent.py` | 10 | `make_subagent_tool` |
| `agent/headless.py` | 11 | `run_task`, `RunReport`, `SandboxUnavailable` |
| `agent/eval.py` | 11 | `run_eval`, `EvalReport`, `RunOutcome` |

## The Lesson Task Procedure (Tasks 2–12, 14)

Each lesson task follows these steps. The task itself lists the files, the interface, the tests, and what the README must cover.

- [ ] **A. Write the lesson's tests** in `lessons/NN-<name>/tests/`, exactly the tests the task lists (more are fine).
- [ ] **B. Create the solution snapshot**: `cp -r solutions/<previous>/agent solutions/NN-<name>/agent` (lesson 0 starts empty).
- [ ] **C. Run the new tests against the snapshot; they must fail.** `uv run pytest lessons/NN-<name> --impl solutions/NN-<name>` → FAIL (import error or assertion).
- [ ] **D. Implement the lesson's interface** in the snapshot.
- [ ] **E. Run the check.** `uv run python scripts/check_solutions.py --upto NN` → every lesson 0..NN passes against solution NN (and earlier solutions still pass their lessons).
- [ ] **F. Live check** against LM Studio: the task's live test(s) with `uv run pytest lessons/NN-<name> --impl solutions/NN-<name> --live`, plus the "Try it live" exercise run by hand. Write down real observations (shapes, token counts, failures) for the README. If the 4B "break it" exercise doesn't produce the failure the README promises, rewrite the exercise to match what really happens.
- [ ] **G. Write `lessons/NN-<name>/README.md`** with these sections, in order: `## Why this exists`, `## How Claude Code does it`, `## What you'll build` (the spec: modules, exact signatures, exact strings the tests check, behavior; never the implementation), `## Tests` (the command to run), `## Try it live`, `## Break it` (the 4B exercise), `## Extras`. Start with one line: "Start from your lesson NN-1 code, or copy `solutions/<previous>/agent` into `agent/`." Fetch every Documented link and confirm the claim.
- [ ] **H. Commit** `lessons/NN-<name>` and `solutions/NN-<name>` with message `Add lesson NN: <title>`.

---

### Task 1: Repository scaffold and test infrastructure

**Files:**
- Create: `pyproject.toml`, `conftest.py`, `.gitignore`, `testing/__init__.py`, `testing/fake_model.py`, `testing/test_fake_model.py`, `scripts/check_solutions.py`, `agent/__init__.py`, `README.md` (skeleton: title, setup, test commands; the lesson index is completed in Task 15)

**Interfaces:**
- Produces:
  - pytest options `--impl PATH` (default: repo root) and `--live`; markers `live`, `sandbox`. In `pytest_configure`, insert the resolved `--impl` path at `sys.path[0]` and drop any cached `agent*` modules from `sys.modules`. Skip `live` tests unless `--live`. Skip `sandbox` tests unless `shutil.which("bwrap")` and running `bwrap --ro-bind / / true` exits 0.
  - `testing.fake_model`:
    - `call(name: str, arguments: dict | str, id: str | None = None) -> dict` — one tool call spec; dict arguments are `json.dumps`ed; ids default to `call_1`, `call_2`, … per `FakeClient`.
    - `reply(content: str | None = None, tool_calls: list[dict] | None = None, reasoning: str | None = None, prompt_tokens: int = 100, completion_tokens: int = 20, finish_reason: str | None = None) -> ChatCompletion` — a real `openai.types.chat.ChatCompletion`; `reasoning` goes in the message's extra field `reasoning_content` (the openai models allow extra fields); `finish_reason` defaults to `"tool_calls"` when there are tool calls, else `"stop"`.
    - `to_chunks(completion: ChatCompletion, text_chunk_size: int = 5) -> list[ChatCompletionChunk]` — splits content and reasoning into deltas; each tool call arrives as a first chunk with `index`, `id`, `name` and empty arguments, then argument fragments; the final chunk has `finish_reason` and `usage`.
    - `bad_request(message: str) -> openai.BadRequestError` and `connection_error() -> openai.APIConnectionError`, built with an `httpx.Request`/`httpx.Response` for `http://fake/v1/chat/completions`.
    - `FakeClient(script: list[ChatCompletion | list[ChatCompletionChunk] | Exception])` with `.chat.completions.create(**kwargs)`: records a deep copy of `kwargs` in `.requests`, pops the next item; raises it if it's an exception; if `kwargs.get("stream")` and the item is a `ChatCompletion`, returns `iter(to_chunks(item))`; raises `AssertionError("FakeClient ran out of scripted responses")` when the script is empty.
  - `scripts/check_solutions.py [--upto NN]`: for each solution `S` in order up to NN, runs `pytest lessons/<L> --impl solutions/S -q` for every lesson `L ≤ S`; prints a pass/fail grid; exits non-zero on any failure. Missing solution dirs are reported, not crashed on.

- [ ] **Step 1: `uv init --bare`, then `uv add openai rich` and `uv add --dev pytest`.** In `pyproject.toml` set `requires-python = ">=3.10"` and `[tool.pytest.ini_options] addopts = "--import-mode=importlib"`, `testpaths = ["lessons", "testing", "capstone/eval"]`, `pythonpath = ["."]` (so `testing` imports; `--impl` is inserted ahead of it), markers `live` and `sandbox`. `.gitignore`: `.venv/`, `__pycache__/`, `.agent/`, `.pytest_cache/`.
- [ ] **Step 2: Write `testing/test_fake_model.py`:**

```python
def test_reply_with_tool_call_shape():
    c = reply(tool_calls=[call("read_file", {"path": "a.txt"})])
    m = c.choices[0].message
    assert c.choices[0].finish_reason == "tool_calls"
    assert m.tool_calls[0].function.name == "read_file"
    assert json.loads(m.tool_calls[0].function.arguments) == {"path": "a.txt"}

def test_reasoning_is_extra_field():
    m = reply(content="hi", reasoning="thinking").choices[0].message
    assert m.reasoning_content == "thinking"

def test_client_records_and_pops():
    fc = FakeClient([reply(content="one"), reply(content="two")])
    r = fc.chat.completions.create(model="m", messages=[{"role": "user", "content": "x"}])
    assert r.choices[0].message.content == "one"
    assert fc.requests[0]["model"] == "m"

def test_client_exhausted():
    with pytest.raises(AssertionError, match="ran out"):
        FakeClient([]).chat.completions.create(model="m", messages=[])

def test_stream_reassembles():  # concatenating deltas gives back content and full arguments
    ...

def test_scripted_exception_is_raised():
    fc = FakeClient([connection_error()])
    with pytest.raises(openai.APIConnectionError):
        fc.chat.completions.create(model="m", messages=[])
```

- [ ] **Step 3: Run `uv run pytest testing -q`** → FAIL (module missing).
- [ ] **Step 4: Implement `testing/fake_model.py`, `conftest.py`, `scripts/check_solutions.py`, `agent/__init__.py`** (docstring: "Your agent. Build it lesson by lesson; see lessons/00-setup.").
- [ ] **Step 5: Run `uv run pytest testing -q`** → PASS. Run `uv run python scripts/check_solutions.py` → reports no solutions, exits 0.
- [ ] **Step 6: Live sanity check:** with LM Studio up, compare one real `client.chat.completions.create` response (one tool) against `reply(...)`: same attribute paths for `tool_calls`, `finish_reason`, `usage`, and `reasoning_content` reachable as an attribute. Do the same for a real streamed response vs. `to_chunks`. Fix the fake if they differ.
- [ ] **Step 7: Commit** `Add course scaffold and test infrastructure`.

### Task 2: Lesson 0 — Setup

**Files:** `lessons/00-setup/{README.md,tests/test_setup.py}`, `solutions/00-setup/agent/{__init__.py,config.py,client.py,__main__.py}`

**Interfaces:**
- Produces:
  - `Config` — frozen dataclass: `base_url: str = "http://localhost:1234/v1"`, `model: str = "qwen/qwen3.8-27b"`, `api_key: str = "lm-studio"`, `context_window: int = 32768`, `log_dir: Path = Path(".agent/logs")`.
  - `load_config(env: Mapping[str, str] | None = None, file: Path | None = None) -> Config` — defaults, then `file` (JSON object with the same field names) if given and present, then env vars `AGENT_BASE_URL`, `AGENT_MODEL`, `AGENT_API_KEY`, `AGENT_CONTEXT_WINDOW`, `AGENT_LOG_DIR`. `env=None` means `os.environ`; `file=None` means `Path("agent.json")`.
  - `make_client(config: Config) -> openai.OpenAI`.
  - `smoke_test(client, model: str) -> SmokeResult` — sends one user message asking to read `notes.txt` with a single `read_file` tool; `SmokeResult` dataclass: `ok: bool`, `tool_name: str | None`, `arguments: dict | None`, `prompt_tokens: int | None`, `detail: str`. `ok` is true when the reply has a `read_file` call whose arguments parse to a dict with a `path` key.
  - CLI `python -m agent smoke` prints the result and exits 0/1.

Tests (`test_setup.py`):
- `test_defaults`: `load_config(env={}, file=Path("/nonexistent"))` equals `Config()`.
- `test_env_overrides_file`: file sets `model="a"`, env sets `AGENT_MODEL="b"` → `model == "b"`; file's other fields applied; `AGENT_CONTEXT_WINDOW="8192"` → `8192` (int).
- `test_smoke_ok`: `FakeClient([reply(tool_calls=[call("read_file", {"path": "notes.txt"})])])` → `ok`, `tool_name == "read_file"`, request sent exactly one tool named `read_file`.
- `test_smoke_no_tool_call`: `reply(content="I can't")` → `ok is False`, `detail` mentions no tool call.
- `test_smoke_bad_json`: arguments `"{not json"` → `ok is False`.
- `test_live_smoke` (`live`): real server → `ok`.

README must cover: what a harness is (model, loop, tools, context, permissions) with a small diagram; starting LM Studio's server and loading the model with 32K context (`lms load qwen/qwen3.8-27b --context-length 32768`); where LM Studio's developer log is; Ollama for the 4B (`AGENT_BASE_URL=http://localhost:11434/v1 AGENT_MODEL=qwen3:4b-instruct`); `uv sync`; how `--impl` works; the real observations from 2026-10-30 (arguments are a JSON string, `reasoning_content`, 329 prompt tokens for one tool). Claude Code claims: **Observed** — Claude Code shows the environment it runs in (working dir, platform, date) to the model (this ties forward to lesson 6).

### Task 3: Lesson 1 — The loop

**Files:** `lessons/01-the-loop/{README.md,tests/test_loop.py,tests/test_log.py}`, solution adds `log.py`, `messages.py`, `workspace.py`, `loop.py`, `tools/{__init__.py,registry.py,files.py}`; CLI adds `ask` and `log`.

**Interfaces:**
- Consumes: `Config`, `make_client` (Task 2).
- Produces:
  - `Tool` dataclass: `name: str`, `description: str`, `parameters: dict` (JSON schema), `fn: Callable[..., str]`, `read_only: bool = False`.
  - `ToolRegistry`: `register(tool) -> None`, `get(name) -> Tool | None`, `names() -> list[str]`, `schemas() -> list[dict]` (OpenAI form `{"type": "function", "function": {"name", "description", "parameters"}}`), `dispatch(name: str, raw_arguments: str) -> str` (L1: `json.loads` then `fn(**args)`).
  - `Workspace(root: Path)`: `.root` (resolved absolute), `.resolve(path: str) -> Path` (relative paths join `root`).
  - `make_default_tools(ws: Workspace, **kwargs) -> ToolRegistry` — L1: `read_file`.
  - `read_file(path: str, offset: int = 1, limit: int = 2000)` tool: lines formatted `f"{n:>6}\t{line}"`, 1-based, `read_only=True`; missing file → `"Error: file not found: <path>"`.
  - `Usage` dataclass: `prompt_tokens: int = 0`, `completion_tokens: int = 0`; `__add__`.
  - `message_to_dict(msg) -> dict` — `{"role": "assistant", "content": str | None}` plus `"tool_calls": [{"id", "type": "function", "function": {"name", "arguments"}}]` only when there are tool calls. `reasoning_content` is not kept.
  - `RequestLog(path: Path, agent: str = "main")`: `record(request: dict, response: dict, duration_s: float) -> None` appends one JSON line `{"ts": ISO-8601, "agent", "duration_s", "request", "response"}`; `RequestLog.for_session(log_dir: Path) -> RequestLog` creates `log_dir/YYYYmmdd-HHMMSS.jsonl`; `with_agent(name: str) -> RequestLog` (same file, different `agent`). `read_log(path) -> list[dict]`, `latest_log(log_dir) -> Path | None`, `format_entry(entry: dict) -> str`.
  - `TurnResult` dataclass: `final_text: str`, `stop_reason: str` (L1: `"done"`), `turns: int`, `usage: Usage`, `error: str | None = None`.
  - `Agent(client, model: str, tools: ToolRegistry, *, system: str | None = None, log: RequestLog | None = None)`; `.messages: list[dict]` (starts with the system message if given); `run(user_message: str) -> TurnResult`. Each request sends `model`, `messages`, `tools=tools.schemas()`; each response's tool calls are run in order and answered with `{"role": "tool", "tool_call_id": id, "content": result}`; stops when a response has no tool calls; `final_text` is that response's content or `""`.
  - CLI: `python -m agent ask "<prompt>" [--root DIR]` (prints final text; logs to `config.log_dir`); `python -m agent log [PATH]` (default `latest_log`; prints `format_entry` for each line with `rich`).

Tests:
- `test_single_tool_round_trip`: script `[reply(tool_calls=[call("read_file", {"path": "a.txt"})]), reply(content="It says hello")]` with `a.txt` = `"hello\n"` → `final_text == "It says hello"`, `turns == 2`; second request's last message is `{"role": "tool", "tool_call_id": "call_1", "content": "     1\thello"}`.
- `test_two_tool_calls_in_one_reply`: both answered, in order, ids matched.
- `test_no_tool_call_ends_turn`: one reply → `turns == 1`, `stop_reason == "done"`.
- `test_none_content_with_no_tools`: `reply(content=None)` → `final_text == ""`.
- `test_reasoning_not_in_history`: reply with `reasoning="x"` → no message in `agent.messages` has `reasoning_content`.
- `test_usage_summed`: two replies of 100/20 → `usage == Usage(200, 40)`.
- `test_history_persists_across_runs`: second `run` sends the earlier messages.
- `test_read_file_offset_limit`: 5-line file, `offset=2, limit=2` → lines 2–3 numbered 2 and 3.
- `test_log_written` (`test_log.py`): after a run, the log has 2 lines; each has `request.messages` and `response.choices`; `agent == "main"`.
- `test_with_agent_shares_file`; `test_latest_log_picks_newest`; `test_format_entry_shows_tool_calls`.
- `test_live_read_file` (`live`): real model reads a temp file and its answer contains the file's marker word.

README must cover: roles, `tool_call_id` pairing, `finish_reason`; why reasoning is dropped from history by default (cost; Qwen's chat template convention — check the model card) and kept in the log; the request log vs. LM Studio's developer log (the chat template turns messages + tools into one prompt; have the learner find the rendered prompt in LM Studio). Claude Code claims: **Observed** — Claude Code's file-reading tool returns `cat -n`-style numbered lines and reads up to 2000 lines by default with offset/limit.

### Task 4: Lesson 2 — Tools

**Files:** `lessons/02-tools/{README.md,tests/test_tools.py}`, solution adds `tools/shell.py`, extends `files.py`, `registry.py`, `tools/__init__.py`.

**Interfaces:**
- Consumes: `Tool`, `ToolRegistry`, `Workspace`, `make_default_tools` (Task 3).
- Produces:
  - `MAX_TOOL_OUTPUT = 20_000`; `truncate(text: str, limit: int = MAX_TOOL_OUTPUT) -> str` — unchanged if `len(text) <= limit`; else first `limit // 2` chars + `f"\n[... {n} characters truncated ...]\n"` + last `limit // 2` chars, where `n` is the number removed. `dispatch` truncates every result.
  - `list_files(pattern: str = "**/*", path: str = ".")` — sorted relative POSIX paths of files only; skips `.git`, `.venv`, `__pycache__`, `node_modules`; at most 500, then `f"[{k} more files not shown]"`. `read_only=True`.
  - `search(pattern: str, path: str = ".", glob: str | None = None)` — Python `re`; lines `f"{relpath}:{lineno}: {line}"`; same skips; skips files that aren't valid UTF-8; at most 200 matches then `f"[{k} more matches not shown]"`; invalid regex → `"Error: invalid regular expression: <msg>"`; no matches → `"No matches."`. `read_only=True`.
  - `bash(command: str, timeout: int = 30)` — `bash -c` in `ws.root`, stdout+stderr combined, result `f"{output}\n[exit code: {code}]"`; on timeout kill the process group and return `f"{partial}\n[timed out after {timeout}s]"`.
  - `make_default_tools(ws, *, confirm_bash: Callable[[str], bool] | None = None)` — registers `read_file`, `list_files`, `search`, `bash`. When `confirm_bash` returns False, `bash` returns `"Error: the user declined to run this command."` without running it. CLI `ask` passes a `rich` y/n prompt as `confirm_bash`.
  - `read_file` on a non-UTF-8 file → `"Error: <path> is not a UTF-8 text file."`

Tests:
- `test_truncate_exact`: `truncate("a" * 30, limit=10)` == `"aaaaa\n[... 20 characters truncated ...]\naaaaa"`; short text unchanged.
- `test_dispatch_truncates`: a tool returning 50,000 chars → result length < 20,100 and contains `"characters truncated"`.
- `test_list_files_skips_git_and_sorts`, `test_list_files_glob`.
- `test_search_matches_format`: `"src/a.py:3: def foo():"`; `test_search_invalid_regex`; `test_search_no_matches`; `test_search_skips_binary` (a file with `b"\xff\xfe\x00"` doesn't crash and is skipped).
- `test_read_file_binary_returns_error` (Review Focus 1).
- `test_bash_exit_code`: `bash("echo hi; exit 3")` == `"hi\n\n[exit code: 3]"`.
- `test_bash_timeout`: `bash("echo start; sleep 10", timeout=1)` returns within 3 s, contains `"start"` and `"[timed out after 1s]"` (Review Focus 2).
- `test_bash_huge_output_is_truncated_by_dispatch`: `yes | head -c 200000` via dispatch → contains `"characters truncated"`.
- `test_bash_declined`: `confirm_bash=lambda c: False` → declined message and a marker file is not created.
- `test_live_finds_function` (`live`): the model uses `search` or `list_files` to find which file defines a function in a small temp project.

README must cover: writing tool descriptions the model follows (show the effect of a vague vs. clear description in the logs); why output must be capped; the fixed token cost of tool schemas (live exercise: `prompt_tokens` with 1 tool vs. 4 tools); a plain warning that `bash` runs unsandboxed until lesson 5, so live exercises run in a scratch copy and you confirm each command. Claude Code claims: **Observed** — when a command's output is very large, Claude Code saves the full output to a file and gives the model a preview plus the file path; **Observed** — Claude Code loads some tool schemas only on demand (deferred tools fetched by a search tool) to save context; **Observed** — its shell tool has a 2-minute default timeout, 10-minute max.

### Task 5: Lesson 3 — When the model gets it wrong

**Files:** `lessons/03-when-the-model-gets-it-wrong/{README.md,tests/test_errors.py}`; solution extends `registry.py`, `loop.py`.

**Interfaces:**
- Consumes: `ToolRegistry.dispatch`, `Agent` (Tasks 3–4).
- Produces (exact strings):
  - `dispatch` never raises. Unknown tool → `f"Error: unknown tool '{name}'. Available tools: {', '.join(names)}"`. Bad JSON → `f"Error: arguments were not valid JSON ({exc.msg}). Send the arguments as a JSON object."`. Arguments not an object → `"Error: arguments must be a JSON object."`. Validation errors (from `validate_args`) → `"Error: " + "; ".join(errors)`. Tool raises → `f"Error: {type(exc).__name__}: {exc}"`.
  - `validate_args(schema: dict, args: dict) -> list[str]` — checks `required` (`f"missing required parameter '{p}'"`), unknown keys (`f"unknown parameter '{k}'"`), and JSON types `string`/`integer`/`number`/`boolean`/`array`/`object` (`f"parameter '{k}' must be {type}"`; booleans are not integers).
  - `Agent(..., max_turns: int = 50)`; on reaching it, `stop_reason == "max_turns"`, `final_text == ""`.
  - `LOOP_THRESHOLD = 3`: when the same `(name, raw_arguments)` is requested for the 3rd consecutive time, it is not executed; the result is `"Error: you have made this exact call 3 times in a row. Try a different approach."`.
  - Any `openai.APIError` (including connection errors) from `create` → `stop_reason == "error"`, `error == f"Model request failed: {exc}"`; nothing is appended for the failed request, so `agent.messages` stays valid.

Tests:
- `test_unknown_tool`, `test_bad_json`, `test_arguments_not_object`, `test_missing_required`, `test_wrong_type`, `test_bool_is_not_integer`, `test_unknown_param`, `test_tool_exception` — each via `dispatch`, asserting the exact string.
- `test_error_fed_back_and_model_recovers`: script = bad JSON call, then a correct call, then text → `stop_reason == "done"`, the first tool message starts with `"Error: arguments were not valid JSON"`.
- `test_max_turns`: `max_turns=3`, script of 3 tool-call replies → `stop_reason == "max_turns"`, `len(fc.requests) == 3`.
- `test_loop_detection`: three identical `read_file` calls in 3 replies, then text → the 3rd tool result is the loop message and the file was read only twice (wrap the tool to count).
- `test_connection_error` (Review Focus 3): script `[connection_error()]` → `stop_reason == "error"`, `"Model request failed"` in `error`, `agent.messages[-1]["role"] == "user"`; a second `run` with a new script works.
- `test_live_4b_failures` (`live`, uses Ollama via env): runs 3 small tasks against the 4B and only asserts the run ends with a `stop_reason`; prints error tool results for the README exercise.

README must cover: the failure catalog (bad JSON, invented tools, missing params, repeating the same call, never stopping); errors as tool results so the model can fix itself; the `Break it` exercise against the 4B with request logs (use the Task 5 Step F observations, not guesses). Claude Code claims: **Observed** — when a tool call is invalid or fails, Claude Code returns an error message to the model as the tool result rather than stopping. Anything about Claude Code's internal retry logic → **Design note** unless documented.

### Task 6: Lesson 4 — Editing files

**Files:** `lessons/04-editing-files/{README.md,tests/test_edit.py}`; solution extends `files.py`, `workspace.py`, `tools/__init__.py`.

**Interfaces:**
- Consumes: `Workspace`, `read_file` (Tasks 3–4).
- Produces:
  - `FileTracker`: `mark_read(path: Path) -> None` (stores `st_mtime_ns` and content hash), `check(path: Path) -> str | None` (`None` when OK; else an error string). `Workspace.tracker: FileTracker`. `read_file` calls `mark_read`.
  - `edit_file(path: str, old_string: str, new_string: str, replace_all: bool = False)` — exact strings: not read → `"Error: read the file with read_file before editing it."`; changed on disk since read → `"Error: the file changed on disk since you last read it. Read it again before editing."`; `old_string == new_string` → `"Error: old_string and new_string are the same."`; not found → `"Error: old_string was not found in the file."`; found k>1 times without `replace_all` → `f"Error: old_string appears {k} times. Include more surrounding lines to make it unique, or set replace_all to true."`; success → `f"Edited {path} ({k} replacement{'s' if k != 1 else ''})."` and re-marks the file as read.
  - `write_file(path: str, content: str)` — new file: creates parent dirs, `f"Created {path}."`; existing file not read → same not-read error; existing and read → overwrite, `f"Wrote {path}."`.
  - Both registered in `make_default_tools`.

Tests: `test_edit_requires_read`, `test_edit_unique_match`, `test_edit_multiple_matches_error` (k reported), `test_edit_replace_all`, `test_edit_not_found`, `test_edit_same_strings`, `test_edit_detects_external_change` (modify file after read, bump mtime with `os.utime`), `test_edit_then_edit_again_without_reread_ok`, `test_write_new_file_creates_dirs`, `test_write_existing_requires_read`, `test_edit_preserves_trailing_newline_and_crlf`, `test_live_edit` (`live`: the model fixes a typo in a temp file using `edit_file`).

README must cover: why exact-match edits beat whole-file rewrites (output tokens, accidental damage, reviewable diffs); why read-before-edit and the stale-file check exist. Claude Code claims: **Observed** — its edit tool replaces an exact string that must be unique unless `replace_all` is set; it refuses to edit a file that hasn't been read in the conversation; it refuses to overwrite an existing file that hasn't been read; it notices when a file changed since it was read.

### Task 7: Lesson 5 — Permissions and sandboxing

**Files:** `lessons/05-permissions-and-sandboxing/{README.md,tests/test_permissions.py,tests/test_sandbox.py}`; solution adds `permissions.py`, `sandbox.py`; extends `workspace.py`, `tools/shell.py`, `loop.py`, `tools/__init__.py`, CLI.

**Interfaces:**
- Consumes: `Agent`, `ToolRegistry`, `Tool.read_only`, `bash` (Tasks 3–6).
- Produces:
  - `Decision` enum: `ALLOW`, `DENY`, `ASK`. `Approver = Callable[[str, dict], str]` returning `"yes"`, `"always"`, or `"no"`.
  - Rule syntax: `"tool"` or `"tool(pattern)"`; pattern matched with `fnmatch.fnmatchcase` against the tool's key argument: `bash` → `command`; `read_file`/`edit_file`/`write_file` → `path`; other tools have none (only bare rules match).
  - `SHELL_OPERATORS = (";", "&&", "||", "|", "`", "$(", ">", "<", "\n")`.
  - `PermissionPolicy(allow: list[str] = [], deny: list[str] = [], auto_approve: bool = False)`; `check(tool: Tool, args: dict) -> Decision`. Order: deny rule matches → DENY; `tool.read_only` → ALLOW; allow rule matches → ALLOW (but a `bash` command containing any `SHELL_OPERATORS` never matches an allow rule); `auto_approve` → ALLOW; else ASK. `remember(tool: Tool, args: dict) -> None` adds `f"bash({glob.escape(command)})"` for bash, else the bare tool name.
  - `Agent(..., permissions: PermissionPolicy | None = None, approver: Approver | None = None)`. With `permissions=None` everything runs (keeps lessons 1–4 tests valid). DENY → tool result `"Error: this call is blocked by a deny rule."`; ASK with "no" → `"Error: the user denied this tool call."`; ASK with no approver → `"Error: this call needs approval but no approver is available."`; "always" → `remember` then run.
  - `Workspace.resolve` now raises `PathOutsideProject(path)` when the fully resolved path (symlinks followed) is not inside `root`; file tools turn it into `f"Error: {path} is outside the project folder."`.
  - `SandboxConfig(enabled: bool = True, network: bool = False, extra_writable: list[Path] = [])`; `Workspace(root, sandbox: SandboxConfig | None = None)`.
  - `build_bwrap_argv(command: str, cwd: Path, root: Path, cfg: SandboxConfig) -> list[str]` — exactly, in order: `["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp", "--bind", str(root), str(root)]`, then `["--bind", str(p), str(p)]` for each extra, then `"--unshare-net"` if not `cfg.network`, then `["--die-with-parent", "--chdir", str(cwd), "--", "bash", "-c", command]`.
  - `sandbox_available() -> bool` — `bwrap` on PATH and `bwrap --ro-bind / / true` exits 0.
  - `bash` uses `build_bwrap_argv` when `ws.sandbox` is set and enabled; output/timeout behavior unchanged.
  - CLI `ask`: `--sandbox/--no-sandbox` (default on when available), `--allow RULE` (repeatable); the approver is a `rich` prompt `[y]es / [a]lways / [n]o`. `confirm_bash` from lesson 2 is no longer used by the CLI.

Tests (`test_permissions.py`): `test_read_only_allowed`, `test_mutating_asks`, `test_deny_beats_allow`, `test_allow_prefix_rule` (`bash(pytest*)` allows `pytest -q`), `test_operators_never_auto_allowed` (`bash(git status*)` does not allow `git status && rm -rf x`), `test_auto_approve`, `test_remember_escapes_glob_chars` (command `ls *.py` then `ls a.py` is not allowed by the remembered rule), `test_agent_denied_result`, `test_agent_no_approver`, `test_agent_always_then_no_prompt` (approver called once for two identical edits), `test_path_outside_project` (`../x`), `test_symlink_escape` (Review Focus 4: symlink `inside -> /etc` then `read_file("inside/hostname")` → outside-project error).
Tests (`test_sandbox.py`): `test_argv_exact` (full list equality for a sample config), `test_argv_network_flag`, `test_tmpfs_before_root_bind` (index order, so a root under `/tmp` stays visible); `sandbox`-marked: `test_real_write_inside_ok`, `test_real_write_outside_blocked` (write to `Path.home() / ".harness_sandbox_probe"` fails, file absent after), `test_real_no_network` (`curl -s -m 2 http://localhost:1234` fails or `python -c` socket connect fails), `test_real_root_under_tmp_visible`.

README must cover: read-only vs. mutating; why prefix rules can't make `bash` safe (operators, scripts the agent writes, `python -c`); what bubblewrap does (mount namespaces, read-only bind of `/`, writable project bind, network namespace) and what it doesn't (it can still read your files, e.g. `~/.ssh`; network off is what stops them leaving; this is not production isolation). Claude Code claims to fetch and confirm: **Documented** — permission rules with `allow`/`deny` lists and specifiers like `Bash(npm run test:*)` (settings/permissions docs); **Documented** — Claude Code's sandboxed bash uses bubblewrap on Linux and Seatbelt on macOS (sandboxing docs); **Documented** — permission modes including one that auto-approves; **Observed** — this session's approval prompts and "don't ask again" options.

### Task 8: Lesson 6 — The system prompt

**Files:** `lessons/06-the-system-prompt/{README.md,tests/test_prompt.py}`; solution adds `prompt.py`; CLI `ask` uses it.

**Interfaces:**
- Consumes: `Workspace`, `ToolRegistry` (earlier tasks).
- Produces:
  - `INSTRUCTION_FILES = ("AGENTS.md", "CLAUDE.md")`; `MAX_INSTRUCTIONS_CHARS = 10_000`.
  - `load_project_instructions(root: Path) -> tuple[str, str] | None` — `(filename, text)` for the first file in `INSTRUCTION_FILES` that exists in `root`; text truncated with `truncate(text, MAX_INSTRUCTIONS_CHARS)`.
  - `git_summary(root: Path) -> str` — `"not a git repository"` or `f"branch {name}, {n} changed file(s)"` (from `git status --porcelain -b`); never raises (git missing → `"git not available"`).
  - `build_system_prompt(ws: Workspace, tools: ToolRegistry, *, now: datetime | None = None, extra: str | None = None) -> str` — contains, in order: a role section; a `# Using tools` section (rules: prefer `search`/`list_files` over `bash` for finding things, read before editing, keep edits small, one step at a time); `# Environment` with lines `Working directory: {root}`, `Platform: {sys.platform}`, `Date: {YYYY-MM-DD}`, `Git: {git_summary}`, `Tools: {comma-separated names}`; `# Project instructions (from {filename})` + text, only when present; `extra` last.

Tests: `test_environment_lines` (fixed `now=datetime(2026, 10, 30)` → `"Date: 2026-10-30"`), `test_agents_md_preferred_over_claude_md`, `test_claude_md_used_alone`, `test_no_instructions_section_when_absent`, `test_instructions_truncated`, `test_git_summary_not_repo`, `test_git_summary_repo` (init a repo in `tmp_path`, one untracked file → `"1 changed file(s)"`), `test_tools_listed`, `test_live_follows_project_instruction` (`live`: `AGENTS.md` says "End every answer with the word BANANA."; answer ends with it).

README must cover: a system prompt built from parts; why wording matters; exercise: change one rule, run the same task twice, compare logs. Claude Code claims: **Documented** — CLAUDE.md files are loaded into context (memory docs; confirm the current locations and import syntax before stating them); **Observed** — the system prompt includes environment details (working directory, whether it's a git repo, platform, OS version, date, model name); **Design note** — `AGENTS.md` is a cross-tool convention used by other agents; check whether Claude Code reads it before saying anything about it.

### Task 9: Lesson 7 — The terminal

**Files:** `lessons/07-the-terminal/{README.md,tests/test_stream.py,tests/test_interrupt.py}`; solution adds `events.py`, `stream.py`, `cli.py`; extends `loop.py`; CLI adds `chat`.

**Interfaces:**
- Consumes: `Agent`, `message_to_dict`, `Usage` (earlier tasks); `to_chunks` (Task 1).
- Produces:
  - `AgentEvents` base class with no-op methods: `on_text(delta: str)`, `on_reasoning(delta: str)`, `on_tool_call(name: str, arguments: str)`, `on_tool_result(name: str, result: str)`.
  - `accumulate(chunks: Iterable[ChatCompletionChunk], events: AgentEvents) -> tuple[dict, Usage | None, str | None]` — returns `(assistant_message_dict, usage, finish_reason)` in the same dict shape as `message_to_dict`; tool calls assembled by `index`; calls `on_text`/`on_reasoning` per delta.
  - `Agent(..., events: AgentEvents | None = None, stream: bool = False)`; with `stream=True` requests add `stream=True, stream_options={"include_usage": True}`. The log's `response` for streamed requests is `{"streamed": True, "message": ..., "usage": ..., "finish_reason": ...}`. `on_tool_call`/`on_tool_result` fire in both modes.
  - Interrupt: `KeyboardInterrupt` raised while streaming or while a tool runs → `run` returns `stop_reason == "interrupted"`. History repair: a partially streamed reply is dropped; if an assistant message with tool calls is already in history, every call without a result gets `{"role": "tool", "tool_call_id": id, "content": "Error: interrupted by the user."}`. The next `run` works.
  - `python -m agent chat [--root DIR]`: REPL with `rich`; streams text; shows reasoning dimmed (toggle `/reasoning`); shows each tool call and a short result preview; Ctrl-C interrupts the turn, Ctrl-C at an empty prompt or `/exit` quits.

Tests: `test_accumulate_text`, `test_accumulate_tool_call_fragments` (arguments split across 4 chunks reassemble to valid JSON), `test_accumulate_two_tool_calls_interleaved_indexes`, `test_accumulate_reasoning_events`, `test_accumulate_usage_last_chunk`, `test_stream_agent_matches_nonstream` (same script → same `agent.messages`), `test_events_fire_for_tool_calls`, `test_interrupt_during_tool_repairs_history` (tool fn raises `KeyboardInterrupt`; second call in the same reply also gets the interrupted result; next `run` sends a valid history), `test_interrupt_during_stream_drops_partial` (chunk iterator raises `KeyboardInterrupt` midway), `test_live_stream_usage` (`live`: LM Studio returns usage with `include_usage`; if it doesn't, the README says so and the agent falls back to estimating in lesson 8).

README must cover: streamed tool-call assembly; what to do with history after an interrupt and why an unanswered tool call breaks the next request. Claude Code claims: **Documented** — Esc interrupts Claude mid-turn (interactive-mode docs; confirm); **Observed** — tool calls and results are shown as they happen, with long outputs collapsed.

### Task 10: Lesson 8 — Context

**Files:** `lessons/08-context/{README.md,tests/test_context.py}`; solution adds `context.py`; extends `loop.py`, `events.py`.

**Interfaces:**
- Consumes: `Agent`, `Config.context_window`, `truncate` (earlier tasks).
- Produces:
  - `estimate_tokens(messages: list[dict]) -> int` — `math.ceil(len(json.dumps(messages)) / 4)`.
  - `trim_old_tool_results(messages: list[dict], keep_recent: int = 6, min_chars: int = 500) -> list[dict]` — returns a new list; tool messages not among the last `keep_recent` messages with content longer than `min_chars` get content `f"[old tool result removed: {n} characters]"`.
  - `split_index(messages: list[dict], keep_recent: int) -> int` — start at `max(1, len - keep_recent)`, move backward until the message at that index has role `"user"` or `"assistant"` (never `"tool"`); never below 1.
  - `compact(messages: list[dict], client, model: str, keep_recent: int = 6) -> list[dict]` — summarizes `messages[1:i]` (`i = split_index`) with one model call (no tools; a fixed summarization prompt asking for goals, decisions, files touched, current state); result is `[messages[0]] + [summary] + messages[i:]` where summary is `{"role": "user", "content": "[Summary of earlier conversation]\n" + text}`; if `messages[i]` is a user message, the summary text is instead prepended to that message's content (no two user messages in a row). Assumes `messages[0]` is the system message.
  - `ContextManager(window: int, threshold: float = 0.8, keep_recent: int = 6)`: `.last_prompt_tokens: int | None` (updated from each response's `usage`); `needs_compaction(messages) -> bool` uses `last_prompt_tokens` plus `estimate_tokens` of messages added since, or `estimate_tokens(messages)` when no usage yet; compares to `threshold * window`.
  - `Agent(..., context: ContextManager | None = None)`: before each request, apply `trim_old_tool_results`, then `compact` if `needs_compaction`; fires `events.on_compact(before: int, after: int)` (new no-op method on `AgentEvents`). On `openai.BadRequestError` whose message contains `"context"` (case-insensitive): compact and retry once; second failure → `stop_reason == "error"`.

Tests: `test_estimate_tokens`, `test_trim_keeps_recent_and_small`, `test_split_never_on_tool_message`, `test_compact_shape` (system kept, summary second, summary request had no `tools`), `test_compact_merges_into_user_message`, `test_compact_keeps_tool_pairs` (every remaining tool message's `tool_call_id` appears in a remaining assistant message), `test_agent_compacts_when_over_threshold` (window 1000, `prompt_tokens=900` → next request is preceded by a summary call), `test_context_overflow_retry` (Review Focus 5: script `[bad_request("context length exceeded"), <summary reply>, reply(content="ok")]` → `stop_reason == "done"`), `test_context_overflow_twice_errors`, `test_live_overflow_message` (`live`: send an oversized prompt to LM Studio and record the real error message; assert the agent's `"context"` check matches it — if LM Studio's wording differs, update the check and the README).

README must cover: 32K fills fast (show a real session's `prompt_tokens` curve from logs); what to keep vs. drop; summaries lose detail; tokenizers differ (Qwen's isn't tiktoken; `usage` is the ground truth, the estimate is a fallback). Claude Code claims: **Documented** — `/compact` and automatic compaction (confirm in docs); **Observed** — Claude Code's own context gets summarized when the conversation grows long, and work continues from the summary.

### Task 11: Lesson 9 — Plans and checking work

**Files:** `lessons/09-plans-and-checking-work/{README.md,tests/test_todo.py,tests/test_verify.py}`; solution adds `tools/todo.py`; extends `workspace.py`, `loop.py`, `prompt.py`, `tools/__init__.py`.

**Interfaces:**
- Consumes: `Workspace`, `Agent`, `build_system_prompt` (earlier tasks).
- Produces:
  - `Workspace.todos: list[dict]`.
  - `todo_write(todos: list[dict])` tool (`read_only=True`; it changes only harness state) — each item `{"content": str, "status": "pending" | "in_progress" | "completed"}`; more than one `in_progress` → `"Error: only one item can be in_progress at a time."`; bad status → `f"Error: invalid status '{s}'."`; success replaces `ws.todos` and returns lines `"[x] ..."`, `"[>] ..."`, `"[ ] ..."`. Its schema uses `items` with an enum for `status`; extend `validate_args` only as far as needed for this (array of objects).
  - `Agent(..., verify: Callable[[], tuple[bool, str]] | None = None, max_verify_attempts: int = 2)` — when a reply has no tool calls and `verify` is set: run it; if it fails and fewer than `max_verify_attempts` checks have failed this `run`, append `{"role": "user", "content": f"[Automatic check failed]\n{output}\nFix the problem, then finish."}` and continue; otherwise stop. `TurnResult.verified: bool | None = None` (None when no `verify`).
  - `build_system_prompt` gains a rule: for multi-step work, keep a list with `todo_write`; before finishing a code change, run the tests.

Tests: `test_todo_replace_and_render`, `test_todo_two_in_progress_error`, `test_todo_bad_status`, `test_verify_pass_first_time` (`verified is True`, one `verify` call), `test_verify_fail_then_fix` (fail, model makes a call, pass → `verified is True`, the injected user message has the exact prefix), `test_verify_gives_up` (always fails → after 2 failed checks `verified is False`, `stop_reason == "done"`), `test_no_verify_is_none`, `test_live_uses_todo` (`live`: a 3-step task; assert only that the run finishes; print whether `todo_write` was used, for the README).

README must cover: keeping a weak model on track with an explicit list; the harness checking work instead of trusting "done"; compare runs with and without the check on the 4B. Claude Code claims: **Observed** — Claude Code has had a to-do list tool for multi-step work (check the current tool list and docs before naming it; if the current version differs, describe it accurately); **Documented** — hooks (e.g. a Stop hook) can run checks when Claude finishes and send results back (hooks docs; one paragraph, since hooks are out of scope); **Design note** — the `verify` callback.

### Task 12: Lesson 10 — Subagents

**Files:** `lessons/10-subagents/{README.md,tests/test_subagent.py}`; solution adds `tools/subagent.py`; extends `registry.py`, `log.py` if needed, `tools/__init__.py`.

**Interfaces:**
- Consumes: `Agent`, `ToolRegistry`, `RequestLog.with_agent`, `truncate` (earlier tasks).
- Produces:
  - `ToolRegistry.subset(names: Iterable[str]) -> ToolRegistry`.
  - `SUBAGENT_TOOLS = ("read_file", "list_files", "search")`; `SUBAGENT_MAX_TURNS = 20`; `SUBAGENT_MAX_ANSWER = 4000`.
  - `make_subagent_tool(client, model: str, tools: ToolRegistry, *, log: RequestLog | None = None) -> Tool` — tool `subagent(task: str)`, `read_only=True`. Each call builds a fresh `Agent` with `tools.subset(SUBAGENT_TOOLS)`, its own system prompt (search/read only; answer concisely with file paths and line numbers), `max_turns=SUBAGENT_MAX_TURNS`, and `log.with_agent(f"subagent-{k}")` (k counts from 1 per tool instance). Returns `truncate(final_text, SUBAGENT_MAX_ANSWER)`; on `max_turns` → `f"Subagent stopped after {SUBAGENT_MAX_TURNS} turns without finishing."`; on error → `f"Error: subagent failed: {error}"`.
  - `make_default_tools(ws, *, client=None, model=None, log=None, ...)` registers `subagent` only when `client` and `model` are given.

Tests: `test_subagent_gets_only_read_tools` (the subagent's request `tools` names == `SUBAGENT_TOOLS`), `test_subagent_fresh_context` (its first request has 2 messages: system + task), `test_parent_sees_only_answer` (parent's tool result == subagent's final text), `test_subagent_log_tag` (log lines tagged `subagent-1`), `test_subagent_max_turns_message`, `test_subagent_answer_truncated`, `test_live_subagent_search` (`live`: parent delegates "find where X is defined"; assert the answer names the right file).

README must cover: context isolation (the parent pays only for the answer); cost (more total tokens) vs. benefit; why subagents get fewer tools. Claude Code claims: **Observed** — Claude Code can start subagents (an Agent tool with types such as a read-only Explore agent) that run with their own context and hand back a final report; **Documented** — custom subagents defined in `.claude/agents/*.md` (confirm in docs).

### Task 13: Capstone project and checker

**Files:** `capstone/buggy_project/{README.md,ledger/__init__.py,ledger/models.py,ledger/parse.py,ledger/periods.py,ledger/report.py,tests/test_parse.py,tests/test_periods.py,tests/test_report.py}`, `capstone/eval/check.py`, `capstone/eval/hidden_tests/test_hidden.py`, `capstone/eval/test_check.py`.

**Interfaces:**
- Produces:
  - `ledger`: a small personal-finance library, roughly 200–350 lines total, standard library only. `models.Transaction(date: datetime.date, amount_cents: int, category: str, memo: str)`; `parse.parse_csv(text: str) -> list[Transaction]` (amounts like `"12.34"`, `"-5"`, to cents with `Decimal`); `periods.month_range(year: int, month: int) -> tuple[date, date]`; `report.monthly_totals(txns, year, month) -> dict[str, int]` and `report.month_summary(...)`.
  - **The planted bug:** `periods.month_range` returns an *inclusive* end (the last day of the month) and documents it that way; `report.monthly_totals` filters with `start <= t.date < end`, so transactions on the last day of the month are dropped. Finding it requires reading `report.py` and `periods.py`. `tests/test_periods.py` pins the inclusive end, so the only fix that leaves the tests untouched is in `report.py` (a few lines); changing `month_range` breaks a visible test.
  - Visible tests: all pass except `test_report.py::test_includes_last_day_of_month`, which fails.
  - `capstone/eval/check.py`: `check_fix(workdir: Path, original: Path) -> CheckResult` — `CheckResult(passed: bool, tests_modified: bool, output: str)`; `tests_modified` compares SHA-256 of every file under `tests/` in `workdir` vs. `original` (added/removed files count); `passed` = visible tests pass and `hidden_tests/test_hidden.py` passes when run against `workdir` (via `pytest` with `rootdir`/`PYTHONPATH` set to `workdir`) and not `tests_modified`.
  - Hidden tests check behavior both fixes satisfy: last-day transactions included, first-day included, next month's first day excluded, February in leap and non-leap years, December → January rollover.

- [ ] **Step 1:** Write `capstone/eval/test_check.py`: `test_unfixed_fails` (copy of the buggy project → `passed is False`, `tests_modified is False`), `test_fix_in_report_passes` (temp copy with the filter changed to `<= end`), `test_fix_in_periods_fails` (temp copy with `month_range` changed to an exclusive end → a visible test fails → `passed is False`), `test_deleting_failing_test_detected` (`tests_modified is True`, `passed is False`).
- [ ] **Step 2:** Run → FAIL (nothing exists).
- [ ] **Step 3:** Write the `ledger` project, its visible tests, the hidden tests, and `check.py`.
- [ ] **Step 4:** Run `uv run pytest capstone/eval/test_check.py -q` → PASS. Run the visible tests in `capstone/buggy_project` → exactly 1 failure.
- [ ] **Step 5:** Commit `Add capstone project and checker`.

(The root run collects `capstone/eval` only; `capstone/buggy_project/tests` and `capstone/eval/hidden_tests` are not in `testpaths` and are run only by `check_fix`. Add `--ignore=capstone/eval/hidden_tests` to `addopts`.)

### Task 14: Lesson 11 — Capstone

**Files:** `lessons/11-capstone/{README.md,tests/test_headless.py,tests/test_eval.py}`; solution adds `headless.py`, `eval.py`; CLI adds `run` and `eval`.

**Interfaces:**
- Consumes: everything above; `check_fix` (Task 13).
- Produces:
  - `SandboxUnavailable(Exception)`.
  - `RunReport` dataclass: `stop_reason: str`, `final_text: str`, `turns: int`, `prompt_tokens: int`, `completion_tokens: int`, `duration_s: float`, `log_path: Path | None`, `verified: bool | None`.
  - `run_task(task: str, root: Path, config: Config, *, client=None, require_sandbox: bool = True, verify_command: str | None = None, max_turns: int = 50) -> RunReport` — raises `SandboxUnavailable` when `require_sandbox` and not `sandbox_available()`; workspace with `SandboxConfig(enabled=require_sandbox)`; `PermissionPolicy(auto_approve=True)`; streaming off; `ContextManager(config.context_window)`; full system prompt; `verify` runs `verify_command` through the same sandboxed `bash` path when given. Default verify command for the CLI: `f"{sys.executable} -m pytest -q"`.
  - `RunOutcome(index: int, report: RunReport, check: CheckResult, workdir: Path)`; `EvalReport(runs: list[RunOutcome])` with `success_rate: float`, `mean_turns`, `mean_prompt_tokens`, `mean_duration_s`.
  - `run_eval(project: Path, task: str, n: int, config: Config, *, check: Callable[[Path, Path], CheckResult], workdir_base: Path, client_factory: Callable[[], Any] | None = None) -> EvalReport` — for each run: copy `project` to `workdir_base / f"run-{i:02d}"`, `run_task` there (fresh client per run), `check(workdir, project)`. Never touches `project`.
  - CLI: `python -m agent run "<task>" --root DIR` (refuses with a clear message if the sandbox is unavailable; `--unsafe-no-sandbox` exists and prints a warning); `python -m agent eval --project capstone/buggy_project --n 10 [--task TEXT]` prints a table (run, result, turns, tokens, seconds, log path) and the summary. Default task: `"The test suite has a failing test. Find the cause and fix it in the source code. Do not modify the tests."`

Tests: `test_requires_sandbox` (monkeypatch `sandbox_available` → False → `SandboxUnavailable`), `test_run_task_with_fake` (fake script edits a file, then finishes → `RunReport` fields filled, log file exists), `test_verify_command_used` (verify fails once, then passes), `test_eval_copies_and_never_touches_project` (hash of `project` unchanged; 2 workdirs exist), `test_eval_success_rate` (fake check returns pass/fail alternately over n=4 → `0.5`), `test_live_capstone_once` (`live`, `sandbox`: one real run on the buggy project; asserts only that it finishes and `check_fix` returns a result).

README must cover: measuring vs. eyeballing; reading failed runs' logs; the comparison exercise (27B vs. 4B vs. optionally Flint, noting Flint needs more memory than the 4090 alone); where to go next (hooks, MCP, Bionic/Claude Code/other harnesses as things to compare against). Claude Code claims: **Documented** — non-interactive mode (`claude -p`) (confirm); **Design note** — the eval loop.

### Task 15: Course index and final verification

**Files:** `README.md` (complete), possibly `capstone/buggy_project/*` (difficulty tuning).

- [ ] **Step 1:** Complete `README.md`: what the course is, prerequisites, setup (uv, LM Studio, Ollama, bubblewrap check), how lessons work, how to run tests (`uv run pytest lessons/NN-...`, `--impl`, `--live`), the lesson index with one line each, the accuracy labels explained.
- [ ] **Step 2:** Run `uv run python scripts/check_solutions.py` → full grid passes. Run `uv run pytest testing capstone/eval -q` → PASS.
- [ ] **Step 3:** Run all `live` tests against `solutions/11-capstone` with LM Studio up: `uv run pytest lessons --impl solutions/11-capstone --live` → PASS (record any flaky ones and why).
- [ ] **Step 4:** Run `uv run python -m agent eval --project capstone/buggy_project --n 10` with `PYTHONPATH=solutions/11-capstone` against the 27B. Expected: success rate between 20% and 90%. If it's outside that range, adjust the bug's difficulty in Task 13's project (and its tests), re-run `capstone/eval/test_check.py`, and repeat. Put the measured numbers (rate, mean turns, tokens, time) in `lessons/11-capstone/README.md` as "what we measured on 2026-xx-xx".
- [ ] **Step 5:** Run the same eval once against the 4B (`AGENT_BASE_URL=http://localhost:11434/v1 AGENT_MODEL=qwen3:4b-instruct`, n=10) and record it the same way.
- [ ] **Step 6:** Verify no reference-solution code appears in any lesson README (grep the READMEs for `def ` and review each hit).
- [ ] **Step 7:** Commit `Complete course index and record capstone measurements`.
