"""Add immutable interaction-mode decision contracts."""

import sqlalchemy as sa
from alembic import op

revision = "20260717_0012"
down_revision = "20260716_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "decision_contracts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("request_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("profile_id", sa.String(), nullable=False),
        sa.Column("profile_version", sa.String(), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("decision_domain", sa.String(), nullable=False),
        sa.Column("risk_level", sa.String(), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=True),
        sa.Column("maximum_loss_amount", sa.Numeric(24, 8), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column(
            "source_contract_id",
            sa.String(),
            sa.ForeignKey("decision_contracts.id"),
            nullable=True,
        ),
        sa.Column("input_json", sa.JSON(), nullable=False),
        sa.Column("output_requirements_json", sa.JSON(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("compiler_policy_json", sa.JSON(), nullable=False),
        sa.Column("missing_inputs_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("execution_eligible", sa.Boolean(), nullable=False),
        sa.Column("requires_human_approval", sa.Boolean(), nullable=False),
        sa.Column("requested_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "idx_decision_contracts_created",
        "decision_contracts",
        ["created_at"],
    )
    op.create_index(
        "idx_decision_contracts_domain_status",
        "decision_contracts",
        ["decision_domain", "status"],
    )
    op.execute(sa.text('ALTER TABLE "decision_contracts" ENABLE ROW LEVEL SECURITY'))
    op.execute(
        sa.text(
            'CREATE TRIGGER "trg_decision_contracts_immutable" '
            'BEFORE UPDATE OR DELETE ON "decision_contracts" '
            "FOR EACH ROW EXECUTE FUNCTION kjds_prevent_ledger_mutation()"
        )
    )


def downgrade() -> None:
    op.drop_index("idx_decision_contracts_domain_status", table_name="decision_contracts")
    op.drop_index("idx_decision_contracts_created", table_name="decision_contracts")
    op.drop_table("decision_contracts")
