from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from .delivery_readback import (
    FORMAL_DELIVERY_READBACK_CONTRACT_ID,
    DisabledDeliveryReadbackSource,
)
from .security import Principal


class ScopedDeliveryExceptionWorkspace:
    """Project exact-scope delivery truth and exception readiness."""

    CONTRACT_ID = "kjds-native-exact-scope-delivery-exception-v1"
    ARTIFACT_CONTRACT_ID = "kjds-delivery-exception-agent-artifact-v1"
    OMS_CONTRACT_ID = "kjds-native-scoped-oms-v1"
    UPSTREAM_CONTRACTS = {
        "inventory": "kjds-native-scoped-inventory-fulfillment-v1",
        "procurement": (
            "kjds-native-exact-scope-procurement-receiving-workspace-v1"
        ),
        "returns": "kjds-native-exact-scope-returns-aftersales-v1",
        "customer_service": (
            "kjds-native-exact-scope-customer-service-v1"
        ),
        "profit": "kjds-native-exact-scope-actual-profit-ledger-v1",
        "delivery_readbacks": (
            FORMAL_DELIVERY_READBACK_CONTRACT_ID
        ),
    }
    DELIVERY_STATES = frozenset(
        {
            "awaiting_packaging",
            "awaiting_handover",
            "in_transit",
            "delivered",
            "returned",
        }
    )
    FILTER_STATES = frozenset(
        {
            "pick_pack",
            "handover",
            "transit",
            "delivery",
            "exception",
            "return",
            "blocked",
        }
    )

    def __init__(
        self,
        *,
        oms,
        inventory,
        procurement,
        returns,
        customer_service,
        profit,
        delivery_readbacks=None,
    ) -> None:
        self.oms = oms
        self.inventory = inventory
        self.procurement = procurement
        self.returns = returns
        self.customer_service = customer_service
        self.profit = profit
        self.delivery_readbacks = (
            delivery_readbacks or DisabledDeliveryReadbackSource()
        )

    def project(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        query: str | None = None,
        state: str | None = None,
        page_size: int = 25,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        if state not in {None, *self.FILTER_STATES}:
            raise ValueError("delivery state filter is invalid")
        if not 1 <= page_size <= 100:
            raise ValueError("delivery page_size must be between 1 and 100")
        cutoff = self._cutoff(as_of)
        scope = self._scope(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
        )
        filters = {
            "query": str(query or "").strip() or None,
            "state": state,
        }
        if scope["entity_ref"] is None:
            return self._payload(
                scope=scope,
                cutoff=cutoff,
                status="no_data",
                filters=filters,
                shipments=[],
                page_size=page_size,
                next_cursor=None,
                source_gaps=["delivery_entity_scope_missing"],
                reads=[],
            )

        oms = self.oms.workspace(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=cutoff,
            page_size=500,
        )
        oms_issues = self._projection_issues(
            name="oms",
            projection=oms,
            contract_id=self.OMS_CONTRACT_ID,
            scope=scope,
            cutoff=cutoff,
        )
        if oms_issues:
            return self._payload(
                scope=scope,
                cutoff=cutoff,
                status="blocked",
                filters=filters,
                shipments=[],
                page_size=page_size,
                next_cursor=None,
                source_gaps=oms_issues,
                reads=["oms"],
                snapshots={"oms_snapshot_sha256": oms.get("snapshot_sha256")},
            )
        orders = list(oms.get("orders", []))
        if not orders:
            return self._payload(
                scope=scope,
                cutoff=cutoff,
                status="no_data",
                filters=filters,
                shipments=[],
                page_size=page_size,
                next_cursor=None,
                source_gaps=["formal_order_missing"],
                reads=["oms"],
                snapshots={"oms_snapshot_sha256": oms.get("snapshot_sha256")},
            )

        upstream = {
            "inventory": self.inventory.workspace(
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store_ref,
                as_of=cutoff,
                page_size=500,
            ),
            "procurement": self.procurement.project(
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store_ref,
                as_of=cutoff.isoformat(),
                page_size=100,
            ),
            "returns": self.returns.project(
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store_ref,
                as_of=cutoff.isoformat(),
                page_size=100,
            ),
            "customer_service": self.customer_service.project(
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store_ref,
                as_of=cutoff.isoformat(),
                page_size=100,
            ),
            "profit": self.profit.snapshot(
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store_ref,
                as_of=cutoff.isoformat(),
                grain="order",
                page_size=500,
            ),
            "delivery_readbacks": self.delivery_readbacks.project(
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store_ref,
                as_of=cutoff,
            ),
        }
        issues = [
            issue
            for name, projection in upstream.items()
            for issue in self._projection_issues(
                name=name,
                projection=projection,
                contract_id=self.UPSTREAM_CONTRACTS[name],
                scope=scope,
                cutoff=cutoff,
            )
        ]
        snapshots = {
            "oms_snapshot_sha256": oms.get("snapshot_sha256"),
            **{
                f"{name}_snapshot_sha256": value.get("snapshot_sha256")
                for name, value in sorted(upstream.items())
            },
        }
        reads = ["oms", *sorted(upstream)]
        readback_issues, readback_index = self._readback_index(
            readbacks=upstream["delivery_readbacks"].get("readbacks", []),
            orders=orders,
            cutoff=cutoff,
        )
        issues.extend(readback_issues)
        if issues:
            return self._payload(
                scope=scope,
                cutoff=cutoff,
                status="blocked",
                filters=filters,
                shipments=[],
                page_size=page_size,
                next_cursor=None,
                source_gaps=sorted(set(issues)),
                reads=reads,
                snapshots=snapshots,
            )

        shipments = [
            self._shipment(
                order=order,
                readback=readback_index.get(
                    str(order.get("external_id") or "")
                ),
                upstream=upstream,
                cutoff=cutoff,
            )
            for order in orders
            if self._is_delivery_order(order)
        ]
        if filters["query"]:
            needle = filters["query"].casefold()
            shipments = [
                item
                for item in shipments
                if needle
                in " ".join(
                    [
                        str(item["shipment_id"] or ""),
                        item["delivery_case_id"],
                        item["order_external_id"],
                        item["product"]["sku"],
                    ]
                ).casefold()
            ]
        if state:
            shipments = [item for item in shipments if item["state"] == state]
        shipments.sort(key=self._sort_key, reverse=True)
        total = len(shipments)
        cursor_key = self._decode_cursor(cursor) if cursor else None
        if cursor_key:
            shipments = [
                item for item in shipments if self._sort_key(item) < cursor_key
            ]
        page = shipments[:page_size]
        next_cursor = (
            self._encode_cursor(self._sort_key(page[-1]))
            if len(shipments) > page_size and page
            else None
        )
        gaps = {
            gap
            for projection in upstream.values()
            for gap in projection.get("source_gaps", [])
        }
        gaps.update(
            gap
            for item in shipments
            for gap in item["exception_readiness"]["missing_authorities"]
        )
        if orders and not total:
            gaps.add("formal_delivery_event_missing")
        status = (
            "no_data"
            if not total
            else "blocked"
            if all(item["projection_status"] == "blocked" for item in page)
            else "partial"
            if gaps
            or any(item["projection_status"] != "ready" for item in page)
            else "ready"
        )
        return self._payload(
            scope=scope,
            cutoff=cutoff,
            status=status,
            filters=filters,
            shipments=page,
            total=total,
            page_size=page_size,
            next_cursor=next_cursor,
            source_gaps=sorted(gaps),
            reads=reads,
            snapshots=snapshots,
        )

    def _shipment(
        self,
        *,
        order: dict[str, Any],
        readback: dict[str, Any] | None,
        upstream: dict[str, dict[str, Any]],
        cutoff: datetime,
    ) -> dict[str, Any]:
        order_id = str(order.get("external_id") or "")
        product_id = str(order.get("product_id") or "")
        sku = str(order.get("sku") or "")
        timeline = [
            {
                "event_id": event.get("fact_id"),
                "state": self._state(event.get("canonical_status")),
                "effective_at": event.get("effective_at"),
                "evidence_id": event.get("evidence_id"),
                "source_evidence_sha256": event.get(
                    "source_evidence_sha256"
                ),
                "quantity": event.get("quantity"),
                "currency": event.get("currency"),
                "amount": event.get("amount"),
            }
            for event in order.get("timeline", [])
            if event.get("canonical_status") in self.DELIVERY_STATES
        ]
        latest = timeline[-1]
        timeline_issues = self._timeline_issues(
            order=order,
            timeline=timeline,
            cutoff=cutoff,
        )
        related = self._related(
            order_id=order_id,
            product_id=product_id,
            sku=sku,
            upstream=upstream,
        )
        missing = (
            [
                "formal_carrier_readback_missing",
                "service_level_missing",
                "package_identity_missing",
                "leg_identity_missing",
                "chargeable_weight_missing",
                "exact_scope_logistics_rate_authority_missing",
                "actual_carrier_fee_missing",
            ]
            if readback is None
            else []
        )
        package = readback.get("package") if readback else None
        legs = list(readback.get("legs", [])) if readback else []
        freight = readback.get("freight_authority", {}) if readback else {}
        projection_status = (
            "blocked"
            if timeline_issues
            else "ready"
            if readback is not None
            else "partial"
        )
        state = str(readback.get("state")) if readback else latest["state"]
        return {
            "delivery_case_id": f"order-delivery:{order_id}",
            "shipment_id": (
                str(readback.get("shipment_id")) if readback else None
            ),
            "order_external_id": order_id,
            "product": {"id": product_id, "sku": sku},
            "package": package,
            "legs": legs,
            "carrier": (
                str(legs[-1].get("carrier") or "") or None
                if legs
                else None
            ),
            "service": (
                str(legs[-1].get("service") or "") or None
                if legs
                else None
            ),
            "chargeable_weight": (
                readback.get("chargeable_weight") if readback else None
            ),
            "freight_authority": {
                "currency": freight.get("currency"),
                "quoted": freight.get("quoted"),
                "actual": freight.get("actual"),
                "rate_card_id": freight.get("rate_card_id"),
                "calculation_id": freight.get("calculation_id"),
                "calculation_sha256": freight.get(
                    "calculation_sha256"
                ),
                "carrier_final_bill_evidence_id": freight.get(
                    "carrier_final_bill_evidence_id"
                ),
                "quote_is_delivery_fact": False,
            },
            "state": state,
            "projection_status": projection_status,
            "timeline": timeline,
            "related_authorities": related,
            "exception_readiness": {
                "status": (
                    "blocked"
                    if missing or timeline_issues
                    else "ready"
                ),
                "missing_authorities": [
                    *timeline_issues,
                    *missing,
                ],
                "compensation_allowed": False,
            },
            "owner": self._owner(state),
            "sla": self._sla(state),
            "next": self._next(state),
        }

    def _readback_index(
        self,
        *,
        readbacks: list[dict[str, Any]],
        orders: list[dict[str, Any]],
        cutoff: datetime,
    ) -> tuple[list[str], dict[str, dict[str, Any]]]:
        issues: list[str] = []
        index: dict[str, dict[str, Any]] = {}
        order_index = {
            str(order.get("external_id") or ""): order for order in orders
        }
        shipment_ids: set[str] = set()
        package_ids: set[str] = set()
        leg_ids: set[str] = set()
        tracking_refs: set[str] = set()
        for item in readbacks:
            order_id = str(item.get("order_external_id") or "").strip()
            order = order_index.get(order_id)
            if order is None:
                issues.append("delivery_readback_order_binding_drift")
                continue
            if order_id in index:
                issues.append("delivery_duplicate_order_readback")
                continue
            item_issues = self._readback_issues(
                item=item,
                order=order,
                cutoff=cutoff,
            )
            shipment_id = str(item.get("shipment_id") or "").strip()
            package_id = str(
                (item.get("package") or {}).get("package_id") or ""
            ).strip()
            if shipment_id in shipment_ids:
                item_issues.append("delivery_duplicate_shipment")
            if package_id in package_ids:
                item_issues.append("delivery_duplicate_package")
            shipment_ids.add(shipment_id)
            package_ids.add(package_id)
            for leg in item.get("legs", []):
                leg_id = str(leg.get("leg_id") or "").strip()
                tracking_ref = str(
                    leg.get("tracking_ref") or ""
                ).strip()
                if leg_id in leg_ids:
                    item_issues.append("delivery_duplicate_leg")
                if tracking_ref in tracking_refs:
                    item_issues.append("delivery_duplicate_tracking")
                leg_ids.add(leg_id)
                tracking_refs.add(tracking_ref)
            if item_issues:
                issues.extend(item_issues)
                continue
            index[order_id] = item
        return sorted(set(issues)), index

    def _readback_issues(
        self,
        *,
        item: dict[str, Any],
        order: dict[str, Any],
        cutoff: datetime,
    ) -> list[str]:
        issues: list[str] = []
        latest = list(order.get("timeline", []))[-1]
        required = {
            "readback_id": item.get("readback_id"),
            "shipment_id": item.get("shipment_id"),
            "order_external_id": item.get("order_external_id"),
        }
        if any(not str(value or "").strip() for value in required.values()):
            issues.append("delivery_readback_identity_missing")
        if (
            not str(item.get("readback_evidence_id") or "").strip()
            or not self._sha_valid(
                item.get("readback_evidence_sha256")
            )
        ):
            issues.append("delivery_readback_evidence_binding_missing")
        if str(item.get("product_id") or "") != str(
            order.get("product_id") or ""
        ):
            issues.append("delivery_readback_product_binding_drift")
        if str(item.get("sku") or "") != str(order.get("sku") or ""):
            issues.append("delivery_readback_sku_binding_drift")
        package = item.get("package") or {}
        if not str(package.get("package_id") or "").strip():
            issues.append("delivery_package_identity_missing")
        if package.get("quantity") != latest.get("quantity"):
            issues.append("delivery_package_quantity_drift")
        if not self._positive(package.get("physical_weight_kg")):
            issues.append("delivery_physical_weight_invalid")
        chargeable = item.get("chargeable_weight") or {}
        if (
            not self._positive(chargeable.get("value"))
            or chargeable.get("unit") != "kg"
            or not self._sha_valid(chargeable.get("calculation_sha256"))
        ):
            issues.append("delivery_chargeable_weight_invalid")
        elif (
            self._positive(package.get("physical_weight_kg"))
            and Decimal(str(chargeable["value"]))
            < Decimal(str(package["physical_weight_kg"]))
        ):
            issues.append("delivery_chargeable_weight_below_physical")
        legs = list(item.get("legs", []))
        if not legs:
            issues.append("delivery_leg_missing")
        prior_time: datetime | None = None
        prior_sequence = 0
        prior_state_rank = 0
        state_rank = {
            "pick_pack": 1,
            "handover": 2,
            "transit": 3,
            "delivery": 4,
            "exception": 5,
            "return": 6,
        }
        for leg in legs:
            sequence = leg.get("sequence")
            effective_at = self._timestamp(leg.get("effective_at"))
            if (
                not isinstance(sequence, int)
                or sequence != prior_sequence + 1
            ):
                issues.append("delivery_leg_sequence_drift")
            prior_sequence = sequence if isinstance(sequence, int) else 0
            if (
                not str(leg.get("leg_id") or "").strip()
                or not str(leg.get("tracking_ref") or "").strip()
                or not str(leg.get("carrier") or "").strip()
                or not str(leg.get("service") or "").strip()
            ):
                issues.append("delivery_leg_binding_missing")
            leg_state = str(leg.get("state") or "")
            current_state_rank = state_rank.get(leg_state)
            if (
                current_state_rank is None
                or current_state_rank < prior_state_rank
            ):
                issues.append("delivery_leg_transition_invalid")
            if current_state_rank is not None:
                prior_state_rank = current_state_rank
            if effective_at is None or effective_at > cutoff:
                issues.append("delivery_leg_time_invalid")
            elif prior_time is not None and effective_at < prior_time:
                issues.append("delivery_leg_time_reversed")
            if effective_at is not None:
                prior_time = effective_at
            if not self._sha_valid(leg.get("source_evidence_sha256")):
                issues.append("delivery_leg_evidence_hash_invalid")
            if (
                leg.get("evidence_status") != "current"
                or leg.get("evidence_revoked") is not False
            ):
                issues.append("delivery_leg_evidence_invalid")
        freight = item.get("freight_authority") or {}
        if (
            len(str(freight.get("currency") or "")) != 3
            or not self._nonnegative(freight.get("quoted"))
            or not self._nonnegative(freight.get("actual"))
            or not str(freight.get("rate_card_id") or "").strip()
            or not str(freight.get("calculation_id") or "").strip()
            or not self._sha_valid(freight.get("calculation_sha256"))
            or not str(
                freight.get("carrier_final_bill_evidence_id") or ""
            ).strip()
        ):
            issues.append("delivery_freight_authority_invalid")
        expected_state = self._state(latest.get("canonical_status"))
        readback_state = str(item.get("state") or "")
        if readback_state not in {expected_state, "exception"}:
            issues.append("delivery_readback_transition_drift")
        if legs and str(legs[-1].get("state") or "") != readback_state:
            issues.append("delivery_readback_leg_state_drift")
        return issues

    def _timeline_issues(
        self,
        *,
        order: dict[str, Any],
        timeline: list[dict[str, Any]],
        cutoff: datetime,
    ) -> list[str]:
        issues: list[str] = []
        event_ids: set[str] = set()
        prior_time: datetime | None = None
        rank = {
            "handover": 1,
            "transit": 2,
            "delivery": 3,
            "return": 4,
            "exception": 5,
        }
        prior_rank = 0
        expected_quantity = None
        for event in timeline:
            event_id = str(event.get("event_id") or "").strip()
            if not event_id or event_id in event_ids:
                issues.append("delivery_duplicate_or_missing_event")
            event_ids.add(event_id)
            effective_at = self._timestamp(event.get("effective_at"))
            if effective_at is None or effective_at > cutoff:
                issues.append("delivery_event_time_invalid")
            elif prior_time is not None and effective_at < prior_time:
                issues.append("delivery_event_time_reversed")
            if effective_at is not None:
                prior_time = effective_at
            current_rank = rank[event["state"]]
            if current_rank < prior_rank:
                issues.append("delivery_event_transition_invalid")
            prior_rank = current_rank
            quantity = event.get("quantity")
            if expected_quantity is None:
                expected_quantity = quantity
            elif quantity != expected_quantity:
                issues.append("delivery_event_quantity_drift")
            if not self._sha_valid(event.get("source_evidence_sha256")):
                issues.append("delivery_event_evidence_hash_invalid")
        if not str(order.get("external_id") or "").strip():
            issues.append("delivery_order_binding_missing")
        if (
            not str(order.get("product_id") or "").strip()
            or not str(order.get("sku") or "").strip()
        ):
            issues.append("delivery_product_binding_missing")
        return sorted(set(issues))

    @staticmethod
    def _related(
        *,
        order_id: str,
        product_id: str,
        sku: str,
        upstream: dict[str, dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        candidates = {
            "inventory": upstream["inventory"].get("sku_summaries", []),
            "procurement": upstream["procurement"].get("items", []),
            "returns": upstream["returns"].get("returns", []),
            "customer_service": upstream["customer_service"].get("cases", []),
            "profit": upstream["profit"].get("items", []),
        }
        return {
            name: [
                row
                for row in rows
                if order_id
                in {
                    str(row.get("order_external_id") or ""),
                    str(row.get("external_id") or ""),
                    str(row.get("order_id") or ""),
                }
                or product_id
                in {
                    str(row.get("product_id") or ""),
                    str((row.get("product") or {}).get("id") or ""),
                }
                or sku
                == str(
                    row.get("sku")
                    or (row.get("product") or {}).get("sku")
                    or ""
                )
            ]
            for name, rows in candidates.items()
        }

    def _projection_issues(
        self,
        *,
        name: str,
        projection: dict[str, Any],
        contract_id: str,
        scope: dict[str, Any],
        cutoff: datetime,
    ) -> list[str]:
        issues = []
        if projection.get("contract_id") != contract_id:
            issues.append(f"delivery_{name}_contract_drift")
        actual_scope = projection.get("scope", {})
        if any(
            actual_scope.get(key) != scope[key]
            for key in ("tenant_ref", "entity_ref", "store_ref")
        ):
            issues.append(f"delivery_{name}_scope_drift")
        if projection.get("as_of") != cutoff.isoformat():
            issues.append(f"delivery_{name}_as_of_drift")
        if len(str(projection.get("snapshot_sha256") or "")) != 64:
            issues.append(f"delivery_{name}_snapshot_invalid")
        if name == "delivery_readbacks":
            expected_snapshot = self._hash(
                {
                    key: value
                    for key, value in projection.items()
                    if key != "snapshot_sha256"
                }
            )
            if projection.get("snapshot_sha256") != expected_snapshot:
                issues.append("delivery_readback_snapshot_drift")
            if projection.get("status") == "ready":
                authority = projection.get("authority") or {}
                controls = projection.get("control_envelope") or {}
                if (
                    authority.get("source_kind")
                    not in {
                        "official_public_api",
                        "authorized_formal_export",
                    }
                    or not str(authority.get("adapter_id") or "").strip()
                    or not str(
                        authority.get("adapter_version") or ""
                    ).strip()
                    or not str(
                        authority.get("authorization_evidence_id") or ""
                    ).strip()
                    or authority.get("immutable") is not True
                    or authority.get("revoked") is not False
                    or not (
                        controls.get("official_adapter_bound") is True
                        or controls.get("formal_export_bound") is True
                    )
                    or controls.get("private_erp_interface_allowed")
                    is not False
                    or controls.get("external_write_allowed") is not False
                ):
                    issues.append(
                        "delivery_readback_authority_contract_invalid"
                    )
        if projection.get("status") == "blocked":
            issues.append(f"delivery_{name}_blocked")
        return issues

    def _payload(
        self,
        *,
        scope: dict[str, Any],
        cutoff: datetime,
        status: str,
        filters: dict[str, Any],
        shipments: list[dict[str, Any]],
        page_size: int,
        next_cursor: str | None,
        source_gaps: list[str],
        reads: list[str],
        total: int | None = None,
        snapshots: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        counts = {
            "total": len(shipments) if total is None else total,
            "formal_shipments": sum(
                bool(item["shipment_id"]) for item in shipments
            ),
            "ready": sum(
                item["projection_status"] == "ready" for item in shipments
            ),
            "partial": sum(
                item["projection_status"] == "partial" for item in shipments
            ),
            "blocked": sum(
                item["projection_status"] == "blocked" for item in shipments
            ),
            "exceptions": sum(
                item["state"] == "exception" for item in shipments
            ),
        }
        artifact = {
            "contract_id": self.ARTIFACT_CONTRACT_ID,
            "scope": scope,
            "as_of": cutoff.isoformat(),
            "shipments": [
                {
                    "shipment_id": item["shipment_id"],
                    "state": item["state"],
                    "next": item["next"],
                }
                for item in shipments
            ],
            "authority": "suggestion_and_internal_exception_task_only",
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
            "shipments": shipments,
            "source_gaps": source_gaps,
            "upstream": snapshots or {},
            "agent_artifact": {
                **artifact,
                "artifact_sha256": self._hash(artifact),
                "shipment_mutation_allowed": False,
                "inventory_mutation_allowed": False,
                "order_mutation_allowed": False,
                "return_mutation_allowed": False,
                "compensation_allowed": False,
                "carrier_contact_allowed": False,
                "customer_contact_allowed": False,
                "self_approval_allowed": False,
                "permit_issue_allowed": False,
                "external_write_allowed": False,
            },
            "control_envelope": {
                "read_only_projection": True,
                "upstream_reads": reads,
                "client_recalculation_allowed": False,
                "legacy_logistics_quote_as_delivery_fact": False,
                "shipment_created": False,
                "shipment_modified": False,
                "handover_confirmed": False,
                "delivery_confirmed": False,
                "inventory_modified": False,
                "order_modified": False,
                "return_modified": False,
                "approval_created": False,
                "permit_created": False,
                "external_write_allowed": False,
                "private_erp_interface_allowed": False,
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
    ) -> dict[str, Any]:
        if not principal.can_access_store(store_ref):
            raise PermissionError("delivery store scope is invalid")
        tenant_ref = str(
            entity_scope.get("tenant_ref") or principal.tenant_ref
        ).strip()
        if tenant_ref != principal.tenant_ref:
            raise PermissionError("delivery tenant scope is invalid")
        granted_store = str(
            entity_scope.get("store_ref") or store_ref
        ).strip()
        if granted_store != store_ref:
            raise PermissionError("delivery store scope is invalid")
        return {
            "tenant_ref": tenant_ref,
            "entity_ref": (
                str(entity_scope.get("entity_ref") or "").strip() or None
            ),
            "store_ref": store_ref,
        }

    @staticmethod
    def _cutoff(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("delivery as_of must include timezone")
        value = value.astimezone(UTC)
        if value > datetime.now(UTC):
            raise ValueError("delivery as_of cannot be in the future")
        return value

    @classmethod
    def _is_delivery_order(cls, order: dict[str, Any]) -> bool:
        return any(
            event.get("canonical_status") in cls.DELIVERY_STATES
            for event in order.get("timeline", [])
        )

    @staticmethod
    def _state(value: Any) -> str:
        return {
            "awaiting_packaging": "pick_pack",
            "awaiting_handover": "handover",
            "in_transit": "transit",
            "delivered": "delivery",
            "returned": "return",
        }.get(str(value), "exception")

    @staticmethod
    def _owner(state: str) -> str:
        return (
            "returns_owner"
            if state == "return"
            else "fulfillment_owner"
            if state == "pick_pack"
            else "logistics_owner"
        )

    @staticmethod
    def _sla(state: str) -> str:
        return (
            "immediate independent review"
            if state in {"exception", "return"}
            else "before carrier or platform deadline"
        )

    @staticmethod
    def _next(state: str) -> str:
        return {
            "pick_pack": "verify package identity and measured weight",
            "handover": "verify formal carrier handover readback",
            "transit": "monitor formal carrier readback",
            "delivery": "reconcile delivery and financial impact",
            "return": "continue in Returns authority",
            "exception": "open an internal exception task",
        }[state]

    @staticmethod
    def _sort_key(item: dict[str, Any]) -> tuple[str, str]:
        return (
            str(item["timeline"][-1]["effective_at"]),
            item["delivery_case_id"],
        )

    @staticmethod
    def _encode_cursor(key: tuple[str, str]) -> str:
        return base64.urlsafe_b64encode(
            json.dumps(list(key), separators=(",", ":")).encode()
        ).decode()

    @staticmethod
    def _decode_cursor(value: str) -> tuple[str, str]:
        try:
            decoded = json.loads(
                base64.urlsafe_b64decode(value.encode()).decode()
            )
        except Exception as exc:
            raise ValueError("delivery cursor is invalid") from exc
        if not isinstance(decoded, list) or len(decoded) != 2:
            raise ValueError("delivery cursor is invalid")
        return str(decoded[0]), str(decoded[1])

    @staticmethod
    def _hash(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(
                value, sort_keys=True, separators=(",", ":"), default=str
            ).encode()
        ).hexdigest()

    @staticmethod
    def _timestamp(value: Any) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(
                str(value).replace("Z", "+00:00")
            )
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(UTC)

    @staticmethod
    def _sha_valid(value: Any) -> bool:
        text = str(value or "")
        return len(text) == 64 and all(
            character in "0123456789abcdef" for character in text
        )

    @staticmethod
    def _positive(value: Any) -> bool:
        try:
            number = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return False
        return number.is_finite() and number > 0

    @staticmethod
    def _nonnegative(value: Any) -> bool:
        try:
            number = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return False
        return number.is_finite() and number >= 0
