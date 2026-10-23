from unittest.mock import MagicMock

import pytest

from docsync.config import Config
from docsync.github_client.client import FileEdit
from docsync.llm.rewriter import CorrectionResult
from docsync.llm.verifier import StalenessResult
from docsync.parsers.code_parser import CodeChunk
from docsync.parsers.docs_parser import DocSection
from docsync.pipeline import CheckResult, IndexResult, run_check, run_index

MODIFIED_DIFF = """diff --git a/src/api.py b/src/api.py
--- a/src/api.py
+++ b/src/api.py
@@ -1,2 +1,3 @@
 def get_user(user_id):
-    return {}
+    return User(user_id)
+    # changed
"""

DELETED_DIFF = """diff --git a/src/api.py b/src/api.py
deleted file mode 100644
--- a/src/api.py
+++ /dev/null
@@ -1,1 +0,0 @@
-def get_user(user_id):
"""

SECTION_ID = "docs/api.md##API Reference>get_user"


def make_config(**overrides):
    values = {
        "openai_api_key": "test-key",
        "openai_base_url": None,
        "github_token": "test-token",
        "github_repo": "owner/repo",
        "docsync_model": "gpt-4o-mini",
        "embedding_model": "text-embedding-3-small",
        "confidence_threshold": 0.8,
        "chroma_path": ".docsync/chroma",
        "graph_path": ".docsync/graph.json",
    }
    values.update(overrides)
    return Config(**values)


def make_chunk():
    return CodeChunk(
        chunk_id="src/api.py::get_user",
        file_path="src/api.py",
        chunk_type="function",
        name="get_user",
        signature="def get_user(user_id):",
        docstring="Gets a user.",
        body="def get_user(user_id):\n    return db.get(user_id)",
        start_line=1,
        end_line=10,
    )


def make_section(section_id=SECTION_ID, content="### get_user\n\nOld docs.\n"):
    return DocSection(
        section_id=section_id,
        file_path="docs/api.md",
        heading_path=["API Reference", "get_user"],
        level=3,
        content=content,
        code_references=["get_user"],
    )


def make_github(diff_text=MODIFIED_DIFF, fix_url="https://github.com/o/r/pull/5"):
    github = MagicMock()
    github.get_diff.return_value = diff_text
    github.get_pr_base_branch.return_value = "main"
    github.create_fix_pr.return_value = fix_url
    return github


def make_store(chunks, sections):
    store = MagicMock()
    store.get_all_chunks.return_value = chunks
    store.get_sections_by_ids.return_value = sections
    return store


def staleness(is_stale, issues=None):
    return StalenessResult(
        is_stale=is_stale,
        confidence=0.9,
        reason="reason",
        specific_issues=issues if issues is not None else [],
        section_id=SECTION_ID,
    )


def correction(requires_human_review=False, content="### get_user\n\nNew docs.\n"):
    return CorrectionResult(
        corrected_content=content,
        confidence=0.9,
        changed_parts=["Reworded the description"],
        requires_human_review=requires_human_review,
        section_id=SECTION_ID,
    )


# --- run_index ---


def test_run_index_orchestrates_pipeline(mocker):
    config = make_config()
    chunk = make_chunk()
    section = make_section()

    mocker.patch("docsync.pipeline.parse_code_directory", return_value=[chunk])
    mocker.patch("docsync.pipeline.parse_docs_directory", return_value=[section])
    embed = mocker.patch(
        "docsync.pipeline.embed_texts", side_effect=[[[0.1, 0.2]], [[0.3, 0.4]]]
    )
    graph = {chunk.chunk_id: [section.section_id]}
    build = mocker.patch("docsync.pipeline.build_graph", return_value=graph)
    save = mocker.patch("docsync.pipeline.save_graph")
    store = MagicMock()

    result = run_index(
        "repo", "docs", config=config, openai_client=MagicMock(), store=store
    )

    assert isinstance(result, IndexResult)
    assert (result.chunks_count, result.sections_count, result.links_count) == (1, 1, 1)

    store.upsert_chunks.assert_called_once_with([chunk], [[0.1, 0.2]])
    store.upsert_sections.assert_called_once_with([section], [[0.3, 0.4]])
    build.assert_called_once_with([chunk], [section], store, [[0.1, 0.2]])
    save.assert_called_once_with(graph, config.graph_path)

    assert embed.call_count == 2
    assert embed.call_args_list[0][0][0] == [
        "def get_user(user_id):\nGets a user.\ndef get_user(user_id):\n    return db.get(user_id)"
    ]
    assert embed.call_args_list[1][0][0] == [section.content]


