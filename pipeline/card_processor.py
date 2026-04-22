"""card_processor.py — Trello card AC text extractor + QA test case generation.

Original contract: get_ac_text(trello_card_url: str) -> tuple[str, str]
Returns (card_name, ac_text). Returns ("", "") on any failure or missing credentials.

Extended (07-01): generate_acceptance_criteria, generate_test_cases,
write_test_cases_to_card, format_qa_comment, parse_test_cases_to_rows, TestCaseRow
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import urllib.request
from dataclasses import dataclass, field as dc_field
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

import config
from dotenv import load_dotenv
try:
    from langchain_anthropic import ChatAnthropic
except Exception:
    class ChatAnthropic:  # type: ignore[override]
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def invoke(self, messages):
            raise RuntimeError("langchain_anthropic is not installed")

try:
    from langchain_core.messages import HumanMessage
except Exception:
    class HumanMessage:  # type: ignore[override]
        def __init__(self, content: str):
            self.content = content

# Explicit dotenv path — established pattern from Phase 1 config.py
load_dotenv(Path(__file__).parent.parent / ".env")

logger = logging.getLogger(__name__)

_TRELLO_API_BASE = "https://api.trello.com/1"
_DEFAULT_REVIEW_STATE: dict[str, object] = {
    "needs_revision": False,
    "issues": [],
    "rewrite_instructions": [],
}
_REVIEW_STATE = threading.local()
_LLM_TIMEOUT_SECONDS = int(os.environ.get("MCSL_LLM_TIMEOUT_SECONDS", "90"))


def _make_llm(
    model: str | None = None,
    *,
    temperature: float = 0.3,
    max_tokens: int = 2048,
):
    return ChatAnthropic(
        model=model or config.CLAUDE_SONNET_MODEL,
        api_key=config.ANTHROPIC_API_KEY,
        temperature=temperature,
        max_tokens=max_tokens,
        default_request_timeout=_LLM_TIMEOUT_SECONDS,
    )


def _set_last_ac_review(data: dict[str, object]) -> None:
    _REVIEW_STATE.last_ac_review = dict(data)


def _set_last_tc_review(data: dict[str, object]) -> None:
    _REVIEW_STATE.last_tc_review = dict(data)


def _get_last_review(attr: str) -> dict[str, object]:
    current = getattr(_REVIEW_STATE, attr, None)
    if not current:
        return dict(_DEFAULT_REVIEW_STATE)
    return dict(current)


def _extract_card_id(trello_url: str) -> str:
    """Extract the short card ID from a Trello card URL.

    Handles: https://trello.com/c/{card_id}/...  and  https://trello.com/c/{card_id}
    Returns empty string if URL does not match expected pattern.
    """
    match = re.search(r"/c/([^/?#]+)", trello_url)
    return match.group(1) if match else ""


def get_ac_text(trello_card_url: str) -> tuple[str, str]:
    """Fetch card name and AC text from a Trello card URL.

    Returns (card_name, ac_text).
    Returns ("", "") if:
      - TRELLO_API_KEY or TRELLO_TOKEN environment variables are missing
      - The URL does not contain a recognisable card ID
      - The Trello API request fails for any reason
    """
    api_key = os.environ.get("TRELLO_API_KEY", "")
    token   = os.environ.get("TRELLO_TOKEN",   "")

    if not api_key or not token:
        return ("", "")

    card_id = _extract_card_id(trello_card_url)
    if not card_id:
        return ("", "")

    url = f"{_TRELLO_API_BASE}/cards/{card_id}?fields=name,desc&key={api_key}&token={token}"

    try:
        with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310
            data: dict = json.loads(resp.read())
        return (data.get("name", ""), data.get("desc", ""))
    except Exception:  # noqa: BLE001
        return ("", "")


# ---------------------------------------------------------------------------
# TestCaseRow dataclass
# ---------------------------------------------------------------------------

@dataclass
class TestCaseRow:
    si_no: int = 0
    epic: str = ""
    scenario: str = ""
    description: str = ""   # Given/When/Then
    comments: str = ""
    priority: str = "Medium"
    details: str = ""
    pass_fail: str = ""
    release: str = ""


# ---------------------------------------------------------------------------
# Prompt constants
# ---------------------------------------------------------------------------

AC_WRITER_PROMPT = """\
You are a senior QA lead for the MCSL (Multi-Carrier Shipping Labels) Shopify App by PluginHive.
The app supports FedEx, UPS, DHL, USPS, and other carriers.
Navigation: ORDERS tab flow, App Settings → Carriers → Add/Edit.
Never write ACs for mobile viewports.

