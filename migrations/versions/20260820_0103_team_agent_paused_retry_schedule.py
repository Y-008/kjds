"""Persist retry schedule while a TeamAgent task is paused.

Revision ID: 20260820_0103
Revises: 20260819_0102
Create Date: 2026-08-20
"""

import sqlalchemy as sa
from alembic import op

revision = "20260820_0103"
down_revision = "20260819_0102"
branch_labels = None
depends_on = None

TASKS = "team_agent_orchestration_tasks"


def upgrade() -> None:
    op.add_column(
        TASKS,
        sa.Column("paused_retry_wait_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        TASKS,
        sa.Column("paused_retry_after_seconds", sa.Float(), nullable=True),
    )
    op.create_check_constraint(
        "ck_team_agent_orchestration_paused_retry_after",
        TASKS,
        "paused_retry_after_seconds IS NULL OR "
        "(paused_retry_after_seconds >= 0 AND paused_retry_after_seconds <= 30)",
    )
    op.create_check_constraint(
        "ck_team_agent_orchestration_paused_retry_shape",
        TASKS,
        "(paused_retry_wait_until IS NULL OR state = 'paused') AND "
        "(paused_retry_after_seconds IS NULL OR paused_retry_wait_until IS NOT NULL)",
    )


def downgrade() -> None:
    op.execute(
        "SELECT pg_advisory_xact_lock("
        "hashtext('kjds-team-agent-paused-retry-schedule-0103'))"
    )
    op.execute(f"LOCK TABLE {TASKS} IN ACCESS EXCLUSIVE MODE")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM {TASKS}
                WHERE paused_retry_wait_until IS NOT NULL
                   OR paused_retry_after_seconds IS NOT NULL
            ) THEN
                RAISE EXCEPTION USING ERRCODE = '55000',
                    MESSAGE = '0103 downgrade blocked: paused retry schedules exist';
            END IF;
        END;
        $$;
        """
    )
    op.drop_constraint(
        "ck_team_agent_orchestration_paused_retry_shape", TASKS, type_="check"
    )
    op.drop_constraint(
        "ck_team_agent_orchestration_paused_retry_after", TASKS, type_="check"
    )
    op.drop_column(TASKS, "paused_retry_after_seconds")
    op.drop_column(TASKS, "paused_retry_wait_until")