def test_run_index_handles_empty_repository(mocker):
    config = make_config()

    mocker.patch("docsync.pipeline.parse_code_directory", return_value=[])
    mocker.patch("docsync.pipeline.parse_docs_directory", return_value=[])
    mocker.patch("docsync.pipeline.embed_texts", side_effect=[[], []])
    mocker.patch("docsync.pipeline.build_graph", return_value={})
    mocker.patch("docsync.pipeline.save_graph")
    store = MagicMock()

    result = run_index(
        "repo", "docs", config=config, openai_client=MagicMock(), store=store
    )

    assert (result.chunks_count, result.sections_count, result.links_count) == (0, 0, 0)
    store.upsert_chunks.assert_called_once_with([], [])
    store.upsert_sections.assert_called_once_with([], [])


def test_run_index_uses_docs_path_relative_to_repo(mocker):
    config = make_config()
    parse_code = mocker.patch("docsync.pipeline.parse_code_directory", return_value=[])
    parse_docs = mocker.patch("docsync.pipeline.parse_docs_directory", return_value=[])
    mocker.patch("docsync.pipeline.embed_texts", side_effect=[[], []])
    mocker.patch("docsync.pipeline.build_graph", return_value={})
    mocker.patch("docsync.pipeline.save_graph")

    run_index("repo", "repo/docs", config=config, openai_client=MagicMock(), store=MagicMock())

    parse_code.assert_called_once_with("repo", "repo")
    parse_docs.assert_called_once_with("repo/docs", "repo")


# --- run_check: no index ---


def test_run_check_without_index_posts_comment(mocker):
    config = make_config()
    mocker.patch("docsync.pipeline.load_graph", return_value={})
    github = make_github()

    result = run_check(
        "base", "head", 3, config=config, github_client=github
    )

    assert isinstance(result, CheckResult)
    assert result.sections_checked == 0
    github.get_diff.assert_not_called()
    github.post_comment.assert_called_once()
    body = github.post_comment.call_args[0][1]
    assert ".docsync/" in body


def test_run_check_without_index_and_dry_run_posts_nothing(mocker):
    config = make_config()
    mocker.patch("docsync.pipeline.load_graph", return_value={})
    github = make_github()

    result = run_check(
        "base", "head", 3, config=config, dry_run=True, github_client=github
    )

    assert result.sections_checked == 0
    github.post_comment.assert_not_called()


# --- run_check: accurate ---


def test_run_check_marks_accurate_section(mocker):
    config = make_config()
    chunk = make_chunk()
    section = make_section()
    graph = {chunk.chunk_id: [section.section_id]}

    mocker.patch("docsync.pipeline.load_graph", return_value=graph)
    verify = mocker.patch(
        "docsync.pipeline.verify_staleness", return_value=staleness(False)
    )
    rewrite = mocker.patch("docsync.pipeline.rewrite_section")
    github = make_github()
    store = make_store([chunk], [section])
    openai_client = MagicMock()

    result = run_check(
        "base",
        "head",
        7,
        config=config,
        openai_client=openai_client,
        github_client=github,
        store=store,
    )

    assert result.sections_checked == 1
    assert result.accurate_count == 1
    assert result.auto_fixed_count == 0
    assert result.flagged_count == 0
    assert result.section_results[0].status == "accurate"
    rewrite.assert_not_called()
    github.create_fix_pr.assert_not_called()

    verify_args = verify.call_args[0]
    assert verify_args[0] is section
    assert "def get_user" in verify_args[1]
    assert verify_args[2] is openai_client
    assert verify_args[3] == config.docsync_model
    assert verify_args[4] == MODIFIED_DIFF

    github.post_comment.assert_called_once()
    assert section.section_id in github.post_comment.call_args[0][1]


