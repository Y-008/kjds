"""Add durable TeamAgent task leases and transition events.

Revision ID: 20260819_0099
Revises: 20260809_0098
Create Date: 2026-08-19
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260819_0099"
down_revision = "20260809_0098"
branch_labels = None
depends_on = None

TASKS = "team_agent_orchestration_tasks"
EVENTS = "team_agent_orchestration_events"


def upgrade() -> None:
    op.create_table(
        TASKS,
        sa.Column("tenant_ref", sa.String(160), nullable=False),
        sa.Column("entity_ref", sa.String(160), nullable=False),
        sa.Column("store_ref", sa.String(160), nullable=False),
        sa.Column("session_ref", sa.String(160), nullable=False),
        sa.Column("task_ref", sa.String(160), nullable=False),
        sa.Column("idempotency_key", sa.String(300), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("claimed_by", sa.String(240), nullable=True),
        sa.Column("lease_ref", sa.String(80), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("retry_wait_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "session_ref",
            "task_ref",
            name="pk_team_agent_orchestration_task",
        ),
        sa.UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "session_ref",
            "idempotency_key",
            name="uq_team_agent_orchestration_idempotency",
        ),
        sa.CheckConstraint(
            "length(btrim(tenant_ref)) > 0 AND length(btrim(entity_ref)) > 0 "
            "AND length(btrim(store_ref)) > 0 AND length(btrim(session_ref)) > 0 "
            "AND length(btrim(task_ref)) > 0 AND length(btrim(idempotency_key)) > 0",
            name="ck_team_agent_orchestration_required_text",
        ),
        sa.CheckConstraint(
            "request_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_team_agent_orchestration_request_sha256",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload_json) = 'object' "
            "AND octet_length(payload_json::text) <= 65536",
            name="ck_team_agent_orchestration_payload",
        ),
        sa.CheckConstraint(
            "state IN ('queued','running','retry_wait','expired','blocked',"
            "'completed','failed','paused')",
            name="ck_team_agent_orchestration_state",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND max_attempts BETWEEN 1 AND 3 "
            "AND attempt_count <= max_attempts AND revision >= 0",
            name="ck_team_agent_orchestration_counters",
        ),
        sa.CheckConstraint(
            "(state = 'running' AND claimed_by IS NOT NULL AND lease_ref IS NOT NULL "
            "AND lease_expires_at IS NOT NULL) OR "
            "(state <> 'running' AND claimed_by IS NULL AND lease_ref IS NULL "
            "AND lease_expires_at IS NULL)",
            name="ck_team_agent_orchestration_lease_shape",
        ),
        sa.CheckConstraint(
            "(state = 'retry_wait' AND retry_wait_until IS NOT NULL) OR "
            "(state <> 'retry_wait' AND retry_wait_until IS NULL)",
            name="ck_team_agent_orchestration_retry_shape",
        ),
        sa.CheckConstraint(
            "updated_at >= created_at AND "
            "(lease_expires_at IS NULL OR lease_expires_at > updated_at)",
            name="ck_team_agent_orchestration_time_order",
        ),
    )
    op.create_index(
        "uq_team_agent_orchestration_lease_ref",
        TASKS,
        ["lease_ref"],
        unique=True,
        postgresql_where=sa.text("lease_ref IS NOT NULL"),
    )
    op.create_index(
        "ix_team_agent_orchestration_claimable",
        TASKS,
        [
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "session_ref",
            "state",
            "retry_wait_until",
            "lease_expires_at",
        ],
    )

    op.create_table(
        EVENTS,
        sa.Column("event_id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("tenant_ref", sa.String(160), nullable=False),
        sa.Column("entity_ref", sa.String(160), nullable=False),
        sa.Column("store_ref", sa.String(160), nullable=False),
        sa.Column("session_ref", sa.String(160), nullable=False),
        sa.Column("task_ref", sa.String(160), nullable=False),
        sa.Column("task_revision", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("worker_id", sa.String(240), nullable=True),
        sa.Column("lease_ref", sa.String(80), nullable=True),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("event_id", name="pk_team_agent_orchestration_event"),
        sa.ForeignKeyConstraint(
            ["tenant_ref", "entity_ref", "store_ref", "session_ref", "task_ref"],
            [
                f"{TASKS}.tenant_ref",
                f"{TASKS}.entity_ref",
                f"{TASKS}.store_ref",
                f"{TASKS}.session_ref",
                f"{TASKS}.task_ref",
            ],
            name="fk_team_agent_orchestration_event_task",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "session_ref",
            "task_ref",
            "task_revision",
            name="uq_team_agent_orchestration_event_revision",
        ),
        sa.CheckConstraint(
            "task_revision >= 0 AND event_type IN "
            "('registered','claimed','heartbeat','released')",
            name="ck_team_agent_orchestration_event_shape",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload_json) = 'object' "
            "AND octet_length(payload_json::text) <= 4096",
            name="ck_team_agent_orchestration_event_payload",
        ),
    )
    op.create_index(
        "ix_team_agent_orchestration_event_cursor",
        EVENTS,
        ["tenant_ref", "entity_ref", "store_ref", "session_ref", "event_id"],
    )

    op.execute(
        """
        CREATE FUNCTION kjds_team_agent_orchestration_event_immutable()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION USING ERRCODE = '55000',
                MESSAGE = 'TeamAgent orchestration events are append-only';
        END;
        $$
        """
    )
    op.execute(
        f"CREATE TRIGGER trg_team_agent_orchestration_event_immutable "
        f"BEFORE UPDATE OR DELETE ON {EVENTS} FOR EACH ROW "
        "EXECUTE FUNCTION kjds_team_agent_orchestration_event_immutable()"
    )
    op.execute(
        f"""
        CREATE FUNCTION kjds_team_agent_orchestration_revision_conserved()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                  FROM {EVENTS} event
                 WHERE event.tenant_ref = NEW.tenant_ref
                   AND event.entity_ref = NEW.entity_ref
                   AND event.store_ref = NEW.store_ref
                   AND event.session_ref = NEW.session_ref
                   AND event.task_ref = NEW.task_ref
                   AND event.task_revision = NEW.revision
            ) THEN
                RAISE EXCEPTION USING ERRCODE = '23514',
                    MESSAGE = 'TeamAgent task revision requires one transition event';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"CREATE CONSTRAINT TRIGGER trg_team_agent_orchestration_revision_conserved "
        f"AFTER INSERT OR UPDATE ON {TASKS} DEFERRABLE INITIALLY DEFERRED "
        "FOR EACH ROW EXECUTE FUNCTION "
        "kjds_team_agent_orchestration_revision_conserved()"
    )


