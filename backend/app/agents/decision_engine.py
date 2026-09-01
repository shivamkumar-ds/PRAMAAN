"""
Decision Intelligence Engine — reasoning only, no persistence (that's
decision_service.py's job, same AI Service Layer / Business Logic Layer
split M3 and M5 already established).

Only one LLM call type exists in this whole module: per-requirement
matching. Everything else — recommendation type, risk level, required
verification, confidence propagation, the executive summary — is
deterministic computation over already-decided facts, per the
milestone's own instruction to avoid black-box behaviour wherever
possible.
"""

import enum
import uuid
from dataclasses import dataclass

from app.agents.json_utils import parse_json_response
from app.agents.llm_client import get_llm_client
from app.agents.prompts import decision_matching
from app.core.config import get_settings
from app.models.enums import (
    CapabilityEntityType,
    MatchStatus,
    RecommendationType,
    RequirementNature,
    RequirementType,
    RiskLevel,
)
from app.schemas.extraction import DecisionMatchExtraction
from app.services.freshness import evaluate_freshness

settings = get_settings()


class QualificationStatus(str, enum.Enum):
    """
    Architecture debate Phase 2 (see BidOps_Architecture_Debate.md):
    whether the company genuinely qualifies for this tender, based
    ONLY on CAPABILITY_CLAIM requirements — real, checkable claims
    about certifications, project history, staff, or financial
    capacity. Deliberately NOT persisted on Recommendation and NOT
    exposed via EvaluationResponse yet — that wiring is Phase 5's
    remediation_summary. Lives here (not app/models/enums.py) because
    it is not a database-backed field; enums.py is reserved for enums
    that type-constrain an actual DB/schema column (see its own
    docstring) and this is a pure in-memory computation result.
    """

    PASS = "pass"
    CONDITIONAL = "conditional"
    FAIL = "fail"


class ReadinessStatus(str, enum.Enum):
    """
    Architecture debate Phase 2: whether the bid itself is ready to
    submit, based on SUBMISSION_GATING / PROCEDURAL /
    FUTURE_CONTRACTUAL_COMMITMENT requirements — bid-mechanics and
    execution-phase commitments, never a claim about company
    capability. Same not-persisted-yet caveat as QualificationStatus.
    """

    READY = "ready"
    ACTION_REQUIRED = "action_required"
    BLOCKED = "blocked"


class EvaluationCoverage(str, enum.Enum):
    """
    Architecture debate Phase 4: a property of BidOps' own extraction
    capability, NOT of the tender requirement — whether a given
    CapabilityEntityType domain currently has a real extraction agent
    behind it. Deliberately per-domain, not per-requirement: a
    requirement can resolve to multiple candidate domains (see
    resolve_candidate_domains), some supported and some not, and
    forcing that mix into one requirement-level SUPPORTED/UNSUPPORTED
    verdict would either hide a genuine gap (if any domain is
    supported) or discard genuinely-available evidence (if any domain
    isn't) — see get_unsupported_domains()'s docstring for how the
    mixed case is actually represented instead. Never persisted, never
    LLM-classified, never a new MatchStatus — see
    get_evaluation_coverage()/get_unsupported_domains().
    """

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"


def get_evaluation_coverage(
    entity_type: CapabilityEntityType, supported_domains: set[CapabilityEntityType]
) -> EvaluationCoverage:
    """
    Deterministic per-domain lookup — no LLM call, nothing persisted.
    `supported_domains` is supplied by the caller (decision_service.py),
    which is the one place in the codebase already positioned to read
    capability_service.ENTITY_MODELS.keys() — the real, single source of
    truth for "which domains currently have an extraction agent" (see
    capability_service.py's own comment: "the three MVP document types
    with an extraction agent... do not add Equipment/FinancialRecord
    here; no agent exists for them yet").

    Deliberately NOT imported directly here: decision_engine.py's own
    module docstring states its layering contract explicitly —
    "reasoning only, no persistence (that's decision_service.py's job)".
    capability_service.py is a stateful persistence-layer module (every
    real function on it takes a Session); importing it into this
    reasoning-only module would invert that layering for the sake of one
    static dict. Passing the resolved set in as a plain parameter keeps
    decision_engine.py's only cross-layer import exactly what it already
    was (app.services.freshness, which is itself a pure, Session-free
    helper — not a counter-example to this rule, see its own docstring).
    """
    return EvaluationCoverage.SUPPORTED if entity_type in supported_domains else EvaluationCoverage.UNSUPPORTED


def get_unsupported_domains(
    domains: list[CapabilityEntityType], supported_domains: set[CapabilityEntityType] | None
) -> frozenset[CapabilityEntityType]:
    """
    The requirement-level representation of coverage: not a single
    SUPPORTED/UNSUPPORTED verdict, but the actual subset of a
    requirement's resolved candidate domains (resolve_candidate_domains)
    that are unsupported — empty if none are. This is deliberately a set,
    not a third EvaluationCoverage value like PARTIALLY_SUPPORTED: a
    requirement with domains {Employee, Equipment} where only Equipment
    is unsupported doesn't need a fabricated blended verdict, it needs
    the literal fact "Equipment couldn't be checked" alongside whatever
    real MatchStatus the Employee-domain evidence produced. Phase 5's
    remediation_summary can answer "which requirements were unsupported
    and by which domain" directly from this, without this phase having
    to guess how that should roll up into a single label.

    supported_domains=None means "no coverage information was supplied"
    (nothing calls match_requirement() this way except possibly a
    future/other caller) — resolves to "nothing is unsupported" rather
    than raising, so existing behavior is preserved for any caller that
    doesn't yet pass this through.
    """
    if supported_domains is None:
        return frozenset()
    return frozenset(d for d in domains if d not in supported_domains)

# Which capability domains are actually candidates for each matchable
# requirement category. Deadline/EvaluationCriteria/Submission are
# deliberately absent — see PROCEDURAL_CATEGORIES below.
CATEGORY_DOMAINS: dict[RequirementType, list[CapabilityEntityType]] = {
    RequirementType.CERTIFICATION: [CapabilityEntityType.CERTIFICATION],
    RequirementType.EXPERIENCE: [CapabilityEntityType.PROJECT],
    RequirementType.ELIGIBILITY: [
        CapabilityEntityType.CERTIFICATION,
        CapabilityEntityType.FINANCIAL_RECORD,
        CapabilityEntityType.PROJECT,
    ],
    RequirementType.TECHNICAL: [
        CapabilityEntityType.EQUIPMENT,
        CapabilityEntityType.EMPLOYEE,
        CapabilityEntityType.PROJECT,
    ],
}

