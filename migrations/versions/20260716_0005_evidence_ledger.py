"""Add immutable evidence blobs, bitemporal records, and lineage."""

import sqlalchemy as sa
from alembic import op

revision = "20260716_0005"
down_revision = "20260716_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evidence_blobs",
        sa.Column("sha256", sa.String(64), primary_key=True),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("content_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "evidence_records",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("blob_sha256", sa.String(64), sa.ForeignKey("evidence_blobs.sha256"), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("grade", sa.String(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_until", sa.DateTime(timezone=True)),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.UniqueConstraint("blob_sha256", "source", "source_ref", "effective_at", name="uq_evidence_capture"),
    )
    op.create_index("idx_evidence_effective_recorded", "evidence_records", ["effective_at", "recorded_at"])
    op.create_table(
        "lineage_edges",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("from_type", sa.String(), nullable=False),
        sa.Column("from_id", sa.String(), nullable=False),
        sa.Column("to_type", sa.String(), nullable=False),
        sa.Column("to_id", sa.String(), nullable=False),
        sa.Column("relationship", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "from_type", "from_id", "to_type", "to_id", "relationship", name="uq_lineage_edge"
        ),
    )
    op.create_index("idx_lineage_from", "lineage_edges", ["from_type", "from_id"])
    op.create_index("idx_lineage_to", "lineage_edges", ["to_type", "to_id"])

    op.execute(
        """
        CREATE OR REPLACE FUNCTION kjds_prevent_ledger_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'immutable ledger rows cannot be updated or deleted';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table in ("evidence_blobs", "evidence_records", "lineage_edges"):
        op.execute(sa.text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
        op.execute(
            sa.text(
                f'CREATE TRIGGER "trg_{table}_immutable" BEFORE UPDATE OR DELETE ON "{table}" '
                "FOR EACH ROW EXECUTE FUNCTION kjds_prevent_ledger_mutation()"
            )
        )


def downgrade() -> None:
    op.drop_index("idx_lineage_to", table_name="lineage_edges")
    op.drop_index("idx_lineage_from", table_name="lineage_edges")
    op.drop_table("lineage_edges")
    op.drop_index("idx_evidence_effective_recorded", table_name="evidence_records")
    op.drop_table("evidence_records")
    op.drop_table("evidence_blobs")
    op.execute("DROP FUNCTION IF EXISTS kjds_prevent_ledger_mutation()")
