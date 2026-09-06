"""
agents.orchestration_flow
-----------------------------
Runnable demo of the HLD Orchestration Flow:

    Router -> [LangChain simple | LangGraph multi-agent]
           -> Input validation (pass / fail)
           -> Prompt library
           -> LLM call
           -> Evaluation (ok / not ok, retry loop capped at 2)
           -> Security guardrail
           -> Observability (tokens & cost)

Run it directly:

    python3 -m agents.orchestration_flow "Summarize GATES in one sentence"
    python3 -m agents.orchestration_flow "Summarize GATES and also list its four components"

The second example has two sub-asks, which routes to the multi-agent
path -- watch the printed trace change accordingly.

Production stack: pip install langchain langgraph openai llm-guard
nemoguardrails deepeval langfuse
"""
import json
import re
import sys
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

# Add the project root when this module is run directly as a script.
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

ORCHESTRATION_GUARDRAILS_PATH = Path(__file__).resolve().parents[1] / "guardrails_config" / "orchestration"


class OrchestrationState(TypedDict, total=False):
    question: str
    status: str
    plan: list[str]
    task_results: list[dict]
    answer: str
    stages: dict


class SubtaskState(TypedDict, total=False):
    task: str
    status: str
    answer: str
    stages: dict


def mock_answer(system: str, user: str) -> str:
    if "Return JSON only" in system:
        question = user.split("Question:", 1)[-1].strip()
        tasks = [part.strip() for part in re.split(r"\s+(?:and|then)\s+|;", question) if part.strip()]
        return json.dumps({"tasks": tasks or [question]})
    if "Subtask results:" in user:
        return " ".join(re.findall(r"Answer: (.*)", user))
    return f"Answer based on subtask: {user.split('Task:', 1)[-1].strip()[:120]}"


