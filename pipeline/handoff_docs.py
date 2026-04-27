from __future__ import annotations

import datetime as _dt
import io
import logging
import re
from dataclasses import dataclass, field

import config
from pipeline.carrier_knowledge import detect_carrier_scope

logger = logging.getLogger(__name__)


@dataclass
class HandoffDocContext:
    card_id: str
    card_name: str
    card_url: str = ""
    release_name: str = ""
    approved_at: str = ""
    card_description: str = ""
    acceptance_criteria: str = ""
    test_cases: str = ""
    ai_qa_summary: str = ""
    ai_qa_evidence: str = ""
    signoff_summary: str = ""
    developer_names: list[str] = field(default_factory=list)
    tester_names: list[str] = field(default_factory=list)
    toggle_names: list[str] = field(default_factory=list)
    carrier_names: list[str] = field(default_factory=list)
    likely_navigation: list[str] = field(default_factory=list)
    generated_on: str = field(default_factory=lambda: _dt.datetime.now().strftime("%Y-%m-%d %H:%M"))


def split_card_members(members: list[dict]) -> tuple[list[str], list[str]]:
    try:
        from pipeline.bug_reporter import is_qa_name
    except Exception:
        def is_qa_name(_: str) -> bool:
            return False

    testers: list[str] = []
    developers: list[str] = []
    for member in members or []:
        full_name = (member.get("fullName") or member.get("username") or "").strip()
        if not full_name:
            continue
        if is_qa_name(full_name):
            if full_name not in testers:
                testers.append(full_name)
        elif full_name not in developers:
            developers.append(full_name)
    return developers, testers


def detect_toggles(*texts: str) -> list[str]:
    patterns = [
        r"\btoggle\b[:\s-]*([A-Za-z0-9 _-]+)",
        r"\bfeature flag\b[:\s-]*([A-Za-z0-9 _-]+)",
        r"\brollout\b[:\s-]*([A-Za-z0-9 _-]+)",
    ]
    found: list[str] = []
    for text in texts:
        for pattern in patterns:
            for match in re.findall(pattern, text or "", flags=re.IGNORECASE):
                value = re.sub(r"\s+", " ", match).strip(" -:")
                if value and value not in found:
                    found.append(value)
    return found


def detect_carriers(*texts: str) -> list[str]:
    return [profile.canonical_name for profile in detect_carrier_scope(*texts).carriers]


def infer_navigation(*texts: str) -> list[str]:
    combined = " ".join(texts).lower()
    nav: list[str] = []
    if any(token in combined for token in ("order", "label generated", "fulfill", "mark as shipped")):
        nav.append("ORDERS tab -> open order -> Prepare Shipment / Generate Label")
    if any(token in combined for token in ("label", "print documents", "tracking", "manifest")) and "ORDERS tab -> open order -> Prepare Shipment / Generate Label" not in nav:
        nav.append("LABELS or order summary flow inside the MCSL app")
    if any(token in combined for token in ("pickup", "schedule pickup")):
        nav.append("PICKUP tab")
    if any(token in combined for token in ("product", "weight", "dimension", "customs value", "dry ice", "alcohol", "battery", "signature")):
        nav.append("Hamburger menu -> Products")
    if any(token in combined for token in ("carrier", "credentials", "production key", "account details")):
        nav.append("Hamburger menu -> Carriers")
    if any(token in combined for token in ("packaging", "box", "packing method")):
        nav.append("Hamburger menu -> Settings / Packaging")
    if any(token in combined for token in ("rate", "checkout", "automation rule", "service selection", "request log")):
        nav.append("Hamburger menu -> Settings / Shipping Rates / Automation or Request Log")
    if any(token in combined for token in ("shopify", "product_id", "variant_id", "tracking number")):
        nav.append("Shopify Admin -> Orders or Products for post-verification")
    if not nav:
        nav.append("MCSL embedded app main flow via ORDERS, LABELS, PICKUP, or hamburger settings")
    return nav


