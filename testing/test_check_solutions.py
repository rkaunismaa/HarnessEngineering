import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_solutions.py"
spec = importlib.util.spec_from_file_location("check_solutions", SCRIPT)
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


def make(root, lessons, solutions):
    """lessons: {name: test source or None (no tests dir)}; solutions: [names]."""
    (root / "conftest.py").write_text((SCRIPT.parent.parent / "conftest.py").read_text())
    for name, src in lessons.items():
        d = root / "lessons" / name
        d.mkdir(parents=True)
        if src is not None:
            (d / "tests").mkdir()
            (d / "tests" / f"test_{name[:2]}.py").write_text(src)
    for name in solutions:
        (root / "solutions" / name / "agent").mkdir(parents=True)
        (root / "solutions" / name / "agent" / "__init__.py").write_text("")


def test_no_solutions_is_ok(tmp_path):
    assert check.main([], root=tmp_path) == 0


def test_lessons_without_tests_or_directory_are_not_failures(tmp_path, capsys):
    make(tmp_path, {"00-a": "def test_ok():\n    pass\n", "01-b": None}, ["00-a", "01-b", "02-c"])
    # 01-b has no tests dir; lesson 02 has no directory at all; 02-c solution has no lesson
    assert check.main([], root=tmp_path) == 0
    assert "none" in capsys.readouterr().out


def test_empty_tests_dir_exit_code_5_is_not_a_failure(tmp_path):
    make(tmp_path, {"00-a": "x = 1\n"}, ["00-a"])  # collects zero tests -> pytest exit 5
    assert check.main([], root=tmp_path) == 0


def test_real_failure_still_fails(tmp_path):
    make(tmp_path, {"00-a": "def test_bad():\n    assert False\n"}, ["00-a"])
    assert check.main([], root=tmp_path) == 1
