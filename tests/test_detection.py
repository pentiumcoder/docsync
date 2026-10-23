import pytest

from docsync.detection.change_filter import (
    filter_changes,
    is_python_file,
    is_test_file,
    map_change_to_chunks,
    map_chunks_to_sections,
)
from docsync.detection.diff_parser import DiffHunk, FileChange, parse_diff
from docsync.parsers.code_parser import CodeChunk

MODIFIED_DIFF = """diff --git a/src/api.py b/src/api.py
index 83db48f..bf269f4 100644
--- a/src/api.py
+++ b/src/api.py
@@ -1,2 +1,3 @@
 def foo():
-    return 1
+    return 2
+    # comment
@@ -20,1 +21,3 @@ class X:
     pass
+    x = 1
+    y = 2
"""

ADDED_DIFF = """diff --git a/pkg/new.py b/pkg/new.py
new file mode 100644
index 0000000..1111111
--- /dev/null
+++ b/pkg/new.py
@@ -0,0 +1,2 @@
+x = 1
+y = 2
"""

DELETED_DIFF = """diff --git a/gone.py b/gone.py
deleted file mode 100644
index 1111111..0000000
--- a/gone.py
+++ /dev/null
@@ -1,2 +0,0 @@
-x = 1
-y = 2
"""

RENAMED_DIFF = """diff --git a/old.py b/renamed.py
similarity index 100%
rename from old.py
rename to renamed.py
"""

RENAMED_WITH_CHANGE_DIFF = """diff --git a/old.py b/new.py
similarity index 90%
rename from old.py
rename to new.py
--- a/old.py
+++ b/new.py
@@ -1,1 +1,1 @@
-a
+b
"""

NO_NEWLINE_DIFF = """diff --git a/n.py b/n.py
--- a/n.py
+++ b/n.py
@@ -1,1 +1,1 @@
-old
+new
\\ No newline at end of file
"""

PURE_INSERTION_DIFF = """diff --git a/ins.py b/ins.py
--- a/ins.py
+++ b/ins.py
@@ -5,0 +6,2 @@
+added one
+added two
"""

PURE_DELETION_DIFF = """diff --git a/del.py b/del.py
--- a/del.py
+++ b/del.py
@@ -5,2 +4,0 @@
-removed one
-removed two
"""

BINARY_DIFF = """diff --git a/img.png b/img.png
index 1111111..2222222 100644
Binary files a/img.png and b/img.png differ
"""


def make_chunk(chunk_id, file_path, name, start_line, end_line):
    return CodeChunk(
        chunk_id=chunk_id,
        file_path=file_path,
        chunk_type="function",
        name=name,
        signature=f"def {name}():",
        docstring=None,
        body="",
        start_line=start_line,
        end_line=end_line,
    )


def make_change(file_path, change_type="modified", hunks=None, old_path=None):
    return FileChange(
        file_path=file_path,
        old_path=old_path,
        change_type=change_type,
        hunks=hunks or [],
    )


def make_hunk(new_start, new_end, added, removed=None, old_start=None, old_end=None):
    return DiffHunk(
        old_start=new_start if old_start is None else old_start,
        old_end=new_end if old_end is None else old_end,
        new_start=new_start,
        new_end=new_end,
        added_lines=added,
        removed_lines=removed or [],
    )


# --- diff_parser tests ---


def test_parse_modified_file():
    changes = parse_diff(MODIFIED_DIFF)
    assert len(changes) == 1
    change = changes[0]
    assert change.file_path == "src/api.py"
    assert change.old_path == "src/api.py"
    assert change.change_type == "modified"
    assert len(change.hunks) == 2

    first = change.hunks[0]
    assert (first.old_start, first.old_end) == (1, 2)
    assert (first.new_start, first.new_end) == (1, 3)
    assert first.added_lines == ["    return 2", "    # comment"]
    assert first.removed_lines == ["    return 1"]

    second = change.hunks[1]
    assert (second.old_start, second.old_end) == (20, 20)
    assert (second.new_start, second.new_end) == (21, 23)
    assert second.added_lines == ["    x = 1", "    y = 2"]
    assert second.removed_lines == []


def test_parse_added_file():
    changes = parse_diff(ADDED_DIFF)
    assert len(changes) == 1
    change = changes[0]
    assert change.file_path == "pkg/new.py"
    assert change.old_path is None
    assert change.change_type == "added"
    assert len(change.hunks) == 1
    hunk = change.hunks[0]
    assert (hunk.old_start, hunk.old_end) == (0, 0)
    assert (hunk.new_start, hunk.new_end) == (1, 2)
    assert hunk.added_lines == ["x = 1", "y = 2"]


