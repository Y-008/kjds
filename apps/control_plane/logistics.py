from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .domain import new_id
from .security import Principal

MONEY = Decimal("0.01")
WEIGHT_PRECISION = Decimal("0.00000001")
LOGISTICS_RULE_VERSION = "crossborder-logistics-rate-v1"
FX_EVIDENCE_SOURCES = frozenset(
    {"fx_rate_snapshot", "central_bank_fx_rate", "bank_fx_quote"}
)
RATE_CARD_EVIDENCE_SOURCES = frozenset(
    {
        "operator_logistics_rate_card",
        "carrier_rate_card",
        "logistics_rate_card",
        "carrier_quote",
    }
)
SCOPE_STATUS_READY = "ready"
SCOPE_STATUS_LEGACY = "legacy_unbound"
RATE_CARD_DECIMAL_FIELDS = (
    "price_per_kg",
    "base_charge_per_parcel",
    "minimum_charge_per_parcel",
    "volumetric_divisor_cm3_per_kg",
    "weight_increment_kg",
    "min_weight_kg",
    "max_weight_kg",
    "max_length_cm",
    "max_width_cm",
    "max_height_cm",
    "max_dimensions_sum_cm",
    "min_declared_value",
    "max_declared_value",
)
CALCULATION_DECIMAL_FIELDS = (
    "physical_weight_kg",
    "length_cm",
    "width_cm",
    "height_cm",
    "declared_value",
    "currency_to_cny_rate",
    "volumetric_weight_kg",
    "chargeable_weight_kg",
    "billable_weight_kg",
    "unit_charge_currency",
    "total_charge_currency",
    "total_charge_cny",
)


