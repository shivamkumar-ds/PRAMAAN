"""add SIH26100 bidder documents (Phase 4)

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-08-26 00:00:00.000000

One new, purely additive table -- sih_bidder_documents -- backing
Phase 4's document upload + AI extraction pipeline. Nothing in this
migration alters, drops, or depends on any existing table, column, or
enum, including the seven sih_* tables from b8c9d0e1f2a3, which are
untouched.

sih_bidder_documents.category_code is nullable and references
sih_compliance_categories.code (same FK style as sih_registry_records) --
an officer may upload without picking a category, and
app.agents.sih_document_extractor.classify_document() may not always be
able to confidently assign one; NULL + extraction_status='REVIEW_REQUIRED'
is the honest state for "we don't know yet," not a guess.

Enum label convention unchanged from every other SIH enum column:
uppercase, matching the Python enum member NAME (see b8c9d0e1f2a3's
docstring re: Bug #005/#006, docs/BUG_BUCKET.md).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c9d0e1f2a3b4'
down_revision: Union[str, None] = 'b8c9d0e1f2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

sih_document_extraction_status_enum = postgresql.ENUM(
    'PENDING', 'PROCESSING', 'EXTRACTED', 'REVIEW_REQUIRED', 'FAILED',
    name='sih_document_extraction_status', create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    sih_document_extraction_status_enum.create(bind, checkfirst=True)

    op.create_table(
        'sih_bidder_documents',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'submission_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('sih_bidder_submissions.id'),
            nullable=False,
        ),
        sa.Column('uploaded_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column(
            'category_code', sa.String(), sa.ForeignKey('sih_compliance_categories.code'), nullable=True
        ),
        sa.Column('category_source', sa.String(), nullable=False),
        sa.Column('file_name', sa.String(), nullable=False),
        sa.Column('storage_path', sa.String(), nullable=False),
        sa.Column('uploaded_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('extraction_status', sih_document_extraction_status_enum, nullable=False),
        sa.Column('extracted_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('extraction_confidence', sa.Float(), nullable=True),
        sa.Column('extraction_error', sa.String(), nullable=True),
        sa.Column('extracted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_sih_bidder_documents_submission_id', 'sih_bidder_documents', ['submission_id'])
    op.create_index('ix_sih_bidder_documents_category_code', 'sih_bidder_documents', ['category_code'])


def downgrade() -> None:
    op.drop_index('ix_sih_bidder_documents_category_code', table_name='sih_bidder_documents')
    op.drop_index('ix_sih_bidder_documents_submission_id', table_name='sih_bidder_documents')
    op.drop_table('sih_bidder_documents')

    bind = op.get_bind()
    sih_document_extraction_status_enum.drop(bind, checkfirst=True)
