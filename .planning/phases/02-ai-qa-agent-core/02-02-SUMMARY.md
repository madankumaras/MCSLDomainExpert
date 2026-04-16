---
phase: 02-ai-qa-agent-core
plan: "02"
subsystem: testing
tags: [playwright, accessibility-tree, screenshot, browser-automation, agentic-loop]

# Dependency graph
requires:
  - phase: 02-01
    provides: smart_ac_verifier.py scaffold with ScenarioResult, VerificationStep, StepResult, stub functions
provides:
  - _walk: recursive AX snapshot walker (depth 6, 250-line cap)
  - _ax_tree: dual-frame accessibility tree capture (Shopify admin + app iframe)
  - _screenshot: base64 PNG via page.screenshot
  - _network: XHR/fetch entries from main page + app iframe, returns joined string
  - _verify_scenario: 15-step agentic browser loop with stop_flag and active_page tracking
  - _decide_next: stub returning qa_needed (real Claude invocation in plan 02-03)
  - _launch_browser: Playwright chromium launch with channel=chrome, anti-bot args, auth.json
affects:
  - 02-03
  - 02-04

# Tech tracking
tech-stack:
  added: []
  patterns:
    - dual-frame AX capture (main page + app iframe filtered by shopify/pluginhive/apps URL)
    - _network returns str not list (joined newlines) — matches test contract
    - _verify_scenario loop uses stop_flag lambda for user-abort support
    - active_page tracking for tab switch actions (_new_page key in action dict)

key-files:
  created: []
  modified:
    - pipeline/smart_ac_verifier.py
    - tests/test_agent.py

key-decisions:
  - "_network returns str (newline-joined) not list[str] — test expects isinstance(net, str)"
  - "VerificationStep fields made keyword-only with defaults so StepResult(step_num=N, ax_tree=s) works"
  - "ScenarioResult gains finding + evidence_screenshot fields alongside existing verdict"
  - "_decide_next stub: returns qa_needed now; plan 02-03 replaces with real Claude invocation"
  - "_launch_browser uses _auth_ctx_kwargs-style JSON validation before setting storage_state"

patterns-established:
  - "Dual-frame AX capture: skip main_frame, include frames with shopify/pluginhive/apps in URL"
  - "net_seen accumulates non-empty _network strings across loop steps (append, not extend)"
  - "stop_flag checked at loop top — returns status=partial when triggered"

requirements-completed:
  - AGENT-04
  - AGENT-05

# Metrics
duration: 18min
completed: 2026-04-15
---

# Phase 02 Plan 02: Browser Loop and State Capture Summary

**Dual-frame AX tree + base64 screenshot + filtered XHR network capture powering the 15-step agentic browser loop with stop_flag, active_page tracking, and Playwright chrome-channel launch**

## Performance

- **Duration:** 18 min
- **Started:** 2026-04-15T17:34:39Z
- **Completed:** 2026-04-15T17:52:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Implemented `_walk` + `_ax_tree` with dual-frame capture — main Shopify page and app iframe (URL filter: shopify/pluginhive/apps), depth 6, 250-line cap
- Implemented `_screenshot` (base64 PNG) and `_network` (XHR/fetch from main + iframe, returns joined string)
- Implemented full `_verify_scenario` 15-step agentic loop with stop_flag, active_page tracking, net_seen accumulation, verify/qa_needed exit conditions
- Added `_launch_browser` for sync Playwright with channel=chrome, _ANTI_BOT_ARGS, auth.json storage state
- Unskipped `test_ax_tree_capture` and `test_browser_loop_scaffold` — both pass

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement _walk, _ax_tree, _screenshot, _network state capture** - `9b96c0b` (feat)
2. **Task 2: Implement _verify_scenario loop, _decide_next stub, _launch_browser** - `051ef44` (feat)

**Plan metadata:** (docs commit — created after this summary)

## Files Created/Modified
- `pipeline/smart_ac_verifier.py` — replaced stubs with full implementations of _walk, _ax_tree, _screenshot, _network, _decide_next, _verify_scenario, _launch_browser; added finding/evidence_screenshot to ScenarioResult; added step_num/ax_tree to VerificationStep
- `tests/test_agent.py` — unskipped test_browser_loop_scaffold with mock-page + _decide_next patch implementation

## Decisions Made
- `_network` returns `str` (newline-joined entries) not `list[str]` — the existing test asserts `isinstance(net, str)` so this is the correct contract; `_verify_scenario` uses `net_seen.append(net)` accordingly
- `VerificationStep` fields changed to keyword-only with defaults — allows `StepResult(step_num=N, ax_tree=s, screenshot_b64=b)` construction pattern from plan without breaking existing usage
- `ScenarioResult` gains `finding` and `evidence_screenshot` fields alongside existing `verdict` — `finding` is the human-readable text from verify/qa_needed actions; `verdict` preserved for compatibility
- `_decide_next` stub returns `{"action": "qa_needed", "finding": "Not yet implemented"}` — plan 02-03 replaces this with the real Claude API invocation

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `_verify_scenario` loop is ready for plan 02-03 to replace the `_decide_next` stub with a real Claude invocation
- `_launch_browser` ready for plan 02-04 to wire up the `verify_ac()` entry point with full browser lifecycle management
- All 5 active tests pass; 3 Wave 0 stubs remain skipped for plans 02-03 and 02-05+

---
*Phase: 02-ai-qa-agent-core*
*Completed: 2026-04-15*
