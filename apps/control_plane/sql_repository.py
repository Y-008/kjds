from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Integer, Numeric, String, Text, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from .database import create_database_engine
from .domain import (
    AgentMode,
    AgentTask,
    Approval,
    ApprovalStatus,
    Charge,
    ChargeType,
    ContentAsset,
    ContentStatus,
    ContentType,
    ExperimentStatus,
    GrowthExperiment,
    MarketObservation,
    OpportunityInsight,
    Order,
    OrderStatus,
    Passport,
    PassportType,
    Product,
    ProductStatus,
    utc_now,
)


class Base(DeclarativeBase):
    pass


class ProductRow(Base):
    __tablename__ = "products"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    sku: Mapped[str] = mapped_column(String, unique=True)
    name: Mapped[str] = mapped_column(String)
    market: Mapped[str] = mapped_column(String)
    channel: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PassportRow(Base):
    __tablename__ = "passports"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"))
    kind: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer)
    facts_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    evidence_json: Mapped[list[str]] = mapped_column(JSON)
    approved_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OrderRow(Base):
    __tablename__ = "orders"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    external_id: Mapped[str] = mapped_column(String, unique=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    gross_revenue_decimal: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    booked_fx_rate_decimal: Mapped[Decimal] = mapped_column(Numeric(24, 10))
    status: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ChargeRow(Base):
    __tablename__ = "charges"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"))
    kind: Mapped[str] = mapped_column(String)
    amount_decimal: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    currency: Mapped[str] = mapped_column(String(3))
    fx_rate_decimal: Mapped[Decimal] = mapped_column(Numeric(24, 10))
    evidence_ref: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ApprovalRow(Base):
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    action: Mapped[str] = mapped_column(String)
    resource_type: Mapped[str] = mapped_column(String)
    resource_id: Mapped[str] = mapped_column(String)
    requested_by: Mapped[str] = mapped_column(String)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String)
    decided_by: Mapped[str | None] = mapped_column(String, nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AgentTaskRow(Base):
    __tablename__ = "agent_tasks"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    agent: Mapped[str] = mapped_column(String)
    mode: Mapped[str] = mapped_column(String)
    task_type: Mapped[str] = mapped_column(String)
    input_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    requested_by: Mapped[str] = mapped_column(String)
    idempotency_key: Mapped[str] = mapped_column(String, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ObservationRow(Base):
    __tablename__ = "market_observations"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    source: Mapped[str] = mapped_column(String)
    market: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String)
    metric: Mapped[str] = mapped_column(String)
    value_decimal: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_ref: Mapped[str] = mapped_column(String)
    confidence_decimal: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    dimensions_json: Mapped[dict[str, str]] = mapped_column(JSON)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OpportunityRow(Base):
    __tablename__ = "opportunities"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    market: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    score_decimal: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    rationale_json: Mapped[list[str]] = mapped_column(JSON)
    evidence_ids_json: Mapped[list[str]] = mapped_column(JSON)
    recommended_action: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ContentAssetRow(Base):
    __tablename__ = "content_assets"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"))
    content_type: Mapped[str] = mapped_column(String)
    locale: Mapped[str] = mapped_column(String)
    channel: Mapped[str] = mapped_column(String)
    brief_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    source_facts_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String)
    artifact_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    qa_results_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ExperimentRow(Base):
    __tablename__ = "growth_experiments"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"))
    channel: Mapped[str] = mapped_column(String)
    hypothesis: Mapped[str] = mapped_column(Text)
    primary_metric: Mapped[str] = mapped_column(String)
    budget_cap_cny_decimal: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    stop_loss_cny_decimal: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    variants_json: Mapped[list[str]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EventRow(Base):
    __tablename__ = "outbox_events"
    sequence: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String)
    aggregate_id: Mapped[str] = mapped_column(String)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _iso(value: datetime) -> str:
    return value.isoformat()


