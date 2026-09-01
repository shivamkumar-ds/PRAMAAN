"""
SIH26100 demo/deployment seed entrypoint.

Deliberately tiny: this calls the two existing, already-tested,
idempotent seed functions -- app.services.sih.compliance_category_service.
seed_default_categories() and app.services.sih.registry_seed_service.
seed_mock_registry() -- against whatever DATABASE_URL the process is
configured with. No new seed logic lives here; this is a deployment-support
entrypoint, not a feature.

Both functions were previously only ever called from tests, per their own
docstrings ("never run automatically at app startup -- called explicitly
by tests / a seed script"). This is that seed script, run once against a
freshly-migrated database (local dev, or a Cloud Run migration/seed job),
never on every app boot -- the same one-shot-job posture as
scripts/migrate.sh, not folded into it, because seeding demo/registry
fixture data is a distinct, deliberately-skippable step from applying
schema migrations (a real production deployment migrates but never seeds
fixture data).

Usage:
    cd backend && python -m scripts.seed_demo
    (or: python scripts/seed_demo.py, with backend/ on PYTHONPATH)

Idempotent -- safe to run more than once; both underlying functions only
insert rows that don't already exist (see their own docstrings).
"""

import logging

from app.core.database import SessionLocal
from app.services.sih import compliance_category_service, registry_seed_service

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("seed_demo")


def main() -> None:
    db = SessionLocal()
    try:
        categories = compliance_category_service.seed_default_categories(db)
        logger.info("Compliance categories created this run: %d", len(categories))

        records = registry_seed_service.seed_mock_registry(db)
        logger.info("Registry records created this run: %d", len(records))

        logger.info("Seed complete (idempotent -- re-running is safe).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
