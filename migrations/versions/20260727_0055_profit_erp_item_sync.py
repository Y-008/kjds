"""Add evidence-bound profitable Item sync outbox."""
import sqlalchemy as sa
from alembic import op

revision = "20260727_0055"
down_revision = "20260727_0054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "profit_erp_item_syncs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_ref", sa.String(), nullable=False),
        sa.Column("store_ref", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("candidate_id", sa.String(), nullable=False),
        sa.Column("product_id", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("evidence_ids_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("remote_name", sa.String(), nullable=True),
        sa.Column("readback_sha256", sa.String(64), nullable=True),
        sa.Column("readback_json", sa.JSON(), nullable=True),
        sa.Column("last_error", sa.String(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('prepared','blocked_connector_not_configured','dispatching','succeeded','failed_write','failed_readback')",
            name="ck_profit_erp_item_sync_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_profit_erp_item_sync_attempts"),
        sa.ForeignKeyConstraint(["run_id"], ["batch_opportunity_runs.id"]),
        sa.ForeignKeyConstraint(["candidate_id"], ["batch_opportunity_candidates.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_ref", "store_ref", "idempotency_key", name="uq_profit_erp_item_sync_idempotency"),
    )
    op.create_index(
        "ix_profit_erp_item_sync_scope_status",
        "profit_erp_item_syncs",
        ["tenant_ref", "store_ref", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_profit_erp_item_sync_scope_status", table_name="profit_erp_item_syncs")
    op.drop_table("profit_erp_item_syncs")
