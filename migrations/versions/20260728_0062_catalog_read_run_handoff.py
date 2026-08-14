"""Add governed Ozon read-run to Catalog handoff ledger."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260728_0062"
down_revision = "20260728_0061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "catalog_read_run_handoffs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_ref", sa.String(160), nullable=False),
        sa.Column("entity_ref", sa.String(160), nullable=False),
        sa.Column("store_ref", sa.String(160), nullable=False),
        sa.Column(
            "scope_grant_authority_sha256",
            sa.String(64),
            nullable=False,
        ),
        sa.Column(
            "scope_evidence_authority_sha256",
            sa.String(64),
            nullable=False,
        ),
        sa.Column(
            "scope_as_of",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.String(),
            sa.ForeignKey(
                "read_only_pilot_runs.id",
                name="fk_catalog_handoff_read_run",
            ),
            nullable=False,
        ),
        sa.Column(
            "raw_response_evidence_id",
            sa.String(),
            sa.ForeignKey(
                "evidence_records.id",
                name="fk_catalog_handoff_raw_evidence",
            ),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column(
            "scope_authority_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "source_contract_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column(
            "catalog_snapshot_id",
            sa.String(),
            sa.ForeignKey(
                "marketplace_catalog_snapshots.id",
                name="fk_catalog_handoff_snapshot",
            ),
            nullable=True,
        ),
        sa.Column("catalog_snapshot_hash", sa.String(64), nullable=True),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("prepared_by", sa.String(160), nullable=False),
        sa.Column(
            "prepared_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "idempotency_key",
            name="uq_catalog_read_run_handoff_scoped_key",
        ),
        sa.CheckConstraint(
            "length(tenant_ref) > 0 "
            "AND length(entity_ref) > 0 "
            "AND length(store_ref) > 0 "
            "AND length(scope_grant_authority_sha256) = 64 "
            "AND length(scope_evidence_authority_sha256) = 64 "
            "AND length(request_hash) = 64 "
            "AND jsonb_typeof(scope_authority_json) = 'object' "
            "AND jsonb_typeof(source_contract_json) = 'object'",
            name="ck_catalog_read_run_handoff_authority",
        ),
        sa.CheckConstraint(
            "("
            "status = 'prepared' AND catalog_snapshot_id IS NULL "
            "AND catalog_snapshot_hash IS NULL AND error_code IS NULL "
            "AND completed_at IS NULL"
            ") OR ("
            "status = 'completed' AND catalog_snapshot_id IS NOT NULL "
            "AND length(catalog_snapshot_hash) = 64 "
            "AND error_code IS NULL AND completed_at IS NOT NULL"
            ") OR ("
            "status = 'blocked' AND catalog_snapshot_id IS NULL "
            "AND catalog_snapshot_hash IS NULL "
            "AND length(error_code) > 0 AND completed_at IS NOT NULL"
            ")",
            name="ck_catalog_read_run_handoff_state",
        ),
    )
    op.create_index(
        "ix_catalog_read_run_handoff_scope_prepared",
        "catalog_read_run_handoffs",
        ["tenant_ref", "entity_ref", "store_ref", "prepared_at"],
    )
    op.create_index(
        "ix_catalog_read_run_handoff_run",
        "catalog_read_run_handoffs",
        ["run_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_catalog_read_run_handoff_run",
        table_name="catalog_read_run_handoffs",
    )
    op.drop_index(
        "ix_catalog_read_run_handoff_scope_prepared",
        table_name="catalog_read_run_handoffs",
    )
    op.drop_table("catalog_read_run_handoffs")
