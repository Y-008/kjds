"""Add durable delivery state and event contract to the transactional outbox."""

import hashlib
import json

import sqlalchemy as sa
from alembic import op

revision = "20260717_0029"
down_revision = "20260717_0028"
branch_labels = None
depends_on = None


def _hash(payload: object) -> str:
    value = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(value).hexdigest()


def upgrade() -> None:
    op.add_column("outbox_events", sa.Column("event_id", sa.String(), nullable=True))
    op.add_column("outbox_events", sa.Column("payload_hash", sa.String(length=64), nullable=True))
    op.add_column("outbox_events", sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("outbox_events", sa.Column("actor_id", sa.String(), nullable=True))
    op.add_column("outbox_events", sa.Column("source_evidence_id", sa.String(), nullable=True))
    op.add_column("outbox_events", sa.Column("schema_version", sa.String(), nullable=True))
    op.add_column("outbox_events", sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False))
    op.add_column("outbox_events", sa.Column("available_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("outbox_events", sa.Column("claimed_by", sa.String(), nullable=True))
    op.add_column("outbox_events", sa.Column("claimed_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("outbox_events", sa.Column("last_error", sa.Text(), nullable=True))

    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT sequence, payload_json, occurred_at FROM outbox_events")).mappings()
    for row in rows:
        bind.execute(
            sa.text(
                """
                UPDATE outbox_events
                SET event_id = :event_id,
                    payload_hash = :payload_hash,
                    recorded_at = :occurred_at,
                    actor_id = 'system',
                    schema_version = 'v1',
                    available_at = :occurred_at
                WHERE sequence = :sequence
                """
            ),
            {
                "event_id": f"evt_legacy_{row['sequence']}",
                "payload_hash": _hash(row["payload_json"]),
                "occurred_at": row["occurred_at"],
                "sequence": row["sequence"],
            },
        )

    for column in ("event_id", "payload_hash", "recorded_at", "actor_id", "schema_version", "available_at"):
        op.alter_column("outbox_events", column, nullable=False)
    op.create_unique_constraint("uq_outbox_event_id", "outbox_events", ["event_id"])
    op.create_index(
        "ix_outbox_delivery_ready",
        "outbox_events",
        ["published_at", "available_at", "sequence"],
    )
    op.create_index("ix_outbox_claim_expiry", "outbox_events", ["claimed_until"])


def downgrade() -> None:
    op.drop_index("ix_outbox_claim_expiry", table_name="outbox_events")
    op.drop_index("ix_outbox_delivery_ready", table_name="outbox_events")
    op.drop_constraint("uq_outbox_event_id", "outbox_events", type_="unique")
    for column in (
        "last_error",
        "claimed_until",
        "claimed_by",
        "available_at",
        "attempt_count",
        "schema_version",
        "source_evidence_id",
        "actor_id",
        "recorded_at",
        "payload_hash",
        "event_id",
    ):
        op.drop_column("outbox_events", column)
