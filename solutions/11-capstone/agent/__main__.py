"""Command line entry point. Later lessons add subcommands (ask, log, chat, run, eval)."""
from __future__ import annotations

import argparse
import importlib.util
import shutil
import sys
import tempfile
from pathlib import Path

from rich.console import Console
from rich.markup import escape
from rich.prompt import Prompt

from .client import make_client, smoke_test
from .cli import ConsoleEvents, chat_loop
from .config import load_config
from .context import ContextManager
from .eval import run_eval
from .headless import (DEFAULT_TASK, DEFAULT_VERIFY_COMMAND, SandboxUnavailable, run_task)
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
    client = make_client(config)
    log = RequestLog.for_session(config.log_dir)
    permissions = PermissionPolicy(allow=args.allow)
    tools = make_default_tools(ws, client=client, model=config.model, log=log,
                               context_window=config.context_window, permissions=permissions)
    if getattr(args, "verify", None):
        agent_kwargs["verify"] = _make_verify(ws, args.verify)
    return Agent(client, config.model, tools,
                 system=build_system_prompt(ws, tools), log=log,
                 permissions=permissions, approver=_approve,
                 workspace=ws, context=ContextManager(config.context_window),
                 **agent_kwargs, sampling=config.sampling())


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


def _run(args) -> int:
    config = load_config()
    if args.unsafe_no_sandbox:
        print("Warning: --unsafe-no-sandbox: bash commands run directly on this machine, "
              "with every tool call allowed.", file=sys.stderr)
    root = Path(args.root)
    if not root.is_dir():
        print(f"No such directory: {root}", file=sys.stderr)
        return 1
    # Every tool call is allowed, so work on a copy: the original stays as it was, and you
    # can diff the copy against it afterwards.
    copy = Path(tempfile.mkdtemp(prefix="harness-run-"))
    shutil.copytree(root, copy, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".git"))
    print(f"Working on a copy of {root}: {copy}", file=sys.stderr)
    try:
        report = run_task(args.task, copy, config,
                          require_sandbox=not args.unsafe_no_sandbox,
                          verify_command=args.verify, max_turns=args.max_turns)
    except SandboxUnavailable as e:
        shutil.rmtree(copy, ignore_errors=True)
        print(f"{e}\nRefusing to run without a sandbox. Pass --unsafe-no-sandbox to run "
              f"anyway.", file=sys.stderr)
        return 1
    print(report.final_text)
    print(f"[{report.stop_reason}] turns={report.turns} prompt_tokens={report.prompt_tokens} "
          f"completion_tokens={report.completion_tokens} seconds={report.duration_s:.0f} "
          f"verified={report.verified} log={report.log_path}", file=sys.stderr)
    print(f"The result is in {copy} (compare: diff -r {root} {copy})", file=sys.stderr)
    return 0 if report.stop_reason == "done" else 1


def _load_checker(path: Path):
    spec = importlib.util.spec_from_file_location("harness_checker", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.check_fix


def _eval(args) -> int:
    config = load_config()
    project, checker_path = Path(args.project), Path(args.checker)
    for what, p in (("project", project), ("checker", checker_path)):
        if not p.exists():
            print(f"No such {what}: {p}", file=sys.stderr)
            return 1
    if args.workdir_base:
        taken = [f"run-{i:02d}" for i in range(args.n)
                 if (Path(args.workdir_base) / f"run-{i:02d}").exists()]
        if taken:
            print(f"{args.workdir_base} already has {', '.join(taken)} from an earlier eval. "
                  f"Give a new --workdir-base, or leave it out to use a fresh temp dir.",
                  file=sys.stderr)
            return 1
    if not sandbox_available():
        print("The eval needs bubblewrap (bwrap) so that runs cannot touch each other or your "
              "files, and it is not usable here.", file=sys.stderr)
        return 1
    check_fix = _load_checker(checker_path)
    base = Path(args.workdir_base) if args.workdir_base \
        else Path(tempfile.mkdtemp(prefix="harness-eval-"))
    print(f"Working copies: {base}")
    report = run_eval(project, args.task, args.n, config, check=check_fix, workdir_base=base,
                      verify_command=args.verify)
    console = Console()
    header = f"{'run':>3}  {'result':<8} {'turns':>5} {'tokens':>8} {'secs':>5}  log"
    console.print(header, markup=False, highlight=False)
    for r in report.runs:
        rep = r.report
        result = "pass" if r.check.passed else ("tests!" if r.check.tests_modified else "fail")
        if rep.stop_reason != "done":
            result += f" ({rep.stop_reason})"
        console.print(f"{r.index:>3}  {result:<8} {rep.turns:>5} "
                      f"{rep.prompt_tokens + rep.completion_tokens:>8} "
                      f"{rep.duration_s:>5.0f}  {rep.log_path}", markup=False, highlight=False,
                      soft_wrap=True)
    passed = sum(1 for r in report.runs if r.check.passed)
    print(f"\nsuccess: {passed}/{len(report.runs)} ({report.success_rate:.0%})  "
          f"mean turns: {report.mean_turns:.1f}  "
          f"mean prompt tokens: {report.mean_prompt_tokens:.0f}  "
          f"mean seconds: {report.mean_duration_s:.0f}")
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
    run = sub.add_parser("run", help="run one task without asking questions (sandboxed)")
    run.add_argument("task")
    run.add_argument("--root", required=True,
                     help="project to work on; the agent edits a copy in a new temp dir")
    run.add_argument("--verify", metavar="COMMAND", default=DEFAULT_VERIFY_COMMAND,
                     help="check to run when the model says it is done (default: pytest -q)")
    run.add_argument("--max-turns", type=int, default=50)
    run.add_argument("--unsafe-no-sandbox", action="store_true",
                     help="run without bubblewrap, with every tool call allowed (dangerous)")
    run.set_defaults(func=_run)
    ev = sub.add_parser("eval", help="run a task many times on copies of a project; count successes")
    ev.add_argument("--project", default="capstone/buggy_project")
    ev.add_argument("--checker", default="capstone/eval/check.py",
                    help="file defining check_fix(workdir, original) (default: %(default)s)")
    ev.add_argument("--n", type=int, default=10)
    ev.add_argument("--task", default=DEFAULT_TASK)
    ev.add_argument("--verify", metavar="COMMAND", default=DEFAULT_VERIFY_COMMAND)
    ev.add_argument("--workdir-base", help="where to put the copies (default: a new temp dir)")
    ev.set_defaults(func=_eval)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
