import pytest


@pytest.fixture
def tmp_chroma_path(tmp_path):
    """Returns a temporary path for ChromaDB during tests."""
    return str(tmp_path / "chroma_db")


@pytest.fixture
def sample_kb_doc():
    """Returns a sample KB article Document for testing."""
    from langchain_core.documents import Document
    return Document(
        page_content="Test KB article content about MCSL shipping",
        metadata={
            "source_type": "kb_articles",
            "source": "test.md",
            "chunk_index": 0,
        },
    )


@pytest.fixture
def sample_wiki_doc():
    """Returns a sample wiki Document for testing."""
    from langchain_core.documents import Document
    return Document(
        page_content="MCSL wiki page about carrier architecture",
        metadata={
            "source_type": "wiki",
            "category": "architecture",
            "file_name": "carriers.md",
            "chunk_index": 0,
        },
    )


@pytest.fixture
def sample_code_doc():
    """Returns a sample source code Document for testing."""
    from langchain_core.documents import Document
    return Document(
        page_content="// File: carrierConfig.js\nconst FEDEX = 'C2';",
        metadata={
            "source_type": "storepepsaas",
            "file_path": "carrierConfig.js",
            "language": "javascript",
        },
    )


@pytest.fixture
def mock_embeddings():
    """Returns a mock embeddings object for testing without Ollama."""
    from unittest.mock import MagicMock
    mock = MagicMock()
    mock.embed_documents.return_value = [[0.1] * 768]
    mock.embed_query.return_value = [0.1] * 768
    return mock
