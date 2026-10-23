import json
import math
import os
from unittest.mock import MagicMock, patch, PropertyMock

import chromadb
import pytest

from docsync.parsers.code_parser import CodeChunk
from docsync.parsers.docs_parser import DocSection
from docsync.index.embedder import embed_texts, embed_chunk, embed_section
from docsync.index.store import ChromaStore
from docsync.index.graph import build_graph, save_graph, load_graph


# --- Helpers ---

def make_embedding(dim: int = 10, seed: float = 1.0) -> list[float]:
    """Create a deterministic unit vector of given dimension."""
    raw = [math.sin(seed * (i + 1)) for i in range(dim)]
    norm = math.sqrt(sum(x * x for x in raw))
    return [x / norm for x in raw]


def make_mock_response(embeddings: list[list[float]]):
    """Create a mock OpenAI embeddings response."""
    response = MagicMock()
    data_objects = []
    for emb in embeddings:
        obj = MagicMock()
        obj.embedding = emb
        data_objects.append(obj)
    response.data = data_objects
    return response


def make_chunk(chunk_id="src/api.py::get_user", name="get_user", file_path="src/api.py",
               chunk_type="function", signature="def get_user(user_id: int):",
               docstring="Gets a user.", body="def get_user(user_id: int):\n    return db.get(user_id)",
               start_line=1, end_line=2) -> CodeChunk:
    return CodeChunk(
        chunk_id=chunk_id, file_path=file_path, chunk_type=chunk_type,
        name=name, signature=signature, docstring=docstring, body=body,
        start_line=start_line, end_line=end_line
    )


def make_section(section_id="docs/api.md##API Reference>get_user", file_path="docs/api.md",
                 heading_path=None, level=3, content="### get_user\n\nGets a user by ID.",
                 code_references=None) -> DocSection:
    return DocSection(
        section_id=section_id, file_path=file_path,
        heading_path=heading_path or ["API Reference", "get_user"],
        level=level, content=content,
        code_references=code_references or ["get_user"]
    )


# --- Test 1: Batching ---

def test_embed_texts_batches_correctly():
    """150 texts with batch_size=100 should result in 2 API calls."""
    mock_client = MagicMock()
    dim = 10

    def side_effect(**kwargs):
        batch = kwargs.get("input", [])
        return make_mock_response([make_embedding(dim, seed=float(i + 1)) for i in range(len(batch))])

    mock_client.embeddings.create.side_effect = side_effect

    texts = [f"text_{i}" for i in range(150)]
    result = embed_texts(texts, mock_client)

    assert mock_client.embeddings.create.call_count == 2
    assert len(result) == 150
    # First call: 100 texts, second call: 50 texts
    first_call_input = mock_client.embeddings.create.call_args_list[0][1]["input"]
    second_call_input = mock_client.embeddings.create.call_args_list[1][1]["input"]
    assert len(first_call_input) == 100
    assert len(second_call_input) == 50


# --- Test 2: Retry on RateLimitError ---

@patch("docsync.index.embedder.time.sleep")
def test_embed_texts_retries_on_rate_limit(mock_sleep):
    """Fails twice with RateLimitError, succeeds on 3rd attempt."""
    from openai import RateLimitError

    mock_client = MagicMock()
    dim = 10
    success_response = make_mock_response([make_embedding(dim)])

    mock_response = MagicMock()
    mock_response.status_code = 429
    mock_response.headers = {}
    mock_response.json.return_value = {"error": {"message": "rate limited"}}

    rate_limit_error = RateLimitError(
        message="Rate limit exceeded",
        response=mock_response,
        body={"error": {"message": "rate limited"}}
    )

    mock_client.embeddings.create.side_effect = [
        rate_limit_error,
        rate_limit_error,
        success_response
    ]

    result = embed_texts(["test"], mock_client)

    assert len(result) == 1
    assert mock_client.embeddings.create.call_count == 3
    # Verify backoff was called with correct values
    assert mock_sleep.call_count == 2
    mock_sleep.assert_any_call(1)
    mock_sleep.assert_any_call(2)


# --- Test 3: Retry exhaustion ---

@patch("docsync.index.embedder.time.sleep")
def test_embed_texts_retry_exhaustion(mock_sleep):
    """Fails 3 times and then raises on the 4th attempt."""
    from openai import RateLimitError

    mock_client = MagicMock()

    mock_response = MagicMock()
    mock_response.status_code = 429
    mock_response.headers = {}
    mock_response.json.return_value = {"error": {"message": "rate limited"}}

    rate_limit_error = RateLimitError(
        message="Rate limit exceeded",
        response=mock_response,
        body={"error": {"message": "rate limited"}}
    )

    mock_client.embeddings.create.side_effect = rate_limit_error

    with pytest.raises(RateLimitError):
        embed_texts(["test"], mock_client)

    # 1 initial + 3 retries = 4 attempts total
    assert mock_client.embeddings.create.call_count == 4
    # 3 sleeps with backoff 1, 2, 4
    assert mock_sleep.call_count == 3
    mock_sleep.assert_any_call(1)
    mock_sleep.assert_any_call(2)
    mock_sleep.assert_any_call(4)


