"""
AI QA Agent — MCSL Multi-Carrier Edition (Phase 02)
=====================================================
Cloned and adapted from FedexDomainExpert/pipeline/smart_ac_verifier.py.

Five-stage pipeline per scenario:
  1. Claude extracts each scenario from AC text
  2. Domain Expert RAG query — expected behaviour, API signals, key checks
  3. Claude plans: nav path, what to click, what to watch (carrier-aware)
  4. Agentic browser loop — up to MAX_STEPS=15 (stubs until plan 02-02)
  5. Pass / fail / partial / qa_needed verdict with screenshot evidence

MCSL-specific adaptations vs FedEx version:
  - Multi-carrier support: carrier name detected from AC text, injected into plan
  - CARRIER_CODES map — FedEx C2, UPS C3, DHL C1, USPS C22, etc.
  - _MCSL_WORKFLOW_GUIDE replaces _APP_WORKFLOW_GUIDE (MCSL order grid navigation)
  - App slug: mcsl-qa (NOT testing-553)
  - iframe selector: iframe[name="app-iframe"]
  - MCSL label flow: ORDERS tab → filter by Order Id → Order Summary → Generate Label → LABEL CREATED
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from textwrap import dedent
from typing import Any, Callable

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

import config

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

MAX_STEPS = 15

_ANTI_BOT_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-setuid-sandbox",
]

_AUTH_JSON = Path("/Users/madan/Documents/mcsl-test-automation/auth.json")

# Carrier keyword → (display name, internal code)
CARRIER_CODES: dict[str, tuple[str, str]] = {
    "fedex":        ("FedEx",          "C2"),
    "ups":          ("UPS",            "C3"),
    "dhl":          ("DHL",            "C1"),
    "usps":         ("USPS",           "C22"),
    "stamps":       ("USPS Stamps",    "C22"),
    "easypost":     ("EasyPost",       "C22"),
    "canada post":  ("Canada Post",    "C4"),
}


# ── Carrier detection ──────────────────────────────────────────────────────────

def _detect_carrier(ac_text: str) -> tuple[str, str]:
    """Return (carrier_name, carrier_code) from AC text. Defaults to ('', '').

    Multi-word keys (e.g. 'canada post') are checked before shorter keys because
    Python 3.7+ dicts preserve insertion order and CARRIER_CODES is defined with
    'canada post' before any ambiguous single-word key.
    """
    lower = ac_text.lower()
    for keyword, (name, code) in CARRIER_CODES.items():
        if keyword in lower:
            return name, code
    return "", ""


_CARRIER_CONFIG_KEYWORDS = frozenset({
    "add carrier", "configure carrier", "carrier account", "set up carrier",
    "carrier setup", "add a carrier", "setup carrier",
})

_SPECIAL_SERVICE_KEYWORDS = frozenset({
    "dry ice", "alcohol", "battery", "signature", "hal", "hold at location",
    "insurance", "cod", "cash on delivery", "registered mail", "registered",
    "international",
})


def _get_carrier_config_steps(carrier_name: str, action: str = "add") -> list[str]:
    """Returns step descriptions for carrier account configuration (CARRIER-02).

    Args:
        carrier_name: Display name of the carrier (e.g. 'FedEx', 'UPS').
        action:       'add' to add a new carrier account, 'edit' to modify an existing one.

    Returns:
        List of natural-language step descriptions for the agent to follow.
    """
    base_steps = [
        "Navigate to App Settings (settings/0)",
        "Click the Carriers tab inside the app iframe",
    ]
    if action == "add":
        base_steps += [
            "Click Add Carrier button",
            f"Select {carrier_name} from the carrier type dropdown",
            f"Fill in the {carrier_name} account credentials",
            "Click Save to complete the configuration",
            f"Verify {carrier_name} appears in the carriers list",
        ]
    elif action == "edit":
        base_steps += [
            f"Find the {carrier_name} row in the carriers list",
            f"Click the Edit button for {carrier_name}",
            "Update the credentials as required",
            "Click Save",
        ]
    return base_steps


def _get_preconditions(
    scenario_text: str,
    carrier: str,
    app_base: str = "",
) -> list[str]:
    """Returns precondition step descriptions for special service scenarios.

    Steps are injected into the plan prompt so Claude knows what to configure
    before generating the label.

    Each branch returns an ordered list of step strings that reference the MCSL
    label flow (ORDERS tab → Order Id filter → Order Summary → Generate Label).
    CLEANUP steps are appended as explicit list items (not comment strings) so
    the agent executes them after label generation.

    Args:
        scenario_text: Scenario text (used for keyword matching).
        carrier:       Carrier name (e.g. 'fedex', 'FedEx', 'ups').
        app_base:      Base URL of the MCSL app (optional, e.g. 'https://…/apps/mcsl-qa').

    Returns:
        List of natural-language step descriptions for the agent to follow.
    """
    lower = scenario_text.lower()
    carrier_lower = carrier.lower()
    steps: list[str] = []

    # --- SHARED PRODUCT CONFIG STEPS (MCSL hamburger nav) ---
    # Used for dry ice, alcohol, battery, signature (product-level settings in AppProducts).
    product_nav = [
        "Click the hamburger menu in the app iframe",
        "Click 'Products' in the navigation menu",
        "Wait for AppProducts page to load",
        "Find the test product by name link and click it to open product settings",
    ]

    # --- CORRECT MCSL LABEL FLOW ---
    # index 0-3: navigate to Order Summary + Prepare Shipment
    # index 4: Generate Label
    # index 5: Wait for LABEL CREATED
    label_flow = [
        "Click 'ORDERS' tab → All Orders grid loads inside iframe",
        "Add filter: Order Id → paste the test order ID → press Escape",
        "Click the order link (bold order number) → Order Summary page opens",
        "On Order Summary: if 'Prepare Shipment' button is visible, click it (retry up to 3x)",
        "Click 'Generate Label' button (exact match, inside app iframe)",
        "Wait for order status to reach 'LABEL CREATED' (up to 800s)",
    ]

    save_steps = [
        "Click Save button",
        "Verify success toast (.s-alert-box-inner) appears",
    ]

    # --- FEDEX ---
    if carrier_lower == "fedex":
        if "dry ice" in lower:
            toggle_steps = [
                "Enable 'Is Dry Ice Needed' toggle",
                "Fill Dry Ice Weight field with a valid value (e.g. 1.0 kg)",
            ]
            cleanup = [
                "(CLEANUP — after LABEL CREATED) Navigate back to AppProducts",
                "(CLEANUP) Open the test product settings",
                "(CLEANUP) Uncheck/disable 'Is Dry Ice Needed' toggle",
                "(CLEANUP) Click Save",
                "(CLEANUP) Verify success toast",
            ]
            steps = product_nav + toggle_steps + save_steps + label_flow + cleanup

        elif "alcohol" in lower:
            toggle_steps = [
                "Enable 'Is Alcohol' toggle",
                "Select alcohol type from dropdown (e.g. Wine)",
            ]
            cleanup = [
                "(CLEANUP — after LABEL CREATED) Navigate back to AppProducts",
                "(CLEANUP) Open the test product settings",
                "(CLEANUP) Uncheck/disable 'Is Alcohol' toggle",
                "(CLEANUP) Click Save",
                "(CLEANUP) Verify success toast",
            ]
            steps = product_nav + toggle_steps + save_steps + label_flow + cleanup

        elif "battery" in lower:
            toggle_steps = [
                "Enable 'Is Battery' or 'Is it a Dangerous Good' toggle",
                "Select battery material type (e.g. Lithium Ion)",
                "Select battery packing type (e.g. Packed with equipment)",
            ]
            cleanup = [
                "(CLEANUP — after LABEL CREATED) Navigate back to AppProducts",
                "(CLEANUP) Open the test product settings",
                "(CLEANUP) Uncheck/disable the battery/dangerous good toggle",
                "(CLEANUP) Click Save",
                "(CLEANUP) Verify success toast",
            ]
            steps = product_nav + toggle_steps + save_steps + label_flow + cleanup

        elif "signature" in lower:
            toggle_steps = [
                "Set 'FedEx\u00ae Delivery Signature Options' (or carrier equivalent) to Adult Signature Required",
            ]
            cleanup = [
                "(CLEANUP — after LABEL CREATED) Navigate back to AppProducts",
                "(CLEANUP) Open the test product settings",
                "(CLEANUP) Reset Signature field to its original/default state",
                "(CLEANUP) Click Save",
                "(CLEANUP) Verify success toast",
            ]
            steps = product_nav + toggle_steps + save_steps + label_flow + cleanup

        elif "hal" in lower or "hold at location" in lower:
            hal_steps = [
                "Find the Hold at Location (HAL) setting in the FedEx carrier section",
                "Enable Hold at Location and enter a valid FedEx facility address or zip code",
                "Select the hold location from the results",
                "Click Save → verify success toast (.s-alert-box-inner)",
            ]
            cleanup = [
                "(CLEANUP — after LABEL CREATED) Navigate back to AppProducts",
                "(CLEANUP) Find the test product and open FedEx carrier settings",
                "(CLEANUP) Disable Hold at Location",
                "(CLEANUP) Click Save → verify success toast",
            ]
            steps = product_nav + hal_steps + label_flow + cleanup

        elif "insurance" in lower:
            insurance_steps = [
                "Find the Insurance or Declared Value field in the carrier section",
                "Set the declared value / insurance amount (e.g. $100)",
                "Click Save → verify success toast (.s-alert-box-inner)",
            ]
            cleanup = [
                "(CLEANUP — after LABEL CREATED) Navigate back to AppProducts",
                "(CLEANUP) Find the test product and open carrier settings",
                "(CLEANUP) Clear the Insurance / Declared Value field",
                "(CLEANUP) Click Save → verify success toast",
            ]
            steps = product_nav + insurance_steps + label_flow + cleanup

        else:
            steps = label_flow  # Default FedEx flow (no special service setup)

    # --- UPS ---
    elif carrier_lower == "ups":
        if "signature" in lower:
            toggle_steps = [
                "Set Signature field to 'DELIVERY_CONFIRMATION' or 'SIGNATURE_REQUIRED' on the product",
            ]
            cleanup = [
                "(CLEANUP — after LABEL CREATED) Navigate back to AppProducts",
                "(CLEANUP) Open the test product settings",
                "(CLEANUP) Reset Signature field to its original/default state",
                "(CLEANUP) Click Save",
                "(CLEANUP) Verify success toast",
            ]
            steps = product_nav + toggle_steps + save_steps + label_flow + cleanup

        elif "insurance" in lower:
            insurance_steps = [
                "Find the Insurance or Declared Value field in the carrier section",
                "Set the declared value / insurance amount (e.g. $100)",
                "Click Save → verify success toast (.s-alert-box-inner)",
            ]
            cleanup = [
                "(CLEANUP — after LABEL CREATED) Navigate back to AppProducts",
                "(CLEANUP) Find the test product and open carrier settings",
                "(CLEANUP) Clear the Insurance / Declared Value field",
                "(CLEANUP) Click Save → verify success toast",
            ]
            steps = product_nav + insurance_steps + label_flow + cleanup

        elif "cod" in lower or "cash on delivery" in lower:
            cod_steps = [
                "Find the COD (Cash on Delivery) setting in the UPS carrier section of AppProducts",
                "Enable COD and enter the COD amount and payment method",
                "Click Save → verify success toast (.s-alert-box-inner)",
            ]
            cleanup = [
                "(CLEANUP — after LABEL CREATED) Navigate back to AppProducts",
                "(CLEANUP) Find the test product and open UPS carrier settings",
                "(CLEANUP) Disable COD (Cash on Delivery)",
                "(CLEANUP) Click Save → verify success toast",
            ]
            steps = product_nav + cod_steps + label_flow + cleanup

        else:
            steps = label_flow

    # --- USPS ---
    elif carrier_lower in ("usps", "usps stamps"):
        if "signature" in lower:
            toggle_steps = [
                "Set Signature field on the product to the required USPS signature option",
            ]
            cleanup = [
                "(CLEANUP — after LABEL CREATED) Navigate back to AppProducts",
                "(CLEANUP) Open the test product settings",
                "(CLEANUP) Reset Signature field to its original/default state",
                "(CLEANUP) Click Save",
                "(CLEANUP) Verify success toast",
            ]
            steps = product_nav + toggle_steps + save_steps + label_flow + cleanup

        elif "registered" in lower or "registered mail" in lower:
            registered_steps = [
                "Ensure the service selected is 'First Class' or 'Priority' with Registered Mail add-on",
                "Confirm Registered Mail option is visible in the rate/service selection",
            ]
            steps = label_flow[:4] + registered_steps + label_flow[4:]

        else:
            steps = label_flow

    # --- DHL ---
    elif carrier_lower == "dhl":
        if "insurance" in lower:
            insurance_steps = [
                "Find the Insurance or Declared Value field in the carrier section",
                "Set the declared value / insurance amount (e.g. $100)",
                "Click Save → verify success toast (.s-alert-box-inner)",
            ]
            cleanup = [
                "(CLEANUP — after LABEL CREATED) Navigate back to AppProducts",
                "(CLEANUP) Find the test product and open carrier settings",
                "(CLEANUP) Clear the Insurance / Declared Value field",
                "(CLEANUP) Click Save → verify success toast",
            ]
            steps = product_nav + insurance_steps + label_flow + cleanup

        elif "signature" in lower:
            toggle_steps = [
                "Set Signature field on the product for DHL carrier requirements",
            ]
            cleanup = [
                "(CLEANUP — after LABEL CREATED) Navigate back to AppProducts",
                "(CLEANUP) Open the test product settings",
                "(CLEANUP) Reset Signature field to its original/default state",
                "(CLEANUP) Click Save",
                "(CLEANUP) Verify success toast",
            ]
            steps = product_nav + toggle_steps + save_steps + label_flow + cleanup

        elif "international" in lower:
            steps = label_flow + [
                "Verify commercial invoice is generated after LABEL CREATED status",
                "Check that customs information (HS code, declared value, description) is present",
            ]

        else:
            steps = label_flow

    else:
        # Unknown carrier — return generic label flow
        steps = label_flow

    return steps


# ── URL map builder ────────────────────────────────────────────────────────────

# MCSL navigation map — all in-app destinations use hamburger menu search.
# "orders" and "shopifyproducts" are the only Shopify admin URLs (outside the app).
_MCSL_NAV_MAP: dict[str, dict] = {
    # key            : how to reach it
    "orders":         {"type": "tab", "index": 1},          # ORDERS tab (responsiveNav nth-child 1)
    "labels":         {"type": "tab", "index": 2},          # LABELS tab
    "pickup":         {"type": "tab", "index": 3},          # PICKUP tab
    "manifest":       {"type": "tab", "index": 4},          # MANIFEST tab
    "tracking":       {"type": "tab", "index": 5},          # TRACKING tab
    # hamburger → search → click
    "views":          {"type": "hamburger", "search": "Views"},
    "appproducts":    {"type": "hamburger", "search": "Products"},
    "carriers":       {"type": "hamburger", "search": "Carriers"},
    "address":        {"type": "hamburger", "search": "Address"},
    "shipping":       {"type": "hamburger", "search": "Shipping"},
    "automation":     {"type": "hamburger", "search": "Automation"},
    "shippingrates":  {"type": "hamburger", "search": "Shipping Rates"},
    "generalsettings":{"type": "hamburger", "search": "General Settings"},
    "bulkimports":    {"type": "hamburger", "search": "Bulk Imports"},
    "account":        {"type": "hamburger", "search": "Account"},
    "stores":         {"type": "hamburger", "search": "Stores"},
    # Shopify admin — full page navigation (outside app iframe)
    "shopifyorders":  {"type": "shopify_url", "path": "orders"},
    "shopifyproducts":{"type": "shopify_url", "path": "products"},
}


def _navigate_in_app(page: "Page", destination: str, store: str = "") -> bool:
    """Click-based navigation for MCSL — no URL jumping inside the app.

    MCSL has a single app endpoint. All sections are reached by:
      - Clicking a top tab (responsiveNav) for ORDERS/LABELS/PICKUP/MANIFEST/TRACKING
      - Clicking hamburger (Menu button) → searching → clicking result for settings sections
      - For Shopify admin pages (shopifyorders, shopifyproducts): page.goto() is acceptable
        because those are outside the app iframe entirely.
    """
    key = destination.lower().replace(" ", "").replace("-", "")
    nav = _MCSL_NAV_MAP.get(key)
    if nav is None:
        logger.warning("navigate: unknown destination %r", destination)
        return False

    try:
        app_frame = page.frame_locator('iframe[name="app-iframe"]')

        if nav["type"] == "tab":
            idx = nav["index"]
            app_frame.locator(f'div[class="responsiveNav"]:nth-child({idx})').click()
            page.wait_for_timeout(1000)
            return True

        if nav["type"] == "hamburger":
            search_term = nav["search"]
            # Click the Menu (hamburger) button inside the app iframe
            page.locator('iframe[name="app-iframe"]').content_frame().get_by_role(
                "button", name="Menu"
            ).click()
            page.wait_for_timeout(500)
            # Fill the search box that appears in the drawer
            app_frame.locator(
                'div[role="presentation"]>div>div>div>input[placeholder="Search..."]'
            ).fill(search_term)
            page.wait_for_timeout(300)
            # Click the matching button (last match to avoid stale duplicates)
            app_frame.get_by_role("button", name=search_term).last().click()
            page.wait_for_timeout(1000)
            return True

        if nav["type"] == "shopify_url":
            store_slug = store or getattr(config, "STORE", "")
            page.goto(
                f"https://admin.shopify.com/store/{store_slug}/{nav['path']}",
                wait_until="domcontentloaded",
            )
            page.wait_for_timeout(500)
            return True

    except Exception as e:
        logger.warning("navigate(%s) failed: %s", destination, e)
        return False

    return False


# ── MCSL workflow guide ────────────────────────────────────────────────────────

_MCSL_WORKFLOW_GUIDE = dedent("""\
## MCSL Multi-Carrier Shipping App — Key Workflows

