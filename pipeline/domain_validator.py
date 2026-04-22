"""
pipeline/domain_validator.py — Domain validator for MCSL QA Pipeline.

Validates Trello card requirements and AC against the knowledge base using Claude.

Exports: validate_card, apply_validation_fixes, ValidationReport, VALIDATION_PROMPT
"""
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

from pipeline.carrier_knowledge import carrier_prompt_block, carrier_research_context

logger = logging.getLogger(__name__)

_CONTEXT_LIMIT = 3800
_CARD_DESC_LIMIT = 2500
_AC_LIMIT = 2500
_LLM_TIMEOUT_SECONDS = int(os.environ.get("MCSL_LLM_TIMEOUT_SECONDS", "90"))


def _compact_text(text: str, limit: int) -> str:
    cleaned_lines = [re.sub(r"\s+", " ", line).strip() for line in (text or "").splitlines()]
    compact = "\n".join(line for line in cleaned_lines if line)
    return compact[:limit]


def _compact_context(text: str, limit: int) -> str:
    if not (text or "").strip():
        return ""
    seen: set[str] = set()
    kept: list[str] = []
    total = 0
    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        next_total = total + len(line) + (1 if kept else 0)
        if next_total > limit:
            remaining = limit - total
            if remaining > 40:
                kept.append(line[:remaining])
            break
        kept.append(line)
        total = next_total
    return "\n".join(kept)


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


def _make_llm():
    from langchain_anthropic import ChatAnthropic

    return ChatAnthropic(
        model=config.CLAUDE_SONNET_MODEL,
        api_key=config.ANTHROPIC_API_KEY,
        temperature=0,
        max_tokens=900,
        default_request_timeout=_LLM_TIMEOUT_SECONDS,
    )


def _basic_fallback_validation(
    card_name: str,
    card_desc: str,
    acceptance_criteria: str,
    *,
    error: str = "",
    sources: list[str] | None = None,
) -> "ValidationReport":
    """Deterministic fallback when model-based validation is unavailable."""
    text = f"{card_name}\n{card_desc}\n{acceptance_criteria}".lower()
    ac_lines = [
        line.strip(" -\t")
        for line in (acceptance_criteria or card_desc or "").splitlines()
        if line.strip()
    ]

    requirement_gaps: list[str] = []
    ac_gaps: list[str] = []
    accuracy_issues: list[str] = []
    suggestions: list[str] = []

    if "acceptance criteria" not in text and len(ac_lines) < 2:
        requirement_gaps.append("Acceptance criteria section is missing or too short.")
    if "no impact" not in text and "regression" not in text:
        ac_gaps.append("Add a regression scenario confirming other document flows remain unaffected.")
    if "multiple" not in text:
        ac_gaps.append("Add coverage for multi-product shipments with different Country of Origin values.")
    if "single" not in text and "individual product" not in text:
        ac_gaps.append("Add a single-product baseline scenario.")
    if "product level" not in text:
        accuracy_issues.append("The card should clearly state that COO must be passed at product level, not shipment level.")
    if "cn22" in text and "carrier" in text and "no impact on other document types or carriers" not in text:
        suggestions.append("Clarify non-impact expectations for other document types and carriers.")

    overall_status = "PASS"
    if accuracy_issues:
        overall_status = "FAIL"
    elif requirement_gaps or ac_gaps or suggestions:
        overall_status = "NEEDS_REVIEW"

    summary = {
        "PASS": "The card looks testable and scoped correctly.",
        "NEEDS_REVIEW": "The card is understandable but needs clearer validation/regression coverage.",
        "FAIL": "The card has correctness issues that should be fixed before QA planning.",
    }[overall_status]

    return ValidationReport(
        overall_status=overall_status,
        summary=summary,
        requirement_gaps=requirement_gaps,
        ac_gaps=ac_gaps,
        accuracy_issues=accuracy_issues,
        suggestions=suggestions or ["Review and refine the AC if domain validation is unavailable."],
        kb_insights="Fallback validation was used because the model/RAG validator did not return a reliable structured response.",
        sources=sources or [],
        error=error,
    )


