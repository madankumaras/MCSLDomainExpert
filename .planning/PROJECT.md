# MCSLDomainExpert

## What This Is

MCSLDomainExpert is an AI-powered QA platform for the PluginHive Shopify Multi Carrier Shipping Label (MCSL) App. It mirrors the architecture of FedexDomainExpert but is tailored to a multi-carrier context — supporting FedEx, UPS, USPS, DHL, Canada Post, Aramex, TNT, Australia Post, and more. It provides three core capabilities: a RAG-backed Domain Expert Chat for answering MCSL app questions, an AI QA Agent that autonomously verifies acceptance criteria by operating the real Shopify app in a browser, and a Pipeline Dashboard that orchestrates the full Trello card → AC writing → QA verification → Playwright test generation workflow.

## Core Value

The AI QA Agent must be able to autonomously verify any AC scenario for the MCSL app — across all supported carriers — without human intervention, reporting clear pass/fail per scenario with evidence.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Domain Expert Chat backed by RAG on MCSL knowledge base docs, wiki, codebase, and approved Trello cards
- [ ] AI QA Agent that opens real MCSL Shopify app, verifies every AC scenario, creates orders, configures carrier settings, downloads logs/labels, and reports pass/fail
- [ ] Multi-carrier aware: agent understands FedEx, UPS, USPS, DHL, Canada Post, and other carrier-specific flows
- [ ] MCSL-specific label generation flows (manual + auto + bulk)
- [ ] MCSL-specific document handling: View Logs, Download Documents, Print Documents (new tab viewer)
- [ ] MCSL carrier account configuration flows (connect carrier, negotiated rates, service selection)
- [ ] Packing methods support (custom boxes, dimensional weight, auto packing)
- [ ] International shipping flows (commercial invoice, customs duties)
- [ ] Rate display at checkout configuration
- [ ] Return label generation
- [ ] Pickup scheduling
- [ ] Pipeline Dashboard (Streamlit) orchestrating Trello → AC → QA → Test Gen
- [ ] RAG auto-updates after each approved Trello card cycle
- [ ] TC sheet ingestion from Google Sheets (provided TC sheet URL)

### Out of Scope

- FedEx-only features (dry ice, alcohol, battery, HAL, COD) — MCSL handles these differently via product-level carrier config; handled per-carrier
- Shopify's own discounted carrier accounts — app only supports merchant's own accounts
- Boxify / Shopify native box integration — MCSL has its own box packing

## Context

- **Architecture reference:** FedexDomainExpert at `~/Documents/Fed-Ex-automation/FedexDomainExpert` — full copy of the agent architecture with Playwright browser automation, ChromaDB RAG, Claude AI, Streamlit UI
- **MCSL automation repo:** `/Users/madan/Documents/mcsl-test-automation` — Playwright/TypeScript, same pattern as fedex-test-automation. Key difference: `carrier-envs/` folder with per-carrier `.env` files (ups.env, usps-ship.env, amazon.env, australia-post.env, etc.) instead of a single `.env`. Store: `mcsl-automation.myshopify.com`
- **70% automation coverage:** Existing Playwright tests cover most core flows — high value from AI QA Agent since the remaining 30% can be explored
- **TC Sheet:** https://docs.google.com/spreadsheets/d/1oVtOaM2PesVR_TkuVaBKpbp_qQdmq4FQnN43Xew0FuY/edit — primary source for test case definitions to ingest into RAG
- **Knowledge Base (26 articles):** Scraped clean to `docs/kb_snapshots/` — Setting Up, Troubleshooting, Carrier Setup, Packing Methods, Touchless Print, Purolator, UPS, USPS, DHL, Amazon, FedEx HAL, EU Shipping, India UPS, and more. **All MCSL-only, no WooCommerce/Magento noise.**
- **MCSL Wiki:** `/Users/madan/Documents/mcsl-wiki/wiki/` — **241 markdown docs** covering:
  - `architecture/` — backend (Express/MongoDB), frontend (React/Redux), tech stack, data flow, auth
  - `modules/shipping/` — carrier system overview (43 carriers, adaptor pattern), carrier config, rate shopping, label generation, batch processing, tracking
  - `modules/orders/` — order lifecycle, bulk actions (40+), returns, address management
  - `modules/products/`, `modules/automation/`, `modules/integrations/`, `modules/stores/`
  - `patterns/` — service layer, API conventions, component patterns, error handling, event sourcing
  - `product/stories/` — 100+ ZI product stories (ZI-001 to ZI-105)
  - `zendesk/summaries/` — 100+ real support ticket summaries → real customer pain points
  - `support/ground-zero/` — pain ranking, sprint views
  - **Ingest into:** `mcsl_knowledge` ChromaDB collection
