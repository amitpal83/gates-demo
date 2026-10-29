"""Airflow only scans this folder; re-exports the LIC dag defined in ontology_graph/dags/ so that package stays self-contained."""
from ontology_graph.dags.lic_policy_ingestion import lic_policy_ingestion_dag  # noqa: F401
