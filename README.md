# GATES AI architecture - reference implementation

## Runtime notes

- Use Python 3.13 for the supplied `venv313` environment. On Python 3.13 and newer, `llm-guard` is intentionally excluded because its pinned `sentencepiece` dependency has no compatible wheel; input validation uses the documented regex fallback.
- Set `GATES_ENV=production` before deploying. Production startup requires `OPENAI_API_KEY`, `langchain`, and `langgraph`; the Streamlit app stops rather than serving mock LLM responses when these requirements are missing.
- Set `GATES_ENV=development` or omit it for local demos. Without `OPENAI_API_KEY`, responses come from deterministic mock implementations and are not representative of production model quality.

