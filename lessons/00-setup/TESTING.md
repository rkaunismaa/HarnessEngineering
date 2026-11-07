# How the lesson 0 tests work

Lesson 0's tests have three parts: a switch that picks which `agent/` package is tested, tests of plain functions that take their inputs as arguments, and a fake OpenAI client that returns scripted replies. Against the reference solution, the result is 10 passed and 1 skipped. The skipped one is the live test, which only runs with `--live`.

## First: how pytest runs a file that never calls its own functions

`test_setup.py` is just a series of `def`s, and nothing in it calls them. Pytest finds them by their names and calls them itself.

**Collection: finding the functions by name.** When you run `uv run pytest lessons/00-setup`, pytest goes through these steps:

1. **It walks the folder** you gave it. With no folder given, it walks the `testpaths` listed in `pyproject.toml`: `lessons`, `testing` and `capstone/eval`.
2. **It picks out files whose names match** `test_*.py` (or `*_test.py`).
3. **It imports each matching file**, the same way `import` would. That runs the top-level code (the imports and the `def` statements), which creates the functions but doesn't call them.
4. **It looks in the module for functions whose names start with `test`** and adds each one to its list. A function named anything else is never run. That's why the helpers in later lessons, like `make_agent` and `tools_for`, don't start with `test`.

`--collect-only` shows the list pytest builds without running anything:

```
$ uv run pytest lessons/00-setup --collect-only -q
lessons/00-setup/tests/test_setup.py::test_defaults
lessons/00-setup/tests/test_setup.py::test_env_overrides_file
...
lessons/00-setup/tests/test_setup.py::test_live_smoke
11 tests collected
```

**Running: one call per function.** Pytest then calls each collected function in turn, roughly like this:

```python
for test in collected:
    try:
        test(**arguments_it_works_out)   # see "fixtures" below
        report PASSED
    except AssertionError:
        report FAILED                    # an assert was false
    except Exception:
        report FAILED                    # the code raised something else
```

A test **passes if it returns without raising**. There's no return value to check. Each `assert` line either does nothing (true) or raises `AssertionError` (false). That's the whole mechanism.

Pytest also rewrites `assert` statements as it imports the file. So when one fails, it can print the values involved (`assert 'a' == 'b'`), not just "AssertionError".

**Where `tmp_path` comes from: fixtures.** `test_env_overrides_file(tmp_path)` takes an argument, and nobody passes it one. Before calling a test, pytest **reads the names of its parameters** and supplies a value for each one it recognizes. These values are called *fixtures*. `tmp_path` is a built-in fixture: pytest creates a new empty folder for this one test and passes its `Path`.

Later lessons use other built-in fixtures the same way:

- `monkeypatch` changes a function or environment variable for one test and undoes it afterwards.
- `capsys` captures what the test prints.

You can also define your own fixtures with `@pytest.fixture`, as lesson 11 does with `project`.

**Decorators and `conftest.py` change what runs.**

- `@pytest.mark.live` on `test_live_smoke` attaches a label, which by itself does nothing. The root `conftest.py` is a file pytest loads automatically before collecting. Its `pytest_collection_modifyitems` function looks for that label and marks the test as skipped unless you passed `--live`.
- `@pytest.mark.parametrize(...)`, used from lesson 3 on, makes pytest call one function several times with different arguments. Each call counts as a separate test.
- `pytest_configure` in the same `conftest.py` handles `--impl`; section 1 below explains it.

**Trying it yourself:**

```
uv run pytest lessons/00-setup -v                      # one line per test, with PASSED/FAILED
uv run pytest lessons/00-setup -k smoke                # only tests whose name contains "smoke"
uv run pytest "lessons/00-setup/tests/test_setup.py::test_defaults"   # just one
```

A good experiment is to rename `test_defaults` to `check_defaults` and run `--collect-only` again: it disappears from the list. Pytest finds tests only by that naming convention.

