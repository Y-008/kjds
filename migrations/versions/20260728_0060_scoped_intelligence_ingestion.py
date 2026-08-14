"""Add native scope and source-adapter authority to market observations."""

import sqlalchemy as sa
from alembic import op

revision = "20260728_0060"
down_revision = "20260728_0059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = (
        sa.Column("tenant_ref", sa.String(160), nullable=True),
        sa.Column("entity_ref", sa.String(160), nullable=True),
        sa.Column(
            "scope_grant_authority_sha256",
            sa.String(64),
            nullable=True,
        ),
        sa.Column(
            "scope_as_of",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("adapter_id", sa.String(160), nullable=True),
        sa.Column("adapter_version", sa.String(80), nullable=True),
        sa.Column(
            "adapter_contract_sha256",
            sa.String(64),
            nullable=True,
        ),
        sa.Column("source_grade", sa.String(1), nullable=True),
        sa.Column("semantic_authority", sa.String(160), nullable=True),
        sa.Column("source_evidence_ids_json", sa.JSON(), nullable=True),
    )
    for column in columns:
        op.add_column("marketplace_observation_snapshots", column)

    op.drop_constraint(
        "uq_marketplace_observation_idempotency",
        "marketplace_observation_snapshots",
        type_="unique",
    )
    op.create_check_constraint(
        "ck_marketplace_observation_scope_adapter_complete",
        "marketplace_observation_snapshots",
        "("
        "tenant_ref IS NULL AND entity_ref IS NULL "
        "AND scope_grant_authority_sha256 IS NULL "
        "AND scope_as_of IS NULL AND adapter_id IS NULL "
        "AND adapter_version IS NULL "
        "AND adapter_contract_sha256 IS NULL "
        "AND source_grade IS NULL AND semantic_authority IS NULL "
        "AND source_evidence_ids_json IS NULL"
        ") OR ("
        "tenant_ref IS NOT NULL AND length(tenant_ref) > 0 "
        "AND entity_ref IS NOT NULL AND length(entity_ref) > 0 "
        "AND scope_grant_authority_sha256 IS NOT NULL "
        "AND length(scope_grant_authority_sha256) = 64 "
        "AND scope_as_of IS NOT NULL "
        "AND adapter_id IS NOT NULL AND length(adapter_id) > 0 "
        "AND adapter_version IS NOT NULL "
        "AND length(adapter_version) > 0 "
        "AND adapter_contract_sha256 IS NOT NULL "
        "AND length(adapter_contract_sha256) = 64 "
        "AND source_grade IN ('A','B','C','D') "
        "AND semantic_authority IS NOT NULL "
        "AND length(semantic_authority) > 0 "
        "AND source_evidence_ids_json IS NOT NULL "
        "AND jsonb_typeof(source_evidence_ids_json::jsonb) = 'array'"
        ")",
    )
    op.create_index(
        "uq_marketplace_observation_legacy_idempotency",
        "marketplace_observation_snapshots",
        ["source_profile", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("tenant_ref IS NULL"),
    )
    op.create_index(
        "uq_marketplace_observation_scoped_idempotency",
        "marketplace_observation_snapshots",
        [
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "source_profile",
            "idempotency_key",
        ],
        unique=True,
        postgresql_where=sa.text("tenant_ref IS NOT NULL"),
    )
    op.create_index(
        "ix_marketplace_observation_scope_observed",
        "marketplace_observation_snapshots",
        ["tenant_ref", "entity_ref", "store_ref", "observed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_marketplace_observation_scope_observed",
        table_name="marketplace_observation_snapshots",
    )
    op.drop_index(
        "uq_marketplace_observation_scoped_idempotency",
        table_name="marketplace_observation_snapshots",
    )
    op.drop_index(
        "uq_marketplace_observation_legacy_idempotency",
        table_name="marketplace_observation_snapshots",
    )
    op.drop_constraint(
        "ck_marketplace_observation_scope_adapter_complete",
        "marketplace_observation_snapshots",
        type_="check",
    )
    op.create_unique_constraint(
        "uq_marketplace_observation_idempotency",
        "marketplace_observation_snapshots",
        ["source_profile", "idempotency_key"],
    )
    for column in (
        "source_evidence_ids_json",
        "semantic_authority",
        "source_grade",
        "adapter_contract_sha256",
        "adapter_version",
        "adapter_id",
        "scope_as_of",
        "scope_grant_authority_sha256",
        "entity_ref",
        "tenant_ref",
    ):
        op.drop_column("marketplace_observation_snapshots", column)
