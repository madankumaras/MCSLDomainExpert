# Roadmap: MCSLDomainExpert

## Overview

MCSLDomainExpert is built in four phases that mirror the FedexDomainExpert architecture while adding multi-carrier awareness. Phase 1 establishes the knowledge foundation — ChromaDB collections, RAG ingestion, and project infrastructure — so that every downstream component has domain knowledge to draw on. Phase 2 builds the AI QA Agent core: the agentic browser loop, multi-carrier planning, and carrier-specific special service flows. Phase 3 layers the full label generation, document verification, and pre-requirements scaffolding on top of the working agent. Phase 4 wires it all into the Streamlit Pipeline Dashboard with threading, stop button, and live progress reporting. By the end of Phase 4, the system can autonomously verify any MCSL AC scenario across all supported carriers with clear pass/fail evidence.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Foundation** - Config, ChromaDB setup, knowledge base ingestion, and Domain Expert Chat
- [x] **Phase 2: AI QA Agent Core** - Agentic browser loop, multi-carrier planning, and carrier-specific flows (completed 2026-04-16)
- [ ] **Phase 3: Label + Docs + Pre-Requirements** - Label generation flows, document verification strategies, and pre-requirement injection
- [ ] **Phase 4: Pipeline Dashboard** - Streamlit UI, threading, stop button, and full pipeline orchestration

## Phase Details

### Phase 1: Foundation
**Goal**: The knowledge base is ingested and queryable; Domain Expert Chat answers MCSL questions using RAG retrieval
**Depends on**: Nothing (first phase)
**Requirements**: RAG-01, RAG-02, RAG-03, RAG-04, RAG-05, RAG-06, RAG-07, INFRA-01, INFRA-02, INFRA-03, INFRA-04, INFRA-05
**Success Criteria** (what must be TRUE):
  1. Running `python ingest/run_ingest.py` successfully indexes MCSL knowledge base articles, TC sheet, and automation codebase into `mcsl_knowledge` and `mcsl_code_knowledge` ChromaDB collections with no errors
  2. Partial re-ingest (`--sources wiki shopify_actions`) completes and adds only the specified sources without duplicating existing embeddings
  3. Domain Expert Chat returns a relevant, ≤200-word answer to any MCSL-specific question (e.g. "How do I add a UPS account?") using retrieved RAG context
  4. After a simulated approved Trello card cycle, the card's AC and test cases appear in ChromaDB and are retrievable by the chat
  5. All environment variables load correctly via explicit dotenv path — no silent failures when the app is launched from any working directory
**Plans**: 5 plans

Plans:
- [x] 01-01: Project scaffold — directory structure, config.py, .env template, explicit dotenv path
- [ ] 01-02: ChromaDB setup — mcsl_knowledge and mcsl_code_knowledge collections, vectorstore.py, code_indexer.py
- [ ] 01-03: Ingest pipeline — run_ingest.py with 5 sources: KB articles (docs/kb_snapshots/), TC sheet (Google Sheets), MCSL wiki (/Users/madan/Documents/mcsl-wiki/wiki/), storepepSAAS codebase (server/src/shared/), mcsl-test-automation repo
- [ ] 01-04: RAG auto-updater — rag_updater.py embeds approved Trello card ACs and test cases after each sprint
- [ ] 01-05: Domain Expert Chat — chat_app.py Streamlit UI backed by mcsl_knowledge RAG retrieval

### Phase 2: AI QA Agent Core
**Goal**: The AI QA Agent can extract scenarios from AC text, plan browser actions with carrier awareness, and execute the agentic loop to produce a pass/fail verdict
**Depends on**: Phase 1
**Requirements**: AGENT-01, AGENT-02, AGENT-03, AGENT-04, AGENT-05, AGENT-06, AGENT-07, CARRIER-01, CARRIER-02, CARRIER-03, CARRIER-04, CARRIER-05, CARRIER-06
**Success Criteria** (what must be TRUE):
  1. Given raw AC text, the agent extracts a JSON array of testable scenarios and generates a valid execution plan (nav_clicks, look_for, api_to_watch, order_action, carrier) for each
  2. The agent detects the carrier name from AC text and injects it into the planning prompt — a FedEx AC produces a FedEx-specific plan, a UPS AC produces a UPS-specific plan
  3. The agentic browser loop runs up to 15 steps, capturing AX tree (depth 6, 250 lines) + base64 screenshot + filtered network calls at each step, and produces a verdict (pass/fail/partial/qa_needed)
  4. The agent navigates carrier account configuration (App Settings → Carriers → Add/Edit) and can add or update a carrier account for FedEx, UPS, USPS, or DHL
  5. Carrier-specific special service flows complete without error: FedEx (signature, dry ice, alcohol, battery, HAL, insurance), UPS (signature, insurance, COD), USPS (signature, registered mail), DHL (insurance, signature, international)
  6. Stop flag is checked at each loop iteration — pressing stop during a run halts the agent within one iteration
**Plans**: 7 plans

