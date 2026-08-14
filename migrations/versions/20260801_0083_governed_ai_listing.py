"""Add governed Agent inference and internal AI Listing dry-run state.

Revision ID: 20260801_0083
Revises: 20260801_0082
Create Date: 2026-08-01
"""

import sqlalchemy as sa
from alembic import op

revision = "20260801_0083"
down_revision = "20260801_0082"
branch_labels = None
depends_on = None

AI_LISTING_STATES = (
    "queued",
    "capture_locked",
    "product_proposed",
    "evidence_review_required",
    "taxonomy_ready",
    "economics_ready",
    "content_ready",
    "media_running",
    "media_review_required",
    "listing_plan_ready",
    "listing_draft_created",
    "listing_approved",
    "dry_run_passed",
    "blocked",
    "failed",
    "cancelled",
)


def upgrade() -> None:
    op.drop_constraint(
        "ck_browser_capture_contract_profile",
        "browser_capture_inbox_submissions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_browser_capture_contract_profile",
        "browser_capture_inbox_submissions",
        "contract_version IN ("
        "'kjds-browser-capture-envelope/1.0',"
        "'kjds-browser-capture-envelope/1.1'"
        ") AND source_profile = 'browser_observation' "
        "AND marketplace IN ('1688','ozon')",
    )

    op.create_table(
        "ai_listing_runs",
        sa.Column("id", sa.String(length=180), nullable=False),
        sa.Column("tenant_ref", sa.String(length=160), nullable=False),
        sa.Column("entity_ref", sa.String(length=160), nullable=False),
        sa.Column("store_ref", sa.String(length=160), nullable=False),
        sa.Column("scope_grant_authority_sha256", sa.String(length=64), nullable=False),
        sa.Column("capture_submission_id", sa.String(length=180), nullable=False),
        sa.Column("capture_evidence_id", sa.String(length=180), nullable=False),
        sa.Column("capture_request_sha256", sa.String(length=64), nullable=False),
        sa.Column("selected_variant_key", sa.String(length=500), nullable=False),
        sa.Column("target_marketplace", sa.String(length=40), nullable=False),
        sa.Column("target_locale", sa.String(length=20), nullable=False),
        sa.Column("mode", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("current_stage", sa.String(length=50), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("selected_item_json", sa.JSON(), nullable=False),
        sa.Column("bindings_json", sa.JSON(), nullable=False),
        sa.Column("artifact_ids_json", sa.JSON(), nullable=False),
        sa.Column("internal_refs_json", sa.JSON(), nullable=False),
        sa.Column("blockers_json", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("requested_by", sa.String(length=240), nullable=False),
        sa.Column("work_requested", sa.Boolean(), nullable=False),
        sa.Column("lease_owner", sa.String(length=240), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=160), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN (" + ",".join(f"'{item}'" for item in AI_LISTING_STATES) + ")",
            name="ck_ai_listing_status",
        ),
        sa.CheckConstraint(
            "target_marketplace = 'ozon' AND target_locale = 'ru-RU' "
            "AND mode = 'internal_dry_run'",
            name="ck_ai_listing_target_mode",
        ),
        sa.CheckConstraint(
            "length(scope_grant_authority_sha256) = 64 "
            "AND length(input_snapshot_sha256) = 64 "
            "AND length(capture_request_sha256) = 64 "
            "AND length(request_sha256) = 64",
            name="ck_ai_listing_hashes",
        ),
        sa.CheckConstraint(
            "length(tenant_ref) > 0 AND length(entity_ref) > 0 "
            "AND length(store_ref) > 0 AND length(capture_submission_id) > 0 "
            "AND length(capture_evidence_id) > 0 AND length(selected_variant_key) > 0",
            name="ck_ai_listing_scope_complete",
        ),
        sa.ForeignKeyConstraint(
            ["capture_submission_id"], ["browser_capture_inbox_submissions.id"]
        ),
        sa.ForeignKeyConstraint(["capture_evidence_id"], ["evidence_records.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "idempotency_key",
            name="uq_ai_listing_scope_idempotency",
        ),
    )
    op.create_index(
        "ix_ai_listing_scope_created",
        "ai_listing_runs",
        ["tenant_ref", "entity_ref", "store_ref", "created_at"],
    )
    op.create_index(
        "ix_ai_listing_worker",
        "ai_listing_runs",
        ["work_requested", "lease_until", "updated_at"],
    )

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(length=180), nullable=False),
        sa.Column("ai_listing_run_id", sa.String(length=180), nullable=True),
        sa.Column("tenant_ref", sa.String(length=160), nullable=False),
        sa.Column("entity_ref", sa.String(length=160), nullable=False),
        sa.Column("store_ref", sa.String(length=160), nullable=False),
        sa.Column("task_type", sa.String(length=160), nullable=False),
        sa.Column("contract_version", sa.String(length=80), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("model", sa.String(length=240), nullable=False),
        sa.Column("prompt_version", sa.String(length=160), nullable=False),
        sa.Column("prompt_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("input_snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("provider_config_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("fallback_reason", sa.String(length=160), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(18, 8), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("lease_owner", sa.String(length=240), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_response_evidence_id", sa.String(), nullable=True),
        sa.Column("provider_request_id", sa.String(length=240), nullable=True),
        sa.Column("error_code", sa.String(length=160), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("attempt BETWEEN 1 AND 2", name="ck_agent_run_attempt"),
        sa.CheckConstraint(
            "status IN ('calling','completed','failed','unknown_outcome','cancelled')",
            name="ck_agent_run_status",
        ),
        sa.CheckConstraint(
            "length(input_snapshot_sha256) = 64 "
            "AND length(provider_config_sha256) = 64",
            name="ck_agent_run_hashes",
        ),
        sa.ForeignKeyConstraint(["ai_listing_run_id"], ["ai_listing_runs.id"]),
        sa.ForeignKeyConstraint(["raw_response_evidence_id"], ["evidence_records.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "ai_listing_run_id",
            "task_type",
            "input_snapshot_sha256",
            "attempt",
            name="uq_agent_run_task_attempt",
        ),
    )
    op.create_index(
        "ix_agent_run_listing_task",
        "agent_runs",
        ["ai_listing_run_id", "task_type", "started_at"],
    )

    op.create_table(
        "agent_artifacts",
        sa.Column("id", sa.String(length=180), nullable=False),
        sa.Column("agent_run_id", sa.String(length=180), nullable=False),
        sa.Column("ai_listing_run_id", sa.String(length=180), nullable=True),
        sa.Column("supersedes_artifact_id", sa.String(length=180), nullable=True),
        sa.Column("task_type", sa.String(length=160), nullable=False),
        sa.Column("contract_version", sa.String(length=80), nullable=False),
        sa.Column("schema_version", sa.String(length=160), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("output_json", sa.JSON(), nullable=False),
        sa.Column("output_sha256", sa.String(length=64), nullable=False),
        sa.Column("input_snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=160), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("model", sa.String(length=240), nullable=False),
        sa.Column("provider_config_sha256", sa.String(length=64), nullable=False),
        sa.Column("field_evidence_json", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Numeric(8, 6), nullable=False),
        sa.Column("unknowns_json", sa.JSON(), nullable=False),
        sa.Column("warnings_json", sa.JSON(), nullable=False),
        sa.Column("raw_response_evidence_id", sa.String(), nullable=False),
        sa.Column("quality_feedback_json", sa.JSON(), nullable=False),
        sa.Column("proposal_only", sa.Boolean(), nullable=False),
        sa.Column("formal_fact", sa.Boolean(), nullable=False),
        sa.Column("external_write_allowed", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(length=240), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_agent_artifact_version"),
        sa.CheckConstraint(
            "length(output_sha256) = 64 "
            "AND length(input_snapshot_sha256) = 64 "
            "AND length(provider_config_sha256) = 64",
            name="ck_agent_artifact_hashes",
        ),
        sa.CheckConstraint(
            "proposal_only IS TRUE AND formal_fact IS FALSE "
            "AND external_write_allowed IS FALSE",
            name="ck_agent_artifact_authority",
        ),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"]),
        sa.ForeignKeyConstraint(["ai_listing_run_id"], ["ai_listing_runs.id"]),
        sa.ForeignKeyConstraint(["supersedes_artifact_id"], ["agent_artifacts.id"]),
        sa.ForeignKeyConstraint(["raw_response_evidence_id"], ["evidence_records.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_run_id", "version", name="uq_agent_artifact_version"),
    )
    op.create_index(
        "ix_agent_artifact_listing_task",
        "agent_artifacts",
        ["ai_listing_run_id", "task_type", "created_at"],
    )

    op.create_table(
        "agent_run_events",
        sa.Column("id", sa.String(length=180), nullable=False),
        sa.Column("ai_listing_run_id", sa.String(length=180), nullable=True),
        sa.Column("agent_run_id", sa.String(length=180), nullable=True),
        sa.Column("event_type", sa.String(length=160), nullable=False),
        sa.Column("state", sa.String(length=80), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("actor_id", sa.String(length=240), nullable=False),
        sa.Column("idempotency_key", sa.String(length=300), nullable=False),
        sa.Column("event_sha256", sa.String(length=64), nullable=False),
        sa.Column("outbox_event_id", sa.String(length=180), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(event_sha256) = 64", name="ck_agent_run_event_hash"),
        sa.ForeignKeyConstraint(["ai_listing_run_id"], ["ai_listing_runs.id"]),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"]),
        sa.ForeignKeyConstraint(["outbox_event_id"], ["outbox_events.event_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "ai_listing_run_id",
            "idempotency_key",
            name="uq_agent_run_event_idempotency",
        ),
    )
    op.create_index(
        "ix_agent_run_event_listing",
        "agent_run_events",
        ["ai_listing_run_id", "occurred_at", "id"],
    )

    for table in ("agent_artifacts", "agent_run_events"):
        op.execute(
            f'CREATE TRIGGER "trg_{table}_immutable" BEFORE UPDATE OR DELETE ON "{table}" '
            "FOR EACH ROW EXECUTE FUNCTION kjds_prevent_ledger_mutation()"
        )


def downgrade() -> None:
    for table in ("agent_run_events", "agent_artifacts"):
        op.execute(f'DROP TRIGGER IF EXISTS "trg_{table}_immutable" ON "{table}"')
    op.drop_index("ix_agent_run_event_listing", table_name="agent_run_events")
    op.drop_table("agent_run_events")
    op.drop_index("ix_agent_artifact_listing_task", table_name="agent_artifacts")
    op.drop_table("agent_artifacts")
    op.drop_index("ix_agent_run_listing_task", table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_index("ix_ai_listing_worker", table_name="ai_listing_runs")
    op.drop_index("ix_ai_listing_scope_created", table_name="ai_listing_runs")
    op.drop_table("ai_listing_runs")

    op.drop_constraint(
        "ck_browser_capture_contract_profile",
        "browser_capture_inbox_submissions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_browser_capture_contract_profile",
        "browser_capture_inbox_submissions",
        "contract_version = 'kjds-browser-capture-envelope/1.0' "
        "AND source_profile = 'browser_observation' "
        "AND marketplace IN ('1688','ozon')",
    )
