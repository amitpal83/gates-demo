"""OpenAI SDK wrapper for chat and embeddings. Reads OPENAI_API_KEY / OPENAI_BASE_URL from the environment, so a gateway such as Portkey is a config change (plus LIC_LLM_DEFAULT_HEADERS)."""
from __future__ import annotations

import json

from ontology_graph import config

_EMBED_BATCH = 100


def _client():
    from openai import OpenAI

    headers = json.loads(config.LLM_DEFAULT_HEADERS) if config.LLM_DEFAULT_HEADERS else None
    return OpenAI(default_headers=headers)


def complete(system: str, user: str, json_mode: bool = False) -> str:
    kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
    response = _client().chat.completions.create(
        model=config.LLM_MODEL,
        temperature=0,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        **kwargs,
    )
    return response.choices[0].message.content or ""


def embed(texts: list[str]) -> list[list[float]]:
    client = _client()
    vectors: list[list[float]] = []
    for start in range(0, len(texts), _EMBED_BATCH):
        response = client.embeddings.create(
            model=config.EMBEDDING_MODEL,
            input=texts[start:start + _EMBED_BATCH],
            dimensions=config.EMBEDDING_DIMENSIONS,
        )
        vectors.extend(item.embedding for item in response.data)
    return vectors
