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
import re

from . import config

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
    "highest",
    "lowest",
    "top",
    "bottom",
}


class GuardrailResult:
    def __init__(self, allowed: bool, reason: str | None, backend: str):
        self.allowed = allowed
        self.reason = reason
        self.backend = backend

    def __repr__(self):
        return f"GuardrailResult(allowed={self.allowed}, reason={self.reason}, backend={self.backend})"


class SecurityGuardrail:
    def __init__(self, config_path: str | None = None):
        self.backend = "keyword-fallback"
        self._rails = None
        if config.HAS_NEMOGUARDRAILS and config_path:
            try:
                self._rails = LLMRails(RailsConfig.from_path(config_path))
                self.backend = "nemo-guardrails"
            except Exception:
                self.backend = "keyword-fallback"
        elif config.HAS_NEMOGUARDRAILS:
            # Keep the fallback active unless a valid config directory is supplied.
            # The SQL agent passes a concrete Rails config path, so the live path can be used.
            self.backend = "keyword-fallback"

    def check_topic_relevance(self, question: str) -> GuardrailResult:
        """Check if the question is on-topic for the SQL agent domain."""
        question_lower = question.lower()
        question_words = set(re.findall(r"\b\w+\b", question_lower))
        
        # Check if any allowed topic keywords are present
        matching_topics = question_words & _ALLOWED_TOPICS
        
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
