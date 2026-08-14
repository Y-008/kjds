"""Add native exact-scope actual profit authority.

Revision ID: 20260729_0076
Revises: 20260729_0075
Create Date: 2026-07-29
"""

import sqlalchemy as sa
from alembic import op

revision = "20260729_0076"
down_revision = "20260729_0075"
branch_labels = None
depends_on = None

SCOPE_COLUMNS = (
    ("tenant_ref", sa.String(length=160)),
    ("entity_ref", sa.String(length=160)),
    ("store_ref", sa.String(length=160)),
    ("scope_grant_authority_sha256", sa.String(length=64)),
    ("source_evidence_sha256", sa.String(length=64)),
    ("scope_as_of", sa.DateTime(timezone=True)),
)
SCOPE_CHECK = (
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
)
PROFIT_COST_TYPES = (
    "advertising",
    "capital_cost",
    "customer_compensation",
    "customs",
    "damage",
    "domestic_logistics",
    "fx",
    "international_logistics",
    "last_mile",
    "packaging",
    "platform_fee",
    "product_cost",
    "return",
    "tax",
    "warehousing",
)
PROFIT_COST_VALUES = ", ".join(f"'{item}'" for item in PROFIT_COST_TYPES)
PROFIT_COST_CHECK = (
    "(profit_cost_type IS NULL AND entry_kind <> 'bank_payment') OR ("
    "tenant_ref IS NOT NULL AND entry_kind = 'bank_payment' "
    f"AND profit_cost_type IN ({PROFIT_COST_VALUES}) AND amount <= 0"
    ")"
)


def _add_scope(table: str) -> None:
    for name, column_type in SCOPE_COLUMNS:
        op.add_column(table, sa.Column(name, column_type, nullable=True))
    op.create_check_constraint(
        f"ck_{table}_scope_complete",
        table,
        sa.text(SCOPE_CHECK),
    )


def upgrade() -> None:
    _add_scope("fee_mappings")
    _add_scope("fx_rates")

    op.drop_constraint(
        "uq_fee_mapping_version",
        "fee_mappings",
        type_="unique",
    )
    op.create_index(
        "uq_fee_mapping_legacy_version",
        "fee_mappings",
        ["provider", "raw_code", "effective_from", "version"],
        unique=True,
        postgresql_where=sa.text("tenant_ref IS NULL"),
        sqlite_where=sa.text("tenant_ref IS NULL"),
    )
    op.create_index(
        "uq_fee_mapping_scoped_version",
        "fee_mappings",
        [
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "provider",
            "raw_code",
            "effective_from",
            "version",
        ],
        unique=True,
        postgresql_where=sa.text("tenant_ref IS NOT NULL"),
        sqlite_where=sa.text("tenant_ref IS NOT NULL"),
    )
    op.create_index(
        "ix_fee_mapping_scope_lookup",
        "fee_mappings",
        [
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "provider",
            "raw_code",
            "effective_from",
            "recorded_at",
        ],
    )

    op.drop_constraint(
        "uq_fx_rate_observation",
        "fx_rates",
        type_="unique",
    )
    op.create_index(
        "uq_fx_rate_legacy_observation",
        "fx_rates",
        [
            "base_currency",
            "quote_currency",
            "effective_at",
            "source",
            "version",
        ],
        unique=True,
        postgresql_where=sa.text("tenant_ref IS NULL"),
        sqlite_where=sa.text("tenant_ref IS NULL"),
    )
    op.create_index(
        "uq_fx_rate_scoped_observation",
        "fx_rates",
        [
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "base_currency",
            "quote_currency",
            "effective_at",
            "source",
            "version",
        ],
        unique=True,
        postgresql_where=sa.text("tenant_ref IS NOT NULL"),
        sqlite_where=sa.text("tenant_ref IS NOT NULL"),
    )
    op.create_index(
        "ix_fx_rate_scope_lookup",
        "fx_rates",
        [
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "base_currency",
            "quote_currency",
            "source",
            "effective_at",
            "recorded_at",
        ],
    )

    op.add_column(
        "finance_entries",
        sa.Column("profit_cost_type", sa.String(), nullable=True),
    )
    op.create_check_constraint(
        "ck_finance_entries_profit_cost_type",
        "finance_entries",
        sa.text(PROFIT_COST_CHECK),
    )
    op.create_index(
        "ix_finance_entry_scope_profit",
        "finance_entries",
        [
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "reconciliation_key",
            "profit_cost_type",
            "effective_at",
            "recorded_at",
        ],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_finance_entry_scope_profit",
        table_name="finance_entries",
    )
    op.drop_constraint(
        "ck_finance_entries_profit_cost_type",
        "finance_entries",
        type_="check",
    )
    op.drop_column("finance_entries", "profit_cost_type")

    op.drop_index("ix_fx_rate_scope_lookup", table_name="fx_rates")
    op.drop_index("uq_fx_rate_scoped_observation", table_name="fx_rates")
    op.drop_index("uq_fx_rate_legacy_observation", table_name="fx_rates")
    op.create_unique_constraint(
        "uq_fx_rate_observation",
        "fx_rates",
        [
            "base_currency",
            "quote_currency",
            "effective_at",
            "source",
            "version",
        ],
    )

    op.drop_index(
        "ix_fee_mapping_scope_lookup",
        table_name="fee_mappings",
    )
    op.drop_index(
        "uq_fee_mapping_scoped_version",
        table_name="fee_mappings",
    )
    op.drop_index(
        "uq_fee_mapping_legacy_version",
        table_name="fee_mappings",
    )
    op.create_unique_constraint(
        "uq_fee_mapping_version",
        "fee_mappings",
        ["provider", "raw_code", "effective_from", "version"],
    )

    for table in ("fx_rates", "fee_mappings"):
        op.drop_constraint(
            f"ck_{table}_scope_complete",
            table,
            type_="check",
        )
        for name, _column_type in reversed(SCOPE_COLUMNS):
            op.drop_column(table, name)
