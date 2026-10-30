"""Running shell commands inside bubblewrap (bwrap): every namespace unshared (pid, ipc,
network, ...), the whole filesystem read-only, the project folder writable, private /tmp
and /run, and the environment variables that point at host sockets removed."""
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


# Environment variables that tell programs where host sockets are.
_HOST_SOCKET_VARS = ("DBUS_SESSION_BUS_ADDRESS", "SSH_AUTH_SOCK", "XDG_RUNTIME_DIR")


def _under_run(p: Path) -> bool:
    p = Path(p)
    return p == Path("/run") or Path("/run") in p.parents \
        or p == Path("/var/run") or Path("/var/run") in p.parents


def build_bwrap_argv(command: str, cwd: Path, root: Path, cfg: SandboxConfig) -> list[str]:
    """The bwrap command line that runs ``command`` with bash in ``cwd``.

    Order matters: later mounts are layered on top of earlier ones, so the private /tmp
    comes before the project bind (a project under /tmp stays visible). A writable path
    under /run would be hidden by the private /run, so that is refused."""
    for p in [root, *cfg.extra_writable]:
        if _under_run(p):
            raise ValueError(f"{p} is under /run, which the sandbox hides")
    argv = ["bwrap", "--unshare-all"]
    if cfg.network:
        argv.append("--share-net")
    argv += ["--die-with-parent", "--new-session",
             "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
             "--tmpfs", "/tmp", "--tmpfs", "/run", "--bind", str(root), str(root)]
    for p in cfg.extra_writable:
        argv += ["--bind", str(p), str(p)]
    for var in _HOST_SOCKET_VARS:
        argv += ["--unsetenv", var]
    argv += ["--chdir", str(cwd), "--", "bash", "-c", command]
    return argv


def sandbox_available() -> bool:
    """True if bwrap is installed and can create this exact kind of sandbox here."""
    if shutil.which("bwrap") is None:
        return False
    probe = build_bwrap_argv("true", Path("/"), Path("/tmp"), SandboxConfig())
    try:
        return subprocess.run(probe, capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False