def build_handoff_context(
    *,
    card,
    release_name: str = "",
    approved_at: str = "",
    acceptance_criteria: str = "",
    test_cases: str = "",
    ai_qa_summary: str = "",
    ai_qa_evidence: str = "",
    signoff_summary: str = "",
    members: list[dict] | None = None,
) -> HandoffDocContext:
    devs, testers = split_card_members(members or [])
    desc = getattr(card, "desc", "") or ""
    toggles = detect_toggles(desc, getattr(card, "name", "") or "", acceptance_criteria, test_cases)
    carriers = detect_carriers(desc, getattr(card, "name", "") or "", acceptance_criteria, test_cases, ai_qa_summary, ai_qa_evidence)
    navigation = infer_navigation(desc, getattr(card, "name", "") or "", acceptance_criteria, test_cases, ai_qa_summary, ai_qa_evidence)
    return HandoffDocContext(
        card_id=getattr(card, "id", ""),
        card_name=getattr(card, "name", ""),
        card_url=getattr(card, "url", "") or "",
        release_name=release_name,
        approved_at=approved_at,
        card_description=desc,
        acceptance_criteria=acceptance_criteria or desc,
        test_cases=test_cases,
        ai_qa_summary=ai_qa_summary,
        ai_qa_evidence=ai_qa_evidence,
        signoff_summary=signoff_summary,
        developer_names=devs,
        tester_names=testers,
        toggle_names=toggles,
        carrier_names=carriers,
        likely_navigation=navigation,
    )


_SUPPORT_PROMPT = """You are writing a detailed QA & support handoff document for an MCSL Shopify shipping feature.

This document is used internally by QA engineers, support staff, and account managers. \
It should read like a polished product release guide — structured, scenario-rich, and immediately actionable.

Use this EXACT section order — no other sections:

1. `# <Feature Name>` — short descriptive title only (no "Support Guide" prefix)
2. `## The Problem` — 3-5 short bullet points describing the merchant pain \
   before this feature. Each bullet: one concrete frustration. No paragraphs.
3. `## The Solution` — one-paragraph overview of what the feature does, followed by \
   a `### <Capability Name>` subsection for EACH major capability. \
   Each subsection: 1-2 sentences describing what it does and when a merchant uses it.
4. `## Key Benefits` — markdown table with two columns: **Benefit** and **Description**. \
   5-6 rows. Each row: one clear, merchant-facing gain (speed, accuracy, continuity, etc.).
5. `## User Story` — one sentence starting with a double-quote: \
   `"As a merchant using the MCSL app, I want to..."`
6. `## How to Use` — numbered steps (1 through N) describing the end-to-end flow \
   a merchant follows to use this feature. Use MCSL app navigation paths. Keep each step tight.
7. `## Test Scenarios` — ALL test cases from the context formatted as grouped markdown tables. \
   Group by logical area (e.g. Order ID Filter, Date Filter, Combination Tests). \
   Each group: a `### [Group Name]` heading followed by a markdown table with columns: \
   `| # | Scenario | Expected Result |`. \
   Derive scenario rows from the test cases in the context. Include ALL of them — do not summarise.
8. `## Acceptance Criteria Checklist` — every acceptance criterion as a checkbox bullet: \
   `- [ ] <criterion text>`. One item per line. Cover all ACs from the context.

Formatting rules:
- Use markdown tables with pipe syntax — header row, separator row (|---|---|), then data rows
- Use `### Scenario N: <name>` format only under The Solution — not elsewhere
- Never use giant paragraphs — prefer bullets, numbered lists, and tables
- Mention MCSL navigation paths naturally (ORDERS tab, hamburger menu → Carriers, etc.)
- Call out carrier names explicitly when the feature is carrier-specific
- DO NOT add: Key Findings, AI Code Analysis, Troubleshooting Notes, Limitations, Rollout Notes, References
- Use facts from the context only. Do not invent test cases or ACs not present in the context.

CONTEXT:
{context}
"""


