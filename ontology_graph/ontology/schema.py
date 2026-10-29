"""Single source of truth for the LIC ULIP ontology schema (TBox): generates the Turtle loaded into GraphDB and the allow-lists and prompt text used to validate LLM extraction. Run `python -m ontology_graph.ontology.schema` to print the Turtle."""
from __future__ import annotations

LIC_NS = "https://gates.example.org/lic#"
DATA_NS = "https://gates.example.org/lic/id/"
SCHEMA_GRAPH = "https://gates.example.org/lic/graph/schema"

# name -> (parent class or None, description)
CLASSES: dict[str, tuple[str | None, str]] = {
    "Insurer": (None, "Company that issues the plan, e.g. Life Insurance Corporation of India"),
    "Regulator": (None, "Authority that regulates the plan, e.g. IRDAI"),
    "Regulation": (None, "Act, section or regulation the plan is subject to, e.g. Section 45 of the Insurance Act 1938"),
    "Plan": (None, "Insurance plan (product), identified by its UIN"),
    "Rider": (None, "Optional add-on cover attached to a plan"),
    "SumAssuredOption": (None, "Choice of basic sum assured, expressed as a multiple of the single premium"),
    "Fund": (None, "Unit fund the premium can be invested in"),
    "Charge": (None, "Deduction levied under the plan"),
    "PremiumAllocationCharge": ("Charge", "Share of the premium kept as charges before units are bought"),
    "MortalityCharge": ("Charge", "Cost of life cover, deducted monthly by cancelling units"),
    "AccidentBenefitCharge": ("Charge", "Cost of the accident benefit rider"),
    "FundManagementCharge": ("Charge", "Annual charge on the fund value, adjusted in the NAV"),
    "SwitchingCharge": ("Charge", "Charge per switch between funds beyond the free switches"),
    "PartialWithdrawalCharge": ("Charge", "Flat charge per partial withdrawal"),
    "DiscontinuanceCharge": ("Charge", "Charge on discontinuing the policy, by policy year and premium size"),
    "MiscellaneousCharge": ("Charge", "Flat charge for a policy alteration"),
    "TaxCharge": ("Charge", "Tax levied on charges as per prevailing tax law"),
    "Benefit": (None, "Amount payable under the plan"),
    "DeathBenefit": ("Benefit", "Amount payable on death of the life assured"),
    "MaturityBenefit": ("Benefit", "Amount payable on surviving the maturity date"),
    "GuaranteedAddition": ("Benefit", "Percentage of single premium added to the unit fund at a policy year"),
    "Eligibility": (None, "Entry age, maturity age, term and premium limits"),
    "Feature": (None, "Optional feature or servicing option of the plan"),
    "PartialWithdrawal": ("Feature", "Withdrawing units from the fund after the lock-in"),
    "Switching": ("Feature", "Moving the whole fund value between fund types"),
    "SettlementOption": ("Feature", "Receiving the death benefit in instalments"),
    "Period": (None, "Time window that conditions the plan"),
    "LockInPeriod": ("Period", "Period during which funds cannot be withdrawn or surrendered"),
    "FreeLookPeriod": ("Period", "Period to return the policy and get a refund"),
    "Exclusion": (None, "Circumstance in which the normal benefit is not paid"),
    "Policy": (None, "A policyholder's policy under a plan; instance data lives in PostgreSQL, not in the brochure"),
}

