"""
pipeline/test_runner.py

Playwright spec runner and result parser for the Run Automation tab.

Provides:
  - SpecResult        — dataclass for a single test result
  - TestRunResult     — dataclass aggregating a full run
  - enumerate_specs   — list .spec.ts files grouped by top-level subfolder
  - parse_playwright_json — parse --reporter=json output into list[dict]
  - run_release_tests — run npx playwright test, never raises
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SpecResult:
    """Result for a single test within a spec file."""
    file: str
    title: str
    status: str  # "passed" | "failed" | "timedOut" | "skipped"
    duration_ms: int


@dataclass
class TestRunResult:
    """Aggregated result for a full playwright test run."""
    specs: list[SpecResult] = field(default_factory=list)
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    duration_ms: int = 0
    error: str = ""


# ---------------------------------------------------------------------------
# Spec enumeration
# ---------------------------------------------------------------------------

def enumerate_specs(repo_path: str) -> dict[str, list[str]]:
    """Walk <repo_path>/tests/ and return spec files grouped by top-level subfolder.

    Returns:
        dict mapping folder name -> sorted list of relative spec paths
        (relative to repo_path, using forward slashes).
        Returns {} if the tests/ directory does not exist.
    """
    root = Path(repo_path) / "tests"
    if not root.exists():
        return {}

    groups: dict[str, list[str]] = {}
    for spec in sorted(root.rglob("*.spec.ts")):
        rel = str(spec.relative_to(Path(repo_path)))
        # Group by the first component under tests/
        parts = spec.relative_to(root).parts
        folder = parts[0] if len(parts) > 1 else "root"
        groups.setdefault(folder, []).append(rel)

    # Sort folder names and entries within each folder
    return {k: sorted(v) for k, v in sorted(groups.items())}


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------

def _parse_suite(suite: dict, results: list) -> None:
    """Recursively walk a Playwright JSON reporter suite and append results."""
    file_name = suite.get("file", suite.get("title", ""))
    for spec in suite.get("specs", []):
        for test in spec.get("tests", []):
            for r in test.get("results", [])[:1]:  # take first result only
                results.append(
                    {
                        "file": file_name,
                        "title": spec.get("title", ""),
                        "status": r.get("status", "unknown"),
                        "duration_ms": r.get("duration", 0),
                    }
                )
    # Recurse into nested suites
    for child in suite.get("suites", []):
        _parse_suite(child, results)


def parse_playwright_json(data: dict) -> list[dict]:
    """Parse Playwright --reporter=json output into a flat list of result dicts.

    Each entry has: file, title, status, duration_ms.
    """
    results: list[dict] = []
    for suite in data.get("suites", []):
        _parse_suite(suite, results)
    return results


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def run_release_tests(
    repo_path: str,
    spec_files: list[str],
    project: str = "Google Chrome",
) -> TestRunResult:
    """Run selected spec files via npx playwright test and return a TestRunResult.

    Uses PLAYWRIGHT_JSON_OUTPUT_FILE env var to capture JSON output to a temp
    file (more reliable than stdout capture when multiple reporters are configured).

    Never raises — all exceptions are captured into TestRunResult.error.
    """
    import subprocess  # noqa: PLC0415 — inside function for testability

    json_path: str | None = None
    try:
        # Create a temp file to receive the JSON reporter output
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            json_path = f.name

        env = {**os.environ, "PLAYWRIGHT_JSON_OUTPUT_FILE": json_path}
        cmd = [
            "npx",
            "playwright",
            "test",
            "--reporter=json",
            "--project",
            project,
            *spec_files,
        ]

        subprocess.run(
            cmd,
            cwd=repo_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
        )

        # Parse output
        p = Path(json_path)
        if p.exists():
            raw_text = p.read_text()
            try:
                data = json.loads(raw_text)
            except json.JSONDecodeError:
                data = {}
        else:
            data = {}

        raw_results = parse_playwright_json(data)

        # Build typed SpecResult list
        spec_results = [
            SpecResult(
                file=r["file"],
                title=r["title"],
                status=r["status"],
                duration_ms=r["duration_ms"],
            )
            for r in raw_results
        ]

        # Aggregate counts
        passed = sum(1 for s in spec_results if s.status == "passed")
        failed = sum(1 for s in spec_results if s.status in ("failed", "timedOut"))
        skipped = sum(1 for s in spec_results if s.status == "skipped")
        total_duration = sum(s.duration_ms for s in spec_results)

        # Fall back to stats.duration if no individual durations
        if total_duration == 0:
            total_duration = data.get("stats", {}).get("duration", 0)

        return TestRunResult(
            specs=spec_results,
            total=len(spec_results),
            passed=passed,
            failed=failed,
            skipped=skipped,
            duration_ms=total_duration,
            error="",
        )

    except Exception as e:  # noqa: BLE001
        return TestRunResult(error=str(e))

    finally:
        # Clean up temp file (ignore errors if it doesn't exist)
        if json_path is not None:
            try:
                os.unlink(json_path)
            except OSError:
                pass