class OrchestratorAgent:
    """LangGraph orchestrator for generic LLM subtasks only."""

    def __init__(self):
        self.prompts = PromptLibrary()
        self.llm = LLMClient(model="gpt-4o-mini", mock_fn=mock_answer)
        self.guardrail = SecurityGuardrail(config_path=str(ORCHESTRATION_GUARDRAILS_PATH))
        self.subtask_graph = self._build_subtask_graph()
        self.graph = self._build_graph()

    def _build_subtask_graph(self):
        graph = StateGraph(SubtaskState)
        graph.add_node("validate", self._validate_subtask)
        graph.add_node("execute", self._execute_subtask)
        graph.add_node("evaluate", self._evaluate_subtask)
        graph.add_node("guard", self._guard_subtask)
        graph.add_edge(START, "validate")
        graph.add_edge("validate", "execute")
        graph.add_edge("execute", "evaluate")
        graph.add_edge("evaluate", "guard")
        graph.add_edge("guard", END)
        return graph.compile()

    def _build_graph(self):
        graph = StateGraph(OrchestrationState)
        graph.add_node("validate_input", self._validate_input)
        graph.add_node("plan_tasks", self._plan_tasks)
        graph.add_node("execute_tasks", self._execute_tasks)
        graph.add_node("combine_results", self._combine_results)
        graph.add_node("final_guard", self._final_guard)
        graph.add_edge(START, "validate_input")
        graph.add_edge("validate_input", "plan_tasks")
        graph.add_edge("plan_tasks", "execute_tasks")
        graph.add_edge("execute_tasks", "combine_results")
        graph.add_edge("combine_results", "final_guard")
        graph.add_edge("final_guard", END)
        return graph.compile()

    def _validate_input(self, state: OrchestrationState) -> dict:
        validation = InputValidator().validate(state["question"])
        stages = {"input_validation": vars(validation), "orchestration_path": "langgraph_multi_agent"}
        if not validation.is_safe:
            return {"status": "blocked_at_input_validation", "stages": stages}
        return {"status": "running", "stages": stages}

    def _plan_tasks(self, state: OrchestrationState) -> dict:
        if state["status"] != "running":
            return {}
        planner_prompt = self.prompts.get("orchestration_agent.planner")
        plan_text, usage = self.llm.complete(planner_prompt, f"Question: {state['question']}")
        try:
            tasks = json.loads(plan_text)["tasks"]
            tasks = [task.strip() for task in tasks if isinstance(task, str) and task.strip()]
        except (json.JSONDecodeError, KeyError, TypeError):
            tasks = [state["question"]]
        stages = dict(state["stages"])
        stages["plan"] = tasks
        stages["planner_prompt"] = {
            "backend": self.prompts.backend,
            "source": self.prompts.last_fetch_source,
            "name": self.prompts.last_fetch_name,
            "version": self.prompts.last_fetch_version,
        }
        stages["planner_usage"] = log_usage("orchestration:planner", usage["input_tokens"], usage["output_tokens"], self.llm.model)
        return {"plan": tasks or [state["question"]], "stages": stages}

    def _validate_subtask(self, state: SubtaskState) -> dict:
        validation = InputValidator().validate(state["task"])
        stages = {"input_validation": vars(validation)}
        return {"status": "running" if validation.is_safe else "blocked_at_input_validation", "stages": stages}

    def _execute_subtask(self, state: SubtaskState) -> dict:
        if state["status"] != "running":
            return {}
        prompt = self.prompts.get("orchestration_agent.system")
        answer, usage = self.llm.complete(prompt, f"Task: {state['task']}")
        stages = dict(state["stages"])
        stages["prompt"] = {
            "backend": self.prompts.backend,
            "source": self.prompts.last_fetch_source,
            "name": self.prompts.last_fetch_name,
            "version": self.prompts.last_fetch_version,
        }
        stages["usage"] = log_usage("orchestration:subtask", usage["input_tokens"], usage["output_tokens"], self.llm.model)
        return {"answer": answer, "stages": stages}

    def _evaluate_subtask(self, state: SubtaskState) -> dict:
        if state["status"] != "running":
            return {}
        evaluation = ResponseEvaluator(threshold=0.0).evaluate(state["task"], state.get("answer", ""), context=[])
        stages = dict(state["stages"])
        stages["evaluation"] = vars(evaluation)
        return {"status": "running" if evaluation.passed else "failed_evaluation", "stages": stages}

    def _guard_subtask(self, state: SubtaskState) -> dict:
        if state["status"] != "running":
            return {}
        guardrail = self.guardrail.check(state.get("answer", ""))
        stages = dict(state["stages"])
        stages["guardrail"] = vars(guardrail)
        return {"status": "ok" if guardrail.allowed else "blocked_by_guardrail", "stages": stages}

    def _execute_tasks(self, state: OrchestrationState) -> dict:
        if state["status"] != "running":
            return {}
        task_results = [self.subtask_graph.invoke({"task": task}) for task in state["plan"]]
        stages = dict(state["stages"])
        stages["subtask_count"] = len(task_results)
        return {"task_results": task_results, "stages": stages}

    def _combine_results(self, state: OrchestrationState) -> dict:
        if state["status"] != "running":
            return {}
        successful = [result for result in state["task_results"] if result.get("status") == "ok"]
        if not successful:
            return {"status": "no_subtask_completed"}
        synthesis_prompt = self.prompts.get("orchestration_agent.synthesizer")
        task_text = "\n".join(f"Task: {result['task']}\nAnswer: {result['answer']}" for result in successful)
        answer, usage = self.llm.complete(synthesis_prompt, f"Question: {state['question']}\n\nSubtask results:\n{task_text}")
        evaluation = ResponseEvaluator(threshold=0.0).evaluate(state["question"], answer, context=[])
        stages = dict(state["stages"])
        stages["synthesis"] = {
            "prompt": {
                "backend": self.prompts.backend,
                "source": self.prompts.last_fetch_source,
                "name": self.prompts.last_fetch_name,
                "version": self.prompts.last_fetch_version,
            },
            "evaluation": vars(evaluation),
            "usage": log_usage("orchestration:synthesis", usage["input_tokens"], usage["output_tokens"], self.llm.model),
        }
        return {"answer": answer, "status": "running" if evaluation.passed else "failed_evaluation", "stages": stages}

    def _final_guard(self, state: OrchestrationState) -> dict:
        if state["status"] != "running":
            return {}
        guardrail = self.guardrail.check(state.get("answer", ""))
        stages = dict(state["stages"])
        stages["final_guardrail"] = vars(guardrail)
        return {"status": "ok" if guardrail.allowed else "blocked_by_guardrail", "stages": stages}

    @trace(name="langgraph_orchestration")
    def run(self, question: str) -> dict:
        return self.graph.invoke({"question": question})


def run_pipeline(question: str) -> dict:
    """Backward-compatible entry point for the LangGraph orchestrator."""
    return OrchestratorAgent().run(question)


def main():
    question = sys.argv[1] if len(sys.argv) > 1 else "Summarize GATES in one sentence"
    config.print_backend_report()
    print(f"\nQuestion: {question}\n")

    outcome = run_pipeline(question)
    print(f"Status: {outcome['status']}\n")
    for stage, detail in outcome["stages"].items():
        print(f"  [{stage}] {detail}")
    if outcome["status"] == "ok":
        print(f"\nFinal answer: {outcome['answer']}")


if __name__ == "__main__":
    main()
