"""add bid_readiness_confirmations

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-08-16 00:00:00.000000

New, purely additive table backing the "Confirm Prepared" action on
bid-readiness gap items (SUBMISSION_GATING / FUTURE_CONTRACTUAL_COMMITMENT
requirements — EMD, DSC, PPE/safety declarations, etc). One row per
Requirement (UNIQUE constraint on requirement_id): a requirement is either
confirmed prepared or it isn't, no history of toggles is needed since
unconfirm is a real DELETE, not a soft-delete/status flip.

requirement_id alone is a safe, already-mission-scoped key (a Requirement
belongs to exactly one Tender, which belongs to exactly one Mission, by
convention) — no composite (mission_id, requirement_id) key needed. The
confirm/unconfirm endpoints still verify mission_id/requirement_id/
company_id ownership at the API layer before touching this table.

Deliberately does NOT touch RequirementNature, decision_engine.py's
enums, or any existing table — this is purely a new, independent row of
human-entered state that decision_engine.compute_bid_readiness() /
classify_remediation() read at evaluation-response time, never at
evaluation-run time (see the architecture debate's bid-readiness-
confirmation frozen decision).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'bid_readiness_confirmations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'requirement_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('requirements.id'),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            'confirmed_by',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id'),
            nullable=False,
        ),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('note', sa.String(), nullable=True),
    )
    # requirement_id already gets a unique index for free from unique=True
    # above; confirmed_by is indexed separately since ownership/audit
    # lookups ("what has this admin confirmed") filter on it directly,
    # matching the FK-indexing precedent set by 8f1a2c9d4b6e.
    op.create_index(
        'ix_bid_readiness_confirmations_confirmed_by',
        'bid_readiness_confirmations',
        ['confirmed_by'],
    )


def downgrade() -> None:
    op.drop_index('ix_bid_readiness_confirmations_confirmed_by', table_name='bid_readiness_confirmations')
    op.drop_table('bid_readiness_confirmations')
