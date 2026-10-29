"""Qdrant access for the LIC collection: one point per chunk with named dense + sparse vectors for hybrid search (needs qdrant-client/server >= 1.10)."""
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
    SparseVector,
    SparseVectorParams,
    VectorParams,
)

from ontology_graph import config

logger = logging.getLogger(__name__)

DENSE = "dense"
SPARSE = "sparse"


def get_client() -> QdrantClient:
    return QdrantClient(url=config.QDRANT_URL)


def ensure_collection(client: QdrantClient, vector_size: int) -> None:
    name = config.QDRANT_COLLECTION
    if not client.collection_exists(name):
        client.create_collection(
            collection_name=name,
            vectors_config={DENSE: VectorParams(size=vector_size, distance=Distance.COSINE)},
            sparse_vectors_config={SPARSE: SparseVectorParams(modifier=Modifier.IDF)},
        )
    try:
        client.create_payload_index(name, field_name="doc_id", field_schema=PayloadSchemaType.KEYWORD)
    except Exception as error:
        logger.debug("doc_id payload index may already exist: %s", error)


def delete_doc(client: QdrantClient, doc_id: str) -> None:
    client.delete(
        collection_name=config.QDRANT_COLLECTION,
        points_selector=Filter(must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]),
    )


def upsert(client: QdrantClient, points: list[dict]) -> None:
    """Each point: {id, dense, sparse_indices, sparse_values, payload}."""
    client.upsert(
        collection_name=config.QDRANT_COLLECTION,
        points=[
            PointStruct(
                id=p["id"],
                vector={DENSE: p["dense"], SPARSE: SparseVector(indices=p["sparse_indices"], values=p["sparse_values"])},
                payload=p["payload"],
            )
            for p in points
        ],
    )


def hybrid_search(client: QdrantClient, dense: list[float], sparse_indices: list[int], sparse_values: list[float], limit: int) -> list[dict]:
    """Dense + sparse candidates fused with RRF; returns payload dicts with a `score`."""
    if not client.collection_exists(config.QDRANT_COLLECTION):
        return []
    response = client.query_points(
        collection_name=config.QDRANT_COLLECTION,
        prefetch=[
            Prefetch(query=dense, using=DENSE, limit=limit * 4),
            Prefetch(query=SparseVector(indices=sparse_indices, values=sparse_values), using=SPARSE, limit=limit * 4),
        ],
        query=FusionQuery(fusion=Fusion.RRF),
        limit=limit,
        with_payload=True,
    )
    return [{**(point.payload or {}), "score": point.score} for point in response.points]
