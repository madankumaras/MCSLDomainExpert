---
phase: 01-foundation
plan: "03"
subsystem: ingest
tags: [langchain, chromadb, google-sheets, wiki, kb-articles, codebase-indexing, argparse]

requires:
  - phase: 01-02
    provides: vectorstore.py (add_documents, delete_by_source_type) and code_indexer.py (index_codebase)
  - phase: 01-01
    provides: config.py with BASE_DIR, CHUNK_SIZE, WIKI_PATH, STOREPEPSAAS_SERVER_PATH, STOREPEPSAAS_CLIENT_PATH, MCSL_AUTOMATION_REPO_PATH, GOOGLE_SHEETS_ID

provides:
  - load_kb_articles() reading 26 KB snapshots from docs/kb_snapshots/ into mcsl_knowledge
  - load_test_cases() reading MCSL TC Google Sheet (all tabs) into mcsl_knowledge
  - load_wiki_docs() reading 241 MCSL wiki docs with MCSL _CATEGORY_MAP into mcsl_knowledge
  - load_codebase() generic code walker for storepepSAAS + automation repos
  - run_ingest(sources) master entry point: 6-source argparse, delete-before-add for no duplicates

affects:
  - 01-04 (rag_updater — calls run_ingest or loaders after card ingestion)
  - phase-02 (domain expert chat — uses mcsl_knowledge populated here)
  - phase-03 (QA agent — may re-ingest wiki/code to update knowledge)

tech-stack:
  added: []
  patterns:
    - "delete_by_source_type(source_type) before add_documents() prevents duplicates on re-run"
    - "MCSL _CATEGORY_MAP maps wiki folder names (architecture/modules/patterns/product/zendesk/support/operations) to human labels"
    - "source_type discriminator: kb_articles | sheets | wiki | storepepsaas_server | storepepsaas_client | automation"
    - "Code sources (storepepsaas_*/automation) route to mcsl_code_knowledge via index_codebase(clear_existing=True)"
    - "Doc sources (kb_articles/sheets/wiki) route to mcsl_knowledge via delete_by_source_type + add_documents"

key-files:
  created:
    - ingest/kb_loader.py
    - ingest/sheets_loader.py
    - ingest/wiki_loader.py
    - ingest/codebase_loader.py
    - ingest/run_ingest.py
    - tests/test_kb_loader.py
    - tests/test_wiki_loader.py
    - tests/test_run_ingest.py
  modified:
    - config.py (added STOREPEPSAAS_SERVER_PATH + STOREPEPSAAS_CLIENT_PATH aliases)

key-decisions:
  - "source_type='sheets' (not 'test_cases') for Google Sheets to match --sources argument name"
  - "6 sources not 5: storepepsaas split into storepepsaas_server + storepepsaas_client for separate metadata tagging"
  - "STOREPEPSAAS_SERVER_PATH + STOREPEPSAAS_CLIENT_PATH added to config.py as aliases for per-source ingest"
  - "carrier-envs/ in _DEFAULT_SKIP_DIRS in codebase_loader.py — contains credential .env files that must never be indexed"
  - "run_ingest.py built fresh (not cloned from FedEx) — MCSL has different sources, collections, and config fields"

patterns-established:
  - "Ingest module pattern: load_*() returns list[Document]; caller does delete_by_source_type + add_documents"
  - "All loaders return [] (not exception) when source path/dir does not exist"
  - "All loaders skip files < 50 chars"
  - "Test pattern: monkeypatch config fields + importlib.reload() for isolated unit tests"

requirements-completed: [RAG-01, RAG-02, RAG-03, RAG-04, RAG-05, INFRA-05]

duration: 6min
completed: 2026-04-15
---

# Phase 1 Plan 3: Ingest Pipeline Summary

**5-source MCSL ingest pipeline: kb_loader, sheets_loader (multi-tab), wiki_loader (MCSL category map), codebase_loader, and run_ingest.py with 6-source argparse and delete-before-add deduplication**

## Performance

- **Duration:** 6 min
- **Started:** 2026-04-15T11:17:09Z
- **Completed:** 2026-04-15T11:22:42Z
- **Tasks:** 2
- **Files modified:** 9 (5 created in ingest/, 3 test files rewritten, config.py updated)

