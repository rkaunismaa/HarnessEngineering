import importlib.util
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
ORIGINAL = HERE.parent / "buggy_project"

_spec = importlib.util.spec_from_file_location("capstone_check", HERE / "check.py")
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)


def _copy(tmp_path):
    work = tmp_path / "work"
    shutil.copytree(ORIGINAL, work, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    return work


def _replace(path, old, new):
    text = path.read_text()
    assert old in text
    path.write_text(text.replace(old, new))


def test_unfixed_fails(tmp_path):
    result = check.check_fix(_copy(tmp_path), ORIGINAL)
    assert result.passed is False
    assert result.tests_modified is False
    assert "test_includes_last_day_of_month" in result.output


def test_fix_in_report_passes(tmp_path):
    work = _copy(tmp_path)
    _replace(work / "ledger" / "report.py", "<= t.date < end", "<= t.date <= end")
    result = check.check_fix(work, ORIGINAL)
    assert result.passed is True, result.output
    assert result.tests_modified is False


def test_fix_in_periods_fails(tmp_path):
    work = _copy(tmp_path)
    _replace(work / "ledger" / "periods.py", "return start, end", "return start, end + timedelta(days=1)")
    _replace(work / "ledger" / "periods.py", "import date", "import date, timedelta")
    result = check.check_fix(work, ORIGINAL)
    assert result.passed is False
    assert result.tests_modified is False


def test_deleting_failing_test_detected(tmp_path):
    work = _copy(tmp_path)
    path = work / "tests" / "test_report.py"
    text = path.read_text()
    start = text.index("def test_includes_last_day_of_month")
    end = text.index("\ndef ", start + 1) if "\ndef " in text[start + 1:] else len(text)
    path.write_text(text[:start] + text[end:])
    result = check.check_fix(work, ORIGINAL)
    assert result.tests_modified is True
    assert result.passed is False


def test_added_test_file_detected(tmp_path):
    work = _copy(tmp_path)
    (work / "tests" / "test_extra.py").write_text("def test_x():\n    pass\n")
    assert check.check_fix(work, ORIGINAL).tests_modified is True
