---
phase: 07-release-qa-pipeline-core
plan: 01
subsystem: pipeline
tags: [langchain, anthropic, claude, trello, validation, test-cases, rag]

# Dependency graph
requires:
  - phase: 06-user-story-move-cards-history
    provides: TrelloClient, TrelloCard, pipeline/card_processor.py get_ac_text()
  - phase: 04-pipeline-dashboard
    provides: ChromaDB RAG vectorstore search()
provides:
  - pipeline/domain_validator.py: validate_card() -> ValidationReport using Claude + RAG
  - pipeline/trello_client.py: TrelloCard expanded with comments/attachments/checklists fields; get_card_comments() helper
  - pipeline/card_processor.py: TestCaseRow, generate_acceptance_criteria(), generate_test_cases(), write_test_cases_to_card(), format_qa_comment(), parse_test_cases_to_rows()
affects: [07-03-release-qa-tab-ui, 07-04-sheets-writer]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - validate_card() never raises — returns ValidationReport with error field on all failure paths
    - patch target must be module-level binding (pipeline.domain_validator.ChatAnthropic), not source package
    - generate_test_cases() uses card.desc directly for AC text — get_ac_text() expects URL string, not TrelloCard

key-files:
  created:
    - pipeline/domain_validator.py
  modified:
    - pipeline/trello_client.py
    - pipeline/card_processor.py
    - tests/test_pipeline.py

key-decisions:
  - "patch target is pipeline.domain_validator.ChatAnthropic (module binding), not langchain_anthropic.ChatAnthropic — already-loaded module ignores source-level patches"
  - "generate_test_cases() uses card.desc directly for AC source — never calls get_ac_text(card) since that function expects a URL string"
  - "validate_card() guard checks config.ANTHROPIC_API_KEY with getattr() fallback — allows test patching via patch.object(config, 'ANTHROPIC_API_KEY', 'test-key')"

patterns-established:
  - "ValidationReport error field pattern: all failure paths set error field and return, never raise"
  - "RAG graceful fallback: search() exceptions caught, context set to 'Knowledge base unavailable.' string"

requirements-completed: [RQA-01, RQA-02]

# Metrics
duration: 5min
completed: 2026-04-17
---

# Phase 07 Plan 01: Domain Validator + Card Processor Expansion Summary

**validate_card() -> ValidationReport with Claude+RAG fallback, TrelloCard expanded with 3 new fields, and full AC/TC generation pipeline in card_processor.py — 7 new tests GREEN, 108 total pass**

## Performance

- **Duration:** 5 min
- **Started:** 2026-04-17T17:27:00Z
- **Completed:** 2026-04-17T17:32:27Z
- **Tasks:** 2 (TDD RED + GREEN)
- **Files modified:** 4

## Accomplishments

- Created `pipeline/domain_validator.py` with `validate_card()` returning `ValidationReport` — handles no API key, RAG failures, and Claude errors gracefully without ever raising
- Expanded `TrelloCard` with `comments`, `attachments`, `checklists` fields (empty-list defaults) and added `TrelloClient.get_card_comments()` fetching `commentCard` actions
- Extended `pipeline/card_processor.py` with `TestCaseRow` dataclass, `AC_WRITER_PROMPT`/`TEST_CASE_PROMPT` constants, and 5 new functions: `generate_acceptance_criteria`, `generate_test_cases`, `write_test_cases_to_card`, `format_qa_comment`, `parse_test_cases_to_rows`

## Task Commits

Each task was committed atomically:

1. **Task 1 (RED): Write failing test stubs** - `9f6b077` (test)
2. **Task 2 (GREEN): Implement modules** - `8c3a23e` (feat)

## Files Created/Modified

- `pipeline/domain_validator.py` — NEW: validate_card() -> ValidationReport, ValidationReport dataclass, VALIDATION_PROMPT
- `pipeline/trello_client.py` — TrelloCard += comments/attachments/checklists; TrelloClient += get_card_comments()
- `pipeline/card_processor.py` — TestCaseRow, AC_WRITER_PROMPT, TEST_CASE_PROMPT, generate_acceptance_criteria(), generate_test_cases(), write_test_cases_to_card(), format_qa_comment(), parse_test_cases_to_rows()
- `tests/test_pipeline.py` — 7 new RQA-01/02/04 test stubs (RED then GREEN)

## Decisions Made

- Patch targets must be module-level bindings (`pipeline.domain_validator.ChatAnthropic`) not source package (`langchain_anthropic.ChatAnthropic`) — Python caches already-imported modules and source-level patching has no effect on live references
- `generate_test_cases()` uses `card.desc` directly for AC text — `get_ac_text()` expects a URL string, passing a `TrelloCard` object caused `TypeError` in `re.search()`
- `validate_card()` guard uses `getattr(config, 'ANTHROPIC_API_KEY', '')` with `patch.object(config, 'ANTHROPIC_API_KEY', 'test-key')` in tests — constructor-level key validation would bypass the guard test

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed incorrect patch targets in tests**
- **Found during:** Task 2 (GREEN phase verification)
- **Issue:** Plan specified `patch("langchain_anthropic.ChatAnthropic")` but modules import ChatAnthropic at top level, so patching the source package after module load has no effect — tests returned empty captured_messages or fell through to ANTHROPIC_API_KEY guard
- **Fix:** Changed patch targets to `pipeline.domain_validator.ChatAnthropic` and `pipeline.card_processor.ChatAnthropic`; added `patch.object(config, "ANTHROPIC_API_KEY", "test-key")` where needed
- **Files modified:** tests/test_pipeline.py
- **Verification:** All 7 tests pass in isolation and together
- **Committed in:** 8c3a23e (Task 2 commit)

**2. [Rule 1 - Bug] Fixed TypeError in generate_test_cases() calling get_ac_text(card)**
- **Found during:** Task 2 (full suite run after GREEN)
- **Issue:** Implementation had `ac_text = get_ac_text(card)` with TrelloCard object — `get_ac_text()` calls `re.search()` on input expecting a URL string, causing `TypeError: expected string or bytes-like object, got 'TrelloCard'`
- **Fix:** Removed the erroneous `get_ac_text(card)` call; use `card.desc` directly as AC text source
- **Files modified:** pipeline/card_processor.py
- **Verification:** Full suite 108 passed
- **Committed in:** 8c3a23e (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 1 - Bug)
**Impact on plan:** Both required for correctness. No scope creep.

## Issues Encountered

None beyond the auto-fixed deviations above.

## Next Phase Readiness

- `validate_card()`, `generate_acceptance_criteria()`, `generate_test_cases()`, `write_test_cases_to_card()`, `parse_test_cases_to_rows()` all ready for 07-03 Release QA tab UI consumption
- `TrelloCard.comments` field ready for 07-03 to populate via `get_card_comments()`
- Full test suite at 108 passed; no regressions

---
*Phase: 07-release-qa-pipeline-core*
*Completed: 2026-04-17*
