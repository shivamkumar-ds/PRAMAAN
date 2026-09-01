"""
Collusion Radar -- SIH26100 minimal-real engine (Phase 4 of the
governing directive).

Transparent, deterministic heuristics over data that genuinely exists in
this domain today -- BidderSubmission.bid_amount (added alongside this
engine; see app/models/sih/bidder.py) and repeated bidder participation
across this company/tenant's Procurements. Every indicator states
exactly what was observed and why it's worth a look; nothing here is a
verdict. score is a 0-100 aggregate of triggered-indicator severity,
explicitly labeled as an attention score, never a probability or
certainty of collusion. COLLUSION IS NEVER STATED AS CONFIRMED ANYWHERE
IN THIS MODULE OR ITS OUTPUT -- see CollusionReport.disclaimer, which is
always populated and always the same text, so no caller can render this
without it.

Heuristics implemented (only where the available data actually supports
them, per the brief -- no "winner" outcome or bid-value field existed
anywhere in this domain before bid_amount was added for this engine):

  1. Narrow bid spread: among this procurement's submissions that have a
     bid_amount, a low coefficient of variation (stdev / mean) across
     values -- bids clustered unusually close together.
  2. Identical bid amounts: two or more submissions with the exact same
     bid_amount -- a stronger, more specific version of (1).
  3. Repeated bidder combinations: a pair of bidders in this procurement
     who have also both submitted against several of this company's
     OTHER procurements together -- frequent co-participation, not
     itself unusual for a small local vendor pool, but worth surfacing.

  4. Repeated winner: this procurement's awarded bidder (Procurement.
     awarded_bidder_id -- see app/models/sih/procurement.py's docstring
     for why this is only ever set explicitly by an officer, never
     inferred) has also been the awarded_bidder_id on several of this
     SAME company/tenant's OTHER procurements. A single vendor winning
     repeatedly is not inherently wrong -- it can simply mean the best or
     only qualified local vendor for a category -- but disproportionate
     award concentration to one bidder is a documented collusion/
     favoritism risk factor worth an officer's attention (see Huber &
     Imhof, "Machine learning with screens for detecting bid-rigging
     cartels," International Journal of Industrial Organization, 2019,
     on repeated-winner/bidder-concentration signals as one input among
     several screening heuristics -- never used here as a standalone
     accusation). Strictly tenant-scoped: only awarded_bidder_id values
     on Procurement rows belonging to this same company_id are ever
     counted -- see get_collusion_indicators()'s ownership check and
     _repeated_winner_indicator()'s query, both filtered on company_id,
     exactly like every other heuristic in this module. This was
     originally out of scope (no awarded_bidder_id field existed at all
     -- see this module's git history for the original "explicitly NOT
     implemented" reasoning); it's implemented now that the field exists,
     following the same honest-data-only rule that kept it out before.

Explicitly still NOT implemented, because the data doesn't exist to
support it honestly: anything that would require knowing bid prices or
participation for procurements outside this company/tenant, or inferring
an award from OfficerDecision.APPROVE (which means "found compliant,"
never "won" -- conflating the two remains exactly the kind of
unsupported claim the brief warns against; only an explicit
awarded_bidder_id counts as an award anywhere in this module).
"""

import statistics
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.sih.bidder import Bidder, BidderSubmission
from app.services.sih import procurement_service

# Coefficient of variation below this threshold is flagged as "narrow" --
# a conservative bar (5%): real competitive bids on a well-specified
# GeM line item can legitimately cluster somewhat; anything tighter is
# unusual enough to be worth an officer's attention, not proof of anything.
_NARROW_SPREAD_CV_THRESHOLD = 0.05
# A pair of bidders who have co-participated in this many OTHER
# procurements (beyond the current one) is flagged as a repeated
# combination.
_REPEATED_COMBINATION_MIN_OTHER_PROCUREMENTS = 2
# A bidder who has been the awarded_bidder_id on at least this many
# procurements within this company/tenant is flagged as a repeated
# winner -- matching _REPEATED_COMBINATION_MIN_OTHER_PROCUREMENTS's style
# of a small, conservative, explainable threshold rather than a tuned
# statistical cutoff (there is no historical dataset in this prototype to
# tune one against).
_REPEATED_WINNER_MIN_AWARDS = 3

