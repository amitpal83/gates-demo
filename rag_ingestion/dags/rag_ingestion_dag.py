"""
rag_ingestion.dags.rag_ingestion_dag
----------------------------------------
The `rag_pdf_ingestion` Airflow DAG: wires the tasks/*.py modules into the
pipeline described in rag_ingestion/README.md --

    stage_raw -> parse_pdf -> chunk_document -> extract_metadata
    -> build_embeddings -> load_qdrant -> evaluate_ingestion_quality

Never scheduled (schedule=None) -- the only trigger is rag-webhook calling
this DAG's REST API in response to a MinIO `s3:ObjectCreated:*` event, with
`conf={"bucket", "object_key", "etag", "metadata_overrides"}` and a
deterministic `dag_run_id` (see rag_ingestion.common.keys), which is what
makes a duplicate MinIO notification idempotent instead of double-ingesting.

Each tasks/*.py module exposes a plain `run(prev) -> dict` function with no
Airflow import of its own (so it stays importable/unit-testable without
Airflow installed) -- this file is the only place that wraps those calls
with Airflow's `@task` and gates_ai_common's `@trace`.

evaluate_ingestion_quality runs with trigger_rule=ALL_DONE and receives
every upstream stage's XCom, not just load_qdrant's: if an earlier stage
raises (e.g. extract_metadata's safety gate failing), the later stages
never produce an XCom, so this task falls back to the last stage that
did succeed -- matching evaluate_ingestion_quality.run()'s own handling
of a `prev` dict that's missing keys from stages that never ran.
"""
from __future__ import annotations

import pendulum
from airflow.decorators import dag, task
from airflow.operators.python import get_current_context
from airflow.utils.trigger_rule import TriggerRule

from gates_ai_common.observability import trace
from rag_ingestion.tasks import (
    build_embeddings,
    chunk_document,
    evaluate_ingestion_quality,
    extract_metadata,
    load_qdrant,
    parse_pdf,
    stage_raw,
)

DAG_ID = "rag_pdf_ingestion"


@dag(
    dag_id=DAG_ID,
    description="MinIO PDF -> LlamaParse -> chunk -> metadata/safety gate -> embed -> Qdrant",
    schedule=None,
    start_date=pendulum.datetime(2024, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=5,
    tags=["rag", "ingestion"],
)
def rag_pdf_ingestion():

    @task
    @trace(name="rag_ingestion.stage_raw")
    def stage_raw_task() -> dict:
        conf = get_current_context()["dag_run"].conf or {}
        return stage_raw.run(conf)

    @task
    @trace(name="rag_ingestion.parse_pdf")
    def parse_pdf_task(prev: dict) -> dict:
        return parse_pdf.run(prev)

    @task
    @trace(name="rag_ingestion.chunk_document")
    def chunk_document_task(prev: dict) -> dict:
        return chunk_document.run(prev)

    @task
    @trace(name="rag_ingestion.extract_metadata")
    def extract_metadata_task(prev: dict) -> dict:
        return extract_metadata.run(prev)

    @task
    @trace(name="rag_ingestion.build_embeddings")
    def build_embeddings_task(prev: dict) -> dict:
        return build_embeddings.run(prev)

    @task
    @trace(name="rag_ingestion.load_qdrant")
    def load_qdrant_task(prev: dict) -> dict:
        return load_qdrant.run(prev)

    @task(trigger_rule=TriggerRule.ALL_DONE)
    @trace(name="rag_ingestion.evaluate_ingestion_quality")
    def evaluate_ingestion_quality_task(
        staged: dict | None,
        parsed: dict | None,
        chunked: dict | None,
        enriched: dict | None,
        embedded: dict | None,
        loaded: dict | None,
    ) -> dict:
        # Use the result of the last stage that actually succeeded -- any
        # stage after a failure resolves to None (no XCom was ever pushed).
        prev = loaded or embedded or enriched or chunked or parsed or staged
        return evaluate_ingestion_quality.run(prev)

    staged = stage_raw_task()
    parsed = parse_pdf_task(staged)
    chunked = chunk_document_task(parsed)
    enriched = extract_metadata_task(chunked)
    embedded = build_embeddings_task(enriched)
    loaded = load_qdrant_task(embedded)
    evaluate_ingestion_quality_task(staged, parsed, chunked, enriched, embedded, loaded)


rag_pdf_ingestion()
