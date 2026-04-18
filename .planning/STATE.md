---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: planning
stopped_at: Completed 09-03-PLAN.md — push_to_branch() + Write Automation tab UI + Release QA Step 5; 129 tests GREEN
last_updated: "2026-04-18T09:31:09.670Z"
last_activity: 2026-04-17 — Phase 4 complete; Phase 5-10 roadmap and requirements added
progress:
  total_phases: 10
  completed_phases: 8
  total_plans: 35
  completed_plans: 39
  percent: 50
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-15)

**Core value:** AI QA Agent autonomously verifies any MCSL app AC scenario across all supported carriers with clear pass/fail evidence
**Current focus:** Phase 5 — Full Dashboard UI (about to plan)

## Current Position

Phase: 5 of 10 (Full Dashboard UI — not yet started)
Plan: 0 of 3 in current phase
Status: Ready to plan
Last activity: 2026-04-17 — Phase 4 complete; Phase 5-10 roadmap and requirements added

Progress: [█████░░░░░] 50% (plans: 21/42)

## Performance Metrics

**Velocity:**
- Total plans completed: 1
- Average duration: 19 min
- Total execution time: 0.32 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-foundation | 1 | 19 min | 19 min |

**Recent Trend:**
- Last 5 plans: 01-01 (19 min)
- Trend: -