class SqlAlchemyRepository:
    """PostgreSQL adapter for the stable domain repository contract."""

    def __init__(self, engine=None) -> None:
        self.engine = engine or create_database_engine()

    def add_product(self, product: Product) -> Product:
        row = ProductRow(
            id=product.id,
            sku=product.sku,
            name=product.name,
            market=product.market,
            channel=product.channel,
            status=product.status.value,
            created_at=_dt(product.created_at),
        )
        try:
            with Session(self.engine) as session, session.begin():
                session.add(row)
        except IntegrityError as exc:
            raise ValueError(f"SKU already exists: {product.sku}") from exc
        return product

    def get_product(self, product_id: str) -> Product:
        with Session(self.engine) as session:
            row = session.get(ProductRow, product_id)
            if row is None:
                raise KeyError(f"Unknown product: {product_id}")
            return Product(
                row.sku, row.name, row.market, row.channel, ProductStatus(row.status), row.id, _iso(row.created_at)
            )

    def list_products(self) -> list[Product]:
        with Session(self.engine) as session:
            rows = session.scalars(select(ProductRow).order_by(ProductRow.created_at, ProductRow.id)).all()
        return [
            Product(row.sku, row.name, row.market, row.channel, ProductStatus(row.status), row.id, _iso(row.created_at))
            for row in rows
        ]

    def save_product(self, product: Product) -> Product:
        with Session(self.engine) as session, session.begin():
            row = session.get(ProductRow, product.id)
            if row is None:
                raise KeyError(f"Unknown product: {product.id}")
            row.status = product.status.value
            row.name = product.name
        return product

    def add_passport(self, passport: Passport) -> Passport:
        with Session(self.engine) as session, session.begin():
            session.add(
                PassportRow(
                    id=passport.id,
                    product_id=passport.product_id,
                    kind=passport.kind.value,
                    version=passport.version,
                    facts_json=passport.facts,
                    evidence_json=passport.evidence,
                    approved_by=passport.approved_by,
                    created_at=_dt(passport.created_at),
                )
            )
        return passport

    def latest_passports(self, product_id: str) -> dict[PassportType, Passport]:
        with Session(self.engine) as session:
            rows = session.scalars(
                select(PassportRow).where(PassportRow.product_id == product_id).order_by(PassportRow.version)
            ).all()
        result: dict[PassportType, Passport] = {}
        for row in rows:
            kind = PassportType(row.kind)
            result[kind] = Passport(
                row.product_id,
                kind,
                row.version,
                row.facts_json,
                row.evidence_json,
                row.approved_by,
                row.id,
                _iso(row.created_at),
            )
        return result

    def add_order(self, order: Order) -> Order:
        try:
            with Session(self.engine) as session, session.begin():
                session.add(
                    OrderRow(
                        id=order.id,
                        external_id=order.external_id,
                        product_id=order.product_id,
                        quantity=order.quantity,
                        currency=order.currency,
                        gross_revenue_decimal=order.gross_revenue,
                        booked_fx_rate_decimal=order.booked_fx_rate,
                        status=order.status.value,
                        created_at=_dt(order.created_at),
                    )
                )
        except IntegrityError as exc:
            raise ValueError(f"External order already exists: {order.external_id}") from exc
        return order

    def get_order(self, order_id: str) -> Order:
        with Session(self.engine) as session:
            row = session.get(OrderRow, order_id)
            if row is None:
                raise KeyError(f"Unknown order: {order_id}")
            return Order(
                row.external_id,
                row.product_id,
                row.quantity,
                row.currency,
                row.gross_revenue_decimal,
                row.booked_fx_rate_decimal,
                OrderStatus(row.status),
                row.id,
                _iso(row.created_at),
            )

    def add_charge(self, charge: Charge) -> Charge:
        with Session(self.engine) as session, session.begin():
            session.add(
                ChargeRow(
                    id=charge.id,
                    order_id=charge.order_id,
                    kind=charge.kind.value,
                    amount_decimal=charge.amount,
                    currency=charge.currency,
                    fx_rate_decimal=charge.fx_rate,
                    evidence_ref=charge.evidence_ref,
                    created_at=_dt(charge.created_at),
                )
            )
        return charge

    def charges_for_order(self, order_id: str) -> list[Charge]:
        with Session(self.engine) as session:
            rows = session.scalars(select(ChargeRow).where(ChargeRow.order_id == order_id)).all()
        return [
            Charge(
                row.order_id,
                ChargeType(row.kind),
                row.amount_decimal,
                row.currency,
                row.fx_rate_decimal,
                row.evidence_ref,
                row.id,
                _iso(row.created_at),
            )
            for row in rows
        ]

    def add_approval(self, approval: Approval) -> Approval:
        with Session(self.engine) as session, session.begin():
            session.add(
                ApprovalRow(
                    id=approval.id,
                    action=approval.action,
                    resource_type=approval.resource_type,
                    resource_id=approval.resource_id,
                    requested_by=approval.requested_by,
                    payload_json=approval.payload,
                    status=approval.status.value,
                    decided_by=approval.decided_by,
                    decision_reason=approval.decision_reason,
                    created_at=_dt(approval.created_at),
                )
            )
        return approval

    def get_approval(self, approval_id: str) -> Approval:
        with Session(self.engine) as session:
            row = session.get(ApprovalRow, approval_id)
            if row is None:
                raise KeyError(f"Unknown approval: {approval_id}")
            return Approval(
                row.action,
                row.resource_type,
                row.resource_id,
                row.requested_by,
                row.payload_json,
                ApprovalStatus(row.status),
                row.decided_by,
                row.decision_reason,
                row.id,
                _iso(row.created_at),
            )

    def list_approvals(self) -> list[Approval]:
        with Session(self.engine) as session:
            rows = session.scalars(select(ApprovalRow).order_by(ApprovalRow.created_at.desc())).all()
        return [
            Approval(
                row.action,
                row.resource_type,
                row.resource_id,
                row.requested_by,
                row.payload_json,
                ApprovalStatus(row.status),
                row.decided_by,
                row.decision_reason,
                row.id,
                _iso(row.created_at),
            )
            for row in rows
        ]

    def save_approval(self, approval: Approval) -> Approval:
        with Session(self.engine) as session, session.begin():
            row = session.get(ApprovalRow, approval.id)
            if row is None:
                raise KeyError(f"Unknown approval: {approval.id}")
            row.status = approval.status.value
            row.decided_by = approval.decided_by
            row.decision_reason = approval.decision_reason
        return approval

    def add_agent_task(self, task: AgentTask) -> AgentTask:
        with Session(self.engine) as session, session.begin():
            existing = session.scalar(select(AgentTaskRow).where(AgentTaskRow.idempotency_key == task.idempotency_key))
            if existing:
                return self._agent(existing)
            session.add(
                AgentTaskRow(
                    id=task.id,
                    agent=task.agent,
                    mode=task.mode.value,
                    task_type=task.task_type,
                    input_json=task.input_data,
                    requested_by=task.requested_by,
                    idempotency_key=task.idempotency_key,
                    created_at=_dt(task.created_at),
                )
            )
        return task

    @staticmethod
    def _agent(row: AgentTaskRow) -> AgentTask:
        return AgentTask(
            row.agent,
            AgentMode(row.mode),
            row.task_type,
            row.input_json,
            row.requested_by,
            row.idempotency_key,
            row.id,
            _iso(row.created_at),
        )

    def append_event(self, event_type: str, aggregate_id: str, payload: dict) -> None:
        with Session(self.engine) as session, session.begin():
            session.add(
                EventRow(
                    event_type=event_type,
                    aggregate_id=aggregate_id,
                    payload_json=payload,
                    occurred_at=_dt(utc_now()),
                    published_at=None,
                )
            )

    def event_count(self) -> int:
        with Session(self.engine) as session:
            return int(session.scalar(select(func.count()).select_from(EventRow)) or 0)

    def events_after(self, sequence: int) -> list[dict]:
        with Session(self.engine) as session:
            rows = session.scalars(
                select(EventRow).where(EventRow.sequence > sequence).order_by(EventRow.sequence)
            ).all()
        return [
            {
                "sequence": row.sequence,
                "type": row.event_type,
                "aggregate_id": row.aggregate_id,
                "payload": row.payload_json,
            }
            for row in rows
        ]

    def add_observation(self, observation: MarketObservation) -> MarketObservation:
        with Session(self.engine) as session, session.begin():
            session.add(
                ObservationRow(
                    id=observation.id,
                    source=observation.source,
                    market=observation.market,
                    category=observation.category,
                    metric=observation.metric,
                    value_decimal=observation.value,
                    observed_at=_dt(observation.observed_at),
                    source_ref=observation.source_ref,
                    confidence_decimal=observation.confidence,
                    dimensions_json=observation.dimensions,
                    ingested_at=_dt(observation.ingested_at),
                )
            )
        return observation

    def observations_for(self, market: str, category: str, metric: str | None = None) -> list[MarketObservation]:
        query = select(ObservationRow).where(ObservationRow.market == market, ObservationRow.category == category)
        if metric is not None:
            query = query.where(ObservationRow.metric == metric)
        with Session(self.engine) as session:
            rows = session.scalars(query).all()
        return [
            MarketObservation(
                row.source,
                row.market,
                row.category,
                row.metric,
                row.value_decimal,
                _iso(row.observed_at),
                row.source_ref,
                row.confidence_decimal,
                row.dimensions_json,
                row.id,
                _iso(row.ingested_at),
            )
            for row in rows
        ]

    def add_opportunity(self, opportunity: OpportunityInsight) -> OpportunityInsight:
        with Session(self.engine) as session, session.begin():
            session.add(
                OpportunityRow(
                    id=opportunity.id,
                    market=opportunity.market,
                    category=opportunity.category,
                    title=opportunity.title,
                    score_decimal=opportunity.score,
                    rationale_json=opportunity.rationale,
                    evidence_ids_json=opportunity.evidence_ids,
                    recommended_action=opportunity.recommended_action,
                    created_at=_dt(opportunity.created_at),
                )
            )
        return opportunity

    def add_content_asset(self, asset: ContentAsset) -> ContentAsset:
        with Session(self.engine) as session, session.begin():
            session.add(
                ContentAssetRow(
                    id=asset.id,
                    product_id=asset.product_id,
                    content_type=asset.content_type.value,
                    locale=asset.locale,
                    channel=asset.channel,
                    brief_json=asset.brief,
                    source_facts_json=asset.source_facts,
                    status=asset.status.value,
                    artifact_ref=asset.artifact_ref,
                    qa_results_json=asset.qa_results,
                    created_at=_dt(asset.created_at),
                )
            )
        return asset

    def get_content_asset(self, asset_id: str) -> ContentAsset:
        with Session(self.engine) as session:
            row = session.get(ContentAssetRow, asset_id)
            if row is None:
                raise KeyError(f"Unknown content asset: {asset_id}")
            return self._asset(row)

    @staticmethod
    def _asset(row: ContentAssetRow) -> ContentAsset:
        return ContentAsset(
            row.product_id,
            ContentType(row.content_type),
            row.locale,
            row.channel,
            row.brief_json,
            row.source_facts_json,
            ContentStatus(row.status),
            row.artifact_ref,
            row.qa_results_json,
            row.id,
            _iso(row.created_at),
        )

    def save_content_asset(self, asset: ContentAsset) -> ContentAsset:
        with Session(self.engine) as session, session.begin():
            row = session.get(ContentAssetRow, asset.id)
            if row is None:
                raise KeyError(f"Unknown content asset: {asset.id}")
            row.status = asset.status.value
            row.artifact_ref = asset.artifact_ref
            row.qa_results_json = asset.qa_results
        return asset

    def content_assets_for_product(self, product_id: str) -> list[ContentAsset]:
        with Session(self.engine) as session:
            rows = session.scalars(select(ContentAssetRow).where(ContentAssetRow.product_id == product_id)).all()
            return [self._asset(row) for row in rows]

    def add_experiment(self, experiment: GrowthExperiment) -> GrowthExperiment:
        with Session(self.engine) as session, session.begin():
            session.add(
                ExperimentRow(
                    id=experiment.id,
                    product_id=experiment.product_id,
                    channel=experiment.channel,
                    hypothesis=experiment.hypothesis,
                    primary_metric=experiment.primary_metric,
                    budget_cap_cny_decimal=experiment.budget_cap_cny,
                    stop_loss_cny_decimal=experiment.stop_loss_cny,
                    variants_json=experiment.variants,
                    status=experiment.status.value,
                    created_at=_dt(experiment.created_at),
                )
            )
        return experiment

    def get_experiment(self, experiment_id: str) -> GrowthExperiment:
        with Session(self.engine) as session:
            row = session.get(ExperimentRow, experiment_id)
            if row is None:
                raise KeyError(f"Unknown experiment: {experiment_id}")
            return self._experiment(row)

    @staticmethod
    def _experiment(row: ExperimentRow) -> GrowthExperiment:
        return GrowthExperiment(
            row.product_id,
            row.channel,
            row.hypothesis,
            row.primary_metric,
            row.budget_cap_cny_decimal,
            row.stop_loss_cny_decimal,
            row.variants_json,
            ExperimentStatus(row.status),
            row.id,
            _iso(row.created_at),
        )

    def save_experiment(self, experiment: GrowthExperiment) -> GrowthExperiment:
        with Session(self.engine) as session, session.begin():
            row = session.get(ExperimentRow, experiment.id)
            if row is None:
                raise KeyError(f"Unknown experiment: {experiment.id}")
            row.status = experiment.status.value
        return experiment
