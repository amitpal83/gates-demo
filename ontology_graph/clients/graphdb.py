"""GraphDB (RDF4J-compatible) REST client: repository bootstrap, named-graph replace, SPARQL select, Turtle export."""
from __future__ import annotations

import logging
import time

import httpx

from ontology_graph import config

logger = logging.getLogger(__name__)

_REPO_CONFIG = """
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>.
@prefix rep: <http://www.openrdf.org/config/repository#>.
@prefix sr: <http://www.openrdf.org/config/repository/sail#>.
@prefix sail: <http://www.openrdf.org/config/sail#>.
@prefix graphdb: <http://www.ontotext.com/config/graphdb#>.

[] a rep:Repository ;
    rep:repositoryID "__REPO_ID__" ;
    rdfs:label "LIC policy ontology" ;
    rep:repositoryImpl [
        rep:repositoryType "graphdb:SailRepository" ;
        sr:sailImpl [
            sail:sailType "graphdb:Sail" ;
            graphdb:ruleset "rdfsplus-optimized" ;
            graphdb:check-for-inconsistencies "false" ;
            graphdb:disable-sameAs "true" ;
            graphdb:entity-id-size "32" ;
            graphdb:enable-context-index "false" ;
            graphdb:enablePredicateList "true" ;
            graphdb:enable-literal-index "true" ;
            graphdb:in-memory-literal-properties "true" ;
            graphdb:storage-folder "storage" ;
            graphdb:base-URL "http://example.org/owlim#"
        ]
    ].
"""


def _client() -> httpx.Client:
    return httpx.Client(base_url=config.GRAPHDB_URL, timeout=120.0)


def wait_ready(timeout_s: int = 180) -> None:
    deadline = time.time() + timeout_s
    while True:
        try:
            with _client() as client:
                if client.get("/rest/repositories").status_code == 200:
                    return
        except httpx.HTTPError:
            pass
        if time.time() > deadline:
            raise RuntimeError(f"GraphDB at {config.GRAPHDB_URL} did not become ready within {timeout_s}s.")
        time.sleep(3)


def ensure_repository() -> None:
    with _client() as client:
        listing = client.get("/rest/repositories")
        listing.raise_for_status()
        if any(repo.get("id") == config.GRAPHDB_REPOSITORY for repo in listing.json()):
            return
        repo_config = _REPO_CONFIG.replace("__REPO_ID__", config.GRAPHDB_REPOSITORY)
        response = client.post("/rest/repositories", files={"config": ("repo-config.ttl", repo_config, "text/turtle")})
        response.raise_for_status()
        logger.info("Created GraphDB repository %s", config.GRAPHDB_REPOSITORY)


def replace_graph(graph_iri: str, turtle: str) -> None:
    """Idempotent: clears the named graph, then loads the Turtle into it."""
    statements = f"/repositories/{config.GRAPHDB_REPOSITORY}/statements"
    context = f"<{graph_iri}>"
    with _client() as client:
        client.delete(statements, params={"context": context}).raise_for_status()
        client.post(
            statements,
            params={"context": context},
            content=turtle.encode("utf-8"),
            headers={"Content-Type": "text/turtle"},
        ).raise_for_status()


def select(query: str, infer: bool = True) -> list[dict]:
    """Runs a SPARQL SELECT; returns one {variable: value} dict per row."""
    with _client() as client:
        response = client.post(
            f"/repositories/{config.GRAPHDB_REPOSITORY}",
            data={"query": query, "infer": "true" if infer else "false"},
            headers={"Accept": "application/sparql-results+json"},
        )
        response.raise_for_status()
    bindings = response.json()["results"]["bindings"]
    return [{var: cell["value"] for var, cell in row.items()} for row in bindings]


def export_turtle() -> str:
    with _client() as client:
        response = client.get(
            f"/repositories/{config.GRAPHDB_REPOSITORY}/statements",
            params={"infer": "false"},
            headers={"Accept": "text/turtle"},
        )
        response.raise_for_status()
    return response.text
