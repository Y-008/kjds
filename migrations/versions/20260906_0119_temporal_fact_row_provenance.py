"""Promote SKU and freshness to first-class temporal-fact columns.

The 0104 temporal table already keeps source, four timestamps, quality and
lineage.  This additive revision makes the two row-level dimensions required
by the data-fabric contract explicit while leaving legacy rows readable.  A
NULL value is permitted only for rows written before this revision; the
application contract derives freshness from ``quality_state`` when reading
such a row and every new adapter write supplies it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260906_0119"
down_revision = "20260906_0118"
branch_labels = None
depends_on = None

TABLE = "temporal_fact_revisions"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("sku", sa.String(length=240), nullable=True))
    op.add_column(TABLE, sa.Column("freshness", sa.String(length=20), nullable=True))
    op.create_index(
        "ix_temporal_fact_sku",
        TABLE,
        ["tenant_id", "entity_id", "sku", "observed_time"],
    )


def downgrade() -> None:
    op.drop_index("ix_temporal_fact_sku", table_name=TABLE)
    op.drop_column(TABLE, "freshness")
    op.drop_column(TABLE, "sku")
