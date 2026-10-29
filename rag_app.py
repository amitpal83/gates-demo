"""RAG-only Streamlit entrypoint: serves just the LlamaIndex RAG page and hides the sidebar nav (st.navigation also disables pages/ auto-discovery)."""
import streamlit as st

page = st.navigation([st.Page("pages/2_LlamaIndex_RAG.py", title="LlamaIndex RAG")], position="hidden")
page.run()
