"""Add bounded leases so interrupted read-only workers can be reaped."""

import sqlalchemy as sa
from alembic import op

revision = "20260717_0026"
down_revision = "20260717_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "read_only_pilot_runs",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE read_only_pilot_runs "
            "SET lease_expires_at = started_at "
            "+ INTERVAL '15 minutes' "
            "WHERE lease_expires_at IS NULL"
        )
    )
    op.alter_column("read_only_pilot_runs", "lease_expires_at", nullable=False)
    op.create_index(
        "ix_read_only_pilot_runs_lease",
        "read_only_pilot_runs",
        ["status", "lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_read_only_pilot_runs_lease", table_name="read_only_pilot_runs")
    op.drop_column("read_only_pilot_runs", "lease_expires_at")