_BUSINESS_PROMPT = """You are writing a customer-facing, marketing-style Business Brief for a new feature in the MCSL \
(Multi-Carrier Shipping Labels) Shopify app by PluginHive.

Your audience is Shopify merchants, e-commerce store owners, account managers, and product marketing — \
NOT engineers or QA teams. Write as if this will appear on a product update page or be shared with a customer \
success manager explaining the release to a merchant.

Tone: Friendly, benefit-first, real-world focused. No jargon, no API field names, no enum values, no code identifiers.

Use this exact section order:
1. `# What's New: <feature name in plain English>`
2. `## The Problem We Solved`
3. `## What You Can Do Now`
4. `## Real-World Scenarios`
5. `## Who Benefits`
6. `## How to Get Started`
7. `## What Stays the Same`

Section guidelines:
- **The Problem We Solved**: Tell the story from a merchant's perspective. What frustration or blocker did they hit? \
  Use a realistic merchant scenario (e.g. "If your warehouse uses thermal label printers..."). 2-4 sentences max.
- **What You Can Do Now**: Plain-English bullets describing the new capability. No technical terms. \
  Translate any label format names (e.g. STOCK_4X6 → "4×6 inch thermal label") into human-readable equivalents.
- **Real-World Scenarios**: Write 2-3 short named scenarios (### Scenario 1: ...) showing a real merchant \
  benefiting from this feature. Use concrete details: store type, shipment type, what they do, what improves.
- **Who Benefits**: Short bullets — which merchant types, business sizes, or shipping patterns benefit most.
- **How to Get Started**: Simple numbered steps in plain English. Use app navigation in natural language \
  (e.g. "Go to Settings → Carriers → FedEx" not raw path codes). No more than 5 steps.
- **What Stays the Same**: Reassure merchants what hasn't changed. Calm any migration concerns.

Rules:
- Never mention API fields, JSON payloads, enum values, or code identifiers
- Never mention internal QA terms (acceptance criteria, test cases, fallback, regression)
- Use merchant-friendly language throughout: "you can now", "your labels", "your store"
- If the feature is carrier-specific, say the carrier name naturally ("FedEx" not "FedEx REST endpoint")
- Keep the whole document skimmable and upbeat

Use facts from the context only. Do not invent features or scenarios not supported by the context.

CONTEXT:
{context}
"""


def _context_text(ctx: HandoffDocContext) -> str:
    parts = [
        f"Card: {ctx.card_name}",
        f"Card URL: {ctx.card_url or '(none)'}",
        f"Release: {ctx.release_name or '(unknown)'}",
        f"Approved at: {ctx.approved_at or '(unknown)'}",
        f"Developed by: {', '.join(ctx.developer_names) if ctx.developer_names else 'Unknown'}",
        f"Tested by: {', '.join(ctx.tester_names) if ctx.tester_names else 'QA Team'}",
        f"Toggles: {', '.join(ctx.toggle_names) if ctx.toggle_names else 'None detected'}",
        f"Carriers: {', '.join(ctx.carrier_names) if ctx.carrier_names else 'Carrier-neutral or not explicitly stated'}",
        "Likely MCSL navigation:",
        "\n".join(f"- {item}" for item in (ctx.likely_navigation or [])),
        "",
        "CARD DESCRIPTION / CURRENT AC:",
        (ctx.acceptance_criteria or ctx.card_description or "").strip()[:7000],
        "",
        "TEST CASES:",
        (ctx.test_cases or "").strip()[:6000],
        "",
        "AI QA SUMMARY:",
        (ctx.ai_qa_summary or "").strip()[:3000],
        "",
        "AI QA EVIDENCE:",
        (ctx.ai_qa_evidence or "").strip()[:5000],
        "",
        "SIGN-OFF / NOTES:",
        (ctx.signoff_summary or "").strip()[:2000],
    ]
    return "\n".join(parts).strip()


def _invoke_doc_prompt(prompt: str, ctx: HandoffDocContext) -> str:
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    from langchain_anthropic import ChatAnthropic
    from langchain_core.messages import HumanMessage

    claude = ChatAnthropic(
        model=config.CLAUDE_SONNET_MODEL,
        api_key=config.ANTHROPIC_API_KEY,
        temperature=0.1,
        max_tokens=2400,
    )
    resp = claude.invoke([HumanMessage(content=prompt.format(context=_context_text(ctx)))])
    content = resp.content if isinstance(resp.content, str) else str(resp.content)
    return content.strip()


