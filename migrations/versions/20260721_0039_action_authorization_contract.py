"""Bind governed execution plans and commands to action authorization snapshots."""

import sqlalchemy as sa
from alembic import op

revision = "20260721_0039"
down_revision = "20260720_0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "governed_execution_plans",
        sa.Column("action_id", sa.String(), server_default="legacy_unmapped", nullable=False),
    )
    op.add_column(
        "governed_execution_plans",
        sa.Column(
            "action_policy_version",
            sa.String(),
            server_default="legacy_requires_reapproval",
            nullable=False,
        ),
    )
    op.add_column(
        "governed_execution_plans",
        sa.Column("risk_limits_json", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
    )
    op.add_column(
        "governed_execution_plans",
        sa.Column("risk_values_json", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
    )
    op.add_column(
        "governed_execution_plans",
        sa.Column("risk_currency", sa.String(length=3), nullable=True),
    )
    op.add_column(
        "governed_execution_plans",
        sa.Column("permit_ttl_seconds", sa.Integer(), nullable=True),
    )
    op.execute(
        """
        UPDATE governed_execution_plans
        SET action_id = CASE adapter_id
            WHEN 'ozon.listing.draft.v1' THEN 'listing_draft'
            WHEN 'ozon.product.import.v3' THEN 'listing_publish'
            ELSE 'legacy_unmapped'
        END
        """
    )

    op.add_column(
        "limited_execution_commands",
        sa.Column("action_id", sa.String(), server_default="legacy_unmapped", nullable=False),
    )
    op.add_column(
        "limited_execution_commands",
        sa.Column(
            "action_policy_version",
            sa.String(),
            server_default="legacy_requires_reapproval",
            nullable=False,
        ),
    )
    op.add_column(
        "limited_execution_commands",
        sa.Column("decision_hash", sa.String(length=64), server_default="0" * 64, nullable=False),
    )
    op.add_column(
        "limited_execution_commands",
        sa.Column(
            "authorization_hash",
            sa.String(length=64),
            server_default="0" * 64,
            nullable=False,
        ),
    )
    op.add_column(
        "limited_execution_commands",
        sa.Column(
            "permit_expires_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.add_column(
        "limited_execution_commands",
        sa.Column("risk_limits_json", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
    )
    op.add_column(
        "limited_execution_commands",
        sa.Column("risk_values_json", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
    )
    op.add_column(
        "limited_execution_commands",
        sa.Column("risk_currency", sa.String(length=3), nullable=True),
    )
    op.execute(
        """
        UPDATE limited_execution_commands AS command
        SET action_id = plan.action_id,
            action_policy_version = plan.action_policy_version,
            permit_expires_at = command.created_at
        FROM governed_execution_plans AS plan
        WHERE plan.id = command.plan_id
        """
    )

    for table_name, columns in (
        (
            "governed_execution_plans",
            ("action_id", "action_policy_version", "risk_limits_json", "risk_values_json"),
        ),
        (
            "limited_execution_commands",
            (
                "action_id",
                "action_policy_version",
                "decision_hash",
                "authorization_hash",
                "permit_expires_at",
                "risk_limits_json",
                "risk_values_json",
            ),
        ),
    ):
        for column_name in columns:
            op.alter_column(table_name, column_name, server_default=None)


def downgrade() -> None:
    for column_name in (
        "risk_currency",
        "risk_values_json",
        "risk_limits_json",
        "permit_expires_at",
        "authorization_hash",
        "decision_hash",
        "action_policy_version",
        "action_id",
    ):
        op.drop_column("limited_execution_commands", column_name)
    for column_name in (
        "permit_ttl_seconds",
        "risk_currency",
        "risk_values_json",
        "risk_limits_json",
        "action_policy_version",
        "action_id",
    ):
        op.drop_column("governed_execution_plans", column_name)
