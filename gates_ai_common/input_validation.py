"""
gates_ai_common.input_validation
----------------------------------
Shared INPUT-side validation gate: screens the raw user prompt before
it reaches any orchestration logic.

Production backend : llm-guard (https://github.com/protectai/llm-guard)
                      PromptInjection + Anonymize scanners.
Fallback backend    : regex-based injection / PII screen, used when
                      llm-guard is not installed.

Every agent calls InputValidator().validate(prompt) -- nobody
re-implements this per project.
"""
from dataclasses import dataclass
import re

from . import config

if config.HAS_LLM_GUARD:
    from llm_guard.input_scanners import PromptInjection, Anonymize
    from llm_guard.vault import Vault

_INJECTION_PATTERNS = [
    r"ignore (all )?previous instructions",
    r"disregard (the )?system prompt",
    r"you are now",
    r"reveal your (system|instructions)",
]

_PII_PATTERNS = {
    "philsys_id": r"\b\d{4}-\d{4}-\d{4}\b",
    "mobile_number": r"\b09\d{9}\b",
    "email": r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b",
}


@dataclass
class ValidationResult:
    is_safe: bool
    reason: str | None = None
    backend: str = "regex-fallback"


class InputValidator:
    """Shared input-validation gate used by every agent in the platform."""

    def __init__(self):
        if config.HAS_LLM_GUARD:
            self._vault = Vault()
            self._injection_scanner = PromptInjection()
            self._anonymize_scanner = Anonymize(self._vault)
            self.backend = "llm-guard"
        else:
            self.backend = "regex-fallback"

    def validate(self, prompt: str) -> ValidationResult:
        if self.backend == "llm-guard":
            return self._validate_live(prompt)
        return self._validate_fallback(prompt)

    # -- production path (requires: pip install llm-guard) --------------
    def _validate_live(self, prompt: str) -> ValidationResult:
        sanitized, is_valid, risk_score = self._injection_scanner.scan(prompt)
        if not is_valid:
            return ValidationResult(False, f"prompt_injection (risk={risk_score:.2f})", "llm-guard")
        sanitized, is_valid, risk_score = self._anonymize_scanner.scan(sanitized)
        if not is_valid:
            return ValidationResult(False, f"pii_detected (risk={risk_score:.2f})", "llm-guard")
        return ValidationResult(True, backend="llm-guard")

    # -- offline fallback path (no extra dependencies) -------------------
    def _validate_fallback(self, prompt: str) -> ValidationResult:
        for pattern in _INJECTION_PATTERNS:
            if re.search(pattern, prompt, re.IGNORECASE):
                return ValidationResult(False, "prompt_injection", "regex-fallback")
        for label, pattern in _PII_PATTERNS.items():
            if re.search(pattern, prompt):
                return ValidationResult(False, f"pii_detected:{label}", "regex-fallback")
        return ValidationResult(True, backend="regex-fallback")
