# Using DocSync

This page describes how to index a repository, enable the pull request check, and configure
DocSync for your team.

## Requirements

DocSync runs on Python 3.10 or newer. The action itself is packaged as a Docker action, so CI needs
no separate Python setup. Local indexing requires an API key and models for embeddings and chat. You
can use OpenAI or any OpenAI-compatible provider, including a local Ollama instance.

The persistent index is stored in `.docsync/` and must be committed. It contains the ChromaDB files
under `.docsync/chroma` and the link graph at `.docsync/graph.json`.

## Building the index

Run the indexer from the repository root:

```bash
docsync index . docs
```

The first argument is the code root and the second is the documentation root. `run_index` parses
both trees with `parse_directory`, embeds every `CodeChunk` and `DocSection` through
`embed_texts`, stores the vectors with `ChromaStore`, and builds the graph with `build_graph`.

Paths recorded in the index are relative to the repository root, so keep the code root at the
repository root when you expect documentation to reference files consistently.

Re-index after adding, renaming, or moving documented code, and after restructuring documentation.
A check loads the committed graph to find affected sections, then re-parses the changed files at the
pull request head so that verification sees the new code. The check never re-embeds the repository.

## Committing the index

`save_graph` writes `.docsync/graph.json`. The ChromaDB directory is written in place. Commit both:

```bash
git add .docsync
git commit -m "Update DocSync index"
```

Continuous integration loads the committed graph with `load_graph`. If the graph is missing,
`run_check` posts a short notice explaining that no index was found and returns without calling the
model.

## Adding the check to a pull request

The action invokes `docsync check` inside its container. Pass the pull request SHAs and number:

```yaml
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

Check out the repository with `fetch-depth: 0`. Grant `contents: write` and
`pull-requests: write` when you want fix branches and comments; `run_check` uses `GitHubClient` to
call `get_diff`, `post_comment`, and `create_fix_pr`.

For a local dry run, call `run_check` through the command line with `--dry-run`. The dry run still
uses `verify_staleness` and `rewrite_section`, but it does not post anything.

## Configuration

`load_config` reads all settings from the environment and returns a `Config` object. No other
module reads environment variables directly.

| Variable | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | none | Authentication for embeddings and chat completions |
| `OPENAI_BASE_URL` | none | Base URL for OpenAI-compatible APIs (e.g. `http://localhost:11434/v1` for Ollama) |
| `GITHUB_TOKEN` | none | Commenting and pull request creation |
| `GITHUB_REPO` | none | Repository slug in `owner/name` form |
| `DOCSYNC_MODEL` | `gpt-4o-mini` | Chat model for verification and rewriting |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | Embedding model for indexing and similarity |
| `CONFIDENCE_THRESHOLD` | `0.8` | Cutoff for automatic fixes |
| `CHROMA_PATH` | `.docsync/chroma` | ChromaDB persistence directory |
| `GRAPH_PATH` | `.docsync/graph.json` | Link graph location |

Missing required values raise `ValueError` with the variable name, for example
`Missing required env var: OPENAI_API_KEY`.

## How automation decides

`parse_diff` converts the pull request diff into `FileChange` records. `filter_changes` drops
non-Python files, test files, and hunks whose added and removed lines are only comments or
whitespace. `run_check` then maps the surviving changes to sections through the graph.

For every affected `DocSection`, `verify_staleness` returns a `StalenessResult`. Accurate sections
are reported as-is. Stale sections go to `rewrite_section`, which returns a `CorrectionResult` and
runs an internal validation pass. The section is auto-fixed only when both the rewrite and the
validation clear `CONFIDENCE_THRESHOLD`; otherwise it is flagged for a human. Each file is updated
once, using the current on-disk content, so several sections in one document produce a single
`FileEdit`.

## Writing documentation DocSync can link

Headings define sections. Content before the first heading is ignored, and nested headings inherit
their parent path in `section_id`. Inline code spans are collected as `code_references`; fenced code
blocks are skipped.

To make linking reliable, mention public names in inline code, for example `run_index`,
`run_check`, `GitHubClient`, or `format_pr_comment`. The heuristic pass links a section when its
references match a chunk name. The semantic pass links sections whose embeddings are close to the
chunk embedding.

## Troubleshooting

- **No index found:** commit `.docsync/` and check that `GRAPH_PATH` points at the committed file.
- **Nothing is checked:** the pull request may contain only documentation, tests, comments, or
  whitespace changes.
- **Missing comments on forks:** forked pull requests get a read-only token, so comment and fix pull
  request calls fail. The check still exits successfully and prints its report to the workflow log.
- **Stale links after refactors:** rebuild the index with `run_index` and commit the result.
