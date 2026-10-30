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

Lessons 1 to 3 still apply. `test_edit_detects_external_change` rewrites a file after the read and moves its mtime forward with `os.utime`; `test_edit_ignores_touch_without_content_change` moves only the mtime. The live test is `test_live_edit`: the model fixes a typo in a temp file using `edit_file`.

## Try it live

Make a small file and ask the 27B to change it:

```
mkdir -p /tmp/scratch && printf 'def total(items):\n    return sum(items)\n\nprint(total([1, 2]))\nprint(total([3]))\n' > /tmp/scratch/calc.py
uv run python -m agent ask "In calc.py rename the function total to add_up everywhere, using edit_file." --root /tmp/scratch
uv run python -m agent log
```

What the reference solution did: `read_file` first (1138 prompt tokens on that request), then a single `edit_file` call with `old_string: "total"`, `new_string: "add_up"` and `replace_all: true`, answered with `Edited calc.py (3 replacements).` Then it read the file again to check, and tried `bash` to run it. (If `bash` asks for confirmation on your terminal, answer it; it waits for you.)

Now try the guard rails yourself: ask for an edit, then change the file in another terminal between the model's read and its edit, and look in the log for the `changed on disk` result and what the model did next.

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
