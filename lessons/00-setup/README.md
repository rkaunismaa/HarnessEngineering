# Lesson 0: Setup

Start from an empty `agent/` package (it only has a docstring). Later lessons start from "your lesson N-1 code, or copy `solutions/<previous>/agent` into `agent/`."

## Why this exists

A coding agent is a **harness** wrapped around a language model. The model only turns text into text; everything else is the harness:

```
            +-----------------------------------------+
            |                 HARNESS                 |
 you ---->  |  context   -->   MODEL   -->  reply     |
            |  (messages)                    |        |
            |     ^                          v        |
            |     |        tool call?  --> TOOLS      |
            |     +-- results <--  LOOP --  (files,   |
            |                       |        shell)   |
            |                  PERMISSIONS            |
            +-----------------------------------------+
```

- **Model**: predicts the next message. It cannot touch your disk.
- **Loop**: calls the model, runs the tools it asks for, feeds results back, repeats until it answers in plain text.
- **Tools**: functions you expose (read a file, run a command). The model asks for them by name with JSON arguments.
- **Context**: the messages sent on every request. Its size is limited (here 32K tokens).
- **Permissions**: what the harness lets a tool call actually do.

This lesson builds none of the loop yet. It gets your machine ready and proves the one thing everything else depends on: the model server answers, and the model emits a well-formed tool call.

## How Claude Code does it

- **Documented**: Claude Code is "an agentic coding tool that reads your codebase, edits files, runs commands" - the same model, loop, tools shape as above. https://code.claude.com/docs/en/overview (checked 2026-10-30).
- **Observed**: Claude Code shows the model the environment it runs in: the working directory, the platform and today's date appear in the model's context. You will add the same to your agent in lesson 6.

## What you'll build

Package `agent/` with three modules.

**`agent/config.py`**
- `Config`: frozen dataclass with `base_url="http://localhost:1234/v1"`, `model="qwen/qwen3.8-27b"`, `api_key="lm-studio"`, `context_window=32768`, `log_dir=Path(".agent/logs")`.
- Three sampling fields, all defaulting to `None`: `temperature: float | None`, `top_p: float | None`, `seed: int | None`. `None` means "send nothing and let the server decide". `Config.sampling() -> dict` returns only the fields that are set, ready to pass as request keyword arguments (`{}` when none are).
- `load_config(env=None, file=None) -> Config`. Layers, later wins: defaults, then `file` (a JSON object using the field names; ignored if it does not exist; `None` means `Path("agent.json")`), then environment variables `AGENT_BASE_URL`, `AGENT_MODEL`, `AGENT_API_KEY`, `AGENT_CONTEXT_WINDOW` (an `int`), `AGENT_LOG_DIR` (a `Path`), `AGENT_TEMPERATURE` and `AGENT_TOP_P` (`float`s), `AGENT_SEED` (an `int`). `env=None` means `os.environ`.

Why sampling is in the config: when you send no `temperature`, the server uses its own default, and LM Studio and Ollama do not have to agree on what that is. Leaving it unset is fine while you build. It matters in lesson 11, where comparing two models with different server defaults would compare the defaults too.

**`agent/client.py`**
- `make_client(config) -> openai.OpenAI`, built with `base_url` and `api_key` from the config.
- `SmokeResult`: dataclass with `ok: bool`, `tool_name: str | None`, `arguments: dict | None`, `prompt_tokens: int | None`, `detail: str`.
- `smoke_test(client, model) -> SmokeResult`: one request, one user message asking to read `notes.txt`, one tool named `read_file` with a required string parameter `path`. `ok` is true only when the reply contains a `read_file` call whose `arguments` string parses (`json.loads`) to a dict with a `path` key. When there is no tool call, `detail` says there was no tool call. Never raise on a malformed reply; report it in `detail`.

**`agent/__main__.py`**
- `main(argv: list[str] | None = None) -> int` using `argparse` subcommands (later lessons add `ask`, `log`, `chat`, `run`, `eval`), and `if __name__ == "__main__": raise SystemExit(main())`.
- `python -m agent smoke` loads the config, runs the smoke test, prints the result, and exits 0 on `ok`, 1 otherwise (including when the server is unreachable).

Only the `openai` package talks to the model. No agent framework.

## Tests

```
uv sync
uv run pytest lessons/00-setup                                # against your agent/
uv run pytest lessons/00-setup --impl solutions/00-setup      # against the reference solution
```

`--impl PATH` is the directory whose `agent` package the tests import; the default is the repo root, i.e. your code. The tests use `testing/fake_model.py` (`FakeClient`, `reply`, `call`), so no server is needed. The `live` test needs one: add `--live`. [TESTING.md](TESTING.md) walks through how the tests and the fake client work.

