"""Thin wrapper around the minio SDK; no fallback, MinIO is core infra here."""
from __future__ import annotations

import io
import json

from minio import Minio
from minio.commonconfig import CopySource

from ontology_graph import config

_client = None


def get_client() -> Minio:
    global _client
    if _client is None:
        _client = Minio(
            config.MINIO_ENDPOINT,
            access_key=config.MINIO_ROOT_USER,
            secret_key=config.MINIO_ROOT_PASSWORD,
            secure=config.MINIO_SECURE,
        )
    return _client


def get_bytes(bucket: str, key: str) -> bytes:
    response = get_client().get_object(bucket, key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def put_bytes(bucket: str, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    client = get_client()
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
    client.put_object(bucket, key, io.BytesIO(data), length=len(data), content_type=content_type)


def put_text(bucket: str, key: str, text: str, content_type: str = "text/plain") -> None:
    put_bytes(bucket, key, text.encode("utf-8"), content_type)


def put_json(bucket: str, key: str, obj) -> None:
    put_text(bucket, key, json.dumps(obj, indent=2), "application/json")


def copy(src_bucket: str, src_key: str, dst_bucket: str, dst_key: str) -> None:
    client = get_client()
    if not client.bucket_exists(dst_bucket):
        client.make_bucket(dst_bucket)
    client.copy_object(dst_bucket, dst_key, CopySource(src_bucket, src_key))