def _fallback_support_doc(ctx: HandoffDocContext) -> str:
    carriers = ", ".join(ctx.carrier_names) if ctx.carrier_names else "carrier-neutral"
    nav_steps = ctx.likely_navigation or ["MCSL embedded app main flow"]
    nav_numbered = "\n".join(f"{i+1}. {item}" for i, item in enumerate(nav_steps))
    ac_lines = ""
    if ctx.acceptance_criteria:
        for line in ctx.acceptance_criteria.splitlines():
            s = line.strip().lstrip("-").lstrip("*").strip()
            if s and not s.startswith("#"):
                ac_lines += f"- [ ] {s}\n"
    if not ac_lines:
        ac_lines = "- [ ] Verify feature behaves as described in the approved card scope\n"
    return f"""# {ctx.card_name}

## The Problem
- Merchants struggled to complete this workflow without errors or manual workarounds
- The existing flow lacked the capability described in this feature
- {carriers} users were particularly impacted when performing related operations
- No built-in mechanism existed to handle the scenario covered by this update

## The Solution
This update introduces the capability described in the card scope, making the workflow faster and more reliable for merchants using {carriers} through the MCSL app.

{nav_numbered}

## Key Benefits

| Benefit | Description |
|---------|-------------|
| Accuracy | Results match exactly what was requested — no false positives |
| Speed | The operation completes without noticeable delay or page reload |
| Reliability | Existing workflows and configurations are fully preserved |
| Clarity | The UI makes the current state immediately visible |
| Safety | No regressions introduced to adjacent features |

## User Story

"As a merchant using the MCSL app, I want to use this feature so that I can complete my shipping workflow faster and with fewer errors."

## How to Use

1. Open the MCSL app from your Shopify Admin panel
2. Navigate to the relevant section: {nav_steps[0]}
3. Locate the new capability as described in the card scope
4. Apply or configure it according to your store's requirements
5. Verify the outcome matches the expected behaviour described in the acceptance criteria

## Test Scenarios

### Core Scenarios

| # | Scenario | Expected Result |
|---|----------|-----------------|
| 1 | Feature used with valid inputs | Expected outcome displayed correctly |
| 2 | Feature used with invalid or empty inputs | Empty state or error shown gracefully |
| 3 | Feature combined with existing related functionality | No regression; both work correctly |

## Acceptance Criteria Checklist

{ac_lines.strip()}
"""


def _fallback_business_doc(ctx: HandoffDocContext) -> str:
    carriers = ", ".join(ctx.carrier_names) if ctx.carrier_names else "all supported carriers"
    return f"""# What's New: {ctx.card_name}

## The Problem We Solved
Merchants using {carriers} through the MCSL app previously encountered a limitation in this area. \
This update removes that blocker so your store can ship more smoothly without workarounds.

## What You Can Do Now
- The new capability is now available directly inside the MCSL app — no additional setup required
- {carriers} users benefit immediately upon updating to this release
- Existing configurations and workflows continue to work exactly as before

## Real-World Scenarios

### Scenario 1: Day-to-day shipping
A merchant shipping orders through {carriers} can now complete their label generation flow \
without hitting the previous limitation, saving time on every shipment.

### Scenario 2: High-volume store
For stores processing many orders per day, this update eliminates a manual workaround step, \
reducing the chance of errors and speeding up fulfilment.

## Who Benefits
- Shopify merchants using {carriers} for shipping
- Stores that previously hit errors or limitations in this label flow
- Merchants looking for a smoother, more reliable shipping experience

## How to Get Started
1. Open the MCSL app from your Shopify admin
2. Navigate to the relevant settings area for your carrier
3. Configure the new option to match your shipping setup
4. Generate a label from the ORDERS tab to verify everything works
5. Contact PluginHive support if you need help getting set up

## What Stays the Same
- All your existing carrier settings and label configurations are untouched
- Other carriers and shipping flows work exactly as before
- No migration or re-configuration is needed for current setups
"""


def generate_support_guide(ctx: HandoffDocContext) -> str:
    try:
        return _invoke_doc_prompt(_SUPPORT_PROMPT, ctx)
    except Exception as exc:
        logger.warning("Support guide generation fell back to template: %s", exc)
        return _fallback_support_doc(ctx)


def generate_business_brief(ctx: HandoffDocContext) -> str:
    try:
        return _invoke_doc_prompt(_BUSINESS_PROMPT, ctx)
    except Exception as exc:
        logger.warning("Business brief generation fell back to template: %s", exc)
        return _fallback_business_doc(ctx)


