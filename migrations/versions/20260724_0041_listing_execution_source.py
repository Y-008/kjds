"""Bind governed execution plans to immutable causal or listing sources."""

import sqlalchemy as sa
from alembic import op

revision = "20260724_0041"
down_revision = "20260721_0040"
branch_labels = None
depends_on = None

SOURCE_CHECK = """
(
    source_kind = 'causal_policy_handoff'
    AND source_id = handoff_id
    AND handoff_id IS NOT NULL
    AND policy_id IS NOT NULL
    AND release_id IS NOT NULL
)
OR
(
    source_kind = 'approved_listing_draft'
    AND handoff_id IS NULL
    AND policy_id IS NULL
    AND release_id IS NULL
)
"""


def upgrade() -> None:
    op.add_column("governed_execution_plans", sa.Column("source_kind", sa.String(), nullable=True))
    op.add_column("governed_execution_plans", sa.Column("source_id", sa.String(), nullable=True))
    op.add_column("governed_execution_plans", sa.Column("source_approval_id", sa.String(), nullable=True))
    op.add_column(
        "governed_execution_plans",
        sa.Column("source_snapshot_hash", sa.String(length=64), nullable=True),
    )
    op.execute(
        """
        UPDATE governed_execution_plans AS plan
        SET source_kind = 'causal_policy_handoff',
            source_id = plan.handoff_id,
            source_approval_id = handoff.approval_id,
            source_snapshot_hash = handoff.policy_snapshot_hash
        FROM causal_policy_activation_handoffs AS handoff
        WHERE handoff.id = plan.handoff_id
        """
    )
    op.alter_column("governed_execution_plans", "source_kind", nullable=False)
    op.alter_column("governed_execution_plans", "source_id", nullable=False)
    op.alter_column("governed_execution_plans", "source_approval_id", nullable=False)
    op.alter_column("governed_execution_plans", "source_snapshot_hash", nullable=False)
    op.alter_column("governed_execution_plans", "handoff_id", nullable=True)
    op.alter_column("governed_execution_plans", "policy_id", nullable=True)
    op.alter_column("governed_execution_plans", "release_id", nullable=True)
    op.create_foreign_key(
        "fk_execution_plan_source_approval",
        "governed_execution_plans",
        "approvals",
        ["source_approval_id"],
        ["id"],
    )
    op.create_check_constraint(
        "ck_execution_plan_source_fields",
        "governed_execution_plans",
        "char_length(source_kind) > 0 "
        "AND char_length(source_id) > 0 "
        "AND char_length(source_approval_id) > 0 "
        "AND char_length(source_snapshot_hash) = 64",
    )
    op.create_check_constraint(
        "ck_execution_plan_source_variant",
        "governed_execution_plans",
        SOURCE_CHECK,
    )
    op.create_unique_constraint(
        "uq_execution_plan_source_key",
        "governed_execution_plans",
        ["source_kind", "source_id", "idempotency_key"],
    )
    op.create_index(
        "uq_execution_evidence_source_ref",
        "evidence_records",
        ["source", "source_ref"],
        unique=True,
        postgresql_where=sa.text("source = 'ozon-isolated-execution-worker'"),
    )


def downgrade() -> None:
    connection = op.get_bind()
    listing_count = connection.execute(
        sa.text(
            "SELECT count(*) FROM governed_execution_plans "
            "WHERE source_kind = 'approved_listing_draft'"
        )
    ).scalar_one()
    if listing_count:
        raise RuntimeError(
            "Cannot downgrade while approved-listing execution plans exist; "
            "export or remove those feature rows explicitly first"
        )
    op.drop_index(
        "uq_execution_evidence_source_ref",
        table_name="evidence_records",
    )
    op.drop_constraint(
        "uq_execution_plan_source_key",
        "governed_execution_plans",
        type_="unique",
    )
    op.drop_constraint(
        "ck_execution_plan_source_variant",
        "governed_execution_plans",
        type_="check",
    )
    op.drop_constraint(
        "ck_execution_plan_source_fields",
        "governed_execution_plans",
        type_="check",
    )
    op.drop_constraint(
        "fk_execution_plan_source_approval",
        "governed_execution_plans",
        type_="foreignkey",
    )
    op.alter_column("governed_execution_plans", "release_id", nullable=False)
    op.alter_column("governed_execution_plans", "policy_id", nullable=False)
    op.alter_column("governed_execution_plans", "handoff_id", nullable=False)
    op.drop_column("governed_execution_plans", "source_snapshot_hash")
    op.drop_column("governed_execution_plans", "source_approval_id")
    op.drop_column("governed_execution_plans", "source_id")
    op.drop_column("governed_execution_plans", "source_kind")
