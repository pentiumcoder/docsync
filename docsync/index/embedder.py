import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openai import OpenAI

def embed_texts(
    texts: list[str],
    client: "OpenAI",
    model: str = "text-embedding-3-small",
) -> list[list[float]]:
    """Embeds a list of texts in batches of 100."""
    from openai import RateLimitError
    
    all_embeddings = []
    batch_size = 100
    
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        
        # Retry logic: max 3 retries (4 attempts total)
        # Backoff: 1s, 2s, 4s
        backoffs = [1, 2, 4]
        attempts = 0
        success = False
        
        while not success and attempts <= len(backoffs):
            try:
                response = client.embeddings.create(
                    input=batch,
                    model=model
                )
                batch_embeddings = [data.embedding for data in response.data]
                all_embeddings.extend(batch_embeddings)
                success = True
            except RateLimitError as e:
                if attempts < len(backoffs):
                    time.sleep(backoffs[attempts])
                    attempts += 1
                else:
                    raise
                    
    return all_embeddings

def embed_chunk(
    signature: str,
    docstring: str | None,
    body: str,
    client: "OpenAI",
    model: str = "text-embedding-3-small",
) -> list[float]:
    """Embeds a CodeChunk using primitive strings."""
    text = f"{signature}\n{docstring or ''}\n{body[:500]}"
    return embed_texts([text], client, model)[0]

def embed_section(
    content: str,
    client: "OpenAI",
    model: str = "text-embedding-3-small",
) -> list[float]:
    """Embeds a DocSection using primitive strings."""
    return embed_texts([content], client, model)[0]
