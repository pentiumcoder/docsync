# Integration tests

Tests in this directory make real calls to the OpenAI and GitHub APIs. They are excluded
from the standard test run:

```
pytest tests/ -v --ignore=tests/integration
```

Run them explicitly, with real credentials, on a throwaway repository:

```
pytest tests/integration -v
```

Required environment variables: `OPENAI_API_KEY`, `GITHUB_TOKEN`, `GITHUB_REPO`.
