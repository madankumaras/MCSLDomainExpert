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
  - MCSL label flow: App order grid → Account Card → Generate Label (NOT Shopify More Actions)
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import tempfile
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
    """Return (carrier_name, carrier_code) from AC text. Defaults to ('', '')."""
    lower = ac_text.lower()
    for keyword, (name, code) in CARRIER_CODES.items():
        if keyword in lower:
            return name, code
    return "", ""


# ── URL map builder ────────────────────────────────────────────────────────────

def _build_url_map(app_base: str, store: str) -> dict[str, str]:
    """Build MCSL page URL map from the app base URL and store slug."""
    return {
        "shipping":         f"{app_base}/shopify",
        "appproducts":      f"{app_base}/products",
        "settings":         f"{app_base}/settings/0",
        "carriers":         f"{app_base}/settings/0",
        "pickup":           f"{app_base}/pickup",
        "faq":              f"{app_base}/faq",
        "rates log":        f"{app_base}/rateslog",
        "orders":           f"https://admin.shopify.com/store/{store}/orders",
        "shopifyproducts":  f"https://admin.shopify.com/store/{store}/products",
    }


# ── MCSL workflow guide ────────────────────────────────────────────────────────

_MCSL_WORKFLOW_GUIDE = dedent("""\
## MCSL Multi-Carrier Shipping App — Key Workflows

App slug: mcsl-qa  (URLs: admin.shopify.com/store/<store>/apps/mcsl-qa)
All app UI lives inside: iframe[name="app-iframe"]

### TWO PRODUCT PAGES — DO NOT CONFUSE

❶  nav_clicks: "AppProducts"  →  <app_base>/products
   PURPOSE: Edit MCSL-specific settings on an EXISTING Shopify product.
   Fields: Dimensions (L/W/H, unit), Weight, special services per carrier.
   Save → success toast.
   ⚠️ Cannot create new products here.

❷  nav_clicks: "ShopifyProducts"  →  admin.shopify.com/store/<store>/products
   PURPOSE: Shopify product management — ONLY place to ADD/CREATE products.

### All App Page URLs
- nav_clicks: "Shipping"      → <app_base>/shopify         — App's own order grid
- nav_clicks: "AppProducts"   → <app_base>/products        — Product settings
- nav_clicks: "Settings"      → <app_base>/settings/0      — Carrier & global settings
- nav_clicks: "Carriers"      → <app_base>/settings/0      — Same as Settings
- nav_clicks: "PickUp"        → <app_base>/pickup          — Pickup scheduling
- nav_clicks: "FAQ"           → <app_base>/faq
- nav_clicks: "Rates Log"     → <app_base>/rateslog        — Storefront checkout rate log
- nav_clicks: "Orders"        → admin.shopify.com/store/<store>/orders
- nav_clicks: "ShopifyProducts" → admin.shopify.com/store/<store>/products

### How to Generate a Label (MCSL-specific flow — NOT Shopify More Actions)
MCSL label generation uses the app's own order grid:
1. App sidebar → Shipping → "All Orders" grid (inside iframe)
2. Add filter → Order Id → paste order ID → press Escape
3. Click the order row (bold order number) → Order Summary page opens
4. (Optional) Click "Prepare Shipment" button
5. Click "Generate Label" button
6. Wait for "LABEL CREATED" status → click "Mark As Fulfilled"

⚠️ DO NOT use Shopify admin "More Actions" for MCSL label generation.
   The MCSL app has its own order grid — use App sidebar → Shipping.

### Label Status Values (App's Shipping page)
- Pending           → no label yet
- In Progress       → label being generated
- Label Generated   → label created successfully
- Failed            → label generation failed

Label status locator (inside iframe):
  div[class="order-summary-greyBlock"] > div:nth-child(1) > div:nth-child(1) > div > span

### Rate Log (App's Rates Log page)
1. App sidebar → Rates Log (shows storefront checkout rate requests)
2. Click a row → View all Rate Summary → 3-dots → View Log → .dialogHalfDivParent
⚠️ Rates Log ONLY shows storefront checkout requests, NOT API-created orders.

### Bulk Labels
1. App sidebar → Shipping → All Orders grid
2. Check header checkbox to select all orders
3. Click "Generate labels" button → Label Batch page opens

### Carrier Account Configuration
1. App sidebar → Settings → Carriers tab
2. Add/Edit carrier account (FedEx, UPS, DHL, USPS, etc.)
3. Enter API credentials → Save

### Order Summary page (accessed from app's Shipping grid)
1. App sidebar → Shipping → click order row
2. Order Summary shows: label status, carrier badge, Generate Label button
3. After generation: "Mark As Fulfilled" button appears
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
    card_name: str
    app_url: str
    scenarios: list[ScenarioResult] = field(default_factory=list)
    summary: str = ""

    @property
    def passed(self) -> int:
        return sum(1 for s in self.scenarios if s.status == "pass")

    @property
    def failed(self) -> int:
        return sum(1 for s in self.scenarios if s.status in ("fail", "partial"))

    @property
    def qa_needed(self) -> list[ScenarioResult]:
        return [s for s in self.scenarios if s.status == "qa_needed"]

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

    Navigation rules:
    - For label generation scenarios → nav_clicks: ["Shipping"]  (app order grid — MCSL-specific)
    - For verifying an EXISTING label / downloading documents → nav_clicks: ["Shipping"]
    - For app settings / carrier configuration → nav_clicks: ["Settings"]
    - For rate log scenarios → nav_clicks: ["Rates Log"]
    - For product-level settings → nav_clicks: ["AppProducts"]
    - For creating/editing Shopify products → nav_clicks: ["ShopifyProducts"]
    - ONLY use: "Shipping", "AppProducts", "Settings", "Carriers", "PickUp",
      "ShopifyProducts", "FAQ", "Rates Log", "Orders"

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
      "nav_clicks": ["e.g. Shipping | Settings | AppProducts | ShopifyProducts | Rates Log"],
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
    """Stage 3: Generate JSON execution plan with carrier injection."""
    carrier_name, carrier_code = _detect_carrier(scenario)
    prompt = _PLAN_PROMPT.format(
        scenario=scenario,
        app_url=app_url,
        carrier_name=carrier_name or "(none)",
        carrier_code=carrier_code or "—",
        mcsl_workflow_guide=_MCSL_WORKFLOW_GUIDE,
        expert_insight=expert_insight or "(not available)",
        code_context=code_ctx[:5000],
    )
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
        try:
            url_key = action.get("url", "").lower()
            url_map = _build_url_map(app_base, getattr(config, "STORE", ""))
            target = url_map.get(url_key, action.get("url", ""))
            page.goto(target, wait_until="domcontentloaded")
            page.wait_for_timeout(500)
            return True
        except Exception as e:
            logger.warning("navigate action failed: %s", e)
            return False

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
        logger.warning(
            "download_zip action not yet implemented (Phase 3). "
            "action=%s", action
        )
        return False

    if atype == "download_file":
        logger.warning(
            "download_file action not yet implemented (Phase 3). "
            "action=%s", action
        )
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
    - "shipping"         → App's order grid (use for label generation flows)
    - "settings"         → App settings (carrier accounts, global config)
    - "carriers"         → Same as settings
    - "appproducts"      → MCSL app products (dry ice, alcohol, battery, dimensions, signature)
    - "shopifyproducts"  → Shopify product management (create new products)
    - "orders"           → Shopify admin orders list
    - "pickup"           → Pickup scheduling
    - "rates log"        → Storefront checkout rate log
    - "faq"              → App FAQ

    Rules:
    - action=verify      → you have clear evidence to give a verdict (pass/fail/partial)
    - action=qa_needed   → you genuinely cannot locate the feature after careful searching
    - ONLY reference targets that literally appear in the accessibility tree above
    - Do NOT use Shopify "More Actions" for MCSL label generation — use App sidebar → Shipping
    - App content is in iframe[name="app-iframe"] — click targets are INSIDE the app frame
    - action=observe on first step to capture visible elements before interacting
    - Do NOT explore unrelated sections of the app

    TWO COMPLETELY DIFFERENT PRODUCT PAGES:
    - navigate: "appproducts"  →  App Products (FedEx/MCSL settings on existing products)
      USE FOR: dry ice, alcohol, battery, dimensions, signature, declared value config
      ⚠️ NO "Add product" button — cannot CREATE products here
    - navigate: "shopifyproducts"  →  Shopify Products admin
      USE FOR: create/edit Shopify products (title, price, weight, SKU, variants)
      ⚠️ This is NOT the MCSL app — no MCSL-specific fields here

    Label generation (MCSL-specific — NOT Shopify More Actions):
    1. App sidebar → Shipping → All Orders grid (inside iframe)
    2. Filter by Order Id → click order row
    3. Click "Generate Label" button
    4. Wait for "LABEL CREATED" status → click "Mark As Fulfilled"
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
            zip_ctx = action.get("_zip_summary", "")

    else:
        result.status = "partial"
        result.finding = f"Loop completed {MAX_STEPS} steps without verdict"

    return result


# ── Entry point ────────────────────────────────────────────────────────────────

def verify_ac(
    ac_text: str,
    card_name: str,
    stop_flag: "Callable[[], bool] | None" = None,
    app_url: str = "",
    progress_cb: "Callable[[int, str, int, str], None] | None" = None,
    qa_answers: "dict[str, str] | None" = None,
    max_scenarios: "int | None" = None,
) -> VerificationReport:
    """Verify AC scenarios for a card against the live MCSL Shopify app.

    Args:
        ac_text:        Full AC markdown text
        card_name:      Feature / card title
        stop_flag:      Optional callable — returns True to abort after current scenario
        app_url:        Full MCSL app URL in Shopify admin (auto-built from config.STORE if empty)
        progress_cb:    Optional callback(scenario_idx, scenario_title, step_num, step_desc)
        qa_answers:     {scenario_text: qa_answer} for stuck scenarios
        max_scenarios:  Cap number of scenarios tested (None = test all)

    Returns:
        VerificationReport with per-scenario results
    """
    if not app_url:
        store = getattr(config, "STORE", "")
        if store:
            app_url = f"https://admin.shopify.com/store/{store}/apps/mcsl-qa"

    if not ac_text:
        return VerificationReport(card_name=card_name, app_url=app_url)

    if not getattr(config, "ANTHROPIC_API_KEY", ""):
        raise RuntimeError("ANTHROPIC_API_KEY not set in .env")

    claude = ChatAnthropic(
        model=config.CLAUDE_SONNET_MODEL,
        api_key=config.ANTHROPIC_API_KEY,
        temperature=0.1,
        max_tokens=4096,
    )

    report    = VerificationReport(card_name=card_name, app_url=app_url)
    scenarios = _extract_scenarios(ac_text, claude)

    if max_scenarios and max_scenarios < len(scenarios):
        scenarios = scenarios[:max_scenarios]
        logger.info("verify_ac: capped to %d scenarios for '%s'", len(scenarios), card_name)
    else:
        logger.info("verify_ac: %d scenarios for '%s'", len(scenarios), card_name)

    for idx, scenario in enumerate(scenarios):
        if stop_flag and stop_flag():
            logger.info("verify_ac: stopped by user after %d scenarios", idx)
            break

        logger.info("[%d/%d] Verifying: %s", idx + 1, len(scenarios), scenario[:70])

        if progress_cb:
            progress_cb(idx + 1, scenario, 0, "Asking domain expert…")

        expert_insight = _ask_domain_expert(scenario, card_name, claude)
        code_ctx       = _code_context(scenario, card_name)
        plan_data      = _plan_scenario(scenario, app_url, code_ctx, expert_insight, claude)

        # Browser loop — stub until plan 02-02 implements _verify_scenario
        sv = _verify_scenario(
            page=None,
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
        )
        report.scenarios.append(sv)

    return report
