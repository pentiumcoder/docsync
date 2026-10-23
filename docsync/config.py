import os
from dataclasses import dataclass
from dotenv import load_dotenv

@dataclass
class Config:
    openai_api_key: str
    github_token: str | None
    github_repo: str | None
    docsync_model: str
    confidence_threshold: float
    chroma_path: str
    graph_path: str

def load_config() -> Config:
    """Load configuration from environment variables."""
    load_dotenv()
    
    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        raise ValueError("Missing required env var: OPENAI_API_KEY")
        
    github_token = os.getenv("GITHUB_TOKEN")
    github_repo = os.getenv("GITHUB_REPO")
    
    docsync_model = os.getenv("DOCSYNC_MODEL", "gpt-4o-mini")
    
    confidence_threshold_str = os.getenv("CONFIDENCE_THRESHOLD", "0.8")
    try:
        confidence_threshold = float(confidence_threshold_str)
    except ValueError as exc:
        raise ValueError(
            f"Invalid CONFIDENCE_THRESHOLD value: {confidence_threshold_str}"
        ) from exc
        
    chroma_path = os.getenv("CHROMA_PATH", ".docsync/chroma")
    graph_path = os.getenv("GRAPH_PATH", ".docsync/graph.json")
    
    return Config(
        openai_api_key=openai_api_key,
        github_token=github_token,
        github_repo=github_repo,
        docsync_model=docsync_model,
        confidence_threshold=confidence_threshold,
        chroma_path=chroma_path,
        graph_path=graph_path,
    )
