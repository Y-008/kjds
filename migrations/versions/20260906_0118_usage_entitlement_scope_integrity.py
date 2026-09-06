"""Enforce exact tenant/customer identity for usage entitlement links.

Revision ID: 20260906_0118
Revises: 20260906_0117

The 0117 link table duplicated scope columns for auditing, but its first
foreign key only referenced the globally unique event id.  A direct SQL
writer could therefore pair an event with a different tenant, customer or
receipt while still satisfying the foreign key.  This forward-only hardening
adds one parent identity and references it with a composite ``RESTRICT`` FK.

Native PostgreSQL RLS is intentionally not enabled here.  ADR-0038 requires a
non-owner application principal, transaction-local scope reset and shadow
policy evidence before ``FORCE ROW LEVEL SECURITY``; enabling it without those
preconditions would create a false isolation claim and can strand legacy rows.
"""

from __future__ import annotations

from alembic import op

revision = "20260906_0118"
down_revision = "20260906_0117"
branch_labels = None
depends_on = None

EVENT_TABLE = "skill_usage_events"
LINK_TABLE = "skill_usage_entitlement_links"
PARENT_IDENTITY = "uq_skill_usage_entitlement_parent_identity"
OLD_FK = "fk_skill_usage_entitlement_link_event"
EXACT_FK = "fk_skill_usage_entitlement_link_exact_event"

PARENT_COLUMNS = [
    "tenant_id",
    "event_id",
    "customer_id",
    "idempotency_key",
    "entitlement_receipt_ref",
]
CHILD_COLUMNS = [
    "tenant_id",
    "usage_event_id",
    "customer_id",
    "idempotency_key",
    "entitlement_receipt_ref",
]


def upgrade() -> None:
    # event_id is already the primary key, so this identity cannot introduce
    # duplicate rows; it exists to make the repeated scope tuple referenceable
    # by PostgreSQL's composite-FK rules.
    op.create_unique_constraint(PARENT_IDENTITY, EVENT_TABLE, PARENT_COLUMNS)
    op.drop_constraint(OLD_FK, LINK_TABLE, type_="foreignkey")
    op.create_foreign_key(
        EXACT_FK,
        LINK_TABLE,
        EVENT_TABLE,
        CHILD_COLUMNS,
        PARENT_COLUMNS,
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )


def downgrade() -> None:
    # Restore the exact 0117 schema so a subsequent downgrade can remove the
    # link table and receipt column in its original order.
    op.drop_constraint(EXACT_FK, LINK_TABLE, type_="foreignkey")
    op.create_foreign_key(
        OLD_FK,
        LINK_TABLE,
        EVENT_TABLE,
        ["usage_event_id"],
        ["event_id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )
    op.drop_constraint(PARENT_IDENTITY, EVENT_TABLE, type_="unique")
