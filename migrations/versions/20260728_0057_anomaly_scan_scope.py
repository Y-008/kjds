"""Add explicit tenant/entity scope to scans and queue escalations."""

import sqlalchemy as sa
from alembic import op

revision = "20260728_0057"
down_revision = "20260727_0056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "anomaly_scan_runs",
        sa.Column("tenant_ref", sa.String(), nullable=True),
    )
    op.add_column(
        "anomaly_scan_runs",
        sa.Column("entity_ref", sa.String(), nullable=True),
    )
    op.add_column(
        "anomaly_scan_runs",
        sa.Column(
            "scope_authority_sha256",
            sa.String(length=64),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_anomaly_scan_scope_complete",
        "anomaly_scan_runs",
        "("
        "tenant_ref IS NULL AND entity_ref IS NULL "
        "AND scope_authority_sha256 IS NULL"
        ") OR ("
        "tenant_ref IS NOT NULL AND length(tenant_ref) > 0 "
        "AND entity_ref IS NOT NULL AND length(entity_ref) > 0 "
        "AND scope_authority_sha256 IS NOT NULL "
        "AND length(scope_authority_sha256) = 64"
        ")",
    )
    op.create_index(
        "ix_anomaly_scan_scope",
        "anomaly_scan_runs",
        ["tenant_ref", "entity_ref", "store_ref", "as_of"],
    )
    op.add_column(
        "operations_escalation_events",
        sa.Column("tenant_ref", sa.String(), nullable=True),
    )
    op.add_column(
        "operations_escalation_events",
        sa.Column("entity_ref", sa.String(), nullable=True),
    )
    op.add_column(
        "operations_escalation_events",
        sa.Column("store_ref", sa.String(), nullable=True),
    )
    op.add_column(
        "operations_escalation_events",
        sa.Column(
            "scope_authority_sha256",
            sa.String(length=64),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_operations_escalation_scope_complete",
        "operations_escalation_events",
        "("
        "tenant_ref IS NULL AND entity_ref IS NULL AND store_ref IS NULL "
        "AND scope_authority_sha256 IS NULL"
        ") OR ("
        "tenant_ref IS NOT NULL AND length(tenant_ref) > 0 "
        "AND entity_ref IS NOT NULL AND length(entity_ref) > 0 "
        "AND store_ref IS NOT NULL AND length(store_ref) > 0 "
        "AND scope_authority_sha256 IS NOT NULL "
        "AND length(scope_authority_sha256) = 64"
        ")",
    )
    op.create_index(
        "ix_operations_escalation_scope",
        "operations_escalation_events",
        ["tenant_ref", "entity_ref", "store_ref", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_operations_escalation_scope",
        table_name="operations_escalation_events",
    )
    op.drop_constraint(
        "ck_operations_escalation_scope_complete",
        "operations_escalation_events",
        type_="check",
    )
    op.drop_column(
        "operations_escalation_events",
        "scope_authority_sha256",
    )
    op.drop_column("operations_escalation_events", "store_ref")
    op.drop_column("operations_escalation_events", "entity_ref")
    op.drop_column("operations_escalation_events", "tenant_ref")
    op.drop_index(
        "ix_anomaly_scan_scope",
        table_name="anomaly_scan_runs",
    )
    op.drop_constraint(
        "ck_anomaly_scan_scope_complete",
        "anomaly_scan_runs",
        type_="check",
    )
    op.drop_column("anomaly_scan_runs", "scope_authority_sha256")
    op.drop_column("anomaly_scan_runs", "entity_ref")
    op.drop_column("anomaly_scan_runs", "tenant_ref")
