"""Ingestion stages for the LIC DAG: stage -> parse -> chunk -> embed+load. Each stage reads and writes MinIO under lic/ and returns a small dict (never large objects) for the next one."""
from __future__ import annotations

import io
import json
import os
import re
import tempfile
import time

from ontology_graph import config, hooks, llm
from ontology_graph.clients import minio_store, qdrant_store
from ontology_graph.pipeline.common import build_sparse_vector, compute_doc_id, point_id, stage_key

_PAGE_RE = re.compile(r"^<<<PAGE (\d+)>>>$")
_MAX_CHARS = 1200
_OVERLAP_CHARS = 250


def run_stage(conf: dict) -> dict:
    """conf: {bucket, object_key, etag} from the DAG run."""
    bucket = conf.get("bucket") or config.MINIO_BUCKET
    object_key, etag = conf["object_key"], conf["etag"]
    doc_id = compute_doc_id(object_key, etag)
    raw_key = stage_key("raw", doc_id, "source.pdf")
    minio_store.copy(bucket, object_key, raw_key)
    return {"bucket": bucket, "object_key": object_key, "etag": etag, "doc_id": doc_id, "raw_key": raw_key}


def _join_pages(pages: list[str]) -> str:
    return "\n\n".join(f"<<<PAGE {i}>>>\n\n{text}" for i, text in enumerate(pages, start=1))


def _parse_llamaparse(pdf_bytes: bytes) -> list[str]:
    from llama_parse import LlamaParse

    parser = LlamaParse(api_key=config.LLAMA_CLOUD_API_KEY, result_type="markdown")
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        path = tmp.name
    try:
        return [doc.text for doc in parser.load_data(path)]
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _parse_pypdf(pdf_bytes: bytes) -> list[str]:
    from pypdf import PdfReader

    return [page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf_bytes)).pages]


def run_parse(prev: dict) -> dict:
    bucket, doc_id = prev["bucket"], prev["doc_id"]
    pdf_bytes = minio_store.get_bytes(bucket, prev["raw_key"])

    backend = "pypdf"
    pages = None
    if config.LLAMA_CLOUD_API_KEY:
        try:
            pages = _parse_llamaparse(pdf_bytes)
            backend = "llamaparse"
        except Exception as error:
            print(f"LlamaParse failed ({error}); falling back to pypdf.")
    if pages is None:
        pages = _parse_pypdf(pdf_bytes)

    parsed_key = stage_key("parsed", doc_id, "parsed.md")
    minio_store.put_text(bucket, parsed_key, _join_pages(pages), "text/markdown")
    minio_store.put_json(bucket, stage_key("parsed", doc_id, "parse_meta.json"), {"backend": backend, "num_pages": len(pages)})
    return {**prev, "parsed_key": parsed_key, "parse_backend": backend, "num_pages": len(pages)}


def _hard_split(paragraph: str, max_chars: int) -> list[str]:
    """Splits an oversized paragraph (e.g. a long markdown table) on line boundaries, then by length."""
    if len(paragraph) <= max_chars:
        return [paragraph]
    pieces, current = [], ""
    for line in paragraph.split("\n"):
        while len(line) > max_chars:
            if current:
                pieces.append(current)
                current = ""
            pieces.append(line[:max_chars])
            line = line[max_chars:]
        if current and len(current) + len(line) + 1 > max_chars:
            pieces.append(current)
            current = ""
        current = f"{current}\n{line}" if current else line
    if current:
        pieces.append(current)
    return pieces


def split_markdown(text: str, max_chars: int = _MAX_CHARS, overlap_chars: int = _OVERLAP_CHARS) -> list[dict]:
    """Paragraph-aware chunks of ~max_chars; each carries the page it starts on, and the last short paragraph repeats as overlap."""
    chunks: list[dict] = []
    buf: list[str] = []
    buf_len = 0
    buf_page = None
    page = None

    def flush():
        if buf:
            chunks.append({"chunk_index": len(chunks), "text": "\n\n".join(buf), "page_number": buf_page})

    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        marker = _PAGE_RE.match(paragraph)
        if marker:
            page = int(marker.group(1))
            continue
        for piece in _hard_split(paragraph, max_chars):
            if buf and buf_len + len(piece) > max_chars:
                flush()
                last = buf[-1]
                buf = [last] if len(last) <= overlap_chars else []
                buf_len = sum(len(b) for b in buf)
                buf_page = page
            if not buf:
                buf_page = page
            buf.append(piece)
            buf_len += len(piece)
    flush()
    return chunks


def run_chunk(prev: dict) -> dict:
    bucket, doc_id = prev["bucket"], prev["doc_id"]
    text = minio_store.get_bytes(bucket, prev["parsed_key"]).decode("utf-8", errors="replace")
    chunks = split_markdown(text)
    chunked_key = stage_key("chunked", doc_id, "chunks.jsonl")
    minio_store.put_text(bucket, chunked_key, "\n".join(json.dumps(c) for c in chunks), "application/json")
    return {**prev, "chunked_key": chunked_key, "chunk_count": len(chunks)}


def read_chunks(bucket: str, chunked_key: str) -> list[dict]:
    raw = minio_store.get_bytes(bucket, chunked_key).decode("utf-8", errors="replace")
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


def run_embed_load(prev: dict) -> dict:
    bucket, doc_id = prev["bucket"], prev["doc_id"]
    chunks = read_chunks(bucket, prev["chunked_key"])
    texts = [c["text"] for c in chunks]

    verdict = hooks.check_document("\n\n".join(texts))
    if not verdict.allowed:
        raise RuntimeError(f"Document {doc_id} rejected by document hook: {verdict.reason}")

    vectors = llm.embed(texts)
    ingestion_ts = int(time.time())
    points = []
    for chunk, vector in zip(chunks, vectors):
        sparse_indices, sparse_values = build_sparse_vector(chunk["text"])
        points.append({
            "id": point_id(doc_id, chunk["chunk_index"]),
            "dense": vector,
            "sparse_indices": sparse_indices,
            "sparse_values": sparse_values,
            "payload": {
                "doc_id": doc_id,
                "doc_type": "lic_policy",
                "chunk_index": chunk["chunk_index"],
                "page_number": chunk.get("page_number"),
                "text": chunk["text"],
                "source_object_key": prev.get("object_key"),
                "ingestion_ts": ingestion_ts,
            },
        })

    client = qdrant_store.get_client()
    qdrant_store.ensure_collection(client, config.EMBEDDING_DIMENSIONS)
    qdrant_store.delete_doc(client, doc_id)
    qdrant_store.upsert(client, points)
    return {**prev, "upserted_count": len(points), "collection_name": config.QDRANT_COLLECTION}
