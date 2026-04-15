"""
RAG Auto-Updater
================
Embeds approved Trello card ACs and test cases into the mcsl_knowledge
ChromaDB collection after each sprint cycle.

Uses stable document IDs so re-running for the same card replaces
(not duplicates) the previous content.

Usage:
    from pipeline.rag_updater import embed_trello_card

    embed_trello_card(
        card_id="CARD-123",
        ac_text="Given the user has a FedEx account...",
        test_cases_text="TC-01: Verify label generated...",
    )
"""
from __future__ import annotations
import logging
from langchain_core.documents import Document
from rag.vectorstore import upsert_documents

logger = logging.getLogger(__name__)


def embed_trello_card(
    card_id: str,
    ac_text: str,
    test_cases_text: str,
) -> None:
    """
    Embed a Trello card's AC and test cases into mcsl_knowledge using
    stable IDs so repeated calls replace rather than duplicate content.

    Args:
        card_id:         Unique Trello card identifier (e.g. "CARD-123")
        ac_text:         Full acceptance criteria text from the card
        test_cases_text: Full test cases text associated with the card
    """
    ac_id         = f"{card_id}__ac"
    test_cases_id = f"{card_id}__test_cases"

    docs = [
        Document(
            page_content=ac_text or f"[No AC text provided for {card_id}]",
            metadata={
                "source_type":  "trello_card",
                "source":       f"trello:{card_id}:ac",
                "source_url":   f"trello:{card_id}",
                "card_id":      card_id,
                "content_type": "ac",
                "chunk_index":  0,
            },
        ),
        Document(
            page_content=test_cases_text or f"[No test cases provided for {card_id}]",
            metadata={
                "source_type":  "trello_card",
                "source":       f"trello:{card_id}:test_cases",
                "source_url":   f"trello:{card_id}",
                "card_id":      card_id,
                "content_type": "test_cases",
                "chunk_index":  0,
            },
        ),
    ]

    upsert_documents(docs, ids=[ac_id, test_cases_id])
    logger.info("Embedded Trello card %s (AC + test cases) into mcsl_knowledge", card_id)
