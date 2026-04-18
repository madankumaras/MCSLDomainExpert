"""
RUN-01 unit tests — pipeline/test_runner.py
Wave 0: Tests are written before implementation (RED phase).
All 4 tests must fail with ImportError until pipeline/test_runner.py exists.
"""
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pipeline.test_runner import (
    SpecResult,
    TestRunResult,
    enumerate_specs,
    parse_playwright_json,
    run_release_tests,
)


def test_run01_enumerate_specs(tmp_path):
    """enumerate_specs groups spec files by top-level subfolder under tests/."""
    # Create a fake repo structure with two spec files in different folders
    (tmp_path / "tests" / "orderGrid").mkdir(parents=True)
    (tmp_path / "tests" / "orderSummary").mkdir(parents=True)
    (tmp_path / "tests" / "orderGrid" / "foo.spec.ts").write_text("// spec")
    (tmp_path / "tests" / "orderSummary" / "bar.spec.ts").write_text("// spec")
    # Non-spec file should be excluded
    (tmp_path / "tests" / "orderGrid" / "helper.ts").write_text("// helper")

    result = enumerate_specs(str(tmp_path))

    assert result == {
        "orderGrid": ["tests/orderGrid/foo.spec.ts"],
        "orderSummary": ["tests/orderSummary/bar.spec.ts"],
    }


def test_run01_test_run_result_dataclass():
    """TestRunResult and SpecResult dataclasses have correct typed fields with defaults."""
    # TestRunResult defaults
    run_result = TestRunResult()
    assert run_result.total == 0
    assert run_result.passed == 0
    assert run_result.failed == 0
    assert run_result.skipped == 0
    assert run_result.duration_ms == 0
    assert run_result.specs == []
    assert run_result.error == ""

    # SpecResult with explicit fields
    spec = SpecResult(file="f", title="t", status="passed", duration_ms=100)
    assert spec.file == "f"
    assert spec.title == "t"
    assert spec.status == "passed"
    assert spec.duration_ms == 100


def test_run01_parse_playwright_json():
    """parse_playwright_json extracts per-test status and duration from JSON fixture."""
    fixture = {
        "suites": [
            {
                "title": "my suite",
                "file": "tests/orderGrid/foo.spec.ts",
                "specs": [
                    {
                        "title": "my test",
                        "tests": [
                            {
                                "results": [
                                    {"status": "passed", "duration": 1500}
                                ]
                            }
                        ],
                    }
                ],
                "suites": [],
            }
        ],
        "stats": {"expected": 1, "unexpected": 0, "duration": 1500},
    }

    result = parse_playwright_json(fixture)

    assert len(result) == 1
    assert result[0]["status"] == "passed"
    assert result[0]["duration_ms"] == 1500


def test_run01_run_release_tests_calls_subprocess():
    """run_release_tests calls npx playwright test with the correct env var and returns TestRunResult."""
    fake_json = json.dumps({"suites": [], "stats": {"duration": 1000}})

    mock_proc = MagicMock()
    mock_proc.returncode = 0

    with patch("subprocess.run", return_value=mock_proc) as mock_run, \
         patch("tempfile.NamedTemporaryFile") as mock_tmp, \
         patch("pathlib.Path.read_text", return_value=fake_json), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("os.unlink"):

        # Set up tempfile mock to return a predictable path
        mock_tmp_file = MagicMock()
        mock_tmp_file.__enter__ = MagicMock(return_value=mock_tmp_file)
        mock_tmp_file.__exit__ = MagicMock(return_value=False)
        mock_tmp_file.name = "/tmp/fake_output.json"
        mock_tmp.return_value = mock_tmp_file

        result = run_release_tests("/fake", ["tests/x.spec.ts"])

    assert isinstance(result, TestRunResult)
    assert result.error == ""
    # Verify subprocess was called
    mock_run.assert_called_once()
    call_args = mock_run.call_args
    cmd = call_args[0][0]
    assert "npx" in cmd
    assert "playwright" in cmd
    assert "test" in cmd
    assert "--reporter=json" in cmd
