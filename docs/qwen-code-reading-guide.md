# Reading Qwen Code alongside the course

A lesson-by-lesson map from this course to the parts of [Qwen Code](https://github.com/QwenLM/qwen-code) that do the same job, and what to compare.

Qwen Code is the Qwen team's open-source coding agent for the terminal. The lessons' "How Claude Code does it" sections can only describe Claude Code from the outside, because its source isn't public. Qwen Code's is, so here you can read how a production harness solves each lesson's problem.

- **Version:** everything here was read in the source at commit `0011d3aa5c` (2026-11-28): `git clone https://github.com/QwenLM/qwen-code && git -C qwen-code checkout 0011d3aa5c`. The project changes daily. On a newer checkout, line numbers will drift and some files may have moved; search for the function name.
- **Where to look:** almost everything is in `packages/core/src/`. Paths below are relative to it unless they start with `packages/`. `packages/cli` is the terminal UI; most of the other packages are product features (desktop, IDE, channels, SDKs) to skip.
- **How to read:** finish the lesson first, then read the matching rows. Don't read whole files: `coreToolScheduler.ts` is 9,198 lines, `shell.ts` 7,237. Go to the function named, read it, and answer the question.
- **History:** it began as a fork of Google's Gemini CLI, which is why types like `GenerateContentResponse` and `FunctionCall` are Gemini's, even on the OpenAI path. Comments often cite Claude Code's behaviour too ("Matches claude-code's ...").

## Before you start: running it on your setup

Not needed for reading, but if you try it against LM Studio with the course's model, one thing found while reading matters:

**It will assume your model has a 1,000,000-token window.** `core/tokenLimits.ts`: `normalize()` (line 147) strips the `qwen/` prefix from `qwen/qwen3.8-27b`, leaving `qwen3.8-27b`, which matches the pattern `/^qwen3\.\d/` (line 283), set to `LIMITS['1m']`. Its compaction triggers at 85% of the window (`DEFAULT_PCT = 0.85`, `services/chatCompressionService.ts:175`), so with a 32K server it would never compact, and the server would reject requests instead. That's exactly lesson 8's warning about setting `context_window` higher than the loaded window. The fix is to pin the window in its settings: `generationConfig.contextWindowSize: 32768` on the model entry (`docs/users/configuration/model-providers.md`, around line 321 for the format). I haven't run it, so this is from reading the code only.

## Lesson 0: the client and the config

| Read | Compare with |
|---|---|
| `core/tokenLimits.ts`: `normalize()` (147), the pattern table (from ~270), `tokenLimit()` (480) | `Config.context_window`: one number you set yourself |
| `core/openaiContentGenerator/converter.ts`: `reasoning_content` (80-95, 595) | lesson 0's observation that `reasoning_content` is a non-standard extra field |

**Questions:** Why does a product need a table of hundreds of model names, when the course needs one setting? (It supports every provider, and users don't set the window.) What does it cost when the table is wrong? (See above.)

## Lesson 1: the loop

| Read | Compare with |
|---|---|
| `core/agent-loop.ts`: `runAgentLoop()` (314-366) | your `Agent.run` |
| `core/agent-loop.ts`: `runModelRound()` (421), `runToolBatch()` (536) | sending one request; running the calls of one reply |

`runAgentLoop` is the course's loop, nearly line for line: send a round; if there are no calls, stop with `'completed'`; run the batch; send the results; repeat. A `maxRounds` limit ends it like `max_turns`.

**Questions:** What can stop the loop besides "no tool calls" (`modelStop`, `hostStop`, `batch.stop`)? What's a "host", and which of your `events` hooks does it correspond to?

## Lesson 2: tools and output limits

| Read | Compare with |
|---|---|
| `tools/truncation.ts`: `PREVIEW_SIZE_CHARS = 2000` (32), the persisted-output stub (`PERSISTED_OUTPUT_STUB_PREFIX`, 68) | your `truncate()` cap |
| `tools/read-file.ts`: `offset` / `limit` (75-120) | your `read_file` |
| `tools/grep.ts`, `tools/ripGrep.ts`, `tools/glob.ts` | your `search` |
| `tools/shell.ts`: `DEFAULT_FOREGROUND_TIMEOUT_MS = 120000` (2249); `process.kill(-pid, 'SIGTERM')` then `'SIGKILL'` (5058-5063) | your `bash` with its 30 s timeout; lesson 2's TESTING.md on killing the process group |

**Questions:** When output is too long, the course cuts it and says so. Qwen Code saves the whole output to a file and gives the model a 2,000-character preview plus the path. What does that let the model do that yours can't? Note that `shell.ts` kills the *process group* (`-pid`), the fix lesson 2's TESTING.md describes, because killing only the shell leaves its children running.

## Lesson 3: when the model gets it wrong

| Read | Compare with |
|---|---|
| `core/xml-tool-call-fallback.ts`: `containsXmlToolCalls()` (39), `tryRecoverXmlToolCalls()` (1016) | lesson 1's note that a tool call can arrive as text in `content`, which the course doesn't handle |
| `core/incomplete-tool-call-args.ts` (header comment) | lesson 3's "arguments are not valid JSON" error |
| `core/stream-transport-retry.ts` | lesson 3's extras: retrying temporary server errors |
| `core/agent-loop.ts`: the duplicate-call checks (`findRepeatedDuplicateProviderToolCall`, imported at 29) | your loop guard: `LOOP_THRESHOLD`, three identical calls in a row |

**Questions:** Your guard counts identical `(name, arguments)` pairs in a row. What does theirs count as a duplicate, and what does the model get back instead of a result? `xml-tool-call-fallback.ts` recovers tool calls written as `<function=...><parameter=...>` text, the very format lesson 1 found in Qwen's chat template. When would the server fail to turn that text into a real `tool_calls` entry? Read the comment on decoding XML entities: what would go wrong with an `edit` if `&lt;` weren't decoded?

## Lesson 4: editing files

| Read | Compare with |
|---|---|
| `tools/edit.ts`: the checks at 480-525 (0 occurrences, more than one without `replace_all`, identical strings, creating a file that exists) | your `edit_file` in `tools/files.py` |
| `tools/priorReadEnforcement.ts`: `checkPriorRead()` (219), and its header comment | your read tracker: refusing an edit if the file changed since it was read |
| `services/fileReadCache.ts` | where the "what was read, and its fingerprint" state lives |

The rules are the same as yours: `old_string` must match exactly once unless `replace_all` is set. Compare the error text sent to the model at line 509, which tells the model what to check ("whitespace, indentation, and context") and which tool to use to look.

**Questions:** What's different about the message for the user (`display`) and the one for the model (`raw`)? Does your tool need both?

## Lesson 5: permissions and the sandbox

| Read | Compare with |
|---|---|
| `config/approval-mode.ts`: `plan`, `default`, `auto-edit`, `auto`, `yolo` | your policy's `auto_approve`; lesson 11's "headless means everything allowed" |
| `permissions/permission-manager.ts`: `evaluate()` (378), the rule order at 489-519 | your `PermissionPolicy.decide` |
| `permissions/destructive-commands.ts` (header comment) | none: a hard block for `git reset --hard` and friends in `auto` mode |
| `permissions/shell-semantics.ts` | your compound-command check |
| `sandbox/bwrap-execution.ts`, `sandbox/landlock-execution.ts` | your bubblewrap arguments |

Rule order is deny, then ask, then allow, then the mode's default, the same "deny wins" principle as yours. Note also the comment at 490: allow rules match the path as written, so a symlink can't widen what you allowed.

**Questions:** What does `auto` mode do that `yolo` doesn't? (It runs a model-based classifier on each call, with `destructive-commands.ts` as a fixed backstop the classifier can't override.) Your lesson-5 policy has nothing between "ask me" and "allow everything". Which of these modes would be easy to add to it?

## Lesson 6: the system prompt

| Read | Compare with |
|---|---|
| `core/prompts.ts`: `getCoreSystemPrompt()` (765) and the text it assembles (roughly 460-700): `# Core Mandates`, `## Using Your Tools`, `# Operational Guidelines`, the sandbox sections | your `prompt.py` |
| the same file, the example conversations (from 1012) | none: the course's prompt has no examples |

**Questions:** How many words does it spend, and on what? Which rules would you copy into your 75-line `prompt.py`? Every word costs tokens on every request, so try one change at a time and measure it with lesson 11's `eval`.

## Lesson 7: the terminal

`packages/cli` is a React (Ink) terminal UI, a different world from your `cli.py`. Worth a glance to see how much code a polished UI takes, but there's little to compare line by line. Skip unless curious.

## Lesson 8: context

| Read | Compare with |
|---|---|
| `services/tokenEstimation.ts` (header comment): characters ÷ 4 | your `estimate_tokens` |
| `services/chatCompressionService.ts`: `DEFAULT_PCT = 0.85` (175), `computeThresholds()` (276) | your `ContextManager`, threshold 0.8 |
| `core/prompts.ts`: `getCompressionPrompt()` (933-981) | your `SUMMARY_PROMPT` in `context.py` |
| `services/microcompaction/microcompact.ts`, `toolResultsNumToKeep` | your `trim_old_tool_results(keep_recent=6)` |

The two-layer design is the same as yours: drop old tool results cheaply first (microcompaction), summarise when that isn't enough. The estimator is the same too: characters ÷ 4, with a comment saying it matches Claude Code's.

**Questions:** Their compression prompt asks for an `<analysis>` block first (stripped afterwards), then a fixed XML structure that includes *every user message, verbatim*. Yours asks for one paragraph. What's each choice protecting against? Lesson 8 says summaries lose detail: which of their sections answers that? Try their structure in your `SUMMARY_PROMPT` with the 27B and see whether the summaries are better or just longer.

## Lesson 9: plans

| Read | Compare with |
|---|---|
| `tools/todoWrite.ts`: the description (37-92), the status check (182) | your `todo_write` |
| `tools/enterPlanMode.ts`, `tools/exitPlanMode.ts`; `core/prompts.ts`: `getPlanModeSystemReminder()` (1435) | none: a mode where the model may only plan |

Same design as yours: the whole list each time, statuses `pending` / `in_progress` / `completed`, at most one in progress, and "do not use it for simple or single-step work".

**Questions:** Their description adds "Do not mark incomplete or blocked work completed" (92). Lesson 9 found the model claiming success it hadn't checked. Is a rule in a tool description enough, or does it need lesson 9's `--verify`?

## Lesson 10: subagents

| Read | Compare with |
|---|---|
| `subagents/builtin-agents.ts`: `Explore` (71) | your subagent's system prompt and tool list |
| `tools/agent/agent.ts` | your subagent tool |

`Explore` is a read-only search agent, the same job as lesson 10's subagent. Its tool list (114-124) leaves out the editing tools, and its system prompt forbids changes in capitals.

**Questions:** Why say "no editing" in the prompt when the editing tools are missing? (The list includes the shell, and a shell can write files: for shell commands, the prompt is the only guard.) Compare lesson 10, where the subagent's tools are all read-only. Note also the comment at 122: `ask_user_question` is left out because a subagent has nobody to ask and would wait forever. What does the parent get back, a summary or the full transcript?

## Lesson 11: headless and measuring

| Read | Compare with |
|---|---|
| `packages/cli/src/nonInteractiveCli.ts` | your `run` command and `headless.py` |
| `core/nonInteractiveToolExecutor.ts` | running tools with nobody to ask |
| the README's SWE-bench section: the same model across seven versions | your `eval`: change one thing, measure a rate |

**Questions:** What does `qwen -p` do about approvals when nobody is there? Does it require a sandbox, as your `run` does? Their SWE-bench table holds the model fixed and varies the harness version, the same "change one thing" rule as lesson 11, at a larger scale.

## What the course doesn't cover (skip, or read for interest)

MCP (`tools/mcp-*.ts`), hooks (`hooks/`), LSP (`lsp/`), skills and memory (`skills/`, `memory/`), agent teams and arenas (`agents/team`, `agents/arena`), worktrees, cron and loops, the daemon (`qwen serve`), the SDKs, voice and images. These are product features built on the same loop.
