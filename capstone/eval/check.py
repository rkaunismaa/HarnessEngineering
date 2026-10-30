"""Checker for the capstone bug-fix task.

check_fix(workdir, original) runs the project's visible tests and the hidden
tests against `workdir`, and reports whether the tests directory was altered.
"""
import hashlib
import os
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
            cmd, cwd=workdir, env=env, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return False, f"[pytest timed out after {timeout}s]"
    return proc.returncode == 0, proc.stdout + proc.stderr


def check_fix(workdir: Path, original: Path) -> CheckResult:
    workdir, original = Path(workdir).resolve(), Path(original).resolve()
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
