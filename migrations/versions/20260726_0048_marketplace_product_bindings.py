"""Bind immutable marketplace listing identities to canonical products."""

import sqlalchemy as sa
from alembic import op

revision = "20260726_0048"
down_revision = "20260726_0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "marketplace_product_bindings",
        sa.Column("marketplace", sa.String(length=20), primary_key=True),
        sa.Column("store_ref", sa.String(length=160), primary_key=True),
        sa.Column("offer_id", sa.String(length=160), primary_key=True),
        sa.Column("marketplace_sku", sa.String(length=160), nullable=True),
        sa.Column(
            "product_id",
            sa.String(),
            sa.ForeignKey(
                "products.id",
                name="fk_marketplace_product_binding_product",
            ),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "source_evidence_id",
            sa.String(),
            sa.ForeignKey(
                "evidence_records.id",
                name="fk_marketplace_product_binding_evidence",
            ),
            nullable=False,
        ),
        sa.Column("item_hash", sa.String(length=64), nullable=False),
        sa.Column("bound_by", sa.String(length=160), nullable=False),
        sa.Column("bound_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "marketplace = 'ozon' "
            "AND char_length(store_ref) > 0 "
            "AND char_length(offer_id) > 0 "
            "AND char_length(product_id) > 0 "
            "AND char_length(source_evidence_id) > 0 "
            "AND char_length(item_hash) = 64 "
            "AND char_length(bound_by) > 0",
            name="ck_marketplace_product_binding_fields",
        ),
    )
    op.create_index(
        "ix_marketplace_product_binding_store",
        "marketplace_product_bindings",
        ["marketplace", "store_ref"],
    )
    op.execute(
        sa.text(
            'CREATE TRIGGER "trg_marketplace_product_bindings_immutable" '
            'BEFORE UPDATE OR DELETE ON "marketplace_product_bindings" '
            "FOR EACH ROW EXECUTE FUNCTION kjds_prevent_ledger_mutation()"
        )
    )


def downgrade() -> None:
    op.drop_index(
        "ix_marketplace_product_binding_store",
        table_name="marketplace_product_bindings",
    )
    op.drop_table("marketplace_product_bindings")