# These three are procedural facts about the tender process itself, not
# claims about company capability — no capability entity could
# "satisfy" a deadline. They skip matching entirely (see
# build_procedural_result below).
PROCEDURAL_CATEGORIES = {
    RequirementType.DEADLINE,
    RequirementType.EVALUATION_CRITERIA,
    RequirementType.SUBMISSION,
}

# Architecture debate Phase 3: deterministic, additive-only keyword hints
# that widen (never narrow) the candidate domain set CATEGORY_DOMAINS
# alone would produce. Fixes the confirmed EXPERIENCE -> Employee gap:
# RequirementType.EXPERIENCE routes only to [PROJECT] above, so a
# requirement like "Bidder shall engage expert labour / skilled
# personnel" never considered Employee candidates even though
# Employee.skills is exactly the relevant evidence. Deliberately a small,
# hand-picked vocabulary, not an NLP system or a second LLM call — see
# resolve_candidate_domains()'s docstring for the safety argument (why
# over-matching here is low-risk and under-matching is a no-op).
_DOMAIN_HINT_KEYWORDS: dict[CapabilityEntityType, tuple[str, ...]] = {
    CapabilityEntityType.EMPLOYEE: (
        "personnel", "staff", "employee", "employees", "labour", "labor",
        "engineer", "worker", "workers", "skilled labour", "skilled labor", "manpower",
    ),
    CapabilityEntityType.PROJECT: (
        "completed", "executed", "contract", "client", "similar work",
        "similar works", "experience of work", "previous work",
    ),
    CapabilityEntityType.EQUIPMENT: (
        "machinery", "equipment", "plant", "vehicle", "vehicles",
    ),
}


def additional_domains(description: str) -> set[CapabilityEntityType]:
    """
    Deterministic, case-insensitive substring matching against
    _DOMAIN_HINT_KEYWORDS — same "text to analyze, not instructions"
    treatment as everywhere else untrusted tender text is handled.
    Intentionally simple (no tokenization/NLP): the keyword list itself
    was chosen to be specific enough (multi-word phrases like "skilled
    labour", not bare "skill") that substring matching's main failure
    mode is occasional over-matching, not silent under-matching — and
    over-matching here is low-risk because this function's output is
    only ever UNION-ed onto CATEGORY_DOMAINS's base set (see
    resolve_candidate_domains), never used to exclude anything. A false-
    positive hint just means the matching LLM briefly sees one extra,
    irrelevant candidate and returns null for it, exactly the same as
    today's existing "candidate exists but nothing matched" path.
    """
    text = (description or "").lower()
    return {domain for domain, keywords in _DOMAIN_HINT_KEYWORDS.items() if any(kw in text for kw in keywords)}


def resolve_candidate_domains(requirement) -> list[CapabilityEntityType]:
    """
    The single source of truth for "which capability domains apply to
    this requirement" — base CATEGORY_DOMAINS mapping, unioned with
    additional_domains()'s deterministic text hints. Used both by
    decision_service._match_one() (to actually build the candidate
    entity list) and by match_requirement()'s own "zero candidates"
    branch (so its descriptive message reflects the real domain set
    considered, not just the base mapping) — one function, not two
    independently-maintained copies of the same union logic.

    Additive-only by construction: base domains are never removed, only
    ever appended to. Base-domain order is preserved; hint domains not
    already present are appended in a fixed, deterministic order (the
    dict iteration order of _DOMAIN_HINT_KEYWORDS, itself fixed at
    module load), so the same requirement always produces the same
    candidate domain list.

    requirement.requirement_type not present in CATEGORY_DOMAINS (the
    three PROCEDURAL_CATEGORIES types) resolves to an empty base list —
    unreachable in practice since match_requirement() already returns
    build_non_capability_result() before this is ever called for a
    non-CAPABILITY_CLAIM-natured requirement, but kept safe rather than
    raising a KeyError.
    """
    base = CATEGORY_DOMAINS.get(requirement.requirement_type, [])
    hints = additional_domains(requirement.description)
    domains = list(base)
    for domain in hints:
        if domain not in domains:
            domains.append(domain)
    return domains


@dataclass
class MatchResult:
    requirement_id: uuid.UUID
    requirement_type: RequirementType
    mandatory: bool
    status: MatchStatus
    matched_entity_type: CapabilityEntityType | None
    matched_entity_id: uuid.UUID | None
    matching_confidence: float
    supporting_evidence: str
    notes: str
    requirement_nature: RequirementNature  # architecture debate Phase 2 — see resolve_evaluation_nature()
    # Architecture debate Phase 4 — see get_unsupported_domains(). Empty
    # (the default) means every resolved candidate domain has a real
    # extraction agent; non-empty names which domain(s) BidOps could not
    # evaluate, independent of whatever `status` the supported domains
    # (if any) produced.
    unsupported_domains: frozenset[CapabilityEntityType] = frozenset()


def resolve_evaluation_nature(requirement) -> RequirementNature:
    """
    The single source of truth for "what nature does this Requirement
    have, for evaluation purposes" — architecture debate Phase 2.

    Distinct from tender_analyzer._resolve_nature() (Phase 1), which
    resolves the LLM's raw, possibly-missing extraction output at
    *write* time, once, when a new tender is first analyzed. This
    function instead resolves the already-persisted
    Requirement.requirement_nature column at *evaluation* time, every
    time, and its only real job is backward compatibility: every
    Requirement row created before the Phase 1 migration (and any row
    from a code path that doesn't set it) has requirement_nature = NULL
    in the database. Historical rows are never backfilled (explicit
    Phase 1 decision) — this function is what lets old and new rows
    evaluate through the same code path without a database write.

    NULL resolution mirrors the old, pre-Phase-2 architecture's own
    implicit interpretation exactly: requirement_type in
    PROCEDURAL_CATEGORIES was already always treated as "not a
    capability claim" (see the old build_procedural_result), and every
    other requirement_type was already always sent through capability
    matching (i.e. treated as a capability claim). Resolving NULL this
    way means a historical tender's recommendation is unaffected by
    this migration unless/until it is re-analyzed.
    """
    if requirement.requirement_nature is not None:
        return requirement.requirement_nature
    if requirement.requirement_type in PROCEDURAL_CATEGORIES:
        return RequirementNature.PROCEDURAL
    return RequirementNature.CAPABILITY_CLAIM