App URL: admin.shopify.com/store/<store>/apps/mcsl-qa  (single endpoint)
All app UI lives inside: iframe[name="app-iframe"]

⚠️ MCSL HAS ONE ENDPOINT. All in-app navigation is CLICK-BASED ONLY.
   Do NOT construct or jump to sub-URLs. Navigate by clicking tabs or the
   hamburger (Menu) button — exactly as a user would.

### How to Navigate

TOP TABS (click the tab text inside the app iframe):
  ORDERS | LABELS | PICKUP | MANIFEST | TRACKING | HELP

HAMBURGER MENU (for settings sections):
  1. Click the "Menu" button (role=button, name="Menu") inside app iframe
  2. A search drawer opens — type the section name
  3. Click the matching button in the results
  Sections available: Views, Tracking, Products, Carriers, Address,
                      Shipping, Automation, Shipping Rates,
                      General Settings, Bulk Imports, Account, Stores

### Getting the Latest Order (Order Import)
Orders from Shopify import automatically when you navigate to the app.
If the expected order is not visible:
  → First: look for and click the "Refresh" button if it appears in the grid
  → If no Refresh button: reload the page (up to 5 retries)
  → Then filter by Order ID to find the specific order

### Label Generation Flow (Manual — same for ALL carriers)
1. Click "ORDERS" tab → All Orders grid loads inside iframe
2. If order not visible → click Refresh button OR reload page (up to 5 retries)
3. Click "Add filter" → select menuitem "Order Id" → type order ID into textbox → press Escape
4. Click the order link (bold order number) → Order Summary page opens
5. If "Prepare Shipment" button is visible → click it (may reappear, retry up to 3×)
6. Click "Generate Label" button (exact match, inside app iframe)
7. Wait for status button (appFrame.getByRole('button').nth(2)) to show "LABEL CREATED" (up to 800s)
8. After LABEL CREATED: verify Label Summary table is visible and shows SUCCESS cell

