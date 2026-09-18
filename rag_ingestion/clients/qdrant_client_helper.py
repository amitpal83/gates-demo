"""Wraps qdrant_client.QdrantClient. Collections use two named vectors per
point ("dense" + "sparse") so hybrid_search() can fuse both in one call --
needs qdrant-client/server >= 1.10. A collection created before hybrid
search existed (single unnamed vector) isn't compatible; drop and
re-ingest."""
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
    try:
        exists = client.collection_exists(collection_name)
    except Exception:
        exists = collection_name in {c.name for c in client.get_collections().collections}

    if not exists:
        client.create_collection(
            collection_name=collection_name,
            vectors_config={_DENSE_VECTOR_NAME: VectorParams(size=vector_size, distance=Distance.COSINE)},
            sparse_vectors_config={_SPARSE_VECTOR_NAME: SparseVectorParams(modifier=Modifier.IDF)},
        )


def ensure_payload_indexes(client: QdrantClient, collection_name: str) -> None:
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
    client.delete(
        collection_name=collection_name,
        points_selector=Filter(
            must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]
        ),
    )


def build_metadata_filter(filters: dict) -> Filter | None:
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
    """One call: dense + sparse candidates fused via RRF, then cut to `limit`.
    candidate_limit should stay above `limit` so a later rerank has enough
    to work with."""
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
