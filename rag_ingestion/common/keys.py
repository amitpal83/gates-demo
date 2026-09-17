"""
rag_ingestion.common.keys
----------------------------
Deterministic id/key helpers shared across the webhook, tasks, and DAG.
Signatures here are load-bearing -- the webhook computes the same
doc_id/dag_run_id the DAG's first task recomputes, so a duplicate MinIO
event notification maps to the same Airflow dag_run_id (idempotent
trigger) instead of creating a duplicate ingestion run.
"""
import hashlib
import uuid

# Fixed namespace UUID for deterministic Qdrant point ids -- must stay
# stable across deploys so re-ingesting the same doc/chunk overwrites the
# same point instead of creating a duplicate.
_POINT_ID_NAMESPACE = uuid.UUID("7c1b6b2e-2f3a-4a5a-9b1e-2b6f7d9c4a10")


def compute_doc_id(object_key: str, etag: str) -> str:
    """Stable short id for a document version, derived from its MinIO key + etag."""
    return hashlib.sha256(f"{object_key}:{etag}".encode()).hexdigest()[:16]


def dag_run_id_for(doc_id: str) -> str:
    """Deterministic Airflow dag_run_id for a doc_id (idempotent trigger)."""
    return f"rag_ingest__{doc_id}"


def stage_key(stage: str, doc_id: str, filename: str) -> str:
    """Object key for a pipeline stage's artifact, e.g. 'raw/<doc_id>/source.pdf'."""
    return f"{stage}/{doc_id}/{filename}"


def deterministic_point_id(doc_id: str, chunk_index: int) -> str:
    """Stable Qdrant point id for a (doc_id, chunk_index) pair."""
    return str(uuid.uuid5(_POINT_ID_NAMESPACE, f"{doc_id}:{chunk_index}"))
