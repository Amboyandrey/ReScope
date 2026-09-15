"""Talking to the self-hosted text-embeddings-inference service — the only place that happens."""

import httpx

from app.core.config import get_settings

MODEL_NAME = "Qwen/Qwen3-Embedding-0.6B"
# The TEI backend caps concurrent requests at 4 regardless of --max-client-batch-size (found by
# actually running it — see infra/docker-compose.yml's `embeddings` service), so batches are kept
# at or under that rather than relying on TEI to reject or silently clamp an oversized one.
_BATCH_SIZE = 4
_TIMEOUT = 30.0


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed each string in `texts`, preserving order. Raises on failure — callers decide how to
    degrade (the scrape pipeline logs and continues without embeddings; search surfaces the error)."""
    if not texts:
        return []
    settings = get_settings()
    vectors: list[list[float]] = []
    async with httpx.AsyncClient(base_url=settings.embeddings_url, timeout=_TIMEOUT) as client:
        for i in range(0, len(texts), _BATCH_SIZE):
            batch = texts[i : i + _BATCH_SIZE]
            response = await client.post("/embed", json={"inputs": batch})
            response.raise_for_status()
            vectors.extend(response.json())
    return vectors


async def embed_text(text: str) -> list[float]:
    """Embed a single string — the shape a search query needs."""
    return (await embed_texts([text]))[0]
