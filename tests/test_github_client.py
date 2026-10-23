from unittest.mock import MagicMock

import pytest
from github import UnknownObjectException

from docsync.detection.diff_parser import parse_diff
from docsync.github_client.client import FileEdit, GitHubClient
from docsync.github_client.formatter import (
    SectionResult,
    format_fix_pr_body,
    format_no_index_comment,
    format_pr_comment,
    format_section_result,
)
from docsync.llm.rewriter import CorrectionResult
from docsync.parsers.docs_parser import DocSection


# --- helpers ---


def make_section_result(section_id="docs/api.md##get_user", status="accurate", fix_pr_url=None, issues=None):
    return SectionResult(
        section_id=section_id,
        status=status,
        fix_pr_url=fix_pr_url,
        issues=issues if issues is not None else [],
    )


def make_doc_section(section_id="docs/api.md##get_user", file_path="docs/api.md"):
    return DocSection(
        section_id=section_id,
        file_path=file_path,
        heading_path=["API Reference", "get_user"],
        level=3,
        content="### get_user",
        code_references=["get_user"],
    )


def make_correction(section_id="docs/api.md##get_user", changed_parts=None):
    return CorrectionResult(
        corrected_content="### get_user",
        confidence=0.9,
        changed_parts=changed_parts if changed_parts is not None else ["Added timeout parameter"],
        requires_human_review=False,
        section_id=section_id,
    )


def make_github_file(filename, status="modified", patch="@@ -1,1 +1,1 @@\n-old\n+new", previous_filename=None):
    file = MagicMock()
    file.filename = filename
    file.status = status
    file.patch = patch
    file.previous_filename = previous_filename
    return file


def make_client():
    github = MagicMock()
    repo = github.get_repo.return_value
    client = GitHubClient("token", "owner/repo", github=github)
    return github, repo, client


# --- formatter ---


def test_format_pr_comment_summarizes_results():
    results = [
        make_section_result("docs/a.md##ok", "accurate"),
        make_section_result(
            "docs/b.md##fixed",
            "auto-fixed",
            fix_pr_url="https://github.com/o/r/pull/2",
        ),
        make_section_result(
            "docs/c.md##stale",
            "flagged",
            issues=["Missing timeout parameter", "Wrong return type"],
        ),
    ]

    body = format_pr_comment(results)

    assert "Checked **3** affected documentation section(s)" in body
    assert "**1** accurate" in body
    assert "**1** auto-fixed" in body
    assert "**1** flagged" in body
    assert "docs/a.md##ok" in body
    assert "docs/b.md##fixed" in body
    assert "https://github.com/o/r/pull/2" in body
    assert "docs/c.md##stale" in body
    assert "Missing timeout parameter" in body
    assert "Wrong return type" in body


def test_format_pr_comment_with_no_results():
    body = format_pr_comment([])
    assert "Checked **0**" in body
    assert "No affected documentation sections were found." in body


def test_format_pr_comment_escapes_pipes():
    result = make_section_result("docs/a.md##a|b", "flagged", issues=["a|b"])
    body = format_pr_comment([result])
    assert "a\\|b" in body


def test_format_section_result_accurate():
    assert format_section_result(make_section_result()) == "- `docs/api.md##get_user` — accurate"


def test_format_section_result_auto_fixed_with_url():
    result = make_section_result(status="auto-fixed", fix_pr_url="https://github.com/o/r/pull/3")
    text = format_section_result(result)
    assert "auto-fixed" in text
    assert "https://github.com/o/r/pull/3" in text


def test_format_section_result_auto_fixed_without_url():
    result = make_section_result(status="auto-fixed")
    assert "auto-fixed" in format_section_result(result)


def test_format_section_result_flagged():
    result = make_section_result(status="flagged", issues=["Issue one", "Issue two"])
    text = format_section_result(result)
    assert "flagged for review" in text
    assert "Issue one; Issue two" in text


