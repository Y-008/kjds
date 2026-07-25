"""Persist versioned logistics rate cards and immutable cost calculations."""

import sqlalchemy as sa
from alembic import op

revision = "20260726_0044"
down_revision = "20260726_0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "logistics_rate_cards",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("provider", sa.String(length=160), nullable=False),
        sa.Column("route_code", sa.String(length=160), nullable=False),
        sa.Column("service_name", sa.String(length=300), nullable=False),
        sa.Column("origin_country", sa.String(length=12), nullable=False),
        sa.Column("destination_country", sa.String(length=12), nullable=False),
        sa.Column("marketplace", sa.String(length=40), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("declared_value_currency", sa.String(length=3), nullable=False),
        sa.Column("price_per_kg", sa.Numeric(24, 8), nullable=False),
        sa.Column("base_charge_per_parcel", sa.Numeric(24, 8), nullable=False),
        sa.Column("minimum_charge_per_parcel", sa.Numeric(24, 8), nullable=False),
        sa.Column("volumetric_divisor_cm3_per_kg", sa.Numeric(24, 8), nullable=False),
        sa.Column("weight_increment_kg", sa.Numeric(24, 8), nullable=False),
        sa.Column("min_weight_kg", sa.Numeric(24, 8), nullable=False),
        sa.Column("max_weight_kg", sa.Numeric(24, 8), nullable=False),
        sa.Column("max_length_cm", sa.Numeric(24, 8), nullable=False),
        sa.Column("max_width_cm", sa.Numeric(24, 8), nullable=False),
        sa.Column("max_height_cm", sa.Numeric(24, 8), nullable=False),
        sa.Column("max_dimensions_sum_cm", sa.Numeric(24, 8), nullable=False),
        sa.Column("min_declared_value", sa.Numeric(24, 8), nullable=False),
        sa.Column("max_declared_value", sa.Numeric(24, 8), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "evidence_id",
            sa.String(),
            sa.ForeignKey("evidence_records.id", name="fk_logistics_rate_card_evidence"),
            nullable=False,
        ),
        sa.Column("captured_by", sa.String(length=160), nullable=False),
        sa.Column("source_sheet", sa.String(length=300), nullable=False),
        sa.Column("source_range", sa.String(length=80), nullable=False),
        sa.Column("rule_version", sa.String(length=80), nullable=False),
        sa.Column("rate_card_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "price_per_kg >= 0 AND base_charge_per_parcel >= 0 "
            "AND minimum_charge_per_parcel >= 0 "
            "AND volumetric_divisor_cm3_per_kg >= 0 "
            "AND weight_increment_kg > 0 AND min_weight_kg >= 0 "
            "AND max_weight_kg > 0 AND min_weight_kg <= max_weight_kg "
            "AND max_length_cm >= 0 AND max_width_cm >= 0 AND max_height_cm >= 0 "
            "AND max_dimensions_sum_cm >= 0 AND min_declared_value >= 0 "
            "AND max_declared_value >= 0 "
            "AND (max_declared_value = 0 OR min_declared_value <= max_declared_value) "
            "AND char_length(currency) = 3 AND char_length(declared_value_currency) = 3 "
            "AND char_length(rate_card_hash) = 64 "
            "AND rule_version = 'crossborder-logistics-rate-v1' "
            "AND (effective_until IS NULL OR effective_until > effective_at)",
            name="ck_logistics_rate_card_contract",
        ),
    )
    op.create_table(
        "logistics_calculations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "rate_card_id",
            sa.String(),
            sa.ForeignKey(
                "logistics_rate_cards.id",
                name="fk_logistics_calculation_rate_card",
            ),
            nullable=False,
        ),
        sa.Column("physical_weight_kg", sa.Numeric(24, 8), nullable=False),
        sa.Column("length_cm", sa.Numeric(24, 8), nullable=False),
        sa.Column("width_cm", sa.Numeric(24, 8), nullable=False),
        sa.Column("height_cm", sa.Numeric(24, 8), nullable=False),
        sa.Column("declared_value", sa.Numeric(24, 8), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("currency_to_cny_rate", sa.Numeric(24, 8), nullable=False),
        sa.Column("volumetric_weight_kg", sa.Numeric(24, 8), nullable=False),
        sa.Column("chargeable_weight_kg", sa.Numeric(24, 8), nullable=False),
        sa.Column("billable_weight_kg", sa.Numeric(24, 8), nullable=False),
        sa.Column("unit_charge_currency", sa.Numeric(24, 8), nullable=False),
        sa.Column("total_charge_currency", sa.Numeric(24, 8), nullable=False),
        sa.Column("total_charge_cny", sa.Numeric(24, 8), nullable=False),
        sa.Column(
            "evidence_id",
            sa.String(),
            sa.ForeignKey(
                "evidence_records.id",
                name="fk_logistics_calculation_evidence",
            ),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("calculated_by", sa.String(length=160), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "rate_card_id",
            "idempotency_key",
            name="uq_logistics_calculation_idempotency",
        ),
        sa.CheckConstraint(
            "physical_weight_kg > 0 AND length_cm >= 0 AND width_cm >= 0 "
            "AND height_cm >= 0 AND declared_value >= 0 AND quantity > 0 "
            "AND currency_to_cny_rate > 0 AND volumetric_weight_kg >= 0 "
            "AND chargeable_weight_kg > 0 AND billable_weight_kg > 0 "
            "AND unit_charge_currency > 0 AND total_charge_currency > 0 "
            "AND total_charge_cny > 0 AND state = 'estimate' "
            "AND char_length(input_hash) = 64",
            name="ck_logistics_calculation_contract",
        ),
    )
    op.create_index(
        "ix_logistics_rate_card_route",
        "logistics_rate_cards",
        ["marketplace", "origin_country", "destination_country", "effective_at"],
    )
    op.create_index(
        "ix_logistics_calculation_latest",
        "logistics_calculations",
        ["rate_card_id", "calculated_at"],
    )
    op.execute("ALTER TABLE logistics_rate_cards ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE logistics_calculations ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index(
        "ix_logistics_calculation_latest",
        table_name="logistics_calculations",
    )
    op.drop_index(
        "ix_logistics_rate_card_route",
        table_name="logistics_rate_cards",
    )
    op.drop_table("logistics_calculations")
    op.drop_table("logistics_rate_cards")
