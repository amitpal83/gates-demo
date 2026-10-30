"""The two demo agents. Both get the same model, temperature, instructions, policy record and database column descriptions; only the ontology agent also gets the plan ontology facts fetched from GraphDB by plan UIN and mode code."""
from __future__ import annotations

import datetime
import json
import logging

from ontology_graph import hooks, llm, prompts
from ontology_graph.clients import graphdb, policy_store
from ontology_graph.ontology import queries

logger = logging.getLogger(__name__)


def ontology_facts(record: dict) -> list[str]:
    """Plan facts for this policy; raises if GraphDB is unreachable so the ontology agent never silently falls back to SQL-only."""
    rows = graphdb.select(queries.policy_context_query(record["plan_uin"], record["mode_code"]))
    return queries.rows_to_lines(rows)


def _ask(record: dict, notes: dict, facts: list[str] | None, question: str) -> dict:
    system = prompts.ANSWER_SYSTEM.format(today=datetime.date.today().isoformat())
    user = prompts.ANSWER_USER_RECORD.format(
        record=json.dumps(record, indent=2, default=str),
        notes="\n".join(f"- {column}: {text}" for column, text in notes.items()),
    )
    if facts is not None:
        user += prompts.ANSWER_USER_ONTOLOGY.format(facts="\n".join(facts) or "(no matching ontology facts)")
    user += prompts.ANSWER_USER_QUESTION.format(question=question)

    raw = llm.complete(system, user, json_mode=True)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"status": "invalid_json", "answer": {}, "raw": raw, "prompt": user}

    verdict = hooks.check_answer(str(parsed.get("answer", "")), context=user)
    if not verdict.allowed:
        return {"status": "blocked_at_answer", "answer": {"answer": verdict.reason}, "raw": raw, "prompt": user}
    return {"status": "ok", "answer": parsed, "raw": raw, "prompt": user}


def run_ontology_agent(record: dict, notes: dict, question: str) -> dict:
    """Agent A: PostgreSQL record + plan ontology."""
    facts = ontology_facts(record)
    result = _ask(record, notes, facts, question)
    result["ontology_facts"] = facts
    return result


def run_sql_only_agent(record: dict, notes: dict, question: str) -> dict:
    """Agent B: PostgreSQL record only."""
    return _ask(record, notes, None, question)


def load_policy_context(policy_number: str) -> tuple[dict, dict]:
    record = policy_store.get_policy(policy_number)
    if record is None:
        raise LookupError(f"No policy found for {policy_number}.")
    return record, policy_store.column_notes()
