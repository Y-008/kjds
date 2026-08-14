"""Add replayable observation unit-price semantics without rewriting 0053."""

import sqlalchemy as sa
from alembic import op

revision = "20260727_0054"
down_revision = "20260727_0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "marketplace_observation_items",
        sa.Column(
            "price_scope",
            sa.String(),
            nullable=False,
            server_default="unit_price",
        ),
    )
    op.add_column(
        "marketplace_observation_items",
        sa.Column(
            "unit_price_decimal",
            sa.Numeric(38, 12),
            nullable=True,
        ),
    )
    # The table is append-only at runtime. The migration temporarily disables
    # the exact immutable trigger inside the same DDL transaction solely to
    # backfill the new derived column; existing source, item and Evidence
    # hashes are not rewritten.
    op.execute(
        sa.text(
            "ALTER TABLE marketplace_observation_items "
            "DISABLE TRIGGER trg_marketplace_observation_items_immutable"
        )
    )
    op.execute(
        sa.text(
            "UPDATE marketplace_observation_items "
            "SET unit_price_decimal = displayed_price_decimal "
            "WHERE unit_price_decimal IS NULL"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE marketplace_observation_items "
            "ENABLE TRIGGER trg_marketplace_observation_items_immutable"
        )
    )
    op.alter_column(
        "marketplace_observation_items",
        "unit_price_decimal",
        nullable=False,
    )
    op.alter_column(
        "marketplace_observation_items",
        "price_scope",
        server_default=None,
    )
    op.create_check_constraint(
        "ck_marketplace_observation_price_scope",
        "marketplace_observation_items",
        "price_scope IN ('unit_price','checkout_total')",
    )
    op.create_check_constraint(
        "ck_marketplace_observation_unit_price_positive",
        "marketplace_observation_items",
        "unit_price_decimal > 0",
    )
    op.create_check_constraint(
        "ck_marketplace_observation_unit_price_semantics",
        "marketplace_observation_items",
        "(price_scope = 'unit_price' AND "
        "unit_price_decimal = displayed_price_decimal) OR "
        "(price_scope = 'checkout_total' AND "
        "observed_quantity IS NOT NULL AND "
        "abs(unit_price_decimal * observed_quantity - "
        "displayed_price_decimal) <= 0.000001)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_marketplace_observation_unit_price_semantics",
        "marketplace_observation_items",
        type_="check",
    )
    op.drop_constraint(
        "ck_marketplace_observation_unit_price_positive",
        "marketplace_observation_items",
        type_="check",
    )
    op.drop_constraint(
        "ck_marketplace_observation_price_scope",
        "marketplace_observation_items",
        type_="check",
    )
    op.drop_column(
        "marketplace_observation_items",
        "unit_price_decimal",
    )
    op.drop_column(
        "marketplace_observation_items",
        "price_scope",
    )
