"""add qualification_overrides

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-08-16 00:00:00.000000

New, purely additive table backing the "Administrator Override" action on
qualification gaps (mandatory CAPABILITY_CLAIM requirements not yet MET).
Distinct from bid_readiness_confirmations -- confirmation says "this is
genuinely prepared" (a fact the engine could never observe); an override
says "no real evidence exists yet, and an administrator is explicitly
choosing to proceed anyway." Both are read only at evaluation-response
time (decision_engine.compute_qualification()/classify_remediation()),
never at evaluation-run time, and neither ever mutates a
Requirement/ComplianceMatrix row.

One row per Requirement (UNIQUE constraint on requirement_id): a
requirement is either overridden or it isn't, no history of toggles is
needed since removing an override is a real DELETE.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'qualification_overrides',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'requirement_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('requirements.id'),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            'overridden_by',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id'),
            nullable=False,
        ),
        sa.Column('overridden_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('note', sa.String(), nullable=True),
    )
    op.create_index(
        'ix_qualification_overrides_overridden_by',
        'qualification_overrides',
        ['overridden_by'],
    )


def downgrade() -> None:
    op.drop_index('ix_qualification_overrides_overridden_by', table_name='qualification_overrides')
    op.drop_table('qualification_overrides')
