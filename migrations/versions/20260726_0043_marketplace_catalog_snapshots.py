"""Persist verified marketplace catalog snapshots and normalized items."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260726_0043"
down_revision = "20260725_0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "marketplace_catalog_snapshots",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("marketplace", sa.String(length=20), nullable=False),
        sa.Column("store_ref", sa.String(length=160), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("contract_version", sa.String(length=80), nullable=False),
        sa.Column(
            "evidence_ids_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("imported_by", sa.String(length=160), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.UniqueConstraint(
            "store_ref",
            "idempotency_key",
            name="uq_marketplace_catalog_snapshot_idempotency",
        ),
        sa.CheckConstraint(
            "marketplace = 'ozon' "
            "AND char_length(store_ref) > 0 "
            "AND char_length(idempotency_key) > 0 "
            "AND char_length(snapshot_hash) = 64 "
            "AND contract_version = 'ozon-product-read-v1' "
            "AND char_length(imported_by) > 0 "
            "AND item_count > 0",
            name="ck_marketplace_catalog_snapshot_fields",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(evidence_ids_json) = 'array' "
            "AND jsonb_array_length(evidence_ids_json) = item_count",
            name="ck_marketplace_catalog_snapshot_evidence",
        ),
    )
    op.create_table(
        "marketplace_catalog_items",
        sa.Column(
            "snapshot_id",
            sa.String(),
            sa.ForeignKey(
                "marketplace_catalog_snapshots.id",
                ondelete="CASCADE",
                name="fk_marketplace_catalog_item_snapshot",
            ),
            primary_key=True,
        ),
        sa.Column("offer_id", sa.String(length=160), primary_key=True),
        sa.Column("marketplace_sku", sa.String(length=160), nullable=True),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("currency_code", sa.String(length=12), nullable=True),
        sa.Column(
            "prices_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("available_stock", sa.Integer(), nullable=True),
        sa.Column(
            "stocks_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "statuses_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "dimensions_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "attributes_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "attributes_with_defaults_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "complex_attributes_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "image_references_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "video_references_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "document_references_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("media_rights_status", sa.String(length=60), nullable=False),
        sa.Column(
            "source_evidence_id",
            sa.String(),
            sa.ForeignKey(
                "evidence_records.id",
                name="fk_marketplace_catalog_item_evidence",
            ),
            nullable=False,
        ),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("item_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "canonical_product_id",
            sa.String(),
            sa.ForeignKey(
                "products.id",
                name="fk_marketplace_catalog_item_product",
            ),
            nullable=True,
        ),
        sa.CheckConstraint(
            "char_length(offer_id) > 0 "
            "AND char_length(name) > 0 "
            "AND (available_stock IS NULL OR available_stock >= 0) "
            "AND media_rights_status = 'unverified_external_reference' "
            "AND char_length(item_hash) = 64",
            name="ck_marketplace_catalog_item_fields",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(prices_json) = 'object' "
            "AND jsonb_typeof(stocks_json) = 'array' "
            "AND jsonb_typeof(statuses_json) = 'object' "
            "AND jsonb_typeof(dimensions_json) = 'object' "
            "AND jsonb_typeof(attributes_json) = 'array' "
            "AND jsonb_typeof(attributes_with_defaults_json) = 'array' "
            "AND jsonb_typeof(complex_attributes_json) = 'array' "
            "AND jsonb_typeof(image_references_json) = 'array' "
            "AND jsonb_typeof(video_references_json) = 'array' "
            "AND jsonb_typeof(document_references_json) = 'array'",
            name="ck_marketplace_catalog_item_json",
        ),
    )
    op.create_index(
        "ix_marketplace_catalog_item_latest",
        "marketplace_catalog_items",
        ["offer_id", "observed_at"],
    )
    op.create_index(
        "ix_marketplace_catalog_snapshot_store",
        "marketplace_catalog_snapshots",
        ["store_ref", "observed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_marketplace_catalog_snapshot_store",
        table_name="marketplace_catalog_snapshots",
    )
    op.drop_index(
        "ix_marketplace_catalog_item_latest",
        table_name="marketplace_catalog_items",
    )
    op.drop_table("marketplace_catalog_items")
    op.drop_table("marketplace_catalog_snapshots")
