"""Add preregistered causal experiments, assignments, observations, and SRM inputs."""

import sqlalchemy as sa
from alembic import op

revision = "20260717_0014"
down_revision = "20260717_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "causal_experiment_protocols",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("request_hash", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "resolution_id",
            sa.String(),
            sa.ForeignKey("decision_resolutions.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("hypothesis", sa.Text(), nullable=False),
        sa.Column("primary_metric", sa.String(), nullable=False),
        sa.Column("randomization_unit", sa.String(), nullable=False),
        sa.Column("interference_cluster", sa.String(), nullable=True),
        sa.Column("variants_json", sa.JSON(), nullable=False),
        sa.Column("target_sample_size", sa.Integer(), nullable=False),
        sa.Column("minimum_detectable_effect_decimal", sa.Numeric(38, 12), nullable=False),
        sa.Column("budget_cap_amount_decimal", sa.Numeric(38, 12), nullable=False),
        sa.Column("stop_loss_amount_decimal", sa.Numeric(38, 12), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome_window_days", sa.Integer(), nullable=False),
        sa.Column("guardrails_json", sa.JSON(), nullable=False),
        sa.Column("assignment_seed", sa.String(64), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "idx_causal_protocols_created",
        "causal_experiment_protocols",
        ["created_at"],
    )
    op.create_table(
        "causal_experiment_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("request_hash", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "protocol_id",
            sa.String(),
            sa.ForeignKey("causal_experiment_protocols.id"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "evidence_id",
            sa.String(),
            sa.ForeignKey("evidence_records.id"),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "protocol_id",
            "sequence",
            name="uq_causal_experiment_event_sequence",
        ),
    )
    op.create_index(
        "idx_causal_events_timeline",
        "causal_experiment_events",
        ["protocol_id", "sequence"],
    )
    op.create_table(
        "causal_experiment_assignments",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "protocol_id",
            sa.String(),
            sa.ForeignKey("causal_experiment_protocols.id"),
            nullable=False,
        ),
        sa.Column("unit_hash", sa.String(64), nullable=False),
        sa.Column("variant_id", sa.String(), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "protocol_id",
            "unit_hash",
            name="uq_causal_experiment_unit",
        ),
    )
    op.create_index(
        "idx_causal_assignments_variant",
        "causal_experiment_assignments",
        ["protocol_id", "variant_id"],
    )
    op.create_table(
        "causal_experiment_observations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("request_hash", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "protocol_id",
            sa.String(),
            sa.ForeignKey("causal_experiment_protocols.id"),
            nullable=False,
        ),
        sa.Column(
            "assignment_id",
            sa.String(),
            sa.ForeignKey("causal_experiment_assignments.id"),
            nullable=False,
        ),
        sa.Column("metric", sa.String(), nullable=False),
        sa.Column("value_decimal", sa.Numeric(38, 12), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "evidence_id",
            sa.String(),
            sa.ForeignKey("evidence_records.id"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "assignment_id",
            "metric",
            name="uq_causal_experiment_assignment_metric",
        ),
    )
    op.create_index(
        "idx_causal_observations_metric",
        "causal_experiment_observations",
        ["protocol_id", "metric", "observed_at"],
    )
    op.create_table(
        "causal_experiment_safety_checks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("request_hash", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "protocol_id",
            sa.String(),
            sa.ForeignKey("causal_experiment_protocols.id"),
            nullable=False,
        ),
        sa.Column("metric", sa.String(), nullable=False),
        sa.Column("value_decimal", sa.Numeric(38, 12), nullable=False),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("threshold_decimal", sa.Numeric(38, 12), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "evidence_id",
            sa.String(),
            sa.ForeignKey("evidence_records.id"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "idx_causal_safety_timeline",
        "causal_experiment_safety_checks",
        ["protocol_id", "observed_at"],
    )
    for table in (
        "causal_experiment_protocols",
        "causal_experiment_events",
        "causal_experiment_assignments",
        "causal_experiment_observations",
        "causal_experiment_safety_checks",
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
    op.drop_index(
        "idx_causal_safety_timeline",
        table_name="causal_experiment_safety_checks",
    )
    op.drop_table("causal_experiment_safety_checks")
    op.drop_index(
        "idx_causal_observations_metric",
        table_name="causal_experiment_observations",
    )
    op.drop_table("causal_experiment_observations")
    op.drop_index(
        "idx_causal_assignments_variant",
        table_name="causal_experiment_assignments",
    )
    op.drop_table("causal_experiment_assignments")
    op.drop_index(
        "idx_causal_events_timeline",
        table_name="causal_experiment_events",
    )
    op.drop_table("causal_experiment_events")
    op.drop_index(
        "idx_causal_protocols_created",
        table_name="causal_experiment_protocols",
    )
    op.drop_table("causal_experiment_protocols")
