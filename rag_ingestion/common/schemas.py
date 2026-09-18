"""Dataclasses shared by ingestion tasks. Cross task boundaries as JSON/JSONL, never as XCom-carried objects -- each task re-reads its input from MinIO."""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class ParsedDocument:
    doc_id: str
    parsed_key: str
    parse_meta_key: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ParsedDocument":
        return cls(**data)


@dataclass
class Chunk:
    chunk_index: int
    text: str
    page_number: int | None
    section_title: str | None
    char_start: int
    char_end: int

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Chunk":
        return cls(**{k: data.get(k) for k in
                       ("chunk_index", "text", "page_number", "section_title",
                        "char_start", "char_end")})


@dataclass
class EnrichedChunk:
    chunk_index: int
    text: str
    page_number: int | None
    section_title: str | None
    char_start: int
    char_end: int
    pdf_type: str
    author: str
    owner: str
    ingestion_ts: int
    source_object_key: str
    guardrail_backend: str
    guardrail_passed: bool

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "EnrichedChunk":
        fields = (
            "chunk_index", "text", "page_number", "section_title", "char_start",
            "char_end", "pdf_type", "author", "owner", "ingestion_ts",
            "source_object_key", "guardrail_backend", "guardrail_passed",
        )
        return cls(**{k: data.get(k) for k in fields})


@dataclass
class EmbeddingRecord:
    chunk_index: int
    vector: list[float]
    payload: dict
    sparse_indices: list[int] = None
    sparse_values: list[float] = None

    def __post_init__(self):
        if self.sparse_indices is None:
            self.sparse_indices = []
        if self.sparse_values is None:
            self.sparse_values = []

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "EmbeddingRecord":
        return cls(
            chunk_index=data["chunk_index"],
            vector=data["vector"],
            payload=data.get("payload", {}),
            sparse_indices=data.get("sparse_indices", []),
            sparse_values=data.get("sparse_values", []),
        )
