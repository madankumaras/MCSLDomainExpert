"""Requirement research helper for User Story / AC generation."""
from __future__ import annotations

import logging
import re
from functools import lru_cache

from pipeline.carrier_knowledge import carrier_research_context, detect_carrier_scope
from pipeline.carrier_request_registry import resolve_carrier_request_profile
from pipeline.locator_knowledge import load_runtime_locator_memory_context

logger = logging.getLogger(__name__)

_BACKLOG_LIST_NAMES = {"backlog", "product backlog", "planning backlog"}


def _clean_text(text: str, limit: int = 500) -> str:
    return re.sub(r"\s+", " ", text or "").strip()[:limit]


def _join_docs(docs: list, *, limit: int = 4, max_chars: int = 700) -> list[str]:
    chunks: list[str] = []
    for doc in docs[:limit]:
        source = (
            doc.metadata.get("title")
            or doc.metadata.get("source")
            or doc.metadata.get("file_path")
            or "unknown"
        )
        body = _clean_text(doc.page_content or "", max_chars)
        if not body:
            continue
        chunks.append(f"- [{source}]\n  {body}")
    return chunks


def _extract_issue_queries(request_text: str) -> list[str]:
    text = request_text or ""
    queries: list[str] = []
    seen: set[str] = set()

    for match in re.finditer(r"(?:zendesk[^0-9]{0,20}|#)?(\d{5,12})", text, re.IGNORECASE):
        ticket_id = match.group(1)
        if ticket_id not in seen:
            seen.add(ticket_id)
            queries.append(ticket_id)

    cleaned = _clean_text(re.sub(r"https?://\S+", " ", text), 180)
    if cleaned and cleaned.lower() not in seen:
        seen.add(cleaned.lower())
        queries.append(cleaned)
    return queries[:4]


def _customer_issue_summary(request_text: str) -> str:
    lower = (request_text or "").lower()
    if not any(token in lower for token in ("zendesk", "customer", "merchant", "support", "ticket", "issue", "bug", "fix")):
        return ""

    try:
        from rag.vectorstore import search_filtered

        findings: list[str] = []
        seen_sources: set[str] = set()
        for query in _extract_issue_queries(request_text):
            docs = search_filtered(query, k=4, source_type="wiki", category="Customer Issues & Support") or []
            for doc in docs:
                source = doc.metadata.get("source") or doc.metadata.get("title") or "wiki"
                if source in seen_sources:
                    continue
                seen_sources.add(source)
                findings.append(f"- Source: {source}\n  {_clean_text(doc.page_content, 420)}")
                if len(findings) >= 4:
                    break
            if len(findings) >= 4:
                break
        if not findings:
            return ""
        return (
            "Customer issue summary from internal wiki:\n"
            "Use this to understand the real customer-facing problem and expected fixed behaviour.\n"
            + "\n".join(findings)
        )
    except Exception as exc:
        logger.debug("Customer issue wiki research skipped: %s", exc)
        return ""


def _trello_backlog_research(request_text: str) -> str:
    try:
        from pipeline.trello_client import TrelloClient

        trello = TrelloClient()
        backlog = next((lst for lst in trello.get_lists() if (lst.name or "").strip().lower() in _BACKLOG_LIST_NAMES), None)
        if not backlog:
            return ""

        cards = trello.get_cards_in_list(backlog.id)
        if not cards:
            return ""

        queries = _extract_issue_queries(request_text)
        matches: list[str] = []
        seen_ids: set[str] = set()
        for card in cards:
            haystack = f"{card.name}\n{card.desc}".lower()
            if not any(query.lower() in haystack for query in queries):
                continue
            if card.id in seen_ids:
                continue
            seen_ids.add(card.id)
            matches.append(
                f"- [Backlog] {card.name}\n"
                f"  URL: {card.url}\n"
                f"  Desc: {_clean_text(card.desc, 220)}"
            )
            if len(matches) >= 6:
                break
        if not matches:
            return ""
        return "Related open Trello backlog / planning cards:\n" + "\n".join(matches)
    except Exception as exc:
        logger.debug("Trello backlog research skipped: %s", exc)
        return ""


