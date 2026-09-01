"""expand SIH26100 demo registry sources

Revision ID: a1c2d3e4f5a6
Revises: d1e2f3a4b5c6
Create Date: 2026-08-26 00:00:00.000000

Data-only, additive migration for the SIH26100 demo-scope expansion --
no table/column/enum changes. This activates the five roadmap categories
seeded inactive by b8c9d0e1f2a3 (Startup India, NSIC, OEM Authorization,
DigiLocker, Make in India -- adapters for all five now exist in
app/services/sih/registry_adapters.py), adds a new "mca21" category, and
splits the combined "epfo_esic" category into separate "epfo" and "esic"
categories (deactivating "epfo_esic" rather than deleting it, so any
already-confirmed BidderDocument/VerificationResult referencing that code
still resolves via FK -- see compliance_category_service.py's docstring
for the full reasoning).

Must be kept in sync by hand with
app/services/sih/compliance_category_service.DEFAULT_CATEGORIES (also
used directly by tests, which build their own in-memory schema rather
than running migrations).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a1c2d3e4f5a6'
down_revision: Union[str, None] = 'd1e2f3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

compliance_categories_table = sa.table(
    'sih_compliance_categories',
    sa.column('id', postgresql.UUID(as_uuid=True)),
    sa.column('code', sa.String()),
    sa.column('name', sa.String()),
    sa.column('description', sa.String()),
    sa.column('mandatory_by_default', sa.Boolean()),
    sa.column('risk_weight', sa.Float()),
    sa.column('adapter_key', sa.String()),
    sa.column('is_active', sa.Boolean()),
)


def upgrade() -> None:
    # Activate the five previously-roadmap categories -- rows already
    # exist (seeded by b8c9d0e1f2a3), only is_active flips.
    for code in ("startup_india", "nsic", "oem_authorization", "digilocker", "make_in_india"):
        op.execute(
            compliance_categories_table.update()
            .where(compliance_categories_table.c.code == code)
            .values(is_active=True)
        )

    # Deactivate the combined EPFO/ESIC category in favour of the split
    # below -- row, name, and description updated to make the supersession
    # explicit to anyone inspecting the table directly; never deleted.
    op.execute(
        compliance_categories_table.update()
        .where(compliance_categories_table.c.code == "epfo_esic")
        .values(
            name="EPFO / ESIC Compliance (legacy combined)",
            description="Superseded by separate EPFO and ESIC categories.",
            is_active=False,
        )
    )

    import uuid as _uuid

    op.bulk_insert(
        compliance_categories_table,
        [
            {
                'id': _uuid.uuid4(),
                'code': 'mca21',
                'name': 'MCA21 (Corporate Registration)',
                'description': 'Company Identification Number (CIN) status with the Ministry of Corporate Affairs.',
                'mandatory_by_default': True,
                'risk_weight': 1.5,
                'adapter_key': 'mca21',
                'is_active': True,
            },
            {
                'id': _uuid.uuid4(),
                'code': 'epfo',
                'name': 'EPFO Compliance',
                'description': "Employees' Provident Fund establishment registration and status.",
                'mandatory_by_default': True,
                'risk_weight': 0.75,
                'adapter_key': 'epfo',
                'is_active': True,
            },
            {
                'id': _uuid.uuid4(),
                'code': 'esic',
                'name': 'ESIC Compliance',
                'description': "Employees' State Insurance establishment registration and status.",
                'mandatory_by_default': True,
                'risk_weight': 0.75,
                'adapter_key': 'esic',
                'is_active': True,
            },
        ],
    )


def downgrade() -> None:
    op.execute(
        compliance_categories_table.delete().where(
            compliance_categories_table.c.code.in_(('mca21', 'epfo', 'esic'))
        )
    )
    op.execute(
        compliance_categories_table.update()
        .where(compliance_categories_table.c.code == "epfo_esic")
        .values(
            name="EPFO / ESIC Compliance",
            description="Labour welfare establishment registration and status.",
            is_active=True,
        )
    )
    for code in ("startup_india", "nsic", "oem_authorization", "digilocker", "make_in_india"):
        op.execute(
            compliance_categories_table.update()
            .where(compliance_categories_table.c.code == code)
            .values(is_active=False)
        )
