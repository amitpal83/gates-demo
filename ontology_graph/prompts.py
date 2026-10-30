"""Prompt templates as plain constants (no prompt library). The two answer prompts are identical except for the ontology block, so the only variable in the demo is whether the ontology is available."""
from __future__ import annotations

from ontology_graph.ontology import schema

_EXTRACTION_SYSTEM = """You extract a very small knowledge graph from a life-insurance plan brochure. Use ONLY the classes, relations and data properties below.

__SCHEMA__

Return a JSON object: {"entities": [{"id": "snake_case_id", "class": "<Class>", "label": "<name as written>", "props": {"<dataProperty>": <value>}}], "relations": [{"s": "<entity id>", "p": "<relation>", "o": "<entity id>"}]}

What to extract:
- one Insurer (id "lic" for Life Insurance Corporation of India).
- one Plan: its name, uin, planNumber, the allowed premium paying terms and policy terms (as text lists such as "5, 7, 10, 15"), and lockInYears (the years before partial withdrawal or surrender is allowed).
- one PremiumMode for EACH way the brochure says premium can be paid (for example yearly, half-yearly, quarterly, monthly): installmentsPerYear, intervalMonths, graceDays (the grace period for that mode, in days), and the minimum installment in rupees (minInstallmentInr for premium paying terms of 5, 7 and 10 years; minInstallmentInrPpt15 for 15 years). Put anything special about the mode, such as "NACH only", in "description".
- one Benefit: the Death Benefit, with payoutMode (how it can be paid), minPctOfPremiumsPaid (the percentage-of-premiums-paid floor) and a one-line description of the amounts it is the highest of.
- ids are lowercase snake_case: the plan from its name, modes as "yearly", "half_yearly", "quarterly", "monthly", the benefit as "death_benefit".

Rules:
- numeric props are plain numbers (60000, not "Rs 60,000"); do NOT output modeCode, and do not output grace-period or lock-in entities (they are built from graceDays and lockInYears).
- include only facts stated in the passages; never guess or use outside knowledge; omit a prop you cannot find.
- ignore everything else in the brochure (funds, charges, maturity benefit, riders, top-up, withdrawals, switching).
- reuse an id from the known list rather than inventing a second one for the same thing."""

EXTRACTION_USER = "Known entity ids so far: {known_ids}\n\nPassages:\n{passages}"

# Both agents get the same instructions and the same record; Agent A additionally gets the ontology block.
ANSWER_SYSTEM = """You answer questions about ONE customer's life-insurance policy using only the information provided below.

Return a JSON object with exactly these keys:
{{"payments_per_year": <integer or null>, "installment_amount_inr": <number or null>, "total_premium_over_paying_term_inr": <number or null>, "next_due_date": "<YYYY-MM-DD or null>", "grace_period_days": <integer or null>, "answer": "<one or two sentences answering the question, with the working>"}}

Rules:
- Use only the information provided; do not use outside knowledge about the plan. If a value cannot be determined from it, use null for that key and say what is missing in "answer".
- Today's date is {today}.
- Never mention other customers."""

ANSWER_USER_RECORD = """POLICY RECORD (from the customer database):
{record}

COLUMN DESCRIPTIONS (data dictionary of the database):
{notes}
"""

ANSWER_USER_ONTOLOGY = """
PLAN ONTOLOGY FACTS (authoritative; where they differ from the column descriptions, they win):
{facts}
"""

ANSWER_USER_QUESTION = "\nQUESTION: {question}"


def extraction_system() -> str:
    return _EXTRACTION_SYSTEM.replace("__SCHEMA__", schema.prompt_description())
