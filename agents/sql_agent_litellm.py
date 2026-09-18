"""Sibling of agents.sql_agent that routes every LLM call through a LiteLLM Proxy instead of OpenAI directly, for gateway-centralized governance (routing, fallback, PII, guardrails, caching, observability, spend tracking); additive and self-contained, falling back to the same offline MockLLM when the proxy isn't configured."""
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

if __package__ is None or __package__ == "":
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from gates_ai_common.evaluation import ResponseEvaluator
from gates_ai_common.observability import trace, log_usage
from gates_ai_common.prompt_library import PromptLibrary

from agents.sql_agent import SCHEMA_DDL, build_demo_database, MockLLM

LANGCHAIN_AVAILABLE = False
try:
    from langchain_community.utilities import SQLDatabase
    from langchain_community.agent_toolkits import SQLDatabaseToolkit
    try:
        from langchain.agents import create_sql_agent
    except ImportError:
        from langchain_community.agent_toolkits.sql.base import create_sql_agent
    from langchain_openai import ChatOpenAI
    from langchain_core.callbacks import BaseCallbackHandler
    from langchain_core.outputs import ChatResult
    LANGCHAIN_AVAILABLE = True
except Exception as e:
    print(f"Warning: LangChain import partially failed: {e}", file=sys.stderr)

if not LANGCHAIN_AVAILABLE:
    raise ImportError(
        "LangChain (+ langchain-openai) is required for the LiteLLM SQL agent. "
        "Install with: pip install langchain langchain-openai langchain-community"
    )

# -- LiteLLM Proxy configuration -- read directly (not via gates_ai_common.config) to stay additive --
LITELLM_PROXY_URL = os.getenv("LITELLM_PROXY_URL")
LITELLM_VIRTUAL_KEY = os.getenv("LITELLM_VIRTUAL_KEY")
LITELLM_MASTER_KEY = os.getenv("LITELLM_MASTER_KEY")
LITELLM_MODEL_NAME = os.getenv("LITELLM_MODEL_NAME", "gates-sql-writer")
USE_LITELLM_PROXY = bool(LITELLM_PROXY_URL) and bool(LITELLM_VIRTUAL_KEY)


class _MockLLM(MockLLM):
    """Fixes agents.sql_agent.MockLLM._generate() returning a bare ChatGeneration instead of a ChatResult, locally, to keep sql_agent.py untouched."""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        generation = super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
        return ChatResult(generations=[generation])


class _CaptureCallback(BaseCallbackHandler):
    """Captures the SQL the agent executes plus the raw LLM response metadata, which reveals which deployment LiteLLM actually used."""

    def __init__(self):
        self.sql_queries: list[str] = []
        self.llm_responses: list[dict] = []

    def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, tags=None, metadata=None, **kwargs):
        if "sql_db_query" in serialized.get("name", ""):
            self.sql_queries.append(input_str)

    def on_llm_end(self, response, *, run_id, parent_run_id=None, tags=None, **kwargs):
        try:
            self.llm_responses.append(dict(response.llm_output or {}))
        except Exception:
            pass


