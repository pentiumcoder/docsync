import os
import pytest

@pytest.fixture(autouse=True)
def mock_env_vars(monkeypatch):
    """Ensure tests run without requiring real environment variables."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("GITHUB_TOKEN", "test-github-token")
    monkeypatch.setenv("GITHUB_REPO", "test-owner/test-repo")
