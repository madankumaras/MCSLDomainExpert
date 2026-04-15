---
phase: 01-foundation
plan: "02"
subsystem: database
tags: [chromadb, langchain, ollama, embeddings, vectorstore, hnsw, rag]

# Dependency graph
requires:
  - phase: 01-01
    provides: config.py with CHROMA_COLLECTION, CHROMA_CODE_COLLECTION, CHROMA_PATH, EMBEDDING_MODEL, OLLAMA_BASE_URL constants
provides:
  - rag/vectorstore.py: mcsl_knowledge ChromaDB collection CRUD (get_vectorstore, add_documents, clear_collection, upsert_documents, delete_by_source_type, search, search_filtered, get_embeddings)
  - rag/code_indexer.py: mcsl_code_knowledge ChromaDB collection CRUD (index_codebase, search_code, get_index_stats, sync_from_git)
  - HNSW overflow prevention config applied to both collections
affects:
  - 01-03 (run_ingest.py calls add_documents and index_codebase)
  - 01-04 (chain.py calls search and search_filtered)
  - all future loaders (write into mcsl_knowledge via add_documents)

# Tech tracking
tech-stack:
  added:
    - chromadb>=0.5.0
    - langchain-chroma>=0.1.0
    - langchain-ollama>=0.2.0
    - langchain-text-splitters>=0.3.0
  patterns:
    - ChromaDB singleton pattern with _reset_ function for test isolation
    - HNSW config: hnsw:M=16, hnsw:batch_size=100, hnsw:sync_threshold=1000 (prevents link_lists.bin overflow)
    - Batch size 500 for add_documents (anti HNSW allocation bug)
    - First-200-char deduplication before insert
    - Stable chunk IDs for upsert semantics (source_type__safe_path__cN)
    - Git-diff incremental sync for code re-indexing

key-files:
  created:
    - rag/vectorstore.py
    - rag/code_indexer.py
  modified:
    - tests/test_vectorstore.py
    - tests/test_code_indexer.py

key-decisions:
  - "HNSW config preserved exactly from FedexDomainExpert — prevents 60-150GB link_lists.bin overflow on Python 3.14+chromadb"
  - "carrier-envs/ added to _SKIP_DIRS in code_indexer.py — contains per-carrier credential .env files that must never be indexed"
  - "venv created at .venv/ for Python package isolation (system pip blocked by PEP 668)"
  - "Source type labels: storepepsaas_server, storepepsaas_client, automation (MCSL-specific, not fedex backend/frontend)"

patterns-established:
  - "Vectorstore singleton: _vectorstore_instance with _reset_vectorstore() for test isolation via monkeypatch"
  - "Code vectorstore singleton: _code_vs_instance with _reset_code_vectorstore() for test isolation"
  - "TDD: write failing tests first, verify RED, then implement, verify GREEN"
  - "_SKIP_DIRS pruned in-place in os.walk to prevent descent into excluded directories"

requirements-completed:
  - INFRA-02

# Metrics
duration: 5min
completed: 2026-04-15
---

# Phase 01 Plan 02: ChromaDB Vectorstore Modules Summary

**Two ChromaDB vectorstore modules with HNSW overflow prevention: mcsl_knowledge (rag/vectorstore.py) and mcsl_code_knowledge (rag/code_indexer.py) with batching, deduplication, and credential-safe skip dirs**

## Performance

- **Duration:** 5 min
- **Started:** 2026-04-15T11:26:33Z
- **Completed:** 2026-04-15T11:31:18Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- rag/vectorstore.py implements full CRUD for mcsl_knowledge collection: get_vectorstore, add_documents (batch 500), _deduplicate (first 200 chars), upsert_documents (stable ID replace), delete_by_source_type (partial re-ingest), search, search_filtered, clear_collection
- rag/code_indexer.py implements mcsl_code_knowledge collection with index_codebase, search_code, get_index_stats, sync_from_git (git-diff incremental re-index), _walk_code_files with MCSL-specific skip dirs
- HNSW config (hnsw:M=16, batch_size=100, sync_threshold=1000) applied to both collections — prevents 60-150GB link_lists.bin sparse file overflow on Python 3.14+chromadb
- All 6 non-integration tests pass (3 vectorstore + 3 code_indexer); 2 integration tests explicitly skipped

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement rag/vectorstore.py for mcsl_knowledge collection** - `1c32594` (feat)
2. **Task 2: Implement rag/code_indexer.py for mcsl_code_knowledge collection** - `e0f6a7f` (feat)

**Plan metadata:** (docs commit — see below)

_Note: Both tasks followed TDD: RED (failing tests) → GREEN (implementation passing)_

## Files Created/Modified
- `rag/vectorstore.py` - mcsl_knowledge ChromaDB collection CRUD with HNSW config, batch 500, dedup, upsert, delete_by_source_type
- `rag/code_indexer.py` - mcsl_code_knowledge collection with walk+index, search, git-diff sync, MCSL _SKIP_DIRS
- `tests/test_vectorstore.py` - Wave 1 tests activated: test_both_collections, test_deduplicate, test_search_returns_empty_on_empty_collection
- `tests/test_code_indexer.py` - Wave 1 tests activated: test_skip_dirs, test_index_nonexistent_path, test_search_returns_empty_on_empty_collection

## Decisions Made
- HNSW config preserved exactly from FedexDomainExpert — prevents 60-150GB link_lists.bin overflow on Python 3.14+chromadb
- carrier-envs/ added to _SKIP_DIRS in code_indexer.py — contains per-carrier credential .env files (ups.env, usps-ship.env, amazon.env, etc.) that must never be indexed
- venv created at .venv/ for Python package isolation (system pip blocked by PEP 668 on this macOS install)
- Source type labels use MCSL-specific names: storepepsaas_server, storepepsaas_client, automation (not FedEx backend/frontend)

## Deviations from Plan

None — plan executed exactly as written. The venv creation was a Rule 3 (blocking) auto-fix: pip install was blocked by PEP 668 system package protection, so a venv was created at .venv/ to install all requirements. This is consistent with good Python hygiene and the blocker in STATE.md ("langchain, chromadb not yet installed system-wide").

## Issues Encountered
- System pip blocked by PEP 668 (macOS Homebrew Python) — resolved by creating .venv/ virtualenv and installing requirements there. Tests and imports verified using .venv/bin/pytest and .venv/bin/python3.

## User Setup Required
None — no external service configuration required for this plan. Ollama must be running for embeddings at runtime, but no additional setup needed for the module implementations themselves.

## Next Phase Readiness
- rag/vectorstore.py is ready for Plan 03 (run_ingest.py) to call add_documents(), delete_by_source_type(), upsert_documents()
- rag/code_indexer.py is ready for Plan 03 to call index_codebase() for storepepsaas server, client, and automation repo
- Both modules verified to import cleanly and pass all unit tests
- Note: All tests must be run with .venv/bin/pytest (not system pytest) until venv is activated in CI or shell

---
*Phase: 01-foundation*
*Completed: 2026-04-15*
