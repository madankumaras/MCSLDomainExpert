---
phase: 02-ai-qa-agent-core
verified: 2026-04-16T05:57:17Z
status: passed
score: 13/13 must-haves verified
re_verification: false
human_verification:
  - test: "Run verify_ac() against live MCSL Shopify store with a real FedEx dry ice AC text"
    expected: "Agent navigates to App Products, enables Is Dry Ice Needed, generates label, returns pass/partial/qa_needed verdict with screenshot"
    why_human: "Requires live Playwright browser, real Shopify session (auth.json), and live app connectivity — cannot be verified programmatically"
  - test: "Run verify_ac() against live store with a UPS COD AC text"
    expected: "Agent opens SideDock, enables Cash on Delivery, fills amount, generates label with UPS carrier"
    why_human: "End-to-end browser flow — SideDock interaction and COD modal cannot be mocked"
  - test: "Click Stop button mid-run while agent is between steps in _verify_scenario loop"
    expected: "Agent halts within one loop iteration, returning status=partial with finding='Stopped by user'"
    why_human: "Threading and timing behaviour requires a live run — confirmed in unit tests but real-time stop UI wiring is Phase 4"
---

# Phase 2: AI QA Agent Core — Verification Report

**Phase Goal:** Build the AI QA agent core — a fully functional agentic browser loop that can verify acceptance criteria for multi-carrier shipping label generation on the MCSL Shopify app.
**Verified:** 2026-04-16T05:57:17Z
**Status:** PASSED
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|---------|
| 1 | Given raw AC text, the agent extracts a JSON array of testable scenarios without error | VERIFIED | `_extract_scenarios()` implemented at line 634; `test_extract_scenarios` passes with mock Claude returning `'["Scenario A", "Scenario B"]'` |
| 2 | For each scenario, the agent queries the domain expert and receives an insight string under 200 words | VERIFIED | `_ask_domain_expert()` implemented at line 693; queries `mcsl_knowledge` and `mcsl_code_knowledge` via `search_filtered`; response capped at 1200 chars; `test_domain_expert_query` passes |
| 3 | The agent produces a JSON execution plan with keys: nav_clicks, look_for, api_to_watch, order_action, carrier | VERIFIED | `_plan_scenario()` implemented at line 777; `_PLAN_PROMPT` at line 557 requires all five keys; `test_build_execution_plan` asserts all five keys present |
| 4 | Carrier name detected from AC text is injected into the planning prompt | VERIFIED | `_plan_scenario()` calls `_detect_carrier(scenario)` at line 790 and injects result into `_PLAN_PROMPT` via `carrier_name` and `carrier_code` template vars |
| 5 | The agentic browser loop runs up to 15 steps with AX tree + screenshot + network capture per step | VERIFIED | `MAX_STEPS=15`; `_verify_scenario()` loop at line 1351 calls `_ax_tree`, `_screenshot`, `_network` every iteration; `test_browser_loop_scaffold` and `test_ax_tree_capture` pass |
| 6 | Agent produces a pass/fail/partial/qa_needed verdict per scenario with finding text and screenshot evidence | VERIFIED | `_verify_scenario()` sets `result.status`, `result.finding`, `result.evidence_screenshot` on verify/qa_needed/timeout; `VerificationReport.to_dict()` serialises all fields; `test_verdict_reporting` and `test_full_report_integration` pass |
| 7 | Stop flag is checked at each loop iteration — triggering it halts the agent within one iteration | VERIFIED | `stop_flag` checked at line 1352 inside `_verify_scenario` loop AND at line 1480 in `verify_ac()` before each scenario; `test_browser_loop_scaffold` case 2 and `test_verdict_reporting` Part 2 both verify stop behaviour |
| 8 | Agent detects carrier and injects it into plan: FedEx AC → carrier=FedEx, UPS AC → carrier=UPS, unknown → carrier='' | VERIFIED | `_detect_carrier()` at line 69 with `CARRIER_CODES` dict covering 7 carriers; `test_carrier_detection` asserts all 8 cases including empty fallback |
| 9 | Agent handles carrier account configuration flow (App Settings → Carriers → Add/Edit) | VERIFIED | `_get_carrier_config_steps()` at line 95; CARRIER-02 section in `_MCSL_WORKFLOW_GUIDE` at line 373; `_plan_scenario()` detects config scenarios via `_CARRIER_CONFIG_KEYWORDS` and injects steps |
| 10 | Agent handles FedEx special service flows (signature, dry ice, alcohol, battery, HAL, insurance) | VERIFIED | `_get_preconditions()` FedEx branch at lines 170–218 covers all 6 service types; steps reference MCSL label flow (Account Card → Generate Label), not Shopify More Actions |
| 11 | Agent handles UPS special service flows (signature, insurance, COD) | VERIFIED | `_get_preconditions()` UPS branch at lines 219–244 covers signature, insurance, COD |
| 12 | Agent handles USPS special service flows (signature, registered mail) | VERIFIED | `_get_preconditions()` USPS branch at lines 246–261 handles both `carrier_lower in ("usps", "usps stamps")` |
| 13 | Agent handles DHL special service flows (insurance, signature, international with commercial invoice) | VERIFIED | `_get_preconditions()` DHL branch at lines 263–286; international branch includes "Verify commercial invoice is generated after LABEL CREATED status" at line 280 |

