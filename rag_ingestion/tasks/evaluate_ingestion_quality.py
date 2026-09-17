"""
rag_ingestion.tasks.evaluate_ingestion_quality
--------------------------------------------------
Final, best-effort task: runs the shared chunk-quality heuristic over the
chunks that were produced for this document and records the result. This
task must NEVER fail the DAG run -- it runs with trigger_rule="all_done"
so it executes even after an upstream failure, purely for observability.
"""
from __future__ import annotations

import json
import logging

from gates_ai_common.evaluation import ResponseEvaluator
from rag_ingestion.clients import minio_client
from rag_ingestion.config import MINIO_BUCKET

logger = logging.getLogger(__name__)


def run(prev: dict | None) -> dict:
    # prev can be None/missing here: this task runs with trigger_rule="all_done"
    # so it still executes even when an upstream gate (e.g. extract_metadata's
    # safety check) failed and caused load_qdrant to be skipped, leaving no
    # XCom to pull. Never let that crash this best-effort task.
    if not isinstance(prev, dict):
        logger.warning("evaluate_ingestion_quality received no upstream result (prev=%r); skipping.", prev)
        return {"quality_eval": {"error": "no upstream result available (an earlier task likely failed)"}}

    try:
        bucket = prev.get("bucket", MINIO_BUCKET)
        # Prefer enriched chunks (post-metadata) but fall back to the raw
        # chunked output if metadata extraction failed/was skipped upstream.
        chunks_key = prev.get("metadata_key") or prev.get("chunked_key")
        if not chunks_key:
            return {**prev, "quality_eval": {"error": "no chunk artifact available to evaluate"}}

        raw_jsonl = minio_client.get_object_bytes(bucket, chunks_key).decode("utf-8", errors="replace")
        texts = [json.loads(line)["text"] for line in raw_jsonl.splitlines() if line.strip()]

        evaluator = ResponseEvaluator()
        result = evaluator.evaluate_chunk_quality(texts)
        quality_eval = {
            "score": result.score,
            "passed": result.passed,
            "backend": result.backend,
            "details": result.details,
        }
        return {**prev, "quality_eval": quality_eval}
    except Exception as error:
        logger.warning("evaluate_ingestion_quality failed non-fatally: %s", error)
        return {**prev, "quality_eval": {"error": str(error)}}
