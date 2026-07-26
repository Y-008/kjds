"""Make supplier RFQ dispatch source references idempotent."""

import sqlalchemy as sa
from alembic import op

revision = "20260726_0050"
down_revision = "20260726_0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_supplier_rfq_dispatch_source_ref",
        "evidence_records",
        ["source", "source_ref"],
        unique=True,
        postgresql_where=sa.text("source = 'supplier_rfq_dispatch'"),
        sqlite_where=sa.text("source = 'supplier_rfq_dispatch'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_supplier_rfq_dispatch_source_ref",
        table_name="evidence_records",
    )
