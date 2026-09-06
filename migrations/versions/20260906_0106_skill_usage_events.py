"""Persist immutable AI skill and generated-media usage events."""

import sqlalchemy as sa
from alembic import op

revision = "20260906_0106"
down_revision = "20260906_0105"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skill_usage_events",
        sa.Column("event_id", sa.String(length=200), primary_key=True),
        sa.Column("idempotency_key", sa.String(length=300), nullable=False),
        sa.Column("tenant_id", sa.String(length=160), nullable=False),
        sa.Column("customer_id", sa.String(length=200), nullable=False),
        sa.Column("skill_id", sa.String(length=200), nullable=False),
        sa.Column("units", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("unit_cost", sa.Numeric(precision=38, scale=18), nullable=False),
        # Numeric values are convenient for bounded SQL reporting; the text
        # mirrors preserve the exact Decimal exponent used for invoicing.
        sa.Column("units_text", sa.String(length=100), nullable=False),
        sa.Column("unit_cost_text", sa.String(length=100), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("asset_ref", sa.String(length=300), nullable=True),
        sa.Column("fingerprint_sha256", sa.String(length=64), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_skill_usage_tenant_idempotency",
        ),
        sa.CheckConstraint(
            "units >= 0", name="ck_skill_usage_units_nonnegative"
        ),
        sa.CheckConstraint(
            "unit_cost >= 0", name="ck_skill_usage_unit_cost_nonnegative"
        ),
        sa.CheckConstraint(
            "length(currency) = 3", name="ck_skill_usage_currency_shape"
        ),
    )
    op.create_index(
        "ix_skill_usage_scope_occurred",
        "skill_usage_events",
        ["tenant_id", "customer_id", "occurred_at", "event_id"],
    )
    op.create_index(
        "ix_skill_usage_skill_occurred",
        "skill_usage_events",
        ["tenant_id", "skill_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_skill_usage_skill_occurred", table_name="skill_usage_events"
    )
    op.drop_index(
        "ix_skill_usage_scope_occurred", table_name="skill_usage_events"
    )
    op.drop_table("skill_usage_events")