def reconstruct_match_result(
    requirement, compliance_row, supported_domains: set[CapabilityEntityType] | None
) -> MatchResult:
    """
    Architecture debate Phase 5: rebuilds a MatchResult-equivalent object
    from already-persisted Requirement + ComplianceMatrix rows, for
    read-time endpoints (GET /evaluation/{mission_id}, GET
    /recommendations/{mission_id}) that never re-run matching — only the
    original run_evaluation() call produces real MatchResult objects, and
    those are discarded in memory once ComplianceMatrix rows are written.

    This reconstruction is exact (not an approximation) because the two
    facts a MatchResult carries beyond what ComplianceMatrix persists —
    requirement_nature and unsupported_domains — are both pure,
    deterministic functions of already-persisted data
    (Requirement.requirement_type/requirement_nature/description, and
    capability_service.ENTITY_MODELS), not information that had to be
    captured at run time and would otherwise be lost. See
    resolve_evaluation_nature() and get_unsupported_domains().

    Known, deliberately-accepted limitation (see Phase 5 completion
    report rather than solving this with a new persisted column): if
    capability_service.ENTITY_MODELS changes between when an evaluation
    ran and when it's later read (e.g. an Equipment extraction agent
    ships), unsupported_domains recomputed here reflects the CURRENT
    registry, not the one in effect at run time. A persisted
    ComplianceMatrix.status of REVIEW_REQUIRED from an old coverage gap
    could, in that narrow window, pair with a freshly-empty
    unsupported_domains until the mission is re-evaluated. Accepted
    because it only matters across a code deploy that adds a new agent,
    and recomputing live capability facts is arguably more honest for
    "can BidOps evaluate this today" than a frozen snapshot would be.
    """
    nature = resolve_evaluation_nature(requirement)
    unsupported: frozenset[CapabilityEntityType] = frozenset()
    if nature == RequirementNature.CAPABILITY_CLAIM:
        resolved_domains = resolve_candidate_domains(requirement)
        unsupported = get_unsupported_domains(resolved_domains, supported_domains)

    matching_confidence = compliance_row.matching_confidence
    return MatchResult(
        requirement_id=requirement.id,
        requirement_type=requirement.requirement_type,
        requirement_nature=nature,
        mandatory=requirement.mandatory,
        status=compliance_row.status,
        matched_entity_type=None,  # not needed by classify_remediation(); real entity lives on CapabilityMapping
        matched_entity_id=None,
        matching_confidence=float(matching_confidence) if matching_confidence is not None else 0.0,
        supporting_evidence=compliance_row.supporting_evidence or "",
        notes=compliance_row.notes or "",
        unsupported_domains=unsupported,
    )


def _summarize_entity(entity_type: CapabilityEntityType, entity) -> str:
    if entity_type == CapabilityEntityType.CERTIFICATION:
        return f"Certification: {entity.certification_name}, issued by {entity.issuing_authority}, expires {entity.expiry_date}"
    if entity_type == CapabilityEntityType.EMPLOYEE:
        return f"Employee: {entity.name}, {entity.position}, qualification: {entity.qualification}, skills: {entity.skills}"
    if entity_type == CapabilityEntityType.PROJECT:
        return f"Project: client {entity.client}, industry {entity.industry}, value {entity.contract_value}, status {entity.completion_status}"
    if entity_type == CapabilityEntityType.EQUIPMENT:
        return f"Equipment: {entity.equipment_name}, category {entity.category}, quantity {entity.quantity}"
    if entity_type == CapabilityEntityType.FINANCIAL_RECORD:
        return f"Financial record: year {entity.financial_year}, revenue {entity.revenue}, net worth {entity.net_worth}"
    return "Unknown entity type"


_NON_CAPABILITY_NOTES: dict[RequirementNature, str] = {
    RequirementNature.PROCEDURAL: (
        "This requirement is procedural (deadline, evaluation criteria, or submission "
        "format), not a claim about company capability. It cannot be automatically "
        "matched and always requires bid-team attention."
    ),
    RequirementNature.SUBMISSION_GATING: (
        "This requirement is a bid-submission gating item (e.g. EMD, DSC, e-procurement "
        "portal registration, a mandatory declaration or annexure) — not a claim about "
        "company capability. No capability entity could satisfy it; it always requires "
        "confirmation that the instrument/document has actually been prepared and will "
        "accompany the bid."
    ),
    RequirementNature.FUTURE_CONTRACTUAL_COMMITMENT: (
        "This requirement is a future contractual/execution-phase commitment (e.g. PPE, "
        "safety, or labour-law compliance during execution) — not a claim about current "
        "company capability. No current-state evidence can establish compliance in "
        "advance of award; it always requires acknowledgement."
    ),
}


def build_non_capability_result(requirement, nature: RequirementNature) -> MatchResult:
    """
    Architecture debate Phase 2: generalizes the old build_procedural_result
    to all three non-CAPABILITY_CLAIM natures, not just the three
    requirement_type-based PROCEDURAL_CATEGORIES. This closes a real gap
    the old architecture had — an EMD or PPE clause filed under
    requirement_type=eligibility used to be sent through ordinary
    capability matching (against Certification/FinancialRecord/Project
    candidates) even though no capability entity could ever satisfy it.
    Now any requirement whose resolved nature isn't CAPABILITY_CLAIM
    skips matching entirely, regardless of its requirement_type.

    Always REVIEW_REQUIRED, deterministically — MatchStatus stays the
    universal, unchanged vocabulary (per the locked architecture
    decision not to add a fifth status); RequirementNature is what
    carries the actual meaning apart from CAPABILITY_CLAIM. There is
    currently no mechanism in the product for one of these three
    natures to resolve to any status other than REVIEW_REQUIRED (no
    "confirm EMD prepared" action exists yet) — that is a real, known
    Phase 2 limitation, not an oversight; see the Phase 2 completion
    report.
    """
    return MatchResult(
        requirement_id=requirement.id,
        requirement_type=requirement.requirement_type,
        requirement_nature=nature,
        mandatory=requirement.mandatory,
        status=MatchStatus.REVIEW_REQUIRED,
        matched_entity_type=None,
        matched_entity_id=None,
        matching_confidence=1.0,  # fully confident this classification itself is correct
        supporting_evidence="No company capability applies — see notes for why.",
        notes=_NON_CAPABILITY_NOTES[nature],
    )


