"""Require immutable source and review references for scope authority."""

import sqlalchemy as sa
from alembic import op

revision = "20260728_0069"
down_revision = "20260728_0068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_scope_authority_source_ref",
        "evidence_records",
        ["source", "source_ref"],
        unique=True,
        postgresql_where=sa.text("source = 'scope_authority_source'"),
        sqlite_where=sa.text("source = 'scope_authority_source'"),
    )
    op.create_index(
        "uq_scope_authority_review_ref",
        "evidence_records",
        ["source", "source_ref"],
        unique=True,
        postgresql_where=sa.text("source = 'scope_authority_review'"),
        sqlite_where=sa.text("source = 'scope_authority_review'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_scope_authority_review_ref",
        table_name="evidence_records",
    )
    op.drop_index(
        "uq_scope_authority_source_ref",
        table_name="evidence_records",
    )
