"""Persist request and trace correlation on pilot runs and execution receipts."""

import sqlalchemy as sa
from alembic import op

revision = "20260717_0035"
down_revision = "20260717_0034"
branch_labels = None
depends_on = None


TABLES = ("read_only_pilot_runs", "limited_execution_receipts")


def upgrade() -> None:
    bind = op.get_bind()
    for table in TABLES:
        op.add_column(table, sa.Column("request_id", sa.String(length=128), nullable=True))
        op.add_column(table, sa.Column("trace_id", sa.String(length=128), nullable=True))
        bind.execute(
            sa.text(
                f"UPDATE {table} SET request_id = 'req_legacy_' || id, "
                "trace_id = 'trace_legacy_' || id"
            )
        )
        op.alter_column(table, "request_id", nullable=False)
        op.alter_column(table, "trace_id", nullable=False)
        op.create_index(f"ix_{table}_trace_id", table, ["trace_id"])


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_index(f"ix_{table}_trace_id", table_name=table)
        op.drop_column(table, "trace_id")
        op.drop_column(table, "request_id")