def build_unsupported_coverage_result(
    requirement, nature: RequirementNature, unsupported_domains: frozenset[CapabilityEntityType]
) -> MatchResult:
    """
    Architecture debate Phase 4: returned when EVERY one of a
    CAPABILITY_CLAIM requirement's resolved candidate domains lacks a
    real extraction agent (get_unsupported_domains() == all resolved
    domains) — e.g. a requirement whose only domain is Equipment.

    Deliberately REVIEW_REQUIRED, never NOT_MET. "Zero rows exist
    because no extraction path can ever create them" and "zero rows
    exist despite the domain being fully queryable" are different facts
    — match_requirement()'s pre-Phase-4 zero-candidates branch collapsed
    both into NOT_MET, which is exactly the "BidOps cannot evaluate
    equipment" == "company lacks the required equipment" conflation this
    phase exists to fix. Confirmed via capability_service.py /
    app/api/v1/capabilities.py: there is genuinely no path in the
    product today to create an Equipment or FinancialRecord capability
    record (the build endpoint 422s on those entity_types), so this
    isn't a hypothetical — it's the real, current state of every
    Equipment/FinancialRecord-domain requirement.
    """
    domains_text = ", ".join(d.value for d in unsupported_domains)
    return MatchResult(
        requirement_id=requirement.id,
        requirement_type=requirement.requirement_type,
        requirement_nature=nature,
        mandatory=requirement.mandatory,
        status=MatchStatus.REVIEW_REQUIRED,
        matched_entity_type=None,
        matched_entity_id=None,
        matching_confidence=1.0,  # fully confident that the classification (not the match) is correct
        supporting_evidence=(
            f"BidOps cannot currently evaluate this requirement — no extraction capability "
            f"exists yet for: {domains_text}."
        ),
        notes=(
            "Unsupported evaluation coverage, not a capability finding: BidOps has no "
            "extraction agent for the relevant domain(s) yet, so no capability record could "
            "ever exist to prove or disprove this requirement. This is a product limitation, "
            "not evidence that the company lacks the capability — requires manual review."
        ),
        unsupported_domains=unsupported_domains,
    )


async def match_requirement(
    requirement,
    candidates: list[tuple[CapabilityEntityType, object]],
    provider: str | None = None,
    supported_domains: set[CapabilityEntityType] | None = None,
) -> MatchResult:
    nature = resolve_evaluation_nature(requirement)
    if nature != RequirementNature.CAPABILITY_CLAIM:
        return build_non_capability_result(requirement, nature)

    resolved_domains = resolve_candidate_domains(requirement)
    unsupported = get_unsupported_domains(resolved_domains, supported_domains)

    # Every resolved domain is unsupported -- no candidate could ever
    # have existed, regardless of what `candidates` happens to contain.
    # Checked before the generic "no candidates" branch below so this
    # case never gets mislabeled NOT_MET.
    if resolved_domains and unsupported == set(resolved_domains):
        return build_unsupported_coverage_result(requirement, nature, unsupported)

    if not candidates:
        domains = ", ".join(d.value for d in resolved_domains)
        return MatchResult(
            requirement_id=requirement.id,
            requirement_type=requirement.requirement_type,
            requirement_nature=nature,
            mandatory=requirement.mandatory,
            status=MatchStatus.NOT_MET,
            matched_entity_type=None,
            matched_entity_id=None,
            matching_confidence=0.9,  # a "zero rows exist" finding is a DB fact, not a guess
            supporting_evidence=f"No records found in company capability graph for domain(s): {domains}.",
            notes="Deterministic: zero candidate entities exist in the relevant capability domain(s).",
            # Mixed case: at least one resolved domain is genuinely
            # supported (otherwise the branch above would have returned
            # already) but still has zero rows -- a real "no evidence"
            # finding, not a coverage gap by itself. Any OTHER domain
            # that is unsupported is still surfaced here so the gap isn't
            # silently dropped just because this requirement also
            # happened to have a genuine NOT_MET outcome.
            unsupported_domains=unsupported,
        )

    candidate_summaries = [_summarize_entity(entity_type, entity) for entity_type, entity in candidates]
    client = get_llm_client(provider)
    raw_response = await client.complete(
        decision_matching.SYSTEM_PROMPT,
        decision_matching.build_prompt(requirement.description or "", candidate_summaries),
        purpose="decision_matching",
    )
    validated = DecisionMatchExtraction.model_validate(parse_json_response(raw_response))
    status = MatchStatus(validated.status)

    matched_entity_type = matched_entity_id = None
    matched_entity = None
    matching_confidence = 0.7  # a judgment call was made despite candidates existing
    supporting_evidence = f"No specific record matched among {len(candidates)} candidate(s) considered."

    if validated.matched_entity_index is not None and 0 <= validated.matched_entity_index < len(candidates):
        matched_entity_type, matched_entity = candidates[validated.matched_entity_index]
        matched_entity_id = matched_entity.id
        matching_confidence = float(matched_entity.confidence_score or 0.7)
        supporting_evidence = _summarize_entity(matched_entity_type, matched_entity)

    notes = validated.reasoning or "(no reasoning provided)"

    # Deterministic freshness override — only applies when a specific
    # entity was actually cited. Refinement: expired forces NOT_MET;
    # stale only downgrades MET to REVIEW_REQUIRED (never NOT_MET) —
    # the system never rejects a company solely for stale evidence.
    if matched_entity is not None:
        freshness = evaluate_freshness(matched_entity)
        if freshness["is_expired"]:
            status = MatchStatus.NOT_MET
            notes += " | OVERRIDE: cited evidence is expired — forced to NOT_MET."
        elif freshness["is_stale"] and status == MatchStatus.MET:
            status = MatchStatus.REVIEW_REQUIRED
            notes += (
                " | OVERRIDE: cited evidence is stale (beyond the configured staleness "
                "threshold) — downgraded from MET to REVIEW_REQUIRED, not rejected. "
                "Stale information is uncertain, not necessarily invalid."
            )
        elif freshness["is_stale"] and status == MatchStatus.CONDITIONAL:
            notes += " | Note: cited evidence is also stale; already conditional, no further downgrade applied."

    return MatchResult(
        requirement_id=requirement.id,
        requirement_type=requirement.requirement_type,
        requirement_nature=nature,
        mandatory=requirement.mandatory,
        status=status,
        matched_entity_type=matched_entity_type,
        matched_entity_id=matched_entity_id,
        matching_confidence=matching_confidence,
        supporting_evidence=supporting_evidence,
        notes=notes,
        # Mixed-domain case: matching proceeded and produced a real
        # status using the supported-domain candidates, but any OTHER
        # domain this requirement also resolved to that lacks an
        # extraction agent is still surfaced here — a genuine MET/
        # NOT_MET/etc. verdict from Employee/Project evidence doesn't
        # erase the fact that Equipment, say, was never actually checked.
        unsupported_domains=unsupported,
    )


