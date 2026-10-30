"""Root pytest config: choose which ``agent`` package the tests import, and gate live/sandbox tests."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent


def pytest_addoption(parser):
    parser.addoption("--impl", default=str(ROOT),
                     help="directory containing the `agent` package to test (default: repo root)")
    parser.addoption("--live", action="store_true", help="run tests that need a live model server")


def pytest_configure(config):
    config.addinivalue_line("markers", "live: needs a running model server; run with --live")
    config.addinivalue_line("markers", "sandbox: needs a usable bubblewrap (bwrap)")
    impl = str(Path(config.getoption("--impl")).resolve())
    for name in [m for m in sys.modules if m == "agent" or m.startswith("agent.")]:
        del sys.modules[name]
    sys.path.insert(0, impl)


def _bwrap_usable() -> bool:
    if not shutil.which("bwrap"):
        return False
    try:
        return subprocess.run(["bwrap", "--ro-bind", "/", "/", "true"],
                              capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def pytest_collection_modifyitems(config, items):
    skip_live = None if config.getoption("--live") else pytest.mark.skip(reason="needs --live")
    skip_sandbox = None
    if any("sandbox" in item.keywords for item in items) and not _bwrap_usable():
        skip_sandbox = pytest.mark.skip(reason="bubblewrap (bwrap) not usable here")
    for item in items:
        if skip_live and "live" in item.keywords:
            item.add_marker(skip_live)
        if skip_sandbox and "sandbox" in item.keywords:
            item.add_marker(skip_sandbox)
