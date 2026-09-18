"""The rag_pdf_ingestion DAG: wires tasks/*.py's run() functions together, triggered only via REST by rag-webhook with a deterministic dag_run_id so duplicate MinIO events don't double-ingest."""
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
        # Falls back to the last stage that succeeded -- a failed stage has no XCom.
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
