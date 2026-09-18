"""Query-time RAG pipeline: understand query -> hybrid retrieve (dense+
sparse, one Qdrant call) -> rerank+cite -> generate -> guardrail -> respond.
Evaluation/cost logging run async, after the response is already sent."""
from __future__ import annotations

import json
import logging
import re
import threading
import time

from gates_ai_common.evaluation import ResponseEvaluator
from gates_ai_common.guardrails import SecurityGuardrail
from gates_ai_common.input_validation import InputValidator
from gates_ai_common.llm_client import LLMClient
from gates_ai_common.observability import log_usage, trace
from gates_ai_common.prompt_library import PromptLibrary
from rag_ingestion.clients import qdrant_client_helper
from rag_ingestion.common.sparse_vectors import build_sparse_vector
from rag_ingestion.config import (
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL,
    QDRANT_COLLECTION,
    QDRANT_COLLECTION_DEV,
    USE_LIVE_EMBEDDINGS,
)

logger = logging.getLogger(__name__)

_CROSS_ENCODER_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"
_CANDIDATE_K = 20

_FILTER_HINT_PATTERN = re.compile(r"\b(pdf_type|type|author|owner)\s*[:=]\s*([\w.\-]+)", re.IGNORECASE)

_cross_encoder = None


def _embed_query_live(question: str) -> list[float]:
    from openai import OpenAI

    client = OpenAI()
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=[question], dimensions=EMBEDDING_DIMENSIONS)
    return response.data[0].embedding


def _embed_query_dev(question: str) -> list[float]:
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer("all-MiniLM-L6-v2")
    return model.encode([question]).tolist()[0]


def _embed_query_dense(question: str) -> list[float]:
    return _embed_query_live(question) if USE_LIVE_EMBEDDINGS else _embed_query_dev(question)


def _collection_name() -> str:
    return QDRANT_COLLECTION if USE_LIVE_EMBEDDINGS else QDRANT_COLLECTION_DEV


def _get_cross_encoder():
    global _cross_encoder
    if _cross_encoder is None:
        from sentence_transformers import CrossEncoder

        _cross_encoder = CrossEncoder(_CROSS_ENCODER_MODEL_NAME)
    return _cross_encoder


def _lexical_rerank(question: str, hits: list[dict]) -> list[dict]:
    """Fallback when the cross-encoder model can't load (e.g. no network)."""
    query_words = set(re.findall(r"[a-z]{4,}", question.lower()))

    def boosted(hit: dict) -> float:
        chunk_words = set(re.findall(r"[a-z]{4,}", hit["text"].lower()))
        return hit["score"] + 0.05 * len(query_words & chunk_words)

    for hit in hits:
        hit["rerank_score"] = boosted(hit)
    return sorted(hits, key=lambda h: h["rerank_score"], reverse=True)


def _cross_encoder_rerank(question: str, hits: list[dict]) -> tuple[list[dict], str]:
    try:
        model = _get_cross_encoder()
        scores = model.predict([(question, hit["text"]) for hit in hits])
        for hit, score in zip(hits, scores):
            hit["rerank_score"] = float(score)
        return sorted(hits, key=lambda h: h["rerank_score"], reverse=True), "cross-encoder"
    except Exception as error:
        logger.warning("Cross-encoder rerank unavailable (%s); using lexical fallback.", error)
        return _lexical_rerank(question, hits), "lexical-fallback"


def _build_context_with_citations(hits: list[dict]) -> tuple[str, list[dict]]:
    lines = []
    citations = []
    for i, hit in enumerate(hits, start=1):
        lines.append(f"[{i}] {hit['text']}")
        citations.append({
            "marker": f"[{i}]",
            "doc_id": hit.get("doc_id"),
            "pdf_type": hit.get("pdf_type"),
            "author": hit.get("author"),
            "owner": hit.get("owner"),
            "section_title": hit.get("section_title"),
            "page_number": hit.get("page_number"),
            "score": round(hit.get("rerank_score", hit.get("score", 0.0)), 3),
        })
    return "\n\n".join(lines), citations


