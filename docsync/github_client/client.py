from dataclasses import dataclass
from uuid import uuid4

from github import Github, UnknownObjectException


@dataclass
class FileEdit:
    file_path: str
    new_content: str


class GitHubClient:
    def __init__(self, token: str, repo_name: str, github: Github | None = None):
        self._github = github if github is not None else Github(token)
        self.repo_name = repo_name
        self.repo = self._github.get_repo(repo_name)

    def get_diff(self, base_ref: str, head_ref: str) -> str:
        comparison = self.repo.compare(base_ref, head_ref)
        parts: list[str] = []
        for file in comparison.files:
            is_rename = file.status == "renamed"
            if not file.patch and not is_rename:
                continue
            parts.append(self._format_file_diff(file))
        return "".join(parts)

    @staticmethod
    def _format_file_diff(file) -> str:
        old_path = file.previous_filename or file.filename
        header = [f"diff --git a/{old_path} b/{file.filename}"]

        if file.status == "added":
            header.extend(
                [
                    "new file mode 100644",
                    "--- /dev/null",
                    f"+++ b/{file.filename}",
                ]
            )
        elif file.status == "removed":
            header.extend(
                [
                    "deleted file mode 100644",
                    f"--- a/{old_path}",
                    "+++ /dev/null",
                ]
            )
        elif file.status == "renamed":
            header.extend(
                [
                    f"rename from {old_path}",
                    f"rename to {file.filename}",
                ]
            )
            if file.patch:
                header.extend([f"--- a/{old_path}", f"+++ b/{file.filename}"])
        else:
            header.extend([f"--- a/{old_path}", f"+++ b/{file.filename}"])

        if not file.patch:
            return "\n".join(header) + "\n"

        patch = file.patch.rstrip("\n")
        return "\n".join(header) + "\n" + patch + "\n"

    def post_comment(self, pr_number: int, body: str) -> str:
        pull = self.repo.get_pull(pr_number)
        comment = pull.create_issue_comment(body)
        return comment.html_url

    def get_pr_base_branch(self, pr_number: int) -> str:
        return self.repo.get_pull(pr_number).base.ref

    def create_fix_pr(
        self,
        base_branch: str,
        edits: list[FileEdit],
        title: str,
        body: str,
    ) -> str:
        if not edits:
            raise ValueError("create_fix_pr requires at least one file edit")

        base_ref = self.repo.get_git_ref(f"heads/{base_branch}")
        base_sha = base_ref.object.sha

        branch_name = f"docsync/fix-{uuid4().hex[:8]}"
        self.repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=base_sha)

        for edit in edits:
            self._write_file(edit, branch_name)

        pull = self.repo.create_pull(
            title=title,
            body=body,
            head=branch_name,
            base=base_branch,
        )
        return pull.html_url

    def _write_file(self, edit: FileEdit, branch_name: str) -> None:
        message = f"docsync: update {edit.file_path}"
        try:
            existing = self.repo.get_contents(edit.file_path, ref=branch_name)
        except UnknownObjectException:
            self.repo.create_file(
                path=edit.file_path,
                message=message,
                content=edit.new_content,
                branch=branch_name,
            )
            return

        self.repo.update_file(
            path=edit.file_path,
            message=message,
            content=edit.new_content,
            sha=existing.sha,
            branch=branch_name,
        )
