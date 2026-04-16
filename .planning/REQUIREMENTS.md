# Requirements: MCSLDomainExpert

**Defined:** 2026-04-15
**Core Value:** AI QA Agent autonomously verifies any MCSL app AC scenario across all supported carriers with clear pass/fail evidence

## v1 Requirements

### RAG Knowledge Base

- [x] **RAG-01**: System ingests 26 pre-scraped MCSL KB articles from `docs/kb_snapshots/` (clean MCSL-only markdown, no WooCommerce/Magento noise) into `mcsl_knowledge`
- [x] **RAG-02**: System ingests TC sheet from Google Sheets (ID: 1oVtOaM2PesVR_TkuVaBKpbp_qQdmq4FQnN43Xew0FuY) into `mcsl_knowledge`
- [x] **RAG-03**: System indexes MCSL wiki (`/Users/madan/Documents/mcsl-wiki/wiki/` — 241 markdown docs: architecture, modules, patterns, ZI stories, Zendesk summaries) into `mcsl_knowledge`
- [x] **RAG-04**: System indexes storepepSAAS codebase (`server/src/shared/` — carrier adaptors, order processing, rate API, settings — skip node_modules/tests/migrations) into `mcsl_code_knowledge`
- [x] **RAG-05**: System indexes MCSL automation repo (`/Users/madan/Documents/mcsl-test-automation` — POM files, helpers, test files, carrier-envs/) into `mcsl_code_knowledge`
- [ ] **RAG-06**: System auto-embeds approved Trello card ACs and test cases after each sprint cycle into `mcsl_knowledge`
- [ ] **RAG-07**: Domain Expert Chat answers MCSL app questions using RAG retrieval with ≤200 word responses

### AI QA Agent — Core

- [x] **AGENT-01**: Agent extracts testable scenarios from AC text as JSON array
- [x] **AGENT-02**: Agent queries Domain Expert RAG for expected behaviour, API signals, and key checks per scenario
- [x] **AGENT-03**: Agent generates a JSON execution plan (nav_clicks, look_for, api_to_watch, order_action, carrier)
- [x] **AGENT-04**: Agent runs agentic browser loop (up to 15 steps): observe/click/fill/scroll/navigate/switch_tab/close_tab/download_zip/download_file/verify/qa_needed
- [x] **AGENT-05**: Agent captures AX tree (depth 6, 250 lines) + screenshot (base64 PNG) + filtered network calls per step
- [x] **AGENT-06**: Agent reports pass/fail/partial/qa_needed verdict per scenario with finding text and screenshot evidence
- [x] **AGENT-07**: Agent supports stop button (threading-based, stop flag checked at each loop iteration)

### AI QA Agent — Multi-Carrier

- [x] **CARRIER-01**: Agent is carrier-aware — carrier name injected into planning prompt from AC text detection
- [x] **CARRIER-02**: Agent handles carrier account configuration flow (App Settings → Carriers → Add/Edit)
- [x] **CARRIER-03**: Agent handles FedEx-specific flows (signature, dry ice, alcohol, battery, HAL, insurance)
- [x] **CARRIER-04**: Agent handles UPS-specific flows (signature, insurance, COD)
- [x] **CARRIER-05**: Agent handles USPS-specific flows (signature, registered mail)
- [x] **CARRIER-06**: Agent handles DHL-specific flows (insurance, signature, international)

### AI QA Agent — Label Generation

- [x] **LABEL-01**: Agent handles Manual Label flow (ORDERS tab → filter by Order Id → order link → Order Summary → Generate Label → LABEL CREATED)
- [x] **LABEL-02**: Agent handles Auto-Generate Label flow (ORDERS tab → select order checkbox → Actions menu → Generate Label → Label Batch page)
- [x] **LABEL-03**: Agent handles Bulk Label generation (ORDERS tab → filter Unfulfilled → header checkbox → Generate labels → Label Batch page)
- [x] **LABEL-04**: Agent handles Return Label flow (ORDERS tab → select order → Actions menu → Create Return Label → Submit → Return Created)
- [x] **LABEL-05**: Agent creates test orders via Shopify REST API (single + bulk, reads SIMPLE_PRODUCTS_JSON/DANGEROUS_PRODUCTS_JSON from carrier-env files)

### AI QA Agent — Document Verification

- [x] **DOC-01**: Agent verifies label existence via "label generated" badge on Order Summary
- [x] **DOC-02**: Agent verifies physical docs via "Download Documents" button on Order Summary (download_zip action → read PDFs/files from ZIP)
- [x] **DOC-03**: Agent verifies label request XML/JSON fields via Label Summary 3-dots (⋯) → View Log → `.dialogHalfDivParent` dialog → read text content
- [x] **DOC-04**: Agent verifies visual label codes via Print Documents → switch_tab → screenshot → read codes → close_tab
- [x] **DOC-05**: Agent views rate logs via ⋯ → View Logs → screenshot dialog (before label generation)

### AI QA Agent — Pre-Requirements

- [ ] **PRE-01**: Hardcoded pre-requirements injected for dry ice scenarios (AppProducts → Is Dry Ice Needed → weight → Save + cleanup)
- [ ] **PRE-02**: Hardcoded pre-requirements injected for alcohol scenarios (AppProducts → Is Alcohol → type → Save + cleanup)
- [ ] **PRE-03**: Hardcoded pre-requirements injected for battery scenarios (AppProducts → Is Battery → material/packing → Save + cleanup)
- [ ] **PRE-04**: Hardcoded pre-requirements for signature scenarios (AppProducts → Signature field → Save + cleanup)
- [x] **PRE-05**: Hardcoded pre-requirements for HAL scenarios (AppProducts hamburger nav → FedEx carrier section → Hold at Location → enable + address → Save + cleanup)
- [x] **PRE-06**: Hardcoded pre-requirements for insurance scenarios (AppProducts hamburger nav → carrier section → Insurance/Declared Value → set amount → Save + cleanup)

