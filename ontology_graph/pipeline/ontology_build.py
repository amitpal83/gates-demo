"""Ontology build stage: LLM extracts entities/relations from the chunks against the fixed schema, the result is validated, saved to MinIO as Turtle + JSON, and loaded into GraphDB (schema and per-document instance data in separate named graphs)."""
from __future__ import annotations

import json
import logging
import re

from ontology_graph import config, hooks, llm, prompts
from ontology_graph.clients import graphdb, minio_store
from ontology_graph.ontology import facts, schema
from ontology_graph.pipeline.common import stage_key
from ontology_graph.pipeline.ingest import read_chunks

logger = logging.getLogger(__name__)

_BATCH_CHARS = 7000


def _batches(texts: list[str]) -> list[list[str]]:
    batches, current, size = [], [], 0
    for text in texts:
        if current and size + len(text) > _BATCH_CHARS:
            batches.append(current)
            current, size = [], 0
        current.append(text)
        size += len(text)
    if current:
        batches.append(current)
    return batches


_WORDS = re.compile(r"[a-z0-9]+")


def _words(text: str) -> str:
    return " ".join(_WORDS.findall(str(text).lower()))


def _supported(value, quote, haystack: str) -> bool:
    """A value is kept only if its quote really appears in the batch's passages and, for numbers, the number appears in the quote."""
    quote_words = _words(quote)
    if len(quote_words) < 6 or f" {quote_words} " not in haystack:
        return False
    try:
        number = float(re.sub(r"(?i)rs\.?|inr|%|,", "", str(value)))
    except ValueError:
        return True  # non-numeric text value: the quote being present in the passages is the evidence
    return not number.is_integer() or str(int(number)) in re.sub(r"[^0-9]", "", str(quote))


def _ground(data: dict, passages_text: str) -> int:
    """Replaces each {"value", "quote"} prop with the plain value if supported, else drops it; returns how many were dropped."""
    haystack = f" {_words(passages_text)} "
    removed = 0
    for entity in data.get("entities") or []:
        grounded = {}
        for key, raw in (entity.get("props") or {}).items():
            if isinstance(raw, dict) and "value" in raw and _supported(raw["value"], raw.get("quote", ""), haystack):
                grounded[key] = raw["value"]
            elif key == "description" and isinstance(raw, str):
                grounded[key] = raw
            else:
                removed += 1
        entity["props"] = grounded
    return removed


def _extract(passages: list[str], known_ids: list[str]) -> tuple[dict, int] | None:
    passages_text = "\n\n---\n\n".join(passages)
    user = prompts.EXTRACTION_USER.format(known_ids=", ".join(known_ids) or "(none yet)", passages=passages_text)
    raw = llm.complete(prompts.extraction_system(), user, json_mode=True)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Extraction batch returned invalid JSON; skipping it.")
        return None
    if not isinstance(data, dict):
        return None
    return data, _ground(data, passages_text)


def doc_graph_iri(doc_id: str) -> str:
    return f"https://gates.example.org/lic/graph/doc/{doc_id}"


def run(prev: dict) -> dict:
    bucket, doc_id = prev["bucket"], prev["doc_id"]
    texts = [c["text"] for c in read_chunks(bucket, prev["chunked_key"])]

    verdict = hooks.check_document("\n\n".join(texts))
    if not verdict.allowed:
        raise RuntimeError(f"Document {doc_id} rejected by document hook: {verdict.reason}")

    batches, known_ids, unsupported = [], [], 0
    for passages in _batches(texts):
        extracted = _extract(passages, known_ids)
        if extracted:
            data, removed = extracted
            unsupported += removed
            batches.append(data)
            known_ids.extend(facts.slug(e.get("id") or e.get("label")) for e in data.get("entities") or [])

    entities, relations, dropped = facts.merge_batches(batches)
    if unsupported:
        dropped["unsupported_prop"] = unsupported
    if not entities:
        raise RuntimeError(f"No ontology entities could be extracted for {doc_id}.")
    facts.apply_mode_codes(entities)
    relations = facts.link_structure(entities, relations)
    try:  # saved before validation so a failed run can still be inspected in MinIO
        minio_store.put_json(bucket, stage_key("ontology", doc_id, "extraction_debug.json"), {
            "raw_llm_batches": batches,
            "entities": entities,
            "relations": relations,
            "dropped": dropped,
        })
    except Exception:
        logger.warning("Could not save the extraction debug file.", exc_info=True)
    facts.validate_compact(entities, relations)
    turtle = facts.to_turtle(entities, relations)

    ontology_key = stage_key("ontology", doc_id, "ontology.ttl")
    minio_store.put_text(bucket, ontology_key, turtle, "text/turtle")
    minio_store.put_text(bucket, stage_key("ontology", doc_id, "schema.ttl"), schema.to_turtle(), "text/turtle")
    minio_store.put_json(bucket, stage_key("ontology", doc_id, "facts.json"), {
        "entities": entities,
        "relations": relations,
        "dropped": dropped,
    })

    graphdb.wait_ready()
    graphdb.ensure_repository()
    graphdb.replace_graph(schema.SCHEMA_GRAPH, schema.to_turtle())
    graphdb.replace_graph(doc_graph_iri(doc_id), turtle)

    return {
        **prev,
        "ontology_key": ontology_key,
        "entity_count": len(entities),
        "relation_count": len(relations),
        "dropped": dropped,
        "graphdb_repository": config.GRAPHDB_REPOSITORY,
    }
