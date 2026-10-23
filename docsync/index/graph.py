import json
import os
from docsync.parsers.code_parser import CodeChunk
from docsync.parsers.docs_parser import DocSection
from docsync.index.store import ChromaStore

def build_graph(
    chunks: list[CodeChunk],
    sections: list[DocSection],
    store: ChromaStore,
    chunk_embeddings: list[list[float]],
    similarity_threshold: float = 0.82
) -> dict[str, list[str]]:
    """
    Builds a graph linking chunk_id to a list of section_ids using heuristic and semantic strategies.
    No OpenAI calls are made here.
    """
    if len(chunks) != len(chunk_embeddings):
        raise ValueError(
            "chunks and chunk_embeddings must have the same length; "
            f"got {len(chunks)} chunks and {len(chunk_embeddings)} embeddings"
        )

    graph: dict[str, list[str]] = {}
    
    # Strategy 1: Heuristic (Exact Match)
    for chunk in chunks:
        chunk_id = chunk.chunk_id
        if chunk_id not in graph:
            graph[chunk_id] = []
            
        for section in sections:
            if chunk.name in section.code_references:
                graph[chunk_id].append(section.section_id)
                
    # Strategy 2: Semantic (Cosine Similarity)
    # Cosine distance = 1 - Cosine Similarity
    # We want similarity > threshold, which implies distance < (1 - threshold)
    max_distance = 1.0 - similarity_threshold
    
    for i, chunk in enumerate(chunks):
        chunk_id = chunk.chunk_id
        embedding = chunk_embeddings[i]
        
        # Query the store for the top 10 most similar sections
        results = store.query_similar_sections(embedding, n=10)
        
        for section, distance in results:
            if distance < max_distance:
                graph[chunk_id].append(section.section_id)
                
    # Deduplicate and sort
    for chunk_id in list(graph.keys()):
        unique_sections = list(set(graph[chunk_id]))
        unique_sections.sort()
        if unique_sections:
            graph[chunk_id] = unique_sections
        else:
            del graph[chunk_id]
            
    return graph

def save_graph(graph: dict[str, list[str]], path: str):
    """Saves the graph as JSON."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(graph, f, indent=2)

def load_graph(path: str) -> dict[str, list[str]]:
    """Loads the graph from JSON, returning an empty dict if not found."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
