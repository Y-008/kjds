"""Add isolated browser capture inbox submissions."""

import sqlalchemy as sa
from alembic import op

revision = "20260729_0071"
down_revision = "20260728_0070"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "browser_capture_inbox_submissions",
        sa.Column("id", sa.String(length=180), nullable=False),
        sa.Column("tenant_ref", sa.String(length=160), nullable=False),
        sa.Column("entity_ref", sa.String(length=160), nullable=True),
        sa.Column("store_ref", sa.String(length=160), nullable=False),
        sa.Column("entity_scope_status", sa.String(length=20), nullable=False),
        sa.Column(
            "scope_grant_authority_sha256",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column("source_profile", sa.String(length=80), nullable=False),
        sa.Column("marketplace", sa.String(length=40), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_host", sa.String(length=255), nullable=False),
        sa.Column(
            "observed_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column("contract_version", sa.String(length=80), nullable=False),
        sa.Column("adapter_id", sa.String(length=160), nullable=False),
        sa.Column("adapter_version", sa.String(length=80), nullable=False),
        sa.Column(
            "adapter_contract_sha256",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "adapter_definition_sha256",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column("source_grade", sa.String(length=1), nullable=False),
        sa.Column(
            "semantic_authority", sa.String(length=160), nullable=False
        ),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("evidence_id", sa.String(), nullable=False),
        sa.Column("evidence_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column(
            "normalized_payload_json", sa.JSON(), nullable=False
        ),
        sa.Column("captured_by", sa.String(length=160), nullable=False),
        sa.Column(
            "captured_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.CheckConstraint(
            "("
            "entity_ref IS NULL "
            "AND scope_grant_authority_sha256 IS NULL "
            "AND entity_scope_status IN ('no_data','blocked')"
            ") OR ("
            "entity_ref IS NOT NULL "
            "AND scope_grant_authority_sha256 IS NOT NULL "
            "AND length(scope_grant_authority_sha256) = 64 "
            "AND entity_scope_status = 'ready'"
            ")",
            name="ck_browser_capture_entity_scope_complete",
        ),
        sa.CheckConstraint(
            "length(adapter_contract_sha256) = 64 "
            "AND length(adapter_definition_sha256) = 64 "
            "AND source_grade IN ('A','B','C','D')",
            name="ck_browser_capture_adapter_authority",
        ),
        sa.CheckConstraint(
            "length(request_sha256) = 64 "
            "AND length(evidence_sha256) = 64",
            name="ck_browser_capture_content_hashes",
        ),
        sa.CheckConstraint(
            "status IN ('quarantined','pending_independent_binding')",
            name="ck_browser_capture_status",
        ),
        sa.CheckConstraint(
            "contract_version = 'kjds-browser-capture-envelope/1.0' "
            "AND source_profile = 'browser_observation' "
            "AND marketplace IN ('1688','ozon')",
            name="ck_browser_capture_contract_profile",
        ),
        sa.CheckConstraint(
            "item_count BETWEEN 1 AND 50",
            name="ck_browser_capture_item_count",
        ),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence_records.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_ref",
            "store_ref",
            "idempotency_key",
            name="uq_browser_capture_scope_idempotency",
        ),
    )
    op.create_index(
        "ix_browser_capture_scope_observed",
        "browser_capture_inbox_submissions",
        ["tenant_ref", "store_ref", "observed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_browser_capture_scope_observed",
        table_name="browser_capture_inbox_submissions",
    )
    op.drop_table("browser_capture_inbox_submissions")