def compute_risk_level(mandatory: bool, status: MatchStatus) -> RiskLevel:
    if mandatory and status == MatchStatus.NOT_MET:
        return RiskLevel.CRITICAL
    if mandatory and status in (MatchStatus.REVIEW_REQUIRED, MatchStatus.CONDITIONAL):
        return RiskLevel.HIGH
    if status in (MatchStatus.REVIEW_REQUIRED, MatchStatus.CONDITIONAL):
        return RiskLevel.MEDIUM
    if not mandatory and status == MatchStatus.NOT_MET:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def compute_requires_verification(
    mandatory: bool, status: MatchStatus, matching_confidence: float
) -> tuple[bool, str]:
    reasons = []
    if mandatory and status != MatchStatus.MET:
        reasons.append(f"Mandatory requirement with status '{status.value}'.")
    if status == MatchStatus.REVIEW_REQUIRED:
        reasons.append("Status is REVIEW_REQUIRED.")
    if matching_confidence < 0.7:
        reasons.append(f"Matching confidence ({matching_confidence}) is below the 0.7 threshold.")
    return (bool(reasons), " ".join(reasons) if reasons else "")


def compute_qualification(
    results: list[MatchResult],
    overridden_requirement_ids: frozenset[uuid.UUID] = frozenset(),
) -> QualificationStatus:
    """
    Architecture debate Phase 2: qualification concerns ONLY genuine
    company capability claims — CAPABILITY_CLAIM-natured results.
    SUBMISSION_GATING / PROCEDURAL / FUTURE_CONTRACTUAL_COMMITMENT
    results never affect qualification, by design — an unresolved EMD
    or a routine deadline instruction says nothing about whether the
    company is actually qualified to perform the work.

    Architecture debate Phase 4 note: this function required NO code
    change for EvaluationCoverage. A fully-unsupported CAPABILITY_CLAIM
    requirement (e.g. domain == Equipment) now arrives here with
    status=REVIEW_REQUIRED, never NOT_MET (see
    build_unsupported_coverage_result()) — so it already falls into the
    `mandatory and status in (REVIEW_REQUIRED, CONDITIONAL)` branch below
    and yields CONDITIONAL, never FAIL, purely as a consequence of the
    status now being honest. This function still only ever looks at
    (mandatory, status) — it has no idea whether a REVIEW_REQUIRED
    result came from genuine matching uncertainty or from unsupported
    coverage, and it doesn't need to: both are equally "not confirmed
    met, not confirmed failed," which is exactly what CONDITIONAL means.

    Qualification override feature (app/models/qualification_override.py):
    overridden_requirement_ids is the ONE deliberate, explicit escape
    hatch into this function — a real, audited administrator decision to
    let a specific mandatory capability gap stop blocking qualification,
    made with full knowledge that no real evidence exists for it yet.
    This is fundamentally different from the bid-readiness confirmation
    feature's boundary rule (that one explicitly NEVER reaches this
    function, because there is no capability entity that could ever
    satisfy an EMD/DSC clause — real evidence is possible for
    CAPABILITY_CLAIM items, just not present yet). An overridden item is
    excluded from both the FAIL and CONDITIONAL checks below, exactly as
    if it were MET for qualification purposes — but it must never be
    silently indistinguishable from real evidence anywhere else: see
    classify_remediation()'s docstring and GapAnalysisEntry's
    overridden/overridden_by/overridden_at/override_note fields, which
    keep the item visible and labeled in every bucket it already
    appears in. Defaults to frozenset() so every existing caller is
    unaffected.
    """
    capability_results = [r for r in results if r.requirement_nature == RequirementNature.CAPABILITY_CLAIM]

    def _is_overridden(r: MatchResult) -> bool:
        return r.requirement_id in overridden_requirement_ids

    if any(r.mandatory and r.status == MatchStatus.NOT_MET and not _is_overridden(r) for r in capability_results):
        return QualificationStatus.FAIL
    if any(
        r.mandatory and r.status in (MatchStatus.REVIEW_REQUIRED, MatchStatus.CONDITIONAL) and not _is_overridden(r)
        for r in capability_results
    ):
        return QualificationStatus.CONDITIONAL
    return QualificationStatus.PASS