Work research-first, not card-text-first.
Before writing the final AC, ground yourself in the structured brief below:
- card type
- linked references
- customer issue or merchant-impact signals
- toggle / feature-flag prerequisites
- known prerequisites and risks
- MCSL source priority

Structured brief:
{generation_brief}

Research context:
{research_context}

Raw feature request:
{raw_request}

Developer / QA comments:
{comments_context}

Write Acceptance Criteria in this format:
### Acceptance Criteria
- AC1: [specific testable criterion]
- AC2: ...

Each AC must be testable via the MCSL app UI.
"""

TEST_CASE_PROMPT = """\
You are a senior QA engineer for the MCSL (Multi-Carrier Shipping Labels) Shopify App by PluginHive.
The app supports FedEx, UPS, DHL, USPS, and other carriers.
Navigation: ORDERS tab flow, App Settings → Carriers → Add/Edit.

Work from real MCSL behaviour, not generic shipping assumptions.
Use the carrier scope, QA knowledge, automation context, code context, and retrospective QA learnings when they help.
Do not write mobile / responsive / viewport test cases.

IMPORTANT: Use EXACTLY this format for each test case:
### TC-{{n}}: {{scenario title}}
**Type:** Positive | Negative | Edge Case
**Priority:** High | Medium | Low
**Preconditions:** {{clear setup needed before starting}}
**Steps:**
Given {{precondition}}
When {{action}}
And {{additional action if needed}}
Then {{expected result}}

Rules:
- Write at least 4 useful test cases unless the card is extremely narrow.
- Include a balanced mix of Positive / Negative / Edge coverage.
- Make Preconditions explicit for setup such as carrier config, product data, packaging settings, order state, Shopify state, request-log validation, or toggle enablement.
- Keep steps executable in the MCSL app, Shopify Admin, or API flow where relevant.
- Reuse exact app/navigation terms when possible.
- When source code context is provided, align with real field names, validations, service mapping, and error handling.
- When Trello comments are provided, incorporate rollout notes, toggle details, and implementation constraints from them.
- When past QA feedback is provided, cover the gaps that were previously missed.

---
Feature Card: {card_name}

Card Description / Acceptance Criteria:
{card_desc}
{dev_comments_section}
{carrier_context_section}
{rag_context_section}
{code_context_section}
{feedback_context_section}
Current AC / user story text:
{ac_text}
"""

TEST_CASE_REVIEW_PROMPT = """\
You are reviewing generated QA test cases for the MCSL Shopify App.

Return ONLY JSON in this exact shape:
{{
  "needs_revision": true | false,
  "issues": ["<short issue>"],
  "rewrite_instructions": ["<short concrete instruction>"]
}}

Review for:
- missing Positive / Negative / Edge coverage
- fewer than 4 useful test cases
- vague or untestable steps / expected results
- missing prerequisites
- duplicate or overlapping scenarios
- missing important AC coverage
- invalid formatting against the required TC template
- mobile / responsive / viewport cases that should not exist

Feature Card: {card_name}

Card Description / Acceptance Criteria:
{card_desc}
{supporting_context}

Generated test cases:
{test_cases_markdown}
"""

TEST_CASE_REWRITE_PROMPT = """\
Revise the QA test cases below using the review findings.

Rules:
- Keep the exact TC format:
  `### TC-{{n}}`, `**Type:**`, `**Priority:**`, `**Preconditions:**`, `**Steps:**`
- Keep steps explicit and testable
- Remove duplicates
- Ensure a useful mix of Positive / Negative / Edge cases
- Do not add mobile / responsive / viewport tests

Feature Card: {card_name}

Card Description / Acceptance Criteria:
{card_desc}
{supporting_context}

Review findings:
{review_summary}

Current test cases:
{test_cases_markdown}

Return ONLY the revised test cases markdown.
"""

REGENERATE_PROMPT = """\
You previously generated these test cases for the feature below.
The reviewer has provided feedback. Update the test cases accordingly.

Card Name: {card_name}
Card Description:
{card_desc}

Previous test cases:
{previous_test_cases}

Reviewer feedback:
{feedback}

Generate the updated test cases in the SAME format.
Address all feedback points. Keep unaffected test cases intact.

Keep the exact TC format:
`### TC-{{n}}`, `**Type:**`, `**Priority:**`, `**Preconditions:**`, `**Steps:**`
"""

AC_REVIEW_PROMPT = """\
You are reviewing generated Acceptance Criteria for the MCSL Shopify App.

Return ONLY JSON in this exact shape:
{{
  "needs_revision": true | false,
  "issues": ["<short issue>"],
  "rewrite_instructions": ["<short concrete instruction>"]
}}

