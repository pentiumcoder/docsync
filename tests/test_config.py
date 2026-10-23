import pytest
from docsync.config import load_config

def test_load_config_defaults(monkeypatch):
    """Test loading config with minimum required env vars and defaults."""
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_REPO", raising=False)
    monkeypatch.delenv("DOCSYNC_MODEL", raising=False)
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
    monkeypatch.delenv("CONFIDENCE_THRESHOLD", raising=False)
    monkeypatch.delenv("CHROMA_PATH", raising=False)
    monkeypatch.delenv("GRAPH_PATH", raising=False)
    
    config = load_config()
    
    assert config.openai_api_key == "test-openai-key"
    assert config.openai_base_url is None
    assert config.github_token is None
    assert config.github_repo is None
    assert config.docsync_model == "gpt-4o-mini"
    assert config.embedding_model == "text-embedding-3-small"
    assert config.confidence_threshold == 0.8
    assert config.chroma_path == ".docsync/chroma"
    assert config.graph_path == ".docsync/graph.json"

def test_load_config_custom_provider(monkeypatch):
    """Test OpenAI-compatible base URL and model overrides."""
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("DOCSYNC_MODEL", "llama3.1:8b")
    monkeypatch.setenv("EMBEDDING_MODEL", "nomic-embed-text")

    config = load_config()

    assert config.openai_base_url == "http://localhost:11434/v1"
    assert config.docsync_model == "llama3.1:8b"
    assert config.embedding_model == "nomic-embed-text"


def test_load_config_blank_base_url(monkeypatch):
    """An empty OPENAI_BASE_URL is treated as unset."""
    monkeypatch.setenv("OPENAI_BASE_URL", "")

    assert load_config().openai_base_url is None


def test_load_config_missing_required(monkeypatch):
    """Test that missing OPENAI_API_KEY raises an error."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    
    with pytest.raises(ValueError, match="Missing required env var: OPENAI_API_KEY"):
        load_config()


def test_load_config_invalid_confidence_threshold(monkeypatch):
    """Test that invalid CONFIDENCE_THRESHOLD raises an error."""
    monkeypatch.setenv("CONFIDENCE_THRESHOLD", "not-a-float")

    with pytest.raises(
        ValueError, match="Invalid CONFIDENCE_THRESHOLD value: not-a-float"
    ):
        load_config()
