"""
gates_ai_common.evaluation
------------------------------
Shared response-quality gate, run after every generation.

Production backend : DeepEval (FaithfulnessMetric, AnswerRelevancyMetric,
                      HallucinationMetric).
Fallback backend    : a lightweight grounding heuristic (word-overlap
                      against the supplied context), used when
                      deepeval / its judge model isn't available -- so
                      the evaluation *gate* is still real and can still
                      fail a bad answer, even offline.

This module intentionally uses a very small evaluation record so the
business logic stays easy to explain in demos. The full DeepEval class
is much more general than this project needs, but we still convert to it
when the live backend is used.
"""
from dataclasses import dataclass
from typing import Optional
from . import config
import re

if config.HAS_DEEPEVAL:
    from deepeval.metrics import FaithfulnessMetric, AnswerRelevancyMetric, HallucinationMetric
    from deepeval.test_case import LLMTestCase


@dataclass
class MinimalLLMTestCase:
    """A stripped-down, demo-friendly version of DeepEval's LLMTestCase.

    This keeps only the fields this SQL workflow actually needs:
    - the user input
    - the generated SQL/output
    - the grounding context
    - the retrieval context

    The full DeepEval class supports more features like MCP, tools, multimodal
    inputs, metrics metadata, and dataset metadata, but they are not needed here.
    """
    input: str
    actual_output: str
    context: list[str]
    retrieval_context: Optional[list[str]] = None

    def to_deepeval_case(self):
        if not config.HAS_DEEPEVAL:
            raise RuntimeError("DeepEval is not available")
        retrieval = self.retrieval_context if self.retrieval_context is not None else self.context
        return LLMTestCase(
            input=self.input,
            actual_output=self.actual_output,
            context=self.context,
            retrieval_context=retrieval,
        )


class EvaluationResult:
    def __init__(self, score: float, passed: bool, backend: str, details: dict):
        self.score = score
        self.passed = passed
        self.backend = backend
        self.details = details

    def __repr__(self):
        return f"EvaluationResult(score={self.score:.2f}, passed={self.passed}, backend={self.backend})"


class ResponseEvaluator:
    def __init__(self, threshold: float = 0.6):
        self.threshold = threshold
        self.backend = "deepeval" if config.HAS_DEEPEVAL else "heuristic-fallback"

    def build_case(self, query: str, answer: str, context: list[str]) -> MinimalLLMTestCase:
        return MinimalLLMTestCase(
            input=query,
            actual_output=answer,
            context=context,
            retrieval_context=context,
        )

    def evaluate(self, query: str, answer: str, context: list[str]) -> EvaluationResult:
        case = self.build_case(query, answer, context)
        return self.evaluate_case(case)

    def evaluate_case(self, case: MinimalLLMTestCase) -> EvaluationResult:
        if self.backend == "deepeval":
            return self._evaluate_live_case(case)
        return self._evaluate_fallback_case(case)

    # -- production path (requires: pip install deepeval) ----------------
    def _evaluate_live_case(self, case: MinimalLLMTestCase):
        deepeval_case = case.to_deepeval_case()
        faithfulness = FaithfulnessMetric(threshold=self.threshold)
        relevancy = AnswerRelevancyMetric(threshold=self.threshold)
        hallucination = HallucinationMetric(threshold=self.threshold)
        for metric in (faithfulness, relevancy, hallucination):
            metric.measure(deepeval_case)
        score = min(faithfulness.score, relevancy.score, hallucination.score)
        return EvaluationResult(
            score, score >= self.threshold, "deepeval",
            {"faithfulness": faithfulness.score, "relevancy": relevancy.score,
             "hallucination": hallucination.score},
        )

    # -- offline fallback path -------------------------------------------
    def _evaluate_fallback_case(self, case: MinimalLLMTestCase):
        context = case.context or []
        answer = case.actual_output
        if not context:
            score = 1.0 if answer and "error" not in answer.lower() else 0.0
            return EvaluationResult(score, score >= self.threshold, "heuristic-fallback",
                                     {"note": "no retrieval context supplied"})
        context_text = " ".join(context).lower()
        answer_words = set(re.findall(r"[a-z_]{5,}", answer.lower()))
        if not answer_words:
            score = 0.0
        else:
            grounded = sum(1 for w in answer_words if w in context_text)
            score = grounded / len(answer_words)
        return EvaluationResult(score, score >= self.threshold, "heuristic-fallback",
                                 {"grounded_word_ratio": round(score, 2)})
