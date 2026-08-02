"""Add immutable Seller ERP bridge authority source references.

Revision ID: 20260729_0074
Revises: 20260729_0073
Create Date: 2026-07-29
"""

import sqlalchemy as sa
from alembic import op

revision = "20260729_0074"
down_revision = "20260729_0073"
branch_labels = None
depends_on = None

SOURCES = (
    "seller_erp_bridge_source",
    "seller_erp_bridge_review",
    "seller_erp_bridge_binding",
    "seller_erp_bridge_revocation",
)


def upgrade() -> None:
    for source in SOURCES:
        op.create_index(
            f"uq_{source}_ref",
            "evidence_records",
            ["source", "source_ref"],
            unique=True,
            postgresql_where=sa.text(f"source = '{source}'"),
            sqlite_where=sa.text(f"source = '{source}'"),
        )


def downgrade() -> None:
    for source in reversed(SOURCES):
        op.drop_index(
            f"uq_{source}_ref",
            table_name="evidence_records",
        )
