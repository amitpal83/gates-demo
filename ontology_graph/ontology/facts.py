"""Validates LLM-extracted entities against the compact schema, enforces the node caps, builds the derived nodes and structural links in code, and renders the instance data (ABox) as Turtle."""
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


def _apply_caps(entities: dict, dropped: Counter) -> None:
    seen: Counter = Counter()
    for entity_id in list(entities):
        cls = entities[entity_id]["class"]
        cap = schema.CLASS_CAPS.get(cls)
        seen[cls] += 1
        if cap is not None and seen[cls] > cap:
            del entities[entity_id]
            dropped["over_cap"] += 1


def merge_batches(batches: list[dict]) -> tuple[dict, list[tuple[str, str, str]], dict]:
    """Returns (entities by id, sorted unique (s, p, o) relations, counts of what was dropped and why)."""
    entities: dict[str, dict] = {}
    dropped: Counter = Counter()

    for batch in batches:
        for raw in batch.get("entities") or []:
            entity_id = slug(raw.get("id") or raw.get("label"))
            cls = raw.get("class")
            if not entity_id or cls not in schema.CLASSES or cls in schema.DERIVED_CLASSES:
                dropped["bad_entity"] += 1
                continue
            entity = entities.setdefault(entity_id, {"class": cls, "label": str(raw.get("label") or entity_id), "props": {}})
            for key, value in (raw.get("props") or {}).items():
                coerced = _coerce(value, key)
                if coerced is None:
                    dropped["bad_property"] += 1
                else:
                    entity["props"].setdefault(key, coerced)  # first value wins so later batches can't drift it

    _apply_caps(entities, dropped)

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


def _infer_per_year(label: str) -> int | None:
    text = label.lower()
    if "half" in text:
        return 2
    if "quarter" in text:
        return 4
    if "month" in text:
        return 12
    if "year" in text or "annual" in text:
        return 1
    return None


def apply_mode_codes(entities: dict) -> None:
    """Fills installmentsPerYear / intervalMonths if the LLM missed them, then assigns the demo modeCode in code (never by the LLM)."""
    for entity in entities.values():
        if entity["class"] != "PremiumMode":
            continue
        props = entity["props"]
        per_year = props.get("installmentsPerYear") or _infer_per_year(entity["label"])
        if per_year is None:
            continue
        props["installmentsPerYear"] = per_year
        if "intervalMonths" not in props and 12 % per_year == 0:
            props["intervalMonths"] = 12 // per_year
        code = schema.MODE_CODE_BY_PER_YEAR.get(per_year)
        if code is not None:
            props["modeCode"] = code


def link_structure(entities: dict, relations: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    """Builds the GracePeriod / LockInPeriod nodes from extracted numbers and wires every structural link in code, so the graph shape doesn't depend on the LLM."""
    linked = set(relations)
    by_class: dict[str, list[str]] = {}
    for entity_id, entity in entities.items():
        by_class.setdefault(entity["class"], []).append(entity_id)

    for mode_id in by_class.get("PremiumMode", []):
        days = entities[mode_id]["props"].pop("graceDays", None)
        if days is None:
            continue
        grace_id = f"grace_{days}_days"
        entities.setdefault(grace_id, {
            "class": "GracePeriod",
            "label": f"{days}-day grace period",
            "props": {"days": days, "description": f"An unpaid installment can still be paid within {days} days of its due date."},
        })
        linked.add((mode_id, "hasGracePeriod", grace_id))

    for plan_id in by_class.get("Plan", []):
        years = entities[plan_id]["props"].pop("lockInYears", None)
        if years is not None:
            entities.setdefault("lock_in_period", {
                "class": "LockInPeriod",
                "label": f"{years}-year lock-in",
                "props": {"durationYears": float(years), "description": f"No partial withdrawal or surrender is allowed during the first {years} years."},
            })
            linked.add((plan_id, "hasLockIn", "lock_in_period"))
        for relation, target_class in (("issuedBy", "Insurer"), ("acceptsMode", "PremiumMode"), ("hasBenefit", "Benefit")):
            for target in by_class.get(target_class, []):
                linked.add((plan_id, relation, target))
    return sorted(linked)


def validate_compact(entities: dict, relations: list[tuple[str, str, str]]) -> None:
    """Fails loudly if the extraction can't support the demo: one Plan with a UIN, all four installment modes, and a grace period on every mode."""
    plans = [e for e in entities.values() if e["class"] == "Plan"]
    if len(plans) != 1 or not plans[0]["props"].get("uin"):
        raise RuntimeError(f"Expected exactly one Plan with a uin; found {[(p['label'], p['props'].get('uin')) for p in plans]}.")
    modes = {i: e for i, e in entities.items() if e["class"] == "PremiumMode"}
    per_year = sorted(e["props"].get("installmentsPerYear") for e in modes.values())
    if per_year != sorted(schema.MODE_CODE_BY_PER_YEAR):
        raise RuntimeError(f"Expected installment modes with installmentsPerYear {sorted(schema.MODE_CODE_BY_PER_YEAR)}; extracted {per_year}.")
    with_grace = {s for s, p, _ in relations if p == "hasGracePeriod"}
    missing = [modes[i]["label"] for i in modes if i not in with_grace]
    if missing:
        raise RuntimeError(f"No graceDays extracted for modes: {missing}.")
    if len(entities) > sum(schema.CLASS_CAPS.values()):
        raise RuntimeError(f"Graph has {len(entities)} nodes, over the {sum(schema.CLASS_CAPS.values())} allowed.")


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
