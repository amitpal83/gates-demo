"""
gates_ai_common.llm_client
-----------------------------
Shared LLM call wrapper.

Production backend : OpenAI chat completions (swap the base_url to
                      route through LiteLLM for other model providers
                      without changing this interface).
Fallback backend    : a deterministic stub, injected by the caller,
                      so the surrounding pipeline (validation, prompt
                      library, evaluation, guardrails, observability)
                      can be demonstrated end-to-end without a key.
"""
from . import config

if config.USE_LIVE_LLM:
    from openai import OpenAI


class LLMClient:
    def __init__(self, model: str = "gpt-4o-mini", mock_fn=None):
        self.model = model
        self.backend = "openai" if config.USE_LIVE_LLM else "mock"
        self._mock_fn = mock_fn or (lambda system, user: f"[mock response to: {user[:60]}...]")
        if self.backend == "openai":
            self._client = OpenAI(timeout=config.LLM_REQUEST_TIMEOUT_SECONDS, max_retries=2)

    def complete(self, system: str, user: str) -> tuple[str, dict]:
        """Returns (text, usage) where usage has input/output token counts."""
        if self.backend == "openai":
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            )
            usage = {
                "input_tokens": resp.usage.prompt_tokens,
                "output_tokens": resp.usage.completion_tokens,
            }
            return resp.choices[0].message.content, usage

        text = self._mock_fn(system, user)
        # Deterministic pseudo-token-count so the observability step has
        # something real to log even in mock mode.
        usage = {
            "input_tokens": max(1, len((system + user).split())),
            "output_tokens": max(1, len(text.split())),
        }
        return text, usage