def compute_bid_readiness(
    results: list[MatchResult],
    confirmed_requirement_ids: frozenset[uuid.UUID] = frozenset(),
) -> ReadinessStatus:
    """
    Architecture debate Phase 2: whether the bid is actually ready to
    submit, based on SUBMISSION_GATING / PROCEDURAL /
    FUTURE_CONTRACTUAL_COMMITMENT results only. Deterministic — the LLM
    is never asked to decide BLOCKED vs ACTION_REQUIRED; this is a pure
    function of (requirement_nature, mandatory, status).

    Only a mandatory, unresolved SUBMISSION_GATING item can produce
    BLOCKED — this is the fix for the earlier architecture mistake
    (round 2/3 of the debate) of treating every mandatory "submission-
    flavored" clause the same way. A mandatory unresolved deadline/
    upload-format/portal-mechanics instruction is real bid-preparation
    work, but it does not, by itself, invalidate the bid the way an
    unresolved EMD does.

    "Unresolved" means status != MET AND requirement_id not in
    confirmed_requirement_ids (bid-readiness confirmation feature —
    BidReadinessConfirmation, app/models/bid_readiness.py). A human
    confirming "this SUBMISSION_GATING/FUTURE_CONTRACTUAL_COMMITMENT item
    is actually prepared" is a real, out-of-band fact the matching engine
    itself can never observe (there is no capability entity that could
    ever satisfy an EMD/DSC/PPE clause — see build_non_capability_result's
    docstring) — this is the one deliberate, explicit escape hatch for
    that fact, scoped to exactly these two natures, never PROCEDURAL
    (deadlines/evaluation-criteria/submission-format items always need a
    fresh bid-team look regardless of a prior confirmation) and never
    CAPABILITY_CLAIM (see compute_qualification()'s docstring — capability
    claims can only be resolved by real evidence, never a checkbox).

    Confirmation is intentionally not restricted to mandatory items here:
    Action Center offers "Confirm Prepared" on any SUBMISSION_GATING/
    FUTURE_CONTRACTUAL_COMMITMENT item in blocked_items OR
    action_required_items (both mandatory and non-mandatory), so a
    non-mandatory confirmed item must also stop counting toward the
    ACTION_REQUIRED fallback below — otherwise confirming it would have
    no visible effect on `bid_readiness` at all.

    confirmed_requirement_ids defaults to frozenset() so every existing
    caller (decision_service.run_evaluation, which has no confirmations
    to pass at run time) is unaffected.
    """
    def _is_confirmed(r: MatchResult) -> bool:
        return (
            r.requirement_nature in (RequirementNature.SUBMISSION_GATING, RequirementNature.FUTURE_CONTRACTUAL_COMMITMENT)
            and r.requirement_id in confirmed_requirement_ids
        )

    gating_unresolved = [
        r for r in results
        if r.requirement_nature == RequirementNature.SUBMISSION_GATING
        and r.status != MatchStatus.MET
        and not _is_confirmed(r)
    ]
    other_unresolved = [
        r for r in results
        if r.requirement_nature in (RequirementNature.PROCEDURAL, RequirementNature.FUTURE_CONTRACTUAL_COMMITMENT)
        and r.status != MatchStatus.MET
        and not _is_confirmed(r)
    ]

    if any(r.mandatory for r in gating_unresolved):
        return ReadinessStatus.BLOCKED
    if gating_unresolved or any(r.mandatory for r in other_unresolved):
        return ReadinessStatus.ACTION_REQUIRED
    return ReadinessStatus.READY


def compute_recommendation_type(
    results: list[MatchResult],
    confirmed_requirement_ids: frozenset[uuid.UUID] = frozenset(),
    overridden_requirement_ids: frozenset[uuid.UUID] = frozenset(),
) -> RecommendationType:
    """
    Architecture debate Phase 2: composed from QualificationStatus +
    ReadinessStatus, not from a single flat scan of every mandatory
    NOT_MET result the way the pre-Phase-2 version worked. See
    compute_qualification()/compute_bid_readiness() for the two axes.

    Bid-readiness confirmation feature: confirmed_requirement_ids is
    forwarded only into compute_bid_readiness() (the readiness axis) —
    a capability-claim qualification gap can only be resolved by real
    evidence or an explicit administrator override, never a plain
    confirmation checkbox.

    Qualification override feature: overridden_requirement_ids is
    forwarded only into compute_qualification() (the qualification axis)
    — the two parameters are deliberately kept on separate axes and
    never cross-wired, matching each function's own boundary rule.
    Both default to frozenset() so every existing caller
    (decision_service.run_evaluation, which has neither confirmations
    nor overrides to pass at evaluation-run time — nothing has been
    confirmed or overridden yet for a brand-new run) is unaffected.

    RecommendationType itself is unchanged (still GO / CONDITIONAL_GO /
    REVIEW / NO_GO — no fifth value, per the locked architecture
    decision). The REVIEW branch (excessive *optional*, i.e.
    non-mandatory, unresolved items) is preserved unchanged from the
    pre-Phase-2 implementation and is deliberately independent of the
    qualification/readiness axes — settings.max_optional_review_items
    was never about mandatory capability or bid-readiness gaps, so it
    is checked only in the one branch where nothing else already
    demands a non-GO outcome (qualification PASS, readiness READY).

    Correction (post-review): QualificationStatus.CONDITIONAL always
    resolves to CONDITIONAL_GO, regardless of readiness. A mandatory
    CAPABILITY_CLAIM item that is REVIEW_REQUIRED/CONDITIONAL means
    qualification is not fully established — a clean GO must not be
    possible while that uncertainty exists, even if nothing else in the
    bid needs attention. The original Phase 2 draft let CONDITIONAL
    qualification fall through to GO whenever readiness was READY,
    reasoning that approval_service's separate blocking-row gate would
    still catch it — but a downstream safety gate does not make an
    inaccurate top-level label acceptable; the recommendation itself
    must communicate the qualification state honestly. PASS is now the
    only qualification value that can ever reach a clean GO.
    """
    qualification = compute_qualification(results, overridden_requirement_ids)
    readiness = compute_bid_readiness(results, confirmed_requirement_ids)

    if qualification == QualificationStatus.FAIL:
        return RecommendationType.NO_GO

    if qualification == QualificationStatus.CONDITIONAL:
        return RecommendationType.CONDITIONAL_GO

    # qualification == PASS here.
    if readiness in (ReadinessStatus.ACTION_REQUIRED, ReadinessStatus.BLOCKED):
        return RecommendationType.CONDITIONAL_GO

    # qualification PASS, readiness READY — preserved, unchanged
    # optional-issue overload check (see docstring).
    optional_issues = sum(
        1
        for r in results
        if not r.mandatory and r.status in (MatchStatus.REVIEW_REQUIRED, MatchStatus.CONDITIONAL, MatchStatus.NOT_MET)
    )
    if optional_issues > settings.max_optional_review_items:
        return RecommendationType.REVIEW
    return RecommendationType.GO


