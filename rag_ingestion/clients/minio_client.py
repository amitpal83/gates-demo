"""Thin wrapper around the `minio` SDK. No fallback -- MinIO is core infra
here, so a missing/unreachable client raises instead of silently no-op-ing."""
from __future__ import annotations

import io
import json
import logging

from rag_ingestion import config

logger = logging.getLogger(__name__)

if config.HAS_MINIO:
    from minio import Minio

_client = None


def _require_minio():
    if not config.HAS_MINIO:
        raise RuntimeError(
            "The 'minio' package is not installed. It is a required dependency "
            "for rag_ingestion (pip install minio)."
        )


def get_client():
    global _client
    _require_minio()
    if _client is None:
        _client = Minio(
            config.MINIO_ENDPOINT,
            access_key=config.MINIO_ROOT_USER,
            secret_key=config.MINIO_ROOT_PASSWORD,
            secure=config.MINIO_SECURE,
        )
    return _client


def ensure_bucket(bucket: str) -> None:
    client = get_client()
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)


def object_exists(bucket: str, key: str) -> bool:
    client = get_client()
    try:
        client.stat_object(bucket, key)
        return True
    except Exception:
        return False


def get_object_bytes(bucket: str, key: str) -> bytes:
    client = get_client()
    response = client.get_object(bucket, key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def put_object_bytes(bucket: str, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    client = get_client()
    ensure_bucket(bucket)
    client.put_object(bucket, key, io.BytesIO(data), length=len(data), content_type=content_type)


def put_object_text(bucket: str, key: str, text: str) -> None:
    content_type = "application/octet-stream"
    if key.endswith(".json") or key.endswith(".jsonl"):
        content_type = "application/json"
    elif key.endswith(".md"):
        content_type = "text/markdown"
    put_object_bytes(bucket, key, text.encode("utf-8"), content_type=content_type)


def put_object_json(bucket: str, key: str, obj) -> None:
    put_object_text(bucket, key, json.dumps(obj))


def copy_object(bucket: str, src_key: str, dst_key: str) -> None:
    client = get_client()
    ensure_bucket(bucket)
    from minio.commonconfig import CopySource
    client.copy_object(bucket, dst_key, CopySource(bucket, src_key))