## Try it live

1. In LM Studio, start the server (Developer tab, or `lms server start`) and load the model with a 32K context:
   `lms load qwen/qwen3.8-27b --context-length 32768`
2. LM Studio's developer log (Developer tab, "Logs"; or `lms log stream`) shows each request and response. Keep it visible; you will use it constantly.
3. From the repository root, run `uv run python -m agent smoke`, then `uv run pytest lessons/00-setup --live`.

What was seen on 2026-10-30 with `qwen/qwen3.8-27b`:

- `message.content` was `""` (empty string, not `None`) for the tool-only reply; treat both as "no text".
- `tool_calls[0].function.arguments` was the **string** `'{"path":"notes.txt"}'`, not a dict. You must `json.loads` it, and it can be invalid.
- The message carried an extra field, `reasoning_content` ("The user wants me to read notes.txt. ..."). It is not part of the standard OpenAI types; read it with `getattr`/`model_extra`.
- `finish_reason` was `"tool_calls"`; `usage.prompt_tokens` was about 320-330 for this single tool and one short message (322 and 329 in two runs). Tool definitions are not free: they count against your 32K window on every request.

## Break it

The weak model is Ollama's 4B: `AGENT_BASE_URL=http://localhost:11434/v1 AGENT_MODEL=qwen3:4b-instruct uv run python -m agent smoke`.

On this trivial task it passed (162 prompt tokens: a different tokenizer and template count differently). Expect it to fail on harder tasks later; this is the baseline. Now break things on purpose and read the messages:

- Point `AGENT_BASE_URL` at a closed port (`http://localhost:1/v1`): the smoke test must exit 1 with a readable "could not reach" line, not a traceback.
- Set `AGENT_MODEL=does-not-exist`: LM Studio (observed) quietly answers with the loaded model anyway, so this still passes there. Try it against Ollama too and compare: a missing model is an error there, and your command should still exit 1 without a traceback. Its message shouldn't say "could not reach": the server was reached, and the model name is what's wrong. The reference solution tells these cases apart with `openai.APIConnectionError` and `openai.APIStatusError`.

## Switching to a different model

No code changes: switching is two or three settings, then a check that the new model can call tools.

1. **Load it in LM Studio**, with the context length you want. It has to fit in GPU memory together with that context: the 27B at Q4 with a 32K window uses about 20 GB of a 24 GB card. If the model is split across a second, slower GPU, it runs on both, and the slow card sets the pace. A 27B split across an RTX 4090 and an RTX 2070 was measured at about 1.6-1.8× slower than on the 4090 alone (2026-11-25).
2. **Tell the harness**, with environment variables:

   ```
   AGENT_MODEL=<identifier from `lms ps`>
   AGENT_CONTEXT_WINDOW=<the context length it was loaded with>
   ```

   or the same in `agent.json`: `{"model": "<identifier>", "context_window": 32768}`.

   - **Copy the name exactly** from the IDENTIFIER column of `lms ps`. LM Studio answers a wrong name with whatever model is loaded (see "Break it"), so a typo still works, and your logs record the wrong model.
   - **`context_window` must match the loaded window.** Nothing reads it until lesson 8, which compacts the history at 80% of it. Set it higher than the real window and the server rejects requests before the harness compacts; set it lower and the harness compacts sooner than it needs to.
   - **`agent.json` is read from the folder you run the command in.** One in the repository root does nothing when you run a solution from inside `solutions/NN`. Environment variables apply wherever you run.
   - **Another server needs `AGENT_BASE_URL` too**, as in the Ollama example above.
3. **Run `uv run python -m agent smoke`.** Everything in the course depends on it passing. The model must be trained for tool use (`lms ps --json` shows `trainedForToolUse`), and its chat template must support tools. If the reply has no tool call, choose another model. No harness setting fixes that.
4. **Expect different behaviour.**
   - The lesson tests use `FakeClient`, so they don't depend on the model. Only the `--live` tests do, and a weaker model may fail them.
   - The numbers in the lesson READMEs (prompt tokens, timings, which tool the model called first) come from `qwen/qwen3.8-27b`. Yours will differ.
   - Reasoning ("thinking") models generate their reasoning before every answer, so each request takes longer.
   - If the model's page gives sampling settings, set them with `AGENT_TEMPERATURE` and `AGENT_TOP_P`. Otherwise the server's defaults apply.
5. **To compare models, measure.** One run of each tells you little. Lesson 11's `eval` runs the same task many times: change only the model, and compare the success rate, turns, tokens and seconds.

## Extras

- Support `AGENT_*` values in a `.env` file.
- Print the LM Studio-reported model list (`client.models.list()`) when the smoke test fails.
- Add `--json` to `smoke` for machine-readable output.
