"""Add sourcing pipeline and Supabase-safe access boundaries."""

import sqlalchemy as sa
from alembic import op

revision = "20260713_0003"
down_revision = "20260712_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_offers",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("platform", sa.String(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("unit_price_decimal", sa.Numeric(24, 8), nullable=False),
        sa.Column("source_to_cny_rate_decimal", sa.Numeric(24, 10), nullable=False),
        sa.Column("min_order_quantity", sa.Integer(), nullable=False),
        sa.Column("weight_kg_decimal", sa.Numeric(18, 6), nullable=False),
        sa.Column("length_cm_decimal", sa.Numeric(18, 4), nullable=False),
        sa.Column("width_cm_decimal", sa.Numeric(18, 4), nullable=False),
        sa.Column("height_cm_decimal", sa.Numeric(18, 4), nullable=False),
        sa.Column("domestic_logistics_per_unit_decimal", sa.Numeric(24, 8), nullable=False),
        sa.Column("evidence_ref", sa.Text(), nullable=False),
        sa.Column("attributes_json", sa.JSON(), nullable=False),
        sa.Column("media_json", sa.JSON(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("platform", "external_id"),
    )
    op.create_index("idx_source_offers_platform_captured", "source_offers", ["platform", "captured_at"])
    op.create_table(
        "profit_scenarios",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("offer_id", sa.String(), sa.ForeignKey("source_offers.id"), nullable=False),
        sa.Column("target_platform", sa.String(), nullable=False),
        sa.Column("inputs_json", sa.JSON(), nullable=False),
        sa.Column("revenue_cny_decimal", sa.Numeric(24, 8), nullable=False),
        sa.Column("purchase_cny_decimal", sa.Numeric(24, 8), nullable=False),
        sa.Column("domestic_logistics_cny_decimal", sa.Numeric(24, 8), nullable=False),
        sa.Column("international_logistics_cny_decimal", sa.Numeric(24, 8), nullable=False),
        sa.Column("packaging_cny_decimal", sa.Numeric(24, 8), nullable=False),
        sa.Column("customs_cny_decimal", sa.Numeric(24, 8), nullable=False),
        sa.Column("last_mile_cny_decimal", sa.Numeric(24, 8), nullable=False),
        sa.Column("platform_fee_cny_decimal", sa.Numeric(24, 8), nullable=False),
        sa.Column("advertising_cny_decimal", sa.Numeric(24, 8), nullable=False),
        sa.Column("return_reserve_cny_decimal", sa.Numeric(24, 8), nullable=False),
        sa.Column("other_cost_cny_decimal", sa.Numeric(24, 8), nullable=False),
        sa.Column("total_cost_cny_decimal", sa.Numeric(24, 8), nullable=False),
        sa.Column("cm3_cny_decimal", sa.Numeric(24, 8), nullable=False),
        sa.Column("cm3_rate_decimal", sa.Numeric(12, 6), nullable=False),
        sa.Column("break_even_price_rub_decimal", sa.Numeric(24, 8), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "listing_drafts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("product_id", sa.String(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("offer_id", sa.String(), sa.ForeignKey("source_offers.id"), nullable=False),
        sa.Column("scenario_id", sa.String(), sa.ForeignKey("profit_scenarios.id"), nullable=False),
        sa.Column("target_platform", sa.String(), nullable=False),
        sa.Column("listing_json", sa.JSON(), nullable=False),
        sa.Column("requested_by", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("approval_id", sa.String(), sa.ForeignKey("approvals.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # Supabase exposes the public schema through its Data API. RLS keeps these
    # business tables private unless explicit policies are added later. The
    # trusted FastAPI database owner continues to use its normal privileges.
    tables = [
        "products", "passports", "orders", "charges", "approvals", "agent_tasks",
        "market_observations", "opportunities", "content_assets", "growth_experiments",
        "outbox_events", "import_jobs", "import_rows", "model_registry",
        "decision_recommendations", "source_offers", "profit_scenarios", "listing_drafts",
    ]
    for table in tables:
        op.execute(sa.text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))


def downgrade() -> None:
    op.drop_table("listing_drafts")
    op.drop_table("profit_scenarios")
    op.drop_index("idx_source_offers_platform_captured", table_name="source_offers")
    op.drop_table("source_offers")
