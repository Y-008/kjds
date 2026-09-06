"""Bind resource-budget reservations to governed execution commands.

The budget ledger deliberately knows nothing about permits or commands.  This
adapter supplies that missing link: every reservation and settlement is an
append-only admission event carrying the exact tenant, command, action, and
permit references.  A remote result marked ``uncertain`` records a durable
``unknown`` hold and leaves the ledger reservation open until reconciliation.

The adapter does not call a marketplace or any other external system.  It is
safe to use at queue/receipt boundaries and remains provider neutral.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from typing import Any, Literal

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import new_id
from .resource_budget_ledger import (
    ResourceBudgetEvent,
    ResourceBudgetEventRow,
    ResourceBudgetLedger,
    ResourceBudgetRow,
    _amount,
    _currency,
    _text,
)
from .sql_repository import Base

AdmissionState = Literal["reserved", "consumed", "released", "unknown"]
AdmissionOperation = Literal["reserve", "consume", "release", "hold_unknown"]
ADMISSION_STATES = frozenset({"reserved", "consumed", "released", "unknown"})
ADMISSION_OPERATIONS = frozenset({"reserve", "consume", "release", "hold_unknown"})


def _required(value: str, name: str, maximum: int = 300) -> str:
    return _text(value, name, maximum)


def _aware(value: datetime | None) -> datetime:
    value = datetime.now(UTC) if value is None else value
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("occurred_at must include a timezone")
    try:
        normalized = value.astimezone(UTC)
    except OverflowError as exc:
        raise ValueError("occurred_at is outside the supported range") from exc
    if normalized > datetime.now(UTC):
        raise ValueError("occurred_at cannot be in the future")
    return normalized


def _event_id(tenant_id: str, admission_id: str, operation: str) -> str:
    digest = hashlib.sha256(
        f"{tenant_id}\x00{admission_id}\x00{operation}".encode()
    ).hexdigest()
    return f"rad_{digest}"


def _ledger_key(admission_id: str, operation: str) -> str:
    # A deterministic key makes a retry after a worker crash idempotent while
    # remaining comfortably below the ledger's 300-character bound.
    return f"resource-admission:{admission_id}:{operation}"


def _fingerprint(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class ResourceAdmissionEventRow(Base):
    """Immutable lifecycle event linking a budget event to execution scope."""

    __tablename__ = "resource_admission_events"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_resource_admission_tenant_idempotency"
        ),
        UniqueConstraint(
            "tenant_id", "admission_id", "operation", name="uq_resource_admission_operation"
        ),
        UniqueConstraint(
            "tenant_id", "resource_event_id", name="uq_resource_admission_resource_event"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "budget_id"],
            ["resource_budgets.tenant_id", "resource_budgets.budget_id"],
            name="fk_resource_admission_budget",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "budget_id", "resource_event_id"],
            [
                "resource_budget_events.tenant_id",
                "resource_budget_events.budget_id",
                "resource_budget_events.event_id",
            ],
            name="fk_resource_admission_resource_event",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "budget_id", "parent_resource_event_id"],
            [
                "resource_budget_events.tenant_id",
                "resource_budget_events.budget_id",
                "resource_budget_events.event_id",
            ],
            name="fk_resource_admission_parent_resource_event",
        ),
        CheckConstraint(
            "operation IN ('reserve', 'consume', 'release', 'hold_unknown')",
            name="ck_resource_admission_operation",
        ),
        CheckConstraint(
            "status IN ('reserved', 'consumed', 'released', 'unknown')",
            name="ck_resource_admission_status",
        ),
        CheckConstraint("amount >= 0", name="ck_resource_admission_amount_nonnegative"),
        CheckConstraint("length(currency) = 3", name="ck_resource_admission_currency_shape"),
        CheckConstraint(
            "(operation = 'reserve' AND status = 'reserved' AND parent_resource_event_id IS NULL "
            "AND resource_event_id IS NOT NULL) OR "
            "(operation = 'consume' AND status = 'consumed' AND parent_resource_event_id IS NOT NULL "
            "AND resource_event_id IS NOT NULL) OR "
            "(operation = 'release' AND status = 'released' AND parent_resource_event_id IS NOT NULL "
            "AND resource_event_id IS NOT NULL) OR "
            "(operation = 'hold_unknown' AND status = 'unknown' "
            "AND parent_resource_event_id IS NOT NULL AND resource_event_id IS NULL)",
            name="ck_resource_admission_shape",
        ),
        Index(
            "ix_resource_admission_command",
            "tenant_id",
            "command_id",
            "recorded_at",
            "event_id",
        ),
        Index(
            "ix_resource_admission_scope",
            "tenant_id",
            "admission_id",
            "recorded_at",
            "event_id",
        ),
    )

    event_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    admission_id: Mapped[str] = mapped_column(String(200), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(160), nullable=False)
    command_id: Mapped[str] = mapped_column(String(200), nullable=False)
    action_id: Mapped[str] = mapped_column(String(200), nullable=False)
    permit_ref: Mapped[str] = mapped_column(String(300), nullable=False)
    budget_id: Mapped[str] = mapped_column(String(200), nullable=False)
    resource_event_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    parent_resource_event_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    operation: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    amount_text: Mapped[str] = mapped_column(String(100), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(300), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    metadata_json: Mapped[dict[str, str] | None] = mapped_column(JSON, nullable=True)
    fingerprint_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ResourceAdmissionService:
    """Durable reserve/settle bridge for command permits and resource budgets."""

    def __init__(self, engine, *, ledger: ResourceBudgetLedger | None = None) -> None:
        self.engine = engine
        self.ledger = ledger or ResourceBudgetLedger(engine)

    @classmethod
    def for_url(cls, url: str) -> ResourceAdmissionService:
        from sqlalchemy import create_engine

        engine = create_engine(url, future=True)
        Base.metadata.create_all(
            engine,
            tables=[
                # The ledger tables are needed by the service's reserve calls.
                # Importing the classes through the ledger avoids relying on a
                # runtime-wide metadata import side effect.
                ResourceBudgetEventRow.__table__,
                ResourceBudgetRow.__table__,
                ResourceAdmissionEventRow.__table__,
            ],
        )
        return cls(engine)

    @staticmethod
    def _metadata(
        *,
        tenant_id: str,
        admission_id: str,
        command_id: str,
        action_id: str,
        permit_ref: str,
        operation: str,
        metadata: Mapping[str, str] | None,
    ) -> dict[str, str]:
        values: dict[str, str] = {}
        if metadata is not None:
            if not isinstance(metadata, Mapping) or len(metadata) > 40:
                raise ValueError("metadata must be a bounded string mapping")
            for key, value in metadata.items():
                if not isinstance(key, str) or not key or len(key) > 120:
                    raise ValueError("metadata keys must be non-empty bounded strings")
                if not isinstance(value, str) or len(value) > 1000:
                    raise ValueError("metadata values must be bounded strings")
                values[key] = value
        # Server-owned bindings cannot be overridden by caller metadata.
        values.update(
            {
                "admission_id": admission_id,
                "tenant_id": tenant_id,
                "command_id": command_id,
                "action_id": action_id,
                "permit_ref": permit_ref,
                "operation": operation,
            }
        )
        return dict(sorted(values.items()))

    @staticmethod
    def _admission_id(tenant_id: str, idempotency_key: str, supplied: str | None) -> str:
        if supplied is not None:
            return _required(supplied, "admission_id", 200)
        digest = hashlib.sha256(f"{tenant_id}\x00{idempotency_key}".encode()).hexdigest()
        return f"rad_{digest}"

    @staticmethod
    def _validate_context(
        *, tenant_id: str, command_id: str, action_id: str, permit_ref: str
    ) -> tuple[str, str, str, str]:
        return (
            _required(tenant_id, "tenant_id", 160),
            _required(command_id, "command_id", 200),
            _required(action_id, "action_id", 200),
            _required(permit_ref, "permit_ref", 300),
        )

    def reserve(
        self,
        *,
        tenant_id: str,
        command_id: str,
        action_id: str,
        permit_ref: str,
        budget_id: str,
        amount: Decimal | str | int | float,
        currency: str = "USD",
        idempotency_key: str,
        admission_id: str | None = None,
        occurred_at: datetime | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        tenant_id, command_id, action_id, permit_ref = self._validate_context(
            tenant_id=tenant_id, command_id=command_id, action_id=action_id, permit_ref=permit_ref
        )
        budget_id = _required(budget_id, "budget_id", 200)
        idempotency_key = _required(idempotency_key, "idempotency_key", 300)
        amount = _amount(amount)
        currency = _currency(currency)
        admission_id = self._admission_id(tenant_id, idempotency_key, admission_id)
        occurred_at = _aware(occurred_at)
        event_id = _event_id(tenant_id, admission_id, "reserve")
        payload = {
            "admission_id": admission_id,
            "tenant_id": tenant_id,
            "command_id": command_id,
            "action_id": action_id,
            "permit_ref": permit_ref,
            "budget_id": budget_id,
            "operation": "reserve",
            "status": "reserved",
            "amount": str(amount),
            "currency": currency,
            "reason": None,
            "metadata": self._metadata(
                tenant_id=tenant_id,
                admission_id=admission_id,
                command_id=command_id,
                action_id=action_id,
                permit_ref=permit_ref,
                operation="reserve",
                metadata=metadata,
            ),
        }
        fingerprint = _fingerprint(payload)
        existing = self._existing(tenant_id, idempotency_key)
        if existing is not None:
            self._check_fingerprint(existing, fingerprint)
            return self._projection(tenant_id, admission_id)
        event = ResourceBudgetEvent(
            event_id=event_id,
            idempotency_key=_ledger_key(admission_id, "reserve"),
            budget_id=budget_id,
            tenant_id=tenant_id,
            state="reserved",
            amount=amount,
            currency=currency,
            occurred_at=occurred_at,
            metadata=payload["metadata"],
        )
        self.ledger.record(event)
        row = ResourceAdmissionEventRow(
            event_id=new_id("rae"),
            admission_id=admission_id,
            tenant_id=tenant_id,
            command_id=command_id,
            action_id=action_id,
            permit_ref=permit_ref,
            budget_id=budget_id,
            resource_event_id=event_id,
            parent_resource_event_id=None,
            operation="reserve",
            status="reserved",
            amount=amount,
            amount_text=str(amount),
            currency=currency,
            idempotency_key=idempotency_key,
            reason=None,
            metadata_json=payload["metadata"],
            fingerprint_sha256=fingerprint,
            occurred_at=occurred_at,
            recorded_at=datetime.now(UTC),
        )
        self._insert(row, fingerprint)
        return self._projection(tenant_id, admission_id)

    def consume(
        self,
        admission_id: str,
        *,
        tenant_id: str,
        idempotency_key: str | None = None,
        command_id: str | None = None,
        action_id: str | None = None,
        permit_ref: str | None = None,
        amount: Decimal | str | int | float | None = None,
        occurred_at: datetime | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        return self._settle(
            admission_id,
            operation="consume",
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            command_id=command_id,
            action_id=action_id,
            permit_ref=permit_ref,
            amount=amount,
            occurred_at=occurred_at,
            reason=None,
            metadata=metadata,
        )

    def release(
        self,
        admission_id: str,
        *,
        tenant_id: str,
        idempotency_key: str | None = None,
        command_id: str | None = None,
        action_id: str | None = None,
        permit_ref: str | None = None,
        amount: Decimal | str | int | float | None = None,
        occurred_at: datetime | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        return self._settle(
            admission_id,
            operation="release",
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            command_id=command_id,
            action_id=action_id,
            permit_ref=permit_ref,
            amount=amount,
            occurred_at=occurred_at,
            reason=None,
            metadata=metadata,
        )

    def hold_unknown(
        self,
        admission_id: str,
        *,
        tenant_id: str,
        reason: str,
        idempotency_key: str | None = None,
        command_id: str | None = None,
        action_id: str | None = None,
        permit_ref: str | None = None,
        occurred_at: datetime | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        reason = _required(reason, "unknown_reason", 2000)
        return self._settle(
            admission_id,
            operation="hold_unknown",
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            command_id=command_id,
            action_id=action_id,
            permit_ref=permit_ref,
            amount=Decimal("0"),
            occurred_at=occurred_at,
            reason=reason,
            metadata=metadata,
        )

    def get(self, admission_id: str, *, tenant_id: str) -> dict[str, Any]:
        tenant_id = _required(tenant_id, "tenant_id", 160)
        admission_id = _required(admission_id, "admission_id", 200)
        return self._projection(tenant_id, admission_id)

    def for_command(self, command_id: str, *, tenant_id: str | None = None) -> dict[str, Any] | None:
        command_id = _required(command_id, "command_id", 200)
        with Session(self.engine) as session:
            query = select(ResourceAdmissionEventRow.admission_id).where(
                ResourceAdmissionEventRow.command_id == command_id,
                ResourceAdmissionEventRow.operation == "reserve",
            )
            if tenant_id is not None:
                query = query.where(ResourceAdmissionEventRow.tenant_id == _required(tenant_id, "tenant_id", 160))
            admission_ids = list(session.scalars(query).unique())
        if not admission_ids:
            return None
        if len(set(admission_ids)) > 1:
            raise ValueError("command is bound to multiple resource admissions")
        admission_id = admission_ids[0]
        # The command id is globally unique in the current execution schema;
        # still require a tenant when callers have one to preserve exact scope.
        if tenant_id is None:
            with Session(self.engine) as session:
                tenant = session.scalar(
                    select(ResourceAdmissionEventRow.tenant_id).where(
                        ResourceAdmissionEventRow.command_id == command_id,
                        ResourceAdmissionEventRow.admission_id == admission_id,
                        ResourceAdmissionEventRow.operation == "reserve",
                    )
                )
            if tenant is None:
                return None
            tenant_id = tenant
        return self._projection(tenant_id, admission_id)

    def _existing(self, tenant_id: str, idempotency_key: str) -> ResourceAdmissionEventRow | None:
        with Session(self.engine) as session:
            return session.scalar(
                select(ResourceAdmissionEventRow).where(
                    ResourceAdmissionEventRow.tenant_id == tenant_id,
                    ResourceAdmissionEventRow.idempotency_key == idempotency_key,
                )
            )

    @staticmethod
    def _check_fingerprint(row: ResourceAdmissionEventRow, fingerprint: str) -> None:
        if row.fingerprint_sha256 != fingerprint:
            raise ValueError("resource admission idempotency key conflicts")

    def _insert(self, row: ResourceAdmissionEventRow, fingerprint: str) -> None:
        try:
            with Session(self.engine) as session, session.begin():
                existing = session.scalar(
                    select(ResourceAdmissionEventRow).where(
                        ResourceAdmissionEventRow.tenant_id == row.tenant_id,
                        ResourceAdmissionEventRow.idempotency_key == row.idempotency_key,
                    )
                )
                if existing is not None:
                    self._check_fingerprint(existing, fingerprint)
                    return
                existing_admission = session.scalar(
                    select(ResourceAdmissionEventRow).where(
                        ResourceAdmissionEventRow.tenant_id == row.tenant_id,
                        ResourceAdmissionEventRow.admission_id == row.admission_id,
                        ResourceAdmissionEventRow.operation == row.operation,
                    )
                )
                if existing_admission is not None:
                    self._check_fingerprint(existing_admission, fingerprint)
                    return
                session.add(row)
                session.flush()
        except IntegrityError:
            with Session(self.engine) as session:
                winner = session.scalar(
                    select(ResourceAdmissionEventRow).where(
                        ResourceAdmissionEventRow.tenant_id == row.tenant_id,
                        ResourceAdmissionEventRow.idempotency_key == row.idempotency_key,
                    )
                )
                if winner is None:
                    winner = session.scalar(
                        select(ResourceAdmissionEventRow).where(
                            ResourceAdmissionEventRow.tenant_id == row.tenant_id,
                            ResourceAdmissionEventRow.admission_id == row.admission_id,
                            ResourceAdmissionEventRow.operation == row.operation,
                        )
                    )
                if winner is None:
                    raise
                self._check_fingerprint(winner, fingerprint)

    def _settle(
        self,
        admission_id: str,
        *,
        operation: Literal["consume", "release", "hold_unknown"],
        tenant_id: str,
        idempotency_key: str | None,
        command_id: str | None,
        action_id: str | None,
        permit_ref: str | None,
        amount: Decimal | str | int | float | None,
        occurred_at: datetime | None,
        reason: str | None,
        metadata: Mapping[str, str] | None,
    ) -> dict[str, Any]:
        tenant_id = _required(tenant_id, "tenant_id", 160)
        admission_id = _required(admission_id, "admission_id", 200)
        with Session(self.engine) as session:
            reserve = session.scalar(
                select(ResourceAdmissionEventRow).where(
                    ResourceAdmissionEventRow.tenant_id == tenant_id,
                    ResourceAdmissionEventRow.admission_id == admission_id,
                    ResourceAdmissionEventRow.operation == "reserve",
                )
            )
            rows = list(
                session.scalars(
                    select(ResourceAdmissionEventRow).where(
                        ResourceAdmissionEventRow.tenant_id == tenant_id,
                        ResourceAdmissionEventRow.admission_id == admission_id,
                    )
                )
            )
        if reserve is None:
            raise KeyError("resource admission not found for exact tenant scope")
        self._assert_binding(reserve, command_id=command_id, action_id=action_id, permit_ref=permit_ref)
        existing_op = next((row for row in rows if row.operation == operation), None)
        if existing_op is not None:
            if idempotency_key is not None and existing_op.idempotency_key != idempotency_key:
                raise ValueError("resource admission lifecycle operation already recorded")
            if operation == "hold_unknown" and existing_op.reason != reason:
                raise ValueError("resource admission idempotency key conflicts")
            if (
                operation != "hold_unknown"
                and amount is not None
                and _amount(amount) != Decimal(existing_op.amount_text)
            ):
                raise ValueError("resource admission idempotency key conflicts")
            return self._projection(tenant_id, admission_id)
        current = self._current_status(rows)
        if operation == "hold_unknown":
            if current in {"consumed", "released"}:
                raise ValueError("terminal resource admission cannot be held unknown")
        elif current in {"consumed", "released"}:
            raise ValueError("terminal resource admission cannot be settled twice")
        if idempotency_key is None:
            idempotency_key = f"resource-admission:{admission_id}:{operation}"
        idempotency_key = _required(idempotency_key, "idempotency_key", 300)
        amount_value = Decimal("0") if operation == "hold_unknown" else (
            Decimal(reserve.amount_text) if amount is None else _amount(amount)
        )
        if operation != "hold_unknown" and amount_value != Decimal(reserve.amount_text):
            # One reservation is settled by one terminal event.  Keeping this
            # invariant avoids a second hidden source of available capacity.
            raise ValueError("resource admission settlement must match its reservation amount")
        if operation == "hold_unknown" and reason is None:
            raise ValueError("unknown resource admission requires a reason")
        command = command_id or reserve.command_id
        action = action_id or reserve.action_id
        permit = permit_ref or reserve.permit_ref
        self._assert_binding(reserve, command_id=command, action_id=action, permit_ref=permit)
        occurred_at = _aware(occurred_at)
        ledger_state: str | None = {"consume": "consumed", "release": "released"}.get(operation)
        if operation != "hold_unknown" and ledger_state is None:
            raise ValueError("unknown resource admission settlement operation")
        status: AdmissionState = "unknown" if operation == "hold_unknown" else ledger_state  # type: ignore[assignment]
        admission_metadata = self._metadata(
            tenant_id=tenant_id,
            admission_id=admission_id,
            command_id=command,
            action_id=action,
            permit_ref=permit,
            operation=operation,
            metadata=metadata,
        )
        payload = {
            "admission_id": admission_id,
            "tenant_id": tenant_id,
            "command_id": command,
            "action_id": action,
            "permit_ref": permit,
            "budget_id": reserve.budget_id,
            "operation": operation,
            "status": status,
            "amount": str(amount_value),
            "currency": reserve.currency,
            "reason": reason,
            "metadata": admission_metadata,
        }
        fingerprint = _fingerprint(payload)
        resource_event_id: str | None = None
        if operation != "hold_unknown":
            resource_event_id = _event_id(tenant_id, admission_id, operation)
            self.ledger.record(
                ResourceBudgetEvent(
                    event_id=resource_event_id,
                    idempotency_key=_ledger_key(admission_id, operation),
                    budget_id=reserve.budget_id,
                    tenant_id=tenant_id,
                    state=ledger_state,  # type: ignore[arg-type]
                    amount=amount_value,
                    currency=reserve.currency,
                    parent_event_id=reserve.resource_event_id,
                    occurred_at=occurred_at,
                    metadata=admission_metadata,
                )
            )
        row = ResourceAdmissionEventRow(
            event_id=new_id("rae"),
            admission_id=admission_id,
            tenant_id=tenant_id,
            command_id=command,
            action_id=action,
            permit_ref=permit,
            budget_id=reserve.budget_id,
            resource_event_id=resource_event_id,
            parent_resource_event_id=reserve.resource_event_id,
            operation=operation,
            status=status,
            amount=amount_value,
            amount_text=str(amount_value),
            currency=reserve.currency,
            idempotency_key=idempotency_key,
            reason=reason,
            metadata_json=admission_metadata,
            fingerprint_sha256=fingerprint,
            occurred_at=occurred_at,
            recorded_at=datetime.now(UTC),
        )
        self._insert(row, fingerprint)
        return self._projection(tenant_id, admission_id)

    @staticmethod
    def _assert_binding(
        reserve: ResourceAdmissionEventRow,
        *,
        command_id: str | None,
        action_id: str | None,
        permit_ref: str | None,
    ) -> None:
        for name, supplied, persisted in (
            ("command_id", command_id, reserve.command_id),
            ("action_id", action_id, reserve.action_id),
            ("permit_ref", permit_ref, reserve.permit_ref),
        ):
            if supplied is not None and _required(supplied, name) != persisted:
                raise ValueError(f"resource admission {name} binding does not match reservation")

    @staticmethod
    def _current_status(rows: list[ResourceAdmissionEventRow]) -> AdmissionState:
        if any(row.operation == "consume" for row in rows):
            return "consumed"
        if any(row.operation == "release" for row in rows):
            return "released"
        if any(row.operation == "hold_unknown" for row in rows):
            return "unknown"
        return "reserved"

    def _projection(self, tenant_id: str, admission_id: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            rows = list(
                session.scalars(
                    select(ResourceAdmissionEventRow)
                    .where(
                        ResourceAdmissionEventRow.tenant_id == tenant_id,
                        ResourceAdmissionEventRow.admission_id == admission_id,
                    )
                    .order_by(ResourceAdmissionEventRow.recorded_at, ResourceAdmissionEventRow.event_id)
                )
            )
        if not rows:
            raise KeyError("resource admission not found for exact tenant scope")
        reserve = next((row for row in rows if row.operation == "reserve"), None)
        if reserve is None:
            raise ValueError("resource admission is missing its reservation event")
        status = self._current_status(rows)
        settled_rows = [row for row in rows if row.operation in {"consume", "release"}]
        with localcontext() as context:
            context.prec = 60
            settled = sum((Decimal(row.amount_text) for row in settled_rows), Decimal("0"))
            reserved = Decimal(reserve.amount_text)
            remaining = reserved - settled
        if remaining < 0:
            raise ValueError("resource admission settlement exceeds its reservation")
        return {
            "admission_id": admission_id,
            "tenant_id": tenant_id,
            "command_id": reserve.command_id,
            "action_id": reserve.action_id,
            "permit_ref": reserve.permit_ref,
            "budget_id": reserve.budget_id,
            "reservation_event_id": reserve.resource_event_id,
            "settlement_event_ids": [
                row.resource_event_id
                for row in settled_rows
                if row.resource_event_id is not None
            ],
            "status": status,
            "amount": str(reserved),
            "settled_amount": str(settled),
            "remaining_amount": str(remaining),
            "currency": reserve.currency,
            "unknown_reason": next(
                (row.reason for row in reversed(rows) if row.operation == "hold_unknown"),
                None,
            ),
            "event_ids": [row.event_id for row in rows],
            "external_write_allowed": False,
        }


__all__ = ["AdmissionState", "ResourceAdmissionEventRow", "ResourceAdmissionService"]
