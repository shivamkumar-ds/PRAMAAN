"""
ComplianceCategory seeding -- SIH26100.

DEFAULT_CATEGORIES is the single source of truth for every category
SIH26100 names -- both the Alembic migrations (b8c9d0e1f2a3 seeds the
original 10; a later additive migration activates the roadmap ones and
adds mca21/epfo/esic -- see alembic/versions/) and
seed_default_categories() below (used directly by tests, which build
their own in-memory schema rather than running migrations) read from data
matching this list, so the paths should never drift. If this list
changes, update that migration's seed data to match.

Demo-scope expansion: every SIH26100-requested source is now active with
a real adapter in app/services/sih/registry_adapters.py -- "roadmap /
not yet implemented" no longer applies to any of them. mandatory_by_default
still distinguishes categories every submission is checked against
(udyam/gst/pan_itr/epfo/esic/blacklisting) from optional/claimed-benefit
categories (startup_india/nsic/oem_authorization/digilocker/make_in_india):
a bidder who never claims Startup India recognition is NOT_CLAIMED, not
penalized -- see verify_submission()'s "declared is None" branch and
compliance_summary_service's NOT_CLAIMED exclusion. mca21 is mandatory
(every company bidding under GeM should have a resolvable corporate
registration), matching the risk profile of udyam/epfo/esic.

epfo_esic (the original single Phase-1 category) is deactivated here in
favour of the epfo/esic split below -- its row, adapter (EPFOESICAdapter),
RegistryRecord data, and extraction prompt/schema are all left completely
untouched so any already-confirmed historical BidderDocument or
VerificationResult referencing it by that code still resolves; it simply
stops being counted in new verification runs (is_active gates that).
"""

from sqlalchemy.orm import Session

from app.models.sih.compliance import ComplianceCategory

DEFAULT_CATEGORIES: list[dict] = [
    # Mandatory -- every submission is checked against these.
    {
        "code": "udyam",
        "name": "Udyam / MSME Registration",
        "description": "Udyam registration status and entity match.",
        "mandatory_by_default": True,
        "risk_weight": 1.0,
        "adapter_key": "udyam",
        "is_active": True,
    },
    {
        "code": "gst",
        "name": "GST / GSTN Registration",
        "description": "GSTIN validity, status, and PAN linkage.",
        "mandatory_by_default": True,
        "risk_weight": 1.5,
        "adapter_key": "gst",
        "is_active": True,
    },
    {
        "code": "pan_itr",
        "name": "PAN / Income Tax / ITR",
        "description": "PAN identity anchor and ITR filing history.",
        "mandatory_by_default": True,
        "risk_weight": 2.0,
        "adapter_key": "pan_itr",
        "is_active": True,
    },
    {
        "code": "mca21",
        "name": "MCA21 (Corporate Registration)",
        "description": "Company Identification Number (CIN) status with the Ministry of Corporate Affairs.",
        "mandatory_by_default": True,
        "risk_weight": 1.5,
        "adapter_key": "mca21",
        "is_active": True,
    },
    {
        "code": "epfo",
        "name": "EPFO Compliance",
        "description": "Employees' Provident Fund establishment registration and status.",
        "mandatory_by_default": True,
        "risk_weight": 0.75,
        "adapter_key": "epfo",
        "is_active": True,
    },
    {
        "code": "esic",
        "name": "ESIC Compliance",
        "description": "Employees' State Insurance establishment registration and status.",
        "mandatory_by_default": True,
        "risk_weight": 0.75,
        "adapter_key": "esic",
        "is_active": True,
    },
    {
        "code": "blacklisting",
        "name": "Blacklisting / Debarment",
        "description": "Active debarment/blacklisting on the central registry.",
        "mandatory_by_default": True,
        "risk_weight": 3.0,
        "adapter_key": "blacklisting",
        "is_active": True,
    },
    # Optional / claimed-benefit categories -- only scored if the bidder
    # actually claims them (see verify_submission's NOT_CLAIMED branch);
    # never a reason a bidder who doesn't claim them scores lower.
    {
        "code": "startup_india",
        "name": "Startup India",
        "description": "Startup India (DPIIT) recognition, claimed benefit only.",
        "mandatory_by_default": False,
        "risk_weight": 0.5,
        "adapter_key": "startup_india",
        "is_active": True,
    },
    {
        "code": "nsic",
        "name": "NSIC Registration",
        "description": "NSIC registration, claimed benefit only.",
        "mandatory_by_default": False,
        "risk_weight": 0.5,
        "adapter_key": "nsic",
        "is_active": True,
    },
    {
        "code": "oem_authorization",
        "name": "OEM Authorization",
        "description": "Manufacturer authorization for the specific equipment being bid.",
        "mandatory_by_default": False,
        "risk_weight": 1.5,
        "adapter_key": "oem_authorization",
        "is_active": True,
    },
    {
        "code": "digilocker",
        "name": "DigiLocker Document Verification",
        "description": "Cross-check of uploaded documents against DigiLocker-issued copies.",
        "mandatory_by_default": False,
        "risk_weight": 0.5,
        "adapter_key": "digilocker",
        "is_active": True,
    },
    {
        "code": "make_in_india",
        "name": "Make in India / Local Content",
        "description": "Declared local content percentage against category thresholds.",
        "mandatory_by_default": False,
        "risk_weight": 1.0,
        "adapter_key": "make_in_india",
        "is_active": True,
    },
    # Superseded by the epfo/esic split above -- kept, deactivated, never
    # deleted. See module docstring.
    {
        "code": "epfo_esic",
        "name": "EPFO / ESIC Compliance (legacy combined)",
        "description": "Superseded by separate EPFO and ESIC categories.",
        "mandatory_by_default": True,
        "risk_weight": 1.0,
        "adapter_key": "epfo_esic",
        "is_active": False,
    },
]


def seed_default_categories(db: Session) -> list[ComplianceCategory]:
    """Idempotent -- inserts only categories whose code isn't already present."""
    existing_codes = {code for (code,) in db.query(ComplianceCategory.code).all()}
    created: list[ComplianceCategory] = []
    for spec in DEFAULT_CATEGORIES:
        if spec["code"] in existing_codes:
            continue
        category = ComplianceCategory(**spec)
        db.add(category)
        created.append(category)
    if created:
        db.commit()
        for category in created:
            db.refresh(category)
    return created
