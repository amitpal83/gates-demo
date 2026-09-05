"""
agents.rag_flow
-------------------
Runnable demo of the HLD RAG Flow:

    LangChain framework (prompt + generation chain)
    -> Input validation (pass / fail)
    -> Take a PDF -> chunk it
    -> Embed chunks -> store embeddings
    -> Search (cosine similarity, top-k) -> rerank
    -> Build prompt chain -> ask the LLM
    -> Evaluation (ok / not ok)
    -> Security guardrail
    -> Observability (tokens & cost)

Run it directly (generates its own sample PDF on first run):

    python3 -m agents.rag_flow "What GPU cluster does GATES use?"

Production stack: pip install langchain qdrant-client openai
sentence-transformers llm-guard nemoguardrails deepeval langfuse
"""
import os
import re
import sys

import numpy as np
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda

from gates_ai_common import config
from gates_ai_common.input_validation import InputValidator
from gates_ai_common.prompt_library import PromptLibrary
from gates_ai_common.llm_client import LLMClient
from gates_ai_common.evaluation import ResponseEvaluator
from gates_ai_common.guardrails import SecurityGuardrail
from gates_ai_common.observability import trace, log_usage

SAMPLE_PDF_PATH = os.path.join(os.path.dirname(__file__), "sample_gates_factsheet.pdf")

SAMPLE_TEXT = """
GATES Program Fact Sheet

The GATES program is a joint initiative between DOST, JICA DX Lab, and BCG to
build a shared data and AI platform for disaster risk management in the
Philippines. The platform's lakehouse runs on Apache Iceberg with Trino as
the federated query engine, and dbt handles Bronze-to-Silver-to-Gold
transformations.

The AI layer procured 24 H200 GPUs, arranged as three HGX nodes, to serve
open-source large language models such as the Llama 3 family through
vLLM and KServe. Retrieval-augmented generation uses Qdrant as the vector
store, with OpenAI's large embedding model producing 1024-dimension vectors.

Two flagship agents run on this stack: a SQL query agent that answers
natural-language questions against the lakehouse gold layer, and a PDRA
agent that fuses PAGASA and PHIVOLCS hazard data with GeoRiskPH exposure
data to draft pre-disaster risk narratives at the municipality level.

Observability is handled by Langfuse, tracking tokens, latency, and cost
across both agent paths so the team can compare their operating profiles.
"""


def ensure_sample_pdf() -> str:
    """Generates a tiny sample PDF the first time this runs, so the
    'Taking a PDF' step has a real file to read -- not a hardcoded
    string pretending to be one."""
    if os.path.exists(SAMPLE_PDF_PATH):
        return SAMPLE_PDF_PATH
    from reportlab.lib.pagesizes import LETTER
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(SAMPLE_PDF_PATH, pagesize=LETTER)
    text_obj = c.beginText(50, 740)
    text_obj.setFont("Helvetica", 10)
    for line in SAMPLE_TEXT.strip().split("\n"):
        text_obj.textLine(line)
    c.drawText(text_obj)
    c.showPage()
    c.save()
    return SAMPLE_PDF_PATH