def _carrier_platform_research(query: str, *, max_docs: int) -> str:
    sections: list[str] = []

    try:
        carrier_context = carrier_research_context(query, max_docs=max_docs)
        if carrier_context:
            sections.append(carrier_context)
    except Exception as exc:
        logger.warning("Carrier research context failed: %s", exc)

    try:
        scope = detect_carrier_scope(query)
        profile = resolve_carrier_request_profile(scope.primary.canonical_name if scope.primary else "")
        if profile:
            sections.append(profile.to_text())
    except Exception as exc:
        logger.warning("Carrier request profile resolution failed: %s", exc)

    try:
        from rag.vectorstore import search_filtered

        findings: list[str] = []
        for source_type in ("wiki", "kb_articles"):
            findings.extend(_join_docs(search_filtered(query, k=max_docs, source_type=source_type) or [], limit=2, max_chars=520))
        if findings:
            sections.append("\n".join(findings[:6]))
    except Exception as exc:
        logger.warning("Carrier/platform local RAG search failed: %s", exc)

    if not sections:
        return ""
    return "Official carrier/platform findings from local RAG:\n" + "\n\n".join(section for section in sections if section.strip())


def _app_behaviour_research(query: str, *, max_docs: int) -> str:
    sections: list[str] = []

    try:
        from rag.vectorstore import search

        docs = search(query, k=max_docs) or []
        joined = _join_docs(docs, limit=max_docs, max_chars=520)
        if joined:
            sections.append("\n".join(joined))
    except Exception as exc:
        logger.warning("Requirement research domain search failed: %s", exc)

    try:
        locator_hints = load_runtime_locator_memory_context(query, limit=8)
        if locator_hints:
            sections.append(
                "Relevant proven UI/navigation hints:\n"
                + "\n".join(f"- {hint}" for hint in locator_hints)
            )
    except Exception as exc:
        logger.warning("Runtime locator memory lookup failed: %s", exc)

    if not sections:
        return ""
    return "MCSL app behaviour findings from local RAG:\n" + "\n\n".join(section for section in sections if section.strip())


def _code_research(query: str) -> str:
    try:
        from rag.code_indexer import get_index_stats, search_code

        stats = get_index_stats()
        sections: list[str] = []
        for source_type, label, limit in (
            ("automation", "Automation flow findings from local code index", 2),
            ("storepepsaas_server", "MCSL server code findings", 2),
            ("storepepsaas_client", "MCSL client code findings", 2),
        ):
            if stats.get(source_type, 0) <= 0:
                continue
            docs = search_code(query, k=limit + 1, source_type=source_type) or []
            joined = _join_docs(docs, limit=limit, max_chars=420)
            if joined:
                sections.append(f"{label}:\n" + "\n".join(joined))
        return "\n\n".join(sections)
    except Exception as exc:
        logger.warning("Requirement research code search failed: %s", exc)
        return ""


@lru_cache(maxsize=128)
def _build_requirement_research_context_cached(request_text: str, max_docs: int) -> str:
    """Return a richer research block for story/AC generation."""
    query = _clean_text(request_text, 500)
    if not query:
        return ""

    parts = [
        part for part in (
            _customer_issue_summary(request_text),
            _trello_backlog_research(request_text),
            _carrier_platform_research(query, max_docs=max_docs),
            _app_behaviour_research(query, max_docs=max_docs),
            _code_research(query),
        )
        if part
    ]

    if not parts:
        return (
            "Requirement research for User Story / AC:\n"
            "No additional MCSL research findings were available. Use existing product and code context, "
            "and flag unknown limits as open questions."
        )

    return (
        "Requirement research for User Story / AC:\n"
        "Priority order for facts:\n"
        "1. Carrier/platform rules and KB/wiki evidence define external constraints.\n"
        "2. MCSL app behaviour context explains how the product currently exposes those rules.\n"
        "3. Code and automation context ground implementation details and QA flow expectations.\n"
        "Use this to add constraints, edge cases, prerequisites, and open questions without inventing unsupported rules.\n\n"
        + "\n\n".join(parts)
    )


def build_requirement_research_context(request_text: str, *, max_docs: int = 4) -> str:
    return _build_requirement_research_context_cached(request_text or "", max_docs)


def clear_requirement_research_cache() -> None:
    _build_requirement_research_context_cached.cache_clear()