def test_format_fix_pr_body_uses_corrections_and_sections():
    corrections = [make_correction()]
    sections = [make_doc_section()]

    body = format_fix_pr_body(corrections, sections)

    assert "DocSync detected as stale" in body
    assert "docs/api.md##get_user" in body
    assert "docs/api.md" in body
    assert "Added timeout parameter" in body


def test_format_fix_pr_body_fallback_when_no_changed_parts():
    corrections = [make_correction(changed_parts=[])]
    body = format_fix_pr_body(corrections, [])
    assert "Updated to match the current implementation." in body


def test_format_no_index_comment():
    body = format_no_index_comment()
    assert ".docsync/" in body
    assert "docsync index" in body


# --- client construction ---


def test_client_gets_repo():
    github = MagicMock()
    GitHubClient("token", "owner/repo", github=github)
    github.get_repo.assert_called_once_with("owner/repo")


def test_client_creates_github_when_not_injected(mocker):
    fake_github = MagicMock()
    fake_class = mocker.patch("docsync.github_client.client.Github", return_value=fake_github)

    GitHubClient("secret-token", "owner/repo")

    fake_class.assert_called_once_with("secret-token")
    fake_github.get_repo.assert_called_once_with("owner/repo")


# --- get_diff ---


def test_get_diff_modified_file_parses_as_modified():
    github, repo, client = make_client()
    repo.compare.return_value.files = [
        make_github_file("src/api.py", status="modified", patch="@@ -1,1 +1,1 @@\n-old\n+new")
    ]

    diff_text = client.get_diff("base", "head")
    changes = parse_diff(diff_text)

    repo.compare.assert_called_once_with("base", "head")
    assert len(changes) == 1
    assert changes[0].file_path == "src/api.py"
    assert changes[0].change_type == "modified"


def test_get_diff_added_file_parses_as_added():
    github, repo, client = make_client()
    repo.compare.return_value.files = [
        make_github_file("pkg/new.py", status="added", patch="@@ -0,0 +1,2 @@\n+a\n+b")
    ]

    changes = parse_diff(client.get_diff("base", "head"))

    assert changes[0].change_type == "added"
    assert changes[0].old_path is None
    assert changes[0].hunks[0].added_lines == ["a", "b"]


def test_get_diff_removed_file_parses_as_deleted():
    github, repo, client = make_client()
    repo.compare.return_value.files = [
        make_github_file("pkg/gone.py", status="removed", patch="@@ -1,2 +0,0 @@\n-a\n-b")
    ]

    changes = parse_diff(client.get_diff("base", "head"))

    assert changes[0].change_type == "deleted"
    assert changes[0].file_path == "pkg/gone.py"
    assert changes[0].hunks[0].removed_lines == ["a", "b"]


def test_get_diff_renamed_file_parses_as_renamed():
    github, repo, client = make_client()
    repo.compare.return_value.files = [
        make_github_file(
            "pkg/new.py",
            status="renamed",
            previous_filename="pkg/old.py",
            patch="@@ -1,1 +1,1 @@\n-a\n+b",
        )
    ]

    changes = parse_diff(client.get_diff("base", "head"))

    assert changes[0].change_type == "renamed"
    assert changes[0].file_path == "pkg/new.py"
    assert changes[0].old_path == "pkg/old.py"


def test_get_diff_pure_rename_without_patch_is_kept():
    github, repo, client = make_client()
    repo.compare.return_value.files = [
        make_github_file(
            "pkg/new.py",
            status="renamed",
            previous_filename="pkg/old.py",
            patch=None,
        )
    ]

    changes = parse_diff(client.get_diff("base", "head"))

    assert len(changes) == 1
    assert changes[0].change_type == "renamed"
    assert changes[0].hunks == []


