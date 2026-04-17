---
phase: 07-release-qa-pipeline-core
plan: 02
subsystem: pipeline
tags: [anthropic, langchain, gspread, google-sheets, chromadb, rag, tdd]

# Dependency graph
requires:
  - phase: 06-user-story-move-cards-history
    provides: trello_client, user_story_writer base pipeline modules
provides:
  - pipeline/release_analyser.py with analyse_release() -> ReleaseAnalysis, CardSummary dataclass
  - pipeline/sheets_writer.py with append_to_sheet(), detect_tab(), check_duplicates(), MCSL SHEET_TABS
  - 5 GREEN unit tests for RQA-04/05 in tests/test_pipeline.py
affects:
  - 07-03-release-qa-tab-ui (consumes analyse_release and append_to_sheet)
  - 07-04 (full pipeline integration)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - gspread imported INSIDE append_to_sheet() and check_duplicates() — not at module top — so sheets_writer can be imported without gspread installed
    - analyse_release() never raises — returns ReleaseAnalysis with non-empty error field on all failure paths
    - RAG context fetched with k = min(6 * len(cards), 20) to scale with release size
    - JSON fence stripping with re.sub before json.loads for robust Claude output parsing

key-files:
  created:
    - pipeline/release_analyser.py
    - pipeline/sheets_writer.py
  modified:
    - tests/test_pipeline.py

key-decisions:
  - "gspread imported inside append_to_sheet()/check_duplicates() — not at module top — so sheets_writer can be imported without gspread installed"
  - "sheets_writer defines TestCaseRow locally — parallel plan (07-01/card_processor) runs concurrently so no shared import"
  - "test_rqa04_append_to_sheet_returns_meta patches gspread via patch.dict(sys.modules) since it's imported inside the function body at call time"
  - "test_rqa05_analyse_release_returns_report patches config.ANTHROPIC_API_KEY via patch.object to bypass the empty-key guard in test env"

patterns-established:
  - "Pattern 1: MCSL TAB_KEYWORDS keyword lookup with fallback to 'Draft Plan' for unmatched content"
  - "Pattern 2: detect_tab() first matched keyword wins — ordered dict iteration"

requirements-completed: [RQA-04, RQA-05]

# Metrics
duration: 4min
completed: 2026-04-17
---

# Phase 7 Plan 02: Release Analyser + Sheets Writer Backend Summary

**Cross-card release risk analyser (Claude + RAG) and MCSL Google Sheets writer with SHEET_TABS keyword routing — 5 RQA-04/05 unit tests GREEN**

## Performance

- **Duration:** 4 min
- **Started:** 2026-04-17T17:26:32Z
- **Completed:** 2026-04-17T17:30:40Z
- **Tasks:** 2 (TDD RED + TDD GREEN)
- **Files modified:** 3

## Accomplishments
- `pipeline/release_analyser.py` created with `analyse_release()` -> `ReleaseAnalysis` using Claude JSON parsing and RAG context retrieval; guards for empty card list and missing API key never raise
- `pipeline/sheets_writer.py` created with `append_to_sheet()`, `detect_tab()`, `check_duplicates()`, `parse_test_cases_to_rows()`, `SHEET_TABS`, `TAB_KEYWORDS`, `TestCaseRow`, `DuplicateMatch` — gspread imported inside functions for safe import without credentials
- All 5 new RQA-04/05 tests pass GREEN; overall test_pipeline.py improved from 7 failing to 1 failing (pre-existing 07-01 issue)

## Task Commits

Each task was committed atomically:

1. **Task 1: TDD RED — 5 test stubs** - `e1ee42c` (test)
2. **Task 2: TDD GREEN — implement release_analyser + sheets_writer** - `a11d34b` (feat)

_Note: TDD tasks have two commits: test (RED) then feat (GREEN)_

## Files Created/Modified
- `pipeline/release_analyser.py` — analyse_release() with CardSummary + ReleaseAnalysis dataclasses; Claude LLM integration with RAG context; JSON fence stripping
- `pipeline/sheets_writer.py` — append_to_sheet(), detect_tab(), check_duplicates(), parse_test_cases_to_rows(); MCSL SHEET_TABS + TAB_KEYWORDS; gspread imported inside functions
- `tests/test_pipeline.py` — 5 new RQA-04/05 test stubs added + patching fixed for API key guard and gspread inside-function import

## Decisions Made
- gspread imported INSIDE `append_to_sheet()` and `check_duplicates()` — not at module top — so `sheets_writer` can be imported without gspread installed in environments without Google credentials
- `TestCaseRow` defined locally in `sheets_writer.py` rather than importing from `card_processor.py` because 07-01 and 07-02 run in parallel (no shared files)
- `test_rqa04_append_to_sheet_returns_meta` patches gspread via `patch.dict(sys.modules)` since gspread is dynamically imported inside the function at call time (not at module level)
- `test_rqa05_analyse_release_returns_report` patches `config.ANTHROPIC_API_KEY` via `patch.object` to bypass the empty-key guard that fires before ChatAnthropic construction in test environments

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed test patching for gspread (inside-function import)**
- **Found during:** Task 2 (GREEN phase)
- **Issue:** Test used `patch("pipeline.sheets_writer.gspread")` but gspread is imported inside the function body, so the module-level attribute doesn't exist — AttributeError on patch setup
- **Fix:** Changed to `patch.dict(sys.modules, {"gspread": mock_gspread, ...})` which intercepts the `import gspread` call at function invocation time
- **Files modified:** tests/test_pipeline.py
- **Verification:** `test_rqa04_append_to_sheet_returns_meta` passes GREEN
- **Committed in:** a11d34b

**2. [Rule 1 - Bug] Fixed test patching for config.ANTHROPIC_API_KEY guard**
- **Found during:** Task 2 (GREEN phase)
- **Issue:** Test env has empty ANTHROPIC_API_KEY so the guard fires before ChatAnthropic is called; test expected `result.error == ""` but got the guard error message
- **Fix:** Added `patch.object(config, "ANTHROPIC_API_KEY", "fake-key")` to the test context manager
- **Files modified:** tests/test_pipeline.py
- **Verification:** `test_rqa05_analyse_release_returns_report` passes GREEN
- **Committed in:** a11d34b

---

**Total deviations:** 2 auto-fixed (2 Rule 1 - bugs in test patching strategy)
**Impact on plan:** Both auto-fixes necessary for tests to correctly exercise the production code paths. No scope creep.

## Issues Encountered
- Pre-existing 07-01 failures in `test_rqa01_validate_card_returns_report` and `test_rqa02_generate_tc_prompt_contains_card` were already failing before 07-02 started (confirmed by git stash). These are 07-01 issues deferred to that plan's completion cycle.

## Next Phase Readiness
- `pipeline/release_analyser.py` and `pipeline/sheets_writer.py` fully implemented and tested
- Ready for 07-03 Release QA tab UI to consume `analyse_release()` and `append_to_sheet()`
- 07-01 must complete its GREEN phase before 07-03 starts (domain_validator + card_processor expansion)

---
*Phase: 07-release-qa-pipeline-core*
*Completed: 2026-04-17*
