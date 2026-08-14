from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from .security import Principal
from .warehouse_fulfillment import WarehouseExecutionAuthorityService


class ScopedWarehouseFulfillmentWorkspace:
    """One read-only seam for exact-scope warehouse execution authority."""

    CONTRACT_ID = "kjds-native-exact-scope-warehouse-fulfillment-v1"
    ARTIFACT_CONTRACT_ID = "kjds-warehouse-fulfillment-agent-artifact-v1"
    OMS_CONTRACT_ID = "kjds-native-scoped-oms-v1"
    INVENTORY_CONTRACT_ID = (
        "kjds-native-scoped-inventory-fulfillment-v1"
    )
    PIM_CONTRACT_ID = "kjds-native-exact-scope-pim-workspace-v1"
    PROCUREMENT_CONTRACT_ID = (
        "kjds-native-exact-scope-procurement-receiving-workspace-v1"
    )
    DELIVERY_CONTRACT_ID = (
        "kjds-native-exact-scope-delivery-exception-workspace-v1"
    )
    EVENT_CONTRACT_ID = (
        WarehouseExecutionAuthorityService.SOURCE_CONTRACT_ID
    )
    WAREHOUSE_STATES = frozenset(
        {"paid", "awaiting_packaging", "awaiting_handover"}
    )
    FILTER_STATES = frozenset(
        {
            "unstarted",
            "reserved",
            "picking",
            "packing",
            "parcel_ready",
            "handoff_ready",
            "handed_over",
            "exception",
            "blocked",
        }
    )
    SCAN_ORDER = {
        "wave_created": 10,
        "wave_order_added": 20,
        "reservation_created": 30,
        "pick_scanned": 40,
        "pack_scanned": 50,
        "parcel_created": 60,
        "label_bound": 70,
        "label_purchased_readback": 70,
        "weight_scanned": 80,
        "outbound_confirmed_readback": 90,
        "carrier_handoff_readback": 100,
    }

    def __init__(
        self,
        *,
        oms,
        inventory,
        pim,
        procurement,
        delivery,
        warehouse_events,
    ) -> None:
        self.oms = oms
        self.inventory = inventory
        self.pim = pim
        self.procurement = procurement
        self.delivery = delivery
        self.warehouse_events = warehouse_events

    def project(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        warehouse_ref: str,
        as_of: datetime,
        order_external_id: str | None = None,
        query: str | None = None,
        state: str | None = None,
        page_size: int = 25,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        if not 1 <= page_size <= 100:
            raise ValueError(
                "warehouse page_size must be between 1 and 100"
            )
        if state not in {None, *self.FILTER_STATES}:
            raise ValueError("warehouse state filter is invalid")
        cutoff = self._cutoff(as_of)
        scope = self._scope(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            warehouse_ref=warehouse_ref,
        )
        filters = {
            "order_external_id": (
                str(order_external_id or "").strip() or None
            ),
            "query": str(query or "").strip() or None,
            "state": state,
        }
        if scope["entity_ref"] is None:
            return self._payload(
                scope=scope,
                cutoff=cutoff,
                status="no_data",
                items=[],
                total=0,
                reads=[],
                source_gaps=["warehouse_entity_scope_missing"],
                page_size=page_size,
                next_cursor=None,
                filters=filters,
            )

        oms = self.oms.workspace(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=cutoff,
            page_size=500,
        )
        issues = self._projection_issues(
            name="oms",
            projection=oms,
            contract_id=self.OMS_CONTRACT_ID,
            scope=scope,
            cutoff=cutoff,
        )
        if issues:
            return self._payload(
                scope=scope,
                cutoff=cutoff,
                status="blocked",
                items=[],
                total=0,
                reads=["oms"],
                source_gaps=issues,
                page_size=page_size,
                next_cursor=None,
                filters=filters,
            )
        orders = [
            order
            for order in oms.get("orders", [])
            if order.get("current_state") in self.WAREHOUSE_STATES
        ]
        if filters["order_external_id"]:
            orders = [
                order
                for order in orders
                if order.get("external_id")
                == filters["order_external_id"]
            ]
        if not orders:
            return self._payload(
                scope=scope,
                cutoff=cutoff,
                status="no_data",
                items=[],
                total=0,
                reads=["oms"],
                source_gaps=["formal_order_missing"],
                page_size=page_size,
                next_cursor=None,
                filters=filters,
                snapshots={
                    "oms_snapshot_sha256": oms.get("snapshot_sha256")
                },
            )

        upstream = {
            "inventory": self.inventory.workspace(
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store_ref,
                as_of=cutoff,
                page_size=500,
            ),
            "pim": self.pim.project(
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store_ref,
                as_of=cutoff,
                page_size=200,
            ),
            "procurement": self.procurement.project(
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store_ref,
                as_of=cutoff.isoformat(),
                page_size=100,
            ),
            "delivery": self.delivery.project(
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store_ref,
                as_of=cutoff,
                page_size=100,
            ),
            "warehouse_events": self.warehouse_events.read_scoped_sources(
                tenant_ref=scope["tenant_ref"],
                entity_ref=str(scope["entity_ref"]),
                store_ref=scope["store_ref"],
                warehouse_ref=scope["warehouse_ref"],
                scope_grant_authority_sha256=str(
                    scope["scope_grant_authority_sha256"]
                ),
                as_of=cutoff.isoformat(),
                order_external_id=filters["order_external_id"],
            ),
        }
        contracts = {
            "inventory": self.INVENTORY_CONTRACT_ID,
            "pim": self.PIM_CONTRACT_ID,
            "procurement": self.PROCUREMENT_CONTRACT_ID,
            "delivery": self.DELIVERY_CONTRACT_ID,
            "warehouse_events": self.EVENT_CONTRACT_ID,
        }
        issues = [
            issue
            for name, projection in upstream.items()
            for issue in self._projection_issues(
                name=name,
                projection=projection,
                contract_id=contracts[name],
                scope=scope,
                cutoff=cutoff,
            )
        ]
        reads = ["oms", *sorted(upstream)]
        snapshots = {
            "oms_snapshot_sha256": oms.get("snapshot_sha256"),
            **{
                f"{name}_snapshot_sha256": projection.get(
                    "snapshot_sha256"
                )
                for name, projection in sorted(upstream.items())
            },
        }
        pim_groups = list(upstream["pim"].get("product_groups", []))
        inventory_summaries = list(
            upstream["inventory"].get("sku_summaries", [])
        )
        events = list(upstream["warehouse_events"].get("events", []))
        if not pim_groups:
            issues.append("warehouse_canonical_product_missing")
        if not inventory_summaries:
            issues.append("warehouse_formal_inventory_missing")
        if upstream["warehouse_events"].get("truncated") is True:
            issues.append("warehouse_execution_scan_truncated")

        order_index = {
            str(order.get("external_id") or ""): order for order in orders
        }
        product_index = {
            (
                str(group.get("product", {}).get("id") or ""),
                str(group.get("product", {}).get("sku") or ""),
            ): group
            for group in pim_groups
        }
        inventory_index = {
            str(summary.get("sku") or ""): summary
            for summary in inventory_summaries
        }
        event_issues = self._event_authority_issues(
            events=events,
            order_index=order_index,
            product_index=product_index,
            inventory_index=inventory_index,
            delivery=upstream["delivery"],
            principal=principal,
            entity_scope=entity_scope,
            scope=scope,
            cutoff=cutoff,
        )
        issues.extend(event_issues)
        if issues and events:
            return self._payload(
                scope=scope,
                cutoff=cutoff,
                status="blocked",
                items=[],
                total=0,
                reads=reads,
                source_gaps=sorted(set(issues)),
                page_size=page_size,
                next_cursor=None,
                filters=filters,
                snapshots=snapshots,
            )
        if not events:
            return self._payload(
                scope=scope,
                cutoff=cutoff,
                status="no_data",
                items=[],
                total=0,
                reads=reads,
                source_gaps=sorted(
                    {
                        *issues,
                        "warehouse_execution_event_missing",
                    }
                ),
                page_size=page_size,
                next_cursor=None,
                filters=filters,
                snapshots=snapshots,
            )

        events_by_order: dict[str, list[dict[str, Any]]] = defaultdict(
            list
        )
        for event in events:
            events_by_order[str(event["order_external_id"])].append(event)
        items = [
            self._item(
                order=order,
                events=events_by_order.get(str(order["external_id"]), []),
                inventory=inventory_index.get(str(order.get("sku") or "")),
                procurement=upstream["procurement"],
                delivery=upstream["delivery"],
            )
            for order in orders
            if events_by_order.get(str(order["external_id"]))
        ]
        if filters["query"]:
            needle = filters["query"].casefold()
            items = [
                item
                for item in items
                if needle
                in " ".join(
                    [
                        item["order_external_id"],
                        item["product"]["sku"],
                        *item["wave_refs"],
                        *item["parcel_refs"],
                        *item["label_refs"],
                    ]
                ).casefold()
            ]
        if state:
            items = [item for item in items if item["state"] == state]
        items.sort(key=self._sort_key, reverse=True)
        total = len(items)
        if cursor:
            cursor_key = self._decode_cursor(cursor)
            items = [
                item for item in items if self._sort_key(item) < cursor_key
            ]
        page = items[:page_size]
        next_cursor = (
            self._encode_cursor(self._sort_key(page[-1]))
            if len(items) > page_size and page
            else None
        )
        gaps = {
            gap
            for projection in upstream.values()
            for gap in projection.get("source_gaps", [])
        }
        status = (
            "no_data"
            if not total
            else "partial"
            if gaps
            or any(item["state"] != "handed_over" for item in page)
            else "ready"
        )
        return self._payload(
            scope=scope,
            cutoff=cutoff,
            status=status,
            items=page,
            total=total,
            reads=reads,
            source_gaps=sorted(gaps),
            page_size=page_size,
            next_cursor=next_cursor,
            filters=filters,
            snapshots=snapshots,
        )

    def _event_authority_issues(
        self,
        *,
        events: list[dict[str, Any]],
        order_index: dict[str, dict[str, Any]],
        product_index: dict[tuple[str, str], dict[str, Any]],
        inventory_index: dict[str, dict[str, Any]],
        delivery: dict[str, Any],
        principal: Principal,
        entity_scope: dict[str, Any],
        scope: dict[str, Any],
        cutoff: datetime,
    ) -> list[str]:
        issues: set[str] = set()
        by_aggregate: dict[str, list[dict[str, Any]]] = defaultdict(list)
        reservations: Counter[tuple[str, str, str]] = Counter()
        picked: Counter[tuple[str, str]] = Counter()
        packed: Counter[tuple[str, str]] = Counter()
        bins: dict[str, str | None] = {}
        lots: dict[str, str | None] = {}
        labels: dict[str, tuple[str, str | None]] = {}
        parcels: dict[str, str] = {}
        scans: set[tuple[Any, ...]] = set()
        command_ids: set[str] = set()
        receipt_ids: set[str] = set()
        last_stage: dict[str, int] = defaultdict(int)
        delivery_orders = {
            str(item.get("order_external_id") or "")
            for item in delivery.get("shipments", [])
            if item.get("shipment_id")
        }
        for event in events:
            order_id = str(event.get("order_external_id") or "")
            order = order_index.get(order_id)
            if order is None:
                issues.add("warehouse_event_order_scope_conflict")
                continue
            key = (
                str(event.get("product_id") or ""),
                str(event.get("sku") or ""),
            )
            if key not in product_index:
                issues.add("warehouse_event_product_sku_conflict")
            if key != (
                str(order.get("product_id") or ""),
                str(order.get("sku") or ""),
            ):
                issues.add("warehouse_event_order_product_conflict")
            try:
                validation = self.warehouse_events.validate_event(
                    event=event,
                    principal=principal,
                    entity_scope=entity_scope,
                    scope=scope,
                    as_of=cutoff,
                )
            except (KeyError, PermissionError, RuntimeError, ValueError):
                validation = ["warehouse_event_evidence_invalid"]
            issues.update(validation)
            by_aggregate[str(event.get("aggregate_ref") or "")].append(
                event
            )
            event_type = str(event.get("event_type") or "")
            stage = self.SCAN_ORDER.get(event_type)
            if stage is not None:
                if stage < last_stage[order_id]:
                    issues.add("warehouse_scan_transition_out_of_order")
                last_stage[order_id] = max(last_stage[order_id], stage)
            signature = (
                event_type,
                order_id,
                event.get("bin_ref"),
                event.get("parcel_ref"),
                event.get("quantity"),
                event.get("effective_at"),
            )
            if event_type.endswith("_scanned") and signature in scans:
                issues.add("warehouse_scan_duplicate")
            scans.add(signature)
            quantity = int(event.get("quantity") or 0)
            sku = str(event.get("sku") or "")
            lot = str(event.get("lot_ref") or "")
            bin_ref = str(event.get("bin_ref") or "")
            location_ref = str(event.get("location_ref") or "") or None
            if bin_ref:
                previous = bins.setdefault(bin_ref, location_ref)
                if previous != location_ref:
                    issues.add("warehouse_location_bin_drift")
            if lot:
                previous = lots.setdefault(lot, bin_ref or None)
                if previous != (bin_ref or None):
                    issues.add("warehouse_lot_bin_drift")
            reservation_key = (order_id, sku, lot)
            quantity_key = (order_id, sku)
            if event_type == "reservation_created":
                reservations[reservation_key] += quantity
            elif event_type == "reservation_released":
                reservations[reservation_key] -= quantity
                if reservations[reservation_key] < 0:
                    issues.add("warehouse_reservation_negative")
            elif event_type == "pick_scanned":
                picked[quantity_key] += quantity
            elif event_type == "pack_scanned":
                packed[quantity_key] += quantity
                if packed[quantity_key] > picked[quantity_key]:
                    issues.add("warehouse_pick_pack_quantity_drift")
            if event_type == "weight_scanned" and (
                self._decimal(event.get("weight_kg")) is None
                or event.get("weight_source")
                not in WarehouseExecutionAuthorityService.WEIGHT_SOURCES
            ):
                issues.add("warehouse_weight_authority_unknown")
            parcel_ref = str(event.get("parcel_ref") or "")
            if parcel_ref:
                prior_order = parcels.setdefault(parcel_ref, order_id)
                if prior_order != order_id:
                    issues.add("warehouse_parcel_order_conflict")
            label_ref = str(event.get("label_ref") or "")
            if label_ref:
                binding = (order_id, parcel_ref or None)
                if labels.setdefault(label_ref, binding) != binding:
                    issues.add("warehouse_label_order_conflict")
            command_id = str(event.get("command_id") or "")
            receipt_id = str(event.get("receipt_id") or "")
            if command_id:
                if command_id in command_ids:
                    issues.add("warehouse_one_time_permit_reused")
                command_ids.add(command_id)
            if receipt_id:
                if receipt_id in receipt_ids:
                    issues.add("warehouse_readback_replay_conflict")
                receipt_ids.add(receipt_id)
            if (
                event_type == "carrier_handoff_readback"
                and order_id not in delivery_orders
            ):
                issues.add("warehouse_handoff_delivery_readback_missing")

        for aggregate_events in by_aggregate.values():
            aggregate_events.sort(key=lambda item: int(item["sequence"]))
            if [
                int(item["sequence"]) for item in aggregate_events
            ] != list(range(1, len(aggregate_events) + 1)):
                issues.add("warehouse_aggregate_sequence_drift")
            timestamps = [
                self._timestamp(item.get("effective_at"))
                for item in aggregate_events
            ]
            if any(
                right < left
                for left, right in zip(
                    timestamps,
                    timestamps[1:],
                    strict=False,
                )
            ):
                issues.add("warehouse_event_time_moved_backwards")

        order_quantities = {
            order_id: int(
                (order.get("current_event") or {}).get("quantity") or 0
            )
            for order_id, order in order_index.items()
        }
        active_by_order_sku: Counter[tuple[str, str]] = Counter()
        for (order_id, sku, _lot), quantity in reservations.items():
            active_by_order_sku[(order_id, sku)] += quantity
        for (order_id, sku), quantity in active_by_order_sku.items():
            if quantity > order_quantities.get(order_id, 0):
                issues.add("warehouse_reservation_exceeds_order")
            inventory = inventory_index.get(sku) or {}
            capacity = int(inventory.get("available_quantity") or 0) + int(
                inventory.get("reserved_quantity") or 0
            )
            if quantity > capacity:
                issues.add("warehouse_reservation_exceeds_inventory")
        for quantity_key, quantity in picked.items():
            if quantity > active_by_order_sku[quantity_key]:
                issues.add("warehouse_pick_exceeds_reservation")
            if quantity > order_quantities.get(quantity_key[0], 0):
                issues.add("warehouse_pick_exceeds_order")
        for quantity_key, quantity in packed.items():
            if quantity > order_quantities.get(quantity_key[0], 0):
                issues.add("warehouse_pack_exceeds_order")
        return sorted(issues)

    def _item(
        self,
        *,
        order: dict[str, Any],
        events: list[dict[str, Any]],
        inventory: dict[str, Any] | None,
        procurement: dict[str, Any],
        delivery: dict[str, Any],
    ) -> dict[str, Any]:
        events.sort(
            key=lambda item: (
                self._timestamp(item["effective_at"]),
                str(item["id"]),
            )
        )
        event_types = {str(item["event_type"]) for item in events}
        if "exception_recorded" in event_types:
            state = "exception"
        elif "carrier_handoff_readback" in event_types:
            state = "handed_over"
        elif {
            "weight_scanned",
            "outbound_confirmed_readback",
        }.issubset(event_types):
            state = "handoff_ready"
        elif "parcel_created" in event_types:
            state = "parcel_ready"
        elif "pack_scanned" in event_types:
            state = "packing"
        elif "pick_scanned" in event_types:
            state = "picking"
        elif "reservation_created" in event_types:
            state = "reserved"
        else:
            state = "unstarted"
        order_id = str(order["external_id"])
        sku = str(order.get("sku") or "")
        procurement_receipts = [
            item.get("receipt")
            for item in procurement.get("items", [])
            if str((item.get("product") or {}).get("sku") or "") == sku
            and item.get("receipt")
        ]
        delivery_rows = [
            item
            for item in delivery.get("shipments", [])
            if item.get("order_external_id") == order_id
        ]
        latest = events[-1]
        return {
            "order_external_id": order_id,
            "warehouse_ref": (
                str(delivery_rows[0].get("warehouse_ref") or "")
                if delivery_rows
                else None
            ),
            "product": {
                "product_id": order.get("product_id"),
                "sku": sku,
            },
            "state": state,
            "latest_effective_at": latest["effective_at"],
            "location_refs": self._values(events, "location_ref"),
            "bin_refs": self._values(events, "bin_ref"),
            "lot_refs": self._values(events, "lot_ref"),
            "wave_refs": self._values(events, "wave_ref"),
            "parcel_refs": self._values(events, "parcel_ref"),
            "label_refs": self._values(events, "label_ref"),
            "reservation_quantity": sum(
                int(item.get("quantity") or 0)
                * (
                    -1
                    if item["event_type"] == "reservation_released"
                    else 1
                )
                for item in events
                if item["event_type"]
                in {"reservation_created", "reservation_released"}
            ),
            "picked_quantity": sum(
                int(item.get("quantity") or 0)
                for item in events
                if item["event_type"] == "pick_scanned"
            ),
            "packed_quantity": sum(
                int(item.get("quantity") or 0)
                for item in events
                if item["event_type"] == "pack_scanned"
            ),
            "measured_weight_kg": next(
                (
                    item.get("weight_kg")
                    for item in reversed(events)
                    if item["event_type"] == "weight_scanned"
                ),
                None,
            ),
            "timeline": events,
            "inventory_authority": inventory,
            "procurement_receipts": procurement_receipts,
            "delivery_authority": delivery_rows,
            "owner": (
                "warehouse-exception-owner"
                if state == "exception"
                else "warehouse-operations"
            ),
            "sla": "before the next physical warehouse transition",
            "next": self._next(state),
            "next_workspace": (
                "/delivery-exceptions"
                if state in {"handed_over", "exception"}
                else "/warehouse-fulfillment"
            ),
        }

    @classmethod
    def _projection_issues(
        cls,
        *,
        name: str,
        projection: dict[str, Any],
        contract_id: str,
        scope: dict[str, Any],
        cutoff: datetime,
    ) -> list[str]:
        issues = []
        if projection.get("contract_id") != contract_id:
            issues.append(f"warehouse_{name}_contract_drift")
        actual_scope = projection.get("scope") or {}
        keys = ["tenant_ref", "entity_ref", "store_ref"]
        if name == "warehouse_events":
            keys.extend(
                ["warehouse_ref", "scope_grant_authority_sha256"]
            )
        if any(
            actual_scope.get(key) != scope.get(key) for key in keys
        ):
            issues.append(f"warehouse_{name}_scope_drift")
        if projection.get("as_of") != cutoff.isoformat():
            issues.append(f"warehouse_{name}_as_of_drift")
        claimed = str(projection.get("snapshot_sha256") or "")
        expected = cls._hash(
            {
                key: value
                for key, value in projection.items()
                if key != "snapshot_sha256"
            }
        )
        if claimed != expected:
            issues.append(f"warehouse_{name}_snapshot_drift")
        if projection.get("status") == "blocked":
            issues.append(f"warehouse_{name}_blocked")
        return issues

    def _payload(
        self,
        *,
        scope: dict[str, Any],
        cutoff: datetime,
        status: str,
        items: list[dict[str, Any]],
        total: int,
        reads: list[str],
        source_gaps: list[str],
        page_size: int,
        next_cursor: str | None,
        filters: dict[str, Any],
        snapshots: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        counts = {
            "total": total,
            **{
                state: sum(item["state"] == state for item in items)
                for state in sorted(self.FILTER_STATES)
            },
        }
        artifact = {
            "contract_id": self.ARTIFACT_CONTRACT_ID,
            "scope": scope,
            "as_of": cutoff.isoformat(),
            "authority": (
                "wave_suggestion_exception_classification_"
                "and_internal_task_only"
            ),
            "items": [
                {
                    "order_external_id": item["order_external_id"],
                    "state": item["state"],
                    "next": item["next"],
                }
                for item in items
            ],
        }
        payload = {
            "contract_id": self.CONTRACT_ID,
            "status": status,
            "as_of": cutoff.isoformat(),
            "scope": scope,
            "filters": filters,
            "counts": counts,
            "pagination": {
                "page_size": page_size,
                "next_cursor": next_cursor,
            },
            "fulfillment_items": items,
            "source_gaps": source_gaps,
            "upstream": snapshots or {},
            "agent_artifact": {
                **artifact,
                "artifact_sha256": self._hash(artifact),
                "warehouse_wave_create_allowed": False,
                "scan_event_create_allowed": False,
                "inventory_adjustment_allowed": False,
                "outbound_confirmation_allowed": False,
                "label_purchase_allowed": False,
                "carrier_handoff_allowed": False,
                "inventory_mutation_allowed": False,
                "order_mutation_allowed": False,
                "shipment_mutation_allowed": False,
                "self_approval_allowed": False,
                "permit_issue_allowed": False,
                "carrier_contact_allowed": False,
                "customer_contact_allowed": False,
                "fictional_authority_allowed": False,
                "external_write_allowed": False,
            },
            "governed_action_contract": {
                "actions": [
                    "inventory_adjustment",
                    "outbound_confirmation",
                    "label_purchase",
                    "carrier_handoff",
                ],
                "requires": [
                    "independent_approval",
                    "one_time_permit",
                    "immutable_readback",
                    "kill_switch_release",
                    "compensation_plan",
                ],
                "projection_grants_permission": False,
            },
            "control_envelope": {
                "read_only_projection": True,
                "upstream_reads": reads,
                "client_recalculation_allowed": False,
                "append_only_warehouse_authority": True,
                "legacy_warehouse_row_as_fact": False,
                "order_truth_duplicated": False,
                "inventory_truth_duplicated": False,
                "delivery_truth_duplicated": False,
                "private_erp_interface_allowed": False,
                "cookie_or_internal_token_allowed": False,
                "external_write_allowed": False,
            },
        }
        payload["snapshot_sha256"] = self._hash(payload)
        return payload

    @staticmethod
    def _scope(
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        warehouse_ref: str,
    ) -> dict[str, Any]:
        if not principal.can_access_store(store_ref):
            raise PermissionError("warehouse store scope is invalid")
        tenant_ref = str(
            entity_scope.get("tenant_ref") or principal.tenant_ref
        ).strip()
        if tenant_ref != principal.tenant_ref:
            raise PermissionError("warehouse tenant scope is invalid")
        granted_store = str(
            entity_scope.get("store_ref") or store_ref
        ).strip()
        if granted_store != store_ref:
            raise PermissionError("warehouse store scope is invalid")
        warehouse = str(warehouse_ref or "").strip()
        if not warehouse:
            raise ValueError("warehouse_ref is required")
        ready = (
            entity_scope.get("status") == "ready"
            and bool(str(entity_scope.get("entity_ref") or "").strip())
            and len(
                str(entity_scope.get("authority_sha256") or "").strip()
            )
            == 64
        )
        return {
            "tenant_ref": tenant_ref,
            "entity_ref": (
                str(entity_scope.get("entity_ref")).strip()
                if ready
                else None
            ),
            "store_ref": store_ref,
            "warehouse_ref": warehouse,
            "scope_grant_authority_sha256": (
                str(entity_scope.get("authority_sha256")).strip().lower()
                if ready
                else None
            ),
        }

    @staticmethod
    def _cutoff(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("warehouse as_of must include timezone")
        value = value.astimezone(UTC)
        if value > datetime.now(UTC):
            raise ValueError("warehouse as_of cannot be in the future")
        return value

    @staticmethod
    def _values(
        events: list[dict[str, Any]],
        field: str,
    ) -> list[str]:
        return sorted(
            {
                str(item[field])
                for item in events
                if item.get(field)
            }
        )

    @staticmethod
    def _next(state: str) -> str:
        return {
            "unstarted": "Suggest an internal wave; do not create it.",
            "reserved": "Review reservation and suggest an internal pick task.",
            "picking": "Resolve scan exceptions before suggesting packing.",
            "packing": "Verify quantity conservation before parcel readiness.",
            "parcel_ready": "Verify authorized weight and governed label state.",
            "handoff_ready": (
                "Await independently governed carrier handoff Readback."
            ),
            "handed_over": "Monitor BAS-156 delivery and exception authority.",
            "exception": "Classify and assign an internal exception task.",
            "blocked": "Repair exact-scope authority before physical action.",
        }[state]

    @staticmethod
    def _sort_key(item: dict[str, Any]) -> tuple[datetime, str]:
        return (
            ScopedWarehouseFulfillmentWorkspace._timestamp(
                item["latest_effective_at"]
            ),
            str(item["order_external_id"]),
        )

    @staticmethod
    def _encode_cursor(value: tuple[datetime, str]) -> str:
        return base64.urlsafe_b64encode(
            json.dumps(
                [value[0].isoformat(), value[1]],
                separators=(",", ":"),
            ).encode()
        ).decode()

    @staticmethod
    def _decode_cursor(value: str) -> tuple[datetime, str]:
        try:
            decoded = json.loads(base64.urlsafe_b64decode(value.encode()))
            if (
                not isinstance(decoded, list)
                or len(decoded) != 2
                or not all(isinstance(item, str) for item in decoded)
            ):
                raise ValueError
            return (
                ScopedWarehouseFulfillmentWorkspace._timestamp(decoded[0]),
                decoded[1],
            )
        except (
            ValueError,
            binascii.Error,
            json.JSONDecodeError,
        ) as exc:
            raise ValueError("warehouse cursor is invalid") from exc

    @staticmethod
    def _timestamp(value: Any) -> datetime:
        parsed = datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("warehouse event time must include timezone")
        return parsed.astimezone(UTC)

    @staticmethod
    def _decimal(value: Any) -> Decimal | None:
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
        return parsed if parsed.is_finite() and parsed > 0 else None

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
