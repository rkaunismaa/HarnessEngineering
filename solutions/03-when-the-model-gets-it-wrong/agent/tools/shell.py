"""The bash tool."""
from __future__ import annotations

import os
import signal
import subprocess
import threading
from typing import Callable

from ..workspace import Workspace
from .registry import Tool

MAX_CAPTURE = 1_000_000  # bytes kept from a command; dispatch truncates what the model sees


def _run(ws: Workspace, command: str, timeout: int) -> tuple[int | None, str]:
    """Run ``command`` with bash in the workspace. Returns (exit code, output);
    the exit code is None when the command timed out and was killed."""
    proc = subprocess.Popen(["bash", "-c", command], cwd=ws.root, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            start_new_session=True)  # own process group, so we can kill it all
    chunks: list[bytes] = []

    def drain() -> None:
        kept = 0
        while True:
            data = proc.stdout.read1(65536)
            if not data:
                return
            if kept < MAX_CAPTURE:
                chunks.append(data[:MAX_CAPTURE - kept])
                kept += len(chunks[-1])

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    try:
        code: int | None = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        code = None
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
    reader.join(timeout=2)
    proc.stdout.close()
    return code, b"".join(chunks).decode("utf-8", errors="replace")


def make_bash(ws: Workspace, confirm: Callable[[str], bool] | None = None) -> Tool:
    def bash(command: str, timeout: int = 30) -> str:
        if confirm is not None and not confirm(command):
            return "Error: the user declined to run this command."
        code, output = _run(ws, command, timeout)
        if code is None:
            return f"{output}\n[timed out after {timeout}s]"
        return f"{output}\n[exit code: {code}]"

    return Tool(
        name="bash",
        description="Run a shell command with bash in the project root. Returns combined "
                    "stdout and stderr followed by the exit code. Commands that run longer "
                    "than timeout seconds (default 30) are killed. Use it for running tests "
                    "and other programs; prefer read_file, list_files and search for "
                    "looking at files.",
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The command line to run"},
                "timeout": {"type": "integer",
                            "description": "Seconds before the command is killed (default 30)"},
            },
            "required": ["command"],
        },
        fn=bash,
    )
