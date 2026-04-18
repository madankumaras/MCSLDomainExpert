---
phase: 01-foundation
plan: 04
subsystem: pipeline
tags: [chromadb, langchain, trello, rag, upsert, idempotent]

# Dependency graph
requires:
  - phase: 01-02
    provides: upsert_documents() idempotent upsert via rag/vectorstore.py

provides:
  - pipeline/rag_updater.py with embed_trello_card() for sprint-cycle RAG updates
  - Idempotent Trello card ingestion: re-running same card_id replaces not appends
  - stable IDs card_id__ac and card_id__test_cases for targeted deletion

affects:
  - pipeline-dashboard
  - rag-chat
  - ingest-pipeline

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Stable ID upsert pattern: f'{card_id}__ac' and f'{card_id}__test_cases' as ChromaDB document IDs"
    - "Patch target convention: patch 'pipeline.module.imported_fn' not 'source.module.fn' for already-imported names"

key-files:
  created:
    - pipeline/rag_updater.py
  modified:
    - tests/test_rag_updater.py

key-decisions:
  - "Patch target is pipeline.rag_updater.upsert_documents (not rag.vectorstore.upsert_documents) because the function is imported at module level — patching source after import has no effect"
  - "ids passed as keyword arg: upsert_documents(docs, ids=[...]) — tests must handle both positional and keyword extraction"

patterns-established:
  - "Patch where the name is used, not where it is defined — patch 'pipeline.rag_updater.upsert_documents'"
  - "stable IDs: f'{card_id}__ac' and f'{card_id}__test_cases' — consistent across all Trello card embeds"

requirements-completed:
  - RAG-06

# Metrics
duration: 12min
completed: 2026-04-15
---

# Phase 01 Plan 04: RAG Updater Summary

**embed_trello_card() idempotent upsert into mcsl_knowledge using stable IDs card_id__ac and card_id__test_cases via rag.vectorstore.upsert_documents**

## Performance

- **Duration:** 12 min
- **Started:** 2026-04-15T11:17:04Z
- **Completed:** 2026-04-15T11:29:00Z
- **Tasks:** 1 (TDD: RED + GREEN)
- **Files modified:** 2

## Accomplishments

- Created pipeline/rag_updater.py with embed_trello_card(card_id, ac_text, test_cases_text)
- Idempotent upsert: re-running for same card_id replaces rather than appends
- Both documents get source_type='trello_card' for filtered retrieval in Domain Expert Chat
- All 3 tests pass: test_stable_ids, test_upsert_idempotent, test_source_type_metadata

## Task Commits

Each task was committed atomically:

1. **Task 1 RED: Failing tests for embed_trello_card** - `6ed076f` (test)
2. **Task 1 GREEN: Implement embed_trello_card + fix tests** - `9c10ec9` (feat)

**Plan metadata:** (docs commit — see below)

_Note: TDD task has two commits: test (RED) → feat (GREEN)_

## Files Created/Modified

- `pipeline/rag_updater.py` - embed_trello_card() function routing through rag.vectorstore.upsert_documents
- `tests/test_rag_updater.py` - 3 tests: stable IDs, idempotency, source_type metadata

## Decisions Made

- Patch target for tests is `pipeline.rag_updater.upsert_documents` (not `rag.vectorstore.upsert_documents`) because `upsert_documents` is imported at module load time via `from rag.vectorstore import upsert_documents` — patching the source module has no effect on already-bound names
- `ids` is passed as a keyword argument to `upsert_documents` — test helper `_get_docs_and_ids()` handles both positional and keyword extraction for robustness

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed mock patch target in tests**
- **Found during:** Task 1 GREEN phase
- **Issue:** Plan template used `patch("rag.vectorstore.upsert_documents")` but `pipeline.rag_updater` imports `upsert_documents` at module level — patching the source has no effect on the already-bound name in rag_updater
- **Fix:** Changed all 3 test patches to `patch("pipeline.rag_updater.upsert_documents")`; added `_get_docs_and_ids()` helper to handle positional-or-keyword `ids` extraction
- **Files modified:** tests/test_rag_updater.py
- **Verification:** All 3 tests pass with `pytest tests/test_rag_updater.py -v`
- **Committed in:** 9c10ec9 (Task 1 GREEN commit)

---

**Total deviations:** 1 auto-fixed (1 bug in plan's test template)
**Impact on plan:** Essential fix — tests would never pass with wrong patch target. No scope creep.

## Issues Encountered

- Plan template test code patched `rag.vectorstore.upsert_documents` — this is the standard Python mock gotcha: patch where the name is USED (in the importing module), not where it is DEFINED. Fixed automatically per Rule 1.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- pipeline/rag_updater.py is ready for use in Pipeline Dashboard (Plan 05)
- embed_trello_card() can be called after each Trello card approval cycle to keep mcsl_knowledge current
- source_type='trello_card' enables Domain Expert Chat to filter by Trello card content

---
*Phase: 01-foundation*
*Completed: 2026-04-15*
