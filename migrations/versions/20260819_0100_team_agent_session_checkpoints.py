"""Add authority-bound TeamAgent session checkpoint CAS.

Revision ID: 20260819_0100
Revises: 20260819_0099
Create Date: 2026-08-19
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260819_0100"
down_revision = "20260819_0099"
branch_labels = None
depends_on = None

CHECKPOINTS = "team_agent_orchestration_checkpoints"
EVENTS = "team_agent_orchestration_checkpoint_events"


def upgrade() -> None:
    op.create_table(
        CHECKPOINTS,
        sa.Column("tenant_ref", sa.String(160), nullable=False),
        sa.Column("entity_ref", sa.String(160), nullable=False),
        sa.Column("store_ref", sa.String(160), nullable=False),
        sa.Column("session_ref", sa.String(160), nullable=False),
        sa.Column("authority_sha256", sa.String(64), nullable=False),
        sa.Column(
            "checkpoint_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("checkpoint_sha256", sa.String(64), nullable=False),
        sa.Column("last_control_cursor", sa.String(160), nullable=False),
        sa.Column("last_control_event_sha256", sa.String(64), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "session_ref",
            name="pk_team_agent_orchestration_checkpoint",
        ),
        sa.CheckConstraint(
            "authority_sha256 ~ '^[0-9a-f]{64}$' AND "
            "checkpoint_sha256 ~ '^[0-9a-f]{64}$' AND "
            "last_control_event_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_team_agent_checkpoint_hashes",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(checkpoint_json) = 'object' AND "
            "octet_length(checkpoint_json::text) <= 4194304",
            name="ck_team_agent_checkpoint_payload",
        ),
        sa.CheckConstraint(
            "revision >= 0 AND updated_at >= created_at",
            name="ck_team_agent_checkpoint_revision_time",
        ),
    )
    op.create_index(
        "ix_team_agent_checkpoint_updated",
        CHECKPOINTS,
        ["tenant_ref", "entity_ref", "store_ref", "updated_at"],
    )
    op.create_table(
        EVENTS,
        sa.Column("event_id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("tenant_ref", sa.String(160), nullable=False),
        sa.Column("entity_ref", sa.String(160), nullable=False),
        sa.Column("store_ref", sa.String(160), nullable=False),
        sa.Column("session_ref", sa.String(160), nullable=False),
        sa.Column("checkpoint_revision", sa.BigInteger(), nullable=False),
        sa.Column("authority_sha256", sa.String(64), nullable=False),
        sa.Column("checkpoint_sha256", sa.String(64), nullable=False),
        sa.Column("last_control_cursor", sa.String(160), nullable=False),
        sa.Column("last_control_event_sha256", sa.String(64), nullable=False),
        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "event_id",
            name="pk_team_agent_orchestration_checkpoint_event",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_ref", "entity_ref", "store_ref", "session_ref"],
            [
                f"{CHECKPOINTS}.tenant_ref",
                f"{CHECKPOINTS}.entity_ref",
                f"{CHECKPOINTS}.store_ref",
                f"{CHECKPOINTS}.session_ref",
            ],
            name="fk_team_agent_checkpoint_event_checkpoint",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "session_ref",
            "checkpoint_revision",
            name="uq_team_agent_checkpoint_event_revision",
        ),
        sa.CheckConstraint(
            "checkpoint_revision >= 0",
            name="ck_team_agent_checkpoint_event_revision",
        ),
    )
    op.create_index(
        "ix_team_agent_checkpoint_event_cursor",
        EVENTS,
        ["tenant_ref", "entity_ref", "store_ref", "session_ref", "event_id"],
    )
    op.execute(
        """
        CREATE FUNCTION kjds_team_agent_checkpoint_event_immutable()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION USING ERRCODE = '55000',
                MESSAGE = 'TeamAgent checkpoint events are append-only';
        END;
        $$
        """
    )
    op.execute(
        f"CREATE TRIGGER trg_team_agent_checkpoint_event_immutable "
        f"BEFORE UPDATE OR DELETE ON {EVENTS} FOR EACH ROW "
        "EXECUTE FUNCTION kjds_team_agent_checkpoint_event_immutable()"
    )
    op.execute(
        f"""
        CREATE FUNCTION kjds_team_agent_checkpoint_revision_conserved()
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
                   AND event.checkpoint_revision = NEW.revision
                   AND event.checkpoint_sha256 = NEW.checkpoint_sha256
            ) THEN
                RAISE EXCEPTION USING ERRCODE = '23514',
                    MESSAGE = 'TeamAgent checkpoint revision requires save history';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"CREATE CONSTRAINT TRIGGER trg_team_agent_checkpoint_revision_conserved "
        f"AFTER INSERT OR UPDATE ON {CHECKPOINTS} DEFERRABLE INITIALLY DEFERRED "
        "FOR EACH ROW EXECUTE FUNCTION "
        "kjds_team_agent_checkpoint_revision_conserved()"
    )


def downgrade() -> None:
    op.execute(
        "SELECT pg_advisory_xact_lock("
        "hashtext('kjds-team-agent-checkpoint-0100'))"
    )
    op.execute(f"LOCK TABLE {CHECKPOINTS}, {EVENTS} IN ACCESS EXCLUSIVE MODE")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM {CHECKPOINTS})
               OR EXISTS (SELECT 1 FROM {EVENTS}) THEN
                RAISE EXCEPTION USING ERRCODE = '55000',
                    MESSAGE = '0100 downgrade blocked: TeamAgent checkpoints exist';
            END IF;
        END;
        $$
        """
    )
    op.execute(
        f"DROP TRIGGER trg_team_agent_checkpoint_revision_conserved ON {CHECKPOINTS}"
    )
    op.execute("DROP FUNCTION kjds_team_agent_checkpoint_revision_conserved()")
    op.execute(
        f"DROP TRIGGER trg_team_agent_checkpoint_event_immutable ON {EVENTS}"
    )
    op.execute("DROP FUNCTION kjds_team_agent_checkpoint_event_immutable()")
    op.drop_index("ix_team_agent_checkpoint_event_cursor", table_name=EVENTS)
    op.drop_table(EVENTS)
    op.drop_index("ix_team_agent_checkpoint_updated", table_name=CHECKPOINTS)
    op.drop_table(CHECKPOINTS)