⚠️ Do NOT use Shopify admin "More Actions" for label generation.
   MCSL has its own order grid — always use the ORDERS tab inside the app.

### After Label Generation — Shopify Order Verification
To verify fulfillment status and tracking number in Shopify:
  → navigate: "shopifyorders"  (this is the only case where we leave the app)
  → Find the order row → check Fulfillment status = "Fulfilled"
  → Open the order → verify tracking number is present

### Bulk Label Flow (LABEL-03)
1. Click "ORDERS" tab → All Orders grid
2. Create multiple orders (order_action: create_bulk, default 3)
3. Filter for unfulfilled orders (Add filter → Fulfillment Status → Unfulfilled)
   so only the test orders are visible in the grid
4. Click the header row checkbox to select ALL visible unfulfilled orders:
   (getByRole "row" name="#" → locator "label" → first click)
5. Click "Generate labels" button — NOTE: lowercase "l" is EXACT, not "Generate Labels"
   (capital L fails all click attempts) → Label Batch page opens
6. Wait for all rows to show SUCCESS status (poll up to 300s)
7. Click "Mark as Fulfilled"

### Actions Menu Label Flow (single order via Actions menu — LABEL-02)
1. Click "ORDERS" tab → All Orders grid
2. Add filter: Order Id → type order ID → press Escape
3. Click header checkbox (getByRole "row" name="#" → locator "label" → first)
4. Click Actions button (div[class="buttons-row"] > button:nth-child(4))
5. In the Actions search box, type "Generate Label" → click menuitem "Generate Label"
   → Label Batch page opens (same as Bulk Labels)
6. Wait for SUCCESS status in batch grid
7. Click "Mark as Fulfilled"

### Return Label Flow (LABEL-04)
⚠️ REQUIRES an already-FULFILLED order. Use order_action: existing_fulfilled in plan.
1. Click "ORDERS" tab → All Orders grid
2. Add filter: Order Id → type order ID → press Escape
3. Click header checkbox (same as Actions Menu Label flow)
4. Click Actions button (div[class="buttons-row"] > button:nth-child(4))
5. In Actions search → type "Create Return Label" → click menuitem "Create Return Label"
   → Return Label modal opens (header text = "Return Label")
