"""Expand observations for governed multi-source supplier research.

Revision ID: 20260814_0099
Revises: 20260809_0098
Create Date: 2026-08-14
"""

import sqlalchemy as sa
from alembic import op

revision = "20260814_0099"
down_revision = "20260809_0098"
branch_labels = None
depends_on = None

TABLE = "marketplace_observation_snapshots"
CONSTRAINT = "ck_marketplace_observation_marketplace"
EXPANDED = (
    "marketplace IN ('1688','alibaba','ozon','pinduoduo','taobao','tmall',"
    "'tvcmall','xianyu','yiwugo')"
)


def upgrade() -> None:
    op.drop_constraint(CONSTRAINT, TABLE, type_="check")
    op.create_check_constraint(CONSTRAINT, TABLE, EXPANDED)


def downgrade() -> None:
    connection = op.get_bind()
    unsupported = connection.scalar(
        sa.text(
            "SELECT count(*) FROM marketplace_observation_snapshots "
            "WHERE marketplace NOT IN ('1688','ozon')"
        )
    )
    if unsupported:
        raise RuntimeError(
            "Cannot downgrade while multi-source observations exist"
        )
    op.drop_constraint(CONSTRAINT, TABLE, type_="check")
    op.create_check_constraint(
        CONSTRAINT,
        TABLE,
        "marketplace IN ('1688','ozon')",
    )
