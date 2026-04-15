import pytest
from unittest.mock import patch
from langchain_core.documents import Document


def test_stable_ids():
    """embed_trello_card calls upsert_documents with the correct stable IDs."""
    with patch("rag.vectorstore.upsert_documents") as mock_upsert:
        from pipeline.rag_updater import embed_trello_card
        embed_trello_card("CARD-123", "AC text here", "Test case text here")
        assert mock_upsert.call_count == 1
        # Get positional args
        call_args = mock_upsert.call_args[0]
        docs, ids = call_args[0], call_args[1]
        assert ids == ["CARD-123__ac", "CARD-123__test_cases"]
        assert len(docs) == 2


def test_upsert_idempotent():
    """Calling embed_trello_card twice with same card_id calls upsert twice with same IDs."""
    with patch("rag.vectorstore.upsert_documents") as mock_upsert:
        from importlib import reload
        import pipeline.rag_updater as ru
        reload(ru)
        ru.embed_trello_card("CARD-456", "AC v1", "TC v1")
        ru.embed_trello_card("CARD-456", "AC v2", "TC v2")
        assert mock_upsert.call_count == 2
        # Both calls used same stable IDs — the underlying upsert_documents handles replace
        first_ids  = mock_upsert.call_args_list[0][0][1]
        second_ids = mock_upsert.call_args_list[1][0][1]
        assert first_ids  == ["CARD-456__ac", "CARD-456__test_cases"]
        assert second_ids == ["CARD-456__ac", "CARD-456__test_cases"]


def test_source_type_metadata():
    """Both documents have source_type='trello_card'."""
    with patch("rag.vectorstore.upsert_documents") as mock_upsert:
        from pipeline.rag_updater import embed_trello_card
        embed_trello_card("CARD-789", "AC content", "TC content")
        docs = mock_upsert.call_args[0][0]
        assert all(d.metadata["source_type"] == "trello_card" for d in docs)
        assert all(d.metadata["card_id"] == "CARD-789" for d in docs)