## 1. Which `agent` gets tested

The test file only says `from agent.config import ...` and `from agent.client import ...`. It never names a folder. Two functions in the root `conftest.py` decide which folder that import finds:

```python
ROOT = Path(__file__).resolve().parent          # the repo root (where conftest.py lives)

def pytest_addoption(parser):
    parser.addoption("--impl", default=str(ROOT), help="...")
    parser.addoption("--live", action="store_true", help="...")

def pytest_configure(config):
    ...
    impl = str(Path(config.getoption("--impl")).resolve())
    for name in [m for m in sys.modules if m == "agent" or m.startswith("agent.")]:
        del sys.modules[name]       # forget any agent already imported
    sys.path.insert(0, impl)        # put the chosen folder first on the import path
```

### Hooks: functions pytest calls by name

Pytest loads `conftest.py` automatically and looks for functions with specific names, called *hooks*. It's the same idea as finding tests by their `test_` prefix. Nothing calls these hooks in the code; pytest calls each one at a fixed point in a run:

| When | Hook | What it does here |
|---|---|---|
| Reading the command line | `pytest_addoption` | Registers `--impl` and `--live`, so pytest accepts them instead of failing with "unrecognized arguments" |
| After the options are parsed, before any test file is imported | `pytest_configure` | Sets up which `agent` package will be imported |
| After collection, before running | `pytest_collection_modifyitems` | Skips the `live` and `sandbox` tests (section 4) |

The timing is the important part. `pytest_configure` runs **before** pytest imports `test_setup.py`, so by the time that file runs `from agent.client import ...`, the import path is already set.

### How Python decides which `agent` to import

When Python runs `import agent`, it does two things in order:

1. **It looks in `sys.modules`**, a dict of modules already imported in this process. If `agent` is there, Python reuses it and never looks at the disk.
2. **Otherwise it searches the folders in `sys.path`, in order**, and uses the first one that contains an `agent/` package.

`pytest_configure` handles both:

- **`del sys.modules[...]`** removes `agent` and every `agent.something` from the cache, in case anything imported one earlier. Without this, a cached copy would win regardless of `sys.path`.
- **`sys.path.insert(0, impl)`** puts your chosen folder *first* in the search. The repo root is also on `sys.path`, because `pyproject.toml` has `pythonpath = ["."]`, but your folder now comes before it. So with `--impl solutions/03-...`, Python finds `solutions/03-.../agent/` before reaching the repo root's `agent/`.

With no `--impl`, the default is `ROOT`, so the repo root goes first and your own `agent/` is the one tested.

A throwaway test that printed where `agent` came from, run with `--impl solutions/03-when-the-model-gets-it-wrong`, showed:

```
agent -> .../solutions/03-when-the-model-gets-it-wrong/agent/__init__.py
sys.path[:3] -> ['.../solutions/03-when-the-model-gets-it-wrong',
                 '.../HarnessEngineering',          # repo root, from pythonpath = ["."]
                 '.../.venv/bin']
```

The test files only ever say `agent`, and the folder that comes first on `sys.path` decides which one that means.

### Two smaller details

- **`.resolve()`** turns a relative path like `solutions/03-...` into an absolute one. The tests can then change the current folder without breaking the import path.
- **`--import-mode=importlib`** in `pyproject.toml` stops pytest from adding each test file's own folder to `sys.path`. In pytest's default mode, every test folder is added there too. That doesn't affect which `agent` is found, but it keeps the import path limited to what conftest set up.

### What `--impl` can't do

- **It picks one package per pytest run.** Once `agent` is imported, every test in that run uses it. To compare your code with the solution, run pytest twice.
- **It points at the folder that *contains* `agent/`, not at `agent/` itself.** `--impl solutions/03-when-the-model-gets-it-wrong` is right. `--impl solutions/03-when-the-model-gets-it-wrong/agent` would put the package's own folder on the path, and `import agent` would fail.

