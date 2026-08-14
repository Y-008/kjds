"""Add native exact-scope procurement and receiving authority.

Revision ID: 20260729_0077
Revises: 20260729_0076
Create Date: 2026-07-29
"""

import sqlalchemy as sa
from alembic import op

revision = "20260729_0077"
down_revision = "20260729_0076"
branch_labels = None
depends_on = None

SCOPE_COLUMNS = (
    ("tenant_ref", sa.String(length=160)),
    ("entity_ref", sa.String(length=160)),
    ("store_ref", sa.String(length=160)),
    ("scope_grant_authority_sha256", sa.String(length=64)),
    ("source_evidence_sha256", sa.String(length=64)),
    ("scope_as_of", sa.DateTime(timezone=True)),
)
SCOPE_CHECK = (
    "("
    "tenant_ref IS NULL AND entity_ref IS NULL AND store_ref IS NULL "
    "AND scope_grant_authority_sha256 IS NULL "
    "AND source_evidence_sha256 IS NULL AND scope_as_of IS NULL"
    ") OR ("
    "tenant_ref IS NOT NULL AND length(tenant_ref) > 0 "
    "AND entity_ref IS NOT NULL AND length(entity_ref) > 0 "
    "AND store_ref IS NOT NULL AND length(store_ref) > 0 "
    "AND scope_grant_authority_sha256 IS NOT NULL "
    "AND length(scope_grant_authority_sha256) = 64 "
    "AND source_evidence_sha256 IS NOT NULL "
    "AND length(source_evidence_sha256) = 64 "
    "AND scope_as_of IS NOT NULL"
    ")"
)


def _add_scope(table: str) -> None:
    for name, column_type in SCOPE_COLUMNS:
        op.add_column(table, sa.Column(name, column_type, nullable=True))


def upgrade() -> None:
    _add_scope("sample_purchase_orders")
    op.add_column(
        "sample_purchase_orders",
        sa.Column(
            "authority_evidence_id",
            sa.String(),
            sa.ForeignKey("evidence_records.id"),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_sample_purchase_orders_scope_complete",
        "sample_purchase_orders",
        sa.text(
            f"({SCOPE_CHECK}) AND ("
            "(tenant_ref IS NULL AND authority_evidence_id IS NULL) OR "
            "(tenant_ref IS NOT NULL AND authority_evidence_id IS NOT NULL)"
            ")"
        ),
    )
    op.create_index(
        "ix_sample_order_scope_created",
        "sample_purchase_orders",
        [
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "created_at",
            "id",
        ],
    )
    op.create_index(
        "ix_sample_order_scope_product",
        "sample_purchase_orders",
        [
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "product_id",
            "created_at",
        ],
    )

    _add_scope("sample_procurement_events")
    op.create_check_constraint(
        "ck_sample_procurement_events_scope_complete",
        "sample_procurement_events",
        sa.text(SCOPE_CHECK),
    )
    op.create_index(
        "ix_sample_event_scope_timeline",
        "sample_procurement_events",
        [
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "purchase_order_id",
            "sequence",
            "effective_at",
        ],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_sample_event_scope_timeline",
        table_name="sample_procurement_events",
    )
    op.drop_constraint(
        "ck_sample_procurement_events_scope_complete",
        "sample_procurement_events",
        type_="check",
    )
    for name, _column_type in reversed(SCOPE_COLUMNS):
        op.drop_column("sample_procurement_events", name)

    op.drop_index(
        "ix_sample_order_scope_product",
        table_name="sample_purchase_orders",
    )
    op.drop_index(
        "ix_sample_order_scope_created",
        table_name="sample_purchase_orders",
    )
    op.drop_constraint(
        "ck_sample_purchase_orders_scope_complete",
        "sample_purchase_orders",
        type_="check",
    )
    op.drop_column(
        "sample_purchase_orders",
        "authority_evidence_id",
    )
    for name, _column_type in reversed(SCOPE_COLUMNS):
        op.drop_column("sample_purchase_orders", name)