def downgrade() -> None:
    op.execute(
        "SELECT pg_advisory_xact_lock("
        "hashtext('kjds-team-agent-orchestration-0099'))"
    )
    op.execute(
        f"LOCK TABLE {TASKS}, {EVENTS} IN ACCESS EXCLUSIVE MODE"
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM {TASKS})
               OR EXISTS (SELECT 1 FROM {EVENTS}) THEN
                RAISE EXCEPTION USING ERRCODE = '55000',
                    MESSAGE = '0099 downgrade blocked: TeamAgent durable state exists';
            END IF;
        END;
        $$
        """
    )
    op.execute(
        f"DROP TRIGGER trg_team_agent_orchestration_revision_conserved ON {TASKS}"
    )
    op.execute("DROP FUNCTION kjds_team_agent_orchestration_revision_conserved()")
    op.execute(
        f"DROP TRIGGER trg_team_agent_orchestration_event_immutable ON {EVENTS}"
    )
    op.execute("DROP FUNCTION kjds_team_agent_orchestration_event_immutable()")
    op.drop_index("ix_team_agent_orchestration_event_cursor", table_name=EVENTS)
    op.drop_table(EVENTS)
    op.drop_index("ix_team_agent_orchestration_claimable", table_name=TASKS)
    op.drop_index("uq_team_agent_orchestration_lease_ref", table_name=TASKS)
    op.drop_table(TASKS)