@dataclass(frozen=True, slots=True)
class LogisticsScope:
    tenant_ref: str
    entity_ref: str
    store_ref: str
    scope_grant_authority_sha256: str
    scope_as_of: str

    def __post_init__(self) -> None:
        for field in ("tenant_ref", "entity_ref", "store_ref"):
            normalized = str(getattr(self, field) or "").strip()
            if not normalized or len(normalized) > 160:
                raise ValueError(f"Logistics exact scope requires {field}")
            object.__setattr__(self, field, normalized)
        authority = str(self.scope_grant_authority_sha256 or "").strip().lower()
        if len(authority) != 64 or any(
            character not in "0123456789abcdef" for character in authority
        ):
            raise ValueError(
                "Logistics exact scope requires scope_grant_authority_sha256"
            )
        object.__setattr__(self, "scope_grant_authority_sha256", authority)
        object.__setattr__(
            self,
            "scope_as_of",
            _utc(self.scope_as_of, "scope_as_of").isoformat(),
        )

    def values(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class LogisticsScopeContext:
    principal: Principal
    scope: LogisticsScope
    as_of: datetime

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("Logistics context as_of must include a timezone")
        cutoff = self.as_of.astimezone(UTC)
        if self.principal.tenant_ref != self.scope.tenant_ref:
            raise ValueError("Logistics context tenant does not match Principal")
        if not self.principal.can_access_store(self.scope.store_ref):
            raise PermissionError(
                "Authenticated identity is not authorized for store_ref"
            )
        if cutoff != _utc(self.scope.scope_as_of, "scope_as_of"):
            raise ValueError("Logistics context timestamp does not match exact scope")
        object.__setattr__(self, "as_of", cutoff)

    @classmethod
    def from_authority(
        cls,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> LogisticsScopeContext:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("Logistics as_of must include a timezone")
        cutoff = as_of.astimezone(UTC)
        store = str(store_ref or "").strip()
        if not principal.can_access_store(store):
            raise PermissionError(
                "Authenticated identity is not authorized for store_ref"
            )
        if (
            entity_scope.get("status") != "ready"
            or not entity_scope.get("entity_ref")
            or not entity_scope.get("authority_sha256")
        ):
            raise ValueError("Logistics exact entity scope authority is not ready")
        if entity_scope.get("tenant_ref") != principal.tenant_ref:
            raise ValueError("Logistics entity scope tenant does not match Principal")
        if entity_scope.get("store_ref") != store:
            raise ValueError("Logistics entity scope store does not match request")
        scope = LogisticsScope(
            tenant_ref=principal.tenant_ref,
            entity_ref=str(entity_scope["entity_ref"]),
            store_ref=store,
            scope_grant_authority_sha256=str(
                entity_scope["authority_sha256"]
            ),
            scope_as_of=cutoff.isoformat(),
        )
        return cls(principal=principal, scope=scope, as_of=cutoff)

    def entity_scope(self) -> dict[str, str]:
        return {
            "status": "ready",
            "tenant_ref": self.scope.tenant_ref,
            "entity_ref": self.scope.entity_ref,
            "store_ref": self.scope.store_ref,
            "authority_sha256": self.scope.scope_grant_authority_sha256,
        }


def _utc(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def _iso(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    parsed = value if isinstance(value, datetime) else _utc(value, "timestamp")
    return parsed.astimezone(UTC).isoformat()


def _positive(value: Decimal, field: str, *, allow_zero: bool = False) -> None:
    if not value.is_finite() or value < 0 or (not allow_zero and value == 0):
        qualifier = "nonnegative" if allow_zero else "positive"
        raise ValueError(f"{field} must be a finite {qualifier} number")


def _hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


def _validate_scope_envelope(record: Any) -> None:
    values = (
        record.tenant_ref,
        record.entity_ref,
        record.store_ref,
        record.scope_grant_authority_sha256,
        record.scope_as_of,
    )
    if record.scope_status == SCOPE_STATUS_LEGACY and all(
        value is None for value in values
    ):
        return
    if record.scope_status != SCOPE_STATUS_READY or any(
        value is None for value in values
    ):
        raise ValueError("Logistics scope envelope is incomplete")
    LogisticsScope(
        tenant_ref=record.tenant_ref,
        entity_ref=record.entity_ref,
        store_ref=record.store_ref,
        scope_grant_authority_sha256=(
            record.scope_grant_authority_sha256
        ),
        scope_as_of=record.scope_as_of,
    )


def _matches_scope(record: Any, scope: LogisticsScope) -> bool:
    return (
        record.scope_status == SCOPE_STATUS_READY
        and record.tenant_ref == scope.tenant_ref
        and record.entity_ref == scope.entity_ref
        and record.store_ref == scope.store_ref
        and record.scope_grant_authority_sha256
        == scope.scope_grant_authority_sha256
    )


def _scope_from_record(record: Any) -> LogisticsScope:
    if record.scope_status != SCOPE_STATUS_READY:
        raise ValueError("Legacy unbound logistics records are read-only")
    return LogisticsScope(
        tenant_ref=record.tenant_ref or "",
        entity_ref=record.entity_ref or "",
        store_ref=record.store_ref or "",
        scope_grant_authority_sha256=(
            record.scope_grant_authority_sha256 or ""
        ),
        scope_as_of=record.scope_as_of or "",
    )


def _scope_parameters(scope: LogisticsScope) -> dict[str, Any]:
    values: dict[str, Any] = scope.values()
    values["scope_as_of"] = _utc(scope.scope_as_of, "scope_as_of")
    return values


@dataclass(frozen=True, slots=True)
class LogisticsRateCard:
    provider: str
    route_code: str
    service_name: str
    origin_country: str
    destination_country: str
    marketplace: str
    currency: str
    declared_value_currency: str
    price_per_kg: Decimal
    base_charge_per_parcel: Decimal
    minimum_charge_per_parcel: Decimal
    volumetric_divisor_cm3_per_kg: Decimal
    weight_increment_kg: Decimal
    min_weight_kg: Decimal
    max_weight_kg: Decimal
    max_length_cm: Decimal
    max_width_cm: Decimal
    max_height_cm: Decimal
    max_dimensions_sum_cm: Decimal
    min_declared_value: Decimal
    max_declared_value: Decimal
    effective_at: str
    effective_until: str | None
    evidence_id: str
    captured_by: str
    source_sheet: str
    source_range: str
    rule_version: str = LOGISTICS_RULE_VERSION
    tenant_ref: str | None = None
    entity_ref: str | None = None
    store_ref: str | None = None
    scope_grant_authority_sha256: str | None = None
    scope_as_of: str | None = None
    scope_status: str = SCOPE_STATUS_LEGACY
    id: str = ""
    rate_card_hash: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        for field in (
            "provider",
            "route_code",
            "service_name",
            "origin_country",
            "destination_country",
            "marketplace",
            "currency",
            "declared_value_currency",
            "evidence_id",
            "captured_by",
            "source_sheet",
            "source_range",
        ):
            if not str(getattr(self, field)).strip():
                raise ValueError(f"Logistics rate card requires {field}")
        if len(self.currency.strip()) != 3 or len(self.declared_value_currency.strip()) != 3:
            raise ValueError("Logistics currencies must be three-letter ISO codes")
        for field in (
            "price_per_kg",
            "base_charge_per_parcel",
            "minimum_charge_per_parcel",
            "volumetric_divisor_cm3_per_kg",
            "min_weight_kg",
            "max_length_cm",
            "max_width_cm",
            "max_height_cm",
            "max_dimensions_sum_cm",
            "min_declared_value",
            "max_declared_value",
        ):
            _positive(getattr(self, field), field, allow_zero=True)
        _positive(self.weight_increment_kg, "weight_increment_kg")
        _positive(self.max_weight_kg, "max_weight_kg")
        if (
            self.price_per_kg == 0
            and self.base_charge_per_parcel == 0
            and self.minimum_charge_per_parcel == 0
        ):
            raise ValueError("Logistics rate card requires at least one positive charge")
        if self.min_weight_kg > self.max_weight_kg:
            raise ValueError("Logistics minimum weight cannot exceed maximum weight")
        if self.min_declared_value > self.max_declared_value and self.max_declared_value > 0:
            raise ValueError(
                "Logistics minimum declared value cannot exceed maximum declared value"
            )
        start = _utc(self.effective_at, "effective_at")
        end = _utc(self.effective_until, "effective_until") if self.effective_until else None
        if end is not None and end <= start:
            raise ValueError("Logistics effective_until must be after effective_at")
        object.__setattr__(self, "provider", self.provider.strip())
        object.__setattr__(self, "route_code", self.route_code.strip())
        object.__setattr__(self, "service_name", self.service_name.strip())
        object.__setattr__(self, "origin_country", self.origin_country.strip().upper())
        object.__setattr__(self, "destination_country", self.destination_country.strip().upper())
        object.__setattr__(self, "marketplace", self.marketplace.strip().upper())
        object.__setattr__(self, "currency", self.currency.strip().upper())
        object.__setattr__(
            self,
            "declared_value_currency",
            self.declared_value_currency.strip().upper(),
        )
        object.__setattr__(self, "effective_at", start.isoformat())
        object.__setattr__(self, "effective_until", end.isoformat() if end else None)
        _validate_scope_envelope(self)
        normalized = {
            key: _decimal_text(value) if isinstance(value, Decimal) else value
            for key, value in asdict(self).items()
            if key
            not in {
                "id",
                "rate_card_hash",
                "created_at",
                "captured_by",
                "tenant_ref",
                "entity_ref",
                "store_ref",
                "scope_grant_authority_sha256",
                "scope_as_of",
                "scope_status",
            }
        }
        computed_hash = _hash(normalized)
        if self.rate_card_hash and self.rate_card_hash != computed_hash:
            raise ValueError("Logistics rate_card_hash does not match immutable content")
        object.__setattr__(self, "id", self.id or new_id("lrc"))
        object.__setattr__(self, "rate_card_hash", computed_hash)
        object.__setattr__(self, "created_at", self.created_at or datetime.now(UTC).isoformat())


@dataclass(frozen=True, slots=True)
class LogisticsCalculation:
    rate_card_id: str
    physical_weight_kg: Decimal
    length_cm: Decimal
    width_cm: Decimal
    height_cm: Decimal
    declared_value: Decimal
    quantity: int
    currency_to_cny_rate: Decimal
    volumetric_weight_kg: Decimal
    chargeable_weight_kg: Decimal
    billable_weight_kg: Decimal
    unit_charge_currency: Decimal
    total_charge_currency: Decimal
    total_charge_cny: Decimal
    evidence_id: str
    fx_evidence_id: str | None
    idempotency_key: str
    input_hash: str
    calculated_by: str
    state: str = "estimate"
    tenant_ref: str | None = None
    entity_ref: str | None = None
    store_ref: str | None = None
    scope_grant_authority_sha256: str | None = None
    scope_as_of: str | None = None
    scope_status: str = SCOPE_STATUS_LEGACY
    id: str = ""
    calculated_at: str = ""

    def __post_init__(self) -> None:
        if self.quantity < 1:
            raise ValueError("Logistics quantity must be positive")
        for field in (
            "physical_weight_kg",
            "currency_to_cny_rate",
            "billable_weight_kg",
            "unit_charge_currency",
            "total_charge_currency",
            "total_charge_cny",
        ):
            _positive(getattr(self, field), field)
        for field in (
            "length_cm",
            "width_cm",
            "height_cm",
            "declared_value",
            "volumetric_weight_kg",
            "chargeable_weight_kg",
        ):
            _positive(getattr(self, field), field, allow_zero=True)
        if self.state != "estimate":
            raise ValueError("Rate-card calculations are estimates; actuals require a carrier final bill")
        _validate_scope_envelope(self)
        expected_input_hash = _hash(
            {
                "rate_card_id": self.rate_card_id,
                "physical_weight_kg": _decimal_text(self.physical_weight_kg),
                "length_cm": _decimal_text(self.length_cm),
                "width_cm": _decimal_text(self.width_cm),
                "height_cm": _decimal_text(self.height_cm),
                "declared_value": _decimal_text(self.declared_value),
                "quantity": self.quantity,
                "currency_to_cny_rate": _decimal_text(
                    self.currency_to_cny_rate
                ),
                "fx_evidence_id": self.fx_evidence_id,
            }
        )
        if self.input_hash != expected_input_hash:
            raise ValueError("Logistics input_hash does not match immutable inputs")
        object.__setattr__(self, "id", self.id or new_id("lgc"))
        object.__setattr__(self, "calculated_at", self.calculated_at or datetime.now(UTC).isoformat())


class LogisticsStore(Protocol):
    def save_rate_card(self, rate_card: LogisticsRateCard) -> LogisticsRateCard: ...
    def get_rate_card(
        self,
        scope: LogisticsScope,
        rate_card_id: str,
    ) -> LogisticsRateCard: ...
    def list_rate_cards(
        self,
        scope: LogisticsScope,
        limit: int = 100,
    ) -> list[LogisticsRateCard]: ...
    def save_calculation(self, calculation: LogisticsCalculation) -> LogisticsCalculation: ...
    def get_calculation(
        self,
        scope: LogisticsScope,
        calculation_id: str,
    ) -> LogisticsCalculation: ...
    def find_calculation(
        self,
        scope: LogisticsScope,
        rate_card_id: str,
        idempotency_key: str,
    ) -> LogisticsCalculation | None: ...
    def list_calculations(
        self,
        scope: LogisticsScope,
        limit: int = 100,
    ) -> list[LogisticsCalculation]: ...


class InMemoryLogisticsStore:
    def __init__(self) -> None:
        self.rate_cards: dict[str, LogisticsRateCard] = {}
        self.calculations: dict[str, LogisticsCalculation] = {}

    def save_rate_card(self, rate_card: LogisticsRateCard) -> LogisticsRateCard:
        if rate_card.scope_status != SCOPE_STATUS_READY:
            raise ValueError("Legacy unbound logistics rate cards are read-only")
        existing = next(
            (
                item
                for item in self.rate_cards.values()
                if item.rate_card_hash == rate_card.rate_card_hash
                and item.tenant_ref == rate_card.tenant_ref
                and item.entity_ref == rate_card.entity_ref
                and item.store_ref == rate_card.store_ref
                and item.scope_grant_authority_sha256
                == rate_card.scope_grant_authority_sha256
            ),
            None,
        )
        if existing:
            return existing
        self.rate_cards[rate_card.id] = rate_card
        return rate_card

    def get_rate_card(
        self,
        scope: LogisticsScope,
        rate_card_id: str,
    ) -> LogisticsRateCard:
        try:
            card = self.rate_cards[rate_card_id]
        except KeyError as exc:
            raise KeyError(f"Unknown logistics rate card: {rate_card_id}") from exc
        if not _matches_scope(card, scope) or _utc(
            card.scope_as_of or "", "scope_as_of"
        ) > _utc(scope.scope_as_of, "scope_as_of"):
            raise KeyError(f"Unknown logistics rate card: {rate_card_id}")
        return card

    def list_rate_cards(
        self,
        scope: LogisticsScope,
        limit: int = 100,
    ) -> list[LogisticsRateCard]:
        cutoff = _utc(scope.scope_as_of, "scope_as_of")
        return sorted(
            (
                item
                for item in self.rate_cards.values()
                if _matches_scope(item, scope)
                and _utc(item.scope_as_of or "", "scope_as_of") <= cutoff
            ),
            key=lambda item: item.created_at,
            reverse=True,
        )[:limit]

    def save_calculation(self, calculation: LogisticsCalculation) -> LogisticsCalculation:
        if calculation.scope_status != SCOPE_STATUS_READY:
            raise ValueError("Legacy unbound logistics calculations are read-only")
        scope = LogisticsScope(
            tenant_ref=calculation.tenant_ref or "",
            entity_ref=calculation.entity_ref or "",
            store_ref=calculation.store_ref or "",
            scope_grant_authority_sha256=(
                calculation.scope_grant_authority_sha256 or ""
            ),
            scope_as_of=calculation.scope_as_of or "",
        )
        card = self.get_rate_card(scope, calculation.rate_card_id)
        if not _matches_scope(card, scope):
            raise ValueError("Logistics calculation scope does not match rate card")
        existing = self.find_calculation(
            scope,
            calculation.rate_card_id,
            calculation.idempotency_key,
        )
        if existing:
            if existing.input_hash != calculation.input_hash:
                raise ValueError(
                    "Logistics idempotency key already belongs to different inputs"
                )
            return existing
        self.calculations[calculation.id] = calculation
        return calculation

    def get_calculation(
        self,
        scope: LogisticsScope,
        calculation_id: str,
    ) -> LogisticsCalculation:
        try:
            calculation = self.calculations[calculation_id]
        except KeyError as exc:
            raise KeyError(f"Unknown logistics calculation: {calculation_id}") from exc
        if not _matches_scope(calculation, scope) or _utc(
            calculation.scope_as_of or "", "scope_as_of"
        ) > _utc(scope.scope_as_of, "scope_as_of"):
            raise KeyError(f"Unknown logistics calculation: {calculation_id}")
        return calculation

    def find_calculation(
        self,
        scope: LogisticsScope,
        rate_card_id: str,
        idempotency_key: str,
    ) -> LogisticsCalculation | None:
        cutoff = _utc(scope.scope_as_of, "scope_as_of")
        return next(
            (
                item
                for item in self.calculations.values()
                if item.rate_card_id == rate_card_id
                and item.idempotency_key == idempotency_key
                and _matches_scope(item, scope)
                and _utc(item.scope_as_of or "", "scope_as_of") <= cutoff
            ),
            None,
        )

    def list_calculations(
        self,
        scope: LogisticsScope,
        limit: int = 100,
    ) -> list[LogisticsCalculation]:
        cutoff = _utc(scope.scope_as_of, "scope_as_of")
        return sorted(
            (
                item
                for item in self.calculations.values()
                if _matches_scope(item, scope)
                and _utc(item.scope_as_of or "", "scope_as_of") <= cutoff
            ),
            key=lambda item: item.calculated_at,
            reverse=True,
        )[:limit]


class SqlLogisticsStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def save_rate_card(self, rate_card: LogisticsRateCard) -> LogisticsRateCard:
        scope = _scope_from_record(rate_card)
        values = {
            key: value
            for key, value in asdict(rate_card).items()
            if key != "created_at"
        }
        values["created_at"] = _utc(rate_card.created_at, "created_at")
        values["effective_at"] = _utc(rate_card.effective_at, "effective_at")
        values["effective_until"] = (
            _utc(rate_card.effective_until, "effective_until")
            if rate_card.effective_until
            else None
        )
        values["scope_as_of"] = _utc(scope.scope_as_of, "scope_as_of")
        values = self._bind_values(values)
        columns = ", ".join(values)
        parameters = ", ".join(f":{key}" for key in values)
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    f"INSERT INTO logistics_rate_cards ({columns}) VALUES ({parameters}) "
                    "ON CONFLICT (tenant_ref, entity_ref, store_ref, "
                    "scope_grant_authority_sha256, rate_card_hash) DO NOTHING"
                ),
                values,
            )
            row = connection.execute(
                text(
                    "SELECT * FROM logistics_rate_cards "
                    "WHERE scope_status='ready' "
                    "AND tenant_ref=:tenant_ref AND entity_ref=:entity_ref "
                    "AND store_ref=:store_ref "
                    "AND scope_grant_authority_sha256="
                    ":scope_grant_authority_sha256 "
                    "AND rate_card_hash=:rate_card_hash"
                ),
                values,
            ).mappings().one()
        return self._rate_card(row)

    def get_rate_card(
        self,
        scope: LogisticsScope,
        rate_card_id: str,
    ) -> LogisticsRateCard:
        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT * FROM logistics_rate_cards WHERE id=:id "
                    "AND scope_status='ready' "
                    "AND tenant_ref=:tenant_ref AND entity_ref=:entity_ref "
                    "AND store_ref=:store_ref "
                    "AND scope_grant_authority_sha256="
                    ":scope_grant_authority_sha256 "
                    "AND scope_as_of<=:scope_as_of"
                ),
                {"id": rate_card_id, **_scope_parameters(scope)},
            ).mappings().first()
        if row is None:
            raise KeyError(f"Unknown logistics rate card: {rate_card_id}")
        return self._rate_card(row)

    def list_rate_cards(
        self,
        scope: LogisticsScope,
        limit: int = 100,
    ) -> list[LogisticsRateCard]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT * FROM logistics_rate_cards "
                    "WHERE scope_status='ready' "
                    "AND tenant_ref=:tenant_ref AND entity_ref=:entity_ref "
                    "AND store_ref=:store_ref "
                    "AND scope_grant_authority_sha256="
                    ":scope_grant_authority_sha256 "
                    "AND scope_as_of<=:scope_as_of "
                    "ORDER BY created_at DESC LIMIT :limit"
                ),
                {**_scope_parameters(scope), "limit": limit},
            ).mappings().all()
        return [self._rate_card(row) for row in rows]

    def save_calculation(self, calculation: LogisticsCalculation) -> LogisticsCalculation:
        scope = _scope_from_record(calculation)
        self.get_rate_card(scope, calculation.rate_card_id)
        values = {
            key: value
            for key, value in asdict(calculation).items()
            if key != "calculated_at"
        }
        values["calculated_at"] = _utc(calculation.calculated_at, "calculated_at")
        values["scope_as_of"] = _utc(scope.scope_as_of, "scope_as_of")
        values = self._bind_values(values)
        columns = ", ".join(values)
        parameters = ", ".join(f":{key}" for key in values)
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    f"INSERT INTO logistics_calculations ({columns}) VALUES ({parameters}) "
                    "ON CONFLICT (tenant_ref, entity_ref, store_ref, "
                    "scope_grant_authority_sha256, rate_card_id, "
                    "idempotency_key) DO NOTHING"
                ),
                values,
            )
            row = connection.execute(
                text(
                    "SELECT * FROM logistics_calculations "
                    "WHERE scope_status='ready' "
                    "AND tenant_ref=:tenant_ref AND entity_ref=:entity_ref "
                    "AND store_ref=:store_ref "
                    "AND scope_grant_authority_sha256="
                    ":scope_grant_authority_sha256 "
                    "AND rate_card_id=:rate_card_id "
                    "AND idempotency_key=:idempotency_key"
                ),
                values,
            ).mappings().one()
        stored = self._calculation(row)
        if stored.input_hash != calculation.input_hash:
            raise ValueError("Logistics idempotency key already belongs to different inputs")
        return stored

    def get_calculation(
        self,
        scope: LogisticsScope,
        calculation_id: str,
    ) -> LogisticsCalculation:
        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT * FROM logistics_calculations WHERE id=:id "
                    "AND scope_status='ready' "
                    "AND tenant_ref=:tenant_ref AND entity_ref=:entity_ref "
                    "AND store_ref=:store_ref "
                    "AND scope_grant_authority_sha256="
                    ":scope_grant_authority_sha256 "
                    "AND scope_as_of<=:scope_as_of"
                ),
                {"id": calculation_id, **_scope_parameters(scope)},
            ).mappings().first()
        if row is None:
            raise KeyError(f"Unknown logistics calculation: {calculation_id}")
        return self._calculation(row)

    def find_calculation(
        self,
        scope: LogisticsScope,
        rate_card_id: str,
        idempotency_key: str,
    ) -> LogisticsCalculation | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT * FROM logistics_calculations "
                    "WHERE scope_status='ready' "
                    "AND tenant_ref=:tenant_ref AND entity_ref=:entity_ref "
                    "AND store_ref=:store_ref "
                    "AND scope_grant_authority_sha256="
                    ":scope_grant_authority_sha256 "
                    "AND scope_as_of<=:scope_as_of "
                    "AND rate_card_id=:rate_card_id "
                    "AND idempotency_key=:idempotency_key"
                ),
                {
                    **_scope_parameters(scope),
                    "rate_card_id": rate_card_id,
                    "idempotency_key": idempotency_key,
                },
            ).mappings().first()
        return self._calculation(row) if row else None

    def list_calculations(
        self,
        scope: LogisticsScope,
        limit: int = 100,
    ) -> list[LogisticsCalculation]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT * FROM logistics_calculations "
                    "WHERE scope_status='ready' "
                    "AND tenant_ref=:tenant_ref AND entity_ref=:entity_ref "
                    "AND store_ref=:store_ref "
                    "AND scope_grant_authority_sha256="
                    ":scope_grant_authority_sha256 "
                    "AND scope_as_of<=:scope_as_of "
                    "ORDER BY calculated_at DESC LIMIT :limit"
                ),
                {**_scope_parameters(scope), "limit": limit},
            ).mappings().all()
        return [self._calculation(row) for row in rows]

    @staticmethod
    def _rate_card(row) -> LogisticsRateCard:
        values = dict(row)
        for field in RATE_CARD_DECIMAL_FIELDS:
            values[field] = Decimal(str(values[field]))
        for field in (
            "effective_at",
            "effective_until",
            "created_at",
            "scope_as_of",
        ):
            values[field] = _iso(values[field])
        return LogisticsRateCard(**values)

    @staticmethod
    def _calculation(row) -> LogisticsCalculation:
        values = dict(row)
        for field in CALCULATION_DECIMAL_FIELDS:
            values[field] = Decimal(str(values[field]))
        values["calculated_at"] = _iso(values["calculated_at"])
        values["scope_as_of"] = _iso(values["scope_as_of"])
        return LogisticsCalculation(**values)

    def _bind_values(self, values: dict[str, Any]) -> dict[str, Any]:
        if self.engine.dialect.name != "sqlite":
            return values
        return {
            key: str(value) if isinstance(value, Decimal) else value
            for key, value in values.items()
        }


