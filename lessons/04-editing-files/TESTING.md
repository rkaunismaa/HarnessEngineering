# How the lesson 4 tests work

Against the reference solution: 20 passed, 1 skipped (the live test). The live test passes too with `--live` (4.5 s against the 27B).

```
uv run pytest lessons/04-editing-files
uv run pytest lessons/04-editing-files --impl solutions/04-editing-files
uv run pytest lessons/04-editing-files --live -s -k live
```

## The big picture

Lesson 4 lets the agent change files, with `edit_file` (replace an exact string) and `write_file` (create or overwrite). These are the first tools that can do damage, so most of the tests check what they *refuse* to do, and then look at the file on disk to prove nothing changed.

There are three kinds of check:

1. **The safety rules.** You can't edit a file you haven't read, and you can't edit one that changed on disk since you read it.
2. **The matching rules.** `old_string` must match exactly once, unless you ask for every match.
3. **The bytes on disk.** Line endings and final newlines come out exactly as they were.

Like lesson 2, these tests call the tools directly through `dispatch`, with no model and no loop.

## Where the "have I read this?" memory lives

The safety rules need memory: which files were read, and what they looked like at the time. In the reference solution that memory is a small object on the **workspace**, `ws.tracker` (a `FileTracker`). It holds one dict:

```python
self._seen: dict[Path, tuple[int, str]]    # resolved path -> (modification time in ns, SHA-256 of the content)
```

- `read_file` calls `ws.tracker.mark_read(path)` after a successful read.
- `edit_file` calls `ws.tracker.check(path)` before doing anything, then `mark_read` again after writing. An edit counts as a read.
- `write_file` does the same.

The tools share the tracker because they share the workspace. That's why every test does its reads and edits through **one** registry built by **one** `tools_for(tmp_path)` call. A test that read a file through one registry and edited it through another would have two separate trackers, and would fail.

## The helpers

```python
def tools_for(tmp_path):
    return make_default_tools(Workspace(tmp_path), confirm_bash=lambda c: False)

def edit(registry, path, old, new, **kw):
    return run(registry, "edit_file", path=path, old_string=old, new_string=new, **kw)
```

`run` is lesson 2's helper: keyword arguments become a JSON string passed to `dispatch`.

## One test, step by step: `test_edit_detects_external_change`

This test plays out a real situation: the agent reads a file, then **you** change it in your editor, then the agent tries to edit its stale copy.

```python
def test_edit_detects_external_change(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("hello\n")
    registry = tools_for(tmp_path)
    run(registry, "read_file", path="a.txt")
    st = p.stat()
    p.write_text("hello world\n")
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    assert edit(registry, "a.txt", "hello", "bye") == CHANGED
    assert p.read_text() == "hello world\n"
    run(registry, "read_file", path="a.txt")
    assert edit(registry, "a.txt", "hello", "bye") == "Edited a.txt (1 replacement)."
```

Here is the tracker's state at each step when this sequence runs on the reference solution, with times shortened:

**Start.** `a.txt` contains `hello\n`, and the tracker is empty: `_seen = {}`. An edit now would return `Error: read the file with read_file before editing it.`

**`read_file`.** It returns `'     1\thello'` and records the file:

```
_seen = {a.txt: (mtime=...072331298678, sha=5891b5b522d5...)}
```

**The outside change.** The test writes `hello world\n` and moves the modification time forward 5 seconds with `os.utime`. The time shift is there because some filesystems only record times to the second, and a write in the same second could look unchanged.

**The edit.** `check` compares the file with the record. The time is different (`...077331298678`), so it computes the hash. That's different too, so the edit is refused:

```
Error: the file changed on disk since you last read it. Read it again before editing.
```

The file still contains `hello world\n`; your change survived. If the agent had edited its stale idea of the file, it would have overwritten your change without knowing.

**Read again.** A new record is stored: `_seen = {a.txt: (mtime=...077331298678, sha=a948904f2f0f...)}`.

**Edit again.** `check` passes, `hello` becomes `bye`, the file is now `bye world\n`, and the result is `Edited a.txt (1 replacement).`. The tracker is updated with the new time and hash. Your own edit doesn't count as a change, so the next edit needs no re-read.

**Why both a time and a hash?** The time is the fast check: if it matches, the file is assumed unchanged. If it differs, the hash decides. `test_edit_ignores_touch_without_content_change` covers exactly that case: tools like `touch` or `git checkout` update the time without changing the content, and the edit must still go through.

## What each group of tests pins down

Every test that expects a refusal also re-reads the file from disk to prove nothing changed.

### Read before you edit

