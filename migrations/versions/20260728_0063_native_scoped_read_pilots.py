"""Add native tenant/entity/store authority to Ozon read pilots."""

import sqlalchemy as sa
from alembic import op

revision = "20260728_0063"
down_revision = "20260728_0062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "read_only_pilots",
        sa.Column("tenant_ref", sa.String(160), nullable=True),
    )
    op.add_column(
        "read_only_pilots",
        sa.Column("entity_ref", sa.String(160), nullable=True),
    )
    op.add_column(
        "read_only_pilots",
        sa.Column("store_ref", sa.String(160), nullable=True),
    )
    op.add_column(
        "read_only_pilots",
        sa.Column(
            "scope_grant_authority_sha256",
            sa.String(64),
            nullable=True,
        ),
    )
    op.add_column(
        "read_only_pilots",
        sa.Column(
            "scope_evidence_authority_sha256",
            sa.String(64),
            nullable=True,
        ),
    )
    op.add_column(
        "read_only_pilots",
        sa.Column(
            "scope_as_of",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_read_only_pilot_scope_complete",
        "read_only_pilots",
        "("
        "tenant_ref IS NULL AND entity_ref IS NULL "
        "AND store_ref IS NULL "
        "AND scope_grant_authority_sha256 IS NULL "
        "AND scope_evidence_authority_sha256 IS NULL "
        "AND scope_as_of IS NULL"
        ") OR ("
        "tenant_ref IS NOT NULL AND length(tenant_ref) > 0 "
        "AND entity_ref IS NOT NULL AND length(entity_ref) > 0 "
        "AND store_ref IS NOT NULL AND length(store_ref) > 0 "
        "AND scope_grant_authority_sha256 IS NOT NULL "
        "AND length(scope_grant_authority_sha256) = 64 "
        "AND scope_evidence_authority_sha256 IS NOT NULL "
        "AND length(scope_evidence_authority_sha256) = 64 "
        "AND scope_as_of IS NOT NULL"
        ")",
    )
    op.drop_constraint(
        "read_only_pilots_idempotency_key_key",
        "read_only_pilots",
        type_="unique",
    )
    op.create_index(
        "uq_read_only_pilot_legacy_idempotency",
        "read_only_pilots",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("tenant_ref IS NULL"),
    )
    op.create_index(
        "uq_read_only_pilot_scoped_idempotency",
        "read_only_pilots",
        ["tenant_ref", "entity_ref", "store_ref", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("tenant_ref IS NOT NULL"),
    )
    op.create_index(
        "ix_read_only_pilot_scope_created",
        "read_only_pilots",
        ["tenant_ref", "entity_ref", "store_ref", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_read_only_pilot_scope_created",
        table_name="read_only_pilots",
    )
    op.drop_index(
        "uq_read_only_pilot_scoped_idempotency",
        table_name="read_only_pilots",
    )
    op.drop_index(
        "uq_read_only_pilot_legacy_idempotency",
        table_name="read_only_pilots",
    )
    op.create_unique_constraint(
        "read_only_pilots_idempotency_key_key",
        "read_only_pilots",
        ["idempotency_key"],
    )
    op.drop_constraint(
        "ck_read_only_pilot_scope_complete",
        "read_only_pilots",
        type_="check",
    )
    op.drop_column("read_only_pilots", "scope_as_of")
    op.drop_column(
        "read_only_pilots",
        "scope_evidence_authority_sha256",
    )
    op.drop_column(
        "read_only_pilots",
        "scope_grant_authority_sha256",
    )
    op.drop_column("read_only_pilots", "store_ref")
    op.drop_column("read_only_pilots", "entity_ref")
    op.drop_column("read_only_pilots", "tenant_ref")
