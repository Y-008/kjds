from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .evidence import EvidenceBlobRow, EvidenceRecordRow
from .facts import FactRecordRow
from .finance import FinanceEntryKind, FinanceEntryRow, FxRateRow
from .sql_repository import ApprovalRow, ChargeRow, OrderRow, ProductRow

ZERO = Decimal("0")
ONE = Decimal("1")
EROSION_CATEGORIES = (
    "purchase",
    "logistics",
    "warehousing",
    "commission",
    "advertising",
    "returns",
    "discount",
    "tax",
    "fx",
    "loss",
    "unallocated",
)
CHARGE_CATEGORY = {
    "product_cost": "purchase",
    "domestic_logistics": "logistics",
    "packaging": "logistics",
    "customs": "logistics",
    "international_logistics": "logistics",
    "last_mile": "logistics",
    "warehousing": "warehousing",
    "platform_fee": "commission",
    "advertising": "advertising",
    "refund": "returns",
    "return": "returns",
    "customer_compensation": "returns",
    "discount": "discount",
    "tax": "tax",
    "fx": "fx",
    "capital_cost": "loss",
    "unclaimed": "loss",
    "damage": "loss",
}


class ProfitLedgerService:
    """Read existing commerce and finance truth through one projection interface."""

    CONTRACT_ID = "kjds-profit-ledger-v1"

    def __init__(self, *, engine, sourcing_store) -> None:
        self.engine = engine
        self.sourcing_store = sourcing_store

    def snapshot(
        self,
        *,
        store_ref: str = "ozon-primary",
        sku: str | None = None,
        order_id: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        grain: str = "order",
        currency: str = "CNY",
        as_of: str | None = None,
    ) -> dict[str, Any]:
        scope = store_ref.strip()
        if not scope or len(scope) > 160:
            raise ValueError("Profit ledger store_ref must be 1 to 160 characters")
        if grain not in {"day", "order", "sku"}:
            raise ValueError("Profit ledger grain must be day, order, or sku")
        quote = self._currency(currency)
        cutoff = self._timestamp(as_of, "as_of") if as_of else datetime.now(UTC)
        start = self._date(date_from, "date_from") if date_from else None
        end = self._date(date_to, "date_to") if date_to else None
        if start and end and end < start:
            raise ValueError("Profit ledger date_to must not precede date_from")

        with Session(self.engine) as session:
            products = {
                row.id: row
                for row in session.scalars(
                    select(ProductRow)
                    .where(ProductRow.created_at <= cutoff)
                    .order_by(ProductRow.id)
                )
            }
            product_by_sku = {row.sku: row for row in products.values()}
            order_rows = list(
                session.scalars(
                    select(OrderRow)
                    .where(OrderRow.created_at <= cutoff)
                    .order_by(OrderRow.created_at, OrderRow.id)
                )
            )
            charge_rows = list(
                session.scalars(
                    select(ChargeRow)
                    .where(ChargeRow.created_at <= cutoff)
                    .order_by(ChargeRow.created_at, ChargeRow.id)
                )
            )
            fact_rows = list(
                session.scalars(
                    select(FactRecordRow)
                    .where(
                        FactRecordRow.tenant_ref.is_(None),
                        FactRecordRow.recorded_at <= cutoff,
                        FactRecordRow.effective_at <= cutoff,
                    )
                    .order_by(FactRecordRow.effective_at, FactRecordRow.id)
                )
            )
            finance_rows = list(
                session.scalars(
                    select(FinanceEntryRow)
                    .where(
                        FinanceEntryRow.recorded_at <= cutoff,
                        FinanceEntryRow.effective_at <= cutoff,
                    )
                    .order_by(
                        FinanceEntryRow.effective_at,
                        FinanceEntryRow.id,
                    )
                )
            )
            fx_rows = list(
                session.scalars(
                    select(FxRateRow)
                    .where(
                        FxRateRow.recorded_at <= cutoff,
                        FxRateRow.effective_at <= cutoff,
                    )
                    .order_by(
                        FxRateRow.effective_at,
                        FxRateRow.version,
                        FxRateRow.id,
                    )
                )
            )
            evidence_rows = {
                row.id: row
                for row in session.scalars(
                    select(EvidenceRecordRow)
                    .where(EvidenceRecordRow.recorded_at <= cutoff)
                    .order_by(EvidenceRecordRow.id)
                )
            }
            blob_hashes = set(session.scalars(select(EvidenceBlobRow.sha256)))
            approvals = {
                row.id: row
                for row in session.scalars(
                    select(ApprovalRow)
                    .where(ApprovalRow.created_at <= cutoff)
                    .order_by(ApprovalRow.id)
                )
            }

        charge_by_order: dict[str, list[ChargeRow]] = defaultdict(list)
        for charge in charge_rows:
            charge_by_order[charge.order_id].append(charge)
        facts_by_external: dict[str, list[FactRecordRow]] = defaultdict(list)
        for fact in fact_rows:
            facts_by_external[str(fact.payload_json.get("external_id", ""))].append(fact)
        finance_by_key: dict[str, list[FinanceEntryRow]] = defaultdict(list)
        for entry in finance_rows:
            finance_by_key[entry.reconciliation_key].append(entry)

        scenario_by_product = self._scenario_bindings(
            approvals,
            as_of=cutoff,
        )
        rows: list[dict[str, Any]] = []
        matched_fact_ids: set[str] = set()
        matched_finance_ids: set[str] = set()

        for order in order_rows:
            product = products.get(order.product_id)
            if product is None:
                continue
            if sku and product.sku != sku:
                continue
            if order_id and order.external_id != order_id and order.id != order_id:
                continue
            accounting_date = self._aware(order.created_at).date()
            if not self._in_range(accounting_date, start, end):
                continue
            related_facts = facts_by_external.get(order.external_id, [])
            matched_fact_ids.update(item.id for item in related_facts)
            related_finance = finance_by_key.get(order.external_id, [])
            matched_finance_ids.update(item.id for item in related_finance)
            rows.append(
                self._order_projection(
                    order=order,
                    product=product,
                    charges=charge_by_order.get(order.id, []),
                    facts=related_facts,
                    finance_entries=related_finance,
                    fx_rows=fx_rows,
                    evidence_rows=evidence_rows,
                    blob_hashes=blob_hashes,
                    as_of=cutoff,
                    scenario=scenario_by_product.get(order.product_id),
                    quote_currency=quote,
                    store_ref=scope,
                )
            )

        # Formal order facts can exist before a core Order is materialized. They are
        # included only when product_id is explicit; no SKU guess is performed.
        for fact in fact_rows:
            if fact.fact_type != "ozon_order" or fact.id in matched_fact_ids:
                continue
            product = products.get(fact.product_id or "")
            if product is None:
                continue
            payload = fact.payload_json
            external_id = str(payload.get("external_id", ""))
            if sku and product.sku != sku:
                continue
            if order_id and external_id != order_id and fact.id != order_id:
                continue
            accounting_date = self._aware(fact.effective_at).date()
            if not self._in_range(accounting_date, start, end):
                continue
            related_finance = finance_by_key.get(external_id, [])
            matched_finance_ids.update(item.id for item in related_finance)
            rows.append(
                self._fact_order_projection(
                    fact=fact,
                    product=product,
                    finance_entries=related_finance,
                    fx_rows=fx_rows,
                    evidence_rows=evidence_rows,
                    blob_hashes=blob_hashes,
                    as_of=cutoff,
                    scenario=scenario_by_product.get(product.id),
                    quote_currency=quote,
                    store_ref=scope,
                )
            )
            matched_fact_ids.add(fact.id)

        unallocated = self._unallocated(
            facts=fact_rows,
            finance_entries=finance_rows,
            matched_fact_ids=matched_fact_ids,
            matched_finance_ids=matched_finance_ids,
            product_by_sku=product_by_sku,
            start=start,
            end=end,
            sku=sku,
            order_id=order_id,
        )
        grouped = self._group(rows, grain)
        status = self._snapshot_status(grouped, unallocated)
        coverage = (
            sum(Decimal(item["coverage_ratio"]) for item in grouped) / Decimal(len(grouped))
            if grouped
            else ZERO
        )
        payload = {
            "contract_id": self.CONTRACT_ID,
            "registry_version": "profit-ledger/1.0.0",
            "as_of": cutoff.isoformat(),
            "store_ref": scope,
            "grain": grain,
            "currency": quote,
            "filters": {
                "sku": sku,
                "order_id": order_id,
                "date_from": start.isoformat() if start else None,
                "date_to": end.isoformat() if end else None,
            },
            "status": status,
            "coverage_ratio": self._decimal(coverage),
            "rows": grouped,
            "unallocated": unallocated,
            "control_envelope": {
                "read_only": True,
                "explicit_binding_only": True,
                "proportional_allocation_allowed": False,
                "actual_profit_requires_reconciliation": True,
                "external_write_allowed": False,
            },
        }
        payload["snapshot_sha256"] = self._hash(payload)
        return payload

    def erosion(self, **filters: Any) -> dict[str, Any]:
        ledger = self.snapshot(**filters)
        currency = ledger["currency"]
        baseline = sum(
            (Decimal(item["gross_revenue"]) for item in ledger["rows"]), ZERO
        )
        totals = {key: ZERO for key in EROSION_CATEGORIES}
        evidence_ids: set[str] = set()
        for row in ledger["rows"]:
            evidence_ids.update(row["evidence_ids"])
            for key in EROSION_CATEGORIES:
                totals[key] += Decimal(row["erosion"][key])
        # Items that cannot be bound are reported but never fabricated as money.
        # A known explicit unallocated amount is conserved in its own bridge leg.
        for item in ledger["unallocated"]:
            if item.get("amount") is not None and item.get("currency") == currency:
                totals["unallocated"] += abs(Decimal(item["amount"]))
            evidence_id = item.get("evidence_id")
            if evidence_id:
                evidence_ids.add(evidence_id)
        erosion_total = sum(totals.values(), ZERO)
        result = baseline - erosion_total
        items = [
            {
                "category": key,
                "amount": self._decimal(totals[key]),
                "direction": "erosion",
            }
            for key in EROSION_CATEGORIES
        ]
        conservation_delta = baseline - erosion_total - result
        payload = {
            "contract_id": "kjds-profit-erosion-bridge-v1",
            "registry_version": ledger["registry_version"],
            "store_ref": ledger["store_ref"],
            "currency": currency,
            "status": ledger["status"],
            "baseline": self._decimal(baseline),
            "result": self._decimal(result),
            "items": items,
            "erosion_total": self._decimal(erosion_total),
            "conservation_delta": self._decimal(conservation_delta),
            "conserved": conservation_delta == ZERO,
            "coverage_ratio": ledger["coverage_ratio"],
            "evidence_ids": sorted(evidence_ids),
            "unallocated": ledger["unallocated"],
            "ledger_snapshot_sha256": ledger["snapshot_sha256"],
        }
        payload["snapshot_sha256"] = self._hash(payload)
        return payload

    def _order_projection(
        self,
        *,
        order: OrderRow,
        product: ProductRow,
        charges: list[ChargeRow],
        facts: list[FactRecordRow],
        finance_entries: list[FinanceEntryRow],
        fx_rows: list[FxRateRow],
        evidence_rows: dict[str, EvidenceRecordRow],
        blob_hashes: set[str],
        as_of: datetime,
        scenario: dict[str, Any] | None,
        quote_currency: str,
        store_ref: str,
    ) -> dict[str, Any]:
        blockers: list[str] = []
        evidence_ids = {fact.evidence_id for fact in facts}
        gross = self._convert_explicit(
            amount=order.gross_revenue_decimal,
            currency=order.currency,
            quote_currency=quote_currency,
            explicit_rate=order.booked_fx_rate_decimal,
            effective_at=order.created_at,
            fx_rows=fx_rows,
            blockers=blockers,
            leg="order_booked_fx",
        )
        erosion = {key: ZERO for key in EROSION_CATEGORIES}
        for charge in charges:
            evidence_ids.add(charge.evidence_ref)
            category = CHARGE_CATEGORY.get(charge.kind, "unallocated")
            erosion[category] += self._convert_explicit(
                amount=charge.amount_decimal,
                currency=charge.currency,
                quote_currency=quote_currency,
                explicit_rate=charge.fx_rate_decimal,
                effective_at=charge.created_at,
                fx_rows=fx_rows,
                blockers=blockers,
                leg=f"charge:{charge.id}",
            )
        settlement, cash, finance_evidence = self._finance_contributions(
            entries=finance_entries,
            quote_currency=quote_currency,
            fx_rows=fx_rows,
            blockers=blockers,
        )
        evidence_ids.update(finance_evidence)
        valid_evidence, invalid_evidence = self._evidence_state(
            evidence_ids,
            evidence_rows,
            blob_hashes,
            as_of=as_of,
        )
        blockers.extend(f"invalid_evidence:{item}" for item in invalid_evidence)
        fact_order_evidence = any(item.fact_type == "ozon_order" for item in facts)
        required_categories = {"purchase", "commission", "returns"}
        present_categories = {
            category for category, amount in erosion.items() if amount != ZERO
        }
        missing = sorted(required_categories - present_categories)
        if not fact_order_evidence:
            blockers.append("missing_formal_order_fact")
        if missing:
            blockers.extend(f"missing_cost_leg:{item}" for item in missing)
        accrual = gross - sum(erosion.values(), ZERO)
        finance_kinds = {item.entry_kind for item in finance_entries}
        reconciled = {
            FinanceEntryKind.ORDER_RECEIVABLE.value,
            FinanceEntryKind.PLATFORM_SETTLEMENT.value,
            FinanceEntryKind.BANK_RECEIPT.value,
        }.issubset(finance_kinds)
        if not reconciled:
            blockers.append("missing_settlement_or_bank_leg")
        coverage = self._coverage(
            revenue=fact_order_evidence,
            purchase="purchase" in present_categories,
            platform_fee="commission" in present_categories,
            returns="returns" in present_categories,
            fx="fx" in present_categories or order.currency == quote_currency,
            settlement=reconciled,
        )
        status = "reconciled" if not blockers and coverage == ONE else "blocked" if invalid_evidence else "partial"
        return self._row(
            store_ref=store_ref,
            product=product,
            order_ref=order.external_id,
            accounting_date=self._aware(order.created_at).date(),
            quote_currency=quote_currency,
            gross=gross,
            erosion=erosion,
            accrual=accrual,
            settlement=settlement,
            cash=cash,
            scenario=scenario,
            status=status,
            coverage=coverage,
            blockers=blockers,
            evidence_ids=valid_evidence,
        )

    def _fact_order_projection(
        self,
        *,
        fact: FactRecordRow,
        product: ProductRow,
        finance_entries: list[FinanceEntryRow],
        fx_rows: list[FxRateRow],
        evidence_rows: dict[str, EvidenceRecordRow],
        blob_hashes: set[str],
        as_of: datetime,
        scenario: dict[str, Any] | None,
        quote_currency: str,
        store_ref: str,
    ) -> dict[str, Any]:
        blockers: list[str] = []
        payload = fact.payload_json
        gross = self._convert(
            amount=Decimal(str(payload["gross_revenue"])),
            currency=str(payload["currency"]),
            quote_currency=quote_currency,
            effective_at=fact.effective_at,
            fx_rows=fx_rows,
            blockers=blockers,
            leg=f"fact:{fact.id}",
        )
        settlement, cash, finance_evidence = self._finance_contributions(
            entries=finance_entries,
            quote_currency=quote_currency,
            fx_rows=fx_rows,
            blockers=blockers,
        )
        evidence_ids = {fact.evidence_id, *finance_evidence}
        valid_evidence, invalid_evidence = self._evidence_state(
            evidence_ids,
            evidence_rows,
            blob_hashes,
            as_of=as_of,
        )
        blockers.extend(f"invalid_evidence:{item}" for item in invalid_evidence)
        blockers.extend(
            [
                "missing_cost_leg:purchase",
                "missing_cost_leg:commission",
                "missing_cost_leg:returns",
                "missing_cost_leg:fx",
            ]
        )
        erosion = {key: ZERO for key in EROSION_CATEGORIES}
        coverage = self._coverage(
            revenue=True,
            purchase=False,
            platform_fee=False,
            returns=False,
            fx=payload["currency"] == quote_currency,
            settlement=False,
        )
        return self._row(
            store_ref=store_ref,
            product=product,
            order_ref=str(payload["external_id"]),
            accounting_date=self._aware(fact.effective_at).date(),
            quote_currency=quote_currency,
            gross=gross,
            erosion=erosion,
            accrual=gross,
            settlement=settlement,
            cash=cash,
            scenario=scenario,
            status="blocked" if blockers else "partial",
            coverage=coverage,
            blockers=blockers,
            evidence_ids=valid_evidence,
        )

    def _finance_contributions(
        self,
        *,
        entries: list[FinanceEntryRow],
        quote_currency: str,
        fx_rows: list[FxRateRow],
        blockers: list[str],
    ) -> tuple[Decimal | None, Decimal | None, set[str]]:
        settlement = ZERO
        cash = ZERO
        has_settlement = False
        has_cash = False
        evidence_ids: set[str] = set()
        for entry in entries:
            evidence_ids.add(entry.evidence_id)
            converted = self._convert(
                amount=entry.amount,
                currency=entry.currency,
                quote_currency=quote_currency,
                effective_at=entry.effective_at,
                fx_rows=fx_rows,
                blockers=blockers,
                leg=f"finance_entry:{entry.id}",
            )
            if entry.entry_kind in {
                FinanceEntryKind.ORDER_RECEIVABLE.value,
                FinanceEntryKind.PLATFORM_FEE.value,
                FinanceEntryKind.RETURN_ADJUSTMENT.value,
                FinanceEntryKind.PLATFORM_SETTLEMENT.value,
            }:
                settlement += converted
                has_settlement = True
            if entry.entry_kind == FinanceEntryKind.BANK_RECEIPT.value:
                cash += converted
                has_cash = True
        return (
            settlement if has_settlement else None,
            cash if has_cash else None,
            evidence_ids,
        )

    def _scenario_bindings(
        self,
        approvals: dict[str, ApprovalRow],
        *,
        as_of: datetime,
    ) -> dict[str, dict[str, Any]]:
        bindings: dict[str, dict[str, Any]] = {}
        try:
            drafts = self.sourcing_store.list_listing_drafts(limit=5000)
        except (KeyError, RuntimeError, ValueError):
            return bindings
        for draft in drafts:
            approval = approvals.get(draft.approval_id or "")
            if approval is None or approval.status != "approved":
                continue
            try:
                scenario = self.sourcing_store.get_scenario(draft.scenario_id)
            except (KeyError, RuntimeError, ValueError):
                continue
            scenario_created_at = self._timestamp(
                scenario.created_at,
                "scenario.created_at",
            )
            if scenario_created_at > as_of:
                continue
            current = bindings.get(draft.product_id)
            if (
                current is not None
                and current["created_at"] >= scenario.created_at
            ):
                continue
            bindings[draft.product_id] = {
                "scenario_id": scenario.id,
                "listing_id": draft.id,
                "approval_id": approval.id,
                "cm3": self._decimal(scenario.cm3_cny),
                "cm3_rate": self._decimal(scenario.cm3_rate),
                "currency": "CNY",
                "cost_complete": scenario.cost_complete,
                "evidence_ids": sorted(
                    set(scenario.evidence) | set(scenario.cost_evidence.values())
                ),
                "created_at": scenario.created_at,
            }
        return bindings

    @staticmethod
    def _evidence_state(
        evidence_ids: set[str],
        evidence_rows: dict[str, EvidenceRecordRow],
        blob_hashes: set[str],
        *,
        as_of: datetime,
    ) -> tuple[list[str], list[str]]:
        valid: list[str] = []
        invalid: list[str] = []
        for evidence_id in sorted(item for item in evidence_ids if item):
            row = evidence_rows.get(evidence_id)
            if (
                row is None
                or row.blob_sha256 not in blob_hashes
                or ProfitLedgerService._aware(row.effective_at) > as_of
                or (
                    row.effective_until is not None
                    and as_of
                    >= ProfitLedgerService._aware(row.effective_until)
                )
            ):
                invalid.append(evidence_id)
            else:
                valid.append(evidence_id)
        return valid, invalid

    def _unallocated(
        self,
        *,
        facts: list[FactRecordRow],
        finance_entries: list[FinanceEntryRow],
        matched_fact_ids: set[str],
        matched_finance_ids: set[str],
        product_by_sku: dict[str, ProductRow],
        start: date | None,
        end: date | None,
        sku: str | None,
        order_id: str | None,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for fact in facts:
            if fact.id in matched_fact_ids or not self._in_range(
                self._aware(fact.effective_at).date(), start, end
            ):
                continue
            payload_sku = str(fact.payload_json.get("sku", "")).strip()
            external_id = str(fact.payload_json.get("external_id", "")).strip()
            if sku and payload_sku != sku:
                continue
            if order_id and external_id != order_id and fact.id != order_id:
                continue
            reason = (
                "requires_product_mapping"
                if not fact.product_id and payload_sku not in product_by_sku
                else "requires_explicit_order_binding"
            )
            items.append(
                {
                    "source_type": "fact_record",
                    "source_id": fact.id,
                    "fact_type": fact.fact_type,
                    "external_id": external_id or None,
                    "sku": payload_sku or None,
                    "amount": fact.payload_json.get("amount"),
                    "currency": fact.payload_json.get("currency"),
                    "evidence_id": fact.evidence_id,
                    "reason": reason,
                    "status": "blocked",
                }
            )
        for entry in finance_entries:
            if entry.id in matched_finance_ids or not self._in_range(
                self._aware(entry.effective_at).date(), start, end
            ):
                continue
            if order_id and entry.reconciliation_key != order_id and entry.id != order_id:
                continue
            items.append(
                {
                    "source_type": "finance_entry",
                    "source_id": entry.id,
                    "entry_kind": entry.entry_kind,
                    "reconciliation_key": entry.reconciliation_key,
                    "amount": self._decimal(entry.amount),
                    "currency": entry.currency,
                    "evidence_id": entry.evidence_id,
                    "reason": "requires_explicit_order_binding",
                    "status": "blocked",
                }
            )
        return sorted(items, key=lambda item: (item["source_type"], item["source_id"]))

    def _group(self, rows: list[dict[str, Any]], grain: str) -> list[dict[str, Any]]:
        if grain == "order":
            return sorted(rows, key=lambda item: (item["accounting_date"], item["order_ref"]))
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            key = row["accounting_date"] if grain == "day" else row["sku"]
            grouped[key].append(row)
        result: list[dict[str, Any]] = []
        for key, items in sorted(grouped.items()):
            erosion = {
                category: sum(
                    (Decimal(item["erosion"][category]) for item in items), ZERO
                )
                for category in EROSION_CATEGORIES
            }
            gross = sum((Decimal(item["gross_revenue"]) for item in items), ZERO)
            accrual = sum((Decimal(item["accrual_contribution"]) for item in items), ZERO)
            settlement_values = [
                Decimal(item["settlement_contribution"])
                for item in items
                if item["settlement_contribution"] is not None
            ]
            cash_values = [
                Decimal(item["cash_contribution"])
                for item in items
                if item["cash_contribution"] is not None
            ]
            statuses = {item["status"] for item in items}
            status = (
                "blocked"
                if "blocked" in statuses
                else "reconciled"
                if statuses == {"reconciled"}
                else "partial"
            )
            result.append(
                {
                    "grain_key": key,
                    "store_ref": items[0]["store_ref"],
                    "product_id": items[0]["product_id"] if grain == "sku" else None,
                    "sku": key if grain == "sku" else None,
                    "order_ref": None,
                    "accounting_date": key if grain == "day" else None,
                    "currency": items[0]["currency"],
                    "status": status,
                    "coverage_ratio": self._decimal(
                        sum(
                            (Decimal(item["coverage_ratio"]) for item in items), ZERO
                        )
                        / Decimal(len(items))
                    ),
                    "gross_revenue": self._decimal(gross),
                    "scenario_contribution": None,
                    "accrual_contribution": self._decimal(accrual),
                    "settlement_contribution": (
                        self._decimal(sum(settlement_values, ZERO))
                        if settlement_values
                        else None
                    ),
                    "cash_contribution": (
                        self._decimal(sum(cash_values, ZERO)) if cash_values else None
                    ),
                    "actual_profit": (
                        self._decimal(sum(cash_values, ZERO) - sum(erosion.values(), ZERO))
                        if status == "reconciled" and cash_values
                        else None
                    ),
                    "erosion": {
                        category: self._decimal(amount)
                        for category, amount in erosion.items()
                    },
                    "blockers": sorted(
                        {reason for item in items for reason in item["blockers"]}
                    ),
                    "evidence_ids": sorted(
                        {value for item in items for value in item["evidence_ids"]}
                    ),
                    "source_order_count": len(items),
                }
            )
        return result

    def _row(
        self,
        *,
        store_ref: str,
        product: ProductRow,
        order_ref: str,
        accounting_date: date,
        quote_currency: str,
        gross: Decimal,
        erosion: dict[str, Decimal],
        accrual: Decimal,
        settlement: Decimal | None,
        cash: Decimal | None,
        scenario: dict[str, Any] | None,
        status: str,
        coverage: Decimal,
        blockers: list[str],
        evidence_ids: list[str],
    ) -> dict[str, Any]:
        actual_profit = (
            cash - sum(erosion.values(), ZERO)
            if status == "reconciled" and cash is not None
            else None
        )
        return {
            "grain_key": order_ref,
            "store_ref": store_ref,
            "product_id": product.id,
            "sku": product.sku,
            "order_ref": order_ref,
            "accounting_date": accounting_date.isoformat(),
            "currency": quote_currency,
            "status": status,
            "coverage_ratio": self._decimal(coverage),
            "gross_revenue": self._decimal(gross),
            "scenario_contribution": (
                scenario["cm3"] if scenario and scenario["cost_complete"] else None
            ),
            "scenario_binding": scenario,
            "accrual_contribution": self._decimal(accrual),
            "settlement_contribution": (
                self._decimal(settlement) if settlement is not None else None
            ),
            "cash_contribution": self._decimal(cash) if cash is not None else None,
            "actual_profit": (
                self._decimal(actual_profit) if actual_profit is not None else None
            ),
            "erosion": {
                category: self._decimal(erosion[category])
                for category in EROSION_CATEGORIES
            },
            "blockers": sorted(set(blockers)),
            "evidence_ids": evidence_ids,
        }

    @staticmethod
    def _coverage(**legs: bool) -> Decimal:
        return sum((ONE for value in legs.values() if value), ZERO) / Decimal(len(legs))

    def _convert_explicit(
        self,
        *,
        amount: Decimal,
        currency: str,
        quote_currency: str,
        explicit_rate: Decimal,
        effective_at: datetime,
        fx_rows: list[FxRateRow],
        blockers: list[str],
        leg: str,
    ) -> Decimal:
        try:
            value = Decimal(amount)
            rate = Decimal(explicit_rate)
        except (InvalidOperation, TypeError) as exc:
            raise ValueError(f"{leg} contains an invalid Decimal") from exc
        if not value.is_finite() or not rate.is_finite() or rate <= ZERO:
            raise ValueError(f"{leg} contains a non-finite amount or FX rate")
        if currency == quote_currency:
            return value
        if quote_currency == "CNY":
            return value * rate
        return self._convert(
            amount=value,
            currency=currency,
            quote_currency=quote_currency,
            effective_at=effective_at,
            fx_rows=fx_rows,
            blockers=blockers,
            leg=leg,
        )

    def _convert(
        self,
        *,
        amount: Decimal,
        currency: str,
        quote_currency: str,
        effective_at: datetime,
        fx_rows: list[FxRateRow],
        blockers: list[str],
        leg: str,
    ) -> Decimal:
        value = Decimal(amount)
        if not value.is_finite():
            raise ValueError(f"{leg} contains a non-finite amount")
        source = self._currency(currency)
        if source == quote_currency:
            return value
        effective = self._aware(effective_at)
        candidates = [
            row
            for row in fx_rows
            if row.base_currency == source
            and row.quote_currency == quote_currency
            and self._aware(row.effective_at) <= effective
        ]
        if not candidates:
            blockers.append(f"missing_fx:{source}/{quote_currency}:{effective.date().isoformat()}")
            return ZERO
        rate = candidates[-1].rate
        return value * rate

    @staticmethod
    def _snapshot_status(rows: list[dict[str, Any]], unallocated: list[dict[str, Any]]) -> str:
        if not rows and not unallocated:
            return "no_data"
        if unallocated or any(item["status"] == "blocked" for item in rows):
            return "blocked"
        if rows and all(item["status"] == "reconciled" for item in rows):
            return "reconciled"
        return "partial"

    @staticmethod
    def _currency(value: str) -> str:
        normalized = value.strip().upper()
        if len(normalized) != 3 or not normalized.isascii() or not normalized.isalpha():
            raise ValueError("Profit ledger currency must be a three-letter code")
        return normalized

    @staticmethod
    def _date(value: str, field: str) -> date:
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{field} must use YYYY-MM-DD") from exc

    @staticmethod
    def _timestamp(value: str, field: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
        if parsed.tzinfo is None:
            raise ValueError(f"{field} must include a timezone")
        return parsed.astimezone(UTC)

    @staticmethod
    def _aware(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    @staticmethod
    def _in_range(value: date, start: date | None, end: date | None) -> bool:
        return (start is None or value >= start) and (end is None or value <= end)

    @staticmethod
    def _decimal(value: Decimal) -> str:
        normalized = Decimal(value)
        if normalized == ZERO:
            return "0"
        return format(normalized.normalize(), "f")

    @staticmethod
    def _hash(value: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
