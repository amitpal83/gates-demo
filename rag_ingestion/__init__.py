"""Airflow-orchestrated PDF ingestion pipeline: MinIO -> LlamaParse -> chunking -> metadata/safety gates -> embeddings -> Qdrant load -> quality evaluation."""
