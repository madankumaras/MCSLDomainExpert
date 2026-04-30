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

MCSL AI QA Agent:
  - Multi-carrier support: carrier name detected from AC text, injected into plan
  - CARRIER_CODES map — FedEx C2, UPS C3, DHL C1, USPS C22, etc.
  - App slug: mcsl-qa
  - iframe selector: iframe[name="app-iframe"]
  - Label flow: ORDERS tab → filter by Order Id → Order Summary → Generate Label → LABEL CREATED
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
from pipeline.carrier_knowledge import detect_carrier_scope
from pipeline.locator_knowledge import build_locator_context, fetch_code_locator_hints, save_runtime_locator_memory
from pipeline.request_expectations import build_request_expectations, compare_expectations

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

MAX_STEPS = 25

_ANTI_BOT_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-setuid-sandbox",
]

_AUTH_JSON = Path(config.MCSL_AUTOMATION_REPO_PATH) / "auth.json" if getattr(config, "MCSL_AUTOMATION_REPO_PATH", "") else Path(__file__).parent.parent / "auth.json"


def _store_slug(raw: str = "") -> str:
    """Return the bare Shopify store slug (no .myshopify.com suffix).

    STORE env var may be set to 'mystore.myshopify.com' or just 'mystore'.
    Shopify admin URLs require the slug form: admin.shopify.com/store/mystore/...
    """
    s = (raw or getattr(config, "STORE", "")).strip()
    return s.removesuffix(".myshopify.com")

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
    scope = detect_carrier_scope(ac_text)
    if scope.primary:
        return scope.primary.canonical_name, scope.primary.internal_code
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

_PRODUCT_SETUP_KEYWORDS = frozenset({
    "customs value", "country of origin", "coo", "hs code", "hs codes",
    "sku", "weight", "dimensions", "length", "width", "height",
    "declared value", "description", "origin country",
})

_PACKAGING_SETUP_KEYWORDS = frozenset({
    "packaging", "package", "box type", "package type", "custom box", "packaging settings",
})

_AUTOMATION_RULE_KEYWORDS = frozenset({
    "automation rule", "automation rules", "rate rule", "rate rules",
    "label rule", "automation criteria", "shipping rule",
})

_REQUEST_LOG_KEYWORDS = frozenset({
    "rate req", "label req", "request log", "response log", "view log",
    "rate request", "label request", "request and response",
})

_DOCUMENT_CHECK_KEYWORDS = frozenset({
    "print documents", "download documents", "commercial invoice", "cn22",
    "cn23", "document", "invoice", "manifest", "packing slip",
})

_SHOPIFY_VERIFY_KEYWORDS = frozenset({
    "tracking number", "tracking no", "fulfilled in shopify", "shopify fulfillment",
    "fulfill order", "shopify order", "shopify orders",
})

