import pytest

import docsync.config

@pytest.fixture(autouse=True)
def mock_env_vars(monkeypatch):
    """Ensure tests run without requiring real environment variables."""
    monkeypatch.setattr(docsync.config, "load_dotenv", lambda: None)
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("GITHUB_TOKEN", "test-github-token")
    monkeypatch.setenv("GITHUB_REPO", "test-owner/test-repo")