def test_run_check_skips_verification_for_refactor_only_diff(mocker):
    config = make_config()
    chunk = make_chunk()
    section = make_section()
    graph = {chunk.chunk_id: [section.section_id]}

    mocker.patch("docsync.pipeline.load_graph", return_value=graph)
    behavior = mocker.patch(
        "docsync.pipeline.diff_changes_behavior", return_value=False
    )
    verify = mocker.patch("docsync.pipeline.verify_staleness")
    rewrite = mocker.patch("docsync.pipeline.rewrite_section")
    github = make_github()
    store = make_store([chunk], [section])
    openai_client = MagicMock()

    result = run_check(
        "base",
        "head",
        7,
        config=config,
        openai_client=openai_client,
        github_client=github,
        store=store,
    )

    assert result.sections_checked == 1
    assert result.accurate_count == 1
    assert result.section_results[0].status == "accurate"
    verify.assert_not_called()
    rewrite.assert_not_called()
    github.create_fix_pr.assert_not_called()
    behavior.assert_called_once()
    behavior_diff = behavior.call_args[0][0]
    assert "src/api.py" in behavior_diff
    assert "+    return User(user_id)" in behavior_diff
    assert "def get_user(user_id):" not in behavior_diff
    assert behavior.call_args[0][1] is openai_client
    assert behavior.call_args[0][2] == config.docsync_model
    github.post_comment.assert_called_once()


def test_run_check_verifies_with_head_code(mocker, tmp_path):
    config = make_config()
    chunk = make_chunk()
    section = make_section()
    graph = {chunk.chunk_id: [section.section_id]}

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "api.py").write_text(
        "def get_user(user_id):\n    return User(user_id)\n", encoding="utf-8"
    )

    mocker.patch("docsync.pipeline.load_graph", return_value=graph)
    verify = mocker.patch(
        "docsync.pipeline.verify_staleness", return_value=staleness(False)
    )
    github = make_github()
    store = make_store([chunk], [section])

    run_check(
        "base",
        "head",
        7,
        config=config,
        openai_client=MagicMock(),
        github_client=github,
        store=store,
        repo_path=str(tmp_path),
    )

    context = verify.call_args[0][1]
    assert "return User(user_id)" in context
    assert "return db.get(user_id)" not in context


def test_run_check_notes_deleted_files(mocker):
    config = make_config()
    chunk = make_chunk()
    section = make_section()
    graph = {chunk.chunk_id: [section.section_id]}

    mocker.patch("docsync.pipeline.load_graph", return_value=graph)
    verify = mocker.patch(
        "docsync.pipeline.verify_staleness", return_value=staleness(True, ["Missing"])
    )
    mocker.patch(
        "docsync.pipeline.rewrite_section",
        return_value=correction(requires_human_review=True),
    )
    github = make_github(diff_text=DELETED_DIFF)
    store = make_store([chunk], [section])

    run_check(
        "base",
        "head",
        7,
        config=config,
        openai_client=MagicMock(),
        github_client=github,
        store=store,
    )

    context = verify.call_args[0][1]
    assert "deleted in the pull request" in context


# --- run_check: flagged ---


def test_run_check_flags_section_requiring_review(mocker):
    config = make_config()
    chunk = make_chunk()
    section = make_section()
    graph = {chunk.chunk_id: [section.section_id]}

    mocker.patch("docsync.pipeline.load_graph", return_value=graph)
    mocker.patch(
        "docsync.pipeline.verify_staleness",
        return_value=staleness(True, ["Missing timeout parameter"]),
    )
    mocker.patch(
        "docsync.pipeline.rewrite_section",
        return_value=correction(requires_human_review=True),
    )
    github = make_github()
    store = make_store([chunk], [section])

    result = run_check(
        "base",
        "head",
        7,
        config=config,
        openai_client=MagicMock(),
        github_client=github,
        store=store,
    )

    assert result.flagged_count == 1
    assert result.auto_fixed_count == 0
    assert result.section_results[0].status == "flagged"
    assert result.section_results[0].issues == ["Missing timeout parameter"]
    github.create_fix_pr.assert_not_called()

    body = github.post_comment.call_args[0][1]
    assert "flagged" in body
    assert "Missing timeout parameter" in body


# --- run_check: auto-fixed ---


