import os
from dataclasses import dataclass

from openai import OpenAI

from docsync.config import Config, load_config
from docsync.detection.change_filter import (
    filter_changes,
    map_change_to_chunks,
    map_chunks_to_sections,
)
from docsync.detection.diff_parser import parse_diff
from docsync.github_client.client import FileEdit, GitHubClient
from docsync.github_client.formatter import (
    SectionResult,
    format_fix_pr_body,
    format_no_index_comment,
    format_pr_comment,
)
from docsync.index.embedder import embed_texts
from docsync.index.graph import build_graph, load_graph, save_graph
from docsync.index.store import ChromaStore
from docsync.llm.rewriter import CorrectionResult, rewrite_section
from docsync.llm.verifier import verify_staleness
from docsync.parsers.code_parser import CodeChunk
from docsync.parsers.code_parser import parse_directory as parse_code_directory
from docsync.parsers.docs_parser import DocSection
from docsync.parsers.docs_parser import parse_directory as parse_docs_directory


@dataclass
class IndexResult:
    chunks_count: int
    sections_count: int
    links_count: int


@dataclass
class CheckResult:
    sections_checked: int
    accurate_count: int
    auto_fixed_count: int
    flagged_count: int
    section_results: list[SectionResult]


def _chunk_text(chunk: CodeChunk) -> str:
    return f"{chunk.signature}\n{chunk.docstring or ''}\n{chunk.body[:500]}"


def _make_github_client(config: Config) -> GitHubClient:
    if not config.github_token:
        raise ValueError("Missing required env var: GITHUB_TOKEN")
    if not config.github_repo:
        raise ValueError("Missing required env var: GITHUB_REPO")
    return GitHubClient(config.github_token, config.github_repo)


def _build_code_context(chunks: list[CodeChunk]) -> str:
    blocks = [
        f"# {chunk.file_path}::{chunk.name}\n{chunk.body}"
        for chunk in sorted(chunks, key=lambda chunk: chunk.chunk_id)
    ]
    return "\n\n".join(blocks)


def _build_file_edits(
    pairs: list[tuple[DocSection, CorrectionResult]], repo_path: str
) -> tuple[list[FileEdit], list[tuple[DocSection, CorrectionResult]]]:
    contents: dict[str, str] = {}
    changed_paths: set[str] = set()
    applied: list[tuple[DocSection, CorrectionResult]] = []

    for section, correction in pairs:
        path = os.path.join(repo_path, section.file_path)
        if path not in contents:
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    contents[path] = handle.read()
            except OSError:
                continue

        if not section.content or section.content not in contents[path]:
            continue

        contents[path] = contents[path].replace(
            section.content, correction.corrected_content, 1
        )
        changed_paths.add(path)
        applied.append((section, correction))

    edits = [
        FileEdit(
            file_path=os.path.relpath(path, repo_path).replace("\\", "/"),
            new_content=contents[path],
        )
        for path in sorted(changed_paths)
    ]
    return edits, applied


def run_index(
    repo_path: str,
    docs_path: str,
    config: Config | None = None,
    openai_client: OpenAI | None = None,
    store: ChromaStore | None = None,
) -> IndexResult:
    config = config or load_config()
    if openai_client is None:
        openai_client = OpenAI(api_key=config.openai_api_key)
    if store is None:
        store = ChromaStore(config.chroma_path)

    chunks = parse_code_directory(repo_path, repo_path)
    sections = parse_docs_directory(docs_path, repo_path)

    chunk_embeddings = embed_texts([_chunk_text(chunk) for chunk in chunks], openai_client)
    section_embeddings = embed_texts([section.content for section in sections], openai_client)

    store.upsert_chunks(chunks, chunk_embeddings)
    store.upsert_sections(sections, section_embeddings)

    graph = build_graph(chunks, sections, store, chunk_embeddings)
    save_graph(graph, config.graph_path)

    links_count = sum(len(section_ids) for section_ids in graph.values())
    return IndexResult(
        chunks_count=len(chunks),
        sections_count=len(sections),
        links_count=links_count,
    )


