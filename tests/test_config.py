import pytest
from docsync.config import load_config

def test_load_config_defaults(monkeypatch):
    """Test loading config with minimum required env vars and defaults."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_REPO", raising=False)
    monkeypatch.delenv("DOCSYNC_MODEL", raising=False)
    monkeypatch.delenv("CONFIDENCE_THRESHOLD", raising=False)
    monkeypatch.delenv("CHROMA_PATH", raising=False)
    monkeypatch.delenv("GRAPH_PATH", raising=False)
    
    config = load_config()
    
    assert config.openai_api_key == "test-openai-key"
    assert config.github_token is None
    assert config.github_repo is None
    assert config.docsync_model == "gpt-4o-mini"
    assert config.confidence_threshold == 0.8
    assert config.chroma_path == ".docsync/chroma"
    assert config.graph_path == ".docsync/graph.json"

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
