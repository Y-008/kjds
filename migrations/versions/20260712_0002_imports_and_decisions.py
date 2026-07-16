"""Add evidence imports, model registry, and shadow decisions."""

import sqlalchemy as sa
from alembic import op

revision = "20260712_0002"
down_revision = "20260711_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "import_jobs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("accepted_count", sa.Integer(), nullable=False),
        sa.Column("rejected_count", sa.Integer(), nullable=False),
        sa.Column("mapping_json", sa.JSON(), nullable=False),
        sa.Column("errors_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "import_rows",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("import_id", sa.String(), sa.ForeignKey("import_jobs.id"), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("record_type", sa.String(), nullable=False),
        sa.Column("external_id", sa.String()),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("normalized_json", sa.JSON(), nullable=False),
        sa.Column("errors_json", sa.JSON(), nullable=False),
        sa.UniqueConstraint("import_id", "row_number"),
    )
    op.create_index("idx_import_rows_external", "import_rows", ["record_type", "external_id"])
    op.create_table(
        "model_registry",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("model_name", sa.String(), nullable=False),
        sa.Column("capability", sa.String(), nullable=False),
        sa.Column("license_name", sa.String(), nullable=False),
        sa.Column("commercial_status", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider", "model_name", "capability"),
    )
    op.create_table(
        "decision_recommendations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("product_id", sa.String(), sa.ForeignKey("products.id")),
        sa.Column("agent", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("expected_cm3_delta_decimal", sa.Numeric(24, 8)),
        sa.Column("risk", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("shadow_mode", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("decision_recommendations")
    op.drop_table("model_registry")
    op.drop_index("idx_import_rows_external", table_name="import_rows")
    op.drop_table("import_rows")
    op.drop_table("import_jobs")
