"""Add explicit resource, provider, model and token dimensions to usage ledger."""

import sqlalchemy as sa
from alembic import op

revision = "20260906_0109"
down_revision = "20260906_0108"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("skill_usage_events", sa.Column("resource_type", sa.String(length=80), nullable=True))
    op.add_column("skill_usage_events", sa.Column("provider_ref", sa.String(length=160), nullable=True))
    op.add_column("skill_usage_events", sa.Column("model_ref", sa.String(length=200), nullable=True))
    op.add_column("skill_usage_events", sa.Column("cost_center", sa.String(length=160), nullable=True))
    op.add_column("skill_usage_events", sa.Column("input_units", sa.Numeric(38, 18), nullable=True))
    op.add_column("skill_usage_events", sa.Column("output_units", sa.Numeric(38, 18), nullable=True))
    op.execute(sa.text("UPDATE skill_usage_events SET resource_type = 'skill' WHERE resource_type IS NULL"))
    op.alter_column("skill_usage_events", "resource_type", nullable=False, server_default="skill")
    op.create_check_constraint("ck_skill_usage_input_units_nonnegative", "skill_usage_events", "input_units IS NULL OR input_units >= 0")
    op.create_check_constraint("ck_skill_usage_output_units_nonnegative", "skill_usage_events", "output_units IS NULL OR output_units >= 0")


def downgrade() -> None:
    op.drop_constraint("ck_skill_usage_output_units_nonnegative", "skill_usage_events", type_="check")
    op.drop_constraint("ck_skill_usage_input_units_nonnegative", "skill_usage_events", type_="check")
    op.drop_column("skill_usage_events", "output_units")
    op.drop_column("skill_usage_events", "input_units")
    op.drop_column("skill_usage_events", "cost_center")
    op.drop_column("skill_usage_events", "model_ref")
    op.drop_column("skill_usage_events", "provider_ref")
    op.drop_column("skill_usage_events", "resource_type")
