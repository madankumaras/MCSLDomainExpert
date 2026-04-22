"""Ticket diagnosis helper for MCSL customer issues and feature cards."""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from textwrap import dedent

import config
try:
    from langchain_core.messages import HumanMessage
except Exception:
    class HumanMessage:  # type: ignore[override]
        def __init__(self, content: str):
            self.content = content

from pipeline.carrier_knowledge import (
    carrier_prompt_block,
    carrier_research_context,
    detect_carrier_scope,
)

logger = logging.getLogger(__name__)
_LLM_TIMEOUT_SECONDS = int(os.environ.get("MCSL_LLM_TIMEOUT_SECONDS", "90"))


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
@dataclass
class TicketDiagnosis:
    issue_type: str = "unknown"
    carrier_scope: str = "generic"
    likely_root_cause: str = "unclear"
    confidence: str = "low"
    summary: str = ""
    evidence: list[str] = field(default_factory=list)
    next_checks: list[str] = field(default_factory=list)
    suggested_test_strategy: list[str] = field(default_factory=list)
    error: str = ""


DIAGNOSIS_PROMPT = dedent("""\
    You are a senior MCSL support engineer, QA lead, and domain expert.

    Diagnose this customer issue or feature card using MCSL domain knowledge, code context,
    and carrier guidance.

    Allowed root-cause categories:
    - generic_platform
    - carrier_setup
    - packaging_or_product_data
    - shopify_sync
    - request_or_label_api
    - code_defect
    - carrier_side
    - unclear

    Allowed issue types:
    - bug
    - feature
    - support_question
    - investigation

    Carrier guidance:
    {carrier_scope}

    Knowledge context:
    {domain_context}

    Code / automation context:
    {code_context}

    Ticket text:
    {ticket_text}

    Return EXACT JSON:
    {{
      "issue_type": "bug" | "feature" | "support_question" | "investigation",
      "carrier_scope": "generic" | "carrier_specific",
      "likely_root_cause": "generic_platform" | "carrier_setup" | "packaging_or_product_data" | "shopify_sync" | "request_or_label_api" | "code_defect" | "carrier_side" | "unclear",
      "confidence": "low" | "medium" | "high",
      "summary": "<short diagnosis summary>",
      "evidence": ["<fact or clue from context>"],
      "next_checks": ["<next thing to verify>"],
      "suggested_test_strategy": ["<how QA should approach testing this card>"]
    }}
""")

DIAGNOSIS_JSON_REPAIR_PROMPT = dedent("""\
    Convert the diagnosis output below into valid JSON only.

    Rules:
    - Return exactly one valid JSON object.
    - Do not add markdown fences.
    - Preserve the original meaning.
    - Use this schema exactly:
      {{
        "issue_type": "bug" | "feature" | "support_question" | "investigation",
        "carrier_scope": "generic" | "carrier_specific",
        "likely_root_cause": "generic_platform" | "carrier_setup" | "packaging_or_product_data" | "shopify_sync" | "request_or_label_api" | "code_defect" | "carrier_side" | "unclear",
        "confidence": "low" | "medium" | "high",
        "summary": "<short diagnosis summary>",
        "evidence": ["<fact or clue from context>"],
        "next_checks": ["<next thing to verify>"],
        "suggested_test_strategy": ["<how QA should approach testing this card>"]
      }}

    Diagnosis output:
    {raw_output}
""")

DIAGNOSIS_MINIMAL_RETRY_PROMPT = dedent("""\
    You are an MCSL QA diagnosis assistant.

    Return ONLY one valid JSON object in this exact schema:
    {{
      "issue_type": "bug" | "feature" | "support_question" | "investigation",
      "carrier_scope": "generic" | "carrier_specific",
      "likely_root_cause": "generic_platform" | "carrier_setup" | "packaging_or_product_data" | "shopify_sync" | "request_or_label_api" | "code_defect" | "carrier_side" | "unclear",
      "confidence": "low" | "medium" | "high",
      "summary": "<short diagnosis summary>",
      "evidence": [],
      "next_checks": [],
      "suggested_test_strategy": []
    }}

    Ticket text: {ticket_text}
    Carrier scope: {carrier_scope}
""")


