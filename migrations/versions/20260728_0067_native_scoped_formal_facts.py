"""Add native tenant/entity/store authority to formal Fact promotion."""

import sqlalchemy as sa
from alembic import op

revision = "20260728_0067"
down_revision = "20260728_0066"
branch_labels = None
depends_on = None


SCOPE_COLUMNS = (
    sa.Column("tenant_ref", sa.String(160), nullable=True),
    sa.Column("entity_ref", sa.String(160), nullable=True),
    sa.Column("store_ref", sa.String(160), nullable=True),
    sa.Column(
        "scope_grant_authority_sha256",
        sa.String(64),
        nullable=True,
    ),
    sa.Column(
        "source_evidence_sha256",
        sa.String(64),
        nullable=True,
    ),
    sa.Column(
        "scope_as_of",
        sa.DateTime(timezone=True),
        nullable=True,
    ),
)


def _scope_check(*, request_hash: bool = False) -> str:
    legacy = (
        "tenant_ref IS NULL AND entity_ref IS NULL AND store_ref IS NULL "
        "AND scope_grant_authority_sha256 IS NULL "
        "AND source_evidence_sha256 IS NULL AND scope_as_of IS NULL"
    )
    native = (
        "tenant_ref IS NOT NULL AND length(tenant_ref) > 0 "
        "AND entity_ref IS NOT NULL AND length(entity_ref) > 0 "
        "AND store_ref IS NOT NULL AND length(store_ref) > 0 "
        "AND scope_grant_authority_sha256 IS NOT NULL "
        "AND length(scope_grant_authority_sha256) = 64 "
        "AND source_evidence_sha256 IS NOT NULL "
        "AND length(source_evidence_sha256) = 64 "
        "AND scope_as_of IS NOT NULL"
    )
    if request_hash:
        legacy += " AND request_sha256 IS NULL"
        native += (
            " AND request_sha256 IS NOT NULL "
            "AND length(request_sha256) = 64"
        )
    return f"({legacy}) OR ({native})"


def upgrade() -> None:
    for column in SCOPE_COLUMNS:
        op.add_column("fact_records", column.copy())
        op.add_column("promotion_runs", column.copy())
    op.add_column(
        "promotion_runs",
        sa.Column("request_sha256", sa.String(64), nullable=True),
    )

    op.create_check_constraint(
        "ck_fact_record_scope_complete",
        "fact_records",
        _scope_check(),
    )
    op.create_check_constraint(
        "ck_promotion_run_scope_complete",
        "promotion_runs",
        _scope_check(request_hash=True),
    )

    op.drop_constraint(
        "uq_fact_import_contract",
        "fact_records",
        type_="unique",
    )
    op.drop_constraint(
        "uq_fact_source_payload",
        "fact_records",
        type_="unique",
    )
    op.create_index(
        "uq_fact_legacy_import_contract",
        "fact_records",
        ["import_row_id", "contract_version"],
        unique=True,
        postgresql_where=sa.text("tenant_ref IS NULL"),
    )
    op.create_index(
        "uq_fact_legacy_source_payload",
        "fact_records",
        ["source", "fact_type", "natural_key", "payload_hash"],
        unique=True,
        postgresql_where=sa.text("tenant_ref IS NULL"),
    )
    op.create_index(
        "uq_fact_scoped_import_contract",
        "fact_records",
        [
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "import_row_id",
            "contract_version",
        ],
        unique=True,
        postgresql_where=sa.text("tenant_ref IS NOT NULL"),
    )
    op.create_index(
        "uq_fact_scoped_source_payload",
        "fact_records",
        [
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "source",
            "fact_type",
            "natural_key",
            "payload_hash",
        ],
        unique=True,
        postgresql_where=sa.text("tenant_ref IS NOT NULL"),
    )
    op.create_index(
        "ix_fact_scope_recorded",
        "fact_records",
        ["tenant_ref", "entity_ref", "store_ref", "recorded_at"],
    )
    op.create_index(
        "uq_promotion_run_scoped_request",
        "promotion_runs",
        [
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "request_sha256",
        ],
        unique=True,
        postgresql_where=sa.text("tenant_ref IS NOT NULL"),
    )
    op.create_index(
        "ix_promotion_run_scope_created",
        "promotion_runs",
        ["tenant_ref", "entity_ref", "store_ref", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_promotion_run_scope_created",
        table_name="promotion_runs",
    )
    op.drop_index(
        "uq_promotion_run_scoped_request",
        table_name="promotion_runs",
    )
    op.drop_index("ix_fact_scope_recorded", table_name="fact_records")
    op.drop_index(
        "uq_fact_scoped_source_payload",
        table_name="fact_records",
    )
    op.drop_index(
        "uq_fact_scoped_import_contract",
        table_name="fact_records",
    )
    op.drop_index(
        "uq_fact_legacy_source_payload",
        table_name="fact_records",
    )
    op.drop_index(
        "uq_fact_legacy_import_contract",
        table_name="fact_records",
    )
    op.create_unique_constraint(
        "uq_fact_import_contract",
        "fact_records",
        ["import_row_id", "contract_version"],
    )
    op.create_unique_constraint(
        "uq_fact_source_payload",
        "fact_records",
        ["source", "fact_type", "natural_key", "payload_hash"],
    )
    op.drop_constraint(
        "ck_promotion_run_scope_complete",
        "promotion_runs",
        type_="check",
    )
    op.drop_constraint(
        "ck_fact_record_scope_complete",
        "fact_records",
        type_="check",
    )
    op.drop_column("promotion_runs", "request_sha256")
    for column in reversed(SCOPE_COLUMNS):
        op.drop_column("promotion_runs", column.name)
        op.drop_column("fact_records", column.name)