DISCLAIMER = (
    "These are transparent, rule-based indicators over available bid and participation data -- "
    "never a determination that collusion has occurred. Any flagged pattern requires an officer's "
    "independent review and may have an entirely legitimate explanation."
)


@dataclass
class CollusionIndicator:
    code: str
    label: str
    detail: str
    severity: str  # "low" | "medium" | "high"


@dataclass
class CollusionReport:
    procurement_id: uuid.UUID
    indicators: list[CollusionIndicator] = field(default_factory=list)
    score: int = 0  # 0-100, an attention score -- never a probability of collusion
    disclaimer: str = DISCLAIMER


def get_collusion_indicators(db: Session, procurement_id: uuid.UUID, company_id: uuid.UUID) -> CollusionReport:
    procurement_service.get_procurement(db, procurement_id, company_id)  # tenant-ownership check

    submissions = (
        db.query(BidderSubmission).filter(BidderSubmission.procurement_id == procurement_id).all()
    )

    indicators: list[CollusionIndicator] = []
    indicators.extend(_bid_value_indicators(submissions))
    indicators.extend(_repeated_combination_indicators(db, procurement_id, company_id, submissions))
    indicators.extend(_repeated_winner_indicator(db, procurement_id, company_id))

    score = _compute_score(indicators)
    return CollusionReport(procurement_id=procurement_id, indicators=indicators, score=score)


def _compute_score(indicators: list[CollusionIndicator]) -> int:
    weights = {"low": 15, "medium": 30, "high": 45}
    raw = sum(weights.get(i.severity, 0) for i in indicators)
    return min(raw, 100)


def _bid_value_indicators(submissions: list[BidderSubmission]) -> list[CollusionIndicator]:
    priced = [(s, s.bid_amount) for s in submissions if s.bid_amount is not None]
    if len(priced) < 2:
        # Honestly nothing to compute -- fewer than two priced bids in
        # this procurement, never assumed/interpolated.
        return []

    values = [float(v) for _s, v in priced]
    mean = statistics.fmean(values)
    indicators: list[CollusionIndicator] = []

    if mean > 0:
        stdev = statistics.pstdev(values)
        cv = stdev / mean
        if cv < _NARROW_SPREAD_CV_THRESHOLD:
            indicators.append(
                CollusionIndicator(
                    code="narrow_bid_spread",
                    label="Unusually narrow spread across bid values",
                    detail=(
                        f"{len(priced)} bids ranging from {min(values):,.2f} to {max(values):,.2f} "
                        f"(mean {mean:,.2f}) cluster within a {cv * 100:.1f}% coefficient of variation -- "
                        "tighter than typical independent competitive bidding."
                    ),
                    severity="medium",
                )
            )

    duplicate_groups: dict[Decimal, list[str]] = defaultdict(list)
    for submission, amount in priced:
        duplicate_groups[amount].append(str(submission.bidder_id))
    for amount, bidder_ids in duplicate_groups.items():
        if len(bidder_ids) >= 2:
            indicators.append(
                CollusionIndicator(
                    code="identical_bid_amount",
                    label="Two or more bidders quoted an identical amount",
                    detail=(
                        f"{len(bidder_ids)} submissions quoted exactly {float(amount):,.2f} -- an exact "
                        "match on a freely-chosen bid value is uncommon by chance alone."
                    ),
                    severity="high",
                )
            )

    return indicators


