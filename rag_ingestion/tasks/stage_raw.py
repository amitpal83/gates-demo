"""First pipeline task: computes doc_id and copies the upload into raw/<doc_id>/source.pdf for a stable path; no Airflow import here (dags/rag_ingestion_dag.py wraps run() with @task and @trace)."""
from __future__ import annotations

from rag_ingestion.clients import minio_client
from rag_ingestion.common.keys import compute_doc_id, stage_key


def run(conf: dict) -> dict:
    """conf: {bucket, object_key, etag, metadata_overrides?} (from dag_run.conf)."""
    bucket = conf["bucket"]
    object_key = conf["object_key"]
    etag = conf["etag"]
    metadata_overrides = conf.get("metadata_overrides", {})

    doc_id = compute_doc_id(object_key, etag)
    raw_key = stage_key("raw", doc_id, "source.pdf")

    minio_client.copy_object(bucket, object_key, raw_key)

    return {
        "bucket": bucket,
        "object_key": object_key,
        "etag": etag,
        "doc_id": doc_id,
        "raw_key": raw_key,
        "metadata_overrides": metadata_overrides,
    }
