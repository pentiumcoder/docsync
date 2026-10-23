from docsync.detection.diff_parser import DiffHunk, FileChange
from docsync.parsers.code_parser import CodeChunk

_TEST_DIR_NAMES = {"test", "tests", "__tests__"}


def is_python_file(path: str) -> bool:
    return path.endswith(".py")


def is_test_file(path: str) -> bool:
    normalized = path.replace("\\", "/")
    parts = [part for part in normalized.split("/") if part]
    if not parts:
        return False
    file_name = parts[-1]
    directory_parts = parts[:-1]
    if any(part in _TEST_DIR_NAMES for part in directory_parts):
        return True
    if file_name == "conftest.py":
        return True
    if file_name.startswith("test_") and file_name.endswith(".py"):
        return True
    if file_name.endswith("_test.py"):
        return True
    return False


def _is_cosmetic_line(text: str) -> bool:
    stripped = text.strip()
    return stripped == "" or stripped.startswith("#")


def _is_cosmetic_hunk(hunk: DiffHunk) -> bool:
    return all(_is_cosmetic_line(line) for line in hunk.added_lines) and all(
        _is_cosmetic_line(line) for line in hunk.removed_lines
    )


def _relevant_paths(change: FileChange) -> list[str]:
    paths = [change.file_path]
    if change.change_type in ("deleted", "renamed") and change.old_path:
        paths.append(change.old_path)
    return paths


def filter_changes(changes: list[FileChange]) -> list[FileChange]:
    filtered: list[FileChange] = []
    for change in changes:
        paths = _relevant_paths(change)
        if not any(is_python_file(path) for path in paths):
            continue
        if all(is_test_file(path) for path in paths):
            continue

        if change.change_type in ("deleted", "renamed"):
            filtered.append(change)
            continue

        meaningful_hunks = [hunk for hunk in change.hunks if not _is_cosmetic_hunk(hunk)]
        if not meaningful_hunks:
            continue
        filtered.append(
            FileChange(
                file_path=change.file_path,
                old_path=change.old_path,
                change_type=change.change_type,
                hunks=meaningful_hunks,
            )
        )
    return filtered


def _overlaps(chunk: CodeChunk, hunk: DiffHunk) -> bool:
    if hunk.new_start <= chunk.end_line and hunk.new_end >= chunk.start_line:
        return True
    if hunk.new_start == hunk.new_end:
        return hunk.old_start <= chunk.end_line and hunk.old_end >= chunk.start_line
    return False


def map_change_to_chunks(
    changes: list[FileChange], chunks: list[CodeChunk]
) -> dict[str, list[CodeChunk]]:
    mapping: dict[str, list[CodeChunk]] = {}
    for change in changes:
        if change.change_type == "deleted":
            matched = [chunk for chunk in chunks if chunk.file_path == change.file_path]
        elif change.change_type == "renamed":
            old_path = change.old_path or change.file_path
            matched = [chunk for chunk in chunks if chunk.file_path == old_path]
        else:
            matched = [
                chunk
                for chunk in chunks
                if chunk.file_path == change.file_path
                and any(_overlaps(chunk, hunk) for hunk in change.hunks)
            ]
        if matched:
            mapping[change.file_path] = matched
    return mapping


def map_chunks_to_sections(
    chunk_ids: list[str], graph: dict[str, list[str]]
) -> list[str]:
    section_ids: set[str] = set()
    for chunk_id in chunk_ids:
        section_ids.update(graph.get(chunk_id, []))
    return sorted(section_ids)
