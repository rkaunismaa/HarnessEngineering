"""Command line entry point. Later lessons add subcommands (ask, log, chat, run, eval)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.markup import escape
from rich.prompt import Confirm

from .client import make_client, smoke_test
from .config import load_config
from .log import RequestLog, format_entry, latest_log, read_log
from .loop import Agent
from .tools import make_default_tools
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


def _confirm_bash(command: str) -> bool:
    return Confirm.ask(f"Run this command?\n  {escape(command)}\n", console=Console(), default=False)


def _ask(args) -> int:
    config = load_config()
    agent = Agent(make_client(config), config.model,
                  make_default_tools(Workspace(Path(args.root)),
                                     confirm_bash=_confirm_bash),
                  log=RequestLog.for_session(config.log_dir))
    result = agent.run(args.prompt)
    if result.stop_reason == "error":
        print(result.error, file=sys.stderr)
        return 1
    if result.stop_reason == "max_turns":
        print(f"Stopped after {result.turns} requests without a final answer.", file=sys.stderr)
        return 1
    print(result.final_text)
    return 0


def _log(args) -> int:
    path = Path(args.path) if args.path else latest_log(load_config().log_dir)
    if path is None or not path.is_file():
        print("No log found.")
        return 1
    console = Console()
    for entry in read_log(path):
        console.print(format_entry(entry), markup=False, highlight=False, soft_wrap=True)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent")
    sub = parser.add_subparsers(dest="command", required=True)
    smoke = sub.add_parser("smoke", help="check the model server and tool calling")
    smoke.set_defaults(func=_smoke)
    ask = sub.add_parser("ask", help="send one prompt and print the final answer")
    ask.add_argument("prompt")
    ask.add_argument("--root", default=".", help="directory the agent works in")
    ask.set_defaults(func=_ask)
    log = sub.add_parser("log", help="print a request log")
    log.add_argument("path", nargs="?", help="log file (default: the latest)")
    log.set_defaults(func=_log)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
