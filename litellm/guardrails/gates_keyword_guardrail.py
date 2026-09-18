"""Custom LiteLLM Proxy guardrail reusing gates_ai_common's regex patterns, mounted read-only into the proxy and registered in litellm/config.yaml -- see litellm/README.md if a hook silently doesn't fire."""
import re

from litellm.integrations.custom_guardrail import CustomGuardrail
from litellm.proxy._types import UserAPIKeyAuth

try:
    from gates_ai_common.input_validation import _INJECTION_PATTERNS, _PII_PATTERNS
    from gates_ai_common.guardrails import _UNSAFE_OUTPUT_PATTERNS, _SUSPICIOUS_OUTPUT_HINTS
except ImportError:
    # Fail safe to "no extra blocking" rather than crashing the proxy if gates_ai_common wasn't mounted correctly.
    _INJECTION_PATTERNS, _PII_PATTERNS = [], {}
    _UNSAFE_OUTPUT_PATTERNS, _SUSPICIOUS_OUTPUT_HINTS = [], []


class GatesKeywordGuardrail(CustomGuardrail):
    """Blocks prompt injection / PII on the way in, and unsafe-output patterns on the way out."""

    async def async_pre_call_hook(self, user_api_key_dict: UserAPIKeyAuth, cache, data: dict, call_type: str):
        messages = data.get("messages", [])
        text = " ".join(
            m.get("content", "") for m in messages if isinstance(m.get("content"), str)
        )

        for pattern in _INJECTION_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                raise ValueError(f"Blocked by gates-keyword-guardrail: prompt_injection ({pattern})")

        for label, pattern in _PII_PATTERNS.items():
            if re.search(pattern, text):
                raise ValueError(f"Blocked by gates-keyword-guardrail: pii_detected:{label}")

        return data

    async def async_post_call_success_hook(self, data: dict, user_api_key_dict: UserAPIKeyAuth, response):
        try:
            text = response.choices[0].message.content or ""
        except Exception:
            return response

        lower = text.lower()
        for pattern in _UNSAFE_OUTPUT_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                raise ValueError(f"Blocked by gates-keyword-guardrail: unsafe_output ({pattern})")
        for hint in _SUSPICIOUS_OUTPUT_HINTS:
            if hint in lower:
                raise ValueError(f"Blocked by gates-keyword-guardrail: suspicious_output ({hint})")

        return response