**Score: 13/13 truths verified**

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `pipeline/smart_ac_verifier.py` | Five-stage pipeline: `_extract_scenarios`, `_ask_domain_expert`, `_plan_scenario`, `_verify_scenario`, `verify_ac`; all MCSL constants | VERIFIED | 1526 lines; all five pipeline functions implemented; `_EXTRACT_PROMPT`, `_PLAN_PROMPT`, `_MCSL_WORKFLOW_GUIDE`, `CARRIER_CODES`, `MAX_STEPS=15`, `_ANTI_BOT_ARGS`, `VerificationReport.to_dict()` all present |
| `pipeline/order_creator.py` | `create_order`, `create_bulk_orders`, `_read_carrier_env`, `_default_address` | VERIFIED | 165 lines; all four functions implemented; reads `SIMPLE_PRODUCTS_JSON` from carrier-env files via `dotenv_values`; calls Shopify REST `POST /orders.json` with `X-Shopify-Access-Token` |
| `tests/test_agent.py` | 9+ test stubs covering AGENT-01..07 and CARRIER-01 | VERIFIED | 14 tests; all pass (14 passed, 0 skipped, 0 failed in 1.34s); covers all originally planned stubs plus additional integration tests |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `_verify_scenario` | `_ax_tree` | called every loop iteration | WIRED | Line 1357: `ax = _ax_tree(active_page)` |
| `_ax_tree` | `iframe[name="app-iframe"]` | frame URL filter: shopify/pluginhive/apps | WIRED | Lines 895–909: frame filter checks `"shopify" not in frame_url and "pluginhive" not in frame_url and "apps" not in frame_url` |
| `_ask_domain_expert` | `rag/vectorstore.py` | `search_filtered` with source_type | WIRED | Lines 710–723: `from rag.vectorstore import search_filtered`; fallback to `search` at line 726 |
| `_code_context` / `_ask_domain_expert` | `rag/code_indexer.py` | `search_code` | WIRED | Lines 655, 737: `from rag.code_indexer import search_code` |
| `smart_ac_verifier.py` | `config.py` | `import config` at module level | WIRED | Line 39: `import config`; used for `config.STORE`, `config.ANTHROPIC_API_KEY`, `config.CLAUDE_SONNET_MODEL`, `config.MCSL_AUTOMATION_REPO_PATH` |
| `_plan_scenario` | `_detect_carrier` | carrier injected before plan prompt | WIRED | Line 790: `carrier_name, carrier_code = _detect_carrier(scenario)` |
| `_plan_scenario` | `_get_preconditions` | special service detection → precondition injection | WIRED | Lines 814–826: `_get_preconditions(carrier_name, scenario, app_base)` called when `_SPECIAL_SERVICE_KEYWORDS` match found |
| `verify_ac` | `_verify_scenario` | called for each scenario; result appended | WIRED | Lines 1494–1516: `sv = _verify_scenario(...)` then `report.scenarios.append(sv)` |
| `verify_ac` | `_extract_scenarios` | scenarios extracted before browser loop | WIRED | Line 1457: `scenarios = _extract_scenarios(ac_text, claude)` |
| `_verify_scenario` | `order_creator.create_order` | `order_action='create_new'` triggers creation | WIRED | Lines 1329–1348: lazy import `from pipeline.order_creator import create_order, create_bulk_orders, get_carrier_env_for_code`; carrier_code required |
| `order_creator._read_carrier_env` | carrier-envs dir | `dotenv_values()` reads per-carrier .env file | WIRED | Line 43: `return dict(dotenv_values(str(path)))`; `_CARRIER_ENV_DIR` set from `config.MCSL_AUTOMATION_REPO_PATH` |
| `_decide_next` | `langchain_anthropic.ChatAnthropic` | HumanMessage with text + base64 image | WIRED | Lines 1235–1241: `content` list with `{"type": "text", ...}` and `{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{scr}"}}` |

