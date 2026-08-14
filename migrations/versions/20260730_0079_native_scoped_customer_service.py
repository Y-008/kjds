"""Add native exact-scope customer-service authority.

Revision ID: 20260730_0079
Revises: 20260730_0078
Create Date: 2026-07-30
"""

import sqlalchemy as sa
from alembic import op

revision = "20260730_0079"
down_revision = "20260730_0078"
branch_labels = None
depends_on = None

SCOPE_REQUIRED = (
    "tenant_ref IS NOT NULL AND length(tenant_ref) > 0 "
    "AND entity_ref IS NOT NULL AND length(entity_ref) > 0 "
    "AND store_ref IS NOT NULL AND length(store_ref) > 0 "
    "AND scope_grant_authority_sha256 IS NOT NULL "
    "AND length(scope_grant_authority_sha256) = 64 "
    "AND source_evidence_sha256 IS NOT NULL "
    "AND length(source_evidence_sha256) = 64 "
    "AND scope_as_of IS NOT NULL"
)
EXECUTION_BINDING = (
    "("
    "approval_id IS NULL AND command_id IS NULL AND receipt_id IS NULL"
    ") OR ("
    "event_type = 'message_sent_readback' "
    "AND approval_id IS NOT NULL AND length(approval_id) > 0 "
    "AND command_id IS NOT NULL AND length(command_id) > 0 "
    "AND receipt_id IS NOT NULL AND length(receipt_id) > 0"
    ")"
)


def _scope_columns() -> list[sa.Column]:
    return [
        sa.Column("tenant_ref", sa.String(length=160), nullable=False),
        sa.Column("entity_ref", sa.String(length=160), nullable=False),
        sa.Column("store_ref", sa.String(length=160), nullable=False),
        sa.Column(
            "scope_grant_authority_sha256",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "source_evidence_sha256",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "scope_as_of",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.drop_constraint(
        "ck_execution_plan_source_variant",
        "governed_execution_plans",
        type_="check",
    )
    op.create_check_constraint(
        "ck_execution_plan_source_variant",
        "governed_execution_plans",
        sa.text(
            "(source_kind = 'causal_policy_handoff' "
            "AND source_id = handoff_id "
            "AND handoff_id IS NOT NULL "
            "AND policy_id IS NOT NULL "
            "AND release_id IS NOT NULL) "
            "OR (source_kind = 'approved_listing_draft' "
            "AND handoff_id IS NULL "
            "AND policy_id IS NULL "
            "AND release_id IS NULL) "
            "OR (source_kind = 'approved_customer_service_reply' "
            "AND handoff_id IS NULL "
            "AND policy_id IS NULL "
            "AND release_id IS NULL)"
        ),
    )
    op.create_table(
        "customer_service_cases",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("external_case_ref", sa.String(length=240), nullable=False),
        sa.Column("channel", sa.String(length=80), nullable=False),
        sa.Column("order_external_id", sa.String(length=240), nullable=False),
        sa.Column(
            "product_id",
            sa.String(),
            sa.ForeignKey("products.id"),
            nullable=False,
        ),
        sa.Column("sku", sa.String(length=240), nullable=False),
        sa.Column("locale", sa.String(length=40), nullable=False),
        sa.Column("classification", sa.String(length=80), nullable=False),
        sa.Column("priority", sa.String(length=40), nullable=False),
        sa.Column(
            "evidence_id",
            sa.String(),
            sa.ForeignKey("evidence_records.id"),
            nullable=False,
        ),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=240), nullable=False),
        *_scope_columns(),
        sa.CheckConstraint(
            SCOPE_REQUIRED,
            name="ck_customer_service_cases_scope_required",
        ),
        sa.CheckConstraint(
            "length(payload_sha256) = 64",
            name="ck_customer_service_cases_payload_sha256",
        ),
    )
    op.create_index(
        "uq_customer_service_case_scope_source",
        "customer_service_cases",
        [
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "channel",
            "external_case_ref",
        ],
        unique=True,
    )
    op.create_index(
        "ix_customer_service_case_scope_opened",
        "customer_service_cases",
        [
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "opened_at",
            "id",
        ],
    )

    op.create_table(
        "customer_service_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "case_id",
            sa.String(),
            sa.ForeignKey("customer_service_cases.id"),
            nullable=False,
        ),
        sa.Column("source_event_ref", sa.String(length=240), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("direction", sa.String(length=40), nullable=False),
        sa.Column("locale", sa.String(length=40), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("body_sha256", sa.String(length=64), nullable=True),
        sa.Column(
            "evidence_id",
            sa.String(),
            sa.ForeignKey("evidence_records.id"),
            nullable=False,
        ),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=240), nullable=False),
        sa.Column(
            "approval_id",
            sa.String(),
            sa.ForeignKey("approvals.id"),
            nullable=True,
        ),
        sa.Column(
            "command_id",
            sa.String(),
            sa.ForeignKey("limited_execution_commands.id"),
            nullable=True,
        ),
        sa.Column(
            "receipt_id",
            sa.String(),
            sa.ForeignKey("limited_execution_receipts.id"),
            nullable=True,
        ),
        *_scope_columns(),
        sa.UniqueConstraint(
            "case_id",
            "sequence",
            name="uq_customer_service_event_sequence",
        ),
        sa.UniqueConstraint(
            "case_id",
            "source_event_ref",
            name="uq_customer_service_event_source",
        ),
        sa.CheckConstraint(
            SCOPE_REQUIRED,
            name="ck_customer_service_events_scope_required",
        ),
        sa.CheckConstraint(
            "sequence > 0",
            name="ck_customer_service_events_sequence",
        ),
        sa.CheckConstraint(
            "body_sha256 IS NULL OR length(body_sha256) = 64",
            name="ck_customer_service_events_body_sha256",
        ),
        sa.CheckConstraint(
            "length(payload_sha256) = 64",
            name="ck_customer_service_events_payload_sha256",
        ),
        sa.CheckConstraint(
            EXECUTION_BINDING,
            name="ck_customer_service_events_execution_binding",
        ),
    )
    op.create_index(
        "ix_customer_service_event_scope_case",
        "customer_service_events",
        [
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "case_id",
            "sequence",
            "id",
        ],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_customer_service_event_scope_case",
        table_name="customer_service_events",
    )
    op.drop_table("customer_service_events")
    op.drop_index(
        "ix_customer_service_case_scope_opened",
        table_name="customer_service_cases",
    )
    op.drop_index(
        "uq_customer_service_case_scope_source",
        table_name="customer_service_cases",
    )
    op.drop_table("customer_service_cases")
    op.drop_constraint(
        "ck_execution_plan_source_variant",
        "governed_execution_plans",
        type_="check",
    )
    op.create_check_constraint(
        "ck_execution_plan_source_variant",
        "governed_execution_plans",
        sa.text(
            "(source_kind = 'causal_policy_handoff' "
            "AND source_id = handoff_id "
            "AND handoff_id IS NOT NULL "
            "AND policy_id IS NOT NULL "
            "AND release_id IS NOT NULL) "
            "OR (source_kind = 'approved_listing_draft' "
            "AND handoff_id IS NULL "
            "AND policy_id IS NULL "
            "AND release_id IS NULL)"
        ),
    )