def _register_fonts() -> tuple[str, str]:
    """Register Arial + Georgia TTF fonts. Returns (sans_family, serif_family)."""
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfbase.pdfmetrics import registerFontFamily

        _SF = "/System/Library/Fonts/Supplemental/"
        pdfmetrics.registerFont(TTFont("Arial",           _SF + "Arial.ttf"))
        pdfmetrics.registerFont(TTFont("Arial-Bold",      _SF + "Arial Bold.ttf"))
        pdfmetrics.registerFont(TTFont("Arial-Italic",    _SF + "Arial Italic.ttf"))
        pdfmetrics.registerFont(TTFont("Arial-BoldItalic",_SF + "Arial Bold Italic.ttf"))
        registerFontFamily("Arial", normal="Arial", bold="Arial-Bold",
                           italic="Arial-Italic", boldItalic="Arial-BoldItalic")

        pdfmetrics.registerFont(TTFont("Georgia",           _SF + "Georgia.ttf"))
        pdfmetrics.registerFont(TTFont("Georgia-Bold",      _SF + "Georgia Bold.ttf"))
        pdfmetrics.registerFont(TTFont("Georgia-Italic",    _SF + "Georgia Italic.ttf"))
        pdfmetrics.registerFont(TTFont("Georgia-BoldItalic",_SF + "Georgia Bold Italic.ttf"))
        registerFontFamily("Georgia", normal="Georgia", bold="Georgia-Bold",
                           italic="Georgia-Italic", boldItalic="Georgia-BoldItalic")
        return "Arial", "Georgia"
    except Exception:
        return "Helvetica", "Times-Roman"


def _md_to_rl(text: str, sans: str = "Arial") -> str:
    """Convert basic markdown inline formatting to ReportLab XML tags."""
    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'<b><i>\1</i></b>', text)
    text = re.sub(r'\*\*(.+?)\*\*',     r'<b>\1</b>', text)
    text = re.sub(r'\*(.+?)\*',         r'<i>\1</i>', text)
    text = re.sub(r'`(.+?)`',           r'<font name="Courier" fontSize="9">\1</font>', text)
    # Strip any unmatched asterisks left over (e.g. from BDD steps bleeding in)
    text = re.sub(r'\*+', '', text)
    return text


