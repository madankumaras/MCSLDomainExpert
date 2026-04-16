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
  - **Server source:** `server/src/shared/` — carrier adaptors, order processing, rate API, settings, constants (1,684 JS files total, focused on shared/)
    - Key files: `carrierConfig.js`, `storePepConstants.js`, `serviceNames.js`, `OrderProcessingService.js`
    - Carrier codes: FedEx=C2, UPS=C3, DHL=C1, EasyPost=C22
    - Source type: `storepepsaas_server` | Skip: `node_modules/`, `tests/`, `db-migrations/`
  - **Client source:** `client/src/` — React/Redux UI components (699 JS files)
    - Key dirs: `components/form/views/summary/order-summary/` (LabelSummary.js, RateSummary.js, PackingSummary.js, OrderSummaryContainerNew.js), `components/form/views/orders/`, `actions/labels/`, `actions/orders/`, `components/form/settings/carriers/`
    - Source type: `storepepsaas_client` | Extensions: `.js`, `.jsx` | Skip: `node_modules/`, `__tests__/`
  - **Ingest into:** `mcsl_code_knowledge` ChromaDB collection (both server + client indexed separately)
- **Key MCSL difference from FedEx:** MCSL supports multiple carriers — each carrier has its own account config, service list, label format, and special services. The AI QA Agent must be carrier-aware when planning and executing scenarios.

## Key MCSL App Flows (vs FedEx) — VERIFIED FROM CODE + WIKI

> ⚠️ These flows are DIFFERENT from FedEx. The AI QA Agent and Domain Expert Chat MUST use these exact flows. Do NOT assume FedEx patterns.

---

### 1. Label Generation — Order Summary (SLGP)

**Navigation:**
```
App URL → click 'ORDERS' tab → filter by Order ID (Add filter → Order Id → paste ID → Escape)
→ wait for order row → click Order ID link → Order Summary page
```

**Button flow on Order Summary:**
```
[PROCESSING status]
  → Optional: "Prepare Shipment" button may appear first — click it (retry up to 3×), then
  → "Generate Label" button → waits for status = "LABEL CREATED" (up to 800s)
  → "Mark As Fulfilled" button → waits for status = "FULFILLED"

OR (Touchless/auto flow):
  → "Generate Label & Fulfil" (single button) → waits for status = "FULFILLED"
```

**Status locator:** `div[class="order-summary-greyBlock"] > div:nth-child(1) > div:nth-child(1) > div > span`

**Label Summary section:** always visible after label created. Shows table with Status=SUCCESS row.

**Key locators (all inside `iframe[name="app-iframe"]`):**
- Generate Label button: `getByRole('button', { name: 'Generate Label', exact: true })`
- Mark As Fulfilled: `getByRole('button', { name: 'Mark As Fulfilled', exact: true })`
- Generate Label & Fulfil: `getByRole('button', { name: 'Generate Label & Fulfil', exact: true })`
- Status button: `getByRole('button').nth(2)` (text = PROCESSING / LABEL CREATED / FULFILLED)
- Prepare Shipment: `getByRole('button', { name: 'Prepare Shipment', exact: true })`

---

### 2. View Label Log (from Order Summary)

**MCSL-specific flow (NOT the FedEx "How To" flow):**
```
Order Summary page (after label created)
→ Label Summary table is visible
→ Click 3-dots button on label row:
  Locator: appFrame.locator('div[class="order-summary-root"]>div>div:nth-child(2)>div>div>div:nth-child(3)>div>div>div:nth-child(2)>div>table>tbody>tr>td:nth-child(8)')
→ Click "View Log" menu item:
  Locator: appFrame.locator('div[role="presentation"]>div:nth-child(2)>ul>li:nth-child(1)').first()
→ Dialog appears: .dialogHalfDivParent (contains label request XML/JSON)
→ Close: complex CSS button locator
```

---

### 3. View Rate Log (from Order Summary)

**MCSL-specific flow:**
```
Order Summary page
→ Click "View all Rate Summary" link (getByTitle('View all Rate Summary'))
  → Rate Summary table expands (locator: .rate-summary-table-container)
→ Click 3-dots button on a rate row:
  Locator: appFrame.locator('.rate-summary-table tbody tr td:last-child button[aria-haspopup="true"]').nth(rowIndex)
→ Click "View Log" menu item:
  Same locator: appFrame.locator('div[role="presentation"]>div:nth-child(2)>ul>li:nth-child(1)').first()
→ Dialog appears: .dialogHalfDivParent (contains rate request XML)
→ Close: getByRole('button', { name: 'Close' })
```

**Note:** Rate Summary is COLLAPSED by default. Must click "View all Rate Summary" first to expand it. This is unique to MCSL — FedEx does not have this pattern.

---

### 4. Bulk Label Generation — from Order Grid

**MCSL flow (NOT via Actions menu — direct button):**
```
Order Grid
→ Select orders: header row checkbox label (getByRole('row', { name: 'Order Date Customer' }).locator('label'))
→ Click "Generate labels" button: frame.locator('role=button[name="Generate labels"]')
  NOTE: lowercase 'l' in "labels" — exact text matters
→ App auto-navigates to Label Batch page
→ Poll label status until SUCCESS (2s interval, 120s timeout)
→ Poll fulfillment status until FULFILLED or PENDING
```

