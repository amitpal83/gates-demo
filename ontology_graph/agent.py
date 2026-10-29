"""Policy Q&A: combines the customer's PostgreSQL record, plan facts from the GraphDB ontology and brochure passages from Qdrant into one grounded answer."""
from __future__ import annotations

import datetime
import json
import logging

from ontology_graph import hooks, llm, prompts
from ontology_graph.clients import graphdb, policy_store, qdrant_store
from ontology_graph.ontology import queries
from ontology_graph.pipeline.common import build_sparse_vector

logger = logging.getLogger(__name__)

TOP_K = 5


class PolicyAgent:
    def _ontology_facts(self, record: dict, stages: dict) -> list[str]:
        try:
            rows = graphdb.select(queries.policy_context_query(record["plan_uin"], record.get("fund_name")))
            lines = queries.rows_to_lines(rows)
            stages["ontology_facts"] = lines
            return lines
        except Exception as error:
            logger.warning("Ontology lookup failed: %s", error)
            stages["ontology_error"] = str(error)
            return []

    def _passages(self, question: str, stages: dict) -> list[dict]:
        dense = llm.embed([question])[0]
        sparse_indices, sparse_values = build_sparse_vector(question)
        hits = qdrant_store.hybrid_search(qdrant_store.get_client(), dense, sparse_indices, sparse_values, TOP_K)
        stages["passages"] = [
            {"marker": f"[{i}]", "page": h.get("page_number"), "score": round(h["score"], 3), "text": h.get("text", "")}
            for i, h in enumerate(hits, start=1)
        ]
        return hits

    def answer(self, policy_number: str, question: str) -> dict:
        stages: dict = {}

        verdict = hooks.check_question(question)
        if not verdict.allowed:
            return {"status": "blocked_at_question", "answer": verdict.reason, "stages": stages}

        record = policy_store.get_policy(policy_number)
        if record is None:
            return {"status": "policy_not_found", "answer": f"No policy found for {policy_number}.", "stages": stages}
        stages["policy_record"] = record

        fact_lines = self._ontology_facts(record, stages)
        hits = self._passages(question, stages)
        if not hits and not fact_lines:
            return {"status": "no_context", "answer": "No plan documents have been ingested yet.", "stages": stages}

        passages_text = "\n\n".join(f"[{i}] (page {h.get('page_number')}) {h.get('text', '')}" for i, h in enumerate(hits, start=1))
        user = prompts.ANSWER_USER.format(
            record=json.dumps(record, indent=2, default=str),
            facts="\n".join(fact_lines) or "(none available)",
            passages=passages_text or "(none available)",
            question=question,
        )
        system = prompts.ANSWER_SYSTEM.format(today=datetime.date.today().isoformat())
        answer = llm.complete(system, user)

        verdict = hooks.check_answer(answer, context=user)
        if not verdict.allowed:
            return {"status": "blocked_at_answer", "answer": verdict.reason, "stages": stages}
        return {"status": "ok", "answer": answer, "stages": stages}
