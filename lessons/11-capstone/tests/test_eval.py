import hashlib
import importlib.util
from pathlib import Path

import pytest

import agent.eval as evalmod
from agent.config import Config
from agent.eval import EvalReport, RunOutcome, run_eval
from agent.headless import RunReport
from testing.fake_model import FakeClient, call, reply

ROOT = Path(__file__).resolve().parents[3]


class Check:
    def __init__(self, passed):
        self.passed, self.tests_modified, self.output = passed, False, ""


def tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        h.update(str(p.relative_to(root)).encode())
        if p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()


@pytest.fixture
def project(tmp_path):
    p = tmp_path / "project"
    (p / "tests").mkdir(parents=True)
    (p / "tests" / "test_x.py").write_text("def test_x(): assert False\n")
    (p / "lib.py").write_text("X = 1\n")
    (p / "__pycache__").mkdir()
    (p / "__pycache__" / "lib.pyc").write_bytes(b"junk")
    return p


def factory():
    return FakeClient([
        reply(tool_calls=[call("bash", {"command": "echo 2 > lib.py"})]),
        reply(content="fixed"),
    ])


@pytest.fixture(autouse=True)
def no_sandbox_needed(monkeypatch):
    # these tests are about copying and counting; run_task need not require bwrap
    real = evalmod.run_task
    monkeypatch.setattr(evalmod, "run_task",
                        lambda *a, **k: real(*a, **{**k, "require_sandbox": False}))


def test_eval_copies_and_never_touches_project(tmp_path, project):
    before = tree_hash(project)
    base = tmp_path / "work"
    report = run_eval(project, "fix it", 2, Config(log_dir=tmp_path / "logs"),
                      check=lambda w, o: Check(True), workdir_base=base, client_factory=factory)
    assert tree_hash(project) == before
    assert (project / "lib.py").read_text() == "X = 1\n"
    assert sorted(p.name for p in base.iterdir()) == ["run-00", "run-01"]
    for run in report.runs:
        assert (run.workdir / "lib.py").read_text() == "2\n"  # the edit landed in the copy
        assert not (run.workdir / "__pycache__").exists()  # junk is not copied
    assert [r.index for r in report.runs] == [0, 1]
    assert all(isinstance(r, RunOutcome) and isinstance(r.report, RunReport) for r in report.runs)


def test_eval_success_rate(tmp_path, project):
    results = iter([True, False, True, False])
    report = run_eval(project, "fix it", 4, Config(log_dir=tmp_path / "logs"),
                      check=lambda w, o: Check(next(results)), workdir_base=tmp_path / "work",
                      client_factory=factory)
    assert isinstance(report, EvalReport)
    assert report.success_rate == 0.5
    assert report.mean_turns == 2
    assert report.mean_prompt_tokens == 200  # 100 per request, two requests
    assert report.mean_duration_s >= 0


def test_eval_check_receives_workdir_and_original(tmp_path, project):
    seen = []
    run_eval(project, "t", 1, Config(log_dir=tmp_path / "logs"),
             check=lambda w, o: seen.append((w, o)) or Check(True),
             workdir_base=tmp_path / "work", client_factory=factory)
    assert seen == [(tmp_path / "work" / "run-00", project)]


def test_each_run_gets_its_own_log(tmp_path, project):
    report = run_eval(project, "t", 3, Config(log_dir=tmp_path / "logs"),
                      check=lambda w, o: Check(True), workdir_base=tmp_path / "work",
                      client_factory=factory)
    paths = [r.report.log_path for r in report.runs]
    assert len(set(paths)) == 3 and all(p.is_file() for p in paths)


def test_empty_report():
    r = EvalReport(runs=[])
    assert r.success_rate == 0.0


@pytest.mark.live
@pytest.mark.sandbox
def test_live_capstone_once(tmp_path):
    spec = importlib.util.spec_from_file_location("checker", ROOT / "capstone/eval/check.py")
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    from agent.headless import DEFAULT_VERIFY_COMMAND, run_task
    project = ROOT / "capstone/buggy_project"
    work = tmp_path / "run"
    import shutil
    shutil.copytree(project, work, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    task = ("The test suite has a failing test. Find the cause and fix it in the source code. "
            "Do not modify the tests.")
    report = run_task(task, work, Config(log_dir=tmp_path / "logs"),
                      verify_command=DEFAULT_VERIFY_COMMAND)
    result = checker.check_fix(work, project)
    print(f"\nstop={report.stop_reason} turns={report.turns} prompt={report.prompt_tokens} "
          f"completion={report.completion_tokens} {report.duration_s:.0f}s "
          f"verified={report.verified} passed={result.passed}")
    assert report.stop_reason in {"done", "max_turns", "error"}
    assert isinstance(result.passed, bool)
