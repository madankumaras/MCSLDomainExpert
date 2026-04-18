"""
Tests for CHAT-01 and CHAT-02: ask_domain_expert() + QUICK_ASKS in ui/chat_app.py
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# CHAT-01: RAG-backed answer with source attribution
# ---------------------------------------------------------------------------

def test_chat01_ask_domain_expert():
    """ask_domain_expert() returns dict with answer and sources from mocked RAG chain."""
    mock_chain = MagicMock()
    mock_result = {"answer": "Use ORDERS tab", "sources": ["kb_article_1"]}

    with (
        patch("rag.chain.build_chain", return_value=mock_chain),
        patch("rag.chain.ask", return_value=mock_result),
    ):
        from ui.chat_app import ask_domain_expert  # noqa: PLC0415

        result = ask_domain_expert("How do I generate a label?")

    assert result["answer"] == "Use ORDERS tab"
    assert result["sources"] == ["kb_article_1"]


def test_chat01_empty_rag_returns_fallback():
    """ask_domain_expert() returns fallback dict when build_chain() raises RuntimeError."""
    with patch("rag.chain.build_chain", side_effect=RuntimeError("no API key")):
        from ui.chat_app import ask_domain_expert  # noqa: PLC0415

        result = ask_domain_expert("any question")

    assert "answer" in result
    assert result["answer"].startswith("Domain expert unavailable")
    assert result["sources"] == []


# ---------------------------------------------------------------------------
# CHAT-02: Quick Questions list + module importability
# ---------------------------------------------------------------------------

def test_chat02_quick_questions_list():
    """QUICK_ASKS is a list with at least 5 entries."""
    from ui.chat_app import QUICK_ASKS  # noqa: PLC0415

    assert isinstance(QUICK_ASKS, list)
    assert len(QUICK_ASKS) >= 5


def test_chat02_module_importable():
    """ui.chat_app is importable and exposes ask_domain_expert + QUICK_ASKS at module level."""
    import importlib  # noqa: PLC0415

    import ui.chat_app  # noqa: PLC0415

    importlib.reload(ui.chat_app)

    assert hasattr(ui.chat_app, "ask_domain_expert")
    assert hasattr(ui.chat_app, "QUICK_ASKS")
