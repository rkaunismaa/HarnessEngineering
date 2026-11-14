# Lesson 4 solution: what changed since lesson 3

This folder is the reference solution for [lesson 4](../../lessons/04-editing-files/README.md). This page compares its `agent/` package with the one in [`solutions/03-when-the-model-gets-it-wrong/agent/`](../03-when-the-model-gets-it-wrong/agent/), file by file. For each change it says what the code does, why it's written that way, and what it's meant to show you.

To run this solution without touching your own `agent/` folder, run commands from inside this folder (`cd solutions/04-editing-files`). `python -m agent` imports the `agent` package from the folder you're in. To run the lesson's tests against it: `uv run pytest lessons/04-editing-files --impl solutions/04-editing-files`, from the repository root.

## At a glance

| File | Lesson 3 | Lesson 4 | Status |
|---|---|---|---|
| `agent/tools/files.py` | 142 lines | 231 lines | **changed**: `edit_file` and `write_file` added; `read_file` records each read |
| `agent/workspace.py` | 13 lines | 50 lines | **changed**: the `FileTracker`, kept on the workspace as `ws.tracker` |
| `agent/tools/__init__.py` | 21 lines | 23 lines | **changed**: registers the two new tools |
| everything else | | | unchanged |

The loop, `dispatch` and the CLI didn't change. The two new tools return their errors as strings, so lesson 3's machinery already handles them.

## What lesson 3 could do, and what it couldn't

Lesson 3's agent could look at a project but not change it, except through `bash`, with something like `sed -i` or `cat > file`. Those edits are blind: nothing checks that the model knows what the file says now, nothing stops it overwriting a file it never read, and a typo in a `sed` expression can quietly do nothing, or the wrong thing.

## What this lesson is meant to show you

1. **Exact-match edits beat whole-file rewrites.** The model sends a piece of the file's current text (`old_string`) and its replacement (`new_string`). It generates only the change, not the whole file. Everything outside the match is untouched by construction, and the edit is small enough to read in the log.
2. **Ambiguity is refused, not guessed.** If `old_string` isn't there, nothing changes. If it's there more than once, the harness refuses and asks for more context, instead of guessing which one was meant.
3. **The model must read before it writes.** Its idea of a file comes from an earlier `read_file` result. If it never read the file, its `old_string` is a guess, and a `write_file` would destroy the file blind.
4. **A read can go stale.** You save in your editor, a formatter runs, a `bash` command rewrites the file. An edit based on the old text could undo the newer change without anyone noticing. So the harness remembers what each file looked like when it was read, and refuses if it's different now.
5. **Bytes matter.** A file with Windows line endings (`\r\n`), or no newline at the end, must keep them. The model writes `\n`; the harness has to fit that into the file as it is.

## File by file

### `agent/workspace.py` (changed): the read tracker

```python
class FileTracker:
    def __init__(self) -> None:
        self._seen: dict[Path, tuple[int, str]] = {}

    def mark_read(self, path: Path) -> None:
        digest = _digest(path)
        if digest is not None:
            self._seen[path] = (path.stat().st_mtime_ns, digest)

    def check(self, path: Path) -> str | None:
        seen = self._seen.get(path)
        if seen is None:
            return "Error: read the file with read_file before editing it."
        mtime, digest = seen
        try:
            if path.stat().st_mtime_ns == mtime:
                return None  # fast path: same timestamp, assume same content
        except OSError:
            pass
        if _digest(path) != digest:  # a touched file with identical content is fine
            return ("Error: the file changed on disk since you last read it. "
                    "Read it again before editing.")
        return None
```

**What it does:** for each file the model has read, it remembers two things: the file's last-modified time in nanoseconds (`st_mtime_ns`), and a SHA-256 fingerprint of its bytes. `check` returns `None` if the file is unchanged since then, or an error string the tool can return as it is.

**Why it's written this way:**

- **Both a timestamp and a fingerprint.** The timestamp is cheap to read, so an unchanged timestamp is trusted without reading the file. But a timestamp can move without the contents changing: an editor saves without changes, or someone runs `touch`. So when it has moved, `check` hashes the file and only complains if the bytes really differ. `test_edit_ignores_touch_without_content_change` pins this down.
- **A deleted file counts as changed.** `_digest` returns `None` when the file can't be read, which never equals a stored fingerprint.
- **It lives on the `Workspace`**, as `ws.tracker`, because every file tool already gets the same `ws`. `read_file` marks, `edit_file` and `write_file` check, and they all see one shared record. This is why lesson 1 made `Workspace` a class.
- **Keys are the paths `Workspace.resolve` returns**, so `a.txt` and `./a.txt` are the same entry.
- **`check` returns the error message itself**, written for the model: it says what to do next ("Read it again before editing").

### `agent/tools/files.py` (changed): editing and writing

