import ast
import os
from dataclasses import dataclass
from typing import Literal

@dataclass
class CodeChunk:
    chunk_id: str
    file_path: str
    chunk_type: Literal["function", "class", "method"]
    name: str
    signature: str
    docstring: str | None
    body: str
    start_line: int
    end_line: int

def parse_file(file_path: str, repo_root: str) -> list[CodeChunk]:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            source = f.read()
    except Exception:
        raise ValueError(f"Failed to read file: {file_path}")

    if not source.strip():
        return []

    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        raise ValueError(f"Failed to parse {file_path}: {e}")

    source_lines = source.splitlines()
    chunks = []
    
    # helper to get signature
    def get_signature(node, source_lines):
        # The AST doesn't strictly delimit the end of the header easily when there are decorators,
        # multiline args, etc.
        # But we can find the def/class line by finding where the colon is before the body starts.
        start_lineno = node.lineno
        # If there are decorators, we might want to include them, but `node.lineno` is usually the def/class line 
        # EXCEPT in Python < 3.8 where decorators messed it up. We are on >= 3.10.
        # Actually node.lineno for ClassDef/FunctionDef is the line with `class` or `def`.
        # The body starts at node.body[0].lineno.
        end_lineno = node.body[0].lineno - 1
        
        # If the body is on the same line: def foo(): pass
        if start_lineno == node.body[0].lineno:
            # We just take the text up to the colon. We can use ast.get_source_segment for the whole node
            # and then split by colon, but that's fragile.
            # Let's extract the header from source_lines
            line = source_lines[start_lineno - 1]
            idx = line.find(":")
            if idx != -1:
                return line[:idx+1]
            return line
            
        header_lines = source_lines[start_lineno - 1:end_lineno]
        # Remove docstring if it was somehow caught in between? No, docstring is in body.
        # Clean up any trailing comments or empty lines that aren't part of the header.
        return "\n".join(header_lines).rstrip()

    def get_body_text(node, source_lines):
        # We need the full source of the node, including decorators.
        # node.lineno is the start of the def/class. Decorators start at node.decorator_list[0].lineno
        body_start_line = node.lineno
        if hasattr(node, "decorator_list") and node.decorator_list:
            body_start_line = node.decorator_list[0].lineno
        end_line = node.end_lineno
        return "\n".join(source_lines[body_start_line - 1:end_line]), end_line

    rel_path = os.path.relpath(file_path, repo_root).replace("\\", "/")

    has_non_imports = False

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            has_non_imports = True
            
            chunk_type = "class" if isinstance(node, ast.ClassDef) else "function"
            name = node.name
            signature = get_signature(node, source_lines)
            docstring = ast.get_docstring(node)
            body_text, end_line = get_body_text(node, source_lines)
            
            chunk_id = f"{rel_path}::{name}"
            
            chunks.append(CodeChunk(
                chunk_id=chunk_id,
                file_path=rel_path,
                chunk_type=chunk_type,
                name=name,
                signature=signature,
                docstring=docstring,
                body=body_text,
                start_line=node.lineno,
                end_line=end_line
            ))
            
            if isinstance(node, ast.ClassDef):
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        method_name = child.name
                        m_signature = get_signature(child, source_lines)
                        m_docstring = ast.get_docstring(child)
                        m_body_text, m_end_line = get_body_text(child, source_lines)
                        
                        m_chunk_id = f"{rel_path}::{name}.{method_name}"
                        
                        chunks.append(CodeChunk(
                            chunk_id=m_chunk_id,
                            file_path=rel_path,
                            chunk_type="method",
                            name=method_name,
                            signature=m_signature,
                            docstring=m_docstring,
                            body=m_body_text,
                            start_line=child.lineno,
                            end_line=m_end_line
                        ))
        elif not isinstance(node, (ast.Import, ast.ImportFrom)):
            has_non_imports = True

    if not has_non_imports:
        return []

    return chunks

def parse_directory(directory: str, repo_root: str) -> list[CodeChunk]:
    chunks = []
    
    # To ensure deterministic parsing order
    files_to_parse = []
    for root, dirs, files in os.walk(directory):
        # Skip irrelevant dirs
        dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", ".venv", "venv"}]
        
        for file in files:
            if file.endswith(".py"):
                files_to_parse.append(os.path.join(root, file))
                
    files_to_parse.sort()
    
    for file_path in files_to_parse:
        chunks.extend(parse_file(file_path, repo_root))
        
    return chunks