def test_parse_deleted_file():
    changes = parse_diff(DELETED_DIFF)
    assert len(changes) == 1
    change = changes[0]
    assert change.file_path == "gone.py"
    assert change.old_path == "gone.py"
    assert change.change_type == "deleted"
    hunk = change.hunks[0]
    assert (hunk.old_start, hunk.old_end) == (1, 2)
    assert (hunk.new_start, hunk.new_end) == (0, 0)
    assert hunk.removed_lines == ["x = 1", "y = 2"]


def test_parse_renamed_file_without_content_change():
    changes = parse_diff(RENAMED_DIFF)
    assert len(changes) == 1
    change = changes[0]
    assert change.file_path == "renamed.py"
    assert change.old_path == "old.py"
    assert change.change_type == "renamed"
    assert change.hunks == []


def test_parse_renamed_file_with_content_change():
    changes = parse_diff(RENAMED_WITH_CHANGE_DIFF)
    change = changes[0]
    assert change.change_type == "renamed"
    assert change.file_path == "new.py"
    assert change.old_path == "old.py"
    assert len(change.hunks) == 1
    assert change.hunks[0].added_lines == ["b"]
    assert change.hunks[0].removed_lines == ["a"]


@pytest.mark.parametrize("diff_text", ["", "   \n\t\n"])
def test_parse_empty_diff(diff_text):
    assert parse_diff(diff_text) == []


def test_no_newline_marker_is_not_a_line():
    changes = parse_diff(NO_NEWLINE_DIFF)
    hunk = changes[0].hunks[0]
    assert hunk.added_lines == ["new"]
    assert hunk.removed_lines == ["old"]


def test_pure_insertion_zero_length_old_side():
    hunk = parse_diff(PURE_INSERTION_DIFF)[0].hunks[0]
    assert hunk.old_start == 5
    assert hunk.old_end == 5
    assert hunk.new_start == 6
    assert hunk.new_end == 7
    assert hunk.added_lines == ["added one", "added two"]


def test_pure_deletion_zero_length_new_side():
    hunk = parse_diff(PURE_DELETION_DIFF)[0].hunks[0]
    assert hunk.old_start == 5
    assert hunk.old_end == 6
    assert hunk.new_start == 4
    assert hunk.new_end == 4
    assert hunk.removed_lines == ["removed one", "removed two"]


def test_parse_diff_captures_hunk_section_header():
    diff = (
        "diff --git a/x.py b/x.py\n"
        "--- a/x.py\n"
        "+++ b/x.py\n"
        "@@ -1 +1 @@ def load_config():\n"
        "-    value = 1\n"
        "+    value = 2\n"
    )
    hunk = parse_diff(diff)[0].hunks[0]
    assert hunk.section_header == "def load_config():"


def test_binary_file_has_no_hunks():
    change = parse_diff(BINARY_DIFF)[0]
    assert change.file_path == "img.png"
    assert change.change_type == "modified"
    assert change.hunks == []


# --- change_filter tests ---


@pytest.mark.parametrize(
    "path, expected",
    [
        ("src/api.py", True),
        ("src/api.md", False),
        ("Dockerfile", False),
        ("notes.txt", False),
        ("img.png", False),
    ],
)
def test_is_python_file(path, expected):
    assert is_python_file(path) is expected


@pytest.mark.parametrize(
    "path, expected",
    [
        ("tests/test_api.py", True),
        ("pkg/tests/helper.py", True),
        ("src/test_api.py", True),
        ("src/api_test.py", True),
        ("conftest.py", True),
        ("src/api.py", False),
        ("src/testing.py", False),
    ],
)
def test_is_test_file(path, expected):
    assert is_test_file(path) is expected


def test_filter_drops_non_python_changes():
    changes = [
        make_change("README.md", hunks=[make_hunk(1, 1, ["text"])]),
        make_change("img.png", hunks=[]),
        make_change("src/api.py", hunks=[make_hunk(1, 1, ["x = 1"])]),
    ]
    result = filter_changes(changes)
    assert [change.file_path for change in result] == ["src/api.py"]


def test_filter_drops_test_files():
    changes = [
        make_change("tests/test_api.py", hunks=[make_hunk(1, 1, ["x = 1"])]),
        make_change("src/api_test.py", hunks=[make_hunk(1, 1, ["x = 1"])]),
        make_change("conftest.py", hunks=[make_hunk(1, 1, ["x = 1"])]),
        make_change("src/api.py", hunks=[make_hunk(1, 1, ["x = 1"])]),
    ]
    result = filter_changes(changes)
    assert [change.file_path for change in result] == ["src/api.py"]


def test_filter_drops_whitespace_only_change():
    change = make_change("src/api.py", hunks=[make_hunk(1, 1, ["   "], ["  "])])
    assert filter_changes([change]) == []


