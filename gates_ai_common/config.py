"""Central switchboard: every module here tries the real enterprise backend first, falling back to a local implementation so the pipeline always runs."""
import importlib
import os

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover - optional dependency in some envs
    def load_dotenv(*args, **kwargs):
        return False


try:
    load_dotenv()
except OSError:
    pass  # .env may exist but be unreadable (root-written, non-root container user)

try:
    import certifi
except ImportError:  # pragma: no cover - optional in some envs
    certifi = None
else:
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())

os.environ.setdefault("LANGFUSE_HOST", "https://cloud.langfuse.com")
os.environ.setdefault("NEMO_GUARDRAILS_NO_USAGE_STATS", "1")


def _installed(module_name: str) -> bool:
    try:
        importlib.import_module(module_name)
        return True
    except ImportError:
        return False


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY")
GATES_ENV = os.getenv("GATES_ENV", "development").lower()
LLM_REQUEST_TIMEOUT_SECONDS = float(os.getenv("LLM_REQUEST_TIMEOUT_SECONDS", "30"))

HAS_OPENAI_PACKAGE = _installed("openai")
HAS_LANGCHAIN = _installed("langchain")
HAS_LANGGRAPH = _installed("langgraph")
HAS_LLM_GUARD = _installed("llm_guard")
HAS_NEMOGUARDRAILS = _installed("nemoguardrails")
HAS_DEEPEVAL = _installed("deepeval") and bool(OPENAI_API_KEY)
HAS_LANGFUSE = _installed("langfuse")
HAS_QDRANT = _installed("qdrant_client")

USE_LIVE_LLM = HAS_OPENAI_PACKAGE and bool(OPENAI_API_KEY)
USE_LIVE_LANGFUSE = HAS_LANGFUSE and bool(LANGFUSE_PUBLIC_KEY)


def production_configuration_errors() -> list[str]:
    """Return missing production requirements without affecting local demos."""
    if GATES_ENV != "production":
        return []

    errors = []
    if not USE_LIVE_LLM:
        errors.append("OPENAI_API_KEY is required when GATES_ENV=production.")
    if not HAS_LANGCHAIN:
        errors.append("langchain must be installed when GATES_ENV=production.")
    if not HAS_LANGGRAPH:
        errors.append("langgraph must be installed when GATES_ENV=production.")
    return errors


def print_backend_report():
    rows = [
        ("LLM (OpenAI)", USE_LIVE_LLM, "openai"),
        ("Orchestration - simple", HAS_LANGCHAIN, "langchain"),
        ("Orchestration - multi-agent", HAS_LANGGRAPH, "langgraph"),
        ("Input validation", HAS_LLM_GUARD, "llm-guard"),
        ("Security guardrail", HAS_NEMOGUARDRAILS, "nemoguardrails"),
        ("Evaluation", HAS_DEEPEVAL, "deepeval"),
        ("Observability", USE_LIVE_LANGFUSE, "langfuse"),
        ("Vector store", HAS_QDRANT, "qdrant-client"),
    ]
    width = max(len(r[0]) for r in rows)
    print("-" * (width + 30))
    print("Backend availability (this run)".ljust(width + 30))
    print("-" * (width + 30))
    for label, live, pkg in rows:
        status = "LIVE" if live else "FALLBACK"
        print(f"  {label.ljust(width)}  [{status:8}]  ({pkg})")
    print("-" * (width + 30))


if __name__ == "__main__":
    print_backend_report()
