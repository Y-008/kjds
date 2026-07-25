"""Add order-triggered procurement and cross-border fulfillment ledger."""

import sqlalchemy as sa
from alembic import op

revision = "20260725_0041"
down_revision = "20260721_0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sales_fulfillment_plans",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("sales_order_id", sa.String(), sa.ForeignKey("orders.id"), nullable=False, unique=True),
        sa.Column("product_id", sa.String(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_sales_fulfillment_quantity"),
    )
    op.create_index(
        "idx_sales_fulfillment_product",
        "sales_fulfillment_plans",
        ["product_id", "created_at"],
    )
    op.create_table(
        "sales_fulfillment_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "plan_id",
            sa.String(),
            sa.ForeignKey("sales_fulfillment_plans.id"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_id", sa.String(), sa.ForeignKey("evidence_records.id"), nullable=False),
        sa.Column("facts_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sequence > 0", name="ck_sales_fulfillment_event_sequence"),
        sa.UniqueConstraint("plan_id", "sequence", name="uq_sales_fulfillment_event_sequence"),
        sa.UniqueConstraint(
            "plan_id",
            "event_type",
            "evidence_id",
            name="uq_sales_fulfillment_event_evidence",
        ),
    )
    op.create_index(
        "idx_sales_fulfillment_events_timeline",
        "sales_fulfillment_events",
        ["plan_id", "sequence"],
    )
    for table in ("sales_fulfillment_plans", "sales_fulfillment_events"):
        op.execute(sa.text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
        op.execute(
            sa.text(
                f'CREATE TRIGGER "trg_{table}_immutable" BEFORE UPDATE OR DELETE ON "{table}" '
                "FOR EACH ROW EXECUTE FUNCTION kjds_prevent_ledger_mutation()"
            )
        )


def downgrade() -> None:
    op.drop_index(
        "idx_sales_fulfillment_events_timeline",
        table_name="sales_fulfillment_events",
    )
    op.drop_table("sales_fulfillment_events")
    op.drop_index("idx_sales_fulfillment_product", table_name="sales_fulfillment_plans")
    op.drop_table("sales_fulfillment_plans")