def _extract_first_json_object(raw: str) -> dict:
    """Best-effort extraction of the first JSON object from model output."""
    cleaned = re.sub(r"```(?:json)?", "", raw or "").strip().rstrip("`").strip()
    cleaned = (
        cleaned.replace("“", '"')
        .replace("”", '"')
        .replace("’", "'")
        .replace("‘", "'")
    )
    if not cleaned:
        raise ValueError("Empty validator response")

    start = cleaned.find("{")
    if start == -1:
        raise ValueError("No JSON object found in validator response")

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
                candidate = cleaned[start : idx + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    # Common model mistake: trailing commas before } or ]
                    repaired = re.sub(r",(\s*[}\]])", r"\1", candidate)
                    return json.loads(repaired)
    raise ValueError("No complete JSON object found in validator response")


def _normalise_validation_error(exc: Exception) -> str:
    text = str(exc).strip()
    if not text:
        return "Validator did not return a reliable structured response."
    if "No complete JSON object found in validator response" in text:
        return "Validator returned malformed JSON; fallback validation was used."
    if "No JSON object found in validator response" in text:
        return "Validator did not return JSON; fallback validation was used."
    if "Empty validator response" in text:
        return "Validator returned an empty response; fallback validation was used."
    return f"Validation fallback used: {text}"


def _parse_failure_validation_report(
    raw_output: str,
    *,
    error: str,
    sources: list[str] | None = None,
) -> "ValidationReport":
    """Return a FedEx-style degraded validation result on parse failure."""
    summary = (raw_output or "").strip()
    summary = re.sub(r"```(?:json)?", "", summary).strip().rstrip("`").strip()
    if summary:
        try:
            parsed = json.loads(summary)
            if isinstance(parsed, dict):
                summary = str(parsed.get("summary") or "").strip()
        except Exception:
            match = re.search(r'"summary"\s*:\s*"([^"]+)"', summary)
            if match:
                summary = match.group(1).strip()
    if not summary:
        summary = "Validation could not be parsed reliably. Review the card manually."
    return ValidationReport(
        overall_status="NEEDS_REVIEW",
        summary=summary[:300],
        kb_insights="Validation output could not be parsed into structured JSON; manual review is recommended.",
        sources=sources or [],
        error=error,
    )


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

    Carrier scope guidance:
    {carrier_scope}

    Interpretation rule:
    - If no carrier is explicitly named in the card, validate it as a generic MCSL platform behaviour first.
    - Only require carrier-specific expectations when the card or retrieved context clearly supports them.

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

VALIDATION_FIX_PROMPT = dedent("""\
    You are a senior domain expert for the MCSL Shopify app.

    Rewrite the acceptance criteria below using the validation report.

    Rules:
    - Keep the existing markdown structure when possible.
    - Fix accuracy issues and fill requirement/AC gaps.
    - Preserve correct details already present.
    - Keep all scenarios testable through the MCSL app/UI/API flow.
    - Do not invent unsupported carrier rules.
    - Do not add mobile / responsive / viewport scenarios.

    Card Name:
    {card_name}

    Current Acceptance Criteria:
    {acceptance_criteria}

    Validation Summary:
    {summary}

    Requirement Gaps:
    {requirement_gaps}

    AC Gaps:
    {ac_gaps}

    Accuracy Issues:
    {accuracy_issues}

    Suggestions:
    {suggestions}

    Return ONLY the revised acceptance criteria markdown.
""")

VALIDATION_JSON_REPAIR_PROMPT = dedent("""\
    Convert the validator output below into valid JSON only.

    Rules:
    - Return exactly one valid JSON object.
    - Do not add markdown fences.
    - Preserve the original meaning.
    - Use this schema exactly:
      {{
        "overall_status": "PASS" | "NEEDS_REVIEW" | "FAIL",
        "summary": "<one sentence>",
        "requirement_gaps": [...],
        "ac_gaps": [...],
        "accuracy_issues": [...],
        "suggestions": [...],
        "kb_insights": "<key facts>"
      }}

    Validator output:
    {raw_output}
""")

VALIDATION_MINIMAL_RETRY_PROMPT = dedent("""\
    You are a QA domain validator for the MCSL Shopify app.

    Return ONLY one valid JSON object in this exact schema:
    {{
      "overall_status": "PASS" | "NEEDS_REVIEW" | "FAIL",
      "summary": "<one sentence>",
      "requirement_gaps": [],
      "ac_gaps": [],
      "accuracy_issues": [],
      "suggestions": [],
      "kb_insights": "<short facts>"
    }}

    Card Name: {card_name}
    Card Description: {card_desc}
    Acceptance Criteria: {acceptance_criteria}
    Carrier scope: {carrier_scope}
""")


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------

def validate_card(
    card_name: str,
    card_desc: str,
    acceptance_criteria: str = "",
    research_context: str = "",
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
        docs = search(query, k=4)
        context = "\n\n---\n\n".join(d.page_content[:900] for d in docs[:4])
        sources = [d.metadata.get("source", "") for d in docs if d.metadata.get("source")]
    except Exception as exc:
        logger.warning("RAG search failed during validate_card: %s", exc)
        context = "Knowledge base unavailable."

    try:
        _carrier_ctx = carrier_research_context(card_name, card_desc, acceptance_criteria)
        if _carrier_ctx:
            context = f"{_carrier_ctx}\n\n---\n\n{context}" if context else _carrier_ctx
    except Exception as exc:
        logger.warning("Carrier research context failed during validate_card: %s", exc)

    # 3. Build prompt and call Claude
    merged_context = context or ""
    if research_context:
        merged_context = (
            f"Requirement research context:\n{research_context[:_CONTEXT_LIMIT]}\n\n---\n\n{merged_context}"
            if merged_context
            else research_context[:_CONTEXT_LIMIT]
        )

    _compact_card_name = _compact_text(card_name or "", 240) or "(untitled card)"
    _compact_card_desc = _compact_text(card_desc or "(no description)", _CARD_DESC_LIMIT)
    _compact_ac = _compact_text(acceptance_criteria or "(not yet written)", _AC_LIMIT)
    _compact_context_text = _compact_context(merged_context or "No context retrieved.", _CONTEXT_LIMIT)
    _compact_carrier_scope = _compact_context(
        carrier_prompt_block(card_name, card_desc, acceptance_criteria),
        1200,
    ) or "Generic MCSL platform scope."

    prompt = VALIDATION_PROMPT.format(
        context=_compact_context_text,
        carrier_scope=_compact_carrier_scope,
        card_name=_compact_card_name,
        card_desc=_compact_card_desc,
        acceptance_criteria=_compact_ac,
    )
    try:
        llm = _make_llm()
        response = llm.invoke([HumanMessage(content=prompt)])
        raw = _normalise_model_text(getattr(response, "content", response))
        try:
            data = _extract_first_json_object(raw)
        except Exception:
            try:
                repair_resp = llm.invoke([
                    HumanMessage(content=VALIDATION_JSON_REPAIR_PROMPT.format(raw_output=raw[:4000]))
                ])
                repaired_raw = _normalise_model_text(getattr(repair_resp, "content", repair_resp))
                data = _extract_first_json_object(repaired_raw)
            except Exception:
                minimal_prompt = VALIDATION_MINIMAL_RETRY_PROMPT.format(
                    card_name=_compact_card_name,
                    card_desc=_compact_text(card_desc or "(no description)", 1200),
                    acceptance_criteria=_compact_text(acceptance_criteria or "(not yet written)", 1200),
                    carrier_scope=_compact_context(_compact_carrier_scope, 500),
                )
                try:
                    retry_resp = llm.invoke([HumanMessage(content=minimal_prompt)])
                    retry_raw = _normalise_model_text(getattr(retry_resp, "content", retry_resp))
                    data = _extract_first_json_object(retry_raw)
                except Exception as parse_exc:
                    logger.info("validate_card parse fallback used for '%s': %s", card_name, parse_exc)
                    return _parse_failure_validation_report(
                        raw,
                        error=_normalise_validation_error(parse_exc),
                        sources=sources,
                    )
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
        logger.info("validate_card fallback used for '%s': %s", card_name, exc)
        return _basic_fallback_validation(
            card_name=card_name,
            card_desc=card_desc,
            acceptance_criteria=acceptance_criteria,
            error=_normalise_validation_error(exc),
            sources=sources,
        )


def apply_validation_fixes(
    card_name: str,
    acceptance_criteria: str,
    report: ValidationReport,
    research_context: str = "",
) -> str:
    """Rewrite AC using the validation report findings."""
    if not getattr(config, "ANTHROPIC_API_KEY", ""):
        raise RuntimeError("ANTHROPIC_API_KEY not configured")

    prompt = VALIDATION_FIX_PROMPT.format(
        card_name=card_name,
        acceptance_criteria=acceptance_criteria or "(no AC yet)",
        summary=report.summary or "(no summary)",
        requirement_gaps="\n".join(f"- {item}" for item in (report.requirement_gaps or [])) or "- None",
        ac_gaps="\n".join(f"- {item}" for item in (report.ac_gaps or [])) or "- None",
        accuracy_issues="\n".join(f"- {item}" for item in (report.accuracy_issues or [])) or "- None",
        suggestions="\n".join(f"- {item}" for item in (report.suggestions or [])) or "- None",
    )
    if research_context:
        prompt = f"{prompt}\n\nRequirement Research Context:\n{research_context[:2000]}"
    from langchain_anthropic import ChatAnthropic

    llm = ChatAnthropic(
        model=config.CLAUDE_SONNET_MODEL,
        api_key=config.ANTHROPIC_API_KEY,
        temperature=0,
        max_tokens=2048,
    )
    response = llm.invoke([HumanMessage(content=prompt)])
    return _normalise_model_text(getattr(response, "content", response)) or acceptance_criteria
