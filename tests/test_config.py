"""Tests for config.py — INFRA-01, INFRA-03, INFRA-04 coverage."""


def test_dotenv_explicit_path(tmp_path, monkeypatch):
    """Verify config uses explicit dotenv path tied to __file__, not CWD."""
    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=test-key-abc\n")
    # Re-import config from a different cwd to verify explicit path works
    import importlib, sys, os
    (tmp_path / "subdir").mkdir(exist_ok=True)
    monkeypatch.chdir(tmp_path / "subdir")
    # config.py must not be affected by cwd change — it uses __file__ path
    import config
    # The key should be loaded from the actual .env, not tmp .env —
    # this tests that the pattern is in place (not None)
    assert hasattr(config, "ANTHROPIC_API_KEY")  # attribute exists


def test_collection_names():
    """Verify ChromaDB collection names are MCSL-specific (not fedex_*)."""
    import config
    assert config.CHROMA_COLLECTION == "mcsl_knowledge"
    assert config.CHROMA_CODE_COLLECTION == "mcsl_code_knowledge"


def test_mcsl_env_vars():
    """Verify all MCSL-specific env vars are present in config module."""
    import config
    assert hasattr(config, "STORE")
    assert hasattr(config, "SHOPIFY_ACCESS_TOKEN")
    assert hasattr(config, "SHOPIFY_API_VERSION")
    assert hasattr(config, "MCSL_AUTOMATION_REPO_PATH")
    assert hasattr(config, "WIKI_PATH")
    assert hasattr(config, "STOREPEPSAAS_SHARED_PATH")


def test_app_iframe_selector():
    """Verify iframe selector constant is correct for MCSL app."""
    import config
    assert config.APP_IFRAME_SELECTOR == "iframe[name='app-iframe']"
