"""Add append-only decision analysis, review, resolution, and outcome ledgers."""

import sqlalchemy as sa
from alembic import op

revision = "20260717_0013"
down_revision = "20260717_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "decision_analyses",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("request_hash", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "contract_id",
            sa.String(),
            sa.ForeignKey("decision_contracts.id"),
            nullable=False,
        ),
        sa.Column("conclusion", sa.Text(), nullable=False),
        sa.Column("recommended_option_id", sa.String(), nullable=True),
        sa.Column("confidence_decimal", sa.Numeric(8, 7), nullable=False),
        sa.Column("forecast_metric", sa.String(), nullable=True),
        sa.Column("forecast_value_decimal", sa.Numeric(38, 12), nullable=True),
        sa.Column("forecast_low_decimal", sa.Numeric(38, 12), nullable=True),
        sa.Column("forecast_high_decimal", sa.Numeric(38, 12), nullable=True),
        sa.Column("forecast_unit", sa.String(), nullable=True),
        sa.Column("forecast_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("assumptions_json", sa.JSON(), nullable=False),
        sa.Column("unknowns_json", sa.JSON(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("model_ref", sa.String(), nullable=True),
        sa.Column("submitted_by", sa.String(), nullable=False),
        sa.Column("execution_eligible", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "idx_decision_analyses_contract",
        "decision_analyses",
        ["contract_id", "created_at"],
    )
    op.create_table(
        "decision_analysis_reviews",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("request_hash", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "analysis_id",
            sa.String(),
            sa.ForeignKey("decision_analyses.id"),
            nullable=False,
        ),
        sa.Column("verdict", sa.String(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("counterarguments_json", sa.JSON(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("reviewed_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "analysis_id",
            "reviewed_by",
            name="uq_decision_analysis_reviewer",
        ),
    )
    op.create_index(
        "idx_decision_reviews_analysis",
        "decision_analysis_reviews",
        ["analysis_id", "created_at"],
    )
    op.create_table(
        "decision_resolutions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("request_hash", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "contract_id",
            sa.String(),
            sa.ForeignKey("decision_contracts.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "analysis_id",
            sa.String(),
            sa.ForeignKey("decision_analyses.id"),
            nullable=False,
        ),
        sa.Column("disposition", sa.String(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("conditions_json", sa.JSON(), nullable=False),
        sa.Column("decided_by", sa.String(), nullable=False),
        sa.Column("execution_eligible", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "idx_decision_resolutions_created",
        "decision_resolutions",
        ["created_at"],
    )
    op.create_table(
        "decision_outcomes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("request_hash", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "resolution_id",
            sa.String(),
            sa.ForeignKey("decision_resolutions.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("metric", sa.String(), nullable=False),
        sa.Column("predicted_value_decimal", sa.Numeric(38, 12), nullable=False),
        sa.Column("interval_low_decimal", sa.Numeric(38, 12), nullable=False),
        sa.Column("interval_high_decimal", sa.Numeric(38, 12), nullable=False),
        sa.Column("actual_value_decimal", sa.Numeric(38, 12), nullable=False),
        sa.Column("unit", sa.String(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("recorded_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "idx_decision_outcomes_metric",
        "decision_outcomes",
        ["metric", "unit", "observed_at"],
    )
    for table in (
        "decision_analyses",
        "decision_analysis_reviews",
        "decision_resolutions",
        "decision_outcomes",
    ):
        op.execute(sa.text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
        op.execute(
            sa.text(
                f'CREATE TRIGGER "trg_{table}_immutable" '
                f'BEFORE UPDATE OR DELETE ON "{table}" '
                "FOR EACH ROW EXECUTE FUNCTION kjds_prevent_ledger_mutation()"
            )
        )


def downgrade() -> None:
    op.drop_index("idx_decision_outcomes_metric", table_name="decision_outcomes")
    op.drop_table("decision_outcomes")
    op.drop_index(
        "idx_decision_resolutions_created",
        table_name="decision_resolutions",
    )
    op.drop_table("decision_resolutions")
    op.drop_index(
        "idx_decision_reviews_analysis",
        table_name="decision_analysis_reviews",
    )
    op.drop_table("decision_analysis_reviews")
    op.drop_index("idx_decision_analyses_contract", table_name="decision_analyses")
    op.drop_table("decision_analyses")