6. Click Submit button
7. Verify order row status column = "Return Created"
   (locator: #all-order-table table tbody tr:first → td:nth-child(11))

### TWO DIFFERENT PRODUCT PAGES — DO NOT CONFUSE

❶  navigate: "appproducts"  →  hamburger → Products
   PURPOSE: Edit MCSL-specific settings on an EXISTING Shopify product.
   Fields: Dimensions (L/W/H/unit), Weight, Special Services per carrier
           (Dry Ice, Alcohol, Battery, Signature, Insurance, etc.)
   Save → success toast appears.
   ⚠️ Cannot CREATE new products here.

❷  navigate: "shopifyproducts"  →  Shopify admin products page
   PURPOSE: Create new products or edit Shopify-native fields (title, price, SKU).
   ⚠️ No MCSL-specific fields here.

### Carrier Account Configuration
Navigation: hamburger → Carriers

To ADD a carrier account:
  1. navigate: "carriers" (hamburger → Carriers)
  2. Click "Add Carrier" button
  3. Select carrier type from dropdown
  4. Fill credentials:
     - FedEx: Account Number, API Key, API Secret, Meter Number
     - UPS: Account Number, Client ID, Client Secret
     - DHL: Account Number, Site ID, Password
     - USPS/EasyPost: Account Number
     - Canada Post: Account Number
  5. Click Save/Add → carrier appears in list

To EDIT a carrier:
  1. navigate: "carriers"
  2. Find carrier row → click Edit → update fields → Save

Carrier codes: FedEx=C2, UPS=C3, DHL=C1, USPS/EasyPost=C22, Canada Post=C4

### Order Summary page
  - Reached by clicking an order row in the ORDERS grid
  - Shows: label status badge, carrier badge, Generate Label / Mark As Fulfilled buttons
  - Label status locator: appFrame.getByRole('button').nth(2)
  - Status values: (empty) → "LABEL CREATED" → "FULFILLED"

### Shopify Orders (admin.shopify.com/store/<store>/orders)
  Use ONLY for post-fulfillment checks:
  - Verify fulfillment status shows "Fulfilled"
  - Verify tracking number has been added
  ⚠️ Do NOT create orders here for automation — use the API (order_creator.py)

---

## Document Verification Strategies

After label generation, use one or more of the following strategies to gather evidence.

### DOC-01: Label Existence Badge Check
After "Generate Label" click, verify status reaches LABEL CREATED:
- Status span: div[class="order-summary-greyBlock"] > div:nth-child(1) > div:nth-child(1) > div > span
- Status button (for polling): getByRole('button').nth(2) shows "LABEL CREATED"
- Label Summary table visible: getByText('Label Summary')
- SUCCESS cell visible: getByRole('cell', name='SUCCESS').first()

### DOC-02: Download Documents ZIP
On Order Summary after LABEL CREATED:
1. Find "Download Documents" button (text may vary — probe AX tree if not found)
2. action: download_zip, target: "Download Documents"
3. Result: action["_zip_content"] populated with file names and content snippets
4. Claude verifies expected document files are present (PDF size notes, CSV content, etc.)

### DOC-03: Label Request XML/JSON (3-dots on Label Summary row)
After LABEL CREATED, in the Label Summary table:
1. Click 3-dots (⋯) on the label row:
   appFrame TD selector: div[class="order-summary-root"]>...>tbody>tr>td:nth-child(8)
   Use .nth(rowIndex) for a specific row
2. Click "View Log" menuitem:
   appFrame.locator('div[role="presentation"]>div:nth-child(2)>ul>li:nth-child(1)').first()
3. Wait for .dialogHalfDivParent to be visible
4. Read textContent() → strip whitespace → verify expected XML/JSON field names are present
5. Close dialog via closeLabelRequestSummary button
NOTE: Do NOT use download_zip here — this is a dialog, not a file download. FedEx "How To" flow does NOT apply to MCSL.

### DOC-04: Print Documents (New Tab Screenshot)
⚠️ IMPORTANT: Print Documents opens a NEW TAB — do NOT use download_zip here.
Steps:
1. Click "Print Documents" button on Order Summary (standalone button)
2. New tab opens at *.pluginhive.io domain
3. action: switch_tab → active_page = new tab
4. Take screenshot → Claude reads label service codes visible on label (ICE, ALCOHOL, ELB, ASR, DSR)
5. action: close_tab → returns to Order Summary

### DOC-05: Rate Log Screenshot (BEFORE label generation)
On Order Summary, after rates load, BEFORE clicking Generate Label:
1. FIRST: Click ViewallRateSummary (getByTitle 'View all Rate Summary') — table is COLLAPSED by default
2. Wait for .rate-summary-table-container to be visible
3. Click 3-dots button on rate summary row:
   .rate-summary-table tbody tr td:last-child button[aria-haspopup="true"]
4. Click View Log menuitem:
   div[role="presentation"]>div:nth-child(2)>ul>li:nth-child(1) (first)
5. Log dialog: .dialogHalfDivParent — contains JSON/XML request text
6. Screenshot dialog → Claude verifies required fields
7. Close: getByRole('button', name='Close')
WARNING: Must expand ViewallRateSummary FIRST — 3-dots button is not visible on collapsed table.
""")


# ── Data models ────────────────────────────────────────────────────────────────

@dataclass
class VerificationStep:
    """A single step in the agentic verification loop."""
    action: str = ""
    description: str = ""
    target: str = ""
    success: bool = True
    screenshot_b64: str = ""
    network_calls: list[str] = field(default_factory=list)
    # Extended fields used by the 02-02 agentic loop
    step_num: int = 0
    ax_tree: str = ""


# Alias used in test stubs — plans 02-02/03 use VerificationStep directly
StepResult = VerificationStep


@dataclass
class ScenarioResult:
    """Result for a single scenario."""
    scenario: str
    status: str = "pending"          # pass | fail | partial | skipped | qa_needed
    verdict: str = ""
    finding: str = ""                # human-readable verdict text from verify/qa_needed actions
    evidence_screenshot: str = ""   # base64 PNG of the final state when verdict reached
    steps: list[VerificationStep] = field(default_factory=list)
    qa_question: str = ""
    bug_report: dict = field(default_factory=dict)
    carrier: str = ""                # carrier name injected from AC text


@dataclass
class VerificationReport:
    """Aggregate report for all scenarios in a card's AC."""
    card_name: str = ""
    app_url: str = ""
    scenarios: list[ScenarioResult] = field(default_factory=list)
    duration_seconds: float = 0.0

    @property
    def total(self) -> int:
        return len(self.scenarios)

    @property
    def summary(self) -> dict[str, int]:
        """Return per-status counts: pass/fail/partial/qa_needed."""
        counts: dict[str, int] = {"pass": 0, "fail": 0, "partial": 0, "qa_needed": 0}
        for s in self.scenarios:
            if s.status in counts:
                counts[s.status] += 1
        return counts

    @property
    def passed(self) -> int:
        return sum(1 for s in self.scenarios if s.status == "pass")

    @property
    def failed(self) -> int:
        return sum(1 for s in self.scenarios if s.status in ("fail", "partial"))

    @property
    def qa_needed_list(self) -> list[ScenarioResult]:
        return [s for s in self.scenarios if s.status == "qa_needed"]

    def to_dict(self) -> dict:
        """Serialise report to a dict consumable by the Phase 4 Streamlit dashboard."""
        return {
            "card_name": self.card_name,
            "total": self.total,
            "summary": self.summary,
            "duration_seconds": self.duration_seconds,
            "scenarios": [
                {
                    "scenario": s.scenario,
                    "carrier": s.carrier,
                    "status": s.status,
                    "finding": s.finding if s.finding else (
                        "Scenario passed" if s.status == "pass" else "No finding recorded"
                    ),
                    "evidence_screenshot": s.evidence_screenshot,
                    "steps_taken": len(s.steps),
                }
                for s in self.scenarios
            ],
        }

    def to_automation_context(self) -> str:
        """Convert verified flows into context string for automation writer."""
        lines = [f"=== MCSL Smart AC Verification: {self.card_name} ===",
                 f"App: {self.app_url}", ""]
        for sv in self.scenarios:
            icon = {"pass": "✅", "fail": "❌", "partial": "⚠️"}.get(sv.status, "⏭️")
            carrier_tag = f" [{sv.carrier}]" if sv.carrier else ""
            lines.append(f"{icon}{carrier_tag} {sv.scenario}")
            for step in sv.steps:
                if step.action in ("click", "fill", "navigate") and step.target:
                    lines.append(f"   [{step.action}] '{step.target}' — {step.description}")
                if step.network_calls:
                    for nc in step.network_calls[:3]:
                        lines.append(f"   [api] {nc}")
            if sv.verdict:
                lines.append(f"   Result: {sv.verdict}")
            lines.append("")
        return "\n".join(lines)


# ── Prompts ────────────────────────────────────────────────────────────────────

_EXTRACT_PROMPT = dedent("""\
    Extract each testable scenario from the acceptance criteria below.
    Return ONLY a JSON array of concise scenario title strings. No explanation.
    Example: ["User can enable Hold at Location", "Success toast shown after Save"]

    Acceptance Criteria:
    {ac}
""")


_DOMAIN_EXPERT_PROMPT = dedent("""\
    You are the domain expert for the MCSL Multi-Carrier Shipping Shopify app.
    A QA engineer is about to verify this scenario in the live app.

    SCENARIO: {scenario}
    FEATURE:  {card_name}

    {preconditions_section}

    Using the domain knowledge and code context below, answer these questions
    concisely (max 200 words total):

    1. EXPECTED BEHAVIOUR — What should happen in the UI when this works correctly?
    2. API SIGNALS — What backend API calls or request fields should appear?
    3. KEY THINGS TO CHECK — Specific UI elements, values, or network calls that
       confirm this scenario is implemented and working.

    Be specific. If the scenario mentions a carrier (FedEx, UPS, DHL, USPS), explain
    exactly what that carrier's flow looks like and what changes in the request or UI.

    DOMAIN KNOWLEDGE (MCSL docs / carrier API):
    {domain_context}

    CODE KNOWLEDGE (automation POM / backend):
    {code_context}

    Answer in plain text — no JSON, no headings, just 3 short paragraphs.
""")


_PLAN_PROMPT = dedent("""\
    You are a QA engineer verifying a feature in the MCSL Multi-Carrier Shipping Shopify App.

    SCENARIO: {scenario}
    APP URL:  {app_url}

    CARRIER: {carrier_name} (internal code: {carrier_code})
    Use carrier-specific navigation, service codes, and account config flows.
    If carrier is empty, the scenario is carrier-neutral.

{mcsl_workflow_guide}

    DOMAIN EXPERT INSIGHT (what this feature should do + what API signals to watch):
    {expert_insight}

    CODE KNOWLEDGE (automation POM patterns + backend API):
    {code_context}

    IMPORTANT: We test WEB (desktop browser) ONLY. SKIP any scenario that involves mobile
    viewports, responsive breakpoints, or screen widths ≤ 768 px.

    Plan how to verify this. The browser will ALWAYS start at the app home page.

    Navigation rules (MCSL has ONE endpoint — all navigation is click-based):
    - For label generation / order verification → nav_clicks: ["orders"]  (ORDERS tab)
    - For verifying an EXISTING label / documents → nav_clicks: ["orders"]
    - For carrier account configuration → nav_clicks: ["carriers"]  (hamburger → Carriers)
    - For product-level settings (dry ice, dimensions, services) → nav_clicks: ["appproducts"]
    - For creating/editing Shopify products → nav_clicks: ["shopifyproducts"]
    - For post-fulfillment Shopify order checks → nav_clicks: ["shopifyorders"]
    - For pickup scheduling → nav_clicks: ["pickup"]
    - For tracking → nav_clicks: ["tracking"]
    - For automation rules → nav_clicks: ["automation"]
    - For settings (general, rates, address) → nav_clicks: ["generalsettings"]
    - ONLY use destinations from _MCSL_NAV_MAP keys: "orders", "labels", "pickup",
      "manifest", "tracking", "views", "appproducts", "carriers", "address",
      "shipping", "automation", "shippingrates", "generalsettings", "bulkimports",
      "account", "stores", "shopifyorders", "shopifyproducts"

    ORDER JUDGMENT — pick order_action by scenario type:
    | Scenario type                                                              | order_action           |
    |----------------------------------------------------------------------------|------------------------|
    | cancel label, return label, verify label, download document, label shows   | existing_fulfilled     |
    | generate label, create label, dry ice, alcohol, battery, HAL, COD,         | create_new             |
    | signature, insurance, declared value, domestic label, international label  |                        |
    | bulk labels, batch label, select all orders                                | create_bulk            |
    | settings, configure, pickup, rates log, navigation, order grid, sidebar    | none                   |

    Respond ONLY in JSON:
    {{
      "app_path": "",
      "look_for": ["UI element or behaviour that proves this scenario is implemented"],
      "api_to_watch": ["API endpoint path fragment to watch in network calls"],
      "nav_clicks": ["e.g. orders | carriers | appproducts | shopifyproducts | tracking"],
      "plan": "one sentence: how you will verify this scenario",
      "order_action": "none | existing_fulfilled | existing_unfulfilled | create_new | create_bulk",
      "carrier": "{carrier_name}"
    }}
""")


# ── JSON parsing ───────────────────────────────────────────────────────────────

def _parse_json(raw: str) -> Any:
    """Extract JSON from Claude's response — handles markdown fences, prefix text."""
    clean = re.sub(r"```(?:json)?\n?", "", raw.strip()).strip().rstrip("`").strip()
    try:
        return json.loads(clean)
    except Exception:
        pass

    match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", raw)
    if match:
        try:
            return json.loads(match.group())
        except Exception:
            pass

    return {}


# ── Core pipeline functions ────────────────────────────────────────────────────

def _extract_scenarios(ac_text: str, claude: "ChatAnthropic") -> list[str]:
    """Stage 1: Extract testable scenario strings from raw AC text."""
    resp = claude.invoke([HumanMessage(content=_EXTRACT_PROMPT.format(ac=ac_text))])
    raw  = resp.content.strip()
    data = _parse_json(raw)
    if isinstance(data, list):
        return data
    # Fallback: parse line by line for BDD-style AC
    return [
        ln.strip("- ").strip()
        for ln in ac_text.splitlines()
        if ln.strip().startswith(("Given", "When", "Scenario", "Then", "-"))
    ][:12]


def _code_context(scenario: str, card_name: str) -> str:
    """Query automation POM + backend code RAG for structured context."""
    parts: list[str] = []
    query = f"{card_name} {scenario}"

    try:
        from rag.code_indexer import search_code

        # Automation POM — always include label generation workflow
        label_docs = search_code(
            "generate label app order grid navigate MCSL",
            k=5, source_type="automation",
        )
        scenario_pom_docs = search_code(query, k=5, source_type="automation")
        pom_docs = (label_docs or []) + (scenario_pom_docs or [])

        be_docs = search_code(query, k=3, source_type="storepepsaas_server") or []
        fe_docs: list = []
        try:
            fe_docs = search_code(query, k=3, source_type="storepepsaas_client") or []
        except Exception:
            pass

        if pom_docs:
            snippets = "\n---\n".join(
                f"[{d.metadata.get('file_path', '').split('/')[-1]}]\n{d.page_content[:600]}"
                for d in pom_docs[:5]
            )
            parts.append(f"=== AUTOMATION WORKFLOW (from POM) ===\n{snippets}")

        if be_docs:
            snippets = "\n---\n".join(d.page_content[:400] for d in be_docs)
            parts.append(f"=== BACKEND MODELS ===\n{snippets}")

        if fe_docs:
            snippets = "\n---\n".join(d.page_content[:300] for d in fe_docs)
            parts.append(f"=== FRONTEND CODE ===\n{snippets}")

    except Exception as e:
        logger.debug("Code RAG error in _code_context: %s", e)

    return "\n\n".join(parts)


def _ask_domain_expert(scenario: str, card_name: str, claude: "ChatAnthropic") -> str:
    """Stage 2: Query Domain Expert RAG and ask Claude for expected behaviour.

    Queries mcsl_knowledge (KB, wiki, sheets) and mcsl_code_knowledge (source code).
    Returns a plain-text insight string (≤200 words) for injection into planning prompt.
    """
    query = f"{card_name} {scenario}"
    domain_sections: list[str] = []
    code_parts: list[str] = []

    _DOMAIN_SOURCES = [
        ("kb_articles",  query, "MCSL Knowledge Base",              4),
        ("wiki",         query, "Internal Wiki (Product & Engineering)", 5),
        ("sheets",       query, "Test Cases & Acceptance Criteria",  3),
    ]

    try:
        from rag.vectorstore import search_filtered
        for src_type, q, label, k in _DOMAIN_SOURCES:
            try:
                docs = search_filtered(q, k=k, source_type=src_type)
                if docs:
                    def _fmt(d: Any) -> str:
                        cat = d.metadata.get("category", "")
                        prefix = f"[{cat}] " if cat else ""
                        return f"{prefix}{d.page_content[:450]}"
                    chunks = "\n\n".join(_fmt(d) for d in docs)
                    domain_sections.append(f"[{label}]\n{chunks}")
            except Exception as e:
                logger.debug("Domain RAG sub-query failed (source_type=%s): %s", src_type, e)
    except ImportError as e:
        logger.debug("search_filtered not available — falling back to unfiltered: %s", e)
        try:
            from rag.vectorstore import search as rag_search
            docs = rag_search(query, k=8)
            if docs:
                domain_sections.append("\n\n".join(
                    f"[{d.metadata.get('source_type', 'doc')}] {d.page_content[:450]}"
                    for d in docs
                ))
        except Exception as e2:
            logger.debug("Fallback domain RAG failed: %s", e2)

    try:
        from rag.code_indexer import search_code
        auto_docs = search_code(query, k=5, source_type="automation")
        if auto_docs:
            code_parts.append("\n---\n".join(
                f"[{d.metadata.get('file_path', '').split('/')[-1]}]\n{d.page_content[:500]}"
                for d in auto_docs
            ))
        be_docs = search_code(query, k=4, source_type="storepepsaas_server")
        if be_docs:
            code_parts.append("\n---\n".join(
                f"[{d.metadata.get('file_path', '').split('/')[-1]}]\n{d.page_content[:400]}"
                for d in be_docs
            ))
    except Exception as e:
        logger.debug("Code RAG error in expert: %s", e)

    domain_context = "\n\n---\n\n".join(domain_sections) or "(no domain knowledge indexed)"
    code_context   = "\n\n".join(code_parts)              or "(no code indexed)"

    prompt = _DOMAIN_EXPERT_PROMPT.format(
        scenario=scenario,
        card_name=card_name,
        domain_context=domain_context[:4000],
        code_context=code_context[:3000],
        preconditions_section="",
    )

    try:
        resp = claude.invoke([HumanMessage(content=prompt)])
        answer = resp.content.strip()
        if isinstance(answer, list):
            answer = " ".join(
                b.get("text", "") if isinstance(b, dict) else str(b) for b in answer
            )
        return answer[:1200]
    except Exception as e:
        logger.warning("Domain expert query failed: %s", e)
        return "(domain expert unavailable)"


def _plan_scenario(
    scenario: str,
    app_url: str,
    code_ctx: str,
    expert_insight: str,
    claude: "ChatAnthropic",
) -> dict:
    """Stage 3: Generate JSON execution plan with carrier injection.

    Detects carrier from scenario text and injects:
      - Carrier name + code into the prompt header
      - Carrier config steps if the scenario involves account setup (CARRIER-02)
    """
    carrier_name, carrier_code = _detect_carrier(scenario)

    # Build carrier context block
    carrier_context_lines = [
        f"CARRIER CONTEXT:",
        f"  Name: {carrier_name or '(none)'}",
        f"  Internal Code: {carrier_code or '—'}",
        "",
        f"Use {carrier_name}-specific service codes, account configuration, and special service flows."
        if carrier_name else "If no carrier detected, treat as carrier-agnostic.",
    ]

    # Detect carrier account config scenarios (CARRIER-02)
    scenario_lower = scenario.lower()
    is_carrier_config = any(kw in scenario_lower for kw in _CARRIER_CONFIG_KEYWORDS)
    if is_carrier_config and carrier_name:
        config_steps = _get_carrier_config_steps(carrier_name, action="add")
        carrier_context_lines += [
            "",
            f"CARRIER ACCOUNT CONFIGURATION STEPS for {carrier_name}:",
        ] + [f"  {i + 1}. {step}" for i, step in enumerate(config_steps)]

    # Detect special service scenarios (CARRIER-03/04/05/06) and inject preconditions
    app_base = app_url.rstrip("/")
    is_special_service = any(kw in scenario_lower for kw in _SPECIAL_SERVICE_KEYWORDS)
    preconditions_block = ""
    if is_special_service and carrier_name:
        precondition_steps = _get_preconditions(scenario_text=scenario, carrier=carrier_name, app_base=app_base)
        if precondition_steps:
            formatted = "\n".join(
                f"  {i + 1}. {step}" for i, step in enumerate(precondition_steps)
            )
            preconditions_block = (
                f"\nPRE-REQUISITE STEPS (must be completed before verification):\n"
                f"{formatted}\n"
            )
            carrier_context_lines += ["", "PRE-REQUISITE STEPS injected — see preconditions_block."]

    carrier_context = "\n".join(carrier_context_lines)

    prompt = _PLAN_PROMPT.format(
        scenario=scenario,
        app_url=app_url,
        carrier_name=carrier_name or "(none)",
        carrier_code=carrier_code or "—",
        mcsl_workflow_guide=_MCSL_WORKFLOW_GUIDE,
        expert_insight=expert_insight or "(not available)",
        code_context=code_ctx[:5000],
    )
    if preconditions_block:
        prompt = prompt + preconditions_block
    resp = claude.invoke([HumanMessage(content=prompt)])
    plan = _parse_json(resp.content) or {}
    # Ensure carrier field is always present
    if "carrier" not in plan:
        plan["carrier"] = carrier_name
    return plan


# ── Browser state capture (implemented in plan 02-02) ─────────────────────────

def _walk(node: dict, lines: list[str], depth: int = 0, max_depth: int = 6) -> None:
    """Recursively walk an accessibility snapshot, appending readable lines."""
    if depth > max_depth or len(lines) > 250:
        return
    role = node.get("role", "")
    name = node.get("name", "")
    _SKIP_ROLES = {"generic", "none", "presentation", "document", "group", "list", "region"}
    if role and name and role not in _SKIP_ROLES:
        ln = f"{'  ' * depth}{role}: '{name}'"
        c = node.get("checked")
        if c is not None:
            ln += f" [checked={c}]"
        v = node.get("value", "")
        if v and role in ("textbox", "combobox"):
            ln += f" [value='{v[:30]}']"
        lines.append(ln)
    for child in node.get("children", []):
        _walk(child, lines, depth + 1, max_depth)


def _ax_tree(page: Any, max_lines: int = 250) -> str:
    """Accessibility tree as readable text — captures both Shopify admin and app iframe.

    Dual-frame capture: main page first, then any iframe whose URL contains
    'shopify', 'pluginhive', or 'apps' (the MCSL app iframe filter).
    """
    lines: list[str] = []

    # 1. Main page snapshot (Shopify admin chrome — sidebar, headers)
    try:
        ax = page.accessibility.snapshot(interesting_only=True)
        if ax:
            _walk(ax, lines)
    except Exception as e:
        lines.append(f"(main page snapshot error: {e})")

    # 2. App iframe — all MCSL app UI lives inside iframe[name="app-iframe"]
    #    Without this, the agent is blind to app buttons, dropdowns, and inputs.
    try:
        for frame in page.frames:
            if frame is page.main_frame:
                continue
            frame_url = frame.url or ""
            # Only capture app-related iframes (skip Shopify analytics/tracking iframes)
            if not frame_url or (
                "shopify" not in frame_url
                and "pluginhive" not in frame_url
                and "apps" not in frame_url
            ):
                continue
            try:
                frame_ax = frame.accessibility.snapshot(interesting_only=True)
                if frame_ax:
                    lines.append(f"\n--- [APP IFRAME: {frame_url[:60]}] ---")
                    _walk(frame_ax, lines)
                    lines.append("--- [END IFRAME] ---")
            except Exception:
                pass
    except Exception:
        pass

    # Truncate to max_lines
    if len(lines) > max_lines:
        lines = lines[:max_lines]

    return "\n".join(lines) or "(no interactive elements)"


_NET_JS = """() =>
    performance.getEntriesByType('resource')
      .filter(e => ['xmlhttprequest','fetch'].includes(e.initiatorType))
      .slice(-40).map(e => e.name)
"""


def _screenshot(page: Any) -> str:
    """Base64 PNG of current page."""
    try:
        raw = page.screenshot(full_page=False, scale="css")
        return base64.standard_b64encode(raw).decode()
    except Exception:
        try:
            return base64.standard_b64encode(page.screenshot(full_page=False)).decode()
        except Exception:
            return ""


def _network(page: Any, patterns: list[str] | None = None) -> str:
    """Recent API/XHR calls matching any pattern — returns newline-joined string.

    Checks both the main page and app iframe frames so MCSL API calls are captured.
    Returns empty string if no matching requests found.
    """
    all_entries: list[str] = []

    # Main page
    try:
        entries = page.evaluate(_NET_JS)
        all_entries.extend(entries or [])
    except Exception:
        pass

    # App iframe frames (same URL filter as _ax_tree)
    try:
        for frame in page.frames:
            if frame is page.main_frame:
                continue
            frame_url = frame.url or ""
            if not frame_url or (
                "shopify" not in frame_url
                and "pluginhive" not in frame_url
                and "apps" not in frame_url
            ):
                continue
            try:
                entries = frame.evaluate(_NET_JS)
                all_entries.extend(entries or [])
            except Exception:
                pass
    except Exception:
        pass

    # Deduplicate
    seen: set[str] = set()
    hits: list[str] = []
    for e in all_entries:
        if e not in seen:
            seen.add(e)
            hits.append(e)

    if patterns:
        hits = [e for e in hits if any(p in e for p in patterns)]
    else:
        hits = [e for e in hits if "/api/" in e or "pluginhive" in e.lower()]

    return "\n".join(hits)


def _get_app_frame(page: Any) -> Any:
    """Return the app iframe Frame object, falling back to page if not found."""
    try:
        for frame in page.frames:
            if "app-iframe" in (frame.name or ""):
                return frame
            url = frame.url or ""
            if "pluginhive" in url or ("apps" in url and "shopify" in url):
                return frame
    except Exception:
        pass
    return page  # fallback to main page


def _format_zip_for_context(extracted: dict) -> str:
    """Format extracted ZIP contents into a readable context string for Claude."""
    lines = ["=== Downloaded ZIP contents ==="]
    for fname, content in extracted.items():
        if isinstance(content, dict):
            lines.append(f"[{fname}] JSON object with keys: {list(content.keys())}")
            snippet = json.dumps(content, indent=2)[:800]
            lines.append(snippet)
        elif isinstance(content, str):
            lines.append(f"[{fname}]\n{content[:500]}")
        else:
            lines.append(f"[{fname}] {content}")
    return "\n".join(lines)


def _format_file_for_context(content: "dict | str") -> str:
    """Format downloaded file content into a readable context string for Claude."""
    if isinstance(content, dict):
        headers = content.get("headers", [])
        row_count = content.get("row_count", 0)
        sample_rows = content.get("sample_rows", [])
        raw_preview = content.get("raw_preview", "")
        lines = [
            "=== Downloaded file contents ===",
            f"Headers: {headers}",
            f"Row count: {row_count}",
            f"Sample rows: {sample_rows[:5]}",
        ]
        if raw_preview:
            lines.append(f"Preview:\n{raw_preview[:500]}")
        return "\n".join(lines)
    return f"=== Downloaded file ===\n{str(content)[:1000]}"


def _do_action(page: Any, action: dict, app_base: str = "") -> bool:
    """Execute a Claude-decided browser action. Returns True on success, False on failure.

    Handles all 11 action types:
      observe, click, fill, scroll, navigate, switch_tab, close_tab,
      verify, qa_needed, download_zip (stub), download_file (stub)
    """
    atype = action.get("action", "observe")

    # No-op actions — agentic loop handles verdict/question extraction
    if atype in ("observe", "verify", "qa_needed"):
        return True

    if atype == "scroll":
        try:
            page.mouse.wheel(0, action.get("delta_y", 300))
        except Exception:
            try:
                page.evaluate("window.scrollBy(0, 400)")
            except Exception:
                pass
        return True

    if atype == "navigate":
        destination = action.get("url", "")
        store = getattr(config, "STORE", "")
        return _navigate_in_app(page, destination, store)

    if atype == "switch_tab":
        try:
            pages = page.context.pages
            if len(pages) > 1:
                new_page = pages[-1]
                new_page.wait_for_load_state("domcontentloaded")
                action["_new_page"] = new_page
                return True
            return False
        except Exception as e:
            logger.debug("switch_tab failed: %s", e)
            return False

    if atype == "close_tab":
        try:
            page.close()
            remaining = page.context.pages
            if remaining:
                action["_new_page"] = remaining[0]
            return True
        except Exception as e:
            logger.debug("close_tab failed: %s", e)
            return False

    if atype == "download_zip":
        try:
            import shutil as _shutil
            tmp_dir = tempfile.mkdtemp(prefix="sav_zip_")
            zip_path = os.path.join(tmp_dir, "mcsl_download.zip")
            frame = _get_app_frame(page)
            target = action.get("target", action.get("selector", "")).strip()

            el_to_click = None
            for fn in [
                lambda: frame.get_by_role("button", name=target, exact=False),
                lambda: frame.get_by_role("link",   name=target, exact=False),
                lambda: frame.get_by_text(target, exact=False),
                lambda: page.get_by_role("button",  name=target, exact=False),
                lambda: page.get_by_role("link",    name=target, exact=False),
                lambda: page.get_by_text(target, exact=False),
            ]:
                try:
                    el = fn()
                    if el.count() > 0:
                        el_to_click = el.first
                        break
                except Exception:
                    continue

            if el_to_click is None:
                logger.debug("download_zip: target %r not found", target)
                _shutil.rmtree(tmp_dir, ignore_errors=True)
                return False

            with page.expect_download(timeout=30_000) as dl_info:
                el_to_click.click(timeout=5_000)

            dl = dl_info.value
            dl.save_as(zip_path)
            page.wait_for_timeout(500)

            extracted: dict = {}
            with zipfile.ZipFile(zip_path, "r") as zf:
                for name in zf.namelist():
                    ext = name.rsplit(".", 1)[-1].lower()
                    if ext == "json":
                        raw = zf.read(name).decode("utf-8", errors="replace")
                        try:
                            extracted[name] = json.loads(raw)
                        except Exception:
                            extracted[name] = raw
                    elif ext in ("csv", "txt", "xml", "log"):
                        extracted[name] = zf.read(name).decode("utf-8", errors="replace")[:3000]
                    else:
                        info = zf.getinfo(name)
                        extracted[name] = f"({ext.upper()} binary — {info.file_size:,} bytes)"

            action["_zip_content"] = extracted
            logger.info("download_zip: extracted %d files — %s", len(extracted), list(extracted.keys()))
            _shutil.rmtree(tmp_dir, ignore_errors=True)
            return True
        except Exception as e:
            logger.debug("download_zip failed: %s", e)
            return False

    if atype == "download_file":
        try:
            import csv as _csv
            import shutil as _shutil
            tmp_dir = tempfile.mkdtemp(prefix="sav_file_")
            frame = _get_app_frame(page)
            target = action.get("target", action.get("selector", "")).strip()

            el_to_click = None
            for fn in [
                lambda: frame.get_by_role("button", name=target, exact=False),
                lambda: frame.get_by_role("link",   name=target, exact=False),
                lambda: frame.get_by_text(target, exact=False),
                lambda: page.get_by_role("button",  name=target, exact=False),
                lambda: page.get_by_role("link",    name=target, exact=False),
                lambda: page.get_by_text(target, exact=False),
            ]:
                try:
                    el = fn()
                    if el.count() > 0:
                        el_to_click = el.first
                        break
                except Exception:
                    continue

            if el_to_click is None:
                logger.debug("download_file: target %r not found", target)
                _shutil.rmtree(tmp_dir, ignore_errors=True)
                return False

            with page.expect_download(timeout=30_000) as dl_info:
                el_to_click.click(timeout=5_000)

            dl = dl_info.value
            suggested = getattr(dl, "suggested_filename", "") or "download"
            ext = suggested.rsplit(".", 1)[-1].lower() if "." in suggested else ""
            file_path = os.path.join(tmp_dir, suggested or "download")
            dl.save_as(file_path)
            page.wait_for_timeout(500)

            file_size = os.path.getsize(file_path)
            result_content: "dict | str"

            if ext == "csv":
                with open(file_path, "r", encoding="utf-8", errors="replace") as fh:
                    raw = fh.read()
                reader = _csv.reader(raw.splitlines())
                rows = list(reader)
                headers = rows[0] if rows else []
                data_rows = rows[1:] if len(rows) > 1 else []
                result_content = {
                    "headers": headers,
                    "row_count": len(data_rows),
                    "sample_rows": data_rows[:5],
                    "raw_preview": raw[:500],
                }
            elif ext in ("xlsx", "xls"):
                try:
                    import openpyxl as _openpyxl
                    wb = _openpyxl.load_workbook(file_path, read_only=True, data_only=True)
                    ws = wb.active
                    all_rows = list(ws.iter_rows(values_only=True))
                    headers = list(all_rows[0]) if all_rows else []
                    data_rows = [list(r) for r in all_rows[1:]]
                    result_content = {
                        "headers": headers,
                        "row_count": len(data_rows),
                        "sample_rows": data_rows[:5],
                        "raw_preview": "",
                    }
                    wb.close()
                except Exception:
                    result_content = f"(Excel — {file_size:,} bytes)"
            elif ext == "pdf":
                result_content = f"(PDF — {file_size:,} bytes)"
            else:
                try:
                    with open(file_path, "r", encoding="utf-8", errors="replace") as fh:
                        result_content = fh.read(2000)
                except Exception:
                    result_content = f"({ext.upper() or 'BINARY'} — {file_size:,} bytes)"

            action["_file_content"] = result_content
            logger.info("download_file: saved %r (%d bytes, ext=%s)", suggested, file_size, ext)
            _shutil.rmtree(tmp_dir, ignore_errors=True)
            return True
        except Exception as e:
            logger.debug("download_file failed: %s", e)
            return False

    # click and fill require a frame-aware locator
    frame = _get_app_frame(page)
    sel = action.get("selector", action.get("target", "")).strip()

    if atype == "click":
        for fn in [
            lambda: frame.get_by_role("button", name=sel, exact=True).first.click(),
            lambda: frame.get_by_role("link", name=sel, exact=True).first.click(),
            lambda: frame.get_by_label(sel, exact=True).first.click(),
            lambda: frame.get_by_text(sel, exact=True).first.click(),
            lambda: frame.get_by_text(sel).first.click(),
            lambda: frame.locator(sel).first.click(),
            lambda: frame.locator(sel).first.dispatch_event("click"),
        ]:
            try:
                fn()
                page.wait_for_timeout(400)
                return True
            except Exception:
                continue
        logger.debug("click failed all strategies for selector: %r", sel)
        return False

    if atype == "fill":
        label = action.get("label", sel)
        value = action.get("value", "")
        for fn in [
            lambda: frame.get_by_label(label).fill(value),
            lambda: frame.get_by_placeholder(action.get("label", "")).fill(value),
            lambda: frame.locator(action.get("selector", "input")).first.fill(value),
        ]:
            try:
                fn()
                return True
            except Exception:
                continue
        return False

    return True


_DECISION_PROMPT = dedent("""\
    You are verifying this AC scenario in the MCSL Multi-Carrier Shipping Shopify App.

    SCENARIO: {scenario}
    CARRIER: {carrier_name} (internal code: {carrier_code})
    Use {carrier_name}-specific service codes, account configuration, and special service flows.
    If carrier is empty, treat as carrier-agnostic.

    DOMAIN EXPERT INSIGHT (what this feature does + what to look for):
    {expert_insight}

    MCSL WORKFLOW GUIDE:
{mcsl_workflow_guide}

    CURRENT PAGE: {url}
    ACCESSIBILITY TREE (what is visible):
    {ax_tree}

    NETWORK CALLS SEEN SO FAR:
    {network_calls}

    STEPS TAKEN SO FAR ({step_num}/{max_steps}):
    {steps_taken}

    CODE KNOWLEDGE:
    {code_context}

    Decide your NEXT action. Respond ONLY in JSON — no extra text:
    {{
      "action":      "click" | "fill" | "scroll" | "observe" | "navigate" | "verify" | "qa_needed" | "switch_tab" | "close_tab" | "download_zip" | "download_file",
      "target":      "<exact element name from accessibility tree — required for click/fill>",
      "selector":    "<CSS/aria selector — alternative to target for click>",
      "value":       "<text to type (fill)>",
      "url":         "<named destination or full URL — required for navigate>",
      "delta_y":     "<pixels to scroll — optional for scroll, default 300>",
      "label":       "<input label — for fill actions>",
      "description": "one sentence: what you are doing and why",
      "verdict":     "pass | fail | partial  — ONLY when action=verify",
      "finding":     "what you observed      — ONLY when action=verify",
      "question":    "your question for QA   — ONLY when action=qa_needed"
    }}

    Available named navigate destinations (use in url field):
    ── In-app tabs (click the tab — no URL jump) ──
    - "orders"           → ORDERS tab — app order grid (label generation, filtering)
    - "labels"           → LABELS tab
    - "pickup"           → PICKUP tab — pickup scheduling
    - "manifest"         → MANIFEST tab
    - "tracking"         → TRACKING tab — shipment tracking
    ── In-app hamburger sections (Menu button → search → click) ──
    - "carriers"         → Carriers — add/edit carrier accounts
    - "appproducts"      → Products — MCSL product settings (dimensions, special services)
    - "automation"       → Automation — automation rules
    - "shippingrates"    → Shipping Rates
    - "generalsettings"  → General Settings
    - "address"          → Address settings
    - "views"            → Views — custom order grid views
    - "bulkimports"      → Bulk Imports
    - "account"          → Account
    - "stores"           → Stores
    ── Shopify admin (leaves app, full page navigation) ──
    - "shopifyorders"    → Shopify admin orders — use ONLY for post-fulfillment checks
    - "shopifyproducts"  → Shopify admin products — create/edit Shopify products

    Rules:
    - action=verify      → you have clear evidence to give a verdict (pass/fail/partial)
    - action=qa_needed   → you genuinely cannot locate the feature after careful searching
    - ONLY reference targets that literally appear in the accessibility tree above
    - MCSL has ONE endpoint — never construct sub-URLs; always navigate by clicking
    - App content is in iframe[name="app-iframe"] — click targets are INSIDE the app frame
    - action=observe on first step to capture visible elements before interacting
    - Do NOT explore unrelated sections of the app
    - If expected order not visible: look for "Refresh" button and click it; else reload page

    TWO COMPLETELY DIFFERENT PRODUCT PAGES:
    - navigate: "appproducts"  →  MCSL Products (edit existing product special service settings)
      USE FOR: dry ice, alcohol, battery, dimensions, signature, declared value config
      ⚠️ NO "Add product" button — cannot CREATE products here
    - navigate: "shopifyproducts"  →  Shopify Products admin
      USE FOR: create/edit Shopify products (title, price, weight, SKU, variants)
      ⚠️ This is NOT the MCSL app — no MCSL-specific fields here

    Label generation (same flow for ALL carriers — NOT Shopify More Actions):
    1. navigate: "orders" → ORDERS tab loads in app iframe
    2. If order not visible → click Refresh button OR reload
    3. Click "Add filter" → "Order Id" → type order ID → press Escape
    4. Click the order link (bold order number) → Order Summary opens
    5. If "Prepare Shipment" visible → click it (up to 3 times if it reappears)
    6. Click "Generate Label" → wait for status button (nth(2)) = "LABEL CREATED"
    7. Click "Mark As Fulfilled" → wait for status = "FULFILLED"
""")


def _decide_next(
    claude: "ChatAnthropic",
    scenario: str,
    url: str,
    ax: str,
    net_seen: list[str],
    steps: list[VerificationStep],
    ctx: str,
    step_num: int,
    scr: str = "",
    expert_insight: str = "",
) -> dict:
    """Ask Claude what action to take next in the agentic verification loop.

    Sends current page state (AX tree + screenshot + prior steps) to Claude and
    parses the returned JSON action. Falls back to qa_needed on unparseable response.
    """
    carrier_name, carrier_code = _detect_carrier(scenario)
    steps_text = "\n".join(
        f"  {i + 1}. [{s.action}] {s.description} ({'OK' if s.success else 'FAIL'})"
        for i, s in enumerate(steps)
    )
    net_text = "\n".join(net_seen[-10:]) if net_seen else "(none)"

    prompt_text = _DECISION_PROMPT.format(
        scenario=scenario,
        carrier_name=carrier_name or "(none)",
        carrier_code=carrier_code or "—",
        expert_insight=expert_insight or "(not available)",
        mcsl_workflow_guide=_MCSL_WORKFLOW_GUIDE,
        url=url,
        ax_tree=ax[:3000],
        network_calls=net_text,
        steps_taken=steps_text or "(just starting)",
        code_context=ctx[:3000],
        step_num=step_num,
        max_steps=MAX_STEPS,
    )

    # Build HumanMessage — include base64 screenshot if available
    content: list[dict] = [{"type": "text", "text": prompt_text}]
    if scr:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{scr}"},
        })
    msg = HumanMessage(content=content)

    try:
        response = claude.invoke([msg])
        raw = response.content
        if not isinstance(raw, str):
            # Handle list-of-blocks content format
            raw = " ".join(
                b.get("text", "") if isinstance(b, dict) else str(b)
                for b in raw
            )
        parsed = _parse_json(raw)
        if not parsed or "action" not in parsed:
            logger.warning(
                "[decide] Could not parse valid action from Claude response — "
                "falling back to qa_needed.\nRaw: %s", raw[:400]
            )
            return {"action": "qa_needed", "question": "Claude returned unparseable response"}
        logger.debug("[decide] action=%s target=%s", parsed.get("action"), parsed.get("target", ""))
        return parsed
    except Exception as e:
        logger.warning("[decide] Claude invocation failed: %s", e)
        return {"action": "qa_needed", "question": "Claude returned unparseable response"}


