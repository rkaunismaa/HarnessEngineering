# Reading *Build an AI Agent (From Scratch)* alongside the course

A lesson-by-lesson map from this course to the code in [shangrilar/ai-agent-from-scratch](https://github.com/shangrilar/ai-agent-from-scratch), the companion repository of Jungjun Hur and Younghee Song's *Build an AI Agent (From Scratch)* (Manning, 2026), and what to compare.

The book and this course start from the same idea: build the harness yourself instead of using a framework. They build different agents. The book's is a general-purpose research agent (web search, files, GAIA benchmark questions) running on hosted APIs. This course's is a coding agent running on a local model. Where both solve the same problem, their solutions are worth comparing; where they differ, the reason is usually the kind of agent or the kind of model.

- **Version:** everything here was read in the repository at commit `d8141b0` (2026-09-09): `git clone https://github.com/shangrilar/ai-agent-from-scratch && git -C ai-agent-from-scratch checkout d8141b0`. On a newer checkout, line numbers may drift; search for the function name.
- **Where to look:** `scratch_agents/` is the finished package (about 3,300 lines), complete through the book's chapter 10. `notebooks/chNN/` holds each chapter's notebook, and for some chapters a snapshot of the package as it stood then. Paths below are relative to the repository root.
- **How to read:** finish the lesson first, then read the matching rows. The files are short, so reading a whole file is fine.
- **Running it:** it needs Python 3.13 or later and API keys (`.env.example`: OpenAI or Anthropic, Tavily for web search, E2B for the sandbox, and a Hugging Face token for the GAIA data). `LlmClient` passes extra keyword arguments to LiteLLM, so pointing it at LM Studio should be possible (something like `LlmClient(model="openai/qwen/qwen3.8-27b", api_base="http://localhost:1234/v1", api_key="lm-studio")`). This hasn't been tried.

## Lesson 0: the client

| Read | Compare with |
|---|---|
| `scratch_agents/llm.py`: `LlmClient` (76), `generate()` (83-99), `_parse_response()` (147) | your `make_client` and `smoke_test` |
| `scratch_agents/llm.py`: `build_messages()` (37) | lesson 1's message format |

The book talks to providers through LiteLLM's `acompletion`, so one model string (`gpt-5-mini`, `anthropic/...`) picks the provider. The course uses the `openai` library and a `base_url`, because every local server speaks that API.

**Questions:** `generate()` catches every exception and returns it as `LlmResponse(error_message=...)`. What does your `smoke` do instead, and why does lesson 0 tell a server that can't be reached apart from one that answered with an error?

## Lesson 1: the loop

| Read | Compare with |
|---|---|
| `scratch_agents/agent.py`: `run()` (93-184), `step()` (186-231), `act()` (237) | your `Agent.run` |
| `scratch_agents/agent.py`: `_is_final_response()` (410) | "no tool calls means done" |
| `scratch_agents/context.py`: `ExecutionContext` (15); `scratch_agents/types.py`: `Event` | your `messages` list |
| `scratch_agents/agent.py`: `_prepare_llm_request()` (357) | none yet: lesson 8 is where you start changing what is sent |
| `scratch_agents/agent.py`: `_log_response()` (673) | your request log in `.agent/logs` |

The loop is the same as yours: send, run the calls, send the results, stop when a reply has no calls or after `max_steps`. The difference is the history. The book stores **events** in an `ExecutionContext` and builds each request from them in `_prepare_llm_request`, which is where its later chapters change what the model sees without changing what's stored. The course keeps the request's `messages` list itself.

**Questions:** What does the book gain by keeping storage and the request apart (its section 6.2.1, "Separating storage from presentation")? `_log_response` prints to the screen when `verbose=True`. What can you do with your log file that you couldn't with that?

## Lesson 2: tools

| Read | Compare with |
|---|---|
| `scratch_agents/tools/base.py`: `FunctionTool` (67), the `@tool` decorator (146) | your `Tool` and registry |
| `scratch_agents/tools/helpers.py`: `function_to_input_schema()` (6) | writing schemas by hand |
| `scratch_agents/tools/file_tools.py`: `list_files()` (45), `read_file()` (76), `_read_text_file()` (109) | your `list_files` and `read_file` |
| `scratch_agents/tools/code_execution.py`: `bash_tool()` (29) | your `bash` |
| `scratch_agents/tools/search.py`: `search_web()` | none: the course has no web tools |

The book builds a tool's schema from the Python function's signature and docstring. The course writes each schema out. Its `read_file` numbers lines (`   4 | ...`) and takes `start_line` / `end_line`.

**Questions:** None of these tools caps its output, and `bash_tool` sets no timeout of its own (it runs in E2B). What would one 50,000-line file do to the book's agent, and what does your `truncate` do about it? What does generating schemas from signatures save, and what do you lose by not choosing each description's wording?

## Lesson 3: when the model gets it wrong

| Read | Compare with |
|---|---|
| `scratch_agents/agent.py`: `act()`, unknown tool (248-255) and `try`/`except` around the call (289-302) | your `dispatch`: unknown tool, and a tool that raises |
| `scratch_agents/llm.py`: `json.loads(tc.function.arguments)` (163), inside `generate()`'s `try` | your "arguments are not valid JSON" message |
| `scratch_agents/agent.py`: `step()`, `raise RuntimeError(...)` (210) | your `stop_reason="error"` |
| `Agent(max_steps=10)` (`agent.py`, 46) | your `max_turns`, and `stop_reason="max_turns"` |

Two checks match yours: an unknown tool and a tool that raises both become error results the model can read. Arguments with the wrong names reach the function and fail with a `TypeError`, whose text goes back to the model.

The others differ. If the model's arguments aren't valid JSON, `json.loads` raises inside `generate()`. That becomes an `error_message`, `step()` turns it into a `RuntimeError`, and nothing in `run()` catches it, so one malformed call ends the run with an exception. Your lesson 3 sends the model a message instead, so it can try again. A run that reaches `max_steps` returns `output=None`, with no reason given. There's no check for a model repeating the same call.

**Questions:** These choices suit GPT-5-class models, which rarely send broken JSON. Which of lesson 3's checks fired when you ran the 4B? Would the book's agent have survived those runs?

## Lesson 4: editing files

No counterpart. The book's agent reads files and writes new ones (`create_file` appears in its compaction rules, `scratch_agents/memory/context_optimizer.py:105`), but it has no tool that edits part of a file, and no check that a file hasn't changed since it was read. Editing safely is what a coding agent needs most and a research agent hardly needs at all.

## Lesson 5: permissions and the sandbox

| Read | Compare with |
|---|---|
| `scratch_agents/callbacks.py`: `DANGEROUS_TOOLS` (8), `approval_callback()` (11) | your `PermissionPolicy` and approver |
| `scratch_agents/tools/base.py`: `requires_confirmation` (31); `agent.py`: the pause in `act()` (260) and `_process_confirmations()` (618) | your approver, which answers during the call |
| `scratch_agents/agent.py`: `_setup_code_env()` (516), and the `finally` in `run()` that kills the sandbox | your bubblewrap sandbox |
| `scratch_agents/tools/file_tools.py` | your workspace's path checks |

The book has two ways to ask a person. `approval_callback` asks in the terminal for tools named in a fixed list. `requires_confirmation` **pauses the run**: `run()` returns `status="pending_confirmation"`, and you call `run()` again later with the answers, which may include **changed arguments** (`modified_arguments`). That suits an agent behind a web page, where the person may answer minutes later.

Its sandbox is E2B, a hosted service: code runs on someone else's machine, so nothing can touch yours. The file tools themselves aren't limited to a folder: `read_file` opens any path it's given.

**Questions:** Your policy decides from rules on the tool *and* its arguments (`bash(python -m pytest*)`). The book decides by tool name only. Which can say "allow running the tests, but ask before anything else"? What does a hosted sandbox cost (an account, a network round trip, your files have to be uploaded) compared with bubblewrap?

## Lesson 6: the system prompt

| Read | Compare with |
|---|---|
| `scratch_agents/agent.py`: `_prepare_llm_request()` (357-405): `instructions`, then the sandbox tools prompt, then the skills prompt | your `build_system_prompt` |
| `scratch_agents/eval/prompts.py` | the prompt for one job (GAIA) |
| `scratch_agents/skills.py`: `generate_skills_prompt()` (70) | none: skills aren't in the course |

**Questions:** Your system prompt states facts about the environment (the working folder, git state, project instructions). The book's agent is told only its instructions and its tools. Why does a coding agent need facts about where it is, when a research agent doesn't? Skills list only a name and a description in the prompt and load the rest on demand (its section 8.5, "progressive disclosure"). Which part of your prompt could work that way?

## Lesson 7: the terminal

| Read | Compare with |
|---|---|
| `scratch_agents/memory/session.py`: `Session` (14), `InMemorySessionManager` (59); `run(session_id=...)` in `agent.py` | your `chat` REPL keeping its `messages` between turns |

There's no streaming and no terminal interface: the book runs its agent from notebooks. Sessions give continuity: `run()` loads a session's events, runs, and saves them back.

**Questions:** Your `chat` keeps one agent alive. The book saves and restores a session by id. Which survives restarting the program?

## Lesson 8: context

| Read | Compare with |
|---|---|
| `scratch_agents/memory/context_optimizer.py`: `count_tokens()` (37), with tiktoken | your `estimate_tokens` (characters ÷ 4) and `usage.prompt_tokens` |
| the same file: `apply_compaction()` (116), with its rules (104-114) | your `trim_old_tool_results` |
| the same file: `SUMMARIZATION_PROMPT` (164), `apply_summarization()` (179) | your `compact` and `SUMMARY_PROMPT` |
| the same file: `ContextOptimizer` (258): threshold 50,000 tokens, `keep_recent=5` | your `ContextManager`: 80% of the window, `keep_recent=6` |
| the same file: `apply_sliding_window()` (74) | none: the course never drops messages without a summary |

The layers are the same as yours: replace old results with a short note first, summarise only if that isn't enough. The note is more specific than yours: `"File content from {file_path}. Re-read if needed."` names the file to read again. It also shortens the *call* to `create_file`, whose `content` argument holds the whole file, which your trimming leaves alone.

The design differs in three ways:

1. **Only the request changes.** The optimizer edits the `LlmRequest`, and the `ExecutionContext` keeps everything. Your trimming is permanent: the trimmed list replaces `self.messages`.
2. **The summary goes into the system instructions** (`request.append_instructions`), not into a user message as yours does.
3. **The cut isn't moved.** `apply_summarization` keeps the last `keep_recent` items wherever that falls. Your `split_index` moves the cut back until it lands on a `user` or `assistant` message, so a tool result never loses the call it answers.

**Questions:** The request is rebuilt from the full history on every step. Once the history is past the threshold, how often does the summary request run? What happens when the first kept item is a `ToolResult` whose `ToolCall` was summarised? (Lesson 8 found that LM Studio and Ollama accept such a history without an error, so nothing warns you: the model just sees a result for a call it never made. Hosted APIs may be stricter.) Tiktoken counts with OpenAI's tokenizer. How far off would it be for Qwen, compared with reading `usage.prompt_tokens`?

## Lesson 9: plans and checking work

| Read | Compare with |
|---|---|
| `scratch_agents/planning.py`: `Task` (10), `create_tasks()` (26) | your `todo_write` |
| `scratch_agents/planning.py`: `reflection()` (50) | your `--verify` check |

`create_tasks` follows the same protocol as your `todo_write` (send the whole list each time; statuses `pending` / `in_progress` / `completed`; "when not to use"). But it stores nothing and doesn't check the list: it renders what it's given and returns it, so two items `in_progress` pass.

`reflection` is the book's answer to "check before you finish": a tool whose only effect is to make the model write its reasoning down. Nothing outside the model runs.

**Questions:** Lesson 9 found the 4B claiming "should pass all tests" when half failed. Would a `reflection` call have caught that? What does your `--verify` know that the model doesn't? `create_tasks` keeps no state. What can your CLI do with `ws.todos` that the book's agent can't?

## Lesson 10: subagents

| Read | Compare with |
|---|---|
| `scratch_agents/tools/agent_tool.py`: `AgentTool` (17-54) | your subagent tool |
| `scratch_agents/transfer.py`; `agent.py`: `_find_agent()` (588) | none: handing the whole conversation to another agent |

Same idea as yours: the subagent runs `agent.run(request)` with a fresh context and only its `output` comes back. Which tools it gets depends on the `Agent` you wrap, and its answer isn't capped. Your subagent has only read-only tools and a 4,000-character answer limit (`SUBAGENT_MAX_ANSWER`).

**Questions:** What happens to the parent's context if a subagent returns a 30,000-character answer? "Transfer" hands the conversation over instead of asking a question (its section 9.5). When would a coding agent want that?

## Lesson 11: measuring

| Read | Compare with |
|---|---|
| `scratch_agents/eval/gaia.py`: `is_correct()` (32), exact match | `capstone/eval/check.py`: hidden tests |
| `scratch_agents/eval/gaia.py`: `evaluate_gaia_agent_single()` (88), `run_experiment()` (138) | your `eval` |
| `notebooks/ch10/ch10_evaluation.ipynb`: LLM-as-a-judge | none: the course checks results with tests |

Both measure a rate instead of trusting one run. The book runs **many questions once each**, all at once (`asyncio.gather`, with a per-provider limit, `PROVIDER_SEMAPHORES`, line 23). The course runs **one task many times**, one after another on fresh copies, because on one local GPU parallel runs slow each other down and their timings stop being comparable.

**Questions:** What does "many questions once" tell you that "one task ten times" doesn't, and the other way round? `is_correct` compares answers as text. When is that enough, and when do you need tests, or a judge?

## What the course doesn't cover (read for interest)

Retrieval (`scratch_agents/rag.py`, chapter 5), long-term memory (`scratch_agents/memory/long_term.py`, chapter 6), workflows (`scratch_agents/workflows/`, chapter 9), agent transfer (`scratch_agents/transfer.py`), A2A (`scratch_agents/remote.py`, `a2a_server.py`), MCP (`scratch_agents/tools/mcp.py`, chapter 3), skills (`scratch_agents/skills.py`, chapter 8), and observability and LLM-as-a-judge (chapter 10).
