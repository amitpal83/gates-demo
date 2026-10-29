"""Prompt templates as plain constants (no prompt library); swap for a managed prompt store later if wanted."""
from __future__ import annotations

from ontology_graph.ontology import schema

_EXTRACTION_SYSTEM = """You extract a knowledge graph from an insurance plan brochure. Use ONLY the classes, relations and data properties below; ignore anything that does not fit.

__SCHEMA__

Return a JSON object: {"entities": [{"id": "snake_case_id", "class": "<Class>", "label": "<name as written>", "props": {"<dataProperty>": <value>}}], "relations": [{"s": "<entity id>", "p": "<relation>", "o": "<entity id>"}]}

Rules:
- ids are lowercase snake_case and stable (for example "nivesh_plus", "balanced_fund", "mortality_charge"); reuse an id from the known list rather than inventing a second one for the same thing.
- one entity per distinct thing: one per fund, per charge (separate entities when the rate depends on a condition, such as offline versus online allocation charge), per guaranteed-addition row, per withdrawal band, per sum assured option.
- numeric props are plain numbers (3.3, not "3.30%"); put the unit in "unit" and any condition in "condition".
- the plan itself is a Plan entity with its "uin"; link it to everything it offers or charges with the relations above.
- include only facts stated in the passages; never guess or use outside knowledge.
- every relation must reference ids that exist in this response or in the known list."""

EXTRACTION_USER = "Known entity ids so far: {known_ids}\n\nPassages:\n{passages}"

ANSWER_SYSTEM = """You answer questions about ONE customer's life-insurance policy using only the material provided: that customer's policy record, structured facts from the plan ontology, and numbered passages from the plan brochure.

Rules:
- Ground every statement in the material; if the answer is not there, say so plainly rather than guessing.
- Combine the customer's own details (dates, option, fund, premium) with the plan rules. Work out dates and amounts explicitly when the question needs it, using today's date: {today}.
- Cite sources inline as [record], [ontology] or [1], [2] for the numbered passages.
- Never mention or infer anything about other customers.
- Be concise and use rupee amounts as written in the sources."""

ANSWER_USER = """POLICY RECORD:
{record}

ONTOLOGY FACTS:
{facts}

BROCHURE PASSAGES:
{passages}

QUESTION: {question}"""


def extraction_system() -> str:
    return _EXTRACTION_SYSTEM.replace("__SCHEMA__", schema.prompt_description())
