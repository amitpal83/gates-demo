"""
rag_ingestion.webhook.app
-----------------------------
Internal-only FastAPI service that turns a MinIO `s3:ObjectCreated:*`
event notification into an `rag_pdf_ingestion` Airflow DAG run.

Never reachable from outside the Docker Compose network (see
docker-compose.yml's `rag-webhook` service, which only `expose`s its port,
never publishes one to the host) -- MinIO's notify_webhook target is the
only intended caller, POSTing to /minio-event. Still gated by
RAG_WEBHOOK_SHARED_SECRET (configured as MinIO's notify_webhook
`auth_token`, which MinIO sends as `Authorization: Bearer <token>`) as
defense-in-depth against anything else reachable on that network.

Idempotent by construction: dag_run_id is deterministically derived from
the same (object_key, etag) pair stage_raw.run() uses to compute doc_id
(see rag_ingestion.common.keys), so a duplicate MinIO notification for the
same object version maps to the same dag_run instead of double-ingesting.
"""
from __future__ import annotations

import logging
import urllib.parse

import httpx
from fastapi import FastAPI, Header, HTTPException, Request

from rag_ingestion import config
from rag_ingestion.common.keys import compute_doc_id, dag_run_id_for

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="rag-webhook")

_INCOMING_PREFIX = "incoming/"
_PDF_SUFFIX = ".pdf"


def _verify_shared_secret(authorization: str | None) -> None:
    if not config.RAG_WEBHOOK_SHARED_SECRET:
        logger.warning("RAG_WEBHOOK_SHARED_SECRET is not set; accepting request unauthenticated.")
        return
    if authorization != f"Bearer {config.RAG_WEBHOOK_SHARED_SECRET}":
        raise HTTPException(status_code=401, detail="Invalid or missing webhook credentials.")


def _trigger_dag_run(bucket: str, object_key: str, etag: str) -> dict:
    doc_id = compute_doc_id(object_key, etag)
    dag_run_id = dag_run_id_for(doc_id)
    url = f"{config.AIRFLOW_API_URL}/api/v1/dags/{config.AIRFLOW_DAG_ID}/dagRuns"
    payload = {
        "dag_run_id": dag_run_id,
        "conf": {"bucket": bucket, "object_key": object_key, "etag": etag},
    }

    response = httpx.post(
        url,
        json=payload,
        auth=(config.AIRFLOW_API_USERNAME, config.AIRFLOW_API_PASSWORD),
        timeout=10.0,
    )
    if response.status_code == 409:
        logger.info(
            "dag_run %s already exists for doc_id %s (duplicate MinIO event); skipping.",
            dag_run_id, doc_id,
        )
        return {"doc_id": doc_id, "dag_run_id": dag_run_id, "status": "already_triggered"}

    response.raise_for_status()
    logger.info("Triggered dag_run %s for doc_id %s (object_key=%s).", dag_run_id, doc_id, object_key)
    return {"doc_id": doc_id, "dag_run_id": dag_run_id, "status": "triggered"}


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/minio-event")
async def minio_event(request: Request, authorization: str | None = Header(default=None)) -> dict:
    _verify_shared_secret(authorization)

    body = await request.json()
    records = body.get("Records") or []

    triggered = []
    for record in records:
        s3_info = record.get("s3", {})
        bucket = s3_info.get("bucket", {}).get("name")
        raw_key = s3_info.get("object", {}).get("key", "")
        etag = s3_info.get("object", {}).get("eTag", "")
        # MinIO percent-encodes object keys in event notifications.
        object_key = urllib.parse.unquote_plus(raw_key)

        if not bucket or not object_key:
            logger.warning("Skipping malformed MinIO event record: %r", record)
            continue

        if not (object_key.startswith(_INCOMING_PREFIX) and object_key.endswith(_PDF_SUFFIX)):
            # `mc event add` is already scoped to --prefix incoming/ --suffix
            # .pdf -- this is defense in depth in case that filter is ever
            # loosened or bypassed by a manually-fired notification.
            logger.info("Ignoring event for %s (outside incoming/*.pdf scope).", object_key)
            continue

        triggered.append(_trigger_dag_run(bucket, object_key, etag))

    return {"triggered": triggered}
