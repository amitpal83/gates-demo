"""BM25-style sparse vector builder, shared by ingestion and query time so
both hash terms into the same index space. Raw term counts, not IDF-
weighted -- Qdrant's Modifier.IDF on the collection computes real corpus
IDF from these at query time. zlib.crc32 (not Python's hash()) because it's
deterministic across processes."""
from __future__ import annotations

import re
import zlib
from collections import Counter

VOCAB_SIZE = 2**24

_TOKEN_PATTERN = re.compile(r"[a-z0-9]{2,}")

_STOP_WORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is",
    "are", "was", "were", "be", "been", "this", "that", "these", "those",
    "with", "by", "as", "at", "it", "its", "from", "into", "about",
}


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_PATTERN.findall(text.lower()) if t not in _STOP_WORDS]


def term_index(term: str) -> int:
    return zlib.crc32(term.encode("utf-8")) % VOCAB_SIZE


def build_sparse_vector(text: str) -> tuple[list[int], list[float]]:
    """Returns (indices, values) for qdrant_client.models.SparseVector."""
    counts = Counter(term_index(t) for t in tokenize(text))
    if not counts:
        return [], []
    indices, values = zip(*sorted(counts.items()))
    return list(indices), [float(v) for v in values]
