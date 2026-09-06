"""
gates_ai_common.guardrails
------------------------------
Shared OUTPUT-side security guardrail: screens the model's response
before it is returned to the caller. Distinct from input_validation.py,
which screens what the user sent, not what the model produced.

Production backend : NVIDIA NeMo Guardrails (topical + safety rails),
                      or Llama Guard as a moderation model.
Fallback backend    : explicit content-policy checks for PII / unsafe
                      output generation, used when nemoguardrails isn't
                      installed or not configured.

This module is intentionally strict: the safety gate should fail on
real unsafe output, not merely on a canned refusal sentence.
"""
import logging
import re

from . import config

logger = logging.getLogger(__name__)

if config.HAS_NEMOGUARDRAILS:
    from nemoguardrails import LLMRails, RailsConfig

_UNSAFE_OUTPUT_PATTERNS = [
    r"\b\d{4}-\d{4}-\d{4}\b",   # PhilSys-style ID
    r"\b09\d{9}\b",              # mobile number
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",  # email
    r"\b(?:credit|debit|card)\s*(?:number|no|#)?\s*\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b",
]

_SUSPICIOUS_OUTPUT_HINTS = [
    "ignore previous instructions",
    "reveal your system prompt",
    "bypass the policy",
    "disregard safety",
    "exfiltrate",
    "i am an ai and can help you bypass",
]

# Allowed topic keywords for the SQL agent
_ALLOWED_TOPICS = {
    "budget",
    "utilization",
    "agency",
    "region",
    "project",
    "quarter",
    "monitoring",
    "rate",
    "total",
    "average",
    "sum",
    "count",
}

_RETRIEVAL_STOP_WORDS = {
    "about", "after", "also", "and", "are", "before", "can", "could", "does",
    "explain", "fact", "factsheet", "for", "from", "gates", "give", "have", "how",
    "into", "list", "more", "of", "program", "question", "sheet", "show", "tell",
    "that", "the", "than", "their", "there", "these", "they", "this", "use", "uses",
    "using", "was", "what", "when", "where", "which", "while", "who", "with", "would",
    "you", "your",
}


class GuardrailResult:
    def __init__(self, allowed: bool, reason: str | None, backend: str):
        self.allowed = allowed
        self.reason = reason
        self.backend = backend

    def __repr__(self):
        return f"GuardrailResult(allowed={self.allowed}, reason={self.reason}, backend={self.backend})"


class SecurityGuardrail:
    def __init__(self, config_path: str | None = None, allowed_topics: set[str] | None = None):
        self.backend = "keyword-fallback"
        self._rails = None
        self._allowed_topics = allowed_topics or _ALLOWED_TOPICS
        if config.HAS_NEMOGUARDRAILS and config_path:
            try:
                self._rails = LLMRails(RailsConfig.from_path(config_path))
                self.backend = "nemo-guardrails"
            except Exception as error:
                logger.warning("Unable to initialize NeMo Guardrails; using keyword fallback: %s", error)
                self.backend = "keyword-fallback"
        elif config.HAS_NEMOGUARDRAILS:
            logger.warning("NeMo Guardrails is installed but no configuration was supplied; using keyword fallback.")
            self.backend = "keyword-fallback"

    def check_topic_relevance(self, question: str) -> GuardrailResult:
        """Check if the question is on-topic for the SQL agent domain."""
        if self.backend == "nemo-guardrails" and self._rails is not None:
            return self._check_topic_relevance_live(question)

        return self._check_topic_relevance_fallback(question)

    def check_retrieval_relevance(self, question: str, context: list[str]) -> GuardrailResult:
        """Reject questions that cannot be answered from the indexed source."""
        def meaningful_terms(text: str) -> set[str]:
            words = re.findall(r"[a-z]{3,}", text.lower())
            return {
                word[:-1] if word.endswith("s") and len(word) > 3 else word
                for word in words
                if word not in _RETRIEVAL_STOP_WORDS
            }

        question_terms = meaningful_terms(question)
        context_terms = meaningful_terms(" ".join(context))
        matched_terms = question_terms & context_terms

        if matched_terms:
            return GuardrailResult(True, None, "retrieval-relevance-check")
        return GuardrailResult(
            False,
            "question_not_supported_by_indexed_context",
            "retrieval-relevance-check",
        )

    def _check_topic_relevance_live(self, question: str) -> GuardrailResult:
        fallback_result = self._check_topic_relevance_fallback(question)
        if not fallback_result.allowed:
            return GuardrailResult(
                False,
                "off_topic_question",
                "nemo-guardrails-input-topic",
            )

        try:
            result = self._rails.generate(
                messages=[{"role": "user", "content": question}]
            )
        except Exception:
            return fallback_result

        if "TOPIC_ALLOWED" in str(result).upper():
            return GuardrailResult(True, None, "nemo-guardrails")
        return GuardrailResult(True, None, "nemo-guardrails+topic-fallback")

    def _check_topic_relevance_fallback(self, question: str) -> GuardrailResult:
        question_lower = question.lower()
        question_words = set(re.findall(r"\b\w+\b", question_lower))
        matching_topics = question_words & self._allowed_topics

        if matching_topics:
            return GuardrailResult(True, None, "topic-check")

        return GuardrailResult(
            False,
            "off_topic_question",
            "topic-check"
        )

    def check(self, response_text: str) -> GuardrailResult:
        if self.backend == "nemo-guardrails" and self._rails is not None:
            return self._check_live(response_text)
        return self._check_fallback(response_text)

    # -- production path (requires: pip install nemoguardrails + a
    #    rails config directory with config.yml / flows.co) -------------
    def _check_live(self, response_text: str) -> GuardrailResult:
        try:
            result = self._rails.generate(
                messages=[{"role": "assistant", "content": response_text}]
            )
            result_text = str(result).lower()
        except Exception:
            return self._check_fallback(response_text)

        blocked = (
            any(hint in result_text for hint in ("i can't", "cannot help", "not allowed", "unsafe"))
            or self._check_fallback(response_text).allowed is False
        )
        return GuardrailResult(not blocked, "rail_triggered" if blocked else None, "nemo-guardrails")

    # -- offline fallback path -------------------------------------------
    def _check_fallback(self, response_text: str) -> GuardrailResult:
        lower = response_text.lower()
        for pattern in _UNSAFE_OUTPUT_PATTERNS:
            if re.search(pattern, response_text, re.IGNORECASE):
                return GuardrailResult(False, "pii_or_sensitive_output_detected", "keyword-fallback")
        for hint in _SUSPICIOUS_OUTPUT_HINTS:
            if hint in lower:
                return GuardrailResult(False, "unsafe_output_pattern_detected", "keyword-fallback")
        return GuardrailResult(True, None, "keyword-fallback")