def _launch_browser(headless: bool = False):
    """Launch a Chromium browser with anti-bot args and auth.json storage state.

    Returns:
        (playwright_instance, browser, context, page) tuple.
    """
    from playwright.sync_api import sync_playwright  # local import — only needed at runtime

    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        channel="chrome",
        headless=headless,
        args=_ANTI_BOT_ARGS,
    )
    ctx_kwargs: dict = {"viewport": {"width": 1400, "height": 1000}}
    if _AUTH_JSON.exists():
        try:
            json.loads(_AUTH_JSON.read_text(encoding="utf-8"))
            ctx_kwargs["storage_state"] = str(_AUTH_JSON)
        except Exception:
            pass
    context = browser.new_context(**ctx_kwargs)
    page = context.new_page()
    page.set_default_timeout(30_000)
    return pw, browser, context, page


def _verify_scenario(
    page: Any,
    scenario: str,
    card_name: str,
    app_base: str,
    plan_data: dict,
    ctx: str = "",
    claude: "ChatAnthropic | None" = None,
    progress_cb: "Callable[[int, str], None] | None" = None,
    qa_answer: str = "",
    first_scenario: bool = False,
    expert_insight: str = "",
    stop_flag: "Callable[[], bool] | None" = None,
) -> ScenarioResult:
    """Run the agentic browser loop for one scenario — up to MAX_STEPS iterations.

    Each step:
      1. Captures AX tree (dual-frame), screenshot, and filtered network calls
      2. Calls _decide_next (Claude) to choose an action
      3. Executes the action via _do_action
      4. Breaks on 'verify' (verdict reached) or 'qa_needed' (needs human)

    active_page tracks tab switches — updated when action contains '_new_page'.
    """
    carrier_name, _ = _detect_carrier(scenario)
    result = ScenarioResult(scenario=scenario, carrier=plan_data.get("carrier", carrier_name))
    active_page = page
    zip_ctx = ""
    net_seen: list[str] = []
    api_endpoints: list[str] = plan_data.get("api_to_watch", [])

    # --- ORDER CREATION (if plan requires it) ---
    order_id: str | None = None
    order_action = plan_data.get("order_action", "")
    carrier_code = plan_data.get("carrier_code", "")

    if order_action in ("create_new", "create_bulk") and carrier_code:
        try:
            from pipeline.order_creator import (
                create_order, create_bulk_orders, get_carrier_env_for_code
            )
            env_path = get_carrier_env_for_code(carrier_code)

            use_dangerous = bool(plan_data.get("dangerous_products"))
            if order_action == "create_new":
                order_id = create_order(env_path, use_dangerous_products=use_dangerous)
                logger.info(f"Created order for scenario: {order_id}")
            elif order_action == "create_bulk":
                order_ids = create_bulk_orders(env_path, count=3, use_dangerous_products=use_dangerous)
                order_id = order_ids[0] if order_ids else None
                logger.info(f"Created bulk orders: {order_ids}")

            if order_id:
                # Inject order ID into scenario context so Claude can use it
                ctx = f"TEST ORDER ID: {order_id}\n\n{ctx}"
        except Exception as e:
            logger.warning(f"Order creation failed for {order_action}/{carrier_code}: {e}")
            # Continue without order — agent will attempt to find existing orders

    for step_num in range(1, MAX_STEPS + 1):
        if stop_flag and stop_flag():
            result.status = "partial"
            result.finding = "Stopped by user"
            break

        ax  = _ax_tree(active_page)
        scr = _screenshot(active_page)
        net = _network(active_page, api_endpoints)
        if net:
            net_seen.append(net)

        effective_ctx = f"{zip_ctx}\n{ctx}" if zip_ctx else ctx
        step = StepResult(step_num=step_num, ax_tree=ax, screenshot_b64=scr)

        action = _decide_next(
            claude, scenario, active_page.url, ax,
            net_seen, result.steps, effective_ctx,
            step_num, scr=scr, expert_insight=expert_insight,
        )
        atype = action.get("action", "observe")
        step.action = atype
        step.description = action.get("description", atype)
        step.target = action.get("target", "")
        step.success = _do_action(active_page, action, app_base)
        result.steps.append(step)

        logger.info("[step %d/%d] action=%-12s target=%-30s | %s",
                    step_num, MAX_STEPS, atype, step.target[:30], step.description[:80])

        if atype == "verify":
            result.status = action.get("verdict", "partial")
            result.finding = action.get("finding", "")
            result.evidence_screenshot = scr
            break

        if atype == "qa_needed":
            result.status = "qa_needed"
            result.finding = action.get("question", action.get("finding", ""))
            result.qa_question = result.finding
            break

        if "_new_page" in action:
            active_page = action["_new_page"]

        if "_zip_content" in action:
            zip_ctx = _format_zip_for_context(action["_zip_content"])
        if "_file_content" in action:
            zip_ctx = _format_file_for_context(action["_file_content"])

    else:
        result.status = "partial"
        result.finding = f"Loop completed {MAX_STEPS} steps without verdict"

    return result


