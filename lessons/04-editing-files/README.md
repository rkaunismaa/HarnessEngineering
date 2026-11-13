# Lesson 4: Editing files

Start from your lesson 3 code, or copy `solutions/03-when-the-model-gets-it-wrong/agent` into `agent/`.

## Why this exists

So far the agent can look but not touch. Two tools fix that: `edit_file` changes part of a file, `write_file` creates a file or replaces one.

**Why exact-match edits beat whole-file rewrites.** The obvious design is "send the whole new file". It is worse in three ways:

- **Output tokens.** Changing one line of a 600-line file means the model generates 600 lines. Generation is the slow, expensive part, and on a 32K context the file is then in the history twice (once read, once written).
- **Accidental damage.** A model rewriting a file from memory drops a comment, "tidies" a line it was not asked about, or truncates the end. Nothing in the harness notices.
- **Reviewable diffs.** An edit says exactly what it removed and what it put in. The change is small enough to read in the log, and everything outside it is untouched by construction.

An edit is a pair of strings: `old_string` must be found in the file exactly (whitespace included), and it is replaced by `new_string`. If it is not found, nothing changes. If it is found more than once, the harness refuses and tells the model to add surrounding lines, rather than guess which one was meant.

**Why read-before-edit.** The model's idea of a file comes from an earlier `read_file` result. If it never read the file, its `old_string` is a guess. Requiring a read first turns a likely wrong edit into an error that says what to do. The same goes for overwriting an existing file with `write_file`: an unread file is one the model is about to destroy blind.

**Why the stale-file check.** A read can be old by the time of the edit: the user saved something in their editor, a formatter ran, a `bash` command rewrote the file. An edit based on the old text would either fail to match or, worse, match and silently undo the newer change. So the harness remembers what each file looked like when it was read, and refuses to edit if it is different now.

## How Claude Code does it

All of these are **Observed** (from using the tool; this course did not find them stated on a documentation page, so they are not labeled Documented):

- **Observed**: its edit tool replaces an exact string, and that string must be unique in the file unless a `replace_all` option is set.
- **Observed**: it refuses to edit a file that has not been read in the conversation.
- **Observed**: it refuses to overwrite an existing file that has not been read.
- **Observed**: it notices when a file has changed since it was read, and asks for a fresh read instead of editing.

## What you'll build

Extend your `agent/` package. Tests are in `lessons/04-editing-files/tests/`.

**`agent/tools/files.py` and `agent/workspace.py`**

`FileTracker` (it may live in `workspace.py`; import it into `files.py` too) with `Workspace.tracker` an instance of it:

- `mark_read(path: Path) -> None` stores the file's `st_mtime_ns` and a hash of its content.
- `check(path: Path) -> str | None` returns `None` when the file was read and is unchanged, otherwise an error string.
- Key everything on the path returned by `Workspace.resolve`, so `a.txt` and `./a.txt` are one file.
- "Changed" means the content differs or the file is gone. A file whose modification time moved but whose content is identical is **not** changed. Use the stored mtime only as a shortcut to skip hashing.
- `read_file` calls `mark_read` on a successful read (a partial read with `offset` and `limit` counts). Its output does not change.

`edit_file(path: str, old_string: str, new_string: str, replace_all: bool = False)`, a tool that is not `read_only`. Tool functions return these strings; they do not raise. Checks run in this order, first failure wins, strings exact:

| Situation | Result |
|---|---|
| File does not exist | `f"Error: file not found: {path}"` |
| Never read | `"Error: read the file with read_file before editing it."` |
| Changed on disk since read | `"Error: the file changed on disk since you last read it. Read it again before editing."` |
| `old_string == new_string` | `"Error: old_string and new_string are the same."` |
| `old_string` not in the file | `"Error: old_string was not found in the file."` |
| Found `k > 1` times, `replace_all` false | `f"Error: old_string appears {k} times. Include more surrounding lines to make it unique, or set replace_all to true."` |
| Success | `f"Edited {path} ({k} replacement{'s' if k != 1 else ''})."` |

On success the file is re-marked as read, so a second edit does not need another `read_file`.

`write_file(path: str, content: str)`:

- Path does not exist: create parent directories, write, return `f"Created {path}."`.
- Exists and was not read (or changed since): the same not-read / changed errors as above.
- Exists and was read: overwrite, return `f"Wrote {path}."`.
- Either way the file counts as read afterwards.

