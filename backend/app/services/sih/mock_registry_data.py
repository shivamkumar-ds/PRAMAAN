"""
Deterministic mock government registry seed data -- SIH26100 Phase 1.

Never real government data. Each entry is deliberately chosen to exercise
a distinct verification outcome (clean/verified, mismatch, missing,
critical PAN mismatch, blacklisted) so tests -- and any future demo --
have realistic variety, per the Phase 0 report's Must-Build scope.

Used by app/services/sih/registry_seed_service.py to populate
RegistryRecord rows (called explicitly by tests / a seed script -- never
run automatically at app startup, same convention as
compliance_category_service.seed_default_categories()).
"""

MOCK_REGISTRY_SEED: list[dict] = [
    # -- Clean bidder: "ABC Engineering Private Limited", PAN ABCDE1234F --
    {
        "category_code": "udyam",
        "identifier_type": "udyam_number",
        "identifier_value": "UDYAM-DL-01-0012345",
        "record_data": {
            "entity_name": "ABC Engineering Private Limited",
            "status": "active",
            "enterprise_type": "small",
        },
    },
    {
        "category_code": "gst",
        "identifier_type": "gstin",
        "identifier_value": "07ABCDE1234F1Z5",
        "record_data": {
            "entity_name": "ABC Engineering Private Limited",
            "pan": "ABCDE1234F",
            "status": "active",
        },
    },
    {
        "category_code": "pan_itr",
        "identifier_type": "pan",
        "identifier_value": "ABCDE1234F",
        "record_data": {
            "entity_name": "ABC Engineering Private Limited",
            "itr_filed_years": ["2022-23", "2023-24", "2024-25"],
        },
    },
    {
        "category_code": "epfo_esic",
        "identifier_type": "establishment_id",
        "identifier_value": "DL/EPFO/998877",
        "record_data": {"entity_name": "ABC Engineering Private Limited", "status": "active"},
    },
    {
        "category_code": "blacklisting",
        "identifier_type": "pan",
        "identifier_value": "ABCDE1234F",
        "record_data": {"is_blacklisted": False},
    },
    # -- Mismatch bidder: GST entity name differs from Udyam, PAN OK --
    {
        "category_code": "udyam",
        "identifier_type": "udyam_number",
        "identifier_value": "UDYAM-MH-02-0054321",
        "record_data": {
            "entity_name": "Sunrise Traders Private Limited",
            "status": "active",
            "enterprise_type": "micro",
        },
    },
    {
        "category_code": "gst",
        "identifier_type": "gstin",
        "identifier_value": "27SUNRZ5678H1Z2",
        "record_data": {"entity_name": "Sunrise Traders", "pan": "SUNRZ5678H", "status": "active"},
    },
    {
        "category_code": "pan_itr",
        "identifier_type": "pan",
        "identifier_value": "SUNRZ5678H",
        "record_data": {
            "entity_name": "Sunrise Traders Private Limited",
            "itr_filed_years": ["2023-24"],
        },
    },
    # -- Critical bidder: GSTIN registered to a different PAN --
    {
        "category_code": "gst",
        "identifier_type": "gstin",
        "identifier_value": "09FRAUD9999K1Z1",
        "record_data": {"entity_name": "Genuine Constructions Ltd", "pan": "OTHRX0000Y", "status": "active"},
    },
    # -- Blacklisted bidder --
    {
        "category_code": "blacklisting",
        "identifier_type": "pan",
        "identifier_value": "DEBAR1234B",
        "record_data": {
            "is_blacklisted": True,
            "order_reference": "MoP&NG/DEBAR/2025/041",
            "debarred_until": "2027-01-01",
        },
    },
    # -------------------------------------------------------------------
    # SIH26100 demo-scope expansion -- ABC Engineering Private Limited
    # (the same "clean bidder" as above, PAN ABCDE1234F) verified across
    # every newly-added source, so a single demo bidder can walk the full
    # 12-category checklist end to end and come back all-VERIFIED.
    # -------------------------------------------------------------------
    {
        "category_code": "mca21",
        "identifier_type": "cin",
        "identifier_value": "U29100DL2015PTC280123",
        "record_data": {
            "entity_name": "ABC Engineering Private Limited",
            "status": "active",
            "incorporation_date": "2015-06-12",
            "roc": "RoC-Delhi",
        },
    },
    {
        "category_code": "epfo",
        "identifier_type": "epfo_establishment_id",
        "identifier_value": "DL/EPFO/998877",
        "record_data": {
            "entity_name": "ABC Engineering Private Limited",
            "legal_name": "ABC Engineering Private Limited",
            "status": "active",
        },
    },
    {
        "category_code": "esic",
        "identifier_type": "esic_establishment_id",
        "identifier_value": "31-00-998877-000-1001",
        "record_data": {
            "entity_name": "ABC Engineering Private Limited",
            "legal_name": "ABC Engineering Private Limited",
            "status": "active",
        },
    },
    {
        "category_code": "nsic",
        "identifier_type": "nsic_registration_number",
        "identifier_value": "NSIC/DL/2019/00456",
        "record_data": {
            "entity_name": "ABC Engineering Private Limited",
            "status": "active",
            "valid_until": "2027-03-31",
        },
    },
    {
        "category_code": "startup_india",
        "identifier_type": "dpiit_number",
        "identifier_value": "DIPP123456",
        "record_data": {
            "entity_name": "ABC Engineering Private Limited",
            "status": "recognized",
            "recognized_since": "2021-09-01",
        },
    },
    {
        "category_code": "oem_authorization",
        "identifier_type": "authorization_number",
        "identifier_value": "OEM-AUTH-2026-0091",
        "record_data": {
            "authorized_bidder_name": "ABC Engineering Private Limited",
            "oem_name": "Larsen Pipeline Systems Ltd",
            "status": "active",
            "valid_until": "2027-06-30",
        },
    },
    {
        "category_code": "digilocker",
        "identifier_type": "digilocker_reference",
        "identifier_value": "DL-REF-ABCENG-0012",
        "record_data": {
            "entity_name": "ABC Engineering Private Limited",
            "verified": True,
            "tampered": False,
        },
    },
    {
        "category_code": "make_in_india",
        "identifier_type": "pan",
        "identifier_value": "ABCDE1234F",
        "record_data": {
            "verified_local_content_percentage": 62,
            "threshold_percentage": 50,
        },
    },
    # -- Category-specific failure (Sunrise Traders, the existing
    # name/identity-mismatch bidder above): MCA21 shows the company as
    # struck off the register -- a realistic, source-specific failure
    # distinct from the GST/PAN scenarios already covered. --
    {
        "category_code": "mca21",
        "identifier_type": "cin",
        "identifier_value": "U27310MH2018PTC312456",
        "record_data": {
            "entity_name": "Sunrise Traders Private Limited",
            "status": "struck off",
        },
    },
]
