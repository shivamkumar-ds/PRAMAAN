"""
Schemas the LLM's JSON output must validate against for SIH26100 bidder
document extraction (Phase 4) -- the same boundary role as
app/schemas/extraction.py's CertificationExtraction/EmployeeExtraction/
ProjectExtraction: a response that fails validation fails the whole
extraction (BidderDocument.extraction_status -> FAILED) rather than
partially-trusted data being persisted.

Each schema mirrors one ComplianceCategory.code from Phase 1's seed data
(app/services/sih/compliance_category_service.DEFAULT_CATEGORIES). Only
the fields the corresponding registry adapter actually reads (see
app/services/sih/registry_adapters.py) are ever forwarded into
declared_facts by app/services/sih/document_declared_facts.py -- every
other extracted field here is informational/audit-only, shown to the
officer but never itself a compliance input.

BlacklistingExtraction is the clearest example of the AI/deterministic
boundary (Phase 4 prompt's Part 5): even if a document explicitly claims
"not blacklisted," that claim is never trusted or forwarded as a
declared fact. Blacklisting status is, and remains, a pure registry/PAN
lookup via BlacklistingAdapter -- this schema exists only so an officer
can see what a debarment-related document said, for audit purposes.
"""

from pydantic import BaseModel


class UdyamExtraction(BaseModel):
    udyam_number: str | None = None
    entity_name: str | None = None
    pan: str | None = None
    address: str | None = None
    status: str | None = None
    enterprise_type: str | None = None


class GSTExtraction(BaseModel):
    gstin: str | None = None
    legal_name: str | None = None
    trade_name: str | None = None
    pan: str | None = None
    status: str | None = None
    filing_status: str | None = None


class PANITRExtraction(BaseModel):
    pan: str | None = None
    legal_name: str | None = None
    assessment_year: str | None = None
    itr_years_claimed: list[str] | None = None
    gross_total_income: str | None = None


class EPFOESICExtraction(BaseModel):
    establishment_id: str | None = None
    legal_name: str | None = None
    employer_name: str | None = None
    status: str | None = None


class BlacklistingExtraction(BaseModel):
    """
    Informational/audit-only -- see module docstring. Never forwarded
    into declared_facts; the actual blacklisting verdict always comes
    from BlacklistingAdapter's registry/PAN lookup, unmodified since
    Phase 1.
    """

    entity_name: str | None = None
    is_blacklisted: bool | None = None
    authority: str | None = None
    order_reference: str | None = None
    effective_date: str | None = None
    expiry_date: str | None = None


# --- SIH26100 demo-scope expansion ---
#
# IdentifierStatusExtraction is a deliberately generic, shared schema for
# every newly-added category whose source document reduces to "one
# authoritative identifier, one entity name, one status" -- MCA21, EPFO,
# ESIC, NSIC, and Startup India. Five near-identical 3-field schemas
# would be pure duplication; see registry_adapters.py's
# _RegistryLookupAdapter for the same reasoning applied on the
# verification side. OEM Authorization, DigiLocker, and Make in India get
# their own schemas below because their documents genuinely carry
# different fields.
class IdentifierStatusExtraction(BaseModel):
    identifier: str | None = None
    entity_name: str | None = None
    status: str | None = None


class OEMAuthorizationDocExtraction(BaseModel):
    authorization_number: str | None = None
    oem_name: str | None = None
    authorized_bidder_name: str | None = None
    status: str | None = None


class DigiLockerDocExtraction(BaseModel):
    digilocker_reference: str | None = None
    entity_name: str | None = None


class MakeInIndiaDocExtraction(BaseModel):
    declared_local_content_percentage: float | None = None
    entity_name: str | None = None


# One entry per active ComplianceCategory.code with a document-upload
# path. blacklisting has none (informational/audit-only, see
# BlacklistingExtraction's docstring above) -- extensible later by
# adding both an adapter and a schema together, never one without the
# other.
CATEGORY_EXTRACTION_SCHEMAS: dict[str, type[BaseModel]] = {
    "udyam": UdyamExtraction,
    "gst": GSTExtraction,
    "pan_itr": PANITRExtraction,
    "epfo_esic": EPFOESICExtraction,
    "blacklisting": BlacklistingExtraction,
    "mca21": IdentifierStatusExtraction,
    "epfo": IdentifierStatusExtraction,
    "esic": IdentifierStatusExtraction,
    "nsic": IdentifierStatusExtraction,
    "startup_india": IdentifierStatusExtraction,
    "oem_authorization": OEMAuthorizationDocExtraction,
    "digilocker": DigiLockerDocExtraction,
    "make_in_india": MakeInIndiaDocExtraction,
}
