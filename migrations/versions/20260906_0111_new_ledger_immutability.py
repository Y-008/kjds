"""Enforce append-only semantics for the new replay and accounting ledgers.

The Python adapters never update or delete these rows, but a database owner or
an accidental SQL path must not be able to rewrite a historical fact behind the
adapter's back.  PostgreSQL triggers provide the second line of defence; a
correction is represented by a new revision/event instead.

Revision ID: 20260906_0111
Revises: 20260906_0110
"""

from __future__ import annotations

from alembic import op

revision = "20260906_0111"
down_revision = "20260906_0110"
branch_labels = None
depends_on = None

TABLES = (
    "temporal_fact_revisions",
    "project_manager_heartbeats",
    "skill_usage_events",
    "project_graph_proposals",
)
FUNCTION = "kjds_replay_ledger_immutable"


def upgrade() -> None:
    op.execute(
        f"""
CREATE OR REPLACE FUNCTION {FUNCTION}() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME
        USING ERRCODE = '55000';
END;
$$
"""
    )
    for table in TABLES:
        trigger = f"trg_{table}_immutable"
        truncate_trigger = f"trg_{table}_truncate_immutable"
        op.execute(f'DROP TRIGGER IF EXISTS "{trigger}" ON "{table}"')
        op.execute(f'DROP TRIGGER IF EXISTS "{truncate_trigger}" ON "{table}"')
        op.execute(
            f'CREATE TRIGGER "{trigger}" '
            f'BEFORE UPDATE OR DELETE ON "{table}" FOR EACH ROW '
            f"EXECUTE FUNCTION {FUNCTION}()"
        )
        op.execute(
            f'CREATE TRIGGER "{truncate_trigger}" '
            f'BEFORE TRUNCATE ON "{table}" FOR EACH STATEMENT '
            f"EXECUTE FUNCTION {FUNCTION}()"
        )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(
            f'DROP TRIGGER IF EXISTS "trg_{table}_truncate_immutable" ON "{table}"'
        )
        op.execute(
            f'DROP TRIGGER IF EXISTS "trg_{table}_immutable" ON "{table}"'
        )
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION}()")

