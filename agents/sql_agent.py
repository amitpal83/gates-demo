"""
agents.sql_agent
--------------------
LLD worked example: a text-to-SQL agent for the "R&D Project Monitoring"
dataset, built entirely on the gates_ai_common shared library and LangChain.

Uses LangChain as the default framework for all scenarios:
- Development mode (no API keys): Uses mock LLM backend
- Production mode (with OPENAI_API_KEY): Uses live OpenAI backend

Run it directly:

    python3 -m agents.sql_agent "What is the total budget by region?"

With no API keys / extra packages installed, every stage still runs
using the fallback backends declared in gates_ai_common -- this is a
genuine end-to-end execution, not a mock of the whole pipeline, only
the external network calls (OpenAI, Langfuse, etc.) are stubbed.

Switch to production mode:

    export OPENAI_API_KEY=...

The agent will automatically use the live OpenAI backend through LangChain.
Nothing else needs to change -- gates_ai_common picks the live backend
automatically (see gates_ai_common/config.py).
"""
import re
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any

if __package__ is None or __package__ == "":
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from gates_ai_common import config
from gates_ai_common.input_validation import InputValidator
from gates_ai_common.prompt_library import PromptLibrary
from gates_ai_common.evaluation import ResponseEvaluator
from gates_ai_common.guardrails import SecurityGuardrail
from gates_ai_common.observability import trace, log_usage

# LangChain imports
LANGCHAIN_AVAILABLE = False
BaseChatModel = None
AIMessage = None
BaseMessage = None
ChatGeneration = None
CallbackManagerForLLMRun = None
SQLDatabase = None
SQLDatabaseToolkit = None
create_sql_agent = None

try:
    from langchain_community.utilities import SQLDatabase
    from langchain_community.agent_toolkits import SQLDatabaseToolkit
    try:
        from langchain.agents import create_sql_agent
    except ImportError:
        try:
            from langchain_community.agent_toolkits.sql.base import create_sql_agent
        except ImportError:
            pass
    
    try:
        from langchain.chat_models.base import BaseChatModel
    except ImportError:
        try:
            from langchain_core.language_models import BaseChatModel
        except ImportError:
            from langchain_core.chat_models import BaseChatModel
    
    from langchain_core.messages import AIMessage, BaseMessage
    from langchain_core.outputs import ChatGeneration
    from langchain_core.callbacks.manager import CallbackManagerForLLMRun
    LANGCHAIN_AVAILABLE = True
except Exception as e:
    import sys
    print(f"Warning: LangChain import partially failed: {e}", file=sys.stderr)


class MockLLM(BaseChatModel):
    """Mock LLM for development mode that uses deterministic SQL generation."""
    
    model_name: str = "mock-sql-generator"
    
    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatGeneration:
        """Generate a mock SQL response based on the user question."""
        # Extract the question from messages
        user_content = ""
        for msg in messages:
            if hasattr(msg, "content"):
                user_content += str(msg.content) + "\n"
        
        # Use the mock_sql_writer logic to generate SQL
        sql_query = mock_sql_writer("", user_content)
        
        return ChatGeneration(message=AIMessage(content=sql_query))
    
    @property
    def _llm_type(self) -> str:
        return "mock"

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        """Return this deterministic development model for LangChain SQL tools."""
        return self


if not LANGCHAIN_AVAILABLE:
    raise ImportError(
        "LangChain is required for the SQL agent. "
        "Install with: pip install langchain langchain-openai langchain-community"
    )

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
    conn = sqlite3.connect(":memory:")
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


