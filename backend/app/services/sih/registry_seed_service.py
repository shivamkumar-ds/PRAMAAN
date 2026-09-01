"""
RegistryRecord seeding -- SIH26100 Phase 1.

Loads app/services/sih/mock_registry_data.MOCK_REGISTRY_SEED into the
sih_registry_records table. Idempotent and, like
compliance_category_service.seed_default_categories(), never run
automatically at app startup -- called explicitly by tests / a seed
script.
"""

from sqlalchemy.orm import Session

from app.models.sih.compliance import RegistryRecord
from app.services.sih.mock_registry_data import MOCK_REGISTRY_SEED


def seed_mock_registry(db: Session) -> list[RegistryRecord]:
    """Idempotent on (category_code, identifier_type, identifier_value)."""
    existing = {
        (r.category_code, r.identifier_type, r.identifier_value)
        for r in db.query(
            RegistryRecord.category_code, RegistryRecord.identifier_type, RegistryRecord.identifier_value
        ).all()
    }
    created: list[RegistryRecord] = []
    for spec in MOCK_REGISTRY_SEED:
        key = (spec["category_code"], spec["identifier_type"], spec["identifier_value"])
        if key in existing:
            continue
        record = RegistryRecord(**spec)
        db.add(record)
        created.append(record)
    if created:
        db.commit()
        for record in created:
            db.refresh(record)
    return created
