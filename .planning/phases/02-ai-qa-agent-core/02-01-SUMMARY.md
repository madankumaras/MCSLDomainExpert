---
phase: 02-ai-qa-agent-core
plan: "01"
subsystem: pipeline
tags: [agent, smart-ac-verifier, carrier-detection, tdd, scaffold]
dependency_graph:
  requires: [01-03]
  provides: [pipeline.smart_ac_verifier, tests.test_agent]
  affects: [02-02, 02-03, 02-04, 02-05, 02-06, 02-07]
tech_stack:
  added: []
  patterns: [five-stage-pipeline, carrier-injection, wave0-stubs, tdd-red-green]
key_files:
  created:
    - pipeline/smart_ac_verifier.py
    - tests/test_agent.py
  modified: []
decisions:
  - "Ported five-stage pipeline from FedexDomainExpert, adapted for MCSL multi-carrier (carrier detected from AC text, injected into _PLAN_PROMPT)"
  - "MCSL label flow uses app order grid (Shipping → order row → Generate Label), NOT Shopify More Actions — captured in _MCSL_WORKFLOW_GUIDE"
  - "App slug mcsl-qa confirmed in _build_url_map (not testing-553)"
  - "ScenarioResult gains carrier: str field for downstream carrier-aware reporting"
  - "Wave 0 stub pattern: all 9 tests start skipped, 4 activated in this plan (AGENT-01..03, CARRIER-01)"
  - "venv at /Users/madan/Documents/MCSLDomainExpert/.venv (parent repo), not worktree — pytest invoked with absolute path"
metrics:
  duration_minutes: 35
  completed_date: "2026-04-15"
  tasks_completed: 2
  files_created: 2
  files_modified: 0
---

# Phase 02 Plan 01: Agent Scaffold + Wave 0 Test Stubs Summary

**One-liner:** MCSL smart_ac_verifier.py scaffold with five-stage pipeline, CARRIER_CODES map, carrier-injection in planning prompt, _MCSL_WORKFLOW_GUIDE, and 9-stub test suite (4 activated).

## What Was Built

Created the foundational pipeline for the AI QA Agent. Every subsequent plan in phase 02 extends the scaffold built here.

### `pipeline/smart_ac_verifier.py`

**Constants and carrier layer:**
- `CARRIER_CODES` — 7-entry dict mapping carrier keywords → `(display name, internal code)`: FedEx C2, UPS C3, DHL C1, USPS C22, USPS Stamps C22, EasyPost C22, Canada Post C4
- `_detect_carrier(ac_text)` — iterates CARRIER_CODES in insertion order, returns first match from lowercased AC text
- `_build_url_map(app_base, store)` — constructs page URL map using `mcsl-qa` app slug (not `testing-553`)
- `_AUTH_JSON` — points to `/Users/madan/Documents/mcsl-test-automation/auth.json`
- `MAX_STEPS = 15`, `_ANTI_BOT_ARGS` — ported from FedexDomainExpert

**Workflow guide:** `_MCSL_WORKFLOW_GUIDE` — MCSL-specific navigation guide covering:
- Two product pages (AppProducts vs ShopifyProducts)
- All app page URLs with nav_clicks keys
- MCSL label generation flow: App sidebar → Shipping → order row → Generate Label (NOT Shopify More Actions)
- Label status locator, Rate Log, Bulk Labels, Carrier account config

**Prompts:** `_EXTRACT_PROMPT`, `_DOMAIN_EXPERT_PROMPT`, `_PLAN_PROMPT` — the plan prompt has a carrier injection block that formats `{carrier_name}` and `{carrier_code}` and references `_MCSL_WORKFLOW_GUIDE` instead of FedEx's `_APP_WORKFLOW_GUIDE`. Plan schema includes `carrier` field.

**Dataclasses:**
- `VerificationStep` / `StepResult` — action, description, target, success, screenshot_b64, network_calls
- `ScenarioResult` — adds `carrier: str = ""` vs FedEx original
- `VerificationReport` — passed/failed/qa_needed properties + `to_automation_context()`

