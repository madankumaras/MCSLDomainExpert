# Roadmap: MCSLDomainExpert

## Overview

MCSLDomainExpert is built in ten phases. Phases 1–4 mirror the FedexDomainExpert architecture while adding multi-carrier awareness: Phase 1 establishes the knowledge foundation, Phase 2 builds the AI QA Agent core, Phase 3 layers label generation and pre-requirements, and Phase 4 wires everything into a basic Streamlit dashboard. Phases 5–10 expand the dashboard into full feature parity with the FedEx QA Pipeline: a 7-tab Streamlit app with User Story writing, Move Cards, Release QA, History, Sign Off, Write Automation, and Run Automation — plus a standalone Domain Expert Chat. By the end of Phase 10, the MCSL QA Pipeline matches the FedEx dashboard end-to-end.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Foundation** - Config, ChromaDB setup, knowledge base ingestion, and Domain Expert Chat
- [x] **Phase 2: AI QA Agent Core** - Agentic browser loop, multi-carrier planning, and carrier-specific flows (completed 2026-04-16)
- [ ] **Phase 3: Label + Docs + Pre-Requirements** - Label generation flows, document verification strategies, and pre-requirement injection
- [x] **Phase 4: Pipeline Dashboard** - Streamlit UI, threading, stop button, and full pipeline orchestration (completed 2026-04-17)
- [x] **Phase 5: Full Dashboard UI** - 7-tab Streamlit app, MCSL branding, sidebar status/progress/KB sections (completed 2026-04-17)
- [ ] **Phase 6: User Story + Move Cards + History** - User Story generation, AC refinement, Move Cards, History persistence
- [x] **Phase 7: Release QA Pipeline Core** - Release QA tab, per-card AC/validation/AI QA Agent, test case approval (completed 2026-04-17)
- [x] **Phase 8: Slack + Sign Off** - Slack DM/channel integration, bug notifications, Sign Off tab (completed 2026-04-18)
- [x] **Phase 9: Automation Writing** - Write Automation tab, Playwright POM+spec generation, Chrome Agent, git push (completed 2026-04-18)
- [x] **Phase 10: Run Automation + Domain Expert Chat** - Run Automation tab, test results, Domain Expert Chat app (completed 2026-04-18)

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

### Phase 5: Full Dashboard UI
**Goal**: Rebuild pipeline_dashboard.py as a 7-tab Streamlit app matching the FedEx QA Pipeline dashboard structure, with MCSL branding and all tabs scaffolded
**Depends on**: Phase 4
**Requirements**: UI-01, UI-02, UI-03, UI-04, UI-05, UI-06, UI-07
**Success Criteria**:
  1. App launches with 7 tabs: User Story, Move Cards, Release QA, History, Sign Off, Write Automation, Run Automation
  2. Sidebar shows System Status (Claude API, Trello, Slack, Google Sheets, Ollama) with live badge checks
  3. Sidebar shows Release Progress section (cards/TCs/approved/automation counters + progress bar)
  4. Sidebar shows Code Knowledge Base section (Automation/Backend/Frontend repo sync)
  5. Dark theme, MCSL branding header ("🚚 MCSL QA Pipeline"), wide layout
**Plans**: 3 plans

Plans:
- [ ] 05-01: App shell — 7-tab layout, MCSL branding, page config, global CSS
- [ ] 05-02: Sidebar — System Status badges, Release Progress, Knowledge Base sections
- [ ] 05-03: Tab scaffolds — placeholder content for all 7 tabs with correct session state keys

### Phase 6: User Story + Move Cards + History
**Goal**: User Story tab (generate AC from description, refine, push to Trello), Move Cards tab (move between lists), History tab (persisted pipeline runs)
**Depends on**: Phase 5
**Requirements**: US-01, US-02, US-03, MC-01, HIST-01
**Success Criteria**:
  1. User can type a feature description and get a User Story + AC generated by Claude
  2. User can refine the generated AC with a change request
  3. Generated AC can be pushed to a new or existing Trello card
  4. Move Cards tab loads cards from source list and moves selected to target list
  5. Every approved card is saved to data/pipeline_history.json and shown in History tab
**Plans**: 3 plans

Plans:
- [ ] 06-01: pipeline/user_story_writer.py — generate_user_story(), refine_user_story()
- [ ] 06-02: User Story tab UI — textarea, Generate, Refine loop, Push to Trello
- [ ] 06-03: Move Cards tab + History tab

