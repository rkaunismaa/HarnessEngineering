# How the lesson 0 tests work

Lesson 0's tests have three parts: a switch that picks which `agent/` package is tested, tests of plain functions that take their inputs as arguments, and a fake OpenAI client that returns scripted replies. Against the reference solution, the result is 10 passed and 1 skipped. The skipped one is the live test, which only runs with `--live`.

## 1. Which `agent` gets tested

The test file only says `from agent.config import ...` and `from agent.client import ...`. It never names a folder. The root `conftest.py` decides which folder that import finds:

```python
parser.addoption("--impl", default=str(ROOT), ...)   # default: repo root

def pytest_configure(config):
    impl = str(Path(config.getoption("--impl")).resolve())
    for name in [m for m in sys.modules if m == "agent" or m.startswith("agent.")]:
        del sys.modules[name]       # forget any agent already imported
    sys.path.insert(0, impl)        # put the chosen folder first on the import path
```

So the same tests run against either package:

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
