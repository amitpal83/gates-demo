"""Deterministic ids, MinIO stage keys and the sparse-vector builder; stdlib only so the webhook can import it without the heavy deps."""
from __future__ import annotations

import hashlib
import re
import uuid
import zlib
from collections import Counter

# Fixed so re-ingesting the same doc/chunk overwrites the same Qdrant point.
_POINT_ID_NAMESPACE = uuid.UUID("3f6c2d4e-8a1b-4c57-9d2e-5b7a1c9e0f42")

VOCAB_SIZE = 2**24
_TOKEN_PATTERN = re.compile(r"[a-z0-9]{2,}")
_STOP_WORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is",
    "are", "was", "were", "be", "been", "this", "that", "these", "those",
    "with", "by", "as", "at", "it", "its", "from", "into", "about",
}


def compute_doc_id(object_key: str, etag: str) -> str:
    return hashlib.sha256(f"{object_key}:{etag}".encode()).hexdigest()[:16]


def dag_run_id_for(doc_id: str) -> str:
    return f"lic_ingest__{doc_id}"


def stage_key(stage: str, doc_id: str, filename: str) -> str:
    return f"lic/{stage}/{doc_id}/{filename}"


def point_id(doc_id: str, chunk_index: int) -> str:
    return str(uuid.uuid5(_POINT_ID_NAMESPACE, f"{doc_id}:{chunk_index}"))


def build_sparse_vector(text: str) -> tuple[list[int], list[float]]:
    """Raw term counts hashed with crc32 (stable across processes); Qdrant's IDF modifier does the weighting."""
    tokens = [t for t in _TOKEN_PATTERN.findall(text.lower()) if t not in _STOP_WORDS]
    counts = Counter(zlib.crc32(t.encode("utf-8")) % VOCAB_SIZE for t in tokens)
    if not counts:
        return [], []
    indices, values = zip(*sorted(counts.items()))
    return list(indices), [float(v) for v in values]
