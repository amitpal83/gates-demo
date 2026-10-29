"""SPARQL used at question time: pulls the plan facts that matter for one policy (the plan, its non-fund relations, and only the fund the policy holds)."""
from __future__ import annotations

import re

from ontology_graph.ontology import schema

_RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"


def _lit(text: str) -> str:
    return schema._lit(text)


def policy_context_query(plan_uin: str, fund_name: str | None) -> str:
    fund_hint = re.sub(r"(?i)\bfund\b", "", fund_name or "").strip().lower()
    fund_branch = (
        f"UNION {{ ?plan lic:offersFund ?subject . ?subject rdfs:label ?fl . FILTER(CONTAINS(LCASE(STR(?fl)), {_lit(fund_hint)})) }}"
        if fund_hint else ""
    )
    return f"""
PREFIX lic: <{schema.LIC_NS}>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
SELECT DISTINCT ?subject ?slabel ?pred ?obj ?olabel WHERE {{
  ?plan lic:uin {_lit(plan_uin)} .
  {{ BIND(?plan AS ?subject) }}
  UNION {{ ?plan ?rel ?subject . FILTER(STRSTARTS(STR(?rel), "{schema.LIC_NS}") && ?rel != lic:offersFund) }}
  {fund_branch}
  ?subject ?pred ?obj .
  FILTER(STRSTARTS(STR(?pred), "{schema.LIC_NS}") || (?pred = rdf:type && STRSTARTS(STR(?obj), "{schema.LIC_NS}")))
  OPTIONAL {{ ?subject rdfs:label ?slabel }}
  OPTIONAL {{ ?obj rdfs:label ?olabel }}
}}
LIMIT 600
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
