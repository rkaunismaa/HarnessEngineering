"""Running shell commands inside bubblewrap (bwrap): the whole filesystem read-only, the
project folder writable, a private /tmp, and (by default) no network."""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SandboxConfig:
    enabled: bool = True
    network: bool = False
    extra_writable: list[Path] = field(default_factory=list)


def build_bwrap_argv(command: str, cwd: Path, root: Path, cfg: SandboxConfig) -> list[str]:
    """The bwrap command line that runs ``command`` with bash in ``cwd``.

    Order matters: later mounts are layered on top of earlier ones, so the private /tmp
    comes before the project bind (a project under /tmp stays visible)."""
    argv = ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
            "--tmpfs", "/tmp", "--bind", str(root), str(root)]
    for p in cfg.extra_writable:
        argv += ["--bind", str(p), str(p)]
    if not cfg.network:
        argv.append("--unshare-net")
    argv += ["--die-with-parent", "--chdir", str(cwd), "--", "bash", "-c", command]
    return argv


def sandbox_available() -> bool:
    """True if bwrap is installed and can actually create a sandbox here."""
    if shutil.which("bwrap") is None:
        return False
    try:
        return subprocess.run(["bwrap", "--ro-bind", "/", "/", "true"],
                              capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False
