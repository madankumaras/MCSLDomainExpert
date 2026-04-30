# MCSL Domain Expert

Streamlit-based QA orchestration for the Shopify Multi-Carrier Shipping Label app.

This repo follows the FedEx workflow shape where that improves QA throughput, but all reasoning, validation, and execution stay MCSL-native.

## What This App Does

The dashboard helps QA move a release through these stages:
1. load Trello release cards
2. validate and refine AC
3. generate and publish test cases
4. run AI QA verification
5. generate or update automation
6. run automation, post results, generate docs, and raise bugs
7. prepare sign-off and handoff output

Entrypoint:
- [pipeline_dashboard.py](/Users/madan/Documents/MCSLDomainExpert/pipeline_dashboard.py:1)

## Current Dashboard Tabs

Top-level tabs:
1. `📝 User Story`
2. `🔀 Move Cards`
3. `🧾 Validate AC`
4. `🧪 Generate TC`
5. `🤖 AI QA Verifier`
6. `⚙️ Generate Automation Script`
7. `📋 History`
8. `✅ Sign Off`
9. `📘 Handoff Docs`

Planned next major workflow:
- `🚚 New Carrier Validation`
  - create store
  - install app
  - manual carrier registration checkpoint
  - create required Shopify products
  - generate carrier env file with product IDs
  - run smoke / sanity / regression
  - publish readiness report

## Current QA Flow

Shared release state is loaded in `🧾 Validate AC` and reused in downstream tabs.

### `🧾 Validate AC`
- select Trello board, list, and release label
- click `Load Cards`
- auto-run per-card MCSL validation and diagnosis
- auto-run release-level `Release Intelligence`
- show `Step 1: Card Requirements`
- run MCSL-specific toggle/store-state handling when needed
- generate or review `AI Suggested User Story & AC`
- save, comment, skip, or share AC
- run `Domain Validation`
- apply fixes and re-validate

Important current behavior:
- there is no separate manual `Analyze loaded cards` step
- generated AC is revalidated immediately
- fix and revalidate preserve requirement research context

### `🧪 Generate TC`
- generate test cases from the current AC draft in session
- reuse saved TCs when present
- regenerate with reviewer feedback
- support manual edits and explicit re-review
- share to Slack DM or channel
- publish full QA summary to Trello
- publish positive TCs to Google Sheets
- perform duplicate checks before sheet write

Important current behavior:
- TC generation does not rely only on stale `card.desc` when a newer AC draft exists
- retry after partial publish failure should not duplicate the Trello summary comment

### `🤖 AI QA Verifier`
- runs TC-first AI QA against the live app
- reuses generated and reviewed test cases
- supports `qa_needed` follow-up and reruns
- supports failed-finding review and notify-dev flow
- supports ask-domain-expert
- persists final approval for downstream automation and sign-off

### `⚙️ Generate Automation Script`
- `① Write Automation Code`
- detect existing-vs-new automation targets with `feature_detector` and `find_pom`
- optional Chrome-agent exploration for locator grounding
- auto-fix loop for generated code
- `② Run Automation & Post to Slack`
- `③ Generate Documentation`
- `🐛 Bug Reporter` for manual QA-found bugs

## MCSL-Specific Rules

### Validation And Analysis

These stay MCSL-native:
- `validate_card(...)`
- `diagnose_customer_ticket(...)`
- `analyse_release(...)`
- `build_requirement_research_context(...)`

FedEx parity work should change workflow shape and UX order, not replace MCSL rules with FedEx rules.

### Toggle Flow

MCSL toggle handling is intentionally different from FedEx.

Current behavior:
- detect toggle details from card title, description, and comments
- derive default store and app URL from MCSL carrier knowledge
- capture live store and toggle state from the app when QA refreshes it
- extract `store_uuid`, `account_uuid`, and toggle state from app or API responses
- compute missing-vs-enabled toggles before notifying
- notify Ashok or the assigned developer through Slack
- poll for confirmation and unblock QA when confirmed

Key files:
- [pipeline/toggle_state.py](/Users/madan/Documents/MCSLDomainExpert/pipeline/toggle_state.py:1)
- [tests/test_toggle_state.py](/Users/madan/Documents/MCSLDomainExpert/tests/test_toggle_state.py:1)

