import json
import chromadb
from docsync.parsers.code_parser import CodeChunk
from docsync.parsers.docs_parser import DocSection

class ChromaStore:
    def __init__(self, path: str, client: chromadb.ClientAPI | None = None):
        """
        Initializes the ChromaStore. If client is provided, uses it (useful for EphemeralClient in tests).
        Otherwise creates a PersistentClient at path.
        """
        if client is None:
            self.client = chromadb.PersistentClient(path=path)
        else:
            self.client = client
            
        self.code_chunks = self.client.get_or_create_collection(
            name="code_chunks",
            metadata={"hnsw:space": "cosine"}
        )
        
        self.doc_sections = self.client.get_or_create_collection(
            name="doc_sections",
            metadata={"hnsw:space": "cosine"}
        )
        
    def upsert_chunks(self, chunks: list[CodeChunk], embeddings: list[list[float]]):
        if not chunks:
            return
            
        ids = [c.chunk_id for c in chunks]
        documents = [c.body for c in chunks]
        metadatas = [
            {
                "chunk_id": c.chunk_id,
                "file_path": c.file_path,
                "chunk_type": c.chunk_type,
                "name": c.name,
                "signature": c.signature,
                "docstring": c.docstring if c.docstring is not None else "",
                "start_line": c.start_line,
                "end_line": c.end_line
            }
            for c in chunks
        ]
        
        self.code_chunks.upsert(
            ids=ids,
            embeddings=embeddings,
            metadatas=metadatas,
            documents=documents
        )

    def upsert_sections(self, sections: list[DocSection], embeddings: list[list[float]]):
        if not sections:
            return
            
        ids = [s.section_id for s in sections]
        documents = [s.content for s in sections]
        metadatas = [
            {
                "section_id": s.section_id,
                "file_path": s.file_path,
                "heading_path": json.dumps(s.heading_path),
                "level": s.level,
                "code_references": json.dumps(s.code_references)
            }
            for s in sections
        ]
        
        self.doc_sections.upsert(
            ids=ids,
            embeddings=embeddings,
            metadatas=metadatas,
            documents=documents
        )

    def query_similar_sections(self, embedding: list[float], n: int = 5) -> list[tuple[DocSection, float]]:
        results = self.doc_sections.query(
            query_embeddings=[embedding],
            n_results=n
        )
        
        if not results or not results["ids"] or not results["ids"][0]:
            return []
            
        sections_with_distances = []
        for i in range(len(results["ids"][0])):
            meta = results["metadatas"][0][i]
            doc = results["documents"][0][i]
            dist = results["distances"][0][i]
            
            section = DocSection(
                section_id=meta["section_id"],
                file_path=meta["file_path"],
                heading_path=json.loads(meta["heading_path"]),
                level=meta["level"],
                content=doc,
                code_references=json.loads(meta["code_references"])
            )
            sections_with_distances.append((section, dist))
            
        return sections_with_distances

    def get_all_chunks(self) -> list[CodeChunk]:
        results = self.code_chunks.get(include=["metadatas", "documents"])
        ids = results.get("ids") or []
        metadatas = results.get("metadatas") or []
        documents = results.get("documents") or []

        chunks = []
        for i in range(len(ids)):
            meta = metadatas[i]
            chunks.append(
                CodeChunk(
                    chunk_id=meta["chunk_id"],
                    file_path=meta["file_path"],
                    chunk_type=meta["chunk_type"],
                    name=meta["name"],
                    signature=meta["signature"],
                    docstring=meta["docstring"] if meta["docstring"] != "" else None,
                    body=documents[i],
                    start_line=meta["start_line"],
                    end_line=meta["end_line"],
                )
            )
        chunks.sort(key=lambda chunk: chunk.chunk_id)
        return chunks

    def get_sections_by_ids(self, section_ids: list[str]) -> list[DocSection]:
        if not section_ids:
            return []

        results = self.doc_sections.get(
            ids=section_ids, include=["metadatas", "documents"]
        )
        ids = results.get("ids") or []
        metadatas = results.get("metadatas") or []
        documents = results.get("documents") or []

        by_id: dict[str, DocSection] = {}
        for i in range(len(ids)):
            meta = metadatas[i]
            section = DocSection(
                section_id=meta["section_id"],
                file_path=meta["file_path"],
                heading_path=json.loads(meta["heading_path"]),
                level=meta["level"],
                content=documents[i],
                code_references=json.loads(meta["code_references"]),
            )
            by_id[section.section_id] = section

        return [by_id[section_id] for section_id in section_ids if section_id in by_id]

    def query_similar_chunks(self, embedding: list[float], n: int = 5) -> list[tuple[CodeChunk, float]]:
        results = self.code_chunks.query(
            query_embeddings=[embedding],
            n_results=n
        )
        
        if not results or not results["ids"] or not results["ids"][0]:
            return []
            
        chunks_with_distances = []
        for i in range(len(results["ids"][0])):
            meta = results["metadatas"][0][i]
            doc = results["documents"][0][i]
            dist = results["distances"][0][i]
            
            chunk = CodeChunk(
                chunk_id=meta["chunk_id"],
                file_path=meta["file_path"],
                chunk_type=meta["chunk_type"],
                name=meta["name"],
                signature=meta["signature"],
                docstring=meta["docstring"] if meta["docstring"] != "" else None,
                body=doc,
                start_line=meta["start_line"],
                end_line=meta["end_line"]
            )
            chunks_with_distances.append((chunk, dist))
            
        return chunks_with_distances
