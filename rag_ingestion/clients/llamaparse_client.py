"""
rag_ingestion.clients.llamaparse_client
------------------------------------------
Production backend : LlamaParse (LlamaCloud) -- PDF -> markdown, handles
                      tables/layout much better than raw text extraction.
Fallback backend    : pypdf page-by-page text extraction (already a root
                      dependency), used when llama_parse isn't installed
                      or LLAMA_CLOUD_API_KEY isn't configured.
"""
from __future__ import annotations

import logging
import os
import tempfile

from rag_ingestion import config

logger = logging.getLogger(__name__)


def parse_pdf_bytes(pdf_bytes: bytes, filename: str) -> tuple[str, dict]:
    """Returns (markdown_text, parse_meta_dict)."""
    if config.HAS_LLAMA_PARSE and config.LLAMA_CLOUD_API_KEY:
        try:
            return _parse_live(pdf_bytes, filename)
        except Exception as error:
            logger.warning("LlamaParse failed (%s); falling back to pypdf extraction.", error)
    return _parse_fallback(pdf_bytes)


def _parse_live(pdf_bytes: bytes, filename: str) -> tuple[str, dict]:
    from llama_parse import LlamaParse

    parser = LlamaParse(api_key=config.LLAMA_CLOUD_API_KEY, result_type="markdown")

    suffix = os.path.splitext(filename)[1] or ".pdf"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(pdf_bytes)
        temp_path = tmp.name

    try:
        documents = parser.load_data(temp_path)
        markdown_text = "\n\n".join(doc.text for doc in documents)
        parse_meta = {"backend": "llamaparse", "num_pages": len(documents)}
        return markdown_text, parse_meta
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass


def _parse_fallback(pdf_bytes: bytes) -> tuple[str, dict]:
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    parse_meta = {"backend": "pypdf-fallback", "num_pages": len(reader.pages)}
    return text, parse_meta
