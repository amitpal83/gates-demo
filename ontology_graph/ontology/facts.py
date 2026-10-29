"""Validates LLM-extracted entities and relations against the schema, merges batches, and renders the instance data (ABox) as Turtle."""
from __future__ import annotations

import re
from collections import Counter

from ontology_graph.ontology import schema


def slug(text) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text or "").lower()).strip("_")


def _coerce(value, key: str):
    spec = schema.DATA_PROPERTIES.get(key)
    if spec is None or value is None:
        return None
    xsd = spec[0]
    if xsd == "string":
        text = str(value).strip()
        return text or None
    cleaned = re.sub(r"(?i)rs\.?|inr|%|,", "", str(value)).strip()
    try:
        number = float(cleaned)
    except ValueError:
        return None
    if xsd == "integer":
        return int(number) if number.is_integer() else None
    return number


def merge_batches(batches: list[dict]) -> tuple[dict, list[tuple[str, str, str]], dict]:
    """Returns (entities by id, sorted unique (s, p, o) relations, counts of what was dropped and why)."""
    entities: dict[str, dict] = {}
    dropped: Counter = Counter()

    for batch in batches:
        for raw in batch.get("entities") or []:
            entity_id = slug(raw.get("id") or raw.get("label"))
            cls = raw.get("class")
            if not entity_id or cls not in schema.CLASSES:
                dropped["bad_entity"] += 1
                continue
            entity = entities.setdefault(entity_id, {"class": cls, "label": str(raw.get("label") or entity_id), "props": {}})
            for key, value in (raw.get("props") or {}).items():
                coerced = _coerce(value, key)
                if coerced is None:
                    dropped["bad_property"] += 1
                else:
                    entity["props"].setdefault(key, coerced)  # first value wins so later batches can't drift it

    relations: set[tuple[str, str, str]] = set()
    for batch in batches:
        for rel in batch.get("relations") or []:
            s, p, o = slug(rel.get("s")), rel.get("p"), slug(rel.get("o"))
            if s not in entities or o not in entities:
                dropped["dangling_relation"] += 1
                continue
            spec = schema.OBJECT_PROPERTIES.get(p)
            if spec is None:
                dropped["unknown_relation"] += 1
                continue
            domain, rng, _ = spec
            if (domain and not schema.is_a(entities[s]["class"], domain)) or (rng and not schema.is_a(entities[o]["class"], rng)):
                dropped["type_mismatch"] += 1
                continue
            relations.add((s, p, o))

    return entities, sorted(relations), dict(dropped)


def _literal(value, xsd: str) -> str:
    if xsd == "string":
        return schema._lit(str(value))
    if xsd == "integer":
        return f'"{int(value)}"^^xsd:integer'
    text = f"{float(value):.6f}".rstrip("0").rstrip(".") or "0"
    return f'"{text}"^^xsd:decimal'


def to_turtle(entities: dict, relations: list[tuple[str, str, str]]) -> str:
    lines = [
        f"@prefix lic: <{schema.LIC_NS}> .",
        f"@prefix data: <{schema.DATA_NS}> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        "",
    ]
    rels_by_subject: dict[str, list[tuple[str, str]]] = {}
    for s, p, o in relations:
        rels_by_subject.setdefault(s, []).append((p, o))

    for entity_id, entity in sorted(entities.items()):
        parts = [f"a lic:{entity['class']}", f"rdfs:label {schema._lit(entity['label'])}"]
        for key, value in sorted(entity["props"].items()):
            parts.append(f"lic:{key} {_literal(value, schema.DATA_PROPERTIES[key][0])}")
        for p, o in rels_by_subject.get(entity_id, []):
            parts.append(f"lic:{p} data:{o}")
        lines.append(f"data:{entity_id} " + " ;\n    ".join(parts) + " .")
    return "\n".join(lines) + "\n"
