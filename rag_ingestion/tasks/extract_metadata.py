"""Attaches document-level metadata to every chunk, then runs the PII and content-safety gates on the joined text; a failure raises and is logged to MinIO under failed/<doc_id>/."""
from __future__ import annotations

import json
import time
from pathlib import Path

from gates_ai_common.guardrails import SecurityGuardrail
from gates_ai_common.input_validation import InputValidator
from rag_ingestion.clients import minio_client
from rag_ingestion.common.keys import stage_key
from rag_ingestion.common.schemas import Chunk, EnrichedChunk
from rag_ingestion.config import MINIO_BUCKET

_GUARDRAILS_CONFIG_PATH = Path(__file__).resolve().parents[2] / "guardrails_config" / "rag_ingestion"


def run(prev: dict) -> dict:
    bucket = prev.get("bucket", MINIO_BUCKET)
    doc_id = prev["doc_id"]
    chunked_key = prev["chunked_key"]
    metadata_overrides = prev.get("metadata_overrides") or {}

    raw_jsonl = minio_client.get_object_bytes(bucket, chunked_key).decode("utf-8", errors="replace")
    chunks = [Chunk.from_dict(json.loads(line)) for line in raw_jsonl.splitlines() if line.strip()]

    full_text = "\n\n".join(c.text for c in chunks)

    validator = InputValidator()
    scan_result = validator.scan_document_text(full_text)

    guardrail = SecurityGuardrail(config_path=str(_GUARDRAILS_CONFIG_PATH))
    safety_result = guardrail.check_document_safety(full_text)

    if not scan_result.is_safe or not safety_result.allowed:
        reason = {
            "scan_passed": scan_result.is_safe,
            "scan_findings": scan_result.findings,
            "safety_passed": safety_result.allowed,
            "safety_reason": safety_result.reason,
        }
        minio_client.put_object_json(bucket, f"failed/{doc_id}/reason.json", reason)
        raise RuntimeError(f"Document {doc_id} failed ingestion-time safety gates: {reason}")

    pdf_type = metadata_overrides.get("pdf_type", "unknown")
    author = metadata_overrides.get("author", "unknown")
    owner = metadata_overrides.get("owner", "unknown")
    ingestion_ts = int(time.time())
    source_object_key = prev.get("object_key", "")

    enriched = [
        EnrichedChunk(
            chunk_index=c.chunk_index,
            text=c.text,
            page_number=c.page_number,
            section_title=c.section_title,
            char_start=c.char_start,
            char_end=c.char_end,
            pdf_type=pdf_type,
            author=author,
            owner=owner,
            ingestion_ts=ingestion_ts,
            source_object_key=source_object_key,
            guardrail_backend=safety_result.backend,
            guardrail_passed=safety_result.allowed,
        )
        for c in chunks
    ]

    metadata_key = stage_key("metadata", doc_id, "enriched_chunks.jsonl")
    jsonl = "\n".join(json.dumps(ec.to_dict()) for ec in enriched)
    minio_client.put_object_text(bucket, metadata_key, jsonl)

    return {**prev, "metadata_key": metadata_key, "scan_passed": True}
