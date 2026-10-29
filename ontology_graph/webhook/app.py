"""Turns a MinIO s3:ObjectCreated event under licdocuments/ into a lic_policy_ingestion DAG run; internal-only, with a shared-secret check as defense-in-depth."""
from __future__ import annotations

import logging
import urllib.parse

import httpx
from fastapi import FastAPI, Header, HTTPException, Request

from ontology_graph import config
from ontology_graph.pipeline.common import compute_doc_id, dag_run_id_for

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="lic-webhook")


def _verify_shared_secret(authorization: str | None) -> None:
    if not config.LIC_WEBHOOK_SHARED_SECRET:
        logger.warning("LIC_WEBHOOK_SHARED_SECRET is not set; accepting request unauthenticated.")
        return
    if authorization != f"Bearer {config.LIC_WEBHOOK_SHARED_SECRET}":
        raise HTTPException(status_code=401, detail="Invalid or missing webhook credentials.")


def _trigger_dag_run(bucket: str, object_key: str, etag: str) -> dict:
    doc_id = compute_doc_id(object_key, etag)
    dag_run_id = dag_run_id_for(doc_id)
    response = httpx.post(
        f"{config.AIRFLOW_API_URL}/api/v1/dags/{config.LIC_DAG_ID}/dagRuns",
        json={"dag_run_id": dag_run_id, "conf": {"bucket": bucket, "object_key": object_key, "etag": etag}},
        auth=(config.AIRFLOW_API_USERNAME, config.AIRFLOW_API_PASSWORD),
        timeout=10.0,
    )
    if response.status_code == 409:
        logger.info("dag_run %s already exists (duplicate MinIO event); skipping.", dag_run_id)
        return {"doc_id": doc_id, "dag_run_id": dag_run_id, "status": "already_triggered"}
    response.raise_for_status()
    logger.info("Triggered dag_run %s for %s.", dag_run_id, object_key)
    return {"doc_id": doc_id, "dag_run_id": dag_run_id, "status": "triggered"}


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/minio-event")
async def minio_event(request: Request, authorization: str | None = Header(default=None)) -> dict:
    _verify_shared_secret(authorization)
    body = await request.json()

    triggered = []
    for record in body.get("Records") or []:
        s3_info = record.get("s3", {})
        bucket = s3_info.get("bucket", {}).get("name")
        object_key = urllib.parse.unquote_plus(s3_info.get("object", {}).get("key", ""))
        etag = s3_info.get("object", {}).get("eTag", "")

        if not bucket or not object_key:
            logger.warning("Skipping malformed MinIO event record: %r", record)
            continue
        if not (object_key.startswith(config.UPLOAD_PREFIX) and object_key.lower().endswith(".pdf")):
            logger.info("Ignoring %s (outside %s*.pdf).", object_key, config.UPLOAD_PREFIX)
            continue
        triggered.append(_trigger_dag_run(bucket, object_key, etag))

    return {"triggered": triggered}