Plans:
- [ ] 02-01-PLAN.md — smart_ac_verifier.py scaffold: Wave 0 test stubs, scenario extractor, domain expert query, planning prompt with carrier injection
- [ ] 02-02-PLAN.md — Agentic browser loop: Playwright setup, iframe-aware AX tree, screenshot, network filter
- [ ] 02-03-PLAN.md — Action handlers: observe, click (8-strategy), fill, scroll, navigate (MCSL URL map), switch_tab, close_tab, verify, qa_needed; _decide_next Claude invocation
- [ ] 02-04-PLAN.md — Multi-carrier planning: hardened carrier detection (7 carriers), carrier context in plan+decision prompts, CARRIER-02 account config flow and helper
- [ ] 02-05-PLAN.md — Carrier special service flows: _get_preconditions() for FedEx/UPS/USPS/DHL with MCSL label flow references; human verify checkpoint
- [ ] 02-06-PLAN.md — Order creator: order_creator.py reads SIMPLE_PRODUCTS_JSON from carrier-env files (not productsconfig.json), Shopify REST API, single + bulk
- [ ] 02-07-PLAN.md — Stop flag integration and verdict reporting: verify_ac() fully wired, VerificationReport.to_dict(), full test suite green

### Phase 3: Label + Docs + Pre-Requirements
**Goal**: The agent correctly handles all label generation flows, verifies documents using all five strategies, and injects hardcoded pre-requirements for scenario types that need app-level setup before label generation
**Depends on**: Phase 2
**Requirements**: LABEL-01, LABEL-02, LABEL-03, LABEL-04, LABEL-05, DOC-01, DOC-02, DOC-03, DOC-04, DOC-05, PRE-01, PRE-02, PRE-03, PRE-04, PRE-05, PRE-06
**Success Criteria** (what must be TRUE):
  1. The agent generates a label end-to-end via Manual flow (ORDERS tab → filter by Order Id → order link → Order Summary → Generate Label → LABEL CREATED) and confirms the "label generated" badge appears on Order Summary
  2. The agent generates labels via Auto-Generate, Bulk (Orders list → select all → Actions → Generate Labels), and Return Label flows — each completes without requiring human intervention
  3. All five document verification strategies produce readable output: badge check (DOC-01), ZIP download read (DOC-02), 3-dots → View Log → dialogHalfDivParent XML/JSON (DOC-03), Print Documents new-tab screenshot with visual label codes (DOC-04), and rate log screenshot (DOC-05)
  4. For a dry ice scenario, the agent automatically enables "Is Dry Ice Needed" on AppProducts before generating the label and unchecks it after — without human prompting
  5. Pre-requirements are injected and cleaned up correctly for all six scenario types: dry ice, alcohol, battery, signature, HAL, and insurance
**Plans**: 6 plans

Plans:
- [ ] 03-01: Manual label flow — App order grid → ORDERS tab → filter by Order ID → order link → Order Summary → Generate Label → LABEL CREATED
- [ ] 03-02: Auto-generate and return label flows — LABEL-02, LABEL-04
- [ ] 03-03: Bulk label generation — LABEL-03 (header checkbox → Generate labels button → Label Batch page)
- [ ] 03-04: Document verification strategies — DOC-01 badge, DOC-02 Download Documents ZIP, DOC-03 3-dots → View Log → dialogHalfDivParent, DOC-04 Print Documents new tab, DOC-05 rate log
- [ ] 03-05: download_zip and download_file action handlers — ZIP intercept, unzip, read JSON/CSV/XML/TXT/log; direct file intercept
- [ ] 03-06: Pre-requirements resolver — _get_preconditions() for dry ice, alcohol, battery, signature, HAL, insurance with cleanup steps

### Phase 4: Pipeline Dashboard
**Goal**: The Streamlit Pipeline Dashboard orchestrates the full Trello → AC → AI QA Agent → Test Generation workflow with a responsive UI, live progress, and functional stop button
**Depends on**: Phase 3
**Requirements**: DASH-01, DASH-02, DASH-03, DASH-04, DASH-05
**Success Criteria** (what must be TRUE):
  1. A user can enter a Trello card URL in the dashboard and trigger the full pipeline: AC writing → AI QA Agent verification → report — without touching the terminal
  2. The AI QA Agent runs in a background thread so the Streamlit UI remains interactive during verification (progress bar updates, stop button clickable)
  3. Clicking the stop button during an active run halts the agent within one loop iteration and displays a "stopped" status in the UI
  4. The dashboard displays a per-scenario report with pass/fail/partial/qa_needed status, finding text, and screenshot evidence for each scenario
  5. Progress bar and live status text update as each scenario completes, giving the user a real-time view of verification progress
**Plans**: 5 plans

Plans:
- [ ] 04-01: pipeline_dashboard.py scaffold — Streamlit layout, Trello card input, pipeline trigger
- [ ] 04-02: Background threading — thread launch, session state keys (sav_running, sav_stop, sav_result, sav_prog)
- [ ] 04-03: Stop button and progress bar — stop flag propagation, sav_prog updates, UI polling
- [ ] 04-04: Report display — per-scenario verdict rendering with pass/fail badges, finding text, screenshot thumbnails
- [ ] 04-05: Full pipeline wiring — Trello → card_processor → smart_ac_verifier → report → sign-off flow

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation | 4/5 | In Progress|  |
| 2. AI QA Agent Core | 7/7 | Complete   | 2026-04-16 |
| 3. Label + Docs + Pre-Requirements | 5/6 | In Progress|  |
| 4. Pipeline Dashboard | 0/5 | Not started | - |
