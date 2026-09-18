# RAG PDF ingestion pipeline

This stack backs the LlamaIndex-backed RAG demo: an Airflow-orchestrated
pipeline that turns a PDF dropped into a MinIO bucket into embedded chunks in
Qdrant, ready for query-time retrieval from the "LlamaIndex RAG" Streamlit
page (`pages/2_LlamaIndex_RAG.py`).

Pipeline shape: MinIO (raw PDF landing zone, `incoming/` prefix) -> a webhook
notification fires on every new `.pdf` -> `rag-webhook` triggers the
`rag_pdf_ingestion` Airflow DAG via the REST API -> LlamaParse (PDF ->
markdown) -> chunking -> metadata + `gates_ai_common` safety gates ->
embeddings -> Qdrant load -> ingestion-quality evaluation.

This is a separate pipeline from the existing mocked `agents/rag_flow.py`
demo.


## Prerequisites

- Docker + Docker Compose v2 (`docker compose version`). 
- An OpenAI API key (for embeddings) and a LlamaParse API key from
  [cloud.llamaindex.ai](https://cloud.llamaindex.ai) (for PDF parsing).

## 1. Configure secrets

    cd rag_ingestion
    cp env.sample .env

Generate the secrets this stack owns (don't leave `env.sample`'s placeholders
in `.env`):

    openssl rand -hex 24   # MINIO_ROOT_PASSWORD
    openssl rand -hex 24   # AIRFLOW_POSTGRES_PASSWORD
    openssl rand -hex 24   # AIRFLOW_API_PASSWORD
    openssl rand -hex 24   # AIRFLOW_WEBSERVER_SECRET_KEY
    openssl rand -hex 24   # RAG_WEBHOOK_SHARED_SECRET

    # AIRFLOW_FERNET_KEY is NOT an openssl-hex value -- it must be a valid
    # Fernet key:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

    nano .env

Fill in:
- `OPENAI_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`,
  `LANGFUSE_HOST` -- copy these from the root `.env` (`gates_ai_lld/.env`);
  same values, not new ones. Langfuse vars are optional, leave blank to skip
  the ingestion-side trace.
- `LLAMA_CLOUD_API_KEY` -- from your LlamaParse account.
- `MINIO_ROOT_PASSWORD` -- **set this to its real value before the first
  `docker compose up -d`**, same reasoning as `litellm/README.md`'s note on
  `POSTGRES_PASSWORD`: MinIO only applies root credentials when it
  initializes its data volume on first start, so changing it later means
  either reconfiguring MinIO's user store or wiping the `minio_data` volume.

## 2. Start the stack

    docker compose up -d
    docker compose ps

You should see `minio`, `qdrant`, `airflow-postgres`, `airflow-webserver`,
`airflow-scheduler`, and `rag-webhook` all "Up" (`minio-init` exits after it
finishes bootstrapping the bucket/webhook -- that's expected, check its logs
if something downstream looks unconfigured):

    docker compose logs minio-init

## 3. Health checks

    curl http://localhost:9000/minio/health/live      # MinIO API
    curl http://localhost:6333/                        # Qdrant (127.0.0.1 only)
    curl http://localhost:8080/health                  # Airflow webserver