# ── Entry point ────────────────────────────────────────────────────────────────

def verify_ac(
    ac_text: str,
    card_name: str = "",
    stop_flag: "Callable[[], bool] | None" = None,
    headless: bool = False,
    app_url: str = "",
    progress_cb: "Callable[[int, str, int, str], None] | None" = None,
    qa_answers: "dict[str, str] | None" = None,
    max_scenarios: "int | None" = None,
) -> VerificationReport:
    """Verify AC scenarios for a card against the live MCSL Shopify app.

    Main entry point. Extracts scenarios from AC text and verifies each one
    using the agentic browser loop.

    Args:
        ac_text:        Full AC markdown text
        card_name:      Feature / card title
        stop_flag:      Optional callable — returns True to abort before next scenario
        headless:       Run browser headless (default False)
        app_url:        Full MCSL app URL in Shopify admin (auto-built from config.STORE if empty)
        progress_cb:    Optional callback(scenario_idx, scenario_title, step_num, step_desc)
        qa_answers:     {scenario_text: qa_answer} for stuck scenarios
        max_scenarios:  Cap number of scenarios tested (None = test all)

    Returns:
        VerificationReport with per-scenario results (even if all fail or stop_flag triggers)
    """
    if not app_url:
        store = getattr(config, "STORE", "")
        if store:
            app_url = f"https://admin.shopify.com/store/{store}/apps/mcsl-qa"

    report = VerificationReport(card_name=card_name, app_url=app_url)
    start = time.time()

    if not ac_text:
        report.duration_seconds = time.time() - start
        return report

    # Initialise Claude (ANTHROPIC_API_KEY validated at runtime — missing key raises here)
    claude = ChatAnthropic(
        model=getattr(config, "CLAUDE_SONNET_MODEL", "claude-sonnet-4-5"),
        api_key=getattr(config, "ANTHROPIC_API_KEY", ""),
        max_tokens=4096,
    )

    # Extract scenarios
    try:
        scenarios = _extract_scenarios(ac_text, claude)
    except Exception as e:
        logger.error(f"Scenario extraction failed: {e}")
        report.duration_seconds = time.time() - start
        return report

    if not scenarios:
        logger.warning("No scenarios extracted from AC text")
        report.duration_seconds = time.time() - start
        return report

    if max_scenarios and max_scenarios < len(scenarios):
        scenarios = scenarios[:max_scenarios]
        logger.info("verify_ac: capped to %d scenarios for '%s'", len(scenarios), card_name)
    else:
        logger.info("verify_ac: %d scenarios for '%s'", len(scenarios), card_name)

    # Launch browser
    pw, browser, ctx, page = _launch_browser(headless=headless)

    try:
        for idx, scenario in enumerate(scenarios):
            # Check stop flag BEFORE each scenario
            if stop_flag and stop_flag():
                logger.info(f"Stop flag triggered before scenario {idx + 1} — halting")
                break

            logger.info("[%d/%d] Verifying: %s", idx + 1, len(scenarios), scenario[:70])

            if progress_cb:
                progress_cb(idx + 1, scenario, 0, "Asking domain expert…")

            try:
                expert_insight = _ask_domain_expert(scenario, card_name, claude)
                code_ctx       = _code_context(scenario, card_name)
                plan_data      = _plan_scenario(scenario, app_url, code_ctx, expert_insight, claude)

                sv = _verify_scenario(
                    page=page,
                    scenario=scenario,
                    card_name=card_name,
                    app_base=app_url,
                    plan_data=plan_data,
                    ctx=code_ctx,
                    claude=claude,
                    progress_cb=None,
                    qa_answer=(qa_answers or {}).get(scenario, ""),
                    first_scenario=(idx == 0),
                    expert_insight=expert_insight,
                    stop_flag=stop_flag,
                )
            except Exception as e:
                logger.error(f"Scenario {idx + 1} failed with exception: {e}")
                sv = ScenarioResult(
                    scenario=scenario,
                    status="fail",
                    finding=f"Agent exception: {e}",
                )

            report.scenarios.append(sv)
            logger.info(f"Scenario {idx + 1} result: {sv.status} — {sv.finding[:80]}")

    finally:
        browser.close()
        pw.stop()

    report.duration_seconds = time.time() - start
    logger.info(f"Verification complete: {report.summary} in {report.duration_seconds:.1f}s")
    return report
