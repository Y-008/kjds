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
    is_non_negative_integer,
    order_timestamp,
)
from .ozon_contracts import (
    CONTRACT_VERSION as OZON_CONTRACT_VERSION,
)
from .ozon_contracts import (
    OzonRecordType,
    natural_key,
)
from .security import Principal
from .sql_repository import ProductRow

OPEN_DEMAND_STATES = frozenset(
    {
        "created",
        "paid",
        "awaiting_packaging",
    }
)
QUANTITY_FIELDS = (
    "available_quantity",
    "reserved_quantity",
    "in_transit_quantity",
    "damaged_quantity",
    "quarantine_quantity",
)


class ScopedInventoryFulfillmentWorkspace:
    """Project exact-scope inventory Facts and OMS demand without side effects."""

    CONTRACT_ID = "kjds-native-scoped-inventory-fulfillment-v1"
    MAX_FACT_ROWS = 10000

    def __init__(self, *, engine, evidence, oms) -> None:
        self.engine = engine
        self.evidence = evidence
        self.oms = oms

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
            raise ValueError(
                "Inventory page_size must be between 1 and 500"
            )
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
        valid_by_cell: dict[str, list[dict[str, Any]]] = defaultdict(list)
        invalid_by_cell: dict[str, list[dict[str, Any]]] = defaultdict(
            list
        )
        invalid_fact_ids: list[str] = []
        gaps: set[str] = set()

        for row in rows:
            snapshot, reason = self._snapshot(
                row=row,
                products=products,
                store_ref=store_ref,
            )
            if snapshot is not None:
                valid_by_cell[snapshot["cell_key"]].append(snapshot)
                continue
            invalid_fact_ids.append(row.id)
            gaps.add(reason or "inventory_fact_invalid")
            invalid = self._invalid_cell_link(row, reason)
            if invalid is not None:
                invalid_by_cell[invalid["cell_key"]].append(invalid)

        cell_keys = set(valid_by_cell) | set(invalid_by_cell)
        all_cells = [
            self._current_cell(
                cell_key,
                valid_by_cell.get(cell_key, []),
                invalid_by_cell.get(cell_key, []),
            )
            for cell_key in cell_keys
        ]
        all_cells.sort(key=self._cell_sort_key, reverse=True)
        total_cells = len(all_cells)
        reliable_cells = sum(
            cell["projection_status"] != "blocked"
            for cell in all_cells
        )
        if normalized_cursor is not None:
            cursor_key = self._decode_cursor(normalized_cursor)
            all_cells = [
                cell
                for cell in all_cells
                if self._cell_sort_key(cell) < cursor_key
            ]
        page = all_cells[:page_size]
        next_cursor = (
            self._encode_cursor(self._cell_sort_key(page[-1]))
            if len(all_cells) > page_size and page
            else None
        )
        if truncated:
            gaps.add("inventory_fact_scan_truncated")

        demand = self._order_demand(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=context["cutoff"],
        )
        gaps.update(demand["source_gaps"])
        summaries = self._sku_summaries(
            cells=[
                cell
                for cell in all_cells
                if cell["projection_status"] != "blocked"
            ],
            demand=demand,
        )
        status = (
            "no_data"
            if not rows
            else "blocked"
            if total_cells == 0 or reliable_cells == 0
            else "partial"
            if gaps
            else "ready"
        )
        blockers = [self._blocker(code) for code in sorted(gaps)]
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
                "raw_inventory_facts": len(rows),
                "total_current_cells": total_cells,
                "page_current_cells": len(page),
                "blocked_current_cells": sum(
                    cell["projection_status"] == "blocked"
                    for cell in page
                ),
                "invalid_facts": len(invalid_fact_ids),
                "sku_summaries": len(summaries),
                "open_demand_orders": demand["open_order_count"],
                "legacy_inventory_rows_read": 0,
                "marketplace_observations_inferred": 0,
            },
            "inventory_cells": page,
            "sku_summaries": summaries,
            "order_demand": demand,
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
                self._agent_suggestion(summary) for summary in summaries
            ],
            "automatic_actions": [],
            "self_approval_allowed": False,
            "permit_issue_allowed": False,
        }
        core["snapshot_sha256"] = self._hash(core)
        return core

    def _snapshot(
        self,
        *,
        row: FactRecordRow,
        products: dict[str, ProductRow],
        store_ref: str,
    ) -> tuple[dict[str, Any] | None, str | None]:
        payload = row.payload_json or {}
        if row.contract_version != OZON_CONTRACT_VERSION:
            return None, "inventory_fact_contract_version_mismatch"
        if self._hash(payload) != row.payload_hash:
            return None, "inventory_fact_payload_hash_mismatch"
        if not self._evidence_valid(row):
            return None, "inventory_fact_evidence_invalid"
        product = products.get(str(row.product_id or ""))
        if product is None:
            return None, "inventory_product_scope_or_binding_missing"
        sku = str(payload.get("sku") or "").strip()
        if not sku or sku != product.sku:
            return None, "inventory_fact_sku_mismatch"
        payload_store = str(payload.get("store_ref") or "").strip()
        if payload_store and payload_store != store_ref:
            return None, "inventory_fact_store_mismatch"
        external_id = str(payload.get("external_id") or "").strip()
        warehouse_ref = str(payload.get("warehouse_ref") or "").strip()
        mode = str(payload.get("fulfillment_mode") or "").strip()
        if not external_id:
            return None, "inventory_fact_external_id_missing"
        if not warehouse_ref:
            return None, "inventory_warehouse_ref_missing"
        if mode not in {"FBP", "realFBS"}:
            return None, "inventory_fulfillment_mode_invalid"
        if any(
            not is_non_negative_integer(payload.get(field, "0"))
            for field in QUANTITY_FIELDS
        ):
            return None, "inventory_quantity_invalid"
        expected_key = natural_key(OzonRecordType.INVENTORY, payload)
        if row.natural_key != expected_key:
            return None, "inventory_natural_key_mismatch"
        quantities = {
            field: int(Decimal(str(payload.get(field, "0"))))
            for field in QUANTITY_FIELDS
        }
        return (
            {
                "cell_key": expected_key,
                "external_id": external_id,
                "product_id": product.id,
                "sku": sku,
                "warehouse_ref": warehouse_ref,
                "cluster_ref": (
                    str(payload.get("cluster_ref") or "").strip() or None
                ),
                "fulfillment_mode": mode,
                "quantities": quantities,
                "effective_at": database_order_timestamp(
                    row.effective_at
                ).isoformat(),
                "recorded_at": database_order_timestamp(
                    row.recorded_at
                ).isoformat(),
                "fact_id": row.id,
                "evidence_id": row.evidence_id,
                "source_evidence_sha256": row.source_evidence_sha256,
                "validation_status": "ready",
            },
            None,
        )

    def _invalid_cell_link(
        self,
        row: FactRecordRow,
        reason: str | None,
    ) -> dict[str, Any] | None:
        payload = row.payload_json or {}
        if not isinstance(payload, dict):
            return None
        try:
            cell_key = natural_key(OzonRecordType.INVENTORY, payload)
        except KeyError:
            return None
        return {
            "cell_key": cell_key,
            "fact_id": row.id,
            "effective_at": database_order_timestamp(
                row.effective_at
            ).isoformat(),
            "recorded_at": database_order_timestamp(
                row.recorded_at
            ).isoformat(),
            "evidence_id": row.evidence_id,
            "validation_status": "blocked",
            "blocker_code": reason or "inventory_fact_invalid",
        }

    @classmethod
    def _current_cell(
        cls,
        cell_key: str,
        valid: list[dict[str, Any]],
        invalid: list[dict[str, Any]],
    ) -> dict[str, Any]:
        timeline = sorted(valid, key=cls._event_sort_key)
        blocked = sorted(invalid, key=cls._event_sort_key)
        last_valid = timeline[-1] if timeline else None
        last_blocked = blocked[-1] if blocked else None
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
            raise ValueError(
                "Inventory cell requires at least one candidate event"
            )
        return {
            "cell_key": cell_key,
            "projection_status": (
                "blocked" if latest_is_blocked else "ready"
            ),
            "current_snapshot": current,
            "last_valid_snapshot": last_valid,
            "timeline": timeline,
            "blocked_events": blocked,
            "fact_ids": [
                event["fact_id"] for event in [*timeline, *blocked]
            ],
            "evidence_ids": sorted(
                {
                    event["evidence_id"]
                    for event in [*timeline, *blocked]
                }
            ),
            "owner": (
                "evidence-governance"
                if latest_is_blocked
                else "inventory-fulfillment"
            ),
            "sla": (
                "before allocation, fulfillment or procurement"
                if latest_is_blocked
                else "before next fulfillment decision"
            ),
            "next": (
                "Repair and independently verify the latest inventory Fact; "
                "prior stock remains history and is not current."
                if latest_is_blocked
                else "Compare this official stock snapshot with current OMS "
                "demand before proposing any internal action."
            ),
            "next_workspace": (
                "/formal-facts"
                if latest_is_blocked
                else "/inventory"
            ),
        }

    def _order_demand(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        oms = self.oms.workspace(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
            page_size=500,
        )
        demand_by_sku: dict[str, int] = defaultdict(int)
        open_orders: list[dict[str, Any]] = []
        for order in oms.get("orders", []):
            current = order.get("current_event") or {}
            if (
                order.get("projection_status") == "blocked"
                or order.get("current_state") not in OPEN_DEMAND_STATES
                or not order.get("sku")
            ):
                continue
            quantity = int(current.get("quantity") or 0)
            demand_by_sku[str(order["sku"])] += quantity
            open_orders.append(
                {
                    "order_external_id": order["external_id"],
                    "sku": order["sku"],
                    "quantity": quantity,
                    "current_state": order["current_state"],
                    "fact_ids": order["fact_ids"],
                    "evidence_ids": order["evidence_ids"],
                }
            )
        gaps: list[str] = []
        if oms["status"] in {"blocked", "partial"}:
            gaps.append("oms_order_demand_not_fully_authoritative")
        if oms["status"] == "no_data":
            gaps.append("oms_order_demand_no_data")
        if oms["query"]["next_cursor"]:
            gaps.append("oms_order_demand_page_truncated")
        return {
            "status": (
                "ready"
                if oms["status"] == "ready"
                else "no_data"
                if oms["status"] == "no_data"
                else "blocked"
            ),
            "oms_snapshot_sha256": oms["snapshot_sha256"],
            "open_states": sorted(OPEN_DEMAND_STATES),
            "open_order_count": len(open_orders),
            "demand_by_sku": dict(sorted(demand_by_sku.items())),
            "orders": open_orders,
            "source_gaps": gaps,
            "legacy_orders_inferred": False,
        }

    @staticmethod
    def _sku_summaries(
        *,
        cells: list[dict[str, Any]],
        demand: dict[str, Any],
    ) -> list[dict[str, Any]]:
        available: dict[str, int] = defaultdict(int)
        reserved: dict[str, int] = defaultdict(int)
        modes: dict[str, set[str]] = defaultdict(set)
        warehouses: dict[str, set[str]] = defaultdict(set)
        fact_ids: dict[str, list[str]] = defaultdict(list)
        evidence_ids: dict[str, set[str]] = defaultdict(set)
        for cell in cells:
            snapshot = cell["current_snapshot"]
            sku = str(snapshot["sku"])
            available[sku] += snapshot["quantities"][
                "available_quantity"
            ]
            reserved[sku] += snapshot["quantities"][
                "reserved_quantity"
            ]
            modes[sku].add(snapshot["fulfillment_mode"])
            warehouses[sku].add(snapshot["warehouse_ref"])
            fact_ids[sku].append(snapshot["fact_id"])
            evidence_ids[sku].add(snapshot["evidence_id"])

        summaries = []
        for sku in sorted(available):
            demand_quantity = demand["demand_by_sku"].get(sku)
            demand_ready = demand["status"] == "ready"
            shortage = (
                max(int(demand_quantity or 0) - available[sku], 0)
                if demand_ready
                else None
            )
            summaries.append(
                {
                    "sku": sku,
                    "available_quantity": available[sku],
                    "reserved_quantity": reserved[sku],
                    "open_order_demand_quantity": (
                        int(demand_quantity or 0)
                        if demand_ready
                        else None
                    ),
                    "shortage_quantity": shortage,
                    "coverage_status": (
                        "blocked"
                        if not demand_ready
                        else "shortage"
                        if shortage
                        else "covered"
                    ),
                    "fulfillment_modes": sorted(modes[sku]),
                    "warehouse_refs": sorted(warehouses[sku]),
                    "fact_ids": sorted(fact_ids[sku]),
                    "evidence_ids": sorted(evidence_ids[sku]),
                    "owner": (
                        "inventory-fulfillment"
                        if demand_ready
                        else "oms-evidence"
                    ),
                    "sla": "before next fulfillment decision",
                    "next": (
                        "Review shortage internally; procurement and stock "
                        "changes remain separately governed."
                        if shortage
                        else "No shortage is proven at this as_of; keep "
                        "monitoring official stock and order Facts."
                        if demand_ready
                        else "Capture authoritative OMS demand before "
                        "claiming inventory coverage."
                    ),
                    "next_workspace": (
                        "/operations/sourcing/procurement"
                        if shortage
                        else "/oms"
                    ),
                }
            )
        return summaries

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
                FactRecordRow.fact_type
                == OzonRecordType.INVENTORY.value,
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
            raise ValueError("Inventory as_of must include a timezone")
        if not principal.can_access_store(store_ref):
            raise PermissionError(
                "Authenticated identity is not authorized for store_ref"
            )
        cutoff = as_of.astimezone(UTC)
        if cutoff > datetime.now(UTC):
            raise ValueError("Inventory as_of cannot be in the future")
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
                "raw_inventory_facts": 0,
                "total_current_cells": 0,
                "page_current_cells": 0,
                "blocked_current_cells": 0,
                "invalid_facts": 0,
                "sku_summaries": 0,
                "open_demand_orders": 0,
                "legacy_inventory_rows_read": 0,
                "marketplace_observations_inferred": 0,
            },
            "inventory_cells": [],
            "sku_summaries": [],
            "order_demand": {
                "status": "no_data",
                "oms_snapshot_sha256": None,
                "open_states": sorted(OPEN_DEMAND_STATES),
                "open_order_count": 0,
                "demand_by_sku": {},
                "orders": [],
                "source_gaps": [reason],
                "legacy_orders_inferred": False,
            },
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
            else "inventory-fulfillment"
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
            "sla": "before allocation, fulfillment or procurement",
            "next": (
                "Restore exact-scope official Inventory/OMS Facts and "
                "rerun this read-only projection."
            ),
            "next_workspace": (
                "/scope-authority"
                if "scope_authority" in code
                else "/formal-facts"
            ),
        }

    @staticmethod
    def _agent_suggestion(summary: dict[str, Any]) -> dict[str, Any]:
        return {
            "sku": summary["sku"],
            "suggestion_type": "internal_inventory_next_action",
            "coverage_status": summary["coverage_status"],
            "owner": summary["owner"],
            "sla": summary["sla"],
            "next": summary["next"],
            "next_workspace": summary["next_workspace"],
            "fact_ids": summary["fact_ids"],
            "evidence_ids": summary["evidence_ids"],
            "inventory_adjustment_allowed": False,
            "reservation_allowed": False,
            "supplier_order_allowed": False,
            "external_action_allowed": False,
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
    def _cell_sort_key(
        cell: dict[str, Any],
    ) -> tuple[datetime, str]:
        return (
            order_timestamp(
                cell["current_snapshot"]["effective_at"]
            ),
            str(cell["cell_key"]),
        )

    @staticmethod
    def _encode_cursor(key: tuple[datetime, str]) -> str:
        payload = json.dumps(
            {
                "effective_at": key[0].isoformat(),
                "cell_key": key[1],
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
            cell_key = str(decoded["cell_key"]).strip()
            effective_at = order_timestamp(decoded["effective_at"])
        except (
            KeyError,
            TypeError,
            ValueError,
            binascii.Error,
            json.JSONDecodeError,
        ) as exc:
            raise ValueError("Inventory cursor is invalid") from exc
        if not cell_key:
            raise ValueError("Inventory cursor is invalid")
        return effective_at, cell_key

    @staticmethod
    def _control(*, input_read: bool) -> dict[str, Any]:
        return {
            "read_only": True,
            "scoped_input_read": input_read,
            "legacy_rows_inferred": False,
            "marketplace_observations_inferred": False,
            "client_recalculation_allowed": False,
            "operating_task_created": False,
            "inventory_adjustment_created": False,
            "reservation_created": False,
            "fulfillment_command_created": False,
            "supplier_order_created": False,
            "payment_created": False,
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