### Automation Matching

Automation generation should prefer updating existing MCSL automation when a matching area already exists.

Key files:
- [pipeline/automation_writer.py](/Users/madan/Documents/MCSLDomainExpert/pipeline/automation_writer.py:1)
- [pipeline/feature_detector.py](/Users/madan/Documents/MCSLDomainExpert/pipeline/feature_detector.py:1)

## Important Files

- [pipeline_dashboard.py](/Users/madan/Documents/MCSLDomainExpert/pipeline_dashboard.py:1)
- [pipeline/card_processor.py](/Users/madan/Documents/MCSLDomainExpert/pipeline/card_processor.py:1)
- [pipeline/smart_ac_verifier.py](/Users/madan/Documents/MCSLDomainExpert/pipeline/smart_ac_verifier.py:1)
- [pipeline/domain_validator.py](/Users/madan/Documents/MCSLDomainExpert/pipeline/domain_validator.py:1)
- [pipeline/automation_writer.py](/Users/madan/Documents/MCSLDomainExpert/pipeline/automation_writer.py:1)
- [pipeline/feature_detector.py](/Users/madan/Documents/MCSLDomainExpert/pipeline/feature_detector.py:1)
- [pipeline/doc_generator.py](/Users/madan/Documents/MCSLDomainExpert/pipeline/doc_generator.py:1)
- [pipeline/bug_tracker.py](/Users/madan/Documents/MCSLDomainExpert/pipeline/bug_tracker.py:1)
- [pipeline/request_expectations.py](/Users/madan/Documents/MCSLDomainExpert/pipeline/request_expectations.py:1)
- [pipeline/carrier_knowledge.py](/Users/madan/Documents/MCSLDomainExpert/pipeline/carrier_knowledge.py:1)

## Local References

Expected local comparison repo:
- `../Fed-Ex-automation/FedexDomainExpert`

Expected local automation repo:
- `config.MCSL_AUTOMATION_REPO_PATH`

## Run Locally

```bash
cd /Users/madan/Documents/MCSLDomainExpert
PYTHONPATH=. .venv/bin/streamlit run pipeline_dashboard.py
```

## Focused Validation Commands

```bash
python3 -m py_compile pipeline_dashboard.py pipeline/card_processor.py
pytest -q tests/test_dashboard.py::test_dash01_scaffold
pytest -q tests/test_dashboard.py::test_ui10b_validate_ac_matches_fedex_auto_analysis_flow
pytest -q tests/test_dashboard.py::test_ui10c_generate_tc_uses_current_ac_and_avoids_duplicate_trello_publish
pytest -q tests/test_toggle_state.py
```

## Supporting Docs

- [CLAUDE.md](/Users/madan/Documents/MCSLDomainExpert/CLAUDE.md:1)
- [docs/FEDEX_FLOW_PARITY_NOTES.md](/Users/madan/Documents/MCSLDomainExpert/docs/FEDEX_FLOW_PARITY_NOTES.md:1)
- [docs/MCSL_PLATFORM_ADAPTATION_PLAN.md](/Users/madan/Documents/MCSLDomainExpert/docs/MCSL_PLATFORM_ADAPTATION_PLAN.md:1)
- [docs/MCSL_CARRIER_KNOWLEDGE_RESEARCH.md](/Users/madan/Documents/MCSLDomainExpert/docs/MCSL_CARRIER_KNOWLEDGE_RESEARCH.md:1)
- [docs/MCSL_CARRIER_SUPPORT_REGISTRY.md](/Users/madan/Documents/MCSLDomainExpert/docs/MCSL_CARRIER_SUPPORT_REGISTRY.md:1)
- [docs/MCSL_CARRIER_CAPABILITY_MATRIX.md](/Users/madan/Documents/MCSLDomainExpert/docs/MCSL_CARRIER_CAPABILITY_MATRIX.md:1)
- [docs/MCSL_CARRIER_REQUEST_REGISTRY.md](/Users/madan/Documents/MCSLDomainExpert/docs/MCSL_CARRIER_REQUEST_REGISTRY.md:1)
- [docs/NEW_CARRIER_VALIDATION_PLAN.md](/Users/madan/Documents/MCSLDomainExpert/docs/NEW_CARRIER_VALIDATION_PLAN.md:1)