def test_filter_drops_comment_only_change():
    change = make_change(
        "src/api.py",
        hunks=[make_hunk(1, 1, ["    # new note"], ["    # old note"])],
    )
    assert filter_changes([change]) == []


def test_filter_keeps_code_change():
    change = make_change("src/api.py", hunks=[make_hunk(1, 1, ["    return 2"])])
    result = filter_changes([change])
    assert len(result) == 1
    assert result[0] == change


def test_filter_removes_only_cosmetic_hunks():
    change = make_change(
        "src/api.py",
        hunks=[
            make_hunk(1, 1, ["    # note"], ["    # old note"]),
            make_hunk(5, 5, ["    return 2"]),
        ],
    )
    result = filter_changes([change])
    assert len(result) == 1
    assert len(result[0].hunks) == 1
    assert result[0].hunks[0].added_lines == ["    return 2"]


def test_filter_keeps_deleted_cosmetic_file():
    change = make_change(
        "src/api.py",
        change_type="deleted",
        hunks=[make_hunk(1, 1, [], ["    # note"])],
    )
    assert filter_changes([change]) == [change]


def test_filter_keeps_renamed_python_file():
    change = make_change(
        "src/new.py", change_type="renamed", old_path="src/old.py"
    )
    assert filter_changes([change]) == [change]


def test_filter_keeps_rename_from_python_to_non_python():
    change = make_change("src/old.txt", change_type="renamed", old_path="src/old.py")
    assert filter_changes([change]) == [change]


# --- mapping tests ---


def test_map_change_to_chunks_by_line_overlap():
    chunks = [
        make_chunk("src/api.py::foo", "src/api.py", "foo", 1, 10),
        make_chunk("src/api.py::bar", "src/api.py", "bar", 20, 30),
    ]
    change = make_change("src/api.py", hunks=[make_hunk(1, 3, ["x = 1"])])
    mapping = map_change_to_chunks([change], chunks)
    assert [chunk.chunk_id for chunk in mapping["src/api.py"]] == ["src/api.py::foo"]


def test_map_change_to_chunks_boundary_inclusive():
    chunks = [make_chunk("src/api.py::foo", "src/api.py", "foo", 10, 20)]
    change = make_change("src/api.py", hunks=[make_hunk(1, 10, ["x = 1"])])
    mapping = map_change_to_chunks([change], chunks)
    assert mapping["src/api.py"] == chunks


def test_map_change_to_chunks_ignores_other_files():
    chunks = [make_chunk("src/other.py::foo", "src/other.py", "foo", 1, 10)]
    change = make_change("src/api.py", hunks=[make_hunk(1, 3, ["x = 1"])])
    assert map_change_to_chunks([change], chunks) == {}


def test_map_deleted_file_maps_all_chunks_by_path():
    chunks = [
        make_chunk("src/api.py::foo", "src/api.py", "foo", 1, 10),
        make_chunk("src/api.py::bar", "src/api.py", "bar", 50, 60),
        make_chunk("src/other.py::baz", "src/other.py", "baz", 1, 10),
    ]
    change = make_change("src/api.py", change_type="deleted", old_path="src/api.py")
    mapping = map_change_to_chunks([change], chunks)
    assert [chunk.chunk_id for chunk in mapping["src/api.py"]] == [
        "src/api.py::foo",
        "src/api.py::bar",
    ]


def test_map_renamed_file_maps_old_path_chunks():
    chunks = [make_chunk("src/old.py::foo", "src/old.py", "foo", 1, 10)]
    change = make_change("src/new.py", change_type="renamed", old_path="src/old.py")
    mapping = map_change_to_chunks([change], chunks)
    assert mapping["src/new.py"] == chunks


def test_map_pure_deletion_hunk_uses_old_range():
    chunks = [make_chunk("src/api.py::foo", "src/api.py", "foo", 5, 10)]
    change = make_change(
        "src/api.py",
        hunks=[make_hunk(4, 4, [], ["removed one", "removed two"], old_start=5, old_end=6)],
    )
    mapping = map_change_to_chunks([change], chunks)
    assert mapping["src/api.py"] == chunks


def test_map_chunks_to_sections_dedupes_and_sorts():
    graph = {
        "a.py::foo": ["docs/b.md##Two", "docs/a.md##One"],
        "a.py::bar": ["docs/a.md##One"],
    }
    result = map_chunks_to_sections(["a.py::foo", "a.py::bar", "a.py::missing"], graph)
    assert result == ["docs/a.md##One", "docs/b.md##Two"]


def test_map_chunks_to_sections_empty_input():
    assert map_chunks_to_sections([], {"a.py::foo": ["docs/a.md##One"]}) == []
