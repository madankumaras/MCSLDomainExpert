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


_SUPPORT_PROMPT = """You are writing a polished internal Support Guide for an MCSL Shopify shipping feature handoff.

Write a practical, support/demo-friendly document in clean markdown.

Requirements:
- Use this exact high-level section order:
  1. `# Support Guide - <feature name>`
  2. `## Snapshot`
  3. `## Ownership`
  4. `## Prerequisites`
  5. `## Where to Find It`
  6. `## Support Walkthrough`
  7. `## Expected Outcome`
  8. `## Troubleshooting Notes`
  9. `## Limitations / Rollout Notes`
  10. `## References`
- In `Snapshot`, use 3-5 short bullets only
- In `Ownership` and `Prerequisites`, keep bullets compact and scannable
- In `Support Walkthrough`, use numbered steps
- In `Expected Outcome`, use bullets
- In `Troubleshooting Notes`, use short bullets, not paragraphs
- In `References`, include Trello link when available
- Mention MCSL navigation using only supported paths such as ORDERS, LABELS, PICKUP, hamburger menu items, and Shopify admin verification pages when relevant
- If carriers are mentioned in context, call them out clearly and mention carrier-specific prerequisites only when supported by the context
- If the flow involves rate troubleshooting, request log, label request, packaging, or Shopify fulfillment verification, mention that explicitly when supported by the context
- Keep the tone polished, crisp, and easy for support/demo teams to skim quickly
- Avoid giant paragraphs and avoid repeating the same facts across sections
Use facts from the context only. Do not invent unsupported details.
Keep it concise but useful.

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
8. `## Release Details`

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
- **Release Details**: Carrier scope in plain English, any prerequisites, release name, team credits. \
  Include Trello link if available.

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
    toggles = ", ".join(ctx.toggle_names) if ctx.toggle_names else "None detected"
    devs = ", ".join(ctx.developer_names) if ctx.developer_names else "Unknown"
    testers = ", ".join(ctx.tester_names) if ctx.tester_names else "QA Team"
    carriers = ", ".join(ctx.carrier_names) if ctx.carrier_names else "Carrier-neutral"
    navigation = "\n".join(f"- {item}" for item in (ctx.likely_navigation or ["MCSL embedded app main flow"]))
    return f"""# Support Guide - {ctx.card_name}

## Snapshot
- Release: {ctx.release_name or 'Unknown'}
- Approved: {ctx.approved_at or 'Unknown'}
- Carrier scope: {carriers}
- Toggles: {toggles}
- Trello: {ctx.card_url or 'N/A'}

## Ownership
- Developed by: {devs}
- Tested by: {testers}

## Prerequisites
- Toggles / rollout items: {toggles}
- Carriers in scope: {carriers}
- Confirm store setup, carrier account state, and any packaging or automation prerequisites before demo or troubleshooting.

## Where to Find It
{navigation}

## Support Walkthrough
1. Open the relevant MCSL app area and confirm the store/account context is correct.
2. Reproduce the flow using the approved acceptance criteria and latest test cases.
3. Verify the expected system behaviour before checking downstream Shopify or carrier-side evidence.
4. Use request-log, label, automation, or fulfillment evidence when the issue depends on those paths.

## Expected Outcome
- {(ctx.ai_qa_summary or 'Use the approved acceptance criteria and test cases as the expected outcome reference.').strip()[:1200]}
- The feature should behave consistently with the approved card scope and release notes.

## Troubleshooting Notes
- Review the Trello card and approved test cases before demoing or triaging.
- Confirm carrier, settings, packaging, Shopify, and toggle prerequisites first.
- If this affects rates or checkout, verify request-log and automation-rule behaviour.
- If this affects fulfillment or tracking, verify both MCSL state and Shopify order state.
- Use the notes below for the latest approved feature details:

{(ctx.acceptance_criteria or ctx.card_description or 'No description available').strip()[:2500]}

## Limitations / Rollout Notes
- {(ctx.signoff_summary or 'No additional rollout notes recorded.').strip()[:1200]}

## References
- Trello: {ctx.card_url or 'N/A'}
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

## Release Details
- Release: {ctx.release_name or 'Latest'}
- Carriers: {carriers}
- Developed by: {', '.join(ctx.developer_names) if ctx.developer_names else 'PluginHive Engineering'}
- Tested by: {', '.join(ctx.tester_names) if ctx.tester_names else 'PluginHive QA'}
- Trello: {ctx.card_url or 'N/A'}
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


def render_pdf_bytes(title: str, markdown_text: str) -> bytes:
    try:
        from reportlab.lib.colors import HexColor
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer
    except ModuleNotFoundError as exc:
        raise RuntimeError("PDF rendering requires reportlab to be installed") from exc

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=0.7 * inch,
        rightMargin=0.7 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        title=title,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Heading1"],
        textColor=HexColor("#0f5c4d"),
        fontSize=20,
        leading=24,
        spaceAfter=10,
    )
    heading_style = ParagraphStyle(
        "DocHeading",
        parent=styles["Heading2"],
        textColor=HexColor("#113a5c"),
        fontSize=13,
        leading=16,
        spaceBefore=10,
        spaceAfter=6,
    )
    subheading_style = ParagraphStyle(
        "DocSubHeading",
        parent=styles["Heading3"],
        textColor=HexColor("#2b4c66"),
        fontSize=11.5,
        leading=14,
        spaceBefore=8,
        spaceAfter=4,
    )
    body_style = ParagraphStyle(
        "DocBody",
        parent=styles["BodyText"],
        fontSize=10.5,
        leading=14,
        textColor=HexColor("#1f2933"),
        spaceAfter=6,
    )
    meta_style = ParagraphStyle(
        "DocMeta",
        parent=styles["BodyText"],
        fontSize=9.5,
        leading=12,
        textColor=HexColor("#52606d"),
        spaceAfter=4,
    )
    bullet_style = ParagraphStyle(
        "DocBullet",
        parent=body_style,
        leftIndent=12,
        firstLineIndent=-8,
    )
    number_style = ParagraphStyle(
        "DocNumber",
        parent=body_style,
        leftIndent=14,
        firstLineIndent=-10,
    )

    story = [
        Paragraph(title, title_style),
        Paragraph(f"Generated on { _dt.datetime.now().strftime('%Y-%m-%d %H:%M') }", meta_style),
        HRFlowable(width="100%", thickness=1, color=HexColor("#d9e2ec")),
        Spacer(1, 0.12 * inch),
    ]
    for line in (markdown_text or "").splitlines():
        clean = line.strip()
        if not clean:
            story.append(Spacer(1, 0.08 * inch))
            continue
        if clean.startswith("# "):
            story.append(Paragraph(clean[2:].strip(), title_style))
            continue
        if clean.startswith("## "):
            story.append(Paragraph(clean[3:].strip(), heading_style))
            story.append(HRFlowable(width="100%", thickness=0.6, color=HexColor("#bcccdc")))
            story.append(Spacer(1, 0.04 * inch))
            continue
        if clean.startswith("### "):
            story.append(Paragraph(clean[4:].strip(), subheading_style))
            continue
        if clean.startswith("- "):
            story.append(Paragraph(f"• {clean[2:].strip()}", bullet_style))
            continue
        if re.match(r"^\d+\.\s+", clean):
            story.append(Paragraph(clean, number_style))
            continue
        story.append(Paragraph(clean, body_style))
    doc.build(story)
    return buf.getvalue()
