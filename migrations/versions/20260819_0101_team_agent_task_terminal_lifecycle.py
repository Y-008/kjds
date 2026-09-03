"""Add durable TeamAgent terminal lifecycle metadata and events.

Revision ID: 20260819_0101
Revises: 20260819_0100
Create Date: 2026-08-19
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260819_0101"
down_revision = "20260819_0100"
branch_labels = None
depends_on = None

TASKS = "team_agent_orchestration_tasks"
EVENTS = "team_agent_orchestration_events"
TERMINAL_EVENT_TYPES = (
    "completed",
    "failed",
    "retry_wait",
    "blocked",
    "paused",
    "expired",
)


def upgrade() -> None:
    op.add_column(TASKS, sa.Column("retry_after_seconds", sa.Float(), nullable=True))
    op.add_column(TASKS, sa.Column("reviewer_id", sa.String(240), nullable=True))
    op.add_column(
        TASKS,
        sa.Column(
            "result_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        TASKS,
        sa.Column(
            "evidence_refs_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(TASKS, sa.Column("failure_code", sa.String(120), nullable=True))
    op.add_column(TASKS, sa.Column("failure_kind", sa.String(120), nullable=True))
    op.add_column(TASKS, sa.Column("blocked_reason", sa.String(500), nullable=True))
    op.add_column(TASKS, sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(TASKS, sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True))
    op.alter_column(TASKS, "evidence_refs_json", server_default=None)

    op.create_check_constraint(
        "ck_team_agent_orchestration_result",
        TASKS,
        "(result_json IS NULL OR jsonb_typeof(result_json) = 'object') AND "
        "(result_json IS NULL OR octet_length(result_json::text) <= 65536)",
    )
    op.create_check_constraint(
        "ck_team_agent_orchestration_evidence_refs",
        TASKS,
        "jsonb_typeof(evidence_refs_json) = 'array' AND "
        "jsonb_array_length(evidence_refs_json) <= 50 AND "
        "octet_length(evidence_refs_json::text) <= 65536",
    )
    op.create_check_constraint(
        "ck_team_agent_orchestration_retry_after",
        TASKS,
        "retry_after_seconds IS NULL OR "
        "(retry_after_seconds >= 0 AND retry_after_seconds <= 30)",
    )
    op.create_check_constraint(
        "ck_team_agent_orchestration_completed_shape",
        TASKS,
        "(state = 'completed' AND completed_at IS NOT NULL AND result_json IS NOT NULL) OR "
        "(state <> 'completed' AND completed_at IS NULL)",
    )
    op.create_check_constraint(
        "ck_team_agent_orchestration_expired_shape",
        TASKS,
        "(state = 'expired' AND expired_at IS NOT NULL) OR "
        "(state <> 'expired' AND expired_at IS NULL)",
    )

    op.drop_constraint("ck_team_agent_orchestration_time_order", TASKS, type_="check")
    op.create_check_constraint(
        "ck_team_agent_orchestration_time_order",
        TASKS,
        "updated_at >= created_at AND "
        "(completed_at IS NULL OR completed_at >= created_at) AND "
        "(expired_at IS NULL OR expired_at >= created_at) AND "
        "(lease_expires_at IS NULL OR lease_expires_at > updated_at)",
    )

    op.drop_constraint("ck_team_agent_orchestration_event_shape", EVENTS, type_="check")
    op.create_check_constraint(
        "ck_team_agent_orchestration_event_shape",
        EVENTS,
        "task_revision >= 0 AND event_type IN "
        "('registered','claimed','heartbeat','released','completed',"
        "'failed','retry_wait','blocked','paused','expired')",
    )


def downgrade() -> None:
    op.execute(
        "SELECT pg_advisory_xact_lock("
        "hashtext('kjds-team-agent-orchestration-0101'))"
    )
    op.execute(f"LOCK TABLE {TASKS}, {EVENTS} IN ACCESS EXCLUSIVE MODE")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                  FROM {EVENTS}
                 WHERE event_type IN ('completed','failed','retry_wait','blocked','paused','expired')
            ) OR EXISTS (
                SELECT 1
                  FROM {TASKS}
                 WHERE retry_after_seconds IS NOT NULL
                    OR reviewer_id IS NOT NULL
                    OR result_json IS NOT NULL
                    OR evidence_refs_json <> '[]'::jsonb
                    OR failure_code IS NOT NULL
                    OR failure_kind IS NOT NULL
                    OR blocked_reason IS NOT NULL
                    OR completed_at IS NOT NULL
                    OR expired_at IS NOT NULL
            ) THEN
                RAISE EXCEPTION USING ERRCODE = '55000',
                    MESSAGE = '0101 downgrade blocked: TeamAgent terminal durable state exists';
            END IF;
        END;
        $$;
        """
    )

    op.drop_constraint("ck_team_agent_orchestration_event_shape", EVENTS, type_="check")
    op.create_check_constraint(
        "ck_team_agent_orchestration_event_shape",
        EVENTS,
        "task_revision >= 0 AND event_type IN "
        "('registered','claimed','heartbeat','released')",
    )

    op.drop_constraint("ck_team_agent_orchestration_time_order", TASKS, type_="check")
    op.create_check_constraint(
        "ck_team_agent_orchestration_time_order",
        TASKS,
        "updated_at >= created_at AND "
        "(lease_expires_at IS NULL OR lease_expires_at > updated_at)",
    )
    op.drop_constraint("ck_team_agent_orchestration_expired_shape", TASKS, type_="check")
    op.drop_constraint("ck_team_agent_orchestration_completed_shape", TASKS, type_="check")
    op.drop_constraint("ck_team_agent_orchestration_retry_after", TASKS, type_="check")
    op.drop_constraint("ck_team_agent_orchestration_evidence_refs", TASKS, type_="check")
    op.drop_constraint("ck_team_agent_orchestration_result", TASKS, type_="check")

    op.drop_column(TASKS, "expired_at")
    op.drop_column(TASKS, "completed_at")
    op.drop_column(TASKS, "blocked_reason")
    op.drop_column(TASKS, "failure_kind")
    op.drop_column(TASKS, "failure_code")
    op.drop_column(TASKS, "evidence_refs_json")
    op.drop_column(TASKS, "result_json")
    op.drop_column(TASKS, "reviewer_id")
    op.drop_column(TASKS, "retry_after_seconds")
