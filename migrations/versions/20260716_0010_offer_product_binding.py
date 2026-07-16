"""Bind supplier offer observations to candidate products."""

import sqlalchemy as sa
from alembic import op

revision = "20260716_0010"
down_revision = "20260716_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("source_offers", sa.Column("product_id", sa.String(), nullable=True))
    op.add_column("source_offers", sa.Column("supplier_ref", sa.String(), nullable=True))
    op.create_foreign_key(
        "fk_source_offers_product_id_products",
        "source_offers",
        "products",
        ["product_id"],
        ["id"],
    )
    op.create_index("idx_source_offers_product_captured", "source_offers", ["product_id", "captured_at"])


def downgrade() -> None:
    op.drop_index("idx_source_offers_product_captured", table_name="source_offers")
    op.drop_constraint("fk_source_offers_product_id_products", "source_offers", type_="foreignkey")
    op.drop_column("source_offers", "supplier_ref")
    op.drop_column("source_offers", "product_id")
