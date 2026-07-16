"""Add evidence-backed finance classification, reconciliation, and cash planning."""

import sqlalchemy as sa
from alembic import op

revision = "20260716_0007"
down_revision = "20260716_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fee_mappings",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("raw_code", sa.String(), nullable=False),
        sa.Column("canonical_type", sa.String(), nullable=False),
        sa.Column("sign_rule", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_until", sa.DateTime(timezone=True)),
        sa.Column("evidence_id", sa.String(), sa.ForeignKey("evidence_records.id"), nullable=False),
        sa.Column("approved_by", sa.String(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "provider", "raw_code", "effective_from", "version", name="uq_fee_mapping_version"
        ),
    )
    op.create_index(
        "idx_fee_mapping_lookup", "fee_mappings", ["provider", "raw_code", "effective_from"]
    )
    op.create_table(
        "fx_rates",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("base_currency", sa.String(3), nullable=False),
        sa.Column("quote_currency", sa.String(3), nullable=False),
        sa.Column("rate", sa.Numeric(38, 12), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("evidence_id", sa.String(), sa.ForeignKey("evidence_records.id"), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "base_currency",
            "quote_currency",
            "effective_at",
            "source",
            "version",
            name="uq_fx_rate_observation",
        ),
    )
    op.create_index(
        "idx_fx_rate_lookup", "fx_rates", ["base_currency", "quote_currency", "source", "effective_at"]
    )
    op.create_table(
        "finance_entries",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("entry_kind", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("source_ref", sa.String(), nullable=False),
        sa.Column("reconciliation_key", sa.String(), nullable=False),
        sa.Column("raw_fee_code", sa.String()),
        sa.Column("amount", sa.Numeric(38, 12), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_id", sa.String(), sa.ForeignKey("evidence_records.id"), nullable=False),
        sa.Column("source_fact_id", sa.String(), sa.ForeignKey("fact_records.id")),
        sa.Column("review_required", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source", "source_ref", "entry_kind", name="uq_finance_source_entry"),
        sa.UniqueConstraint("source_fact_id", name="uq_finance_source_fact"),
    )
    op.create_index(
        "idx_finance_reconciliation", "finance_entries", ["reconciliation_key", "effective_at"]
    )
    op.create_table(
        "reconciliation_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("reconciliation_key", sa.String(), nullable=False),
        sa.Column("quote_currency", sa.String(3), nullable=False),
        sa.Column("fx_source", sa.String(), nullable=False),
        sa.Column("tolerance_ratio", sa.Numeric(18, 12), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "idx_reconciliation_runs", "reconciliation_runs", ["reconciliation_key", "recorded_at"]
    )
    op.create_table(
        "cash_plan_items",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("source_ref", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("amount", sa.Numeric(38, 12), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("expected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("probability", sa.Numeric(18, 12), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("evidence_id", sa.String(), sa.ForeignKey("evidence_records.id"), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source", "source_ref", name="uq_cash_plan_source"),
    )
    op.create_index("idx_cash_plan_window", "cash_plan_items", ["expected_at", "status"])

    for table in (
        "fee_mappings",
        "fx_rates",
        "finance_entries",
        "reconciliation_runs",
        "cash_plan_items",
    ):
        op.execute(sa.text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
        op.execute(
            sa.text(
                f'CREATE TRIGGER "trg_{table}_immutable" BEFORE UPDATE OR DELETE ON "{table}" '
                "FOR EACH ROW EXECUTE FUNCTION kjds_prevent_ledger_mutation()"
            )
        )


def downgrade() -> None:
    op.drop_index("idx_cash_plan_window", table_name="cash_plan_items")
    op.drop_table("cash_plan_items")
    op.drop_index("idx_reconciliation_runs", table_name="reconciliation_runs")
    op.drop_table("reconciliation_runs")
    op.drop_index("idx_finance_reconciliation", table_name="finance_entries")
    op.drop_table("finance_entries")
    op.drop_index("idx_fx_rate_lookup", table_name="fx_rates")
    op.drop_table("fx_rates")
    op.drop_index("idx_fee_mapping_lookup", table_name="fee_mappings")
    op.drop_table("fee_mappings")
