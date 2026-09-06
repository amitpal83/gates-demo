"""
gates_ai_common.config
-----------------------
Central switchboard the rest of the shared library reads from.

Every module in this package follows the same rule: try to import the
real enterprise backend; if it isn't installed / configured, fall back
to a small local implementation so the *pipeline shape* (validate ->
prompt -> generate -> evaluate -> guardrail -> observe) is always
runnable, in any environment, with or without API keys.

This is the "common capability library" referenced throughout the
HLD/LLD: any agent -- SQL agent, RAG agent, PDRA agent, or a future
one nobody has built yet -- imports these modules instead of
re-implementing validation / prompts / evaluation / guardrails /
observability per project.
"""
import importlib
import os

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover - optional dependency in some envs
    def load_dotenv(*args, **kwargs):
        return False


load_dotenv()

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
