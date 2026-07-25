"""Reject logistics rate cards that cannot produce a positive charge."""

from alembic import op

revision = "20260726_0046"
down_revision = "20260726_0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_logistics_rate_card_positive_charge",
        "logistics_rate_cards",
        "price_per_kg > 0 OR base_charge_per_parcel > 0 "
        "OR minimum_charge_per_parcel > 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_logistics_rate_card_positive_charge",
        "logistics_rate_cards",
        type_="check",
    )