**Then from Label Batch page:**
```
→ "Mark as Fulfilled" button: frame.locator('.buttons-row > button:nth-child(3)')
```

---

### 5. Label Batch Page

**Page title:** "Label Batch"
**Columns:** Download | Order | Tracking Numbers | Customer | ShipTo | Label Status | Fulfillment Status | [Pickup Time if applicable] | Carrier | Total | Shipping Cost | Packages | Info

**Label status flow:** INITIAL → Processing → SUCCESS
**Fulfillment status flow:** PENDING → FULFILLED

**Buttons (inside iframe):**
- `#quick-actions-0` → "Generate Label"
- `#quick-actions-1 > div` → "Print Documents"
- `#quick-actions-2` → "Mark as fulfilled" (in batch)

**Print Documents menu items (in order):** Label | Packing Slips | Tax Invoice | Pick List | Commercial Invoice | All

**Print Documents = opens new tab** (NOT a zip download)

---

### 6. Today's Labels Button

```
Order Grid → click "Todays Labels" button → navigates to today's label batch
```

---

### 7. Quick Ship Flow (from Order Grid)

```
Order Grid
→ Select order(s) → select action "Quick Ship" from Actions menu
→ Modal pre-fills: From Address, Carrier, Service, Service Option (set defaults if blank)
→ Weight/Dimensions: fill if 0 (set to 5 each)
→ Click "Generate Label" in modal
→ Navigates to Label Batch
```

**Action menu pattern:**
```
Select checkbox → click Actions button (frame.locator('div[class="buttons-row"] > button:nth-child(4)'))
→ Search box appears (getByRole('textbox', { name: 'Search' }))
→ Fill action name → click menu item
→ For "Quick Ship": getByRole('menuitem', { name: 'Quick Ship' })
→ For others: getByText(actionName)
```

---

### 8. Touchless SLGP / Preset Flow

```
Order 1: Navigate to Order Summary → createPreset() → saves packaging+carrier+service config
Order 2: Navigate to Order Summary → applyPreset() → auto-fills all details
→ Click "Generate Label" (all details pre-filled — no manual entry needed)
```

---

### 9. Order Status Transitions (MCSL-specific)

```
INITIAL → PROCESSING → LABEL CREATED → FULFILLED
                     ↘ LABEL FAILED (error)
Special states:
  CANCELLED — strikethrough text, red in grid
  PARTIALLY EXTERNALLY FULFILLED — Shopify Hold → label → Fulfill → Release → 2 batches
  EXTERNALLY FULFILLED — fulfilled outside MCSL
  RETURN CREATED — return label generated
```

---

### 10. Carrier Account Configuration

```
App Settings → Carriers → Add Carrier → select carrier type (FedEx/UPS/DHL/USPS/etc.)
→ Enter credentials (account number, API key, etc.)
→ Enable/disable carriers
```

**Carrier codes:** FedEx=C2, UPS=C3, DHL=C1, EasyPost/USPS=C22, Canada Post=C4, etc.
**43 total carriers** supported via adaptor pattern in storepepSAAS.

---

### 11. Special Services (carrier-specific)

- **FedEx:** signature, dry ice, alcohol, battery, HAL (Hold at Location), insurance
- **UPS:** signature, insurance, COD
- **USPS (STAMPS):** signature, registered mail
- **DHL:** insurance, signature, international
- **Canada Post:** package + signature required
- **Australia Post, Aramex, TNT, Sendle, PostNord, DHL Sweden, Parcel Force:** Quick Ship with Signature Required

---

### 12. Document Handling

- **Print Documents** → opens new tab with PDF (NOT a zip download)
- **Download Documents** → ZIP containing: label PDF + packing slip + commercial invoice (international)
- **Upload Document Summary** — auto-upload feature: click 3-dots on upload row → "View Log"
- **Print Documents menu:** Label | Packing Slips | Tax Invoice | Pick List | Commercial Invoice | All

---

### 13. Iframe Selector

**MCSL iframe:** `iframe[name="app-iframe"]` (same as FedEx — confirmed from automation code)

---

### ⚠️ Key Differences from FedEx (for AI QA Agent)

| Feature | FedEx | MCSL |
|---------|-------|------|
| Label flow | Get Rates → SideDock → Generate | Prepare Shipment (optional) → Generate Label |
| Rate log | "How To" button → JSON | "View all Rate Summary" → 3-dots → View Log |
| Label log | Different path | 3-dots on Label Summary row → View Log |
| Bulk generate | Actions → Generate Labels | Direct "Generate labels" button → Label Batch page |
| Carrier | Single carrier (FedEx) | 43 carriers, carrier-aware |
| Batch page | FedEx batch structure | Different columns, different button IDs |
| Note on screenshots | KB screenshots may show OLD app UI | Always trust text content, not UI screenshots |

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
