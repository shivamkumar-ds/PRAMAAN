"""
Government Registry Adapter -- SIH26100.

GovernmentRegistryAdapter is the seam behind which every compliance
category's "government registry" lookup happens. Phase 1 implements it
against RegistryRecord (deterministic mock data seeded into Postgres --
see mock_registry_data.py), never a real government API: the SIH26100
problem statement itself requires this to be simulated ("simulate/mock
government portal integrations because real APIs are unavailable").

The interface is deliberately narrow and uniform across every category
-- the same shape already used elsewhere in this codebase for exactly
this kind of seam (app/core/storage.py's local/GCS swap,
app/agents/llm_client.py's provider swap) -- so a real adapter
implementation can later replace a mock one without changing any caller.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.sih.compliance import RegistryRecord
from app.models.sih.enums import ComplianceVerificationStatus


@dataclass
class AdapterVerificationResult:
    """What one adapter.verify() call produces -- consumed directly by
    app/services/sih/verification_service.py to build a VerificationResult row."""

    status: ComplianceVerificationStatus
    registry_value: dict | None
    discrepancies: list[str]
    source: str
    reason: str
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    confidence: float | None = None


class GovernmentRegistryAdapter(abc.ABC):
    """One adapter per ComplianceCategory.adapter_key."""

    category_code: str
    source_name: str

    @abc.abstractmethod
    def verify(
        self, db: Session, bidder_identity: dict, declared_facts: dict
    ) -> AdapterVerificationResult:
        """
        bidder_identity: at minimum {"pan": str | None} -- the
        deterministic identity anchor (Phase 0 report's identity-
        resolution proposal). Individual adapters may also use other
        identity fields where a category's registry is naturally keyed
        on something other than PAN.

        declared_facts: what the bidder claims for this category (e.g.
        {"udyam_number": "...", "entity_name": "..."}). Phase 1 has no
        document-extraction/OCR pipeline yet -- extraction is explicitly
        deferred to a later phase -- so this is supplied directly by the
        caller (a seed/test harness today) rather than produced by OCR.
        """
        raise NotImplementedError


def _lookup_registry_record(
    db: Session, category_code: str, identifier_type: str, identifier_value: str | None
) -> RegistryRecord | None:
    if not identifier_value:
        return None
    return (
        db.query(RegistryRecord)
        .filter(
            RegistryRecord.category_code == category_code,
            RegistryRecord.identifier_type == identifier_type,
            RegistryRecord.identifier_value == identifier_value,
            RegistryRecord.is_active.is_(True),
        )
        .one_or_none()
    )


class UdyamAdapter(GovernmentRegistryAdapter):
    category_code = "udyam"
    source_name = "Mock Udyam / MSME Registry"

    def verify(self, db, bidder_identity, declared_facts):
        udyam_number = declared_facts.get("udyam_number")
        if not udyam_number:
            return AdapterVerificationResult(
                status=ComplianceVerificationStatus.MISSING,
                registry_value=None,
                discrepancies=[],
                source=self.source_name,
                reason="No Udyam registration number was declared.",
            )
        record = _lookup_registry_record(db, self.category_code, "udyam_number", udyam_number)
        if record is None:
            return AdapterVerificationResult(
                status=ComplianceVerificationStatus.MISMATCH,
                registry_value=None,
                discrepancies=["Udyam number not found in registry."],
                source=self.source_name,
                reason="Declared Udyam number does not resolve to any registry record.",
            )
        discrepancies = []
        declared_name = (declared_facts.get("entity_name") or "").strip().lower()
        registry_name = (record.record_data.get("entity_name") or "").strip().lower()
        if declared_name and registry_name and declared_name != registry_name:
            discrepancies.append(
                f"Declared entity name '{declared_facts.get('entity_name')}' does not exactly "
                f"match registry name '{record.record_data.get('entity_name')}'."
            )
        status = (
            ComplianceVerificationStatus.VERIFIED
            if not discrepancies
            else ComplianceVerificationStatus.MISMATCH
        )
        return AdapterVerificationResult(
            status=status,
            registry_value=record.record_data,
            discrepancies=discrepancies,
            source=self.source_name,
            reason=(
                "Udyam registration verified against registry."
                if status == ComplianceVerificationStatus.VERIFIED
                else "Udyam registration found but declared details differ from registry."
            ),
        )


class GSTAdapter(GovernmentRegistryAdapter):
    category_code = "gst"
    source_name = "Mock GSTN Registry"

    def verify(self, db, bidder_identity, declared_facts):
        gstin = declared_facts.get("gstin")
        if not gstin:
            return AdapterVerificationResult(
                status=ComplianceVerificationStatus.MISSING,
                registry_value=None,
                discrepancies=[],
                source=self.source_name,
                reason="No GSTIN was declared.",
            )
        record = _lookup_registry_record(db, self.category_code, "gstin", gstin)
        if record is None:
            return AdapterVerificationResult(
                status=ComplianceVerificationStatus.MISMATCH,
                registry_value=None,
                discrepancies=["GSTIN not found in registry."],
                source=self.source_name,
                reason="Declared GSTIN does not resolve to any registry record.",
            )
        pan = bidder_identity.get("pan")
        registry_pan = record.record_data.get("pan")
        if pan and registry_pan and pan != registry_pan:
            # PAN mismatch is a deterministic, non-negotiable critical
            # finding -- Phase 0 report's identity-resolution proposal.
            # Never softened by a confidence score.
            return AdapterVerificationResult(
                status=ComplianceVerificationStatus.CRITICAL_FAIL,
                registry_value=record.record_data,
                discrepancies=[
                    f"GSTIN's registered PAN '{registry_pan}' does not match bidder PAN '{pan}'."
                ],
                source=self.source_name,
                reason=(
                    "Critical: the PAN linked to this GSTIN in the registry does not match "
                    "the bidder's declared PAN."
                ),
            )
        discrepancies = []
        registry_status = record.record_data.get("status")
        if registry_status and registry_status.lower() != "active":
            discrepancies.append(f"GST registration status is '{registry_status}', not active.")
        verdict = (
            ComplianceVerificationStatus.MISMATCH
            if discrepancies
            else ComplianceVerificationStatus.VERIFIED
        )
        return AdapterVerificationResult(
            status=verdict,
            registry_value=record.record_data,
            discrepancies=discrepancies,
            source=self.source_name,
            reason=(
                "GST registration verified."
                if verdict == ComplianceVerificationStatus.VERIFIED
                else "GST registration found but has an issue."
            ),
        )


class PANIncomeTaxAdapter(GovernmentRegistryAdapter):
    category_code = "pan_itr"
    source_name = "Mock Income Tax / PAN Registry"

    def verify(self, db, bidder_identity, declared_facts):
        pan = bidder_identity.get("pan") or declared_facts.get("pan")
        if not pan:
            # PAN missing entirely is treated as an automatic gating
            # failure, not just a missing checkbox -- Phase 0 report:
            # GeM registration is generally PAN-anchored, and PAN is the
            # identity anchor every other adapter relies on.
            return AdapterVerificationResult(
                status=ComplianceVerificationStatus.CRITICAL_FAIL,
                registry_value=None,
                discrepancies=["No PAN on file for this bidder."],
                source=self.source_name,
                reason=(
                    "Critical: PAN is the identity anchor for every other category and "
                    "none was declared."
                ),
            )
        record = _lookup_registry_record(db, self.category_code, "pan", pan)
        if record is None:
            return AdapterVerificationResult(
                status=ComplianceVerificationStatus.MISMATCH,
                registry_value=None,
                discrepancies=["PAN not found in Income Tax registry."],
                source=self.source_name,
                reason="Declared PAN does not resolve to any registry record.",
            )
        filed_years = record.record_data.get("itr_filed_years", [])
        declared_years = declared_facts.get("itr_years_claimed", [])
        missing_years = [y for y in declared_years if y not in filed_years]
        discrepancies = [f"ITR for {y} not found in registry." for y in missing_years]
        status = (
            ComplianceVerificationStatus.MISMATCH
            if discrepancies
            else ComplianceVerificationStatus.VERIFIED
        )
        return AdapterVerificationResult(
            status=status,
            registry_value=record.record_data,
            discrepancies=discrepancies,
            source=self.source_name,
            reason=(
                "PAN and ITR filings verified."
                if status == ComplianceVerificationStatus.VERIFIED
                else "PAN verified but one or more claimed ITR years are not on file."
            ),
        )


class EPFOESICAdapter(GovernmentRegistryAdapter):
    category_code = "epfo_esic"
    source_name = "Mock EPFO/ESIC Registry"

    def verify(self, db, bidder_identity, declared_facts):
        establishment_id = declared_facts.get("establishment_id")
        if not establishment_id:
            return AdapterVerificationResult(
                status=ComplianceVerificationStatus.MISSING,
                registry_value=None,
                discrepancies=[],
                source=self.source_name,
                reason="No EPFO/ESIC establishment ID was declared.",
            )
        record = _lookup_registry_record(db, self.category_code, "establishment_id", establishment_id)
        if record is None:
            return AdapterVerificationResult(
                status=ComplianceVerificationStatus.MISMATCH,
                registry_value=None,
                discrepancies=["Establishment ID not found in registry."],
                source=self.source_name,
                reason="Declared EPFO/ESIC establishment ID does not resolve to any registry record.",
            )
        registry_status = (record.record_data.get("status") or "").lower()
        discrepancies = (
            [] if registry_status == "active" else [f"Establishment status is '{registry_status}', not active."]
        )
        verdict = (
            ComplianceVerificationStatus.VERIFIED
            if not discrepancies
            else ComplianceVerificationStatus.MISMATCH
        )
        return AdapterVerificationResult(
            status=verdict,
            registry_value=record.record_data,
            discrepancies=discrepancies,
            source=self.source_name,
            reason=(
                "EPFO/ESIC registration verified."
                if verdict == ComplianceVerificationStatus.VERIFIED
                else "EPFO/ESIC registration found but not currently active."
            ),
        )


class BlacklistingAdapter(GovernmentRegistryAdapter):
    category_code = "blacklisting"
    source_name = "Mock Central Debarment Registry"

    def verify(self, db, bidder_identity, declared_facts):
        pan = bidder_identity.get("pan")
        record = _lookup_registry_record(db, self.category_code, "pan", pan) if pan else None
        if record is not None and record.record_data.get("is_blacklisted"):
            return AdapterVerificationResult(
                status=ComplianceVerificationStatus.CRITICAL_FAIL,
                registry_value=record.record_data,
                discrepancies=["Bidder has an active debarment/blacklisting record."],
                source=self.source_name,
                reason="Critical: bidder is currently blacklisted/debarred.",
            )
        return AdapterVerificationResult(
            status=ComplianceVerificationStatus.VERIFIED,
            registry_value=(record.record_data if record else {"is_blacklisted": False}),
            discrepancies=[],
            source=self.source_name,
            reason="No active debarment found.",
        )


# ---------------------------------------------------------------------------
# SIH26100 demo-scope expansion (post-Phase 5): the remaining requested
# verification sources (MCA21, EPFO, ESIC, NSIC, Startup India, OEM
# Authorization, DigiLocker, Make in India). Same mock-only, deterministic-
# RegistryRecord-backed pattern as every adapter above -- no real
# government API, no second verification engine.
#
# EPFO and ESIC were previously one combined category/adapter
# (EPFOESICAdapter above, category_code "epfo_esic"). The demo brief asks
# for them to be visibly separate sources ("EPFO" and "ESIC" as distinct
# checklist entries), so EPFOAdapter/ESICAdapter below are the new,
# separately-registered replacements; EPFOESICAdapter and its
# "epfo_esic" category are left entirely in place (code, tests,
# RegistryRecord seed data, extraction prompt/schema all untouched) since
# other tests and any already-confirmed historical documents still
# reference it by that code -- it is simply deactivated in
# compliance_category_service.DEFAULT_CATEGORIES in favour of the split.
#
# _RegistryLookupAdapter is the shared base for every category whose mock
# verification reduces to "bidder declares one identifier -> look it up
# in RegistryRecord -> VERIFIED if found and status is in ok_statuses
# (optionally cross-checking a declared name), else MISMATCH; MISSING if
# nothing was declared." That is a faithful description of MCA21, EPFO,
# ESIC, NSIC, and Startup India even though the real-world agencies behind
# them are unrelated -- sharing this base avoids five near-identical
# ~40-line classes. Blacklisting (above), OEM Authorization, DigiLocker,
# and Make in India keep their own classes below because their
# verification semantics genuinely differ (PAN-keyed negative check,
# cross-entity authorization match, document-authenticity cross-check,
# and a numeric threshold comparison respectively) -- forcing those into
# the same base would be exactly the "duplicate/force-fit" the brief
# warns against, in the other direction.
class _RegistryLookupAdapter(GovernmentRegistryAdapter):
    identifier_field: str  # key read from declared_facts
    identifier_type: str  # RegistryRecord.identifier_type for this category
    identifier_label: str  # human-readable label used in messages
    entity_name_field: str | None = "entity_name"  # optional cross-check field
    ok_statuses: tuple[str, ...] = ("active",)

    def verify(self, db, bidder_identity, declared_facts):
        identifier = declared_facts.get(self.identifier_field)
        if not identifier:
            return AdapterVerificationResult(
                status=ComplianceVerificationStatus.MISSING,
                registry_value=None,
                discrepancies=[],
                source=self.source_name,
                reason=f"No {self.identifier_label} was declared.",
            )
        record = _lookup_registry_record(db, self.category_code, self.identifier_type, identifier)
        if record is None:
            return AdapterVerificationResult(
                status=ComplianceVerificationStatus.MISMATCH,
                registry_value=None,
                discrepancies=[f"{self.identifier_label} not found in registry."],
                source=self.source_name,
                reason=f"Declared {self.identifier_label} does not resolve to any registry record.",
            )
        discrepancies: list[str] = []
        if self.entity_name_field:
            declared_name = (declared_facts.get(self.entity_name_field) or "").strip().lower()
            registry_name = (record.record_data.get("entity_name") or "").strip().lower()
            if declared_name and registry_name and declared_name != registry_name:
                discrepancies.append(
                    f"Declared name '{declared_facts.get(self.entity_name_field)}' does not exactly "
                    f"match registry name '{record.record_data.get('entity_name')}'."
                )
        registry_status = (record.record_data.get("status") or "").lower()
        if registry_status and registry_status not in self.ok_statuses:
            discrepancies.append(
                f"{self.identifier_label} status is '{registry_status}', not {'/'.join(self.ok_statuses)}."
            )
        status = (
            ComplianceVerificationStatus.VERIFIED if not discrepancies else ComplianceVerificationStatus.MISMATCH
        )
        return AdapterVerificationResult(
            status=status,
            registry_value=record.record_data,
            discrepancies=discrepancies,
            source=self.source_name,
            reason=(
                f"{self.identifier_label} verified against registry."
                if status == ComplianceVerificationStatus.VERIFIED
                else f"{self.identifier_label} found in registry but has an issue."
            ),
        )


class MCA21Adapter(_RegistryLookupAdapter):
    category_code = "mca21"
    source_name = "Mock MCA21 Registry"
    identifier_field = "cin"
    identifier_type = "cin"
    identifier_label = "CIN"


class EPFOAdapter(_RegistryLookupAdapter):
    category_code = "epfo"
    source_name = "Mock EPFO Registry"
    identifier_field = "establishment_id"
    identifier_type = "epfo_establishment_id"
    identifier_label = "EPFO establishment ID"
    entity_name_field = "legal_name"


class ESICAdapter(_RegistryLookupAdapter):
    category_code = "esic"
    source_name = "Mock ESIC Registry"
    identifier_field = "establishment_id"
    identifier_type = "esic_establishment_id"
    identifier_label = "ESIC establishment ID"
    entity_name_field = "legal_name"


class NSICAdapter(_RegistryLookupAdapter):
    category_code = "nsic"
    source_name = "Mock NSIC Registry"
    identifier_field = "nsic_registration_number"
    identifier_type = "nsic_registration_number"
    identifier_label = "NSIC registration number"


class StartupIndiaAdapter(_RegistryLookupAdapter):
    category_code = "startup_india"
    source_name = "Mock Startup India (DPIIT) Registry"
    identifier_field = "dpiit_number"
    identifier_type = "dpiit_number"
    identifier_label = "DPIIT recognition number"
    ok_statuses = ("recognized", "active")


class OEMAuthorizationAdapter(GovernmentRegistryAdapter):
    """
    Not a government registry at all in the real world -- it's the OEM's
    own authorization letter -- but SIH26100 asks for it alongside the
    government sources as one more uniform "third-party claim you can
    verify against a simulated authoritative record" category, so it's
    modeled the same way: a mock registry of (authorization_number ->
    which bidder that OEM actually authorized).
    """

    category_code = "oem_authorization"
    source_name = "Mock OEM Authorization Registry"

    def verify(self, db, bidder_identity, declared_facts):
        authorization_number = declared_facts.get("authorization_number")
        if not authorization_number:
            return AdapterVerificationResult(
                status=ComplianceVerificationStatus.MISSING,
                registry_value=None,
                discrepancies=[],
                source=self.source_name,
                reason="No OEM authorization number was declared.",
            )
        record = _lookup_registry_record(db, self.category_code, "authorization_number", authorization_number)
        if record is None:
            return AdapterVerificationResult(
                status=ComplianceVerificationStatus.MISMATCH,
                registry_value=None,
                discrepancies=["Authorization number not found in registry."],
                source=self.source_name,
                reason="Declared OEM authorization number does not resolve to any registry record.",
            )
        discrepancies = []
        declared_bidder = (declared_facts.get("bidder_name") or "").strip().lower()
        authorized_bidder = (record.record_data.get("authorized_bidder_name") or "").strip().lower()
        if declared_bidder and authorized_bidder and declared_bidder != authorized_bidder:
            discrepancies.append(
                f"This OEM authorization is issued to '{record.record_data.get('authorized_bidder_name')}', "
                "not the declared bidder."
            )
        status = (
            ComplianceVerificationStatus.VERIFIED if not discrepancies else ComplianceVerificationStatus.MISMATCH
        )
        return AdapterVerificationResult(
            status=status,
            registry_value=record.record_data,
            discrepancies=discrepancies,
            source=self.source_name,
            reason=(
                "OEM authorization verified."
                if status == ComplianceVerificationStatus.VERIFIED
                else "OEM authorization record found but does not match the declared bidder."
            ),
        )


class DigiLockerAdapter(GovernmentRegistryAdapter):
    """
    Cross-checks an uploaded document against a simulated DigiLocker-
    issued copy. A reference the mock registry marks as tampered is a
    deterministic CRITICAL_FAIL (a forged/altered document is exactly the
    "never soften with a confidence score" case the Phase 0 report's
    identity-resolution proposal describes for PAN mismatches) -- a
    reference that simply isn't found is an ordinary MISMATCH, since that
    more often just means the bidder hasn't linked DigiLocker yet.
    """

    category_code = "digilocker"
    source_name = "Mock DigiLocker Cross-Check"

    def verify(self, db, bidder_identity, declared_facts):
        reference = declared_facts.get("digilocker_reference")
        if not reference:
            return AdapterVerificationResult(
                status=ComplianceVerificationStatus.MISSING,
                registry_value=None,
                discrepancies=[],
                source=self.source_name,
                reason="No DigiLocker reference was declared.",
            )
        record = _lookup_registry_record(db, self.category_code, "digilocker_reference", reference)
        if record is None:
            return AdapterVerificationResult(
                status=ComplianceVerificationStatus.MISMATCH,
                registry_value=None,
                discrepancies=["DigiLocker reference not found."],
                source=self.source_name,
                reason="Declared DigiLocker reference does not resolve to any issued document.",
            )
        if record.record_data.get("tampered"):
            return AdapterVerificationResult(
                status=ComplianceVerificationStatus.CRITICAL_FAIL,
                registry_value=record.record_data,
                discrepancies=["Uploaded document does not match the DigiLocker-issued original."],
                source=self.source_name,
                reason="Critical: possible document tampering detected against the DigiLocker original.",
            )
        return AdapterVerificationResult(
            status=ComplianceVerificationStatus.VERIFIED,
            registry_value=record.record_data,
            discrepancies=[],
            source=self.source_name,
            reason="Document matches the DigiLocker-issued original.",
        )


class MakeInIndiaAdapter(GovernmentRegistryAdapter):
    """
    Unlike every other adapter here, this isn't an identifier lookup --
    it's a numeric-threshold comparison against what a certifying agency
    verified, keyed on the bidder's PAN (same identity anchor as
    BlacklistingAdapter) rather than a category-specific document number.
    """

    category_code = "make_in_india"
    source_name = "Mock Make in India / Local Content Registry"

    def verify(self, db, bidder_identity, declared_facts):
        raw_declared = declared_facts.get("local_content_percentage")
        if raw_declared in (None, ""):
            return AdapterVerificationResult(
                status=ComplianceVerificationStatus.MISSING,
                registry_value=None,
                discrepancies=[],
                source=self.source_name,
                reason="No local content percentage was declared.",
            )
        try:
            declared_pct = float(raw_declared)
        except (TypeError, ValueError):
            return AdapterVerificationResult(
                status=ComplianceVerificationStatus.MISMATCH,
                registry_value=None,
                discrepancies=[f"Declared local content '{raw_declared}' is not a valid percentage."],
                source=self.source_name,
                reason="Declared local content percentage could not be parsed.",
            )
        pan = bidder_identity.get("pan")
        record = _lookup_registry_record(db, self.category_code, "pan", pan) if pan else None
        if record is None:
            return AdapterVerificationResult(
                status=ComplianceVerificationStatus.MISMATCH,
                registry_value=None,
                discrepancies=["No certifying-agency local content verification found for this bidder."],
                source=self.source_name,
                reason="Declared local content percentage could not be cross-checked against any registry record.",
            )
        verified_pct = record.record_data.get("verified_local_content_percentage")
        threshold_pct = record.record_data.get("threshold_percentage", 50)
        discrepancies = []
        if verified_pct is not None and declared_pct > verified_pct + 0.01:
            discrepancies.append(
                f"Declared local content {declared_pct}% exceeds the certifying agency's verified "
                f"{verified_pct}%."
            )
        if verified_pct is not None and verified_pct < threshold_pct:
            discrepancies.append(
                f"Verified local content {verified_pct}% is below the {threshold_pct}% Make in India threshold."
            )
        status = (
            ComplianceVerificationStatus.VERIFIED if not discrepancies else ComplianceVerificationStatus.MISMATCH
        )
        return AdapterVerificationResult(
            status=status,
            registry_value=record.record_data,
            discrepancies=discrepancies,
            source=self.source_name,
            reason=(
                "Local content declaration verified against the certifying agency's record."
                if status == ComplianceVerificationStatus.VERIFIED
                else "Local content declaration does not match the certifying agency's verified record."
            ),
        )


_ADAPTER_REGISTRY: dict[str, type[GovernmentRegistryAdapter]] = {
    "udyam": UdyamAdapter,
    "gst": GSTAdapter,
    "pan_itr": PANIncomeTaxAdapter,
    "epfo_esic": EPFOESICAdapter,
    "blacklisting": BlacklistingAdapter,
    "mca21": MCA21Adapter,
    "epfo": EPFOAdapter,
    "esic": ESICAdapter,
    "nsic": NSICAdapter,
    "startup_india": StartupIndiaAdapter,
    "oem_authorization": OEMAuthorizationAdapter,
    "digilocker": DigiLockerAdapter,
    "make_in_india": MakeInIndiaAdapter,
}


def get_adapter(adapter_key: str) -> GovernmentRegistryAdapter:
    adapter_cls = _ADAPTER_REGISTRY.get(adapter_key)
    if adapter_cls is None:
        raise ValueError(f"No registry adapter implemented for '{adapter_key}' yet (roadmap category).")
    return adapter_cls()
