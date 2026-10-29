"""Extension points for guardrails (e.g. Portkey); every hook currently allows everything, replace the bodies later."""
from dataclasses import dataclass


@dataclass
class HookResult:
    allowed: bool = True
    reason: str = ""


def check_document(text: str) -> HookResult:
    """Called with the full parsed document before ontology build and embedding."""
    return HookResult()


def check_question(text: str) -> HookResult:
    """Called with the user's question before any retrieval."""
    return HookResult()


def check_answer(text: str, context: str = "") -> HookResult:
    """Called with the generated answer (and the context it was built from) before it is returned."""
    return HookResult()