Both tools write exactly the bytes they are given, UTF-8 encoded. Do not let Python translate line endings: a file with `\r\n` line endings must keep them on lines you did not touch, and a file with no trailing newline must still have none. The model writes line breaks as `\n`, so in a file that uses `\r\n`, `edit_file` must never insert a bare `\n`: turn every `\n` in `new_string` into `\r\n`. If `old_string` is not found as given, try again with its `\n` turned into `\r\n` too, so a multi-line match works. The tests check both: `two` replaced by `two\nthree` in `one\r\ntwo\r\n` gives `one\r\ntwo\r\nthree\r\n`.

**`agent/tools/__init__.py`**: register `edit_file` and `write_file` in `make_default_tools`.

## Tests

```
uv run pytest lessons/04-editing-files                               # against your agent/
uv run pytest lessons/04-editing-files --impl solutions/04-editing-files
uv run pytest lessons/04-editing-files --live                        # the 27B fixes a typo
```

[TESTING.md](TESTING.md) walks through what each test checks and why.

Lessons 1 to 3 still apply. `test_edit_detects_external_change` rewrites a file after the read and moves its mtime forward with `os.utime`; `test_edit_ignores_touch_without_content_change` moves only the mtime. The live test is `test_live_edit`: the model fixes a typo in a temp file using `edit_file`.

## Try it live

Make a fresh copy of the practice project (its `calc.py` has a function `total` used twice) and ask the 27B to change it:

```
uv run python scripts/make_fixture.py scratch /tmp/scratch4
uv run python -m agent ask "In calc.py rename the function total to add_up everywhere, using edit_file." --root /tmp/scratch4
uv run python -m agent log
```

What the reference solution did: `read_file` first (1138 prompt tokens on that request), then a single `edit_file` call with `old_string: "total"`, `new_string: "add_up"` and `replace_all: true`, answered with `Edited calc.py (3 replacements).` Then it read the file again to check, and tried `bash` to run it. (If `bash` asks for confirmation on your terminal, answer it; it waits for you.)

Now try the guard rails yourself: ask for an edit, then change the file in another terminal between the model's read and its edit, and look in the log for the `changed on disk` result and what the model did next.

### What happens when you run it, step by step

This follows two real runs, made on 2026-11-13 with the reference solution (`solutions/04-editing-files`) and `qwen/qwen3.8-27b` in LM Studio:

1. **The `ask` command above, exactly as written.** The model renamed the function in four requests.
2. **The same request, with the file changed between the model's read and its edit**, the guard-rail experiment from the paragraph above. Timing a change in another terminal by hand is hard, so a small driver script did it: it builds the agent the way `_ask` does, and appends one line to `calc.py` straight after the model's first `read_file` returns.

Every request, reply, tool result and token count below comes from those runs' logs. Your model will word things differently, and may take a different route.

