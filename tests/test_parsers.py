import os
import pytest
from docsync.parsers.code_parser import parse_directory as parse_code_directory, parse_file as parse_code_file
from docsync.parsers.docs_parser import parse_directory as parse_docs_directory, parse_file as parse_docs_file

@pytest.fixture
def repo_dir(tmp_path):
    # Python source
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    
    api_py = src_dir / "api.py"
    api_py.write_text(
        "def health_check():\n"
        "    return 'ok'\n"
        "\n"
        "class UserAPI:\n"
        "    def get_user(self, user_id: int):\n"
        "        pass\n"
        "\n"
        "    async def create_user(self, name: str, email: str):\n"
        "        pass\n",
        encoding="utf-8"
    )
    
    utils_py = src_dir / "utils.py"
    utils_py.write_text(
        "def format_response(data: dict):\n"
        "    \"\"\"Formats a response dict.\"\"\"\n"
        "    return data\n",
        encoding="utf-8"
    )
    
    empty_py = src_dir / "empty.py"
    empty_py.write_text("", encoding="utf-8")
    
    imports_py = src_dir / "imports.py"
    imports_py.write_text("import os\nfrom sys import exit\n", encoding="utf-8")
    
    # Markdown source
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    
    api_md = docs_dir / "api.md"
    api_md.write_text(
        "# API Reference\n"
        "\n"
        "## UserAPI\n"
        "\n"
        "### get_user\n"
        "\n"
        "Use `get_user` with `UserAPI`.\n"
        "Call `get_user` again.\n"
        "```python\n"
        "# This is a fenced block\n"
        "```\n",
        encoding="utf-8"
    )
    
    config_md = docs_dir / "config.md"
    config_md.write_text(
        "# Configuration\n"
        "## Environment Variables\n",
        encoding="utf-8"
    )
    
    no_heading_md = docs_dir / "no_heading.md"
    no_heading_md.write_text("Just some prose.\n", encoding="utf-8")
    
    empty_md = docs_dir / "empty.md"
    empty_md.write_text("", encoding="utf-8")
    
    return tmp_path

# --- Python parser tests ---

def test_1_module_level_declarations(repo_dir):
    chunks = parse_code_file(str(repo_dir / "src" / "api.py"), str(repo_dir))
    assert len(chunks) == 4
    types = [c.chunk_type for c in chunks]
    assert types == ["function", "class", "method", "method"]
    ids = [c.chunk_id for c in chunks]
    assert "src/api.py::health_check" in ids
    assert "src/api.py::UserAPI" in ids
    assert "src/api.py::UserAPI.get_user" in ids

def test_2_complete_codechunk_fields(repo_dir):
    chunks = parse_code_file(str(repo_dir / "src" / "utils.py"), str(repo_dir))
    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.chunk_id == "src/utils.py::format_response"
    assert chunk.file_path == "src/utils.py"
    assert chunk.chunk_type == "function"
    assert chunk.name == "format_response"
    assert chunk.signature == "def format_response(data: dict):"
    assert chunk.docstring == "Formats a response dict."
    assert "return data" in chunk.body
    assert chunk.start_line == 1
    assert chunk.end_line == 3

def test_3_async_declarations(repo_dir):
    chunks = parse_code_file(str(repo_dir / "src" / "api.py"), str(repo_dir))
    create_user_chunk = next(c for c in chunks if c.name == "create_user")
    assert create_user_chunk.chunk_type == "method"

def test_4_class_and_method_relationships(repo_dir):
    chunks = parse_code_file(str(repo_dir / "src" / "api.py"), str(repo_dir))
    get_user_chunk = next(c for c in chunks if c.name == "get_user")
    assert get_user_chunk.chunk_id == "src/api.py::UserAPI.get_user"
    assert get_user_chunk.name == "get_user"

def test_5_empty_python_file(repo_dir):
    chunks = parse_code_file(str(repo_dir / "src" / "empty.py"), str(repo_dir))
    assert chunks == []

def test_6_imports_only_python_file(repo_dir):
    chunks = parse_code_file(str(repo_dir / "src" / "imports.py"), str(repo_dir))
    assert chunks == []

def test_7_deterministic_directory_parsing(repo_dir):
    chunks1 = parse_code_directory(str(repo_dir / "src"), str(repo_dir))
    chunks2 = parse_code_directory(str(repo_dir / "src"), str(repo_dir))
    assert [c.chunk_id for c in chunks1] == [c.chunk_id for c in chunks2]
    # Ensure they are sorted by path
    assert chunks1[0].file_path == "src/api.py"

# --- Markdown parser tests ---

def test_8_section_extraction(repo_dir):
    sections = parse_docs_file(str(repo_dir / "docs" / "api.md"), str(repo_dir))
    assert len(sections) == 3
    levels = [s.level for s in sections]
    assert levels == [1, 2, 3]

def test_9_heading_hierarchy(repo_dir):
    sections = parse_docs_file(str(repo_dir / "docs" / "api.md"), str(repo_dir))
    paths = [s.heading_path for s in sections]
    assert paths[0] == ["API Reference"]
    assert paths[1] == ["API Reference", "UserAPI"]
    assert paths[2] == ["API Reference", "UserAPI", "get_user"]

def test_10_complete_section_content(repo_dir):
    sections = parse_docs_file(str(repo_dir / "docs" / "api.md"), str(repo_dir))
    content = sections[-1].content
    assert "### get_user" in content
    assert "Use `get_user`" in content

def test_11_inline_code_references(repo_dir):
    sections = parse_docs_file(str(repo_dir / "docs" / "api.md"), str(repo_dir))
    refs = sections[-1].code_references
    assert "get_user" in refs
    assert "UserAPI" in refs

def test_12_duplicate_references(repo_dir):
    sections = parse_docs_file(str(repo_dir / "docs" / "api.md"), str(repo_dir))
    refs = sections[-1].code_references
    # get_user appears twice but should be in list once
    assert refs.count("get_user") == 1

def test_13_code_references_preserve_first_seen_order(repo_dir):
    sections = parse_docs_file(str(repo_dir / "docs" / "api.md"), str(repo_dir))
    refs = sections[-1].code_references
    assert refs == ["get_user", "UserAPI"]

def test_inline_code_references_ignore_double_backticks(tmp_path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    file_path = docs_dir / "double_ticks.md"
    file_path.write_text(
        "# Notes\n\nUse ``literal text`` and `actual_ref`.\n",
        encoding="utf-8",
    )

    sections = parse_docs_file(str(file_path), str(tmp_path))
    assert len(sections) == 1
    assert sections[0].code_references == ["actual_ref"]

def test_14_no_heading_document(repo_dir):
    sections = parse_docs_file(str(repo_dir / "docs" / "no_heading.md"), str(repo_dir))
    assert sections == []

def test_15_empty_markdown_file(repo_dir):
    sections = parse_docs_file(str(repo_dir / "docs" / "empty.md"), str(repo_dir))
    assert sections == []

def test_16_deterministic_directory_parsing(repo_dir):
    sections1 = parse_docs_directory(str(repo_dir / "docs"), str(repo_dir))
    sections2 = parse_docs_directory(str(repo_dir / "docs"), str(repo_dir))
    assert [s.section_id for s in sections1] == [s.section_id for s in sections2]
