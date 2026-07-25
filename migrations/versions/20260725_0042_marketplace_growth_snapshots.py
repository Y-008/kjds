"""Persist immutable marketplace growth snapshots and observations."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260725_0042"
down_revision = "20260724_0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "marketplace_growth_snapshots",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("captured_by", sa.String(length=160), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observation_count", sa.Integer(), nullable=False),
        sa.UniqueConstraint(
            "source",
            "idempotency_key",
            name="uq_marketplace_growth_snapshot_idempotency",
        ),
        sa.CheckConstraint(
            "source IN ('ozon_seller_api', 'ozon_export', 'operator_verified')",
            name="ck_marketplace_growth_snapshot_source",
        ),
        sa.CheckConstraint(
            "char_length(idempotency_key) > 0 "
            "AND char_length(snapshot_hash) = 64 "
            "AND char_length(captured_by) > 0 "
            "AND observation_count > 0",
            name="ck_marketplace_growth_snapshot_fields",
        ),
    )
    op.create_table(
        "marketplace_growth_observations",
        sa.Column(
            "snapshot_id",
            sa.String(),
            sa.ForeignKey(
                "marketplace_growth_snapshots.id",
                ondelete="CASCADE",
                name="fk_marketplace_growth_observation_snapshot",
            ),
            primary_key=True,
        ),
        sa.Column("marketplace_sku", sa.String(length=120), primary_key=True),
        sa.Column("scenario_id", sa.String(length=120), nullable=False),
        sa.Column("category", sa.String(length=300), nullable=False),
        sa.Column(
            "competitor_prices_rub_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("stock", sa.Integer(), nullable=False),
        sa.Column("review_count", sa.Integer(), nullable=False),
        sa.Column("orders_14d", sa.Integer(), nullable=False),
        sa.Column("rating_decimal", sa.Numeric(8, 4), nullable=False),
        sa.Column("content_score_decimal", sa.Numeric(8, 4), nullable=False),
        sa.Column("conversion_rate_decimal", sa.Numeric(8, 4), nullable=True),
        sa.Column("compliance_risk", sa.String(length=12), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "evidence_ids_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("observation_hash", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "char_length(marketplace_sku) > 0 "
            "AND char_length(scenario_id) > 0 "
            "AND char_length(category) > 0 "
            "AND stock >= 0 AND review_count >= 0 AND orders_14d >= 0 "
            "AND rating_decimal >= 0 AND rating_decimal <= 5 "
            "AND content_score_decimal >= 0 AND content_score_decimal <= 100 "
            "AND (conversion_rate_decimal IS NULL "
            "OR (conversion_rate_decimal >= 0 AND conversion_rate_decimal <= 1)) "
            "AND compliance_risk IN ('low', 'medium', 'high') "
            "AND char_length(observation_hash) = 64",
            name="ck_marketplace_growth_observation_fields",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(competitor_prices_rub_json) = 'array' "
            "AND jsonb_array_length(competitor_prices_rub_json) >= 3 "
            "AND jsonb_typeof(evidence_ids_json) = 'array' "
            "AND jsonb_array_length(evidence_ids_json) >= 1",
            name="ck_marketplace_growth_observation_json",
        ),
    )
    op.create_index(
        "ix_marketplace_growth_observation_latest",
        "marketplace_growth_observations",
        ["marketplace_sku", "observed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_marketplace_growth_observation_latest",
        table_name="marketplace_growth_observations",
    )
    op.drop_table("marketplace_growth_observations")
    op.drop_table("marketplace_growth_snapshots")
