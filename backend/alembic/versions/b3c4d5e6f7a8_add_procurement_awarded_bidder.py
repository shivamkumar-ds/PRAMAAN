"""add sih_procurements.awarded_bidder_id (Collusion Radar repeat-winner signal)

Revision ID: b3c4d5e6f7a8
Revises: f7a8b9c0d1e2
Create Date: 2026-09-02 00:00:00.000000

Purely additive: one new nullable column, sih_procurements.awarded_bidder_id
(FK -> sih_bidders.id). Nothing existing is altered, dropped, or renamed.

Settable only via procurement_service.set_awarded_bidder(), gated
require_sih_award_role (Administrator/Executive only) at the API layer --
see app/models/sih/procurement.py's Procurement.awarded_bidder_id docstring
for why this is never inferred automatically from an OfficerDecision.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, None] = 'f7a8b9c0d1e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'sih_procurements',
        sa.Column(
            'awarded_bidder_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('sih_bidders.id'),
            nullable=True,
        ),
    )
    op.create_index('ix_sih_procurements_awarded_bidder_id', 'sih_procurements', ['awarded_bidder_id'])


def downgrade() -> None:
    op.drop_index('ix_sih_procurements_awarded_bidder_id', table_name='sih_procurements')
    op.drop_column('sih_procurements', 'awarded_bidder_id')
