"""Embedding client for bge-m3 via OpenAI Compatible API."""

import time
from typing import Any

import requests

from config import EMBEDDING_BATCH_SIZE, EMBEDDING_ENDPOINT, EMBEDDING_MODEL


def embed_texts(texts: list[str], batch_size: int = EMBEDDING_BATCH_SIZE) -> list[list[float]]:
    """Embed a list of texts using bge-m3.

    Args:
        texts: List of strings to embed.
        batch_size: Number of texts per API call.

    Returns:
        List of embedding vectors.
    """
    all_embeddings = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        response = requests.post(
            EMBEDDING_ENDPOINT,
            json={"model": EMBEDDING_MODEL, "input": batch},
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        embeddings = [item["embedding"] for item in data["data"]]
        all_embeddings.extend(embeddings)
        if i + batch_size < len(texts):
            time.sleep(0.1)
    return all_embeddings


def embed_text(text: str) -> list[float]:
    """Embed a single text."""
    return embed_texts([text])[0]
