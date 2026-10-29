"""Streamlit entrypoint for the LIC pipeline: ask about a policy, and inspect the ontology built from the ingested documents."""
import logging

import streamlit as st

from ontology_graph.agent import PolicyAgent
from ontology_graph.clients import policy_store
from ontology_graph.ui import ontology_view

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

st.set_page_config(page_title="Policy Data Query Agent", layout="wide")
st.title("Policy Data Query Agent")
st.caption("Ask any details about your policy")


@st.cache_resource
def get_agent() -> PolicyAgent:
    return PolicyAgent()


query_tab, ontology_tab = st.tabs(["Ask about a policy", "Ontology"])

with query_tab:
    try:
        policies = policy_store.list_policies()
    except Exception as error:
        logger.error("Could not read policies", exc_info=True)
        st.error(f"Could not read the policy database: {error}")
        st.stop()

    selected = st.selectbox(
        "Policy (demo data)",
        policies,
        format_func=lambda p: f"{p['policy_number']} - {p['holder_name']}",
    )
    question = st.text_input(
        "Question",
        placeholder="e.g. Can I withdraw part of my fund now?",
        label_visibility="collapsed",
    )

    if st.button("Ask"):
        if not question.strip():
            st.warning("Enter a question first.")
        else:
            try:
                with st.spinner("Reading your policy, the plan ontology and the brochure..."):
                    outcome = get_agent().answer(selected["policy_number"], question.strip())
            except Exception as error:
                logger.error("Policy agent failed", exc_info=True)
                st.error(f"The agent hit an error: {error}")
                st.stop()

            stages = outcome.get("stages", {})
            if outcome["status"] == "ok":
                st.subheader("Answer")
                st.write(outcome["answer"])
            else:
                st.warning(f"{outcome['status']}: {outcome.get('answer', '')}")

            with st.expander("Policy record used"):
                st.json(stages.get("policy_record", {}))
            with st.expander("Ontology facts used"):
                if stages.get("ontology_error"):
                    st.error(stages["ontology_error"])
                st.code("\n".join(stages.get("ontology_facts", [])) or "(none)")
            with st.expander("Brochure passages used"):
                st.json(stages.get("passages", []))

with ontology_tab:
    ontology_view.render()
