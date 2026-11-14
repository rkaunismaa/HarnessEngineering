# Lesson 0 solution: where the agent starts

This folder is the reference solution for [lesson 0](../../lessons/00-setup/README.md). There's no earlier solution to compare it with: lesson 0 starts from an `agent/` package that holds only a docstring. So this page goes through what's here, why each piece is written the way it is, and what it's meant to show you. Each later solution folder has a README comparing it with the one before, starting with [`solutions/01-the-loop/`](../01-the-loop/README.md).

To run this solution without touching your own `agent/` folder, run commands from inside this folder (`cd solutions/00-setup`). `python -m agent` imports the `agent` package from the folder you're in. To run the lesson's tests against it: `uv run pytest lessons/00-setup --impl solutions/00-setup`, from the repository root.

## At a glance

| File | Lines | What's in it |
|---|---|---|
| `agent/__init__.py` | 1 | the package's docstring |
| `agent/config.py` | 67 | `Config` and `load_config`: where the server is, which model, the window size, sampling settings |
| `agent/client.py` | 61 | `make_client`, and `smoke_test`, a one-request check that tool calling works |
| `agent/__main__.py` | 37 | the command line, with one command: `python -m agent smoke` |

About 165 lines. Every later lesson builds on these files without rewriting them: `config.py` and `client.py` stay the same for the rest of the course.

## What this lesson is meant to show you

1. **A coding agent is a harness around a model.** The model only turns text into text. It can't read your disk or run anything. Everything else (the loop, the tools, the permissions) is code you write, starting next lesson.
2. **Everything depends on one fact: the model can make a well-formed tool call.** If the server doesn't answer, or the model can't produce a tool call with valid JSON arguments, nothing in the later lessons can work. `smoke` checks exactly that, before any harness exists.
3. **Settings belong in one place, with clear precedence.** The defaults are in the code, an `agent.json` file overrides them, and environment variables override both. Switching to another model or server is a setting, not a code change.
4. **Fail with a message, not a traceback.** A missing server or a wrong model name is the most common first problem, and `smoke` says so in one line.

## File by file

### `agent/config.py`: the settings

```python
@dataclass(frozen=True)
class Config:
    base_url: str = "http://localhost:1234/v1"
    model: str = "qwen/qwen3.8-27b"
    api_key: str = "lm-studio"
    context_window: int = 32768
    log_dir: Path = Path(".agent/logs")
    temperature: float | None = None
    top_p: float | None = None
    seed: int | None = None
```

**Why it's written this way:**

- **The defaults match the course's setup**: LM Studio on port 1234, the 27B model, a 32K window. With that setup, there's nothing to configure.
- **`frozen=True`**: once loaded, the settings can't be changed by accident halfway through a run.
- **Every field is used later.** `context_window` drives lesson 8's compaction. `log_dir` is where lesson 1's request logs go. They're defined now so the configuration doesn't change shape as the course goes on.
- **`api_key="lm-studio"`**: local servers ignore the key, but the `openai` library insists on having one.
- **Sampling settings default to `None`, meaning "send nothing".** `sampling()` returns only those that are set, as keyword arguments for the request. With none set, the server's own defaults apply.

**`load_config(env=None, file=None)`** builds a `Config` in three layers, each overriding the one before:

1. the defaults above;
2. `agent.json` in the current folder, if there is one. Unknown keys are ignored, and a file that isn't a JSON object is an error;
3. environment variables: `AGENT_BASE_URL`, `AGENT_MODEL`, `AGENT_API_KEY`, `AGENT_CONTEXT_WINDOW`, `AGENT_LOG_DIR`, `AGENT_TEMPERATURE`, `AGENT_TOP_P`, `AGENT_SEED`.

Values from the file and the environment are converted to the right type by `_coerce` (`"16384"` becomes `16384`). **`env` and `file` can be passed in**, so the tests can check every layer without touching your real environment or files.

### `agent/client.py`: talking to the server

**`make_client(config)`** is one line: `openai.OpenAI(base_url=config.base_url, api_key=config.api_key)`. LM Studio, Ollama and many other servers speak the same OpenAI-compatible API, so the course uses the official `openai` library and no framework. Pointing `base_url` somewhere else is all it takes to change server.

**`smoke_test(client, model)`** makes one request, with one tool and a user message that needs it:

```python
response = client.chat.completions.create(
    model=model,
    messages=[{"role": "user", "content": "Please read the file notes.txt."}],
    tools=[READ_FILE_TOOL],
)
```

Then it checks the reply, step by step, and stops at the first problem:

| Check | Failure message |
|---|---|
| The reply has a tool call | `no tool call in the reply (content: '...')` |
| Its `arguments` string is valid JSON | `arguments are not valid JSON: ...` |
| ... and a JSON object | `arguments are not a JSON object` |
| The tool is `read_file` | `expected read_file, got ...` |
| The arguments include `path` | `arguments have no 'path' key` |

and returns a `SmokeResult`: `ok`, the tool name, the parsed arguments, the prompt-token count, and a one-line `detail`.

**Why:**

- **These are exactly the things lesson 1's loop will rely on.** A tool call arrives as a name plus an arguments *string*. The harness must parse that string, and it has to turn out to be an object with the right keys.
- **Each failure says which step failed.** "The model answered in text instead" and "the model sent broken JSON" are different problems, with different fixes (another model, another server setting).
- **The prompt-token count is reported** because it's the first sign of what a tool schema costs: a schema is written into the prompt on every request.
- **`READ_FILE_TOOL` is written out by hand**, as a plain dict in the API's format. Lesson 1 replaces it with a `Tool` and a registry that builds this dict for you.
- **Nothing reads the file.** The smoke test only checks that the model *asks*. Running the tool and sending back the result is the loop, which is lesson 1.

### `agent/__main__.py`: the command line

`python -m agent smoke` loads the config, builds the client, runs `smoke_test`, and prints the result:

```
OK: read_file('notes.txt')
  tool: read_file  arguments: {'path': 'notes.txt'}  prompt tokens: 322
```

(The token count depends on the model and server.) The exit status is 0 for `OK` and 1 otherwise.

- **Any exception from the request is caught** and printed as `FAIL: could not reach http://localhost:1234/v1: Connection error.`. A stopped server or a wrong model name gives one readable line instead of a traceback.
- **`argparse` subcommands**, with `required=True`. Later lessons add `ask`, `log`, `chat`, `run` and `eval` the same way, each with its own function.
- **`main(argv)` takes its arguments as a parameter**, so the tests can call it directly.

## What's missing, and which lesson adds it

Nearly everything, on purpose. This lesson only proves the model can ask for a tool.

| Missing | Added in |
|---|---|
| Running the tool, sending back the result, and asking again: the loop | lesson 1 |
| A real `read_file`, a request log, and the `ask` and `log` commands | lesson 1 |
| More tools, output limits, error handling, editing, permissions, a sandbox, a system prompt, ... | lessons 2 to 11 |

## Seeing it work

From inside this folder:

```
uv run python -m agent smoke
AGENT_BASE_URL=http://localhost:11434/v1 AGENT_MODEL=qwen3:4b-instruct uv run python -m agent smoke
```

The first command checks LM Studio's 27B. The second checks Ollama's 4B, with no code change: only settings. [TESTING.md](../../lessons/00-setup/TESTING.md) explains how the lesson's tests work, including how `--impl` picks which `agent` package is tested, and walks through what `smoke` does step by step.
