from __future__ import annotations

import base64
import hashlib
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from .finance import FinanceEntryKind
from .scoped_profit_ledger import ScopedProfitOrderSkuReceiptAuthority
from .security import Principal


class ScopedSettlementCashWorkspace:
    """Project native three-book finance state without creating financial truth."""

    CONTRACT_ID = "kjds-native-exact-scope-settlement-cash-control-v1"
    ARTIFACT_CONTRACT_ID = "kjds-finance-steward-artifact-v1"
    SOURCE_CONTRACT_ID = "kjds-scoped-finance-read-source-v1"
    STAGES = frozenset(
        {
            "fact_pending",
            "accrual_pending",
            "settlement_pending",
            "cash_pending",
            "reconcile_pending",
            "variance",
            "unknown_fee",
            "reconciled",
            "blocked",
        }
    )
    FACT_TYPES = frozenset(
        {
            "ozon_order",
            "ozon_accrual",
            "ozon_settlement",
            "ozon_fee",
            "ozon_return",
        }
    )
    ENTRY_KINDS = frozenset(item.value for item in FinanceEntryKind)
    RECONCILIATION_STATUSES = frozenset(
        {
            "matched",
            "variance",
            "incomplete",
            "blocked_missing_fx",
            "blocked_unknown_fee",
            "blocked_review_required",
            "blocked_evidence_independence",
            "blocked_self_review",
        }
    )

    def __init__(
        self,
        *,
        finance,
        evidence,
        scoped_evidence,
        profit_ledger,
        profit_receipt_authority,
    ) -> None:
        self.finance = finance
        self.evidence = evidence
        self.scoped_evidence = scoped_evidence
        self.profit_ledger = profit_ledger
        self.profit_receipt_authority = profit_receipt_authority

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

        sources = self.finance.read_scoped_sources(
            tenant_ref=context["scope"]["tenant_ref"],
            entity_ref=context["scope"]["entity_ref"],
            store_ref=context["scope"]["store_ref"],
            scope_grant_authority_sha256=context["scope"][
                "scope_grant_authority_sha256"
            ],
            as_of=context["cutoff"].isoformat(),
        )
        source_conflicts = self._source_contract_conflicts(
            sources,
            context=context,
        )
        if source_conflicts:
            return self._empty(
                context=context,
                filters=filters,
                page_size=normalized_page_size,
                status="blocked",
                reason=source_conflicts[0],
                extra_gaps=source_conflicts[1:],
                scoped_input_read=True,
                source_snapshot_sha256=sources.get("snapshot_sha256"),
            )

        invalid_keys: dict[str, set[str]] = defaultdict(set)
        facts: list[dict[str, Any]] = []
        entries: list[dict[str, Any]] = []
        reconciliations: list[dict[str, Any]] = []

        for fact in sources["facts"]:
            key = self._fact_key(fact)
            issues = self._fact_issues(
                fact,
                context=context,
            )
            if not key:
                issues.append("finance_fact_reconciliation_key_missing")
                key = self._opaque_invalid_key("fact", fact.get("id"))
            if issues:
                invalid_keys[key].update(issues)
            else:
                facts.append({**fact, "_key": key})

        for entry in sources["entries"]:
            key = str(entry.get("reconciliation_key") or "").strip()
            issues = self._entry_issues(
                entry,
                context=context,
            )
            if not key:
                issues.append("finance_entry_reconciliation_key_missing")
                key = self._opaque_invalid_key("entry", entry.get("id"))
            if issues:
                invalid_keys[key].update(issues)
            else:
                entries.append({**entry, "_key": key})

        entries_by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for entry in entries:
            entries_by_key[entry["_key"]].append(entry)
        reconciliation_candidates: dict[
            str, list[dict[str, Any]]
        ] = defaultdict(list)
        for run in sources["reconciliations"]:
            key = str(run.get("reconciliation_key") or "").strip()
            if not key:
                invalid_key = self._opaque_invalid_key(
                    "reconciliation",
                    run.get("id"),
                )
                invalid_keys[invalid_key].add(
                    "finance_reconciliation_key_missing"
                )
                continue
            reconciliation_candidates[key].append(run)

        for key, candidates in reconciliation_candidates.items():
            run = max(
                candidates,
                key=self._reconciliation_rank,
            )
            issues = self._reconciliation_issues(
                run,
                entries=entries_by_key.get(key, []),
                context=context,
            )
            if issues:
                invalid_keys[key].update(issues)
            else:
                reconciliations.append({**run, "_key": key})

        facts_by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
        runs_by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for fact in facts:
            facts_by_key[fact["_key"]].append(fact)
        for run in reconciliations:
            runs_by_key[run["_key"]].append(run)

        keys = sorted(
            set(facts_by_key) | set(entries_by_key) | set(runs_by_key)
        )
        cycles: list[dict[str, Any]] = []
        exclusion_reasons: Counter[str] = Counter()
        for key in keys:
            if key in invalid_keys:
                exclusion_reasons.update(invalid_keys[key])
                continue
            cycle = self._cycle(
                key=key,
                facts=facts_by_key.get(key, []),
                entries=entries_by_key.get(key, []),
                reconciliations=runs_by_key.get(key, []),
                context=context,
            )
            cycles.append(cycle)
        for key in sorted(set(invalid_keys) - set(keys)):
            exclusion_reasons.update(invalid_keys[key])

        cycles.sort(
            key=lambda item: (
                item["latest_effective_at"],
                item["reconciliation_key"],
            ),
            reverse=True,
        )
        total_counts = self._counts(cycles)
        filtered = [
            item
            for item in cycles
            if (
                not normalized_query
                or normalized_query
                in item["reconciliation_key"].lower()
                or normalized_query in str(item.get("currency") or "").lower()
            )
            and (
                normalized_stage is None
                or item["stage"] == normalized_stage
            )
        ]
        cursor_key = (
            self._decode_cursor(normalized_cursor)
            if normalized_cursor
            else None
        )
        if cursor_key is not None:
            positions = {
                self._cursor_key(item): index
                for index, item in enumerate(filtered)
            }
            if cursor_key not in positions:
                raise ValueError(
                    "cursor does not belong to the current finance result"
                )
            filtered = filtered[positions[cursor_key] + 1 :]
        page = filtered[:normalized_page_size]
        has_more = len(filtered) > normalized_page_size
        next_cursor = (
            self._encode_cursor(self._cursor_key(page[-1]))
            if has_more and page
            else None
        )

        source_gaps = [
            f"finance_source_excluded:{reason}"
            for reason in sorted(exclusion_reasons)
        ]
        if not cycles:
            source_gaps.append("scoped_finance_cycle_missing")
        if cycles and any(
            item["actual_cash_cm3"]["status"] != "available"
            for item in cycles
        ):
            source_gaps.append("actual_cash_cm3_authority_missing")
        status = self._status(
            cycles=cycles,
            excluded_count=sum(exclusion_reasons.values()),
        )
        return self._payload(
            context=context,
            status=status,
            filters=filters,
            page_size=normalized_page_size,
            total_filtered=len(
                [
                    item
                    for item in cycles
                    if (
                        not normalized_query
                        or normalized_query
                        in item["reconciliation_key"].lower()
                        or normalized_query
                        in str(item.get("currency") or "").lower()
                    )
                    and (
                        normalized_stage is None
                        or item["stage"] == normalized_stage
                    )
                ]
            ),
            next_cursor=next_cursor,
            cycles=page,
            total_counts=total_counts,
            excluded={
                "count": sum(exclusion_reasons.values()),
                "reason_counts": dict(sorted(exclusion_reasons.items())),
                "business_values_exposed": False,
            },
            source_gaps=sorted(set(source_gaps)),
            source_snapshot_sha256=sources["snapshot_sha256"],
        )

    def _cycle(
        self,
        *,
        key: str,
        facts: list[dict[str, Any]],
        entries: list[dict[str, Any]],
        reconciliations: list[dict[str, Any]],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        order_facts = [
            item for item in facts if item["fact_type"] == "ozon_order"
        ]
        accrual_facts = [
            item for item in facts if item["fact_type"] == "ozon_accrual"
        ]
        settlement_facts = [
            item
            for item in facts
            if item["fact_type"] == "ozon_settlement"
        ]
        fee_facts = [
            item for item in facts if item["fact_type"] == "ozon_fee"
        ]
        return_facts = [
            item for item in facts if item["fact_type"] == "ozon_return"
        ]
        settlement_entries = [
            item
            for item in entries
            if item["entry_kind"] == "platform_settlement"
        ]
        bank_entries = [
            item
            for item in entries
            if item["entry_kind"] == "bank_receipt"
        ]
        fee_entries = [
            item
            for item in entries
            if item["entry_kind"] == "platform_fee"
        ]
        settlement_fact_amount = self._sum_fact_amount(
            settlement_facts,
            "amount",
        )
        settlement_entry_amount = self._sum_entry_amount(
            settlement_entries
        )
        latest_run = (
            max(
                reconciliations,
                key=lambda item: (
                    item["recorded_at"],
                    item["id"],
                ),
            )
            if reconciliations
            else None
        )
        currencies = {
            str(value).strip().upper()
            for value in [
                *[
                    (item.get("payload") or {}).get("currency")
                    for item in facts
                ],
                *[item.get("currency") for item in entries],
            ]
            if str(value or "").strip()
        }
        blockers: list[str] = []
        if len(currencies) > 1:
            blockers.append("finance_cycle_currency_conflict")
        if (
            settlement_fact_amount is not None
            and settlement_entry_amount is not None
            and Decimal(settlement_fact_amount)
            != Decimal(settlement_entry_amount)
        ):
            blockers.append("finance_settlement_source_conflict")
        unknown_fees = bool(
            latest_run
            and (latest_run.get("snapshot") or {}).get("unknown_fees")
        )
        review_required = any(
            bool(item.get("review_required")) for item in entries
        )
        if review_required:
            blockers.append("finance_entry_review_required")
        if len(order_facts) > 1:
            order_identities = {
                (
                    str(item.get("payload_hash") or ""),
                    str(item.get("product_id") or "").strip(),
                    str((item.get("payload") or {}).get("sku") or "").strip(),
                )
                for item in order_facts
            }
            if len(order_identities) > 1:
                blockers.append("finance_order_fact_current_conflict")
        if order_facts and any(
            not str(item.get("product_id") or "").strip()
            or not str((item.get("payload") or {}).get("sku") or "").strip()
            for item in order_facts
        ):
            blockers.append("finance_order_product_sku_binding_missing")
        if latest_run and latest_run["status"] in {
            "blocked_missing_fx",
            "blocked_review_required",
            "blocked_evidence_independence",
            "blocked_self_review",
        }:
            blockers.append(
                f"finance_reconciliation_{latest_run['status']}"
            )
        stage = self._cycle_stage(
            has_order=bool(order_facts),
            has_accrual=bool(accrual_facts or fee_facts),
            has_settlement=bool(
                settlement_facts or settlement_entries
            ),
            has_cash=bool(bank_entries),
            latest_run=latest_run,
            unknown_fees=unknown_fees,
            blockers=blockers,
        )
        all_records = [*facts, *entries, *reconciliations]
        latest_effective = max(
            (
                str(
                    item.get("effective_at")
                    or item.get("recorded_at")
                    or context["cutoff"].isoformat()
                )
                for item in all_records
            ),
            default=context["cutoff"].isoformat(),
        )
        actual_cash = self._actual_cash_cm3(
            key=key,
            stage=stage,
            order_facts=order_facts,
            context=context,
        )
        evidence_ids = sorted(
            {
                str(item.get("evidence_id"))
                for item in [*facts, *entries]
                if item.get("evidence_id")
            }
        )
        books = {
            "order_accrual": {
                "order_fact_count": len(order_facts),
                "accrual_fact_count": len(accrual_facts),
                "fee_fact_count": len(fee_facts),
                "return_fact_count": len(return_facts),
                "gross_revenue": self._sum_fact_amount(
                    order_facts,
                    "gross_revenue",
                ),
                "accrual_total": self._sum_fact_amount(
                    accrual_facts,
                    "amount",
                ),
                "status": (
                    "observed"
                    if order_facts and (accrual_facts or fee_facts)
                    else "incomplete"
                ),
            },
            "platform_settlement": {
                "fact_count": len(settlement_facts),
                "entry_count": len(settlement_entries),
                "amount": (
                    settlement_fact_amount
                    if settlement_entry_amount is None
                    else settlement_entry_amount
                    if settlement_fact_amount is None
                    else settlement_fact_amount
                    if settlement_fact_amount == settlement_entry_amount
                    else None
                ),
                "status": (
                    "observed"
                    if settlement_facts or settlement_entries
                    else "missing"
                ),
            },
            "bank_cash": {
                "entry_count": len(bank_entries),
                "amount": self._sum_entry_amount(bank_entries),
                "status": "observed" if bank_entries else "missing",
            },
        }
        run_snapshot = latest_run.get("snapshot") if latest_run else {}
        return {
            "reconciliation_key": key,
            "reconciliation_key_sha256": self._hash(key),
            "currency": next(iter(currencies), None),
            "stage": stage,
            "latest_effective_at": latest_effective,
            "books": books,
            "variance": {
                "expected_settlement": run_snapshot.get(
                    "expected_settlement"
                ),
                "settlement_variance": run_snapshot.get(
                    "settlement_variance"
                ),
                "settlement_variance_ratio": run_snapshot.get(
                    "settlement_variance_ratio"
                ),
                "bank_variance": run_snapshot.get("bank_variance"),
                "bank_variance_ratio": run_snapshot.get(
                    "bank_variance_ratio"
                ),
            },
            "classification": {
                "unknown_fee_count": len(
                    run_snapshot.get("unknown_fees") or []
                ),
                "review_required_count": sum(
                    bool(item.get("review_required"))
                    for item in entries
                ),
                "fee_entry_count": len(fee_entries),
            },
            "latest_reconciliation": (
                {
                    "id": latest_run["id"],
                    "status": latest_run["status"],
                    "recorded_at": latest_run["recorded_at"],
                    "created_by": latest_run["created_by"],
                    "input_sha256": run_snapshot.get("input_sha256"),
                }
                if latest_run
                else None
            ),
            "actual_cash_cm3": actual_cash,
            "evidence": {
                "count": len(evidence_ids),
                "ids": evidence_ids,
                "all_current_and_exact_scope": not blockers,
            },
            "blockers": sorted(set(blockers)),
            "owner": "finance-control",
            "sla": self._sla(stage),
            "next": self._next(stage),
            "next_workspace": self._next_workspace(stage),
        }

    def _actual_cash_cm3(
        self,
        *,
        key: str,
        stage: str,
        order_facts: list[dict[str, Any]],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        if stage != "reconciled":
            return self._actual_cash_no_data(
                "three_book_reconciliation_incomplete"
            )
        if not bool(
            getattr(self.profit_ledger, "native_exact_scope", False)
        ):
            return self._actual_cash_no_data(
                "native_exact_scope_profit_source_missing"
            )
        profit = self.profit_ledger.snapshot(
            store_ref=context["scope"]["store_ref"],
            order_id=key,
            grain="order",
            currency="CNY",
            as_of=context["cutoff"].isoformat(),
            principal=context["principal"],
            entity_scope=context["entity_scope"],
        )
        if not isinstance(profit, dict):
            return self._actual_cash_no_data(
                "scoped_profit_authority_contract_invalid"
            )
        profit_hash = str(profit.get("snapshot_sha256") or "")
        expected_scope = {
            "tenant_ref": context["scope"]["tenant_ref"],
            "entity_ref": context["scope"]["entity_ref"],
            "store_ref": context["scope"]["store_ref"],
            "scope_grant_authority_sha256": context["scope"][
                "scope_grant_authority_sha256"
            ],
        }
        profit_scope = profit.get("scope")
        envelope = profit.get("control_envelope")
        pagination = profit.get("pagination")
        counts = profit.get("counts")
        filters = profit.get("filters")
        rows = profit.get("rows")
        try:
            profit_cutoff = self._timestamp(
                profit.get("as_of"),
                "profit.as_of",
            )
        except ValueError:
            profit_cutoff = None
        if (
            profit.get("contract_id")
            != "kjds-native-exact-scope-actual-profit-ledger-v1"
            or not self._valid_snapshot(profit)
            or profit.get("status") != "reconciled"
            or profit.get("grain") != "order"
            or profit.get("store_ref") != context["scope"]["store_ref"]
            or profit.get("currency") != "CNY"
            or profit_cutoff != context["cutoff"]
            or not isinstance(profit_scope, dict)
            or {
                field: profit_scope.get(field)
                for field in expected_scope
            }
            != expected_scope
            or not isinstance(envelope, dict)
            or envelope.get("read_only") is not True
            or envelope.get("native_exact_scope") is not True
            or envelope.get("scoped_input_read") is not True
            or envelope.get("explicit_order_binding_only") is not True
            or envelope.get("proportional_allocation_allowed") is not False
            or envelope.get("actual_profit_requires_reconciliation") is not True
            or envelope.get("external_write_allowed") is not False
            or not isinstance(pagination, dict)
            or pagination.get("page_size") != 100
            or pagination.get("next_cursor") is not None
            or not isinstance(counts, dict)
            or {
                field: counts.get(field)
                for field in (
                    "order_candidates",
                    "considered",
                    "reconciled",
                    "excluded",
                    "filtered",
                    "page",
                )
            }
            != {
                "order_candidates": 1,
                "considered": 1,
                "reconciled": 1,
                "excluded": 0,
                "filtered": 1,
                "page": 1,
            }
            or not isinstance(filters, dict)
            or filters.get("order_id") != key
            or any(
                filters.get(field) is not None
                for field in ("sku", "date_from", "date_to", "query")
            )
            or not isinstance(rows, list)
            or len(rows) != 1
            or profit.get("source_gaps") != []
            or profit.get("blockers") != []
        ):
            return self._actual_cash_no_data(
                "scoped_profit_authority_contract_invalid",
                profit_snapshot_sha256=(profit_hash or None),
            )
        matches = [
            row
            for row in rows
            if isinstance(row, dict)
            and row.get("order_ref") == key
            and row.get("status") == "reconciled"
            and row.get("actual_profit") is not None
        ]
        if (
            profit.get("status") != "reconciled"
            or len(matches) != 1
            or len(order_facts) != 1
            or profit.get("unallocated")
            or not isinstance(profit.get("excluded"), dict)
            or profit["excluded"].get("count") != 0
        ):
            return self._actual_cash_no_data(
                "scoped_profit_reconciliation_incomplete",
                profit_snapshot_sha256=(profit_hash or None),
            )
        row = matches[0]
        row_cash = row.get("actual_cash_cm3")
        conservation = row.get("cash_conservation")
        receipt = row.get("canonical_order_sku_receipt")
        product_id = str(row.get("product_id") or "").strip()
        sku = str(row.get("sku") or "").strip()
        identities = {
            (
                str(item.get("product_id") or "").strip(),
                str((item.get("payload") or {}).get("sku") or "").strip(),
            )
            for item in order_facts
        }
        order_fact = order_facts[0] if len(order_facts) == 1 else None
        scope_receipt = {
            "tenant_ref": context["scope"]["tenant_ref"],
            "entity_ref": context["scope"]["entity_ref"],
            "store_ref": context["scope"]["store_ref"],
            "scope_grant_authority_sha256": context["scope"][
                "scope_grant_authority_sha256"
            ],
        }
        expected_order_fact_receipt = (
            self._hash(
                {
                    "fact_id_sha256": self._hash(order_fact["id"]),
                    "payload_sha256": order_fact["payload_hash"],
                    "order_ref_sha256": self._hash(key),
                    "product_sha256": self._hash(product_id),
                    "sku_sha256": self._hash(sku),
                }
            )
            if isinstance(order_fact, dict)
            else None
        )
        receipt_fields = {
            "contract_id",
            "issuer_contract_id",
            "scope_sha256",
            "scope_grant_authority_sha256",
            "order_ref_sha256",
            "product_sha256",
            "sku_sha256",
            "order_fact_receipt_sha256",
            "profit_row_basis_sha256",
            "receipt_sha256",
        }
        receipt_valid = (
            isinstance(receipt, dict)
            and set(receipt) == receipt_fields
            and receipt.get("contract_id")
            == "canonical_order_sku_receipt_v1"
            and receipt.get("issuer_contract_id")
            == "kjds-native-exact-scope-actual-profit-ledger-v1"
            and all(
                self._sha256(str(receipt.get(field) or ""))
                for field in receipt_fields
                if field not in {"contract_id", "issuer_contract_id"}
            )
            and receipt.get("scope_sha256") == self._hash(scope_receipt)
            and receipt.get("scope_grant_authority_sha256")
            == scope_receipt["scope_grant_authority_sha256"]
            and receipt.get("order_ref_sha256") == self._hash(key)
            and receipt.get("product_sha256") == self._hash(product_id)
            and receipt.get("sku_sha256") == self._hash(sku)
            and receipt.get("order_fact_receipt_sha256")
            == expected_order_fact_receipt
            and receipt.get("profit_row_basis_sha256")
            == self._hash(
                {
                    field: value
                    for field, value in row.items()
                    if field
                    not in {
                        "canonical_order_sku_receipt",
                        "snapshot_sha256",
                    }
                }
            )
            and receipt.get("receipt_sha256")
            == self._hash(
                {
                    field: value
                    for field, value in receipt.items()
                    if field != "receipt_sha256"
                }
            )
        )
        receipt_authority = None
        verifier = self.profit_receipt_authority
        if (
            receipt_valid
            and type(verifier) is ScopedProfitOrderSkuReceiptAuthority
        ):
            try:
                receipt_authority = verifier.verify_order_sku_receipt(
                    receipt=receipt,
                    store_ref=context["scope"]["store_ref"],
                    order_id=key,
                    as_of=context["cutoff"].isoformat(),
                    principal=context["principal"],
                    entity_scope=context["entity_scope"],
                )
            except Exception:
                receipt_authority = None
        receipt_authority_fields = {
            "contract_id",
            "status",
            "as_of",
            "scope",
            "issuer_contract_id",
            "receipt",
            "receipt_sha256",
            "source_profit_snapshot_sha256",
            "control_envelope",
            "snapshot_sha256",
        }
        receipt_authority_scope = (
            receipt_authority.get("scope")
            if isinstance(receipt_authority, dict)
            else None
        )
        receipt_authority_envelope = (
            receipt_authority.get("control_envelope")
            if isinstance(receipt_authority, dict)
            else None
        )
        receipt_authority_valid = (
            isinstance(receipt_authority, dict)
            and set(receipt_authority) == receipt_authority_fields
            and self._valid_snapshot(receipt_authority)
            and receipt_authority.get("contract_id")
            == "kjds-profit-order-sku-receipt-authority-v1"
            and receipt_authority.get("status") == "verified"
            and receipt_authority.get("as_of")
            == context["cutoff"].isoformat()
            and receipt_authority.get("issuer_contract_id")
            == "kjds-native-exact-scope-actual-profit-ledger-v1"
            and receipt_authority.get("receipt") == receipt
            and receipt_authority.get("receipt_sha256")
            == receipt.get("receipt_sha256")
            and receipt_authority.get("source_profit_snapshot_sha256")
            == profit_hash
            and isinstance(receipt_authority_scope, dict)
            and {
                field: receipt_authority_scope.get(field)
                for field in expected_scope
            }
            == expected_scope
            and isinstance(receipt_authority_envelope, dict)
            and receipt_authority_envelope.get("read_only") is True
            and receipt_authority_envelope.get("native_exact_scope") is True
            and receipt_authority_envelope.get("external_write_allowed")
            is False
        )
        if (
            row.get("order_count") != 1
            or not product_id
            or not sku
            or identities != {(product_id, sku)}
            or not self._valid_snapshot(row)
            or not receipt_valid
            or not receipt_authority_valid
            or row.get("currency") != "CNY"
            or not self._decimal(row.get("actual_profit"))
            or not isinstance(row_cash, dict)
            or row_cash.get("status") != "available"
            or not self._decimal(row_cash.get("amount"))
            or Decimal(str(row_cash.get("amount")))
            != Decimal(str(row.get("actual_profit")))
            or row_cash.get("currency") != "CNY"
            or not isinstance(conservation, dict)
            or conservation.get("conserved") is not True
            or not self._decimal(conservation.get("conservation_delta"))
            or Decimal(str(conservation.get("conservation_delta"))) != 0
        ):
            return self._actual_cash_no_data(
                "single_sku_profit_attribution_invalid",
                profit_snapshot_sha256=profit_hash,
            )
        attribution = {
            "schema_version": "single-sku-attribution/2",
            "status": "verified",
            "identity_count": 1,
            "scope_sha256": receipt["scope_sha256"],
            "scope_grant_authority_sha256": receipt[
                "scope_grant_authority_sha256"
            ],
            "product_sha256": receipt["product_sha256"],
            "sku_sha256": receipt["sku_sha256"],
            "order_ref_sha256": receipt["order_ref_sha256"],
            "order_fact_receipt_sha256": receipt[
                "order_fact_receipt_sha256"
            ],
            "profit_row_basis_sha256": receipt[
                "profit_row_basis_sha256"
            ],
            "profit_row_sha256": row["snapshot_sha256"],
            "profit_receipt_sha256": receipt["receipt_sha256"],
        }
        attribution["lineage_sha256"] = self._hash(attribution)
        return {
            "status": "available",
            "amount": row["actual_profit"],
            "currency": profit["currency"],
            "reason": None,
            "profit_snapshot_sha256": profit_hash,
            "single_sku_attribution": attribution,
        }

    @staticmethod
    def _actual_cash_no_data(
        reason: str,
        *,
        profit_snapshot_sha256: str | None = None,
    ) -> dict[str, Any]:
        return {
            "status": "no_data",
            "amount": None,
            "currency": None,
            "reason": reason,
            "profit_snapshot_sha256": profit_snapshot_sha256,
            "single_sku_attribution": {
                "schema_version": "single-sku-attribution/2",
                "status": "no_data",
                "identity_count": 0,
                "scope_sha256": None,
                "scope_grant_authority_sha256": None,
                "product_sha256": None,
                "sku_sha256": None,
                "order_ref_sha256": None,
                "order_fact_receipt_sha256": None,
                "profit_row_basis_sha256": None,
                "profit_row_sha256": None,
                "profit_receipt_sha256": None,
                "lineage_sha256": None,
            },
        }

    def _fact_issues(
        self,
        fact: dict[str, Any],
        *,
        context: dict[str, Any],
    ) -> list[str]:
        issues: list[str] = []
        if fact.get("fact_type") not in self.FACT_TYPES:
            issues.append("finance_fact_type_invalid")
        payload = fact.get("payload")
        if not isinstance(payload, dict):
            return ["finance_fact_payload_invalid"]
        if self._hash(payload) != fact.get("payload_hash"):
            issues.append("finance_fact_payload_hash_drift")
        if fact.get("resolution_status") != "resolved":
            issues.append("finance_fact_unresolved")
        issues.extend(
            self._temporal_issues(
                fact,
                context=context,
                prefix="finance_fact",
            )
        )
        if not self._currency(payload.get("currency")):
            issues.append("finance_fact_currency_invalid")
        amount_field = (
            "gross_revenue"
            if fact.get("fact_type") == "ozon_order"
            else "amount"
        )
        if not self._decimal(payload.get(amount_field)):
            issues.append("finance_fact_amount_invalid")
        issues.extend(
            self._evidence_issues(
                evidence_id=fact.get("evidence_id"),
                source_sha256=fact.get("source_evidence_sha256"),
                context=context,
                prefix="finance_fact",
            )
        )
        return sorted(set(issues))

    def _entry_issues(
        self,
        entry: dict[str, Any],
        *,
        context: dict[str, Any],
    ) -> list[str]:
        issues: list[str] = []
        if entry.get("entry_kind") not in self.ENTRY_KINDS:
            issues.append("finance_entry_kind_invalid")
        if not self._currency(entry.get("currency")):
            issues.append("finance_entry_currency_invalid")
        if not self._decimal(entry.get("amount")):
            issues.append("finance_entry_amount_invalid")
        issues.extend(
            self._temporal_issues(
                entry,
                context=context,
                prefix="finance_entry",
            )
        )
        issues.extend(
            self._evidence_issues(
                evidence_id=entry.get("evidence_id"),
                source_sha256=entry.get("source_evidence_sha256"),
                context=context,
                prefix="finance_entry",
            )
        )
        return sorted(set(issues))

    def _reconciliation_issues(
        self,
        run: dict[str, Any],
        *,
        entries: list[dict[str, Any]],
        context: dict[str, Any],
    ) -> list[str]:
        issues: list[str] = []
        if run.get("status") not in self.RECONCILIATION_STATUSES:
            issues.append("finance_reconciliation_status_invalid")
        if not self._currency(run.get("quote_currency")):
            issues.append("finance_reconciliation_currency_invalid")
        if not self._ratio(run.get("tolerance_ratio")):
            issues.append("finance_reconciliation_tolerance_invalid")
        issues.extend(
            self._temporal_issues(
                run,
                context=context,
                prefix="finance_reconciliation",
                effective_field=None,
            )
        )
        snapshot = run.get("snapshot")
        if not isinstance(snapshot, dict):
            return sorted(
                set(
                    [
                        *issues,
                        "finance_reconciliation_snapshot_invalid",
                    ]
                )
            )
        claimed = str(snapshot.get("input_sha256") or "")
        snapshot_without_hash = {
            key: value
            for key, value in snapshot.items()
            if key != "input_sha256"
        }
        input_entries = [
            entry
            for entry in entries
            if entry["recorded_at"] <= run["recorded_at"]
        ]
        expected = self._hash(
            {
                "reconciliation_key": run.get(
                    "reconciliation_key"
                ),
                "quote_currency": run.get("quote_currency"),
                "fx_source": run.get("fx_source"),
                "tolerance_ratio": run.get("tolerance_ratio"),
                "entry_ids": [entry["id"] for entry in input_entries],
                "entry_authorities": [
                    entry.get("source_evidence_sha256")
                    for entry in input_entries
                ],
                "snapshot": snapshot_without_hash,
            }
        )
        if claimed != expected:
            issues.append("finance_reconciliation_input_hash_drift")
        authority = self._hash(
            sorted(
                {
                    str(entry.get("source_evidence_sha256"))
                    for entry in input_entries
                    if entry.get("source_evidence_sha256")
                }
            )
        )
        if run.get("source_evidence_sha256") != authority:
            issues.append(
                "finance_reconciliation_source_authority_drift"
            )
        if run.get("created_by") in {
            entry.get("created_by") for entry in input_entries
        }:
            issues.append("finance_reconciliation_self_review")
        return sorted(set(issues))

    def _evidence_issues(
        self,
        *,
        evidence_id: Any,
        source_sha256: Any,
        context: dict[str, Any],
        prefix: str,
    ) -> list[str]:
        evidence_ref = str(evidence_id or "").strip()
        source_hash = str(source_sha256 or "").strip().lower()
        if not evidence_ref or not self._sha256(source_hash):
            return [f"{prefix}_evidence_authority_missing"]
        try:
            verification = self.evidence.verify(evidence_ref)
        except (KeyError, RuntimeError, ValueError):
            return [f"{prefix}_evidence_invalid"]
        if (
            not verification.valid
            or verification.expected_sha256 != source_hash
        ):
            return [f"{prefix}_evidence_invalid"]
        projection = self.scoped_evidence.project(
            evidence_ids=[evidence_ref],
            principal=context["principal"],
            entity_scope=context["entity_scope"],
            store_ref=context["scope"]["store_ref"],
            as_of=context["cutoff"],
        )
        if projection.get("status") != "ready":
            return [f"{prefix}_evidence_scope_invalid"]
        return []

    def _source_contract_conflicts(
        self,
        sources: dict[str, Any],
        *,
        context: dict[str, Any],
    ) -> list[str]:
        issues: list[str] = []
        if sources.get("contract_id") != self.SOURCE_CONTRACT_ID:
            issues.append("finance_source_contract_conflict")
        if sources.get("as_of") != context["cutoff"].isoformat():
            issues.append("finance_source_as_of_conflict")
        scope = sources.get("scope") or {}
        for field in (
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
        ):
            if scope.get(field) != context["scope"].get(field):
                issues.append(f"finance_source_{field}_conflict")
        if any((sources.get("truncated") or {}).values()):
            issues.append("finance_source_truncated")
        if not self._valid_snapshot(sources):
            issues.append("finance_source_snapshot_hash_drift")
        return sorted(set(issues))

    def _temporal_issues(
        self,
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
                value = self._timestamp(item.get(field), field)
            except ValueError:
                issues.append(f"{prefix}_{field}_invalid")
                continue
            if value > context["cutoff"]:
                issues.append(f"{prefix}_{field}_future")
        return issues

    def _payload(
        self,
        *,
        context: dict[str, Any],
        status: str,
        filters: dict[str, Any],
        page_size: int,
        total_filtered: int,
        next_cursor: str | None,
        cycles: list[dict[str, Any]],
        total_counts: dict[str, int],
        excluded: dict[str, Any],
        source_gaps: list[str],
        source_snapshot_sha256: str | None,
        scoped_input_read: bool = True,
    ) -> dict[str, Any]:
        core = {
            "contract_id": self.CONTRACT_ID,
            "status": status,
            "as_of": context["cutoff"].isoformat(),
            "scope": context["scope"],
            "filters": filters,
            "counts": {
                **total_counts,
                "filtered": total_filtered,
                "page": len(cycles),
            },
            "pagination": {
                "page_size": page_size,
                "next_cursor": next_cursor,
            },
            "cycles": cycles,
            "excluded": excluded,
            "source_gaps": sorted(set(source_gaps)),
            "blockers": self._blockers(source_gaps),
            "owner": "finance-control",
            "sla": "before settlement close, scale or cash-profit claim",
            "next": (
                "Bind exact scoped financial Evidence and complete the "
                "three-book independent reconciliation."
            ),
            "next_workspace": "/finance-control",
            "upstream": {
                "finance_source_snapshot_sha256": (
                    source_snapshot_sha256
                ),
            },
            "control_envelope": {
                "read_only": True,
                "scoped_input_read": scoped_input_read,
                "client_recalculation_allowed": False,
                "legacy_finance_rows_admitted": False,
                "proportional_allocation_allowed": False,
                "finance_entry_created": False,
                "reconciliation_created": False,
                "fact_created": False,
                "cash_plan_created": False,
                "approval_created": False,
                "permit_created": False,
                "payment_initiated": False,
                "collection_initiated": False,
                "refund_initiated": False,
                "dispute_initiated": False,
                "external_write_allowed": False,
            },
        }
        input_hash = self._hash(core)
        suggestions = [
            {
                "type": "internal_task_suggestion",
                "code": gap,
                "owner": "finance-control",
                "next_workspace": "/finance-control",
            }
            for gap in core["source_gaps"]
        ]
        artifact = {
            "contract_id": self.ARTIFACT_CONTRACT_ID,
            "version": "1",
            "scope": context["scope"],
            "as_of": context["cutoff"].isoformat(),
            "input_snapshot_sha256": input_hash,
            "suggestions": suggestions,
            "authority": (
                "decision_support_and_internal_task_suggestion_only"
            ),
            "owner": "finance-control",
            "self_approval_allowed": False,
            "permit_issue_allowed": False,
            "finance_record_creation_allowed": False,
            "payment_or_refund_allowed": False,
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
            cycles=[],
            total_counts=self._counts([]),
            excluded={
                "count": 0,
                "reason_counts": {},
                "business_values_exposed": False,
            },
            source_gaps=sorted(
                set([reason, *(extra_gaps or [])])
            ),
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
                "finance_scope_authority_invalid"
                if malformed_ready
                else str(
                    scope.get("reason")
                    or (
                        "finance_scope_principal_missing"
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
    def _fact_key(fact: dict[str, Any]) -> str:
        payload = fact.get("payload") or {}
        return str(
            payload.get("order_external_id")
            or payload.get("external_id")
            or fact.get("natural_key")
            or ""
        ).strip()

    @staticmethod
    def _cycle_stage(
        *,
        has_order: bool,
        has_accrual: bool,
        has_settlement: bool,
        has_cash: bool,
        latest_run: dict[str, Any] | None,
        unknown_fees: bool,
        blockers: list[str],
    ) -> str:
        if blockers:
            return "blocked"
        if unknown_fees or (
            latest_run
            and latest_run.get("status") == "blocked_unknown_fee"
        ):
            return "unknown_fee"
        if not has_order:
            return "fact_pending"
        if not has_accrual:
            return "accrual_pending"
        if not has_settlement:
            return "settlement_pending"
        if not has_cash:
            return "cash_pending"
        if latest_run is None or latest_run.get("status") == "incomplete":
            return "reconcile_pending"
        if latest_run.get("status") == "variance":
            return "variance"
        if latest_run.get("status") == "matched":
            return "reconciled"
        return "blocked"

    @classmethod
    def _reconciliation_rank(
        cls,
        run: dict[str, Any],
    ) -> tuple[datetime, str]:
        try:
            recorded_at = cls._timestamp(
                run.get("recorded_at"),
                "recorded_at",
            )
        except ValueError:
            recorded_at = datetime.max.replace(tzinfo=UTC)
        return recorded_at, str(run.get("id") or "")

    @classmethod
    def _counts(cls, cycles: list[dict[str, Any]]) -> dict[str, int]:
        counts = {
            "total_cycles": len(cycles),
            "order_fact_cycles": 0,
            "accrual_cycles": 0,
            "settlement_cycles": 0,
            "cash_cycles": 0,
            "actual_cash_cm3_available": 0,
            **{stage: 0 for stage in sorted(cls.STAGES)},
        }
        for item in cycles:
            counts[item["stage"]] += 1
            counts["order_fact_cycles"] += bool(
                item["books"]["order_accrual"]["order_fact_count"]
            )
            counts["accrual_cycles"] += bool(
                item["books"]["order_accrual"]["accrual_fact_count"]
                or item["books"]["order_accrual"]["fee_fact_count"]
            )
            counts["settlement_cycles"] += bool(
                item["books"]["platform_settlement"]["fact_count"]
                or item["books"]["platform_settlement"]["entry_count"]
            )
            counts["cash_cycles"] += bool(
                item["books"]["bank_cash"]["entry_count"]
            )
            counts["actual_cash_cm3_available"] += (
                item["actual_cash_cm3"]["status"] == "available"
            )
        return counts

    @staticmethod
    def _status(
        *,
        cycles: list[dict[str, Any]],
        excluded_count: int,
    ) -> str:
        if excluded_count:
            return "blocked"
        if not cycles:
            return "no_data"
        if all(item["stage"] == "reconciled" for item in cycles):
            return (
                "ready"
                if all(
                    item["actual_cash_cm3"]["status"] == "available"
                    for item in cycles
                )
                else "partial"
            )
        if all(item["stage"] == "blocked" for item in cycles):
            return "blocked"
        return "partial"

    @staticmethod
    def _blockers(source_gaps: list[str]) -> list[dict[str, Any]]:
        return [
            {
                "code": gap,
                "severity": "P0",
                "owner": "finance-control",
                "sla": "before settlement close, scale or cash-profit claim",
                "next": (
                    "Inspect the exact Evidence and repair the authoritative "
                    "finance leg without proportional allocation."
                ),
                "next_workspace": "/finance-control",
            }
            for gap in sorted(set(source_gaps))
        ]

    @staticmethod
    def _sum_fact_amount(
        facts: list[dict[str, Any]],
        field: str,
    ) -> str | None:
        if not facts:
            return None
        return ScopedSettlementCashWorkspace._decimal_text(
            sum(
                (
                    Decimal(str((item.get("payload") or {})[field]))
                    for item in facts
                ),
                Decimal("0"),
            )
        )

    @staticmethod
    def _sum_entry_amount(
        entries: list[dict[str, Any]],
    ) -> str | None:
        if not entries:
            return None
        return ScopedSettlementCashWorkspace._decimal_text(
            sum(
                (Decimal(str(item["amount"])) for item in entries),
                Decimal("0"),
            )
        )

    @staticmethod
    def _currency(value: Any) -> bool:
        normalized = str(value or "").strip().upper()
        return bool(
            len(normalized) == 3
            and normalized.isascii()
            and normalized.isalpha()
        )

    @staticmethod
    def _decimal(value: Any) -> bool:
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return False
        return parsed.is_finite()

    @staticmethod
    def _ratio(value: Any) -> bool:
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return False
        return parsed.is_finite() and Decimal("0") <= parsed < Decimal("1")

    @staticmethod
    def _decimal_text(value: Decimal) -> str:
        if value == 0:
            return "0"
        return format(value.normalize(), "f")

    @staticmethod
    def _timestamp(value: Any, field: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(
                str(value).replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise ValueError(
                f"{field} must be an ISO-8601 timestamp"
            ) from exc
        if parsed.tzinfo is None:
            raise ValueError(f"{field} must include a timezone")
        return parsed.astimezone(UTC)

    @staticmethod
    def _sha256(value: str) -> bool:
        return bool(
            len(value) == 64
            and all(
                character in "0123456789abcdef"
                for character in value.lower()
            )
        )

    @classmethod
    def _valid_snapshot(cls, value: dict[str, Any]) -> bool:
        claimed = str(value.get("snapshot_sha256") or "")
        if not cls._sha256(claimed):
            return False
        return cls._hash(
            {
                key: item
                for key, item in value.items()
                if key != "snapshot_sha256"
            }
        ) == claimed

    @staticmethod
    def _query(value: str | None) -> str:
        normalized = str(value or "").strip().lower()
        if len(normalized) > 160:
            raise ValueError("query must be at most 160 characters")
        return normalized

    @classmethod
    def _stage(cls, value: str | None) -> str | None:
        normalized = str(value or "").strip().lower()
        if not normalized:
            return None
        if normalized not in cls.STAGES:
            raise ValueError("stage is not supported")
        return normalized

    @staticmethod
    def _page_size(value: int) -> int:
        if value < 1 or value > 100:
            raise ValueError("page_size must be between 1 and 100")
        return value

    @staticmethod
    def _cursor_key(item: dict[str, Any]) -> str:
        return json.dumps(
            [
                item["latest_effective_at"],
                item["reconciliation_key"],
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @staticmethod
    def _encode_cursor(value: str) -> str:
        return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")

    @staticmethod
    def _decode_cursor(value: str) -> str:
        try:
            padding = "=" * (-len(value) % 4)
            decoded = base64.urlsafe_b64decode(value + padding).decode()
            parsed = json.loads(decoded)
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("cursor is invalid") from exc
        if (
            not isinstance(parsed, list)
            or len(parsed) != 2
            or not all(isinstance(item, str) for item in parsed)
        ):
            raise ValueError("cursor is invalid")
        return json.dumps(
            parsed,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @staticmethod
    def _opaque_invalid_key(kind: str, value: Any) -> str:
        return f"invalid:{kind}:{ScopedSettlementCashWorkspace._hash(value)[:16]}"

    @staticmethod
    def _sla(stage: str) -> str:
        return {
            "fact_pending": "before financial ingestion",
            "accrual_pending": "before settlement close",
            "settlement_pending": "within platform settlement window",
            "cash_pending": "within one banking day after expected payout",
            "reconcile_pending": "before management close",
            "variance": "within the platform dispute window",
            "unknown_fee": "before fee classification approval",
            "reconciled": "monitor through the next settlement cycle",
            "blocked": "immediate finance data-governance review",
        }[stage]

    @staticmethod
    def _next(stage: str) -> str:
        return {
            "fact_pending": "Promote reviewed official Order Fact.",
            "accrual_pending": "Bind reviewed Accrual and fee classification.",
            "settlement_pending": "Bind official Platform Settlement.",
            "cash_pending": "Bind independent bank receipt Evidence.",
            "reconcile_pending": "Run independent three-book reconciliation.",
            "variance": "Investigate variance without proportional allocation.",
            "unknown_fee": "Approve the exact fee mapping independently.",
            "reconciled": "Await native Actual Cash CM3 authority.",
            "blocked": "Repair the failed exact-scope authority.",
        }[stage]

    @staticmethod
    def _next_workspace(stage: str) -> str:
        return {
            "fact_pending": "/formal-facts",
            "accrual_pending": "/finance-control",
            "settlement_pending": "/finance-control",
            "cash_pending": "/finance-control",
            "reconcile_pending": "/finance-control",
            "variance": "/finance-control",
            "unknown_fee": "/finance-control",
            "reconciled": "/profit-ledger",
            "blocked": "/evidenceops",
        }[stage]

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
