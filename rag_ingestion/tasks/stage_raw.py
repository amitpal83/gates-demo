"""
rag_ingestion.tasks.stage_raw
--------------------------------
First pipeline task: computes the deterministic doc_id for this
(object_key, etag) pair and copies the freshly-landed object into this
pipeline's own 'raw/<doc_id>/source.pdf' staging key, so every downstream
task works off a stable key that doesn't move even if the original
upload gets deleted/overwritten.

No Airflow import here (or in any other tasks/*.py module) -- this stays
importable/unit-testable without Airflow installed. `dags/rag_ingestion_dag.py`
wraps `run()` with `@task` and `@trace`.
"""
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
