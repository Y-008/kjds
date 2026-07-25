from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import ApprovalStatus, new_id
from .evidence import parse_timestamp
from .sql_repository import Base


class SalesFulfillmentPlanRow(Base):
    __tablename__ = "sales_fulfillment_plans"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    sales_order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), unique=True, nullable=False)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SalesFulfillmentEventRow(Base):
    __tablename__ = "sales_fulfillment_events"
    __table_args__ = (
        UniqueConstraint("plan_id", "sequence", name="uq_sales_fulfillment_event_sequence"),
        UniqueConstraint(
            "plan_id",
            "event_type",
            "evidence_id",
            name="uq_sales_fulfillment_event_evidence",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("sales_fulfillment_plans.id"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence_records.id"), nullable=False)
    facts_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


EVENT_STATE = {
    "route_selected": "route_selected",
    "procurement_approval_requested": "approval_pending",
    "supplier_order_confirmed": "supplier_order_confirmed",
    "domestic_shipped": "domestic_shipped",
    "warehouse_received": "warehouse_received",
    "packed_for_export": "packed_for_export",
    "international_handover": "international_handover",
    "cancelled": "cancelled",
}

ALLOWED_TRANSITIONS = {
    "awaiting_route": {"route_selected", "cancelled"},
    "route_selected": {"route_selected", "procurement_approval_requested", "cancelled"},
    "approval_pending": {"supplier_order_confirmed", "cancelled"},
    "supplier_order_confirmed": {"domestic_shipped", "cancelled"},
    "domestic_shipped": {"warehouse_received", "cancelled"},
    "warehouse_received": {"packed_for_export", "cancelled"},
    "packed_for_export": {"international_handover", "cancelled"},
    "international_handover": set(),
    "cancelled": set(),
}

REQUIRED_EVENT_FACTS = {
    "route_selected": {
        "aggregator",
        "carrier_code",
        "service_code",
        "warehouse_id",
        "warehouse_name",
        "warehouse_address",
        "address_valid_at",
        "delivery_method_status",
        "legacy_connection",
    },
    "supplier_order_confirmed": {
        "supplier_order_ref",
        "ship_to_warehouse_id",
        "ship_to_name",
        "ship_to_address",
        "promised_dispatch_at",
    },
    "domestic_shipped": {"tracking_ref", "domestic_carrier"},
    "warehouse_received": {"received_quantity", "damaged_quantity"},
    "packed_for_export": {
        "package_length_cm",
        "package_width_cm",
        "package_height_cm",
        "package_weight_kg",
        "logistics_label_ref",
    },
    "international_handover": {"crossborder_tracking_ref", "carrier_code"},
    "cancelled": {"reason"},
}


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


class SalesFulfillmentService:
    """Order-triggered sourcing and routing ledger with no external execution path."""

    def __init__(self, *, engine, repository, sourcing_store, sourcing, evidence, commerce) -> None:
        self.engine = engine
        self.repository = repository
        self.sourcing_store = sourcing_store
        self.sourcing = sourcing
        self.evidence = evidence
        self.commerce = commerce

    def create_plan(self, sales_order_id: str, *, created_by: str) -> dict[str, Any]:
        order = self.repository.get_order(sales_order_id)
        now = datetime.now(UTC)
        with Session(self.engine) as session, session.begin():
            existing = session.scalar(
                select(SalesFulfillmentPlanRow).where(
                    SalesFulfillmentPlanRow.sales_order_id == sales_order_id
                )
            )
            if existing is not None:
                return self._view(session, existing)
            row = SalesFulfillmentPlanRow(
                id=new_id("sfp"),
                sales_order_id=order.id,
                product_id=order.product_id,
                quantity=order.quantity,
                created_by=created_by,
                created_at=now,
            )
            session.add(row)
            session.flush()
            return self._view(session, row)

    def select_route(
        self,
        plan_id: str,
        *,
        effective_at: str,
        evidence_id: str,
        facts: dict[str, Any],
        created_by: str,
    ) -> dict[str, Any]:
        normalized = self._validate_route_facts(facts)
        return self._append_event(
            plan_id,
            event_type="route_selected",
            effective_at=effective_at,
            evidence_id=evidence_id,
            facts=normalized,
            created_by=created_by,
        )

    def request_procurement_approval(
        self,
        plan_id: str,
        *,
        offer_id: str,
        scenario_id: str,
        quantity: int,
        rationale: str,
        requested_by: str,
    ) -> dict[str, Any]:
        plan = self.get_plan(plan_id)
        if plan["status"] != "route_selected":
            raise ValueError("A current logistics route and domestic warehouse are required before procurement")
        order = self.repository.get_order(plan["sales_order_id"])
        offer = self.sourcing_store.get_offer(offer_id)
        scenario = self.sourcing_store.get_scenario(scenario_id)
        if offer.product_id != order.product_id or scenario.offer_id != offer.id:
            raise ValueError("Sales order, supplier offer, and profit scenario must reference the same product")
        if scenario.cm3_cny <= 0:
            raise ValueError("Order-triggered procurement requires positive CM3")
        self.sourcing.require_release_ready(scenario)
        comparison = self.sourcing.compare_product_offers(order.product_id)
        if not comparison["ready_for_procurement_review"]:
            raise ValueError("Three current evidence-backed offers and complete CM3 scenarios are required")
        selected = next(
            (
                item
                for item in comparison["rows"]
                if item["offer"].id == offer.id
                and item["scenario"] is not None
                and item["scenario"].id == scenario.id
            ),
            None,
        )
        if selected is None:
            raise ValueError("Selected offer and scenario are not in the current supplier comparison")
        if not self.commerce.product_readiness(order.product_id)["ready_for_validation"]:
            raise ValueError("All three Product Passports must be approved before production procurement")
        if quantity < max(order.quantity, offer.min_order_quantity):
            raise ValueError("Procurement quantity must cover the sales order and supplier MOQ")
        if quantity > order.quantity and not rationale.strip():
            raise ValueError("MOQ overbuy requires an explicit inventory rationale")
        route = plan["route"]
        approval = self.commerce.request_approval(
            action="procurement.place_order",
            resource_type="sales_fulfillment_plan",
            resource_id=plan_id,
            requested_by=requested_by,
            payload={
                "sales_order_id": order.id,
                "external_sales_order_id": order.external_id,
                "product_id": order.product_id,
                "offer_id": offer.id,
                "scenario_id": scenario.id,
                "supplier_ref": offer.supplier_ref,
                "sales_quantity": order.quantity,
                "procurement_quantity": quantity,
                "inventory_rationale": rationale.strip(),
                "route_selection": route,
                "expected_cm3_cny": str(scenario.cm3_cny),
                "cost_evidence": scenario.cost_evidence,
                "automatic_supplier_order": False,
                "automatic_payment": False,
            },
        )
        return self._append_event(
            plan_id,
            event_type="procurement_approval_requested",
            effective_at=datetime.now(UTC).isoformat(),
            evidence_id=route["evidence_id"],
            facts={
                "approval_id": approval.id,
                "offer_id": offer.id,
                "scenario_id": scenario.id,
                "quantity": quantity,
                "supplier_ref": offer.supplier_ref,
            },
            created_by=requested_by,
        )

    def record_event(
        self,
        plan_id: str,
        *,
        event_type: str,
        effective_at: str,
        evidence_id: str,
        facts: dict[str, Any],
        created_by: str,
    ) -> dict[str, Any]:
        event_type = event_type.strip().lower()
        if event_type in {"route_selected", "procurement_approval_requested"}:
            raise ValueError(f"{event_type} must use its dedicated governed operation")
        if event_type not in REQUIRED_EVENT_FACTS:
            raise ValueError(f"Unsupported sales fulfillment event: {event_type}")
        normalized = dict(facts)
        missing = sorted(
            key for key in REQUIRED_EVENT_FACTS[event_type] if normalized.get(key) in (None, "")
        )
        if missing:
            raise ValueError(f"{event_type} missing facts: {', '.join(missing)}")
        plan = self.get_plan(plan_id)
        if event_type == "supplier_order_confirmed":
            self._require_approved_procurement(plan)
            route = plan["route"]
            if (
                str(normalized["ship_to_warehouse_id"]) != str(route["warehouse_id"])
                or str(normalized["ship_to_name"]).strip() != str(route["warehouse_name"]).strip()
                or str(normalized["ship_to_address"]).strip()
                != str(route["warehouse_address"]).strip()
            ):
                raise ValueError("Supplier order ship-to address must equal the selected logistics warehouse")
            parse_timestamp(str(normalized["promised_dispatch_at"]), "promised_dispatch_at")
        elif event_type == "warehouse_received":
            try:
                received = int(normalized["received_quantity"])
                damaged = int(normalized["damaged_quantity"])
            except (TypeError, ValueError) as exc:
                raise ValueError("Warehouse receipt quantities must be integers") from exc
            if received < 0 or damaged < 0 or damaged > received:
                raise ValueError("Warehouse receipt quantities are inconsistent")
        elif event_type == "packed_for_export":
            try:
                measurements = [
                    float(normalized[key])
                    for key in (
                        "package_length_cm",
                        "package_width_cm",
                        "package_height_cm",
                        "package_weight_kg",
                    )
                ]
            except (TypeError, ValueError) as exc:
                raise ValueError("Packed dimensions and weight must be numeric") from exc
            if any(not isfinite(value) or value <= 0 for value in measurements):
                raise ValueError("Packed dimensions and weight must be positive")
        elif event_type == "international_handover":
            route = plan["route"]
            if self._carrier_code(str(normalized["carrier_code"])) != route["carrier_code"]:
                raise ValueError("International handover carrier must equal the selected route")
            normalized["carrier_code"] = route["carrier_code"]
        return self._append_event(
            plan_id,
            event_type=event_type,
            effective_at=effective_at,
            evidence_id=evidence_id,
            facts=normalized,
            created_by=created_by,
        )

    def get_plan(self, plan_id: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            row = session.get(SalesFulfillmentPlanRow, plan_id)
            if row is None:
                raise KeyError(f"Unknown sales fulfillment plan: {plan_id}")
            return self._view(session, row)

    def list_plans(self, limit: int = 100) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            rows = list(
                session.scalars(
                    select(SalesFulfillmentPlanRow)
                    .order_by(SalesFulfillmentPlanRow.created_at.desc())
                    .limit(min(max(limit, 1), 500))
                )
            )
            return [self._view(session, row) for row in rows]

    def _append_event(
        self,
        plan_id: str,
        *,
        event_type: str,
        effective_at: str,
        evidence_id: str,
        facts: dict[str, Any],
        created_by: str,
    ) -> dict[str, Any]:
        self.evidence.require_valid([evidence_id])
        effective = parse_timestamp(effective_at, "effective_at")
        recorded = datetime.now(UTC)
        with Session(self.engine) as session, session.begin():
            plan = session.scalar(
                select(SalesFulfillmentPlanRow)
                .where(SalesFulfillmentPlanRow.id == plan_id)
                .with_for_update()
            )
            if plan is None:
                raise KeyError(f"Unknown sales fulfillment plan: {plan_id}")
            events = list(
                session.scalars(
                    select(SalesFulfillmentEventRow)
                    .where(SalesFulfillmentEventRow.plan_id == plan_id)
                    .order_by(SalesFulfillmentEventRow.sequence)
                )
            )
            for existing in events:
                if (
                    existing.event_type == event_type
                    and existing.evidence_id == evidence_id
                    and existing.facts_json == facts
                    and _iso(existing.effective_at) == effective.isoformat()
                ):
                    return self._view(session, plan, events)
            state = EVENT_STATE[events[-1].event_type] if events else "awaiting_route"
            if event_type not in ALLOWED_TRANSITIONS[state]:
                raise ValueError(f"Cannot record {event_type} while fulfillment plan is {state}")
            row = SalesFulfillmentEventRow(
                id=new_id("sfe"),
                plan_id=plan_id,
                sequence=len(events) + 1,
                event_type=event_type,
                effective_at=effective,
                evidence_id=evidence_id,
                facts_json=facts,
                created_by=created_by,
                recorded_at=recorded,
            )
            session.add(row)
            session.flush()
            events.append(row)
            result = self._view(session, plan, events)
            event_id = row.id
        self.evidence.link(
            evidence_id=evidence_id,
            target_type="sales_fulfillment_event",
            target_id=event_id,
            relationship="proves",
            created_by=created_by,
        )
        return result

    def _validate_route_facts(self, facts: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(facts, dict):
            raise ValueError("Route selection facts must be an object")
        normalized = dict(facts)
        missing = sorted(
            key for key in REQUIRED_EVENT_FACTS["route_selected"] if normalized.get(key) in (None, "")
        )
        if missing:
            raise ValueError(f"route_selected missing facts: {', '.join(missing)}")
        if str(normalized["aggregator"]).strip().lower() != "kuajing84":
            raise ValueError("The current route contract requires a Kuajing84 warehouse observation")
        normalized["aggregator"] = "kuajing84"
        normalized["carrier_code"] = self._carrier_code(str(normalized["carrier_code"]))
        normalized["service_code"] = str(normalized["service_code"]).strip()
        normalized["warehouse_id"] = str(normalized["warehouse_id"]).strip()
        normalized["warehouse_name"] = str(normalized["warehouse_name"]).strip()
        normalized["warehouse_address"] = str(normalized["warehouse_address"]).strip()
        normalized["delivery_method_status"] = str(normalized["delivery_method_status"]).strip().lower()
        if not isinstance(normalized["legacy_connection"], bool):
            raise ValueError("legacy_connection must be a boolean")
        parse_timestamp(str(normalized["address_valid_at"]), "address_valid_at")
        if normalized["delivery_method_status"] not in {"active", "legacy_only"}:
            raise ValueError("Delivery method status must be active or legacy_only")
        if normalized["carrier_code"] == "UNI":
            if normalized["delivery_method_status"] != "legacy_only" or not normalized["legacy_connection"]:
                raise ValueError("UNI can only be recorded for an already-connected legacy Ozon method")
        elif normalized["delivery_method_status"] != "active":
            raise ValueError("A new route selection requires an active delivery method")
        return normalized

    def _require_approved_procurement(self, plan: dict[str, Any]) -> None:
        request = plan["procurement_approval"]
        if request is None:
            raise ValueError("Supplier order requires a procurement approval request")
        approval = self.repository.get_approval(str(request["approval_id"]))
        if (
            approval.status != ApprovalStatus.APPROVED
            or approval.action != "procurement.place_order"
            or approval.resource_type != "sales_fulfillment_plan"
            or approval.resource_id != plan["id"]
        ):
            raise ValueError("Supplier order requires an independently approved order-bound decision")

    @staticmethod
    def _carrier_code(value: str) -> str:
        code = value.strip().upper()
        if code == "GOOL":
            code = "GUOO"
        if len(code) < 2 or len(code) > 40 or not all(
            char.isalnum() or char in {"_", "-"} for char in code
        ):
            raise ValueError("Carrier code is invalid")
        return code

    @staticmethod
    def _event(row: SalesFulfillmentEventRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "sequence": row.sequence,
            "event_type": row.event_type,
            "effective_at": _iso(row.effective_at),
            "evidence_id": row.evidence_id,
            "facts": row.facts_json,
            "created_by": row.created_by,
            "recorded_at": _iso(row.recorded_at),
        }

    def _view(
        self,
        session: Session,
        row: SalesFulfillmentPlanRow,
        event_rows: list[SalesFulfillmentEventRow] | None = None,
    ) -> dict[str, Any]:
        if event_rows is None:
            event_rows = list(
                session.scalars(
                    select(SalesFulfillmentEventRow)
                    .where(SalesFulfillmentEventRow.plan_id == row.id)
                    .order_by(SalesFulfillmentEventRow.sequence)
                )
            )
        events = [self._event(item) for item in event_rows]
        status = EVENT_STATE[event_rows[-1].event_type] if event_rows else "awaiting_route"
        route_event = next(
            (item for item in reversed(events) if item["event_type"] == "route_selected"),
            None,
        )
        approval_event = next(
            (item for item in events if item["event_type"] == "procurement_approval_requested"),
            None,
        )
        approval_status = None
        ready_for_supplier_order = False
        if approval_event is not None:
            approval = self.repository.get_approval(str(approval_event["facts"]["approval_id"]))
            approval_status = approval.status.value
            ready_for_supplier_order = approval.status == ApprovalStatus.APPROVED
        order = self.repository.get_order(row.sales_order_id)
        return {
            "id": row.id,
            "sales_order_id": row.sales_order_id,
            "external_sales_order_id": order.external_id,
            "product_id": row.product_id,
            "quantity": row.quantity,
            "status": status,
            "route": (
                {
                    **route_event["facts"],
                    "evidence_id": route_event["evidence_id"],
                    "selected_at": route_event["effective_at"],
                }
                if route_event
                else None
            ),
            "domestic_warehouse_address_known": route_event is not None,
            "procurement_approval": approval_event["facts"] if approval_event else None,
            "procurement_approval_status": approval_status,
            "ready_for_supplier_order": ready_for_supplier_order,
            "automatic_supplier_order": False,
            "automatic_payment": False,
            "created_by": row.created_by,
            "created_at": _iso(row.created_at),
            "events": events,
        }
