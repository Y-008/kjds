"""Add native scoped authority to Batch Opportunity runs."""

import sqlalchemy as sa
from alembic import op

revision = "20260728_0058"
down_revision = "20260728_0057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "batch_opportunity_runs",
        sa.Column("tenant_ref", sa.String(), nullable=True),
    )
    op.add_column(
        "batch_opportunity_runs",
        sa.Column("entity_ref", sa.String(), nullable=True),
    )
    op.add_column(
        "batch_opportunity_runs",
        sa.Column(
            "scope_grant_authority_sha256",
            sa.String(length=64),
            nullable=True,
        ),
    )
    op.add_column(
        "batch_opportunity_runs",
        sa.Column(
            "scope_evidence_authority_sha256",
            sa.String(length=64),
            nullable=True,
        ),
    )
    op.drop_constraint(
        "uq_batch_opportunity_run_idempotency",
        "batch_opportunity_runs",
        type_="unique",
    )
    op.create_check_constraint(
        "ck_batch_opportunity_run_scope_complete",
        "batch_opportunity_runs",
        "("
        "tenant_ref IS NULL AND entity_ref IS NULL "
        "AND scope_grant_authority_sha256 IS NULL "
        "AND scope_evidence_authority_sha256 IS NULL"
        ") OR ("
        "tenant_ref IS NOT NULL AND length(tenant_ref) > 0 "
        "AND entity_ref IS NOT NULL AND length(entity_ref) > 0 "
        "AND scope_grant_authority_sha256 IS NOT NULL "
        "AND length(scope_grant_authority_sha256) = 64 "
        "AND scope_evidence_authority_sha256 IS NOT NULL "
        "AND length(scope_evidence_authority_sha256) = 64"
        ")",
    )
    op.create_index(
        "uq_batch_opportunity_run_legacy_idempotency",
        "batch_opportunity_runs",
        ["store_ref", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("tenant_ref IS NULL"),
    )
    op.create_index(
        "uq_batch_opportunity_run_scoped_idempotency",
        "batch_opportunity_runs",
        ["tenant_ref", "entity_ref", "store_ref", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("tenant_ref IS NOT NULL"),
    )
    op.create_index(
        "ix_batch_opportunity_run_scope_as_of",
        "batch_opportunity_runs",
        [
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "as_of",
        ],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_batch_opportunity_run_scope_as_of",
        table_name="batch_opportunity_runs",
    )
    op.drop_index(
        "uq_batch_opportunity_run_scoped_idempotency",
        table_name="batch_opportunity_runs",
    )
    op.drop_index(
        "uq_batch_opportunity_run_legacy_idempotency",
        table_name="batch_opportunity_runs",
    )
    op.drop_constraint(
        "ck_batch_opportunity_run_scope_complete",
        "batch_opportunity_runs",
        type_="check",
    )
    op.create_unique_constraint(
        "uq_batch_opportunity_run_idempotency",
        "batch_opportunity_runs",
        ["store_ref", "idempotency_key"],
    )
    op.drop_column(
        "batch_opportunity_runs",
        "scope_evidence_authority_sha256",
    )
    op.drop_column(
        "batch_opportunity_runs",
        "scope_grant_authority_sha256",
    )
    op.drop_column("batch_opportunity_runs", "entity_ref")
    op.drop_column("batch_opportunity_runs", "tenant_ref")
