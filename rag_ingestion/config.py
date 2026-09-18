"""Env-var switchboard for rag_ingestion. Names here are fixed contracts with docker-compose.yml, Terraform, and the DAG/webhook."""
import importlib
import os

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv(*args, **kwargs):
        return False


try:
    load_dotenv()
except OSError:
    pass  # .env may exist but be unreadable (root-written, non-root container user)


def _installed(module_name: str) -> bool:
    try:
        importlib.import_module(module_name)
        return True
    except ImportError:
        return False


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


GATES_ENV = os.getenv("GATES_ENV", "development").lower()

# -- MinIO --
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ROOT_USER = os.getenv("MINIO_ROOT_USER")
MINIO_ROOT_PASSWORD = os.getenv("MINIO_ROOT_PASSWORD")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "gates-rag-ingestion")
MINIO_SECURE = _bool_env("MINIO_SECURE", False)

# -- Qdrant --
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "gates_rag_docs")
QDRANT_COLLECTION_DEV = os.getenv("QDRANT_COLLECTION_DEV", "gates_rag_docs_dev384")

# -- Embeddings --
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-large")
EMBEDDING_DIMENSIONS = int(os.getenv("EMBEDDING_DIMENSIONS", "1024"))

# -- LlamaParse --
LLAMA_CLOUD_API_KEY = os.getenv("LLAMA_CLOUD_API_KEY")

# -- Airflow REST API (webhook uses this to trigger dag runs) --
AIRFLOW_API_URL = os.getenv("AIRFLOW_API_URL", "http://localhost:8080")
AIRFLOW_API_USERNAME = os.getenv("AIRFLOW_API_USERNAME")
AIRFLOW_API_PASSWORD = os.getenv("AIRFLOW_API_PASSWORD")
AIRFLOW_DAG_ID = os.getenv("AIRFLOW_DAG_ID", "rag_pdf_ingestion")

# -- Webhook --
RAG_WEBHOOK_PORT = int(os.getenv("RAG_WEBHOOK_PORT", "8090"))
RAG_WEBHOOK_SHARED_SECRET = os.getenv("RAG_WEBHOOK_SHARED_SECRET")

# -- Optional-dependency flags --
HAS_MINIO = _installed("minio")
HAS_LLAMA_PARSE = _installed("llama_parse")
HAS_LLAMA_INDEX = _installed("llama_index")
HAS_QDRANT_CLIENT = _installed("qdrant_client")

# False -> dev fallback (sentence-transformers, 384-dim); True -> OpenAI, 1024-dim.
USE_LIVE_EMBEDDINGS = bool(OPENAI_API_KEY) and HAS_LLAMA_INDEX


def print_backend_report():
    rows = [
        ("MinIO client", HAS_MINIO, "minio"),
        ("LlamaParse", HAS_LLAMA_PARSE, "llama_parse"),
        ("LlamaIndex", HAS_LLAMA_INDEX, "llama_index"),
        ("Qdrant client", HAS_QDRANT_CLIENT, "qdrant_client"),
        ("Live embeddings", USE_LIVE_EMBEDDINGS, "openai + llama_index"),
    ]
    width = max(len(r[0]) for r in rows)
    print("-" * (width + 30))
    print("rag_ingestion backend availability".ljust(width + 30))
    print("-" * (width + 30))
    for label, live, pkg in rows:
        status = "LIVE" if live else "FALLBACK"
        print(f"  {label.ljust(width)}  [{status:8}]  ({pkg})")
    print("-" * (width + 30))


if __name__ == "__main__":
    print_backend_report()