- **storepepSAAS codebase:** `/Users/madan/Documents/storepep-react/storepepSAAS/` — actual MCSL app backend (Node.js/Express, 1,684 JS files) + frontend (React, 699 JS files)
  - Internal name: "StorePep" (MCSL app = storepep product)
  - Key source dirs: `server/src/shared/storepepAdaptors/` (carrier adaptors), `server/src/shared/order/`, `server/src/shared/settings/`, `server/src/shared/ratesApi/`
  - Key files: `carrierConfig.js`, `storePepConstants.js`, `serviceNames.js`, `OrderProcessingService.js`
  - Carrier codes: FedEx=C2, UPS=C3, DHL=C1, EasyPost=C22
  - **Ingest into:** `mcsl_code_knowledge` ChromaDB collection (focused on server/src/shared/ — skip node_modules, tests, migrations)
- **Key MCSL difference from FedEx:** MCSL supports multiple carriers — each carrier has its own account config, service list, label format, and special services. The AI QA Agent must be carrier-aware when planning and executing scenarios.

## Key MCSL App Flows (vs FedEx)

### Label Generation
- Manual: Same flow as FedEx but carrier selection happens at account level, not service level
- Auto-generate: Works same as FedEx but carrier is pre-configured
- Bulk: Select all orders → Actions → "Generate Labels" (different button text than FedEx)

### Carrier Account Configuration
- App Settings → Carriers → Add Carrier → select carrier type → enter credentials
- Each carrier has its own rate zones, services, and special services

