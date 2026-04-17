---
phase: 07-release-qa-pipeline-core
plan: "03"
subsystem: ui
tags: [streamlit, trello, domain_validator, release_analyser, card_processor, smart_ac_verifier, threading, tdd]

requires:
  - phase: 07-01
    provides: validate_card, ValidationReport, generate_acceptance_criteria, TrelloClient expansion
  - phase: 07-02
    provides: analyse_release, ReleaseAnalysis, CardSummary

provides:
  - Full tab_release UI replacing Phase 7 stub — list selector, card loader, health summary, release intelligence, per-card accordion Steps 1–2
  - Per-card sav_running_{card.id} threading pattern for AI QA Agent
  - 5-metric release health dashboard (Total, Pass, Needs Review, Fail, Approved)
  - Release Intelligence expander with risk_level, conflicts, coverage_gaps
  - AC generation + save to Trello per card
  - 3 new RQA session-state and threading unit tests GREEN

affects: [07-04, phase-8-slack-integration]

tech-stack:
  added: []
  patterns:
    - Per-card scoped session_state keys (sav_running_{id}, sav_result_{id}, sav_stop_{id}) for concurrent multi-card AI agent threads
    - Atomic result-before-flag ordering: sav_result set before sav_running=False to prevent polling race condition
    - validate_card + analyse_release called on card load; stored in session_state for later display
    - Top-level pipeline imports (not lazy) for domain modules used inside tab_release

key-files:
  created: []
  modified:
    - pipeline_dashboard.py
    - tests/test_dashboard.py

key-decisions:
  - "Per-card sav_running_{card.id} key (not a global sav_running) — enables concurrent AI QA Agent runs per card without state collision"
  - "top-level pipeline imports (validate_card, analyse_release, generate_acceptance_criteria, verify_ac, TrelloClient) added alongside existing lazy imports — keeps tab_release readable without nested lazy imports"
  - "Thread closure captures all mutable keys as default args to avoid late-binding closure bugs in for-loop"

patterns-established:
  - "Per-card threading: sav_running_{card.id}, sav_stop_{card.id}, sav_result_{card.id}, sav_stop_event_{card.id} — scoped to card ID to prevent cross-card state pollution"
  - "Result-before-flag: st.session_state[_rk] assigned before st.session_state[sav_running_key] = False in thread finally"

requirements-completed: [RQA-01, RQA-02, RQA-03]

duration: 15min
completed: 2026-04-17
---

# Phase 7 Plan 03: Release QA Tab UI (Steps 1-2) Summary

**Full Streamlit tab_release replacing the Phase 7 stub: Trello list selector, per-card validate_card + analyse_release on load, 5-metric health summary, Release Intelligence expander, per-card accordion with Steps 1a/1b/1c (card details, validation, AC gen/save) and Step 2 (AI QA Agent with per-card threading)**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-04-17T17:22:00Z
- **Completed:** 2026-04-17T17:37:29Z
- **Tasks:** 2 (RED test stubs + GREEN implementation)
- **Files modified:** 2

## Accomplishments

- Replaced single-line `st.info("Release QA pipeline coming in Phase 7.")` stub with ~330 lines of full tab_release UI
- Added 4 new session_state keys (`rqa_list_name`, `rqa_board_id`, `rqa_board_name`, `release_analysis`) to `_init_state()`
- Implemented per-card scoped threading pattern: `sav_running_{card.id}` never collides across cards
- 3 new RQA tests GREEN (test_rqa01_session_state_keys, test_rqa03_sav_running_per_card, test_rqa03_sav_result_before_flag)
- Full suite: 111 passed, 7 skipped, 0 failed

## Task Commits

1. **Task 1: RED phase — 3 failing test stubs** - `f5f609a` (test)
2. **Task 2: GREEN phase — full tab_release implementation** - `7964aeb` (feat)

## Files Created/Modified

- `pipeline_dashboard.py` — Added 4 _init_state() keys, top-level pipeline imports, full tab_release implementation (~330 lines replacing 1-line stub)
- `tests/test_dashboard.py` — Added 3 new RQA test functions: test_rqa01_session_state_keys, test_rqa03_sav_running_per_card, test_rqa03_sav_result_before_flag

## Decisions Made

- Per-card sav_running_{card.id} key (not global sav_running) ensures concurrent AI QA Agent threads per card don't collide
- Top-level pipeline imports added for domain modules consumed throughout tab_release — avoids deeply nested lazy imports; existing lazy imports in _run_pipeline preserved
- Thread closure captures mutable loop variables as default args to avoid late-binding closure bugs inside for-loop over cards

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None — all tests GREEN on first implementation pass.

## Next Phase Readiness

- tab_release Steps 1–2 complete; Steps 3 (TC generation + approval) and Step 4 (Sheets export) are implemented in 07-04
- Phase 8 Slack DM placeholder comment present in per-card section as specified

---
*Phase: 07-release-qa-pipeline-core*
*Completed: 2026-04-17*
