"""The lic_policy_ingestion DAG: licdocuments/*.pdf -> parse -> chunk -> (ontology to GraphDB || embeddings to Qdrant); triggered via REST by lic-webhook with a deterministic dag_run_id so duplicate MinIO events don't double-ingest."""
from __future__ import annotations

import pendulum
from airflow.decorators import dag, task
from airflow.operators.python import get_current_context

DAG_ID = "lic_policy_ingestion"


@dag(
    dag_id=DAG_ID,
    description="MinIO licdocuments/ PDF -> LlamaParse -> chunk -> GraphDB ontology + Qdrant lic_policy_docs",
    schedule=None,
    start_date=pendulum.datetime(2024, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=2,
    tags=["lic", "ontology"],
)
def lic_policy_ingestion():

    # Heavy imports live inside the tasks so DAG parsing stays fast and can't fail on a missing dependency.
    @task
    def stage_task() -> dict:
        from ontology_graph.pipeline import ingest

        return ingest.run_stage(get_current_context()["dag_run"].conf or {})

    @task
    def parse_task(prev: dict) -> dict:
        from ontology_graph.pipeline import ingest

        return ingest.run_parse(prev)

    @task
    def chunk_task(prev: dict) -> dict:
        from ontology_graph.pipeline import ingest

        return ingest.run_chunk(prev)

    @task
    def build_ontology_task(prev: dict) -> dict:
        from ontology_graph.pipeline import ontology_build

        return ontology_build.run(prev)

    @task
    def embed_load_task(prev: dict) -> dict:
        from ontology_graph.pipeline import ingest

        return ingest.run_embed_load(prev)

    chunked = chunk_task(parse_task(stage_task()))
    build_ontology_task(chunked)
    embed_load_task(chunked)


lic_policy_ingestion_dag = lic_policy_ingestion()
