---
phase: 03-label-docs-pre-requirements
plan: "04"
subsystem: testing
tags: [pytest, tdd, document-verification, workflow-guide, label-docs]

# Dependency graph
requires:
  - phase: 03-label-docs-pre-requirements
    provides: _MCSL_WORKFLOW_GUIDE with Label flow sections, tests/test_label_flows.py Wave 0 stubs
provides:
  - _MCSL_WORKFLOW_GUIDE with complete Document Verification Strategies section (DOC-01 through DOC-05)
  - tests/test_label_flows.py with test_doc01 through test_doc05 active and passing
affects: [03-05, 03-06]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Guide content TDD: unskip test asserting string presence in _MCSL_WORKFLOW_GUIDE, then add guide section to pass"
    - "DOC strategy naming convention: DOC-01 through DOC-05 as named subsections in guide"

key-files:
  created: []
  modified:
    - pipeline/smart_ac_verifier.py
    - tests/test_label_flows.py

key-decisions:
  - "DOC-01 test passes immediately because LABEL CREATED/status/Label Summary were already in guide — no regression, just content spec was already met"
  - "DOC-04 explicitly warns NOT to use download_zip — Print Documents is a new-tab flow (switch_tab), not a file download"
  - "DOC-05 requires ViewallRateSummary expand FIRST because the rate table is COLLAPSED by default — 3-dots button invisible without expand"
  - "DOC-03 references td:nth-child(8) MCSL-specific locator and notes FedEx How-To ZIP flow does NOT exist in MCSL"

patterns-established:
  - "Document verification strategy format: numbered steps with exact locators, warnings for common mistakes (wrong action type, missing prerequisite expand)"

requirements-completed: [DOC-01, DOC-02, DOC-03, DOC-04, DOC-05]

# Metrics
duration: 11min
completed: 2026-04-16
---

# Phase 03 Plan 04: Document Verification Strategies Summary

**_MCSL_WORKFLOW_GUIDE extended with all five Document Verification Strategies (DOC-01 through DOC-05) covering badge check, ZIP download, label request XML via 3-dots dialog, print-documents new-tab, and rate log expand-then-screenshot**

## Performance

- **Duration:** 11 min
- **Started:** 2026-04-16T11:04:36Z
- **Completed:** 2026-04-16T11:14:51Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Added Document Verification Strategies section to _MCSL_WORKFLOW_GUIDE with all 5 named subsections (DOC-01 through DOC-05)
- Activated test_doc01_badge_check, test_doc04_print_documents, test_doc02_download_zip, test_doc03_label_request_xml, test_doc05_rate_log — all passing
- DOC-04 explicitly guards against the download_zip mistake (Print Documents opens a NEW TAB — use switch_tab)
- DOC-05 enforces ViewallRateSummary expand step before 3-dots click (table COLLAPSED by default)
- Full test suite: 52 passed, 14 skipped, 0 failures

## Task Commits

Each task was committed atomically:

1. **Task 1 RED: unskip test_doc01_badge_check and test_doc04_print_documents** - `32c2c2b` (test)
2. **Task 1 GREEN: add DOC-01 and DOC-04 sections to _MCSL_WORKFLOW_GUIDE** - `d125a2b` (feat)
3. **Task 2 RED: unskip test_doc02_download_zip, test_doc03_label_request_xml, test_doc05_rate_log** - `25c2915` (test)
4. **Task 2 GREEN: add DOC-02, DOC-03, DOC-05 sections to _MCSL_WORKFLOW_GUIDE** - `7e310ea` (feat)

**Plan metadata:** (docs commit — see below)

_Note: TDD tasks have multiple commits (test → feat)_

## Files Created/Modified
- `pipeline/smart_ac_verifier.py` — _MCSL_WORKFLOW_GUIDE extended with Document Verification Strategies section: DOC-01 (badge check locators), DOC-02 (download_zip + _zip_content), DOC-03 (3-dots Label Summary → View Log → dialogHalfDivParent), DOC-04 (switch_tab NOT download_zip warning), DOC-05 (ViewallRateSummary expand FIRST warning)
- `tests/test_label_flows.py` — test_doc01 through test_doc05 unskipped and active; content assertion tests on _MCSL_WORKFLOW_GUIDE string

## Decisions Made
- DOC-01 test was immediately GREEN because "LABEL CREATED", "status", and "Label Summary" already existed in the guide — this is correct, not a regression; the existing content already satisfied the spec
- DOC-04 warning pattern: "do NOT use download_zip here" placed prominently at the top of the strategy entry, not buried in numbered steps
- DOC-05 expand-first requirement captured both in the numbered step ("FIRST: Click ViewallRateSummary") and in a footer WARNING line for emphasis
- DOC-03 notes that FedEx "How To → Click Here → ZIP" flow does NOT apply to MCSL (this was a source of confusion per research)

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All 5 document verification strategy tests are active and passing
- _MCSL_WORKFLOW_GUIDE now has a complete Document Verification Strategies section the agent can consult
- Ready for 03-05 (Pre-requirement strategies) and 03-06 plans
- 52 tests pass, 14 skipped (remaining Wave 0 stubs for PRE-01 through PRE-06)

---
*Phase: 03-label-docs-pre-requirements*
*Completed: 2026-04-16*
