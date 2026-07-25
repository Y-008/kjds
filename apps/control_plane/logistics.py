from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .domain import new_id

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
        normalized = {
            key: _decimal_text(value) if isinstance(value, Decimal) else value
            for key, value in asdict(self).items()
            if key not in {"id", "rate_card_hash", "created_at", "captured_by"}
        }
        object.__setattr__(self, "id", self.id or new_id("lrc"))
        object.__setattr__(self, "rate_card_hash", self.rate_card_hash or _hash(normalized))
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
        object.__setattr__(self, "id", self.id or new_id("lgc"))
        object.__setattr__(self, "calculated_at", self.calculated_at or datetime.now(UTC).isoformat())


class LogisticsStore(Protocol):
    def save_rate_card(self, rate_card: LogisticsRateCard) -> LogisticsRateCard: ...
    def get_rate_card(self, rate_card_id: str) -> LogisticsRateCard: ...
    def list_rate_cards(self, limit: int = 100) -> list[LogisticsRateCard]: ...
    def save_calculation(self, calculation: LogisticsCalculation) -> LogisticsCalculation: ...
    def get_calculation(self, calculation_id: str) -> LogisticsCalculation: ...
    def find_calculation(
        self, rate_card_id: str, idempotency_key: str
    ) -> LogisticsCalculation | None: ...
    def list_calculations(self, limit: int = 100) -> list[LogisticsCalculation]: ...


class InMemoryLogisticsStore:
    def __init__(self) -> None:
        self.rate_cards: dict[str, LogisticsRateCard] = {}
        self.calculations: dict[str, LogisticsCalculation] = {}

    def save_rate_card(self, rate_card: LogisticsRateCard) -> LogisticsRateCard:
        existing = next(
            (
                item
                for item in self.rate_cards.values()
                if item.rate_card_hash == rate_card.rate_card_hash
            ),
            None,
        )
        if existing:
            return existing
        self.rate_cards[rate_card.id] = rate_card
        return rate_card

    def get_rate_card(self, rate_card_id: str) -> LogisticsRateCard:
        try:
            return self.rate_cards[rate_card_id]
        except KeyError as exc:
            raise KeyError(f"Unknown logistics rate card: {rate_card_id}") from exc

    def list_rate_cards(self, limit: int = 100) -> list[LogisticsRateCard]:
        return sorted(self.rate_cards.values(), key=lambda item: item.created_at, reverse=True)[:limit]

    def save_calculation(self, calculation: LogisticsCalculation) -> LogisticsCalculation:
        self.calculations[calculation.id] = calculation
        return calculation

    def get_calculation(self, calculation_id: str) -> LogisticsCalculation:
        try:
            return self.calculations[calculation_id]
        except KeyError as exc:
            raise KeyError(f"Unknown logistics calculation: {calculation_id}") from exc

    def find_calculation(
        self, rate_card_id: str, idempotency_key: str
    ) -> LogisticsCalculation | None:
        return next(
            (
                item
                for item in self.calculations.values()
                if item.rate_card_id == rate_card_id
                and item.idempotency_key == idempotency_key
            ),
            None,
        )

    def list_calculations(self, limit: int = 100) -> list[LogisticsCalculation]:
        return sorted(
            self.calculations.values(), key=lambda item: item.calculated_at, reverse=True
        )[:limit]


class SqlLogisticsStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def save_rate_card(self, rate_card: LogisticsRateCard) -> LogisticsRateCard:
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
        columns = ", ".join(values)
        parameters = ", ".join(f":{key}" for key in values)
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    f"INSERT INTO logistics_rate_cards ({columns}) VALUES ({parameters}) "
                    "ON CONFLICT (rate_card_hash) DO NOTHING"
                ),
                values,
            )
            row = connection.execute(
                text("SELECT * FROM logistics_rate_cards WHERE rate_card_hash=:value"),
                {"value": rate_card.rate_card_hash},
            ).mappings().one()
        return self._rate_card(row)

    def get_rate_card(self, rate_card_id: str) -> LogisticsRateCard:
        with self.engine.connect() as connection:
            row = connection.execute(
                text("SELECT * FROM logistics_rate_cards WHERE id=:id"), {"id": rate_card_id}
            ).mappings().first()
        if row is None:
            raise KeyError(f"Unknown logistics rate card: {rate_card_id}")
        return self._rate_card(row)

    def list_rate_cards(self, limit: int = 100) -> list[LogisticsRateCard]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text("SELECT * FROM logistics_rate_cards ORDER BY created_at DESC LIMIT :limit"),
                {"limit": limit},
            ).mappings().all()
        return [self._rate_card(row) for row in rows]

    def save_calculation(self, calculation: LogisticsCalculation) -> LogisticsCalculation:
        values = {
            key: value
            for key, value in asdict(calculation).items()
            if key != "calculated_at"
        }
        values["calculated_at"] = _utc(calculation.calculated_at, "calculated_at")
        columns = ", ".join(values)
        parameters = ", ".join(f":{key}" for key in values)
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    f"INSERT INTO logistics_calculations ({columns}) VALUES ({parameters}) "
                    "ON CONFLICT (rate_card_id, idempotency_key) DO NOTHING"
                ),
                values,
            )
            row = connection.execute(
                text(
                    "SELECT * FROM logistics_calculations "
                    "WHERE rate_card_id=:rate_card_id AND idempotency_key=:idempotency_key"
                ),
                values,
            ).mappings().one()
        stored = self._calculation(row)
        if stored.input_hash != calculation.input_hash:
            raise ValueError("Logistics idempotency key already belongs to different inputs")
        return stored

    def get_calculation(self, calculation_id: str) -> LogisticsCalculation:
        with self.engine.connect() as connection:
            row = connection.execute(
                text("SELECT * FROM logistics_calculations WHERE id=:id"),
                {"id": calculation_id},
            ).mappings().first()
        if row is None:
            raise KeyError(f"Unknown logistics calculation: {calculation_id}")
        return self._calculation(row)

    def find_calculation(
        self, rate_card_id: str, idempotency_key: str
    ) -> LogisticsCalculation | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT * FROM logistics_calculations "
                    "WHERE rate_card_id=:rate_card_id AND idempotency_key=:idempotency_key"
                ),
                {"rate_card_id": rate_card_id, "idempotency_key": idempotency_key},
            ).mappings().first()
        return self._calculation(row) if row else None

    def list_calculations(self, limit: int = 100) -> list[LogisticsCalculation]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT * FROM logistics_calculations "
                    "ORDER BY calculated_at DESC LIMIT :limit"
                ),
                {"limit": limit},
            ).mappings().all()
        return [self._calculation(row) for row in rows]

    @staticmethod
    def _rate_card(row) -> LogisticsRateCard:
        values = dict(row)
        for field in ("effective_at", "effective_until", "created_at"):
            values[field] = _iso(values[field])
        return LogisticsRateCard(**values)

    @staticmethod
    def _calculation(row) -> LogisticsCalculation:
        values = dict(row)
        values["calculated_at"] = _iso(values["calculated_at"])
        return LogisticsCalculation(**values)


class LogisticsQuoteWorkspace:
    def __init__(
        self,
        store: LogisticsStore,
        evidence_validator,
        evidence_linker=None,
        evidence_resolver=None,
        fx_evidence_current_validator=None,
    ) -> None:
        self.store = store
        self.evidence_validator = evidence_validator
        self.evidence_linker = evidence_linker
        self.evidence_resolver = evidence_resolver
        self.fx_evidence_current_validator = fx_evidence_current_validator

    def capture_rate_card(self, rate_card: LogisticsRateCard) -> LogisticsRateCard:
        self.evidence_validator([rate_card.evidence_id])
        if self.evidence_resolver is None:
            raise ValueError("Logistics rate-card evidence authority is not configured")
        record = self.evidence_resolver(rate_card.evidence_id)
        source = str(record.source).strip().lower()
        grade = getattr(record.grade, "value", str(record.grade))
        if source not in RATE_CARD_EVIDENCE_SOURCES or grade not in {"A", "B"}:
            raise ValueError(
                "Logistics rate-card evidence must be an A/B-grade carrier quote"
            )
        stored = self.store.save_rate_card(rate_card)
        if self.evidence_linker:
            self.evidence_linker(
                evidence_id=stored.evidence_id,
                target_type="logistics_rate_card",
                target_id=stored.id,
                relationship="source_for",
                created_by=rate_card.captured_by,
            )
        return stored

    def get_rate_card(self, rate_card_id: str) -> LogisticsRateCard:
        return self.store.get_rate_card(rate_card_id)

    def calculate(
        self,
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
        card = self.store.get_rate_card(rate_card_id)
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
        existing = self.store.find_calculation(rate_card_id, idempotency_key.strip())
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

    def resolve_profit_cost(
        self,
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
        calculation = self.store.get_calculation(calculation_id)
        card = self.store.get_rate_card(calculation.rate_card_id)
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

    def decision_support(self, calculation_id: str) -> dict[str, object]:
        calculation = self.store.get_calculation(calculation_id)
        card = self.store.get_rate_card(calculation.rate_card_id)
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
