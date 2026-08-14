from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import new_id
from .evidence import EvidenceGrade, parse_timestamp
from .procurement import SamplePurchaseOrderRow  # noqa: F401
from .security import Principal
from .sql_repository import Base, ProductRow  # noqa: F401

SCOPE_REQUIRED_SQL = (
    "tenant_ref IS NOT NULL AND length(tenant_ref) > 0 "
    "AND entity_ref IS NOT NULL AND length(entity_ref) > 0 "
    "AND store_ref IS NOT NULL AND length(store_ref) > 0 "
    "AND scope_grant_authority_sha256 IS NOT NULL "
    "AND length(scope_grant_authority_sha256) = 64 "
    "AND source_evidence_sha256 IS NOT NULL "
    "AND length(source_evidence_sha256) = 64 "
    "AND scope_as_of IS NOT NULL"
)


class SupplierInvoiceRow(Base):
    """Immutable exact-scope supplier invoice header."""

    __tablename__ = "supplier_invoices"
    __table_args__ = (
        CheckConstraint(
            SCOPE_REQUIRED_SQL,
            name="ck_supplier_invoices_scope_required",
        ),
        CheckConstraint(
            "length(payload_sha256) = 64",
            name="ck_supplier_invoices_payload_sha256",
        ),
        CheckConstraint(
            "net_amount >= 0 AND tax_amount >= 0 AND gross_amount > 0 "
            "AND net_amount + tax_amount = gross_amount",
            name="ck_supplier_invoices_amounts",
        ),
        CheckConstraint(
            "due_at >= issued_at",
            name="ck_supplier_invoices_dates",
        ),
        Index(
            "uq_supplier_invoice_scope_ref",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "supplier_ref",
            "invoice_ref",
            unique=True,
        ),
        Index(
            "ix_supplier_invoice_scope_order",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "purchase_order_id",
            "issued_at",
            "id",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    invoice_ref: Mapped[str] = mapped_column(String(240), nullable=False)
    purchase_order_id: Mapped[str] = mapped_column(
        ForeignKey("sample_purchase_orders.id"),
        nullable=False,
    )
    supplier_ref: Mapped[str] = mapped_column(String(240), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    net_amount: Mapped[Decimal] = mapped_column(
        Numeric(38, 12),
        nullable=False,
    )
    tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(38, 12),
        nullable=False,
    )
    gross_amount: Mapped[Decimal] = mapped_column(
        Numeric(38, 12),
        nullable=False,
    )
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    evidence_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_records.id"),
        nullable=False,
    )
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(240), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_grant_authority_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    source_evidence_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    scope_as_of: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class SupplierInvoiceLineRow(Base):
    """Immutable line detail; scope is repeated to permit exact isolated reads."""

    __tablename__ = "supplier_invoice_lines"
    __table_args__ = (
        UniqueConstraint(
            "invoice_id",
            "line_number",
            name="uq_supplier_invoice_line_number",
        ),
        CheckConstraint(
            SCOPE_REQUIRED_SQL,
            name="ck_supplier_invoice_lines_scope_required",
        ),
        CheckConstraint(
            "quantity > 0 AND unit_price >= 0 "
            "AND net_amount >= 0 AND tax_amount >= 0 AND gross_amount >= 0 "
            "AND net_amount + tax_amount = gross_amount",
            name="ck_supplier_invoice_lines_amounts",
        ),
        Index(
            "ix_supplier_invoice_line_scope_invoice",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "invoice_id",
            "line_number",
        ),
        Index(
            "ix_supplier_invoice_line_scope_product",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "product_id",
            "invoice_id",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    invoice_id: Mapped[str] = mapped_column(
        ForeignKey("supplier_invoices.id"),
        nullable=False,
    )
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    product_id: Mapped[str] = mapped_column(
        ForeignKey("products.id"),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(38, 12),
        nullable=False,
    )
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(38, 12),
        nullable=False,
    )
    net_amount: Mapped[Decimal] = mapped_column(
        Numeric(38, 12),
        nullable=False,
    )
    tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(38, 12),
        nullable=False,
    )
    gross_amount: Mapped[Decimal] = mapped_column(
        Numeric(38, 12),
        nullable=False,
    )
    evidence_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_records.id"),
        nullable=False,
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_grant_authority_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    source_evidence_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    scope_as_of: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class AccountsPayableAuthorityService:
    """Capture and independently attest exact-scope supplier invoices."""

    SOURCE_CONTRACT_ID = "kjds-supplier-invoice-authority-v1"
    REVIEW_CONTRACT_ID = "kjds-supplier-invoice-authority-review-v1"
    REVIEW_SOURCE = "supplier_invoice_authority_review"
    REVIEW_RELATIONSHIP = "supplier_invoice_authority_review"

    def __init__(self, *, engine, evidence, scoped_evidence) -> None:
        self.engine = engine
        self.evidence = evidence
        self.scoped_evidence = scoped_evidence

    def capture_invoice(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        invoice_ref: str,
        purchase_order_id: str,
        supplier_ref: str,
        currency: str,
        net_amount: Decimal,
        tax_amount: Decimal,
        gross_amount: Decimal,
        issued_at: str,
        due_at: str,
        evidence_id: str,
        lines: list[dict[str, Any]],
        as_of: str | None = None,
    ) -> dict[str, Any]:
        context = self._context(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        invoice_ref = self._required(invoice_ref, "invoice_ref", 240)
        purchase_order_id = self._required(
            purchase_order_id,
            "purchase_order_id",
            240,
        )
        supplier_ref = self._required(supplier_ref, "supplier_ref", 240)
        currency = self._currency(currency)
        net = self._nonnegative(net_amount, "net_amount")
        tax = self._nonnegative(tax_amount, "tax_amount")
        gross = self._positive(gross_amount, "gross_amount")
        if net + tax != gross:
            raise ValueError("Supplier invoice header amounts do not conserve")
        issued = parse_timestamp(issued_at, "issued_at")
        due = parse_timestamp(due_at, "due_at")
        if due < issued:
            raise ValueError("due_at must not be earlier than issued_at")
        if issued > context["cutoff"] or due < issued:
            raise ValueError("Supplier invoice timestamps are outside the capture cutoff")
        normalized_lines = self._lines(lines)
        if sum(item["net_amount"] for item in normalized_lines) != net:
            raise ValueError("Supplier invoice line net amount does not match header")
        if sum(item["tax_amount"] for item in normalized_lines) != tax:
            raise ValueError("Supplier invoice line tax amount does not match header")
        if sum(item["gross_amount"] for item in normalized_lines) != gross:
            raise ValueError("Supplier invoice line gross amount does not match header")

        self.evidence.require_current(
            [evidence_id],
            as_of=context["cutoff"],
        )
        original = self.evidence.get(evidence_id)
        projection = self.scoped_evidence.project_targets(
            evidence_ids=[evidence_id],
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=context["cutoff"],
        )
        target = next(
            (
                item
                for item in projection.get("records", [])
                if item.get("evidence_id", item.get("id")) == evidence_id
            ),
            None,
        )
        if (
            projection.get("status") != "ready"
            or target is None
            or (
                target.get("status")
                or (target.get("scope_binding") or {}).get("status")
            )
            != "ready"
        ):
            raise ValueError("Supplier invoice Evidence is not exact-scope ready")

        payload = {
            "contract_id": self.SOURCE_CONTRACT_ID,
            "invoice_ref": invoice_ref,
            "purchase_order_id": purchase_order_id,
            "supplier_ref": supplier_ref,
            "currency": currency,
            "net_amount": str(net),
            "tax_amount": str(tax),
            "gross_amount": str(gross),
            "issued_at": issued.isoformat(),
            "due_at": due.isoformat(),
            "evidence_id": evidence_id,
            "evidence_sha256": original.sha256,
            "lines": [
                {
                    **item,
                    "quantity": str(item["quantity"]),
                    "unit_price": str(item["unit_price"]),
                    "net_amount": str(item["net_amount"]),
                    "tax_amount": str(item["tax_amount"]),
                    "gross_amount": str(item["gross_amount"]),
                }
                for item in normalized_lines
            ],
            "scope": context["scope"],
        }
        payload_sha256 = self._hash(payload)
        now = datetime.now(UTC)
        scope_columns = {
            "tenant_ref": context["scope"]["tenant_ref"],
            "entity_ref": context["scope"]["entity_ref"],
            "store_ref": context["scope"]["store_ref"],
            "scope_grant_authority_sha256": context["scope"][
                "scope_grant_authority_sha256"
            ],
            "source_evidence_sha256": original.sha256,
            "scope_as_of": context["cutoff"],
        }
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            existing = session.scalar(
                select(SupplierInvoiceRow).where(
                    SupplierInvoiceRow.tenant_ref
                    == context["scope"]["tenant_ref"],
                    SupplierInvoiceRow.entity_ref
                    == context["scope"]["entity_ref"],
                    SupplierInvoiceRow.store_ref
                    == context["scope"]["store_ref"],
                    SupplierInvoiceRow.supplier_ref == supplier_ref,
                    SupplierInvoiceRow.invoice_ref == invoice_ref,
                )
            )
            if existing is not None:
                existing_lines = list(
                    session.scalars(
                        select(SupplierInvoiceLineRow)
                        .where(
                            SupplierInvoiceLineRow.invoice_id == existing.id
                        )
                        .order_by(
                            SupplierInvoiceLineRow.line_number,
                            SupplierInvoiceLineRow.id,
                        )
                    ).all()
                )
                if existing.payload_sha256 != payload_sha256:
                    raise ValueError(
                        "Supplier invoice identity conflicts with immutable values"
                    )
                return self._invoice(existing, existing_lines, idempotent=True)

            row = SupplierInvoiceRow(
                id=new_id("sinv"),
                invoice_ref=invoice_ref,
                purchase_order_id=purchase_order_id,
                supplier_ref=supplier_ref,
                currency=currency,
                net_amount=net,
                tax_amount=tax,
                gross_amount=gross,
                issued_at=issued,
                due_at=due,
                evidence_id=evidence_id,
                payload_sha256=payload_sha256,
                created_by=principal.actor_id,
                recorded_at=now,
                **scope_columns,
            )
            session.add(row)
            session.flush()
            line_rows = []
            for item in normalized_lines:
                line = SupplierInvoiceLineRow(
                    id=new_id("sinvl"),
                    invoice_id=row.id,
                    line_number=item["line_number"],
                    product_id=item["product_id"],
                    description=item["description"],
                    quantity=item["quantity"],
                    unit_price=item["unit_price"],
                    net_amount=item["net_amount"],
                    tax_amount=item["tax_amount"],
                    gross_amount=item["gross_amount"],
                    evidence_id=evidence_id,
                    recorded_at=now,
                    **scope_columns,
                )
                session.add(line)
                line_rows.append(line)
            session.flush()
            return self._invoice(row, line_rows, idempotent=False)

    def review_invoice(
        self,
        *,
        principal: Principal,
        invoice_id: str,
        accepted: bool,
        authentic_original: bool,
        legal_entity_matches: bool,
        supplier_matches: bool,
        purchase_order_matches: bool,
        receipt_inspection_matches: bool,
        line_quantity_price_matches: bool,
        currency_tax_total_matches: bool,
        rationale: str,
        idempotency_key: str,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        invoice_id = self._required(invoice_id, "invoice_id", 240)
        rationale = self._required(rationale, "rationale", 5000)
        idempotency_key = self._required(
            idempotency_key,
            "idempotency_key",
            300,
        )
        cutoff = parse_timestamp(
            as_of or datetime.now(UTC).isoformat(),
            "as_of",
        )
        with Session(self.engine) as session:
            invoice = session.get(SupplierInvoiceRow, invoice_id)
            if invoice is None or self._aware(invoice.recorded_at) > cutoff:
                raise KeyError(f"Unknown supplier invoice: {invoice_id}")
        if principal.tenant_ref != invoice.tenant_ref:
            raise PermissionError(
                "Authenticated identity is not authorized for supplier invoice"
            )
        if not principal.can_access_store(invoice.store_ref):
            raise PermissionError(
                "Authenticated identity is not authorized for store_ref"
            )
        if principal.actor_id == invoice.created_by:
            raise PermissionError(
                "Supplier invoice uploader cannot review their own invoice"
            )
        self.evidence.require_current(
            [invoice.evidence_id],
            as_of=cutoff,
        )
        original = self.evidence.get(invoice.evidence_id)
        if original.sha256 != invoice.source_evidence_sha256:
            raise ValueError("Supplier invoice Evidence hash has drifted")
        checks = {
            "authentic_original": authentic_original,
            "legal_entity_matches": legal_entity_matches,
            "supplier_matches": supplier_matches,
            "purchase_order_matches": purchase_order_matches,
            "receipt_inspection_matches": receipt_inspection_matches,
            "line_quantity_price_matches": line_quantity_price_matches,
            "currency_tax_total_matches": currency_tax_total_matches,
        }
        if accepted and not all(checks.values()):
            raise ValueError(
                "Accepted supplier invoice review requires every check to pass"
            )
        payload = {
            "contract_id": self.REVIEW_CONTRACT_ID,
            "invoice_id": invoice.id,
            "invoice_payload_sha256": invoice.payload_sha256,
            "invoice_evidence_id": invoice.evidence_id,
            "invoice_evidence_sha256": invoice.source_evidence_sha256,
            "tenant_ref": invoice.tenant_ref,
            "entity_ref": invoice.entity_ref,
            "store_ref": invoice.store_ref,
            "scope_grant_authority_sha256": (
                invoice.scope_grant_authority_sha256
            ),
            "decision": "accepted" if accepted else "rejected",
            "submitted_by": invoice.created_by,
            "reviewed_by": principal.actor_id,
            "rationale": rationale,
            "checks": checks,
        }
        content = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        source_ref = (
            f"supplier-invoice-review://{invoice.id}/"
            f"{principal.actor_id}/{idempotency_key}"
        )
        existing = self.evidence.find_by_source_ref(
            source=self.REVIEW_SOURCE,
            source_ref=source_ref,
        )
        if existing is not None:
            if (
                existing.sha256 != hashlib.sha256(content).hexdigest()
                or existing.created_by != principal.actor_id
                or existing.metadata != payload
            ):
                raise ValueError(
                    "Supplier invoice review idempotency key conflicts"
                )
            return {
                "invoice_id": invoice.id,
                "review_evidence_id": existing.id,
                "decision": payload["decision"],
                "idempotent": True,
            }
        review = self.evidence.capture(
            content=content,
            filename=f"{invoice.id}-authority-review.json",
            content_type="application/json",
            source=self.REVIEW_SOURCE,
            source_ref=source_ref,
            grade=EvidenceGrade.A,
            effective_at=cutoff.isoformat(),
            effective_until=None,
            created_by=principal.actor_id,
            metadata=payload,
        )
        self.evidence.link(
            evidence_id=review.id,
            target_type="supplier_invoice",
            target_id=invoice.id,
            relationship=self.REVIEW_RELATIONSHIP,
            created_by=principal.actor_id,
        )
        return {
            "invoice_id": invoice.id,
            "review_evidence_id": review.id,
            "decision": payload["decision"],
            "idempotent": False,
        }

    def read_scoped_sources(
        self,
        *,
        tenant_ref: str,
        entity_ref: str,
        store_ref: str,
        scope_grant_authority_sha256: str,
        as_of: str,
        max_invoices: int = 5000,
        max_lines: int = 20_000,
    ) -> dict[str, Any]:
        context = self._read_context(
            tenant_ref=tenant_ref,
            entity_ref=entity_ref,
            store_ref=store_ref,
            scope_grant_authority_sha256=scope_grant_authority_sha256,
            as_of=as_of,
        )
        if not 1 <= max_invoices <= 50_000:
            raise ValueError("max_invoices must be between 1 and 50000")
        if not 1 <= max_lines <= 100_000:
            raise ValueError("max_lines must be between 1 and 100000")
        cutoff = context["cutoff"]
        with Session(self.engine) as session:
            invoices = list(
                session.scalars(
                    select(SupplierInvoiceRow)
                    .where(
                        SupplierInvoiceRow.tenant_ref
                        == context["scope"]["tenant_ref"],
                        SupplierInvoiceRow.entity_ref
                        == context["scope"]["entity_ref"],
                        SupplierInvoiceRow.store_ref
                        == context["scope"]["store_ref"],
                        SupplierInvoiceRow.scope_grant_authority_sha256
                        == context["scope"][
                            "scope_grant_authority_sha256"
                        ],
                        SupplierInvoiceRow.issued_at <= cutoff,
                        SupplierInvoiceRow.recorded_at <= cutoff,
                        SupplierInvoiceRow.scope_as_of <= cutoff,
                    )
                    .order_by(
                        SupplierInvoiceRow.issued_at,
                        SupplierInvoiceRow.recorded_at,
                        SupplierInvoiceRow.id,
                    )
                    .limit(max_invoices + 1)
                ).all()
            )
            invoice_ids = [row.id for row in invoices[:max_invoices]]
            lines = (
                list(
                    session.scalars(
                        select(SupplierInvoiceLineRow)
                        .where(
                            SupplierInvoiceLineRow.invoice_id.in_(
                                invoice_ids
                            ),
                            SupplierInvoiceLineRow.tenant_ref
                            == context["scope"]["tenant_ref"],
                            SupplierInvoiceLineRow.entity_ref
                            == context["scope"]["entity_ref"],
                            SupplierInvoiceLineRow.store_ref
                            == context["scope"]["store_ref"],
                            SupplierInvoiceLineRow.scope_grant_authority_sha256
                            == context["scope"][
                                "scope_grant_authority_sha256"
                            ],
                            SupplierInvoiceLineRow.recorded_at <= cutoff,
                            SupplierInvoiceLineRow.scope_as_of <= cutoff,
                        )
                        .order_by(
                            SupplierInvoiceLineRow.invoice_id,
                            SupplierInvoiceLineRow.line_number,
                            SupplierInvoiceLineRow.id,
                        )
                        .limit(max_lines + 1)
                    ).all()
                )
                if invoice_ids
                else []
            )
        payload = {
            "contract_id": "kjds-scoped-accounts-payable-read-source-v1",
            "as_of": cutoff.isoformat(),
            "scope": context["scope"],
            "invoices": [
                self._invoice_source(row) for row in invoices[:max_invoices]
            ],
            "lines": [
                self._line_source(row) for row in lines[:max_lines]
            ],
            "truncated": {
                "invoices": len(invoices) > max_invoices,
                "lines": len(lines) > max_lines,
            },
        }
        payload["snapshot_sha256"] = self._hash(payload)
        return payload

    @classmethod
    def review_records(
        cls,
        *,
        invoice_id: str,
        evidence,
        as_of: datetime,
    ) -> dict[str, Any]:
        review_ids = evidence.target_evidence_ids(
            target_type="supplier_invoice",
            target_id=invoice_id,
            relationship=cls.REVIEW_RELATIONSHIP,
        )
        records = []
        invalid = []
        for review_id in review_ids:
            try:
                evidence.require_current([review_id], as_of=as_of)
                review = evidence.get(review_id)
                metadata = review.metadata
                if (
                    review.source != cls.REVIEW_SOURCE
                    or metadata.get("contract_id")
                    != cls.REVIEW_CONTRACT_ID
                    or metadata.get("invoice_id") != invoice_id
                    or metadata.get("reviewed_by") != review.created_by
                ):
                    raise ValueError("Review contract mismatch")
                records.append(
                    {
                        "id": review.id,
                        "recorded_at": review.recorded_at,
                        "effective_at": review.effective_at,
                        "created_by": review.created_by,
                        "metadata": metadata,
                    }
                )
            except (KeyError, RuntimeError, ValueError):
                invalid.append(review_id)
        records.sort(
            key=lambda item: (
                item["effective_at"],
                item["recorded_at"],
                item["id"],
            )
        )
        return {"records": records, "invalid_ids": sorted(invalid)}

    @classmethod
    def _context(
        cls,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: str | None,
    ) -> dict[str, Any]:
        store = cls._required(store_ref, "store_ref", 160)
        if not principal.can_access_store(store):
            raise PermissionError(
                "Authenticated identity is not authorized for store_ref"
            )
        entity_ref = str(entity_scope.get("entity_ref") or "").strip()
        authority = str(
            entity_scope.get("authority_sha256") or ""
        ).strip().lower()
        if (
            entity_scope.get("status") != "ready"
            or not entity_ref
            or not cls._sha256(authority)
        ):
            raise ValueError("Exact entity scope authority is required")
        cutoff = parse_timestamp(
            as_of or datetime.now(UTC).isoformat(),
            "as_of",
        )
        return {
            "cutoff": cutoff,
            "scope": {
                "tenant_ref": principal.tenant_ref,
                "entity_ref": entity_ref,
                "store_ref": store,
                "scope_grant_authority_sha256": authority,
            },
        }

    @classmethod
    def _read_context(
        cls,
        *,
        tenant_ref: str,
        entity_ref: str,
        store_ref: str,
        scope_grant_authority_sha256: str,
        as_of: str,
    ) -> dict[str, Any]:
        scope = {
            "tenant_ref": cls._required(tenant_ref, "tenant_ref", 160),
            "entity_ref": cls._required(entity_ref, "entity_ref", 160),
            "store_ref": cls._required(store_ref, "store_ref", 160),
            "scope_grant_authority_sha256": str(
                scope_grant_authority_sha256 or ""
            )
            .strip()
            .lower(),
        }
        if not cls._sha256(scope["scope_grant_authority_sha256"]):
            raise ValueError(
                "scope_grant_authority_sha256 must be SHA-256"
            )
        return {
            "scope": scope,
            "cutoff": parse_timestamp(as_of, "as_of"),
        }

    @classmethod
    def _lines(cls, values: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not values:
            raise ValueError("Supplier invoice requires at least one line")
        if len(values) > 1000:
            raise ValueError("Supplier invoice supports at most 1000 lines")
        result = []
        seen = set()
        for value in values:
            line_number = int(value.get("line_number", 0))
            if line_number < 1 or line_number in seen:
                raise ValueError(
                    "Supplier invoice line numbers must be unique positive integers"
                )
            seen.add(line_number)
            quantity = cls._positive(
                value.get("quantity"),
                "line quantity",
            )
            unit_price = cls._nonnegative(
                value.get("unit_price"),
                "line unit_price",
            )
            net_amount = cls._nonnegative(
                value.get("net_amount"),
                "line net_amount",
            )
            tax_amount = cls._nonnegative(
                value.get("tax_amount"),
                "line tax_amount",
            )
            gross_amount = cls._nonnegative(
                value.get("gross_amount"),
                "line gross_amount",
            )
            if net_amount + tax_amount != gross_amount:
                raise ValueError(
                    "Supplier invoice line amounts do not conserve"
                )
            result.append(
                {
                    "line_number": line_number,
                    "product_id": cls._required(
                        value.get("product_id"),
                        "line product_id",
                        240,
                    ),
                    "description": cls._required(
                        value.get("description"),
                        "line description",
                        5000,
                    ),
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "net_amount": net_amount,
                    "tax_amount": tax_amount,
                    "gross_amount": gross_amount,
                }
            )
        return sorted(result, key=lambda item: item["line_number"])

    @staticmethod
    def _required(value: Any, name: str, limit: int) -> str:
        result = str(value or "").strip()
        if not result or len(result) > limit:
            raise ValueError(f"{name} must be 1 to {limit} characters")
        return result

    @staticmethod
    def _decimal(value: Any, name: str) -> Decimal:
        try:
            result = Decimal(value)
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be numeric") from exc
        if not result.is_finite():
            raise ValueError(f"{name} must be finite")
        return result

    @classmethod
    def _positive(cls, value: Any, name: str) -> Decimal:
        result = cls._decimal(value, name)
        if result <= 0:
            raise ValueError(f"{name} must be positive")
        return result

    @classmethod
    def _nonnegative(cls, value: Any, name: str) -> Decimal:
        result = cls._decimal(value, name)
        if result < 0:
            raise ValueError(f"{name} must be nonnegative")
        return result

    @staticmethod
    def _currency(value: str) -> str:
        result = str(value or "").strip().upper()
        if len(result) != 3 or not result.isalpha() or not result.isascii():
            raise ValueError("currency must be a three-letter code")
        return result

    @staticmethod
    def _sha256(value: str) -> bool:
        return len(value) == 64 and all(
            character in "0123456789abcdef" for character in value
        )

    @staticmethod
    def _aware(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value

    @staticmethod
    def _hash(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()

    @classmethod
    def _invoice(
        cls,
        row: SupplierInvoiceRow,
        lines: list[SupplierInvoiceLineRow],
        *,
        idempotent: bool,
    ) -> dict[str, Any]:
        return {
            **cls._invoice_source(row),
            "lines": [cls._line_source(line) for line in lines],
            "idempotent": idempotent,
        }

    @classmethod
    def _invoice_source(cls, row: SupplierInvoiceRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "invoice_ref": row.invoice_ref,
            "purchase_order_id": row.purchase_order_id,
            "supplier_ref": row.supplier_ref,
            "currency": row.currency,
            "net_amount": str(row.net_amount),
            "tax_amount": str(row.tax_amount),
            "gross_amount": str(row.gross_amount),
            "issued_at": cls._aware(row.issued_at).isoformat(),
            "due_at": cls._aware(row.due_at).isoformat(),
            "evidence_id": row.evidence_id,
            "payload_sha256": row.payload_sha256,
            "created_by": row.created_by,
            "recorded_at": cls._aware(row.recorded_at).isoformat(),
            "source_evidence_sha256": row.source_evidence_sha256,
            "scope_as_of": cls._aware(row.scope_as_of).isoformat(),
        }

    @classmethod
    def _line_source(cls, row: SupplierInvoiceLineRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "invoice_id": row.invoice_id,
            "line_number": row.line_number,
            "product_id": row.product_id,
            "description": row.description,
            "quantity": str(row.quantity),
            "unit_price": str(row.unit_price),
            "net_amount": str(row.net_amount),
            "tax_amount": str(row.tax_amount),
            "gross_amount": str(row.gross_amount),
            "evidence_id": row.evidence_id,
            "recorded_at": cls._aware(row.recorded_at).isoformat(),
            "source_evidence_sha256": row.source_evidence_sha256,
            "scope_as_of": cls._aware(row.scope_as_of).isoformat(),
        }
