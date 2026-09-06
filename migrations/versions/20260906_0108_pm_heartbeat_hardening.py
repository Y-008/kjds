"""Harden project-manager heartbeat identity, liveness and recovery fields.

Revision ID: 20260906_0108
Revises: 20260906_0107
"""

from __future__ import annotations

import hashlib
import json

import sqlalchemy as sa
from alembic import op

revision = "20260906_0108"
down_revision = "20260906_0107"
branch_labels = None
depends_on = None

TABLE = "project_manager_heartbeats"


def _request_digest(row: sa.Row) -> str:
    payload = row.payload_json
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = {"legacy_payload": payload}
    canonical = {
        "project_id": row.project_id,
        "tenant_id": row.tenant_id,
        "entity_id": row.entity_id,
        "store_ref": row.store_ref,
        "head": row.head,
        "graph_snapshot_sha256": row.graph_snapshot_sha256,
        "status": row.status,
        "payload": payload or {},
        "observed_at": str(row.observed_at),
        "liveness_deadline": None,
        "heartbeat_at": str(row.observed_at),
        "progress_cursor": None,
        "expected_next_event": None,
        "stuck_detector_version": None,
        "compensation_action": None,
        "recovery_ref": None,
    }
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def upgrade() -> None:
    # Add nullable first so an already populated 0105 table can be upgraded
    # without inventing a single shared key or digest for all historical rows.
    op.add_column(TABLE, sa.Column("idempotency_key", sa.String(length=300), nullable=True))
    op.add_column(TABLE, sa.Column("request_sha256", sa.String(length=64), nullable=True))
    op.add_column(TABLE, sa.Column("liveness_deadline", sa.DateTime(timezone=True), nullable=True))
    op.add_column(TABLE, sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(TABLE, sa.Column("progress_cursor", sa.String(length=500), nullable=True))
    op.add_column(TABLE, sa.Column("expected_next_event", sa.String(length=300), nullable=True))
    op.add_column(TABLE, sa.Column("stuck_detector_version", sa.String(length=100), nullable=True))
    op.add_column(TABLE, sa.Column("compensation_action", sa.String(length=300), nullable=True))
    op.add_column(TABLE, sa.Column("recovery_ref", sa.String(length=300), nullable=True))

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            f"SELECT heartbeat_id, project_id, tenant_id, entity_id, store_ref, "
            f"head, graph_snapshot_sha256, status, payload_json, observed_at "
            f"FROM {TABLE} WHERE idempotency_key IS NULL OR request_sha256 IS NULL"
        )
    ).mappings()
    for row in rows:
        # Legacy keys are scoped to the immutable row id.  They cannot collide
        # with an explicitly supplied key unless a caller deliberately chooses
        # the reserved ``legacy:`` prefix and exact row id.
        bind.execute(
            sa.text(
                f"UPDATE {TABLE} SET idempotency_key = :key, request_sha256 = :digest, "
                "heartbeat_at = COALESCE(heartbeat_at, observed_at) "
                "WHERE heartbeat_id = :heartbeat_id"
            ),
            {
                "key": f"legacy:{row['heartbeat_id']}",
                "digest": _request_digest(row),
                "heartbeat_id": row["heartbeat_id"],
            },
        )
    op.alter_column(TABLE, "idempotency_key", nullable=False)
    op.alter_column(TABLE, "request_sha256", nullable=False)
    op.alter_column(TABLE, "heartbeat_at", nullable=False)
    op.create_unique_constraint(
        "uq_pm_heartbeat_scope_revision",
        TABLE,
        ["tenant_id", "entity_id", "project_id", "store_ref", "revision"],
    )
    op.create_unique_constraint(
        "uq_pm_heartbeat_scope_idempotency",
        TABLE,
        ["tenant_id", "entity_id", "project_id", "store_ref", "idempotency_key"],
    )
    op.create_check_constraint(
        "ck_pm_heartbeat_revision_positive",
        TABLE,
        "revision >= 1",
    )


def downgrade() -> None:
    op.drop_constraint("ck_pm_heartbeat_revision_positive", TABLE, type_="check")
    op.drop_constraint("uq_pm_heartbeat_scope_idempotency", TABLE, type_="unique")
    op.drop_constraint("uq_pm_heartbeat_scope_revision", TABLE, type_="unique")
    op.drop_column(TABLE, "recovery_ref")
    op.drop_column(TABLE, "compensation_action")
    op.drop_column(TABLE, "stuck_detector_version")
    op.drop_column(TABLE, "expected_next_event")
    op.drop_column(TABLE, "progress_cursor")
    op.drop_column(TABLE, "heartbeat_at")
    op.drop_column(TABLE, "liveness_deadline")
    op.drop_column(TABLE, "request_sha256")
    op.drop_column(TABLE, "idempotency_key")
