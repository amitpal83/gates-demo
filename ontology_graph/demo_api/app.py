"""FastAPI backend for the demo front end: policies, the plan ontology as nodes/edges, and /api/compare which asks the same question of the ontology-backed agent and the SQL-only agent and scores both against ground truth. Also serves the built React app from ./static when present."""
from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ontology_graph import agent, hooks, truth
from ontology_graph.clients import graphdb, policy_store
from ontology_graph.ontology import schema

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="lic-demo-api")

_POLICY_RE = re.compile(r"^[A-Z0-9-]{3,24}$")
PRESET_QUESTIONS = [
    "How many premium payments do I make each year, and what is the total premium I will pay over the premium paying term?",
    "When is my next premium due, and how many days of grace do I get to pay it?",
    "How often do I pay, and how much do I pay each time?",
]


class CompareRequest(BaseModel):
    policy_number: str = Field(..., min_length=3, max_length=24)
    question: str = Field(..., min_length=3, max_length=500)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/questions")
def questions() -> list[str]:
    return PRESET_QUESTIONS


@app.get("/api/policies")
def policies() -> list[dict]:
    """Policies as the database stores them: mode_code is raw, with no meaning attached."""
    try:
        return [policy_store.get_policy(p["policy_number"]) for p in policy_store.list_policies()]
    except Exception as error:
        logger.exception("Could not read policies")
        raise HTTPException(status_code=502, detail=f"Could not read the policy database: {error}")


@app.get("/api/ontology")
def ontology() -> dict:
    """The extracted plan graph as {nodes, edges} for the React Flow view."""
    prefix = f"PREFIX lic: <{schema.LIC_NS}>\nPREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
    scope = f'FILTER(STRSTARTS(STR(?s), "{schema.DATA_NS}")) FILTER(STRSTARTS(STR(?cls), "{schema.LIC_NS}"))'
    try:
        attr_rows = graphdb.select(
            prefix + f"SELECT ?s ?cls ?label ?p ?v WHERE {{ ?s a ?cls . OPTIONAL {{ ?s rdfs:label ?label }} "
            f"OPTIONAL {{ ?s ?p ?v . FILTER(isLiteral(?v) && ?p != rdfs:label) }} {scope} }}",
            infer=False,
        )
        edge_rows = graphdb.select(
            prefix + f'SELECT ?s ?p ?o WHERE {{ ?s ?p ?o . FILTER(STRSTARTS(STR(?s), "{schema.DATA_NS}")) '
            f'FILTER(STRSTARTS(STR(?o), "{schema.DATA_NS}")) FILTER(STRSTARTS(STR(?p), "{schema.LIC_NS}")) }}',
            infer=False,
        )
    except Exception as error:
        logger.exception("GraphDB query failed")
        raise HTTPException(status_code=502, detail=f"Could not read the ontology from GraphDB: {error}")

    nodes: dict[str, dict] = {}
    for row in attr_rows:
        node_id = row["s"].rsplit("/", 1)[-1]
        node = nodes.setdefault(node_id, {"id": node_id, "label": row.get("label") or node_id, "class": row["cls"].rsplit("#", 1)[-1], "props": {}})
        if row.get("p") is not None:
            node["props"][row["p"].rsplit("#", 1)[-1]] = row["v"]
    edges = [
        {"id": f"{r['s'].rsplit('/', 1)[-1]}-{r['p'].rsplit('#', 1)[-1]}-{r['o'].rsplit('/', 1)[-1]}",
         "source": r["s"].rsplit("/", 1)[-1], "target": r["o"].rsplit("/", 1)[-1], "label": r["p"].rsplit("#", 1)[-1]}
        for r in edge_rows
    ]
    return {"nodes": list(nodes.values()), "edges": edges}


@app.post("/api/compare")
def compare(request: CompareRequest) -> dict:
    if not _POLICY_RE.match(request.policy_number):
        raise HTTPException(status_code=422, detail="Invalid policy number.")
    verdict = hooks.check_question(request.question)
    if not verdict.allowed:
        raise HTTPException(status_code=422, detail=verdict.reason)
    try:
        record, notes = agent.load_policy_context(request.policy_number)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except Exception as error:
        logger.exception("Could not load the policy")
        raise HTTPException(status_code=502, detail=f"Could not read the policy database: {error}")

    expected = truth.ground_truth(record)
    with ThreadPoolExecutor(max_workers=2) as pool:
        future_a = pool.submit(agent.run_ontology_agent, record, notes, request.question)
        future_b = pool.submit(agent.run_sql_only_agent, record, notes, request.question)
        try:
            result_a, result_b = future_a.result(), future_b.result()
        except Exception as error:
            logger.exception("An agent failed")
            raise HTTPException(status_code=502, detail=f"An agent failed: {error}")

    response = {"policy_number": request.policy_number, "question": request.question, "truth": expected}
    for key, result in (("ontology_agent", result_a), ("sql_agent", result_b)):
        checks = truth.check_answer(expected, result["answer"])
        response[key] = {**result, "checks": checks, "summary": truth.summarize(checks)}
    return response


_STATIC = Path(__file__).resolve().parent.parent / "static"
if _STATIC.is_dir():
    app.mount("/", StaticFiles(directory=_STATIC, html=True), name="static")
