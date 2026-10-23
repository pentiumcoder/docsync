from dataclasses import dataclass
from typing import Literal

from unidiff import PatchSet
from unidiff.errors import UnidiffParseError

ChangeType = Literal["added", "modified", "deleted", "renamed"]


@dataclass
class DiffHunk:
    old_start: int
    old_end: int
    new_start: int
    new_end: int
    added_lines: list[str]
    removed_lines: list[str]


@dataclass
class FileChange:
    file_path: str
    old_path: str | None
    change_type: ChangeType
    hunks: list[DiffHunk]


def _strip_prefix(path: str | None) -> str | None:
    if not path or path == "/dev/null":
        return None
    if path.startswith("a/") or path.startswith("b/"):
        return path[2:]
    return path


def _line_text(line) -> str:
    value = line.value
    if value.endswith("\n"):
        value = value[:-1]
    if value.endswith("\r"):
        value = value[:-1]
    return value


def _change_type(patched_file) -> ChangeType:
    if patched_file.is_removed_file:
        return "deleted"
    if patched_file.is_added_file:
        return "added"
    if patched_file.is_rename:
        return "renamed"
    return "modified"


def _build_hunk(hunk) -> DiffHunk:
    old_start = hunk.source_start
    new_start = hunk.target_start
    old_end = old_start + max(hunk.source_length - 1, 0)
    new_end = new_start + max(hunk.target_length - 1, 0)
    added_lines = [_line_text(line) for line in hunk if line.is_added]
    removed_lines = [_line_text(line) for line in hunk if line.is_removed]
    return DiffHunk(
        old_start=old_start,
        old_end=old_end,
        new_start=new_start,
        new_end=new_end,
        added_lines=added_lines,
        removed_lines=removed_lines,
    )


def parse_diff(diff_text: str) -> list[FileChange]:
    if not diff_text or not diff_text.strip():
        return []

    try:
        patch = PatchSet(diff_text)
    except UnidiffParseError as exc:
        raise ValueError(f"Failed to parse diff: {exc}")

    changes: list[FileChange] = []
    for patched_file in patch:
        change_type = _change_type(patched_file)
        file_path = _strip_prefix(patched_file.path) or (patched_file.path or "")
        old_path = None if change_type == "added" else _strip_prefix(patched_file.source_file)
        hunks = [_build_hunk(hunk) for hunk in patched_file]
        changes.append(
            FileChange(
                file_path=file_path,
                old_path=old_path,
                change_type=change_type,
                hunks=hunks,
            )
        )
    return changes
