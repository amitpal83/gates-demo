"""
agents.sql_agent
--------------------
LLD worked example: a text-to-SQL agent for the "R&D Project Monitoring"
dataset, built entirely on the gates_ai_common shared library.

Run it directly:

    python3 -m agents.sql_agent "What is the total budget by region?"

With no API keys / extra packages installed, every stage still runs
using the fallback backends declared in gates_ai_common -- this is a
genuine end-to-end execution, not a mock of the whole pipeline, only
the external network calls (OpenAI, Langfuse, etc.) are stubbed.

Install the production stack to switch every stage to its live backend:

    pip install langchain langchain-openai langgraph llm-guard \
                nemoguardrails deepeval langfuse openai
    export OPENAI_API_KEY=...

Nothing in this file changes when you do that -- gates_ai_common picks
the live backend automatically (see gates_ai_common/config.py).
"""
import re
import sqlite3
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from gates_ai_common import config
from gates_ai_common.input_validation import InputValidator
from gates_ai_common.prompt_library import PromptLibrary
from gates_ai_common.llm_client import LLMClient
from gates_ai_common.evaluation import ResponseEvaluator
from gates_ai_common.guardrails import SecurityGuardrail
from gates_ai_common.observability import trace, log_usage

SCHEMA_DDL = """
CREATE TABLE rd_project_monitoring (
    project_id      TEXT PRIMARY KEY,
    agency          TEXT,
    program_area    TEXT,
    region          TEXT,
    quarter         TEXT,
    budget_php      REAL,
    utilization_rate REAL
);
"""

SAMPLE_ROWS = [
    ("PRJ-001", "PCHRD", "Health R&D", "Region IV-A", "2026-Q1", 4_500_000, 0.82),
    ("PRJ-002", "PCHRD", "Health R&D", "Region V", "2026-Q1", 3_200_000, 0.65),
    ("PRJ-003", "PCAARRD", "Agri R&D", "Region III", "2026-Q1", 2_800_000, 0.91),
    ("PRJ-004", "PCAARRD", "Agri R&D", "Region V", "2026-Q1", 1_950_000, 0.58),
    ("PRJ-005", "PCIEERD", "Industry R&D", "Region IV-A", "2026-Q1", 5_100_000, 0.77),
    ("PRJ-006", "PCIEERD", "Industry R&D", "NCR", "2026-Q1", 6_300_000, 0.88),
]


