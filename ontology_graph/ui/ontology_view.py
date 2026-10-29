"""Ontology tab: the fixed schema as a diagram, plus what was extracted from the ingested documents (counts, entities, instance graph) and Turtle downloads."""
from __future__ import annotations

import streamlit as st

from ontology_graph.clients import graphdb
from ontology_graph.ontology import schema

_PREFIX = f"PREFIX lic: <{schema.LIC_NS}>\nPREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"


def _dot_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def schema_dot(show_subclass_edges: bool) -> str:
    lines = ['digraph G { rankdir=LR; node [shape=box, style="rounded,filled", fillcolor="#eef3fb", fontsize=10]; edge [fontsize=9];']
    for name, (parent, _) in schema.CLASSES.items():
        lines.append(f'"{name}";')
        if parent and show_subclass_edges:
            lines.append(f'"{name}" -> "{parent}" [style=dashed, arrowhead=empty, color="#888888"];')
    for name, (domain, rng, _) in schema.OBJECT_PROPERTIES.items():
        if domain and rng:
            lines.append(f'"{domain}" -> "{rng}" [label="{name}"];')
    lines.append("}")
    return "\n".join(lines)


def instance_dot(rows: list[dict]) -> str:
    lines = ['digraph G { rankdir=LR; node [shape=box, style="rounded,filled", fillcolor="#fdf3d8", fontsize=10]; edge [fontsize=9];']
    for row in rows:
        s = _dot_escape(row.get("sl") or row["s"].rsplit("/", 1)[-1])
        o = _dot_escape(row.get("ol") or row["o"].rsplit("/", 1)[-1])
        p = _dot_escape(row["p"].rsplit("#", 1)[-1])
        lines.append(f'"{s}" -> "{o}" [label="{p}"];')
    lines.append("}")
    return "\n".join(lines)


def render() -> None:
    st.subheader("Schema")
    st.caption("The fixed classes and relations the extraction is allowed to use. Dashed arrows are subclass links.")
    show_sub = st.checkbox("Show subclass links", value=True)
    st.graphviz_chart(schema_dot(show_sub), use_container_width=True)
    st.download_button("Download schema (Turtle)", schema.to_turtle(), file_name="lic_schema.ttl", mime="text/turtle")

    st.subheader("Extracted from ingested documents")
    st.caption("Reads GraphDB. Upload a PDF to licdocuments/ in MinIO and wait for the lic_policy_ingestion DAG to finish.")
    try:
        counts = graphdb.select(
            _PREFIX + f'SELECT ?cls (COUNT(DISTINCT ?s) AS ?n) WHERE {{ ?s a ?cls . FILTER(STRSTARTS(STR(?s), "{schema.DATA_NS}")) '
            f'FILTER(STRSTARTS(STR(?cls), "{schema.LIC_NS}")) }} GROUP BY ?cls ORDER BY DESC(?n)'
        )
        entities = graphdb.select(
            _PREFIX + f'SELECT ?label ?cls WHERE {{ ?s a ?cls ; rdfs:label ?label . FILTER(STRSTARTS(STR(?s), "{schema.DATA_NS}")) '
            f'FILTER(STRSTARTS(STR(?cls), "{schema.LIC_NS}")) }} ORDER BY ?cls ?label',
            infer=False,
        )
        edges = graphdb.select(
            _PREFIX + f'SELECT ?s ?sl ?p ?o ?ol WHERE {{ ?s ?p ?o . FILTER(STRSTARTS(STR(?s), "{schema.DATA_NS}")) '
            f'FILTER(STRSTARTS(STR(?o), "{schema.DATA_NS}")) FILTER(STRSTARTS(STR(?p), "{schema.LIC_NS}")) '
            f'OPTIONAL {{ ?s rdfs:label ?sl }} OPTIONAL {{ ?o rdfs:label ?ol }} }} LIMIT 400',
            infer=False,
        )
    except Exception as error:
        st.info(f"GraphDB has no data yet, or is unreachable: {error}")
        return

    if not entities:
        st.info("Nothing extracted yet.")
        return

    left, right = st.columns([1, 2])
    with left:
        st.markdown("**Instances per class** (including subclasses)")
        st.dataframe([{"class": r["cls"].rsplit("#", 1)[-1], "count": int(r["n"])} for r in counts], hide_index=True)
    with right:
        st.markdown("**Entities**")
        st.dataframe(
            [{"class": r["cls"].rsplit("#", 1)[-1], "label": r["label"]} for r in entities],
            hide_index=True,
            use_container_width=True,
        )

    st.markdown("**Instance graph** (first 400 relations)")
    st.graphviz_chart(instance_dot(edges), use_container_width=True)
    try:
        st.download_button("Download everything in GraphDB (Turtle)", graphdb.export_turtle(), file_name="lic_ontology.ttl", mime="text/turtle")
    except Exception as error:
        st.caption(f"Export unavailable: {error}")
    st.caption("For class hierarchy and SPARQL, open the GraphDB Workbench at http://localhost:7200 through an SSH tunnel.")