def load_pdf_text(path: str) -> str:
    """Step: Taking a PDF. Production-grade extraction via pypdf."""
    from pypdf import PdfReader
    reader = PdfReader(path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def chunk_text(text: str, chunk_size: int = 220, overlap: int = 40) -> list[str]:
    """Step: Chunking the PDF. Fixed-size sliding window over
    whitespace-normalized text -- production would likely use a
    sentence/paragraph-aware splitter (e.g. langchain's
    RecursiveCharacterTextSplitter), same idea, smarter boundaries."""
    normalized = re.sub(r"\s+", " ", text).strip()
    chunks = []
    start = 0
    while start < len(normalized):
        end = start + chunk_size
        chunks.append(normalized[start:end])
        start = end - overlap
    return [c for c in chunks if c.strip()]


def embed(text: str, dims: int = 64) -> np.ndarray:
    """Step: turning text into (small) embeddings.

    Stands in for a real embedding model (e.g. OpenAI
    text-embedding-3-large, 1024-dim) using a deterministic hashed
    bag-of-words vector -- offline, but genuinely responsive to word
    overlap, which is enough to demonstrate real cosine-similarity
    search and reranking behaviour.
    """
    vec = np.zeros(dims)
    for word in re.findall(r"[a-z]{3,}", text.lower()):
        idx = hash(word) % dims
        vec[idx] += 1.0
    norm = np.linalg.norm(vec)
    return vec / norm if norm > 0 else vec


class InMemoryVectorStore:
    """Stands in for Qdrant. Same three operations a real Qdrant
    client exposes: create collection (implicit here), upsert, search.

    Production equivalent:
        from qdrant_client import QdrantClient
        from qdrant_client.models import VectorParams, Distance, PointStruct
        client = QdrantClient(url="http://qdrant:6333")
        client.create_collection("gates_docs", VectorParams(size=1024, distance=Distance.COSINE))
        client.upsert("gates_docs", points=[PointStruct(id=i, vector=v, payload={"text": t})...])
        client.search("gates_docs", query_vector=q, limit=top_k)
    """

    def __init__(self):
        self._vectors: list[np.ndarray] = []
        self._payloads: list[str] = []

    def upsert(self, chunks: list[str]):
        for chunk in chunks:
            self._vectors.append(embed(chunk))
            self._payloads.append(chunk)

    def search(self, query_vector: np.ndarray, top_k: int = 4) -> list[tuple[str, float]]:
        scores = [float(np.dot(query_vector, v)) for v in self._vectors]  # vectors are unit-norm -> dot == cosine
        ranked = sorted(zip(self._payloads, scores), key=lambda x: x[1], reverse=True)
        return ranked[:top_k]


def rerank(query: str, hits: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """Step: reranking. Stands in for a cross-encoder reranker
    (e.g. sentence_transformers.CrossEncoder) with a cheap lexical
    boost: chunks containing an exact query keyword move up."""
    query_words = set(re.findall(r"[a-z]{4,}", query.lower()))

    def boosted_score(item):
        chunk, score = item
        chunk_words = set(re.findall(r"[a-z]{4,}", chunk.lower()))
        overlap = len(query_words & chunk_words)
        return score + 0.05 * overlap

    return sorted(hits, key=boosted_score, reverse=True)


def mock_rag_answer(system: str, user: str) -> str:
    """Offline stand-in for the LLM: extracts the sentence from the
    context most relevant to the question, so the answer is
    genuinely grounded in what was retrieved (and evaluation can
    meaningfully check that)."""
    context_match = re.search(r"Context:\n(.*?)\n\nQuestion:", user, re.DOTALL)
    context = context_match.group(1) if context_match else ""
    question = user.split("Question:")[-1].strip()
    sentences = re.split(r"(?<=[.!?])\s+", context)
    q_words = set(re.findall(r"[a-z]{3,}", question.lower()))
    best = max(sentences, key=lambda s: len(q_words & set(re.findall(r"[a-z]{3,}", s.lower()))), default="")
    return best.strip() or "The context does not contain the answer."


class RAGAgent:
    def __init__(self):
        self.validator = InputValidator()
        self.prompts = PromptLibrary()
        self.llm = LLMClient(model="gpt-4o-mini", mock_fn=mock_rag_answer)
        self.evaluator = ResponseEvaluator(threshold=0.3)
        self.guardrail = SecurityGuardrail()
        self.store = InMemoryVectorStore()

    def build_answer_chain(self, system_prompt: str):
        """Create the default LangChain prompt and LLM generation chain."""
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "Context:\n{context}\n\nQuestion: {question}"),
        ])

        def complete(prompt_value):
            messages = prompt_value.to_messages()
            answer, usage = self.llm.complete(messages[0].content, messages[-1].content)
            return {"answer": answer, "usage": usage}

        return prompt | RunnableLambda(complete)

    def ingest(self, pdf_path: str):
        text = load_pdf_text(pdf_path)
        chunks = chunk_text(text)
        self.store.upsert(chunks)
        return len(chunks)

    @trace(name="rag_agent_run")
    def run(self, question: str) -> dict:
        stages = {}

        # 1. Input validation
        validation = self.validator.validate(question)
        stages["input_validation"] = vars(validation)
        if not validation.is_safe:
            return {"status": "blocked_at_input_validation", "stages": stages}

        # 2. Search (embed query, cosine similarity, top-k)
        query_vector = embed(question)
        hits = self.store.search(query_vector, top_k=4)
        stages["retrieved_top_k"] = [(c[:50] + "...", round(s, 3)) for c, s in hits]

        # 3. Rerank
        reranked = rerank(question, hits)
        top_chunks = [c for c, _ in reranked[:2]]
        stages["reranked_top_2"] = [c[:50] + "..." for c in top_chunks]

        # 4. LangChain prompt and generation chain
        system = self.prompts.get("rag_agent.system")
        context_block = "\n".join(top_chunks)
        chain = self.build_answer_chain(system)

        # 5. Ask the LLM through LangChain
        chain_result = chain.invoke({"context": context_block, "question": question})
        answer = chain_result["answer"]
        usage = chain_result["usage"]
        stages["answer"] = answer
        stages["chain_backend"] = "langchain"
        stages["llm_backend"] = self.llm.backend

        # 6. Evaluation
        eval_result = self.evaluator.evaluate(question, answer, context=top_chunks)
        stages["evaluation"] = eval_result.__dict__
        if not eval_result.passed:
            return {"status": "failed_evaluation", "stages": stages}

        # 7. Security guardrail
        guard_result = self.guardrail.check(answer)
        stages["guardrail"] = vars(guard_result)
        if not guard_result.allowed:
            return {"status": "blocked_by_guardrail", "stages": stages}

        # 8. Observability -- tokens & cost
        usage_record = log_usage(agent_path="rag_agent", input_tokens=usage["input_tokens"],
                                  output_tokens=usage["output_tokens"], model=self.llm.model)
        stages["usage"] = usage_record

        return {"status": "ok", "answer": answer, "stages": stages}


def main():
    question = sys.argv[1] if len(sys.argv) > 1 else "What GPU cluster does GATES use?"
    config.print_backend_report()

    pdf_path = ensure_sample_pdf()
    print(f"\nSample PDF: {pdf_path}")

    agent = RAGAgent()
    n_chunks = agent.ingest(pdf_path)
    print(f"Ingested and embedded {n_chunks} chunks\n")
    print(f"Question: {question}\n")

    outcome = agent.run(question)
    print(f"Status: {outcome['status']}\n")
    for stage, detail in outcome["stages"].items():
        print(f"  [{stage}] {detail}")


if __name__ == "__main__":
    main()