@dataclass
class RemediationClassification:
    """
    Architecture debate Phase 5: the deterministic backend representation
    that lets every consumer (API, and later the frontend/PDF in Phase 6)
    answer "what does this evaluation actually require, and why" without
    re-deriving qualification/readiness/coverage logic themselves. See
    classify_remediation()'s docstring for the exact classification rules.

    Deliberately holds MatchResult objects, not API schema objects —
    this stays in the pure-reasoning agents layer; converting each
    MatchResult into a GapAnalysisEntry (which needs Requirement fields
    like description/source_page) is decision_service.py's job, same
    AI Service Layer / Business Logic Layer split this module's own
    docstring already describes.
    """

    qualification: QualificationStatus
    bid_readiness: ReadinessStatus
    qualification_gaps: list[MatchResult]
    blocked_items: list[MatchResult]
    action_required_items: list[MatchResult]
    coverage_gaps: list[MatchResult]
    human_review_items: list[MatchResult]
    # Architecture debate Phase 6 (REVIEW-explainability gap): see
    # classify_remediation()'s docstring point 2 for the exact,
    # narrowly-scoped membership rule. Added because compute_recommendation_type()'s
    # REVIEW branch (qualification PASS, readiness READY, optional_issues >
    # settings.max_optional_review_items) could previously fire while every
    # other remediation_summary bucket was empty — this bucket is the one
    # previously-invisible contributor to that threshold.
    optional_capability_gaps: list[MatchResult]


def classify_remediation(
    results: list[MatchResult],
    confirmed_requirement_ids: frozenset[uuid.UUID] = frozenset(),
    overridden_requirement_ids: frozenset[uuid.UUID] = frozenset(),
) -> RemediationClassification:
    """
    Architecture debate Phase 5 (extended Phase 6 with a fifth,
    optional_capability_gaps view — see the loop below). Builds the
    remediation views from the exact same `results` list — and,
    critically, the exact same
    compute_qualification()/compute_bid_readiness() functions — that
    already drive compute_recommendation_type(). One source of truth:
    this function cannot silently diverge from the recommendation logic
    because it calls the same two functions, not a re-implementation of
    their rules.

    Classification order matters and is deliberately exclusive per item
    (no requirement is duplicated across buckets merely because it has
    multiple properties — see the module's Phase 5 discussion):

    1. unsupported_domains non-empty -> coverage_gaps, unconditionally,
       regardless of status. This is checked FIRST and short-circuits
       the rest: a mixed-domain requirement that matched MET on its
       supported subset still belongs here (the gap is about what
       *wasn't* checked, independent of what the checked part found),
       and it must never also land in qualification_gaps/human_review —
       coverage_gaps already tells the fuller, more specific story
       ("BidOps couldn't fully evaluate this"), so duplicating it into
       "capability evidence failed" or "ambiguous evidence" would
       misrepresent why the item needs attention.

    2. CAPABILITY_CLAIM (no unsupported domains):
       - mandatory + NOT_MET -> qualification_gaps (matches
         compute_qualification()'s FAIL condition exactly)
       - status in (REVIEW_REQUIRED, CONDITIONAL) -> human_review_items,
         regardless of mandatory -- "genuine evidence exists but the
         system isn't fully confident" always warrants a human look;
         only the *mandatory* ones additionally drive
         QualificationStatus.CONDITIONAL (see compute_qualification()).
       - non-mandatory + NOT_MET -> optional_capability_gaps (architecture
         debate Phase 6). Originally (Phase 5) these landed in neither
         bucket, reasoning that they're "not a qualification risk (not
         mandatory) and not ambiguous (status is definitively NOT_MET,
         nothing for a human to adjudicate)." That reasoning still holds
         for qualification_gaps/human_review_items specifically — this
         is a new, fourth bucket, not a reassignment into either.
         It exists because compute_recommendation_type()'s REVIEW branch
         counts exactly this item shape (non-mandatory, status in
         {NOT_MET, REVIEW_REQUIRED, CONDITIONAL}) toward
         settings.max_optional_review_items, and this is the ONLY item
         shape that can contribute to that threshold while landing in
         zero existing buckets: non-mandatory REVIEW_REQUIRED/CONDITIONAL
         CAPABILITY_CLAIM items already land in human_review_items above;
         by the time compute_recommendation_type() reaches its REVIEW
         branch (qualification PASS, readiness READY), no unresolved
         SUBMISSION_GATING item can exist at all (any unresolved gating
         item, mandatory or not, forces readiness to ACTION_REQUIRED —
         see compute_bid_readiness()); and every PROCEDURAL/
         FUTURE_CONTRACTUAL_COMMITMENT item is always REVIEW_REQUIRED
         (never NOT_MET, see build_non_capability_result()) and already
         lands in action_required_items above regardless of mandatory.
         So non-mandatory NOT_MET CAPABILITY_CLAIM items were the one
         genuine gap: a real, possibly-REVIEW-driving fact with no
         structured representation anywhere in remediation_summary. They
         remain additionally visible in the unchanged `gap_analysis` list
         too (any non-MET item), same as before.

    3. SUBMISSION_GATING (no unsupported domains):
       - mandatory + unresolved (status != MET) -> blocked_items
         (matches compute_bid_readiness()'s BLOCKED condition exactly)
       - non-mandatory + unresolved -> action_required_items (matches
         compute_bid_readiness()'s "any unresolved gating" ACTION_REQUIRED
         fallback)

    4. PROCEDURAL / FUTURE_CONTRACTUAL_COMMITMENT (no unsupported
       domains): unresolved (status != MET) -> action_required_items,
       regardless of mandatory — matches compute_bid_readiness() treating
       both natures identically (mandatory drives the status, but any
       unresolved instance is real bid-preparation work either way).

    MET, fully-supported results contribute to no bucket — this
    function only ever surfaces things that still need attention,
    exactly per the "must not flatten every unresolved requirement into
    one blocker list" requirement.

    confirmed_requirement_ids (bid-readiness confirmation feature):
    forwarded only to compute_bid_readiness() above, which is what
    changes bid_readiness's own READY/ACTION_REQUIRED/BLOCKED value.
    Per-item bucket membership (blocked_items/action_required_items) is
    NOT changed by confirmation — a confirmed item stays in exactly the
    bucket its (requirement_nature, mandatory, status) already puts it
    in, so it remains visible rather than silently disappearing. The
    caller (decision_service/app.api.v1.evaluation) is responsible for
    marking each resulting GapAnalysisEntry's `confirmed`/`confirmed_at`
    fields from the same confirmation set, so the UI can show a
    checkmark on an item that is still listed.

    overridden_requirement_ids (qualification override feature):
    forwarded only to compute_qualification() above, which is what
    changes qualification's own PASS/CONDITIONAL/FAIL value. Exactly the
    same "stays visible" rule applies here — an overridden item is NOT
    removed from qualification_gaps/human_review_items just because it
    stopped blocking the overall qualification value; the caller is
    responsible for marking each resulting GapAnalysisEntry's
    `overridden`/`overridden_by`/`overridden_at`/`override_note` fields,
    so the UI can show it as an explicit administrator override on an
    item that is still listed — never as if it were genuinely MET.
    """
    # Boundary rule (bid-readiness confirmation feature): confirmed_requirement_ids
    # is passed ONLY into compute_bid_readiness(), never compute_qualification().
    # Boundary rule (qualification override feature): overridden_requirement_ids
    # is passed ONLY into compute_qualification(), never compute_bid_readiness().
    # The two parameters are deliberately kept on separate axes — see each
    # function's own docstring and the frozen architecture decision.
    qualification = compute_qualification(results, overridden_requirement_ids)
    bid_readiness = compute_bid_readiness(results, confirmed_requirement_ids)

    qualification_gaps: list[MatchResult] = []
    blocked_items: list[MatchResult] = []
    action_required_items: list[MatchResult] = []
    coverage_gaps: list[MatchResult] = []
    human_review_items: list[MatchResult] = []
    optional_capability_gaps: list[MatchResult] = []

    for r in results:
        if r.unsupported_domains:
            coverage_gaps.append(r)
            continue

        if r.requirement_nature == RequirementNature.CAPABILITY_CLAIM:
            # NOT_MET and REVIEW_REQUIRED/CONDITIONAL are mutually
            # exclusive MatchStatus values, so if/elif here is equivalent
            # to the prior two independent `if`s for MET/NOT_MET/
            # REVIEW_REQUIRED/CONDITIONAL items alike — restructured only
            # to make room for the mandatory/non-mandatory NOT_MET split
            # below without duplicating the status check.
            if r.status == MatchStatus.NOT_MET:
                if r.mandatory:
                    qualification_gaps.append(r)
                else:
                    optional_capability_gaps.append(r)
            elif r.status in (MatchStatus.REVIEW_REQUIRED, MatchStatus.CONDITIONAL):
                human_review_items.append(r)

        elif r.requirement_nature == RequirementNature.SUBMISSION_GATING:
            if r.status != MatchStatus.MET:
                if r.mandatory:
                    blocked_items.append(r)
                else:
                    action_required_items.append(r)

        elif r.requirement_nature in (RequirementNature.PROCEDURAL, RequirementNature.FUTURE_CONTRACTUAL_COMMITMENT):
            if r.status != MatchStatus.MET:
                action_required_items.append(r)

    return RemediationClassification(
        qualification=qualification,
        bid_readiness=bid_readiness,
        qualification_gaps=qualification_gaps,
        blocked_items=blocked_items,
        action_required_items=action_required_items,
        coverage_gaps=coverage_gaps,
        human_review_items=human_review_items,
        optional_capability_gaps=optional_capability_gaps,
    )