# --- Test 4: ChromaStore CodeChunk round-trip ---

def test_chroma_store_codechunk_roundtrip():
    """Upsert a CodeChunk and query it back; verify all fields are restored."""
    ephemeral_client = chromadb.EphemeralClient()
    store = ChromaStore(path="unused", client=ephemeral_client)

    chunk = make_chunk()
    emb = make_embedding(10, seed=1.0)

    store.upsert_chunks([chunk], [emb])
    results = store.query_similar_chunks(emb, n=1)

    assert len(results) == 1
    returned_chunk, distance = results[0]

    assert returned_chunk.chunk_id == chunk.chunk_id
    assert returned_chunk.file_path == chunk.file_path
    assert returned_chunk.chunk_type == chunk.chunk_type
    assert returned_chunk.name == chunk.name
    assert returned_chunk.signature == chunk.signature
    assert returned_chunk.docstring == chunk.docstring
    assert returned_chunk.body == chunk.body
    assert returned_chunk.start_line == chunk.start_line
    assert returned_chunk.end_line == chunk.end_line
    assert isinstance(distance, float)


# --- Test 5: ChromaStore DocSection round-trip + metadata serialization ---

def test_chroma_store_docsection_roundtrip_and_serialization():
    """Upsert a DocSection and query it back; verify all fields including JSON-serialized metadata."""
    ephemeral_client = chromadb.EphemeralClient()
    store = ChromaStore(path="unused", client=ephemeral_client)

    section = make_section(
        heading_path=["API Reference", "UserAPI", "get_user"],
        code_references=["get_user", "user_id", "UserAPI"]
    )
    emb = make_embedding(10, seed=2.0)

    store.upsert_sections([section], [emb])

    # Verify raw metadata is JSON-serialized
    raw_result = store.doc_sections.get(ids=[section.section_id], include=["metadatas"])
    raw_meta = raw_result["metadatas"][0]
    assert isinstance(raw_meta["heading_path"], str)
    assert isinstance(raw_meta["code_references"], str)
    assert json.loads(raw_meta["heading_path"]) == ["API Reference", "UserAPI", "get_user"]
    assert json.loads(raw_meta["code_references"]) == ["get_user", "user_id", "UserAPI"]

    # Verify query reconstruction
    results = store.query_similar_sections(emb, n=1)
    assert len(results) == 1
    returned_section, distance = results[0]

    assert returned_section.section_id == section.section_id
    assert returned_section.file_path == section.file_path
    assert returned_section.heading_path == ["API Reference", "UserAPI", "get_user"]
    assert returned_section.level == section.level
    assert returned_section.content == section.content
    assert returned_section.code_references == ["get_user", "user_id", "UserAPI"]
    assert isinstance(distance, float)


# --- Test 6: Cosine configuration ---

def test_chroma_cosine_configuration():
    """Verify both collections are created with cosine distance."""
    ephemeral_client = chromadb.EphemeralClient()
    store = ChromaStore(path="unused", client=ephemeral_client)

    code_meta = store.code_chunks.metadata
    doc_meta = store.doc_sections.metadata

    assert code_meta is not None
    assert code_meta.get("hnsw:space") == "cosine"
    assert doc_meta is not None
    assert doc_meta.get("hnsw:space") == "cosine"


# --- Test 7: build_graph heuristic ---

def test_build_graph_heuristic():
    """Chunk with name='get_user' links to section with code_references=['get_user']."""
    ephemeral_client = chromadb.EphemeralClient()
    store = ChromaStore(path="unused", client=ephemeral_client)

    chunk = make_chunk(name="get_user")
    section = make_section(code_references=["get_user"])

    # Upsert section with an embedding far from the chunk embedding
    # so semantic strategy doesn't match
    chunk_emb = make_embedding(10, seed=1.0)
    section_emb = make_embedding(10, seed=100.0)  # very different

    store.upsert_sections([section], [section_emb])

    graph = build_graph([chunk], [section], store, [chunk_emb])

    assert chunk.chunk_id in graph
    assert section.section_id in graph[chunk.chunk_id]


# --- Test 8: build_graph semantic with threshold cutoff ---

def test_build_graph_semantic_threshold():
    """
    Semantic: links chunk to section when distance < 0.18.
    Uses identical embeddings (distance=0) for the match, and very different
    embeddings (distance near 2.0) for the non-match.
    """
    ephemeral_client = chromadb.EphemeralClient()
    store = ChromaStore(path="unused", client=ephemeral_client)

    chunk = make_chunk(name="unique_name_no_heuristic_match")

    # Section that should match semantically (identical embedding → distance ≈ 0)
    close_section = make_section(
        section_id="docs/api.md##close_section",
        code_references=[]  # no heuristic match
    )
    # Section that should NOT match (very different embedding → distance >> 0.18)
    far_section = make_section(
        section_id="docs/api.md##far_section",
        code_references=[]  # no heuristic match
    )

    chunk_emb = make_embedding(10, seed=1.0)
    close_emb = make_embedding(10, seed=1.0)   # identical → distance ≈ 0
    far_emb = make_embedding(10, seed=999.0)    # very different → distance >> 0.18

    store.upsert_sections([close_section, far_section], [close_emb, far_emb])

    graph = build_graph([chunk], [close_section, far_section], store, [chunk_emb])

    assert chunk.chunk_id in graph
    assert "docs/api.md##close_section" in graph[chunk.chunk_id]
    assert "docs/api.md##far_section" not in graph[chunk.chunk_id]


