"""
pipeline/user_story_writer.py — User Story generation and refinement for MCSL multi-carrier app.

Exports: generate_user_story, refine_user_story
"""
from __future__ import annotations

import logging

import config
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

US_WRITER_PROMPT = """\
You are a senior Product Owner / Business Analyst for the MCSL multi-carrier Shopify app.
The app integrates FedEx, UPS, DHL, USPS, and other carrier shipping services
(label generation, rate calculation, tracking, returns, signature options, etc.)
into Shopify stores via a Shopify embedded app.

Feature request:
{feature_request}

Domain context (MCSL knowledge base):
{domain_context}

Codebase context (relevant MCSL code):
{code_context}

Write a User Story and Acceptance Criteria in this format:
### User Story
As a [persona], I want [feature], so that [benefit].

### Acceptance Criteria
- AC1: [specific testable criterion]
- AC2: ...

### Notes
[Implementation hints, edge cases, carrier-specific considerations]
"""

US_REFINE_PROMPT = """\
You are refining an existing User Story and Acceptance Criteria for the MCSL multi-carrier Shopify app.

Current User Story:
{previous_us}

Requested change:
{change_request}

Return the complete updated User Story + Acceptance Criteria in the same markdown format.
Only change what is needed to incorporate the requested change.
"""


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _get_claude(model: str | None = None) -> ChatAnthropic:
    """Return a ChatAnthropic instance using the configured Sonnet model."""
    return ChatAnthropic(
        model=model or config.CLAUDE_SONNET_MODEL,
        api_key=config.ANTHROPIC_API_KEY,
        temperature=0.3,
        max_tokens=2048,
    )


def _fetch_domain_context(query: str) -> str:
    """Fetch relevant domain knowledge from the MCSL vector store."""
    try:
        from rag.vectorstore import search
        docs = search(query, k=5)
        if not docs:
            return "No domain context available."
        return "\n\n---\n\n".join(doc.page_content for doc in docs)
    except Exception as exc:
        logger.warning("Domain context fetch failed: %s", exc)
        return "No domain context available."


def _fetch_code_context(query: str) -> str:
    """Fetch relevant code chunks from the MCSL code index."""
    try:
        from rag.code_indexer import search_code
        docs = search_code(query, k=5)
        if not docs:
            return "No code context available."
        return "\n\n---\n\n".join(doc.page_content for doc in docs)
    except Exception as exc:
        logger.warning("Code context fetch failed: %s", exc)
        return "No code context available."


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_user_story(feature_request: str, model: str | None = None) -> str:
    """Generate a User Story + Acceptance Criteria for the given feature request.

    Uses MCSL domain knowledge and codebase context when available.
    Falls back gracefully if the RAG collections are empty or unavailable.

    Args:
        feature_request: Plain-language description of the desired feature.
        model: Optional Claude model ID override.

    Returns:
        Markdown string containing User Story, Acceptance Criteria, and Notes sections.
    """
    domain_context = _fetch_domain_context(feature_request)
    code_context = _fetch_code_context(feature_request)
    prompt = US_WRITER_PROMPT.format(
        feature_request=feature_request,
        domain_context=domain_context,
        code_context=code_context,
    )
    response = _get_claude(model).invoke([HumanMessage(content=prompt)])
    return response.content.strip()


def refine_user_story(
    previous_us: str,
    change_request: str,
    model: str | None = None,
) -> str:
    """Refine an existing User Story based on a change request.

    Args:
        previous_us: The current User Story markdown text.
        change_request: Description of what should change.
        model: Optional Claude model ID override.

    Returns:
        Updated User Story markdown string.
    """
    prompt = US_REFINE_PROMPT.format(
        previous_us=previous_us.strip(),
        change_request=change_request.strip(),
    )
    response = _get_claude(model).invoke([HumanMessage(content=prompt)])
    return response.content.strip()
