"""Ontology build stage: LLM extracts entities/relations from the chunks against the fixed schema, the result is validated, saved to MinIO as Turtle + JSON, and loaded into GraphDB (schema and per-document instance data in separate named graphs)."""
from __future__ import annotations

import json
import logging

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


def _extract(passages: list[str], known_ids: list[str]) -> dict | None:
    user = prompts.EXTRACTION_USER.format(
        known_ids=", ".join(known_ids) or "(none yet)",
        passages="\n\n---\n\n".join(passages),
    )
    raw = llm.complete(prompts.extraction_system(), user, json_mode=True)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Extraction batch returned invalid JSON; skipping it.")
        return None


def doc_graph_iri(doc_id: str) -> str:
    return f"https://gates.example.org/lic/graph/doc/{doc_id}"


def run(prev: dict) -> dict:
    bucket, doc_id = prev["bucket"], prev["doc_id"]
    texts = [c["text"] for c in read_chunks(bucket, prev["chunked_key"])]

    verdict = hooks.check_document("\n\n".join(texts))
    if not verdict.allowed:
        raise RuntimeError(f"Document {doc_id} rejected by document hook: {verdict.reason}")

    batches, known_ids = [], []
    for passages in _batches(texts):
        data = _extract(passages, known_ids)
        if data:
            batches.append(data)
            known_ids.extend(facts.slug(e.get("id") or e.get("label")) for e in data.get("entities") or [])

    entities, relations, dropped = facts.merge_batches(batches)
    if not entities:
        raise RuntimeError(f"No ontology entities could be extracted for {doc_id}.")
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