def run_check(
    base_ref: str,
    head_ref: str,
    pr_number: int,
    config: Config | None = None,
    dry_run: bool = False,
    openai_client: OpenAI | None = None,
    github_client: GitHubClient | None = None,
    store: ChromaStore | None = None,
    repo_path: str = ".",
) -> CheckResult:
    config = config or load_config()
    graph = load_graph(config.graph_path)

    if github_client is None:
        github_client = _make_github_client(config)

    if not graph:
        if not dry_run:
            github_client.post_comment(pr_number, format_no_index_comment())
        return CheckResult(
            sections_checked=0,
            accurate_count=0,
            auto_fixed_count=0,
            flagged_count=0,
            section_results=[],
        )

    if openai_client is None:
        openai_client = OpenAI(api_key=config.openai_api_key)
    if store is None:
        store = ChromaStore(config.chroma_path)

    diff_text = github_client.get_diff(base_ref, head_ref)
    changes = filter_changes(parse_diff(diff_text))

    chunks = store.get_all_chunks()
    chunk_mapping = map_change_to_chunks(changes, chunks)

    matched_chunks: dict[str, CodeChunk] = {}
    for chunk_list in chunk_mapping.values():
        for chunk in chunk_list:
            matched_chunks[chunk.chunk_id] = chunk

    section_ids = map_chunks_to_sections(list(matched_chunks.keys()), graph)
    sections = store.get_sections_by_ids(section_ids)

    section_chunks: dict[str, list[CodeChunk]] = {}
    for chunk in matched_chunks.values():
        for section_id in graph.get(chunk.chunk_id, []):
            section_chunks.setdefault(section_id, []).append(chunk)

    section_results: list[SectionResult] = []
    auto_fix_pairs: list[tuple[DocSection, CorrectionResult]] = []

    for section in sections:
        code_context = _build_code_context(section_chunks.get(section.section_id, []))
        staleness = verify_staleness(
            section, code_context, openai_client, config.docsync_model
        )

        if not staleness.is_stale:
            section_results.append(
                SectionResult(
                    section_id=section.section_id,
                    status="accurate",
                    fix_pr_url=None,
                    issues=[],
                )
            )
            continue

        correction = rewrite_section(
            section,
            staleness,
            code_context,
            openai_client,
            config.docsync_model,
            config.confidence_threshold,
        )

        if correction.requires_human_review:
            section_results.append(
                SectionResult(
                    section_id=section.section_id,
                    status="flagged",
                    fix_pr_url=None,
                    issues=list(staleness.specific_issues),
                )
            )
            continue

        section_results.append(
            SectionResult(
                section_id=section.section_id,
                status="auto-fixed",
                fix_pr_url=None,
                issues=[],
            )
        )
        auto_fix_pairs.append((section, correction))

    if not dry_run and auto_fix_pairs:
        edits, applied = _build_file_edits(auto_fix_pairs, repo_path)
        applied_ids = {section.section_id for section, _ in applied}

        for index, result in enumerate(section_results):
            if result.status == "auto-fixed" and result.section_id not in applied_ids:
                section_results[index] = SectionResult(
                    section_id=result.section_id,
                    status="flagged",
                    fix_pr_url=None,
                    issues=[
                        "Could not locate the original section content for automatic "
                        "replacement; manual review required."
                    ],
                )

        if edits:
            corrections = [correction for _, correction in applied]
            applied_sections = [section for section, _ in applied]
            base_branch = github_client.get_pr_base_branch(pr_number)
            fix_pr_url = github_client.create_fix_pr(
                base_branch,
                edits,
                "docsync: update stale documentation",
                format_fix_pr_body(corrections, applied_sections),
            )
            for result in section_results:
                if result.status == "auto-fixed":
                    result.fix_pr_url = fix_pr_url

    if not dry_run:
        github_client.post_comment(pr_number, format_pr_comment(section_results))

    accurate_count = sum(1 for result in section_results if result.status == "accurate")
    auto_fixed_count = sum(
        1 for result in section_results if result.status == "auto-fixed"
    )
    flagged_count = sum(1 for result in section_results if result.status == "flagged")

    return CheckResult(
        sections_checked=len(section_results),
        accurate_count=accurate_count,
        auto_fixed_count=auto_fixed_count,
        flagged_count=flagged_count,
        section_results=section_results,
    )