class LlamaIndexRAGQuery:
    def __init__(self, similarity_top_k: int = 4, candidate_k: int = _CANDIDATE_K):
        self.validator = InputValidator()
        self.prompts = PromptLibrary()
        self.llm = LLMClient(model="gpt-4o-mini")
        self.evaluator = ResponseEvaluator(threshold=0.3)
        self.guardrail = SecurityGuardrail()
        self.similarity_top_k = similarity_top_k
        self.candidate_k = candidate_k
        self.collection_name = _collection_name()
        self._client = qdrant_client_helper.get_client()

    def _understand_query(self, question: str) -> dict:
        cleaned = question.strip()

        if self.llm.backend != "openai":
            return self._understand_query_fallback(cleaned)

        system = self.prompts.get("llamaindex_rag_agent.query_understanding")
        raw, usage = self.llm.complete(system, f"User question: {cleaned}")
        try:
            parsed = json.loads(raw)
            expanded_query = (parsed.get("expanded_query") or cleaned).strip() or cleaned
            filters = {k: v for k, v in (parsed.get("filters") or {}).items() if v}
            return {"expanded_query": expanded_query, "filters": filters, "usage": usage, "backend": "llm"}
        except (json.JSONDecodeError, AttributeError, TypeError):
            logger.warning("Query-understanding LLM response wasn't valid JSON; using heuristic fallback.")
            result = self._understand_query_fallback(cleaned)
            result["usage"] = usage
            return result

    def _understand_query_fallback(self, cleaned: str) -> dict:
        filters = {}
        for key, value in _FILTER_HINT_PATTERN.findall(cleaned):
            filters["pdf_type" if key.lower() == "type" else key.lower()] = value
        expanded_query = _FILTER_HINT_PATTERN.sub("", cleaned).strip() or cleaned
        return {"expanded_query": expanded_query, "filters": filters, "usage": None, "backend": "heuristic-fallback"}

    def _retrieve(self, expanded_query: str, filters: dict) -> list[dict]:
        try:
            if not self._client.collection_exists(self.collection_name):
                return []
        except Exception:
            pass

        dense_vector = _embed_query_dense(expanded_query)
        sparse_indices, sparse_values = build_sparse_vector(expanded_query)
        query_filter = qdrant_client_helper.build_metadata_filter(filters)

        scored_points = qdrant_client_helper.hybrid_search(
            self._client,
            self.collection_name,
            dense_vector,
            sparse_indices,
            sparse_values,
            limit=self.candidate_k,
            candidate_limit=self.candidate_k,
            query_filter=query_filter,
        )
        return [
            {
                "score": point.score,
                "text": point.payload.get("text", ""),
                "doc_id": point.payload.get("doc_id"),
                "pdf_type": point.payload.get("pdf_type"),
                "author": point.payload.get("author"),
                "owner": point.payload.get("owner"),
                "section_title": point.payload.get("section_title"),
                "page_number": point.payload.get("page_number"),
                "source_object_key": point.payload.get("source_object_key"),
            }
            for point in scored_points
        ]

    def _rerank_and_assemble(self, query_for_rerank: str, hits: list[dict]) -> tuple[list[dict], str, str, list[dict]]:
        reranked, rerank_backend = _cross_encoder_rerank(query_for_rerank, hits)
        top_hits = reranked[: self.similarity_top_k]
        context_block, citations = _build_context_with_citations(top_hits)
        return top_hits, rerank_backend, context_block, citations

    def _generate(self, context_block: str, question: str) -> tuple[str, dict]:
        system = self.prompts.get("llamaindex_rag_agent.system")
        return self.llm.complete(system, f"Context:\n{context_block}\n\nQuestion: {question}")

    @trace(name="llamaindex_rag_query.async_evaluate")
    def _evaluate_and_log(self, question: str, answer: str, top_hits: list[dict], usage: dict, started_at: float) -> None:
        try:
            eval_result = self.evaluator.evaluate(question, answer, context=[h["text"] for h in top_hits])
            latency_ms = round((time.time() - started_at) * 1000, 1)
            usage_record = log_usage(
                agent_path="rag_ingestion.query_engine",
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                model=self.llm.model,
            )
            logger.info(
                "async evaluate+log: score=%.2f passed=%s backend=%s latency_ms=%s cost_usd=%s",
                eval_result.score, eval_result.passed, eval_result.backend,
                latency_ms, usage_record["estimated_cost_usd"],
            )
        except Exception:
            logger.warning("Async evaluate+log failed (response was already sent).", exc_info=True)

    @trace(name="llamaindex_rag_query")
    def run(self, question: str) -> dict:
        started_at = time.time()
        stages: dict = {"collection_name": self.collection_name}

        validation = self.validator.validate(question)
        stages["input_validation"] = vars(validation)
        if not validation.is_safe:
            return {"status": "blocked_at_input_validation", "stages": stages}

        understanding = self._understand_query(question)
        stages["query_understanding"] = {k: v for k, v in understanding.items() if k != "usage"}
        expanded_query = understanding["expanded_query"]
        filters = understanding["filters"]
        total_usage = dict(understanding.get("usage") or {"input_tokens": 0, "output_tokens": 0})

        hits = self._retrieve(expanded_query, filters)
        stages["retrieved"] = [
            {"score": round(h["score"], 3), "doc_id": h["doc_id"], "text_preview": h["text"][:80] + "..."}
            for h in hits
        ]
        if not hits:
            return {
                "status": "no_matching_documents",
                "answer": "No ingested documents matched this question yet.",
                "stages": stages,
            }

        top_hits, rerank_backend, context_block, citations = self._rerank_and_assemble(expanded_query, hits)
        stages["rerank_backend"] = rerank_backend
        stages["reranked"] = [{"score": round(h.get("rerank_score", 0.0), 3), "doc_id": h["doc_id"]} for h in top_hits]

        answer, usage = self._generate(context_block, question)
        stages["answer"] = answer
        stages["llm_backend"] = self.llm.backend
        total_usage["input_tokens"] = total_usage.get("input_tokens", 0) + usage["input_tokens"]
        total_usage["output_tokens"] = total_usage.get("output_tokens", 0) + usage["output_tokens"]

        guard_result = self.guardrail.check(answer)
        stages["guardrail"] = vars(guard_result)
        if not guard_result.allowed:
            return {"status": "blocked_by_guardrail", "stages": stages}

        stages["citations"] = citations
        stages["evaluation"] = "running asynchronously -- see gates_ai_common/observability.log or Langfuse"

        threading.Thread(
            target=self._evaluate_and_log,
            args=(question, answer, top_hits, total_usage, started_at),
            daemon=True,
        ).start()

        return {"status": "ok", "answer": answer, "citations": citations, "stages": stages}
