"""Add complete exact-scope FX evidence metadata.

Revision ID: 20260802_0087
Revises: 20260802_0086
Create Date: 2026-08-02
"""

import sqlalchemy as sa
from alembic import op

revision = "20260802_0087"
down_revision = "20260802_0086"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "fx_rates",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "fx_rates",
        sa.Column("source_type", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "fx_rates",
        sa.Column("authority", sa.String(length=300), nullable=True),
    )
    op.add_column(
        "fx_rates",
        sa.Column("purposes_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "fx_rates",
        sa.Column("intake_content_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "fx_rates",
        sa.Column("idempotency_key", sa.String(length=180), nullable=True),
    )
    op.create_check_constraint(
        "ck_fx_rates_complete_intake_metadata",
        "fx_rates",
        "(expires_at IS NULL AND source_type IS NULL AND authority IS NULL "
        "AND purposes_json IS NULL AND intake_content_sha256 IS NULL "
        "AND idempotency_key IS NULL) OR "
        "(expires_at IS NOT NULL AND expires_at > effective_at "
        "AND source_type IS NOT NULL AND length(source_type) > 0 "
        "AND authority IS NOT NULL AND length(authority) > 0 "
        "AND purposes_json IS NOT NULL "
        "AND intake_content_sha256 IS NOT NULL "
        "AND length(intake_content_sha256) = 64 "
        "AND idempotency_key IS NOT NULL AND length(idempotency_key) > 0)",
    )
    op.create_index(
        "uq_fx_rate_scoped_intake_idempotency",
        "fx_rates",
        ["tenant_ref", "entity_ref", "store_ref", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text(
            "tenant_ref IS NOT NULL AND idempotency_key IS NOT NULL"
        ),
        sqlite_where=sa.text(
            "tenant_ref IS NOT NULL AND idempotency_key IS NOT NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_fx_rate_scoped_intake_idempotency",
        table_name="fx_rates",
    )
    op.drop_constraint(
        "ck_fx_rates_complete_intake_metadata",
        "fx_rates",
        type_="check",
    )
    op.drop_column("fx_rates", "idempotency_key")
    op.drop_column("fx_rates", "intake_content_sha256")
    op.drop_column("fx_rates", "purposes_json")
    op.drop_column("fx_rates", "authority")
    op.drop_column("fx_rates", "source_type")
    op.drop_column("fx_rates", "expires_at")