**`read_file`** gains one line, `ws.tracker.mark_read(p)`, after a successful read. A partial read with `offset` and `limit` counts too. Its output doesn't change.

**`edit_file(path, old_string, new_string, replace_all=False)`** runs its checks in a fixed order, and the first failure is returned:

| Check | Error |
|---|---|
| The file exists | `Error: file not found: <path>` |
| `ws.tracker.check(p)`: read, and unchanged since | `Error: read the file with read_file before editing it.` or `Error: the file changed on disk since you last read it. Read it again before editing.` |
| `old_string` differs from `new_string` | `Error: old_string and new_string are the same.` |
| The file is UTF-8 | `Error: <path> is not a UTF-8 text file.` |
| `old_string` is found | `Error: old_string was not found in the file.` |
| It's found once, or `replace_all` is set | `Error: old_string appears 3 times. Include more surrounding lines to make it unique, or set replace_all to true.` |

On success it writes the file, **marks it as read again**, and returns `Edited <path> (N replacements).`.

**Why:**

- **The tracker check comes before anything else that reads the file.** An edit based on a stale view is refused, even if its `old_string` would still happen to match.
- **Each error says how to fix it.** The "appears N times" message names both ways out: more context, or `replace_all`.
- **The replacement count is in the result,** so the model can check the edit did what it expected (a rename across a file should say 3, not 1).
- **Re-marking after the write** is essential. The edit has just changed the file's timestamp and bytes. Without it, the model's *next* edit to the same file would be refused as "changed on disk", by its own change.
- **`replace_all`** exists for renames. Without it, renaming a function used ten times would take ten edits, each with enough context to be unique.
- **An empty `old_string` never matches** (`count = 0`), rather than "matching" between every character.

**`_read_exact` and line endings.** Python's `read_text` translates `\r\n` to `\n` by default, and `write_text` can translate back the other way. Either would change lines the model never touched. So `edit_file` reads and writes **bytes**, decoded and encoded as UTF-8. In a file that uses `\r\n`:

```python
if "\r\n" in text:
    if old_string not in text:
        old_string = old_string.replace("\r\n", "\n").replace("\n", "\r\n")
    new_string = new_string.replace("\r\n", "\n").replace("\n", "\r\n")
```

The model writes line breaks as `\n`, because that's what it sees in `read_file` output. So every line break in `new_string` becomes `\r\n`, and a multi-line `old_string` is retried with `\r\n` if it isn't found as given. A file never ends up with mixed line endings, and a file with no final newline still has none.

**`write_file(path, content)`** creates a file (and any missing parent folders) or replaces one. For a file that **already exists**, it runs the same `ws.tracker.check` first, so it can't overwrite a file the model never read, or one that changed since. A new file needs no read. Either way, the file counts as read afterwards. It returns `Created <path>.` or `Wrote <path>.`, so the model knows which happened.

**Why both tools:** `edit_file` is right for changing part of a file. `write_file` is right for a new file. The descriptions say so ("To change part of a file, use edit_file instead"), because a model left to itself tends to rewrite whole files.

Neither new tool is `read_only`. That flag is unused until lesson 5, where it decides which tools run without asking you.

### `agent/tools/__init__.py` (changed): six tools

`make_default_tools` now registers `read_file`, `list_files`, `search`, `edit_file`, `write_file` and `bash`. The two new schemas cost about 300 prompt tokens on every request: lesson 2's four tools came to 844 tokens for a simple question, and lesson 4's six to 1,138.

## What's still missing, and which lesson adds it

| Gap in this version | What goes wrong | Fixed in |
|---|---|---|
| `resolve` lets paths leave the project | `edit_file("../other-project/x.py", ...)` works | lesson 5 |
| Edits and writes run without asking you | only `bash` asks; a bad edit lands straight away | lesson 5 |
| A `bash` command can change a file without the tracker knowing | the next edit is refused as "changed on disk". That's the right answer, but it costs the model an extra read | (by design) |
| No system prompt | the model learns "read before edit" by being refused once | lesson 6 |
| Nothing checks that an edit worked | the model says "done" without running the tests | lesson 9 |

## Seeing it work

From inside this folder:

```
uv run python ../../scripts/make_fixture.py scratch /tmp/scratch4
uv run python -m agent ask "In calc.py rename the function total to add_up everywhere, using edit_file." --root /tmp/scratch4
uv run python -m agent log
```

The reference run read `calc.py`, then made one `edit_file` call with `old_string: "total"`, `new_string: "add_up"` and `replace_all: true`, and got `Edited calc.py (3 replacements).`. The lesson's README walks through that run [step by step](../../lessons/04-editing-files/README.md#what-happens-when-you-run-it-step-by-step), including the tracker's state, and a second run where the file changed between the read and the edit. [TESTING.md](../../lessons/04-editing-files/TESTING.md) explains each test.