class LogisticsQuoteWorkspace:
    def __init__(
        self,
        store: LogisticsStore,
        evidence_validator,
        evidence_linker=None,
        evidence_resolver=None,
        fx_evidence_current_validator=None,
        scoped_evidence=None,
    ) -> None:
        self.store = store
        self.evidence_validator = evidence_validator
        self.evidence_linker = evidence_linker
        self.evidence_resolver = evidence_resolver
        self.fx_evidence_current_validator = fx_evidence_current_validator
        self.scoped_evidence = scoped_evidence

    @staticmethod
    def context(
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> LogisticsScopeContext:
        return LogisticsScopeContext.from_authority(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )

    def capture_rate_card(
        self,
        context: LogisticsScopeContext,
        rate_card: LogisticsRateCard,
    ) -> LogisticsRateCard:
        if rate_card.scope_status != SCOPE_STATUS_LEGACY or any(
            value is not None
            for value in (
                rate_card.tenant_ref,
                rate_card.entity_ref,
                rate_card.store_ref,
                rate_card.scope_grant_authority_sha256,
                rate_card.scope_as_of,
            )
        ):
            raise ValueError("Logistics scope is server-derived and cannot be supplied")
        if rate_card.captured_by != context.principal.actor_id:
            raise PermissionError("Rate-card capturer must match authenticated identity")
        record = self._require_scoped_evidence(
            context,
            [rate_card.evidence_id],
        )[rate_card.evidence_id]
        self._validate_rate_card_evidence(record)
        stored = self.store.save_rate_card(
            replace(
                rate_card,
                tenant_ref=context.scope.tenant_ref,
                entity_ref=context.scope.entity_ref,
                store_ref=context.scope.store_ref,
                scope_grant_authority_sha256=(
                    context.scope.scope_grant_authority_sha256
                ),
                scope_as_of=context.scope.scope_as_of,
                scope_status=SCOPE_STATUS_READY,
            )
        )
        if self.evidence_linker:
            self.evidence_linker(
                evidence_id=stored.evidence_id,
                target_type="logistics_rate_card",
                target_id=stored.id,
                relationship="source_for",
                created_by=rate_card.captured_by,
            )
        return stored

    def _require_scoped_evidence(
        self,
        context: LogisticsScopeContext,
        evidence_ids: list[str],
    ) -> dict[str, Any]:
        normalized = sorted({item.strip() for item in evidence_ids if item.strip()})
        if len(normalized) != len(evidence_ids) or not normalized:
            raise ValueError("Logistics evidence references must be distinct and non-empty")
        if (
            self.scoped_evidence is None
            or self.evidence_resolver is None
            or self.evidence_validator is None
        ):
            raise ValueError("Scoped logistics Evidence authority is not configured")
        self.evidence_validator(normalized)
        projection = self.scoped_evidence.project_targets(
            evidence_ids=normalized,
            principal=context.principal,
            entity_scope=context.entity_scope(),
            store_ref=context.scope.store_ref,
            as_of=context.as_of,
        )
        projected = {
            item["evidence_id"]: item
            for item in projection.get("records", [])
        }
        if projection.get("status") != "ready" or any(
            projected.get(evidence_id, {})
            .get("scope_binding", {})
            .get("status")
            != "ready"
            for evidence_id in normalized
        ):
            raise ValueError(
                "Logistics Evidence is not current, intact, and bound to exact scope"
            )
        return {
            evidence_id: self.evidence_resolver(evidence_id)
            for evidence_id in normalized
        }

    def get_rate_card(
        self,
        context: LogisticsScopeContext,
        rate_card_id: str,
    ) -> LogisticsRateCard:
        card = self.store.get_rate_card(context.scope, rate_card_id)
        record = self._require_scoped_evidence(
            context,
            [card.evidence_id],
        )[card.evidence_id]
        self._validate_rate_card_evidence(record)
        return card

    def list_rate_cards(
        self,
        context: LogisticsScopeContext,
        limit: int = 100,
    ) -> list[LogisticsRateCard]:
        cards = self.store.list_rate_cards(context.scope, limit)
        if not cards:
            return []
        records = self._require_scoped_evidence(
            context,
            list(dict.fromkeys(item.evidence_id for item in cards)),
        )
        for card in cards:
            self._validate_rate_card_evidence(records[card.evidence_id])
        return cards

    @staticmethod
    def _validate_rate_card_evidence(record: Any) -> None:
        source = str(record.source).strip().lower()
        grade = getattr(record.grade, "value", str(record.grade))
        if source not in RATE_CARD_EVIDENCE_SOURCES or grade not in {"A", "B"}:
            raise ValueError(
                "Logistics rate-card evidence must be an A/B-grade carrier quote"
            )

    def calculate(
        self,
        context: LogisticsScopeContext,
        *,
        rate_card_id: str,
        physical_weight_kg: Decimal,
        length_cm: Decimal,
        width_cm: Decimal,
        height_cm: Decimal,
        declared_value: Decimal,
        quantity: int,
        currency_to_cny_rate: Decimal,
        idempotency_key: str,
        calculated_by: str,
        evaluated_at: str | None = None,
        fx_evidence_id: str | None = None,
    ) -> LogisticsCalculation:
        if not idempotency_key.strip():
            raise ValueError("Logistics calculation requires idempotency_key")
        if calculated_by != context.principal.actor_id:
            raise PermissionError("Logistics calculator must match authenticated identity")
        card = self.get_rate_card(context, rate_card_id)
        normalized_fx_evidence_id = (
            fx_evidence_id.strip() if fx_evidence_id and fx_evidence_id.strip() else None
        )
        evaluation = _utc(evaluated_at or datetime.now(UTC).isoformat(), "evaluated_at")
        if evaluation < _utc(card.effective_at, "effective_at"):
            raise ValueError("Logistics rate card is not effective yet")
        if card.effective_until and evaluation >= _utc(card.effective_until, "effective_until"):
            raise ValueError("Logistics rate card has expired")
        for value, field in (
            (physical_weight_kg, "physical_weight_kg"),
            (currency_to_cny_rate, "currency_to_cny_rate"),
        ):
            _positive(value, field)
        for value, field in (
            (length_cm, "length_cm"),
            (width_cm, "width_cm"),
            (height_cm, "height_cm"),
            (declared_value, "declared_value"),
        ):
            _positive(value, field, allow_zero=True)
        if card.currency == "CNY":
            if currency_to_cny_rate != 1:
                raise ValueError("CNY logistics rate cards require a 1:1 CNY rate")
            if normalized_fx_evidence_id:
                raise ValueError("CNY logistics rate cards do not require FX evidence")
        else:
            if not normalized_fx_evidence_id:
                raise ValueError("Non-CNY logistics calculations require FX evidence")
            self._validate_fx_evidence(
                context=context,
                card=card,
                evidence_id=normalized_fx_evidence_id,
                currency_to_cny_rate=currency_to_cny_rate,
                evaluation=evaluation,
            )
        if quantity < 1:
            raise ValueError("Logistics quantity must be positive")
        self._validate_constraints(
            card,
            physical_weight_kg=physical_weight_kg,
            length_cm=length_cm,
            width_cm=width_cm,
            height_cm=height_cm,
            declared_value=declared_value,
        )
        raw_volumetric = (
            (length_cm * width_cm * height_cm / card.volumetric_divisor_cm3_per_kg)
            if card.volumetric_divisor_cm3_per_kg > 0
            else Decimal("0")
        )
        raw_chargeable = max(physical_weight_kg, raw_volumetric)
        billable = (
            (raw_chargeable / card.weight_increment_kg).to_integral_value(
                rounding=ROUND_CEILING
            )
            * card.weight_increment_kg
        )
        volumetric = raw_volumetric.quantize(WEIGHT_PRECISION, rounding=ROUND_HALF_UP)
        chargeable = raw_chargeable.quantize(WEIGHT_PRECISION, rounding=ROUND_HALF_UP)
        unit = max(
            card.minimum_charge_per_parcel,
            card.base_charge_per_parcel + billable * card.price_per_kg,
        ).quantize(MONEY, rounding=ROUND_HALF_UP)
        total = (unit * quantity).quantize(MONEY, rounding=ROUND_HALF_UP)
        total_cny = (total * currency_to_cny_rate).quantize(MONEY, rounding=ROUND_HALF_UP)
        input_payload = {
            "rate_card_id": rate_card_id,
            "physical_weight_kg": _decimal_text(physical_weight_kg),
            "length_cm": _decimal_text(length_cm),
            "width_cm": _decimal_text(width_cm),
            "height_cm": _decimal_text(height_cm),
            "declared_value": _decimal_text(declared_value),
            "quantity": quantity,
            "currency_to_cny_rate": _decimal_text(currency_to_cny_rate),
            "fx_evidence_id": normalized_fx_evidence_id,
        }
        input_hash = _hash(input_payload)
        existing = self.store.find_calculation(
            context.scope,
            rate_card_id,
            idempotency_key.strip(),
        )
        if existing:
            if existing.input_hash != input_hash:
                raise ValueError("Logistics idempotency key already belongs to different inputs")
            return existing
        calculation = LogisticsCalculation(
            rate_card_id=rate_card_id,
            physical_weight_kg=physical_weight_kg,
            length_cm=length_cm,
            width_cm=width_cm,
            height_cm=height_cm,
            declared_value=declared_value,
            quantity=quantity,
            currency_to_cny_rate=currency_to_cny_rate,
            volumetric_weight_kg=volumetric,
            chargeable_weight_kg=chargeable,
            billable_weight_kg=billable,
            unit_charge_currency=unit,
            total_charge_currency=total,
            total_charge_cny=total_cny,
            evidence_id=card.evidence_id,
            fx_evidence_id=normalized_fx_evidence_id,
            idempotency_key=idempotency_key.strip(),
            input_hash=input_hash,
            calculated_by=calculated_by,
            tenant_ref=context.scope.tenant_ref,
            entity_ref=context.scope.entity_ref,
            store_ref=context.scope.store_ref,
            scope_grant_authority_sha256=(
                context.scope.scope_grant_authority_sha256
            ),
            scope_as_of=context.scope.scope_as_of,
            scope_status=SCOPE_STATUS_READY,
        )
        stored = self.store.save_calculation(calculation)
        if self.evidence_linker:
            self.evidence_linker(
                evidence_id=stored.evidence_id,
                target_type="logistics_calculation",
                target_id=stored.id,
                relationship="supports",
                created_by=calculated_by,
            )
            if stored.fx_evidence_id:
                self.evidence_linker(
                    evidence_id=stored.fx_evidence_id,
                    target_type="logistics_calculation",
                    target_id=stored.id,
                    relationship="fx_source_for",
                    created_by=calculated_by,
                )
        return stored

    def _validate_fx_evidence(
        self,
        *,
        context: LogisticsScopeContext,
        card: LogisticsRateCard,
        evidence_id: str,
        currency_to_cny_rate: Decimal,
        evaluation: datetime,
    ) -> None:
        if (
            self.evidence_resolver is None
            or self.fx_evidence_current_validator is None
        ):
            raise ValueError("FX evidence authority is not configured")
        self._require_scoped_evidence(context, [evidence_id])
        self.fx_evidence_current_validator([evidence_id], as_of=evaluation)
        record = self.evidence_resolver(evidence_id)
        source = str(record.source).strip().lower()
        grade = getattr(record.grade, "value", str(record.grade))
        metadata = record.metadata or {}
        if source not in FX_EVIDENCE_SOURCES or grade not in {"A", "B"}:
            raise ValueError("FX evidence must be a current A/B-grade rate snapshot")
        base_currency = str(metadata.get("base_currency", "")).strip().upper()
        quote_currency = str(metadata.get("quote_currency", "")).strip().upper()
        if (base_currency, quote_currency) != (card.currency, "CNY"):
            raise ValueError("FX evidence currency pair does not match the logistics route")
        try:
            evidenced_rate = Decimal(str(metadata["rate"]))
        except (InvalidOperation, KeyError, ValueError) as exc:
            raise ValueError("FX evidence requires a valid metadata rate") from exc
        _positive(evidenced_rate, "FX evidence metadata rate")
        if evidenced_rate != currency_to_cny_rate:
            raise ValueError("FX evidence rate does not match currency_to_cny_rate")

    def get_calculation(
        self,
        context: LogisticsScopeContext,
        calculation_id: str,
    ) -> LogisticsCalculation:
        calculation = self.store.get_calculation(context.scope, calculation_id)
        card = self.get_rate_card(context, calculation.rate_card_id)
        if not _matches_scope(card, context.scope) or not _matches_scope(
            calculation,
            context.scope,
        ):
            raise ValueError("Logistics calculation scope does not match rate card")
        if calculation.evidence_id != card.evidence_id:
            raise ValueError("Logistics calculation Evidence does not match rate card")
        if card.currency == "CNY":
            if calculation.fx_evidence_id is not None:
                raise ValueError("CNY logistics calculation contains unexpected FX Evidence")
        else:
            if not calculation.fx_evidence_id:
                raise ValueError("Non-CNY logistics calculation is missing FX Evidence")
            self._validate_fx_evidence(
                context=context,
                card=card,
                evidence_id=calculation.fx_evidence_id,
                currency_to_cny_rate=calculation.currency_to_cny_rate,
                evaluation=context.as_of,
            )
        return calculation

    def list_calculations(
        self,
        context: LogisticsScopeContext,
        limit: int = 100,
    ) -> list[LogisticsCalculation]:
        return [
            self.get_calculation(context, item.id)
            for item in self.store.list_calculations(context.scope, limit)
        ]

    def resolve_profit_cost(
        self,
        context: LogisticsScopeContext,
        calculation_id: str,
        *,
        marketplace: str,
        destination_country: str,
        declared_value_currency: str,
        declared_value: Decimal,
        physical_weight_kg: Decimal,
        length_cm: Decimal,
        width_cm: Decimal,
        height_cm: Decimal,
    ) -> LogisticsCalculation:
        calculation = self.get_calculation(context, calculation_id)
        card = self.get_rate_card(context, calculation.rate_card_id)
        expected_scope = (
            marketplace.strip().upper(),
            destination_country.strip().upper(),
            declared_value_currency.strip().upper(),
        )
        actual_scope = (
            card.marketplace,
            card.destination_country,
            card.declared_value_currency,
        )
        if actual_scope != expected_scope:
            raise ValueError(
                "Logistics calculation scope does not match the profit scenario"
            )
        expected_values = (
            declared_value,
            physical_weight_kg,
            length_cm,
            width_cm,
            height_cm,
        )
        actual_values = (
            calculation.declared_value,
            calculation.physical_weight_kg,
            calculation.length_cm,
            calculation.width_cm,
            calculation.height_cm,
        )
        if actual_values != expected_values:
            raise ValueError(
                "Logistics calculation shipment inputs do not match the profit scenario"
            )
        if calculation.quantity != 1:
            raise ValueError("Profit scenario logistics calculation must be for one unit")
        return calculation

    def decision_support(
        self,
        context: LogisticsScopeContext,
        calculation_id: str,
    ) -> dict[str, object]:
        calculation = self.get_calculation(context, calculation_id)
        card = self.get_rate_card(context, calculation.rate_card_id)
        ratio = (
            calculation.volumetric_weight_kg / calculation.physical_weight_kg
            if calculation.physical_weight_kg > 0
            else Decimal("0")
        )
        alerts: list[dict[str, str]] = []
        recommendations: list[dict[str, str]] = []
        if ratio > Decimal("1.20"):
            alerts.append(
                {
                    "code": "VOLUMETRIC_WEIGHT_DOMINATES",
                    "severity": "high" if ratio >= Decimal("2") else "medium",
                    "detail": "体积重高于实重，包装体积正在显著抬高头程成本。",
                }
            )
            recommendations.append(
                {
                    "action": "PACKAGING_REVIEW",
                    "detail": "在不影响质检与破损率的前提下，评估缩小包装尺寸并重新测算。",
                }
            )
        rounding_delta = calculation.billable_weight_kg - calculation.chargeable_weight_kg
        if rounding_delta > 0:
            alerts.append(
                {
                    "code": "WEIGHT_ROUNDING_UP",
                    "severity": "info",
                    "detail": "计费重按线路进位单位向上取整。",
                }
            )
        if calculation.unit_charge_currency == card.minimum_charge_per_parcel:
            alerts.append(
                {
                    "code": "MINIMUM_CHARGE_APPLIED",
                    "severity": "info",
                    "detail": "本次测算触发每票最低收费。",
                }
            )
        recommendations.append(
            {
                "action": "COMPARE_ACTIVE_ROUTES",
                "detail": "用相同重量、尺寸、货值和汇率比较至少两条仍在有效期内的线路。",
            }
        )
        return {
            "schema_version": "logistics-decision-support-v1",
            "calculation_id": calculation.id,
            "rate_card_id": card.id,
            "scope": {
                "tenant_ref": calculation.tenant_ref,
                "entity_ref": calculation.entity_ref,
                "store_ref": calculation.store_ref,
                "scope_grant_authority_sha256": (
                    calculation.scope_grant_authority_sha256
                ),
                "scope_as_of": calculation.scope_as_of,
                "scope_status": calculation.scope_status,
            },
            "facts": {
                "physical_weight_kg": str(calculation.physical_weight_kg),
                "volumetric_weight_kg": str(calculation.volumetric_weight_kg),
                "chargeable_weight_kg": str(calculation.chargeable_weight_kg),
                "billable_weight_kg": str(calculation.billable_weight_kg),
                "volumetric_to_physical_ratio": str(ratio.quantize(Decimal("0.01"))),
                "total_charge_cny": str(calculation.total_charge_cny),
                "state": calculation.state,
                "effective_until": card.effective_until,
                "evidence_id": calculation.evidence_id,
                "fx_evidence_id": calculation.fx_evidence_id,
            },
            "alerts": alerts,
            "recommendations": recommendations,
            "ai_boundary": {
                "facts_and_math_are_deterministic": True,
                "recommendation_only": True,
                "automatic_rate_card_selection": False,
                "automatic_profit_write": False,
                "automatic_procurement": False,
                "actual_cost_requires_carrier_final_bill": True,
            },
        }

    @staticmethod
    def _validate_constraints(
        card: LogisticsRateCard,
        *,
        physical_weight_kg: Decimal,
        length_cm: Decimal,
        width_cm: Decimal,
        height_cm: Decimal,
        declared_value: Decimal,
    ) -> None:
        if physical_weight_kg < card.min_weight_kg or physical_weight_kg > card.max_weight_kg:
            raise ValueError("Shipment weight is outside the selected logistics tier")
        for value, maximum, label in (
            (length_cm, card.max_length_cm, "length"),
            (width_cm, card.max_width_cm, "width"),
            (height_cm, card.max_height_cm, "height"),
        ):
            if maximum > 0 and value > maximum:
                raise ValueError(f"Shipment {label} exceeds the selected logistics tier")
        if (
            card.max_dimensions_sum_cm > 0
            and length_cm + width_cm + height_cm > card.max_dimensions_sum_cm
        ):
            raise ValueError("Shipment dimension sum exceeds the selected logistics tier")
        if declared_value < card.min_declared_value:
            raise ValueError("Shipment declared value is below the selected logistics tier")
        if card.max_declared_value > 0 and declared_value > card.max_declared_value:
            raise ValueError("Shipment declared value exceeds the selected logistics tier")
