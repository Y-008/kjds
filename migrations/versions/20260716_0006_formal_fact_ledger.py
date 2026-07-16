"""Add Ozon data contracts and staging-to-fact promotion ledger."""

import sqlalchemy as sa
from alembic import op

revision = "20260716_0006"
down_revision = "20260716_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "import_jobs",
        sa.Column("record_type", sa.String(), nullable=False, server_default="ozon_order"),
    )
    op.add_column("import_jobs", sa.Column("evidence_id", sa.String(), nullable=True))
    op.create_foreign_key(
        "fk_import_jobs_evidence",
        "import_jobs",
        "evidence_records",
        ["evidence_id"],
        ["id"],
    )
    op.alter_column("import_jobs", "record_type", server_default=None)

    op.create_table(
        "fact_records",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("fact_type", sa.String(), nullable=False),
        sa.Column("natural_key", sa.String(), nullable=False),
        sa.Column("contract_version", sa.String(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_id", sa.String(), sa.ForeignKey("evidence_records.id"), nullable=False),
        sa.Column("import_row_id", sa.String(), sa.ForeignKey("import_rows.id"), nullable=False),
        sa.Column("product_id", sa.String(), sa.ForeignKey("products.id")),
        sa.Column("resolution_status", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.UniqueConstraint("import_row_id", "contract_version", name="uq_fact_import_contract"),
        sa.UniqueConstraint("source", "fact_type", "natural_key", "payload_hash", name="uq_fact_source_payload"),
    )
    op.create_index("idx_facts_type_effective", "fact_records", ["fact_type", "effective_at"])
    op.create_index("idx_facts_resolution", "fact_records", ["resolution_status", "recorded_at"])
    op.create_table(
        "promotion_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("import_id", sa.String(), sa.ForeignKey("import_jobs.id"), nullable=False),
        sa.Column("promoted_count", sa.Integer(), nullable=False),
        sa.Column("duplicate_count", sa.Integer(), nullable=False),
        sa.Column("blocked_count", sa.Integer(), nullable=False),
        sa.Column("errors_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for table in ("fact_records", "promotion_runs"):
        op.execute(sa.text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
        op.execute(
            sa.text(
                f'CREATE TRIGGER "trg_{table}_immutable" BEFORE UPDATE OR DELETE ON "{table}" '
                "FOR EACH ROW EXECUTE FUNCTION kjds_prevent_ledger_mutation()"
            )
        )


def downgrade() -> None:
    op.drop_table("promotion_runs")
    op.drop_index("idx_facts_resolution", table_name="fact_records")
    op.drop_index("idx_facts_type_effective", table_name="fact_records")
    op.drop_table("fact_records")
    op.drop_constraint("fk_import_jobs_evidence", "import_jobs", type_="foreignkey")
    op.drop_column("import_jobs", "evidence_id")
    op.drop_column("import_jobs", "record_type")