- **`test_edit_requires_read`**: editing an unread file returns `Error: read the file with read_file before editing it.`, and the file is untouched. The model can only write a correct `old_string` if it has seen the current text.
- **`test_edit_same_file_via_different_spelling`**: reading `./a.txt` then editing `a.txt` works. The tracker is keyed by the *resolved* path.
- **`test_edit_then_edit_again_without_reread_ok`**: two edits in a row both work, because each edit updates the record.
- **`test_write_existing_requires_read`**: overwriting an existing file also needs a read first. After the read it returns `Wrote a.txt.`, and a following edit needs no re-read.
- **`test_write_new_file_creates_dirs`** and **`test_write_created_file_can_be_edited`**: creating a *new* file needs no read. Missing folders are created, the result is `Created deep/er/new.txt.`, and the new file can be edited at once.
- **`test_edit_detects_deleted_file`**: if the file was deleted after the read, the edit returns an error.

### Matching `old_string`

| Test | Situation | Exact result |
|---|---|---|
| `test_edit_unique_match` | one match | `Edited a.txt (1 replacement).` |
| `test_edit_multiple_matches_error` | `x` three times | `Error: old_string appears 3 times. Include more surrounding lines to make it unique, or set replace_all to true.` |
| `test_edit_replace_all` | `replace_all=True` | `Edited a.txt (3 replacements).` |
| `test_edit_not_found` | no match | `Error: old_string was not found in the file.` |
| `test_edit_same_strings` | old == new | `Error: old_string and new_string are the same.` |
| `test_edit_missing_file` | file doesn't exist | an error |

Refusing an ambiguous match, instead of replacing the first one, is the main design choice. A model that meant the third `x` would otherwise silently edit the wrong place. Each error is written as instructions, because the model is the one reading it.

### Line endings: exact bytes

These tests use `write_bytes` and `read_bytes`, so Python's text-mode newline conversion can't hide a mistake:

- **`test_edit_preserves_trailing_newline_and_crlf`**: in a Windows-style (`\r\n`) file, changing `two` to `2` leaves every other `\r\n` in place. A file with no final newline doesn't gain one.
- **`test_crlf_multiline_edit`**: the model writes `\n`, because that's what `read_file` showed it. Here `old_string` is `"b\nc\n"`, which doesn't literally occur in the CRLF file. The solution converts it to `\r\n` form, finds it, and writes the replacement with `\r\n` too: `b'a\r\nB\r\nC\r\nC2\r\nd\r\n'`.
- **`test_crlf_edit_never_inserts_bare_newline`**: `old_string` (`two`) matches directly with no conversion, but `new_string` (`two\nthree`) has a newline, which must still become `\r\n`. This test was added after a real bug in the reference solution (commit 5e40ef8).

**`test_read_file_output_unchanged`** guards against a side effect: adding the tracker must not change what `read_file` returns.

## The live test

`test_live_edit` (run with `--live`) writes `greeting.py` containing `"Helo, "` and asks the 27B to fix the typo with `edit_file`. It then checks the **file**, not the answer. A model saying it fixed something proves nothing; the change on disk does. On 2026-11-12:

```
stop_reason=done turns=3
  CALL read_file({"path":"greeting.py"})
  RESULT '     1\tdef greet(name):\n     2\t    return "Helo, " + name'
  CALL edit_file({"path":"greeting.py","old_string":"return \"Helo, \" + name","new_string":"return \"Hello, \" + name"})
  RESULT 'Edited greeting.py (1 replacement).'
```

The model read first, without being told to. Its `old_string` is the line *without* the `     2\t` number prefix that `read_file` showed it. The tool description says not to include that prefix, and a model that copies it gets `old_string was not found`.

## If a test fails

- **"read before editing" errors where you expected success:** your read and edit use different trackers (built from different workspaces), or the tracker isn't keyed by the resolved path.
- **`test_edit_ignores_touch_without_content_change` fails:** you compare only modification times. Fall back to comparing content when the time differs.
- **A CRLF test fails:** print `crlf.read_bytes()` and look for a bare `\n` with no `\r` before it.

## Words used above

| Term | Meaning here |
|---|---|
| **tracker** | The workspace's record of which files were read, and their time and hash at that moment. |
| **mtime** | A file's last-modified time; `st_mtime_ns` is in nanoseconds. |
| **hash (SHA-256)** | A short fingerprint of the content. Different content gives a different hash. |
| **CRLF / LF** | Windows line endings (`\r\n`) versus Unix ones (`\n`). |
| **`os.utime`** | Sets a file's access and modification times; the test uses it to fake "changed later". |
