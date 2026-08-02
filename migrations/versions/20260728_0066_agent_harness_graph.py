"""Add append-only Agent Harness and canonical Graph authority."""

import sqlalchemy as sa
from alembic import op

revision = "20260728_0066"
down_revision = "20260728_0065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "graph_projects",
        sa.Column("id", sa.String(180), primary_key=True),
        sa.Column("tenant_ref", sa.String(160), nullable=False),
        sa.Column("entity_ref", sa.String(160), nullable=True),
        sa.Column("store_ref", sa.String(160), nullable=True),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("lifecycle", sa.String(40), nullable=False),
        sa.Column("baseline_sha256", sa.String(64), nullable=False),
        sa.Column("goal_contract_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_graph_projects_tenant_ref", "graph_projects", ["tenant_ref"])
    op.create_table(
        "verifier_registry",
        sa.Column("id", sa.String(180), primary_key=True),
        sa.Column("version", sa.String(80), primary_key=True),
        sa.Column("source_type", sa.String(80), nullable=False),
        sa.Column("authority", sa.String(80), nullable=False),
        sa.Column("success_states_json", sa.JSON(), nullable=False),
        sa.Column("freshness_seconds", sa.Integer(), nullable=False),
        sa.Column("contract_sha256", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("freshness_seconds > 0", name="ck_verifier_freshness_positive"),
    )
    op.create_table(
        "goal_contracts",
        sa.Column("id", sa.String(180), primary_key=True),
        sa.Column("project_id", sa.String(180), sa.ForeignKey("graph_projects.id"), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("constraints_json", sa.JSON(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "goal_tasks",
        sa.Column("id", sa.String(180), primary_key=True),
        sa.Column("project_id", sa.String(180), sa.ForeignKey("graph_projects.id"), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("owner", sa.String(160), nullable=False),
        sa.Column("verifier_id", sa.String(180), nullable=False),
        sa.Column("verifier_version", sa.String(80), nullable=False),
        sa.Column("dependency_ids_json", sa.JSON(), nullable=False),
        sa.Column("verification_condition", sa.Text(), nullable=False),
        sa.Column("next_safe_action", sa.Text(), nullable=False),
        sa.Column("workspace", sa.String(180), nullable=False),
        sa.Column("sla_seconds", sa.Integer(), nullable=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "fingerprint", name="uq_goal_task_fingerprint"),
    )
    op.create_table(
        "harness_observations",
        sa.Column("id", sa.String(180), primary_key=True),
        sa.Column("project_id", sa.String(180), sa.ForeignKey("graph_projects.id"), nullable=False),
        sa.Column("task_id", sa.String(180), sa.ForeignKey("goal_tasks.id"), nullable=True),
        sa.Column("verifier_id", sa.String(180), nullable=False),
        sa.Column("verifier_version", sa.String(80), nullable=False),
        sa.Column("source", sa.String(240), nullable=False),
        sa.Column("scope_json", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(40), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("result_sha256", sa.String(64), nullable=False),
        sa.Column("authority", sa.String(80), nullable=False),
        sa.Column("artifact_ref", sa.String(500), nullable=False),
        sa.Column("evidence_ref", sa.String(500), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fresh_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_by", sa.String(160), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "verifier_id", "verifier_version", "input_sha256", "result_sha256", name="uq_harness_observation_replay"),
    )
    op.create_index("ix_harness_observations_project_id", "harness_observations", ["project_id"])
    op.create_index("ix_harness_observations_task_id", "harness_observations", ["task_id"])
    op.create_index("ix_harness_observations_observed_at", "harness_observations", ["observed_at"])
    op.create_table(
        "graph_nodes",
        sa.Column("id", sa.String(180), primary_key=True),
        sa.Column("project_id", sa.String(180), sa.ForeignKey("graph_projects.id"), nullable=False),
        sa.Column("graph_kind", sa.String(40), nullable=False),
        sa.Column("stable_key", sa.String(300), nullable=False),
        sa.Column("node_type", sa.String(80), nullable=False),
        sa.Column("label", sa.String(300), nullable=False),
        sa.Column("authority", sa.String(80), nullable=False),
        sa.Column("source", sa.String(300), nullable=False),
        sa.Column("scope_json", sa.JSON(), nullable=False),
        sa.Column("version", sa.String(80), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("artifact_ref", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "graph_kind", "stable_key", name="uq_graph_node_stable_key"),
    )
    op.create_index("ix_graph_nodes_project_id", "graph_nodes", ["project_id"])
    op.create_index("ix_graph_nodes_graph_kind", "graph_nodes", ["graph_kind"])
    op.create_table(
        "graph_edges",
        sa.Column("id", sa.String(180), primary_key=True),
        sa.Column("project_id", sa.String(180), sa.ForeignKey("graph_projects.id"), nullable=False),
        sa.Column("graph_kind", sa.String(40), nullable=False),
        sa.Column("source_node_id", sa.String(180), sa.ForeignKey("graph_nodes.id"), nullable=False),
        sa.Column("target_node_id", sa.String(180), sa.ForeignKey("graph_nodes.id"), nullable=False),
        sa.Column("edge_type", sa.String(100), nullable=False),
        sa.Column("derivation_method", sa.String(40), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False),
        sa.Column("evidence_ref", sa.String(500), nullable=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 100", name="ck_graph_edge_confidence"),
        sa.UniqueConstraint("project_id", "graph_kind", "source_node_id", "edge_type", "target_node_id", name="uq_graph_edge_stable"),
    )
    op.create_index("ix_graph_edges_project_id", "graph_edges", ["project_id"])
    op.create_index("ix_graph_edges_graph_kind", "graph_edges", ["graph_kind"])


def downgrade() -> None:
    op.drop_table("graph_edges")
    op.drop_table("graph_nodes")
    op.drop_table("harness_observations")
    op.drop_table("goal_tasks")
    op.drop_table("goal_contracts")
    op.drop_table("verifier_registry")
    op.drop_table("graph_projects")
