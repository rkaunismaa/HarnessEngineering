import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "make_fixture.py"
spec = importlib.util.spec_from_file_location("make_fixture", SCRIPT)
mf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mf)


def test_scratch_is_a_copy(tmp_path):
    mf.make_fixture("scratch", tmp_path / "s")
    assert (tmp_path / "s" / "app" / "billing.py").read_text().startswith("def compute_invoice_total")
    (tmp_path / "s" / "notes.txt").write_text("changed")
    assert (mf.FIXTURES / "scratch" / "notes.txt").read_text() == "alpha\nbeta\ngamma\n"


def test_nums_has_four_300_line_files(tmp_path):
    mf.make_fixture("nums", tmp_path / "n")
    files = sorted(p.name for p in (tmp_path / "n").iterdir())
    assert files == ["nums.txt", "nums2.txt", "nums3.txt", "nums4.txt"]
    lines = (tmp_path / "n" / "nums.txt").read_text().splitlines()
    assert len(lines) == 300 and lines[-1] == "nums line 300: 90000"


def test_pattern_has_one_odd_function(tmp_path):
    mf.make_fixture("pattern", tmp_path / "p")
    modules = sorted((tmp_path / "p").glob("module_*.py"))
    assert len(modules) == 8
    odd = [(m.name, line.strip()) for m in modules for line in m.read_text().splitlines()
           if line.strip().startswith("total = a -")]
    assert odd == [("module_5.py", "total = a - b * 13")]
    assert "def compute_invoice_total" in (tmp_path / "p" / "module_3.py").read_text()


def test_six_bugs_fails_six_of_eight_tests(tmp_path):
    mf.make_fixture("six-bugs", tmp_path / "b")
    out = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-c", "/dev/null",
                          "--rootdir", str(tmp_path / "b"), str(tmp_path / "b")],
                         cwd=tmp_path / "b", capture_output=True, text=True)
    assert "6 failed, 2 passed" in out.stdout


def test_refuses_non_empty_dest(tmp_path):
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "f").write_text("")
    with pytest.raises(SystemExit):
        mf.make_fixture("scratch", tmp_path / "x")


def test_unknown_name(tmp_path):
    with pytest.raises(SystemExit):
        mf.make_fixture("nope", tmp_path / "x")
