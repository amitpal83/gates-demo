"""
Streamlit multipage entry for the LlamaIndex-backed RAG pipeline
(rag_ingestion/). Living under pages/ means Streamlit auto-discovers this
as a separate sidebar page when you run `streamlit run streamlit_app.py`
-- no edit to streamlit_app.py needed.

Queries whatever documents the `rag_pdf_ingestion` Airflow DAG has
ingested into Qdrant so far (see rag_ingestion/README.md to bring that
pipeline up and upload a PDF). This is a separate pipeline/store from the
"RAG Agent" tab in the main app, which answers from a single in-memory
demo factsheet.

The query pipeline (rag_ingestion/query_engine.py) runs: Understand Query
-> Retrieve (hybrid dense+sparse) -> Rerank & Assemble -> Generate ->
Respond, with evaluation/cost logging happening afterwards in a
background thread (fire-and-forget) so it never adds latency here -- see
that module's docstring.
"""
import logging

import streamlit as st

from rag_ingestion.query_engine import LlamaIndexRAGQuery

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

st.set_page_config(page_title="LlamaIndex RAG", layout="wide")
st.title("LlamaIndex RAG")
st.caption(
    "Ask questions about PDFs ingested through the Airflow pipeline (MinIO -> LlamaParse -> "
    "LlamaIndex chunking -> metadata/safety gates -> embeddings -> Qdrant). See "
    "rag_ingestion/README.md to bring that stack up and upload a document."
)
st.caption(
    "Pipeline: Understand Query -> Retrieve (hybrid dense+sparse search + metadata filter) -> "
    "Rerank & Assemble (cross-encoder + citations) -> Generate -> Respond. Evaluation and "
    "cost/latency logging run afterwards in the background (fire-and-forget) and don't delay "
    "the answer below."
)


def get_query_agent() -> LlamaIndexRAGQuery:
    if "llamaindex_rag_query" not in st.session_state:
        logger.info("Initializing LlamaIndexRAGQuery for this session...")
        st.session_state.llamaindex_rag_query = LlamaIndexRAGQuery()
    return st.session_state.llamaindex_rag_query


try:
    agent = get_query_agent()
except Exception as e:
    logger.error("Failed to connect to Qdrant", exc_info=True)
    st.error(
        f"Could not connect to the Qdrant instance the ingestion pipeline writes to: {e}\n\n"
        "Check QDRANT_URL and that `docker compose -f rag_ingestion/docker-compose.yml up -d` is running."
    )
    st.stop()

st.caption(f"Querying Qdrant collection: `{agent.collection_name}`")

question = st.text_input(
    "Ask a question about an ingested document",
    placeholder="e.g. What is the budget in the policy documents owned by DOST?",
)
st.caption("Tip: mention things like `type: policy`, `author: ...`, or `owner: ...` to filter by metadata.")

if st.button("Run"):
    if not question.strip():
        st.warning("Enter a question before running the query.")
    else:
        try:
            with st.spinner("Understanding the query, retrieving, reranking, and generating an answer..."):
                outcome = agent.run(question.strip())
        except Exception as error:
            logger.error("LlamaIndex RAG query failed", exc_info=True)
            st.error(f"Query pipeline encountered an error: {error}")
            st.stop()

        stages = outcome.get("stages", {})
        if outcome["status"] == "ok":
            st.success("The query completed successfully.")
            st.subheader("Answer")
            st.write(outcome["answer"])
            st.caption("Citation markers like [1], [2] refer to the sources listed below.")
        elif outcome["status"] == "no_matching_documents":
            st.warning(outcome["answer"])
        elif outcome["status"] == "blocked_at_input_validation":
            st.warning("The question was blocked during input validation.")
        elif outcome["status"] == "blocked_by_guardrail":
            st.error("The generated answer was blocked by the output guardrail.")
        else:
            st.warning(f"Status: {outcome['status']}")

        col1, col2, col3 = st.columns(3)
        with col1:
            st.subheader("1. Understand Query")
            st.json(stages.get("query_understanding", {}))
        with col2:
            st.subheader("2. Retrieve (hybrid)")
            st.json(stages.get("retrieved", []))
        with col3:
            st.subheader("3. Rerank")
            st.json({"backend": stages.get("rerank_backend"), "top": stages.get("reranked", [])})

        st.subheader("Sources / citations")
        st.json(outcome.get("citations", stages.get("citations", [])))

        st.subheader("Guardrail")
        st.json(stages.get("guardrail", {}))

        st.subheader("Evaluation & cost logging (async)")
        st.caption(stages.get("evaluation", "n/a"))

        st.subheader("Raw stage dictionary")
        st.json(stages)
