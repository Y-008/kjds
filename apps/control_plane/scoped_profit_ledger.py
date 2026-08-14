from __future__ import annotations

import base64
import hashlib
import json
from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .domain import CM1_COSTS, CM2_COSTS, CM3_COSTS, ChargeType
from .finance import (
    ACTUAL_PROFIT_COST_TYPES,
    FeeSignRule,
    FinanceEntryKind,
)
from .profit_ledger import EROSION_CATEGORIES
from .security import Principal
from .sql_repository import ProductRow

ZERO = Decimal("0")
COST_ORDER = (
    ChargeType.PRODUCT_COST,
    ChargeType.DOMESTIC_LOGISTICS,
    ChargeType.INTERNATIONAL_LOGISTICS,
    ChargeType.PACKAGING,
    ChargeType.WAREHOUSING,
    ChargeType.CUSTOMS,
    ChargeType.TAX,
    ChargeType.LAST_MILE,
    ChargeType.PLATFORM_FEE,
    ChargeType.ADVERTISING,
    ChargeType.RETURN,
    ChargeType.FX,
    ChargeType.CAPITAL_COST,
    ChargeType.CUSTOMER_COMPENSATION,
    ChargeType.DAMAGE,
)
COST_VALUES = frozenset(item.value for item in ACTUAL_PROFIT_COST_TYPES)
CM1_VALUES = frozenset(item.value for item in CM1_COSTS)
CM2_VALUES = frozenset(item.value for item in CM2_COSTS)
CM3_VALUES = frozenset(
    item.value for item in CM3_COSTS if item.value in COST_VALUES
)
REVENUE_EROSION_TYPES = frozenset(
    {ChargeType.DISCOUNT.value, ChargeType.REFUND.value}
)