### Document Handling
- View Logs: App-specific log viewer (different from FedEx's "How To" flow)
- Print Documents: Opens new tab (same as FedEx — NOT a zip download)
- Download Documents: ZIP with label PDF + packing slip + CI (for international)

### Special Services (carrier-specific)
- FedEx: signature, dry ice, alcohol, battery, HAL, insurance
- UPS: signature, insurance, COD
- USPS (STAMPS): signature, registered mail
- DHL: insurance, signature, international
- Canada Post: package + signature required
- Australia Post, Aramex, TNT, Sendle, PostNord, DHL Sweden, Parcel Force: Quick Ship with Signature Required

### Order Status Transitions (MCSL-specific)
```
Initial → Processing → Label Created → Fulfilled
                    ↘ Label Failed
Special: Partially Externally Fulfilled | Externally Fulfilled | CANCELLED | Return Created
```
- CANCELLED: strikethrough text, red color in grid
- Partially Externally Fulfilled: generated when Shopify Hold/Release used; creates 2 batches for same order

### SLGP Flow (Single Label Generation Page)
- Order Summary page — primary label generation UI
- Presets/Favorites: up to 20 presets per order (Initial/Processing only); auto-highlights when order matches
- Edit Address: opens popup → rates auto-refresh → updated address on label, packing slip, invoices
- Edit Payment: COD ↔ Prepaid toggle → order reprocesses automatically
- Change Carrier Service: modal shows all active carriers → rate summary updates
- Presets persist across sessions; deleted via colored icon click

### Quick Ship Flow
- Select multiple orders in grid → Quick Ship button appears in sticky header
- Modal pre-fills: address, carrier, service from first order; weight/dimensions blank
- Generates Label Batch → marks all orders Fulfilled
- Each order: single package, single label
- Supports presets for auto-fill

### Touchless Print
- Barcode scan → auto-fills order search → opens order
- "Generate Label & Fulfill" → label auto-prints → status Fulfilled
- Tested with: Touchless print toggle enabled

### Batch Flow
- Create Batch from Orders Grid: select orders → Create Batch → enter name → Generate Label
- Actions: print (Label, Packing Slips, Tax Invoice, Pick List, CI, All), Mark Fulfilled, Retry
- Parallel processing: configurable concurrency, queue-based
- Partially Fulfilled: On Hold → label → Fulfill → Release → creates separate batch → "Partially Externally Fulfilled"

### Document Types
- Label — main shipping label
- Packing Slip — order contents list
- Tax Invoice — billing document
- Commercial Invoice — international customs
- Manifest — end-of-day carrier manifest
- Pick List — warehouse pick list (order-based or product-based)

### Known App Bugs (from TC Sheet)
1. **Quantity Reduction** — order update with reduced quantity not working; existing issue
2. **Retry Batch Loop** — infinite loop after Shopify address update for label-failed orders in batch
3. **Cancel Fulfillment** — not functioning correctly for partially fulfilled orders
4. **Payment mode changes** — only work with XpressBees, Delhivery, BlueDart, Amazon

### Manual Must-Cover Areas (from TC Sheet — require AI QA Agent focus)
Batch Creation, Volumetric weights, Box Packing, Stacking Packing, Weight-based packing, Rates, Automation rules sanity, Discounts, Label with long shipping address, Auto order update script, BoGo Fix, Edit packages sanity, Touchless one print, Reports, COD cases

## Constraints

- **Tech stack:** Python, ChromaDB, Claude claude-sonnet-4-6/claude-haiku-4-5-20251001, Playwright (Python), Streamlit — same as FedexDomainExpert
- **Embeddings:** Ollama `nomic-embed-text` (local)
- **ChromaDB collections:** `mcsl_knowledge`, `mcsl_code_knowledge`
- **Config:** Must use explicit dotenv path (same pattern as FedexDomainExpert `config.py` fix)
- **Automation repo path:** `/Users/madan/Documents/mcsl-test-automation` — confirmed
- **Carrier env files:** `carrier-envs/ups.env`, `carrier-envs/usps-ship.env`, `carrier-envs/amazon.env`, `carrier-envs/australia-post.env`, `carrier-envs/blue-dart.env`, `carrier-envs/packaging-fedexrest.env` etc. Each contains CARRIER, SHOPIFYURL, APPURL, SHOPIFY_API_VERSION, SHOPIFY_STORE_NAME
- **Shopify store:** `mcsl-automation` — `mcsl-automation.myshopify.com`, API version 2023-01
- **TC sheet:** Google Sheets ID `1oVtOaM2PesVR_TkuVaBKpbp_qQdmq4FQnN43Xew0FuY`

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Clone FedexDomainExpert architecture | 70% of code is reusable; MCSL same platform (Shopify embedded app in iframe) | — Pending |
| Multi-carrier abstraction in AI QA Agent | Single agent must handle all carriers — carrier name injected in planning prompt | — Pending |
| Separate project from FedexDomainExpert | Different ChromaDB collections, different knowledge base, different automation repo | — Pending |
| YOLO execution mode | User preference — auto-approve, fast execution | — Pending |

---
*Last updated: 2026-04-15 after TC sheet ingestion (all tabs read: Draft Plan, Sections, Single Label Generation, Orders Grid, Batch Flow, Order_Update, Rate_Domestic_Packaging Type, Pluginhive app Setup, SLGP Flow & Quick Ship, Manual Must Cover)*
