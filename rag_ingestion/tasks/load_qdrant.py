"""
rag_ingestion.tasks.load_qdrant
-----------------------------------
Reads the embeddings JSONL from MinIO and upserts into Qdrant, choosing
the prod (1024-dim) or dev (384-dim) collection based on the embedding
dimensionality actually produced upstream. Idempotent: any stale points
for this doc_id are deleted before the fresh batch is upserted, so
re-running ingestion for the same document doesn't leave orphaned points
from a previous chunking.

Each point carries both the dense embedding and the BM25-style sparse
vector build_embeddings.py computed, as two named vectors ("dense" /
"sparse") -- see qdrant_client_helper.ensure_collection -- so
query_engine.py's hybrid_search() can fuse both in one call at query time.
"""
from __future__ import annotations

import json

from rag_ingestion.clients import minio_client, qdrant_client_helper
from rag_ingestion.common.keys import deterministic_point_id
from rag_ingestion.common.schemas import EmbeddingRecord
from rag_ingestion.config import MINIO_BUCKET, QDRANT_COLLECTION, QDRANT_COLLECTION_DEV


def run(prev: dict) -> dict:
    bucket = prev.get("bucket", MINIO_BUCKET)
    doc_id = prev["doc_id"]
    embeddings_key = prev["embeddings_key"]
    embedding_dims = prev["embedding_dims"]

    raw_jsonl = minio_client.get_object_bytes(bucket, embeddings_key).decode("utf-8", errors="replace")
    records = [EmbeddingRecord.from_dict(json.loads(line)) for line in raw_jsonl.splitlines() if line.strip()]

    collection_name = QDRANT_COLLECTION if embedding_dims == 1024 else QDRANT_COLLECTION_DEV

    client = qdrant_client_helper.get_client()
    qdrant_client_helper.ensure_collection(client, collection_name, embedding_dims)
    qdrant_client_helper.ensure_payload_indexes(client, collection_name)
    qdrant_client_helper.delete_points_by_doc_id(client, collection_name, doc_id)

    points = [
        {
            "id": deterministic_point_id(doc_id, record.chunk_index),
            "dense_vector": record.vector,
            "sparse_indices": record.sparse_indices,
            "sparse_values": record.sparse_values,
            "payload": record.payload,
        }
        for record in records
    ]
    qdrant_client_helper.upsert_points(client, collection_name, points)

    return {**prev, "upserted_count": len(points), "collection_name": collection_name}