class ScopedProfitLedgerAuthority:
    """Project actual profit from native exact-scope accounting authorities."""

    CONTRACT_ID = "kjds-native-exact-scope-actual-profit-ledger-v1"
    EROSION_CONTRACT_ID = "kjds-native-exact-scope-profit-erosion-v1"
    FINANCE_SOURCE_CONTRACT_ID = "kjds-scoped-finance-read-source-v1"
    AUTHORITY_SOURCE_CONTRACT_ID = (
        "kjds-scoped-profit-authority-source-v1"
    )
    ARTIFACT_CONTRACT_ID = "kjds-profit-steward-artifact-v1"
    ORDER_SKU_RECEIPT_CONTRACT_ID = "canonical_order_sku_receipt_v1"
    ORDER_SKU_RECEIPT_AUTHORITY_CONTRACT_ID = (
        "kjds-profit-order-sku-receipt-authority-v1"
    )
    native_exact_scope = True

    def __init__(
        self,
        *,
        engine,
        finance,
        evidence,
        scoped_evidence,
    ) -> None:
        self.engine = engine
        self.finance = finance
        self.evidence = evidence
        self.scoped_evidence = scoped_evidence

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
        principal: Principal | None = None,
        entity_scope: dict[str, Any] | None = None,
        query: str | None = None,
        page_size: int = 100,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        context = self._context(
            store_ref=store_ref,
            principal=principal,
            entity_scope=entity_scope,
            as_of=as_of,
        )
        normalized_currency = self._currency(currency)
        normalized_grain = self._grain(grain)
        start = self._date(date_from, "date_from") if date_from else None
        end = self._date(date_to, "date_to") if date_to else None
        if start and end and end < start:
            raise ValueError("date_to must not precede date_from")
        normalized_query = str(query or "").strip().lower() or None
        normalized_page_size = self._page_size(page_size)
        normalized_cursor = str(cursor or "").strip() or None
        filters = {
            "sku": str(sku or "").strip() or None,
            "order_id": str(order_id or "").strip() or None,
            "date_from": start.isoformat() if start else None,
            "date_to": end.isoformat() if end else None,
            "query": normalized_query,
        }
        if context["status"] != "ready":
            return self._empty(
                context=context,
                filters=filters,
                grain=normalized_grain,
                currency=normalized_currency,
                page_size=normalized_page_size,
                status=context["status"],
                reason=context["reason"],
            )

        source = self.finance.read_scoped_sources(
            tenant_ref=context["scope"]["tenant_ref"],
            entity_ref=context["scope"]["entity_ref"],
            store_ref=context["scope"]["store_ref"],
            scope_grant_authority_sha256=context["scope"][
                "scope_grant_authority_sha256"
            ],
            as_of=context["cutoff"].isoformat(),
        )
        authorities = self.finance.read_scoped_profit_authorities(
            tenant_ref=context["scope"]["tenant_ref"],
            entity_ref=context["scope"]["entity_ref"],
            store_ref=context["scope"]["store_ref"],
            scope_grant_authority_sha256=context["scope"][
                "scope_grant_authority_sha256"
            ],
            as_of=context["cutoff"].isoformat(),
        )
        products = self._read_products(context)
        source_issues = [
            *self._source_issues(
                source,
                contract_id=self.FINANCE_SOURCE_CONTRACT_ID,
                context=context,
            ),
            *self._source_issues(
                authorities,
                contract_id=self.AUTHORITY_SOURCE_CONTRACT_ID,
                context=context,
            ),
            *self._product_source_issues(products, context=context),
        ]
        if source_issues:
            return self._empty(
                context=context,
                filters=filters,
                grain=normalized_grain,
                currency=normalized_currency,
                page_size=normalized_page_size,
                status="blocked",
                reason=source_issues[0],
                extra_gaps=source_issues[1:],
                scoped_input_read=True,
                source_snapshot_sha256=self._hash(
                    {
                        "finance": source.get("snapshot_sha256"),
                        "authorities": authorities.get("snapshot_sha256"),
                        "products": products.get("snapshot_sha256"),
                    }
                ),
            )

        products_by_id = {item["id"]: item for item in products["items"]}
        entries_by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
        runs_by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in source["entries"]:
            key = str(item.get("reconciliation_key") or "").strip()
            if key:
                entries_by_key[key].append(item)
        for item in source["reconciliations"]:
            key = str(item.get("reconciliation_key") or "").strip()
            if key:
                runs_by_key[key].append(item)

        order_candidates: dict[str, list[dict[str, Any]]] = defaultdict(list)
        orphan_order_fact_count = 0
        for item in source["facts"]:
            if item.get("fact_type") != "ozon_order":
                continue
            key = self._fact_key(item)
            if not key:
                orphan_order_fact_count += 1
                continue
            order_candidates[key].append(item)

        excluded_reasons: Counter[str] = Counter()
        if orphan_order_fact_count:
            excluded_reasons["profit_order_key_missing"] += (
                orphan_order_fact_count
            )
        rows: list[dict[str, Any]] = []
        evidence_cache: dict[tuple[str, str], list[str]] = {}
        considered_keys: set[str] = set()
        for key in sorted(order_candidates):
            candidates = order_candidates[key]
            latest = max(candidates, key=self._fact_rank)
            payload = latest.get("payload")
            if not self._matches_filters(
                key=key,
                payload=payload,
                effective_at=latest.get("effective_at"),
                filters=filters,
                start=start,
                end=end,
            ):
                continue
            considered_keys.add(key)
            issues = self._latest_fact_conflicts(candidates)
            issues.extend(
                self._fact_issues(
                    latest,
                    context=context,
                    evidence_cache=evidence_cache,
                )
            )
            if not issues:
                product = products_by_id.get(str(latest.get("product_id")))
                issues.extend(
                    self._product_issues(
                        product,
                        fact=latest,
                        context=context,
                    )
                )
            else:
                product = None
            if issues:
                excluded_reasons.update(set(issues))
                continue
            row, projection_issues = self._project_order(
                fact=latest,
                product=product,
                entries=entries_by_key.get(key, []),
                runs=runs_by_key.get(key, []),
                mappings=authorities["fee_mappings"],
                fx_rates=authorities["fx_rates"],
                quote_currency=normalized_currency,
                context=context,
                evidence_cache=evidence_cache,
            )
            if projection_issues:
                excluded_reasons.update(set(projection_issues))
                continue
            rows.append(row)

        unmatched_keys = (
            set(entries_by_key) | set(runs_by_key)
        ) - set(order_candidates)
        if unmatched_keys and not filters["order_id"] and not filters["sku"]:
            excluded_reasons["profit_finance_without_order_fact"] += len(
                unmatched_keys
            )

        aggregated = self._aggregate(rows, grain=normalized_grain)
        aggregated.sort(
            key=lambda item: (
                item["latest_effective_at"],
                item["grain_key"],
            ),
            reverse=True,
        )
        if normalized_query:
            aggregated = [
                item
                for item in aggregated
                if normalized_query in item["grain_key"].lower()
                or normalized_query in str(item.get("sku") or "").lower()
                or normalized_query
                in str(item.get("product_name") or "").lower()
            ]
        total_filtered = len(aggregated)
        cursor_key = (
            self._decode_cursor(normalized_cursor)
            if normalized_cursor
            else None
        )
        if cursor_key is not None:
            positions = {
                self._cursor_key(item): index
                for index, item in enumerate(aggregated)
            }
            if cursor_key not in positions:
                raise ValueError(
                    "cursor does not belong to the current profit result"
                )
            aggregated = aggregated[positions[cursor_key] + 1 :]
        page = aggregated[:normalized_page_size]
        has_more = len(aggregated) > normalized_page_size
        next_cursor = (
            self._encode_cursor(self._cursor_key(page[-1]))
            if has_more and page
            else None
        )
        excluded_count = sum(excluded_reasons.values())
        source_gaps = [
            f"profit_source_excluded:{reason}"
            for reason in sorted(excluded_reasons)
        ]
        if not considered_keys and not source_gaps:
            source_gaps.append("scoped_order_fact_missing")
        status = self._status(
            row_count=len(rows),
            excluded_count=excluded_count,
        )
        source_snapshot_sha256 = self._hash(
            {
                "finance": source["snapshot_sha256"],
                "authorities": authorities["snapshot_sha256"],
                "products": products["snapshot_sha256"],
            }
        )
        payload = {
            "contract_id": self.CONTRACT_ID,
            "registry_version": "native-scoped-actual-profit/1.0.0",
            "status": status,
            "as_of": context["cutoff"].isoformat(),
            "scope": {
                **context["scope"],
                "status": "ready",
                "authority": "native_exact_scope",
            },
            "store_ref": context["scope"]["store_ref"],
            "grain": normalized_grain,
            "currency": normalized_currency,
            "filters": filters,
            "coverage_ratio": (
                "1" if rows else "0"
            ),
            "counts": {
                "order_candidates": len(order_candidates),
                "considered": len(considered_keys),
                "reconciled": len(rows),
                "excluded": excluded_count,
                "filtered": total_filtered,
                "page": len(page),
            },
            "pagination": {
                "page_size": normalized_page_size,
                "next_cursor": next_cursor,
            },
            "rows": page,
            "unallocated": [],
            "excluded": {
                "count": excluded_count,
                "reason_counts": dict(sorted(excluded_reasons.items())),
                "business_values_exposed": False,
            },
            "source_gaps": sorted(set(source_gaps)),
            "blockers": self._blockers(source_gaps),
            "source_snapshot_sha256": source_snapshot_sha256,
            "control_envelope": self._control_envelope(
                scoped_input_read=True
            ),
        }
        payload["artifact"] = self._artifact(
            payload=payload,
            source_snapshot_sha256=source_snapshot_sha256,
        )
        payload["snapshot_sha256"] = self._hash(payload)
        return payload

    def erosion(self, **filters: Any) -> dict[str, Any]:
        snapshot_filters = dict(filters)
        snapshot_filters.pop("cursor", None)
        snapshot_filters["page_size"] = 250
        ledger = self.snapshot(**snapshot_filters)
        ledgers = [ledger]
        next_cursor = ledger["pagination"]["next_cursor"]
        while next_cursor:
            page = self.snapshot(
                **snapshot_filters,
                cursor=next_cursor,
            )
            ledgers.append(page)
            next_cursor = page["pagination"]["next_cursor"]
        totals = {key: ZERO for key in EROSION_CATEGORIES}
        evidence_ids: set[str] = set()
        baseline = ZERO
        result = ZERO
        for page in ledgers:
            for row in page["rows"]:
                baseline += Decimal(row["gross_revenue"])
                result += Decimal(row["actual_profit"])
                evidence_ids.update(row.get("evidence_ids", []))
                for key in EROSION_CATEGORIES:
                    totals[key] += Decimal(row["erosion"][key])
        erosion_total = sum(totals.values(), ZERO)
        conservation_delta = baseline - erosion_total - result
        payload = {
            "contract_id": self.EROSION_CONTRACT_ID,
            "registry_version": ledger["registry_version"],
            "status": ledger["status"],
            "as_of": ledger["as_of"],
            "scope": ledger["scope"],
            "store_ref": ledger["store_ref"],
            "currency": ledger["currency"],
            "baseline": self._decimal(baseline),
            "result": self._decimal(result),
            "items": [
                {
                    "category": key,
                    "amount": self._decimal(totals[key]),
                    "direction": "erosion",
                }
                for key in EROSION_CATEGORIES
            ],
            "erosion_total": self._decimal(erosion_total),
            "conservation_delta": self._decimal(conservation_delta),
            "conserved": conservation_delta == ZERO,
            "coverage_ratio": ledger["coverage_ratio"],
            "evidence_ids": sorted(evidence_ids),
            "unallocated": ledger["unallocated"],
            "excluded": ledger["excluded"],
            "source_gaps": ledger["source_gaps"],
            "blockers": ledger["blockers"],
            "ledger_snapshot_sha256": self._hash(
                [item["snapshot_sha256"] for item in ledgers]
            ),
            "control_envelope": self._control_envelope(
                scoped_input_read=ledger["control_envelope"][
                    "scoped_input_read"
                ]
            ),
        }
        payload["snapshot_sha256"] = self._hash(payload)
        return payload

    def _project_order(
        self,
        *,
        fact: dict[str, Any],
        product: dict[str, Any],
        entries: list[dict[str, Any]],
        runs: list[dict[str, Any]],
        mappings: list[dict[str, Any]],
        fx_rates: list[dict[str, Any]],
        quote_currency: str,
        context: dict[str, Any],
        evidence_cache: dict[tuple[str, str], list[str]],
    ) -> tuple[dict[str, Any], list[str]]:
        issues: list[str] = []
        key = self._fact_key(fact)
        valid_entries: list[dict[str, Any]] = []
        for entry in entries:
            entry_issues = self._entry_issues(
                entry,
                context=context,
                evidence_cache=evidence_cache,
            )
            if entry_issues:
                issues.extend(entry_issues)
            else:
                valid_entries.append(entry)
        if not runs:
            issues.append("profit_reconciliation_missing")
            return {}, sorted(set(issues))
        latest_run = max(runs, key=self._run_rank)
        issues.extend(
            self._run_issues(
                latest_run,
                entries=valid_entries,
                context=context,
            )
        )
        if latest_run.get("status") != "matched":
            issues.append("profit_reconciliation_not_matched")
        if issues:
            return {}, sorted(set(issues))

        payload = fact["payload"]
        gross = self._decimal_value(
            payload.get("gross_revenue"),
            "profit_order_gross_invalid",
            issues,
        )
        order_currency = self._currency_or_none(payload.get("currency"))
        if order_currency is None:
            issues.append("profit_order_currency_invalid")
        receivables = [
            item
            for item in valid_entries
            if item.get("entry_kind")
            == FinanceEntryKind.ORDER_RECEIVABLE.value
        ]
        if len(receivables) != 1:
            issues.append("profit_order_receivable_not_exact")
        elif receivables[0].get("source_fact_id") != fact.get("id"):
            issues.append("profit_order_receivable_fact_binding_invalid")
        if issues:
            return {}, sorted(set(issues))
        receivable = receivables[0]
        receivable_amount = Decimal(receivable["amount"])
        if (
            receivable_amount != gross
            or receivable.get("currency") != order_currency
        ):
            issues.append("profit_order_receivable_amount_conflict")

        fx_source = str(latest_run.get("fx_source") or "").strip()
        if not fx_source:
            issues.append("profit_reconciliation_fx_source_missing")
        normalized_entries: dict[str, Decimal] = {}
        selected_mapping_ids: dict[str, str] = {}
        selected_fx_ids: dict[str, str] = {}
        evidence_ids = {str(fact["evidence_id"])}
        revenue_erosion = ZERO
        refund_erosion = ZERO
        discount_erosion = ZERO
        cost_sources: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for entry in valid_entries:
            amount = Decimal(entry["amount"])
            mapping: dict[str, Any] | None = None
            if (
                entry.get("entry_kind")
                == FinanceEntryKind.PLATFORM_FEE.value
            ):
                mapping, mapping_issues = self._mapping_for(
                    entry=entry,
                    mappings=mappings,
                    context=context,
                    evidence_cache=evidence_cache,
                )
                issues.extend(mapping_issues)
                if mapping is None:
                    continue
                amount = self._apply_sign_rule(
                    amount,
                    FeeSignRule(mapping["sign_rule"]),
                )
                selected_mapping_ids[entry["id"]] = mapping["id"]
                evidence_ids.add(mapping["evidence_id"])
                if mapping.get("approved_by") == latest_run.get("created_by"):
                    issues.append("profit_mapping_self_review")
            converted, rate, conversion_issues = self._convert(
                amount=amount,
                currency=entry.get("currency"),
                quote_currency=quote_currency,
                effective_at=entry.get("effective_at"),
                fx_source=fx_source,
                fx_rates=fx_rates,
                context=context,
                evidence_cache=evidence_cache,
            )
            issues.extend(conversion_issues)
            if converted is None:
                continue
            normalized_entries[entry["id"]] = converted
            evidence_ids.add(entry["evidence_id"])
            if rate is not None:
                selected_fx_ids[entry["id"]] = rate["id"]
                evidence_ids.add(rate["evidence_id"])
                if rate.get("created_by") == latest_run.get("created_by"):
                    issues.append("profit_fx_self_review")

            kind = entry.get("entry_kind")
            if kind == FinanceEntryKind.PLATFORM_FEE.value:
                canonical_type = str(mapping["canonical_type"])
                if converted > ZERO:
                    issues.append("profit_platform_adjustment_sign_invalid")
                elif canonical_type in COST_VALUES:
                    cost_sources[canonical_type].append(
                        {
                            "amount": abs(converted),
                            "evidence_ids": [
                                entry["evidence_id"],
                                mapping["evidence_id"],
                            ],
                            "source": "platform_fee_mapping",
                        }
                    )
                elif canonical_type in REVENUE_EROSION_TYPES:
                    revenue_erosion += converted
                    if canonical_type == ChargeType.DISCOUNT.value:
                        discount_erosion += abs(converted)
                    else:
                        refund_erosion += abs(converted)
                else:
                    issues.append("profit_fee_classification_invalid")
            elif kind == FinanceEntryKind.RETURN_ADJUSTMENT.value:
                if converted > ZERO:
                    issues.append("profit_return_adjustment_sign_invalid")
                revenue_erosion += converted
                refund_erosion += abs(converted)
            elif kind == FinanceEntryKind.BANK_PAYMENT.value:
                cost_type = str(entry.get("profit_cost_type") or "")
                if (
                    converted > ZERO
                    or cost_type not in COST_VALUES
                    or cost_type == ChargeType.PLATFORM_FEE.value
                ):
                    issues.append("profit_bank_payment_classification_invalid")
                else:
                    cost_sources[cost_type].append(
                        {
                            "amount": abs(converted),
                            "evidence_ids": [entry["evidence_id"]],
                            "source": "bank_payment",
                        }
                    )
            elif kind == FinanceEntryKind.CASH_ADJUSTMENT.value:
                issues.append("profit_cash_adjustment_unclassified")

        if issues:
            return {}, sorted(set(issues))

        expected_mapping_ids = {
            str(item.get("entry_id")): str(item.get("mapping_id"))
            for item in (
                latest_run.get("snapshot", {}).get(
                    "applied_fee_mappings",
                    [],
                )
            )
        }
        expected_fx_ids = {
            str(item.get("entry_id")): str(item.get("fx_rate_id"))
            for item in (
                latest_run.get("snapshot", {}).get("applied_fx", [])
            )
        }
        if expected_mapping_ids != selected_mapping_ids:
            issues.append("profit_reconciliation_mapping_drift")
        if expected_fx_ids != selected_fx_ids:
            issues.append("profit_reconciliation_fx_drift")

        cost_legs: list[dict[str, Any]] = []
        cost_totals: dict[str, Decimal] = {}
        for cost_type in COST_ORDER:
            values = cost_sources.get(cost_type.value, [])
            if not values:
                cost_totals[cost_type.value] = ZERO
                cost_legs.append(
                    {
                        "cost_type": cost_type.value,
                        "status": "unknown",
                        "amount": None,
                        "currency": quote_currency,
                        "evidence_ids": [],
                        "source_count": 0,
                    }
                )
                issues.append(
                    f"profit_cost_leg_unknown:{cost_type.value}"
                )
                continue
            amount = sum((item["amount"] for item in values), ZERO)
            cost_totals[cost_type.value] = amount
            cost_legs.append(
                {
                    "cost_type": cost_type.value,
                    "status": "zero" if amount == ZERO else "actual",
                    "amount": self._decimal(amount),
                    "currency": quote_currency,
                    "evidence_ids": sorted(
                        {
                            evidence_id
                            for item in values
                            for evidence_id in item["evidence_ids"]
                        }
                    ),
                    "source_count": len(values),
                }
            )
        if issues:
            return {}, sorted(set(issues))

        gross_quote = normalized_entries[receivable["id"]]
        totals = {
            kind.value: sum(
                (
                    normalized_entries[item["id"]]
                    for item in valid_entries
                    if item["entry_kind"] == kind.value
                ),
                ZERO,
            )
            for kind in FinanceEntryKind
        }
        platform_adjustments = (
            totals[FinanceEntryKind.PLATFORM_FEE.value]
            + totals[FinanceEntryKind.RETURN_ADJUSTMENT.value]
            + totals[FinanceEntryKind.CASH_ADJUSTMENT.value]
        )
        platform_settlement = totals[
            FinanceEntryKind.PLATFORM_SETTLEMENT.value
        ]
        bank_receipt = totals[FinanceEntryKind.BANK_RECEIPT.value]
        bank_payments = totals[FinanceEntryKind.BANK_PAYMENT.value]
        expected_settlement = gross_quote + platform_adjustments
        actual_cash_profit = bank_receipt + bank_payments
        expected_cash_profit = expected_settlement + bank_payments

        if platform_settlement != expected_settlement:
            issues.append("profit_platform_settlement_not_conserved")
        if bank_receipt != platform_settlement:
            issues.append("profit_bank_receipt_not_conserved")
        if actual_cash_profit != expected_cash_profit:
            issues.append("profit_actual_cash_not_conserved")
        issues.extend(
            self._reconciliation_totals_issues(
                latest_run,
                totals=totals,
                expected_settlement=expected_settlement,
                platform_settlement=platform_settlement,
                bank_receipt=bank_receipt,
            )
        )
        bank_authorities = {
            item.get("source_evidence_sha256")
            for item in valid_entries
            if item.get("entry_kind")
            in {
                FinanceEntryKind.BANK_RECEIPT.value,
                FinanceEntryKind.BANK_PAYMENT.value,
            }
        }
        platform_authorities = {
            item.get("source_evidence_sha256")
            for item in valid_entries
            if item.get("entry_kind")
            in {
                FinanceEntryKind.ORDER_RECEIVABLE.value,
                FinanceEntryKind.PLATFORM_FEE.value,
                FinanceEntryKind.RETURN_ADJUSTMENT.value,
                FinanceEntryKind.PLATFORM_SETTLEMENT.value,
            }
        }
        if {
            item for item in bank_authorities if item
        } & {item for item in platform_authorities if item}:
            issues.append("profit_evidence_independence_conflict")

        net_revenue = gross_quote + revenue_erosion
        cm1 = net_revenue - sum(
            (cost_totals[item] for item in CM1_VALUES),
            ZERO,
        )
        cm2 = cm1 - sum(
            (cost_totals[item] for item in CM2_VALUES),
            ZERO,
        )
        cm3 = cm2 - sum(
            (cost_totals[item] for item in CM3_VALUES),
            ZERO,
        )
        if cm3 != actual_cash_profit:
            issues.append("profit_cm3_cash_conservation_conflict")
        if issues:
            return {}, sorted(set(issues))

        total_cost = sum(cost_totals.values(), ZERO)
        cm3_rate = cm3 / gross_quote if gross_quote != ZERO else ZERO
        erosion = self._erosion(
            cost_totals=cost_totals,
            discount_erosion=discount_erosion,
            refund_erosion=refund_erosion,
        )
        row = {
            "grain_key": key,
            "order_ref": key,
            "order_count": 1,
            "product_id": product["id"],
            "sku": product["sku"],
            "product_name": product["name"],
            "latest_effective_at": fact["effective_at"],
            "status": "reconciled",
            "currency": quote_currency,
            "gross_revenue": self._decimal(gross_quote),
            "net_revenue": self._decimal(net_revenue),
            "total_cost": self._decimal(total_cost),
            "cm1": self._decimal(cm1),
            "cm2": self._decimal(cm2),
            "cm3": self._decimal(cm3),
            "cm3_rate": self._decimal(cm3_rate),
            "actual_profit": self._decimal(actual_cash_profit),
            "actual_cash_cm3": {
                "status": "available",
                "amount": self._decimal(actual_cash_profit),
                "currency": quote_currency,
            },
            "cost_legs": cost_legs,
            "cost_coverage": {
                "required": len(COST_ORDER),
                "actual_or_zero": len(COST_ORDER),
                "unknown": 0,
            },
            "coverage_ratio": "1",
            "cash_conservation": {
                "gross_plus_platform_adjustments": self._decimal(
                    expected_settlement
                ),
                "platform_settlement": self._decimal(platform_settlement),
                "bank_receipt": self._decimal(bank_receipt),
                "bank_payments": self._decimal(bank_payments),
                "actual_cash_profit": self._decimal(actual_cash_profit),
                "conservation_delta": "0",
                "conserved": True,
            },
            "reconciliation": {
                "status": latest_run["status"],
                "quote_currency": latest_run["quote_currency"],
                "tolerance_ratio": latest_run["tolerance_ratio"],
                "recorded_at": latest_run["recorded_at"],
                "input_sha256": latest_run["snapshot"]["input_sha256"],
            },
            "evidence_ids": sorted(evidence_ids),
            "erosion": {
                key: self._decimal(value)
                for key, value in erosion.items()
            },
            "owner": "finance-controller",
            "sla": "before scaling, payout or management reporting",
            "next": (
                "Reverify the next settlement cycle and preserve all "
                "fifteen cost-leg Evidence."
            ),
            "next_workspace": "/finance-control",
        }
        order_ref_sha256 = self._hash(key)
        product_sha256 = self._hash(product["id"])
        sku_sha256 = self._hash(product["sku"])
        scope_receipt = {
            "tenant_ref": context["scope"]["tenant_ref"],
            "entity_ref": context["scope"]["entity_ref"],
            "store_ref": context["scope"]["store_ref"],
            "scope_grant_authority_sha256": context["scope"][
                "scope_grant_authority_sha256"
            ],
        }
        order_fact_receipt = {
            "fact_id_sha256": self._hash(fact["id"]),
            "payload_sha256": fact["payload_hash"],
            "order_ref_sha256": order_ref_sha256,
            "product_sha256": product_sha256,
            "sku_sha256": sku_sha256,
        }
        receipt = {
            "contract_id": self.ORDER_SKU_RECEIPT_CONTRACT_ID,
            "issuer_contract_id": self.CONTRACT_ID,
            "scope_sha256": self._hash(scope_receipt),
            "scope_grant_authority_sha256": scope_receipt[
                "scope_grant_authority_sha256"
            ],
            "order_ref_sha256": order_ref_sha256,
            "product_sha256": product_sha256,
            "sku_sha256": sku_sha256,
            "order_fact_receipt_sha256": self._hash(order_fact_receipt),
            "profit_row_basis_sha256": self._hash(row),
        }
        receipt["receipt_sha256"] = self._hash(receipt)
        row["canonical_order_sku_receipt"] = receipt
        row["snapshot_sha256"] = self._hash(row)
        return row, []

    def _entry_issues(
        self,
        entry: dict[str, Any],
        *,
        context: dict[str, Any],
        evidence_cache: dict[tuple[str, str], list[str]],
    ) -> list[str]:
        issues: list[str] = []
        try:
            kind = FinanceEntryKind(str(entry.get("entry_kind")))
        except ValueError:
            return ["profit_finance_entry_kind_invalid"]
        if self._currency_or_none(entry.get("currency")) is None:
            issues.append("profit_finance_entry_currency_invalid")
        amount = self._decimal_or_none(entry.get("amount"))
        if amount is None:
            issues.append("profit_finance_entry_amount_invalid")
        if not str(entry.get("reconciliation_key") or "").strip():
            issues.append("profit_finance_entry_key_missing")
        if (
            kind is FinanceEntryKind.PLATFORM_FEE
            and not str(entry.get("raw_fee_code") or "").strip()
        ):
            issues.append("profit_fee_code_missing")
        if kind is FinanceEntryKind.BANK_PAYMENT:
            if entry.get("profit_cost_type") not in COST_VALUES:
                issues.append("profit_bank_payment_cost_type_invalid")
            if amount is not None and amount > ZERO:
                issues.append("profit_bank_payment_sign_invalid")
        elif entry.get("profit_cost_type") is not None:
            issues.append("profit_cost_type_wrong_entry_kind")
        if entry.get("review_required"):
            issues.append("profit_finance_review_required")
        issues.extend(
            self._temporal_issues(
                entry,
                context=context,
                prefix="profit_finance_entry",
            )
        )
        issues.extend(
            self._evidence_issues(
                evidence_id=entry.get("evidence_id"),
                source_sha256=entry.get("source_evidence_sha256"),
                context=context,
                prefix="profit_finance_entry",
                cache=evidence_cache,
            )
        )
        return sorted(set(issues))

    def _fact_issues(
        self,
        fact: dict[str, Any],
        *,
        context: dict[str, Any],
        evidence_cache: dict[tuple[str, str], list[str]],
    ) -> list[str]:
        issues: list[str] = []
        payload = fact.get("payload")
        if not isinstance(payload, dict):
            return ["profit_order_payload_invalid"]
        if fact.get("fact_type") != "ozon_order":
            issues.append("profit_order_fact_type_invalid")
        if self._hash(payload) != fact.get("payload_hash"):
            issues.append("profit_order_payload_hash_drift")
        if fact.get("resolution_status") != "resolved":
            issues.append("profit_order_unresolved")
        if not str(fact.get("product_id") or "").strip():
            issues.append("profit_order_product_binding_missing")
        if not str(payload.get("sku") or "").strip():
            issues.append("profit_order_sku_missing")
        if self._currency_or_none(payload.get("currency")) is None:
            issues.append("profit_order_currency_invalid")
        gross = self._decimal_or_none(payload.get("gross_revenue"))
        if gross is None or gross < ZERO:
            issues.append("profit_order_gross_invalid")
        quantity = self._decimal_or_none(payload.get("quantity"))
        if (
            quantity is None
            or quantity <= ZERO
            or quantity != quantity.to_integral_value()
        ):
            issues.append("profit_order_quantity_invalid")
        issues.extend(
            self._temporal_issues(
                fact,
                context=context,
                prefix="profit_order",
            )
        )
        issues.extend(
            self._evidence_issues(
                evidence_id=fact.get("evidence_id"),
                source_sha256=fact.get("source_evidence_sha256"),
                context=context,
                prefix="profit_order",
                cache=evidence_cache,
            )
        )
        return sorted(set(issues))

    def _product_issues(
        self,
        product: dict[str, Any] | None,
        *,
        fact: dict[str, Any],
        context: dict[str, Any],
    ) -> list[str]:
        if product is None:
            return ["profit_exact_product_missing"]
        issues: list[str] = []
        payload = fact["payload"]
        if product["id"] != fact.get("product_id"):
            issues.append("profit_product_id_conflict")
        if product["sku"] != str(payload.get("sku") or "").strip():
            issues.append("profit_product_sku_conflict")
        if product["scope_as_of"] > context["cutoff"].isoformat():
            issues.append("profit_product_scope_future")
        if product["created_at"] > context["cutoff"].isoformat():
            issues.append("profit_product_created_future")
        return issues

    def _run_issues(
        self,
        run: dict[str, Any],
        *,
        entries: list[dict[str, Any]],
        context: dict[str, Any],
    ) -> list[str]:
        issues = self._temporal_issues(
            run,
            context=context,
            prefix="profit_reconciliation",
            effective_field=None,
        )
        snapshot = run.get("snapshot")
        if not isinstance(snapshot, dict):
            return sorted(
                set([*issues, "profit_reconciliation_snapshot_invalid"])
            )
        input_entries = sorted(
            (
                item
                for item in entries
                if self._timestamp(
                    item.get("recorded_at"),
                    "recorded_at",
                )
                <= self._timestamp(run.get("recorded_at"), "recorded_at")
            ),
            key=lambda item: (
                self._timestamp(item.get("effective_at"), "effective_at"),
                str(item.get("id")),
            ),
        )
        snapshot_without_hash = {
            key: value
            for key, value in snapshot.items()
            if key != "input_sha256"
        }
        expected_input = self._hash(
            {
                "reconciliation_key": run.get("reconciliation_key"),
                "quote_currency": run.get("quote_currency"),
                "fx_source": run.get("fx_source"),
                "tolerance_ratio": run.get("tolerance_ratio"),
                "entry_ids": [item["id"] for item in input_entries],
                "entry_authorities": [
                    item.get("source_evidence_sha256")
                    for item in input_entries
                ],
                "snapshot": snapshot_without_hash,
            }
        )
        if snapshot.get("input_sha256") != expected_input:
            issues.append("profit_reconciliation_input_hash_drift")
        authority = self._hash(
            sorted(
                {
                    str(item.get("source_evidence_sha256"))
                    for item in input_entries
                    if item.get("source_evidence_sha256")
                }
            )
        )
        if run.get("source_evidence_sha256") != authority:
            issues.append("profit_reconciliation_source_authority_drift")
        if run.get("created_by") in {
            item.get("created_by") for item in input_entries
        }:
            issues.append("profit_reconciliation_self_review")
        if len(input_entries) != len(entries):
            issues.append("profit_reconciliation_stale_entries")
        if self._currency_or_none(run.get("quote_currency")) is None:
            issues.append("profit_reconciliation_currency_invalid")
        if self._ratio_or_none(run.get("tolerance_ratio")) is None:
            issues.append("profit_reconciliation_tolerance_invalid")
        return sorted(set(issues))

    def _reconciliation_totals_issues(
        self,
        run: dict[str, Any],
        *,
        totals: dict[str, Decimal],
        expected_settlement: Decimal,
        platform_settlement: Decimal,
        bank_receipt: Decimal,
    ) -> list[str]:
        snapshot = run["snapshot"]
        issues: list[str] = []
        claimed_totals = snapshot.get("totals")
        if not isinstance(claimed_totals, dict):
            return ["profit_reconciliation_totals_invalid"]
        for kind in FinanceEntryKind:
            if self._decimal_or_none(claimed_totals.get(kind.value)) != totals[
                kind.value
            ]:
                issues.append("profit_reconciliation_totals_drift")
                break
        comparisons = (
            ("expected_settlement", expected_settlement),
            ("platform_settlement", platform_settlement),
            ("bank_receipt", bank_receipt),
        )
        for field, expected in comparisons:
            if self._decimal_or_none(snapshot.get(field)) != expected:
                issues.append(f"profit_reconciliation_{field}_drift")
        tolerance = Decimal(str(run["tolerance_ratio"]))
        settlement_ratio = self._variance_ratio(
            platform_settlement - expected_settlement,
            expected_settlement,
        )
        bank_ratio = self._variance_ratio(
            bank_receipt - platform_settlement,
            platform_settlement,
        )
        if settlement_ratio > tolerance or bank_ratio > tolerance:
            issues.append("profit_reconciliation_variance")
        if snapshot.get("unknown_fees"):
            issues.append("profit_unknown_fee")
        if snapshot.get("review_required"):
            issues.append("profit_finance_review_required")
        if snapshot.get("missing_fx"):
            issues.append("profit_fx_missing")
        if snapshot.get("missing_legs"):
            issues.append("profit_reconciliation_leg_missing")
        if snapshot.get("evidence_conflicts"):
            issues.append("profit_evidence_independence_conflict")
        if snapshot.get("self_review_dependencies"):
            issues.append("profit_reconciliation_self_review")
        return sorted(set(issues))

    def _mapping_for(
        self,
        *,
        entry: dict[str, Any],
        mappings: list[dict[str, Any]],
        context: dict[str, Any],
        evidence_cache: dict[tuple[str, str], list[str]],
    ) -> tuple[dict[str, Any] | None, list[str]]:
        effective = self._timestamp(entry.get("effective_at"), "effective_at")
        candidates = [
            item
            for item in mappings
            if item.get("provider") == "ozon"
            and item.get("raw_code") == entry.get("raw_fee_code")
            and self._timestamp(
                item.get("effective_from"),
                "effective_from",
            )
            <= effective
            and (
                item.get("effective_until") is None
                or self._timestamp(
                    item.get("effective_until"),
                    "effective_until",
                )
                > effective
            )
        ]
        if not candidates:
            return None, ["profit_unknown_fee"]
        mapping = max(
            candidates,
            key=lambda item: (
                self._timestamp(
                    item.get("effective_from"),
                    "effective_from",
                ),
                int(item.get("version") or 0),
                self._timestamp(item.get("recorded_at"), "recorded_at"),
                str(item.get("id")),
            ),
        )
        issues: list[str] = []
        try:
            FeeSignRule(str(mapping.get("sign_rule")))
            canonical = ChargeType(str(mapping.get("canonical_type")))
        except ValueError:
            issues.append("profit_fee_mapping_contract_invalid")
        else:
            if (
                canonical.value not in COST_VALUES
                and canonical.value not in REVENUE_EROSION_TYPES
            ):
                issues.append("profit_fee_mapping_contract_invalid")
        issues.extend(
            self._temporal_issues(
                mapping,
                context=context,
                prefix="profit_fee_mapping",
                effective_field="effective_from",
            )
        )
        issues.extend(
            self._evidence_issues(
                evidence_id=mapping.get("evidence_id"),
                source_sha256=mapping.get("source_evidence_sha256"),
                context=context,
                prefix="profit_fee_mapping",
                cache=evidence_cache,
            )
        )
        return mapping, sorted(set(issues))

    def _convert(
        self,
        *,
        amount: Decimal,
        currency: Any,
        quote_currency: str,
        effective_at: Any,
        fx_source: str,
        fx_rates: list[dict[str, Any]],
        context: dict[str, Any],
        evidence_cache: dict[tuple[str, str], list[str]],
    ) -> tuple[Decimal | None, dict[str, Any] | None, list[str]]:
        base = self._currency_or_none(currency)
        if base is None:
            return None, None, ["profit_fx_currency_invalid"]
        if base == quote_currency:
            return amount, None, []
        effective = self._timestamp(effective_at, "effective_at")
        candidates = [
            item
            for item in fx_rates
            if item.get("base_currency") == base
            and item.get("quote_currency") == quote_currency
            and item.get("source") == fx_source
            and self._timestamp(
                item.get("effective_at"),
                "effective_at",
            )
            <= effective
        ]
        if not candidates:
            return None, None, ["profit_fx_missing"]
        rate = max(
            candidates,
            key=lambda item: (
                self._timestamp(item.get("effective_at"), "effective_at"),
                int(item.get("version") or 0),
                self._timestamp(item.get("recorded_at"), "recorded_at"),
                str(item.get("id")),
            ),
        )
        issues = self._temporal_issues(
            rate,
            context=context,
            prefix="profit_fx",
        )
        rate_value = self._decimal_or_none(rate.get("rate"))
        if rate_value is None or rate_value <= ZERO:
            issues.append("profit_fx_rate_invalid")
        issues.extend(
            self._evidence_issues(
                evidence_id=rate.get("evidence_id"),
                source_sha256=rate.get("source_evidence_sha256"),
                context=context,
                prefix="profit_fx",
                cache=evidence_cache,
            )
        )
        if issues:
            return None, rate, sorted(set(issues))
        return amount * rate_value, rate, []

    def _evidence_issues(
        self,
        *,
        evidence_id: Any,
        source_sha256: Any,
        context: dict[str, Any],
        prefix: str,
        cache: dict[tuple[str, str], list[str]],
    ) -> list[str]:
        evidence_ref = str(evidence_id or "").strip()
        source_hash = str(source_sha256 or "").strip().lower()
        cache_key = (evidence_ref, source_hash)
        if cache_key in cache:
            return [
                item.replace("profit_evidence", prefix, 1)
                for item in cache[cache_key]
            ]
        canonical_issues: list[str] = []
        if not evidence_ref or not self._sha256(source_hash):
            canonical_issues.append("profit_evidence_authority_invalid")
        else:
            try:
                verification = self.evidence.verify(evidence_ref)
            except (KeyError, RuntimeError, ValueError):
                canonical_issues.append("profit_evidence_invalid")
            else:
                if (
                    not verification.valid
                    or verification.expected_sha256 != source_hash
                ):
                    canonical_issues.append("profit_evidence_invalid")
                else:
                    projection = self.scoped_evidence.project(
                        evidence_ids=[evidence_ref],
                        principal=context["principal"],
                        entity_scope=context["entity_scope"],
                        store_ref=context["scope"]["store_ref"],
                        as_of=context["cutoff"],
                    )
                    if projection.get("status") != "ready":
                        canonical_issues.append(
                            "profit_evidence_scope_invalid"
                        )
        cache[cache_key] = canonical_issues
        return [
            item.replace("profit_evidence", prefix, 1)
            for item in canonical_issues
        ]

    def _read_products(self, context: dict[str, Any]) -> dict[str, Any]:
        limit = 5000
        cutoff = context["cutoff"]
        with Session(self.engine) as session:
            rows = list(
                session.scalars(
                    select(ProductRow)
                    .where(
                        ProductRow.tenant_ref
                        == context["scope"]["tenant_ref"],
                        ProductRow.entity_ref
                        == context["scope"]["entity_ref"],
                        ProductRow.store_ref
                        == context["scope"]["store_ref"],
                        ProductRow.scope_grant_authority_sha256
                        == context["scope"][
                            "scope_grant_authority_sha256"
                        ],
                        ProductRow.scope_as_of <= cutoff,
                        ProductRow.created_at <= cutoff,
                    )
                    .order_by(ProductRow.created_at, ProductRow.id)
                    .limit(limit + 1)
                ).all()
            )
        payload = {
            "contract_id": "kjds-scoped-profit-product-source-v1",
            "as_of": cutoff.isoformat(),
            "scope": context["scope"],
            "items": [
                {
                    "id": row.id,
                    "sku": row.sku,
                    "name": row.name,
                    "market": row.market,
                    "channel": row.channel,
                    "status": row.status,
                    "created_at": self._aware(row.created_at).isoformat(),
                    "scope_as_of": self._aware(row.scope_as_of).isoformat(),
                    "created_by": row.created_by,
                }
                for row in rows[:limit]
            ],
            "truncated": len(rows) > limit,
        }
        payload["snapshot_sha256"] = self._hash(payload)
        return payload

    def _source_issues(
        self,
        source: dict[str, Any],
        *,
        contract_id: str,
        context: dict[str, Any],
    ) -> list[str]:
        issues: list[str] = []
        if source.get("contract_id") != contract_id:
            issues.append("profit_source_contract_conflict")
        if source.get("as_of") != context["cutoff"].isoformat():
            issues.append("profit_source_as_of_conflict")
        scope = source.get("scope") or {}
        for field in (
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
        ):
            if scope.get(field) != context["scope"].get(field):
                issues.append(f"profit_source_{field}_conflict")
        truncated = source.get("truncated")
        if isinstance(truncated, dict) and any(truncated.values()):
            issues.append("profit_source_truncated")
        if not self._valid_snapshot(source):
            issues.append("profit_source_snapshot_hash_drift")
        return sorted(set(issues))

    def _product_source_issues(
        self,
        source: dict[str, Any],
        *,
        context: dict[str, Any],
    ) -> list[str]:
        issues: list[str] = []
        if source.get("contract_id") != (
            "kjds-scoped-profit-product-source-v1"
        ):
            issues.append("profit_product_source_contract_conflict")
        if source.get("as_of") != context["cutoff"].isoformat():
            issues.append("profit_product_source_as_of_conflict")
        if source.get("scope") != context["scope"]:
            issues.append("profit_product_source_scope_conflict")
        if source.get("truncated"):
            issues.append("profit_product_source_truncated")
        if not self._valid_snapshot(source):
            issues.append("profit_product_source_snapshot_hash_drift")
        return issues

    @classmethod
    def _aggregate(
        cls,
        rows: list[dict[str, Any]],
        *,
        grain: str,
    ) -> list[dict[str, Any]]:
        if grain == "order":
            return list(rows)
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            key = (
                row["sku"]
                if grain == "sku"
                else row["latest_effective_at"][:10]
            )
            grouped[key].append(row)
        result: list[dict[str, Any]] = []
        for key, items in sorted(grouped.items()):
            cost_legs = []
            for cost_type in COST_ORDER:
                matching = [
                    leg
                    for item in items
                    for leg in item["cost_legs"]
                    if leg["cost_type"] == cost_type.value
                ]
                amount = sum(
                    (Decimal(leg["amount"]) for leg in matching),
                    ZERO,
                )
                cost_legs.append(
                    {
                        "cost_type": cost_type.value,
                        "status": "zero" if amount == ZERO else "actual",
                        "amount": cls._decimal(amount),
                        "currency": items[0]["currency"],
                        "evidence_ids": sorted(
                            {
                                evidence_id
                                for leg in matching
                                for evidence_id in leg["evidence_ids"]
                            }
                        ),
                        "source_count": sum(
                            int(leg["source_count"]) for leg in matching
                        ),
                    }
                )
            gross = sum(
                (Decimal(item["gross_revenue"]) for item in items),
                ZERO,
            )
            actual = sum(
                (Decimal(item["actual_profit"]) for item in items),
                ZERO,
            )
            row = {
                "grain_key": key,
                "order_ref": None,
                "order_count": len(items),
                "product_id": (
                    items[0]["product_id"] if grain == "sku" else None
                ),
                "sku": items[0]["sku"] if grain == "sku" else None,
                "product_name": (
                    items[0]["product_name"] if grain == "sku" else None
                ),
                "latest_effective_at": max(
                    item["latest_effective_at"] for item in items
                ),
                "status": "reconciled",
                "currency": items[0]["currency"],
                "gross_revenue": cls._decimal(gross),
                "net_revenue": cls._decimal(
                    sum(
                        (Decimal(item["net_revenue"]) for item in items),
                        ZERO,
                    )
                ),
                "total_cost": cls._decimal(
                    sum(
                        (Decimal(item["total_cost"]) for item in items),
                        ZERO,
                    )
                ),
                "cm1": cls._decimal(
                    sum((Decimal(item["cm1"]) for item in items), ZERO)
                ),
                "cm2": cls._decimal(
                    sum((Decimal(item["cm2"]) for item in items), ZERO)
                ),
                "cm3": cls._decimal(actual),
                "cm3_rate": cls._decimal(
                    actual / gross if gross != ZERO else ZERO
                ),
                "actual_profit": cls._decimal(actual),
                "actual_cash_cm3": {
                    "status": "available",
                    "amount": cls._decimal(actual),
                    "currency": items[0]["currency"],
                },
                "cost_legs": cost_legs,
                "cost_coverage": {
                    "required": len(COST_ORDER),
                    "actual_or_zero": len(COST_ORDER),
                    "unknown": 0,
                },
                "coverage_ratio": "1",
                "cash_conservation": {
                    "conservation_delta": "0",
                    "conserved": True,
                },
                "reconciliation": {
                    "status": "matched",
                    "order_count": len(items),
                },
                "evidence_ids": sorted(
                    {
                        evidence_id
                        for item in items
                        for evidence_id in item["evidence_ids"]
                    }
                ),
                "erosion": {
                    category: cls._decimal(
                        sum(
                            (
                                Decimal(item["erosion"][category])
                                for item in items
                            ),
                            ZERO,
                        )
                    )
                    for category in EROSION_CATEGORIES
                },
                "owner": "finance-controller",
                "sla": "before scaling, payout or management reporting",
                "next": (
                    "Reverify the next settlement cycle and preserve all "
                    "fifteen cost-leg Evidence."
                ),
                "next_workspace": "/finance-control",
            }
            row["snapshot_sha256"] = cls._hash(row)
            result.append(row)
        return result

    def verify_order_sku_receipt(
        self,
        *,
        receipt: dict[str, Any],
        store_ref: str,
        order_id: str,
        as_of: str,
        principal: Principal,
        entity_scope: dict[str, Any],
    ) -> dict[str, Any]:
        """Verify a receipt by replaying the canonical Profit authority."""
        profit = self.snapshot(
            store_ref=store_ref,
            order_id=order_id,
            grain="order",
            currency="CNY",
            as_of=as_of,
            principal=principal,
            entity_scope=entity_scope,
        )
        rows = profit.get("rows") if isinstance(profit, dict) else None
        matched = []
        if isinstance(rows, list):
            matched = [
                row
                for row in rows
                if isinstance(row, dict)
                and row.get("order_ref") == order_id
                and row.get("canonical_order_sku_receipt") == receipt
            ]
        scope = profit.get("scope") if isinstance(profit, dict) else None
        verified = (
            profit.get("contract_id") == self.CONTRACT_ID
            and profit.get("status") == "reconciled"
            and profit.get("grain") == "order"
            and profit.get("currency") == "CNY"
            and profit.get("as_of") == as_of
            and isinstance(scope, dict)
            and len(matched) == 1
            and len(rows) == 1
            and isinstance(receipt, dict)
            and receipt.get("contract_id")
            == self.ORDER_SKU_RECEIPT_CONTRACT_ID
            and receipt.get("issuer_contract_id") == self.CONTRACT_ID
            and receipt.get("receipt_sha256")
            == self._hash(
                {
                    field: value
                    for field, value in receipt.items()
                    if field != "receipt_sha256"
                }
            )
        )
        projection = {
            "contract_id": self.ORDER_SKU_RECEIPT_AUTHORITY_CONTRACT_ID,
            "status": "verified" if verified else "no_data",
            "as_of": as_of,
            "scope": (
                {
                    "tenant_ref": scope.get("tenant_ref"),
                    "entity_ref": scope.get("entity_ref"),
                    "store_ref": scope.get("store_ref"),
                    "scope_grant_authority_sha256": scope.get(
                        "scope_grant_authority_sha256"
                    ),
                }
                if isinstance(scope, dict)
                else None
            ),
            "issuer_contract_id": self.CONTRACT_ID,
            "receipt": receipt if verified else None,
            "receipt_sha256": (
                receipt.get("receipt_sha256") if verified else None
            ),
            "source_profit_snapshot_sha256": (
                profit.get("snapshot_sha256")
                if isinstance(profit, dict)
                else None
            ),
            "control_envelope": {
                "read_only": True,
                "native_exact_scope": True,
                "external_write_allowed": False,
            },
        }
        projection["snapshot_sha256"] = self._hash(projection)
        return projection

    @staticmethod
    def _erosion(
        *,
        cost_totals: dict[str, Decimal],
        discount_erosion: Decimal,
        refund_erosion: Decimal,
    ) -> dict[str, Decimal]:
        return {
            "purchase": cost_totals[ChargeType.PRODUCT_COST.value],
            "logistics": (
                cost_totals[ChargeType.DOMESTIC_LOGISTICS.value]
                + cost_totals[ChargeType.INTERNATIONAL_LOGISTICS.value]
                + cost_totals[ChargeType.LAST_MILE.value]
                + cost_totals[ChargeType.PACKAGING.value]
            ),
            "warehousing": cost_totals[ChargeType.WAREHOUSING.value],
            "commission": cost_totals[ChargeType.PLATFORM_FEE.value],
            "advertising": cost_totals[ChargeType.ADVERTISING.value],
            "returns": (
                cost_totals[ChargeType.RETURN.value] + refund_erosion
            ),
            "discount": discount_erosion,
            "tax": (
                cost_totals[ChargeType.TAX.value]
                + cost_totals[ChargeType.CUSTOMS.value]
            ),
            "fx": cost_totals[ChargeType.FX.value],
            "loss": (
                cost_totals[ChargeType.CAPITAL_COST.value]
                + cost_totals[ChargeType.DAMAGE.value]
                + cost_totals[ChargeType.CUSTOMER_COMPENSATION.value]
            ),
            "unallocated": ZERO,
        }

    @classmethod
    def _empty(
        cls,
        *,
        context: dict[str, Any],
        filters: dict[str, Any],
        grain: str,
        currency: str,
        page_size: int,
        status: str,
        reason: str,
        extra_gaps: list[str] | None = None,
        scoped_input_read: bool = False,
        source_snapshot_sha256: str | None = None,
    ) -> dict[str, Any]:
        source_gaps = [reason, *(extra_gaps or [])]
        payload = {
            "contract_id": cls.CONTRACT_ID,
            "registry_version": "native-scoped-actual-profit/1.0.0",
            "status": status,
            "as_of": context["cutoff"].isoformat(),
            "scope": {
                **context["scope"],
                "status": context["status"],
                "authority": (
                    "native_exact_scope"
                    if context["status"] == "ready"
                    else None
                ),
                "reason": reason,
            },
            "store_ref": context["scope"]["store_ref"],
            "grain": grain,
            "currency": currency,
            "filters": filters,
            "coverage_ratio": "0",
            "counts": {
                "order_candidates": 0,
                "considered": 0,
                "reconciled": 0,
                "excluded": 0,
                "filtered": 0,
                "page": 0,
            },
            "pagination": {
                "page_size": page_size,
                "next_cursor": None,
            },
            "rows": [],
            "unallocated": [],
            "excluded": {
                "count": 0,
                "reason_counts": {},
                "business_values_exposed": False,
            },
            "source_gaps": sorted(set(source_gaps)),
            "blockers": cls._blockers(source_gaps),
            "source_snapshot_sha256": source_snapshot_sha256,
            "control_envelope": cls._control_envelope(
                scoped_input_read=scoped_input_read
            ),
        }
        payload["artifact"] = cls._artifact(
            payload=payload,
            source_snapshot_sha256=source_snapshot_sha256,
        )
        payload["snapshot_sha256"] = cls._hash(payload)
        return payload

    @classmethod
    def _artifact(
        cls,
        *,
        payload: dict[str, Any],
        source_snapshot_sha256: str | None,
    ) -> dict[str, Any]:
        core = {
            "contract_id": cls.ARTIFACT_CONTRACT_ID,
            "artifact_version": "1.0.0",
            "scope": payload["scope"],
            "as_of": payload["as_of"],
            "input_sha256": source_snapshot_sha256,
            "status": payload["status"],
            "recommendations": [
                {
                    "kind": "internal_task",
                    "code": item["code"],
                    "owner": item["owner"],
                    "next": item["next"],
                }
                for item in payload["blockers"]
            ],
            "writes": {
                "fact": False,
                "product": False,
                "fee_mapping": False,
                "fx": False,
                "finance_entry": False,
                "reconciliation": False,
                "approval": False,
                "permit": False,
                "payment": False,
                "refund": False,
                "pricing": False,
                "advertising": False,
                "external": False,
            },
        }
        core["artifact_sha256"] = cls._hash(core)
        return core

    @staticmethod
    def _control_envelope(*, scoped_input_read: bool) -> dict[str, Any]:
        return {
            "read_only": True,
            "native_exact_scope": True,
            "scoped_input_read": scoped_input_read,
            "legacy_order_charge_read": False,
            "legacy_finance_read": False,
            "client_recalculation": False,
            "explicit_order_binding_only": True,
            "proportional_allocation_allowed": False,
            "fifteen_cost_legs_required": True,
            "explicit_zero_evidence_required": True,
            "actual_profit_requires_reconciliation": True,
            "agent_self_approval_allowed": False,
            "agent_permit_issue_allowed": False,
            "external_write_allowed": False,
        }

    @staticmethod
    def _blockers(source_gaps: list[str]) -> list[dict[str, Any]]:
        return [
            {
                "code": reason,
                "severity": "P0",
                "owner": "finance-data-governance",
                "sla": "before profit scoring, payout or Pilot approval",
                "next": (
                    "Bind and independently review the exact Order, "
                    "fifteen cost legs, settlement, bank and FX Evidence."
                ),
                "next_workspace": "/profit-ledger",
            }
            for reason in sorted(set(source_gaps))
        ]

    @staticmethod
    def _status(*, row_count: int, excluded_count: int) -> str:
        if row_count and excluded_count:
            return "partial"
        if row_count:
            return "reconciled"
        if excluded_count:
            return "blocked"
        return "no_data"

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
        authority = str(scope.get("authority_sha256") or "").strip().lower()
        ready = bool(
            principal is not None
            and scope.get("status") == "ready"
            and str(scope.get("entity_ref") or "").strip()
            and cls._sha256(authority)
        )
        malformed_ready = bool(scope.get("status") == "ready" and not ready)
        return {
            "status": (
                "ready"
                if ready
                else "blocked"
                if malformed_ready
                else "no_data"
            ),
            "reason": (
                "profit_scope_authority_invalid"
                if malformed_ready
                else str(
                    scope.get("reason")
                    or (
                        "profit_scope_principal_missing"
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

    @classmethod
    def _matches_filters(
        cls,
        *,
        key: str,
        payload: Any,
        effective_at: Any,
        filters: dict[str, Any],
        start: date | None,
        end: date | None,
    ) -> bool:
        if filters["order_id"] and key != filters["order_id"]:
            return False
        if not isinstance(payload, dict):
            return filters["sku"] is None
        if filters["sku"] and payload.get("sku") != filters["sku"]:
            return False
        try:
            effective_date = cls._timestamp(
                effective_at,
                "effective_at",
            ).date()
        except ValueError:
            return True
        if start and effective_date < start:
            return False
        return not (end and effective_date > end)

    @classmethod
    def _latest_fact_conflicts(
        cls,
        candidates: list[dict[str, Any]],
    ) -> list[str]:
        latest = max(candidates, key=cls._fact_rank)
        latest_effective = latest.get("effective_at")
        latest_recorded = latest.get("recorded_at")
        peers = [
            item
            for item in candidates
            if item.get("effective_at") == latest_effective
            and item.get("recorded_at") == latest_recorded
        ]
        if len({item.get("payload_hash") for item in peers}) > 1:
            return ["profit_latest_order_fact_conflict"]
        return []

    @classmethod
    def _temporal_issues(
        cls,
        item: dict[str, Any],
        *,
        context: dict[str, Any],
        prefix: str,
        effective_field: str | None = "effective_at",
    ) -> list[str]:
        issues: list[str] = []
        fields = ["recorded_at", "scope_as_of"]
        if effective_field:
            fields.append(effective_field)
        for field in fields:
            try:
                value = cls._timestamp(item.get(field), field)
            except ValueError:
                issues.append(f"{prefix}_{field}_invalid")
                continue
            if value > context["cutoff"]:
                issues.append(f"{prefix}_{field}_future")
        return issues

    @staticmethod
    def _fact_key(fact: dict[str, Any]) -> str:
        payload = fact.get("payload") or {}
        return str(
            payload.get("external_id")
            or fact.get("natural_key")
            or ""
        ).strip()

    @classmethod
    def _fact_rank(cls, fact: dict[str, Any]) -> tuple[datetime, datetime, str]:
        return (
            cls._timestamp(fact.get("effective_at"), "effective_at"),
            cls._timestamp(fact.get("recorded_at"), "recorded_at"),
            str(fact.get("id")),
        )

    @classmethod
    def _run_rank(cls, run: dict[str, Any]) -> tuple[datetime, str]:
        return (
            cls._timestamp(run.get("recorded_at"), "recorded_at"),
            str(run.get("id")),
        )

    @staticmethod
    def _grain(value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized not in {"day", "order", "sku"}:
            raise ValueError("grain must be day, order, or sku")
        return normalized

    @staticmethod
    def _page_size(value: int) -> int:
        if value < 1 or value > 250:
            raise ValueError("page_size must be between 1 and 250")
        return value

    @staticmethod
    def _currency(value: str) -> str:
        normalized = str(value or "").strip().upper()
        if (
            len(normalized) != 3
            or not normalized.isascii()
            or not normalized.isalpha()
        ):
            raise ValueError("currency must be a three-letter code")
        return normalized

    @classmethod
    def _currency_or_none(cls, value: Any) -> str | None:
        try:
            return cls._currency(str(value or ""))
        except ValueError:
            return None

    @staticmethod
    def _date(value: str, field: str) -> date:
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{field} must use YYYY-MM-DD") from exc

    @staticmethod
    def _timestamp(value: Any, field: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(
                str(value or "").replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise ValueError(
                f"{field} must be an ISO-8601 timestamp"
            ) from exc
        if parsed.tzinfo is None:
            raise ValueError(f"{field} must include a timezone")
        return parsed.astimezone(UTC)

    @staticmethod
    def _aware(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value

    @staticmethod
    def _decimal_or_none(value: Any) -> Decimal | None:
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return None
        return parsed if parsed.is_finite() else None

    @classmethod
    def _decimal_value(
        cls,
        value: Any,
        issue: str,
        issues: list[str],
    ) -> Decimal:
        parsed = cls._decimal_or_none(value)
        if parsed is None:
            issues.append(issue)
            return ZERO
        return parsed

    @classmethod
    def _ratio_or_none(cls, value: Any) -> Decimal | None:
        parsed = cls._decimal_or_none(value)
        if parsed is None or parsed < ZERO or parsed >= Decimal("1"):
            return None
        return parsed

    @staticmethod
    def _decimal(value: Decimal) -> str:
        normalized = Decimal(value)
        if normalized == ZERO:
            return "0"
        return format(normalized.normalize(), "f")

    @staticmethod
    def _apply_sign_rule(amount: Decimal, rule: FeeSignRule) -> Decimal:
        if rule is FeeSignRule.ABSOLUTE_INFLOW:
            return abs(amount)
        if rule is FeeSignRule.ABSOLUTE_OUTFLOW:
            return -abs(amount)
        return amount

    @staticmethod
    def _variance_ratio(variance: Decimal, base: Decimal) -> Decimal:
        return abs(variance) / max(abs(base), Decimal("1"))

    @classmethod
    def _cursor_key(cls, item: dict[str, Any]) -> tuple[str, str]:
        return (item["latest_effective_at"], item["grain_key"])

    @staticmethod
    def _encode_cursor(value: tuple[str, str]) -> str:
        return base64.urlsafe_b64encode(
            json.dumps(value, separators=(",", ":")).encode("utf-8")
        ).decode("ascii").rstrip("=")

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
        return (decoded[0], decoded[1])

    @staticmethod
    def _sha256(value: str) -> bool:
        return len(value) == 64 and all(
            character in "0123456789abcdef" for character in value
        )

    @classmethod
    def _valid_snapshot(cls, value: dict[str, Any]) -> bool:
        claimed = value.get("snapshot_sha256")
        if not cls._sha256(str(claimed or "")):
            return False
        return claimed == cls._hash(
            {
                key: item
                for key, item in value.items()
                if key != "snapshot_sha256"
            }
        )

    @staticmethod
    def _hash(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()


class ScopedProfitOrderSkuReceiptAuthority:
    """Server-owned verifier isolated from mutable Profit projection adapters."""

    CONTRACT_ID = "kjds-profit-order-sku-receipt-authority-v1"

    def __init__(
        self,
        *,
        engine,
        finance,
        evidence,
        scoped_evidence,
    ) -> None:
        self.__canonical_profit = ScopedProfitLedgerAuthority(
            engine=engine,
            finance=finance,
            evidence=evidence,
            scoped_evidence=scoped_evidence,
        )

    def verify_order_sku_receipt(
        self,
        *,
        receipt: dict[str, Any],
        store_ref: str,
        order_id: str,
        as_of: str,
        principal: Principal,
        entity_scope: dict[str, Any],
    ) -> dict[str, Any]:
        return self.__canonical_profit.verify_order_sku_receipt(
            receipt=receipt,
            store_ref=store_ref,
            order_id=order_id,
            as_of=as_of,
            principal=principal,
            entity_scope=entity_scope,
        )
