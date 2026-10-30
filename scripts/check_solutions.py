#!/usr/bin/env python3
"""Run lesson tests against reference solutions: solution S must pass every lesson L <= S.

Usage: python scripts/check_solutions.py [--upto NN]
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def numbered_dirs(base: Path) -> dict:
    if not base.is_dir():
        return {}
    return {int(p.name[:2]): p for p in sorted(base.iterdir())
            if p.is_dir() and p.name[:2].isdigit()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--upto", type=int, default=None, help="only check solutions up to NN")
    args = ap.parse_args(argv)

    lessons = numbered_dirs(ROOT / "lessons")
    solutions = numbered_dirs(ROOT / "solutions")
    if args.upto is not None:
        solutions = {n: p for n, p in solutions.items() if n <= args.upto}
    if not solutions:
        print("No solutions found under solutions/ - nothing to check.")
        return 0

    failures = 0
    grid = {}
    for s, sdir in solutions.items():
        for l, ldir in lessons.items():
            if l > s:
                continue
            tests = ldir / "tests"
            if not tests.is_dir():
                grid[(s, l)] = "missing"
                failures += 1
                print(f"lesson {l:02d}: no tests directory at {tests}", file=sys.stderr)
                continue
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", str(ldir), "--impl", str(sdir), "-q"],
                cwd=ROOT, capture_output=True, text=True)
            ok = proc.returncode == 0
            grid[(s, l)] = "pass" if ok else "FAIL"
            if not ok:
                failures += 1
                print(f"--- solution {s:02d} vs lesson {l:02d} failed ---\n{proc.stdout}{proc.stderr}")
        for l in range(s + 1):
            if l not in lessons:
                grid[(s, l)] = "missing"
                failures += 1
                print(f"lesson {l:02d}: directory missing under lessons/", file=sys.stderr)

    cols = sorted({l for _, l in grid})
    print("\nsolution \\ lesson  " + " ".join(f"{l:>4d}" for l in cols))
    for s in solutions:
        row = " ".join(f"{grid.get((s, l), ''):>4}" for l in cols)
        print(f"{s:>16d}   {row}")
    print("OK" if not failures else f"{failures} problem(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
