"""Add marketplace observation snapshots for portfolio pilot screening."""

import sqlalchemy as sa
from alembic import op

revision = "20260726_0052"
down_revision = "20260726_0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "marketplace_observation_snapshots",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("source_profile", sa.String(), nullable=False),
        sa.Column("marketplace", sa.String(), nullable=False),
        sa.Column("store_ref", sa.String(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("contract_version", sa.String(), nullable=False),
        sa.Column(
            "evidence_id",
            sa.String(),
            sa.ForeignKey("evidence_records.id"),
            nullable=False,
        ),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("captured_by", sa.String(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.UniqueConstraint(
            "source_profile",
            "idempotency_key",
            name="uq_marketplace_observation_idempotency",
        ),
        sa.CheckConstraint(
            "source_profile IN "
            "('browser_observation','seller_tool_export',"
            "'manual_verified_public_page')",
            name="ck_marketplace_observation_source_profile",
        ),
        sa.CheckConstraint(
            "marketplace IN ('1688','ozon')",
            name="ck_marketplace_observation_marketplace",
        ),
        sa.CheckConstraint(
            "item_count > 0",
            name="ck_marketplace_observation_item_count",
        ),
    )
    op.create_index(
        "ix_marketplace_observation_snapshot_latest",
        "marketplace_observation_snapshots",
        ["marketplace", "store_ref", "observed_at"],
    )
    op.create_table(
        "marketplace_observation_items",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "snapshot_id",
            sa.String(),
            sa.ForeignKey("marketplace_observation_snapshots.id"),
            nullable=False,
        ),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("item_sha256", sa.String(64), nullable=False),
        sa.Column("external_item_id", sa.String(), nullable=False),
        sa.Column("supplier_ref", sa.String(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("variant_key", sa.String(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column(
            "displayed_price_decimal",
            sa.Numeric(38, 12),
            nullable=False,
        ),
        sa.Column("price_kind", sa.String(), nullable=False),
        sa.Column("min_order_quantity", sa.Integer(), nullable=True),
        sa.Column("availability", sa.String(), nullable=False),
        sa.Column("specifications_json", sa.JSON(), nullable=False),
        sa.Column("target_product_id", sa.String(), nullable=True),
        sa.Column("target_offer_id", sa.String(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "evidence_id",
            sa.String(),
            sa.ForeignKey("evidence_records.id"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "snapshot_id",
            "fingerprint",
            name="uq_marketplace_observation_item_fingerprint",
        ),
        sa.CheckConstraint(
            "displayed_price_decimal > 0",
            name="ck_marketplace_observation_price_positive",
        ),
        sa.CheckConstraint(
            "min_order_quantity IS NULL OR min_order_quantity > 0",
            name="ck_marketplace_observation_moq_positive",
        ),
        sa.CheckConstraint(
            "price_kind IN "
            "('public_display_price','new_customer_price','member_price',"
            "'range_minimum','marketplace_listing_price')",
            name="ck_marketplace_observation_price_kind",
        ),
    )
    op.create_index(
        "ix_marketplace_observation_item_latest",
        "marketplace_observation_items",
        ["target_product_id", "observed_at"],
    )
    op.create_index(
        "ix_marketplace_observation_item_supplier",
        "marketplace_observation_items",
        ["supplier_ref", "external_item_id", "variant_key"],
    )
    for table in (
        "marketplace_observation_snapshots",
        "marketplace_observation_items",
    ):
        op.execute(sa.text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
        op.execute(
            sa.text(
                f'CREATE TRIGGER "trg_{table}_immutable" '
                f'BEFORE UPDATE OR DELETE ON "{table}" '
                "FOR EACH ROW EXECUTE FUNCTION kjds_prevent_ledger_mutation()"
            )
        )


def downgrade() -> None:
    op.drop_index(
        "ix_marketplace_observation_item_supplier",
        table_name="marketplace_observation_items",
    )
    op.drop_index(
        "ix_marketplace_observation_item_latest",
        table_name="marketplace_observation_items",
    )
    op.drop_table("marketplace_observation_items")
    op.drop_index(
        "ix_marketplace_observation_snapshot_latest",
        table_name="marketplace_observation_snapshots",
    )
    op.drop_table("marketplace_observation_snapshots")
