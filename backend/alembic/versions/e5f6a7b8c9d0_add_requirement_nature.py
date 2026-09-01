"""add requirement_nature (architecture debate Phase 1)

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-08-15 00:00:00.000000

Adds RequirementNature (see app/models/enums.py's docstring) as a new,
nullable column on `requirements` -- purely additive, no backfill, no
change to any existing column, table, or enum.

Enum labels are declared uppercase ('CAPABILITY_CLAIM', 'SUBMISSION_GATING',
'PROCEDURAL', 'FUTURE_CONTRACTUAL_COMMITMENT'), matching
RequirementNature's member *names* -- not repeating Bug #005
(docs/BUG_BUCKET.md), where the auth_provider enum was created with
lowercase labels while SQLAlchemy's Enum(SomePythonEnum) column type
serializes via member.name, never member.value, with no
values_callable override anywhere in this codebase. Confirmed against
every other enum column in 3d8622ed98f0 (requirement_type itself is
declared 'ELIGIBILITY', 'TECHNICAL', ... uppercase, same pattern).

No backfill: every Requirement row that existed before this migration
reads as requirement_nature = NULL. This is deliberate (Phase 1 scope
decision, BidOps_Architecture_Debate.md) -- nothing downstream reads
this column yet, so there is no behavioral change to any existing
tender's evaluation as a result of this migration.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# One shared object, referenced by both .create() and the column
# definition -- see Bug #006 (docs/BUG_BUCKET.md): constructing a second
# sa.Enum/postgresql.ENUM for the same Postgres type name inside the
# same migration risks a duplicate CREATE TYPE.
requirement_nature_enum = postgresql.ENUM(
    'CAPABILITY_CLAIM', 'SUBMISSION_GATING', 'PROCEDURAL', 'FUTURE_CONTRACTUAL_COMMITMENT',
    name='requirement_nature', create_type=False,
)


def upgrade() -> None:
    requirement_nature_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        'requirements',
        sa.Column('requirement_nature', requirement_nature_enum, nullable=True),
    )


def downgrade() -> None:
    op.drop_column('requirements', 'requirement_nature')
    requirement_nature_enum.drop(op.get_bind(), checkfirst=True)
