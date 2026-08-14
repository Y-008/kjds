"""Add native tenant/entity/store authority to Ozon import staging."""

import sqlalchemy as sa
from alembic import op

revision = "20260728_0065"
down_revision = "20260728_0064"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "import_jobs",
        sa.Column("tenant_ref", sa.String(160), nullable=True),
    )
    op.add_column(
        "import_jobs",
        sa.Column("entity_ref", sa.String(160), nullable=True),
    )
    op.add_column(
        "import_jobs",
        sa.Column("store_ref", sa.String(160), nullable=True),
    )
    op.add_column(
        "import_jobs",
        sa.Column(
            "scope_grant_authority_sha256",
            sa.String(64),
            nullable=True,
        ),
    )
    op.add_column(
        "import_jobs",
        sa.Column(
            "source_evidence_sha256",
            sa.String(64),
            nullable=True,
        ),
    )
    op.add_column(
        "import_jobs",
        sa.Column(
            "scope_as_of",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_import_job_scope_complete",
        "import_jobs",
        "("
        "tenant_ref IS NULL AND entity_ref IS NULL "
        "AND store_ref IS NULL "
        "AND scope_grant_authority_sha256 IS NULL "
        "AND source_evidence_sha256 IS NULL "
        "AND scope_as_of IS NULL"
        ") OR ("
        "tenant_ref IS NOT NULL AND length(tenant_ref) > 0 "
        "AND entity_ref IS NOT NULL AND length(entity_ref) > 0 "
        "AND store_ref IS NOT NULL AND length(store_ref) > 0 "
        "AND scope_grant_authority_sha256 IS NOT NULL "
        "AND length(scope_grant_authority_sha256) = 64 "
        "AND source_evidence_sha256 IS NOT NULL "
        "AND length(source_evidence_sha256) = 64 "
        "AND scope_as_of IS NOT NULL "
        "AND evidence_id IS NOT NULL"
        ")",
    )
    op.drop_constraint(
        "import_jobs_sha256_key",
        "import_jobs",
        type_="unique",
    )
    op.create_index(
        "uq_import_job_legacy_sha256",
        "import_jobs",
        ["sha256"],
        unique=True,
        postgresql_where=sa.text("tenant_ref IS NULL"),
    )
    op.create_index(
        "uq_import_job_scoped_sha256",
        "import_jobs",
        ["tenant_ref", "entity_ref", "store_ref", "sha256"],
        unique=True,
        postgresql_where=sa.text("tenant_ref IS NOT NULL"),
    )
    op.create_index(
        "ix_import_job_scope_created",
        "import_jobs",
        ["tenant_ref", "entity_ref", "store_ref", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_import_job_scope_created",
        table_name="import_jobs",
    )
    op.drop_index(
        "uq_import_job_scoped_sha256",
        table_name="import_jobs",
    )
    op.drop_index(
        "uq_import_job_legacy_sha256",
        table_name="import_jobs",
    )
    op.create_unique_constraint(
        "import_jobs_sha256_key",
        "import_jobs",
        ["sha256"],
    )
    op.drop_constraint(
        "ck_import_job_scope_complete",
        "import_jobs",
        type_="check",
    )
    op.drop_column("import_jobs", "scope_as_of")
    op.drop_column("import_jobs", "source_evidence_sha256")
    op.drop_column("import_jobs", "scope_grant_authority_sha256")
    op.drop_column("import_jobs", "store_ref")
    op.drop_column("import_jobs", "entity_ref")
    op.drop_column("import_jobs", "tenant_ref")
