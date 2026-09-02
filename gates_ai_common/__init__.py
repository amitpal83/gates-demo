"""
gates_ai_common
------------------
Enterprise-shared capability library for GATES AI agents.

Any agent -- SQL agent, RAG agent, PDRA agent, or a future one --
imports from here instead of re-implementing these cross-cutting
concerns per project:

    from gates_ai_common.input_validation import InputValidator
    from gates_ai_common.prompt_library    import PromptLibrary
    from gates_ai_common.llm_client        import LLMClient
    from gates_ai_common.evaluation        import ResponseEvaluator
    from gates_ai_common.guardrails        import SecurityGuardrail
    from gates_ai_common.observability     import trace, log_usage

Each module tries a real backend first (llm-guard, langfuse, deepeval,
nemoguardrails, openai) and falls back to a small local implementation
when that backend isn't installed / configured, so the same code runs
in a laptop demo and in the production stack.
"""