def _repeated_combination_indicators(
    db: Session, procurement_id: uuid.UUID, company_id: uuid.UUID, submissions: list[BidderSubmission]
) -> list[CollusionIndicator]:
    bidder_ids = [s.bidder_id for s in submissions]
    if len(bidder_ids) < 2:
        return []

    # Every OTHER procurement in this company/tenant, and which of THIS
    # procurement's bidders also submitted there -- one query, grouped in
    # Python (the bidder pool per procurement is small; no need for a
    # heavier SQL self-join here).
    from app.models.sih.procurement import Procurement

    other_submissions = (
        db.query(BidderSubmission)
        .join(Procurement, Procurement.id == BidderSubmission.procurement_id)
        .filter(
            Procurement.company_id == company_id,
            BidderSubmission.procurement_id != procurement_id,
            BidderSubmission.bidder_id.in_(bidder_ids),
        )
        .all()
    )
    co_participation: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for s in other_submissions:
        co_participation[s.bidder_id].add(s.procurement_id)

    names_by_id = {
        b.id: b.legal_name for b in db.query(Bidder).filter(Bidder.id.in_(bidder_ids)).all()
    }

    indicators: list[CollusionIndicator] = []
    seen_pairs: set[frozenset] = set()
    for i, bidder_a in enumerate(bidder_ids):
        for bidder_b in bidder_ids[i + 1 :]:
            pair = frozenset((bidder_a, bidder_b))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            shared_procurements = co_participation.get(bidder_a, set()) & co_participation.get(bidder_b, set())
            if len(shared_procurements) >= _REPEATED_COMBINATION_MIN_OTHER_PROCUREMENTS:
                indicators.append(
                    CollusionIndicator(
                        code="repeated_bidder_combination",
                        label="Repeated bidder combination across procurements",
                        detail=(
                            f"{names_by_id.get(bidder_a, bidder_a)} and {names_by_id.get(bidder_b, bidder_b)} "
                            f"have both submitted against {len(shared_procurements)} other procurements in "
                            "this account, beyond this one."
                        ),
                        severity="low",
                    )
                )

    return indicators


def _repeated_winner_indicator(
    db: Session, procurement_id: uuid.UUID, company_id: uuid.UUID
) -> list[CollusionIndicator]:
    """
    See this module's docstring, point 4, for the reasoning and the Huber
    & Imhof (2019) citation. Only ever looks at this procurement's own
    awarded_bidder_id and other Procurement rows filtered on the SAME
    company_id -- never any other tenant's data (tenant isolation was an
    explicit, confirmed constraint for this feature).
    """
    from app.models.sih.procurement import Procurement

    procurement = db.get(Procurement, procurement_id)
    if procurement is None or procurement.awarded_bidder_id is None:
        # Honestly nothing to compute -- this procurement itself has no
        # recorded award yet. Never inferred from anything else.
        return []

    awarded_bidder_id = procurement.awarded_bidder_id
    award_count = (
        db.query(Procurement.id)
        .filter(Procurement.company_id == company_id, Procurement.awarded_bidder_id == awarded_bidder_id)
        .count()
    )
    if award_count < _REPEATED_WINNER_MIN_AWARDS:
        return []

    bidder = db.get(Bidder, awarded_bidder_id)
    bidder_name = bidder.legal_name if bidder is not None else str(awarded_bidder_id)
    return [
        CollusionIndicator(
            code="repeated_winner",
            label="Bidder has been awarded a disproportionate share of procurements",
            detail=(
                f"{bidder_name} has been recorded as the awarded bidder on {award_count} procurements in "
                "this account, including this one. Repeated wins by the same vendor can have an entirely "
                "legitimate explanation (e.g. the best or only qualified local vendor for this category) "
                "and are not themselves proof of favoritism or collusion -- but award concentration is a "
                "documented screening signal worth an officer's review (see Huber & Imhof, 'Machine "
                "learning with screens for detecting bid-rigging cartels,' International Journal of "
                "Industrial Organization, 2019)."
            ),
            severity="medium",
        )
    ]
