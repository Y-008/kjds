"""Add native exact-scope finance authority.

Revision ID: 20260729_0075
Revises: 20260729_0074
Create Date: 2026-07-29
"""

import sqlalchemy as sa
from alembic import op

revision = "20260729_0075"
down_revision = "20260729_0074"
branch_labels = None
depends_on = None

SCOPE_TABLES = (
    "finance_entries",
    "reconciliation_runs",
    "cash_plan_items",
)
SCOPE_COLUMNS = (
    ("tenant_ref", sa.String(length=160)),
    ("entity_ref", sa.String(length=160)),
    ("store_ref", sa.String(length=160)),
    ("scope_grant_authority_sha256", sa.String(length=64)),
    ("source_evidence_sha256", sa.String(length=64)),
    ("scope_as_of", sa.DateTime(timezone=True)),
)


def _scope_check(table: str) -> None:
    op.create_check_constraint(
        f"ck_{table}_scope_complete",
        table,
        sa.text(
            "("
            "tenant_ref IS NULL AND entity_ref IS NULL AND store_ref IS NULL "
            "AND scope_grant_authority_sha256 IS NULL "
            "AND source_evidence_sha256 IS NULL AND scope_as_of IS NULL"
            ") OR ("
            "tenant_ref IS NOT NULL AND length(tenant_ref) > 0 "
            "AND entity_ref IS NOT NULL AND length(entity_ref) > 0 "
            "AND store_ref IS NOT NULL AND length(store_ref) > 0 "
            "AND scope_grant_authority_sha256 IS NOT NULL "
            "AND length(scope_grant_authority_sha256) = 64 "
            "AND source_evidence_sha256 IS NOT NULL "
            "AND length(source_evidence_sha256) = 64 "
            "AND scope_as_of IS NOT NULL"
            ")"
        ),
    )


def upgrade() -> None:
    for table in SCOPE_TABLES:
        for name, column_type in SCOPE_COLUMNS:
            op.add_column(
                table,
                sa.Column(name, column_type, nullable=True),
            )
        _scope_check(table)

    op.drop_constraint(
        "uq_finance_source_entry",
        "finance_entries",
        type_="unique",
    )
    op.drop_constraint(
        "uq_finance_source_fact",
        "finance_entries",
        type_="unique",
    )
    op.create_index(
        "uq_finance_entry_legacy_source",
        "finance_entries",
        ["source", "source_ref", "entry_kind"],
        unique=True,
        postgresql_where=sa.text("tenant_ref IS NULL"),
        sqlite_where=sa.text("tenant_ref IS NULL"),
    )
    op.create_index(
        "uq_finance_entry_scoped_source",
        "finance_entries",
        [
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "source",
            "source_ref",
            "entry_kind",
        ],
        unique=True,
        postgresql_where=sa.text("tenant_ref IS NOT NULL"),
        sqlite_where=sa.text("tenant_ref IS NOT NULL"),
    )
    op.create_index(
        "uq_finance_entry_legacy_fact",
        "finance_entries",
        ["source_fact_id"],
        unique=True,
        postgresql_where=sa.text(
            "tenant_ref IS NULL AND source_fact_id IS NOT NULL"
        ),
        sqlite_where=sa.text(
            "tenant_ref IS NULL AND source_fact_id IS NOT NULL"
        ),
    )
    op.create_index(
        "uq_finance_entry_scoped_fact",
        "finance_entries",
        ["tenant_ref", "entity_ref", "store_ref", "source_fact_id"],
        unique=True,
        postgresql_where=sa.text(
            "tenant_ref IS NOT NULL AND source_fact_id IS NOT NULL"
        ),
        sqlite_where=sa.text(
            "tenant_ref IS NOT NULL AND source_fact_id IS NOT NULL"
        ),
    )
    op.create_index(
        "ix_finance_entry_scope_reconciliation",
        "finance_entries",
        [
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "reconciliation_key",
            "effective_at",
            "recorded_at",
        ],
    )
    op.create_index(
        "ix_reconciliation_scope_key_recorded",
        "reconciliation_runs",
        [
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "reconciliation_key",
            "recorded_at",
        ],
    )

    op.drop_constraint(
        "uq_cash_plan_source",
        "cash_plan_items",
        type_="unique",
    )
    op.create_index(
        "uq_cash_plan_legacy_source",
        "cash_plan_items",
        ["source", "source_ref"],
        unique=True,
        postgresql_where=sa.text("tenant_ref IS NULL"),
        sqlite_where=sa.text("tenant_ref IS NULL"),
    )
    op.create_index(
        "uq_cash_plan_scoped_source",
        "cash_plan_items",
        ["tenant_ref", "entity_ref", "store_ref", "source", "source_ref"],
        unique=True,
        postgresql_where=sa.text("tenant_ref IS NOT NULL"),
        sqlite_where=sa.text("tenant_ref IS NOT NULL"),
    )
    op.create_index(
        "ix_cash_plan_scope_window",
        "cash_plan_items",
        [
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "expected_at",
            "recorded_at",
        ],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_cash_plan_scope_window",
        table_name="cash_plan_items",
    )
    op.drop_index(
        "uq_cash_plan_scoped_source",
        table_name="cash_plan_items",
    )
    op.drop_index(
        "uq_cash_plan_legacy_source",
        table_name="cash_plan_items",
    )
    op.create_unique_constraint(
        "uq_cash_plan_source",
        "cash_plan_items",
        ["source", "source_ref"],
    )

    op.drop_index(
        "ix_reconciliation_scope_key_recorded",
        table_name="reconciliation_runs",
    )
    op.drop_index(
        "ix_finance_entry_scope_reconciliation",
        table_name="finance_entries",
    )
    op.drop_index(
        "uq_finance_entry_scoped_fact",
        table_name="finance_entries",
    )
    op.drop_index(
        "uq_finance_entry_legacy_fact",
        table_name="finance_entries",
    )
    op.drop_index(
        "uq_finance_entry_scoped_source",
        table_name="finance_entries",
    )
    op.drop_index(
        "uq_finance_entry_legacy_source",
        table_name="finance_entries",
    )
    op.create_unique_constraint(
        "uq_finance_source_entry",
        "finance_entries",
        ["source", "source_ref", "entry_kind"],
    )
    op.create_unique_constraint(
        "uq_finance_source_fact",
        "finance_entries",
        ["source_fact_id"],
    )

    for table in reversed(SCOPE_TABLES):
        op.drop_constraint(
            f"ck_{table}_scope_complete",
            table,
            type_="check",
        )
        for name, _column_type in reversed(SCOPE_COLUMNS):
            op.drop_column(table, name)