### In practice

The same tests run against either package:

```
uv run pytest lessons/00-setup                              # your agent/ in the repo root
uv run pytest lessons/00-setup --impl solutions/00-setup    # the reference solution
```

When something fails, run both commands. If the solution passes and yours fails, the bug is in your code.

## 2. Config tests: inputs passed as arguments

`load_config(env=None, file=None)` reads `os.environ` and `agent.json` only when you pass nothing. The tests always pass both:

```python
def test_defaults():
    assert load_config(env={}, file=Path("/nonexistent")) == Config()
```

`env={}` means "no environment variables at all", and the made-up path means "no config file". The result has to equal a plain `Config()`, which has all the defaults. Your real shell variables and any `agent.json` on disk can't change the result.

`test_env_overrides_file` writes a temporary `agent.json` to `tmp_path` (a fresh folder pytest creates for each test), then passes an env dict that sets the same key. It checks three things:

- the env value wins (`model == "b"`);
- a value only the file sets still comes through (`base_url`);
- `"8192"` from the env becomes the integer `8192`, not a string.

The sampling tests follow the same pattern. With nothing set, `sampling()` returns `{}`, so nothing extra is sent to the server. With values set, you get only the keys that are set, with the right types.

## 3. Smoke tests: the fake client

`smoke_test(client, model)` takes a client as an argument instead of creating one. That's why it can be tested without a server: the tests pass a `FakeClient` from `testing/fake_model.py` instead.

The fake does one thing. You give it a list of replies (the "script"), and each call to `client.chat.completions.create(...)` does two things:

1. It saves a copy of the request arguments in `client.requests`, so the test can check what your code sent.
2. It removes the next reply from the script and returns it. If the script is empty, it fails with "ran out of scripted responses".

The helpers `reply(...)` and `call(...)` build real `openai` types (`ChatCompletion`, `ChatCompletionMessageToolCall`, and so on). Your code reads `response.choices[0].message.tool_calls[0].function.arguments` exactly as it would from LM Studio. Here's the main test, step by step:

```python
def test_smoke_ok():
    client = FakeClient([reply(tool_calls=[call("read_file", {"path": "notes.txt"})],
                               prompt_tokens=329)])
    # "When asked, the model replies with one tool call: read_file(path='notes.txt')"
    result = smoke_test(client, "m")

    # Did your code read the reply correctly?
    assert result.ok and result.tool_name == "read_file"
    assert result.arguments == {"path": "notes.txt"}     # parsed from the JSON *string*
    assert result.prompt_tokens == 329                   # read from response.usage

    # Did your code send the right request?
    assert len(client.requests) == 1
    tools = client.requests[0]["tools"]
    assert len(tools) == 1 and tools[0]["function"]["name"] == "read_file"
    assert client.requests[0]["model"] == "m"
```

Each failure test scripts one way the model can go wrong and checks that you return `ok=False` instead of crashing:

| Test | Scripted reply | What your code must do |
|---|---|---|
| `test_smoke_no_tool_call` | `reply(content="I can't")` | Treat "no tool call" as a failure, with that phrase in `detail` |
| `test_smoke_bad_json` | `call("read_file", "{not json")` | Catch the `json.loads` error |
| `test_smoke_missing_path` | `{"file": "x"}` | Notice that the `path` key is missing |

`call()` turns a dict into a JSON string, but a string is passed through unchanged. That's how `test_smoke_bad_json` gets broken JSON past it. Real models do send broken JSON sometimes, especially small ones.

`test_make_client_uses_config` is the one test that builds a real `openai.OpenAI`. It never sends a request; it only checks that `base_url` and `api_key` come from the config.

## 4. The live test

```python
@pytest.mark.live
def test_live_smoke():
    cfg = load_config()                       # real env and agent.json
    result = smoke_test(make_client(cfg), cfg.model)
    assert result.ok, result.detail
```

