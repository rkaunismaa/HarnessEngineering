"""The directory the agent works in."""
from __future__ import annotations

from pathlib import Path


class Workspace:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def resolve(self, path: str) -> Path:
        """Relative paths are taken relative to the root; absolute paths are kept."""
        return self.root / path