---

### Requirements Coverage

| Requirement | Source Plan(s) | Description | Status | Evidence |
|-------------|---------------|-------------|--------|---------|
| AGENT-01 | 02-01 | Agent extracts testable scenarios from AC text as JSON array | SATISFIED | `_extract_scenarios()` + `test_extract_scenarios` passes |
| AGENT-02 | 02-01 | Agent queries Domain Expert RAG for expected behaviour | SATISFIED | `_ask_domain_expert()` queries `mcsl_knowledge` + `mcsl_code_knowledge`; `test_domain_expert_query` passes |
| AGENT-03 | 02-01 | Agent generates JSON execution plan with all required keys | SATISFIED | `_plan_scenario()` + `_PLAN_PROMPT`; `test_build_execution_plan` asserts all 5 keys |
| AGENT-04 | 02-02, 02-03, 02-06 | Agent runs agentic browser loop (up to 15 steps) with all 11 action types | SATISFIED | `_verify_scenario()` 15-step loop + `_do_action()` handling all 11 types + order_action wiring; `test_browser_loop_scaffold`, `test_action_handlers`, `test_order_creator`, `test_verify_scenario_order_wiring` all pass |
| AGENT-05 | 02-02 | Agent captures AX tree (depth 6, 250 lines) + screenshot + filtered network calls per step | SATISFIED | `_ax_tree()` with dual-frame capture, `_screenshot()`, `_network()`; `test_ax_tree_capture` passes |
| AGENT-06 | 02-07 | Agent reports pass/fail/partial/qa_needed verdict per scenario with finding and screenshot | SATISFIED | `ScenarioResult` with status/finding/evidence_screenshot; `VerificationReport.to_dict()`; `test_verdict_reporting` and `test_full_report_integration` pass |
| AGENT-07 | 02-07 | Agent supports stop flag checked at each loop iteration | SATISFIED | `stop_flag` checked at line 1352 (inner loop) and line 1480 (outer loop); both test cases verify halt behaviour |
| CARRIER-01 | 02-01, 02-04 | Carrier name injected into planning prompt from AC text detection | SATISFIED | `_detect_carrier()` + `_plan_scenario()` carrier injection; `test_carrier_detection` and `test_plan_scenario_injects_carrier` pass |
| CARRIER-02 | 02-04 | Agent handles carrier account configuration flow (App Settings → Carriers → Add/Edit) | SATISFIED | `_get_carrier_config_steps()` + CARRIER-02 section in `_MCSL_WORKFLOW_GUIDE`; `_plan_scenario()` detects config scenarios via `_CARRIER_CONFIG_KEYWORDS` |
| CARRIER-03 | 02-05 | Agent handles FedEx-specific flows (signature, dry ice, alcohol, battery, HAL, insurance) | SATISFIED | `_get_preconditions()` FedEx branch covers all 6 special services; steps use MCSL label flow, no Shopify More Actions references in steps |
| CARRIER-04 | 02-05 | Agent handles UPS-specific flows (signature, insurance, COD) | SATISFIED | `_get_preconditions()` UPS branch at lines 219–244 |
| CARRIER-05 | 02-05 | Agent handles USPS-specific flows (signature, registered mail) | SATISFIED | `_get_preconditions()` USPS branch; handles both "usps" and "usps stamps" via `carrier_lower in (...)` check |
| CARRIER-06 | 02-05 | Agent handles DHL-specific flows (insurance, signature, international) | SATISFIED | `_get_preconditions()` DHL branch; international step explicitly verifies commercial invoice post-LABEL CREATED |

