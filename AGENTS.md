# AGENTS.md

Working notes for future agents in this repo.

## Read This First

If docs and code disagree, trust current code, especially:
- [pipeline_dashboard.py](/Users/madan/Documents/MCSLDomainExpert/pipeline_dashboard.py:1)

Use these docs as the current handoff set:
- [README.md](/Users/madan/Documents/MCSLDomainExpert/README.md:1)
- [docs/FEDEX_FLOW_PARITY_NOTES.md](/Users/madan/Documents/MCSLDomainExpert/docs/FEDEX_FLOW_PARITY_NOTES.md:1)
- [docs/MCSL_PLATFORM_ADAPTATION_PLAN.md](/Users/madan/Documents/MCSLDomainExpert/docs/MCSL_PLATFORM_ADAPTATION_PLAN.md:1)
- [docs/MCSL_CARRIER_KNOWLEDGE_RESEARCH.md](/Users/madan/Documents/MCSLDomainExpert/docs/MCSL_CARRIER_KNOWLEDGE_RESEARCH.md:1)

## Repo Intent

This is the MCSL version of the QA orchestration platform.

Do:
- reuse FedEx workflow shape where it helps QA flow
- keep validation, diagnosis, automation targeting, and request reasoning MCSL-native
- prefer current implementation over old planning notes

Do not:
- copy FedEx navigation assumptions into MCSL
- replace MCSL rules with FedEx rules
- treat stale docs as source of truth without checking the dashboard code

## Current Dashboard Split

Keep this split unless the user explicitly asks to change it:
1. `🧾 Validate AC`
2. `🧪 Generate TC`
3. `🤖 AI QA Verifier`
4. `⚙️ Generate Automation Script`

Shared release state is stored in Streamlit session and reused across tabs:
- board
- list
- release label
- loaded cards
- validations
- diagnoses
- release analysis
- AC drafts
- test cases
- AI QA reports
- approvals
- automation outputs

## Validate AC Rules

Current intended flow:
- `Load Cards`
- auto-run MCSL validation, diagnosis, and release analysis
- show `Release Intelligence`
- show `Step 1: Card Requirements`
- run MCSL-specific toggle/store-state handling if needed
- show `AI Suggested User Story & AC`
- show `Domain Validation`
- allow `Apply Fixes to AC`
- allow `Re-validate after fix`

Important:
- there should not be a separate `Analyze loaded cards` button
- generated AC should be revalidated immediately
- fix and revalidate should preserve research context
- MCSL toggle flow should remain MCSL-specific

## Generate TC Rules

Current intended flow:
- generate TCs from the current AC draft in session
- reuse existing saved TCs when available
- support feedback-based regeneration
- support manual edits
- support explicit TC re-review after manual edits
- support Slack DM and channel sharing
- publish Trello full summary and positive cases to Sheets

Important:
- do not generate or review TCs only from stale `card.desc` when a newer AC draft exists
- avoid duplicate Trello comments on retry after partial publish failure

## AI QA Rules

Keep TC-first verification as the default path.

Use automation for:
- navigation
- locators
- repeated flows

Use codebase, KB, wiki, request registry, and carrier registries for:
- expectation building
- request and response reasoning
- setup guidance

Do not reduce AI QA back to AC-only execution.

## Automation Rules

Current intended flow:
- `① Write Automation Code`
- `② Run Automation & Post to Slack`
- `③ Generate Documentation`
- `🐛 Bug Reporter`

Current automation matching behavior:
- detect existing-vs-new feature areas
- prefer updating existing MCSL automation coverage
- use `feature_detector` and `find_pom`

## Toggle Rules

Toggle flow is MCSL-specific and already has live-state support.

Current behavior:
- detect toggle details from card text and comments
- derive default store and app URL from MCSL knowledge
- capture live `store_uuid`, `account_uuid`, and toggle state from app or API responses
- compute enabled vs missing toggles
- notify Ashok or developer through Slack
- poll replies and unblock QA when confirmed

If touching toggle flow:
- keep live state as the source of truth when available
- do not regress to store-name-only logic

## Optional Dependency Shims

This repo includes compatibility shims for local test and import stability:
- `streamlit.py`
- `langchain_anthropic/`
- `langchain_core/`
- `chromadb/`
- `langchain_chroma/`
- `langchain_ollama/`
- `langchain_text_splitters/`

Do not remove them casually without checking test coverage and local `.venv` behavior.

## Docs To Keep Updated

When workflow changes materially, update:
- [README.md](/Users/madan/Documents/MCSLDomainExpert/README.md:1)
- [AGENTS.md](/Users/madan/Documents/MCSLDomainExpert/AGENTS.md:1)
- [docs/FEDEX_FLOW_PARITY_NOTES.md](/Users/madan/Documents/MCSLDomainExpert/docs/FEDEX_FLOW_PARITY_NOTES.md:1)
- [docs/MCSL_PLATFORM_ADAPTATION_PLAN.md](/Users/madan/Documents/MCSLDomainExpert/docs/MCSL_PLATFORM_ADAPTATION_PLAN.md:1)

When carrier reasoning changes, also update:
- [docs/MCSL_CARRIER_KNOWLEDGE_RESEARCH.md](/Users/madan/Documents/MCSLDomainExpert/docs/MCSL_CARRIER_KNOWLEDGE_RESEARCH.md:1)
- [docs/MCSL_CARRIER_SUPPORT_REGISTRY.md](/Users/madan/Documents/MCSLDomainExpert/docs/MCSL_CARRIER_SUPPORT_REGISTRY.md:1)
- [docs/MCSL_CARRIER_CAPABILITY_MATRIX.md](/Users/madan/Documents/MCSLDomainExpert/docs/MCSL_CARRIER_CAPABILITY_MATRIX.md:1)
- [docs/MCSL_CARRIER_REQUEST_REGISTRY.md](/Users/madan/Documents/MCSLDomainExpert/docs/MCSL_CARRIER_REQUEST_REGISTRY.md:1)

## Useful Commands

```bash
python3 -m py_compile pipeline_dashboard.py pipeline/card_processor.py
pytest -q tests/test_dashboard.py::test_dash01_scaffold
pytest -q tests/test_dashboard.py::test_ui10b_validate_ac_matches_fedex_auto_analysis_flow
pytest -q tests/test_dashboard.py::test_ui10c_generate_tc_uses_current_ac_and_avoids_duplicate_trello_publish
pytest -q tests/test_toggle_state.py
```
