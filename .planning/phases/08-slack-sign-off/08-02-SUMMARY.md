---
phase: 08-slack-sign-off
plan: 02
subsystem: pipeline
tags: [bug-reporter, slack-dm, trello, tdd, mcsl]
dependency_graph:
  requires: []
  provides: [pipeline/bug_reporter.py, TrelloClient.get_card_members]
  affects: [08-03-sign-off-tab]
tech_stack:
  added: [langchain_anthropic, langchain_core]
  patterns: [TDD red-green, never-raises pattern, RAG-backed Claude call]
key_files:
  created:
    - pipeline/bug_reporter.py
  modified:
    - pipeline/trello_client.py
    - tests/test_pipeline.py
decisions:
  - "notify_devs_of_bug() returns dict (sent_count, error) and never raises — matches plan spec"
  - "BUG_DM_PROMPT and DOMAIN_EXPERT_PROMPT reference MCSL Shopify App, not FedEx"
  - "Code RAG uses storepepsaas_server + storepepsaas_client source types (MCSL-specific)"
  - "get_card_members() returns empty list (not raises) when API returns non-list data"
metrics:
  duration: 11 min
  completed: 2026-04-18
  tasks_completed: 2
  files_changed: 3
---

# Phase 8 Plan 2: bug_reporter + TrelloClient.get_card_members Summary

Bug reporter for MCSL QA Pipeline implementing `notify_devs_of_bug()` (Slack DMs per Trello card member) and `ask_domain_expert()` (RAG + Claude Sonnet Q&A), plus `TrelloClient.get_card_members()` fetching `/1/cards/{id}/members`.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | TDD RED — 3 SLACK-02 failing tests | 797f232 | tests/test_pipeline.py |
| 2 | TDD GREEN — bug_reporter.py + get_card_members() | cce582e | pipeline/bug_reporter.py, pipeline/trello_client.py |

## Verification

- `notify_devs_of_bug` and `ask_domain_expert` both exported at lines 58, 97
- `storepepsaas_server` and `storepepsaas_client` referenced at lines 116-117
- MCSL branding in prompts — no FedEx references in prompt strings
- `get_card_members()` added to TrelloClient at line 198
- All 3 SLACK-02 tests PASS
- Full suite: 119 passed, 0 failures, 7 skipped

## Deviations from Plan

None - plan executed exactly as written.

## Self-Check: PASSED

- pipeline/bug_reporter.py: FOUND
- pipeline/trello_client.py (get_card_members): FOUND
- Commit 797f232 (RED tests): FOUND
- Commit cce582e (GREEN implementation): FOUND
- 119 passed, 0 failures: VERIFIED