**Core functions:**
- `_extract_scenarios(ac_text, claude)` — invokes Claude with `_EXTRACT_PROMPT`, parses JSON list, fallback line-by-line BDD parser
- `_ask_domain_expert(scenario, card_name, claude)` — queries `mcsl_knowledge` (kb_articles, wiki, sheets via `search_filtered`), queries `mcsl_code_knowledge` (storepepsaas_server/client via `search_code`), synthesises ≤200-word answer
- `_code_context(scenario, card_name)` — queries automation + storepepsaas_server + storepepsaas_client
- `_plan_scenario(scenario, app_url, code_ctx, expert_insight, claude)` — calls `_detect_carrier()`, injects carrier into `_PLAN_PROMPT`, parses JSON plan, ensures `carrier` key present
- `_parse_json(raw)` — handles markdown fences, prefix text, `{...}` and `[...]` extraction (ported verbatim)

**Stubs for plan 02-02:** `_ax_tree`, `_screenshot`, `_network`, `_do_action`, `_decide_next`, `_verify_scenario` — all return safe defaults with informative messages.

**Entry point:** `verify_ac(ac_text, card_name, ...)` — auto-builds app URL from `config.STORE` + `mcsl-qa` slug, initialises `ChatAnthropic`, runs `_extract_scenarios` loop with stop_flag support, calls stub `_verify_scenario`, returns `VerificationReport`.

### `tests/test_agent.py`

9 test functions:

| Test | Req | Status |
|------|-----|--------|
| test_extract_scenarios | AGENT-01 | PASS (unskipped) |
| test_domain_expert_query | AGENT-02 | PASS (unskipped) |
| test_build_execution_plan | AGENT-03 | PASS (unskipped) |
| test_browser_loop_scaffold | AGENT-04 | SKIPPED (02-02) |
| test_ax_tree_capture | AGENT-05 | SKIPPED (02-02) |
| test_action_handlers | AGENT-06 | SKIPPED (02-02) |
| test_carrier_detection | CARRIER-01 | PASS (unskipped) |
| test_order_creator | AGENT-01 | SKIPPED (02-04) |
| test_verdict_reporting | AGENT-06 | SKIPPED (02-02) |

**Result:** 4 passed, 5 skipped, 0 failed.

## Verification

```
PYTHONPATH=. /Users/madan/Documents/MCSLDomainExpert/.venv/bin/pytest tests/test_agent.py
4 passed, 5 skipped, 1 warning in 0.87s
```

```python
from pipeline.smart_ac_verifier import verify_ac, _detect_carrier, CARRIER_CODES  # → OK
_detect_carrier("FedEx account")   # → ("FedEx", "C2")
_detect_carrier("UPS label")       # → ("UPS", "C3")
_detect_carrier("unknown")         # → ("", "")
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] venv location is parent repo (.../MCSLDomainExpert/.venv), not worktree**
- **Found during:** Task 0 verification
- **Issue:** The plan says `PYTHONPATH=. .venv/bin/pytest` but the worktree has no `.venv/` — the venv lives at `/Users/madan/Documents/MCSLDomainExpert/.venv/`
- **Fix:** All verification commands use absolute venv path `/Users/madan/Documents/MCSLDomainExpert/.venv/bin/pytest`
- **Files modified:** None (runtime command only)
- **Commit:** Implicit in test runs

**2. [Rule 2 - Enhancement] test_carrier_detection expanded with DHL assertion**
- **Found during:** Task 1 implementation
- **Issue:** Plan only specified FedEx + UPS assertions; CARRIER_CODES adds DHL, USPS, Canada Post
- **Fix:** Added `assert _detect_carrier("DHL shipment") == ("DHL", "C1")` to carrier detection test
- **Files modified:** tests/test_agent.py

## Commits

| Task | Commit | Message |
|------|--------|---------|
| Task 0 (Wave 0 stubs) | `29090a5` | test(02-01): add Wave 0 stubs for 9 agent test functions |
| Task 1 (scaffold + unskip) | `2da680b` | feat(02-01): add smart_ac_verifier.py scaffold + unskip 4 agent tests |
