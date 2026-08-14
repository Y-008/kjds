"""Add market recon bundle and profit command records.

Revision ID: 20260802_0085
Revises: 20260801_0084
Create Date: 2026-08-02
"""

import sqlalchemy as sa
from alembic import op

revision = "20260802_0085"
down_revision = "20260801_0084"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "market_recon_bundle_runs",
        sa.Column("id", sa.String(length=180), primary_key=True),
        sa.Column("tenant_ref", sa.String(length=160), nullable=False),
        sa.Column("entity_ref", sa.String(length=160), nullable=False),
        sa.Column("store_ref", sa.String(length=160), nullable=False),
        sa.Column("scope_grant_authority_sha256", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=180), nullable=False),
        sa.Column("contract_id", sa.String(length=100), nullable=False),
        sa.Column("bundle_sha256", sa.String(length=64), nullable=False),
        sa.Column("archive_evidence_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("source_total", sa.Integer(), nullable=False),
        sa.Column("accepted_count", sa.Integer(), nullable=False),
        sa.Column("quarantined_count", sa.Integer(), nullable=False),
        sa.Column("stage_counts_json", sa.JSON(), nullable=False),
        sa.Column("quality_json", sa.JSON(), nullable=False),
        sa.Column("artifacts_json", sa.JSON(), nullable=False),
        sa.Column("imported_by", sa.String(length=240), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(scope_grant_authority_sha256) = 64 AND length(bundle_sha256) = 64",
            name="ck_market_recon_bundle_hashes",
        ),
        sa.CheckConstraint(
            "status IN ('completed','partial','quarantined')",
            name="ck_market_recon_bundle_status",
        ),
        sa.CheckConstraint(
            "source_total >= 0 AND accepted_count >= 0 AND quarantined_count >= 0 "
            "AND accepted_count + quarantined_count = source_total",
            name="ck_market_recon_bundle_conservation",
        ),
        sa.ForeignKeyConstraint(["archive_evidence_id"], ["evidence_records.id"]),
        sa.UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "idempotency_key",
            name="uq_market_recon_bundle_scope_idempotency",
        ),
    )
    op.create_index(
        "ix_market_recon_bundle_scope_created",
        "market_recon_bundle_runs",
        ["tenant_ref", "entity_ref", "store_ref", "created_at"],
    )
    op.create_table(
        "market_recon_bundle_items",
        sa.Column("id", sa.String(length=180), primary_key=True),
        sa.Column("bundle_id", sa.String(length=180), nullable=False),
        sa.Column("tenant_ref", sa.String(length=160), nullable=False),
        sa.Column("entity_ref", sa.String(length=160), nullable=False),
        sa.Column("store_ref", sa.String(length=160), nullable=False),
        sa.Column("artifact_path", sa.Text(), nullable=False),
        sa.Column("artifact_kind", sa.String(length=80), nullable=False),
        sa.Column("record_index", sa.Integer(), nullable=False),
        sa.Column("record_key", sa.String(length=500), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("artifact_evidence_id", sa.String(), nullable=False),
        sa.Column("disposition", sa.String(length=30), nullable=False),
        sa.Column("highest_stage", sa.String(length=50), nullable=False),
        sa.Column("reason_codes_json", sa.JSON(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(source_sha256) = 64", name="ck_market_recon_bundle_item_hash"),
        sa.CheckConstraint(
            "disposition IN ('accepted','quarantined')",
            name="ck_market_recon_bundle_item_disposition",
        ),
        sa.CheckConstraint(
            "highest_stage IN ('raw_evidence','normalized_observation','reviewed_observation',"
            "'formal_fact','decision_snapshot')",
            name="ck_market_recon_bundle_item_stage",
        ),
        sa.ForeignKeyConstraint(["bundle_id"], ["market_recon_bundle_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["artifact_evidence_id"], ["evidence_records.id"]),
        sa.UniqueConstraint(
            "bundle_id",
            "artifact_path",
            "record_index",
            name="uq_market_recon_bundle_item_position",
        ),
    )
    op.create_index(
        "ix_market_recon_bundle_item_scope_kind",
        "market_recon_bundle_items",
        ["tenant_ref", "entity_ref", "store_ref", "artifact_kind", "disposition"],
    )
    op.execute(
        'CREATE TRIGGER "trg_market_recon_bundle_items_immutable" '
        'BEFORE UPDATE OR DELETE ON "market_recon_bundle_items" '
        "FOR EACH ROW EXECUTE FUNCTION kjds_prevent_ledger_mutation()"
    )
    op.create_table(
        "profit_decision_snapshots",
        sa.Column("id", sa.String(length=180), primary_key=True),
        sa.Column("tenant_ref", sa.String(length=160), nullable=False),
        sa.Column("entity_ref", sa.String(length=160), nullable=False),
        sa.Column("store_ref", sa.String(length=160), nullable=False),
        sa.Column("scope_grant_authority_sha256", sa.String(length=64), nullable=False),
        sa.Column("bundle_id", sa.String(length=180), nullable=True),
        sa.Column("algorithm_version", sa.String(length=100), nullable=False),
        sa.Column("display_currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("input_snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("output_snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("evidence_ids_json", sa.JSON(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=240), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(scope_grant_authority_sha256) = 64 "
            "AND length(input_snapshot_sha256) = 64 "
            "AND length(output_snapshot_sha256) = 64",
            name="ck_profit_decision_snapshot_hashes",
        ),
        sa.CheckConstraint(
            "status IN ('ready_with_constraints','no_data','blocked')",
            name="ck_profit_decision_snapshot_status",
        ),
        sa.ForeignKeyConstraint(["bundle_id"], ["market_recon_bundle_runs.id"]),
        sa.UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "input_snapshot_sha256",
            name="uq_profit_decision_scope_input",
        ),
    )
    op.create_index(
        "ix_profit_decision_scope_created",
        "profit_decision_snapshots",
        ["tenant_ref", "entity_ref", "store_ref", "created_at"],
    )
    op.create_table(
        "profit_pilot_proposals",
        sa.Column("id", sa.String(length=180), primary_key=True),
        sa.Column("snapshot_id", sa.String(length=180), nullable=False),
        sa.Column("tenant_ref", sa.String(length=160), nullable=False),
        sa.Column("entity_ref", sa.String(length=160), nullable=False),
        sa.Column("store_ref", sa.String(length=160), nullable=False),
        sa.Column("candidate_id", sa.String(length=240), nullable=False),
        sa.Column("idempotency_key", sa.String(length=180), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("request_evidence_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("reason_codes_json", sa.JSON(), nullable=False),
        sa.Column("budget_amount", sa.Numeric(24, 8), nullable=True),
        sa.Column("budget_currency", sa.String(length=3), nullable=True),
        sa.Column("stop_loss_amount", sa.Numeric(24, 8), nullable=True),
        sa.Column("proposal_json", sa.JSON(), nullable=False),
        sa.Column("external_write_allowed", sa.Boolean(), nullable=False),
        sa.Column("approval_created", sa.Boolean(), nullable=False),
        sa.Column("permit_created", sa.Boolean(), nullable=False),
        sa.Column("pilot_started", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(length=240), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('proposal_only','blocked')",
            name="ck_profit_pilot_proposal_status",
        ),
        sa.CheckConstraint("length(request_sha256) = 64", name="ck_profit_pilot_proposal_hash"),
        sa.CheckConstraint(
            "external_write_allowed IS FALSE AND approval_created IS FALSE "
            "AND permit_created IS FALSE AND pilot_started IS FALSE",
            name="ck_profit_pilot_proposal_authority",
        ),
        sa.ForeignKeyConstraint(["snapshot_id"], ["profit_decision_snapshots.id"]),
        sa.ForeignKeyConstraint(["request_evidence_id"], ["evidence_records.id"]),
        sa.UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "idempotency_key",
            name="uq_profit_pilot_scope_idempotency",
        ),
    )
    op.create_index(
        "ix_profit_pilot_scope_created",
        "profit_pilot_proposals",
        ["tenant_ref", "entity_ref", "store_ref", "created_at"],
    )
    for table in ("profit_decision_snapshots", "profit_pilot_proposals"):
        op.execute(
            f'CREATE TRIGGER "trg_{table}_immutable" BEFORE UPDATE OR DELETE ON "{table}" '
            "FOR EACH ROW EXECUTE FUNCTION kjds_prevent_ledger_mutation()"
        )


def downgrade() -> None:
    for table in ("profit_pilot_proposals", "profit_decision_snapshots"):
        op.execute(f'DROP TRIGGER IF EXISTS "trg_{table}_immutable" ON "{table}"')
    op.drop_index("ix_profit_pilot_scope_created", table_name="profit_pilot_proposals")
    op.drop_table("profit_pilot_proposals")
    op.drop_index("ix_profit_decision_scope_created", table_name="profit_decision_snapshots")
    op.drop_table("profit_decision_snapshots")
    op.execute('DROP TRIGGER IF EXISTS "trg_market_recon_bundle_items_immutable" ON "market_recon_bundle_items"')
    op.drop_index("ix_market_recon_bundle_item_scope_kind", table_name="market_recon_bundle_items")
    op.drop_table("market_recon_bundle_items")
    op.drop_index("ix_market_recon_bundle_scope_created", table_name="market_recon_bundle_runs")
    op.drop_table("market_recon_bundle_runs")
