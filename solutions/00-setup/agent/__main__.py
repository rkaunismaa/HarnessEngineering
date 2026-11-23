"""Command line entry point. Later lessons add subcommands (ask, log, chat, run, eval)."""
from __future__ import annotations

import argparse

import openai

from .client import make_client, smoke_test
from .config import load_config


def _smoke(args) -> int:
    config = load_config()
    try:
        result = smoke_test(make_client(config), config.model)
    except openai.APIConnectionError as e:  # server not running, wrong address, timeout
        print(f"FAIL: could not reach {config.base_url}: {e}")
        return 1
    except openai.APIStatusError as e:  # the server answered, with an error (e.g. unknown model)
        print(f"FAIL: {config.base_url} answered with an error: {e}")
        return 1
    except Exception as e:  # anything else: still one line, not a traceback
        print(f"FAIL: {type(e).__name__}: {e}")
        return 1
    print(f"{'OK' if result.ok else 'FAIL'}: {result.detail}")
    print(f"  tool: {result.tool_name}  arguments: {result.arguments}  "
          f"prompt tokens: {result.prompt_tokens}")
    return 0 if result.ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent")
    sub = parser.add_subparsers(dest="command", required=True)
    smoke = sub.add_parser("smoke", help="check the model server and tool calling")
    smoke.set_defaults(func=_smoke)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