def test_get_diff_skips_files_without_patch():
    github, repo, client = make_client()
    repo.compare.return_value.files = [
        make_github_file("img.png", status="modified", patch=None),
        make_github_file("src/api.py", status="modified", patch="@@ -1,1 +1,1 @@\n-a\n+b"),
    ]

    diff_text = client.get_diff("base", "head")

    assert "img.png" not in diff_text
    assert "src/api.py" in diff_text


def test_get_diff_multiple_files_concatenated():
    github, repo, client = make_client()
    repo.compare.return_value.files = [
        make_github_file("src/a.py", status="modified", patch="@@ -1,1 +1,1 @@\n-a\n+b"),
        make_github_file("src/b.py", status="modified", patch="@@ -2,1 +2,1 @@\n-c\n+d"),
    ]

    changes = parse_diff(client.get_diff("base", "head"))

    assert [change.file_path for change in changes] == ["src/a.py", "src/b.py"]


# --- post_comment ---


def test_post_comment_returns_url():
    github, repo, client = make_client()
    pull = repo.get_pull.return_value
    pull.create_issue_comment.return_value.html_url = "https://github.com/o/r/pull/1#issuecomment-1"

    url = client.post_comment(7, "hello")

    repo.get_pull.assert_called_once_with(7)
    pull.create_issue_comment.assert_called_once_with("hello")
    assert url == "https://github.com/o/r/pull/1#issuecomment-1"


def test_get_pr_base_branch():
    github, repo, client = make_client()
    repo.get_pull.return_value.base.ref = "main"

    assert client.get_pr_base_branch(11) == "main"
    repo.get_pull.assert_called_once_with(11)


# --- create_fix_pr ---


def test_create_fix_pr_creates_branch_and_pr_with_new_file():
    github, repo, client = make_client()
    repo.get_git_ref.return_value.object.sha = "base-sha"
    repo.get_contents.side_effect = UnknownObjectException(status=404, data={"message": "Not Found"})
    repo.create_pull.return_value.html_url = "https://github.com/o/r/pull/9"

    edits = [FileEdit("docs/api.md", "new content")]
    url = client.create_fix_pr("main", edits, "Fix docs", "Body text")

    repo.get_git_ref.assert_called_once_with("heads/main")
    ref_kwargs = repo.create_git_ref.call_args[1]
    assert ref_kwargs["sha"] == "base-sha"
    assert ref_kwargs["ref"].startswith("refs/heads/docsync/fix-")
    branch_name = ref_kwargs["ref"].replace("refs/heads/", "")

    repo.create_file.assert_called_once()
    create_kwargs = repo.create_file.call_args[1]
    assert create_kwargs["path"] == "docs/api.md"
    assert create_kwargs["content"] == "new content"
    assert create_kwargs["branch"] == branch_name
    repo.update_file.assert_not_called()

    repo.create_pull.assert_called_once()
    pull_kwargs = repo.create_pull.call_args[1]
    assert pull_kwargs["title"] == "Fix docs"
    assert pull_kwargs["body"] == "Body text"
    assert pull_kwargs["head"] == branch_name
    assert pull_kwargs["base"] == "main"
    assert url == "https://github.com/o/r/pull/9"


def test_create_fix_pr_updates_existing_file():
    github, repo, client = make_client()
    repo.get_git_ref.return_value.object.sha = "base-sha"
    existing = MagicMock()
    existing.sha = "file-sha"
    repo.get_contents.return_value = existing
    repo.create_pull.return_value.html_url = "https://github.com/o/r/pull/10"

    client.create_fix_pr("main", [FileEdit("docs/api.md", "updated")], "t", "b")

    repo.update_file.assert_called_once()
    update_kwargs = repo.update_file.call_args[1]
    assert update_kwargs["path"] == "docs/api.md"
    assert update_kwargs["content"] == "updated"
    assert update_kwargs["sha"] == "file-sha"
    repo.create_file.assert_not_called()


def test_create_fix_pr_requires_edits():
    github, repo, client = make_client()
    with pytest.raises(ValueError, match="at least one file edit"):
        client.create_fix_pr("main", [], "t", "b")
