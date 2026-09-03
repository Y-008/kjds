"""Add durable TeamAgent session-control task transitions.

Revision ID: 20260819_0102
Revises: 20260819_0101
Create Date: 2026-08-19
"""

from alembic import op

revision = "20260819_0102"
down_revision = "20260819_0101"
branch_labels = None
depends_on = None

EVENTS = "team_agent_orchestration_events"


def upgrade() -> None:
    op.drop_constraint("ck_team_agent_orchestration_event_shape", EVENTS, type_="check")
    op.create_check_constraint(
        "ck_team_agent_orchestration_event_shape",
        EVENTS,
        "task_revision >= 0 AND event_type IN "
        "('registered','claimed','heartbeat','released','completed',"
        "'failed','retry_wait','blocked','paused','resumed','expired')",
    )


def downgrade() -> None:
    op.execute(
        "SELECT pg_advisory_xact_lock("
        "hashtext('kjds-team-agent-session-task-controls-0102'))"
    )
    op.execute(f"LOCK TABLE {EVENTS} IN ACCESS EXCLUSIVE MODE")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM {EVENTS} WHERE event_type = 'resumed') THEN
                RAISE EXCEPTION USING ERRCODE = '55000',
                    MESSAGE = '0102 downgrade blocked: resumed TeamAgent tasks exist';
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
        "('registered','claimed','heartbeat','released','completed',"
        "'failed','retry_wait','blocked','paused','expired')",
    )
