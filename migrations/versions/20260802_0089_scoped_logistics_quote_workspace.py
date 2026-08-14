"""Add fail-closed exact scope to logistics rates and calculations.

Revision ID: 20260802_0089
Revises: 20260802_0088
Create Date: 2026-08-02
"""

import sqlalchemy as sa
from alembic import op

revision = "20260802_0089"
down_revision = "20260802_0088"
branch_labels = None
depends_on = None

SCOPE_COLUMNS = (
    "tenant_ref",
    "entity_ref",
    "store_ref",
    "scope_grant_authority_sha256",
)


def _add_scope_columns(table_name: str) -> None:
    op.add_column(
        table_name,
        sa.Column("tenant_ref", sa.String(length=160), nullable=True),
    )
    op.add_column(
        table_name,
        sa.Column("entity_ref", sa.String(length=160), nullable=True),
    )
    op.add_column(
        table_name,
        sa.Column("store_ref", sa.String(length=160), nullable=True),
    )
    op.add_column(
        table_name,
        sa.Column(
            "scope_grant_authority_sha256",
            sa.String(length=64),
            nullable=True,
        ),
    )
    op.add_column(
        table_name,
        sa.Column("scope_as_of", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        table_name,
        sa.Column(
            "scope_status",
            sa.String(length=30),
            nullable=False,
            server_default="legacy_unbound",
        ),
    )


def _drop_scope_columns(table_name: str) -> None:
    op.drop_column(table_name, "scope_status")
    op.drop_column(table_name, "scope_as_of")
    op.drop_column(table_name, "scope_grant_authority_sha256")
    op.drop_column(table_name, "store_ref")
    op.drop_column(table_name, "entity_ref")
    op.drop_column(table_name, "tenant_ref")


def upgrade() -> None:
    _add_scope_columns("logistics_rate_cards")
    _add_scope_columns("logistics_calculations")

    op.create_check_constraint(
        "ck_logistics_rate_card_scope_envelope",
        "logistics_rate_cards",
        "(scope_status = 'legacy_unbound' "
        "AND tenant_ref IS NULL AND entity_ref IS NULL AND store_ref IS NULL "
        "AND scope_grant_authority_sha256 IS NULL AND scope_as_of IS NULL) OR "
        "(scope_status = 'ready' "
        "AND tenant_ref IS NOT NULL AND length(tenant_ref) > 0 "
        "AND entity_ref IS NOT NULL AND length(entity_ref) > 0 "
        "AND store_ref IS NOT NULL AND length(store_ref) > 0 "
        "AND scope_grant_authority_sha256 IS NOT NULL "
        "AND scope_grant_authority_sha256 ~ '^[0-9a-f]{64}$' "
        "AND scope_as_of IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_logistics_calculation_scope_envelope",
        "logistics_calculations",
        "(scope_status = 'legacy_unbound' "
        "AND tenant_ref IS NULL AND entity_ref IS NULL AND store_ref IS NULL "
        "AND scope_grant_authority_sha256 IS NULL AND scope_as_of IS NULL) OR "
        "(scope_status = 'ready' "
        "AND tenant_ref IS NOT NULL AND length(tenant_ref) > 0 "
        "AND entity_ref IS NOT NULL AND length(entity_ref) > 0 "
        "AND store_ref IS NOT NULL AND length(store_ref) > 0 "
        "AND scope_grant_authority_sha256 IS NOT NULL "
        "AND scope_grant_authority_sha256 ~ '^[0-9a-f]{64}$' "
        "AND scope_as_of IS NOT NULL)",
    )

    op.drop_constraint(
        "logistics_rate_cards_rate_card_hash_key",
        "logistics_rate_cards",
        type_="unique",
    )
    op.drop_constraint(
        "uq_logistics_calculation_idempotency",
        "logistics_calculations",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_logistics_rate_card_scope_identity",
        "logistics_rate_cards",
        ["id", *SCOPE_COLUMNS],
    )
    op.create_unique_constraint(
        "uq_logistics_rate_card_exact_scope_hash",
        "logistics_rate_cards",
        [*SCOPE_COLUMNS, "rate_card_hash"],
    )
    op.create_unique_constraint(
        "uq_logistics_calculation_exact_scope_idempotency",
        "logistics_calculations",
        [*SCOPE_COLUMNS, "rate_card_id", "idempotency_key"],
    )
    op.create_foreign_key(
        "fk_logistics_calculation_exact_scope_rate_card",
        "logistics_calculations",
        "logistics_rate_cards",
        ["rate_card_id", *SCOPE_COLUMNS],
        ["id", *SCOPE_COLUMNS],
    )
    op.create_index(
        "ix_logistics_rate_card_exact_scope_route",
        "logistics_rate_cards",
        [*SCOPE_COLUMNS, "marketplace", "destination_country", "effective_at"],
    )
    op.create_index(
        "ix_logistics_calculation_exact_scope_latest",
        "logistics_calculations",
        [*SCOPE_COLUMNS, "calculated_at", "id"],
    )


def downgrade() -> None:
    # Revision 0088 cannot represent exact-scope duplicates without data loss.
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM logistics_rate_cards
                    GROUP BY rate_card_hash
                    HAVING count(*) > 1
                ) THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23505',
                        MESSAGE = 'Cannot downgrade 0089: exact-scope rate-card hashes cannot be represented by 0088';
                END IF;
                IF EXISTS (
                    SELECT 1
                    FROM logistics_calculations
                    GROUP BY rate_card_id, idempotency_key
                    HAVING count(*) > 1
                ) THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23505',
                        MESSAGE = 'Cannot downgrade 0089: exact-scope calculation keys cannot be represented by 0088';
                END IF;
            END
            $$;
            """
        )
    )
    op.drop_index(
        "ix_logistics_calculation_exact_scope_latest",
        table_name="logistics_calculations",
    )
    op.drop_index(
        "ix_logistics_rate_card_exact_scope_route",
        table_name="logistics_rate_cards",
    )
    op.drop_constraint(
        "fk_logistics_calculation_exact_scope_rate_card",
        "logistics_calculations",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_logistics_calculation_exact_scope_idempotency",
        "logistics_calculations",
        type_="unique",
    )
    op.drop_constraint(
        "uq_logistics_rate_card_exact_scope_hash",
        "logistics_rate_cards",
        type_="unique",
    )
    op.drop_constraint(
        "uq_logistics_rate_card_scope_identity",
        "logistics_rate_cards",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_logistics_calculation_idempotency",
        "logistics_calculations",
        ["rate_card_id", "idempotency_key"],
    )
    op.create_unique_constraint(
        "logistics_rate_cards_rate_card_hash_key",
        "logistics_rate_cards",
        ["rate_card_hash"],
    )
    op.drop_constraint(
        "ck_logistics_calculation_scope_envelope",
        "logistics_calculations",
        type_="check",
    )
    op.drop_constraint(
        "ck_logistics_rate_card_scope_envelope",
        "logistics_rate_cards",
        type_="check",
    )
    _drop_scope_columns("logistics_calculations")
    _drop_scope_columns("logistics_rate_cards")
