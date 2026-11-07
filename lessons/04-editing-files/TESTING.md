# How the lesson 4 tests work

Lesson 4's tests drive `edit_file` and `write_file` directly, through `dispatch`, the same way lesson 2's tests drive the read-only tools. They check three kinds of thing: the safety rules (read before you edit; stop if the file changed underneath you), the matching rules (`old_string` must match exactly once unless you ask for every match), and that the bytes on disk come out exactly right, line endings included. Against the reference solution: 20 passed, 1 skipped (the live test).

```
uv run pytest lessons/04-editing-files
uv run pytest lessons/04-editing-files --impl solutions/04-editing-files
```

## The helpers, and why one registry matters

```python
def tools_for(tmp_path):
    return make_default_tools(Workspace(tmp_path), confirm_bash=lambda c: False)

def edit(registry, path, old, new, **kw):
    return run(registry, "edit_file", path=path, old_string=old, new_string=new, **kw)
```

Most tests follow the same pattern: write a file, `read_file` it, then `edit` it, all through *one* registry. The tools built by one `make_default_tools` call share a record of which files have been read and what they looked like at the time. That shared record is what the "read first" and "changed on disk" rules check, so a test that read the file with one registry and edited with another would fail.

Every test that expects a refusal also re-reads the file from disk to prove nothing changed. Checking the message alone wouldn't catch an edit that went through anyway.

## Read before you edit

- **`test_edit_requires_read`**: editing a file the model never read returns `Error: read the file with read_file before editing it.`, and the file is untouched. The model can only write a correct `old_string` if it has seen the current text.
- **`test_edit_same_file_via_different_spelling`**: reading `./a.txt` and then editing `a.txt` works. The record is keyed by the resolved path, not by whatever string the model typed.
- **`test_edit_then_edit_again_without_reread_ok`**: two edits in a row, with no read in between, both work. Your own edit updates the record, so the model doesn't have to re-read after every change.
- **`test_write_existing_requires_read`**: overwriting an existing file with `write_file` also needs a read first. After the read it works and returns `Wrote a.txt.`. A write counts as a read, so a following edit needs no re-read.
- **`test_write_new_file_creates_dirs`** and **`test_write_created_file_can_be_edited`**: creating a *new* file needs no read (there is nothing to read). Missing folders are created, the result is `Created deep/er/new.txt.`, and the new file can be edited straight away.

## Changed on disk since the last read

- **`test_edit_detects_external_change`**: read the file, then change it behind the agent's back (as you might in your editor while it works). The edit returns `Error: the file changed on disk since you last read it. Read it again before editing.`, and your change survives. Reading again clears the error. The test pushes the modification time forward 5 seconds with `os.utime`, because some filesystems only record times to the second. Without that, a write within the same second could look unchanged.
- **`test_edit_ignores_touch_without_content_change`**: only the modification time moves; the content is the same. The edit must go through. A changed time alone isn't enough: tools like `touch` or `git checkout` update it without changing anything, so the check has to compare content too.
- **`test_edit_detects_deleted_file`**: if the file was deleted after the read, the edit returns an error.

## Matching `old_string`

| Test | Situation | Result |
|---|---|---|
| `test_edit_unique_match` | one match | `Edited a.txt (1 replacement).` and the new content on disk |
| `test_edit_multiple_matches_error` | `x` appears 3 times | an error that says how many, and how to fix it: add surrounding lines, or set `replace_all` |
| `test_edit_replace_all` | `replace_all=True` | `Edited a.txt (3 replacements).` |
| `test_edit_not_found` | no match | `Error: old_string was not found in the file.` |
| `test_edit_same_strings` | old == new | `Error: old_string and new_string are the same.` |
| `test_edit_missing_file` | file doesn't exist | an error |

Refusing an ambiguous match, rather than replacing the first one, is the core design choice. A model that meant the third `x` would otherwise silently edit the wrong place. The error message is phrased as instructions, because the model reads it.

## Line endings: exact bytes

These tests use `write_bytes` and `read_bytes`, so text-mode newline conversion can't hide a mistake:

- **`test_edit_preserves_trailing_newline_and_crlf`**: in a Windows-style (`\r\n`) file, changing `two` to `2` leaves every other `\r\n` in place. In a file with no final newline, the edit doesn't add one.
- **`test_crlf_multiline_edit`**: the model always writes `\n`, because that's what `read_file` showed it. Here `old_string` is `"b\nc\n"`, which doesn't literally occur in a CRLF file, yet it must still match, and the replacement must be written with `\r\n`.
- **`test_crlf_edit_never_inserts_bare_newline`**: here `old_string` (`two`) matches directly, with no newline in it, but `new_string` (`two\nthree`) has one. It must become `\r\n` too, or the file ends up with mixed line endings. This test was added after a real bug in the reference solution (commit 5e40ef8).

**`test_read_file_output_unchanged`** guards against a side effect: adding the read record must not change what `read_file` returns.

## The live test

`test_live_edit` (run with `--live`) writes `greeting.py` containing `"Helo, "` and asks the 27B in LM Studio to fix the typo with `edit_file`. It prints each call and result, then checks the *file*, not the answer: `"Hello, "` must be on disk. A model saying it fixed something proves nothing; the change on disk does.

```
uv run pytest lessons/04-editing-files --live -s -k live
```