In `conftest.py`, `pytest_collection_modifyitems` skips every test marked `live` unless you pass `--live`. With `--live`, this test does what `python -m agent smoke` does, against LM Studio. The `, result.detail` part means a failure shows the reason, such as "no tool call in the reply…".

## The pattern to notice

Each function you write gets the things the outside world normally provides (environment variables, the config file, the client) as arguments, and only falls back to the real ones when none are given. The tests use that to swap in fakes, so they run in a fraction of a second with no server.

Every later lesson's tests work the same way. A test scripts the model's replies with `FakeClient`, runs your loop, and then checks two things: what came back, and what your code sent, through `client.requests`. For example, lesson 7 uses `to_chunks(...)` from the same file to turn a scripted reply into a stream of chunks.

## What happens when you run `uv run python -m agent smoke`

The tests above swap in a fake client. This section follows the real command, against LM Studio, from the moment you press Enter.

**1. `uv run` starts Python.** It uses the project's `.venv`, which has `openai` and `rich` installed, and runs it from the repo root.

**2. `python -m agent` runs your package as a program.** Python finds `agent/` in the current folder and runs `agent/__main__.py`. Since that file is run as the main program, the line `if __name__ == "__main__": raise SystemExit(main())` executes. Whatever `main()` returns becomes the process exit code.

**3. `argparse` reads `smoke`.** `build_parser()` registers one subcommand, `smoke`, with `set_defaults(func=_smoke)`. Parsing `["smoke"]` gives an `args` object whose `args.func` is `_smoke`, and `main` calls it. Later lessons add `ask`, `chat` and the others by registering more subcommands the same way.

**4. `load_config()` builds the settings.** It uses the defaults in `Config`, then values from `agent.json` (if you have one), then any `AGENT_*` environment variables. With nothing set, you get `base_url=http://localhost:1234/v1`, `model=qwen/qwen3.8-27b` and `api_key=lm-studio`.

**5. `make_client(config)` creates an `openai.OpenAI` client** pointed at LM Studio instead of OpenAI. Creating the client sends nothing over the network. LM Studio ignores the API key, but the SDK requires one.

**6. `smoke_test` sends one request.** It's a `POST http://localhost:1234/v1/chat/completions` with this body:

```json
{"model": "qwen/qwen3.8-27b",
 "messages": [{"role": "user", "content": "Please read the file notes.txt."}],
 "tools": [{"type": "function", "function": {"name": "read_file", ...}}]}
```

You can watch this exact request, and the model's reply, in LM Studio's developer log. On the server side:

- LM Studio renders the messages and the tool schema into Qwen's chat template (about 322 prompt tokens in one run).
- The model generates a reply. Since it was offered a tool, it usually asks to use it.
- LM Studio turns that into a `tool_calls` entry whose `arguments` is the JSON *string* `'{"path": "notes.txt"}'`.

**7. Your code checks the reply.** It looks for a tool call and parses the arguments with `json.loads`. Then it checks that the result is a dict, that the tool name is `read_file`, and that there's a `path` key. Any check that fails returns `SmokeResult(ok=False, detail=<why>)`.

**8. `_smoke` prints the result and returns the exit code:**

```
OK: read_file('notes.txt')
  tool: read_file  arguments: {'path': 'notes.txt'}  prompt tokens: 322
```

It returns 0 on success and 1 on failure. If the request itself raises (server not running, wrong model name), the `except` prints a `FAIL: could not reach ...` line instead of a traceback. If you see that line, check that LM Studio's server is running: `lms server start`, or the Developer tab in the app.

**Nothing reads `notes.txt`.** The file doesn't need to exist. The smoke test only checks whether the model *asks* to call a tool, in the right format. Nobody runs that call, and no tool result is sent back.

Running the call, sending the result back and asking again until the model gives an answer is the agent loop. You build it in lesson 1.