### Phase 7: Release QA Pipeline Core
**Goal**: Release QA tab — load Trello cards, per-card AC generation, Domain Expert validation, AI QA Agent verification (threaded), test case generation and approval
**Depends on**: Phase 6
**Requirements**: RQA-01, RQA-02, RQA-03, RQA-04, RQA-05
**Success Criteria**:
  1. User selects a Trello list → cards load with release health summary
  2. Per-card: Generate AC → validate with domain expert → run AI QA Agent in background thread
  3. AI QA Agent results show per-scenario verdict with bug report + re-verify capability
  4. Generate Test Cases → review → Approve (saves to Trello + Google Sheets)
  5. Release analysis (risk level, cross-card conflicts, coverage gaps) shown on card load
**Plans**: 4 plans

Plans:
- [ ] 07-01: pipeline/domain_validator.py — validate_card() using RAG + Claude
- [ ] 07-02: pipeline/release_analyser.py — analyse_release() cross-card analysis
- [ ] 07-03: Release QA tab — card load, per-card AC + validation + AI QA Agent UI
- [ ] 07-04: Test case generation + approval + Google Sheets write

### Phase 8: Slack + Sign Off
**Goal**: Slack integration (DM, channels, bug notifications, sign-off), Sign Off tab (compose message, mark Trello done, export to Sheets)
**Depends on**: Phase 7
**Requirements**: SLACK-01, SLACK-02, SIGNOFF-01, SIGNOFF-02
**Success Criteria**:
  1. AC and test cases can be sent via Slack DM or posted to a channel
  2. Bug reports are DMed to developers automatically from AI QA Agent results
  3. Sign Off tab composes a formatted Slack message with card checkboxes and bug list
  4. "Send Sign-Off" posts to Slack and marks all approved cards as QA-done in Trello
**Plans**: 3 plans

Plans:
- [ ] 08-01: pipeline/slack_client.py — send_dm(), post_to_channel(), post_signoff(), list_slack_channels()
- [ ] 08-02: pipeline/bug_reporter.py — notify_devs_of_bug(), ask_domain_expert()
- [ ] 08-03: Sign Off tab UI

### Phase 9: Automation Writing
**Goal**: Write Automation tab (write Playwright POM + spec from TCs + optional Chrome agent exploration), integrated into Release QA Step 5
**Depends on**: Phase 8
**Requirements**: AUTO-01, AUTO-02, AUTO-03
**Success Criteria**:
  1. User can enter feature name + test cases and generate Playwright automation code
  2. Chrome Agent can explore the live MCSL app and return element/nav data to inform code generation
  3. Generated code can be pushed to a git branch automatically
  4. Write Automation tab works standalone (no Trello card required)
**Plans**: 3 plans

Plans:
- [ ] 09-01: pipeline/automation_writer.py — write_automation() generates POM + spec
- [ ] 09-02: pipeline/feature_detector.py + pipeline/chrome_agent.py (MCSL-specific exploration)
- [ ] 09-03: Write Automation tab UI + Release QA Step 5 integration

### Phase 10: Run Automation + Domain Expert Chat
**Goal**: Run Automation tab (run Playwright specs from UI), domain expert chat app for MCSL knowledge queries
**Depends on**: Phase 9
**Requirements**: RUN-01, CHAT-01, CHAT-02
**Success Criteria**:
  1. Run Automation tab shows spec files grouped by folder with checkboxes, runs selected specs
  2. Test results (pass/fail/duration) shown in UI with "Post to Slack" button
  3. Domain Expert Chat answers questions about the MCSL app using RAG over docs + codebase
  4. Quick Questions sidebar buttons cover common MCSL queries (label generation, carrier config, etc.)
**Plans**: 3 plans

Plans:
- [ ] 10-01-PLAN.md — pipeline/test_runner.py: SpecResult, TestRunResult, enumerate_specs, parse_playwright_json, run_release_tests (TDD, Wave 1)
- [ ] 10-02-PLAN.md — ui/chat_app.py: ask_domain_expert() export + CHAT-01/CHAT-02 test stubs (TDD, Wave 1)
- [ ] 10-03-PLAN.md — pipeline_dashboard.py: Run Automation tab full implementation + human verify checkpoint (Wave 2)

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation | 4/5 | In Progress|  |
| 2. AI QA Agent Core | 7/7 | Complete   | 2026-04-16 |
| 3. Label + Docs + Pre-Requirements | 5/6 | In Progress|  |
| 4. Pipeline Dashboard | 5/5 | Complete   | 2026-04-17 |
| 5. Full Dashboard UI | 3/3 | Complete   | 2026-04-17 |
| 6. User Story + Move Cards + History | 2/3 | In Progress|  |
| 7. Release QA Pipeline Core | 4/4 | Complete   | 2026-04-17 |
| 8. Slack + Sign Off | 3/3 | Complete   | 2026-04-18 |
| 9. Automation Writing | 3/3 | Complete   | 2026-04-18 |
| 10. Run Automation + Domain Expert Chat | 3/3 | Complete    | 2026-04-18 |