### Pipeline Dashboard

- [ ] **DASH-01**: Streamlit dashboard orchestrates Trello card → AC writing → AI QA Agent → test generation → sign-off
- [ ] **DASH-02**: AI QA Agent runs in background threading.Thread so UI stays responsive during verification
- [ ] **DASH-03**: Progress bar and live status updates shown during AI QA Agent execution
- [ ] **DASH-04**: Stop button functional during AI QA Agent run (stop flag checked per loop iteration)
- [ ] **DASH-05**: Report displayed in dashboard with per-scenario pass/fail/partial/qa_needed

### Configuration & Infrastructure

- [x] **INFRA-01**: config.py uses explicit dotenv path (load_dotenv with Path(__file__).parent / ".env") — not plain load_dotenv()
- [x] **INFRA-02**: ChromaDB collections: `mcsl_knowledge` (docs) + `mcsl_code_knowledge` (automation code)
- [x] **INFRA-03**: All env vars in .env: ANTHROPIC_API_KEY, CLAUDE_SONNET_MODEL, CLAUDE_HAIKU_MODEL, STORE, SHOPIFY_ACCESS_TOKEN, SHOPIFY_API_VERSION, MCSL_AUTOMATION_REPO_PATH
- [x] **INFRA-04**: MCSL iframe structure handled: app content in `iframe[name="app-iframe"]`, Shopify admin content outside iframe
- [x] **INFRA-05**: Partial re-ingest supported: `python ingest/run_ingest.py --sources wiki shopify_actions`

## v2 Requirements

### Advanced Features

- **ADV-01**: Playwright test auto-generation from verified AC scenarios
- **ADV-02**: Carrier-specific rate comparison verification (compare live rates vs expected)
- **ADV-03**: Checkout rate display verification (verify carrier rates appear at Shopify checkout)
- **ADV-04**: Multi-store support (different Shopify stores for different carrier configs)

### Extended Carrier Support

- **EXT-01**: Canada Post specific flows
- **EXT-02**: Australia Post specific flows
- **EXT-03**: Aramex specific flows
- **EXT-04**: TNT specific flows

## Out of Scope

| Feature | Reason |
|---------|--------|
| Shopify discounted carrier rates | App only supports merchant's own carrier accounts |
| Boxify / Shopify boxes integration | MCSL has its own box packing engine |
| WooCommerce MCSL variant | Different product — this is Shopify only |
| Real-time Shopify checkout testing | Requires live storefront — deferred to v2 |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| RAG-01 | Phase 1 | Complete |
| RAG-02 | Phase 1 | Complete |
| RAG-03 | Phase 1 | Complete |
| RAG-04 | Phase 1 | Complete |
| RAG-05 | Phase 1 | Complete |
| RAG-06 | Phase 1 | Pending |
| RAG-07 | Phase 1 | Pending |
| INFRA-01 | Phase 1 | Complete |
| INFRA-02 | Phase 1 | Complete |
| INFRA-03 | Phase 1 | Complete |
| INFRA-04 | Phase 1 | Complete |
| INFRA-05 | Phase 1 | Complete |
| AGENT-01 | Phase 2 | Complete |
| AGENT-02 | Phase 2 | Complete |
| AGENT-03 | Phase 2 | Complete |
| AGENT-04 | Phase 2 | Complete |
| AGENT-05 | Phase 2 | Complete |
| AGENT-06 | Phase 2 | Complete |
| AGENT-07 | Phase 2 | Complete |
| CARRIER-01 | Phase 2 | Complete |
| CARRIER-02 | Phase 2 | Complete |
| CARRIER-03 | Phase 2 | Complete |
| CARRIER-04 | Phase 2 | Complete |
| CARRIER-05 | Phase 2 | Complete |
| CARRIER-06 | Phase 2 | Complete |
| LABEL-01 | Phase 3 | Complete |
| LABEL-02 | Phase 3 | Complete |
| LABEL-03 | Phase 3 | Complete |
| LABEL-04 | Phase 3 | Complete |
| LABEL-05 | Phase 3 | Complete |
| DOC-01 | Phase 3 | Complete |
| DOC-02 | Phase 3 | Complete |
| DOC-03 | Phase 3 | Complete |
| DOC-04 | Phase 3 | Complete |
| DOC-05 | Phase 3 | Complete |
| PRE-01 | Phase 3 | Complete |
| PRE-02 | Phase 3 | Complete |
| PRE-03 | Phase 3 | Complete |
| PRE-04 | Phase 3 | Complete |
| PRE-05 | Phase 3 | Complete |
| PRE-06 | Phase 3 | Complete |
| DASH-01 | Phase 4 | Pending |
| DASH-02 | Phase 4 | Pending |
| DASH-03 | Phase 4 | Pending |
| DASH-04 | Phase 4 | Pending |
| DASH-05 | Phase 4 | Pending |

**Coverage:**
- v1 requirements: 46 total (RAG×7, INFRA×5, AGENT×7, CARRIER×6, LABEL×5, DOC×5, PRE×6, DASH×5)
- Mapped to phases: 44
- Unmapped: 0

---
*Requirements defined: 2026-04-15*
*Last updated: 2026-04-15 — traceability expanded to individual requirements, count corrected to 44*
