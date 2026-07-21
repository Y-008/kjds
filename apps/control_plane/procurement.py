from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import ApprovalStatus, new_id
from .evidence import parse_timestamp
from .sql_repository import Base


class SamplePurchaseOrderRow(Base):
    __tablename__ = "sample_purchase_orders"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    approval_id: Mapped[str] = mapped_column(ForeignKey("approvals.id"), unique=True, nullable=False)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), nullable=False)
    offer_id: Mapped[str] = mapped_column(String, nullable=False)
    scenario_id: Mapped[str] = mapped_column(String, nullable=False)
    supplier_ref: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(38, 12), nullable=False)
    requested_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SampleProcurementEventRow(Base):
    __tablename__ = "sample_procurement_events"
    __table_args__ = (
        UniqueConstraint("purchase_order_id", "sequence", name="uq_sample_event_sequence"),
        UniqueConstraint(
            "purchase_order_id", "event_type", "evidence_id", name="uq_sample_event_evidence"
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    purchase_order_id: Mapped[str] = mapped_column(
        ForeignKey("sample_purchase_orders.id"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence_records.id"), nullable=False)
    facts_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


EVENT_STATE = {
    "order_confirmed": "order_confirmed",
    "shipped": "shipped",
    "received": "received",
    "inspection_completed": "inspected",
    "golden_sample_approved": "golden_sample_approved",
    "sample_rejected": "sample_rejected",
    "rework_required": "rework_required",
    "cancelled": "cancelled",
}

ALLOWED_TRANSITIONS = {
    "approved_to_order": {"order_confirmed", "cancelled"},
    "order_confirmed": {"shipped", "cancelled"},
    "shipped": {"received", "cancelled"},
    "received": {"inspection_completed"},
    "inspected": {"golden_sample_approved", "sample_rejected", "rework_required"},
    "rework_required": {"inspection_completed", "cancelled"},
    "golden_sample_approved": set(),
    "sample_rejected": set(),
    "cancelled": set(),
}

REQUIRED_EVENT_FACTS = {
    "order_confirmed": {"supplier_order_ref", "promised_delivery_at"},
    "shipped": {"tracking_ref", "carrier"},
    "received": {"received_quantity", "damaged_quantity"},
    "inspection_completed": {"inspected_quantity", "passed_quantity", "defect_count", "result"},
    "golden_sample_approved": {"golden_sample_ref"},
    "sample_rejected": {"reason"},
    "rework_required": {"reason"},
    "cancelled": {"reason"},
}


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


class ProcurementService:
    def __init__(self, *, engine, repository, sourcing_store, sourcing, evidence) -> None:
        self.engine = engine
        self.repository = repository
        self.sourcing_store = sourcing_store
        self.sourcing = sourcing
        self.evidence = evidence

    def create_sample_order(self, approval_id: str, *, created_by: str) -> dict:
        approval = self.repository.get_approval(approval_id)
        if approval.status != ApprovalStatus.APPROVED:
            raise ValueError("Sample order requires an independently approved procurement decision")
        if approval.action != "procurement.place_order" or approval.resource_type != "profit_scenario":
            raise ValueError("Approval is not a procurement decision")
        payload = approval.payload
        required = {"product_id", "offer_id", "scenario_id", "quantity"}
        missing = sorted(required - payload.keys())
        if missing:
            raise ValueError(f"Procurement approval payload missing: {', '.join(missing)}")
        offer = self.sourcing_store.get_offer(str(payload["offer_id"]))
        scenario = self.sourcing_store.get_scenario(str(payload["scenario_id"]))
        if approval.resource_id != scenario.id or scenario.offer_id != offer.id:
            raise ValueError("Approval, offer, and scenario do not share the same decision basis")
        if offer.product_id != payload["product_id"] or scenario.cm3_cny <= 0:
            raise ValueError("Approved procurement basis is invalid or no longer positive-CM3")
        self.sourcing.require_release_ready(scenario)
        quantity = int(payload["quantity"])
        if quantity < offer.min_order_quantity:
            raise ValueError("Approved quantity is below supplier MOQ")
        now = datetime.now(UTC)
        with Session(self.engine) as session, session.begin():
            existing = session.scalar(
                select(SamplePurchaseOrderRow).where(SamplePurchaseOrderRow.approval_id == approval_id)
            )
            if existing is not None:
                return self._view(session, existing)
            row = SamplePurchaseOrderRow(
                id=new_id("spo"),
                approval_id=approval.id,
                product_id=offer.product_id,
                offer_id=offer.id,
                scenario_id=scenario.id,
                supplier_ref=offer.supplier_ref,
                quantity=quantity,
                currency=offer.currency,
                unit_price=offer.unit_price,
                requested_by=created_by,
                created_at=now,
            )
            session.add(row)
            session.flush()
            result = self._view(session, row)
        for evidence_id in scenario.evidence:
            self.evidence.link(
                evidence_id=evidence_id,
                target_type="sample_purchase_order",
                target_id=result["id"],
                relationship="approved_basis",
                created_by=created_by,
            )
        return result

    def record_event(
        self,
        order_id: str,
        *,
        event_type: str,
        effective_at: str,
        evidence_id: str,
        facts: dict[str, Any],
        created_by: str,
    ) -> dict:
        event_type = event_type.strip().lower()
        if event_type not in EVENT_STATE:
            raise ValueError(f"Unsupported sample procurement event: {event_type}")
        if not isinstance(facts, dict):
            raise ValueError("Sample procurement event facts must be an object")
        missing = sorted(
            key for key in REQUIRED_EVENT_FACTS[event_type] if facts.get(key) in (None, "")
        )
        if missing:
            raise ValueError(f"{event_type} missing facts: {', '.join(missing)}")
        self._validate_event_facts(event_type, facts)
        self.evidence.require_valid([evidence_id])
        effective = parse_timestamp(effective_at, "effective_at")
        recorded = datetime.now(UTC)
        with Session(self.engine) as session, session.begin():
            order = session.scalar(
                select(SamplePurchaseOrderRow)
                .where(SamplePurchaseOrderRow.id == order_id)
                .with_for_update()
            )
            if order is None:
                raise KeyError(f"Unknown sample purchase order: {order_id}")
            events = list(
                session.scalars(
                    select(SampleProcurementEventRow)
                    .where(SampleProcurementEventRow.purchase_order_id == order_id)
                    .order_by(SampleProcurementEventRow.sequence)
                )
            )
            for existing in events:
                if (
                    existing.event_type == event_type
                    and existing.evidence_id == evidence_id
                    and existing.facts_json == facts
                    and _iso(existing.effective_at) == effective.isoformat()
                ):
                    return self._view(session, order, events)
            state = EVENT_STATE[events[-1].event_type] if events else "approved_to_order"
            if event_type not in ALLOWED_TRANSITIONS[state]:
                raise ValueError(f"Cannot record {event_type} while sample order is {state}")
            row = SampleProcurementEventRow(
                id=new_id("spe"),
                purchase_order_id=order_id,
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
            result = self._view(session, order, events)
            event_id = row.id
        self.evidence.link(
            evidence_id=evidence_id,
            target_type="sample_procurement_event",
            target_id=event_id,
            relationship="proves",
            created_by=created_by,
        )
        return result

    def list_orders(self, limit: int = 100) -> list[dict]:
        with Session(self.engine) as session:
            rows = list(
                session.scalars(
                    select(SamplePurchaseOrderRow)
                    .order_by(SamplePurchaseOrderRow.created_at.desc())
                    .limit(min(max(limit, 1), 500))
                )
            )
            return [self._view(session, row) for row in rows]

    def get_order(self, order_id: str) -> dict:
        with Session(self.engine) as session:
            row = session.get(SamplePurchaseOrderRow, order_id)
            if row is None:
                raise KeyError(f"Unknown sample purchase order: {order_id}")
            return self._view(session, row)

    def supplier_performance(self) -> list[dict]:
        orders = self.list_orders(limit=500)
        grouped = defaultdict(list)
        for order in orders:
            grouped[order["supplier_ref"]].append(order)
        result = []
        for supplier_ref, supplier_orders in grouped.items():
            quality_values = []
            completeness_values = []
            on_time_values = []
            evidence_ids = set()
            for order in supplier_orders:
                events = {item["event_type"]: item for item in order["events"]}
                evidence_ids.update(item["evidence_id"] for item in order["events"])
                received = events.get("received")
                inspected = events.get("inspection_completed")
                confirmed = events.get("order_confirmed")
                if received:
                    completeness_values.append(
                        min(Decimal("1"), Decimal(str(received["facts"]["received_quantity"])) / order["quantity"])
                    )
                if inspected and Decimal(str(inspected["facts"]["inspected_quantity"])) > 0:
                    quality_values.append(
                        Decimal(str(inspected["facts"]["passed_quantity"]))
                        / Decimal(str(inspected["facts"]["inspected_quantity"]))
                    )
                if confirmed and received:
                    promised = parse_timestamp(
                        str(confirmed["facts"]["promised_delivery_at"]), "promised_delivery_at"
                    )
                    actual = parse_timestamp(received["effective_at"], "received_at")
                    on_time_values.append(Decimal("1") if actual <= promised else Decimal("0"))
            metrics = {
                "quality_yield": self._average(quality_values),
                "delivery_completeness": self._average(completeness_values),
                "on_time_rate": self._average(on_time_values),
            }
            weighted = [(metrics["quality_yield"], Decimal("0.4")), (metrics["on_time_rate"], Decimal("0.3")), (metrics["delivery_completeness"], Decimal("0.3"))]
            available = [(value, weight) for value, weight in weighted if value is not None]
            score = None
            if available:
                score = (sum(value * weight for value, weight in available) / sum(weight for _, weight in available) * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
            result.append(
                {
                    "supplier_ref": supplier_ref,
                    "sample_order_count": len(supplier_orders),
                    "completed_sample_count": sum(order["status"] == "golden_sample_approved" for order in supplier_orders),
                    "rejected_sample_count": sum(order["status"] == "sample_rejected" for order in supplier_orders),
                    "quality_yield": str(metrics["quality_yield"]) if metrics["quality_yield"] is not None else None,
                    "delivery_completeness": str(metrics["delivery_completeness"]) if metrics["delivery_completeness"] is not None else None,
                    "on_time_rate": str(metrics["on_time_rate"]) if metrics["on_time_rate"] is not None else None,
                    "score": str(score) if score is not None else None,
                    "evidence_count": len(evidence_ids),
                }
            )
        return sorted(result, key=lambda item: Decimal(item["score"] or "-1"), reverse=True)

    def backup_options(self, order_id: str) -> dict:
        order = self.get_order(order_id)
        comparison = self.sourcing.compare_product_offers(order["product_id"])
        performance = {item["supplier_ref"]: item for item in self.supplier_performance()}
        options = []
        for item in comparison["rows"]:
            offer = item["offer"]
            scenario = item["scenario"]
            if (
                offer.supplier_ref == order["supplier_ref"]
                or scenario is None
                or scenario.cm3_cny <= 0
                or not scenario.cost_complete
            ):
                continue
            options.append(
                {
                    "offer": offer,
                    "scenario": scenario,
                    "supplier_performance": performance.get(offer.supplier_ref),
                    "advisory_only": True,
                }
            )
        options.sort(
            key=lambda item: (
                Decimal((item["supplier_performance"] or {}).get("score") or "-1"),
                item["scenario"].cm3_cny,
            ),
            reverse=True,
        )
        return {"sample_order": order, "options": options, "automatic_switch": False}

    @staticmethod
    def _validate_event_facts(event_type: str, facts: dict[str, Any]) -> None:
        if event_type == "order_confirmed":
            parse_timestamp(str(facts["promised_delivery_at"]), "promised_delivery_at")
        elif event_type == "received":
            received = int(facts["received_quantity"])
            damaged = int(facts["damaged_quantity"])
            if received < 0 or damaged < 0 or damaged > received:
                raise ValueError("Received and damaged quantities are inconsistent")
        elif event_type == "inspection_completed":
            inspected = int(facts["inspected_quantity"])
            passed = int(facts["passed_quantity"])
            defects = int(facts["defect_count"])
            if inspected < 1 or passed < 0 or passed > inspected or defects < 0:
                raise ValueError("Inspection quantities are inconsistent")
            if facts["result"] not in {"passed", "failed", "rework"}:
                raise ValueError("Inspection result must be passed, failed, or rework")

    @staticmethod
    def _average(values: list[Decimal]) -> Decimal | None:
        if not values:
            return None
        return (sum(values) / len(values)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    @staticmethod
    def _event(row: SampleProcurementEventRow) -> dict:
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
        row: SamplePurchaseOrderRow,
        event_rows: list[SampleProcurementEventRow] | None = None,
    ) -> dict:
        if event_rows is None:
            event_rows = list(
                session.scalars(
                    select(SampleProcurementEventRow)
                    .where(SampleProcurementEventRow.purchase_order_id == row.id)
                    .order_by(SampleProcurementEventRow.sequence)
                )
            )
        events = [self._event(item) for item in event_rows]
        status = EVENT_STATE[event_rows[-1].event_type] if event_rows else "approved_to_order"
        product = self.repository.get_product(row.product_id)
        return {
            "id": row.id,
            "approval_id": row.approval_id,
            "product_id": row.product_id,
            "product": {"sku": product.sku, "name": product.name},
            "offer_id": row.offer_id,
            "scenario_id": row.scenario_id,
            "supplier_ref": row.supplier_ref,
            "quantity": row.quantity,
            "currency": row.currency,
            "unit_price": str(row.unit_price),
            "requested_by": row.requested_by,
            "created_at": _iso(row.created_at),
            "status": status,
            "next_events": sorted(ALLOWED_TRANSITIONS[status]),
            "events": events,
        }
