"""add SIH26100 bidder verification domain

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-08-23 00:00:00.000000

New, purely additive tables backing SIH26100 (AI-Powered Integrated Bid
Compliance Verification Platform for GeM Procurement) -- a new,
independent sibling domain alongside BidOps' existing bidder-side
self-assessment product. Nothing in this migration alters, drops, or
depends on any existing table, column, or enum (tenders, requirements,
capability_mappings, missions, compliance_matrix, qualification_overrides,
bid_readiness_confirmations are all untouched).

Seven new tables, all prefixed sih_ to make the domain boundary visible
directly in the schema:

  sih_compliance_categories  -- fixed, seeded registry of the ~10
                                 SIH26100 verification categories
                                 (Udyam, GST, PAN/ITR, EPFO/ESIC,
                                 Blacklisting active; Startup India,
                                 NSIC, OEM Authorization, DigiLocker,
                                 Make in India seeded inactive/roadmap)
  sih_procurements            -- a GeM procurement opportunity
  sih_bidders                 -- a third-party bidder being verified,
                                 independent of any one Procurement
  sih_bidder_submissions      -- one Bidder's submission against one
                                 Procurement (unique per pair)
  sih_registry_records        -- deterministic MOCK government registry
                                 data (never a real government API)
  sih_verification_results    -- insert-only per-category verification
                                 history for a submission
  sih_officer_decisions       -- insert-only Procurement Officer
                                 decision history (APPROVE / REJECT /
                                 REQUEST_CLARIFICATION), mandatory note

Enum labels are declared uppercase, matching each Python enum member's
NAME (not value) -- same convention as every other enum column in this
schema (see e5f6a7b8c9d0's docstring re: Bug #005, docs/BUG_BUCKET.md).

Compliance-category seed data is inserted at the end of upgrade() so a
fresh database has the full SIH26100 checklist immediately -- this list
must be kept in sync by hand with
app/services/sih/compliance_category_service.DEFAULT_CATEGORIES (that
module is also used directly by tests, which build their own in-memory
schema rather than running this migration).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# One shared object per enum, referenced by both .create() and the
# column definition -- see Bug #006 (docs/BUG_BUCKET.md): constructing a
# second sa.Enum/postgresql.ENUM for the same Postgres type name inside
# the same migration risks a duplicate CREATE TYPE.
sih_procurement_status_enum = postgresql.ENUM(
    'OPEN', 'CLOSED', 'ARCHIVED', name='sih_procurement_status', create_type=False,
)
sih_submission_status_enum = postgresql.ENUM(
    'SUBMITTED', 'UNDER_REVIEW', 'DECIDED', name='sih_submission_status', create_type=False,
)
sih_verification_status_enum = postgresql.ENUM(
    'VERIFIED', 'MISMATCH', 'MISSING', 'NOT_APPLICABLE', 'NOT_CLAIMED', 'CRITICAL_FAIL',
    name='sih_verification_status', create_type=False,
)
sih_officer_decision_type_enum = postgresql.ENUM(
    'APPROVE', 'REJECT', 'REQUEST_CLARIFICATION', name='sih_officer_decision_type', create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    sih_procurement_status_enum.create(bind, checkfirst=True)
    sih_submission_status_enum.create(bind, checkfirst=True)
    sih_verification_status_enum.create(bind, checkfirst=True)
    sih_officer_decision_type_enum.create(bind, checkfirst=True)

    op.create_table(
        'sih_compliance_categories',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('code', sa.String(), nullable=False, unique=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('mandatory_by_default', sa.Boolean(), nullable=False),
        sa.Column('risk_weight', sa.Float(), nullable=False),
        sa.Column('adapter_key', sa.String(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        'ix_sih_compliance_categories_code', 'sih_compliance_categories', ['code'], unique=True,
    )

    op.create_table(
        'sih_procurements',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id'), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('organization', sa.String(), nullable=True),
        sa.Column('reference_number', sa.String(), nullable=True),
        sa.Column('category', sa.String(), nullable=True),
        sa.Column('closing_date', sa.Date(), nullable=True),
        sa.Column('status', sih_procurement_status_enum, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_sih_procurements_company_id', 'sih_procurements', ['company_id'])

    op.create_table(
        'sih_bidders',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('companies.id'), nullable=False),
        sa.Column('legal_name', sa.String(), nullable=False),
        sa.Column('trade_name', sa.String(), nullable=True),
        sa.Column('pan', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_sih_bidders_company_id', 'sih_bidders', ['company_id'])
    op.create_index('ix_sih_bidders_pan', 'sih_bidders', ['pan'])

    op.create_table(
        'sih_bidder_submissions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'procurement_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sih_procurements.id'), nullable=False
        ),
        sa.Column('bidder_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sih_bidders.id'), nullable=False),
        sa.Column('status', sih_submission_status_enum, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('procurement_id', 'bidder_id', name='uq_sih_submission_procurement_bidder'),
    )
    op.create_index('ix_sih_bidder_submissions_procurement_id', 'sih_bidder_submissions', ['procurement_id'])
    op.create_index('ix_sih_bidder_submissions_bidder_id', 'sih_bidder_submissions', ['bidder_id'])

    op.create_table(
        'sih_registry_records',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'category_code', sa.String(), sa.ForeignKey('sih_compliance_categories.code'), nullable=False
        ),
        sa.Column('identifier_type', sa.String(), nullable=False),
        sa.Column('identifier_value', sa.String(), nullable=False),
        sa.Column('record_data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('last_synced_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_sih_registry_records_category_code', 'sih_registry_records', ['category_code'])
    op.create_index('ix_sih_registry_records_identifier_value', 'sih_registry_records', ['identifier_value'])

    op.create_table(
        'sih_verification_results',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'submission_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('sih_bidder_submissions.id'),
            nullable=False,
        ),
        sa.Column(
            'category_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('sih_compliance_categories.id'),
            nullable=False,
        ),
        sa.Column('status', sih_verification_status_enum, nullable=False),
        sa.Column('declared_value', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('registry_value', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('discrepancies', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('source', sa.String(), nullable=False),
        sa.Column('reason', sa.String(), nullable=True),
        sa.Column('ai_explanation', sa.String(), nullable=True),
        sa.Column('checked_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_sih_verification_results_submission_id', 'sih_verification_results', ['submission_id'])
    op.create_index('ix_sih_verification_results_category_id', 'sih_verification_results', ['category_id'])

    op.create_table(
        'sih_officer_decisions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'submission_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('sih_bidder_submissions.id'),
            nullable=False,
        ),
        sa.Column('officer_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('decision', sih_officer_decision_type_enum, nullable=False),
        sa.Column('note', sa.String(), nullable=False),
        sa.Column('decided_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_sih_officer_decisions_submission_id', 'sih_officer_decisions', ['submission_id'])
    op.create_index('ix_sih_officer_decisions_officer_id', 'sih_officer_decisions', ['officer_id'])

    # Seed the fixed compliance-category checklist -- must match
    # app/services/sih/compliance_category_service.DEFAULT_CATEGORIES.
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
    import uuid as _uuid

    op.bulk_insert(
        compliance_categories_table,
        [
            {
                'id': _uuid.uuid4(),
                'code': 'udyam',
                'name': 'Udyam / MSME Registration',
                'description': 'Udyam registration status and entity match.',
                'mandatory_by_default': True,
                'risk_weight': 1.0,
                'adapter_key': 'udyam',
                'is_active': True,
            },
            {
                'id': _uuid.uuid4(),
                'code': 'gst',
                'name': 'GST / GSTN Registration',
                'description': 'GSTIN validity, status, and PAN linkage.',
                'mandatory_by_default': True,
                'risk_weight': 1.5,
                'adapter_key': 'gst',
                'is_active': True,
            },
            {
                'id': _uuid.uuid4(),
                'code': 'pan_itr',
                'name': 'PAN / Income Tax / ITR',
                'description': 'PAN identity anchor and ITR filing history.',
                'mandatory_by_default': True,
                'risk_weight': 2.0,
                'adapter_key': 'pan_itr',
                'is_active': True,
            },
            {
                'id': _uuid.uuid4(),
                'code': 'epfo_esic',
                'name': 'EPFO / ESIC Compliance',
                'description': 'Labour welfare establishment registration and status.',
                'mandatory_by_default': True,
                'risk_weight': 1.0,
                'adapter_key': 'epfo_esic',
                'is_active': True,
            },
            {
                'id': _uuid.uuid4(),
                'code': 'blacklisting',
                'name': 'Blacklisting / Debarment',
                'description': 'Active debarment/blacklisting on the central registry.',
                'mandatory_by_default': True,
                'risk_weight': 3.0,
                'adapter_key': 'blacklisting',
                'is_active': True,
            },
            {
                'id': _uuid.uuid4(),
                'code': 'startup_india',
                'name': 'Startup India',
                'description': 'Startup India recognition, claimed benefit only.',
                'mandatory_by_default': False,
                'risk_weight': 0.5,
                'adapter_key': 'startup_india',
                'is_active': False,
            },
            {
                'id': _uuid.uuid4(),
                'code': 'nsic',
                'name': 'NSIC Registration',
                'description': 'NSIC registration, claimed benefit only.',
                'mandatory_by_default': False,
                'risk_weight': 0.5,
                'adapter_key': 'nsic',
                'is_active': False,
            },
            {
                'id': _uuid.uuid4(),
                'code': 'oem_authorization',
                'name': 'OEM Authorization',
                'description': 'Manufacturer authorization for the specific equipment being bid.',
                'mandatory_by_default': False,
                'risk_weight': 1.5,
                'adapter_key': 'oem_authorization',
                'is_active': False,
            },
            {
                'id': _uuid.uuid4(),
                'code': 'digilocker',
                'name': 'DigiLocker Document Verification',
                'description': 'Cross-check of uploaded documents against DigiLocker-issued copies.',
                'mandatory_by_default': False,
                'risk_weight': 0.5,
                'adapter_key': 'digilocker',
                'is_active': False,
            },
            {
                'id': _uuid.uuid4(),
                'code': 'make_in_india',
                'name': 'Make in India / Local Content',
                'description': 'Declared local content percentage against category thresholds.',
                'mandatory_by_default': False,
                'risk_weight': 1.0,
                'adapter_key': 'make_in_india',
                'is_active': False,
            },
        ],
    )


def downgrade() -> None:
    op.drop_index('ix_sih_officer_decisions_officer_id', table_name='sih_officer_decisions')
    op.drop_index('ix_sih_officer_decisions_submission_id', table_name='sih_officer_decisions')
    op.drop_table('sih_officer_decisions')

    op.drop_index('ix_sih_verification_results_category_id', table_name='sih_verification_results')
    op.drop_index('ix_sih_verification_results_submission_id', table_name='sih_verification_results')
    op.drop_table('sih_verification_results')

    op.drop_index('ix_sih_registry_records_identifier_value', table_name='sih_registry_records')
    op.drop_index('ix_sih_registry_records_category_code', table_name='sih_registry_records')
    op.drop_table('sih_registry_records')

    op.drop_index('ix_sih_bidder_submissions_bidder_id', table_name='sih_bidder_submissions')
    op.drop_index('ix_sih_bidder_submissions_procurement_id', table_name='sih_bidder_submissions')
    op.drop_table('sih_bidder_submissions')

    op.drop_index('ix_sih_bidders_pan', table_name='sih_bidders')
    op.drop_index('ix_sih_bidders_company_id', table_name='sih_bidders')
    op.drop_table('sih_bidders')

    op.drop_index('ix_sih_procurements_company_id', table_name='sih_procurements')
    op.drop_table('sih_procurements')

    op.drop_index('ix_sih_compliance_categories_code', table_name='sih_compliance_categories')
    op.drop_table('sih_compliance_categories')

    bind = op.get_bind()
    sih_officer_decision_type_enum.drop(bind, checkfirst=True)
    sih_verification_status_enum.drop(bind, checkfirst=True)
    sih_submission_status_enum.drop(bind, checkfirst=True)
    sih_procurement_status_enum.drop(bind, checkfirst=True)
