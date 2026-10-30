"""SPARQL used at question time: fetches the plan, its insurer, lock-in and benefit, and only the installment mode the policy uses (with that mode's grace period), joined on the policy's plan UIN and mode code."""
from __future__ import annotations

import re

from ontology_graph.ontology import schema

_RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"


def policy_context_query(plan_uin: str, mode_code: int) -> str:
    return f"""
PREFIX lic: <{schema.LIC_NS}>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
SELECT DISTINCT ?subject ?slabel ?pred ?obj ?olabel WHERE {{
  ?plan lic:uin {schema._lit(plan_uin)} .
  {{ BIND(?plan AS ?subject) }}
  UNION {{ ?plan lic:issuedBy ?subject }}
  UNION {{ ?plan lic:hasLockIn ?subject }}
  UNION {{ ?plan lic:hasBenefit ?subject }}
  UNION {{ ?plan lic:acceptsMode ?subject . ?subject lic:modeCode {int(mode_code)} }}
  UNION {{ ?plan lic:acceptsMode ?mode . ?mode lic:modeCode {int(mode_code)} . ?mode lic:hasGracePeriod ?subject }}
  ?subject ?pred ?obj .
  FILTER(STRSTARTS(STR(?pred), "{schema.LIC_NS}") || (?pred = rdf:type && STRSTARTS(STR(?obj), "{schema.LIC_NS}")))
  OPTIONAL {{ ?subject rdfs:label ?slabel }}
  OPTIONAL {{ ?obj rdfs:label ?olabel }}
}}
LIMIT 200
"""


def _local(iri: str) -> str:
    return re.split(r"[#/]", iri)[-1]


def rows_to_lines(rows: list[dict]) -> list[str]:
    """Groups SPARQL rows by subject into readable lines for the prompt."""
    grouped: dict[str, dict] = {}
    for row in rows:
        subject = grouped.setdefault(row["subject"], {"label": row.get("slabel") or _local(row["subject"]), "types": set(), "facts": []})
        pred = row["pred"]
        if pred == _RDF_TYPE:
            subject["types"].add(_local(row["obj"]))
            continue
        obj = row.get("olabel") or (_local(row["obj"]) if row["obj"].startswith(schema.DATA_NS) else row["obj"])
        subject["facts"].append(f"{_local(pred)}={obj}")

    lines = []
    for subject in sorted(grouped.values(), key=lambda s: s["label"]):
        types = ", ".join(sorted(subject["types"]))
        lines.append(f"{subject['label']} [{types}]: " + "; ".join(sorted(subject["facts"])))
    return lines
