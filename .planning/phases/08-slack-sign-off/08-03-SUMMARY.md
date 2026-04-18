---
phase: 08-slack-sign-off
plan: 03
subsystem: ui
tags: [streamlit, slack, trello, sign-off, bug-reporter, tdd]

# Dependency graph
requires:
  - phase: 08-01
    provides: slack_client.py with post_signoff(), slack_configured(), dm_token_configured()
  - phase: 08-02
    provides: bug_reporter.py with notify_devs_of_bug()
  - phase: 07-release-qa-pipeline-core
    provides: rqa_cards, rqa_approved, rqa_test_cases, rqa_release session state keys; sav_report_{card.id}
provides:
  - Full tab_signoff UI: per-card approval summary, bug list text area, message composer, Send Sign-Off button
  - Phase 8 bug-DM wiring in tab_release Step 2 (auto notify_devs_of_bug on failed verdict)
  - signoff_message and signoff_sent keys in _init_state()
  - slack_post_signoff + notify_devs_of_bug imports at module top
affects: [09-write-automation, 10-run-automation]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Slack configuration gate (slack_configured()) guards all Slack UI controls with st.warning fallback
    - TrelloClient instantiated inside with-tab block with try/except guard for unavailable credentials
    - Phase 8 bug-DM auto-triggered on failed verdict without user interaction; bug_dm_sent_{card.id} prevents re-sends
    - signoff_sent session flag gates success banner vs send button

key-files:
  created: []
  modified:
    - pipeline_dashboard.py
    - tests/test_dashboard.py

key-decisions:
  - "tab_signoff trello instance created with try/except guard; all trello.* calls guarded with if trello: — prevents crash when Trello creds absent"
  - "notify_devs_of_bug uses __import__ for SlackClient inside the call to avoid circular import at tab render time"
  - "logging.getLogger(__name__) added at module level for bug-DM warning logging"
  - "test_signoff01_compose_message and test_signoff02_send_signoff_posts_slack use source inspection (inspect.getsource) for fast deterministic assertions without mocking Streamlit"

patterns-established:
  - "Slack gate pattern: if not slack_configured(): st.warning(...) — all Slack controls hidden behind this check"
  - "signoff_sent flag: set True after successful Slack post + Trello moves; gates success banner vs send UI"

requirements-completed: [SIGNOFF-01, SIGNOFF-02]

# Metrics
duration: 14min
completed: 2026-04-17
---

# Phase 8 Plan 03: Sign Off Tab + Phase 8 Bug-DM Wiring Summary

**Full tab_signoff UI with Slack sign-off posting, Trello QA-done card moves, and auto bug-DM on failed AI QA verdict — all gated by slack_configured()**

## Performance

- **Duration:** 14 min
- **Started:** 2026-04-17T09:55:47Z
- **Completed:** 2026-04-17T10:09:00Z
- **Tasks:** 2 (RED + GREEN)
- **Files modified:** 2

## Accomplishments
- Replaced tab_signoff stub with full Sign Off UI: per-card approved checkboxes (from rqa_approved), auto-populated bug list from failed sav_report_{card.id} verdicts, sign-off message composer with mentions/CC/QA lead fields, message preview, Send Sign-Off button posting to Slack + moving approved cards to selected QA-done Trello list
- Wired Phase 8 bug-DM placeholder in tab_release Step 2: on failed verdict with slack_configured(), auto-calls notify_devs_of_bug() and sets bug_dm_sent_{card.id} to prevent re-sends
- Added signoff_message and signoff_sent to _init_state(); all 122 tests GREEN (7 skipped)

## Task Commits

1. **Task 1: TDD RED — 3 SIGNOFF test stubs** - `20013ca` (test)
2. **Task 2: GREEN — full implementation** - `76d28c8` (feat)

## Files Created/Modified
- `pipeline_dashboard.py` - Added slack/bug_reporter imports, logging, _init_state() Phase 8 keys, tab_signoff full UI, Phase 8 bug-DM wiring in tab_release
- `tests/test_dashboard.py` - Added test_signoff01_session_keys, test_signoff01_compose_message, test_signoff02_send_signoff_posts_slack

## Decisions Made
- TrelloClient in tab_signoff wrapped in try/except with `if trello:` guards on all calls — prevents crash when TRELLO_* env vars absent
- Used `__import__("pipeline.slack_client", fromlist=["SlackClient"]).SlackClient()` for notify_devs_of_bug to avoid circular imports at module top; safe since this code only executes inside the Streamlit render loop when conditions are met
- Added `import logging` + `logger = logging.getLogger(__name__)` at module level (plan used `logger.warning` but dashboard had no logger defined — Rule 1 auto-fix)
- Source-inspection tests (inspect.getsource) for compose_message and send_signoff — avoids complex Streamlit mock setup while deterministically asserting all required symbols are present

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Added missing `logger` definition**
- **Found during:** Task 2 (GREEN implementation)
- **Issue:** Plan's Phase 8 bug-DM code used `logger.warning(...)` but pipeline_dashboard.py had no logger defined — would NameError at runtime
- **Fix:** Added `import logging` and `logger = logging.getLogger(__name__)` at module top
- **Files modified:** pipeline_dashboard.py
- **Verification:** No NameError; 122 tests pass
- **Committed in:** 76d28c8 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - missing logger)
**Impact on plan:** Essential correctness fix. No scope creep.

## Issues Encountered
None beyond the logger auto-fix above.

## User Setup Required
None — no new external services introduced. Slack and Trello credentials were handled by 08-01 and 08-02.

## Next Phase Readiness
- Phase 8 Slack sign-off flow complete: SIGNOFF-01 (compose + send) and SIGNOFF-02 (Trello QA-done) satisfied
- Phase 9 (Write Automation / tab_manual) can proceed independently
- tab_manual and tab_run stubs remain in place for Phases 9 and 10

---
*Phase: 08-slack-sign-off*
*Completed: 2026-04-17*
