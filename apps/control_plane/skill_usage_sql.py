"""Durable SQL adapter for the AI skill and generated-media usage ledger.

The in-process :class:`~apps.control_plane.skill_usage_ledger.SkillUsageLedger`
is useful for isolated contract tests, but a commercial usage event must survive
process restarts and concurrent workers.  This adapter keeps the same small
interface while making the event append-only and tenant-scoped in SQL.

Schema ownership stays with Alembic migrations.  ``for_url`` is intentionally a
test/development convenience; runtime composition only receives an existing
engine and never creates tables implicitly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    create_engine,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from .skill_usage_ledger import SkillUsageEvent, _usage_fingerprint
from .sql_repository import Base


class SkillUsageEventRow(Base):
    """Append-only commercial usage event row.

    ``event_id`` is globally unique so an external receipt can unambiguously
    refer to one event.  Idempotency keys are scoped by tenant, which permits
    independent customers to use the same request key without leaking or
    replaying another tenant's event.
    """

    __tablename__ = "skill_usage_events"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_skill_usage_tenant_idempotency",
        ),
        CheckConstraint("units >= 0", name="ck_skill_usage_units_nonnegative"),
        CheckConstraint(
            "unit_cost >= 0", name="ck_skill_usage_unit_cost_nonnegative"
        ),
        CheckConstraint(
            "length(currency) = 3", name="ck_skill_usage_currency_shape"
        ),
        CheckConstraint(
            "input_units IS NULL OR input_units >= 0",
            name="ck_skill_usage_input_units_nonnegative",
        ),
        CheckConstraint(
            "output_units IS NULL OR output_units >= 0",
            name="ck_skill_usage_output_units_nonnegative",
        ),
        Index(
            "ix_skill_usage_scope_occurred",
            "tenant_id",
            "customer_id",
            "occurred_at",
            "event_id",
        ),
        Index(
            "ix_skill_usage_skill_occurred",
            "tenant_id",
            "skill_id",
            "occurred_at",
        ),
    )

    event_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(300), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(160), nullable=False)
    customer_id: Mapped[str] = mapped_column(String(200), nullable=False)
    skill_id: Mapped[str] = mapped_column(String(200), nullable=False)
    units: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    # Numeric columns support bounded SQL reporting; text mirrors retain the
    # original Decimal exponent so invoice previews remain byte-for-byte
    # reproducible (``2 * 0.25`` must render as ``0.50``, not a DB-scale value).
    units_text: Mapped[str] = mapped_column(String(100), nullable=False)
    unit_cost_text: Mapped[str] = mapped_column(String(100), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    asset_ref: Mapped[str | None] = mapped_column(String(300), nullable=True)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False, default="skill")
    provider_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    model_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cost_center: Mapped[str | None] = mapped_column(String(160), nullable=True)
    input_units: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    output_units: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    fingerprint_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


def _aware(value: datetime) -> datetime:
    """Normalize database timestamps (SQLite drops timezone metadata)."""

    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _event_from_row(row: SkillUsageEventRow) -> SkillUsageEvent:
    return SkillUsageEvent(
        event_id=row.event_id,
        idempotency_key=row.idempotency_key,
        tenant_id=row.tenant_id,
        customer_id=row.customer_id,
        skill_id=row.skill_id,
        units=Decimal(row.units_text) if row.units_text else Decimal(str(row.units)),
        unit_cost=(
            Decimal(row.unit_cost_text)
            if row.unit_cost_text
            else Decimal(str(row.unit_cost))
        ),
        currency=row.currency,
        occurred_at=_aware(row.occurred_at),
        asset_ref=row.asset_ref,
        resource_type=row.resource_type or "skill",
        provider_ref=row.provider_ref,
        model_ref=row.model_ref,
        cost_center=row.cost_center,
        input_units=Decimal(str(row.input_units)) if row.input_units is not None else None,
        output_units=Decimal(str(row.output_units)) if row.output_units is not None else None,
    )


class SqlSkillUsageLedger:
    """Append-only SQL implementation of ``SkillUsageLedger``'s read contract."""

    def __init__(self, engine: Engine):
        self.engine = engine

    @classmethod
    def for_url(cls, url: str) -> SqlSkillUsageLedger:
        """Build a store and create only its table for local tests.

        Production migrations remain the sole schema authority; callers using
        ``build_runtime`` should construct the class directly with an engine.
        """

        engine = create_engine(url, future=True)
        Base.metadata.create_all(engine, tables=[SkillUsageEventRow.__table__])
        return cls(engine)

    @staticmethod
    def _validate(event: SkillUsageEvent) -> None:
        if event.units < 0 or event.unit_cost < 0:
            raise ValueError("usage units and unit_cost must be non-negative")
        if len(event.currency) != 3:
            raise ValueError("currency must be a three-letter code")
        if not event.resource_type.strip() or len(event.resource_type) > 80:
            raise ValueError("resource_type is required and must be <= 80 characters")
        for name, amount in (("input_units", event.input_units), ("output_units", event.output_units)):
            if amount is not None and amount < 0:
                raise ValueError(f"{name} cannot be negative")

    @staticmethod
    def _by_idempotency(session: Session, event: SkillUsageEvent) -> SkillUsageEventRow | None:
        return session.scalar(
            select(SkillUsageEventRow).where(
                SkillUsageEventRow.tenant_id == event.tenant_id,
                SkillUsageEventRow.idempotency_key == event.idempotency_key,
            )
        )

    @staticmethod
    def _resolve_existing(
        row: SkillUsageEventRow,
        fingerprint: str,
    ) -> SkillUsageEvent:
        existing = _event_from_row(row)
        if (
            row.fingerprint_sha256 != fingerprint
            or _usage_fingerprint(existing) != row.fingerprint_sha256
        ):
            raise ValueError("usage idempotency key conflicts with immutable event")
        return existing

    def record(self, event: SkillUsageEvent) -> SkillUsageEvent:
        """Insert one event, returning the idempotent winner on retries.

        The unique tenant/key constraint is the final arbiter under concurrent
        workers.  If a race wins after the initial lookup, a fresh read returns
        the winner and still compares its immutable fingerprint.
        """

        self._validate(event)
        fingerprint = _usage_fingerprint(event)
        occurred_at = _aware(event.occurred_at)
        try:
            with Session(self.engine) as session, session.begin():
                existing = self._by_idempotency(session, event)
                if existing is not None:
                    return self._resolve_existing(existing, fingerprint)
                by_id = session.get(SkillUsageEventRow, event.event_id)
                if by_id is not None:
                    raise ValueError("event_id already exists")
                row = SkillUsageEventRow(
                    event_id=event.event_id,
                    idempotency_key=event.idempotency_key,
                    tenant_id=event.tenant_id,
                    customer_id=event.customer_id,
                    skill_id=event.skill_id,
                    units=event.units,
                    unit_cost=event.unit_cost,
                    units_text=str(event.units),
                    unit_cost_text=str(event.unit_cost),
                    currency=event.currency,
                    occurred_at=occurred_at,
                    asset_ref=event.asset_ref,
                    resource_type=event.resource_type,
                    provider_ref=event.provider_ref,
                    model_ref=event.model_ref,
                    cost_center=event.cost_center,
                    input_units=event.input_units,
                    output_units=event.output_units,
                    fingerprint_sha256=fingerprint,
                    recorded_at=datetime.now(UTC),
                )
                session.add(row)
                session.flush()
                return _event_from_row(row)
        except IntegrityError as exc:
            # A concurrent worker may have won either unique constraint.  Read
            # in a new transaction before deciding whether this is an ordinary
            # idempotent retry or an event-id collision.
            with Session(self.engine) as session:
                winner = session.scalar(
                    select(SkillUsageEventRow).where(
                        SkillUsageEventRow.tenant_id == event.tenant_id,
                        SkillUsageEventRow.idempotency_key == event.idempotency_key,
                    )
                )
                if winner is not None:
                    return self._resolve_existing(winner, fingerprint)
                by_id = session.get(SkillUsageEventRow, event.event_id)
                if by_id is not None:
                    raise ValueError("event_id already exists") from exc
            raise

    def get(self, event_id: str) -> SkillUsageEvent:
        with Session(self.engine) as session:
            row = session.get(SkillUsageEventRow, event_id)
            if row is None:
                raise KeyError(f"Unknown usage event: {event_id}")
            return _event_from_row(row)

    def events_for(
        self, *, tenant_id: str, customer_id: str | None = None
    ) -> tuple[SkillUsageEvent, ...]:
        with Session(self.engine) as session:
            query = select(SkillUsageEventRow).where(
                SkillUsageEventRow.tenant_id == tenant_id
            )
            if customer_id is not None:
                query = query.where(SkillUsageEventRow.customer_id == customer_id)
            rows = session.scalars(
                query.order_by(
                    SkillUsageEventRow.occurred_at, SkillUsageEventRow.event_id
                )
            ).all()
        return tuple(_event_from_row(row) for row in rows)

    def total_cost(
        self,
        *,
        tenant_id: str,
        customer_id: str | None = None,
        currency: str = "USD",
    ) -> Decimal:
        rows = self.events_for(tenant_id=tenant_id, customer_id=customer_id)
        if any(event.currency != currency for event in rows):
            raise ValueError("mixed currencies require an explicit FX snapshot")
        return sum((event.total_cost for event in rows), Decimal("0"))

    def invoice_preview(
        self, *, tenant_id: str, customer_id: str, currency: str = "USD"
    ) -> dict[str, object]:
        rows = self.events_for(tenant_id=tenant_id, customer_id=customer_id)
        total = self.total_cost(
            tenant_id=tenant_id, customer_id=customer_id, currency=currency
        )
        return {
            "tenant_id": tenant_id,
            "customer_id": customer_id,
            "currency": currency,
            "event_count": len(rows),
            "total_cost": str(total),
            "event_ids": [event.event_id for event in rows],
        }


__all__ = ["SkillUsageEventRow", "SqlSkillUsageLedger"]