**All 13 requirements for Phase 2 are SATISFIED.**

**Note on orphaned requirement coverage:** REQUIREMENTS.md also shows AGENT-04 partially addressing LABEL-05 (order creation pulled forward from Phase 3). This is intentional — documented in 02-06-PLAN.md frontmatter comment. LABEL-05 remains formally owned by Phase 3.

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `pipeline/smart_ac_verifier.py` | 1062–1074 | `download_zip` and `download_file` return `False` with warning log | INFO | Intentional Phase 2 stub — documented in plan 02-03, tested in `test_action_handlers`, deferred to Phase 3 |
| `pipeline/smart_ac_verifier.py` | 629 | `return {}` in `_parse_json` | INFO | Not a stub — correct fallback when all JSON extraction strategies fail; prevents crash on malformed Claude response |
| `pipeline/smart_ac_verifier.py` | 1081–1089 | Click fallback has 7 strategies, not 8 as plan 02-03 describes | INFO | Plan description listed "nth child" as a strategy, implementation omits it. The 7 strategies (role/link/label/exact-text/partial-text/CSS/dispatch_event) cover all practical cases. No functional gap. |

No blockers or warnings found. All anti-patterns are informational.

---

### Human Verification Required

These items require a live browser session against the real MCSL Shopify store. Automated unit tests cover all mock-based behaviour.

#### 1. End-to-end FedEx dry ice label generation

**Test:** Call `verify_ac()` with a FedEx dry ice AC text (e.g., "When dry ice weight is set to 1.0 kg on a product, FedEx label generation succeeds with dry ice surcharge applied")
**Expected:** Agent navigates to App Products, enables "Is Dry Ice Needed" toggle, sets dry ice weight, navigates to Order Summary, generates label, confirms "LABEL CREATED" status, returns `status=pass` or `status=qa_needed`
**Why human:** Requires live auth.json, live Playwright browser, and real MCSL app connectivity. Precondition step correctness (product toggle enable/disable) can only be confirmed against the live UI.

#### 2. UPS COD SideDock flow

**Test:** Call `verify_ac()` with a UPS COD AC text
**Expected:** Agent opens SideDock, enables COD option, enters amount and payment method, generates label with UPS carrier code C3 in the request
**Why human:** SideDock interaction is app-iframe specific; XHR filtering for COD-specific request fields requires live network traffic.

#### 3. Multi-scenario stop button real-time behaviour

**Test:** Start `verify_ac()` with a 5-scenario AC text, trigger stop after 2 seconds
**Expected:** Agent halts before the next scenario boundary; `VerificationReport` contains partial results for completed scenarios only
**Why human:** Threading timing and UI responsiveness can only be confirmed in a live run. Unit test confirms the flag check logic but not real-world latency.

---

### Gaps Summary

No gaps. All 13 observable truths are verified. All required artifacts are substantive and wired. All 13 requirements (AGENT-01 through AGENT-07, CARRIER-01 through CARRIER-06) are satisfied.

The one plan description discrepancy (plan 02-03 states "8-strategy click fallback"; implementation has 7) is informational — the missing "nth child" strategy does not affect functional coverage and is not testable via the existing test contract.

The three human verification items are expected at this phase: they require live browser, real app connectivity, and threading — none of which are testable in unit tests. They should be executed when auth.json is available and the MCSL store is accessible.

---

_Verified: 2026-04-16T05:57:17Z_
_Verifier: Claude (gsd-verifier)_