def _extract_first_json_object(raw: str) -> dict:
    cleaned = re.sub(r"```(?:json)?", "", raw or "").strip().rstrip("`").strip()
    if not cleaned:
        raise ValueError("Empty diagnosis response")

    start = cleaned.find("{")
    if start == -1:
        raise ValueError("No JSON object found in diagnosis response")

    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(cleaned)):
        ch = cleaned[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(cleaned[start : idx + 1])
    raise ValueError("No complete JSON object found in diagnosis response")


def _basic_fallback_diagnosis(ticket_text: str, *, error: str = "") -> TicketDiagnosis:
    text = (ticket_text or "").lower()
    issue_type = "feature" if any(token in text for token in ("enhancement", "feature", "support for", "allow ")) else "bug"
    carrier_scope = "carrier_specific" if detect_carrier_scope(ticket_text).scope == "carrier_specific" else "generic"
    likely_root_cause = "request_or_label_api" if any(token in text for token in ("customs", "label", "api", "request")) else "generic_platform"
    evidence: list[str] = []
    next_checks: list[str] = []
    strategy: list[str] = []

    if "customs" in text:
        evidence.append("The ticket refers to customs-related shipment data or document behavior.")
        next_checks.append("Verify product-level customs values and generated customs documents for the active order.")
        strategy.append("Test both baseline and regression customs flows with single-product and multi-product shipments.")
    if "toggle" in text or "feature flag" in text:
        evidence.append("The ticket may depend on a toggle or rollout prerequisite.")
        next_checks.append("Confirm required toggles are enabled for the target store before QA execution.")
    if not evidence:
        evidence.append("Fallback diagnosis was used because the model response could not be parsed reliably.")
    if not next_checks:
        next_checks.append("Review card requirements, linked references, and the primary affected MCSL flow.")
    if not strategy:
        strategy.append("Validate the primary flow first, then run regression checks on nearby app behavior.")

    summary = (
        "Fallback diagnosis: review the primary MCSL flow and confirm prerequisites before deep investigation."
    )
    return TicketDiagnosis(
        issue_type=issue_type,
        carrier_scope=carrier_scope,
        likely_root_cause=likely_root_cause,
        confidence="low",
        summary=summary,
        evidence=evidence,
        next_checks=next_checks,
        suggested_test_strategy=strategy,
        error=error,
    )


def diagnose_ticket(ticket_text: str, model: str | None = None) -> TicketDiagnosis:
    detected_scope = detect_carrier_scope(ticket_text)

    if not getattr(config, "ANTHROPIC_API_KEY", ""):
        return TicketDiagnosis(error="ANTHROPIC_API_KEY not configured")

    domain_context = ""
    code_context = ""
    try:
        from rag.vectorstore import search

        docs = search(ticket_text, k=8)
        domain_context = "\n\n---\n\n".join(d.page_content for d in docs)
    except Exception as exc:
        logger.warning("Ticket diagnosis domain search failed: %s", exc)
        domain_context = "Knowledge base unavailable."

    try:
        carrier_context = carrier_research_context(ticket_text)
        if carrier_context:
            domain_context = f"{carrier_context}\n\n---\n\n{domain_context}" if domain_context else carrier_context
    except Exception as exc:
        logger.warning("Carrier research context failed in diagnose_ticket: %s", exc)

    try:
        from rag.code_indexer import search_code

        auto_docs = search_code(ticket_text, k=4, source_type="automation") or []
        be_docs = search_code(ticket_text, k=3, source_type="storepepsaas_server") or []
        fe_docs = search_code(ticket_text, k=3, source_type="storepepsaas_client") or []
        code_context = "\n\n---\n\n".join(d.page_content for d in (auto_docs + be_docs + fe_docs))
    except Exception as exc:
        logger.warning("Ticket diagnosis code search failed: %s", exc)
        code_context = "Code context unavailable."

    prompt = DIAGNOSIS_PROMPT.format(
        carrier_scope=carrier_prompt_block(ticket_text),
        domain_context=domain_context or "No context retrieved.",
        code_context=code_context or "No code context retrieved.",
        ticket_text=ticket_text.strip() or "(empty ticket)",
    )
    try:
        from langchain_anthropic import ChatAnthropic

        llm = ChatAnthropic(
            model=model or config.CLAUDE_SONNET_MODEL,
            api_key=config.ANTHROPIC_API_KEY,
            temperature=0,
            max_tokens=1200,
            default_request_timeout=_LLM_TIMEOUT_SECONDS,
        )
        response = llm.invoke([HumanMessage(content=prompt)])
        raw = _normalise_model_text(getattr(response, "content", response))
        try:
            data = _extract_first_json_object(raw)
        except Exception:
            try:
                repair_resp = llm.invoke([
                    HumanMessage(content=DIAGNOSIS_JSON_REPAIR_PROMPT.format(raw_output=raw[:4000]))
                ])
                data = _extract_first_json_object(
                    _normalise_model_text(getattr(repair_resp, "content", repair_resp))
                )
            except Exception:
                retry_resp = llm.invoke([
                    HumanMessage(
                        content=DIAGNOSIS_MINIMAL_RETRY_PROMPT.format(
                            ticket_text=(ticket_text or "(empty ticket)")[:1600],
                            carrier_scope=carrier_prompt_block(ticket_text),
                        )
                    )
                ])
                data = _extract_first_json_object(
                    _normalise_model_text(getattr(retry_resp, "content", retry_resp))
                )
        return TicketDiagnosis(
            issue_type=data.get("issue_type", "unknown"),
            carrier_scope=(
                "carrier_specific"
                if detected_scope.scope == "carrier_specific"
                else data.get("carrier_scope", "generic")
            ),
            likely_root_cause=data.get("likely_root_cause", "unclear"),
            confidence=data.get("confidence", "low"),
            summary=data.get("summary", ""),
            evidence=[
                *(
                    [f"Detected carrier context from card text/comments: {', '.join(profile.canonical_name for profile in detected_scope.carriers)}."]
                    if detected_scope.scope == "carrier_specific"
                    else []
                ),
                *(data.get("evidence", []) or []),
            ],
            next_checks=data.get("next_checks", []) or [],
            suggested_test_strategy=data.get("suggested_test_strategy", []) or [],
        )
    except Exception as exc:
        logger.warning("diagnose_ticket fallback used: %s", exc)
        return _basic_fallback_diagnosis(ticket_text, error=f"Diagnosis failed: {exc}")
