"""
rag_ingestion
--------------
Airflow-orchestrated PDF ingestion pipeline for the LlamaIndex-backed RAG
stack: MinIO (raw PDF landing zone) -> LlamaParse (PDF -> markdown) ->
chunking -> metadata + gates_ai_common safety gates -> embeddings ->
Qdrant load -> ingestion-quality evaluation.

This is a separate pipeline from the existing mocked `agents/rag_flow.py`
demo -- see `rag_ingestion/query_engine.py` for the query-time counterpart
that reads from the real Qdrant collection this pipeline populates.
"""
