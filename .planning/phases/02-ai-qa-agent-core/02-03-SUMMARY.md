---
phase: 02-ai-qa-agent-core
plan: "03"
subsystem: testing
tags: [playwright, langchain, anthropic, claude, browser-automation, agentic-loop]

# Dependency graph
requires:
  - phase: 02-02
    provides: _verify_scenario loop, _ax_tree, _screenshot, _network, _launch_browser stubs

provides:
  - _get_app_frame() — iframe-aware frame resolver (app-iframe name or pluginhive/apps URL)
  - _do_action() — full dispatcher for all 11 action types
  - _DECISION_PROMPT — MCSL-adapted prompt for Claude step decisions
  - _decide_next() — Claude invocation with HumanMessage text + base64 image block

affects: [02-04, 02-05, 02-06, 02-07]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "8-strategy click fallback: role/link/label/exact-text/partial-text/CSS/dispatch_event"
    - "Frame-aware action dispatch: _get_app_frame() returns app iframe or page fallback"
    - "TDD RED-GREEN cycle: failing test committed before implementation"
    - "_decide_next falls back to qa_needed on unparseable or missing-action Claude response"

key-files:
  created: []
  modified:
    - pipeline/smart_ac_verifier.py
    - tests/test_agent.py

key-decisions:
  - "download_zip and download_file are Phase 2 stubs (log warning + return False) — full implementation deferred to Phase 3"
  - "_decide_next sends image_url content block (data:image/png;base64,...) not Anthropic-native image source — compatible with LangChain HumanMessage"
  - "_get_app_frame checks frame.name for 'app-iframe' first, then URL for 'pluginhive'/'apps' — fallback to page if no match"
  - "_DECISION_PROMPT explicitly forbids Shopify More Actions for MCSL label generation"

patterns-established:
  - "Frame-aware locator pattern: _get_app_frame(page) used by click and fill before any locator call"
  - "Action fallback pattern: try each strategy, catch all exceptions, move to next"
  - "Claude fallback pattern: missing 'action' key or unparseable JSON → qa_needed with question string"

requirements-completed: [AGENT-04]

# Metrics
duration: 6min
completed: 2026-04-16
---

# Phase 02 Plan 03: Action Handlers + Claude Decision Engine Summary

**Full agentic loop wired end-to-end: _do_action dispatcher (11 types, iframe-aware) + _decide_next Claude invocation with _DECISION_PROMPT and qa_needed fallback**

## Performance

- **Duration:** 6 min
- **Started:** 2026-04-16T05:00:20Z
- **Completed:** 2026-04-16T05:06:30Z
- **Tasks:** 2 (TDD — 4 commits total: 2 RED + 2 GREEN)
- **Files modified:** 2

## Accomplishments
- Implemented `_get_app_frame()` — resolves app iframe (name=app-iframe or pluginhive/apps URL) with page fallback
- Implemented `_do_action()` dispatcher handling all 11 action types: observe, click, fill, scroll, navigate, switch_tab, close_tab, verify, qa_needed, download_zip (stub), download_file (stub)
- Implemented `_DECISION_PROMPT` (3445 chars) adapted for MCSL — includes workflow guide, action schema, MCSL-specific nav rules
- Implemented `_decide_next()` — Claude invocation with text + base64 image HumanMessage, falls back to qa_needed on garbage response
- All 9 active tests pass (2 remain skipped for plans 06/07)

## Task Commits

Each task was committed atomically using TDD:

1. **Task 1 RED: test_action_handlers (failing)** - `8954608` (test)
2. **Task 1 GREEN: _do_action dispatcher + 11 handlers** - `9f0fa65` (feat)
3. **Task 2 RED: test_decide_next_valid_response + test_decide_next_garbage_fallback** - `6941094` (test)
4. **Task 2 GREEN: _DECISION_PROMPT + _decide_next** - `20cb68e` (feat)

_Note: TDD tasks have 2 commits each (RED test → GREEN implementation)_

## Files Created/Modified
- `pipeline/smart_ac_verifier.py` - Added _get_app_frame, full _do_action, _DECISION_PROMPT, _decide_next
- `tests/test_agent.py` - Unskipped test_action_handlers; added test_decide_next_valid_response and test_decide_next_garbage_fallback

## Decisions Made
- `download_zip` and `download_file` are Phase 2 stubs: log warning + return False. Full implementation (Playwright expect_download + ZIP extraction) is deferred to Phase 3 per plan spec.
- `_decide_next` uses `image_url` content block format (LangChain-compatible) rather than Anthropic native `image.source.base64` format — this matches LangChain ChatAnthropic's expected schema.
- `_get_app_frame` checks frame name first (`app-iframe`), then URL fragments (`pluginhive`, `apps` + `shopify`) before falling back to page — robust to name changes.
- `_DECISION_PROMPT` explicitly states "Do NOT use Shopify More Actions for MCSL label generation" inline, and also includes the full `_MCSL_WORKFLOW_GUIDE` so Claude has complete navigation context.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - both TDD cycles completed cleanly.

## Next Phase Readiness
- Full agentic loop is now functional end-to-end: `_verify_scenario` → `_decide_next` (Claude) → `_do_action` (browser)
- Plans 02-04 and beyond can layer carrier-specific behaviour without modifying the core loop
- download_zip and download_file stubs are clearly marked for Phase 3 implementation

---
*Phase: 02-ai-qa-agent-core*
*Completed: 2026-04-16*