## Accomplishments
- Full 5-module ingest pipeline covering all 6 MCSL knowledge sources
- MCSL-specific wiki _CATEGORY_MAP replacing FedEx categories (architecture/modules/patterns/product/zendesk/support/operations)
- run_ingest.py with --sources argparse and per-source delete-before-add pattern (no duplicates on re-run)
- 15 tests passing covering kb_loader, wiki_loader, and run_ingest behavior

## Task Commits

Each task was committed atomically:

1. **Task 1: Create kb_loader.py, sheets_loader.py, wiki_loader.py** - `02a7422` (feat)
2. **Task 2: Create codebase_loader.py and run_ingest.py** - `f1a3fc4` (feat)

## Files Created/Modified
- `ingest/kb_loader.py` - load_kb_articles() reads docs/kb_snapshots/*.md, skips <50 chars, returns Documents
- `ingest/sheets_loader.py` - load_test_cases() with service-account + public CSV fallback, source_type='sheets'
- `ingest/wiki_loader.py` - load_wiki_docs() with MCSL _CATEGORY_MAP, skips <50 chars, returns empty on missing path
- `ingest/codebase_loader.py` - load_codebase(path, source_type, extensions, exclude_dirs) generic walker, carrier-envs/ excluded
- `ingest/run_ingest.py` - master entry with 6-source argparse, delete_by_source_type before add, index_codebase for code
- `tests/test_kb_loader.py` - 5 tests: missing dir, source_type metadata, documents returned, short file skipped, chunk size
- `tests/test_wiki_loader.py` - 5 tests: MCSL categories, missing path, documents, short files, all 7 category labels
- `tests/test_run_ingest.py` - 5 tests: argparse choices, partial re-ingest delete order, all-sources mode, source_types
- `config.py` - added STOREPEPSAAS_SERVER_PATH + STOREPEPSAAS_CLIENT_PATH aliases

## Decisions Made
- **source_type='sheets' not 'test_cases'**: Matches the --sources argument name for consistency; FedEx used 'test_cases'
- **6 sources not 5**: storepepSAAS split into storepepsaas_server + storepepsaas_client for independent re-ingest and metadata filtering
- **Config aliases added**: STOREPEPSAAS_SERVER_PATH and STOREPEPSAAS_CLIENT_PATH added to config.py (were missing, plan referenced them)
- **run_ingest.py written fresh**: FedEx run_ingest had different sources and config structure — adapting would have created confusion
- **carrier-envs in default skip dirs**: Protection for per-carrier .env credential files in mcsl-test-automation repo

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added STOREPEPSAAS_SERVER_PATH + STOREPEPSAAS_CLIENT_PATH to config.py**
- **Found during:** Task 2 (run_ingest.py implementation)
- **Issue:** Plan referenced config.STOREPEPSAAS_SERVER_PATH and config.STOREPEPSAAS_CLIENT_PATH but config.py only had STOREPEPSAAS_SHARED_PATH
- **Fix:** Added both path aliases to config.py pointing to server/src/shared/ and client/src/ respectively
- **Files modified:** config.py
- **Verification:** run_ingest.py imports cleanly, tests pass
- **Committed in:** 02a7422 (Task 1 commit)

**2. [Rule 3 - Blocking] Added PYTHONPATH to subprocess env in test_sources_argparse**
- **Found during:** Task 2 test execution
- **Issue:** subprocess running run_ingest.py couldn't find 'config' module (not on sys.path)
- **Fix:** Added env={"PYTHONPATH": project_root} to subprocess.run call
- **Files modified:** tests/test_run_ingest.py
- **Verification:** test_sources_argparse passes
- **Committed in:** f1a3fc4 (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 3 - Blocking)
**Impact on plan:** Both auto-fixes necessary for implementation to work. No scope creep.

## Issues Encountered
None beyond the two blocking issues auto-fixed above.

## Next Phase Readiness
- All 6 ingest sources implemented and tested
- run_ingest.py ready to run: `python ingest/run_ingest.py --sources kb_articles` or `python ingest/run_ingest.py` for all
- 01-04 (embed_trello_card) can use add_documents + delete_by_source_type from vectorstore.py
- Phase 2 (domain expert chat) can query mcsl_knowledge once ingest runs

---
*Phase: 01-foundation*
*Completed: 2026-04-15*
