# DocSync

DocSync is a GitHub Action that detects when Python code changes make documentation inaccurate.
On every pull request it checks the docs linked to the changed code, then either opens a fix pull
request or flags the affected sections for human review. It never blocks a pull request: the check
reports results and always exits successfully.

## How it works

1. `docsync index` parses Python into `CodeChunk` objects and Markdown into `DocSection` objects,
   embeds both with OpenAI, stores them in a local ChromaDB directory, and builds a
   `{chunk_id: [section_id]}` link graph.
2. On a pull request, `docsync check` parses the diff, ignores non-Python files, test files, and
   comment/whitespace-only hunks, and maps the remaining changes to documentation sections through
   the committed link graph.
3. A quick LLM pass skips verification when the changes only preserve behavior. Otherwise each
   affected section is verified, rewritten, and validated; fixes are applied when confidence clears
   the threshold, and everything else is flagged in the PR comment.

The index lives in `.docsync/` and is committed to your repository, so CI does not re-embed anything.

## Quick start

### 1. Build the index

Install DocSync from source, then point it at your code and docs directories:

```bash
pip install "git+https://github.com/pentiumcoder/docsync.git"

# Use OpenAI or any OpenAI-compatible API (e.g. Ollama)
export OPENAI_API_KEY=sk-...
docsync index . docs
```

For local inference with Ollama, set `OPENAI_BASE_URL` and the models:

```bash
export OPENAI_API_KEY=ollama
export OPENAI_BASE_URL=http://localhost:11434/v1
export DOCSYNC_MODEL=llama3.1:8b
export EMBEDDING_MODEL=nomic-embed-text
docsync index . docs
```

`docsync index <repo_path> <docs_path>` writes `.docsync/chroma/` and `.docsync/graph.json`.
Paths stored in the graph are relative to the repository root.

Commit the generated index:

```bash
git add .docsync
git commit -m "Add DocSync documentation index"
```

Re-run the indexer whenever you add, rename, or move documented code or documentation. The check
does not re-index on its own.

### 2. Add the check to pull requests

```yaml
name: docsync

on:
  pull_request:
    types: [opened, synchronize, reopened]

permissions:
  contents: write
  pull-requests: write

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Check documentation
        uses: pentiumcoder/docsync@v1
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GITHUB_REPO: ${{ github.repository }}
        with:
          base_ref: ${{ github.event.pull_request.base.sha }}
          head_ref: ${{ github.event.pull_request.head.sha }}
          pr_number: ${{ github.event.pull_request.number }}
```

`fetch-depth: 0` is required so both pull request SHAs are available. `contents: write` and
`pull-requests: write` let the action push fix branches and open pull requests. If you only want
reporting, see `--dry-run` below and grant `pull-requests: write` only.

### Action inputs

| Input | Required | Description |
|---|---|---|
| `base_ref` | yes | Base commit SHA of the pull request |
| `head_ref` | yes | Head commit SHA of the pull request |
| `pr_number` | yes | Pull request number |

### Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENAI_API_KEY` | yes | - | Used for embeddings, verification, and rewriting |
| `GITHUB_TOKEN` | yes | - | Automatically provided by Actions; do not add it as a manual secret |
| `GITHUB_REPO` | yes | - | Repository in `owner/name` form |
| `DOCSYNC_MODEL` | no | `gpt-4o-mini` | OpenAI chat model used for checks and rewrites |
| `CONFIDENCE_THRESHOLD` | no | `0.8` | Minimum confidence required to auto-fix a section |
| `CHROMA_PATH` | no | `.docsync/chroma` | Persistent ChromaDB directory |
| `GRAPH_PATH` | no | `.docsync/graph.json` | Link graph file |

## Running a check locally

```bash
docsync check \
  --base-ref origin/main \
  --head-ref HEAD \
  --pr-number 42 \
  --dry-run
```

`--dry-run` performs the full analysis but posts no comment and creates no fix pull request. A dry
run still needs `OPENAI_API_KEY`; it does not need `GITHUB_TOKEN` or `GITHUB_REPO`.

`docsync check` exits with status 0 even when it reports a failure, and writes errors to stderr.
Documentation drift should never break your build.

## Writing documentation DocSync can link

DocSync links a section to a code chunk in two ways:

- **Heuristic:** the section contains the chunk's name as an inline code span, for example
  `` `run_check` ``.
- **Semantic:** the section embedding is similar to the chunk embedding (cosine similarity above
  0.82).

Prefer explicit names in inline code spans. Each Markdown heading starts a new section; content
before the first heading is not indexed. Fenced code blocks are ignored when collecting names.

## Development

```bash
pip install -e ".[dev]"
pytest tests/ -v --ignore=tests/integration
actionlint action.yml .github/workflows/*.yml
docker build -t docsync .
```

The unit suite uses mocked OpenAI and GitHub clients and passes without real credentials. Tests
under `tests/integration/` are excluded and require real keys.

## Limitations

- Python source and Markdown documentation only.
- The index is a snapshot. Re-index after large refactors, file moves, or documentation rewrites.
- Pull requests from forks receive a read-only `GITHUB_TOKEN`, so they cannot receive comments or
  fix pull requests. Reports still appear in the workflow log and the job exits successfully.
- LLM classification, verification, and rewriting incur OpenAI usage on each check.

## License

MIT