def build_demo_database() -> sqlite3.Connection:
    """Creates and seeds an in-memory SQLite DB standing in for the
    GATES lakehouse gold-layer table this agent would query in
    production (via Trino, not sqlite3)."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute(SCHEMA_DDL)
    conn.executemany(
        "INSERT INTO rd_project_monitoring VALUES (?, ?, ?, ?, ?, ?, ?)", SAMPLE_ROWS
    )
    conn.commit()
    return conn


def mock_sql_writer(system: str, user: str) -> str:
    """Stands in for the LLM's SQL-writing behaviour when no OpenAI key
    is configured, using simple keyword matching so the demo produces
    a real, executable query rather than a canned string."""
    match = re.search(r"Question:\s*(.*)", user, re.IGNORECASE)
    q = (match.group(1) if match else user).lower()
    if "budget" in q and "region" in q:
        return "SELECT region, SUM(budget_php) AS total_budget FROM rd_project_monitoring GROUP BY region ORDER BY total_budget DESC;"
    if "budget" in q and "agency" in q:
        return "SELECT agency, SUM(budget_php) AS total_budget FROM rd_project_monitoring GROUP BY agency ORDER BY total_budget DESC;"
    if "utilization" in q:
        return "SELECT project_id, agency, utilization_rate FROM rd_project_monitoring ORDER BY utilization_rate ASC;"
    return "SELECT * FROM rd_project_monitoring;"


def is_read_only(sql: str) -> bool:
    forbidden = re.compile(r"\b(insert|update|delete|drop|alter|create)\b", re.IGNORECASE)
    return not forbidden.search(sql)


class SQLAgent:
    """The full pipeline: validate -> prompt -> LLM writes SQL ->
    execute -> evaluate -> guardrail -> observe."""

    def __init__(self, db_conn: sqlite3.Connection):
        self.db = db_conn
        self.validator = InputValidator()
        self.prompts = PromptLibrary()
        self.llm = LLMClient(model="gpt-4o-mini", mock_fn=mock_sql_writer)
        self.evaluator = ResponseEvaluator(threshold=0.3)
        self.guardrail = SecurityGuardrail(config_path=str(Path(__file__).resolve().parents[1] / "guardrails_config"))

    @trace(name="sql_agent_run")
    def run(self, question: str) -> dict:
        stages = {}

        # 1. Input validation
        validation = self.validator.validate(question)
        stages["input_validation"] = vars(validation)
        if not validation.is_safe:
            return {"status": "blocked_at_input_validation", "stages": stages}

        # 1.5 Topic relevance check (guardrail)
        topic_check = self.guardrail.check_topic_relevance(question)
        stages["topic_relevance"] = vars(topic_check)
        if not topic_check.allowed:
            stages["guardrail"] = {"allowed": False, "reason": "off_topic_question", "backend": "topic-check"}
            return {"status": "blocked_by_guardrail", "stages": stages}

        # 2. Prompt library
        system_prompt = self.prompts.get("sql_agent.system")
        stages["prompt_backend"] = self.prompts.backend
        stages["prompt_source"] = self.prompts.last_fetch_source
        stages["prompt_name"] = self.prompts.last_fetch_name
        stages["prompt_version"] = self.prompts.last_fetch_version
        stages["prompt_preview"] = system_prompt[:200] + ("..." if len(system_prompt) > 200 else "")

        # 3. LLM call -> SQL text
        schema_context = SCHEMA_DDL.strip()
        user_prompt = f"Schema:\n{schema_context}\n\nQuestion: {question}\nWrite the SQL query only."
        sql_text, usage = self.llm.complete(system_prompt, user_prompt)
        sql_text = sql_text.strip()
        fenced_match = re.fullmatch(r"```(?:sql)?\s*(.*?)\s*```", sql_text, re.IGNORECASE | re.DOTALL)
        if fenced_match:
            sql_text = fenced_match.group(1).strip()
        stages["generated_sql"] = sql_text
        stages["llm_backend"] = self.llm.backend

        # Guard against non read-only SQL before ever executing it.
        if not is_read_only(sql_text):
            return {"status": "blocked_non_readonly_sql", "stages": stages}

        # 4. Execute against the (demo) lakehouse
        try:
            cursor = self.db.execute(sql_text)
            columns = [d[0] for d in cursor.description]
            rows = cursor.fetchall()
            result_text = "; ".join(
                ", ".join(f"{c}={v}" for c, v in zip(columns, row)) for row in rows
            )
        except sqlite3.Error as exc:
            return {"status": "sql_execution_error", "error": str(exc), "stages": stages}
        stages["sql_result"] = result_text

        # 5. Evaluation (schema text used as grounding context)
        eval_case = self.evaluator.build_case(question, sql_text, [schema_context])
        eval_result = self.evaluator.evaluate_case(eval_case)
        stages["evaluation"] = vars(eval_result) if hasattr(eval_result, "__dict__") else eval_result.__dict__
        if not eval_result.passed:
            return {"status": "failed_evaluation", "stages": stages}

        # 6. Security guardrail (output side)
        guard_result = self.guardrail.check(result_text)
        stages["guardrail"] = vars(guard_result)
        if not guard_result.allowed:
            return {"status": "blocked_by_guardrail", "stages": stages}

        # 7. Observability -- tokens & cost
        usage_record = log_usage(
            agent_path="sql_agent",
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
            model=self.llm.model,
        )
        stages["usage"] = usage_record

        return {"status": "ok", "sql": sql_text, "result": result_text, "stages": stages}


def run_with_langchain_production_stack(question: str) -> str:
    """Production code path -- NOT executed by default in this demo,
    shown here so the file is a complete reference, not just the
    offline-safe version.

    Requires: pip install langchain langchain-openai langchain-community
    and OPENAI_API_KEY set. Swap the SQLDatabase URI for the real
    Trino/lakehouse gold-layer connection string in production.
    """
    from langchain_community.agent_toolkits import SQLDatabaseToolkit
    from langchain_community.utilities import SQLDatabase
    from langchain_openai import ChatOpenAI
    from langchain.agents import create_sql_agent

    db = SQLDatabase.from_uri("sqlite:///gates_demo.db")  # -> trino://gates-lakehouse/gold in production
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    toolkit = SQLDatabaseToolkit(db=db, llm=llm)
    agent = create_sql_agent(llm=llm, toolkit=toolkit, agent_type="tool-calling",
                              top_k=10, max_iterations=5)
    return agent.invoke({"input": question})["output"]


def main():
    question = sys.argv[1] if len(sys.argv) > 1 else "What is the total budget by region?"

    config.print_backend_report()
    print(f"\nQuestion: {question}\n")

    conn = build_demo_database()
    agent = SQLAgent(conn)
    outcome = agent.run(question)

    print(f"Status: {outcome['status']}\n")
    for stage, detail in outcome["stages"].items():
        print(f"  [{stage}] {detail}")

    if outcome["status"] == "ok":
        print(f"\nSQL executed: {outcome['sql']}")
        print(f"Result: {outcome['result']}")


if __name__ == "__main__":
    main()
