"""
pipeline/release_analyser.py — Cross-card release risk and conflict analysis.
Phase 07 Plan 02 — RQA-05

Exports: analyse_release, CardSummary, ReleaseAnalysis
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from textwrap import dedent

import config
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

_LLM_TIMEOUT_SECONDS = int(os.environ.get("MCSL_LLM_TIMEOUT_SECONDS", "90"))
@dataclass
class CardSummary:
    card_id: str
    card_name: str
    card_desc: str
    card_comments: list[str] = field(default_factory=list)
    card_labels: list[str] = field(default_factory=list)
    card_checklists: list[dict] = field(default_factory=list)

    def combined_text(self) -> str:
        checklist_text = "\n".join(
            f"{cl.get('name', '')}: "
            + ", ".join(
                item.get("name", "")
                for item in cl.get("items", [])
                if item.get("name")
            )
            for cl in (self.card_checklists or [])
        )
        return "\n".join(
            part for part in [
                self.card_name,
                self.card_desc,
                "\n".join(self.card_comments or []),
                " ".join(self.card_labels or []),
                checklist_text,
            ] if (part or "").strip()
        )


@dataclass
class ReleaseAnalysis:
    release_name: str = ""
    risk_level: str = "LOW"           # "LOW" | "MEDIUM" | "HIGH"
    risk_summary: str = ""
    conflicts: list[dict] = field(default_factory=list)
    ordering: list[dict] = field(default_factory=list)
    coverage_gaps: list[str] = field(default_factory=list)
    kb_context_summary: str = ""
    sources: list[str] = field(default_factory=list)
    error: str = ""


RELEASE_ANALYSIS_PROMPT = dedent("""\
    You are a senior QA lead and MCSL (Multi-Carrier Shipping Labels) Shopify App domain expert
    for PluginHive. The app supports FedEx, UPS, DHL, USPS, and other carriers.

    A release "{release_name}" contains the following cards:
    {cards_summary}

    Knowledge base context for this release area:
    {context}

    Analyse the release and respond in this EXACT JSON format (no extra text, no markdown fences):
    {{
      "risk_level": "LOW" | "MEDIUM" | "HIGH",
      "risk_summary": "<one sentence overall risk assessment>",
      "conflicts": [
        {{"cards": ["card name 1", "card name 2"], "area": "...", "description": "..."}}
      ],
      "ordering": [
        {{"position": 1, "card_name": "...", "reason": "..."}}
      ],
      "coverage_gaps": ["<area not covered by any card>"],
      "kb_context_summary": "<key MCSL domain facts relevant to this release>"
    }}
""")


def _normalise_model_text(content) -> str:
    """Flatten Anthropic/LangChain response content into plain text."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
                elif isinstance(item.get("content"), str):
                    parts.append(item["content"])
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part).strip()
    if isinstance(content, dict):
        text = content.get("text")
        if isinstance(text, str):
            return text.strip()
        inner = content.get("content")
        if isinstance(inner, str):
            return inner.strip()
    return str(content).strip()


def _basic_fallback_release_analysis(
    release_name: str,
    cards: list[CardSummary],
    *,
    context_available: bool,
    error: str = "",
    sources: list[str] | None = None,
) -> ReleaseAnalysis:
    """Deterministic release analysis when model-backed analysis is unavailable."""
    joined = "\n".join(c.combined_text() for c in cards).lower()
    risk_level = "LOW"
    coverage_gaps: list[str] = []

    if len(cards) >= 5:
        risk_level = "MEDIUM"
    if any(token in joined for token in ("label", "rate", "automation", "tracking", "customs", "fulfillment")):
        risk_level = "MEDIUM"
    if any(token in joined for token in ("toggle", "migration", "breaking", "regression", "carrier")) and len(cards) >= 2:
        risk_level = "HIGH"

    if "regression" not in joined:
        coverage_gaps.append("Regression coverage expectations are not explicit across the loaded cards.")
    if "multi" not in joined and "carrier" in joined:
        coverage_gaps.append("Check whether multi-carrier impact needs explicit validation.")

    ordering = [
        {
            "position": idx,
            "card_name": card.card_name,
            "reason": "Fallback ordering preserves the loaded release order until model-based analysis is available.",
        }
        for idx, card in enumerate(cards, start=1)
    ]
    summary = (
        "Fallback release analysis was used. Review card dependencies and regression scope before final sign-off."
    )
    kb_summary = (
        "Knowledge base context was available but model-backed release reasoning was unavailable."
        if context_available
        else "Knowledge base context was unavailable during fallback release analysis."
    )
    return ReleaseAnalysis(
        release_name=release_name,
        risk_level=risk_level,
        risk_summary=summary,
        conflicts=[],
        ordering=ordering,
        coverage_gaps=coverage_gaps,
        kb_context_summary=kb_summary,
        sources=sources or [],
        error=error,
    )


def analyse_release(release_name: str, cards: list[CardSummary]) -> ReleaseAnalysis:
    """Analyse a release for cross-card risks, conflicts, and ordering.

    Returns ReleaseAnalysis — never raises.
    """
    # Guard: empty cards
    if not cards:
        return ReleaseAnalysis(
            release_name=release_name,
            risk_level="LOW",
            error="Empty card list — no analysis performed.",
        )

    # Guard: no API key
    if not getattr(config, "ANTHROPIC_API_KEY", ""):
        return _basic_fallback_release_analysis(
            release_name,
            cards,
            context_available=False,
            error="ANTHROPIC_API_KEY not configured",
        )

    # Build combined query and fetch RAG context
    combined_query = " ".join(c.combined_text()[:300] for c in cards)
    k = min(6 * len(cards), 20)
    context = ""
    sources = []
    try:
        from rag.vectorstore import search
        docs = search(combined_query, k=k)
        context = "\n\n---\n\n".join(d.page_content for d in docs)
        sources = [d.metadata.get("source", "") for d in docs if d.metadata.get("source")]
    except Exception as exc:
        logging.warning("RAG search failed in analyse_release: %s", exc)
        context = "Knowledge base unavailable."

    # Build cards summary for prompt
    cards_summary = "\n".join(
        f"- [{c.card_id}] {c.combined_text()[:500]}" for c in cards
    )
    prompt = RELEASE_ANALYSIS_PROMPT.format(
        release_name=release_name,
        cards_summary=cards_summary,
        context=context or "No context retrieved.",
    )

    max_tokens = min(3000 + len(cards) * 400, 6000)
    try:
        llm = ChatAnthropic(
            model=config.CLAUDE_SONNET_MODEL,
            api_key=config.ANTHROPIC_API_KEY,
            temperature=0,
            max_tokens=max_tokens,
            default_request_timeout=_LLM_TIMEOUT_SECONDS,
        )
        response = llm.invoke([HumanMessage(content=prompt)])
        raw = _normalise_model_text(getattr(response, "content", response))
        raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        data = json.loads(m.group(0) if m else raw)
        return ReleaseAnalysis(
            release_name=release_name,
            risk_level=data.get("risk_level", "LOW"),
            risk_summary=data.get("risk_summary", ""),
            conflicts=data.get("conflicts", []),
            ordering=data.get("ordering", []),
            coverage_gaps=data.get("coverage_gaps", []),
            kb_context_summary=data.get("kb_context_summary", ""),
            sources=sources,
        )
    except Exception as exc:
        logging.warning("analyse_release fallback used: %s", exc)
        return _basic_fallback_release_analysis(
            release_name,
            cards,
            context_available=context != "Knowledge base unavailable.",
            error=f"Analysis failed: {exc}",
            sources=sources,
        )
