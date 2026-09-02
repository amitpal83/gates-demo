"""
gates_ai_common.prompt_library
--------------------------------
Shared, named, versioned prompt registry.

Production backend : Langfuse prompt management (client.get_prompt).
Fallback backend    : a small in-memory registry, used when no
                       Langfuse keys are configured.

Every agent fetches its system prompt by *name* from here rather than
hardcoding prompt strings inline -- that's what lets a prompt be
tuned centrally (in Langfuse) without a code deploy, once the live
backend is wired up.
"""
from . import config

if config.USE_LIVE_LANGFUSE:
    from langfuse import Langfuse

_LOCAL_PROMPTS = {
    "sql_agent.system": (
        "You are a careful data analyst for the GATES program. Given a "
        "natural-language question and a database schema, write a single "
        "read-only SQL query (SELECT only) that answers the question. "
        "Never write INSERT, UPDATE, DELETE, or DROP statements."
    ),
    "rag_agent.system": (
        "You are an assistant answering questions strictly from the "
        "provided context. If the context does not contain the answer, "
        "say so explicitly rather than guessing."
    ),
    "orchestration_agent.system": (
        "You are the GATES assistant. Answer clearly and concisely, "
        "and say when you are uncertain."
    ),
}


class PromptLibrary:
    def __init__(self):
        self.backend = "langfuse" if config.USE_LIVE_LANGFUSE else "local-registry"
        self.last_fetch_source = None
        self.last_fetch_name = None
        self.last_fetch_version = version = None
        if self.backend == "langfuse":
            self._client = Langfuse()

    def get(self, name: str, version: str | None = None) -> str:
        if self.backend == "langfuse":
            try:
                prompt = self._client.get_prompt(name, version=version)
                rendered = prompt.compile()
                self.last_fetch_source = "langfuse"
                self.last_fetch_name = name
                self.last_fetch_version = version
                return rendered
            except Exception:
                # Keep the pipeline usable when Langfuse is unreachable.
                self.backend = "local-registry"
                self.last_fetch_source = "local-registry"
                self.last_fetch_name = name
                self.last_fetch_version = version
        try:
            rendered = _LOCAL_PROMPTS[name]
            if self.last_fetch_source is None:
                self.last_fetch_source = "local-registry"
                self.last_fetch_name = name
                self.last_fetch_version = version
            return rendered
        except KeyError as exc:
            raise KeyError(f"No local fallback prompt registered for '{name}'") from exc
