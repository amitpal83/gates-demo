"""
rag_ingestion.common.sparse_vectors
---------------------------------------
Shared BM25-style sparse vector builder, used identically at ingestion
time (tasks/build_embeddings.py, one sparse vector per chunk) and query
time (query_engine.py, one sparse vector per question) so both sides hash
terms into the same index space -- a term hashed differently on the two
sides would never match at search time.

Deliberately raw term-frequency counts, NOT IDF-weighted here. Qdrant's
own `Modifier.IDF` on the sparse vector's collection config (see
clients/qdrant_client_helper.py's ensure_collection) computes real,
corpus-wide IDF from the indexed term frequencies at query time -- that's
the documented way to get BM25-equivalent scoring out of Qdrant sparse
vectors without re-deriving IDF client-side. See
https://qdrant.tech/documentation/concepts/hybrid-queries/.

No new dependency (no fastembed/onnxruntime): term hashing uses stdlib
zlib.crc32, which is deterministic across processes -- unlike Python's
built-in hash() on strings, which is randomized per-run unless
PYTHONHASHSEED is fixed, and would silently break term matching between
the ingestion process and a separately-run query process.
"""
from __future__ import annotations

import re
import zlib
from collections import Counter

# Large enough bucket space to keep hash collisions rare for a single
# chunk/question's vocabulary (at most a few hundred unique terms).
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
    """Returns (indices, values) -- raw term-frequency counts per hashed
    term index, ready for qdrant_client.models.SparseVector(indices=, values=).
    Empty text (or text with no surviving tokens) yields ([], [])."""
    counts = Counter(term_index(t) for t in tokenize(text))
    if not counts:
        return [], []
    indices, values = zip(*sorted(counts.items()))
    return list(indices), [float(v) for v in values]