def test_run_check_auto_fixes_and_creates_pr(mocker, tmp_path):
    config = make_config()
    chunk = make_chunk()
    section = make_section()
    graph = {chunk.chunk_id: [section.section_id]}

    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "api.md").write_text(
        "Intro\n\n### get_user\n\nOld docs.\n\nOutro\n", encoding="utf-8"
    )

    mocker.patch("docsync.pipeline.load_graph", return_value=graph)
    mocker.patch(
        "docsync.pipeline.verify_staleness",
        return_value=staleness(True, ["Outdated example"]),
    )
    rewrite = mocker.patch(
        "docsync.pipeline.rewrite_section", return_value=correction()
    )
    github = make_github()
    store = make_store([chunk], [section])

    result = run_check(
        "base",
        "head",
        7,
        config=config,
        openai_client=MagicMock(),
        github_client=github,
        store=store,
        repo_path=str(tmp_path),
    )

    assert result.auto_fixed_count == 1
    assert result.section_results[0].status == "auto-fixed"
    assert result.section_results[0].fix_pr_url == "https://github.com/o/r/pull/5"

    rewrite_args = rewrite.call_args[0]
    assert rewrite_args[5] == config.confidence_threshold

    github.get_pr_base_branch.assert_called_once_with(7)
    github.create_fix_pr.assert_called_once()
    args = github.create_fix_pr.call_args[0]
    assert args[0] == "main"
    edits = args[1]
    assert len(edits) == 1
    assert isinstance(edits[0], FileEdit)
    assert edits[0].file_path == "docs/api.md"
    assert edits[0].new_content == "Intro\n\n### get_user\n\nNew docs.\n\nOutro\n"

    body = github.post_comment.call_args[0][1]
    assert "https://github.com/o/r/pull/5" in body


def test_run_check_dry_run_does_not_create_pr(mocker):
    config = make_config()
    chunk = make_chunk()
    section = make_section()
    graph = {chunk.chunk_id: [section.section_id]}

    mocker.patch("docsync.pipeline.load_graph", return_value=graph)
    mocker.patch(
        "docsync.pipeline.verify_staleness", return_value=staleness(True, ["Issue"])
    )
    mocker.patch("docsync.pipeline.rewrite_section", return_value=correction())
    github = make_github()
    store = make_store([chunk], [section])

    result = run_check(
        "base",
        "head",
        7,
        config=config,
        dry_run=True,
        openai_client=MagicMock(),
        github_client=github,
        store=store,
    )

    assert result.auto_fixed_count == 1
    assert result.section_results[0].fix_pr_url is None
    github.create_fix_pr.assert_not_called()
    github.post_comment.assert_not_called()


def test_run_check_flags_when_section_cannot_be_located(mocker, tmp_path):
    config = make_config()
    chunk = make_chunk()
    section = make_section()
    graph = {chunk.chunk_id: [section.section_id]}

    mocker.patch("docsync.pipeline.load_graph", return_value=graph)
    mocker.patch(
        "docsync.pipeline.verify_staleness", return_value=staleness(True, ["Issue"])
    )
    mocker.patch("docsync.pipeline.rewrite_section", return_value=correction())
    github = make_github()
    store = make_store([chunk], [section])

    result = run_check(
        "base",
        "head",
        7,
        config=config,
        openai_client=MagicMock(),
        github_client=github,
        store=store,
        repo_path=str(tmp_path),
    )

    assert result.flagged_count == 1
    assert result.auto_fixed_count == 0
    assert "manual review required" in result.section_results[0].issues[0]
    github.create_fix_pr.assert_not_called()


# --- run_check: aggregate counts ---


def test_run_check_counts_multiple_sections(mocker):
    config = make_config()
    chunk = make_chunk()
    section_a = make_section(section_id="docs/api.md##A")
    section_b = make_section(section_id="docs/api.md##B")
    graph = {chunk.chunk_id: [section_a.section_id, section_b.section_id]}

    mocker.patch("docsync.pipeline.load_graph", return_value=graph)
    mocker.patch(
        "docsync.pipeline.verify_staleness",
        side_effect=[staleness(False), staleness(True, ["Issue"])],
    )
    mocker.patch(
        "docsync.pipeline.rewrite_section",
        return_value=correction(requires_human_review=True),
    )
    github = make_github()
    store = make_store([chunk], [section_a, section_b])

    result = run_check(
        "base",
        "head",
        7,
        config=config,
        openai_client=MagicMock(),
        github_client=github,
        store=store,
    )

    assert result.sections_checked == 2
    assert result.accurate_count == 1
    assert result.flagged_count == 1
    assert result.auto_fixed_count == 0


def test_run_check_requires_github_credentials(mocker):
    config = make_config(github_token=None)
    mocker.patch("docsync.pipeline.load_graph", return_value={"a": ["b"]})

    with pytest.raises(ValueError, match="GITHUB_TOKEN"):
        run_check("base", "head", 1, config=config)


def test_run_check_requires_github_repo(mocker):
    config = make_config(github_repo=None)
    mocker.patch("docsync.pipeline.load_graph", return_value={"a": ["b"]})

    with pytest.raises(ValueError, match="GITHUB_REPO"):
        run_check("base", "head", 1, config=config)