# name -> (domain class or None, range class or None, description)
OBJECT_PROPERTIES: dict[str, tuple[str | None, str | None, str]] = {
    "issuedBy": ("Plan", "Insurer", "Insurer that issues the plan"),
    "regulatedBy": ("Plan", "Regulator", "Regulator of the plan"),
    "offersFund": ("Plan", "Fund", "Fund type the policyholder can choose"),
    "hasCharge": ("Plan", "Charge", "Charge levied under the plan"),
    "chargeAppliesTo": ("Charge", "Fund", "Fund a charge is levied on"),
    "hasSumAssuredOption": ("Plan", "SumAssuredOption", "Sum assured option offered"),
    "hasRider": ("Plan", "Rider", "Rider that can be added"),
    "hasBenefit": ("Plan", "Benefit", "Benefit payable"),
    "hasEligibility": ("Plan", "Eligibility", "Eligibility conditions"),
    "eligibilityFor": ("Eligibility", "SumAssuredOption", "Sum assured option an eligibility row applies to"),
    "hasFeature": ("Plan", "Feature", "Optional feature or servicing option"),
    "hasPeriod": ("Plan", "Period", "Lock-in or free-look period"),
    "hasExclusion": ("Plan", "Exclusion", "Exclusion under the plan"),
    "freeSwitchTo": ("Fund", "Fund", "Fund the policyholder may switch to free of charge if this fund becomes non-compliant"),
    "governedBy": (None, "Regulation", "Regulation or Act section that governs something"),
    "underPlan": ("Policy", "Plan", "Plan a policy is issued under"),
}

# name -> (xsd type: string | decimal | integer, description)
DATA_PROPERTIES: dict[str, tuple[str, str]] = {
    "description": ("string", "Short free-text summary of the entity"),
    "uin": ("string", "Unique Identification Number of a plan or rider"),
    "sfin": ("string", "Segregated Fund Identification Number of a fund"),
    "riskProfile": ("string", "Risk profile of a fund, e.g. Low Risk, High Risk"),
    "value": ("decimal", "Numeric value of a rate, amount or percentage"),
    "unit": ("string", "Unit of value, e.g. '% of premium', '% p.a. of unit fund', 'Rs per switch', 'Rs per thousand sum assured'"),
    "condition": ("string", "Condition under which the value applies, e.g. 'offline sale', 'policy year 1'"),
    "minValue": ("decimal", "Lower bound"),
    "maxValue": ("decimal", "Upper bound"),
    "multiplier": ("decimal", "Multiple of the single premium, for a sum assured option"),
    "atPolicyYear": ("integer", "Policy year at which something happens"),
    "policyYearFrom": ("integer", "First policy year of a band"),
    "policyYearTo": ("integer", "Last policy year of a band"),
    "durationYears": ("decimal", "Length in years"),
    "durationDays": ("integer", "Length in days"),
    "minEntryAge": ("decimal", "Minimum age at entry"),
    "maxEntryAge": ("decimal", "Maximum age at entry"),
    "minMaturityAge": ("decimal", "Minimum maturity age"),
    "maxMaturityAge": ("decimal", "Maximum maturity age"),
    "minTermYears": ("decimal", "Minimum policy term in years"),
    "maxTermYears": ("decimal", "Maximum policy term in years"),
    "minPremiumInr": ("decimal", "Minimum premium in rupees"),
    "premiumMultipleInr": ("decimal", "Premium must be a multiple of this many rupees"),
    "minEquityPct": ("decimal", "Minimum share invested in listed equity"),
    "maxEquityPct": ("decimal", "Maximum share invested in listed equity"),
    "minDebtPct": ("decimal", "Minimum share in government securities and corporate debt"),
    "maxDebtPct": ("decimal", "Maximum share in government securities and corporate debt"),
    "maxMoneyMarketPct": ("decimal", "Maximum share in money market instruments"),
}


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
        f"<{LIC_NS.rstrip('#')}> a owl:Ontology ; rdfs:label \"LIC ULIP plan ontology\" .",
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
    """Compact schema listing embedded in the extraction prompt."""
    out = ["CLASSES (Class < Parent: meaning)"]
    for name, (parent, comment) in CLASSES.items():
        out.append(f"- {name}{' < ' + parent if parent else ''}: {comment}")
    out.append("\nRELATIONS (name: Domain -> Range: meaning)")
    for name, (domain, rng, comment) in OBJECT_PROPERTIES.items():
        out.append(f"- {name}: {domain or 'Any'} -> {rng or 'Any'}: {comment}")
    out.append("\nDATA PROPERTIES (name (type): meaning)")
    for name, (xsd, comment) in DATA_PROPERTIES.items():
        out.append(f"- {name} ({xsd}): {comment}")
    return "\n".join(out)


if __name__ == "__main__":
    print(to_turtle())
