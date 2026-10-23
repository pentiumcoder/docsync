import os
import re
from dataclasses import dataclass

@dataclass
class DocSection:
    section_id: str
    file_path: str
    heading_path: list[str]
    level: int
    content: str
    code_references: list[str]

def parse_file(file_path: str, docs_root: str) -> list[DocSection]:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        raise ValueError(f"Failed to read file: {file_path}")

    if not lines:
        return []

    rel_path = os.path.relpath(file_path, docs_root).replace("\\", "/")
    
    sections = []
    heading_stack = []
    
    current_heading_path = []
    current_level = 0
    current_content = []
    
    in_fenced_code = False
    
    def extract_code_references(content_lines):
        text = "".join(content_lines)
        # Remove fenced blocks first, then collect only single-backtick inline spans.
        text_without_fenced = re.sub(r"```.*?```|~~~.*?~~~", "", text, flags=re.DOTALL)

        matches = re.findall(r"(?<!`)`([^`\n]+)`(?!`)", text_without_fenced)
        
        # Deduplicate while preserving order
        seen = set()
        refs = []
        for match in matches:
            if match not in seen:
                seen.add(match)
                refs.append(match)
        return refs

    def save_section():
        if current_content and current_heading_path:
            section_id = f"{rel_path}##{'>'.join(current_heading_path)}"
            sections.append(DocSection(
                section_id=section_id,
                file_path=rel_path,
                heading_path=list(current_heading_path),
                level=current_level,
                content="".join(current_content),
                code_references=extract_code_references(current_content)
            ))

    has_headings = False

    for line in lines:
        # Check for fenced code block toggle
        if line.lstrip().startswith("```") or line.lstrip().startswith("~~~"):
            in_fenced_code = not in_fenced_code
            current_content.append(line)
            continue
            
        match = re.match(r"^(#{1,6})\s+(.*)$", line)
        if match and not in_fenced_code:
            has_headings = True
            save_section()
            
            level = len(match.group(1))
            heading_text = match.group(2).strip()
            
            # Update heading stack
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
                
            heading_stack.append((level, heading_text))
            
            current_level = level
            current_heading_path = [text for lvl, text in heading_stack]
            current_content = [line]
        else:
            current_content.append(line)
            
    save_section()

    if not has_headings:
        return []

    return sections

def parse_directory(directory: str, docs_root: str) -> list[DocSection]:
    sections = []
    
    files_to_parse = []
    for root, dirs, files in os.walk(directory):
        # Skip hidden dirs and irrelevant ones
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in {"__pycache__", "venv", ".venv"}]
        
        for file in files:
            if file.endswith(".md"):
                files_to_parse.append(os.path.join(root, file))
                
    files_to_parse.sort()
    
    for file_path in files_to_parse:
        sections.extend(parse_file(file_path, docs_root))
        
    return sections
