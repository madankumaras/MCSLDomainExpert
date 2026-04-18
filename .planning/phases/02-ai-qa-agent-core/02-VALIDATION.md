---
phase: 2
slug: ai-qa-agent-core
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-15
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | `tests/conftest.py` (exists from Phase 1) |
| **Quick run command** | `PYTHONPATH=. .venv/bin/pytest tests/test_agent.py -x -q` |
| **Full suite command** | `PYTHONPATH=. .venv/bin/pytest tests/ -q` |
| **Estimated runtime** | ~10 seconds (unit tests); browser tests skipped without live Shopify |

---

## Sampling Rate

- **After every task commit:** Run `PYTHONPATH=. .venv/bin/pytest tests/test_agent.py -x -q`
- **After every plan wave:** Run `PYTHONPATH=. .venv/bin/pytest tests/ -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 2-01-01 | 01 | 1 | AGENT-01 | unit | `pytest tests/test_agent.py::test_extract_scenarios -x -q` | ❌ W0 | ⬜ pending |
| 2-01-02 | 01 | 1 | AGENT-02 | unit | `pytest tests/test_agent.py::test_domain_expert_query -x -q` | ❌ W0 | ⬜ pending |
| 2-01-03 | 01 | 1 | AGENT-03 | unit | `pytest tests/test_agent.py::test_build_execution_plan -x -q` | ❌ W0 | ⬜ pending |
| 2-02-01 | 02 | 1 | AGENT-04 | unit | `pytest tests/test_agent.py::test_browser_loop_scaffold -x -q` | ❌ W0 | ⬜ pending |
| 2-02-02 | 02 | 1 | AGENT-05 | unit | `pytest tests/test_agent.py::test_ax_tree_capture -x -q` | ❌ W0 | ⬜ pending |
| 2-03-01 | 03 | 1 | AGENT-04 | unit | `pytest tests/test_agent.py::test_action_handlers -x -q` | ❌ W0 | ⬜ pending |
| 2-04-01 | 04 | 2 | CARRIER-01 | unit | `pytest tests/test_agent.py::test_carrier_detection -x -q` | ❌ W0 | ⬜ pending |
| 2-05-01 | 05 | 2 | CARRIER-03 | manual | Live Shopify browser run | N/A | ⬜ pending |
| 2-06-01 | 06 | 2 | LABEL-05 | unit | `pytest tests/test_agent.py::test_order_creator -x -q` | ❌ W0 | ⬜ pending |
| 2-07-01 | 07 | 2 | AGENT-06 | unit | `pytest tests/test_agent.py::test_verdict_reporting -x -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_agent.py` — stubs for all AGENT-01..07 and CARRIER-01 unit tests
- [ ] `agent/__init__.py` — package init
- [ ] `PYTHONPATH=. .venv/bin/pytest tests/test_agent.py -q` runs with all stubs skipped

*Wave 0 is the first task in Plan 02-01.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Carrier special service flows (dry ice, alcohol, HAL) | CARRIER-03..06 | Requires live Shopify + carrier account + physical label generation | Run agent against real AC text on mcsl-automation store |
| AX tree + screenshot capture at each step | AGENT-05 | Requires live Playwright browser | Visual inspection of screenshot PNG files |
| Stop button halts within one iteration | AGENT-07 | Requires threaded Streamlit UI | Manual click during live run |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
