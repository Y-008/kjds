from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .facts import FactRecordRow
from .order_fact_semantics import (
    database_order_timestamp,
    is_explicit_currency,
    is_positive_decimal,
    is_positive_integer,
    order_timestamp,
)
from .ozon_contracts import CONTRACT_VERSION as OZON_CONTRACT_VERSION
from .security import Principal
from .sql_repository import ProductRow

ORDER_STATUS_MAP = {
    "created": "created",
    "paid": "paid",
    "awaiting_packaging": "awaiting_packaging",
    "awaiting_deliver": "awaiting_handover",
    "awaiting_handover": "awaiting_handover",
    "shipped": "in_transit",
    "delivering": "in_transit",
    "in_transit": "in_transit",
    "delivered": "delivered",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "returned": "returned",
}
RETURN_STATUS_MAP = {
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "returned": "returned",
}


class ScopedOmsWorkspace:
    """Project exact-scope formal Facts into a read-only OMS timeline."""

    CONTRACT_ID = "kjds-native-scoped-oms-v1"
    MAX_FACT_ROWS = 10000

    def __init__(self, *, engine, evidence) -> None:
        self.engine = engine
        self.evidence = evidence

    def workspace(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        page_size: int = 100,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        if not 1 <= page_size <= 500:
            raise ValueError("OMS page_size must be between 1 and 500")
        context = self._context(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        normalized_cursor = str(cursor or "").strip() or None
        if context["status"] != "ready":
            return self._empty(
                context=context,
                page_size=page_size,
                cursor=normalized_cursor,
            )

        rows, truncated = self._fact_rows(context)
        products = self._products(context)
        timelines: dict[str, list[dict[str, Any]]] = defaultdict(list)
        invalid_by_order: dict[str, list[dict[str, Any]]] = defaultdict(list)
        invalid_fact_ids: list[str] = []
        gaps: set[str] = set()
        raw_order_fact_count = sum(
            row.fact_type == "ozon_order" for row in rows
        )
        raw_return_fact_count = sum(
            row.fact_type == "ozon_return" for row in rows
        )

        for row in rows:
            event, reason = self._event(
                row=row,
                products=products,
                store_ref=store_ref,
            )
            if event is None:
                invalid_fact_ids.append(row.id)
                gaps.add(reason or "oms_fact_invalid")
                invalid_link = self._invalid_order_link(row, reason)
                if invalid_link is not None:
                    invalid_by_order[
                        invalid_link["order_external_id"]
                    ].append(invalid_link)
                continue
            timelines[event["order_external_id"]].append(event)

        order_ids = {
            external_id
            for external_id, events in timelines.items()
            if any(event["fact_type"] == "ozon_order" for event in events)
        }
        order_ids.update(
            external_id
            for external_id, events in invalid_by_order.items()
            if any(event["fact_type"] == "ozon_order" for event in events)
        )
        all_orders = [
            self._order(
                external_id,
                timelines.get(external_id, []),
                invalid_by_order.get(external_id, []),
            )
            for external_id in order_ids
        ]
        all_orders.sort(
            key=self._order_sort_key,
            reverse=True,
        )
        total_current_orders = len(all_orders)
        reliable_current_orders = sum(
            item["projection_status"] != "blocked"
            for item in all_orders
        )
        if any(
            item["current_state"] == "unknown" for item in all_orders
        ):
            gaps.add("unknown_order_lifecycle_status")
        if normalized_cursor is not None:
            cursor_key = self._decode_cursor(normalized_cursor)
            all_orders = [
                item
                for item in all_orders
                if self._order_sort_key(item) < cursor_key
            ]
        page = all_orders[:page_size]
        next_cursor = (
            self._encode_cursor(self._order_sort_key(page[-1]))
            if len(all_orders) > page_size and page
            else None
        )
        if truncated:
            gaps.add("oms_fact_scan_truncated")

        status = (
            "no_data"
            if raw_order_fact_count == 0
            else "blocked"
            if total_current_orders == 0
            or reliable_current_orders == 0
            else "partial"
            if gaps
            else "ready"
        )
        blockers = [
            self._blocker(code)
            for code in sorted(gaps)
        ]
        core = {
            "contract_id": self.CONTRACT_ID,
            "status": status,
            "as_of": context["cutoff"].isoformat(),
            "scope": context["scope"],
            "query": {
                "page_size": page_size,
                "cursor": normalized_cursor,
                "next_cursor": next_cursor,
                "max_fact_rows": self.MAX_FACT_ROWS,
            },
            "counts": {
                "raw_order_facts": raw_order_fact_count,
                "raw_return_facts": raw_return_fact_count,
                "valid_timeline_events": sum(
                    len(item["timeline"]) for item in page
                ),
                "total_current_orders": total_current_orders,
                "page_current_orders": len(page),
                "blocked_current_orders": sum(
                    item["projection_status"] == "blocked"
                    for item in page
                ),
                "invalid_facts": len(invalid_fact_ids),
                "legacy_orders_read": 0,
            },
            "orders": page,
            "invalid_fact_ids": sorted(invalid_fact_ids),
            "source_gaps": sorted(gaps),
            "blockers": blockers,
            "control_envelope": self._control(input_read=True),
        }
        agent_input_sha = self._hash(core)
        core["agent_support"] = {
            "authority": "decision_support_only",
            "input_snapshot_sha256": agent_input_sha,
            "suggestions": [
                self._agent_suggestion(item)
                for item in page
            ],
            "automatic_actions": [],
            "self_approval_allowed": False,
            "permit_issue_allowed": False,
        }
        core["snapshot_sha256"] = self._hash(core)
        return core

    def _invalid_order_link(
        self,
        row: FactRecordRow,
        reason: str | None,
    ) -> dict[str, Any] | None:
        payload = row.payload_json or {}
        if not isinstance(payload, dict):
            return None
        payload_hash_valid = self._hash(payload) == row.payload_hash
        payload_external_id = str(
            payload.get("external_id") or ""
        ).strip()
        order_external_id = ""
        if row.fact_type == "ozon_order":
            natural_key = str(row.natural_key or "").strip()
            if (
                natural_key
                and payload_external_id
                and natural_key == payload_external_id
            ):
                order_external_id = natural_key
        elif row.fact_type == "ozon_return" and payload_hash_valid:
            order_external_id = str(
                payload.get("order_external_id") or ""
            ).strip()
        if not order_external_id:
            return None
        return {
            "fact_id": row.id,
            "fact_type": row.fact_type,
            "order_external_id": order_external_id,
            "effective_at": database_order_timestamp(
                row.effective_at
            ).isoformat(),
            "recorded_at": database_order_timestamp(
                row.recorded_at
            ).isoformat(),
            "evidence_id": row.evidence_id,
            "validation_status": "blocked",
            "blocker_code": reason or "oms_fact_invalid",
        }

    def _event(
        self,
        *,
        row: FactRecordRow,
        products: dict[str, ProductRow],
        store_ref: str,
    ) -> tuple[dict[str, Any] | None, str | None]:
        payload = row.payload_json or {}
        if row.contract_version != OZON_CONTRACT_VERSION:
            return None, "oms_fact_contract_version_mismatch"
        if self._hash(payload) != row.payload_hash:
            return None, "oms_fact_payload_hash_mismatch"
        if not self._evidence_valid(row):
            return None, "oms_fact_evidence_invalid"
        product = products.get(str(row.product_id or ""))
        if product is None:
            return None, "oms_product_scope_or_binding_missing"
        if str(payload.get("sku") or "") != product.sku:
            return None, "oms_fact_sku_mismatch"
        payload_store = str(payload.get("store_ref") or "").strip()
        if payload_store and payload_store != store_ref:
            return None, "oms_fact_store_mismatch"

        external_id = str(payload.get("external_id") or "").strip()
        order_external_id = (
            external_id
            if row.fact_type == "ozon_order"
            else str(payload.get("order_external_id") or "").strip()
        )
        if not external_id:
            return None, "oms_fact_external_id_missing"
        if not order_external_id:
            return None, "oms_return_order_link_missing"
        if not is_positive_integer(payload.get("quantity")):
            return None, "oms_fact_quantity_invalid"

        raw_status = str(payload.get("status") or "").strip().lower()
        canonical_status = (
            ORDER_STATUS_MAP.get(raw_status, "unknown")
            if row.fact_type == "ozon_order"
            else RETURN_STATUS_MAP.get(raw_status, "unknown")
        )
        currency = None
        amount = None
        if row.fact_type == "ozon_order":
            if not is_positive_decimal(payload.get("gross_revenue")):
                return None, "oms_order_revenue_invalid"
            if not is_explicit_currency(payload.get("currency")):
                return None, "oms_order_currency_invalid"
            currency = str(payload["currency"])
            amount = str(Decimal(str(payload["gross_revenue"])))
        elif payload.get("amount") is not None:
            if not is_positive_decimal(payload.get("amount")):
                return None, "oms_return_amount_invalid"
            if not is_explicit_currency(payload.get("currency")):
                return None, "oms_return_currency_invalid"
            currency = str(payload["currency"])
            amount = str(Decimal(str(payload["amount"])))

        return (
            {
                "fact_id": row.id,
                "fact_type": row.fact_type,
                "external_id": external_id,
                "order_external_id": order_external_id,
                "product_id": product.id,
                "sku": product.sku,
                "quantity": int(Decimal(str(payload["quantity"]))),
                "currency": currency,
                "amount": amount,
                "raw_status": raw_status or None,
                "canonical_status": canonical_status,
                "return_reason": (
                    str(payload.get("return_reason") or "").strip() or None
                ),
                "effective_at": database_order_timestamp(
                    row.effective_at
                ).isoformat(),
                "recorded_at": database_order_timestamp(
                    row.recorded_at
                ).isoformat(),
                "evidence_id": row.evidence_id,
                "source_evidence_sha256": row.source_evidence_sha256,
            },
            None,
        )

    def _evidence_valid(self, row: FactRecordRow) -> bool:
        try:
            verification = self.evidence.verify(row.evidence_id)
        except (KeyError, RuntimeError, ValueError):
            return False
        return bool(
            verification.valid
            and verification.expected_sha256
            == row.source_evidence_sha256
        )

    @classmethod
    def _order(
        cls,
        external_id: str,
        events: list[dict[str, Any]],
        invalid_events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        timeline = sorted(
            events,
            key=lambda item: (
                order_timestamp(item["effective_at"]),
                order_timestamp(item["recorded_at"]),
                item["fact_id"],
            ),
        )
        blocked_events = sorted(
            invalid_events,
            key=lambda item: (
                order_timestamp(item["effective_at"]),
                order_timestamp(item["recorded_at"]),
                item["fact_id"],
            ),
        )
        last_valid = timeline[-1] if timeline else None
        last_blocked = blocked_events[-1] if blocked_events else None
        latest_is_blocked = bool(
            last_blocked is not None
            and (
                last_valid is None
                or cls._event_sort_key(last_blocked)
                >= cls._event_sort_key(last_valid)
            )
        )
        current = last_blocked if latest_is_blocked else last_valid
        if current is None:
            raise ValueError("OMS order projection requires at least one event")
        current_state = (
            "unknown"
            if latest_is_blocked
            else str(current["canonical_status"])
        )
        return {
            "external_id": external_id,
            "product_id": (
                last_valid["product_id"] if last_valid else None
            ),
            "sku": last_valid["sku"] if last_valid else None,
            "current_state": current_state,
            "current_event": current,
            "projection_status": (
                "blocked"
                if latest_is_blocked
                else "partial"
                if current_state == "unknown"
                else "ready"
            ),
            "timeline": timeline,
            "blocked_events": blocked_events,
            "timeline_event_count": len(timeline),
            "evidence_ids": sorted(
                {
                    item["evidence_id"]
                    for item in [*timeline, *blocked_events]
                }
            ),
            "fact_ids": [
                item["fact_id"] for item in [*timeline, *blocked_events]
            ],
            "owner": (
                "evidence-governance"
                if latest_is_blocked
                else cls._owner(current_state)
            ),
            "sla": (
                "before any fulfillment, procurement or customer action"
                if latest_is_blocked
                else cls._sla(current_state)
            ),
            "next": (
                "Repair and independently verify the latest formal Fact "
                "before treating any prior lifecycle state as current."
                if latest_is_blocked
                else cls._next(current_state)
            ),
            "next_workspace": (
                "/formal-facts"
                if latest_is_blocked
                else cls._workspace(current_state)
            ),
        }

    @staticmethod
    def _event_sort_key(
        event: dict[str, Any],
    ) -> tuple[datetime, datetime, str]:
        return (
            order_timestamp(event["effective_at"]),
            order_timestamp(event["recorded_at"]),
            str(event["fact_id"]),
        )

    @staticmethod
    def _order_sort_key(
        order: dict[str, Any],
    ) -> tuple[datetime, str]:
        return (
            order_timestamp(order["current_event"]["effective_at"]),
            str(order["external_id"]),
        )

    @staticmethod
    def _encode_cursor(key: tuple[datetime, str]) -> str:
        payload = json.dumps(
            {
                "effective_at": key[0].isoformat(),
                "external_id": key[1],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return base64.urlsafe_b64encode(payload).decode().rstrip("=")

    @staticmethod
    def _decode_cursor(value: str) -> tuple[datetime, str]:
        try:
            padding = "=" * (-len(value) % 4)
            decoded = json.loads(
                base64.urlsafe_b64decode(value + padding)
            )
            external_id = str(decoded["external_id"]).strip()
            effective_at = order_timestamp(decoded["effective_at"])
        except (
            KeyError,
            TypeError,
            ValueError,
            binascii.Error,
            json.JSONDecodeError,
        ) as exc:
            raise ValueError("OMS cursor is invalid") from exc
        if not external_id:
            raise ValueError("OMS cursor is invalid")
        return effective_at, external_id

    @staticmethod
    def _agent_suggestion(order: dict[str, Any]) -> dict[str, Any]:
        return {
            "order_external_id": order["external_id"],
            "suggestion_type": "internal_next_action",
            "current_state": order["current_state"],
            "owner": order["owner"],
            "sla": order["sla"],
            "next": order["next"],
            "next_workspace": order["next_workspace"],
            "fact_ids": order["fact_ids"],
            "evidence_ids": order["evidence_ids"],
            "external_action_allowed": False,
        }

    def _fact_rows(
        self,
        context: dict[str, Any],
    ) -> tuple[list[FactRecordRow], bool]:
        scope = context["scope"]
        cutoff = context["cutoff"]
        query = (
            select(FactRecordRow)
            .where(
                FactRecordRow.tenant_ref == scope["tenant_ref"],
                FactRecordRow.entity_ref == scope["entity_ref"],
                FactRecordRow.store_ref == scope["store_ref"],
                FactRecordRow.scope_grant_authority_sha256
                == scope["scope_grant_authority_sha256"],
                FactRecordRow.fact_type.in_(
                    ("ozon_order", "ozon_return")
                ),
                FactRecordRow.resolution_status == "resolved",
                FactRecordRow.scope_as_of <= cutoff,
                FactRecordRow.effective_at <= cutoff,
                FactRecordRow.recorded_at <= cutoff,
            )
            .order_by(
                FactRecordRow.effective_at,
                FactRecordRow.recorded_at,
                FactRecordRow.id,
            )
            .limit(self.MAX_FACT_ROWS + 1)
        )
        with Session(self.engine) as session:
            rows = list(session.scalars(query).all())
        return rows[: self.MAX_FACT_ROWS], len(rows) > self.MAX_FACT_ROWS

    def _products(
        self,
        context: dict[str, Any],
    ) -> dict[str, ProductRow]:
        scope = context["scope"]
        cutoff = context["cutoff"]
        with Session(self.engine) as session:
            rows = list(
                session.scalars(
                    select(ProductRow).where(
                        ProductRow.tenant_ref == scope["tenant_ref"],
                        ProductRow.entity_ref == scope["entity_ref"],
                        ProductRow.store_ref == scope["store_ref"],
                        ProductRow.scope_grant_authority_sha256
                        == scope["scope_grant_authority_sha256"],
                        ProductRow.scope_as_of <= cutoff,
                        ProductRow.created_at <= cutoff,
                    )
                ).all()
            )
            for row in rows:
                session.expunge(row)
        return {row.id: row for row in rows}

    @staticmethod
    def _context(
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("OMS as_of must include a timezone")
        if not principal.can_access_store(store_ref):
            raise PermissionError(
                "Authenticated identity is not authorized for store_ref"
            )
        cutoff = as_of.astimezone(UTC)
        authority = str(
            entity_scope.get("authority_sha256") or ""
        ).strip()
        ready = bool(
            entity_scope.get("status") == "ready"
            and entity_scope.get("entity_ref")
            and len(authority) == 64
            and all(
                character in "0123456789abcdef"
                for character in authority
            )
        )
        status = (
            "ready"
            if ready
            else "blocked"
            if entity_scope.get("status") == "blocked"
            else "no_data"
        )
        return {
            "status": status,
            "reason": (
                None
                if ready
                else str(
                    entity_scope.get("reason")
                    or "entity_scope_authority_missing"
                )
            ),
            "cutoff": cutoff,
            "scope": {
                "tenant_ref": principal.tenant_ref,
                "entity_ref": (
                    str(entity_scope["entity_ref"])
                    if ready
                    else None
                ),
                "store_ref": store_ref,
                "scope_grant_authority_sha256": (
                    authority if ready else None
                ),
            },
        }

    def _empty(
        self,
        *,
        context: dict[str, Any],
        page_size: int,
        cursor: str | None,
    ) -> dict[str, Any]:
        reason = str(context["reason"])
        payload = {
            "contract_id": self.CONTRACT_ID,
            "status": context["status"],
            "as_of": context["cutoff"].isoformat(),
            "scope": context["scope"],
            "query": {
                "page_size": page_size,
                "cursor": cursor,
                "next_cursor": None,
                "max_fact_rows": self.MAX_FACT_ROWS,
            },
            "counts": {
                "raw_order_facts": 0,
                "raw_return_facts": 0,
                "valid_timeline_events": 0,
                "total_current_orders": 0,
                "page_current_orders": 0,
                "blocked_current_orders": 0,
                "invalid_facts": 0,
                "legacy_orders_read": 0,
            },
            "orders": [],
            "invalid_fact_ids": [],
            "source_gaps": [reason],
            "blockers": [self._blocker(reason)],
            "agent_support": {
                "authority": "decision_support_only",
                "input_snapshot_sha256": None,
                "suggestions": [],
                "automatic_actions": [],
                "self_approval_allowed": False,
                "permit_issue_allowed": False,
            },
            "control_envelope": self._control(input_read=False),
        }
        payload["snapshot_sha256"] = self._hash(payload)
        return payload

    @staticmethod
    def _blocker(code: str) -> dict[str, Any]:
        owner = (
            "identity-governance"
            if "scope_authority" in code
            else "evidence-governance"
            if "evidence" in code or "hash" in code
            else "oms-operations"
        )
        return {
            "code": code,
            "severity": (
                "P0"
                if any(
                    token in code
                    for token in ("evidence", "hash", "mismatch")
                )
                else "P1"
            ),
            "owner": owner,
            "sla": "before any fulfillment, procurement or customer action",
            "next": (
                "Restore the exact scoped formal Fact/Evidence contract and "
                "rerun the read-only OMS projection."
            ),
            "next_workspace": "/formal-facts",
        }

    @staticmethod
    def _owner(state: str) -> str:
        return {
            "awaiting_packaging": "oms-procurement",
            "awaiting_handover": "fulfillment",
            "in_transit": "logistics",
            "delivered": "finance-reconciliation",
            "cancelled": "customer-service",
            "returned": "returns-finance",
        }.get(state, "oms-operations")

    @staticmethod
    def _sla(state: str) -> str:
        return {
            "awaiting_packaging": "4h",
            "awaiting_handover": "before ship-by deadline",
            "in_transit": "daily until delivery",
            "delivered": "before accrual close",
            "cancelled": "4h",
            "returned": "1 business day",
        }.get(state, "before external action")

    @staticmethod
    def _next(state: str) -> str:
        return {
            "awaiting_packaging": (
                "Review procurement, stock and packaging internally."
            ),
            "awaiting_handover": "Verify package and carrier handover readiness.",
            "in_transit": "Monitor authorized carrier status and delivery SLA.",
            "delivered": "Await accrual, settlement and cash reconciliation.",
            "cancelled": "Reconcile cancellation cause and avoid purchase.",
            "returned": "Reconcile return, refund, inventory and actual CM3.",
        }.get(
            state,
            "Resolve lifecycle semantics from official Evidence.",
        )

    @staticmethod
    def _workspace(state: str) -> str:
        return {
            "awaiting_packaging": "/operations/sourcing/procurement",
            "awaiting_handover": "/operations/logistics/fulfillment",
            "in_transit": "/operations/logistics/fulfillment",
            "delivered": "/operating-intelligence",
            "cancelled": "/operations/orders/customer-service",
            "returned": "/operating-intelligence",
        }.get(state, "/formal-facts")

    @staticmethod
    def _control(*, input_read: bool) -> dict[str, Any]:
        return {
            "read_only": True,
            "scoped_input_read": input_read,
            "legacy_rows_inferred": False,
            "client_recalculation_allowed": False,
            "operating_task_created": False,
            "supplier_order_created": False,
            "payment_created": False,
            "customer_message_sent": False,
            "approval_created": False,
            "permit_created": False,
            "external_write_allowed": False,
        }

    @staticmethod
    def _hash(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode()
        ).hexdigest()
