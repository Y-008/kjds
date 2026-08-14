from __future__ import annotations

import base64
import hashlib
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .accounts_payable import AccountsPayableAuthorityService
from .domain import ApprovalStatus
from .security import Principal


class ScopedAccountsPayableWorkspace:
    """Project invoice-to-payment authority without creating or paying."""

    CONTRACT_ID = "kjds-native-exact-scope-accounts-payable-workspace-v1"
    SOURCE_CONTRACT_ID = "kjds-scoped-accounts-payable-read-source-v1"
    FINANCE_SOURCE_CONTRACT_ID = "kjds-scoped-finance-read-source-v1"
    PROCUREMENT_CONTRACT_ID = (
        "kjds-native-exact-scope-procurement-receiving-workspace-v1"
    )
    ARTIFACT_CONTRACT_ID = "kjds-accounts-payable-agent-artifact-v1"
    STAGES = frozenset(
        {
            "invoice_captured",
            "review_pending",
            "rejected",
            "three_way_match_pending",
            "matched",
            "payment_approval_pending",
            "payment_permit_pending",
            "payment_readback_pending",
            "partially_paid",
            "settled",
            "variance",
            "blocked",
        }
    )

    def __init__(
        self,
        *,
        engine,
        accounts_payable,
        scoped_procurement_receiving,
        finance,
        repository,
        evidence,
        scoped_evidence,
    ) -> None:
        self.engine = engine
        self.accounts_payable = accounts_payable
        self.scoped_procurement_receiving = scoped_procurement_receiving
        self.finance = finance
        self.repository = repository
        self.evidence = evidence
        self.scoped_evidence = scoped_evidence

    def project(
        self,
        *,
        store_ref: str = "ozon-primary",
        principal: Principal | None = None,
        entity_scope: dict[str, Any] | None = None,
        as_of: str | None = None,
        query: str | None = None,
        stage: str | None = None,
        page_size: int = 25,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        context = self._context(
            store_ref=store_ref,
            principal=principal,
            entity_scope=entity_scope,
            as_of=as_of,
        )
        normalized_query = self._query(query)
        normalized_stage = self._stage(stage)
        normalized_page_size = self._page_size(page_size)
        normalized_cursor = str(cursor or "").strip() or None
        filters = {
            "query": normalized_query or None,
            "stage": normalized_stage,
        }
        if context["status"] != "ready":
            return self._empty(
                context=context,
                filters=filters,
                page_size=normalized_page_size,
                status=context["status"],
                reason=context["reason"],
            )

        source = self.accounts_payable.read_scoped_sources(
            tenant_ref=context["scope"]["tenant_ref"],
            entity_ref=context["scope"]["entity_ref"],
            store_ref=context["scope"]["store_ref"],
            scope_grant_authority_sha256=context["scope"][
                "scope_grant_authority_sha256"
            ],
            as_of=context["cutoff"].isoformat(),
        )
        source_issues = self._source_issues(source, context=context)
        if source_issues:
            return self._empty(
                context=context,
                filters=filters,
                page_size=normalized_page_size,
                status="blocked",
                reason=source_issues[0],
                extra_gaps=source_issues[1:],
                scoped_input_read=True,
                source_snapshot_sha256=source.get("snapshot_sha256"),
            )
        invoices = source["invoices"]
        if not invoices:
            return self._empty(
                context=context,
                filters=filters,
                page_size=normalized_page_size,
                status="no_data",
                reason="scoped_supplier_invoice_evidence_missing",
                scoped_input_read=True,
                source_snapshot_sha256=source["snapshot_sha256"],
            )

        finance_source = self.finance.read_scoped_sources(
            tenant_ref=context["scope"]["tenant_ref"],
            entity_ref=context["scope"]["entity_ref"],
            store_ref=context["scope"]["store_ref"],
            scope_grant_authority_sha256=context["scope"][
                "scope_grant_authority_sha256"
            ],
            as_of=context["cutoff"].isoformat(),
        )
        finance_issues = self._finance_source_issues(
            finance_source,
            context=context,
        )
        if finance_issues:
            return self._empty(
                context=context,
                filters=filters,
                page_size=normalized_page_size,
                status="blocked",
                reason=finance_issues[0],
                extra_gaps=finance_issues[1:],
                scoped_input_read=True,
                source_snapshot_sha256=self._hash(
                    {
                        "accounts_payable": source["snapshot_sha256"],
                        "finance": finance_source.get("snapshot_sha256"),
                    }
                ),
            )

        lines_by_invoice: dict[str, list[dict[str, Any]]] = defaultdict(
            list
        )
        invoice_ids = {str(item.get("id")) for item in invoices}
        orphan_lines = 0
        for line in source["lines"]:
            invoice_id = str(line.get("invoice_id") or "")
            if invoice_id not in invoice_ids:
                orphan_lines += 1
            else:
                lines_by_invoice[invoice_id].append(line)
        payments_by_invoice: dict[str, list[dict[str, Any]]] = defaultdict(
            list
        )
        for entry in finance_source["entries"]:
            invoice_id = str(entry.get("supplier_invoice_id") or "")
            if invoice_id:
                payments_by_invoice[invoice_id].append(entry)

        order_cache: dict[str, dict[str, Any]] = {}
        evidence_cache: dict[str, list[str]] = {}
        excluded_reasons: Counter[str] = Counter()
        if orphan_lines:
            excluded_reasons[
                "supplier_invoice_line_header_scope_conflict"
            ] += orphan_lines
        rows = []
        for invoice in invoices:
            invoice_id = str(invoice.get("id") or "")
            row, issues = self._project_invoice(
                invoice=invoice,
                lines=lines_by_invoice.get(invoice_id, []),
                payments=payments_by_invoice.get(invoice_id, []),
                context=context,
                order_cache=order_cache,
                evidence_cache=evidence_cache,
            )
            if issues:
                excluded_reasons.update(set(issues))
                continue
            if row is None:
                excluded_reasons[
                    "accounts_payable_projection_failed_closed"
                ] += 1
                continue
            if normalized_query and not self._matches_query(
                row,
                normalized_query,
            ):
                continue
            if normalized_stage and row["stage"] != normalized_stage:
                continue
            rows.append(row)

        rows.sort(
            key=lambda item: (
                item["issued_at"],
                item["invoice_id"],
            ),
            reverse=True,
        )
        counts = self._counts(rows)
        page, next_cursor = self._paginate(
            rows,
            page_size=normalized_page_size,
            cursor=normalized_cursor,
        )
        source_gaps = sorted(excluded_reasons)
        status = (
            "blocked"
            if excluded_reasons and not rows
            else "partial"
            if excluded_reasons
            else "ready"
        )
        return self._payload(
            context=context,
            status=status,
            filters=filters,
            page_size=normalized_page_size,
            total_filtered=len(rows),
            next_cursor=next_cursor,
            invoices=page,
            counts=counts,
            excluded={
                "count": sum(excluded_reasons.values()),
                "reason_counts": dict(sorted(excluded_reasons.items())),
                "business_values_exposed": False,
            },
            source_gaps=source_gaps,
            source_snapshot_sha256=self._hash(
                {
                    "accounts_payable": source["snapshot_sha256"],
                    "finance": finance_source["snapshot_sha256"],
                    "procurement": sorted(
                        (
                            key,
                            value.get("snapshot_sha256"),
                        )
                        for key, value in order_cache.items()
                    ),
                }
            ),
        )

    def _project_invoice(
        self,
        *,
        invoice: dict[str, Any],
        lines: list[dict[str, Any]],
        payments: list[dict[str, Any]],
        context: dict[str, Any],
        order_cache: dict[str, dict[str, Any]],
        evidence_cache: dict[str, list[str]],
    ) -> tuple[dict[str, Any] | None, list[str]]:
        issues = self._invoice_issues(
            invoice,
            lines=lines,
            context=context,
            evidence_cache=evidence_cache,
        )
        order_projection = None
        order = None
        purchase_order_id = str(invoice.get("purchase_order_id") or "")
        if not issues:
            order_projection = order_cache.get(purchase_order_id)
            if order_projection is None:
                order_projection = (
                    self.scoped_procurement_receiving.project(
                        principal=context["principal"],
                        entity_scope=context["entity_scope"],
                        store_ref=context["scope"]["store_ref"],
                        as_of=context["cutoff"].isoformat(),
                        query=purchase_order_id,
                        page_size=100,
                    )
                )
                order_cache[purchase_order_id] = order_projection
            issues.extend(
                self._procurement_issues(
                    order_projection,
                    purchase_order_id=purchase_order_id,
                    context=context,
                )
            )
            order = next(
                (
                    item
                    for item in order_projection.get("orders", [])
                    if item.get("purchase_order_id")
                    == purchase_order_id
                ),
                None,
            )
            if order is None:
                issues.append("supplier_invoice_purchase_order_missing")
        review = self._review_state(
            invoice=invoice,
            context=context,
            evidence_cache=evidence_cache,
        )
        issues.extend(review["issues"])
        if issues:
            return None, sorted(set(issues))
        if order is None:
            return None, ["supplier_invoice_purchase_order_missing"]

        match = self._three_way_match(
            invoice=invoice,
            lines=lines,
            order=order,
        )
        payment = self._payment_state(
            invoice=invoice,
            payments=payments,
            context=context,
            evidence_cache=evidence_cache,
        )
        if payment["issues"]:
            return None, sorted(set(payment["issues"]))
        stage = self._stage_for(
            review=review,
            match=match,
            payment=payment,
        )
        gross = self._decimal(invoice["gross_amount"], "gross_amount")
        paid = payment["paid_amount"]
        return (
            {
                "invoice_id": str(invoice["id"]),
                "invoice_ref": str(invoice["invoice_ref"]),
                "purchase_order_id": purchase_order_id,
                "supplier_ref": str(invoice["supplier_ref"]),
                "currency": str(invoice["currency"]),
                "issued_at": str(invoice["issued_at"]),
                "due_at": str(invoice["due_at"]),
                "recorded_at": str(invoice["recorded_at"]),
                "amounts": {
                    "net": self._decimal_text(
                        self._decimal(invoice["net_amount"], "net_amount")
                    ),
                    "tax": self._decimal_text(
                        self._decimal(invoice["tax_amount"], "tax_amount")
                    ),
                    "gross": self._decimal_text(gross),
                    "paid": self._decimal_text(paid),
                    "open": self._decimal_text(max(gross - paid, Decimal(0))),
                    "client_recalculation_allowed": False,
                },
                "lines": lines,
                "stage": stage,
                "review": {
                    "status": review["status"],
                    "review_evidence_id": review["review_evidence_id"],
                    "reviewed_by": review["reviewed_by"],
                    "independent": review["independent"],
                    "checks": review["checks"],
                },
                "three_way_match": match,
                "procurement": {
                    "stage": order["stage"],
                    "product": order["product"],
                    "ordered_quantity": order["quantity"],
                    "unit_price": order["unit_price"],
                    "order_value": order["order_value"],
                    "receipt": order["receipt"],
                    "decision_basis": order["decision_basis"],
                },
                "payment_control": {
                    "status": payment["status"],
                    "approval_id": payment["approval_id"],
                    "command_id": payment["command_id"],
                    "receipt_id": payment["receipt_id"],
                    "bank_entry_ids": payment["bank_entry_ids"],
                    "one_time_permit_verified": payment[
                        "one_time_permit_verified"
                    ],
                    "readback_verified": payment["readback_verified"],
                    "adapter_enabled": False,
                    "payment_execution_available": False,
                },
                "evidence": {
                    "invoice_evidence_id": str(invoice["evidence_id"]),
                    "invoice_evidence_sha256": str(
                        invoice["source_evidence_sha256"]
                    ),
                    "payload_sha256": str(invoice["payload_sha256"]),
                    "payment_evidence_ids": payment[
                        "payment_evidence_ids"
                    ],
                },
                "owner": self._owner(stage),
                "sla": self._sla(stage),
                "next": self._next(stage),
                "next_workspace": "/accounts-payable",
            },
            [],
        )

    def _invoice_issues(
        self,
        invoice: dict[str, Any],
        *,
        lines: list[dict[str, Any]],
        context: dict[str, Any],
        evidence_cache: dict[str, list[str]],
    ) -> list[str]:
        issues = []
        required = (
            "id",
            "invoice_ref",
            "purchase_order_id",
            "supplier_ref",
            "currency",
            "evidence_id",
            "payload_sha256",
            "source_evidence_sha256",
        )
        if any(not str(invoice.get(key) or "").strip() for key in required):
            issues.append("supplier_invoice_identity_incomplete")
        try:
            net = self._decimal(invoice.get("net_amount"), "net_amount")
            tax = self._decimal(invoice.get("tax_amount"), "tax_amount")
            gross = self._decimal(
                invoice.get("gross_amount"),
                "gross_amount",
            )
            if net < 0 or tax < 0 or gross <= 0 or net + tax != gross:
                raise ValueError
        except (InvalidOperation, TypeError, ValueError):
            issues.append("supplier_invoice_header_amount_invalid")
        if not self._currency(invoice.get("currency")):
            issues.append("supplier_invoice_currency_invalid")
        issues.extend(
            self._temporal_issues(
                invoice,
                fields=(
                    "issued_at",
                    "recorded_at",
                    "scope_as_of",
                ),
                context=context,
                prefix="supplier_invoice",
            )
        )
        if not self._sha256(str(invoice.get("payload_sha256") or "")):
            issues.append("supplier_invoice_payload_hash_invalid")
        try:
            issued = self._timestamp(invoice.get("issued_at"), "issued_at")
            due = self._timestamp(invoice.get("due_at"), "due_at")
            if due < issued:
                issues.append("supplier_invoice_date_order_invalid")
        except ValueError:
            issues.append("supplier_invoice_due_at_invalid")
        issues.extend(
            self._evidence_issues(
                evidence_id=invoice.get("evidence_id"),
                source_sha256=invoice.get("source_evidence_sha256"),
                context=context,
                prefix="supplier_invoice",
                evidence_cache=evidence_cache,
            )
        )
        if not lines:
            issues.append("supplier_invoice_lines_missing")
        expected_numbers = list(range(1, len(lines) + 1))
        actual_numbers = sorted(
            int(item.get("line_number", 0)) for item in lines
        )
        if actual_numbers != expected_numbers:
            issues.append("supplier_invoice_line_sequence_invalid")
        line_net = Decimal(0)
        line_tax = Decimal(0)
        line_gross = Decimal(0)
        seen_products = set()
        for line in lines:
            if line.get("invoice_id") != invoice.get("id"):
                issues.append("supplier_invoice_line_header_conflict")
            try:
                quantity = self._decimal(
                    line.get("quantity"),
                    "line quantity",
                )
                unit_price = self._decimal(
                    line.get("unit_price"),
                    "line unit_price",
                )
                net_amount = self._decimal(
                    line.get("net_amount"),
                    "line net_amount",
                )
                tax_amount = self._decimal(
                    line.get("tax_amount"),
                    "line tax_amount",
                )
                gross_amount = self._decimal(
                    line.get("gross_amount"),
                    "line gross_amount",
                )
                if (
                    quantity <= 0
                    or unit_price < 0
                    or net_amount < 0
                    or tax_amount < 0
                    or gross_amount < 0
                    or net_amount + tax_amount != gross_amount
                ):
                    raise ValueError
                line_net += net_amount
                line_tax += tax_amount
                line_gross += gross_amount
            except (InvalidOperation, TypeError, ValueError):
                issues.append("supplier_invoice_line_amount_invalid")
            product_id = str(line.get("product_id") or "")
            if not product_id or product_id in seen_products:
                issues.append("supplier_invoice_line_product_invalid")
            seen_products.add(product_id)
            issues.extend(
                self._temporal_issues(
                    line,
                    fields=("recorded_at", "scope_as_of"),
                    context=context,
                    prefix="supplier_invoice_line",
                )
            )
            issues.extend(
                self._evidence_issues(
                    evidence_id=line.get("evidence_id"),
                    source_sha256=line.get("source_evidence_sha256"),
                    context=context,
                    prefix="supplier_invoice_line",
                    evidence_cache=evidence_cache,
                )
            )
        try:
            if (
                line_net
                != self._decimal(invoice.get("net_amount"), "net_amount")
                or line_tax
                != self._decimal(invoice.get("tax_amount"), "tax_amount")
                or line_gross
                != self._decimal(invoice.get("gross_amount"), "gross_amount")
            ):
                issues.append("supplier_invoice_line_header_not_conserved")
        except (InvalidOperation, TypeError, ValueError):
            pass
        return sorted(set(issues))

    def _review_state(
        self,
        *,
        invoice: dict[str, Any],
        context: dict[str, Any],
        evidence_cache: dict[str, list[str]],
    ) -> dict[str, Any]:
        records = AccountsPayableAuthorityService.review_records(
            invoice_id=str(invoice["id"]),
            evidence=self.evidence,
            as_of=context["cutoff"],
        )
        issues = []
        if records["invalid_ids"]:
            issues.append("supplier_invoice_latest_review_evidence_invalid")
        if not records["records"]:
            return {
                "status": "pending",
                "review_evidence_id": None,
                "reviewed_by": None,
                "independent": False,
                "checks": {},
                "issues": issues,
            }
        latest = records["records"][-1]
        metadata = latest["metadata"]
        issues.extend(
            self._evidence_issues(
                evidence_id=latest["id"],
                source_sha256=None,
                context=context,
                prefix="supplier_invoice_review",
                evidence_cache=evidence_cache,
                accept_record_hash=True,
            )
        )
        expected = {
            "invoice_payload_sha256": invoice.get("payload_sha256"),
            "invoice_evidence_id": invoice.get("evidence_id"),
            "invoice_evidence_sha256": invoice.get(
                "source_evidence_sha256"
            ),
            "tenant_ref": context["scope"]["tenant_ref"],
            "entity_ref": context["scope"]["entity_ref"],
            "store_ref": context["scope"]["store_ref"],
            "scope_grant_authority_sha256": context["scope"][
                "scope_grant_authority_sha256"
            ],
            "submitted_by": invoice.get("created_by"),
        }
        if any(metadata.get(key) != value for key, value in expected.items()):
            issues.append("supplier_invoice_review_binding_conflict")
        checks = metadata.get("checks")
        expected_checks = {
            "authentic_original",
            "legal_entity_matches",
            "supplier_matches",
            "purchase_order_matches",
            "receipt_inspection_matches",
            "line_quantity_price_matches",
            "currency_tax_total_matches",
        }
        if (
            not isinstance(checks, dict)
            or set(checks) != expected_checks
            or any(not isinstance(value, bool) for value in checks.values())
        ):
            issues.append("supplier_invoice_review_checks_invalid")
            checks = {}
        decision = metadata.get("decision")
        if decision not in {"accepted", "rejected"}:
            issues.append("supplier_invoice_review_decision_invalid")
        if decision == "accepted" and (
            not checks or not all(checks.values())
        ):
            issues.append("supplier_invoice_review_acceptance_invalid")
        independent = bool(
            latest["created_by"]
            and latest["created_by"] != invoice.get("created_by")
            and latest["created_by"] == metadata.get("reviewed_by")
        )
        if not independent:
            issues.append("supplier_invoice_review_not_independent")
        return {
            "status": decision or "invalid",
            "review_evidence_id": latest["id"],
            "reviewed_by": latest["created_by"],
            "independent": independent,
            "checks": checks,
            "issues": sorted(set(issues)),
        }

    def _three_way_match(
        self,
        *,
        invoice: dict[str, Any],
        lines: list[dict[str, Any]],
        order: dict[str, Any],
    ) -> dict[str, Any]:
        checks = {
            "supplier_matches": (
                invoice["supplier_ref"] == order["supplier_ref"]
            ),
            "currency_matches": (
                invoice["currency"] == order["currency"]
            ),
            "single_product_order": len(lines) == 1,
            "product_matches": False,
            "quantity_matches": False,
            "unit_price_matches": False,
            "line_extension_matches": False,
            "received_quantity_covers_invoice": False,
            "inspected_quantity_covers_invoice": False,
            "passed_quantity_covers_invoice": False,
        }
        if lines:
            line = lines[0]
            quantity = self._decimal(line["quantity"], "line quantity")
            unit_price = self._decimal(
                line["unit_price"],
                "line unit_price",
            )
            line_net = self._decimal(
                line["net_amount"],
                "line net_amount",
            )
            order_quantity = Decimal(order["quantity"])
            order_unit_price = self._decimal(
                order["unit_price"],
                "order unit_price",
            )
            checks["product_matches"] = (
                line["product_id"] == order["product"]["id"]
            )
            checks["quantity_matches"] = quantity == order_quantity
            checks["unit_price_matches"] = unit_price == order_unit_price
            checks["line_extension_matches"] = (
                line_net == quantity * unit_price
            )
            receipt = order.get("receipt") or {}
            checks["received_quantity_covers_invoice"] = (
                receipt.get("received_quantity") is not None
                and Decimal(receipt["received_quantity"]) >= quantity
            )
            checks["inspected_quantity_covers_invoice"] = (
                receipt.get("inspected_quantity") is not None
                and Decimal(receipt["inspected_quantity"]) >= quantity
            )
            checks["passed_quantity_covers_invoice"] = (
                receipt.get("passed_quantity") is not None
                and Decimal(receipt["passed_quantity"]) >= quantity
            )
        matched = all(checks.values())
        return {
            "status": "matched" if matched else "pending",
            "matched": matched,
            "checks": checks,
            "server_authoritative": True,
        }

    def _payment_state(
        self,
        *,
        invoice: dict[str, Any],
        payments: list[dict[str, Any]],
        context: dict[str, Any],
        evidence_cache: dict[str, list[str]],
    ) -> dict[str, Any]:
        if not payments:
            return {
                "status": "not_paid",
                "paid_amount": Decimal(0),
                "approval_id": None,
                "command_id": None,
                "receipt_id": None,
                "bank_entry_ids": [],
                "payment_evidence_ids": [],
                "one_time_permit_verified": False,
                "readback_verified": False,
                "issues": [],
            }
        issues = []
        paid = Decimal(0)
        approval_ids = set()
        command_ids = set()
        receipt_ids = set()
        bank_ids = []
        evidence_ids = []
        permits_verified = True
        readbacks_verified = True
        for entry in sorted(
            payments,
            key=lambda item: (
                item.get("effective_at") or "",
                item.get("recorded_at") or "",
                item.get("id") or "",
            ),
        ):
            binding_issues, authority = self._payment_entry_issues(
                entry=entry,
                invoice=invoice,
                context=context,
                evidence_cache=evidence_cache,
            )
            issues.extend(binding_issues)
            if binding_issues:
                permits_verified = False
                readbacks_verified = False
                continue
            amount = self._decimal(entry["amount"], "payment amount")
            paid += abs(amount)
            approval_ids.add(str(entry["payment_approval_id"]))
            command_ids.add(str(entry["payment_command_id"]))
            receipt_ids.add(str(authority["receipt_id"]))
            bank_ids.append(str(entry["id"]))
            evidence_ids.extend(authority["evidence_ids"])
        gross = self._decimal(invoice["gross_amount"], "gross_amount")
        if paid > gross:
            issues.append("supplier_invoice_payment_overallocated")
        return {
            "status": (
                "variance"
                if paid > gross
                else "settled"
                if paid == gross
                else "partially_paid"
                if paid > 0
                else "not_paid"
            ),
            "paid_amount": paid,
            "approval_id": (
                next(iter(approval_ids)) if len(approval_ids) == 1 else None
            ),
            "command_id": (
                next(iter(command_ids)) if len(command_ids) == 1 else None
            ),
            "receipt_id": (
                next(iter(receipt_ids)) if len(receipt_ids) == 1 else None
            ),
            "bank_entry_ids": sorted(bank_ids),
            "payment_evidence_ids": sorted(set(evidence_ids)),
            "one_time_permit_verified": (
                permits_verified and bool(command_ids)
            ),
            "readback_verified": readbacks_verified and bool(bank_ids),
            "issues": sorted(set(issues)),
        }

    def _payment_entry_issues(
        self,
        *,
        entry: dict[str, Any],
        invoice: dict[str, Any],
        context: dict[str, Any],
        evidence_cache: dict[str, list[str]],
    ) -> tuple[list[str], dict[str, Any]]:
        issues = []
        if (
            entry.get("supplier_invoice_id") != invoice.get("id")
            or entry.get("supplier_ref") != invoice.get("supplier_ref")
            or entry.get("entry_kind") != "bank_payment"
            or entry.get("profit_cost_type") != "product_cost"
            or entry.get("currency") != invoice.get("currency")
        ):
            issues.append("supplier_invoice_payment_binding_conflict")
        try:
            if self._decimal(entry.get("amount"), "payment amount") >= 0:
                issues.append("supplier_invoice_payment_amount_invalid")
        except ValueError:
            issues.append("supplier_invoice_payment_amount_invalid")
        issues.extend(
            self._temporal_issues(
                entry,
                fields=(
                    "effective_at",
                    "recorded_at",
                    "scope_as_of",
                ),
                context=context,
                prefix="supplier_invoice_payment",
            )
        )
        issues.extend(
            self._evidence_issues(
                evidence_id=entry.get("evidence_id"),
                source_sha256=entry.get("source_evidence_sha256"),
                context=context,
                prefix="supplier_invoice_payment",
                evidence_cache=evidence_cache,
            )
        )
        approval_id = str(entry.get("payment_approval_id") or "")
        command_id = str(entry.get("payment_command_id") or "")
        authority = {
            "receipt_id": None,
            "evidence_ids": [str(entry.get("evidence_id") or "")],
        }
        if not approval_id or not command_id:
            issues.append("supplier_invoice_payment_authority_incomplete")
            return sorted(set(issues)), authority
        try:
            approval = self.repository.get_approval_at(
                approval_id,
                as_of=context["cutoff"],
            )
            if (
                approval.status is not ApprovalStatus.APPROVED
                or approval.action != "finance.pay_supplier_invoice"
                or approval.resource_type != "supplier_invoice"
                or approval.resource_id != invoice.get("id")
                or not approval.decided_by
                or approval.requested_by == approval.decided_by
            ):
                issues.append("supplier_invoice_payment_approval_invalid")
            payload = approval.payload
            expected_payload = {
                "supplier_invoice_id": invoice.get("id"),
                "supplier_ref": invoice.get("supplier_ref"),
                "currency": invoice.get("currency"),
            }
            if any(
                payload.get(key) != value
                for key, value in expected_payload.items()
            ):
                issues.append(
                    "supplier_invoice_payment_approval_payload_conflict"
                )
            approved_amount = self._decimal(
                payload.get("amount"),
                "approved amount",
            )
            if approved_amount != abs(
                self._decimal(entry.get("amount"), "payment amount")
            ):
                issues.append(
                    "supplier_invoice_payment_approval_amount_conflict"
                )
        except (KeyError, RuntimeError, ValueError):
            issues.append("supplier_invoice_payment_approval_missing")

        from .execution_plans import ExecutionPlanRow
        from .limited_executor import (
            LimitedExecutionCommandRow,
            LimitedExecutionReceiptRow,
        )

        with Session(self.engine) as session:
            command = session.get(LimitedExecutionCommandRow, command_id)
            receipt = session.scalar(
                select(LimitedExecutionReceiptRow).where(
                    LimitedExecutionReceiptRow.command_id == command_id
                )
            )
            plan = (
                session.get(ExecutionPlanRow, command.plan_id)
                if command is not None
                else None
            )
        if command is None or plan is None:
            issues.append("supplier_invoice_payment_permit_missing")
            return sorted(set(issues)), authority
        if (
            command.command_kind != "execute"
            or command.action_id != "supplier_payment"
            or command.operation != "finance.pay_supplier_invoice"
            or command.target_json.get("supplier_invoice_id")
            != invoice.get("id")
            or command.status != "succeeded"
            or len(command.decision_hash) != 64
            or len(command.authorization_hash) != 64
            or approval_id
            not in {plan.source_approval_id, plan.approval_id}
        ):
            issues.append("supplier_invoice_payment_permit_invalid")
        if (
            receipt is None
            or receipt.outcome != "succeeded"
            or not receipt.mutation_applied
            or not receipt.resulting_state_hash
            or self._aware(receipt.recorded_at) > context["cutoff"]
            or self._aware(receipt.recorded_at)
            > self._aware(command.permit_expires_at)
        ):
            issues.append("supplier_invoice_payment_readback_invalid")
            return sorted(set(issues)), authority
        authority["receipt_id"] = receipt.id
        receipt_evidence = [
            str(item) for item in receipt.evidence_json if str(item).strip()
        ]
        if not receipt_evidence:
            issues.append("supplier_invoice_payment_readback_evidence_missing")
        for evidence_id in receipt_evidence:
            issues.extend(
                self._evidence_issues(
                    evidence_id=evidence_id,
                    source_sha256=None,
                    context=context,
                    prefix="supplier_invoice_payment_readback",
                    evidence_cache=evidence_cache,
                    accept_record_hash=True,
                )
            )
        authority["evidence_ids"].extend(receipt_evidence)
        return sorted(set(issues)), authority

    @staticmethod
    def _stage_for(
        *,
        review: dict[str, Any],
        match: dict[str, Any],
        payment: dict[str, Any],
    ) -> str:
        if review["status"] == "pending":
            return "review_pending"
        if review["status"] == "rejected":
            return "rejected"
        if not match["matched"]:
            return "three_way_match_pending"
        if payment["status"] == "variance":
            return "variance"
        if payment["status"] == "settled":
            return "settled"
        if payment["status"] == "partially_paid":
            return "partially_paid"
        if not payment["approval_id"]:
            return "payment_approval_pending"
        if not payment["command_id"]:
            return "payment_permit_pending"
        return "payment_readback_pending"

    def _procurement_issues(
        self,
        projection: dict[str, Any],
        *,
        purchase_order_id: str,
        context: dict[str, Any],
    ) -> list[str]:
        issues = []
        if projection.get("contract_id") != self.PROCUREMENT_CONTRACT_ID:
            issues.append("supplier_invoice_procurement_contract_conflict")
        if projection.get("as_of") != context["cutoff"].isoformat():
            issues.append("supplier_invoice_procurement_as_of_conflict")
        if projection.get("scope") != context["scope"]:
            issues.append("supplier_invoice_procurement_scope_conflict")
        if not self._valid_snapshot(projection):
            issues.append("supplier_invoice_procurement_snapshot_hash_drift")
        orders = projection.get("orders")
        if not isinstance(orders, list):
            issues.append("supplier_invoice_procurement_payload_invalid")
            return sorted(set(issues))
        matches = [
            item
            for item in orders
            if item.get("purchase_order_id") == purchase_order_id
        ]
        if len(matches) != 1:
            issues.append("supplier_invoice_procurement_exact_order_missing")
        if projection.get("status") in {"blocked", "no_data"}:
            issues.append("supplier_invoice_procurement_authority_blocked")
        return sorted(set(issues))

    def _source_issues(
        self,
        source: dict[str, Any],
        *,
        context: dict[str, Any],
    ) -> list[str]:
        issues = []
        if source.get("contract_id") != self.SOURCE_CONTRACT_ID:
            issues.append("accounts_payable_source_contract_conflict")
        if source.get("as_of") != context["cutoff"].isoformat():
            issues.append("accounts_payable_source_as_of_conflict")
        if source.get("scope") != context["scope"]:
            issues.append("accounts_payable_source_scope_conflict")
        if not isinstance(source.get("invoices"), list) or not isinstance(
            source.get("lines"),
            list,
        ):
            issues.append("accounts_payable_source_payload_invalid")
        if any((source.get("truncated") or {}).values()):
            issues.append("accounts_payable_source_truncated")
        if not self._valid_snapshot(source):
            issues.append("accounts_payable_source_snapshot_hash_drift")
        return sorted(set(issues))

    def _finance_source_issues(
        self,
        source: dict[str, Any],
        *,
        context: dict[str, Any],
    ) -> list[str]:
        issues = []
        if source.get("contract_id") != self.FINANCE_SOURCE_CONTRACT_ID:
            issues.append("accounts_payable_finance_contract_conflict")
        if source.get("as_of") != context["cutoff"].isoformat():
            issues.append("accounts_payable_finance_as_of_conflict")
        if source.get("scope") != context["scope"]:
            issues.append("accounts_payable_finance_scope_conflict")
        if not isinstance(source.get("entries"), list):
            issues.append("accounts_payable_finance_payload_invalid")
        if any((source.get("truncated") or {}).values()):
            issues.append("accounts_payable_finance_source_truncated")
        if not self._valid_snapshot(source):
            issues.append("accounts_payable_finance_snapshot_hash_drift")
        return sorted(set(issues))

    def _evidence_issues(
        self,
        *,
        evidence_id: Any,
        source_sha256: Any,
        context: dict[str, Any],
        prefix: str,
        evidence_cache: dict[str, list[str]],
        accept_record_hash: bool = False,
    ) -> list[str]:
        reference = str(evidence_id or "").strip()
        source_hash = str(source_sha256 or "").strip().lower()
        cache_key = (
            f"{reference}:{source_hash}:{accept_record_hash}:{prefix}"
        )
        if cache_key in evidence_cache:
            return evidence_cache[cache_key]
        issues = []
        if not reference or (
            not accept_record_hash and not self._sha256(source_hash)
        ):
            issues.append(f"{prefix}_evidence_reference_invalid")
        else:
            try:
                verification = self.evidence.verify(reference)
                if not verification.valid or (
                    not accept_record_hash
                    and verification.expected_sha256 != source_hash
                ):
                    issues.append(f"{prefix}_evidence_invalid")
                projection = self.scoped_evidence.project_targets(
                    evidence_ids=[reference],
                    principal=context["principal"],
                    entity_scope=context["entity_scope"],
                    store_ref=context["scope"]["store_ref"],
                    as_of=context["cutoff"],
                )
                target = next(
                    (
                        item
                        for item in projection.get("records", [])
                        if item.get("evidence_id", item.get("id"))
                        == reference
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
                    issues.append(f"{prefix}_evidence_scope_invalid")
            except (KeyError, RuntimeError, ValueError):
                issues.append(f"{prefix}_evidence_invalid")
        result = sorted(set(issues))
        evidence_cache[cache_key] = result
        return result

    def _payload(
        self,
        *,
        context: dict[str, Any],
        status: str,
        filters: dict[str, Any],
        page_size: int,
        total_filtered: int,
        next_cursor: str | None,
        invoices: list[dict[str, Any]],
        counts: dict[str, int],
        excluded: dict[str, Any],
        source_gaps: list[str],
        source_snapshot_sha256: str | None,
        scoped_input_read: bool = True,
    ) -> dict[str, Any]:
        gaps = sorted(set(source_gaps))
        core = {
            "contract_id": self.CONTRACT_ID,
            "status": status,
            "as_of": context["cutoff"].isoformat(),
            "scope": context["scope"],
            "filters": filters,
            "counts": {
                **counts,
                "filtered": total_filtered,
                "page": len(invoices),
            },
            "pagination": {
                "page_size": page_size,
                "next_cursor": next_cursor,
            },
            "invoices": invoices,
            "excluded": excluded,
            "source_gaps": gaps,
            "blockers": self._blockers(gaps),
            "owner": "accounts-payable-control",
            "sla": "before invoice acceptance, payment approval or cash booking",
            "next": (
                "Capture and independently review exact-scope supplier "
                "invoice Evidence, then satisfy three-way match. External "
                "supplier payment remains gated."
            ),
            "next_workspace": "/accounts-payable",
            "upstream": {
                "source_snapshot_sha256": source_snapshot_sha256,
            },
            "control_envelope": {
                "read_only_projection": True,
                "scoped_input_read": scoped_input_read,
                "client_recalculation_allowed": False,
                "legacy_invoice_rows_admitted": False,
                "invoice_created": False,
                "invoice_review_created": False,
                "approval_created": False,
                "permit_created": False,
                "payment_initiated": False,
                "bank_entry_created": False,
                "external_write_allowed": False,
                "private_erp_interface_allowed": False,
            },
        }
        input_hash = self._hash(core)
        artifact = {
            "contract_id": self.ARTIFACT_CONTRACT_ID,
            "version": "1",
            "scope": context["scope"],
            "as_of": context["cutoff"].isoformat(),
            "input_snapshot_sha256": input_hash,
            "suggestions": [
                {
                    "type": "internal_task_suggestion",
                    "code": gap,
                    "owner": "accounts-payable-control",
                    "next_workspace": "/accounts-payable",
                }
                for gap in gaps
            ],
            "authority": (
                "decision_support_and_internal_task_suggestion_only"
            ),
            "owner": "accounts-payable-control",
            "self_approval_allowed": False,
            "permit_issue_allowed": False,
            "invoice_creation_allowed": False,
            "payment_allowed": False,
            "external_write_allowed": False,
        }
        core["agent_artifact"] = {
            **artifact,
            "artifact_sha256": self._hash(artifact),
        }
        core["snapshot_sha256"] = self._hash(core)
        return core

    def _empty(
        self,
        *,
        context: dict[str, Any],
        filters: dict[str, Any],
        page_size: int,
        status: str,
        reason: str,
        extra_gaps: list[str] | None = None,
        scoped_input_read: bool = False,
        source_snapshot_sha256: str | None = None,
    ) -> dict[str, Any]:
        return self._payload(
            context=context,
            status=status,
            filters=filters,
            page_size=page_size,
            total_filtered=0,
            next_cursor=None,
            invoices=[],
            counts=self._counts([]),
            excluded={
                "count": 0,
                "reason_counts": {},
                "business_values_exposed": False,
            },
            source_gaps=[reason, *(extra_gaps or [])],
            source_snapshot_sha256=source_snapshot_sha256,
            scoped_input_read=scoped_input_read,
        )

    @classmethod
    def _context(
        cls,
        *,
        store_ref: str,
        principal: Principal | None,
        entity_scope: dict[str, Any] | None,
        as_of: str | None,
    ) -> dict[str, Any]:
        store = str(store_ref or "").strip()
        if not store or len(store) > 160:
            raise ValueError("store_ref must be 1 to 160 characters")
        cutoff = cls._timestamp(
            as_of or datetime.now(UTC).isoformat(),
            "as_of",
        )
        if principal is not None and not principal.can_access_store(store):
            raise PermissionError(
                "Authenticated identity is not authorized for store_ref"
            )
        scope = entity_scope or {
            "status": "no_data",
            "entity_ref": None,
            "reason": "entity_scope_authority_missing",
        }
        authority = str(scope.get("authority_sha256") or "").strip()
        ready = bool(
            principal is not None
            and scope.get("status") == "ready"
            and str(scope.get("entity_ref") or "").strip()
            and cls._sha256(authority)
        )
        malformed_ready = bool(
            scope.get("status") == "ready" and not ready
        )
        return {
            "status": (
                "ready"
                if ready
                else "blocked"
                if malformed_ready
                else "no_data"
            ),
            "reason": (
                "accounts_payable_scope_authority_invalid"
                if malformed_ready
                else str(
                    scope.get("reason")
                    or (
                        "accounts_payable_scope_principal_missing"
                        if principal is None
                        else "entity_scope_authority_missing"
                    )
                )
            ),
            "cutoff": cutoff,
            "principal": principal,
            "entity_scope": scope,
            "scope": {
                "tenant_ref": (
                    principal.tenant_ref if principal is not None else None
                ),
                "entity_ref": (
                    str(scope.get("entity_ref"))
                    if scope.get("entity_ref")
                    else None
                ),
                "store_ref": store,
                "scope_grant_authority_sha256": (
                    authority if ready else None
                ),
            },
        }

    @staticmethod
    def _matches_query(row: dict[str, Any], query: str) -> bool:
        product = (row.get("procurement") or {}).get("product") or {}
        haystack = " ".join(
            (
                str(row.get("invoice_id") or ""),
                str(row.get("invoice_ref") or ""),
                str(row.get("purchase_order_id") or ""),
                str(row.get("supplier_ref") or ""),
                str(product.get("sku") or ""),
                str(product.get("name") or ""),
            )
        ).lower()
        return query in haystack

    @classmethod
    def _counts(cls, rows: list[dict[str, Any]]) -> dict[str, int]:
        counts = {item: 0 for item in sorted(cls.STAGES)}
        for row in rows:
            counts[row["stage"]] += 1
        return {"total": len(rows), **counts}

    @classmethod
    def _paginate(
        cls,
        rows: list[dict[str, Any]],
        *,
        page_size: int,
        cursor: str | None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        start = 0
        if cursor:
            decoded = cls._decode_cursor(cursor)
            for index, row in enumerate(rows):
                if cls._cursor_key(row) == decoded:
                    start = index + 1
                    break
            else:
                raise ValueError("cursor is stale or outside the result set")
        page = rows[start : start + page_size]
        next_cursor = (
            cls._encode_cursor(cls._cursor_key(page[-1]))
            if page and start + page_size < len(rows)
            else None
        )
        return page, next_cursor

    @staticmethod
    def _cursor_key(row: dict[str, Any]) -> tuple[str, str]:
        return str(row["issued_at"]), str(row["invoice_id"])

    @staticmethod
    def _encode_cursor(value: tuple[str, str]) -> str:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")

    @staticmethod
    def _decode_cursor(value: str) -> tuple[str, str]:
        try:
            padding = "=" * (-len(value) % 4)
            decoded = json.loads(
                base64.urlsafe_b64decode(value + padding).decode("utf-8")
            )
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("cursor is invalid") from exc
        if (
            not isinstance(decoded, list)
            or len(decoded) != 2
            or not all(isinstance(item, str) for item in decoded)
        ):
            raise ValueError("cursor is invalid")
        return decoded[0], decoded[1]

    @classmethod
    def _valid_snapshot(cls, value: dict[str, Any]) -> bool:
        supplied = str(value.get("snapshot_sha256") or "")
        if not cls._sha256(supplied):
            return False
        payload = {
            key: item
            for key, item in value.items()
            if key != "snapshot_sha256"
        }
        return supplied == cls._hash(payload)

    @classmethod
    def _temporal_issues(
        cls,
        item: dict[str, Any],
        *,
        fields: tuple[str, ...],
        context: dict[str, Any],
        prefix: str,
    ) -> list[str]:
        issues = []
        values = {}
        for field in fields:
            try:
                values[field] = cls._timestamp(item.get(field), field)
                if values[field] > context["cutoff"]:
                    issues.append(f"{prefix}_{field}_after_as_of")
            except ValueError:
                issues.append(f"{prefix}_{field}_invalid")
        if (
            "issued_at" in values
            and "due_at" in values
            and values["due_at"] < values["issued_at"]
        ):
            issues.append(f"{prefix}_date_order_invalid")
        return sorted(set(issues))

    @staticmethod
    def _timestamp(value: Any, name: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(
                str(value).replace("Z", "+00:00")
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be ISO-8601") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{name} must include a timezone")
        return parsed.astimezone(UTC)

    @staticmethod
    def _aware(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value

    @staticmethod
    def _sha256(value: str) -> bool:
        return len(value) == 64 and all(
            character in "0123456789abcdef" for character in value
        )

    @staticmethod
    def _query(value: str | None) -> str:
        result = str(value or "").strip().lower()
        if len(result) > 240:
            raise ValueError("query must be at most 240 characters")
        return result

    @classmethod
    def _stage(cls, value: str | None) -> str | None:
        result = str(value or "").strip()
        if not result:
            return None
        if result not in cls.STAGES:
            raise ValueError("stage is unsupported")
        return result

    @staticmethod
    def _page_size(value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("page_size must be an integer")
        if not 1 <= value <= 100:
            raise ValueError("page_size must be between 1 and 100")
        return value

    @staticmethod
    def _currency(value: Any) -> bool:
        result = str(value or "").strip().upper()
        return (
            len(result) == 3
            and result.isalpha()
            and result.isascii()
        )

    @staticmethod
    def _decimal(value: Any, name: str) -> Decimal:
        try:
            result = Decimal(value)
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be numeric") from exc
        if not result.is_finite():
            raise ValueError(f"{name} must be finite")
        return result

    @staticmethod
    def _decimal_text(value: Decimal) -> str:
        return format(value.normalize(), "f")

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

    @staticmethod
    def _blockers(gaps: list[str]) -> list[dict[str, str]]:
        return [
            {
                "code": gap,
                "severity": "P0",
                "owner": "accounts-payable-control",
                "next_action": (
                    "Repair exact-scope invoice, three-way-match, approval, "
                    "Permit or bank Readback authority before payment."
                ),
                "workspace": "/accounts-payable",
            }
            for gap in sorted(set(gaps))
        ]

    @staticmethod
    def _owner(stage: str) -> str:
        if stage in {"review_pending", "rejected"}:
            return "invoice-review"
        if stage in {"three_way_match_pending", "matched"}:
            return "accounts-payable-control"
        if stage in {
            "payment_approval_pending",
            "payment_permit_pending",
        }:
            return "independent-payment-approver"
        return "treasury-reconciliation"

    @staticmethod
    def _sla(stage: str) -> str:
        return {
            "invoice_captured": "within one business day of capture",
            "review_pending": "before invoice acceptance",
            "rejected": "before replacement invoice intake",
            "three_way_match_pending": "before payment approval",
            "matched": "before payment scheduling",
            "payment_approval_pending": "before any payment Permit",
            "payment_permit_pending": "before any adapter delivery",
            "payment_readback_pending": "before bank booking",
            "partially_paid": "before invoice due date",
            "settled": "within one business day of bank Readback",
            "variance": "immediate stop and reconciliation",
            "blocked": "immediate fail-closed review",
        }[stage]

    @staticmethod
    def _next(stage: str) -> str:
        return {
            "invoice_captured": "Submit an independent invoice review.",
            "review_pending": "Complete independent invoice authority review.",
            "rejected": "Capture corrected supplier invoice Evidence.",
            "three_way_match_pending": "Resolve PO, receipt or invoice variance.",
            "matched": "Request independent payment approval.",
            "payment_approval_pending": "Request independent payment approval.",
            "payment_permit_pending": "Issue no Permit until an authorized adapter exists.",
            "payment_readback_pending": "Reconcile execution receipt and bank Evidence.",
            "partially_paid": "Reconcile the remaining open balance.",
            "settled": "Close invoice after settlement-period verification.",
            "variance": "Stop payment and reconcile the variance.",
            "blocked": "Repair the invalid authority chain.",
        }[stage]
