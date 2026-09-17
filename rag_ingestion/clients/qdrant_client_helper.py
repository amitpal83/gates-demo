"""
rag_ingestion.clients.qdrant_client_helper
---------------------------------------------
Wraps `qdrant_client.QdrantClient`. qdrant-client is a core dependency of
this subproject (not optional), so it is imported at module level.

Collections use two NAMED vectors per point -- "dense" (OpenAI/
sentence-transformers embedding) and "sparse" (BM25-style term-frequency
vector, see rag_ingestion.common.sparse_vectors) -- so query_engine.py can
run a single hybrid_search() call that fuses both via Qdrant's Query API
(RRF). This needs qdrant-client/qdrant-server >= 1.10 (Query API,
sparse vectors, Modifier.IDF); the server is pinned to v1.12.1 in
docker-compose.yml. A collection created before hybrid search existed
(single unnamed vector) is NOT compatible with this schema -- drop it and
let ensure_collection recreate it before re-ingesting.
"""
from __future__ import annotations

import logging

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    Fusion,
    FusionQuery,
    MatchValue,
    Modifier,
    PayloadSchemaType,
    PointStruct,
    Prefetch,
    ScoredPoint,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)

from rag_ingestion import config

logger = logging.getLogger(__name__)

_DENSE_VECTOR_NAME = "dense"
_SPARSE_VECTOR_NAME = "sparse"


def get_client() -> QdrantClient:
    return QdrantClient(url=config.QDRANT_URL)


def ensure_collection(client: QdrantClient, collection_name: str, vector_size: int) -> None:
    """Idempotent collection creation -- dense + sparse named vectors."""
    try:
        exists = client.collection_exists(collection_name)
    except Exception:
        # Older qdrant-client versions don't have collection_exists; fall back
        # to listing collections.
        exists = collection_name in {c.name for c in client.get_collections().collections}

    if not exists:
        client.create_collection(
            collection_name=collection_name,
            vectors_config={_DENSE_VECTOR_NAME: VectorParams(size=vector_size, distance=Distance.COSINE)},
            sparse_vectors_config={_SPARSE_VECTOR_NAME: SparseVectorParams(modifier=Modifier.IDF)},
        )


def ensure_payload_indexes(client: QdrantClient, collection_name: str) -> None:
    """Idempotent creation of payload indexes used for filtering.

    Exact idempotent-check APIs vary by qdrant-client version, so each
    index creation is wrapped in its own try/except and treated as a
    no-op if the index already exists.
    """
    index_fields = {
        "ingestion_ts": PayloadSchemaType.INTEGER,
        "pdf_type": PayloadSchemaType.KEYWORD,
        "author": PayloadSchemaType.KEYWORD,
        "owner": PayloadSchemaType.KEYWORD,
        "source_object_key": PayloadSchemaType.KEYWORD,
        "doc_id": PayloadSchemaType.KEYWORD,
    }
    for field_name, schema_type in index_fields.items():
        try:
            client.create_payload_index(
                collection_name=collection_name,
                field_name=field_name,
                field_schema=schema_type,
            )
        except Exception as error:
            logger.debug("Payload index for %s may already exist: %s", field_name, error)


def upsert_points(client: QdrantClient, collection_name: str, points: list[dict]) -> None:
    """Each point dict: {id, dense_vector, sparse_indices, sparse_values, payload}."""
    point_structs = [
        PointStruct(
            id=p["id"],
            vector={
                _DENSE_VECTOR_NAME: p["dense_vector"],
                _SPARSE_VECTOR_NAME: SparseVector(
                    indices=p.get("sparse_indices") or [],
                    values=p.get("sparse_values") or [],
                ),
            },
            payload=p.get("payload", {}),
        )
        for p in points
    ]
    client.upsert(collection_name=collection_name, points=point_structs)


def delete_points_by_doc_id(client: QdrantClient, collection_name: str, doc_id: str) -> None:
    """Used by load_qdrant for idempotent re-ingestion (delete-then-upsert)."""
    client.delete(
        collection_name=collection_name,
        points_selector=Filter(
            must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]
        ),
    )


def build_metadata_filter(filters: dict) -> Filter | None:
    """Builds a Qdrant Filter from detected {field: value} metadata hints
    (see query_engine.py's query-understanding stage) against the KEYWORD
    payload indexes ensure_payload_indexes creates (pdf_type/author/owner/
    doc_id/source_object_key). Returns None if there's nothing to filter on."""
    conditions = [
        FieldCondition(key=field, match=MatchValue(value=value))
        for field, value in (filters or {}).items()
        if value
    ]
    return Filter(must=conditions) if conditions else None


def hybrid_search(
    client: QdrantClient,
    collection_name: str,
    dense_vector: list[float],
    sparse_indices: list[int],
    sparse_values: list[float],
    limit: int,
    candidate_limit: int = 20,
    query_filter: Filter | None = None,
) -> list[ScoredPoint]:
    """Single-call hybrid retrieval: dense + sparse candidates (each scoped
    by the same metadata filter, when given), fused via Qdrant's native RRF
    (Reciprocal Rank Fusion) and cut down to `limit` results.

    `candidate_limit` is how many candidates each of the dense/sparse
    prefetches contributes to the fusion before it's cut to `limit` --
    keep it >= limit and comfortably above it so fusion has enough from
    each side to actually blend (a subsequent cross-encoder rerank step,
    see query_engine.py, then re-scores this candidate set)."""
    response = client.query_points(
        collection_name=collection_name,
        prefetch=[
            Prefetch(
                query=dense_vector,
                using=_DENSE_VECTOR_NAME,
                limit=candidate_limit,
                filter=query_filter,
            ),
            Prefetch(
                query=SparseVector(indices=sparse_indices, values=sparse_values),
                using=_SPARSE_VECTOR_NAME,
                limit=candidate_limit,
                filter=query_filter,
            ),
        ],
        query=FusionQuery(fusion=Fusion.RRF),
        limit=limit,
        with_payload=True,
    )
    return response.points
