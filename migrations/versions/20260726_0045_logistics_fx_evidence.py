"""Add optional FX evidence lineage to non-CNY logistics calculations."""

import sqlalchemy as sa
from alembic import op

revision = "20260726_0045"
down_revision = "20260726_0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "logistics_calculations",
        sa.Column("fx_evidence_id", sa.String(), nullable=True),
    )
    op.create_foreign_key(
        "fk_logistics_calculation_fx_evidence",
        "logistics_calculations",
        "evidence_records",
        ["fx_evidence_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_logistics_calculation_fx_evidence",
        "logistics_calculations",
        type_="foreignkey",
    )
    op.drop_column("logistics_calculations", "fx_evidence_id")
