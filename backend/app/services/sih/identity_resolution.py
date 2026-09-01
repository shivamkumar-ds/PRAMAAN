"""
PAN-anchored identity resolution -- SIH26100 Phase 4.

The PAN-match/PAN-mismatch determination itself is NOT implemented here.
It already exists, unmodified, in app/services/sih/registry_adapters.py
(GSTAdapter, PANIncomeTaxAdapter, BlacklistingAdapter all compare PAN
strings exactly and are never softened by a confidence score -- this was
Phase 1's frozen design, itself following the Phase 0 report's identity-
resolution proposal). Phase 4 does not touch that comparison at all: an
extracted document's PAN reaches the same adapters through the exact same
declared_facts dict verify_submission() already accepts, so PAN mismatch
detection is unchanged from Phase 1/2/3.

What Phase 4 actually adds is the fallback path the Phase 4 brief asks
for: when a PAN is unavailable (a document that doesn't carry one, or a
bidder record with no PAN on file), a normalized/fuzzy name-match
confidence gives the officer a *reviewable* signal instead of nothing --
explicitly never an authoritative substitute for a real PAN match. This
module computes that confidence only; it never writes a VerificationResult
and never decides compliance, keeping the same AI/deterministic boundary
Phase 1 already established.

difflib.SequenceMatcher (Python's standard library), not an LLM call --
deterministic, explainable, and keeps the "PAN/identity comparisons are
never AI-softened" invariant intact even for the fuzzy fallback: nothing
here asks a model to judge whether two names "seem like" the same entity.
"""

import re
from difflib import SequenceMatcher


def normalize_name(name: str | None) -> str:
    """Lowercases, strips common legal-entity suffixes/punctuation, and
    collapses whitespace -- so "ABC Engineering Pvt. Ltd." and "ABC
    ENGINEERING PRIVATE LIMITED" compare as near-identical rather than
    being penalized for formatting differences that carry no identity
    signal."""
    if not name:
        return ""
    lowered = name.lower()
    lowered = re.sub(r"[.,]", "", lowered)
    for suffix in (
        "private limited",
        "pvt ltd",
        "pvt. ltd.",
        "limited",
        "ltd",
        "llp",
        "inc",
        "corporation",
        "corp",
    ):
        lowered = re.sub(rf"\b{re.escape(suffix)}\b", "", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def fuzzy_name_match(name_a: str | None, name_b: str | None) -> float:
    """Returns a 0.0-1.0 similarity score between two entity names after
    normalization. 0.0 if either name is missing -- an absent name is not
    "somewhat similar" to anything, it's simply not comparable."""
    a, b = normalize_name(name_a), normalize_name(name_b)
    if not a or not b:
        return 0.0
    return round(SequenceMatcher(None, a, b).ratio(), 4)


def resolve_pan_identity(declared_pan: str | None, registry_pan: str | None) -> str:
    """
    Documents the exact three-way outcome the Phase 4 brief specifies:
      - "match": both present and equal.
      - "mismatch": both present and different -- CRITICAL, per
        GSTAdapter/PANIncomeTaxAdapter, never softened.
      - "unavailable": one or both missing -- falls back to fuzzy name
        matching (see fuzzy_name_match above), which stays reviewable,
        never an automatic pass.

    This function is informational/explanatory for the frontend and for
    tests -- the actual VerificationResult.status an officer sees still
    comes only from the Phase 1 adapters, which already implement this
    exact same three-way logic independently for GST/PAN/blacklisting.
    """
    if not declared_pan or not registry_pan:
        return "unavailable"
    return "match" if declared_pan.strip().upper() == registry_pan.strip().upper() else "mismatch"
