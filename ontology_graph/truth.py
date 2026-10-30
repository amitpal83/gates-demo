"""Ground truth for the demo, computed from the policy row and the brochure facts below, independently of both agents; used to mark each agent's answer correct, wrong or unanswered per field."""
from __future__ import annotations

import calendar
import datetime

from ontology_graph.ontology import schema

# What each stored mode_code really means, per the Protection Plus brochure (premium modes on page 11, grace period on page 11) plus the demo's own code mapping in schema.MODE_CODE_BY_PER_YEAR.
MODE_FACTS: dict[int, dict] = {
    1: {"label": "Yearly", "per_year": 1, "grace_days": 30},
    6: {"label": "Half-yearly", "per_year": 2, "grace_days": 30},
    3: {"label": "Quarterly", "per_year": 4, "grace_days": 30},
    12: {"label": "Monthly (NACH only)", "per_year": 12, "grace_days": 15},
}

assert {facts["per_year"]: code for code, facts in MODE_FACTS.items()} == schema.MODE_CODE_BY_PER_YEAR

FIELDS = (
    "payments_per_year",
    "installment_amount_inr",
    "total_premium_over_paying_term_inr",
    "next_due_date",
    "grace_period_days",
)


def add_months(day: datetime.date, months: int) -> datetime.date:
    carry, month_index = divmod(day.month - 1 + months, 12)
    year, month = day.year + carry, month_index + 1
    return datetime.date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def ground_truth(record: dict) -> dict:
    facts = MODE_FACTS[int(record["mode_code"])]
    last_paid = datetime.date.fromisoformat(str(record["last_paid_date"]))
    return {
        "payments_per_year": facts["per_year"],
        "installment_amount_inr": float(record["installment_premium"]),
        "total_premium_over_paying_term_inr": float(record["installment_premium"]) * facts["per_year"] * int(record["premium_paying_term_years"]),
        "next_due_date": add_months(last_paid, 12 // facts["per_year"]).isoformat(),
        "grace_period_days": facts["grace_days"],
        "mode_label": facts["label"],
    }


def _matches(field: str, truth_value, answer_value) -> bool:
    if field == "next_due_date":
        return str(answer_value).strip() == str(truth_value)
    try:
        return abs(float(answer_value) - float(truth_value)) <= 0.5
    except (TypeError, ValueError):
        return False


def check_answer(truth: dict, answer: dict) -> dict:
    """Per field: correct, wrong, or unanswered (null). 'unanswered' is not counted as a hallucination."""
    checks = {}
    for field in FIELDS:
        given = answer.get(field)
        if given is None or given == "":
            verdict = "unanswered"
        else:
            verdict = "correct" if _matches(field, truth[field], given) else "wrong"
        checks[field] = {"truth": truth[field], "answer": given, "verdict": verdict}
    return checks


def summarize(checks: dict) -> dict:
    counts = {"correct": 0, "wrong": 0, "unanswered": 0}
    for check in checks.values():
        counts[check["verdict"]] += 1
    return counts
