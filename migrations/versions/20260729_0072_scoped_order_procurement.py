"""Add exact-scope current-order lookup index for procurement review.

Revision ID: 20260729_0072
Revises: 20260729_0071
Create Date: 2026-07-29
"""

import sqlalchemy as sa
from alembic import op

revision = "20260729_0072"
down_revision = "20260729_0071"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_fact_scope_order_product_effective"


def upgrade() -> None:
    op.create_index(
        INDEX_NAME,
        "fact_records",
        [
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "product_id",
            "effective_at",
            "recorded_at",
        ],
        unique=False,
        postgresql_where=sa.text(
            "tenant_ref IS NOT NULL AND fact_type = 'ozon_order'"
        ),
        sqlite_where=sa.text(
            "tenant_ref IS NOT NULL AND fact_type = 'ozon_order'"
        ),
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="fact_records")
