"""Add operating intelligence tasks, scans, and media execution ledgers."""

import sqlalchemy as sa
from alembic import op

revision = "20260726_0051"
down_revision = "20260726_0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operating_tasks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("metric_id", sa.String(), nullable=False),
        sa.Column("scope_json", sa.JSON(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("owner", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("first_detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_ids_json", sa.JSON(), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('open','acknowledged','in_progress','resolved','dismissed')",
            name="ck_operating_task_status",
        ),
        sa.CheckConstraint(
            "severity IN ('critical','high','medium','low')",
            name="ck_operating_task_severity",
        ),
    )
    op.create_index(
        "ix_operating_tasks_queue",
        "operating_tasks",
        ["status", "severity", "updated_at"],
    )
    op.create_index(
        "ix_operating_tasks_metric_cooldown",
        "operating_tasks",
        ["metric_id", "cooldown_until"],
    )
    op.create_table(
        "operating_task_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "task_id",
            sa.String(),
            sa.ForeignKey("operating_tasks.id"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("from_status", sa.String(), nullable=False),
        sa.Column("to_status", sa.String(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence_ids_json", sa.JSON(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "task_id",
            "sequence",
            name="uq_operating_task_event_sequence",
        ),
    )
    op.create_index(
        "ix_operating_task_events_timeline",
        "operating_task_events",
        ["task_id", "sequence"],
    )
    op.create_table(
        "anomaly_scan_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("registry_version", sa.String(), nullable=False),
        sa.Column("store_ref", sa.String(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("results_json", sa.JSON(), nullable=False),
        sa.Column("snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_anomaly_scan_runs_store_asof",
        "anomaly_scan_runs",
        ["store_ref", "as_of"],
    )
    op.create_table(
        "media_executions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "asset_id",
            sa.String(),
            sa.ForeignKey("content_assets.id"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("media_kind", sa.String(), nullable=False),
        sa.Column("template_id", sa.String(), nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("queued_by", sa.String(), nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("cost_amount", sa.Numeric(38, 12), nullable=False),
        sa.Column("cost_currency", sa.String(3), nullable=False),
        sa.Column("outputs_json", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "asset_id",
            "idempotency_key",
            name="uq_media_asset_idempotency",
        ),
    )
    op.create_index(
        "ix_media_executions_lease",
        "media_executions",
        ["media_kind", "status", "lease_expires_at", "queued_at"],
    )
    op.create_table(
        "media_execution_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "execution_id",
            sa.String(),
            sa.ForeignKey("media_executions.id"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("from_status", sa.String(), nullable=True),
        sa.Column("to_status", sa.String(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "execution_id",
            "sequence",
            name="uq_media_execution_event_sequence",
        ),
    )
    op.create_index(
        "ix_media_execution_events_timeline",
        "media_execution_events",
        ["execution_id", "sequence"],
    )
    op.create_table(
        "media_delivery_manifests",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "asset_id",
            sa.String(),
            sa.ForeignKey("content_assets.id"),
            nullable=False,
        ),
        sa.Column(
            "execution_id",
            sa.String(),
            sa.ForeignKey("media_executions.id"),
            nullable=True,
        ),
        sa.Column("asset_state_sha256", sa.String(64), nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "asset_id",
            "asset_state_sha256",
            name="uq_media_manifest_state",
        ),
    )
    for table in (
        "operating_task_events",
        "anomaly_scan_runs",
        "media_execution_events",
        "media_delivery_manifests",
    ):
        op.execute(sa.text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
        op.execute(
            sa.text(
                f'CREATE TRIGGER "trg_{table}_immutable" '
                f'BEFORE UPDATE OR DELETE ON "{table}" '
                "FOR EACH ROW EXECUTE FUNCTION kjds_prevent_ledger_mutation()"
            )
        )


def downgrade() -> None:
    op.drop_table("media_delivery_manifests")
    op.drop_index(
        "ix_media_execution_events_timeline",
        table_name="media_execution_events",
    )
    op.drop_table("media_execution_events")
    op.drop_index(
        "ix_media_executions_lease",
        table_name="media_executions",
    )
    op.drop_table("media_executions")
    op.drop_index(
        "ix_anomaly_scan_runs_store_asof",
        table_name="anomaly_scan_runs",
    )
    op.drop_table("anomaly_scan_runs")
    op.drop_index(
        "ix_operating_task_events_timeline",
        table_name="operating_task_events",
    )
    op.drop_table("operating_task_events")
    op.drop_index(
        "ix_operating_tasks_metric_cooldown",
        table_name="operating_tasks",
    )
    op.drop_index("ix_operating_tasks_queue", table_name="operating_tasks")
    op.drop_table("operating_tasks")
