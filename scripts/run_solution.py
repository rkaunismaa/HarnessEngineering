#!/usr/bin/env python3
"""Run a reference solution's CLI: python scripts/run_solution.py <solution-dir> <agent args...>

`python -m agent` from the repo root imports your own `agent/` package. This puts the
given solution first on sys.path instead, so you can run the reference agent.
"""
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help"}:
        print(__doc__)
        return 2
    solution = Path(argv[0]).resolve()
    if not (solution / "agent" / "__main__.py").is_file():
        print(f"{solution} has no agent/__main__.py", file=sys.stderr)
        return 2
    sys.path.insert(0, str(solution))
    from agent.__main__ import main as agent_main
    return agent_main(argv[1:])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
