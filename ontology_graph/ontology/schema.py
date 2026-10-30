"""Compact ontology schema (TBox) for the Protection Plus demo: 6 classes, so the plan graph stays at 10 nodes (1 Insurer, 1 Plan, 4 PremiumMode, 2 GracePeriod, 1 LockInPeriod, 1 Benefit). Generates the Turtle loaded into GraphDB and the allow-lists and prompt text used to validate LLM extraction. Run `python -m ontology_graph.ontology.schema` to print the Turtle."""
from __future__ import annotations

LIC_NS = "https://gates.example.org/lic#"
DATA_NS = "https://gates.example.org/lic/id/"
SCHEMA_GRAPH = "https://gates.example.org/lic/graph/schema"

# name -> (parent class or None, description)
CLASSES: dict[str, tuple[str | None, str]] = {
    "Insurer": (None, "Company that issues the plan, e.g. Life Insurance Corporation of India"),
    "Plan": (None, "Insurance plan (product), identified by its UIN"),
    "PremiumMode": (None, "How often the policyholder pays the premium (yearly, half-yearly, quarterly, monthly); installments per year differ by mode"),
    "GracePeriod": (None, "Days allowed to pay an unpaid premium installment after its due date"),
    "LockInPeriod": (None, "Years from commencement during which funds cannot be withdrawn or the policy surrendered"),
    "Benefit": (None, "Amount the plan pays out, e.g. the death benefit"),
}

# Created in code from numbers the LLM extracts on other entities (see facts.link_structure); the LLM is not asked for these.
DERIVED_CLASSES = {"GracePeriod", "LockInPeriod"}

# At most this many entities of a class are kept, so the graph stays small enough to draw (1+1+4+2+1+1 = 10 nodes).
CLASS_CAPS: dict[str, int] = {"Insurer": 1, "Plan": 1, "PremiumMode": 4, "GracePeriod": 2, "LockInPeriod": 1, "Benefit": 1}

# name -> (domain class or None, range class or None, description)
OBJECT_PROPERTIES: dict[str, tuple[str | None, str | None, str]] = {
    "issuedBy": ("Plan", "Insurer", "Insurer that issues the plan"),
    "acceptsMode": ("Plan", "PremiumMode", "Premium mode the plan allows"),
    "hasGracePeriod": ("PremiumMode", "GracePeriod", "Grace period that applies to premiums paid in this mode"),
    "hasLockIn": ("Plan", "LockInPeriod", "Lock-in period of the plan"),
    "hasBenefit": ("Plan", "Benefit", "Benefit payable under the plan"),
}

# name -> (xsd type: string | decimal | integer, description)
DATA_PROPERTIES: dict[str, tuple[str, str]] = {
    "description": ("string", "Short free-text summary of the entity"),
    "uin": ("string", "Unique Identification Number of the plan"),
    "planNumber": ("integer", "LIC plan number"),
    "premiumPayingTermsYears": ("string", "Allowed premium paying terms in years, e.g. '5, 7, 10, 15'"),
    "policyTermsYears": ("string", "Allowed policy terms in years, e.g. '10, 15, 20, 25'"),
    "lockInYears": ("integer", "Extraction input on the plan; becomes the LockInPeriod node"),
    "modeCode": ("integer", "Code the policy database stores for this mode (assigned by the demo, not printed in the brochure)"),
    "installmentsPerYear": ("integer", "Number of premium installments paid in one policy year under this mode"),
    "intervalMonths": ("integer", "Months between two installments under this mode"),
    "graceDays": ("integer", "Extraction input on a mode; becomes a GracePeriod node"),
    "minInstallmentInr": ("decimal", "Minimum installment in rupees for premium paying terms of 5, 7 and 10 years"),
    "minInstallmentInrPpt15": ("decimal", "Minimum installment in rupees for a premium paying term of 15 years"),
    "days": ("integer", "Length of a grace period in days"),
    "durationYears": ("decimal", "Length of a lock-in period in years"),
    "payoutMode": ("string", "How a benefit is paid, e.g. lump sum or in instalments"),
    "minPctOfPremiumsPaid": ("decimal", "A payout floor expressed as a percentage of the total premiums paid"),
}

# Demo mapping of installments-per-year -> the code stored in customer_policy.mode_code. The codes are our own convention (they are not in the brochure) and deliberately not "installments per year" for half-yearly and quarterly.
MODE_CODE_BY_PER_YEAR: dict[int, int] = {1: 1, 2: 6, 4: 3, 12: 12}


def is_a(cls: str, ancestor: str) -> bool:
    """True if `cls` is `ancestor` or a descendant of it."""
    while cls is not None:
        if cls == ancestor:
            return True
        cls = CLASSES.get(cls, (None, ""))[0]
    return False


def _lit(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return f'"{escaped}"'


def to_turtle() -> str:
    lines = [
        f"@prefix lic: <{LIC_NS}> .",
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        "",
        f"<{LIC_NS.rstrip('#')}> a owl:Ontology ; rdfs:label \"LIC Protection Plus demo ontology\" .",
        "",
    ]
    for name, (parent, comment) in CLASSES.items():
        parent_clause = f" ;\n    rdfs:subClassOf lic:{parent}" if parent else ""
        lines.append(f"lic:{name} a owl:Class ;\n    rdfs:label {_lit(name)} ;\n    rdfs:comment {_lit(comment)}{parent_clause} .")
    lines.append("")
    for name, (domain, rng, comment) in OBJECT_PROPERTIES.items():
        extra = ""
        if domain:
            extra += f" ;\n    rdfs:domain lic:{domain}"
        if rng:
            extra += f" ;\n    rdfs:range lic:{rng}"
        lines.append(f"lic:{name} a owl:ObjectProperty ;\n    rdfs:label {_lit(name)} ;\n    rdfs:comment {_lit(comment)}{extra} .")
    lines.append("")
    for name, (xsd, comment) in DATA_PROPERTIES.items():
        lines.append(f"lic:{name} a owl:DatatypeProperty ;\n    rdfs:label {_lit(name)} ;\n    rdfs:comment {_lit(comment)} ;\n    rdfs:range xsd:{xsd} .")
    return "\n".join(lines) + "\n"


def prompt_description() -> str:
    """Compact schema listing embedded in the extraction prompt; derived classes and relations are left out because code builds them."""
    out = ["CLASSES (Class: meaning, maximum count)"]
    for name, (_, comment) in CLASSES.items():
        if name not in DERIVED_CLASSES:
            out.append(f"- {name}: {comment} (at most {CLASS_CAPS[name]})")
    out.append("\nRELATIONS (name: Domain -> Range: meaning)")
    for name, (domain, rng, comment) in OBJECT_PROPERTIES.items():
        if domain not in DERIVED_CLASSES and rng not in DERIVED_CLASSES:
            out.append(f"- {name}: {domain or 'Any'} -> {rng or 'Any'}: {comment}")
    out.append("\nDATA PROPERTIES (name (type): meaning)")
    for name, (xsd, comment) in DATA_PROPERTIES.items():
        if name not in {"days", "durationYears", "modeCode", "installmentsPerYear", "intervalMonths"}:  # built or inferred in code
            out.append(f"- {name} ({xsd}): {comment}")
    return "\n".join(out)


if __name__ == "__main__":
    print(to_turtle())
