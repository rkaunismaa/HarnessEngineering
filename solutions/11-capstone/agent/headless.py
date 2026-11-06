"""Running the agent without a person at the keyboard: one task in, one report out."""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path

from .client import make_client
from .config import Config
from .context import ContextManager
from .log import RequestLog
from .loop import Agent
from .permissions import PermissionPolicy
from .prompt import build_system_prompt
from .sandbox import SandboxConfig, sandbox_available
from .tools import make_default_tools
from .tools.shell import run_shell
from .workspace import Workspace

DEFAULT_VERIFY_COMMAND = f"{sys.executable} -m pytest -q"
DEFAULT_TASK = ("The test suite has a failing test. Find the cause and fix it in the source "
                "code. Do not modify the tests.")
VERIFY_TIMEOUT = 300


class SandboxUnavailable(Exception):
    """A sandbox was required but bubblewrap cannot be used here."""


@dataclass
class RunReport:
    stop_reason: str
    final_text: str
    turns: int
    prompt_tokens: int
    completion_tokens: int
    duration_s: float
    log_path: Path | None
    verified: bool | None  # the last automatic check passed; None: no check ran


def _make_verify(ws: Workspace, command: str):
    def verify() -> tuple[bool, str]:
        code, output = run_shell(ws, command, timeout=VERIFY_TIMEOUT)
        if code is None:
            return False, f"{output}\n[timed out after {VERIFY_TIMEOUT}s]"
        return code == 0, output
    return verify


def run_task(task: str, root: Path, config: Config, *, client=None, require_sandbox: bool = True,
             verify_command: str | None = None, max_turns: int = 50,
             log: RequestLog | None = None) -> RunReport:
    """Run ``task`` in ``root`` with every tool call allowed, and report what happened.
    ``log`` defaults to a new session log in ``config.log_dir``."""
    if require_sandbox and not sandbox_available():
        raise SandboxUnavailable("bubblewrap (bwrap) is not usable here; install it or pass "
                                 "require_sandbox=False")
    ws = Workspace(Path(root).resolve(), sandbox=SandboxConfig(enabled=require_sandbox))
    client = client if client is not None else make_client(config)
    log = log if log is not None else RequestLog.for_session(config.log_dir)
    permissions = PermissionPolicy(auto_approve=True)
    tools = make_default_tools(ws, client=client, model=config.model, log=log,
                               context_window=config.context_window, permissions=permissions)
    agent = Agent(client, config.model, tools, system=build_system_prompt(ws, tools), log=log,
                  max_turns=max_turns, permissions=permissions, workspace=ws, stream=False,
                  context=ContextManager(config.context_window),
                  verify=_make_verify(ws, verify_command) if verify_command else None,
                  sampling=config.sampling())
    start = time.monotonic()
    result = agent.run(task)
    return RunReport(result.stop_reason, result.final_text, result.turns,
                     result.usage.prompt_tokens, result.usage.completion_tokens,
                     time.monotonic() - start, log.path, result.verified)
