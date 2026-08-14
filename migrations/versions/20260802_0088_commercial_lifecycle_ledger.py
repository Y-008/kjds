"""Add minimal commercial lifecycle ledger.

Revision ID: 20260802_0088
Revises: 20260802_0087
Create Date: 2026-08-02
"""

import sqlalchemy as sa
from alembic import op

revision = "20260802_0088"
down_revision = "20260802_0087"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "commercial_lifecycle_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("lifecycle_kind", sa.String(length=32), nullable=False),
        sa.Column("event_kind", sa.String(length=80), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("customer_ref", sa.String(length=160), nullable=False),
        sa.Column("deployment_ref", sa.String(length=160), nullable=False),
        sa.Column("tenant_ref", sa.String(length=160), nullable=False),
        sa.Column("entity_ref", sa.String(length=160), nullable=False),
        sa.Column("store_ref", sa.String(length=160), nullable=False),
        sa.Column("record_ref", sa.String(length=240), nullable=False),
        sa.Column("parent_ref", sa.String(length=240), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("amount", sa.Numeric(38, 12), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("decision_sha256", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=180), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "customer_ref IS NOT NULL AND length(customer_ref) > 0 "
            "AND deployment_ref IS NOT NULL AND length(deployment_ref) > 0 "
            "AND tenant_ref IS NOT NULL AND length(tenant_ref) > 0 "
            "AND entity_ref IS NOT NULL AND length(entity_ref) > 0 "
            "AND store_ref IS NOT NULL AND length(store_ref) > 0",
            name="ck_commercial_lifecycle_events_scope_required",
        ),
        sa.CheckConstraint(
            "length(request_sha256) = 64 AND length(decision_sha256) = 64",
            name="ck_commercial_lifecycle_events_hashes",
        ),
        sa.CheckConstraint(
            "currency IS NULL OR (length(currency) = 3)",
            name="ck_commercial_lifecycle_events_currency",
        ),
        sa.CheckConstraint(
            "amount IS NULL OR amount >= 0",
            name="ck_commercial_lifecycle_events_amount",
        ),
    )
    op.create_index(
        "uq_commercial_lifecycle_scope_kind_idempotency",
        "commercial_lifecycle_events",
        [
            "customer_ref",
            "deployment_ref",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "lifecycle_kind",
            "idempotency_key",
        ],
        unique=True,
    )
    op.create_index(
        "ix_commercial_lifecycle_scope_recorded",
        "commercial_lifecycle_events",
        [
            "customer_ref",
            "deployment_ref",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "recorded_at",
            "id",
        ],
    )

    op.create_table(
        "commercial_lifecycle_evidence",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "event_id",
            sa.String(),
            sa.ForeignKey("commercial_lifecycle_events.id"),
            nullable=False,
        ),
        sa.Column("customer_ref", sa.String(length=160), nullable=False),
        sa.Column("deployment_ref", sa.String(length=160), nullable=False),
        sa.Column("tenant_ref", sa.String(length=160), nullable=False),
        sa.Column("entity_ref", sa.String(length=160), nullable=False),
        sa.Column("store_ref", sa.String(length=160), nullable=False),
        sa.Column("evidence_id", sa.String(length=240), nullable=False),
        sa.Column("evidence_sha256", sa.String(length=64), nullable=False),
        sa.Column("evidence_kind", sa.String(length=120), nullable=False),
        sa.Column("authority", sa.String(length=300), nullable=False),
        sa.Column("source_kind", sa.String(length=120), nullable=False),
        sa.Column("purposes_json", sa.JSON(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(evidence_id) > 0 AND length(evidence_sha256) = 64 "
            "AND length(evidence_kind) > 0 AND length(authority) > 0 "
            "AND length(source_kind) > 0",
            name="ck_commercial_lifecycle_evidence_required",
        ),
    )
    op.create_index(
        "uq_commercial_lifecycle_evidence_event",
        "commercial_lifecycle_evidence",
        ["event_id", "evidence_id"],
        unique=True,
    )
    op.create_index(
        "ix_commercial_lifecycle_evidence_scope",
        "commercial_lifecycle_evidence",
        ["tenant_ref", "entity_ref", "store_ref", "recorded_at", "event_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_commercial_lifecycle_evidence_scope", table_name="commercial_lifecycle_evidence")
    op.drop_index("uq_commercial_lifecycle_evidence_event", table_name="commercial_lifecycle_evidence")
    op.drop_table("commercial_lifecycle_evidence")

    op.drop_index("ix_commercial_lifecycle_scope_recorded", table_name="commercial_lifecycle_events")
    op.drop_index("uq_commercial_lifecycle_scope_kind_idempotency", table_name="commercial_lifecycle_events")
    op.drop_table("commercial_lifecycle_events")
