"""
pipeline/domain_validator.py — Domain validator for MCSL QA Pipeline.

Validates Trello card requirements and AC against the knowledge base using Claude.

Exports: validate_card, ValidationReport, VALIDATION_PROMPT
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from textwrap import dedent

import config
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ValidationReport:
    overall_status: str = "NEEDS_REVIEW"   # "PASS" | "NEEDS_REVIEW" | "FAIL"
    summary: str = ""
    requirement_gaps: list[str] = field(default_factory=list)
    ac_gaps: list[str] = field(default_factory=list)
    accuracy_issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    kb_insights: str = ""
    sources: list[str] = field(default_factory=list)
    error: str = ""


# ---------------------------------------------------------------------------
# Prompt constant
# ---------------------------------------------------------------------------

VALIDATION_PROMPT = dedent("""\
    You are a senior domain expert and QA lead for the MCSL (Multi-Carrier Shipping Labels)
    Shopify App built by PluginHive. The app supports multiple carriers: FedEx, UPS, DHL, USPS.

    The MCSL label flow: ORDERS tab → filter by Order ID → Order Summary → Generate Label button.
    Carrier accounts configured via: App Settings → Carriers → Add/Edit.

    A new Trello card has come in. Validate the card's requirements and acceptance criteria
    against the knowledge base before test cases are generated.

    Knowledge base context (retrieved for this feature):
    {context}

    ---
    Card Name: {card_name}

    Card Description / Requirements:
    {card_desc}

    Acceptance Criteria (if already written):
    {acceptance_criteria}
    ---

    Analyse carefully and respond in this EXACT JSON format (no extra text, no markdown fences):
    {{
      "overall_status": "PASS" | "NEEDS_REVIEW" | "FAIL",
      "summary": "<one sentence>",
      "requirement_gaps": [...],
      "ac_gaps": [...],
      "accuracy_issues": [...],
      "suggestions": [...],
      "kb_insights": "<key facts, constraints, known MCSL behaviours for this feature>"
    }}
""")


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------

def validate_card(
    card_name: str,
    card_desc: str,
    acceptance_criteria: str = "",
) -> ValidationReport:
    """Validate a Trello card's requirements against the MCSL knowledge base.

    Returns a ValidationReport. Never raises — returns ValidationReport with error
    field populated on any failure.
    """
    # 1. Guard: if no API key, return error report immediately (no exception)
    if not getattr(config, "ANTHROPIC_API_KEY", ""):
        return ValidationReport(error="ANTHROPIC_API_KEY not configured")

    # 2. Fetch RAG context — gracefully handle all failures
    context = ""
    sources = []
    try:
        from rag.vectorstore import search
        query = f"{card_name} {card_desc[:200]}"
        docs = search(query, k=5)
        context = "\n\n---\n\n".join(d.page_content for d in docs)
        sources = [d.metadata.get("source", "") for d in docs if d.metadata.get("source")]
    except Exception as exc:
        logger.warning("RAG search failed during validate_card: %s", exc)
        context = "Knowledge base unavailable."

    # 3. Build prompt and call Claude
    prompt = VALIDATION_PROMPT.format(
        context=context or "No context retrieved.",
        card_name=card_name,
        card_desc=card_desc or "(no description)",
        acceptance_criteria=acceptance_criteria or "(not yet written)",
    )
    try:
        llm = ChatAnthropic(
            model=config.CLAUDE_SONNET_MODEL,
            api_key=config.ANTHROPIC_API_KEY,
            temperature=0,
            max_tokens=1024,
        )
        response = llm.invoke([HumanMessage(content=prompt)])
        raw = response.content.strip()
        # Strip JSON fences Claude sometimes adds
        raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
        # Find JSON object in response
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        data = json.loads(m.group(0) if m else raw)
        return ValidationReport(
            overall_status=data.get("overall_status", "NEEDS_REVIEW"),
            summary=data.get("summary", ""),
            requirement_gaps=data.get("requirement_gaps", []),
            ac_gaps=data.get("ac_gaps", []),
            accuracy_issues=data.get("accuracy_issues", []),
            suggestions=data.get("suggestions", []),
            kb_insights=data.get("kb_insights", ""),
            sources=sources,
        )
    except Exception as exc:
        logger.error("validate_card failed: %s", exc)
        return ValidationReport(
            error=f"Validation failed: {exc}",
            sources=sources,
        )