_SHOPIFY_PRODUCT_KEYWORDS = frozenset({
    "create product", "new product", "variant", "product id", "parent id",
    "shopify product", "shopify products",
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
            steps = label_flow  # Default: no special service setup needed

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


def _extract_explicit_preconditions(scenario: str) -> list[str]:
    lines: list[str] = []
    match = re.search(r"preconditions?:\s*(.+?)(?:\n|$)", scenario, re.IGNORECASE | re.DOTALL)
    if match:
        raw = match.group(1).strip()
        for part in re.split(r"[;\n]+", raw):
            clean = part.strip(" -")
            if clean:
                lines.append(clean)
    return lines


def _infer_setup_requirements(scenario: str, carrier_name: str, app_base: str = "") -> dict[str, Any]:
    lower = scenario.lower()
    nav_clicks: list[str] = []
    api_to_watch: list[str] = []
    look_for: list[str] = []
    precondition_steps: list[str] = []
    order_action = "none"

    def _add_nav(*values: str) -> None:
        for value in values:
            if value and value not in nav_clicks:
                nav_clicks.append(value)

    def _add_api(*values: str) -> None:
        for value in values:
            if value and value not in api_to_watch:
                api_to_watch.append(value)

    def _add_look(*values: str) -> None:
        for value in values:
            if value and value not in look_for:
                look_for.append(value)

    explicit = _extract_explicit_preconditions(scenario)
    for item in explicit:
        precondition_steps.append(f"Explicit precondition from test case: {item}")

    is_carrier_config = any(kw in lower for kw in _CARRIER_CONFIG_KEYWORDS)
    is_special_service = any(kw in lower for kw in _SPECIAL_SERVICE_KEYWORDS)
    is_product_setup = any(kw in lower for kw in _PRODUCT_SETUP_KEYWORDS)
    is_packaging = any(kw in lower for kw in _PACKAGING_SETUP_KEYWORDS)
    is_automation = any(kw in lower for kw in _AUTOMATION_RULE_KEYWORDS)
    is_request_log = any(kw in lower for kw in _REQUEST_LOG_KEYWORDS)
    is_document_check = any(kw in lower for kw in _DOCUMENT_CHECK_KEYWORDS)
    is_shopify_verify = any(kw in lower for kw in _SHOPIFY_VERIFY_KEYWORDS)
    is_shopify_product = any(kw in lower for kw in _SHOPIFY_PRODUCT_KEYWORDS)

    if is_carrier_config and carrier_name:
        _add_nav("carriers")
        precondition_steps.extend(_get_carrier_config_steps(carrier_name, action="add"))
        _add_look(f"{carrier_name} appears in the carriers list", "success toast after saving carrier settings")

    if is_special_service and carrier_name:
        _add_nav("appproducts", "orders")
        precondition_steps.extend(_get_preconditions(scenario_text=scenario, carrier=carrier_name, app_base=app_base))
        order_action = "create_new"

    if is_product_setup:
        _add_nav("appproducts")
        precondition_steps.extend([
            "Open MCSL Products from the hamburger menu.",
            "Open the existing test product settings.",
            "Update the required product fields for this scenario.",
            "Save product settings and confirm the success toast appears.",
        ])
        _add_look("updated product settings are visible", "success toast after product save")

    if is_packaging:
        _add_nav("generalsettings")
        precondition_steps.extend([
            "Open General Settings / packaging-related configuration from the app menu.",
            "Update the packaging or package-type setting required for the scenario.",
            "Save the setting and confirm the success toast appears.",
        ])
        _add_look("packaging setting is visible after save", "success toast after packaging change")

    if is_automation:
        _add_nav("automation")
        precondition_steps.extend([
            "Open Automation from the app menu.",
            "Create or edit the rule needed for the scenario.",
            "Save the rule and confirm it is listed as active or updated.",
        ])
        _add_look("automation rule appears in the list", "success toast after rule save")

    if is_request_log:
        _add_nav("orders")
        _add_api("/rates", "/label", "/shipment", "/documents")
        _add_look("View Log option is available on the order summary", "request/response payload contains expected scenario values")
        if order_action == "none":
            order_action = "create_new"

    if is_document_check:
        _add_nav("orders")
        _add_api("/documents", "/label")
        _add_look("Print Documents or Download Documents action is available", "expected document type is generated")
        if order_action == "none":
            order_action = "existing_fulfilled" if "download" in lower else "create_new"

    if is_shopify_verify:
        _add_nav("shopifyorders")
        _add_look("Shopify order shows fulfilled state", "tracking number appears on the Shopify order")

    if is_shopify_product:
        _add_nav("shopifyproducts")
        precondition_steps.extend([
            "Open Shopify Products admin.",
            "Create or edit the Shopify product needed for this scenario.",
            "Capture the product id and variant id after save.",
        ])
        _add_look("product appears in Shopify products admin", "product id / variant id can be retrieved for ordering")

    if "generate label" in lower or "label" in lower or "shipment" in lower:
        _add_nav("orders")
        _add_api("/rates", "/label", "/shipment")
        _add_look("order reaches LABEL CREATED", "label/rate request includes expected scenario data")
        if order_action == "none":
            order_action = "create_new"

    if "bulk" in lower or "batch" in lower:
        order_action = "create_bulk"

    if any(kw in lower for kw in ("multiple package", "multi package", "multi-package",
                                   "cleanup button", "clean up button", "cleanup", "clean-up",
                                   "failed package", "package fail", "remove package")):
        _add_nav("orders")
        _add_look(
            "Cleanup button appears on the failed package row in the Order Summary",
            "Cleanup button is visible after a package fails label generation",
            "Label Summary table shows a FAILED or ERROR status row",
        )
        _add_api("/label", "/rates")
        if order_action == "none":
            order_action = "create_new_multi_package"

    if "cancel label" in lower or "return label" in lower or "download document" in lower:
        order_action = "existing_fulfilled"

    return {
        "nav_clicks": nav_clicks,
        "api_to_watch": api_to_watch,
        "look_for": look_for,
        "precondition_steps": precondition_steps,
        "order_action": order_action,
    }


# ── URL map builder ────────────────────────────────────────────────────────────

# MCSL navigation map — all in-app destinations use hamburger menu search.
# "shopifyorders" and "shopifyproducts" navigate outside the app to Shopify admin (post-fulfillment checks only).
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
    "requestlog":     {"type": "hamburger", "search": "Request Log"},
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
            page.goto(
                f"https://admin.shopify.com/store/{_store_slug(store)}/{nav['path']}",
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

Always use the ORDERS tab inside the app for label generation.

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

### Multi-Package Order Flow (order has 2+ line items / packages)
An order with multiple distinct products is automatically split into multiple
packages by MCSL. The flow after creating the order is:
1. Click "ORDERS" tab → All Orders grid
2. Add filter: Order Id → type order ID → press Escape
3. Click the order link → Order Summary page opens
4. Click "Prepare Shipment" if visible (retry up to 3×)
5. Click "Generate Label" → wait for label generation to complete
   - Each package row in the Label Summary table shows its own status cell
   - A package that fails label generation shows status = "FAILED" or "ERROR"
6. After generation: check the Label Summary table for a FAILED package row
7. On a FAILED package row: look for a "Cleanup" button (or "Clean up" / "Remove")
   - Locator to try: appFrame.getByRole('button', { name: /cleanup/i })
   - Also check: appFrame.locator('button[title*="Clean"], button[title*="cleanup"]')
   - Also check: any button near the FAILED status cell in the Label Summary table
8. Verify the Cleanup button is visible and clickable — that is the assertion for
   "cleanup button missing in new UI" scenarios.

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
NOTE: This is a dialog — read text content directly from .dialogHalfDivParent. Do NOT use download_zip here.

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
    selector: str = ""
    locator_source: str = ""
    page_url: str = ""
    destination: str = ""
    success: bool = True
    screenshot_b64: str = ""
    network_calls: list[str] = field(default_factory=list)
    captured_artifact: str = ""
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
    expectation_summary: str = ""
    expectation_comparison: str = ""
    setup_context_summary: str = ""


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
                    "expectation_summary": s.expectation_summary,
                    "expectation_comparison": s.expectation_comparison,
                    "setup_context_summary": s.setup_context_summary,
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
                if step.selector:
                    source = f" ({step.locator_source})" if step.locator_source else ""
                    page_hint = f" @ {step.page_url}" if step.page_url else ""
                    lines.append(f"   [locator{source}] {step.selector}{page_hint}")
                if step.network_calls:
                    for nc in step.network_calls[:3]:
                        lines.append(f"   [api] {nc}")
            if sv.verdict:
                lines.append(f"   Result: {sv.verdict}")
            lines.append("")
        return "\n".join(lines)


@dataclass(frozen=True)
class ParsedTestCase:
    index: int
    tc_id: str
    title: str
    tc_type: str
    priority: str
    preconditions: str
    body: str

    @property
    def priority_rank(self) -> int:
        return {"high": 0, "medium": 1, "low": 2}.get(self.priority.lower(), 3)

    @property
    def scenario_text(self) -> str:
        parts = [self.title]
        if self.preconditions:
            parts.append(f"Preconditions: {self.preconditions}")
        if self.body:
            parts.append(self.body)
        return "\n".join(parts)


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


def parse_test_cases_markdown(test_cases_markdown: str) -> list[ParsedTestCase]:
    """Parse markdown test cases into structured entries."""
    if not test_cases_markdown.strip():
        return []

    blocks = re.split(r"(?=^#{2,3}\s+TC-\d+)", test_cases_markdown, flags=re.MULTILINE)
    parsed: list[ParsedTestCase] = []
    for idx, block in enumerate(blocks, start=1):
        block = block.strip()
        if not re.match(r"^#{2,3}\s+TC-\d+", block):
            continue
        title_match = re.match(r"^#{2,3}\s+(TC-\d+)[:\s]+(.+)", block)
        tc_id = title_match.group(1).strip() if title_match else f"TC-{idx}"
        title = title_match.group(2).strip() if title_match else block.splitlines()[0].strip("# ").strip()
        type_match = re.search(r"\*\*Type:\*\*\s*(.+)", block)
        priority_match = re.search(r"\*\*Priority:\*\*\s*(.+)", block)
        preconditions_match = re.search(r"\*\*Preconditions:\*\*\s*(.+)", block)
        parsed.append(
            ParsedTestCase(
                index=len(parsed) + 1,
                tc_id=tc_id,
                title=title,
                tc_type=(type_match.group(1).strip() if type_match else "Positive"),
                priority=(priority_match.group(1).strip() if priority_match else "Medium"),
                preconditions=(preconditions_match.group(1).strip() if preconditions_match else ""),
                body=block,
            )
        )
    return parsed


def rank_test_cases_for_execution(test_cases_markdown: str) -> list[ParsedTestCase]:
    """Rank reviewed test cases for execution, prioritizing high-value cases first."""
    parsed = parse_test_cases_markdown(test_cases_markdown)
    return sorted(
        parsed,
        key=lambda tc: (
            tc.priority_rank,
            0 if "positive" in tc.tc_type.lower() else 1 if "edge" in tc.tc_type.lower() else 2,
            tc.index,
        ),
    )


def _prune_context_block(text: str, *, max_chars: int, max_sections: int = 6) -> str:
    clean = (text or "").strip()
    if not clean:
        return ""
    parts = [part.strip() for part in re.split(r"\n\s*---\s*\n", clean) if part.strip()]
    pruned: list[str] = []
    total = 0
    for part in parts[:max_sections]:
        clipped = part[: max_chars // max(1, min(max_sections, len(parts)))]
        if total + len(clipped) > max_chars:
            remaining = max_chars - total
            if remaining <= 0:
                break
            clipped = clipped[:remaining]
        pruned.append(clipped)
        total += len(clipped)
        if total >= max_chars:
            break
    combined = "\n\n---\n\n".join(pruned)
    return combined[:max_chars]


def _code_context(scenario: str, card_name: str) -> str:
    """Query automation POM + backend code RAG for structured context."""
    parts: list[str] = []
    query = f"{card_name} {scenario}"

    try:
        from rag.code_indexer import search_code

        # Automation POM — always include label generation workflow
        label_docs = search_code(
            "generate label app order grid navigate MCSL",
            k=2, source_type="automation",
        )
        scenario_pom_docs = search_code(query, k=3, source_type="automation")
        pom_docs = (label_docs or []) + (scenario_pom_docs or [])

        be_docs = search_code(query, k=2, source_type="storepepsaas_server") or []
        fe_docs: list = []
        try:
            fe_docs = search_code(query, k=2, source_type="storepepsaas_client") or []
        except Exception:
            pass

        if pom_docs:
            snippets = "\n---\n".join(
                f"[{d.metadata.get('file_path', '').split('/')[-1]}]\n{d.page_content[:420]}"
                for d in pom_docs[:4]
            )
            parts.append(f"=== AUTOMATION WORKFLOW (from POM) ===\n{snippets}")

        if be_docs:
            snippets = "\n---\n".join(d.page_content[:260] for d in be_docs[:2])
            parts.append(f"=== BACKEND MODELS ===\n{snippets}")

        if fe_docs:
            snippets = "\n---\n".join(d.page_content[:220] for d in fe_docs[:2])
            parts.append(f"=== FRONTEND CODE ===\n{snippets}")

    except Exception as e:
        logger.debug("Code RAG error in _code_context: %s", e)

    try:
        locator_context = build_locator_context(f"{card_name} {scenario}")
        if locator_context:
            parts.append(f"=== LOCATOR HINTS ===\n{locator_context[:1800]}")
    except Exception as e:
        logger.debug("Locator knowledge error in _code_context: %s", e)

    return _prune_context_block("\n\n".join(parts), max_chars=4200, max_sections=5)


def _ask_domain_expert(scenario: str, card_name: str, claude: "ChatAnthropic") -> str:
    """Stage 2: Query Domain Expert RAG and ask Claude for expected behaviour.

    Queries mcsl_knowledge (KB, wiki, sheets) and mcsl_code_knowledge (source code).
    Returns a plain-text insight string (≤200 words) for injection into planning prompt.
    """
    query = f"{card_name} {scenario}"
    domain_sections: list[str] = []
    code_parts: list[str] = []

    _DOMAIN_SOURCES = [
        ("kb_articles",  query, "MCSL Knowledge Base",              2),
        ("wiki",         query, "Internal Wiki (Product & Engineering)", 2),
        ("sheets",       query, "Test Cases & Acceptance Criteria",  2),
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
                        return f"{prefix}{d.page_content[:260]}"
                    chunks = "\n\n".join(_fmt(d) for d in docs)
                    domain_sections.append(f"[{label}]\n{chunks}")
            except Exception as e:
                logger.debug("Domain RAG sub-query failed (source_type=%s): %s", src_type, e)
    except ImportError as e:
        logger.debug("search_filtered not available — falling back to unfiltered: %s", e)
        try:
            from rag.vectorstore import search as rag_search
            docs = rag_search(query, k=4)
            if docs:
                domain_sections.append("\n\n".join(
                    f"[{d.metadata.get('source_type', 'doc')}] {d.page_content[:260]}"
                    for d in docs[:4]
                ))
        except Exception as e2:
            logger.debug("Fallback domain RAG failed: %s", e2)

    try:
        from rag.code_indexer import search_code
        auto_docs = search_code(query, k=3, source_type="automation")
        if auto_docs:
            code_parts.append("\n---\n".join(
                f"[{d.metadata.get('file_path', '').split('/')[-1]}]\n{d.page_content[:320]}"
                for d in auto_docs[:3]
            ))
        be_docs = search_code(query, k=2, source_type="storepepsaas_server")
        if be_docs:
            code_parts.append("\n---\n".join(
                f"[{d.metadata.get('file_path', '').split('/')[-1]}]\n{d.page_content[:240]}"
                for d in be_docs[:2]
            ))
    except Exception as e:
        logger.debug("Code RAG error in expert: %s", e)

    domain_context = _prune_context_block("\n\n---\n\n".join(domain_sections), max_chars=2200, max_sections=4) or "(no domain knowledge indexed)"
    code_context   = _prune_context_block("\n\n".join(code_parts), max_chars=1600, max_sections=3) or "(no code indexed)"
    carrier_name, _ = _detect_carrier(scenario)
    _setup = _infer_setup_requirements(scenario, carrier_name)
    _pre_lines = _extract_explicit_preconditions(scenario) + (_setup.get("precondition_steps") or [])
    _preconditions_section = ""
    if _pre_lines:
        _preconditions_section = "KNOWN PRE-REQUIREMENTS:\n" + "\n".join(
            f"- {_line}" for _line in _pre_lines[:12]
        )

    prompt = _DOMAIN_EXPERT_PROMPT.format(
        scenario=scenario,
        card_name=card_name,
        domain_context=domain_context[:2200],
        code_context=code_context[:1600],
        preconditions_section=_preconditions_section,
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


def _domain_context_for_expectations(query: str) -> str:
    sections: list[str] = []
    try:
        from rag.vectorstore import search_filtered
        for src_type in ("kb_articles", "wiki", "sheets"):
            try:
                docs = search_filtered(query, k=2, source_type=src_type) or []
                if docs:
                    sections.append("\n\n".join(d.page_content[:220] for d in docs[:2]))
            except Exception:
                continue
    except Exception:
        pass
    return _prune_context_block("\n\n---\n\n".join(sections), max_chars=1200, max_sections=3)


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

    # Deterministic setup requirements before Claude planning
    scenario_lower = scenario.lower()
    setup = _infer_setup_requirements(scenario, carrier_name, app_base=app_url.rstrip("/"))
    is_carrier_config = any(kw in scenario_lower for kw in _CARRIER_CONFIG_KEYWORDS)
    if is_carrier_config and carrier_name:
        config_steps = _get_carrier_config_steps(carrier_name, action="add")
        carrier_context_lines += [
            "",
            f"CARRIER ACCOUNT CONFIGURATION STEPS for {carrier_name}:",
        ] + [f"  {i + 1}. {step}" for i, step in enumerate(config_steps)]

    carrier_context = "\n".join(carrier_context_lines)
    preconditions_block = ""
    if setup.get("precondition_steps"):
        formatted = "\n".join(
            f"  {i + 1}. {step}" for i, step in enumerate(setup["precondition_steps"])
        )
        preconditions_block = (
            f"\nPRE-REQUISITE STEPS (must be completed before verification):\n"
            f"{formatted}\n"
        )
        carrier_context += "\n\nPRE-REQUISITE STEPS injected — execute them before deciding the final verdict."

    setup_summary_lines: list[str] = []
    if setup.get("nav_clicks"):
        setup_summary_lines.append(f"SETUP NAVIGATION HINTS: {', '.join(setup['nav_clicks'])}")
    if setup.get("api_to_watch"):
        setup_summary_lines.append(f"SETUP API HINTS: {', '.join(setup['api_to_watch'])}")
    if setup.get("look_for"):
        setup_summary_lines.append(f"SETUP UI HINTS: {', '.join(setup['look_for'])}")
    setup_summary = "\n".join(setup_summary_lines)

    prompt = _PLAN_PROMPT.format(
        scenario=scenario,
        app_url=app_url,
        carrier_name=carrier_name or "(none)",
        carrier_code=carrier_code or "—",
        mcsl_workflow_guide=_MCSL_WORKFLOW_GUIDE + ("\n\n" + carrier_context if carrier_context else "") + ("\n\n" + setup_summary if setup_summary else ""),
        expert_insight=expert_insight or "(not available)",
        code_context=code_ctx[:2600],
    )
    if preconditions_block:
        prompt = prompt + preconditions_block
    resp = claude.invoke([HumanMessage(content=prompt)])
    plan = _parse_json(resp.content) or {}
    # Ensure carrier/setup defaults are always present even if Claude is vague
    if "carrier" not in plan:
        plan["carrier"] = carrier_name
    if not isinstance(plan.get("nav_clicks"), list):
        plan["nav_clicks"] = []
    for _nav in setup.get("nav_clicks", []):
        if _nav not in plan["nav_clicks"]:
            plan["nav_clicks"].append(_nav)
    if not isinstance(plan.get("api_to_watch"), list):
        plan["api_to_watch"] = []
    for _api in setup.get("api_to_watch", []):
        if _api not in plan["api_to_watch"]:
            plan["api_to_watch"].append(_api)
    if not isinstance(plan.get("look_for"), list):
        plan["look_for"] = []
    for _look in setup.get("look_for", []):
        if _look not in plan["look_for"]:
            plan["look_for"].append(_look)
    if not plan.get("order_action") or plan.get("order_action") == "none":
        _default_order_action = setup.get("order_action", "none")
        if _default_order_action and _default_order_action != "none":
            plan["order_action"] = _default_order_action
    if setup.get("precondition_steps"):
        plan["precondition_steps"] = setup["precondition_steps"]
    if setup_summary_lines and plan.get("plan"):
        plan["plan"] = f"{plan['plan']} Setup focus: {'; '.join(setup_summary_lines)}"
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
    """Return a FrameLocator for the MCSL app iframe.

    Mirrors the mcsl-test-automation pattern:
        page.frameLocator('iframe[name="app-iframe"]')

    Uses FrameLocator (lazy resolution) so callers don't have to wait for the
    iframe to appear before calling this — the frame is resolved when a locator
    is actually used.  Falls back to eager Frame lookup and then to page if the
    browser API is not available.
    """
    try:
        return page.frame_locator('iframe[name="app-iframe"]')
    except Exception:
        pass
    # Fallback: eager Frame object from page.frames
    try:
        for frame in page.frames:
            if "app-iframe" in (frame.name or ""):
                return frame
            url = frame.url or ""
            if "pluginhive" in url or ("apps" in url and "shopify" in url):
                return frame
    except Exception:
        pass
    return page  # last resort


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


def _artifact_to_text(content: Any) -> str:
    if isinstance(content, dict):
        return json.dumps(content, ensure_ascii=False)[:4000]
    return str(content)[:4000]


def _extract_setup_values_from_steps(steps: list[VerificationStep]) -> list[str]:
    extracted: list[str] = []
    pattern = re.compile(r'Preflight set "([^"]+)" to "([^"]+)"', re.I)
    for step in steps:
        if not getattr(step, "success", False):
            continue
        match = pattern.search(getattr(step, "description", "") or "")
        if not match:
            continue
        label = match.group(1).strip()
        value = match.group(2).strip()
        if label and value:
            extracted.append(f"{label}: {value}")
    return _dedupe_strings(extracted)


def _extract_setup_item_values_from_steps(steps: list[VerificationStep]) -> list[str]:
    extracted: list[str] = []
    field_pattern = re.compile(r'Preflight set "([^"]+)" to "([^"]+)"', re.I)
    identity_pattern = re.compile(r"Preflight captured product identity:\s*(.+)$", re.I)
    current_scope = "global"
    scope_counters: dict[str, int] = {
        "product_record": 0,
        "general_settings_record": 0,
        "automation_rule_record": 0,
        "carrier_record": 0,
        "order_record": 0,
    }

    for step in steps:
        if not getattr(step, "success", False):
            continue
        description = getattr(step, "description", "") or ""
        target = (getattr(step, "target", "") or "").lower()

        if "editable product settings" in description.lower() or "product settings" in target:
            scope_counters["product_record"] += 1
            current_scope = f"product_record_{scope_counters['product_record']}"
        elif "editable general-settings" in description.lower() or "general settings" in target:
            scope_counters["general_settings_record"] += 1
            current_scope = f"general_settings_record_{scope_counters['general_settings_record']}"
        elif "automation-rule" in description.lower() or "automation rule" in target:
            scope_counters["automation_rule_record"] += 1
            current_scope = f"automation_rule_record_{scope_counters['automation_rule_record']}"
        elif "add carrier" in description.lower() or "carrier" == target:
            scope_counters["carrier_record"] += 1
            current_scope = f"carrier_record_{scope_counters['carrier_record']}"
        elif "opened order summary" in description.lower() or "order summary" in target:
            scope_counters["order_record"] += 1
            current_scope = f"order_record_{scope_counters['order_record']}"

        identity_match = identity_pattern.search(description)
        if identity_match:
            raw_identity = identity_match.group(1).strip()
            safe_identity = re.sub(r"[^a-z0-9]+", "_", raw_identity.lower()).strip("_")
            if safe_identity:
                current_scope = f"product_{safe_identity[:60]}"
                extracted.append(f"{current_scope}.item_identity: {raw_identity}")
            continue

        match = field_pattern.search(description)
        if not match:
            continue
        label = match.group(1).strip()
        value = match.group(2).strip()
        if label and value:
            extracted.append(f"{current_scope}.{label}: {value}")
    return _dedupe_strings(extracted)


def _build_setup_context_summary(steps: list[VerificationStep]) -> str:
    setup_values = _extract_setup_values_from_steps(steps)
    setup_item_values = _extract_setup_item_values_from_steps(steps)
    order_ids: list[str] = []
    destinations: list[str] = []
    surfaces: list[str] = []

    order_patterns = (
        re.compile(r"order\s+([A-Za-z0-9\-]+)", re.I),
        re.compile(r'Order Id filter with\s+([A-Za-z0-9\-]+)', re.I),
    )
    for step in steps:
        description = getattr(step, "description", "") or ""
        destination = getattr(step, "destination", "") or ""
        target = getattr(step, "target", "") or ""
        if destination:
            destinations.append(destination)
        if target and any(token in target.lower() for token in ("product settings", "general settings", "automation rule", "add carrier", "order summary")):
            surfaces.append(target)
        for pattern in order_patterns:
            match = pattern.search(description)
            if match:
                order_ids.append(match.group(1).strip())

    lines = ["=== SETUP CONTEXT ==="]
    if order_ids:
        lines.append("Orders touched:")
        lines.extend(f"- {item}" for item in _dedupe_strings(order_ids)[:6])
    if surfaces:
        lines.append("Setup surfaces touched:")
        lines.extend(f"- {item}" for item in _dedupe_strings(surfaces)[:8])
    if destinations:
        lines.append("Navigation destinations:")
        lines.extend(f"- {item}" for item in _dedupe_strings(destinations)[:8])
    if setup_values:
        lines.append("Entered setup values:")
        lines.extend(f"- {item}" for item in setup_values[:12])
    if setup_item_values:
        lines.append("Entered setup values by record:")
        lines.extend(f"- {item}" for item in setup_item_values[:16])
    return "\n".join(lines)


def _capture_log_dialog_text(page: Any) -> str:
    try:
        frame = _get_app_frame(page)
        candidates: list[str] = []

        for locator in [
            frame.locator('.dialogHalfDivParent').first,
            frame.get_by_text('Request:{', exact=False).first,
            frame.get_by_text('Request: {', exact=False).first,
            frame.get_by_text('ShipmentRequest', exact=False).first,
            frame.get_by_text('PickupCreationRequest', exact=False).first,
            frame.locator('td[title="Click to view Summary"]').first,
        ]:
            try:
                if locator.count() == 0:
                    continue
                text = (locator.text_content(timeout=2_000) or "").strip()
                if text and text not in candidates:
                    candidates.append(text[:6000])
            except Exception:
                continue

        return "\n\n---\n\n".join(candidates[:4])
    except Exception:
        return ""


def _record_macro_step(
    result: ScenarioResult,
    *,
    action: str,
    description: str,
    target: str = "",
    selector: str = "",
    locator_source: str = "macro",
    success: bool = True,
    page: Any | None = None,
) -> None:
    step = StepResult(
        step_num=len(result.steps) + 1,
        action=action,
        description=description,
        target=target,
        selector=selector,
        locator_source=locator_source,
        success=success,
    )
    if page is not None:
        try:
            step.page_url = page.url or ""
        except Exception:
            step.page_url = ""
    result.steps.append(step)


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        clean = (value or "").strip()
        if clean and clean not in seen:
            seen.add(clean)
            deduped.append(clean)
    return deduped


def _automation_hint_selectors(
    query: str,
    *,
    action: str,
    frame: Any,
    value: str = "",
    limit: int = 8,
) -> list[tuple[str, str, Callable[[], Any]]]:
    selectors: list[tuple[str, str, Callable[[], Any]]] = []
    try:
        hints = fetch_code_locator_hints(query, source_type="automation", k=4, limit=limit) or []
    except Exception:
        hints = []

    for hint in hints:
        raw = hint.split("] ", 1)[-1].strip()
        if raw.startswith("getByLabel("):
            match = re.search(r'getByLabel\("([^"]+)"', raw)
            if match:
                label = match.group(1)
                if action == "fill":
                    selectors.append(("automation_label", raw, lambda label=label: frame.get_by_label(label, exact=False).first.fill(value)))
                else:
                    selectors.append(("automation_label", raw, lambda label=label: frame.get_by_label(label, exact=False).first.click()))
        elif raw.startswith("getByPlaceholder("):
            match = re.search(r'getByPlaceholder\("([^"]+)"', raw)
            if match:
                placeholder = match.group(1)
                if action == "fill":
                    selectors.append(("automation_placeholder", raw, lambda placeholder=placeholder: frame.get_by_placeholder(placeholder).first.fill(value)))
                else:
                    selectors.append(("automation_placeholder", raw, lambda placeholder=placeholder: frame.get_by_placeholder(placeholder).first.click()))
        elif raw.startswith("getByText("):
            match = re.search(r'getByText\("([^"]+)"', raw)
            if match:
                text_value = match.group(1)
                selectors.append(("automation_text", raw, lambda text_value=text_value: frame.get_by_text(text_value, exact=False).first.click()))
        elif raw.startswith("getByRole("):
            role_match = re.search(r'getByRole\("([^"]+)"', raw)
            name_match = re.search(r'name:\s*"([^"]+)"', raw)
            if role_match and name_match:
                role = role_match.group(1)
                name = name_match.group(1)
                if action == "fill" and role in {"textbox", "combobox"}:
                    selectors.append(("automation_role", raw, lambda role=role, name=name: frame.get_by_role(role, name=name, exact=False).first.fill(value)))
                else:
                    selectors.append(("automation_role", raw, lambda role=role, name=name: frame.get_by_role(role, name=name, exact=False).first.click()))
        elif raw.startswith("locator("):
            match = re.search(r'locator\("([^"]+)"', raw)
            if match:
                css = match.group(1)
                if action == "fill":
                    selectors.append(("automation_css", raw, lambda css=css: frame.locator(css).first.fill(value)))
                else:
                    selectors.append(("automation_css", raw, lambda css=css: frame.locator(css).first.click()))
    return selectors


def _macro_click(
    page: Any,
    *,
    name: str,
    selectors: list[tuple[str, str, Callable[[], Any]]],
) -> tuple[bool, str, str]:
    for source, resolved, fn in selectors:
        try:
            fn()
            page.wait_for_timeout(400)
            return True, resolved, source
        except Exception:
            continue
    logger.debug("macro_click failed for %r", name)
    return False, "", ""


def _macro_fill(
    page: Any,
    *,
    value: str,
    selectors: list[tuple[str, str, Callable[[], Any]]],
) -> tuple[bool, str, str]:
    for source, resolved, fn in selectors:
        try:
            fn()
            page.wait_for_timeout(250)
            return True, resolved, source
        except Exception:
            continue
    logger.debug("macro_fill failed for %r", value)
    return False, "", ""


def _preflight_open_order_summary(page: Any, result: ScenarioResult, order_id: str) -> bool:
    _link_val = order_id if order_id.startswith("#") else f"#{order_id}"

    page.wait_for_timeout(1000)

    # Build a list of (strategy_name, click_fn) to try in order.
    # Mirrors automation clickOrderId:
    #   appFrame.getByRole("link", { name: orderID }).first().click()
    # where appFrame = page.frameLocator('iframe[name="app-iframe"]')
    _click_strategies: list[tuple[str, Any]] = []

    # 1. frame_locator approach (lazy FrameLocator — matches TypeScript automation)
    try:
        _fl = page.frame_locator('iframe[name="app-iframe"]')
        _lv = _link_val  # capture for lambda
        _click_strategies.append(("frame_locator+getByRole",   lambda lv=_lv, fl=_fl: fl.get_by_role("link", name=lv).first.click(timeout=8000)))
        _click_strategies.append(("frame_locator+has-text",    lambda lv=_lv, fl=_fl: fl.locator(f'a:has-text("{lv}")').first.click(timeout=5000)))
        _click_strategies.append(("frame_locator+getByText",   lambda lv=_lv, fl=_fl: fl.get_by_text(lv).first.click(timeout=5000)))
    except Exception:
        pass

    # 2. page.frame() approach (eager Frame object — direct frame reference)
    try:
        _f = page.frame(name="app-iframe")
        if _f:
            _lv = _link_val
            _click_strategies.append(("frame_obj+getByRole",   lambda lv=_lv, f=_f: f.get_by_role("link", name=lv).first.click(timeout=8000)))
            _click_strategies.append(("frame_obj+has-text",    lambda lv=_lv, f=_f: f.locator(f'a:has-text("{lv}")').first.click(timeout=5000)))
    except Exception:
        pass

    # Try each strategy; return True on first success
    for _strat_name, _click_fn in _click_strategies:
        try:
            _click_fn()
            page.wait_for_timeout(1500)
            logger.info("Preflight clicked order %s via strategy: %s", _link_val, _strat_name)
            _record_macro_step(
                result, action="click",
                description=f"Preflight clicked order {_link_val} ({_strat_name})",
                target=_link_val, selector=_strat_name,
                locator_source=_strat_name, success=True, page=page,
            )
            return True
        except Exception as _e:
            logger.debug("Preflight order click strategy %s failed: %s", _strat_name, _e)
            continue

    # ── Slow path: use Add filter → Order Id filter ──
    # Button label is "Add filter +" in the UI — use has-text to avoid exact mismatch.
    ok, selector, source = _macro_click(
        page,
        name="Add filter",
        selectors=[
            ("css_has_text",     'button:has-text("Add filter")',                       lambda: frame.locator('button:has-text("Add filter")').first.click()),
            ("role_button_partial", 'getByRole("button") with text Add filter',          lambda: frame.get_by_role("button", name=re.compile(r"Add filter")).first.click()),
            ("text_contains",    'text=Add filter',                                      lambda: frame.locator("text=Add filter").first.click()),
        ],
    )
    _record_macro_step(
        result,
        action="click",
        description="Preflight clicked Add filter in ORDERS",
        target="Add filter",
        selector=selector,
        locator_source=source or "macro_click",
        success=ok,
        page=page,
    )
    if not ok:
        return False

    ok, selector, source = _macro_click(
        page,
        name="Order Id",
        selectors=[
            ("role_menuitem_exact", 'getByRole("menuitem", { name: "Order Id" })', lambda: frame.get_by_role("menuitem", name="Order Id", exact=True).click()),
            ("text_exact", 'getByText("Order Id", { exact: true })', lambda: frame.get_by_text("Order Id", exact=True).click()),
        ],
    )
    _record_macro_step(
        result,
        action="click",
        description="Preflight selected Order Id filter",
        target="Order Id",
        selector=selector,
        locator_source=source or "macro_click",
        success=ok,
        page=page,
    )
    if not ok:
        return False

    # MCSL Order Id filter expects the numeric part (without #); the link in the
    # grid shows the full name including # so we keep both variants.
    _filter_val = order_id.lstrip("#") if order_id.startswith("#") else order_id
    _link_val   = order_id if order_id.startswith("#") else f"#{order_id}"

    ok, selector, source = _macro_fill(
        page,
        value=_filter_val,
        selectors=[
            ("role_textbox_first", 'getByRole("textbox").last()', lambda: frame.get_by_role("textbox").last.fill(_filter_val)),
            ("placeholder", 'getByPlaceholder("Value")', lambda: frame.get_by_placeholder("Value").fill(_filter_val)),
            ("css_locator", 'input[type="text"]', lambda: frame.locator('input[type="text"]').last.fill(_filter_val)),
        ],
    )
    _record_macro_step(
        result,
        action="fill",
        description=f"Preflight filled Order Id filter with {_filter_val}",
        target="Order Id filter",
        selector=selector,
        locator_source=source or "macro_fill",
        success=ok,
        page=page,
    )
    if not ok:
        return False

    try:
        frame.locator('input[type="text"]').last.press("Enter")
    except Exception:
        pass
    try:
        page.wait_for_timeout(1500)
    except Exception:
        pass

    ok, selector, source = _macro_click(
        page,
        name=_link_val,
        selectors=[
            ("role_link_exact",  f'getByRole("link", {{ name: "{_link_val}" }})',  lambda: frame.get_by_role("link", name=_link_val, exact=True).first.click()),
            ("text_exact",       f'getByText("{_link_val}", {{ exact: true }})',    lambda: frame.get_by_text(_link_val, exact=True).first.click()),
            ("role_link_no_hash",f'getByRole("link", {{ name: "{_filter_val}" }})',lambda: frame.get_by_role("link", name=_filter_val, exact=True).first.click()),
            ("css_first_row",    '#all-order-table table tbody tr:first-child a',   lambda: frame.locator('#all-order-table table tbody tr:first-child a').first.click()),
        ],
    )
    _record_macro_step(
        result,
        action="click",
        description=f"Preflight opened order summary for order {order_id}",
        target=order_id,
        selector=selector,
        locator_source=source or "macro_click",
        success=ok,
        page=page,
    )
    return ok


def _preflight_open_view_log(page: Any, result: ScenarioResult) -> bool:
    frame = _get_app_frame(page)

    ok, selector, source = _macro_click(
        page,
        name="View all Rate Summary",
        selectors=[
            ("title_exact", 'getByTitle("View all Rate Summary")', lambda: frame.get_by_title("View all Rate Summary").click()),
            ("text_fuzzy", 'getByText("View all Rate Summary")', lambda: frame.get_by_text("View all Rate Summary").click()),
        ],
    )
    _record_macro_step(
        result,
        action="click",
        description="Preflight expanded the rate summary section",
        target="View all Rate Summary",
        selector=selector,
        locator_source=source or "macro_click",
        success=ok,
        page=page,
    )

    ok_menu, selector_menu, source_menu = _macro_click(
        page,
        name="rate summary menu",
        selectors=[
            ("css_locator", '.rate-summary-table tbody tr td:last-child button[aria-haspopup="true"]', lambda: frame.locator('.rate-summary-table tbody tr td:last-child button[aria-haspopup="true"]').first.click()),
        ],
    )
    _record_macro_step(
        result,
        action="click",
        description="Preflight opened the rate-summary actions menu",
        target="rate summary actions",
        selector=selector_menu,
        locator_source=source_menu or "macro_click",
        success=ok_menu,
        page=page,
    )
    if not ok_menu:
        return False

    ok_log, selector_log, source_log = _macro_click(
        page,
        name="View Log",
        selectors=[
            ("role_menuitem_exact", 'getByRole("menuitem", { name: "View Log" })', lambda: frame.get_by_role("menuitem", name="View Log", exact=True).first.click()),
            ("text_exact", 'getByText("View Log", { exact: true })', lambda: frame.get_by_text("View Log", exact=True).first.click()),
            ("css_locator", 'div[role="presentation"]>div:nth-child(2)>ul>li:nth-child(1)', lambda: frame.locator('div[role="presentation"]>div:nth-child(2)>ul>li:nth-child(1)').first.click()),
        ],
    )
    _record_macro_step(
        result,
        action="click",
        description="Preflight opened the View Log dialog",
        target="View Log",
        selector=selector_log,
        locator_source=source_log or "macro_click",
        success=ok_log,
        page=page,
    )
    if ok_log:
        _log_text = _capture_log_dialog_text(page)
        if _log_text and result.steps:
            result.steps[-1].captured_artifact = _log_text
    return ok_log


def _preflight_open_label_view_log(page: Any, result: ScenarioResult) -> bool:
    frame = _get_app_frame(page)

    ok_menu, selector_menu, source_menu = _macro_click(
        page,
        name="label summary menu",
        selectors=[
            ("automation_css", 'orderSummaryPage.click3DotsOnLabelSummary', lambda: frame.locator('div[class="order-summary-root"]>div>div:nth-child(2)>div>div>div:nth-child(3)>div>div>div:nth-child(2)>div>table>tbody>tr>td:nth-child(8)').first.click()),
            ("label_summary_scoped", 'label summary scoped menu', lambda: frame.get_by_text("Label Summary", exact=True).locator("..").locator("..").locator('tbody tr td:nth-child(8), button[aria-haspopup="true"]').first.click()),
        ],
    )
    _record_macro_step(
        result,
        action="click",
        description="Preflight opened the label-summary actions menu",
        target="label summary actions",
        selector=selector_menu,
        locator_source=source_menu or "macro_click",
        success=ok_menu,
        page=page,
    )
    if not ok_menu:
        return False

    ok_log, selector_log, source_log = _macro_click(
        page,
        name="View Log",
        selectors=[
            ("role_menuitem_exact", 'getByRole("menuitem", { name: "View Log" })', lambda: frame.get_by_role("menuitem", name="View Log", exact=True).first.click()),
            ("text_exact", 'getByText("View Log", { exact: true })', lambda: frame.get_by_text("View Log", exact=True).first.click()),
            ("css_locator", 'div[role="presentation"]>div:nth-child(2)>ul>li:nth-child(1)', lambda: frame.locator('div[role="presentation"]>div:nth-child(2)>ul>li:nth-child(1)').first.click()),
        ],
    )
    _record_macro_step(
        result,
        action="click",
        description="Preflight opened the label-request View Log dialog",
        target="Label View Log",
        selector=selector_log,
        locator_source=source_log or "macro_click",
        success=ok_log,
        page=page,
    )
    if ok_log:
        _log_text = _capture_log_dialog_text(page)
        if _log_text and result.steps:
            result.steps[-1].captured_artifact = _log_text
    return ok_log


def _preflight_open_upload_document_log(page: Any, result: ScenarioResult) -> bool:
    frame = _get_app_frame(page)
    ok_menu, selector_menu, source_menu = _macro_click(
        page,
        name="upload documents menu",
        selectors=[
            ("upload_summary_scoped", 'upload summary scoped menu', lambda: frame.locator('.summary-table-container').last.locator('tbody tr td:last-child button[aria-haspopup="true"]').first.click()),
        ],
    )
    _record_macro_step(
        result,
        action="click",
        description="Preflight opened the upload-documents actions menu",
        target="upload documents actions",
        selector=selector_menu,
        locator_source=source_menu or "macro_click",
        success=ok_menu,
        page=page,
    )
    if not ok_menu:
        return False

    ok_log, selector_log, source_log = _macro_click(
        page,
        name="View Log",
        selectors=[
            ("role_menuitem_exact", 'getByRole("menuitem", { name: "View Log" })', lambda: frame.get_by_role("menuitem", name="View Log", exact=True).first.click()),
            ("text_exact", 'getByText("View Log", { exact: true })', lambda: frame.get_by_text("View Log", exact=True).first.click()),
        ],
    )
    _record_macro_step(
        result,
        action="click",
        description="Preflight opened the upload-document View Log dialog",
        target="Upload Document View Log",
        selector=selector_log,
        locator_source=source_log or "macro_click",
        success=ok_log,
        page=page,
    )
    if ok_log:
        _log_text = _capture_log_dialog_text(page)
        if _log_text and result.steps:
            result.steps[-1].captured_artifact = _log_text
    return ok_log


def _preflight_open_request_log_summary(page: Any, result: ScenarioResult) -> bool:
    frame = _get_app_frame(page)
    ok_request_log, selector_btn, source_btn = _macro_click(
        page,
        name="Request Log",
        selectors=[
            ("role_button_exact", 'getByRole("button", { name: "Request Log" })', lambda: frame.get_by_role("button", name="Request Log", exact=True).first.click()),
            ("text_exact", 'getByText("Request Log", { exact: true })', lambda: frame.get_by_text("Request Log", exact=True).first.click()),
        ],
    )
    _record_macro_step(
        result,
        action="click",
        description="Preflight opened the automation Request Log table",
        target="Request Log",
        selector=selector_btn,
        locator_source=source_btn or "macro_click",
        success=ok_request_log,
        page=page,
    )
    if not ok_request_log:
        return False

    ok_summary, selector_summary, source_summary = _macro_click(
        page,
        name="request log summary",
        selectors=[
            ("css_locator", 'td[title="Click to view Summary"] a', lambda: frame.locator('td[title="Click to view Summary"]').get_by_role('link').first.click()),
            ("css_locator", 'td[title="Click to view Summary"]', lambda: frame.locator('td[title="Click to view Summary"]').first.click()),
        ],
    )
    _record_macro_step(
        result,
        action="click",
        description="Preflight opened the automation request summary dialog",
        target="request log summary",
        selector=selector_summary,
        locator_source=source_summary or "macro_click",
        success=ok_summary,
        page=page,
    )
    if ok_summary:
        _log_text = _capture_log_dialog_text(page)
        if _log_text and result.steps:
            result.steps[-1].captured_artifact = _log_text
    return ok_summary


def _preflight_prepare_and_generate_label(page: Any, result: ScenarioResult) -> bool:
    frame = _get_app_frame(page)
    success = False

    for _ in range(3):
        ok_prepare, selector_prepare, source_prepare = _macro_click(
            page,
            name="Prepare Shipment",
            selectors=[
                ("role_button_exact", 'getByRole("button", { name: "Prepare Shipment" })', lambda: frame.get_by_role("button", name="Prepare Shipment", exact=True).first.click()),
                ("text_exact", 'getByText("Prepare Shipment", { exact: true })', lambda: frame.get_by_text("Prepare Shipment", exact=True).first.click()),
            ],
        )
        if not ok_prepare:
            break
        _record_macro_step(
            result,
            action="click",
            description="Preflight clicked Prepare Shipment",
            target="Prepare Shipment",
            selector=selector_prepare,
            locator_source=source_prepare or "macro_click",
            success=ok_prepare,
            page=page,
        )
        success = True

    ok_label, selector_label, source_label = _macro_click(
        page,
        name="Generate Label",
        selectors=[
            ("role_button_exact", 'getByRole("button", { name: "Generate Label" })', lambda: frame.get_by_role("button", name="Generate Label", exact=True).first.click()),
            ("text_exact", 'getByText("Generate Label", { exact: true })', lambda: frame.get_by_text("Generate Label", exact=True).first.click()),
        ],
    )
    _record_macro_step(
        result,
        action="click",
        description="Preflight clicked Generate Label",
        target="Generate Label",
        selector=selector_label,
        locator_source=source_label or "macro_click",
        success=ok_label,
        page=page,
    )
    return success or ok_label


def _preflight_download_documents(page: Any, result: ScenarioResult) -> bool:
    action = {"action": "download_zip", "target": "Download Documents"}
    ok = _do_action(page, action, "")
    _record_macro_step(
        result,
        action="download_zip",
        description="Preflight downloaded documents ZIP",
        target="Download Documents",
        selector=action.get("_resolved_locator", "Download Documents"),
        locator_source=action.get("_locator_source", "macro_download"),
        success=ok,
        page=page,
    )
    return ok


def _preflight_open_print_documents(page: Any, result: ScenarioResult) -> bool:
    frame = _get_app_frame(page)
    ok, selector, source = _macro_click(
        page,
        name="Print Documents",
        selectors=[
            ("role_button_exact", 'getByRole("button", { name: "Print Documents" })', lambda: frame.get_by_role("button", name="Print Documents", exact=True).first.click()),
            ("text_exact", 'getByText("Print Documents", { exact: true })', lambda: frame.get_by_text("Print Documents", exact=True).first.click()),
        ],
    )
    _record_macro_step(
        result,
        action="click",
        description="Preflight opened Print Documents",
        target="Print Documents",
        selector=selector,
        locator_source=source or "macro_click",
        success=ok,
        page=page,
    )
    return ok


def _capture_product_identity(page: Any) -> str:
    try:
        frame = _get_app_frame(page)
        found: list[str] = []

        for label in ("Product Name", "Name", "Title", "SKU"):
            try:
                locator = frame.get_by_label(label, exact=True).first
                if locator.count() == 0:
                    continue
                value = (
                    locator.input_value(timeout=1_500)
                    or locator.get_attribute("value", timeout=1_500)
                    or locator.text_content(timeout=1_500)
                    or ""
                ).strip()
                if value:
                    found.append(f"{label}={value[:80]}")
            except Exception:
                continue

        if not found:
            for locator in [
                frame.locator("h1").first,
                frame.locator("h2").first,
                frame.locator('[data-testid*="product"]').first,
            ]:
                try:
                    if locator.count() == 0:
                        continue
                    text = (locator.text_content(timeout=1_500) or "").strip()
                    if text:
                        found.append(f"Heading={text[:80]}")
                        break
                except Exception:
                    continue

        return " | ".join(_dedupe_strings(found[:4]))
    except Exception:
        return ""


def _preflight_open_product_settings(page: Any, result: ScenarioResult) -> bool:
    frame = _get_app_frame(page)
    selectors = _automation_hint_selectors("mcsl products product settings edit row", action="click", frame=frame)
    selectors.extend([
        ("css_locator", '#all-product-table table tbody tr:first-child a', lambda: frame.locator('#all-product-table table tbody tr:first-child a').first.click()),
        ("css_locator", 'table tbody tr:first-child a', lambda: frame.locator('table tbody tr:first-child a').first.click()),
        ("role_link_first", 'getByRole("link").first()', lambda: frame.get_by_role("link").first.click()),
    ])
    ok, selector, source = _macro_click(
        page,
        name="first product settings",
        selectors=selectors,
    )
    _record_macro_step(
        result,
        action="click",
        description="Preflight opened the first editable product settings record",
        target="product settings",
        selector=selector,
        locator_source=source or "macro_click",
        success=ok,
        page=page,
    )
    if ok:
        product_identity = _capture_product_identity(page)
        if product_identity:
            _record_macro_step(
                result,
                action="observe",
                description=f"Preflight captured product identity: {product_identity}",
                target="product identity",
                selector="live product settings surface",
                locator_source="macro_identity",
                success=True,
                page=page,
            )
    return ok


def _preflight_open_add_carrier(page: Any, result: ScenarioResult) -> bool:
    frame = _get_app_frame(page)
    selectors = _automation_hint_selectors("mcsl carriers add carrier button", action="click", frame=frame)
    selectors.extend([
        ("role_button_exact", 'getByRole("button", { name: "Add Carrier" })', lambda: frame.get_by_role("button", name="Add Carrier", exact=True).first.click()),
        ("text_exact", 'getByText("Add Carrier", { exact: true })', lambda: frame.get_by_text("Add Carrier", exact=True).first.click()),
        ("text_fuzzy", 'getByText("Add Carrier")', lambda: frame.get_by_text("Add Carrier").first.click()),
    ])
    ok, selector, source = _macro_click(
        page,
        name="Add Carrier",
        selectors=selectors,
    )
    _record_macro_step(
        result,
        action="click",
        description="Preflight opened the Add Carrier flow",
        target="Add Carrier",
        selector=selector,
        locator_source=source or "macro_click",
        success=ok,
        page=page,
    )
    return ok


def _preflight_open_automation_rule(page: Any, result: ScenarioResult) -> bool:
    frame = _get_app_frame(page)
    selectors = _automation_hint_selectors("mcsl automation add rule create rule", action="click", frame=frame)
    selectors.extend([
        ("role_button_exact", 'getByRole("button", { name: "Add Rule" })', lambda: frame.get_by_role("button", name="Add Rule", exact=True).first.click()),
        ("role_button_exact", 'getByRole("button", { name: "Create Rule" })', lambda: frame.get_by_role("button", name="Create Rule", exact=True).first.click()),
        ("role_button_exact", 'getByRole("button", { name: "Add Automation" })', lambda: frame.get_by_role("button", name="Add Automation", exact=True).first.click()),
        ("css_locator", 'table tbody tr:first-child a', lambda: frame.locator('table tbody tr:first-child a').first.click()),
    ])
    ok, selector, source = _macro_click(
        page,
        name="automation rule entry",
        selectors=selectors,
    )
    _record_macro_step(
        result,
        action="click",
        description="Preflight opened an automation-rule creation or edit surface",
        target="automation rule",
        selector=selector,
        locator_source=source or "macro_click",
        success=ok,
        page=page,
    )
    return ok


def _preflight_open_general_settings(page: Any, result: ScenarioResult) -> bool:
    frame = _get_app_frame(page)
    selectors = _automation_hint_selectors("mcsl general settings packaging settings row", action="click", frame=frame)
    selectors.extend([
        ("css_locator", 'table tbody tr:first-child a', lambda: frame.locator('table tbody tr:first-child a').first.click()),
        ("role_link_first", 'getByRole("link").first()', lambda: frame.get_by_role("link").first.click()),
    ])
    ok, selector, source = _macro_click(
        page,
        name="general settings row",
        selectors=selectors,
    )
    _record_macro_step(
        result,
        action="click",
        description="Preflight opened the first editable general-settings record",
        target="general settings",
        selector=selector,
        locator_source=source or "macro_click",
        success=ok,
        page=page,
    )
    return ok


def _infer_product_field_updates(scenario: str) -> list[tuple[str, str]]:
    lower = scenario.lower()
    updates: list[tuple[str, str]] = []

    def _add(label: str, value: str) -> None:
        pair = (label, value)
        if pair not in updates:
            updates.append(pair)

    if "customs value" in lower:
        _add("Customs Value", "12.34")
    if "country of origin" in lower or "coo" in lower or "origin country" in lower:
        _add("Country of Origin", "IN")
    if "hs code" in lower or "hs codes" in lower:
        _add("HS Code", "123456")
    if "weight" in lower:
        _add("Weight", "1")
    if "dimensions" in lower or "length" in lower:
        _add("Length", "10")
    if "dimensions" in lower or "width" in lower:
        _add("Width", "10")
    if "dimensions" in lower or "height" in lower:
        _add("Height", "10")
    return updates


def _preflight_fill_named_field(page: Any, result: ScenarioResult, label: str, value: str) -> bool:
    frame = _get_app_frame(page)
    selectors = _automation_hint_selectors(f"mcsl products {label}", action="fill", frame=frame, value=value)
    selectors.extend([
        ("label", f'getByLabel("{label}")', lambda: frame.get_by_label(label, exact=False).first.fill(value)),
        ("placeholder", f'getByPlaceholder("{label}")', lambda: frame.get_by_placeholder(label).first.fill(value)),
        ("role_textbox_exact", f'getByRole("textbox", {{ name: "{label}" }})', lambda: frame.get_by_role("textbox", name=label, exact=False).first.fill(value)),
        ("css_locator", f'input[name*="{label.lower().replace(" ", "")}"]', lambda: frame.locator(f'input[name*="{label.lower().replace(" ", "")}"]').first.fill(value)),
    ])
    ok, selector, source = _macro_fill(
        page,
        value=value,
        selectors=selectors,
    )
    _record_macro_step(
        result,
        action="fill",
        description=f'Preflight set "{label}" to "{value}"',
        target=label,
        selector=selector,
        locator_source=source or "macro_fill",
        success=ok,
        page=page,
    )
    return ok


def _preflight_save_form(page: Any, result: ScenarioResult, *, description: str) -> bool:
    frame = _get_app_frame(page)
    selectors = _automation_hint_selectors("mcsl save button product settings automation carriers general settings", action="click", frame=frame)
    selectors.extend([
        ("role_button_exact", 'getByRole("button", { name: "Save" })', lambda: frame.get_by_role("button", name="Save", exact=True).first.click()),
        ("text_exact", 'getByText("Save", { exact: true })', lambda: frame.get_by_text("Save", exact=True).first.click()),
    ])
    ok, selector, source = _macro_click(
        page,
        name="Save",
        selectors=selectors,
    )
    _record_macro_step(
        result,
        action="click",
        description=description,
        target="Save",
        selector=selector,
        locator_source=source or "macro_click",
        success=ok,
        page=page,
    )
    return ok


def _preflight_update_product_fields(page: Any, result: ScenarioResult, scenario: str) -> tuple[int, bool]:
    updates = _infer_product_field_updates(scenario)
    if not updates:
        return 0, False

    success_count = 0
    for label, value in updates[:6]:
        if _preflight_fill_named_field(page, result, label, value):
            success_count += 1

    saved = False
    if success_count:
        saved = _preflight_save_form(page, result, description="Preflight saved product field updates")
    return success_count, saved


def _run_preflight_setup(
    *,
    page: Any,
    result: ScenarioResult,
    plan_data: dict,
    app_base: str,
    scenario: str,
    order_id: str | None,
) -> str:
    setup_notes: list[str] = []
    nav_clicks = _dedupe_strings([str(v) for v in (plan_data.get("nav_clicks") or []) if isinstance(v, str)])
    precondition_steps = _dedupe_strings([str(v) for v in (plan_data.get("precondition_steps") or []) if isinstance(v, str)])
    look_for = _dedupe_strings([str(v) for v in (plan_data.get("look_for") or []) if isinstance(v, str)])
    api_to_watch = _dedupe_strings([str(v) for v in (plan_data.get("api_to_watch") or []) if isinstance(v, str)])

    for destination in nav_clicks[:3]:
        ok = _do_action(page, {"action": "navigate", "url": destination}, app_base)
        _record_macro_step(
            result,
            action="navigate",
            description=f"Preflight navigation to {destination}",
            target=destination,
            selector=destination,
            locator_source="macro_nav",
            success=ok,
            page=page,
        )
        if ok:
            setup_notes.append(f"Preflight opened {destination}.")
        else:
            setup_notes.append(f"Preflight could not open {destination}.")

    _orders_in_plan = "orders" in nav_clicks or any("order" in str(s).lower() for s in nav_clicks)
    _orders_in_scenario = "order" in scenario.lower()
    if order_id and (_orders_in_plan or _orders_in_scenario):
        setup_notes.append(f"Use test order id {order_id} when filtering the ORDERS grid.")
        opened_order = _preflight_open_order_summary(page, result, order_id)
        if opened_order:
            setup_notes.append(f"Opened Order Summary for test order {order_id} during preflight.")
        else:
            setup_notes.append(f"Could not open Order Summary for test order {order_id} during preflight.")

    if precondition_steps:
        setup_notes.append("Deterministic setup checklist:")
        setup_notes.extend(f"- {line}" for line in precondition_steps[:12])
        _record_macro_step(
            result,
            action="observe",
            description="Captured deterministic setup checklist for this scenario",
            target="preconditions",
            locator_source="macro_context",
            success=True,
            page=page,
        )

    if look_for:
        setup_notes.append("Expected UI signals:")
        setup_notes.extend(f"- {line}" for line in look_for[:8])
    if api_to_watch:
        setup_notes.append("Expected API/log signals:")
        setup_notes.extend(f"- {line}" for line in api_to_watch[:8])

    # Targeted preflight hints for the most common execution paths.
    lower = scenario.lower()
    if ("view log" in lower or "request log" in lower or "rate req" in lower or "label req" in lower) and "orders" not in nav_clicks:
        ok = _do_action(page, {"action": "navigate", "url": "orders"}, app_base)
        _record_macro_step(
            result,
            action="navigate",
            description="Preflight opened ORDERS for upcoming request/log verification",
            target="orders",
            selector="orders",
            locator_source="macro_nav",
            success=ok,
            page=page,
        )
        if ok and order_id:
            opened_order = _preflight_open_order_summary(page, result, order_id)
            if opened_order:
                setup_notes.append(f"Opened Order Summary for test order {order_id} after request/log preflight navigation.")
    if ("view log" in lower or "request log" in lower or "rate req" in lower or "label req" in lower) and order_id:
        opened_log = _preflight_open_view_log(page, result)
        if opened_log:
            setup_notes.append("Opened View Log dialog during preflight for request/log verification.")
        else:
            setup_notes.append("Could not open View Log dialog during preflight.")
    if any(token in lower for token in ("label req", "label request", "label log", "label summary")) and order_id:
        opened_label_log = _preflight_open_label_view_log(page, result)
        if opened_label_log:
            setup_notes.append("Opened label-request View Log during preflight.")
        else:
            setup_notes.append("Could not open label-request View Log during preflight.")
    if any(token in lower for token in ("request log", "automation summary", "rate automation", "automation criteria")):
        if "requestlog" not in nav_clicks:
            ok = _do_action(page, {"action": "navigate", "url": "requestlog"}, app_base)
            _record_macro_step(
                result,
                action="navigate",
                description="Preflight opened Request Log for automation log verification",
                target="requestlog",
                selector="requestlog",
                locator_source="macro_nav",
                success=ok,
                page=page,
            )
        opened_request_summary = _preflight_open_request_log_summary(page, result)
        if opened_request_summary:
            setup_notes.append("Opened automation Request Log summary during preflight.")
        else:
            setup_notes.append("Could not open automation Request Log summary during preflight.")
    if ("commercial invoice" in lower or "cn22" in lower or "print documents" in lower or "download documents" in lower) and "orders" not in nav_clicks:
        ok = _do_action(page, {"action": "navigate", "url": "orders"}, app_base)
        _record_macro_step(
            result,
            action="navigate",
            description="Preflight opened ORDERS for upcoming document verification",
            target="orders",
            selector="orders",
            locator_source="macro_nav",
            success=ok,
            page=page,
        )
        if ok and order_id:
            opened_order = _preflight_open_order_summary(page, result, order_id)
            if opened_order:
                setup_notes.append(f"Opened Order Summary for test order {order_id} after document preflight navigation.")

    if order_id and any(token in lower for token in ("generate label", "label created", "mark as fulfilled", "shipment", "shipping label")):
        triggered = _preflight_prepare_and_generate_label(page, result)
        if triggered:
            setup_notes.append("Triggered Prepare Shipment / Generate Label during preflight.")

    if any(token in lower for token in ("download documents", "commercial invoice", "cn22", "cn23")):
        downloaded = _preflight_download_documents(page, result)
        if downloaded:
            setup_notes.append("Downloaded documents ZIP during preflight.")
        else:
            setup_notes.append("Could not download documents ZIP during preflight.")
        opened_upload_log = _preflight_open_upload_document_log(page, result)
        if opened_upload_log:
            setup_notes.append("Opened upload-document View Log during preflight.")

    if "print documents" in lower:
        printed = _preflight_open_print_documents(page, result)
        if printed:
            setup_notes.append("Opened Print Documents during preflight.")
        else:
            setup_notes.append("Could not open Print Documents during preflight.")

    if "appproducts" in nav_clicks or any(token in lower for token in ("customs value", "country of origin", "coo", "hs code", "dimensions", "weight", "dry ice", "alcohol", "battery", "signature")):
        opened_product = _preflight_open_product_settings(page, result)
        if opened_product:
            setup_notes.append("Opened an editable product settings record during preflight.")
            updated_count, saved = _preflight_update_product_fields(page, result, scenario)
            if updated_count:
                setup_notes.append(f"Updated {updated_count} product field(s) during preflight.")
                if saved:
                    setup_notes.append("Saved product field changes during preflight.")
                else:
                    setup_notes.append("Could not save product field changes during preflight.")
        else:
            setup_notes.append("Could not open a product settings record during preflight.")

    if "carriers" in nav_clicks or any(token in lower for token in ("add carrier", "carrier setup", "configure carrier", "carrier account")):
        opened_carrier = _preflight_open_add_carrier(page, result)
        if opened_carrier:
            setup_notes.append("Opened Add Carrier during preflight.")
        else:
            setup_notes.append("Could not open Add Carrier during preflight.")

    if "automation" in nav_clicks or any(token in lower for token in ("automation rule", "rate rule", "label rule", "automation criteria")):
        opened_automation = _preflight_open_automation_rule(page, result)
        if opened_automation:
            setup_notes.append("Opened an automation rule surface during preflight.")
        else:
            setup_notes.append("Could not open an automation rule surface during preflight.")

    if "generalsettings" in nav_clicks or any(token in lower for token in ("packaging", "package type", "packaging settings", "general settings")):
        opened_settings = _preflight_open_general_settings(page, result)
        if opened_settings:
            setup_notes.append("Opened a general settings record during preflight.")
        else:
            setup_notes.append("Could not open a general settings record during preflight.")

    return "\n".join(setup_notes).strip()


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
        for source, resolved, fn in [
            ("role_button_exact", f'getByRole("button", {{ name: "{sel}" }})', lambda: frame.get_by_role("button", name=sel, exact=True).first.click()),
            ("role_link_exact", f'getByRole("link", {{ name: "{sel}" }})', lambda: frame.get_by_role("link", name=sel, exact=True).first.click()),
            ("label_exact", f'getByLabel("{sel}")', lambda: frame.get_by_label(sel, exact=True).first.click()),
            ("text_exact", f'getByText("{sel}", {{ exact: true }})', lambda: frame.get_by_text(sel, exact=True).first.click()),
            ("text_fuzzy", f'getByText("{sel}")', lambda: frame.get_by_text(sel).first.click()),
            ("css_locator", sel, lambda: frame.locator(sel).first.click()),
            ("css_dispatch", sel, lambda: frame.locator(sel).first.dispatch_event("click")),
        ]:
            try:
                fn()
                action["_resolved_locator"] = resolved
                action["_locator_source"] = source
                page.wait_for_timeout(400)
                return True
            except Exception:
                continue
        logger.debug("click failed all strategies for selector: %r", sel)
        return False

    if atype == "fill":
        label = action.get("label", sel)
        value = action.get("value", "")
        placeholder = action.get("label", "")
        raw_selector = action.get("selector", "input")
        for source, resolved, fn in [
            ("label", f'getByLabel("{label}")', lambda: frame.get_by_label(label).fill(value)),
            ("placeholder", f'getByPlaceholder("{placeholder}")', lambda: frame.get_by_placeholder(placeholder).fill(value)),
            ("css_locator", raw_selector, lambda: frame.locator(raw_selector).first.fill(value)),
        ]:
            try:
                fn()
                action["_resolved_locator"] = resolved
                action["_locator_source"] = source
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

    Label generation (same flow for ALL carriers):
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

    if order_action in ("create_new", "create_bulk", "create_new_multi_package"):
        try:
            from pipeline.order_creator import (
                create_order, create_bulk_orders, create_order_multi_package,
                get_carrier_env_for_code,
            )
            env_path = None
            if carrier_code:
                try:
                    env_path = get_carrier_env_for_code(carrier_code)
                except Exception:
                    env_path = None  # will fall back to automation root .env

            use_dangerous = bool(plan_data.get("dangerous_products"))
            # Fall back to automation root .env when no carrier-specific env was found.
            if env_path is None:
                from pipeline.order_creator import _automation_root_env as _arc
                _root_env = _arc()
                if _root_env.exists():
                    env_path = _root_env

            if order_action == "create_new":
                if env_path:
                    order_id = create_order(env_path, use_dangerous_products=use_dangerous)
                    logger.info(f"Created order for scenario: {order_id}")
                else:
                    logger.warning("create_new requested but no env_path available — skipping order creation")
            elif order_action == "create_new_multi_package":
                order_id = create_order_multi_package(env_path, num_packages=2)
                logger.info(f"Created multi-package order for scenario: {order_id}")
            elif order_action == "create_bulk":
                if env_path:
                    order_ids = create_bulk_orders(env_path, count=3, use_dangerous_products=use_dangerous)
                    order_id = order_ids[0] if order_ids else None
                    logger.info(f"Created bulk orders: {order_ids}")

            if order_id:
                ctx = f"TEST ORDER ID: {order_id}\n\n{ctx}"
        except Exception as e:
            logger.warning(f"Order creation failed for {order_action}/{carrier_code}: {e}")
            # Continue without order — agent will attempt to find existing orders

    try:
        preflight_ctx = _run_preflight_setup(
            page=active_page,
            result=result,
            plan_data=plan_data,
            app_base=app_base,
            scenario=scenario,
            order_id=order_id,
        )
        if preflight_ctx:
            ctx = f"{preflight_ctx}\n\n{ctx}" if ctx else preflight_ctx
    except Exception as e:
        logger.debug("Preflight setup failed: %s", e)

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
        step.selector = action.get("_resolved_locator", action.get("selector", "")).strip()
        step.locator_source = action.get("_locator_source", "")
        step.destination = action.get("url", "")
        if "_zip_content" in action:
            step.captured_artifact = _artifact_to_text(action["_zip_content"])
        elif "_file_content" in action:
            step.captured_artifact = _artifact_to_text(action["_file_content"])
        elif atype in {"click", "observe"} and (
            "view log" in (step.target or "").lower()
            or "view log" in (step.description or "").lower()
            or "log" in (step.description or "").lower()
        ):
            step.captured_artifact = _capture_log_dialog_text(active_page)
        try:
            step.page_url = active_page.url or ""
        except Exception:
            step.page_url = ""
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

    _observed_parts: list[str] = []
    _observed_sources: list[str] = []
    if net_seen:
        _observed_parts.append("\n".join(net_seen[-12:]))
        _observed_sources.append("network calls")
    if zip_ctx:
        _observed_parts.append(zip_ctx)
        _observed_sources.append("downloaded logs/documents")
    for _step in result.steps:
        if getattr(_step, "captured_artifact", ""):
            _observed_parts.append(_step.captured_artifact)
            _observed_sources.append(f"{_step.action}:{_step.target or 'artifact'}")
    expectation_obj = plan_data.get("_expectation_obj")
    if expectation_obj:
        try:
            _setup_values = _extract_setup_values_from_steps(result.steps)
            _setup_item_values = _extract_setup_item_values_from_steps(result.steps)
            result.setup_context_summary = _build_setup_context_summary(result.steps)
            comparison = compare_expectations(
                expectation_obj,
                "\n\n".join(_observed_parts),
                observed_sources=_dedupe_strings(_observed_sources),
                setup_values=_setup_values,
                setup_item_values=_setup_item_values,
            )
            result.expectation_comparison = comparison.to_text()
        except Exception as e:
            logger.debug("Expectation comparison failed: %s", e)

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
        _slug = _store_slug()
        if _slug:
            app_url = f"https://admin.shopify.com/store/{_slug}/apps/mcsl-qa"

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

    _run_scenario_verification(
        report=report,
        scenario_entries=[{"execution_text": scenario, "label": scenario} for scenario in scenarios],
        card_name=card_name,
        app_url=app_url,
        stop_flag=stop_flag,
        headless=headless,
        progress_cb=progress_cb,
        qa_answers=qa_answers,
        claude=claude,
    )

    report.duration_seconds = time.time() - start
    logger.info(f"Verification complete: {report.summary} in {report.duration_seconds:.1f}s")
    return report


def build_smart_context(card_name: str, tc_markdown: str = "") -> str:
    """Query every KB source upfront for this card and return a single briefing string.

    Called once before the browser opens so every scenario shares a pre-built
    knowledge snapshot:
      - Matching test cases + acceptance criteria from the TC sheet
      - Relevant wiki feature / pattern docs
      - KB articles for the feature area
      - Automation page-object code for navigation / selectors
      - Backend server code (storepepsaas) relevant to the feature

    Returns a plain-text block injected as SMART KB CONTEXT into the agent
    context for every scenario in the run.
    """
    query = f"{card_name} {tc_markdown[:400]}".strip()
    parts: list[str] = []

    _DOC_SOURCES = [
        ("sheets",      f"{card_name} test cases acceptance criteria",  5, "Matching test cases from TC sheet"),
        ("wiki",        f"{card_name} feature workflow",                4, "Wiki: feature docs & patterns"),
        ("kb_articles", f"{card_name} expected behaviour",              3, "KB: product behaviour notes"),
    ]
    _CODE_SOURCES = [
        ("automation",          f"{card_name} navigation selector page object", 5, "Automation: page objects & selectors"),
        ("storepepsaas_server", f"{card_name} shipping label carrier",          3, "Backend: server-side logic"),
    ]

    try:
        from rag.vectorstore import search_filtered
        for src_type, q, k, label in _DOC_SOURCES:
            try:
                docs = search_filtered(q, k=k, source_type=src_type)
                if docs:
                    snippet = "\n\n".join(
                        f"• {d.page_content[:300]}" for d in docs
                    )
                    parts.append(f"### {label}\n{snippet}")
            except Exception:
                pass
    except Exception:
        pass

    try:
        from rag.code_indexer import search_code
        for src_type, q, k, label in _CODE_SOURCES:
            try:
                docs = search_code(q, k=k, source_type=src_type)
                if docs:
                    snippet = "\n---\n".join(
                        f"[{d.metadata.get('file_path','').split('/')[-1]}]\n{d.page_content[:360]}"
                        for d in docs
                    )
                    parts.append(f"### {label}\n{snippet}")
            except Exception:
                pass
    except Exception:
        pass

    if not parts:
        return ""

    header = (
        f"=== SMART KB CONTEXT for: {card_name} ===\n"
        "Pre-fetched from wiki, TC sheet, KB articles, automation repo, and server code.\n"
        "Use this context to guide navigation, selectors, expected behaviour, and pass/fail criteria.\n\n"
    )
    return header + "\n\n".join(parts)


def verify_test_cases(
    test_cases_markdown: str,
    card_name: str = "",
    stop_flag: "Callable[[], bool] | None" = None,
    headless: bool = False,
    app_url: str = "",
    progress_cb: "Callable[[int, str, int, str], None] | None" = None,
    qa_answers: "dict[str, str] | None" = None,
    max_test_cases: "int | None" = None,
    smart_baseline_ctx: str = "",
) -> VerificationReport:
    """Verify reviewed test cases one-by-one, preserving full TC context."""
    ranked = rank_test_cases_for_execution(test_cases_markdown)
    if max_test_cases and max_test_cases < len(ranked):
        ranked = ranked[:max_test_cases]
    if not app_url:
        _slug = _store_slug()
        if _slug:
            app_url = f"https://admin.shopify.com/store/{_slug}/apps/mcsl-qa"

    report = VerificationReport(card_name=card_name, app_url=app_url)
    if not ranked:
        return report

    claude = ChatAnthropic(
        model=getattr(config, "CLAUDE_SONNET_MODEL", "claude-sonnet-4-5"),
        api_key=getattr(config, "ANTHROPIC_API_KEY", ""),
        max_tokens=4096,
    )
    _run_scenario_verification(
        report=report,
        scenario_entries=[
            {
                "execution_text": tc.scenario_text,
                "label": f"{tc.tc_id}: {tc.title}",
            }
            for tc in ranked
        ],
        card_name=card_name,
        app_url=app_url,
        stop_flag=stop_flag,
        headless=headless,
        progress_cb=progress_cb,
        qa_answers=qa_answers,
        claude=claude,
        smart_baseline_ctx=smart_baseline_ctx,
    )
    return report


def reverify_failed(
    previous_report: VerificationReport,
    test_cases_markdown: str,
    card_name: str = "",
    stop_flag: "Callable[[], bool] | None" = None,
    headless: bool = False,
    app_url: str = "",
    progress_cb: "Callable[[int, str, int, str], None] | None" = None,
    qa_answers: "dict[str, str] | None" = None,
) -> VerificationReport:
    """Re-run only failed/partial/qa-needed test cases from a previous report."""
    ranked = rank_test_cases_for_execution(test_cases_markdown)
    if not ranked:
        return VerificationReport(card_name=card_name, app_url=app_url)

    failed_titles = {
        scenario.scenario for scenario in previous_report.scenarios
        if scenario.status in ("fail", "partial", "qa_needed")
    }
    selected = [tc for tc in ranked if f"{tc.tc_id}: {tc.title}" in failed_titles or tc.title in failed_titles]
    if not selected:
        selected = ranked

    report = verify_test_cases(
        test_cases_markdown="\n\n".join(tc.body for tc in selected),
        card_name=card_name,
        stop_flag=stop_flag,
        headless=headless,
        app_url=app_url,
        progress_cb=progress_cb,
        qa_answers=qa_answers,
        max_test_cases=None,
    )
    return report


def _run_scenario_verification(
    *,
    report: VerificationReport,
    scenario_entries: list[dict[str, str]],
    card_name: str,
    app_url: str,
    stop_flag: "Callable[[], bool] | None",
    headless: bool,
    progress_cb: "Callable[[int, str, int, str], None] | None",
    qa_answers: "dict[str, str] | None",
    claude: "ChatAnthropic",
    smart_baseline_ctx: str = "",
) -> None:
    """Shared browser-runner for AC scenarios and parsed test cases."""
    start = time.time()
    pw, browser, ctx, page = _launch_browser(headless=headless)
    try:
        # Navigate to the app URL so the Shopify embedded-app iframe loads before
        # any scenario starts. Without this the page is blank and _navigate_in_app
        # cannot find the iframe.
        if app_url:
            try:
                page.goto(app_url, wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_timeout(2000)
                logger.info("Navigated to app URL: %s", app_url)
            except Exception as _nav_err:
                logger.warning("Initial navigation to %s failed: %s", app_url, _nav_err)

        total = len(scenario_entries)
        for idx, item in enumerate(scenario_entries):
            execution_text = item.get("execution_text", "").strip()
            scenario_label = item.get("label", execution_text).strip() or f"Scenario {idx + 1}"
            if not execution_text:
                continue
            if stop_flag and stop_flag():
                logger.info("Stop flag triggered before scenario %d — halting", idx + 1)
                break

            logger.info("[%d/%d] Verifying: %s", idx + 1, total, scenario_label[:90])
            if progress_cb:
                progress_cb(idx + 1, scenario_label, 0, "Asking domain expert…")

            try:
                expert_insight = _ask_domain_expert(execution_text, card_name, claude)
                code_ctx = _code_context(execution_text, card_name)
                # Prepend card-level smart KB briefing if this is a smart run
                if smart_baseline_ctx:
                    code_ctx = f"{smart_baseline_ctx}\n\n{code_ctx}" if code_ctx else smart_baseline_ctx
                _carrier_name, _ = _detect_carrier(execution_text)
                expectation = build_request_expectations(
                    scenario=execution_text,
                    carrier=_carrier_name,
                    expert_insight=expert_insight,
                    domain_context=_domain_context_for_expectations(f"{card_name} {execution_text}"),
                    code_context=code_ctx,
                )
                expectation_text = expectation.to_text()
                if expectation_text:
                    code_ctx = f"{code_ctx}\n\n{expectation_text}" if code_ctx else expectation_text
                plan_data = _plan_scenario(execution_text, app_url, code_ctx, expert_insight, claude)
                if expectation.rate_request_fields:
                    for _item in expectation.rate_request_fields:
                        if _item not in plan_data.setdefault("look_for", []):
                            plan_data["look_for"].append(_item)
                if expectation.label_request_fields:
                    for _item in expectation.label_request_fields:
                        if _item not in plan_data.setdefault("look_for", []):
                            plan_data["look_for"].append(_item)
                if expectation.response_signals:
                    for _item in expectation.response_signals:
                        if _item not in plan_data.setdefault("look_for", []):
                            plan_data["look_for"].append(_item)
                if expectation.request_types:
                    _api_hints = []
                    if "rate" in expectation.request_types:
                        _api_hints.extend(["/rates", "rate"])
                    if "label" in expectation.request_types:
                        _api_hints.extend(["/label", "label"])
                    if "response" in expectation.request_types:
                        _api_hints.extend(["response", "/shipment"])
                    for _item in _api_hints:
                        if _item not in plan_data.setdefault("api_to_watch", []):
                            plan_data["api_to_watch"].append(_item)
                if expectation.order_kind and expectation.order_kind != "generic":
                    plan_data.setdefault("expectation_order_kind", expectation.order_kind)
                plan_data["_expectation_obj"] = expectation
                sv = _verify_scenario(
                    page=page,
                    scenario=execution_text,
                    card_name=card_name,
                    app_base=app_url,
                    plan_data=plan_data,
                    ctx=code_ctx,
                    claude=claude,
                    progress_cb=None,
                    qa_answer=(qa_answers or {}).get(scenario_label, (qa_answers or {}).get(execution_text, "")),
                    first_scenario=(idx == 0),
                    expert_insight=expert_insight,
                    stop_flag=stop_flag,
                )
                sv.scenario = scenario_label
                sv.expectation_summary = expectation_text
            except Exception as e:
                logger.error("Scenario %d failed with exception: %s", idx + 1, e)
                sv = ScenarioResult(
                    scenario=scenario_label,
                    status="fail",
                    finding=f"Agent exception: {e}",
                )

            report.scenarios.append(sv)
            try:
                save_runtime_locator_memory(card_name, scenario_label, sv.steps, scenario_status=sv.status)
            except Exception as e:
                logger.debug("Saving runtime locator memory failed: %s", e)
            logger.info("Scenario %d result: %s — %s", idx + 1, sv.status, sv.finding[:80])
    finally:
        browser.close()
        pw.stop()
        report.duration_seconds = time.time() - start
        logger.info("Verification complete: %s in %.1fs", report.summary, report.duration_seconds)