Review for:
- duplicate or overlapping scenarios
- vague expected results that are not testable
- missing prerequisites or setup assumptions
- unsupported claims not grounded in the structured brief or research
- missing regression or customer-impact scenarios for bug-style requests
- missing toggle prerequisites when a toggle or feature flag is involved

Structured brief:
{generation_brief}

Research context:
{research_context}

Generated AC draft:
{ac_markdown}
"""

AC_REWRITE_PROMPT = """\
Revise the Acceptance Criteria markdown below using the review findings.

Rules:
- Keep the same markdown structure
- Remove duplicates and merge overlaps
- Make expected outcomes explicit and testable
- Add missing prerequisites where needed
- Do not invent unsupported carrier or app rules
- Preserve useful references already present

Structured brief:
{generation_brief}

Research context:
{research_context}

Review findings:
{review_summary}

Current AC draft:
{ac_markdown}

Return ONLY the revised AC markdown.
"""


# ---------------------------------------------------------------------------
# AC brief helpers
# ---------------------------------------------------------------------------

def _extract_urls(text: str) -> list[str]:
    if not text:
        return []
    seen: set[str] = set()
    urls: list[str] = []
    for match in re.finditer(r"https?://[^\s)>]+", text):
        url = match.group(0).rstrip(".,)")
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def _friendly_ref(url: str) -> str:
    host = urlparse(url).netloc.lower().replace("www.", "")
    if "trello" in host:
        return "Trello"
    if "shopify" in host:
        return "Shopify"
    if "pluginhive" in host:
        return "PluginHive"
    if "zendesk" in host:
        return "Zendesk"
    if "fedex" in host:
        return "FedEx"
    if "ups" in host:
        return "UPS"
    if "dhl" in host:
        return "DHL"
    if "usps" in host:
        return "USPS"
    return host or "reference"


def _classify_card_type(raw_request: str, research_context: str, comments_context: str = "") -> str:
    text = f"{raw_request}\n{research_context}\n{comments_context}".lower()
    if any(k in text for k in ("zendesk", "customer issue", "merchant issue", "support", "bug", "fix", "regression")):
        return "bug_fix_or_customer_issue"
    if any(k in text for k in ("toggle", "feature flag", "rollout", "enable on store")):
        return "toggle_or_rollout_change"
    if any(k in text for k in ("rate", "checkout", "service availability", "shipping rate")):
        return "rates_or_checkout_behaviour"
    if any(k in text for k in ("customs", "commercial invoice", "cn22", "country of origin", "hs code")):
        return "customs_or_document_behaviour"
    if any(k in text for k in ("carrier", "credentials", "account", "service mapping")):
        return "carrier_or_configuration_change"
    return "new_feature_or_general_change"


def _extract_prerequisites(
    raw_request: str,
    research_context: str,
    checklists: list[dict],
    comments_context: str = "",
) -> list[str]:
    text = f"{raw_request}\n{research_context}\n{comments_context}"
    prerequisites: list[str] = []

    try:
        from pipeline.slack_client import detect_toggles

        toggles = detect_toggles(raw_request, "", f"{research_context}\n{comments_context}")
    except Exception:
        toggles = []

    if toggles:
        prerequisites.append("Feature toggle(s) may need store enablement before QA: " + ", ".join(toggles))

    lower = text.lower()
    if "zendesk" in lower or "customer issue" in lower:
        prerequisites.append("Review the linked customer/support issue and preserve the real broken-vs-fixed behavior.")
    if any(k in lower for k in ("generate label", "label generation", "manual label")):
        prerequisites.append("Requires a valid store, carrier setup, and an order state that supports label generation.")
    if any(k in lower for k in ("customs", "commercial invoice", "cn22", "hs code", "country of origin")):
        prerequisites.append("Requires product-level customs data and document verification for the affected shipment flow.")
    if any(k in lower for k in ("rate", "checkout")):
        prerequisites.append("Requires a reproducible checkout or rate-request scenario with matching cart and address data.")
    if any(k in lower for k in ("pickup", "schedule pickup")):
        prerequisites.append("Requires a labeled shipment/order before pickup verification.")
    if any(k in lower for k in ("packaging", "packing method", "dimensions", "weight")):
        prerequisites.append("Packaging scenarios require explicit packaging method, dimensions, and weight setup.")

    for checklist in (checklists or [])[:3]:
        name = (checklist.get("name") or "").strip()
        items = [i.get("name", "").strip() for i in checklist.get("items", []) if i.get("name")]
        if name or items:
            preview = ", ".join(items[:3])
            prerequisites.append(f"Checklist context '{name}': {preview}".strip(": "))

    deduped: list[str] = []
    seen: set[str] = set()
    for item in prerequisites:
        norm = item.lower()
        if item and norm not in seen:
            seen.add(norm)
            deduped.append(item)
    return deduped[:8]


def _build_generation_brief(
    raw_request: str,
    attachments: list[dict],
    checklists: list[dict],
    research_context: str,
    comments_context: str,
) -> str:
    urls: list[str] = []
    seen_urls: set[str] = set()
    for url in _extract_urls(raw_request + "\n" + research_context + "\n" + comments_context):
        if url not in seen_urls:
            seen_urls.add(url)
            urls.append(url)
    for attachment in attachments or []:
        url = (attachment.get("url") or "").strip()
        if url and url not in seen_urls:
            seen_urls.add(url)
            urls.append(url)

    card_type = _classify_card_type(raw_request, research_context, comments_context)
    prerequisites = _extract_prerequisites(raw_request, research_context, checklists or [], comments_context)

    try:
        from pipeline.slack_client import detect_toggles

        toggles = detect_toggles(raw_request, "", f"{research_context}\n{comments_context}")
    except Exception:
        toggles = []

    lines = [
        "Research priority:",
        "1. Raw card request and linked references define the requested change.",
        "2. Requirement research provides MCSL carrier/platform, wiki, backlog, and app-behavior facts.",
        "3. Use only supported MCSL flows and avoid inventing carrier-only rules without evidence.",
        "",
        f"Card type: {card_type}",
    ]

    if toggles:
        lines.append("Detected toggles / feature flags: " + ", ".join(toggles))

    if comments_context.strip():
        lines.append("Developer / QA comment context is available and may contain rollout notes, toggle details, or clarifications.")

    if prerequisites:
        lines.append("")
        lines.append("Likely prerequisites:")
        lines.extend(f"- {item}" for item in prerequisites)

    if urls:
        lines.append("")
        lines.append("Linked references already detected:")
        lines.extend(f"- [{_friendly_ref(url)}] {url}" for url in urls[:12])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# New functions
# ---------------------------------------------------------------------------

def generate_acceptance_criteria(
    raw_request: str,
    model: str | None = None,
    attachments: list[dict] | None = None,
    checklists: list[dict] | None = None,
    research_context: str | None = None,
    comments_context: str | None = None,
) -> str:
    """Generate acceptance criteria for a feature request using Claude."""
    generation_brief = _build_generation_brief(
        raw_request=raw_request,
        attachments=attachments or [],
        checklists=checklists or [],
        research_context=research_context or "",
        comments_context=comments_context or "",
    )
    prompt = AC_WRITER_PROMPT.format(
        raw_request=raw_request,
        comments_context=comments_context or "None",
        generation_brief=generation_brief,
        research_context=research_context or "None",
    )
    llm = _make_llm(model=model, temperature=0.3, max_tokens=2048)
    response = llm.invoke([HumanMessage(content=prompt)])
    return _review_and_rewrite_ac(
        raw_request=raw_request,
        ac_markdown=response.content.strip(),
        generation_brief=generation_brief,
        research_context=research_context or "None",
        model=model,
    )


def generate_test_cases(card, model: str | None = None, ac_text: str | None = None) -> str:
    """Generate test cases for a TrelloCard using Claude.

    card is a TrelloCard — uses card.name, card.desc, card.comments.
    """
    comments = getattr(card, "comments", None) or []
    comments_text = "\n".join(comments) if comments else "None"
    _requirements_text = (ac_text or card.desc or "").strip()
    ac_text_str = _requirements_text or "(no AC yet)"
    dev_comments_section = _build_dev_comments_section(comments)

    try:
        from pipeline.carrier_knowledge import carrier_research_context

        carrier_context = carrier_research_context(card.name, _requirements_text, comments_text)
    except Exception:
        carrier_context = "Carrier scope unavailable."
    carrier_context_section = (
        f"\nCarrier / platform context:\n{carrier_context}\n"
        if carrier_context and carrier_context != "Carrier scope unavailable."
        else ""
    )
    rag_context_section = _build_rag_context_section(card.name, _requirements_text)
    code_context_section = _build_code_context_section(card.name, _requirements_text)
    feedback_context_section = _build_feedback_context_section(card.name, _requirements_text)

    ctx_parts = []
    if dev_comments_section:
        ctx_parts.append(f"{len(comments)} dev comment(s)")
    if carrier_context_section:
        ctx_parts.append("carrier context")
    if rag_context_section:
        ctx_parts.append("QA RAG")
    if code_context_section:
        ctx_parts.append("source code")
    if feedback_context_section:
        ctx_parts.append("QA feedback")
    logger.info(
        "Generating TCs for '%s' — context: %s",
        card.name,
        ", ".join(ctx_parts) if ctx_parts else "card desc only",
    )
    supporting_context = _build_tc_supporting_context(
        dev_comments_section=dev_comments_section,
        carrier_context_section=carrier_context_section,
        rag_context_section=rag_context_section,
        code_context_section=code_context_section,
        feedback_context_section=feedback_context_section,
        ac_text=ac_text_str,
    )

    prompt = TEST_CASE_PROMPT.format(
        card_name=card.name,
        card_desc=_requirements_text or "(no description)",
        dev_comments_section=dev_comments_section,
        carrier_context_section=carrier_context_section,
        rag_context_section=rag_context_section,
        code_context_section=code_context_section,
        feedback_context_section=feedback_context_section,
        ac_text=ac_text_str,
    )
    llm = _make_llm(model=model, temperature=0.3, max_tokens=2048)
    response = llm.invoke([HumanMessage(content=prompt)])
    return _review_and_rewrite_test_cases(
        card_name=card.name,
        card_desc=_requirements_text or "(no description)",
        test_cases_markdown=response.content.strip(),
        supporting_context=supporting_context,
        model=model,
    )


def _review_and_rewrite_ac(
    raw_request: str,
    ac_markdown: str,
    generation_brief: str,
    research_context: str,
    model: str | None = None,
) -> str:
    """Run a lightweight review pass on generated AC and rewrite if needed."""
    _set_last_ac_review(_DEFAULT_REVIEW_STATE)
    llm = _make_llm(model=model, temperature=0, max_tokens=1024)
    review_prompt = AC_REVIEW_PROMPT.format(
        generation_brief=generation_brief or "(no brief)",
        research_context=research_context or "None",
        ac_markdown=ac_markdown or "(empty)",
    )
    try:
        review_resp = llm.invoke([HumanMessage(content=review_prompt)])
        review_raw = re.sub(r"```(?:json)?", "", review_resp.content.strip()).strip().rstrip("`").strip()
        review_data = json.loads(review_raw)
    except Exception:
        return ac_markdown

    _set_last_ac_review({
        "needs_revision": bool(review_data.get("needs_revision")),
        "issues": review_data.get("issues", []) or [],
        "rewrite_instructions": review_data.get("rewrite_instructions", []) or [],
    })
    if not review_data.get("needs_revision"):
        return ac_markdown

    issues = review_data.get("issues", []) or []
    rewrite_instructions = review_data.get("rewrite_instructions", []) or []
    review_summary = "\n".join([f"- {item}" for item in [*issues, *rewrite_instructions] if item])
    if not review_summary:
        return ac_markdown

    rewrite_prompt = AC_REWRITE_PROMPT.format(
        generation_brief=generation_brief or "(no brief)",
        research_context=research_context or "None",
        review_summary=review_summary,
        ac_markdown=ac_markdown,
    )
    rewrite_resp = llm.invoke([HumanMessage(content=rewrite_prompt)])
    return rewrite_resp.content.strip()


def review_acceptance_criteria(
    raw_request: str,
    ac_markdown: str,
    model: str | None = None,
) -> dict[str, object]:
    """Review existing AC without rewriting it."""
    _set_last_ac_review(_DEFAULT_REVIEW_STATE)
    generation_brief = _build_generation_brief(
        raw_request=raw_request or "",
        attachments=[],
        checklists=[],
        research_context="",
        comments_context="",
    )
    llm = _make_llm(model=model, temperature=0, max_tokens=1024)
    review_prompt = AC_REVIEW_PROMPT.format(
        generation_brief=generation_brief or "(no brief)",
        research_context="None",
        ac_markdown=ac_markdown or "(empty)",
    )
    try:
        review_resp = llm.invoke([HumanMessage(content=review_prompt)])
        review_raw = re.sub(r"```(?:json)?", "", review_resp.content.strip()).strip().rstrip("`").strip()
        review_data = json.loads(review_raw)
    except Exception:
        review_data = dict(_DEFAULT_REVIEW_STATE)
    result = {
        "needs_revision": bool(review_data.get("needs_revision")),
        "issues": review_data.get("issues", []) or [],
        "rewrite_instructions": review_data.get("rewrite_instructions", []) or [],
    }
    _set_last_ac_review(result)
    return result


def get_last_ac_review() -> dict[str, object]:
    return _get_last_review("last_ac_review")


def _build_dev_comments_section(comments: list[str]) -> str:
    """Format Trello comments into a compact section for TC generation."""
    filtered = [comment.strip() for comment in comments if comment and comment.strip()]
    if not filtered:
        return ""
    lines = "\n".join(f"- {comment}" for comment in filtered[:10])
    return f"\nDeveloper / QA comments from Trello:\n{lines}\n"


def _build_rag_context_section(card_name: str, card_desc: str) -> str:
    """Query the QA knowledge base for relevant prior test coverage."""
    return _build_rag_context_section_cached(card_name or "", card_desc or "")


@lru_cache(maxsize=128)
def _build_rag_context_section_cached(card_name: str, card_desc: str) -> str:
    """Cached QA knowledge-base context for TC generation."""
    try:
        from rag.vectorstore import search

        query = f"{card_name} {card_desc or ''}".strip()[:500]
        docs = search(query, k=5)
        preferred = [doc for doc in docs if doc.metadata.get("doc_type") == "test_cases"]
        use_docs = preferred if preferred else docs
        if not use_docs:
            return ""
        snippets: list[str] = []
        for doc in use_docs[:3]:
            source = (
                doc.metadata.get("card_name")
                or doc.metadata.get("title")
                or doc.metadata.get("source")
                or doc.metadata.get("file_path")
                or "reference"
            )
            snippets.append(f"[From: {source}]\n{doc.page_content[:600]}")
        return (
            "\nSimilar past test cases from the QA knowledge base "
            "(use as style and coverage reference):\n"
            + "\n\n---\n".join(snippets)
            + "\n"
        )
    except Exception as exc:
        logger.debug("RAG context fetch failed (non-fatal): %s", exc)
        return ""


def _build_code_context_section(card_name: str, card_desc: str) -> str:
    """Query indexed MCSL code for automation, backend, and frontend context."""
    return _build_code_context_section_cached(card_name or "", card_desc or "")


@lru_cache(maxsize=128)
def _build_code_context_section_cached(card_name: str, card_desc: str) -> str:
    """Cached indexed code context for TC generation."""
    try:
        from rag.code_indexer import get_index_stats, search_code

        stats = get_index_stats()
        if stats.get("total", 0) == 0:
            return ""

        query = f"{card_name} {card_desc or ''}".strip()[:500]
        sections: list[str] = []
        for source_type, label, limit, snippet_limit in (
            ("automation", "Existing automation test patterns", 3, 600),
            ("backend", "Backend implementation", 3, 600),
            ("frontend", "Frontend implementation", 2, 500),
        ):
            if stats.get(source_type, 0) <= 0:
                continue
            docs = search_code(query, k=4, source_type=source_type)
            lines = []
            seen: set[str] = set()
            for doc in docs:
                file_path = doc.metadata.get("file_path", "")
                language = doc.metadata.get("language", "")
                if file_path and file_path not in seen:
                    seen.add(file_path)
                    fence = language or ""
                    lines.append(f"[{source_type}/{file_path}]\n```{fence}\n{doc.page_content[:snippet_limit]}\n```")
            if lines:
                sections.append(f"{label}:\n" + "\n\n".join(lines[:limit]))
        if not sections:
            return ""
        return "\nRelevant automation / code context:\n" + "\n\n---\n".join(sections) + "\n"
    except Exception as exc:
        logger.debug("Code context fetch failed (non-fatal): %s", exc)
        return ""


def _build_feedback_context_section(card_name: str, card_desc: str) -> str:
    """Optionally include retrospective QA learnings if that module exists."""
    return _build_feedback_context_section_cached(card_name or "", card_desc or "")


@lru_cache(maxsize=128)
def _build_feedback_context_section_cached(card_name: str, card_desc: str) -> str:
    """Cached retrospective QA learnings for TC generation."""
    try:
        from pipeline.qa_feedback import build_feedback_context

        context = build_feedback_context(f"{card_name} {card_desc[:300]}")
        if not context:
            return ""
        return f"\nPast QA feedback / learnings:\n{context}\n"
    except Exception as exc:
        logger.debug("Feedback context fetch skipped (non-fatal): %s", exc)
        return ""


def clear_tc_context_caches() -> None:
    _build_rag_context_section_cached.cache_clear()
    _build_code_context_section_cached.cache_clear()
    _build_feedback_context_section_cached.cache_clear()


def _build_tc_supporting_context(
    *,
    dev_comments_section: str = "",
    carrier_context_section: str = "",
    rag_context_section: str = "",
    code_context_section: str = "",
    feedback_context_section: str = "",
    ac_text: str = "",
) -> str:
    parts = [
        dev_comments_section.strip(),
        carrier_context_section.strip(),
        rag_context_section.strip(),
        code_context_section.strip(),
        feedback_context_section.strip(),
    ]
    if ac_text and ac_text.strip():
        parts.append(f"Current AC / user story text:\n{ac_text.strip()}")
    filtered = [part for part in parts if part]
    if not filtered:
        return ""
    return "\n\n".join(filtered)


def _review_and_rewrite_test_cases(
    card_name: str,
    card_desc: str,
    test_cases_markdown: str,
    supporting_context: str = "",
    model: str | None = None,
) -> str:
    """Run a lightweight review pass on generated test cases and rewrite if needed."""
    _set_last_tc_review(_DEFAULT_REVIEW_STATE)
    llm = _make_llm(model=model, temperature=0, max_tokens=1024)
    review_prompt = TEST_CASE_REVIEW_PROMPT.format(
        card_name=card_name,
        card_desc=card_desc,
        supporting_context=supporting_context or "",
        test_cases_markdown=test_cases_markdown or "(empty)",
    )
    try:
        review_resp = llm.invoke([HumanMessage(content=review_prompt)])
        review_raw = re.sub(r"```(?:json)?", "", review_resp.content.strip()).strip().rstrip("`").strip()
        review_data = json.loads(review_raw)
    except Exception:
        return test_cases_markdown

    _set_last_tc_review({
        "needs_revision": bool(review_data.get("needs_revision")),
        "issues": review_data.get("issues", []) or [],
        "rewrite_instructions": review_data.get("rewrite_instructions", []) or [],
    })
    if not review_data.get("needs_revision"):
        return test_cases_markdown

    issues = review_data.get("issues", []) or []
    rewrite_instructions = review_data.get("rewrite_instructions", []) or []
    review_summary = "\n".join([f"- {item}" for item in [*issues, *rewrite_instructions] if item])
    if not review_summary:
        return test_cases_markdown

    rewrite_prompt = TEST_CASE_REWRITE_PROMPT.format(
        card_name=card_name,
        card_desc=card_desc,
        supporting_context=supporting_context or "",
        review_summary=review_summary,
        test_cases_markdown=test_cases_markdown,
    )
    rewrite_resp = llm.invoke([HumanMessage(content=rewrite_prompt)])
    return rewrite_resp.content.strip()


def review_test_cases(
    card_name: str,
    card_desc: str,
    test_cases_markdown: str,
    supporting_context: str = "",
    model: str | None = None,
) -> dict[str, object]:
    """Review existing test cases without rewriting them."""
    _set_last_tc_review(_DEFAULT_REVIEW_STATE)
    llm = _make_llm(model=model, temperature=0, max_tokens=1024)
    review_prompt = TEST_CASE_REVIEW_PROMPT.format(
        card_name=card_name,
        card_desc=card_desc,
        supporting_context=supporting_context or "",
        test_cases_markdown=test_cases_markdown or "(empty)",
    )
    try:
        review_resp = llm.invoke([HumanMessage(content=review_prompt)])
        review_raw = re.sub(r"```(?:json)?", "", review_resp.content.strip()).strip().rstrip("`").strip()
        review_data = json.loads(review_raw)
    except Exception:
        review_data = dict(_DEFAULT_REVIEW_STATE)
    result = {
        "needs_revision": bool(review_data.get("needs_revision")),
        "issues": review_data.get("issues", []) or [],
        "rewrite_instructions": review_data.get("rewrite_instructions", []) or [],
    }
    _set_last_tc_review(result)
    return result


def get_last_tc_review() -> dict[str, object]:
    return _get_last_review("last_tc_review")


def regenerate_with_feedback(
    card,
    previous_test_cases: str,
    feedback: str,
    model: str | None = None,
    ac_text: str | None = None,
) -> str:
    """Regenerate test cases using explicit reviewer feedback."""
    _requirements_text = (ac_text or card.desc or "").strip()
    llm = _make_llm(model=model, temperature=0.3, max_tokens=2048)
    prompt = REGENERATE_PROMPT.format(
        card_name=card.name,
        card_desc=_requirements_text or "(no description)",
        previous_test_cases=previous_test_cases,
        feedback=feedback,
    )
    response = llm.invoke([HumanMessage(content=prompt)])
    return _review_and_rewrite_test_cases(
        card_name=card.name,
        card_desc=_requirements_text or "(no description)",
        test_cases_markdown=response.content.strip(),
        model=model,
    )


def format_qa_comment(
    card_name: str,
    test_cases_markdown: str,
    release: str = "",
    qa_name: str = "",
) -> str:
    """Format a FedEx-style grouped QA summary comment for Trello."""
    blocks = re.split(r"(?=^#{2,3}\s+TC-\d+)", test_cases_markdown, flags=re.MULTILINE)
    groups: dict[str, list[str]] = {"Positive": [], "Negative": [], "Edge": []}

    for block in blocks:
        block = block.strip()
        if not block or not re.match(r"^#{2,3}\s+TC-\d+", block):
            continue

        title_match = re.match(r"^#{2,3}\s+(TC-\d+)[:\s]+(.+)", block)
        tc_num = title_match.group(1) if title_match else "TC-?"
        tc_title = title_match.group(2).strip() if title_match else "Unknown"

        type_match = re.search(r"\*\*Type:\*\*\s*(Positive|Negative|Edge)", block, re.IGNORECASE)
        tc_type = type_match.group(1).capitalize() if type_match else "Positive"

        then_match = re.search(r"^Then (.+)$", block, re.MULTILINE | re.IGNORECASE)
        result = then_match.group(1).strip() if then_match else ""

        one_liner = f"• {tc_num}: {tc_title}"
        if result:
            one_liner += f" — {result}"

        groups.get(tc_type, groups["Positive"]).append(one_liner)

    release_str = f" ({release})" if release else ""
    lines = [f"📋 **QA Test Cases — {card_name}{release_str}**"]
    if qa_name:
        lines.append(f"_Prepared by: {qa_name}_")
    lines.append("")

    icons = {"Positive": "✅ Positive", "Negative": "❌ Negative", "Edge": "⚠️ Edge"}
    for tc_type, icon_label in icons.items():
        if groups[tc_type]:
            lines.append(f"**{icon_label}**")
            lines.extend(groups[tc_type])
            lines.append("")

    total = sum(len(v) for v in groups.values())
    lines.append(
        f"_Total: {total} cases — "
        f"{len(groups['Positive'])} positive · "
        f"{len(groups['Negative'])} negative · "
        f"{len(groups['Edge'])} edge_"
    )
    return "\n".join(lines)


def _get_qa_member_name(card_id: str, trello) -> str:
    """Best-effort lookup for the QA member assigned to a card."""
    try:
        from pipeline.bug_reporter import is_qa_name

        members = trello.get_card_members(card_id)
        for member in members:
            full_name = (member.get("fullName") or member.get("username") or "").strip()
            if full_name and is_qa_name(full_name):
                return full_name
    except Exception:
        pass
    return ""


def write_test_cases_to_card(
    card_id: str,
    test_cases: str,
    trello,
    release: str = "",
    card_name: str = "",
) -> None:
    """Post formatted test cases as a comment on the Trello card."""
    comment = format_qa_comment(
        card_name=card_name,
        test_cases_markdown=test_cases,
        release=release,
        qa_name=_get_qa_member_name(card_id, trello),
    )
    trello.add_comment(card_id, comment)


def parse_test_cases_to_rows(
    card_name: str,
    test_cases_markdown: str,
    epic: str = "",
    positive_only: bool = False,
) -> list[TestCaseRow]:
    """Parse test case markdown into a list of TestCaseRow objects."""
    rows = []
    tc_blocks = re.split(r"(?=^#{2,3}\s+TC-\d+)", test_cases_markdown, flags=re.MULTILINE)
    si = 1
    for block in tc_blocks:
        block = block.strip()
        if not block or not re.match(r"^#{2,3}\s+TC-\d+", block):
            continue
        title_match = re.match(r"^#{2,3}\s+TC-\d+[:\s]+(.+)", block)
        scenario = title_match.group(1).strip() if title_match else card_name

        # Extract type/priority
        tc_type = "Positive"
        priority = "Medium"
        type_match = re.search(r"\*\*Type:\*\*\s*(.+)", block)
        if type_match:
            tc_type = type_match.group(1).strip()
        priority_match = re.search(r"\*\*Priority:\*\*\s*(.+)", block)
        if priority_match:
            priority = priority_match.group(1).strip()

        if positive_only and "positive" not in tc_type.lower():
            continue

        preconditions_match = re.search(r"\*\*Preconditions?:\*\*\s*(.+?)(?:\n|$)", block, re.IGNORECASE)
        comments = preconditions_match.group(1).strip() if preconditions_match else ""

        gwt_parts = []
        in_steps = False
        for line in block.splitlines():
            stripped = line.strip()
            if re.match(r"\*\*Steps:\*\*", stripped, re.IGNORECASE):
                in_steps = True
                continue
            if in_steps and re.match(r"\*\*.+\*\*", stripped) and not re.match(
                r"^(Given|When|And|Then|But)\b", stripped, re.IGNORECASE
            ):
                break
            if re.match(r"^(Given|When|And|Then|But)\b", stripped, re.IGNORECASE):
                gwt_parts.append(stripped)
                in_steps = True
        description = "\n".join(gwt_parts) if gwt_parts else block[:200]

        rows.append(TestCaseRow(
            si_no=si,
            epic=epic or card_name,
            scenario=scenario,
            description=description,
            comments=comments,
            priority=priority,
            release="",
        ))
        si += 1
    return rows
