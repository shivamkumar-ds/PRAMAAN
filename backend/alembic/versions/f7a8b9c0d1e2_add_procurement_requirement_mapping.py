"""add procurement documents + requirement-to-evidence mapping

Revision ID: f7a8b9c0d1e2
Revises: e2f3a4b5c6d7
Create Date: 2026-09-01 00:00:00.000000

Two new, purely additive tables backing the Requirement-to-Evidence
Mapping engine:

1. sih_procurement_documents -- the officer's own uploaded tender
   document. Unlike sih_bidder_documents there is no confirmation gate
   (is_confirmed/confirmed_data) -- the officer uploading their own
   tender is trusted by definition, this isn't third-party evidence
   needing grounding (see app/models/sih/procurement_document.py's
   module docstring). ondelete='CASCADE' on procurement_id: a
   ProcurementDocument has no independent meaning once its parent
   Procurement is gone (unlike sih_bidder_documents, which has no such
   cascade because a BidderSubmission's documents are audit trail for a
   verification decision that outlives casual deletion).

2. sih_procurement_requirements -- one row per extracted eligibility/
   compliance requirement. Also ondelete='CASCADE' on procurement_id
   for the same reason. source_document_id has no ondelete clause (a
   requirement can outlive its source document's deletion, same
   provenance-preservation posture as sih_verification_results.
   source_document_id) and no DB-level FK to
   sih_compliance_categories.code either (category_hint is advisory
   extracted data, not a referential-integrity relationship -- see the
   model docstring).

Enum label convention unchanged from every other SIH enum column:
uppercase, matching the Python enum member NAME.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f7a8b9c0d1e2'
down_revision: Union[str, None] = 'e2f3a4b5c6d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

sih_procurement_document_extraction_status_enum = postgresql.ENUM(
    'PENDING', 'EXTRACTED', 'FAILED',
    name='sih_procurement_document_extraction_status', create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    sih_procurement_document_extraction_status_enum.create(bind, checkfirst=True)

    op.create_table(
        'sih_procurement_documents',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'procurement_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('sih_procurements.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('original_filename', sa.String(), nullable=False),
        sa.Column('storage_path', sa.String(), nullable=False),
        sa.Column('mime_type', sa.String(), nullable=True),
        sa.Column('file_size_bytes', sa.Integer(), nullable=True),
        sa.Column('extraction_status', sih_procurement_document_extraction_status_enum, nullable=False),
        sa.Column('extraction_error', sa.String(), nullable=True),
        sa.Column('uploaded_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('uploaded_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
    )
    op.create_index(
        'ix_sih_procurement_documents_procurement_id', 'sih_procurement_documents', ['procurement_id']
    )

    op.create_table(
        'sih_procurement_requirements',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'procurement_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('sih_procurements.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'source_document_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('sih_procurement_documents.id'),
            nullable=True,
        ),
        sa.Column('requirement_text', sa.Text(), nullable=False),
        sa.Column('category_hint', sa.String(), nullable=True),
        sa.Column('is_mandatory', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        'ix_sih_procurement_requirements_procurement_id', 'sih_procurement_requirements', ['procurement_id']
    )
    op.create_index(
        'ix_sih_procurement_requirements_category_hint', 'sih_procurement_requirements', ['category_hint']
    )


def downgrade() -> None:
    op.drop_index('ix_sih_procurement_requirements_category_hint', table_name='sih_procurement_requirements')
    op.drop_index('ix_sih_procurement_requirements_procurement_id', table_name='sih_procurement_requirements')
    op.drop_table('sih_procurement_requirements')

    op.drop_index('ix_sih_procurement_documents_procurement_id', table_name='sih_procurement_documents')
    op.drop_table('sih_procurement_documents')

    bind = op.get_bind()
    sih_procurement_document_extraction_status_enum.drop(bind, checkfirst=True)
