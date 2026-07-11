"""Initial Hermes control-plane schema."""

import sqlalchemy as sa
from alembic import op

revision = "20260711_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("sku", sa.String(), nullable=False, unique=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("market", sa.String(), nullable=False),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "passports",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("product_id", sa.String(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("facts_json", sa.JSON(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("approved_by", sa.String()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("product_id", "kind", "version"),
    )
    op.create_table(
        "market_observations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("market", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("metric", sa.String(), nullable=False),
        sa.Column("value_decimal", sa.Numeric(24, 8), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_ref", sa.String(), nullable=False),
        sa.Column("confidence_decimal", sa.Numeric(8, 6), nullable=False),
        sa.Column("dimensions_json", sa.JSON(), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_observation_slice", "market_observations", ["market", "category", "metric", "observed_at"])
    op.create_table(
        "opportunities",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("market", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("score_decimal", sa.Numeric(12, 6), nullable=False),
        sa.Column("rationale_json", sa.JSON(), nullable=False),
        sa.Column("evidence_ids_json", sa.JSON(), nullable=False),
        sa.Column("recommended_action", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "content_assets",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("product_id", sa.String(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("locale", sa.String(), nullable=False),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column("brief_json", sa.JSON(), nullable=False),
        sa.Column("source_facts_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("artifact_ref", sa.String()),
        sa.Column("qa_results_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "growth_experiments",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("product_id", sa.String(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column("hypothesis", sa.Text(), nullable=False),
        sa.Column("primary_metric", sa.String(), nullable=False),
        sa.Column("budget_cap_cny_decimal", sa.Numeric(24, 8), nullable=False),
        sa.Column("stop_loss_cny_decimal", sa.Numeric(24, 8), nullable=False),
        sa.Column("variants_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "orders",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("external_id", sa.String(), nullable=False, unique=True),
        sa.Column("product_id", sa.String(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("gross_revenue_decimal", sa.Numeric(24, 8), nullable=False),
        sa.Column("booked_fx_rate_decimal", sa.Numeric(24, 10), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "charges",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("order_id", sa.String(), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("amount_decimal", sa.Numeric(24, 8), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("fx_rate_decimal", sa.Numeric(24, 10), nullable=False),
        sa.Column("evidence_ref", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "approvals",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("resource_type", sa.String(), nullable=False),
        sa.Column("resource_id", sa.String(), nullable=False),
        sa.Column("requested_by", sa.String(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("decided_by", sa.String()),
        sa.Column("decision_reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "agent_tasks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("agent", sa.String(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("task_type", sa.String(), nullable=False),
        sa.Column("input_json", sa.JSON(), nullable=False),
        sa.Column("requested_by", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "outbox_events",
        sa.Column("sequence", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("aggregate_id", sa.String(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "connector_cursors",
        sa.Column("connector", sa.String(), primary_key=True),
        sa.Column("cursor", sa.Text()),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
    )


def downgrade() -> None:
    for table in [
        "connector_cursors",
        "outbox_events",
        "agent_tasks",
        "approvals",
        "charges",
        "orders",
        "growth_experiments",
        "content_assets",
        "opportunities",
        "market_observations",
        "passports",
        "products",
    ]:
        op.drop_table(table)
