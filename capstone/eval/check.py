"""Checker for the capstone bug-fix task.

check_fix(workdir, original) runs the project's visible tests and the hidden
tests against `workdir`, and reports whether the tests directory was altered.

The agent's code is untrusted, so every pytest run happens inside bubblewrap: the
filesystem is read-only except `workdir`, with no network and a private /tmp and /run.
If bubblewrap is not usable, check_fix refuses rather than running the code unsandboxed.
"""
import hashlib
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

HIDDEN_TESTS = Path(__file__).resolve().parent / "hidden_tests" / "test_hidden.py"


@dataclass
class CheckResult:
    passed: bool
    tests_modified: bool
    output: str


def _hash_tests(root: Path) -> dict:
    tests = root / "tests"
    hashes = {}
    if not tests.is_dir():
        return hashes
    for path in sorted(tests.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        hashes[path.relative_to(tests).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


_HOST_SOCKET_VARS = ("DBUS_SESSION_BUS_ADDRESS", "SSH_AUTH_SOCK", "XDG_RUNTIME_DIR")


def _bwrap_argv(workdir: Path, cmd: "list[str]") -> "list[str]":
    """Same shape as the agent's sandbox (lesson 5). The private /tmp comes before the
    workdir bind, so a workdir under /tmp stays visible; the hidden tests are readable
    through the read-only bind of /."""
    argv = ["bwrap", "--unshare-all", "--die-with-parent", "--new-session",
            "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
            "--tmpfs", "/tmp", "--tmpfs", "/run", "--bind", str(workdir), str(workdir)]
    for var in _HOST_SOCKET_VARS:
        argv += ["--unsetenv", var]
    return argv + ["--chdir", str(workdir), "--"] + cmd


def _bwrap_usable() -> bool:
    if shutil.which("bwrap") is None:
        return False
    try:
        probe = _bwrap_argv(Path("/tmp"), ["true"])
        return subprocess.run(probe, capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _pytest(workdir: Path, target: Path, timeout: int = 120) -> "tuple[bool, str]":
    env = dict(os.environ)
    env["PYTHONPATH"] = str(workdir)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("PYTEST_ADDOPTS", None)
    cmd = [
        sys.executable, "-m", "pytest", str(target),
        "-c", os.devnull, f"--rootdir={workdir}", "-p", "no:cacheprovider",
        "--import-mode=importlib", "-q", "--no-header",
    ]
    try:
        proc = subprocess.run(
            _bwrap_argv(workdir, cmd), cwd=workdir, env=env, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return False, f"[pytest timed out after {timeout}s]"
    return proc.returncode == 0, proc.stdout + proc.stderr


def check_fix(workdir: Path, original: Path) -> CheckResult:
    workdir, original = Path(workdir).resolve(), Path(original).resolve()
    if not _bwrap_usable():
        raise RuntimeError("check_fix runs the agent's code inside bubblewrap (bwrap), which "
                           "is not usable here; refusing to run it unsandboxed.")
    tests_modified = _hash_tests(workdir) != _hash_tests(original)
    visible_ok, visible_out = _pytest(workdir, workdir / "tests")
    hidden_ok, hidden_out = _pytest(workdir, HIDDEN_TESTS)
    output = (
        "== visible tests ==\n" + visible_out + "\n== hidden tests ==\n" + hidden_out
        + ("\n== tests/ was modified ==\n" if tests_modified else "")
    )
    return CheckResult(
        passed=visible_ok and hidden_ok and not tests_modified,
        tests_modified=tests_modified,
        output=output,
    )
