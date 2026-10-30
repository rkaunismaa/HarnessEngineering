"""The directory the agent works in."""
from __future__ import annotations

import hashlib
from pathlib import Path

from .sandbox import SandboxConfig


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


class PathOutsideProject(Exception):
    """A tool was asked for a path that is not inside the project folder."""

    def __init__(self, path: str):
        super().__init__(f"{path} is outside the project folder.")
        self.path = path


class Workspace:
    def __init__(self, root: Path, sandbox: SandboxConfig | None = None):
        self.root = Path(root).resolve()
        self.sandbox = sandbox
        self.tracker = FileTracker()
        self.todos: list[dict] = []  # the model's plan, set by the todo_write tool

    def contains(self, p: Path) -> bool:
        """True if ``p``, fully resolved (symlinks followed), is the root or below it."""
        real = Path(p).resolve()
        return real == self.root or self.root in real.parents

    def resolve(self, path: str) -> Path:
        """Relative paths are taken relative to the root; absolute paths are kept. The result
        is fully resolved (``..`` collapsed, symlinks followed) and must lie inside the root,
        otherwise ``PathOutsideProject`` is raised."""
        p = (self.root / path).resolve()
        if not self.contains(p):
            raise PathOutsideProject(str(path))
        return p
