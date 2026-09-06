"""Harden temporal fact identity and idempotency constraints.

The original temporal table established the append-only shape.  This revision
adds database-enforced uniqueness so concurrent workers cannot create two rows
for the same canonical revision or reuse a real idempotency key in one scope.
Empty keys are intentionally excluded from the partial index because legacy
imports may be non-idempotent and are stored as NULL by the adapter.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260906_0107"
down_revision = "20260906_0106"
branch_labels = None
depends_on = None

TABLE = "temporal_fact_revisions"


def upgrade() -> None:
    op.create_index(
        "uq_temporal_fact_identity_revision",
        TABLE,
        ["scope_key", "fact_type", "natural_key", "revision"],
        unique=True,
    )
    op.create_index(
        "uq_temporal_fact_id_revision",
        TABLE,
        ["fact_id", "revision"],
        unique=True,
    )
    # Partial unique indexes are supported by PostgreSQL and SQLite.  The
    # dialect-specific predicates keep empty legacy keys from colliding.
    op.create_index(
        "uq_temporal_fact_scope_idempotency",
        TABLE,
        ["scope_key", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL AND idempotency_key <> ''"),
        sqlite_where=sa.text("idempotency_key IS NOT NULL AND idempotency_key <> ''"),
    )


def downgrade() -> None:
    op.drop_index("uq_temporal_fact_scope_idempotency", table_name=TABLE)
    op.drop_index("uq_temporal_fact_id_revision", table_name=TABLE)
    op.drop_index("uq_temporal_fact_identity_revision", table_name=TABLE)