def render_pdf_bytes(title: str, markdown_text: str) -> bytes:
    try:
        from reportlab.lib.colors import HexColor
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import (
            HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
        )
    except ModuleNotFoundError as exc:
        raise RuntimeError("PDF rendering requires reportlab to be installed") from exc

    SANS, SERIF = _register_fonts()

    PAGE_W, PAGE_H = A4
    LM = RM = 0.7 * inch
    CW = PAGE_W - LM - RM

    # ── Professional navy / gold colour palette ──────────────────────────────
    C_NAVY      = HexColor("#0d1b3e")   # header background — deep navy
    C_NAVY_MID  = HexColor("#162447")   # header body rows
    C_NAVY_META = HexColor("#1a2f5e")   # metadata strip
    C_GOLD      = HexColor("#c9922a")   # badge label & subtitle — warm gold
    C_BLUE      = HexColor("#1d4ed8")   # section headings — royal blue
    C_ACCENT    = HexColor("#2563eb")   # left accent bar
    C_WHITE     = HexColor("#ffffff")
    C_HDR_DESC  = HexColor("#cbd5e1")   # header description text
    C_META_TXT  = HexColor("#94a3b8")   # metadata strip text
    C_TEXT      = HexColor("#1e293b")   # body text — rich charcoal
    C_GRAY      = HexColor("#475569")   # secondary / quote text
    C_BORDER    = HexColor("#e2e8f0")   # dividers & table borders

    def _ps(name, **kw):
        return ParagraphStyle(name, **kw)

    # Fonts: Georgia for the big title impact, Arial everywhere else
    hdr_badge  = _ps("HBadge", fontName=f"{SANS}-Bold",   fontSize=8.5, leading=11, textColor=C_GOLD,
                               spaceAfter=2, tracking=60)
    hdr_title  = _ps("HTitle", fontName=f"{SERIF}-Bold",  fontSize=26,  leading=32, textColor=C_WHITE,
                               spaceAfter=4)
    hdr_sub    = _ps("HSub",   fontName=f"{SANS}-Bold",   fontSize=10.5,leading=14, textColor=C_GOLD,
                               spaceAfter=0)
    hdr_desc   = _ps("HDesc",  fontName=f"{SANS}-Italic", fontSize=10,  leading=14, textColor=C_HDR_DESC)
    hdr_meta   = _ps("HMeta",  fontName=SANS,             fontSize=8.5, leading=12, textColor=C_META_TXT)
    h2_style   = _ps("H2",     fontName=f"{SANS}-Bold",   fontSize=12,  leading=16, textColor=C_BLUE,
                               spaceBefore=12, spaceAfter=2)
    h3_style   = _ps("H3",     fontName=f"{SANS}-BoldItalic", fontSize=11, leading=14, textColor=C_BLUE,
                               spaceBefore=8, spaceAfter=3)
    body_style = _ps("Body",   fontName=SANS,             fontSize=10.5, leading=16, textColor=C_TEXT,
                               spaceAfter=6)
    bullet_sty = _ps("Bullet", fontName=SANS,             fontSize=10.5, leading=16, textColor=C_TEXT,
                               spaceAfter=4, leftIndent=16)
    num_style  = _ps("Num",    fontName=SANS,             fontSize=10.5, leading=16, textColor=C_TEXT,
                               spaceAfter=4, leftIndent=18)
    quote_sty  = _ps("Quote",  fontName=f"{SERIF}-Italic",fontSize=10.5, leading=16, textColor=C_GRAY,
                               leftIndent=20, rightIndent=20, spaceAfter=8,
                               borderPadding=(6, 10, 6, 14),
                               borderColor=C_GOLD, borderWidth=0)

    # ── H2 with left royal-blue accent bar ──────────────────────────────────
    def _h2_row(text: str):
        bar = Table([[""]], colWidths=[4], rowHeights=[18])
        bar.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), C_ACCENT),
            ("TOPPADDING",    (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ("LEFTPADDING",   (0, 0), (-1, -1), 0),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ]))
        p = Paragraph(_md_to_rl(text), h2_style)
        row = Table([[bar, p]], colWidths=[6, CW - 6])
        row.setStyle(TableStyle([
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",    (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ("LEFTPADDING",   (0, 0), (-1, -1), 0),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
            ("LEFTPADDING",   (0, 1), (0, 1), 9),
        ]))
        return [row, HRFlowable(width=CW, thickness=0.5, color=C_BORDER, spaceAfter=5)]

    # ── Badge / subtitle detection ───────────────────────────────────────────
    tl = title.lower()
    if any(w in tl for w in ["delay", "fix", "bug", "error", "performance", "slow", "issue"]):
        badge_txt = "PERFORMANCE FIX"
    elif any(w in tl for w in ["new", "feature", "add", "introduc", "launch"]):
        badge_txt = "NEW FEATURE"
    else:
        badge_txt = "UPDATE"

    clean_title = re.sub(r'\[#\d+\]', '', title).strip()
    clean_title = re.sub(r'From SL:\s*[A-Z]+-\d+\s*[—–-]\s*', '', clean_title).strip()

    carriers_found = re.findall(
        r'\b(Australia Post|eParcel|MyPost|FedEx|UPS|DHL|USPS|Stamps)\b', title, re.IGNORECASE,
    )
    subtitle = "MCSL Shopify App"
    if carriers_found:
        subtitle = "MCSL App  ·  " + "  /  ".join(dict.fromkeys(c.title() for c in carriers_found))

    # ── Parse markdown ───────────────────────────────────────────────────────
    lines = (markdown_text or "").splitlines()
    content_lines: list[str] = []
    desc_text = ""
    skip_h1 = True
    for line in lines:
        if skip_h1 and line.startswith("# "):
            skip_h1 = False
            continue
        content_lines.append(line)
        if not desc_text:
            s = line.strip()
            if s and not s.startswith("#") and not s.startswith("-"):
                desc_text = s[:170] + ("…" if len(s) > 170 else "")

    # ── Canvas footer ────────────────────────────────────────────────────────
    buf = io.BytesIO()

    def _draw_footer(canvas_obj, doc):
        canvas_obj.saveState()
        # Thin gold rule above footer
        canvas_obj.setStrokeColor(C_GOLD)
        canvas_obj.setLineWidth(0.5)
        canvas_obj.line(LM, 26, PAGE_W - RM, 26)
        canvas_obj.setFillColor(C_GRAY)
        canvas_obj.setFont(SANS, 7.5)
        canvas_obj.drawString(LM, 12, f"Generated {_dt.datetime.now().strftime('%B %d, %Y')}  ·  Confidential — PluginHive")
        canvas_obj.drawCentredString(PAGE_W / 2, 12, f"Page {doc.page}")
        canvas_obj.drawRightString(PAGE_W - RM, 12, "pluginhive.com")
        canvas_obj.restoreState()

    doc_obj = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=LM, rightMargin=RM,
        topMargin=0.4 * inch, bottomMargin=0.5 * inch,
        title=title,
    )

    story: list = []

    # ── Header panel (deep navy) ─────────────────────────────────────────────
    badge_p = Paragraph(badge_txt, hdr_badge)
    title_p = Paragraph(clean_title, hdr_title)
    sub_p   = Paragraph(subtitle, hdr_sub)
    desc_p  = Paragraph(_md_to_rl(desc_text), hdr_desc) if desc_text else Spacer(1, 2)

    hdr_tbl = Table([[badge_p], [title_p], [sub_p], [desc_p]], colWidths=[CW])
    hdr_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), C_NAVY_MID),
        ("BACKGROUND",    (0, 0), (0, 0),   C_NAVY),
        ("TOPPADDING",    (0, 0), (0, 0), 18),
        ("BOTTOMPADDING", (0, 0), (0, 0),  4),
        ("TOPPADDING",    (0, 1), (0, 1),  4),
        ("BOTTOMPADDING", (0, 1), (0, 1),  6),
        ("TOPPADDING",    (0, 2), (0, 2),  2),
        ("BOTTOMPADDING", (0, 2), (0, 2),  8),
        ("TOPPADDING",    (0, 3), (0, 3),  2),
        ("BOTTOMPADDING", (0, 3), (0, 3), 18),
        ("LEFTPADDING",   (0, 0), (-1, -1), 22),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 22),
    ]))

    # Gold top-border accent line on header
    hdr_border = Table([[""]], colWidths=[CW], rowHeights=[3])
    hdr_border.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), C_GOLD),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
    ]))

    meta_txt = (
        f"Generated {_dt.datetime.now().strftime('%B %Y')}     ·     "
        f"PluginHive QA Team"
    )
    meta_tbl = Table([[Paragraph(meta_txt, hdr_meta)]], colWidths=[CW])
    meta_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), C_NAVY_META),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING",   (0, 0), (-1, -1), 22),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 22),
    ]))

    story += [hdr_border, hdr_tbl, meta_tbl, Spacer(1, 0.25 * inch)]

    # ── Styles for tables and checkboxes ────────────────────────────────────
    tbl_hdr  = _ps("TblHdr",  fontName=f"{SANS}-Bold", fontSize=9,   leading=12,
                               textColor=C_WHITE)
    tbl_cell = _ps("TblCell", fontName=SANS,            fontSize=9,   leading=13,
                               textColor=C_TEXT)
    tbl_cell_sm = _ps("TblSm", fontName=SANS,           fontSize=8.5, leading=12,
                               textColor=C_TEXT)
    chk_sty  = _ps("Chk",     fontName=SANS,            fontSize=10.5, leading=16,
                               textColor=C_TEXT, spaceAfter=3, leftIndent=16)

    def _flush_table(raw_rows: list[str]) -> None:
        """Parse buffered markdown table lines and append a styled ReportLab Table."""
        parsed: list[list[str]] = []
        for r in raw_rows:
            if re.match(r"^\|[-| :]+\|$", r.strip()):
                continue  # separator row
            cells = [c.strip() for c in r.strip().strip("|").split("|")]
            parsed.append(cells)
        if not parsed:
            return
        n_cols = max(len(r) for r in parsed)
        # Normalise column count
        parsed = [r + [""] * (n_cols - len(r)) for r in parsed]
        # Auto column widths: first col narrower, last col narrower for status cols
        if n_cols == 3:
            col_ws = [0.06 * CW, 0.56 * CW, 0.38 * CW]
        elif n_cols == 2:
            col_ws = [0.32 * CW, 0.68 * CW]
        else:
            unit = CW / n_cols
            col_ws = [unit] * n_cols
        # Build cell paragraphs
        tbl_data: list[list] = []
        for ri, row in enumerate(parsed):
            style = tbl_hdr if ri == 0 else tbl_cell_sm
            tbl_data.append([Paragraph(_md_to_rl(cell), style) for cell in row])
        rl_tbl = Table(tbl_data, colWidths=col_ws, repeatRows=1)
        ts = TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0),   C_NAVY),
            ("TEXTCOLOR",     (0, 0), (-1, 0),   C_WHITE),
            ("FONTNAME",      (0, 0), (-1, 0),   f"{SANS}-Bold"),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1),  [C_WHITE, HexColor("#f1f5f9")]),
            ("GRID",          (0, 0), (-1, -1),  0.4, C_BORDER),
            ("TOPPADDING",    (0, 0), (-1, -1),  5),
            ("BOTTOMPADDING", (0, 0), (-1, -1),  5),
            ("LEFTPADDING",   (0, 0), (-1, -1),  7),
            ("RIGHTPADDING",  (0, 0), (-1, -1),  7),
            ("VALIGN",        (0, 0), (-1, -1),  "TOP"),
        ])
        rl_tbl.setStyle(ts)
        story.append(rl_tbl)
        story.append(Spacer(1, 0.1 * inch))

    # ── Render content (with table buffering) ────────────────────────────────
    table_buf: list[str] = []

    def _maybe_flush():
        if table_buf:
            _flush_table(list(table_buf))
            table_buf.clear()

    for line in content_lines:
        clean = line.strip()

        # Table row detection
        if clean.startswith("|"):
            table_buf.append(clean)
            continue
        else:
            _maybe_flush()

        if not clean:
            story.append(Spacer(1, 0.05 * inch))
            continue
        if clean.startswith("## ") or (clean.startswith("# ") and not skip_h1):
            prefix = "## " if clean.startswith("## ") else "# "
            story.extend(_h2_row(clean[len(prefix):].strip()))
        elif clean.startswith("### "):
            story.append(Paragraph(_md_to_rl(clean[4:].strip()), h3_style))
        elif re.match(r"^- \[[ xX]\]", clean):
            # Checkbox bullet: - [ ] or - [x]
            checked = bool(re.match(r"^- \[[xX]\]", clean))
            raw_text = re.sub(r"^- \[[ xX]\]\s*", "", clean)
            # Strip any leftover ** / * that _md_to_rl couldn't pair-match
            raw_text = re.sub(r"\*+", "", raw_text)
            text = _md_to_rl(raw_text)
            if checked:
                icon = f'<font color="#16a34a" fontName="{SANS}-Bold" fontSize="13">✓</font>'
            else:
                icon = f'<font color="#1d4ed8" fontName="{SANS}-Bold" fontSize="11">✦</font>'
            story.append(Paragraph(f"{icon}  {text}", chk_sty))
        elif clean.startswith("- ") or clean.startswith("* "):
            text = _md_to_rl(clean[2:].strip())
            story.append(Paragraph(
                f'<font color="#c9922a" fontName="{SANS}-Bold">›</font>  {text}', bullet_sty,
            ))
        elif re.match(r"^\d+\.\s+", clean):
            m = re.match(r"^(\d+)\.\s+(.*)", clean)
            if m:
                n, cnt = m.group(1), _md_to_rl(m.group(2))
                story.append(Paragraph(
                    f'<font color="#1d4ed8" fontName="{SANS}-Bold">{n}.</font>  {cnt}', num_style,
                ))
        elif clean.startswith('"') or clean.startswith('\u201c'):
            q_tbl = Table([[Paragraph(_md_to_rl(clean), quote_sty)]], colWidths=[CW])
            q_tbl.setStyle(TableStyle([
                ("BACKGROUND",   (0, 0), (-1, -1), HexColor("#fefce8")),
                ("LINEAFTER",    (0, 0), (0, -1),  3, C_GOLD),
                ("LINEBEFORE",   (0, 0), (0, -1),  3, C_GOLD),
                ("TOPPADDING",   (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING",(0, 0), (-1, -1), 10),
                ("LEFTPADDING",  (0, 0), (-1, -1), 14),
                ("RIGHTPADDING", (0, 0), (-1, -1), 14),
            ]))
            story.append(q_tbl)
            story.append(Spacer(1, 0.06 * inch))
        else:
            story.append(Paragraph(_md_to_rl(clean), body_style))

    _maybe_flush()
    story.append(Spacer(1, 0.3 * inch))
    doc_obj.build(story, onFirstPage=_draw_footer, onLaterPages=_draw_footer)
    return buf.getvalue()
