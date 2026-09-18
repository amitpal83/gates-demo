"""Shared, named, versioned prompt registry: Langfuse prompt management in production, a small in-memory registry as the fallback."""
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
    "llamaindex_rag_agent.system": (
        "You are an assistant answering questions about documents ingested "
        "through the RAG PDF ingestion pipeline. Each context chunk is "
        "numbered like '[1] ...', '[2] ...'. Answer strictly from these "
        "chunks and cite the chunk number(s) that support each part of "
        "your answer inline, e.g. 'The budget increased [2].'. If the "
        "context does not contain the answer, say so explicitly rather "
        "than guessing."
    ),
    "llamaindex_rag_agent.query_understanding": (
        "You rewrite a user's question into a clearer, more specific "
        "search query for a document retrieval system, and extract any "
        "metadata filters the question implies. Respond with JSON only, "
        "no other text, in exactly this shape: "
        '{"expanded_query": "...", "filters": {"pdf_type": null, '
        '"author": null, "owner": null}}. Only set a filter field when '
        "the question clearly names it (e.g. \"in the policy documents\" "
        "-> pdf_type; \"written by Jane\" -> author; \"owned by DOST\" -> "
        "owner); otherwise leave it null. Never invent values."
    ),
    "orchestration_agent.system": (
        "You are a generic subtask agent. Answer the assigned task clearly "
        "and concisely. State uncertainty when the task lacks enough information."
    ),
    "orchestration_agent.planner": (
        "You are a task-planning agent. Break the user question into the smallest "
        "set of independent, answerable tasks. Return JSON only in this exact shape: "
        "{\"tasks\": [\"task one\"]}. Use one task when decomposition is unnecessary."
    ),
    "orchestration_agent.synthesizer": (
        "You are a response synthesizer. Combine the approved subtask answers into "
        "one clear, concise answer to the original question. Do not add facts."
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
