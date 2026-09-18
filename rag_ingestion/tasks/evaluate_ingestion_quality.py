"""Best-effort final task: scores chunk quality for observability. Runs
with trigger_rule=all_done so it still runs after an upstream failure."""
from __future__ import annotations

import json
import logging

from gates_ai_common.evaluation import ResponseEvaluator
from rag_ingestion.clients import minio_client
from rag_ingestion.config import MINIO_BUCKET

logger = logging.getLogger(__name__)


def run(prev: dict | None) -> dict:
    if not isinstance(prev, dict):
        logger.warning("evaluate_ingestion_quality received no upstream result (prev=%r); skipping.", prev)
        return {"quality_eval": {"error": "no upstream result available (an earlier task likely failed)"}}

    try:
        bucket = prev.get("bucket", MINIO_BUCKET)
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
