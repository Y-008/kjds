"""Add native exact-scope append-only warehouse execution authority.

Revision ID: 20260730_0080
Revises: 20260730_0079
Create Date: 2026-07-30
"""

import sqlalchemy as sa
from alembic import op

revision = "20260730_0080"
down_revision = "20260730_0079"
branch_labels = None
depends_on = None

SCOPE_REQUIRED = (
    "tenant_ref IS NOT NULL AND length(tenant_ref) > 0 "
    "AND entity_ref IS NOT NULL AND length(entity_ref) > 0 "
    "AND store_ref IS NOT NULL AND length(store_ref) > 0 "
    "AND warehouse_ref IS NOT NULL AND length(warehouse_ref) > 0 "
    "AND scope_grant_authority_sha256 IS NOT NULL "
    "AND length(scope_grant_authority_sha256) = 64 "
    "AND source_evidence_sha256 IS NOT NULL "
    "AND length(source_evidence_sha256) = 64 "
    "AND source_payload_sha256 IS NOT NULL "
    "AND length(source_payload_sha256) = 64 "
    "AND payload_sha256 IS NOT NULL AND length(payload_sha256) = 64 "
    "AND scope_as_of IS NOT NULL"
)
EXECUTION_BINDING = (
    "("
    "event_type NOT IN ("
    "'inventory_adjustment_readback',"
    "'outbound_confirmed_readback',"
    "'label_purchased_readback',"
    "'carrier_handoff_readback'"
    ") "
    "AND approval_id IS NULL AND command_id IS NULL AND receipt_id IS NULL "
    "AND kill_switch_evidence_id IS NULL "
    "AND compensation_evidence_id IS NULL"
    ") OR ("
    "event_type IN ("
    "'inventory_adjustment_readback',"
    "'outbound_confirmed_readback',"
    "'label_purchased_readback',"
    "'carrier_handoff_readback'"
    ") "
    "AND approval_id IS NOT NULL AND length(approval_id) > 0 "
    "AND command_id IS NOT NULL AND length(command_id) > 0 "
    "AND receipt_id IS NOT NULL AND length(receipt_id) > 0 "
    "AND kill_switch_evidence_id IS NOT NULL "
    "AND compensation_evidence_id IS NOT NULL"
    ")"
)


def upgrade() -> None:
    op.create_table(
        "warehouse_execution_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("source_event_ref", sa.String(length=240), nullable=False),
        sa.Column("aggregate_ref", sa.String(length=240), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("order_external_id", sa.String(length=240), nullable=False),
        sa.Column(
            "product_id",
            sa.String(),
            sa.ForeignKey("products.id"),
            nullable=False,
        ),
        sa.Column("sku", sa.String(length=240), nullable=False),
        sa.Column("location_ref", sa.String(length=240), nullable=True),
        sa.Column("bin_ref", sa.String(length=240), nullable=True),
        sa.Column("lot_ref", sa.String(length=240), nullable=True),
        sa.Column("wave_ref", sa.String(length=240), nullable=True),
        sa.Column("parcel_ref", sa.String(length=240), nullable=True),
        sa.Column("label_ref", sa.String(length=240), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=True),
        sa.Column("weight_kg", sa.String(length=48), nullable=True),
        sa.Column("weight_source", sa.String(length=80), nullable=True),
        sa.Column("carrier_ref", sa.String(length=240), nullable=True),
        sa.Column("service_ref", sa.String(length=240), nullable=True),
        sa.Column(
            "evidence_id",
            sa.String(),
            sa.ForeignKey("evidence_records.id"),
            nullable=False,
        ),
        sa.Column(
            "source_payload_sha256",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "approval_id",
            sa.String(),
            sa.ForeignKey("approvals.id"),
            nullable=True,
        ),
        sa.Column(
            "command_id",
            sa.String(),
            sa.ForeignKey("limited_execution_commands.id"),
            nullable=True,
        ),
        sa.Column(
            "receipt_id",
            sa.String(),
            sa.ForeignKey("limited_execution_receipts.id"),
            nullable=True,
        ),
        sa.Column(
            "kill_switch_evidence_id",
            sa.String(),
            sa.ForeignKey("evidence_records.id"),
            nullable=True,
        ),
        sa.Column(
            "compensation_evidence_id",
            sa.String(),
            sa.ForeignKey("evidence_records.id"),
            nullable=True,
        ),
        sa.Column(
            "effective_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=240), nullable=False),
        sa.Column("tenant_ref", sa.String(length=160), nullable=False),
        sa.Column("entity_ref", sa.String(length=160), nullable=False),
        sa.Column("store_ref", sa.String(length=160), nullable=False),
        sa.Column("warehouse_ref", sa.String(length=160), nullable=False),
        sa.Column(
            "scope_grant_authority_sha256",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "source_evidence_sha256",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "scope_as_of",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "warehouse_ref",
            "source_event_ref",
            name="uq_warehouse_execution_source_event",
        ),
        sa.UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "warehouse_ref",
            "aggregate_ref",
            "sequence",
            name="uq_warehouse_execution_aggregate_sequence",
        ),
        sa.UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "warehouse_ref",
            "command_id",
            name="uq_warehouse_execution_command",
        ),
        sa.UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "warehouse_ref",
            "receipt_id",
            name="uq_warehouse_execution_receipt",
        ),
        sa.CheckConstraint(
            SCOPE_REQUIRED,
            name="ck_warehouse_execution_scope_required",
        ),
        sa.CheckConstraint(
            "sequence > 0",
            name="ck_warehouse_execution_sequence",
        ),
        sa.CheckConstraint(
            "quantity IS NULL OR quantity > 0",
            name="ck_warehouse_execution_quantity",
        ),
        sa.CheckConstraint(
            "weight_kg IS NULL OR length(weight_kg) > 0",
            name="ck_warehouse_execution_weight",
        ),
        sa.CheckConstraint(
            EXECUTION_BINDING,
            name="ck_warehouse_execution_governance_binding",
        ),
    )
    op.create_index(
        "ix_warehouse_execution_scope_order",
        "warehouse_execution_events",
        [
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "warehouse_ref",
            "order_external_id",
            "effective_at",
            "id",
        ],
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_warehouse_execution_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'warehouse_execution_events is append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_warehouse_execution_no_update
        BEFORE UPDATE ON warehouse_execution_events
        FOR EACH ROW EXECUTE FUNCTION reject_warehouse_execution_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_warehouse_execution_no_delete
        BEFORE DELETE ON warehouse_execution_events
        FOR EACH ROW EXECUTE FUNCTION reject_warehouse_execution_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_warehouse_execution_no_delete "
        "ON warehouse_execution_events"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_warehouse_execution_no_update "
        "ON warehouse_execution_events"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS reject_warehouse_execution_mutation()"
    )
    op.drop_index(
        "ix_warehouse_execution_scope_order",
        table_name="warehouse_execution_events",
    )
    op.drop_table("warehouse_execution_events")
