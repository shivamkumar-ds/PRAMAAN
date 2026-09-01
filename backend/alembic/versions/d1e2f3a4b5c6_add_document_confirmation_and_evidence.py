"""add SIH26100 document confirmation and verification evidence link (Phase 5)

Revision ID: d1e2f3a4b5c6
Revises: c9d0e1f2a3b4
Create Date: 2026-08-26 00:00:00.000000

Purely additive: five new nullable/defaulted columns on
sih_bidder_documents (is_confirmed, confirmed_data, confirmed_at,
confirmed_by, manually_corrected) and one new nullable column on
sih_verification_results (source_document_id). Nothing existing is
altered, dropped, or renamed.

Confirmation is modeled as a boolean + columns, NOT a new
DocumentExtractionStatus enum member -- see
app/models/sih/document.py's module docstring for why: ALTER TYPE ...
ADD VALUE cannot run inside a transaction on the Postgres versions this
project has to assume in the field, and has no clean rollback (no DROP
VALUE), whereas plain columns apply and reverse cleanly like every other
migration in this package.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, None] = 'c9d0e1f2a3b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'sih_bidder_documents',
        sa.Column('is_confirmed', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        'sih_bidder_documents',
        sa.Column('confirmed_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        'sih_bidder_documents',
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'sih_bidder_documents',
        sa.Column(
            'confirmed_by',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id'),
            nullable=True,
        ),
    )
    op.add_column(
        'sih_bidder_documents',
        sa.Column('manually_corrected', sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.add_column(
        'sih_verification_results',
        sa.Column(
            'source_document_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('sih_bidder_documents.id'),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column('sih_verification_results', 'source_document_id')

    op.drop_column('sih_bidder_documents', 'manually_corrected')
    op.drop_column('sih_bidder_documents', 'confirmed_by')
    op.drop_column('sih_bidder_documents', 'confirmed_at')
    op.drop_column('sih_bidder_documents', 'confirmed_data')
    op.drop_column('sih_bidder_documents', 'is_confirmed')
