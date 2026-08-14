from __future__ import annotations

import base64
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from .security import Principal


class ScopedReturnsAfterSalesWorkspace:
    """Project exact OMS returns and finance outcomes without creating truth."""

    CONTRACT_ID = "kjds-native-exact-scope-returns-aftersales-v1"
    ARTIFACT_CONTRACT_ID = "kjds-returns-steward-artifact-v1"
    OMS_CONTRACT_ID = "kjds-native-scoped-oms-v1"
    FINANCE_CONTRACT_ID = (
        "kjds-native-exact-scope-settlement-cash-control-v1"
    )
    STAGES = frozenset(
        {
            "return_observed",
            "refund_finance_pending",
            "refund_settlement_pending",
            "refund_cash_pending",
            "refund_reconcile_pending",
            "refund_reconciled",
            "variance",
            "blocked",
        }
    )
    FINANCE_STAGE_MAP = {
        "fact_pending": "refund_finance_pending",
        "accrual_pending": "refund_finance_pending",
        "settlement_pending": "refund_settlement_pending",
        "cash_pending": "refund_cash_pending",
        "reconcile_pending": "refund_reconcile_pending",
        "unknown_fee": "refund_reconcile_pending",
        "reconciled": "refund_reconciled",
        "variance": "variance",
        "blocked": "blocked",
    }

    def __init__(self, *, oms, finance) -> None:
        self.oms = oms
        self.finance = finance

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
        filters = {
            "query": self._query(query) or None,
            "stage": self._stage(stage),
        }
        normalized_page_size = self._page_size(page_size)
        normalized_cursor = str(cursor or "").strip() or None
        if context["status"] != "ready":
            return self._empty(
                context=context,
                filters=filters,
                page_size=normalized_page_size,
                status=context["status"],
                reason=context["reason"],
            )

        oms = self.oms.workspace(
            principal=principal,
            entity_scope=entity_scope or {},
            store_ref=context["scope"]["store_ref"],
            as_of=context["cutoff"],
            page_size=500,
        )
        oms_issues = self._upstream_issues(
            oms,
            contract_id=self.OMS_CONTRACT_ID,
            context=context,
            prefix="returns_oms",
            items_key="orders",
        )
        if oms.get("query", {}).get("next_cursor"):
            oms_issues.append("returns_oms_projection_truncated")
        if oms_issues or oms.get("status") == "blocked":
            return self._empty(
                context=context,
                filters=filters,
                page_size=normalized_page_size,
                status="blocked",
                reason=(
                    sorted(set(oms_issues))[0]
                    if oms_issues
                    else "returns_oms_authority_blocked"
                ),
                extra_gaps=sorted(set(oms_issues))[1:],
                scoped_input_read=True,
                oms_snapshot_sha256=oms.get("snapshot_sha256"),
            )

        returned_orders = [
            item
            for item in oms.get("orders", [])
            if any(
                event.get("fact_type") == "ozon_return"
                for event in item.get("timeline", [])
            )
        ]
        if not returned_orders:
            return self._empty(
                context=context,
                filters=filters,
                page_size=normalized_page_size,
                status="no_data",
                reason="return_fact_missing",
                scoped_input_read=True,
                oms_snapshot_sha256=oms.get("snapshot_sha256"),
            )

        rows: list[dict[str, Any]] = []
        exclusions: Counter[str] = Counter()
        return_ids: set[str] = set()
        finance_hashes: dict[str, str] = {}
        for order in returned_orders:
            item, issues, finance_hash = self._return_item(
                order=order,
                context=context,
                principal=principal,
                entity_scope=entity_scope or {},
                return_ids=return_ids,
            )
            if finance_hash:
                finance_hashes[str(order.get("external_id"))] = finance_hash
            if issues:
                exclusions.update(issues)
            elif item is not None:
                rows.append(item)

        rows.sort(key=self._cursor_key, reverse=True)
        total_counts = self._counts(rows)
        filtered = [
            item
            for item in rows
            if self._matches(item, filters=filters)
        ]
        start = 0
        if normalized_cursor:
            key = self._decode_cursor(normalized_cursor)
            positions = {
                self._cursor_key(item): index
                for index, item in enumerate(filtered)
            }
            if key not in positions:
                raise ValueError(
                    "cursor does not belong to the current returns result"
                )
            start = positions[key] + 1
        page = filtered[start : start + normalized_page_size]
        next_cursor = (
            self._encode_cursor(self._cursor_key(page[-1]))
            if page and start + normalized_page_size < len(filtered)
            else None
        )
        gaps = [
            "customer_service_case_authority_missing",
            "customer_message_authority_missing",
            "platform_dispute_authority_missing",
            "rma_authority_missing",
        ]
        if exclusions:
            gaps.extend(exclusions)
        status = (
            "blocked"
            if exclusions
            else "partial"
            if rows
            else "no_data"
        )
        return self._payload(
            context=context,
            status=status,
            filters=filters,
            page_size=normalized_page_size,
            total_filtered=len(filtered),
            next_cursor=next_cursor,
            returns=page,
            total_counts=total_counts,
            excluded={
                "count": sum(exclusions.values()),
                "reason_counts": dict(sorted(exclusions.items())),
                "business_values_exposed": False,
            },
            source_gaps=gaps,
            oms_snapshot_sha256=oms.get("snapshot_sha256"),
            finance_snapshot_sha256_by_order=finance_hashes,
        )

    def _return_item(
        self,
        *,
        order: dict[str, Any],
        context: dict[str, Any],
        principal: Principal | None,
        entity_scope: dict[str, Any],
        return_ids: set[str],
    ) -> tuple[dict[str, Any] | None, list[str], str | None]:
        issues: list[str] = []
        order_id = str(order.get("external_id") or "").strip()
        product_id = str(order.get("product_id") or "").strip()
        sku = str(order.get("sku") or "").strip()
        if (
            not order_id
            or not product_id
            or not sku
            or order.get("projection_status") != "ready"
        ):
            issues.append("returns_order_authority_invalid")

        timeline = order.get("timeline")
        if not isinstance(timeline, list):
            return None, ["returns_order_timeline_invalid"], None
        order_events = [
            item for item in timeline if item.get("fact_type") == "ozon_order"
        ]
        return_events = [
            item for item in timeline if item.get("fact_type") == "ozon_return"
        ]
        order_quantities = {
            item.get("quantity")
            for item in order_events
            if self._positive_integer(item.get("quantity"))
        }
        if len(order_quantities) != 1 or len(order_events) == 0:
            issues.append("returns_order_quantity_authority_invalid")
            ordered_quantity = None
        else:
            ordered_quantity = int(next(iter(order_quantities)))

        returned_quantity = 0
        currencies = {
            str(item.get("currency") or "").strip().upper()
            for item in order_events
            if item.get("currency")
        }
        for event in return_events:
            return_id = str(event.get("external_id") or "").strip()
            fact_id = str(event.get("fact_id") or "").strip()
            if (
                not return_id
                or not fact_id
                or event.get("order_external_id") != order_id
                or event.get("product_id") != product_id
                or event.get("sku") != sku
                or not self._positive_integer(event.get("quantity"))
            ):
                issues.append("returns_fact_binding_invalid")
                continue
            if return_id in return_ids:
                issues.append("returns_duplicate_external_id")
            return_ids.add(return_id)
            returned_quantity += int(event["quantity"])
            currency = str(event.get("currency") or "").strip().upper()
            if event.get("amount") is not None:
                if not self._decimal(event.get("amount")) or not currency:
                    issues.append("returns_amount_authority_invalid")
                else:
                    currencies.add(currency)
        if ordered_quantity is not None and returned_quantity > ordered_quantity:
            issues.append("returns_quantity_exceeds_order")
        if len(currencies) > 1:
            issues.append("returns_currency_conflict")

        finance = self.finance.project(
            store_ref=context["scope"]["store_ref"],
            principal=principal,
            entity_scope=entity_scope,
            as_of=context["cutoff"].isoformat(),
            query=order_id,
            page_size=100,
        )
        finance_hash = str(finance.get("snapshot_sha256") or "") or None
        finance_issues = self._upstream_issues(
            finance,
            contract_id=self.FINANCE_CONTRACT_ID,
            context=context,
            prefix="returns_finance",
            items_key="cycles",
        )
        if finance.get("pagination", {}).get("next_cursor"):
            finance_issues.append("returns_finance_projection_truncated")
        cycles = [
            item
            for item in finance.get("cycles", [])
            if item.get("reconciliation_key") == order_id
        ]
        if len(cycles) > 1:
            finance_issues.append("returns_finance_cycle_ambiguous")
        issues.extend(finance_issues)
        if issues:
            return None, sorted(set(issues)), finance_hash

        cycle = cycles[0] if cycles else None
        finance_stage = str((cycle or {}).get("stage") or "")
        return_stage = (
            self.FINANCE_STAGE_MAP.get(
                finance_stage,
                "refund_finance_pending",
            )
            if cycle
            else "refund_finance_pending"
        )
        latest = max(
            return_events,
            key=lambda item: (
                self._timestamp(item.get("effective_at"), "effective_at"),
                self._timestamp(item.get("recorded_at"), "recorded_at"),
                str(item.get("fact_id") or ""),
            ),
        )
        return {
            "order_external_id": order_id,
            "product_id": product_id,
            "sku": sku,
            "stage": return_stage,
            "ordered_quantity": ordered_quantity,
            "returned_quantity": returned_quantity,
            "remaining_quantity": (
                ordered_quantity - returned_quantity
                if ordered_quantity is not None
                else None
            ),
            "currency": next(iter(currencies), None),
            "return_events": return_events,
            "latest_return": latest,
            "finance_cycle": cycle,
            "finance_status": (
                finance_stage or "not_observed"
            ),
            "customer_service": {
                "status": "gated",
                "customer_service_case_authority_available": False,
                "customer_message_authority_available": False,
                "platform_dispute_authority_available": False,
                "rma_authority_available": False,
            },
            "owner": self._owner(return_stage),
            "sla": self._sla(return_stage),
            "next": self._next(return_stage),
            "next_workspace": self._next_workspace(return_stage),
        }, [], finance_hash

    @classmethod
    def _upstream_issues(
        cls,
        value: dict[str, Any],
        *,
        contract_id: str,
        context: dict[str, Any],
        prefix: str,
        items_key: str,
    ) -> list[str]:
        issues = []
        if value.get("contract_id") != contract_id:
            issues.append(f"{prefix}_contract_conflict")
        if value.get("as_of") != context["cutoff"].isoformat():
            issues.append(f"{prefix}_as_of_conflict")
        if value.get("scope") != context["scope"]:
            issues.append(f"{prefix}_scope_conflict")
        if not isinstance(value.get(items_key), list):
            issues.append(f"{prefix}_payload_invalid")
        if not cls._valid_snapshot(value):
            issues.append(f"{prefix}_snapshot_hash_drift")
        return sorted(set(issues))

    def _payload(
        self,
        *,
        context: dict[str, Any],
        status: str,
        filters: dict[str, Any],
        page_size: int,
        total_filtered: int,
        next_cursor: str | None,
        returns: list[dict[str, Any]],
        total_counts: dict[str, int],
        excluded: dict[str, Any],
        source_gaps: list[str],
        oms_snapshot_sha256: str | None,
        finance_snapshot_sha256_by_order: dict[str, str],
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
                **total_counts,
                "filtered": total_filtered,
                "page": len(returns),
            },
            "pagination": {
                "page_size": page_size,
                "next_cursor": next_cursor,
            },
            "returns": returns,
            "excluded": excluded,
            "source_gaps": gaps,
            "blockers": self._blockers(gaps),
            "customer_service_authority": {
                "status": "gated",
                "customer_service_case_authority_available": False,
                "customer_message_authority_available": False,
                "platform_dispute_authority_available": False,
                "rma_authority_available": False,
            },
            "owner": "returns-control",
            "sla": "before refund, customer response or settlement close",
            "next": (
                "Observe exact Return and finance authority. Build customer "
                "service cases only through a later authorized source."
            ),
            "next_workspace": "/returns",
            "upstream": {
                "oms_snapshot_sha256": oms_snapshot_sha256,
                "finance_snapshot_sha256_by_order": dict(
                    sorted(finance_snapshot_sha256_by_order.items())
                ),
            },
            "control_envelope": {
                "read_only_projection": True,
                "scoped_input_read": scoped_input_read,
                "client_recalculation_allowed": False,
                "legacy_return_rows_admitted": False,
                "return_fact_created": False,
                "refund_created": False,
                "customer_service_case_created": False,
                "customer_message_sent": False,
                "dispute_created": False,
                "reconciliation_created": False,
                "approval_created": False,
                "permit_created": False,
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
                    "owner": "returns-control",
                    "next_workspace": "/returns",
                }
                for gap in gaps
            ],
            "authority": (
                "decision_support_and_internal_task_suggestion_only"
            ),
            "owner": "returns-control",
            "self_approval_allowed": False,
            "permit_issue_allowed": False,
            "refund_allowed": False,
            "customer_message_allowed": False,
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
        oms_snapshot_sha256: str | None = None,
    ) -> dict[str, Any]:
        return self._payload(
            context=context,
            status=status,
            filters=filters,
            page_size=page_size,
            total_filtered=0,
            next_cursor=None,
            returns=[],
            total_counts=self._counts([]),
            excluded={
                "count": 0,
                "reason_counts": {},
                "business_values_exposed": False,
            },
            source_gaps=[
                reason,
                *(extra_gaps or []),
                "customer_service_case_authority_missing",
                "customer_message_authority_missing",
                "platform_dispute_authority_missing",
                "rma_authority_missing",
            ],
            oms_snapshot_sha256=oms_snapshot_sha256,
            finance_snapshot_sha256_by_order={},
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
        malformed = bool(scope.get("status") == "ready" and not ready)
        return {
            "status": "ready" if ready else "blocked" if malformed else "no_data",
            "reason": (
                "returns_scope_authority_invalid"
                if malformed
                else str(
                    scope.get("reason")
                    or (
                        "returns_scope_principal_missing"
                        if principal is None
                        else "entity_scope_authority_missing"
                    )
                )
            ),
            "cutoff": cutoff,
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
                "scope_grant_authority_sha256": authority if ready else None,
            },
        }

    @classmethod
    def _counts(cls, rows: list[dict[str, Any]]) -> dict[str, int]:
        counts = {
            "total_returns": len(rows),
            "return_events": sum(len(item["return_events"]) for item in rows),
            "returned_units": sum(item["returned_quantity"] for item in rows),
            **{stage: 0 for stage in sorted(cls.STAGES)},
        }
        for item in rows:
            counts[item["stage"]] += 1
        return counts

    @staticmethod
    def _matches(
        item: dict[str, Any],
        *,
        filters: dict[str, Any],
    ) -> bool:
        query = filters["query"]
        return bool(
            (
                not query
                or query in item["order_external_id"].lower()
                or query in item["sku"].lower()
                or any(
                    query in str(event.get("external_id") or "").lower()
                    for event in item["return_events"]
                )
            )
            and (
                filters["stage"] is None
                or item["stage"] == filters["stage"]
            )
        )

    @staticmethod
    def _cursor_key(item: dict[str, Any]) -> str:
        latest = item["latest_return"]
        return json.dumps(
            [
                latest["effective_at"],
                latest["recorded_at"],
                latest["fact_id"],
                item["order_external_id"],
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
            or len(parsed) != 4
            or not all(isinstance(item, str) for item in parsed)
        ):
            raise ValueError("cursor is invalid")
        return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def _valid_snapshot(cls, value: dict[str, Any]) -> bool:
        claimed = str(value.get("snapshot_sha256") or "")
        if not cls._sha256(claimed):
            return False
        return claimed == cls._hash(
            {
                key: item
                for key, item in value.items()
                if key != "snapshot_sha256"
            }
        )

    @staticmethod
    def _positive_integer(value: Any) -> bool:
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return False
        return parsed.is_finite() and parsed > 0 and parsed == parsed.to_integral()

    @staticmethod
    def _decimal(value: Any) -> bool:
        try:
            return Decimal(str(value)).is_finite()
        except (InvalidOperation, TypeError, ValueError):
            return False

    @staticmethod
    def _query(value: str | None) -> str:
        normalized = str(value or "").strip().lower()
        if len(normalized) > 160:
            raise ValueError("query must be at most 160 characters")
        return normalized

    @classmethod
    def _stage(cls, value: str | None) -> str | None:
        normalized = str(value or "").strip()
        if not normalized:
            return None
        if normalized not in cls.STAGES:
            raise ValueError("stage is unsupported")
        return normalized

    @staticmethod
    def _page_size(value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("page_size must be an integer")
        if not 1 <= value <= 100:
            raise ValueError("page_size must be between 1 and 100")
        return value

    @staticmethod
    def _timestamp(value: Any, field: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(
                str(value).replace("Z", "+00:00")
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} must be ISO-8601") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{field} must include a timezone")
        return parsed.astimezone(UTC)

    @staticmethod
    def _sha256(value: str) -> bool:
        return len(value) == 64 and all(
            character in "0123456789abcdef" for character in value.lower()
        )

    @staticmethod
    def _blockers(gaps: list[str]) -> list[dict[str, str]]:
        return [
            {
                "code": gap,
                "severity": "P0",
                "owner": "returns-control",
                "next_action": (
                    "Repair exact Return/Finance authority or use a later "
                    "authorized service-case intake."
                ),
                "workspace": "/returns",
            }
            for gap in sorted(set(gaps))
        ]

    @staticmethod
    def _owner(stage: str) -> str:
        return (
            "finance-control"
            if stage != "return_observed"
            else "returns-control"
        )

    @staticmethod
    def _sla(stage: str) -> str:
        return {
            "return_observed": "before any refund decision",
            "refund_finance_pending": "before financial close",
            "refund_settlement_pending": "within platform settlement window",
            "refund_cash_pending": "within one banking day of expected cash",
            "refund_reconcile_pending": "before management close",
            "refund_reconciled": "monitor through next settlement cycle",
            "variance": "within the platform dispute window",
            "blocked": "immediate evidence-governance review",
        }[stage]

    @staticmethod
    def _next(stage: str) -> str:
        return {
            "return_observed": "Bind exact refund finance Evidence.",
            "refund_finance_pending": "Observe reviewed return accrual.",
            "refund_settlement_pending": "Observe official settlement.",
            "refund_cash_pending": "Observe independent bank Readback.",
            "refund_reconcile_pending": "Run independent reconciliation.",
            "refund_reconciled": "Monitor Actual Cash CM3 impact.",
            "variance": "Stop and investigate the exact variance.",
            "blocked": "Repair the failed Return or Finance authority.",
        }[stage]

    @staticmethod
    def _next_workspace(stage: str) -> str:
        return (
            "/profit-ledger"
            if stage == "refund_reconciled"
            else "/evidenceops"
            if stage == "blocked"
            else "/finance-control"
        )

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
