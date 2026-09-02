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
import sys

from gates_ai_common import config
from gates_ai_common.input_validation import InputValidator
from gates_ai_common.prompt_library import PromptLibrary
from gates_ai_common.llm_client import LLMClient
from gates_ai_common.evaluation import ResponseEvaluator
from gates_ai_common.guardrails import SecurityGuardrail
from gates_ai_common.observability import trace, log_usage

MAX_RETRIES = 2


def route(question: str) -> str:
    """Decides simple (LangChain) vs multi-agent (LangGraph) orchestration.

    Production: this would be an LLM-based or rule-based classifier
    node. Demo heuristic: more than one clause/sub-ask -> multi-agent.
    """
    sub_asks = question.count(" and ") + question.count(";")
    return "multi_agent" if sub_asks >= 1 else "simple"


def mock_answer(system: str, user: str) -> str:
    return f"Summary based on: {user.split('Question:')[-1].strip()[:80]}"


@trace(name="simple_orchestration")
def run_simple(question: str, prompts: PromptLibrary, llm: LLMClient) -> tuple[str, dict]:
    """LangChain-style single chain: one prompt, one LLM call."""
    system = prompts.get("orchestration_agent.system")
    answer, usage = llm.complete(system, f"Question: {question}")
    return answer, usage


@trace(name="multi_agent_orchestration")
def run_multi_agent(question: str, prompts: PromptLibrary, llm: LLMClient) -> tuple[str, dict]:
    """LangGraph-style multi-step orchestration: split into sub-asks,
    answer each, then synthesize. A real implementation would use
    langgraph.graph.StateGraph with one node per step; this demo
    inlines the same three steps as plain function calls so it runs
    without the langgraph package installed.
    """
    system = prompts.get("orchestration_agent.system")
    sub_asks = [s.strip() for s in question.replace(";", " and ").split(" and ") if s.strip()]

    total_usage = {"input_tokens": 0, "output_tokens": 0}
    partial_answers = []
    for sub_ask in sub_asks:
        partial, usage = llm.complete(system, f"Question: {sub_ask}")
        partial_answers.append(partial)
        total_usage["input_tokens"] += usage["input_tokens"]
        total_usage["output_tokens"] += usage["output_tokens"]

    synthesis_prompt = "Combine these into one coherent answer: " + " | ".join(partial_answers)
    final_answer, usage = llm.complete(system, synthesis_prompt)
    total_usage["input_tokens"] += usage["input_tokens"]
    total_usage["output_tokens"] += usage["output_tokens"]
    return final_answer, total_usage


def run_pipeline(question: str) -> dict:
    validator = InputValidator()
    prompts = PromptLibrary()
    llm = LLMClient(model="gpt-4o-mini", mock_fn=mock_answer)
    evaluator = ResponseEvaluator(threshold=0.0)  # no retrieval context in this flow -> neutral pass/fail
    guardrail = SecurityGuardrail()

    stages = {}

    # 1/2. Router chooses LangChain vs LangGraph path
    path = route(question)
    stages["orchestration_path"] = path

    # 3. Input validation
    validation = validator.validate(question)
    stages["input_validation"] = vars(validation)
    if not validation.is_safe:
        return {"status": "blocked_at_input_validation", "stages": stages}

    # 4-5. Prompt library + LLM call, with an evaluation retry loop
    attempt = 0
    while True:
        attempt += 1
        if path == "simple":
            answer, usage = run_simple(question, prompts, llm)
        else:
            answer, usage = run_multi_agent(question, prompts, llm)

        # 6. Evaluation
        eval_result = evaluator.evaluate(question, answer, context=[])
        stages[f"evaluation_attempt_{attempt}"] = eval_result.__dict__
        if eval_result.passed or attempt >= MAX_RETRIES:
            break

    if not eval_result.passed:
        return {"status": "failed_evaluation_after_retries", "stages": stages}

    # 7. Security guardrail
    guard_result = guardrail.check(answer)
    stages["guardrail"] = vars(guard_result)
    if not guard_result.allowed:
        return {"status": "blocked_by_guardrail", "stages": stages}

    # 8. Observability -- tokens & cost / pricing & cost
    usage_record = log_usage(agent_path=f"orchestration:{path}", input_tokens=usage["input_tokens"],
                              output_tokens=usage["output_tokens"], model=llm.model)
    stages["usage"] = usage_record

    return {"status": "ok", "answer": answer, "stages": stages}


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