# --- Test 9: build_graph merge/deduplication ---

def test_build_graph_merge_deduplication():
    """
    A chunk that matches a section via BOTH heuristic and semantic should
    have the section_id appear only once.
    """
    ephemeral_client = chromadb.EphemeralClient()
    store = ChromaStore(path="unused", client=ephemeral_client)

    chunk = make_chunk(name="get_user")
    section = make_section(
        code_references=["get_user"]  # heuristic match
    )

    # Use identical embeddings so semantic also matches (distance ≈ 0 < 0.18)
    emb = make_embedding(10, seed=1.0)

    store.upsert_sections([section], [emb])

    graph = build_graph([chunk], [section], store, [emb])

    assert chunk.chunk_id in graph
    section_ids = graph[chunk.chunk_id]
    assert section_ids.count(section.section_id) == 1


# --- Test 10: build_graph input validation ---

def test_build_graph_requires_matching_embedding_count():
    """Mismatched chunk/embedding lengths should raise a clear ValueError."""
    ephemeral_client = chromadb.EphemeralClient()
    store = ChromaStore(path="unused", client=ephemeral_client)

    chunk = make_chunk()

    with pytest.raises(
        ValueError,
        match="chunks and chunk_embeddings must have the same length",
    ):
        build_graph([chunk], [], store, [])


# --- Test 11: save_graph / load_graph roundtrip ---

def test_save_load_graph_roundtrip(tmp_path):
    """save_graph then load_graph returns identical dict."""
    graph = {
        "src/api.py::get_user": ["docs/api.md##API Reference>get_user"],
        "src/api.py::UserAPI": ["docs/api.md##API Reference>UserAPI"]
    }
    path = str(tmp_path / "docsync" / "graph.json")

    save_graph(graph, path)
    loaded = load_graph(path)

    assert loaded == graph


# --- Test 12: load_graph on missing file ---

def test_load_graph_missing_file(tmp_path):
    """load_graph on a non-existent path returns {}."""
    path = str(tmp_path / "nonexistent" / "graph.json")
    result = load_graph(path)
    assert result == {}


# --- Test 13: get_all_chunks ---

def test_get_all_chunks_roundtrip(tmp_path):
    persistent_client = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
    store = ChromaStore(path="unused", client=persistent_client)

    chunk_b = make_chunk(chunk_id="src/api.py::b", name="b")
    chunk_a = make_chunk(chunk_id="src/api.py::a", name="a")

    store.upsert_chunks(
        [chunk_b, chunk_a],
        [make_embedding(10, seed=1.0), make_embedding(10, seed=2.0)],
    )

    chunks = store.get_all_chunks()

    assert [chunk.chunk_id for chunk in chunks] == ["src/api.py::a", "src/api.py::b"]
    assert chunks[0].file_path == chunk_a.file_path
    assert chunks[0].signature == chunk_a.signature
    assert chunks[0].docstring == chunk_a.docstring
    assert chunks[0].body == chunk_a.body
    assert chunks[0].start_line == chunk_a.start_line
    assert chunks[0].end_line == chunk_a.end_line


def test_get_all_chunks_empty_store(tmp_path):
    persistent_client = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
    store = ChromaStore(path="unused", client=persistent_client)
    assert store.get_all_chunks() == []


# --- Test 14: get_sections_by_ids ---

def test_get_sections_by_ids_preserves_request_order():
    ephemeral_client = chromadb.EphemeralClient()
    store = ChromaStore(path="unused", client=ephemeral_client)

    section_a = make_section(section_id="docs/api.md##A")
    section_b = make_section(section_id="docs/api.md##B")

    store.upsert_sections(
        [section_a, section_b],
        [make_embedding(10, seed=1.0), make_embedding(10, seed=2.0)],
    )

    result = store.get_sections_by_ids(
        [section_b.section_id, section_a.section_id, "docs/missing.md##C"]
    )

    assert [section.section_id for section in result] == [
        section_b.section_id,
        section_a.section_id,
    ]
    assert result[0].content == section_b.content
    assert result[0].heading_path == section_b.heading_path
    assert result[0].code_references == section_b.code_references


def test_get_sections_by_ids_empty_input():
    ephemeral_client = chromadb.EphemeralClient()
    store = ChromaStore(path="unused", client=ephemeral_client)
    assert store.get_sections_by_ids([]) == []