class SQLAgentLiteLLM:
    """Sibling pipeline to SQLAgent: prompt -> LLM writes SQL through the LiteLLM Proxy (which owns input/output guardrails) -> execute -> evaluate -> observe."""

    def __init__(self, db_conn: sqlite3.Connection | None = None, db_uri: str | None = None):
        self.db_conn = db_conn
        self.db_uri = db_uri or "sqlite:///:memory:"
        self.db = None
        self.agent = None
        self.model = LITELLM_MODEL_NAME if USE_LITELLM_PROXY else "mock-sql-generator"
        self._temp_db_path: Path | None = None
        self.last_executed_sql = None
        self.history: list[tuple[str, str]] = []  # conversation memory (question, answer) pairs

        self.prompts = PromptLibrary()
        self.evaluator = ResponseEvaluator(threshold=0.3)

        self._setup_langchain_agent()

    def _setup_langchain_agent(self):
        try:
            if self.db_conn:
                temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
                temp_file.close()
                self._temp_db_path = Path(temp_file.name)
                file_conn = sqlite3.connect(self._temp_db_path)
                try:
                    self.db_conn.backup(file_conn)
                finally:
                    file_conn.close()
                self.db_uri = f"sqlite:///{self._temp_db_path.as_posix()}"

            self.db = SQLDatabase.from_uri(self.db_uri)

            if USE_LITELLM_PROXY:
                llm = ChatOpenAI(
                    base_url=LITELLM_PROXY_URL,
                    api_key=LITELLM_VIRTUAL_KEY,
                    model=LITELLM_MODEL_NAME,
                    temperature=0,
                    timeout=30,
                    max_retries=0,  # let the LiteLLM proxy own retries/fallback, not the client
                )
            else:
                llm = _MockLLM()

            toolkit = SQLDatabaseToolkit(db=self.db, llm=llm)
            self.agent = create_sql_agent(
                llm=llm,
                toolkit=toolkit,
                agent_type="tool-calling",
                top_k=10,
                max_iterations=5,
                verbose=False,
            )
        except Exception as e:
            raise RuntimeError(f"Failed to set up LangChain SQL agent: {e}")

    def close(self):
        """Release the demo database file created for LangChain."""
        if self.db is not None:
            self.db._engine.dispose()
        if self._temp_db_path and self._temp_db_path.exists():
            self._temp_db_path.unlink()
            self._temp_db_path = None

    def _gateway_status(self) -> dict:
        """Best-effort peek at the proxy's virtual-key spend/budget -- the
        'memory' LiteLLM itself tracks, persisted in its Postgres DB."""
        if not (USE_LITELLM_PROXY and LITELLM_MASTER_KEY):
            return {"available": False, "reason": "LITELLM_MASTER_KEY not set"}
        try:
            import httpx
            resp = httpx.get(
                f"{LITELLM_PROXY_URL}/key/info",
                params={"key": LITELLM_VIRTUAL_KEY},
                headers={"Authorization": f"Bearer {LITELLM_MASTER_KEY}"},
                timeout=5,
            )
            resp.raise_for_status()
            body = resp.json()
            info = body.get("info", body)
            return {"available": True, "spend": info.get("spend"), "max_budget": info.get("max_budget")}
        except Exception as exc:
            return {"available": False, "reason": str(exc)}

    @trace(name="sql_agent_litellm_run")
    def run(self, question: str) -> dict:
        stages = {"backend": "litellm-proxy" if USE_LITELLM_PROXY else "mock"}

        # 1. Prompt library -- still versions the system prompt; LiteLLM has no prompt-management feature of its own.
        system_prompt = self.prompts.get("sql_agent.system")
        stages["prompt_backend"] = self.prompts.backend
        stages["prompt_source"] = self.prompts.last_fetch_source

        # 2. Conversation memory: fold prior turns into the input so a follow-up like "now just Region V" resolves correctly.
        history_block = ""
        if self.history:
            history_block = "Conversation so far:\n" + "\n".join(
                f"Q: {q}\nA: {a}" for q, a in self.history
            ) + "\n\n"
        agent_input = f"{history_block}Question: {question}"

        # 3. LangChain agent execution -- every LLM call inside goes through the LiteLLM proxy, invisibly to this code.
        callback = _CaptureCallback()
        start = time.time()
        try:
            agent_result = self.agent.invoke({"input": agent_input}, config={"callbacks": [callback]})
            result_text = agent_result.get("output", "")
        except Exception as e:
            return {"status": "agent_execution_error", "error": str(e), "stages": stages}
        elapsed = time.time() - start

        self.last_executed_sql = callback.sql_queries[0] if callback.sql_queries else ""
        stages["generated_sql"] = self.last_executed_sql or "Query executed by LangChain agent"
        stages["sql_result"] = result_text
        stages["elapsed_seconds"] = round(elapsed, 3)
        stages["llm_backend"] = "litellm-proxy" if USE_LITELLM_PROXY else "mock"

        # Resolved model name from LiteLLM's completion response -- reveals whether the primary or fallback deployment served this call.
        resolved_models = [r.get("model_name") for r in callback.llm_responses if r.get("model_name")]
        stages["resolved_model"] = resolved_models[-1] if resolved_models else self.model

        # 4. Evaluation -- kept at the app level, see class docstring.
        eval_case = self.evaluator.build_case(question, self.last_executed_sql, [SCHEMA_DDL.strip()])
        eval_result = self.evaluator.evaluate_case(eval_case)
        stages["evaluation"] = vars(eval_result) if hasattr(eval_result, "__dict__") else eval_result
        if not eval_result.passed:
            return {"status": "failed_evaluation", "stages": stages}

        # 5. Observability -- the app-level trace/usage log, complementing the proxy's own Langfuse callback.
        usage_record = log_usage(
            agent_path="sql_agent_litellm",
            input_tokens=len(agent_input.split()),
            output_tokens=len(result_text.split()),
            model=stages["resolved_model"],
        )
        stages["usage"] = usage_record
        stages["gateway_status"] = self._gateway_status()

        self.history.append((question, result_text))
        return {"status": "ok", "result": result_text, "stages": stages}


def main():
    question = sys.argv[1] if len(sys.argv) > 1 else "What is the total budget by region?"
    print(f"LiteLLM proxy configured: {USE_LITELLM_PROXY}")
    if not USE_LITELLM_PROXY:
        print("Set LITELLM_PROXY_URL and LITELLM_VIRTUAL_KEY to use the live proxy; falling back to MockLLM.\n")
    print(f"Question: {question}\n")

    conn = build_demo_database()
    try:
        agent = SQLAgentLiteLLM(db_conn=conn)
        outcome = agent.run(question)
        print(f"Status: {outcome['status']}\n")
        for stage, detail in outcome.get("stages", {}).items():
            print(f"  [{stage}] {detail}")
        if outcome["status"] == "ok":
            print(f"\nResult: {outcome['result']}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
