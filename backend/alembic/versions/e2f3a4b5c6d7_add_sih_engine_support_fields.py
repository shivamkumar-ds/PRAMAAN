"""add SIH26100 engine support fields (Network Graph, Collusion Radar, Authenticity Scanner)

Revision ID: e2f3a4b5c6d7
Revises: a1c2d3e4f5a6
Create Date: 2026-08-31 00:00:00.000000

Purely additive, three independent pieces, all nullable/no-default-risk:

1. Four nullable String columns on sih_bidders (registered_address,
   director_name, contact_email, contact_phone). None of these exist
   today -- Bidder currently only carries legal_name/trade_name/pan (see
   app/models/sih/bidder.py's original docstring). They are the minimal
   real identifiers the Bidder Network Graph (SIH26100 demo-scope
   expansion) needs to find genuine shared-identifier relationships
   between bidders; a bidder with none of these filled in simply
   contributes no relationships, never a fabricated one.

2. One nullable Numeric column on sih_bidder_submissions (bid_amount) --
   no bid value of any kind existed anywhere in the SIH domain before
   this. The Collusion Radar's "similar bid values / narrow spread"
   heuristic is honestly impossible without it; a submission with no
   bid_amount is simply excluded from that specific heuristic (never
   assumed to be zero or average).

3. A new insert-only table, sih_authenticity_scans, one row per
   Authenticity Scanner run against a BidderDocument -- mirrors
   sih_verification_results' insert-only/never-overwritten pattern so a
   document's scan history is preserved across re-scans, not silently
   replaced.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e2f3a4b5c6d7'
down_revision: Union[str, None] = 'a1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('sih_bidders', sa.Column('registered_address', sa.String(), nullable=True))
    op.add_column('sih_bidders', sa.Column('director_name', sa.String(), nullable=True))
    op.add_column('sih_bidders', sa.Column('contact_email', sa.String(), nullable=True))
    op.add_column('sih_bidders', sa.Column('contact_phone', sa.String(), nullable=True))

    op.add_column(
        'sih_bidder_submissions',
        sa.Column('bid_amount', sa.Numeric(14, 2), nullable=True),
    )

    op.create_table(
        'sih_authenticity_scans',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'document_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('sih_bidder_documents.id'),
            nullable=False,
        ),
        sa.Column('indicators', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('summary_label', sa.String(), nullable=False),
        sa.Column(
            'scanned_by',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id'),
            nullable=False,
        ),
        sa.Column('scanned_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        'ix_sih_authenticity_scans_document_id', 'sih_authenticity_scans', ['document_id']
    )


def downgrade() -> None:
    op.drop_index('ix_sih_authenticity_scans_document_id', table_name='sih_authenticity_scans')
    op.drop_table('sih_authenticity_scans')

    op.drop_column('sih_bidder_submissions', 'bid_amount')

    op.drop_column('sih_bidders', 'contact_phone')
    op.drop_column('sih_bidders', 'contact_email')
    op.drop_column('sih_bidders', 'director_name')
    op.drop_column('sih_bidders', 'registered_address')
