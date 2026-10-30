"""Command line entry point. Later lessons add subcommands (ask, log, chat, run, eval)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.markup import escape
from rich.prompt import Prompt

from .client import make_client, smoke_test
from .cli import ConsoleEvents, chat_loop
from .config import load_config
from .context import ContextManager
from .log import RequestLog, format_entry, latest_log, read_log
from .loop import Agent
from .permissions import PermissionPolicy
from .prompt import build_system_prompt
from .sandbox import SandboxConfig, sandbox_available
from .tools import make_default_tools
from .tools.shell import run_shell
from .workspace import Workspace


def _smoke(args) -> int:
    config = load_config()
    try:
        result = smoke_test(make_client(config), config.model)
    except Exception as e:  # server down, wrong model name, ...
        print(f"FAIL: could not reach {config.base_url}: {e}")
        return 1
    print(f"{'OK' if result.ok else 'FAIL'}: {result.detail}")
    print(f"  tool: {result.tool_name}  arguments: {result.arguments}  "
          f"prompt tokens: {result.prompt_tokens}")
    return 0 if result.ok else 1


def _approve(name: str, args: dict) -> str:
    """Ask the user about one tool call: "yes", "always" or "no"."""
    console = Console()
    shown = args.get("command") if name == "bash" else args
    console.print(f"[bold]{escape(name)}[/bold] wants to run:\n  {escape(str(shown))}")
    try:
        answer = Prompt.ask(escape("[y]es / [a]lways / [n]o"), choices=["y", "a", "n"],
                            default="n", show_choices=False, console=console)
    except (EOFError, KeyboardInterrupt):  # no one to answer: refuse
        return "no"
    return {"y": "yes", "a": "always"}.get(answer, "no")


def _make_verify(ws: Workspace, command: str):
    """The check passes when ``command`` exits with code 0; its output is what the model
    is told when it fails."""
    def verify() -> tuple[bool, str]:
        code, output = run_shell(ws, command, timeout=300)
        if code is None:
            return False, f"{output}\n[timed out after 300s]"
        return code == 0, f"{output}\n[exit code: {code}]"
    return verify


def _build_agent(args, **agent_kwargs) -> Agent | None:
    """The agent both ``ask`` and ``chat`` use, or None (after printing why) if it can't start."""
    config = load_config()
    available = sandbox_available() if args.sandbox is not False else False
    if args.sandbox and not available:
        print("--sandbox was given but bubblewrap (bwrap) is not usable here.", file=sys.stderr)
        return None
    use_sandbox = available
    if not use_sandbox:
        print("Warning: running bash commands without a sandbox.", file=sys.stderr)
    ws = Workspace(Path(args.root), sandbox=SandboxConfig() if use_sandbox else None)
    tools = make_default_tools(ws)
    if getattr(args, "verify", None):
        agent_kwargs["verify"] = _make_verify(ws, args.verify)
    return Agent(make_client(config), config.model, tools,
                 system=build_system_prompt(ws, tools),
                 log=RequestLog.for_session(config.log_dir),
                 permissions=PermissionPolicy(allow=args.allow), approver=_approve,
                 workspace=ws, context=ContextManager(config.context_window),
                 **agent_kwargs)


def _ask(args) -> int:
    agent = _build_agent(args)
    if agent is None:
        return 1
    result = agent.run(args.prompt)
    if result.stop_reason == "error":
        print(result.error, file=sys.stderr)
        return 1
    if result.stop_reason == "max_turns":
        print(f"Stopped after {result.turns} requests without a final answer.", file=sys.stderr)
        return 1
    print(result.final_text)
    return 0


def _chat(args) -> int:
    console = Console()
    events = ConsoleEvents(console)
    agent = _build_agent(args, events=events, stream=True)
    if agent is None:
        return 1
    return chat_loop(agent, events, console)


def _log(args) -> int:
    path = Path(args.path) if args.path else latest_log(load_config().log_dir)
    if path is None or not path.is_file():
        print("No log found.")
        return 1
    console = Console()
    for entry in read_log(path):
        console.print(format_entry(entry), markup=False, highlight=False, soft_wrap=True)
    return 0


def _add_agent_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", default=".", help="directory the agent works in")
    parser.add_argument("--sandbox", action=argparse.BooleanOptionalAction, default=None,
                        help="run bash inside bubblewrap (default: on when bwrap is usable)")
    parser.add_argument("--allow", action="append", default=[], metavar="RULE",
                        help="permission rule to allow without asking, e.g. 'bash(pytest*)' "
                             "(repeatable)")
    parser.add_argument("--verify", metavar="COMMAND",
                        help="shell command to run when the model says it is done; if it "
                             "fails, its output goes back to the model (e.g. 'pytest -q')")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent")
    sub = parser.add_subparsers(dest="command", required=True)
    smoke = sub.add_parser("smoke", help="check the model server and tool calling")
    smoke.set_defaults(func=_smoke)
    ask = sub.add_parser("ask", help="send one prompt and print the final answer")
    ask.add_argument("prompt")
    _add_agent_options(ask)
    ask.set_defaults(func=_ask)
    chat = sub.add_parser("chat", help="interactive session that streams the model's output")
    _add_agent_options(chat)
    chat.set_defaults(func=_chat)
    log = sub.add_parser("log", help="print a request log")
    log.add_argument("path", nargs="?", help="log file (default: the latest)")
    log.set_defaults(func=_log)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
