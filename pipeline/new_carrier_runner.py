"""Automation runner helpers for new-carrier validation."""
from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

import config

_VALID_SUITES = {"smoke", "sanity", "regression"}


@dataclass(frozen=True)
class CarrierSuiteRunResult:
    suite: str
    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    started_at: float
    finished_at: float
    html_report: str
    smart_report: str

    @property
    def duration_seconds(self) -> float:
        return max(0.0, self.finished_at - self.started_at)


def build_playwright_command(
    suite: str,
    *,
    project: str = "Google Chrome",
    headed: bool = True,
) -> list[str]:
    normalized = suite.strip().lower()
    if normalized not in _VALID_SUITES:
        raise ValueError(f"Unsupported suite: {suite}")
    command = [
        "npx",
        "playwright",
        "test",
        "--grep",
        f"@{normalized}",
        "--project",
        project,
    ]
    if headed:
        command.append("--headed")
    return command


def run_carrier_suite(
    *,
    env_path: str,
    suite: str,
    project: str = "Google Chrome",
    headed: bool = True,
    timeout_seconds: int = 7200,
    repo_path: str | None = None,
) -> CarrierSuiteRunResult:
    repo = Path(repo_path or config.MCSL_AUTOMATION_REPO_PATH).expanduser().resolve()
    if not repo.exists():
        raise FileNotFoundError(f"Automation repo not found: {repo}")

    env_file = Path(env_path).expanduser().resolve()
    if not env_file.exists():
        raise FileNotFoundError(f"Carrier env not found: {env_file}")

    command = build_playwright_command(suite, project=project, headed=headed)
    env = os.environ.copy()
    env.update({k: str(v) for k, v in dotenv_values(str(env_file)).items() if v is not None})

    started_at = time.time()
    completed = subprocess.run(
        command,
        cwd=str(repo),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    finished_at = time.time()

    return CarrierSuiteRunResult(
        suite=suite.strip().lower(),
        command=command,
        returncode=int(completed.returncode),
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
        started_at=started_at,
        finished_at=finished_at,
        html_report=str(repo / "my-html-report" / "index.html"),
        smart_report=str(repo / "smart-report" / "index.html"),
    )
