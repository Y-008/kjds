"""Add native exact-scope accounts payable authority.

Revision ID: 20260730_0078
Revises: 20260729_0077
Create Date: 2026-07-30
"""

import sqlalchemy as sa
from alembic import op

revision = "20260730_0078"
down_revision = "20260729_0077"
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
PAYMENT_BINDING = (
    "("
    "supplier_invoice_id IS NULL AND supplier_ref IS NULL "
    "AND payment_approval_id IS NULL AND payment_command_id IS NULL"
    ") OR ("
    "supplier_invoice_id IS NOT NULL AND length(supplier_invoice_id) > 0 "
    "AND supplier_ref IS NOT NULL AND length(supplier_ref) > 0 "
    "AND payment_approval_id IS NOT NULL "
    "AND length(payment_approval_id) > 0 "
    "AND payment_command_id IS NOT NULL "
    "AND length(payment_command_id) > 0 "
    "AND tenant_ref IS NOT NULL "
    "AND entry_kind = 'bank_payment' AND amount < 0"
    ")"
)


def upgrade() -> None:
    op.create_table(
        "supplier_invoices",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("invoice_ref", sa.String(length=240), nullable=False),
        sa.Column(
            "purchase_order_id",
            sa.String(),
            sa.ForeignKey("sample_purchase_orders.id"),
            nullable=False,
        ),
        sa.Column("supplier_ref", sa.String(length=240), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("net_amount", sa.Numeric(38, 12), nullable=False),
        sa.Column("tax_amount", sa.Numeric(38, 12), nullable=False),
        sa.Column("gross_amount", sa.Numeric(38, 12), nullable=False),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "due_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "evidence_id",
            sa.String(),
            sa.ForeignKey("evidence_records.id"),
            nullable=False,
        ),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=240), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
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
        sa.CheckConstraint(
            SCOPE_REQUIRED,
            name="ck_supplier_invoices_scope_required",
        ),
        sa.CheckConstraint(
            "length(payload_sha256) = 64",
            name="ck_supplier_invoices_payload_sha256",
        ),
        sa.CheckConstraint(
            "net_amount >= 0 AND tax_amount >= 0 AND gross_amount > 0 "
            "AND net_amount + tax_amount = gross_amount",
            name="ck_supplier_invoices_amounts",
        ),
        sa.CheckConstraint(
            "due_at >= issued_at",
            name="ck_supplier_invoices_dates",
        ),
    )
    op.create_index(
        "uq_supplier_invoice_scope_ref",
        "supplier_invoices",
        [
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "supplier_ref",
            "invoice_ref",
        ],
        unique=True,
    )
    op.create_index(
        "ix_supplier_invoice_scope_order",
        "supplier_invoices",
        [
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "purchase_order_id",
            "issued_at",
            "id",
        ],
    )

    op.create_table(
        "supplier_invoice_lines",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "invoice_id",
            sa.String(),
            sa.ForeignKey("supplier_invoices.id"),
            nullable=False,
        ),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column(
            "product_id",
            sa.String(),
            sa.ForeignKey("products.id"),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(38, 12), nullable=False),
        sa.Column("unit_price", sa.Numeric(38, 12), nullable=False),
        sa.Column("net_amount", sa.Numeric(38, 12), nullable=False),
        sa.Column("tax_amount", sa.Numeric(38, 12), nullable=False),
        sa.Column("gross_amount", sa.Numeric(38, 12), nullable=False),
        sa.Column(
            "evidence_id",
            sa.String(),
            sa.ForeignKey("evidence_records.id"),
            nullable=False,
        ),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
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
        sa.UniqueConstraint(
            "invoice_id",
            "line_number",
            name="uq_supplier_invoice_line_number",
        ),
        sa.CheckConstraint(
            SCOPE_REQUIRED,
            name="ck_supplier_invoice_lines_scope_required",
        ),
        sa.CheckConstraint(
            "quantity > 0 AND unit_price >= 0 "
            "AND net_amount >= 0 AND tax_amount >= 0 "
            "AND gross_amount >= 0 "
            "AND net_amount + tax_amount = gross_amount",
            name="ck_supplier_invoice_lines_amounts",
        ),
    )
    op.create_index(
        "ix_supplier_invoice_line_scope_invoice",
        "supplier_invoice_lines",
        [
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "invoice_id",
            "line_number",
        ],
    )
    op.create_index(
        "ix_supplier_invoice_line_scope_product",
        "supplier_invoice_lines",
        [
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "product_id",
            "invoice_id",
        ],
    )

    op.add_column(
        "finance_entries",
        sa.Column(
            "supplier_invoice_id",
            sa.String(),
            sa.ForeignKey("supplier_invoices.id"),
            nullable=True,
        ),
    )
    op.add_column(
        "finance_entries",
        sa.Column("supplier_ref", sa.String(length=240), nullable=True),
    )
    op.add_column(
        "finance_entries",
        sa.Column(
            "payment_approval_id",
            sa.String(),
            sa.ForeignKey("approvals.id"),
            nullable=True,
        ),
    )
    op.add_column(
        "finance_entries",
        sa.Column(
            "payment_command_id",
            sa.String(),
            sa.ForeignKey("limited_execution_commands.id"),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_finance_entries_supplier_payment_binding",
        "finance_entries",
        sa.text(PAYMENT_BINDING),
    )
    op.create_index(
        "ix_finance_entry_scope_supplier_invoice",
        "finance_entries",
        [
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "supplier_invoice_id",
            "effective_at",
            "recorded_at",
        ],
        postgresql_where=sa.text("supplier_invoice_id IS NOT NULL"),
        sqlite_where=sa.text("supplier_invoice_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_finance_entry_scope_supplier_invoice",
        table_name="finance_entries",
    )
    op.drop_constraint(
        "ck_finance_entries_supplier_payment_binding",
        "finance_entries",
        type_="check",
    )
    op.drop_column("finance_entries", "payment_command_id")
    op.drop_column("finance_entries", "payment_approval_id")
    op.drop_column("finance_entries", "supplier_ref")
    op.drop_column("finance_entries", "supplier_invoice_id")

    op.drop_index(
        "ix_supplier_invoice_line_scope_product",
        table_name="supplier_invoice_lines",
    )
    op.drop_index(
        "ix_supplier_invoice_line_scope_invoice",
        table_name="supplier_invoice_lines",
    )
    op.drop_table("supplier_invoice_lines")

    op.drop_index(
        "ix_supplier_invoice_scope_order",
        table_name="supplier_invoices",
    )
    op.drop_index(
        "uq_supplier_invoice_scope_ref",
        table_name="supplier_invoices",
    )
    op.drop_table("supplier_invoices")
