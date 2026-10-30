"""Ontology build stage: LLM extracts entities/relations from the chunks against the fixed schema, every fact must be backed by a quote found in the passages, the result is validated, saved to MinIO as Turtle + JSON, and loaded into GraphDB (schema and per-document instance data in separate named graphs)."""
from __future__ import annotations

import copy
import json
import logging
import re
from collections import Counter

from ontology_graph import config, hooks, llm, prompts
from ontology_graph.clients import graphdb, minio_store
from ontology_graph.ontology import facts, schema
from ontology_graph.pipeline.common import stage_key
from ontology_graph.pipeline.ingest import read_chunks

logger = logging.getLogger(__name__)

_BATCH_CHARS = 7000
_MIN_QUOTE_WORDS = 3
_MIN_COVERAGE = 0.85  # share of the quote's distinct words that must sit together in one window of the passages
_WINDOW_SLACK = 2.0  # the window may be this many times longer than the quote, so a rewritten or per-mode quote still fits


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


def _words(text: str) -> list[str]:
    return _WORDS.findall(str(text).lower())


def _coverage(quote_words: list[str], haystack: list[str]) -> float:
    """Best share of the quote's distinct words found together inside any one window of the passages."""
    wanted = set(quote_words)
    size = int(len(quote_words) * _WINDOW_SLACK) + 2
    counts: Counter = Counter()
    present, best = 0, 0.0
    for i, word in enumerate(haystack):
        if word in wanted:
            counts[word] += 1
            present += counts[word] == 1
        old = i - size
        if old >= 0 and haystack[old] in wanted:
            counts[haystack[old]] -= 1
            present -= counts[haystack[old]] == 0
        best = max(best, present / len(wanted))
    return best


def _mentions(label: str, quote_words: list[str]) -> bool:
    """True if the quote names the entity (e.g. the premium mode); 'half yearly' is not mistaken for 'yearly'."""
    label_words = _words(re.split(r"[(\[]", str(label))[0])
    if not label_words:
        return False
    if len(label_words) > 1:
        n = len(label_words)
        return any(quote_words[i:i + n] == label_words for i in range(len(quote_words) - n + 1))
    return any(word == label_words[0] and (i == 0 or quote_words[i - 1] != "half") for i, word in enumerate(quote_words))


def _check(value, quote, haystack: list[str], entity_label: str, key: str) -> str | None:
    """None if the value is supported by its quote in the passages, else the reason it is not."""
    quote_words = _words(quote)
    if len(quote_words) < _MIN_QUOTE_WORDS:
        return "quote too short or missing"
    if _coverage(quote_words, haystack) < _MIN_COVERAGE:
        return "quote not found in the passages"
    try:
        number = float(re.sub(r"(?i)rs\.?|inr|%|,", "", str(value)))
    except ValueError:
        number = None  # non-numeric text value: the quote being present in the passages is the evidence
    if number is not None and number.is_integer() and str(int(number)) not in re.sub(r"[^0-9]", "", str(quote)):
        return "number not in the quote"
    if key in schema.PER_ENTITY_QUOTE_PROPS and not _mentions(entity_label, quote_words):
        return "quote does not name the entity"
    pattern = schema.PROP_FORMATS.get(key)
    if pattern and not re.fullmatch(pattern, str(value).strip()):
        return "value has the wrong format"
    return None


def _ground(data: dict, passages_text: str) -> list[dict]:
    """Replaces each {"value", "quote"} prop with the plain value if supported, else drops it; returns the rejected props with reasons."""
    haystack = _words(passages_text)
    rejected = []
    for entity in data.get("entities") or []:
        grounded = {}
        for key, raw in (entity.get("props") or {}).items():
            if key == "description" and isinstance(raw, str):
                grounded[key] = raw
                continue
            if not (isinstance(raw, dict) and "value" in raw):
                rejected.append({"entity": entity.get("id"), "prop": key, "value": raw, "quote": None, "reason": "not a {value, quote} object"})
                continue
            reason = _check(raw["value"], raw.get("quote", ""), haystack, str(entity.get("label") or entity.get("id") or ""), key)
            if reason is None:
                grounded[key] = raw["value"]
            else:
                rejected.append({"entity": entity.get("id"), "prop": key, "value": raw["value"], "quote": raw.get("quote"), "reason": reason})
        entity["props"] = grounded
    return rejected


def _extract(passages: list[str], known_ids: list[str]) -> tuple[dict, dict, list[dict]] | None:
    """Returns (raw model output, grounded output, rejected props)."""
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
    grounded = copy.deepcopy(data)
    return data, grounded, _ground(grounded, passages_text)


def doc_graph_iri(doc_id: str) -> str:
    return f"https://gates.example.org/lic/graph/doc/{doc_id}"


def run(prev: dict) -> dict:
    bucket, doc_id = prev["bucket"], prev["doc_id"]
    texts = [c["text"] for c in read_chunks(bucket, prev["chunked_key"])]

    verdict = hooks.check_document("\n\n".join(texts))
    if not verdict.allowed:
        raise RuntimeError(f"Document {doc_id} rejected by document hook: {verdict.reason}")

    raw_batches, batches, rejected, known_ids = [], [], [], []
    for passages in _batches(texts):
        extracted = _extract(passages, known_ids)
        if extracted:
            raw, grounded, rejects = extracted
            raw_batches.append(raw)
            batches.append(grounded)
            rejected.extend(rejects)
            known_ids.extend(facts.slug(e.get("id") or e.get("label")) for e in grounded.get("entities") or [])

    entities, relations, dropped = facts.merge_batches(batches)
    if rejected:
        dropped["unsupported_prop"] = len(rejected)
    try:  # saved before validation so a failed run can still be inspected in MinIO
        minio_store.put_json(bucket, stage_key("ontology", doc_id, "extraction_debug.json"), {
            "raw_llm_batches_before_grounding": raw_batches,
            "rejected_props": rejected,
            "merged_entities": entities,
            "dropped": dropped,
        })
    except Exception:
        logger.warning("Could not save the extraction debug file.", exc_info=True)
    if not entities:
        raise RuntimeError(f"No ontology entities could be extracted for {doc_id}.")
    if dropped.get("conflicts"):
        raise RuntimeError(f"Conflicting supported values for the same field: {dropped['conflicts']}")
    facts.apply_mode_codes(entities)
    relations = facts.link_structure(entities, relations)
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
