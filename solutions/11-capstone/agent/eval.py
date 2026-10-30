"""Run the same task many times on fresh copies of a project and count how often it works."""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .client import make_client
from .config import Config
from .headless import RunReport, run_task
from .log import RequestLog


@dataclass
class RunOutcome:
    index: int
    report: RunReport
    check: Any  # the checker's result: needs ``passed``
    workdir: Path


@dataclass
class EvalReport:
    runs: list[RunOutcome]

    def _mean(self, values) -> float:
        values = list(values)
        return sum(values) / len(values) if values else 0.0

    @property
    def success_rate(self) -> float:
        return self._mean(1.0 if r.check.passed else 0.0 for r in self.runs)

    @property
    def mean_turns(self) -> float:
        return self._mean(r.report.turns for r in self.runs)

    @property
    def mean_prompt_tokens(self) -> float:
        return self._mean(r.report.prompt_tokens for r in self.runs)

    @property
    def mean_duration_s(self) -> float:
        return self._mean(r.report.duration_s for r in self.runs)


def run_eval(project: Path, task: str, n: int, config: Config, *,
             check: Callable[[Path, Path], Any], workdir_base: Path,
             client_factory: Callable[[], Any] | None = None,
             verify_command: str | None = None) -> EvalReport:
    """Run ``task`` ``n`` times, each in its own copy of ``project`` under ``workdir_base``,
    then ``check(workdir, project)``. ``verify_command`` is passed to every ``run_task``. ``project`` itself is never modified. Each run's request
    log is ``<log_dir>/<timestamp>-run-NN.jsonl``, so runs started in the same second differ."""
    project, workdir_base = Path(project).resolve(), Path(workdir_base)
    client_factory = client_factory or (lambda: make_client(config))
    stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    log_dir = Path(config.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    runs = []
    for i in range(n):
        workdir = workdir_base / f"run-{i:02d}"
        shutil.copytree(project, workdir,
                        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
        report = run_task(task, workdir, config, client=client_factory(),
                          verify_command=verify_command,
                          log=RequestLog(log_dir / f"{stamp}-run-{i:02d}.jsonl"))
        runs.append(RunOutcome(i, report, check(workdir, project), workdir))
    return EvalReport(runs)
