"""
rag_ingestion.tasks.chunk_document
--------------------------------------
Reads the parsed markdown from MinIO and splits it into chunks.

Production backend : llama_index's SentenceSplitter over a Document, when
                      llama_index is installed.
Fallback backend    : a simple fixed-window splitter with overlap (same
                      spirit as agents/rag_flow.py's chunk_text, but
                      reimplemented here rather than imported -- this
                      subproject must not import from agents/).
"""
from __future__ import annotations

import json
import re

from rag_ingestion.clients import minio_client
from rag_ingestion.common.keys import stage_key
from rag_ingestion.common.schemas import Chunk
from rag_ingestion.config import HAS_LLAMA_INDEX, MINIO_BUCKET

_WINDOW_SIZE = 800
_OVERLAP = 100


def _fallback_split(text: str) -> list[Chunk]:
    normalized = re.sub(r"\s+", " ", text).strip()
    chunks: list[Chunk] = []
    start = 0
    index = 0
    while start < len(normalized):
        end = min(start + _WINDOW_SIZE, len(normalized))
        piece = normalized[start:end]
        if piece.strip():
            chunks.append(
                Chunk(
                    chunk_index=index,
                    text=piece,
                    page_number=None,
                    section_title=None,
                    char_start=start,
                    char_end=end,
                )
            )
            index += 1
        if end >= len(normalized):
            break
        start = end - _OVERLAP
    return chunks


def _llama_index_split(text: str) -> list[Chunk]:
    from llama_index.core import Document
    from llama_index.core.node_parser import SentenceSplitter

    splitter = SentenceSplitter(chunk_size=_WINDOW_SIZE, chunk_overlap=_OVERLAP)
    document = Document(text=text)
    nodes = splitter.get_nodes_from_documents([document])

    chunks: list[Chunk] = []
    for i, node in enumerate(nodes):
        node_text = node.get_content()
        char_start = text.find(node_text) if node_text in text else -1
        char_end = char_start + len(node_text) if char_start >= 0 else -1
        chunks.append(
            Chunk(
                chunk_index=i,
                text=node_text,
                page_number=None,
                section_title=None,
                char_start=char_start,
                char_end=char_end,
            )
        )
    return chunks


def run(prev: dict) -> dict:
    bucket = prev.get("bucket", MINIO_BUCKET)
    doc_id = prev["doc_id"]
    parsed_key = prev["parsed_key"]

    text = minio_client.get_object_bytes(bucket, parsed_key).decode("utf-8", errors="replace")

    if HAS_LLAMA_INDEX:
        try:
            chunks = _llama_index_split(text)
        except Exception:
            chunks = _fallback_split(text)
    else:
        chunks = _fallback_split(text)

    chunked_key = stage_key("chunked", doc_id, "chunks.jsonl")
    jsonl = "\n".join(json.dumps(c.to_dict()) for c in chunks)
    minio_client.put_object_text(bucket, chunked_key, jsonl)

    return {**prev, "chunked_key": chunked_key, "chunk_count": len(chunks)}