# One severity scale drives both the recommendation and its risk level —
# avoids two separate, potentially inconsistent severity computations.
RECOMMENDATION_RISK_MAP = {
    RecommendationType.NO_GO: RiskLevel.CRITICAL,
    RecommendationType.CONDITIONAL_GO: RiskLevel.HIGH,
    RecommendationType.REVIEW: RiskLevel.MEDIUM,
    RecommendationType.GO: RiskLevel.LOW,
}


def compute_confidence_propagation(
    results: list[MatchResult], entity_confidences: list[float], document_confidences: list[float]
) -> dict:
    """
    Weighted, not a simple average — matching_confidence carries the
    highest weight (0.50) since it represents the engine's core
    reasoning. Capped so one genuinely weak stage can't be hidden by
    averaging with several strong ones: overall can never exceed the
    lowest individual stage by more than 0.15.
    """
    matching_values = [r.matching_confidence for r in results] or [0.5]
    matching_confidence = round(sum(matching_values) / len(matching_values), 4)
    entity_confidence = round(sum(entity_confidences) / len(entity_confidences), 4) if entity_confidences else 0.5
    document_confidence = (
        round(sum(document_confidences) / len(document_confidences), 4) if document_confidences else 0.5
    )

    non_clean = sum(1 for r in results if r.status in (MatchStatus.REVIEW_REQUIRED, MatchStatus.CONDITIONAL))
    recommendation_confidence = round(1.0 - 0.5 * (non_clean / len(results)), 4) if results else 0.5

    stages = {
        "document_confidence": document_confidence,
        "entity_confidence": entity_confidence,
        "matching_confidence": matching_confidence,
        "recommendation_confidence": recommendation_confidence,
    }
    weights = {
        "document_confidence": 0.15,
        "entity_confidence": 0.15,
        "matching_confidence": 0.50,
        "recommendation_confidence": 0.20,
    }
    weighted_average = sum(stages[k] * weights[k] for k in stages)
    lowest_stage = min(stages.values())
    overall_confidence = round(min(weighted_average, lowest_stage + 0.15), 4)

    return {**stages, "overall_confidence": overall_confidence}


def build_executive_summary(
    recommendation_type: RecommendationType, results: list[MatchResult], confidence: dict
) -> str:
    """Deterministic string template, not an LLM call — see the strategy note on why."""
    total = len(results)
    met = sum(1 for r in results if r.status == MatchStatus.MET)
    not_met = sum(1 for r in results if r.status == MatchStatus.NOT_MET)
    review = sum(1 for r in results if r.status == MatchStatus.REVIEW_REQUIRED)
    conditional = sum(1 for r in results if r.status == MatchStatus.CONDITIONAL)
    mandatory_not_met = sum(1 for r in results if r.mandatory and r.status == MatchStatus.NOT_MET)

    return (
        f"Recommendation: {recommendation_type.value.upper().replace('_', ' ')}. "
        f"Evaluated {total} tender requirement(s): {met} met, {not_met} not met, "
        f"{review} requiring review, {conditional} conditionally met. "
        f"{mandatory_not_met} mandatory requirement(s) are not met. "
        f"Overall confidence: {confidence['overall_confidence']}. "
        f"See the Compliance Matrix for the complete per-requirement evidence and reasoning "
        f"behind this recommendation."
    )
