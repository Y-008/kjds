"""Add native scope to Product and Listing approval plans."""

import sqlalchemy as sa
from alembic import op

revision = "20260728_0059"
down_revision = "20260728_0058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column in (
        sa.Column("tenant_ref", sa.String(160), nullable=True),
        sa.Column("entity_ref", sa.String(160), nullable=True),
        sa.Column("store_ref", sa.String(160), nullable=True),
        sa.Column(
            "scope_grant_authority_sha256",
            sa.String(64),
            nullable=True,
        ),
        sa.Column(
            "scope_as_of",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("created_by", sa.String(160), nullable=True),
    ):
        op.add_column("products", column)

    op.drop_constraint("products_sku_key", "products", type_="unique")
    op.create_check_constraint(
        "ck_product_scope_complete",
        "products",
        "("
        "tenant_ref IS NULL AND entity_ref IS NULL AND store_ref IS NULL "
        "AND scope_grant_authority_sha256 IS NULL AND scope_as_of IS NULL "
        "AND created_by IS NULL"
        ") OR ("
        "tenant_ref IS NOT NULL AND length(tenant_ref) > 0 "
        "AND entity_ref IS NOT NULL AND length(entity_ref) > 0 "
        "AND store_ref IS NOT NULL AND length(store_ref) > 0 "
        "AND scope_grant_authority_sha256 IS NOT NULL "
        "AND length(scope_grant_authority_sha256) = 64 "
        "AND scope_as_of IS NOT NULL "
        "AND created_by IS NOT NULL AND length(created_by) > 0"
        ")",
    )
    op.create_index(
        "uq_product_legacy_sku",
        "products",
        ["sku"],
        unique=True,
        postgresql_where=sa.text("tenant_ref IS NULL"),
    )
    op.create_index(
        "uq_product_scoped_sku",
        "products",
        ["tenant_ref", "entity_ref", "store_ref", "sku"],
        unique=True,
        postgresql_where=sa.text("tenant_ref IS NOT NULL"),
    )
    op.create_index(
        "ix_product_scope_created",
        "products",
        ["tenant_ref", "entity_ref", "store_ref", "created_at"],
    )

    listing_columns = (
        sa.Column("tenant_ref", sa.String(160), nullable=True),
        sa.Column("entity_ref", sa.String(160), nullable=True),
        sa.Column("store_ref", sa.String(160), nullable=True),
        sa.Column(
            "scope_grant_authority_sha256",
            sa.String(64),
            nullable=True,
        ),
        sa.Column(
            "scoped_product_content_sha256",
            sa.String(64),
            nullable=True,
        ),
        sa.Column(
            "approval_plan_sha256",
            sa.String(64),
            nullable=True,
        ),
        sa.Column("evidence_ids_json", sa.JSON(), nullable=True),
        sa.Column(
            "scope_as_of",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    for column in listing_columns:
        op.add_column("listing_drafts", column)
    op.create_check_constraint(
        "ck_listing_draft_scope_complete",
        "listing_drafts",
        "("
        "tenant_ref IS NULL AND entity_ref IS NULL AND store_ref IS NULL "
        "AND scope_grant_authority_sha256 IS NULL "
        "AND scoped_product_content_sha256 IS NULL "
        "AND approval_plan_sha256 IS NULL "
        "AND evidence_ids_json IS NULL AND scope_as_of IS NULL"
        ") OR ("
        "tenant_ref IS NOT NULL AND length(tenant_ref) > 0 "
        "AND entity_ref IS NOT NULL AND length(entity_ref) > 0 "
        "AND store_ref IS NOT NULL AND length(store_ref) > 0 "
        "AND scope_grant_authority_sha256 IS NOT NULL "
        "AND length(scope_grant_authority_sha256) = 64 "
        "AND scoped_product_content_sha256 IS NOT NULL "
        "AND length(scoped_product_content_sha256) = 64 "
        "AND approval_plan_sha256 IS NOT NULL "
        "AND length(approval_plan_sha256) = 64 "
        "AND evidence_ids_json IS NOT NULL "
        "AND jsonb_typeof(evidence_ids_json::jsonb) = 'array' "
        "AND jsonb_array_length(evidence_ids_json::jsonb) > 0 "
        "AND scope_as_of IS NOT NULL"
        ")",
    )
    op.create_index(
        "ix_listing_draft_scope_created",
        "listing_drafts",
        ["tenant_ref", "entity_ref", "store_ref", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_listing_draft_scope_created",
        table_name="listing_drafts",
    )
    op.drop_constraint(
        "ck_listing_draft_scope_complete",
        "listing_drafts",
        type_="check",
    )
    for column in (
        "scope_as_of",
        "evidence_ids_json",
        "approval_plan_sha256",
        "scoped_product_content_sha256",
        "scope_grant_authority_sha256",
        "store_ref",
        "entity_ref",
        "tenant_ref",
    ):
        op.drop_column("listing_drafts", column)

    op.drop_index("ix_product_scope_created", table_name="products")
    op.drop_index("uq_product_scoped_sku", table_name="products")
    op.drop_index("uq_product_legacy_sku", table_name="products")
    op.drop_constraint(
        "ck_product_scope_complete",
        "products",
        type_="check",
    )
    op.create_unique_constraint("products_sku_key", "products", ["sku"])
    for column in (
        "created_by",
        "scope_as_of",
        "scope_grant_authority_sha256",
        "store_ref",
        "entity_ref",
        "tenant_ref",
    ):
        op.drop_column("products", column)
