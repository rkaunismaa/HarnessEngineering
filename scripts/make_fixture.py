"""Make a fresh copy of a practice project for a lesson's live exercises.

    uv run python scripts/make_fixture.py NAME DEST

NAME is one of the projects below. DEST must not exist yet (or be an empty
directory): the agent edits its copy, never the originals in fixtures/.

  scratch   a tiny app (app/billing.py, app/util.py, app/main.py, calc.py, notes.txt)   lessons 2-6
  nums      nums.txt, nums2.txt, nums3.txt, nums4.txt: 300 numbered lines each        lessons 7-8
  six-bugs  utils.py with six buggy functions and test_utils.py with 8 tests          lesson 9
  pattern   8 modules of 25 functions; one function breaks the pattern                lesson 10
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
PATTERN_MODULES = 8
PATTERN_FUNCTIONS = 25
PATTERN_ODD_ONE = (5, 13)  # module_5.func_5_13 uses "-" where every other function uses "+"


def _nums(dest: Path) -> None:
    for name in ("nums.txt", "nums2.txt", "nums3.txt", "nums4.txt"):
        stem = name.removesuffix(".txt")
        lines = [f"{stem} line {i}: {i * i}" for i in range(1, 301)]
        (dest / name).write_text("\n".join(lines) + "\n")


def _pattern(dest: Path) -> None:
    for m in range(1, PATTERN_MODULES + 1):
        parts = [f'"""Module {m}: small arithmetic helpers."""\n']
        for k in range(1, PATTERN_FUNCTIONS + 1):
            op = "-" if (m, k) == PATTERN_ODD_ONE else "+"
            parts.append(
                f"\n\ndef func_{m}_{k}(a, b):\n"
                f'    """Combine a and b with weight {k}."""\n'
                f"    total = a {op} b * {k}\n"
                f"    return total\n"
            )
        if m == 3:
            parts.append(
                "\n\ndef compute_invoice_total(items):\n"
                '    """Sum the item amounts."""\n'
                "    return sum(items)\n"
            )
        (dest / f"module_{m}.py").write_text("".join(parts))


GENERATED = {"nums": _nums, "pattern": _pattern}
COPIED = ("scratch", "six-bugs")


def make_fixture(name: str, dest: Path) -> None:
    if dest.exists() and any(dest.iterdir()):
        raise SystemExit(f"{dest} already exists and is not empty; pick a new folder")
    if name in COPIED:
        shutil.copytree(FIXTURES / name, dest, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    elif name in GENERATED:
        dest.mkdir(parents=True, exist_ok=True)
        GENERATED[name](dest)
    else:
        raise SystemExit(f"unknown fixture {name!r}; choose from {', '.join(COPIED + tuple(GENERATED))}")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    make_fixture(argv[0], Path(argv[1]).expanduser())
    print(f"made {argv[0]} in {argv[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