*Updated after each plan completion*
| Phase 01-foundation P01 | 19 | 2 tasks | 19 files |
| Phase 01-foundation P02 | 5 | 2 tasks | 4 files |
| Phase 01-foundation P03 | 6 | 2 tasks | 9 files |
| Phase 02-ai-qa-agent-core P01 | 5 | 2 tasks | 2 files |
| Phase 02-ai-qa-agent-core P02 | 18 | 2 tasks | 2 files |
| Phase 02-ai-qa-agent-core P03 | 7 | 2 tasks | 2 files |
| Phase 02-ai-qa-agent-core P04 | 3 | 2 tasks | 2 files |
| Phase 02-ai-qa-agent-core P05 | 3 | 1 tasks | 1 files |
| Phase 02-ai-qa-agent-core P06 | 25 | 2 tasks | 3 files |
| Phase 02-ai-qa-agent-core P07 | 8 | 2 tasks | 2 files |
| Phase 03-label-docs-pre-requirements P01 | 18 | 2 tasks | 3 files |
| Phase 03-label-docs-pre-requirements P02 | 7 | 2 tasks | 2 files |
| Phase 03-label-docs-pre-requirements P03 | 8 | 1 tasks | 2 files |
| Phase 03-label-docs-pre-requirements P04 | 11 | 2 tasks | 2 files |
| Phase 03-label-docs-pre-requirements P05 | 7 | 2 tasks | 2 files |
| Phase 04-pipeline-dashboard P01 | 14 | 2 tasks | 3 files |
| Phase 04-pipeline-dashboard P02 | 8 | 2 tasks | 2 files |
| Phase 04-pipeline-dashboard P03 | 8 | 2 tasks | 2 files |
| Phase 04-pipeline-dashboard P04 | 5 | 2 tasks | 2 files |
| Phase 04-pipeline-dashboard P05 | 7 | 2 tasks | 3 files |
| Phase 05-full-dashboard-ui P01 | 3 | 2 tasks | 2 files |
| Phase 05-full-dashboard-ui P02 | 1 | 2 tasks | 2 files |
| Phase 05-full-dashboard-ui P03 | 8 | 1 tasks | 2 files |
| Phase 06-user-story-move-cards-history P02 | 2 | 2 tasks | 2 files |
| Phase 06-user-story-move-cards-history P03 | 2 | 2 tasks | 2 files |
| Phase 07-release-qa-pipeline-core P02 | 4 | 2 tasks | 3 files |
| Phase 07-release-qa-pipeline-core P01 | 5 | 2 tasks | 4 files |
| Phase 07-release-qa-pipeline-core P03 | 15 | 2 tasks | 2 files |
| Phase 07-release-qa-pipeline-core P04 | 7 | 1 tasks | 1 files |
| Phase 08-slack-sign-off P02 | 11 | 2 tasks | 3 files |
| Phase 08-slack-sign-off P01 | 12 | 2 tasks | 2 files |
| Phase 08-slack-sign-off P03 | 14 | 2 tasks | 2 files |
| Phase 09-automation-writing P01 | 3 | 2 tasks | 2 files |
| Phase 09-automation-writing P02 | 5 | 2 tasks | 2 files |
| Phase 09-automation-writing P03 | 2 | 2 tasks | 3 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- Init: Clone FedexDomainExpert architecture — 70% of code is reusable; same Shopify iframe structure
- Init: Multi-carrier abstraction — carrier name injected into planning prompt from AC text detection
- Init: Separate ChromaDB collections — mcsl_knowledge + mcsl_code_knowledge (not shared with FedEx project)
- Init: Explicit dotenv path in config.py — required to avoid silent load failures across working directories
- 01-01: ChromaDB collection names mcsl_knowledge + mcsl_code_knowledge established — no fedex_* names
- 01-01: conftest.py uses lazy imports for langchain_core — test_config.py runs without full stack installed
- 01-01: Wave-based skip reasons in test stubs — enables progressive activation across plans
- [Phase 01-foundation]: 01-02: HNSW config hnsw:M=16 batch_size=100 sync_threshold=1000 preserved from FedexDomainExpert — prevents 60-150GB link_lists.bin overflow on Python 3.14+chromadb
- [Phase 01-foundation]: 01-02: carrier-envs/ added to _SKIP_DIRS in code_indexer.py — contains per-carrier credential .env files that must never be indexed
- [Phase 01-foundation]: 01-02: venv created at .venv/ for Python package isolation (system pip blocked by PEP 668)
- [Phase 01-foundation]: 01-02: Source type labels storepepsaas_server + storepepsaas_client + automation (MCSL-specific, not FedEx backend/frontend)
- [Phase 01-foundation]: source_type='sheets' (not 'test_cases') matches --sources arg name
- [Phase 01-foundation]: 6 sources: storepepsaas split into storepepsaas_server + storepepsaas_client for independent re-ingest
- [Phase 01-foundation]: STOREPEPSAAS_SERVER_PATH + STOREPEPSAAS_CLIENT_PATH added to config.py as aliases for per-source ingest
- [Phase 02-ai-qa-agent-core]: 02-01: MCSL label flow uses ORDERS tab (click 'ORDERS' tab → filter by Order Id → order link → Order Summary → Generate Label), NOT Shopify More Actions
- [Phase 02-ai-qa-agent-core]: 02-01: App slug mcsl-qa confirmed in _build_url_map (not testing-553)
- [Phase 02-ai-qa-agent-core]: 02-01: ScenarioResult.carrier field added for carrier-aware reporting downstream
- [Phase 02-ai-qa-agent-core]: 02-01: venv at MCSLDomainExpert/.venv (parent repo), not worktree — absolute path required for pytest
- [Phase 02-ai-qa-agent-core]: 02-02: _network returns str (newline-joined) not list[str] — test contract requires isinstance(net, str)
- [Phase 02-ai-qa-agent-core]: 02-02: ScenarioResult gains finding + evidence_screenshot fields; VerificationStep fields keyword-only with defaults
- [Phase 02-ai-qa-agent-core]: 02-03: download_zip and download_file are Phase 2 stubs (log + return False) — full implementation deferred to Phase 3
- [Phase 02-ai-qa-agent-core]: 02-03: _decide_next falls back to qa_needed when Claude returns unparseable or missing-action JSON response
- [Phase 02-ai-qa-agent-core]: 02-03: _DECISION_PROMPT explicitly forbids Shopify More Actions for MCSL label generation; uses _MCSL_WORKFLOW_GUIDE inline
- [Phase 02-ai-qa-agent-core]: 02-04: Carrier context injected into _DECISION_PROMPT as well as _PLAN_PROMPT so agent is carrier-aware during every browser step
- [Phase 02-ai-qa-agent-core]: 02-04: _get_carrier_config_steps returns a list for composability; _plan_scenario formats it inline when scenario matches CARRIER-02 keywords
- [Phase 02-ai-qa-agent-core]: _SPECIAL_SERVICE_KEYWORDS frozenset added alongside _CARRIER_CONFIG_KEYWORDS for precondition detection
- [Phase 02-ai-qa-agent-core]: preconditions_block appended to _PLAN_PROMPT string rather than adding a new format placeholder — avoids breaking existing prompt structure
- [Phase 02-ai-qa-agent-core]: HAL and insurance use AppProducts hamburger nav (not SideDock — corrected in Phase 03-06); COD uses AppProducts UPS carrier section
- [Phase 02-ai-qa-agent-core]: DHL international commercial invoice verification appended after full label_flow (post-LABEL CREATED)
- [Phase 02-ai-qa-agent-core]: MCSL order creator reads SIMPLE_PRODUCTS_JSON from per-carrier .env files, not productsconfig.json
- [Phase 02-ai-qa-agent-core]: Order ID injected into ctx as 'TEST ORDER ID: {id}' prefix before the agentic step loop so Claude knows which order to navigate to
- [Phase 02-ai-qa-agent-core]: VerificationReport gains to_dict(), duration_seconds, and summary property dict for Phase 4 Streamlit dashboard
- [Phase 02-ai-qa-agent-core]: verify_ac() now calls _launch_browser() and closes browser in finally block — removes page=None stub from plans 02-01/02
- [Phase 02-ai-qa-agent-core]: ANTHROPIC_API_KEY pre-check removed from verify_ac() — ChatAnthropic constructor validates at runtime, allows test patching
- [Phase 03-label-docs-pre-requirements]: 03-01: test_manual_label_flow_plan verifies _MCSL_WORKFLOW_GUIDE string content directly — validates guide without network calls
- [Phase 03-label-docs-pre-requirements]: 03-01: _MCSL_WORKFLOW_GUIDE Label Generation Flow expanded to 8 explicit steps — step 8 adds Label Summary SUCCESS cell verification
- [Phase 03-label-docs-pre-requirements]: 03-01: create_bulk_orders gets use_dangerous_products param; _verify_scenario reads plan_data["dangerous_products"] to select product source
- [Phase 03-label-docs-pre-requirements]: 03-02: test_auto_generate_flow (LABEL-02) is the actual stub — plan referenced test_actions_menu_label_flow but both are equivalent
- [Phase 03-label-docs-pre-requirements]: 03-02: _PLAN_PROMPT order judgment table already had return label -> existing_fulfilled; guide section added warning to match
- [Phase 03-label-docs-pre-requirements]: 03-03: test_bulk_label_flow asserts 'lowercase' keyword in guide — forces explicit casing warning not just correct button text
- [Phase 03-label-docs-pre-requirements]: 03-03: _PLAN_PROMPT order judgment table already had 'bulk labels → create_bulk' mapping — no change required
- [Phase 03-label-docs-pre-requirements]: 03-04: DOC-04 explicitly warns NOT to use download_zip — Print Documents is a new-tab flow using switch_tab
- [Phase 03-label-docs-pre-requirements]: 03-04: DOC-05 requires ViewallRateSummary expand FIRST — rate table is COLLAPSED by default, 3-dots invisible without expand
- [Phase 03-label-docs-pre-requirements]: 03-04: DOC-03 uses MCSL-specific td:nth-child(8) 3-dots locator — FedEx How-To ZIP flow does NOT exist in MCSL
- [Phase 03-label-docs-pre-requirements]: 03-05: download_zip uses page.expect_download() — Frame objects lack this method; only Page exposes it
- [Phase 03-label-docs-pre-requirements]: 03-05: _verify_scenario had broken _zip_summary reference — replaced with _format_zip_for_context(action['_zip_content'])
- [Phase 04-pipeline-dashboard]: STATUS_BADGE dict maps 4 verdict types to CSS pill HTML; STATUS_BADGE_MD for plain-markdown contexts
- [Phase 04-pipeline-dashboard]: start_run and render_report are stubs (pass) — implemented by 04-02 and 04-04 respectively
- [Phase 04-pipeline-dashboard]: _run_pipeline() accesses st.session_state dict keys only — never calls any st.* render functions (threading contract)
- [Phase 04-pipeline-dashboard]: sav_result assigned before sav_running=False in _run_pipeline() — result-before-flag ordering prevents polling race condition
- [Phase 04-pipeline-dashboard]: 04-03: Stop button uses on_click= callback not conditional if st.button() — click captured before rerun fires
- [Phase 04-pipeline-dashboard]: 04-03: total = max(prog.get(total,1),1) ZeroDivisionError guard ensures progress fraction never raises when sav_prog not yet populated
- [Phase 04-pipeline-dashboard]: 04-04: render_report uses 5 st.columns() — Total + Pass + Fail + Partial + QA Needed metrics; test mock updated to match
- [Phase 04-pipeline-dashboard]: 04-04: Screenshot decode wrapped in try/except — prevents crash on corrupted base64, shows caption fallback
- [Phase 04-pipeline-dashboard]: card_processor uses os.environ.get() so tests can mock via patch after importlib.reload()
- [Phase 04-pipeline-dashboard]: Lazy import from pipeline.card_processor inside Run handler — avoids cold-import cost on every Streamlit reload
- [Phase 04-pipeline-dashboard]: fetched_ac truthiness (not card_name) decides whether to use Trello result
- [Phase 05-full-dashboard-ui]: 05-01: _CSS expanded from 8 to 24 classes using MCSL teal-navy brand colours matching .streamlit/config.toml
- [Phase 05-full-dashboard-ui]: 05-01: _init_state() extended to 12 keys (4 Phase-4 + 8 Phase-5); sidebar stripped to placeholder — implemented in 05-02/03
- [Phase 05-full-dashboard-ui]: _status_badge() placed at module level so tests can import it without calling main()
- [Phase 05-full-dashboard-ui]: Ollama status uses live urllib HTTP check with timeout=2 wrapped in try/except — not hardcoded True
- [Phase 05-full-dashboard-ui]: code_paths_initialized guard uses dict-form st.session_state set before widget keys registered — prevents StreamlitAPIException
- [Phase 05-full-dashboard-ui]: 7-tab layout uses exact variable names tab_us/tab_devdone/tab_release/tab_history/tab_signoff/tab_manual/tab_run required by test_ui01_tab_stubs
- [Phase 05-full-dashboard-ui]: Pipeline header placed in main() body so it appears above tabs in main content area
- [Phase 06-user-story-move-cards-history]: move_card_to_list_by_id calls PUT /1/cards/{card_id} directly with idList=list_id — no name lookup, prevents stale-list-name errors
- [Phase 06-user-story-move-cards-history]: US_WRITER_PROMPT references MCSL multi-carrier (FedEx, UPS, DHL, USPS) — RAG context helpers catch all exceptions and return fallback strings
- [Phase 06-user-story-move-cards-history]: _save_history() only called when dry_run is False — consistent with all other Trello/write operations
- [Phase 06-user-story-move-cards-history]: History helpers added at module level so 06-03 History tab can import them directly
- [Phase 06-user-story-move-cards-history]: move_card_to_list_by_id used exclusively in tab_devdone; name->ID map built from get_lists() prevents stale-name errors
- [Phase 06-user-story-move-cards-history]: dd_chk_{card.id} per-card widget key prefix scoped to avoid future Phase 7 rqa_chk_ collision
- [Phase 07-release-qa-pipeline-core]: gspread imported inside append_to_sheet()/check_duplicates() — not at module top — so sheets_writer can be imported without gspread installed
- [Phase 07-release-qa-pipeline-core]: sheets_writer defines TestCaseRow locally — parallel plan (07-01/card_processor) runs concurrently so no shared import
- [Phase 07-release-qa-pipeline-core]: test_rqa04_append_to_sheet_returns_meta patches gspread via patch.dict(sys.modules) since it's imported inside the function body at call time
- [Phase 07-release-qa-pipeline-core]: test_rqa05_analyse_release_returns_report patches config.ANTHROPIC_API_KEY via patch.object to bypass the empty-key guard in test env
- [Phase 07-release-qa-pipeline-core]: patch target is pipeline.domain_validator.ChatAnthropic (module binding), not langchain_anthropic.ChatAnthropic — already-loaded module ignores source-level patches
- [Phase 07-release-qa-pipeline-core]: generate_test_cases() uses card.desc directly for AC source — never calls get_ac_text(card) since that function expects a URL string
- [Phase 07-release-qa-pipeline-core]: validate_card() never raises — ValidationReport error field populated on all failure paths (no API key, RAG failure, Claude error)
- [Phase 07-release-qa-pipeline-core]: Per-card sav_running_{card.id} key (not global sav_running) ensures concurrent AI QA Agent threads per card don't collide
- [Phase 07-release-qa-pipeline-core]: Thread closure captures mutable loop variables as default args to avoid late-binding closure bugs inside for-loop over cards
- [Phase 07-release-qa-pipeline-core]: write_test_cases_to_card and append_to_sheet imported at module top — called inside Streamlit button handler, no cold-start cost concern
- [Phase 07-release-qa-pipeline-core]: Error isolation: Trello write and Sheets write each in separate try/except — partial failure shows warnings but still marks card approved and saves history
- [Phase 08-slack-sign-off]: notify_devs_of_bug() never raises — returns dict(sent_count, error); BUG_DM_PROMPT uses MCSL Shopify App branding; storepepsaas_server/client RAG source types
- [Phase 08-slack-sign-off]: SlackClient raises ValueError when both webhook_url and token absent — fail-fast config validation
- [Phase 08-slack-sign-off]: Webhook returns plain text 'ok' not JSON — _post() returns hardcoded {'ok': True} after webhook call
- [Phase 08-slack-sign-off]: Module-level post_signoff() is a rich formatter that calls client.post_signoff() — distinct from class method
- [Phase 08-slack-sign-off]: tab_signoff TrelloClient wrapped in try/except with if trello: guards — prevents crash when TRELLO_* env vars absent
- [Phase 08-slack-sign-off]: Source-inspection tests (inspect.getsource) used for signoff compose/send assertions — avoids complex Streamlit mock setup
- [Phase 08-slack-sign-off]: logging.getLogger added to pipeline_dashboard.py — plan used logger.warning but dashboard had no logger defined
- [Phase 09-automation-writing]: patch target is pipeline.automation_writer.ChatAnthropic (module binding); POM_WRITER_PROMPT uses === delimiters for re.search parsing; write_automation() never raises — all errors captured in AutomationResult.error field
- [Phase 09-automation-writing]: Module-level import of _launch_browser/_ax_tree/_navigate_in_app from smart_ac_verifier — required for patch('pipeline.chrome_agent._launch_browser') to work in tests; lazy import inside function body makes patch target unavailable
- [Phase 09-automation-writing]: push_to_branch uses re.sub + .strip('-') for branch name slugification — consistent with write_automation snake-case helpers
- [Phase 09-automation-writing]: Step 5 gated behind approved_store.get(card.id, False) — automation only available after test cases are approved in Step 4
- [Phase 09-automation-writing]: MCSL_AUTOMATION_REPO_PATH read from config via getattr fallback — tab shows warning rather than crashing when key absent

### Pending Todos

None yet.

### Blockers/Concerns

- langchain, chromadb not yet installed system-wide — 01-02 should create venv or install before using

## Session Continuity

Last session: 2026-04-18T09:28:09.671Z
Stopped at: Completed 09-03-PLAN.md — push_to_branch() + Write Automation tab UI + Release QA Step 5; 129 tests GREEN
Resume file: None
