"""
rag_ingestion.tasks.parse_pdf
--------------------------------
Reads the staged raw PDF bytes from MinIO, parses it to markdown via
LlamaParse (or the pypdf fallback), and writes the markdown + parse
metadata back to MinIO. Only small dicts/keys cross the Airflow XCom
boundary -- the parsed text itself lives in MinIO.
"""
from __future__ import annotations

from rag_ingestion.clients import llamaparse_client, minio_client
from rag_ingestion.common.keys import stage_key
from rag_ingestion.config import MINIO_BUCKET


def run(prev: dict) -> dict:
    bucket = prev.get("bucket", MINIO_BUCKET)
    doc_id = prev["doc_id"]
    raw_key = prev["raw_key"]

    pdf_bytes = minio_client.get_object_bytes(bucket, raw_key)
    filename = prev.get("object_key", "source.pdf")

    markdown_text, parse_meta = llamaparse_client.parse_pdf_bytes(pdf_bytes, filename)

    parsed_key = stage_key("parsed", doc_id, "parsed.md")
    parse_meta_key = stage_key("parsed", doc_id, "parse_meta.json")

    minio_client.put_object_text(bucket, parsed_key, markdown_text)
    minio_client.put_object_json(bucket, parse_meta_key, parse_meta)

    return {**prev, "parsed_key": parsed_key, "parse_meta_key": parse_meta_key}