class SQLAgent:
    """The full pipeline using LangChain: validate -> prompt -> LLM writes SQL
    (via LangChain agent) -> execute -> evaluate -> guardrail -> observe."""

    def __init__(self, db_conn: sqlite3.Connection | None = None, db_uri: str | None = None):
        """
        Args:
            db_conn: SQLite connection for demo mode (in-memory)
            db_uri: Database URI string (e.g., "sqlite:///path/db.sqlite")
                   If provided, LangChain's SQLDatabase is used directly.
                   Otherwise, db_conn is required.
        """
        if not LANGCHAIN_AVAILABLE:
            raise ImportError(
                "LangChain is required. Install with: "
                "pip install langchain langchain-openai langchain-community"
            )
        
        self.db_conn = db_conn
        self.db_uri = db_uri or "sqlite:///:memory:"
        self.db = None
        self.agent = None
        self.model = "gpt-4o-mini"
        self._temp_db_path: Path | None = None
        self.last_executed_sql = None  # Track SQL for evaluation
        
        self.validator = InputValidator()
        self.prompts = PromptLibrary()
        self.evaluator = ResponseEvaluator(threshold=0.3)
        self.guardrail = SecurityGuardrail(
            config_path=str(Path(__file__).resolve().parents[1] / "guardrails_config")
        )
        
        self._setup_langchain_agent()
    
    def _setup_langchain_agent(self):
        """Initialize LangChain SQL agent with appropriate LLM backend."""
        try:
            # For demo mode with in-memory DB, save to temp file so LangChain can access it
            if self.db_conn:
                temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
                temp_file.close()
                self._temp_db_path = Path(temp_file.name)
                
                # Export in-memory DB to file
                file_conn = sqlite3.connect(self._temp_db_path)
                try:
                    self.db_conn.backup(file_conn)
                finally:
                    file_conn.close()
                
                # Use the file-based URI
                self.db_uri = f"sqlite:///{self._temp_db_path.as_posix()}"
            
            # Set up the SQL database using LangChain
            self.db = SQLDatabase.from_uri(self.db_uri)
            
            # Create LLM (mock or live based on config)
            if config.USE_LIVE_LLM:
                try:
                    from langchain_openai import ChatOpenAI
                    llm = ChatOpenAI(
                        model=self.model,
                        temperature=0,
                        timeout=config.LLM_REQUEST_TIMEOUT_SECONDS,
                        max_retries=2,
                    )
                except ImportError:
                    raise ImportError(
                        "langchain-openai is required for production mode. "
                        "Install with: pip install langchain-openai"
                    )
            else:
                llm = MockLLM()
            
            # Create SQL toolkit and agent
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
            stages["guardrail"] = {
                "allowed": False,
                "reason": "off_topic_question",
                "backend": "topic-check",
            }
            return {"status": "blocked_by_guardrail", "stages": stages}

        # 2. Prompt library
        system_prompt = self.prompts.get("sql_agent.system")
        stages["prompt_backend"] = self.prompts.backend
        stages["prompt_source"] = self.prompts.last_fetch_source
        stages["prompt_name"] = self.prompts.last_fetch_name
        stages["prompt_version"] = self.prompts.last_fetch_version
        stages["prompt_preview"] = system_prompt[:200] + (
            "..." if len(system_prompt) > 200 else ""
        )

        # 3. LangChain agent execution (generates SQL and executes it)
        # Create a callback to capture SQL executions
        try:
            from langchain_core.callbacks import BaseCallbackHandler
            
            class SQLCaptureCallback(BaseCallbackHandler):
                def __init__(self):
                    self.sql_queries = []
                
                def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, tags=None, metadata=None, **kwargs):
                    # Capture SQL queries from the sql_db_query tool
                    if "sql_db_query" in serialized.get("name", ""):
                        self.sql_queries.append(input_str)
            
            callback = SQLCaptureCallback()
            agent_result = self.agent.invoke(
                {"input": question},
                config={"callbacks": [callback]}
            )
            
            # Extract the output
            result_text = agent_result.get("output", "")
            stages["generated_sql"] = callback.sql_queries[0] if callback.sql_queries else "Query execution via LangChain agent"
            self.last_executed_sql = callback.sql_queries[0] if callback.sql_queries else ""
            
        except Exception as exc:
            # Fallback if callback approach doesn't work
            try:
                agent_result = self.agent.invoke({"input": question})
                result_text = agent_result.get("output", "")
                stages["generated_sql"] = "Query executed by LangChain agent"
            except Exception as e:
                return {
                    "status": "agent_execution_error",
                    "error": str(e),
                    "stages": stages,
                }
        
        stages["llm_backend"] = "langchain-openai" if config.USE_LIVE_LLM else "langchain-mock"
        stages["sql_result"] = result_text

        # 4. Evaluation (using captured SQL for proper grounding)
        eval_case = self.evaluator.build_case(
            question, self.last_executed_sql, [SCHEMA_DDL.strip()]
        )
        eval_result = self.evaluator.evaluate_case(eval_case)
        stages["evaluation"] = (
            vars(eval_result) if hasattr(eval_result, "__dict__") else eval_result
        )
        if not eval_result.passed:
            return {"status": "failed_evaluation", "stages": stages}

        # 5. Security guardrail (output side)
        guard_result = self.guardrail.check(result_text)
        stages["guardrail"] = vars(guard_result)
        if not guard_result.allowed:
            return {"status": "blocked_by_guardrail", "stages": stages}

        # 6. Observability -- tokens & cost
        usage_record = log_usage(
            agent_path="sql_agent",
            input_tokens=len(question.split()),
            output_tokens=len(result_text.split()),
            model=self.model,
        )
        stages["usage"] = usage_record

        return {
            "status": "ok",
            "result": result_text,
            "stages": stages,
        }


def main():
    question = sys.argv[1] if len(sys.argv) > 1 else "What is the total budget by region?"

    config.print_backend_report()
    print(f"\nQuestion: {question}\n")

    # Build demo database
    conn = build_demo_database()
    
    # Create and run SQL agent with LangChain
    try:
        agent = SQLAgent(db_conn=conn)
        outcome = agent.run(question)

        print(f"Status: {outcome['status']}\n")
        for stage, detail in outcome["stages"].items():
            print(f"  [{stage}] {detail}")

        if outcome["status"] == "ok":
            print(f"\nResult: {outcome['result']}")
    except Exception as e:
        print(f"Error initializing SQL Agent: {e}")
        print("Make sure LangChain is installed: pip install langchain langchain-openai langchain-community")
        sys.exit(1)


if __name__ == "__main__":
    main()
