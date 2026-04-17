---
phase: 06-user-story-move-cards-history
plan: 01
subsystem: pipeline
tags: [anthropic, langchain, trello, rag, user-story, tdd]

requires:
  - phase: 05-full-dashboard-ui
    provides: tab stubs (tab_us, tab_devdone) that consume these modules

provides:
  - pipeline/user_story_writer.py — generate_user_story(), refine_user_story(), US_WRITER_PROMPT, US_REFINE_PROMPT
  - pipeline/trello_client.py — TrelloClient with move_card_to_list_by_id (direct PUT), TrelloCard, TrelloList dataclasses

affects: [06-02-user-story-tab, 06-03-move-cards-tab, 06-04-history-tab]

tech-stack:
  added: [requests (already in venv), langchain-anthropic, langchain-core]
  patterns:
    - RAG helpers wrap exceptions → fallback string (never crash Claude generation)
    - TrelloClient _auth property returns auth dict; _get/_post/_put share it via params=
    - move_card_to_list_by_id is distinct from move_card_to_list — zero name resolution

key-files:
  created:
    - pipeline/user_story_writer.py
    - pipeline/trello_client.py
  modified:
    - tests/test_pipeline.py (RED commit already existed; this is GREEN)

key-decisions:
  - "move_card_to_list_by_id calls PUT /1/cards/{card_id} directly with idList=list_id — no name lookup, prevents stale-list-name errors"
  - "US_WRITER_PROMPT references MCSL multi-carrier (FedEx, UPS, DHL, USPS) not FedEx-only — avoids incorrect domain framing"
  - "_fetch_domain_context and _fetch_code_context catch ALL exceptions and return fallback strings — generate_user_story never crashes on empty RAG"
  - "TrelloClient accepts constructor args (api_key, token, board_id) for testability; falls back to env vars when None"

patterns-established:
  - "RAG context helpers: try/except around vectorstore.search + code_indexer.search_code, return placeholder on any failure"
  - "Trello _auth property pattern: single dict returned, merged into every request via {**self._auth, **params}"

requirements-completed: [US-01, US-02, US-03, MC-01]

duration: 8min
completed: 2026-04-17
---

# Phase 6 Plan 01: User Story Writer + Trello Client Summary

**MCSL-branded user story generator (Claude + RAG with graceful fallback) and full Trello REST wrapper with direct move_card_to_list_by_id — 8 tests GREEN, 3 history tests skip pending 06-03**

## Performance

- **Duration:** 8 min
- **Started:** 2026-04-17T08:25:00Z
- **Completed:** 2026-04-17T08:33:00Z
- **Tasks:** 1 (GREEN implementation — RED was pre-committed)
- **Files modified:** 2

## Accomplishments

- `pipeline/user_story_writer.py` implemented with MCSL multi-carrier prompts, RAG context fetching (vectorstore + code_indexer), and graceful exception handling when collections are empty
- `pipeline/trello_client.py` implemented with TrelloCard/TrelloList dataclasses, full method set including `move_card_to_list_by_id` (direct PUT, no name lookup), and constructor-arg testability pattern
- Full test suite: 84 passed, 10 skipped — all 15 pre-existing tests still pass

## Task Commits

1. **GREEN — user_story_writer + trello_client** - `0221977` (feat)

## Files Created/Modified

- `/Users/madan/Documents/MCSLDomainExpert/.claude/worktrees/objective-archimedes/pipeline/user_story_writer.py` — generate_user_story(), refine_user_story(), US_WRITER_PROMPT, US_REFINE_PROMPT, _get_claude(), _fetch_domain_context(), _fetch_code_context()
- `/Users/madan/Documents/MCSLDomainExpert/.claude/worktrees/objective-archimedes/pipeline/trello_client.py` — TrelloClient, TrelloCard, TrelloList; methods: get_lists, get_list_by_name, create_list, get_board_members, get_cards_in_list, create_card_in_list, move_card_to_list, move_card_to_list_by_id, add_comment, update_card_description

## Decisions Made

- `move_card_to_list_by_id` kept separate from `move_card_to_list` — direct ID path avoids stale-name resolution; UI 06-03 will always use the by_id variant
- US prompts reference "FedEx, UPS, DHL, USPS" explicitly to ground Claude in multi-carrier context rather than single-carrier framing
- `_fetch_domain_context` / `_fetch_code_context` use broad `except Exception` catch — RAG unavailability must never surface as a user-visible error in story generation

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required for this plan.

## Next Phase Readiness

- `pipeline/user_story_writer.py` ready for 06-02 (User Story tab) — call `generate_user_story(request)` and `refine_user_story(prev, change)`
- `pipeline/trello_client.py` ready for 06-03 (Move Cards tab) — instantiate `TrelloClient()` from env, call `move_card_to_list_by_id(card_id, list_id)` then `add_comment(card_id, text)`
- 06-03 must implement `_save_history` / `_load_history` in `pipeline_dashboard.py` to unblock the 3 skipped history tests

---
*Phase: 06-user-story-move-cards-history*
*Completed: 2026-04-17*

## Self-Check: PASSED

- pipeline/user_story_writer.py: FOUND
- pipeline/trello_client.py: FOUND
- Commit 0221977: FOUND (feat(06-01): implement user_story_writer and trello_client — GREEN)
- 8 tests PASS, 3 SKIP, 0 FAIL in test_pipeline.py
- Full suite: 84 passed, 10 skipped, 0 failed
