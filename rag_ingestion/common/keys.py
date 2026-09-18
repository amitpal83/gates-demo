"""Deterministic id/key helpers -- shared by the webhook, tasks, and DAG so
a duplicate MinIO notification maps to the same dag_run_id instead of
double-ingesting."""
import hashlib
import uuid

# Fixed so re-ingesting the same doc/chunk overwrites the same Qdrant point.
_POINT_ID_NAMESPACE = uuid.UUID("7c1b6b2e-2f3a-4a5a-9b1e-2b6f7d9c4a10")


def compute_doc_id(object_key: str, etag: str) -> str:
    return hashlib.sha256(f"{object_key}:{etag}".encode()).hexdigest()[:16]


def dag_run_id_for(doc_id: str) -> str:
    return f"rag_ingest__{doc_id}"


def stage_key(stage: str, doc_id: str, filename: str) -> str:
    return f"{stage}/{doc_id}/{filename}"


def deterministic_point_id(doc_id: str, chunk_index: int) -> str:
    return str(uuid.uuid5(_POINT_ID_NAMESPACE, f"{doc_id}:{chunk_index}"))
