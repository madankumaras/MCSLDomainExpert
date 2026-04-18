---
phase: 10-run-automation-domain-expert-chat
plan: 01
subsystem: pipeline
tags: [playwright, test-runner, subprocess, tdd]

# Dependency graph
requires:
  - phase: 09-automation-writing
    provides: mcsl-test-automation repo with spec files at MCSL_AUTOMATION_REPO_PATH
provides:
  - SpecResult dataclass (file, title, status, duration_ms, error)
  - TestRunResult dataclass (specs, passed, failed, skipped, duration_ms, error, branch)
  - enumerate_specs() — dict grouped by folder with .spec.ts paths
  - parse_playwright_json() — parse Playwright JSON reporter output
  - run_release_tests() — launch npx playwright test via subprocess, never raises
  - 4 unit tests for RUN-01 in tests/test_run_automation.py
affects: [10-run-automation-domain-expert-chat, pipeline_dashboard.py tab_run]

# Tech tracking
tech-stack:
  added: []
  used: [subprocess, pathlib, tempfile, json, dataclasses]

# Key files
key-files:
  created:
    - pipeline/test_runner.py
    - tests/test_run_automation.py
  modified: []

# Self-Check
## Self-Check: PASSED

- [x] tests/test_run_automation.py created with 4 RED stubs, then 4 GREEN
- [x] pipeline/test_runner.py created with SpecResult, TestRunResult, enumerate_specs, parse_playwright_json, run_release_tests
- [x] PLAYWRIGHT_JSON_OUTPUT_FILE tempfile approach used (avoids reporter conflicts)
- [x] run_release_tests() never raises — all errors go to TestRunResult.error
- [x] enumerate_specs() returns {} when repo path absent (no crash)
- [x] All 4 test_run01_* tests PASS
- [x] Full suite: 137 passed, 7 skipped, 0 failures
