---
plan: 01-05
phase: 01-foundation
status: complete
completed: 2026-04-15
---

# Summary: Plan 01-05 — Domain Expert Chat

## What was built

- **`rag/prompts.py`** — MCSL-specific QA prompt with 200-word cap, no FedEx references; CONDENSE_QUESTION_PROMPT unchanged (generic)
- **`rag/chain.py`** — `SimpleConversationalChain` with 6-source `_SOURCE_LABELS` for MCSL, `build_chain()`, `ask()`, `get_llm()`
- **`ui/chat_app.py`** — Streamlit chat UI with MCSL quick-asks (UPS, DHL, FedEx label, bulk label, auto-generate, packing); sys.path fix on line 12
- **`ui/__init__.py`** — empty package init

## Tests

```
tests/test_chat.py — 4 passed, 2 skipped
  test_prompts_contain_mcsl_not_fedex  PASSED
  test_source_labels_mcsl              PASSED
  test_source_labels_all_six_types     PASSED
  test_condense_question_prompt_has_placeholders  PASSED
  test_domain_expert_answers_mcsl_question  SKIPPED (integration)
  test_response_under_200_words        SKIPPED (integration)
```

## Key decisions

- `_SOURCE_LABELS` includes both `storepepsaas_server` and `storepepsaas_client` in addition to the 6 core types (kb_articles, wiki, sheets, trello_card, storepepsaas, automation) — forward-compatible with ingest pipeline
- QA_PROMPT lists carriers generically ("All supported carriers and their specific configuration flows") to avoid any FedEx brand in the MCSL-domain system prompt
- sys.path.insert on line 12 (after module docstring + `from __future__`) — satisfies plan requirement of "first 15 lines"

## Human checkpoint

Pending user verification:
1. `streamlit run ui/chat_app.py` from project root
2. Verify page title = "MCSL Domain Expert"
3. Quick-ask "How do I add a UPS account?" → MCSL-specific answer ≤200 words
4. Source attribution shows MCSL sources (KB Articles, MCSL Internal Wiki, etc.)
