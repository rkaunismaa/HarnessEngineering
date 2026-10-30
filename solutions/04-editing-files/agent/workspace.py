"""The directory the agent works in."""
from __future__ import annotations

import hashlib
from pathlib import Path


def _digest(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


class FileTracker:
    """Remembers which files the model has read, and what they looked like then."""

    def __init__(self) -> None:
        self._seen: dict[Path, tuple[int, str]] = {}

    def mark_read(self, path: Path) -> None:
        digest = _digest(path)
        if digest is not None:
            self._seen[path] = (path.stat().st_mtime_ns, digest)

    def check(self, path: Path) -> str | None:
        """None if ``path`` was read and is unchanged; otherwise an error string."""
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


class Workspace:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.tracker = FileTracker()

    def resolve(self, path: str) -> Path:
        """Relative paths are taken relative to the root; absolute paths are kept."""
        return self.root / path
