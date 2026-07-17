"""Add evidence-backed sample procurement episodes."""

import sqlalchemy as sa
from alembic import op

revision = "20260716_0011"
down_revision = "20260716_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sample_purchase_orders",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("approval_id", sa.String(), sa.ForeignKey("approvals.id"), nullable=False, unique=True),
        sa.Column("product_id", sa.String(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("offer_id", sa.String(), sa.ForeignKey("source_offers.id"), nullable=False),
        sa.Column("scenario_id", sa.String(), sa.ForeignKey("profit_scenarios.id"), nullable=False),
        sa.Column("supplier_ref", sa.String(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("unit_price", sa.Numeric(38, 12), nullable=False),
        sa.Column("requested_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_sample_orders_product", "sample_purchase_orders", ["product_id", "created_at"])
    op.create_index("idx_sample_orders_supplier", "sample_purchase_orders", ["supplier_ref", "created_at"])
    op.create_table(
        "sample_procurement_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("purchase_order_id", sa.String(), sa.ForeignKey("sample_purchase_orders.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_id", sa.String(), sa.ForeignKey("evidence_records.id"), nullable=False),
        sa.Column("facts_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("purchase_order_id", "sequence", name="uq_sample_event_sequence"),
        sa.UniqueConstraint("purchase_order_id", "event_type", "evidence_id", name="uq_sample_event_evidence"),
    )
    op.create_index("idx_sample_events_timeline", "sample_procurement_events", ["purchase_order_id", "sequence"])
    for table in ("sample_purchase_orders", "sample_procurement_events"):
        op.execute(sa.text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
        op.execute(
            sa.text(
                f'CREATE TRIGGER "trg_{table}_immutable" BEFORE UPDATE OR DELETE ON "{table}" '
                "FOR EACH ROW EXECUTE FUNCTION kjds_prevent_ledger_mutation()"
            )
        )


def downgrade() -> None:
    op.drop_index("idx_sample_events_timeline", table_name="sample_procurement_events")
    op.drop_table("sample_procurement_events")
    op.drop_index("idx_sample_orders_supplier", table_name="sample_purchase_orders")
    op.drop_index("idx_sample_orders_product", table_name="sample_purchase_orders")
    op.drop_table("sample_purchase_orders")
