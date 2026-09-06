"""Add explicit observation and settlement times to commercial finance facts.

Revision ID: 20260907_0120
Revises: 20260906_0119

``occurred_at`` remains the business event time.  ``recorded_at`` is retained
for compatibility with the original 0113 schema, while ``observed_at`` is the
canonical ingestion/knowledge time used by ``as_of`` audit queries.
``settled_at`` is nullable because a cost or revenue event can be observed
before a platform or bank confirms final settlement.  Existing rows are
backfilled from ``recorded_at`` and all new rows must carry an observation time.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260907_0120"
down_revision = "20260906_0119"
branch_labels = None
depends_on = None

TABLE = "commercial_finance_events"
OBSERVED_INDEX = "ix_commercial_finance_scope_observed"
SETTLED_INDEX = "ix_commercial_finance_scope_settled"
SETTLED_CHECK = "ck_commercial_finance_settled_after_occurred"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        TABLE,
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
    )
    # ``recorded_at`` is the only observation timestamp in 0113.  The update
    # is deterministic and leaves the old column intact for compatibility.
    op.execute(
        f'UPDATE "{TABLE}" SET "observed_at" = "recorded_at" '
        'WHERE "observed_at" IS NULL'
    )
    op.alter_column(
        TABLE,
        "observed_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )
    op.create_check_constraint(
        SETTLED_CHECK,
        TABLE,
        "settled_at IS NULL OR settled_at >= occurred_at",
    )
    op.create_index(
        OBSERVED_INDEX,
        TABLE,
        ["tenant_id", "customer_id", "observed_at", "event_id"],
    )
    op.create_index(
        SETTLED_INDEX,
        TABLE,
        ["tenant_id", "customer_id", "settled_at", "event_id"],
    )


def downgrade() -> None:
    op.drop_index(SETTLED_INDEX, table_name=TABLE)
    op.drop_index(OBSERVED_INDEX, table_name=TABLE)
    op.drop_constraint(SETTLED_CHECK, TABLE, type_="check")
    op.drop_column(TABLE, "settled_at")
    op.drop_column(TABLE, "observed_at")

