"""
rag_ingestion.tasks.build_embeddings
----------------------------------------
Reads enriched chunks from MinIO and embeds them.

Production backend : OpenAI embeddings API directly (text-embedding-3-large,
                      1024-dim to match agents/rag_flow.py's stated
                      embedding dimension), batched, with usage logged via
                      gates_ai_common.observability.log_usage.
Fallback backend    : sentence-transformers all-MiniLM-L6-v2, 384-dim,
                      run locally -- no API call, no usage to log.

Also builds a BM25-style sparse vector per chunk (rag_ingestion.common.
sparse_vectors) alongside the dense embedding, for query-time hybrid
dense+sparse retrieval (see load_qdrant.py and query_engine.py).
"""
from __future__ import annotations

import json

from gates_ai_common.observability import log_usage
from rag_ingestion.clients import minio_client
from rag_ingestion.common.keys import stage_key
from rag_ingestion.common.schemas import EmbeddingRecord, EnrichedChunk
from rag_ingestion.common.sparse_vectors import build_sparse_vector
from rag_ingestion.config import EMBEDDING_MODEL, MINIO_BUCKET, USE_LIVE_EMBEDDINGS

_OPENAI_BATCH_SIZE = 100
_OPENAI_PRICE_PER_1K_INPUT = 0.00013
_DEV_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
_DEV_DIMS = 384
_LIVE_DIMS = 1024


def _build_payload(chunk: EnrichedChunk, prev: dict) -> dict:
    payload = chunk.to_dict()
    payload["doc_id"] = prev["doc_id"]
    payload["parsed_key"] = prev.get("parsed_key")
    payload["chunked_key"] = prev.get("chunked_key")
    payload["metadata_key"] = prev.get("metadata_key")
    return payload


def _embed_live(texts: list[str]) -> list[list[float]]:
    from openai import OpenAI
    from rag_ingestion.config import EMBEDDING_DIMENSIONS

    client = OpenAI()
    vectors: list[list[float]] = []
    for start in range(0, len(texts), _OPENAI_BATCH_SIZE):
        batch = texts[start:start + _OPENAI_BATCH_SIZE]
        response = client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=batch,
            dimensions=EMBEDDING_DIMENSIONS,
        )
        vectors.extend(item.embedding for item in response.data)
        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "prompt_tokens", None) or getattr(usage, "total_tokens", 0) or 0
        log_usage(
            agent_path="rag_ingestion.build_embeddings",
            input_tokens=input_tokens,
            output_tokens=0,
            model=EMBEDDING_MODEL,
            price_per_1k_input=_OPENAI_PRICE_PER_1K_INPUT,
            price_per_1k_output=0.0,
        )
    return vectors


def _embed_dev(texts: list[str]) -> list[list[float]]:
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer("all-MiniLM-L6-v2")
    embeddings = model.encode(texts, convert_to_numpy=True)
    return [vec.tolist() for vec in embeddings]


def run(prev: dict) -> dict:
    bucket = prev.get("bucket", MINIO_BUCKET)
    doc_id = prev["doc_id"]
    metadata_key = prev["metadata_key"]

    raw_jsonl = minio_client.get_object_bytes(bucket, metadata_key).decode("utf-8", errors="replace")
    enriched_chunks = [EnrichedChunk.from_dict(json.loads(line)) for line in raw_jsonl.splitlines() if line.strip()]

    texts = [c.text for c in enriched_chunks]

    if USE_LIVE_EMBEDDINGS:
        vectors = _embed_live(texts)
        embedding_dims = _LIVE_DIMS
    else:
        vectors = _embed_dev(texts)
        embedding_dims = _DEV_DIMS

    records = []
    for chunk, vector in zip(enriched_chunks, vectors):
        sparse_indices, sparse_values = build_sparse_vector(chunk.text)
        records.append(
            EmbeddingRecord(
                chunk_index=chunk.chunk_index,
                vector=vector,
                payload=_build_payload(chunk, prev),
                sparse_indices=sparse_indices,
                sparse_values=sparse_values,
            )
        )

    embeddings_key = stage_key("embeddings", doc_id, "embeddings.jsonl")
    jsonl = "\n".join(json.dumps(r.to_dict()) for r in records)
    minio_client.put_object_text(bucket, embeddings_key, jsonl)

    return {
        **prev,
        "embeddings_key": embeddings_key,
        "vector_count": len(records),
        "embedding_dims": embedding_dims,
    }
