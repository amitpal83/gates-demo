"""Env-var switchboard for ontology_graph. Names match docker-compose.yml; defaults assume the compose service names."""
import os


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    return default if raw is None else raw.strip().lower() in ("1", "true", "yes", "on")


# -- MinIO (shared server; LIC uses its own licdocuments/ and lic/ prefixes) --
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ROOT_USER = os.getenv("MINIO_ROOT_USER")
MINIO_ROOT_PASSWORD = os.getenv("MINIO_ROOT_PASSWORD")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "gates-rag-ingestion")
MINIO_SECURE = _bool_env("MINIO_SECURE", False)
UPLOAD_PREFIX = "licdocuments/"

# -- Qdrant --
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_COLLECTION = os.getenv("LIC_QDRANT_COLLECTION", "lic_policy_docs")

# -- LLM + embeddings via the OpenAI SDK; for a gateway (Portkey) set OPENAI_BASE_URL and LIC_LLM_DEFAULT_HEADERS (JSON) --
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
LLM_MODEL = os.getenv("LIC_LLM_MODEL", "gpt-4o-mini")
LLM_DEFAULT_HEADERS = os.getenv("LIC_LLM_DEFAULT_HEADERS")
EMBEDDING_MODEL = os.getenv("LIC_EMBEDDING_MODEL", "text-embedding-3-large")
EMBEDDING_DIMENSIONS = int(os.getenv("LIC_EMBEDDING_DIMENSIONS", "1024"))

# -- LlamaParse --
LLAMA_CLOUD_API_KEY = os.getenv("LLAMA_CLOUD_API_KEY")

# -- GraphDB --
GRAPHDB_URL = os.getenv("GRAPHDB_URL", "http://graphdb:7200")
GRAPHDB_REPOSITORY = os.getenv("GRAPHDB_REPOSITORY", "lic_policy")

# -- PostgreSQL (policy records) --
POLICY_DB_HOST = os.getenv("POLICY_DB_HOST", "policy-postgres")
POLICY_DB_PORT = int(os.getenv("POLICY_DB_PORT", "5432"))
POLICY_DB_NAME = os.getenv("POLICY_DB_NAME", "lic_policies")
POLICY_DB_USER = os.getenv("POLICY_DB_USER", "lic")
POLICY_DB_PASSWORD = os.getenv("POLICY_DB_PASSWORD")

# -- Airflow REST API + webhook --
AIRFLOW_API_URL = os.getenv("AIRFLOW_API_URL", "http://airflow-webserver:8080")
AIRFLOW_API_USERNAME = os.getenv("AIRFLOW_API_USERNAME")
AIRFLOW_API_PASSWORD = os.getenv("AIRFLOW_API_PASSWORD")
LIC_DAG_ID = os.getenv("LIC_DAG_ID", "lic_policy_ingestion")
LIC_WEBHOOK_SHARED_SECRET = os.getenv("LIC_WEBHOOK_SHARED_SECRET")
