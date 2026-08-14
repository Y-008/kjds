from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    select,
    text,
)
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
    new_id,
    utc_now,
)


class Base(DeclarativeBase):
    pass


class ProductRow(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint(
            "("
            "tenant_ref IS NULL AND entity_ref IS NULL AND store_ref IS NULL "
            "AND scope_grant_authority_sha256 IS NULL AND scope_as_of IS NULL "
            "AND created_by IS NULL"
            ") OR ("
            "tenant_ref IS NOT NULL AND length(tenant_ref) > 0 "
            "AND entity_ref IS NOT NULL AND length(entity_ref) > 0 "
            "AND store_ref IS NOT NULL AND length(store_ref) > 0 "
            "AND scope_grant_authority_sha256 IS NOT NULL "
            "AND length(scope_grant_authority_sha256) = 64 "
            "AND scope_as_of IS NOT NULL "
            "AND created_by IS NOT NULL AND length(created_by) > 0"
            ")",
            name="ck_product_scope_complete",
        ),
        Index(
            "uq_product_legacy_sku",
            "sku",
            unique=True,
            postgresql_where=text("tenant_ref IS NULL"),
            sqlite_where=text("tenant_ref IS NULL"),
        ),
        Index(
            "uq_product_scoped_sku",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "sku",
            unique=True,
            postgresql_where=text("tenant_ref IS NOT NULL"),
            sqlite_where=text("tenant_ref IS NOT NULL"),
        ),
        Index(
            "ix_product_scope_created",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "created_at",
        ),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    sku: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    market: Mapped[str] = mapped_column(String)
    channel: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    tenant_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    entity_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    store_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    scope_grant_authority_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    scope_as_of: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[str | None] = mapped_column(String(160), nullable=True)


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
    generation_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
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
    sequence: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    event_id: Mapped[str] = mapped_column(String, unique=True)
    event_type: Mapped[str] = mapped_column(String)
    aggregate_id: Mapped[str] = mapped_column(String)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    payload_hash: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actor_id: Mapped[str] = mapped_column(String)
    source_evidence_id: Mapped[str | None] = mapped_column(String, nullable=True)
    schema_version: Mapped[str] = mapped_column(String)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    claimed_by: Mapped[str | None] = mapped_column(String, nullable=True)
    claimed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _iso(value: datetime) -> str:
    return value.isoformat()


def _payload_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def add_outbox_event(
    session: Session,
    event_type: str,
    aggregate_id: str,
    payload: dict[str, Any],
    *,
    actor_id: str = "system",
    source_evidence_id: str | None = None,
) -> EventRow:
    """Stage an outbox event in the caller's business transaction."""
    now = _dt(utc_now())
    row = EventRow(
        event_id=new_id("evt"),
        event_type=event_type,
        aggregate_id=aggregate_id,
        payload_json=payload,
        payload_hash=_payload_hash(payload),
        occurred_at=now,
        recorded_at=now,
        actor_id=actor_id,
        source_evidence_id=source_evidence_id,
        schema_version="v1",
        attempt_count=0,
        available_at=now,
        claimed_by=None,
        claimed_until=None,
        last_error=None,
        published_at=None,
    )
    session.add(row)
    return row


class SqlAlchemyRepository:
    """PostgreSQL adapter for the stable domain repository contract."""

    def __init__(self, engine=None) -> None:
        self.engine = engine or create_database_engine()
        self._active_session: ContextVar[Session | None] = ContextVar(
            f"kjds_repository_session_{id(self)}", default=None
        )

    @contextmanager
    def transaction(self) -> Iterator[SqlAlchemyRepository]:
        if self._active_session.get() is not None:
            yield self
            return
        with Session(self.engine) as session, session.begin():
            token = self._active_session.set(session)
            try:
                yield self
            finally:
                self._active_session.reset(token)

    @contextmanager
    def _session(self, *, write: bool = False) -> Iterator[Session]:
        active = self._active_session.get()
        if active is not None:
            yield active
            return
        with Session(self.engine) as session:
            if write:
                with session.begin():
                    yield session
            else:
                yield session

    def add_product(self, product: Product) -> Product:
        row = ProductRow(
            id=product.id,
            sku=product.sku,
            name=product.name,
            market=product.market,
            channel=product.channel,
            status=product.status.value,
            created_at=_dt(product.created_at),
            tenant_ref=product.tenant_ref,
            entity_ref=product.entity_ref,
            store_ref=product.store_ref,
            scope_grant_authority_sha256=product.scope_grant_authority_sha256,
            scope_as_of=(
                _dt(product.scope_as_of) if product.scope_as_of else None
            ),
            created_by=product.created_by,
        )
        try:
            with self._session(write=True) as session:
                session.add(row)
                session.flush()
        except IntegrityError as exc:
            raise ValueError(f"SKU already exists: {product.sku}") from exc
        return product

    def get_product(self, product_id: str) -> Product:
        with self._session() as session:
            row = session.get(ProductRow, product_id)
            if row is None:
                raise KeyError(f"Unknown product: {product_id}")
            return self._product(row)

    @staticmethod
    def _product(row: ProductRow) -> Product:
        return Product(
            sku=row.sku,
            name=row.name,
            market=row.market,
            channel=row.channel,
            status=ProductStatus(row.status),
            id=row.id,
            created_at=_iso(row.created_at),
            tenant_ref=row.tenant_ref,
            entity_ref=row.entity_ref,
            store_ref=row.store_ref,
            scope_grant_authority_sha256=(
                row.scope_grant_authority_sha256
            ),
            scope_as_of=(
                _iso(row.scope_as_of) if row.scope_as_of else None
            ),
            created_by=row.created_by,
        )

    def list_products(self) -> list[Product]:
        with self._session() as session:
            rows = session.scalars(select(ProductRow).order_by(ProductRow.created_at, ProductRow.id)).all()
        return [self._product(row) for row in rows]

    def get_product_scoped(
        self,
        *,
        product_id: str,
        tenant_ref: str,
        entity_ref: str,
        store_ref: str,
        as_of: datetime,
    ) -> Product:
        with self._session() as session:
            row = session.scalar(
                select(ProductRow).where(
                    ProductRow.id == product_id,
                    ProductRow.tenant_ref == tenant_ref,
                    ProductRow.entity_ref == entity_ref,
                    ProductRow.store_ref == store_ref,
                    ProductRow.created_at <= as_of,
                    ProductRow.scope_as_of <= as_of,
                )
            )
        if row is None:
            raise KeyError("Unknown product in authorized operating scope")
        return self._product(row)

    def list_products_scoped(
        self,
        *,
        tenant_ref: str,
        entity_ref: str,
        store_ref: str,
        as_of: datetime,
    ) -> list[Product]:
        with self._session() as session:
            rows = session.scalars(
                select(ProductRow)
                .where(
                    ProductRow.tenant_ref == tenant_ref,
                    ProductRow.entity_ref == entity_ref,
                    ProductRow.store_ref == store_ref,
                    ProductRow.created_at <= as_of,
                    ProductRow.scope_as_of <= as_of,
                )
                .order_by(ProductRow.created_at, ProductRow.id)
            ).all()
        return [self._product(row) for row in rows]

    def save_product(self, product: Product) -> Product:
        with self._session(write=True) as session:
            row = session.get(ProductRow, product.id)
            if row is None:
                raise KeyError(f"Unknown product: {product.id}")
            row.status = product.status.value
            row.name = product.name
        return product

    def add_passport(self, passport: Passport) -> Passport:
        with self._session(write=True) as session:
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

    def latest_passports(
        self,
        product_id: str,
        *,
        as_of: datetime | None = None,
    ) -> dict[PassportType, Passport]:
        with self._session() as session:
            query = select(PassportRow).where(
                PassportRow.product_id == product_id
            )
            if as_of is not None:
                query = query.where(PassportRow.created_at <= as_of)
            rows = session.scalars(query.order_by(PassportRow.version)).all()
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
            with self._session(write=True) as session:
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
                session.flush()
        except IntegrityError as exc:
            raise ValueError(f"External order already exists: {order.external_id}") from exc
        return order

    def get_order(self, order_id: str) -> Order:
        with self._session() as session:
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
        with self._session(write=True) as session:
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
        with self._session() as session:
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
        with self._session(write=True) as session:
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
        with self._session() as session:
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

    def get_approval_at(
        self,
        approval_id: str,
        *,
        as_of: datetime,
    ) -> Approval:
        if as_of.tzinfo is None:
            raise ValueError("as_of must include a timezone")
        cutoff = as_of.astimezone(UTC)
        with self._session() as session:
            row = session.get(ApprovalRow, approval_id)
            created_at = (
                row.created_at.replace(tzinfo=UTC)
                if row is not None
                and row.created_at.tzinfo is None
                else row.created_at
                if row is not None
                else None
            )
            if row is None or created_at is None or created_at > cutoff:
                raise KeyError(
                    f"Unknown approval at requested cutoff: {approval_id}"
                )
            decision = session.scalar(
                select(EventRow)
                .where(
                    EventRow.event_type == "approval.decided",
                    EventRow.aggregate_id == approval_id,
                    EventRow.occurred_at <= cutoff,
                    EventRow.recorded_at <= cutoff,
                )
                .order_by(
                    EventRow.occurred_at.desc(),
                    EventRow.recorded_at.desc(),
                    EventRow.sequence.desc(),
                )
            )
            decided_at_cutoff = decision is not None
            status = (
                ApprovalStatus(row.status)
                if decided_at_cutoff
                else ApprovalStatus.PENDING
            )
            decided_by = row.decided_by if decided_at_cutoff else None
            decision_reason = (
                row.decision_reason if decided_at_cutoff else None
            )
            return Approval(
                row.action,
                row.resource_type,
                row.resource_id,
                row.requested_by,
                row.payload_json,
                status,
                decided_by,
                decision_reason,
                row.id,
                _iso(row.created_at),
            )

    def list_approvals(self) -> list[Approval]:
        with self._session() as session:
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
        with self._session(write=True) as session:
            row = session.get(ApprovalRow, approval.id)
            if row is None:
                raise KeyError(f"Unknown approval: {approval.id}")
            row.status = approval.status.value
            row.decided_by = approval.decided_by
            row.decision_reason = approval.decision_reason
        return approval

    def add_agent_task(self, task: AgentTask) -> AgentTask:
        with self._session(write=True) as session:
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

    def append_event(
        self,
        event_type: str,
        aggregate_id: str,
        payload: dict,
        *,
        actor_id: str = "system",
        source_evidence_id: str | None = None,
    ) -> None:
        with self._session(write=True) as session:
            add_outbox_event(
                session,
                event_type,
                aggregate_id,
                payload,
                actor_id=actor_id,
                source_evidence_id=source_evidence_id,
            )

    def event_count(self) -> int:
        with self._session() as session:
            return int(session.scalar(select(func.count()).select_from(EventRow)) or 0)

    def events_after(self, sequence: int) -> list[dict]:
        with self._session() as session:
            rows = session.scalars(
                select(EventRow).where(EventRow.sequence > sequence).order_by(EventRow.sequence)
            ).all()
        return [
            {
                "sequence": row.sequence,
                "event_id": row.event_id,
                "type": row.event_type,
                "aggregate_id": row.aggregate_id,
                "payload": row.payload_json,
                "payload_hash": row.payload_hash,
                "occurred_at": _iso(row.occurred_at),
                "recorded_at": _iso(row.recorded_at),
                "actor_id": row.actor_id,
                "source_evidence_id": row.source_evidence_id,
                "schema_version": row.schema_version,
                "attempt_count": row.attempt_count,
                "published_at": _iso(row.published_at) if row.published_at else None,
            }
            for row in rows
        ]

    def add_observation(self, observation: MarketObservation) -> MarketObservation:
        with self._session(write=True) as session:
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
        with self._session() as session:
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
        with self._session(write=True) as session:
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
        with self._session(write=True) as session:
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
                    generation_json=asset.generation,
                    created_at=_dt(asset.created_at),
                )
            )
        return asset

    def get_content_asset(self, asset_id: str) -> ContentAsset:
        with self._session() as session:
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
            row.generation_json,
            row.id,
            _iso(row.created_at),
        )

    def save_content_asset(self, asset: ContentAsset) -> ContentAsset:
        with self._session(write=True) as session:
            row = session.get(ContentAssetRow, asset.id)
            if row is None:
                raise KeyError(f"Unknown content asset: {asset.id}")
            row.status = asset.status.value
            row.artifact_ref = asset.artifact_ref
            row.qa_results_json = asset.qa_results
            row.generation_json = asset.generation
        return asset

    def content_assets_for_product(
        self,
        product_id: str,
        *,
        as_of: datetime | None = None,
    ) -> list[ContentAsset]:
        with self._session() as session:
            query = select(ContentAssetRow).where(
                ContentAssetRow.product_id == product_id
            )
            if as_of is not None:
                query = query.where(ContentAssetRow.created_at <= as_of)
            rows = session.scalars(
                query.order_by(ContentAssetRow.created_at, ContentAssetRow.id)
            ).all()
            return [self._asset(row) for row in rows]

    def get_content_asset_scoped(
        self,
        *,
        asset_id: str,
        tenant_ref: str,
        entity_ref: str,
        store_ref: str,
        as_of: datetime,
    ) -> ContentAsset:
        with self._session() as session:
            row = session.scalar(
                select(ContentAssetRow)
                .join(ProductRow, ProductRow.id == ContentAssetRow.product_id)
                .where(
                    ContentAssetRow.id == asset_id,
                    ContentAssetRow.created_at <= as_of,
                    ProductRow.tenant_ref == tenant_ref,
                    ProductRow.entity_ref == entity_ref,
                    ProductRow.store_ref == store_ref,
                    ProductRow.created_at <= as_of,
                    ProductRow.scope_as_of <= as_of,
                )
            )
        if row is None:
            raise KeyError(
                "Unknown content asset in authorized operating scope"
            )
        return self._asset(row)

    def get_content_asset_for_products(
        self,
        *,
        asset_id: str,
        product_ids: list[str],
        as_of: datetime,
    ) -> ContentAsset:
        normalized = sorted(
            {item.strip() for item in product_ids if item.strip()}
        )
        if not normalized:
            raise KeyError(
                "Unknown content asset in authorized operating scope"
            )
        with self._session() as session:
            row = session.scalar(
                select(ContentAssetRow).where(
                    ContentAssetRow.id == asset_id,
                    ContentAssetRow.product_id.in_(normalized),
                    ContentAssetRow.created_at <= as_of,
                )
            )
        if row is None:
            raise KeyError(
                "Unknown content asset in authorized operating scope"
            )
        return self._asset(row)

    def add_experiment(self, experiment: GrowthExperiment) -> GrowthExperiment:
        with self._session(write=True) as session:
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
        with self._session() as session:
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
        with self._session(write=True) as session:
            row = session.get(ExperimentRow, experiment.id)
            if row is None:
                raise KeyError(f"Unknown experiment: {experiment.id}")
            row.status = experiment.status.value
        return experiment