The start of the command is the same as in lesson 1 ([walkthrough](../01-the-loop/README.md#what-happens-when-you-run-ask-step-by-step)), and every call goes through lesson 3's checks ([walkthrough](../03-when-the-model-gets-it-wrong/README.md#what-happens-when-you-run-it-step-by-step)). This section concentrates on what's new: the read tracker, and how `edit_file` finds and replaces text.

#### Where the code lives

Paths are relative to your own package. The reference versions are the same files under `solutions/04-editing-files/agent/`.

| File | What's in it that this walkthrough uses |
|---|---|
| `agent/workspace.py` | `Workspace` (now with a `tracker`), `FileTracker`, `FileTracker.mark_read`, `FileTracker.check`, `_digest` |
| `agent/tools/files.py` | `read_file`, `search`, `edit_file`, `write_file` (defined inside `make_read_file`, `make_search`, `make_edit_file`, `make_write_file`), `_read_exact` |
| `agent/tools/__init__.py` | `make_default_tools` |
| `agent/tools/registry.py` | `ToolRegistry.schemas`, `ToolRegistry.dispatch` |
| `agent/loop.py` | `Agent.run` |
| `agent/__main__.py` | `_ask` |

#### The big picture first

`edit_file` changes a file by **find and replace**. The model doesn't send line numbers or a whole new file. It sends an exact piece of the file's current text (`old_string`) and the text to put in its place (`new_string`). That only works if the model knows what the file says *now*, so the harness keeps a note of every file the model has read, and refuses an edit to a file that has changed since.

```
 read_file(calc.py)  ──>  tracker notes: calc.py, its timestamp, a fingerprint of its bytes
        │
        │   (the file might change here: you, another program, the model's own bash)
        v
 edit_file(calc.py, old, new)  ──>  tracker: "read, and unchanged?"
                                       yes ──> find old in the file, replace it, write it, note the new state
                                       no  ──> "Error: ... Read it again before editing."   (file untouched)
```

#### Run 1, step 1. Two more tools, and a tracker

`_ask` (`agent/__main__.py`) builds a `Workspace` for `/tmp/scratch4`. In this lesson, `Workspace.__init__` (`agent/workspace.py`) also creates a `FileTracker`, kept as `ws.tracker`. Its only data is a dictionary, `_seen`, that maps a file's path to what it looked like when it was last read. It starts empty.

`make_default_tools` (`agent/tools/__init__.py`) now registers six tools, in this order: `read_file`, `list_files`, `search`, `edit_file`, `write_file`, `bash`. Every file tool gets the same `ws`, so `read_file` and `edit_file` share one tracker. The `edit_file` schema the model sees:

```json
{"name": "edit_file",
 "description": "Edit a file by replacing an exact string. The file must have been read with read_file first. old_string must match the file exactly (including whitespace) and appear once, unless replace_all is true. Do not include the line-number prefix from read_file output.",
 "parameters": {"type": "object", "properties": {
   "path": {"type": "string", "description": "File path"},
   "old_string": {"type": "string", "description": "Exact text to replace"},
   "new_string": {"type": "string", "description": "Replacement text"},
   "replace_all": {"type": "boolean", "description": "Replace every occurrence (default false)"}},
   "required": ["path", "old_string", "new_string"]}}
```

The description states every rule `edit_file` enforces. The model learns the rules from this text, before it ever breaks one.

The file it will edit, `calc.py`:

```python
def total(items):
    return sum(items)

print(total([1, 2]))
print(total([3]))
```

#### Run 1, step 2. Request 1: read the file and look for other uses

The first request was **1,138 prompt tokens**. In lesson 2, with four tools, a similar question was 844, so about 300 of the difference is the `edit_file` and `write_file` schemas. After **2.133 s** the model asked for two calls in one reply:

```
read_file({"path":"calc.py"})
search({"pattern":"total"})
```

**`read_file`** (defined inside `make_read_file` in `agent/tools/files.py`) reads the text, then calls `ws.tracker.mark_read(p)` *before* returning the numbered lines. `mark_read` stores two things about the file:

```python
ws.tracker._seen == {
    PosixPath("/tmp/scratch4/calc.py"): (st_mtime_ns, "3976e1d2a3aa...")
    #                                    ^ the file's last-modified time, in nanoseconds
    #                                                  ^ the SHA-256 of its bytes (the first 12 hex digits shown)
}
```

The tool result is the file with line numbers:

```
     1	def total(items):
     2	    return sum(items)
     3	
     4	print(total([1, 2]))
     5	print(total([3]))
```

**`search("total")`** matches the text anywhere in a line, so it found more than the function:

```
app/billing.py:1: def compute_invoice_total(items):
app/main.py:1: from app.billing import compute_invoice_total
app/main.py:2: print(compute_invoice_total([1]))
calc.py:1: def total(items):
calc.py:4: print(total([1, 2]))
calc.py:5: print(total([3]))
```

#### Run 1, step 3. Request 2: the model decides how to edit

This request took **7.586 s** and 418 completion tokens, 346 of them reasoning. That's long for this model. The log shows what it was weighing:

> The task is to rename `total` to `add_up` only within calc.py (not in other files like app/billing.py or app/main.py). ... Using edit_file with old_string="total" and replace_all=true will replace all three. ... Actually, one caveat: what if there were "subtotal" or other words containing "total"? Not in this file. So replace_all is safe.

That's exactly the risk with find and replace. `old_string` is plain text, not a whole word, so `"total"` would also match `subtotal` or `compute_invoice_total`. The model checked the file it had read and found only the three it wanted. Its call:

```json
{"path": "calc.py", "old_string": "total", "new_string": "add_up", "replace_all": true}
```

#### Run 1, step 4. `edit_file` runs its checks, then writes

`edit_file` (defined inside `make_edit_file` in `agent/tools/files.py`) runs these steps in order, and returns at the first problem:

| Step | What it checks | This call |
|---|---|---|
| 1 | Does the file exist? Otherwise `Error: file not found: calc.py` | yes |
| 2 | **`ws.tracker.check(p)`**: was it read, and is it unchanged? | see below: `None`, meaning fine |
| 3 | Are `old_string` and `new_string` different? Otherwise `Error: old_string and new_string are the same.` | yes |
| 4 | Read the exact text with `_read_exact`: bytes decoded as UTF-8, with `\r\n` line endings left alone | 80 bytes, `\n` endings |
| 5 | If the file uses `\r\n`, convert the line breaks in `old_string` and `new_string` to match | not needed |
| 6 | Count `old_string` in the text. 0 gives `Error: old_string was not found in the file.` More than 1 without `replace_all` gives `Error: old_string appears N times. Include more surrounding lines to make it unique, or set replace_all to true.` | 3, and `replace_all` is true |
| 7 | Replace, write the bytes back, and call `ws.tracker.mark_read(p)` again | done |

**Step 2, `FileTracker.check`** (`agent/workspace.py`):

```python
seen = self._seen.get(path)          # (mtime, digest) from step 2's read_file
if seen is None:
    return "Error: read the file with read_file before editing it."
mtime, digest = seen
if path.stat().st_mtime_ns == mtime:
    return None                      # same timestamp: assume unchanged (fast)
if _digest(path) != digest:
    return "Error: the file changed on disk since you last read it. Read it again before editing."
return None                          # timestamp moved, bytes identical: fine
```

Nothing had touched `calc.py`, so the timestamp matched and `check` returned `None` on the fast path. It didn't need to hash the file at all.

**Step 7** re-marks the file. That matters: the edit itself has just changed the file's timestamp and bytes. Without this call, the model's *next* edit to `calc.py` would be refused as "changed on disk", by a change it made itself. After step 7, `_seen` holds the new state, with fingerprint `97cc942283f0...`.

The tool result is `Edited calc.py (3 replacements).`. The count tells the model the edit did what it expected.

#### Run 1, steps 5–6. Checking, then answering

**Request 3** (0.769 s): the reasoning is "Verify the results.", and the model calls `read_file(calc.py)` again:

```
     1	def add_up(items):
     2	    return sum(items)
     3	
     4	print(add_up([1, 2]))
     5	print(add_up([3]))
```

**Request 4** (2.054 s): no tool calls, so the run ends with:

> Done. Renamed all 3 occurrences in `calc.py` — the function definition and both call sites — from `total` to `add_up`. Other files weren't touched since they reference a different function (`compute_invoice_total`).

That's `stop_reason="done"`, 4 turns, and 5,387 prompt and 622 completion tokens in all. `_ask` prints the answer and exits with 0. The model didn't call `bash` this time (an earlier run did, to run the file). If it does, `_ask` asks you first, and the agent waits for your answer.

#### Run 2: the file changes between the read and the edit

Same project, same prompt. The driver appended `print(total([10, 20]))` to `calc.py` straight after the model's first `read_file`. Here's the log, with each tool's result added below its call:

```
request 1   1.118s  prompt=1138   read_file({"path":"calc.py"})
              -> the 5 lines, as in run 1. The tracker notes fingerprint 3976e1d2a3aa...
              (the driver now appends line 6; on disk the fingerprint is 76f4aeb3cfa4...)
request 2   3.533s  prompt=1220   edit_file({"path":"calc.py","old_string":"total","new_string":"add_up","replace_all":true})
              -> Error: the file changed on disk since you last read it. Read it again before editing.
request 3   0.943s  prompt=1322   reasoning: "The file was modified on disk. Re-reading it."
                                  read_file({"path":"calc.py"})
              -> 6 lines, now including "     6	print(total([10, 20]))". The tracker notes 76f4aeb3cfa4...
request 4   1.699s  prompt=1418   reasoning: "The file has been modified — a print line was added. I'll use replace_all to do the edit again."
                                  edit_file({"path":"calc.py","old_string":"total","new_string":"add_up","replace_all":true})
              -> Edited calc.py (4 replacements).
request 5   0.835s  prompt=1508   read_file({"path":"calc.py"})   (to check)
request 6   1.402s  prompt=1608   "Done. All 4 occurrences of `total` in calc.py have been renamed to `add_up` (the function definition and the 3 print calls) ..."
```

In request 2, `FileTracker.check` found a **different timestamp**: appending the line had moved it. So it hashed the file, got `76f4aeb3cfa4...` instead of the `3976e1d2a3aa...` it had noted, and returned the error. `edit_file` stopped at step 2. **The file wasn't touched.** The error is an ordinary tool result, as in lesson 3, so the model read it, re-read the file, saw the new line, and made the edit again. This time it counted 4 replacements instead of 3. The final file:

```python
def add_up(items):
    return sum(items)

print(add_up([1, 2]))
print(add_up([3]))
print(add_up([10, 20]))
```

**What the guard prevented here, honestly:** this particular edit would have come out right even without the check. `edit_file` always reads the file fresh, and `replace_all` on `"total"` would have caught the new line too. But the model would then have reported "3 occurrences" for a file that now had 4, and its idea of the file would have been wrong for every later step. The guard matters more in two cases:

- **An `old_string` copied from a stale view** of a file whose lines have since changed. It either isn't found or replaces the wrong thing.
- **A `write_file` of the whole file**, which would wipe out the other person's change completely. `write_file` runs the same `check` on any file that already exists.

**Why both a timestamp and a fingerprint?** The timestamp is cheap to read but can change without the contents changing, for example when a tool saves a file unchanged or someone runs `touch`. The fingerprint is exact but means reading the whole file. So `check` trusts an unchanged timestamp, and only hashes the file when the timestamp has moved. `test_edit_ignores_touch_without_content_change` pins that down: a `touch` alone doesn't block an edit.

#### If something goes wrong

- **`Error: read the file with read_file before editing it.` on a file the model did read:** `read_file` and `edit_file` were given different `Workspace` objects, so they have different trackers, or `read_file` returned before calling `mark_read`. Or the paths differ: `_seen` is keyed by the resolved `Path`, so `calc.py` and `./calc.py` must resolve to the same thing.
- **The second edit to a file fails with `changed on disk`:** `edit_file` (or `write_file`) didn't call `mark_read` after writing.
- **`old_string was not found` when the text is clearly there:** the model included the line-number prefix from `read_file` (`     4\t...`), or the file has `\r\n` endings and your `edit_file` reads it with Python's default newline translation. `_read_exact` reads bytes to avoid that.
- **A rename changed more than it should:** `replace_all` with a short `old_string` matches inside longer words. That's the model's choice, not a harness bug. A longer `old_string`, such as `def total(`, is safer.

#### Words used above

| Term | Meaning here |
|---|---|
| **`old_string` / `new_string`** | The exact text to find, and the text to put in its place. |
| **`replace_all`** | Replace every occurrence. Without it, `old_string` must appear exactly once. |
| **read tracker** (`ws.tracker`) | The `FileTracker` that remembers each file's state when the model last read it. |
| **mtime** | A file's last-modified time. `st_mtime_ns` is that time in nanoseconds. |
| **fingerprint / digest** | The SHA-256 of a file's bytes: identical bytes always give the same value, and any change gives a different one. |
| **stale** | Describes a view of a file that no longer matches what's on disk. |
| **CRLF** | `\r\n` line endings, used by Windows. `edit_file` keeps them as they are. |

## Break it

Run the 4B (`qwen3:4b-instruct` on Ollama, see lesson 3 for the config) on three small tasks against `edit_file` and `write_file`, and read the calls and results. What happened for the reference solution:

- *"In settings.py change PORT to 9000."* The 4B called `edit_file` first, got `Error: read the file with read_file before editing it.`, read the file, repeated the same edit, and it went through. The error text was enough.
- *"In app.py, in function b only, rename the variable x to count."* Two functions contain `x = 1`. The 4B's first edit hit the `appears 2 times` error, it retried the identical edit once after an unnecessary re-read, then widened `old_string` to `def b():\n    x = 1`. That edit applied, and it stopped with `return x + 1` still using the old name. The harness did its job (no wrong edit was made) and the task is still unfinished. Nothing here checks the work; that is lesson 9.
- *"Replace the contents of notes.txt with the single line 'gamma'."* The 4B went straight to `write_file`, got the not-read error, and ended its run after two requests without reading and retrying, leaving the file untouched. A refusal protects the file; it does not make the model comply.

Small models vary between runs, so yours may differ; the exercise is to read what yours did. Then remove the read-before-edit check from your tools and rerun the third task. What does the file look like, and would anything have told you?

## Extras

- Show the model a diff in the success message (a few lines around the change) so it can confirm without a re-read.
- When `old_string` is not found, suggest the closest line in the file.
- Write to a temporary file and rename it over the target, so a crash cannot leave a half-written file.
- A `replace_lines` tool by line number, and why line numbers are fragile after the first edit.
