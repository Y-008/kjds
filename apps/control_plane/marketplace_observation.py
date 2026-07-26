from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import new_id
from .evidence import EvidenceGrade
from .sql_repository import Base

OBSERVATION_CONTRACT_VERSION = "marketplace-observation/1.0.0"
PILOT_CONTRACT_VERSION = "portfolio-pilot/1.0.0"
OBSERVATION_SOURCE = "marketplace-observation"
SOURCE_PROFILES = {
    "browser_observation",
    "seller_tool_export",
    "manual_verified_public_page",
}
MARKETPLACES = {"1688", "ozon"}
PRICE_KINDS = {
    "public_display_price",
    "new_customer_price",
    "member_price",
    "range_minimum",
    "marketplace_listing_price",
}
MONEY = Decimal("0.01")

SCREENING_POLICIES: dict[str, dict[str, Any]] = {
    "ozon-cny-research-screening-v1": {
        "id": "ozon-cny-research-screening-v1",
        "currency": "CNY",
        "base": {
            "variable_rate": Decimal("0.37"),
            "fixed_reserve_cny": Decimal("400"),
        },
        "downside": {
            "variable_rate": Decimal("0.60"),
            "fixed_reserve_cny": Decimal("800"),
        },
        "assumption_breakdown": {
            "base": {
                "platform_fee_rate": "0.18",
                "advertising_rate": "0.06",
                "return_rate": "0.04",
                "tax_rate": "0.06",
                "fx_buffer_rate": "0.02",
                "loss_rate": "0.01",
                "logistics_packaging_reserve_cny": "400",
            },
            "downside": {
                "platform_fee_rate": "0.20",
                "advertising_rate": "0.10",
                "return_rate": "0.12",
                "tax_rate": "0.10",
                "fx_buffer_rate": "0.05",
                "loss_rate": "0.03",
                "logistics_packaging_reserve_cny": "800",
            },
        },
        "authority": "research_policy_only",
        "supplier_offer_created": False,
        "actual_cost_created": False,
    }
}


class MarketplaceObservationSnapshotRow(Base):
    __tablename__ = "marketplace_observation_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "source_profile",
            "idempotency_key",
            name="uq_marketplace_observation_idempotency",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_profile: Mapped[str] = mapped_column(String, nullable=False)
    marketplace: Mapped[str] = mapped_column(String, nullable=False)
    store_ref: Mapped[str] = mapped_column(String, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False)
    snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    contract_version: Mapped[str] = mapped_column(String, nullable=False)
    evidence_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_records.id"), nullable=False
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    captured_by: Mapped[str] = mapped_column(String, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    item_count: Mapped[int] = mapped_column(Integer, nullable=False)


class MarketplaceObservationItemRow(Base):
    __tablename__ = "marketplace_observation_items"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_id",
            "fingerprint",
            name="uq_marketplace_observation_item_fingerprint",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("marketplace_observation_snapshots.id"), nullable=False
    )
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    item_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    external_item_id: Mapped[str] = mapped_column(String, nullable=False)
    supplier_ref: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    variant_key: Mapped[str] = mapped_column(String, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    displayed_price_decimal: Mapped[Decimal] = mapped_column(
        Numeric(38, 12), nullable=False
    )
    price_kind: Mapped[str] = mapped_column(String, nullable=False)
    min_order_quantity: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    availability: Mapped[str] = mapped_column(String, nullable=False)
    specifications_json: Mapped[dict[str, str]] = mapped_column(
        JSON, nullable=False
    )
    target_product_id: Mapped[str | None] = mapped_column(
        String, nullable=True
    )
    target_offer_id: Mapped[str | None] = mapped_column(
        String, nullable=True
    )
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    evidence_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_records.id"), nullable=False
    )


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _required_text(value: Any, field: str, *, max_length: int) -> str:
    text = str(value or "").strip()
    if not text or len(text) > max_length:
        raise ValueError(f"{field} must be 1 to {max_length} characters")
    return text


def _optional_text(value: Any, field: str, *, max_length: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) > max_length:
        raise ValueError(f"{field} must be at most {max_length} characters")
    return text


def _timestamp(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def _url(value: Any, field: str) -> str:
    text = _required_text(value, field, max_length=2000)
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field} must be an HTTP(S) URL")
    return text


def _currency(value: Any) -> str:
    currency = str(value or "").strip().upper()
    if (
        len(currency) != 3
        or not currency.isascii()
        or not currency.isalpha()
    ):
        raise ValueError("currency must be a three-letter ISO code")
    return currency


def _positive_decimal(value: Any, field: str) -> Decimal:
    try:
        amount = Decimal(str(value))
    except Exception as exc:
        raise ValueError(f"{field} must be a decimal value") from exc
    if not amount.is_finite() or amount <= 0:
        raise ValueError(f"{field} must be positive and finite")
    return amount


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


class MarketplaceObservationWorkspace:
    """Capture research observations without promoting price or product facts."""

    def __init__(self, *, engine, evidence) -> None:
        self.engine = engine
        self.evidence = evidence

    def capture(
        self,
        request: dict[str, Any],
        *,
        actor_id: str,
    ) -> dict[str, Any]:
        actor = _required_text(actor_id, "actor_id", max_length=160)
        if request.get("confirmed") is not True:
            raise ValueError(
                "Marketplace observation requires explicit operator confirmation"
            )
        source_profile = _required_text(
            request.get("source_profile"),
            "source_profile",
            max_length=80,
        )
        if source_profile not in SOURCE_PROFILES:
            raise ValueError("Unknown marketplace observation source profile")
        marketplace = _required_text(
            request.get("marketplace"), "marketplace", max_length=40
        ).lower()
        if marketplace not in MARKETPLACES:
            raise ValueError("Unsupported marketplace observation marketplace")
        store_ref = _required_text(
            request.get("store_ref") or "external",
            "store_ref",
            max_length=160,
        )
        source_url = _url(request.get("source_url"), "source_url")
        observed_at = _timestamp(request.get("observed_at"), "observed_at")
        idempotency_key = _required_text(
            request.get("idempotency_key"),
            "idempotency_key",
            max_length=160,
        )
        items_input = request.get("items")
        if not isinstance(items_input, list) or not 1 <= len(items_input) <= 1000:
            raise ValueError("Marketplace observation requires 1 to 1000 items")

        normalized_items: list[dict[str, Any]] = []
        fingerprints: set[str] = set()
        for raw in items_input:
            if not isinstance(raw, dict):
                raise ValueError("Marketplace observation items must be objects")
            item_source_url = _url(
                raw.get("source_url") or source_url, "item.source_url"
            )
            price_kind = _required_text(
                raw.get("price_kind"), "price_kind", max_length=80
            )
            if price_kind not in PRICE_KINDS:
                raise ValueError("Unknown marketplace observation price kind")
            specifications = raw.get("specifications") or {}
            if not isinstance(specifications, dict) or len(specifications) > 80:
                raise ValueError("specifications must be an object with at most 80 keys")
            normalized_specs = {
                _required_text(key, "specification key", max_length=100): _required_text(
                    value, "specification value", max_length=500
                )
                for key, value in specifications.items()
            }
            moq_value = raw.get("min_order_quantity")
            moq = int(moq_value) if moq_value is not None else None
            if moq is not None and moq < 1:
                raise ValueError("min_order_quantity must be positive")
            natural_key = {
                "marketplace": marketplace,
                "supplier_ref": _required_text(
                    raw.get("supplier_ref"), "supplier_ref", max_length=240
                ),
                "external_item_id": _required_text(
                    raw.get("external_item_id"),
                    "external_item_id",
                    max_length=240,
                ),
                "variant_key": _required_text(
                    raw.get("variant_key"), "variant_key", max_length=500
                ),
            }
            fingerprint = _sha256(natural_key)
            if fingerprint in fingerprints:
                raise ValueError(
                    "Marketplace observation contains duplicate natural keys"
                )
            fingerprints.add(fingerprint)
            item = {
                **natural_key,
                "fingerprint": fingerprint,
                "title": _required_text(
                    raw.get("title"), "title", max_length=2000
                ),
                "currency": _currency(raw.get("currency")),
                "displayed_price": format(
                    _positive_decimal(
                        raw.get("displayed_price"), "displayed_price"
                    ),
                    "f",
                ),
                "price_kind": price_kind,
                "min_order_quantity": moq,
                "availability": _required_text(
                    raw.get("availability") or "unknown",
                    "availability",
                    max_length=80,
                ),
                "specifications": normalized_specs,
                "target_product_id": _optional_text(
                    raw.get("target_product_id"),
                    "target_product_id",
                    max_length=160,
                ),
                "target_offer_id": _optional_text(
                    raw.get("target_offer_id"),
                    "target_offer_id",
                    max_length=160,
                ),
                "source_url": item_source_url,
            }
            item["item_sha256"] = _sha256(item)
            normalized_items.append(item)
        normalized_items.sort(key=lambda item: item["fingerprint"])

        artifact = {
            "contract_version": OBSERVATION_CONTRACT_VERSION,
            "source_profile": source_profile,
            "marketplace": marketplace,
            "store_ref": store_ref,
            "source_url": source_url,
            "observed_at": _iso(observed_at),
            "idempotency_key": idempotency_key,
            "capture_note": _optional_text(
                request.get("capture_note"),
                "capture_note",
                max_length=4000,
            ),
            "items": normalized_items,
            "control_envelope": {
                "formal_fact_promoted": False,
                "supplier_offer_created": False,
                "actual_cost_created": False,
                "external_write_allowed": False,
            },
        }
        artifact_bytes = _canonical_json(artifact)
        evidence_record = self.evidence.capture(
            content=artifact_bytes,
            filename=f"marketplace-observation-{idempotency_key}.json",
            content_type="application/json",
            source=OBSERVATION_SOURCE,
            source_ref=f"{source_profile}:{idempotency_key}",
            grade=EvidenceGrade.C,
            effective_at=_iso(observed_at),
            effective_until=None,
            created_by=actor,
            metadata={
                "retention_class": "operational",
                "contract_version": OBSERVATION_CONTRACT_VERSION,
                "marketplace": marketplace,
                "store_ref": store_ref,
                "source_url": source_url,
                "formal_fact_promoted": False,
                "price_authority": "research_only",
            },
        )
        snapshot_payload = {
            **artifact,
            "evidence_id": evidence_record.id,
        }
        snapshot_hash = _sha256(snapshot_payload)
        captured_at = datetime.now(UTC)
        snapshot_id = new_id("mos")
        try:
            with Session(
                self.engine, expire_on_commit=False
            ) as session, session.begin():
                existing = session.scalar(
                    select(MarketplaceObservationSnapshotRow).where(
                        MarketplaceObservationSnapshotRow.source_profile
                        == source_profile,
                        MarketplaceObservationSnapshotRow.idempotency_key
                        == idempotency_key,
                    )
                )
                if existing is not None:
                    if existing.snapshot_sha256 != snapshot_hash:
                        raise ValueError(
                            "Marketplace observation idempotency conflict"
                        )
                    return self._snapshot(session, existing)
                snapshot = MarketplaceObservationSnapshotRow(
                    id=snapshot_id,
                    source_profile=source_profile,
                    marketplace=marketplace,
                    store_ref=store_ref,
                    source_url=source_url,
                    idempotency_key=idempotency_key,
                    snapshot_sha256=snapshot_hash,
                    contract_version=OBSERVATION_CONTRACT_VERSION,
                    evidence_id=evidence_record.id,
                    observed_at=observed_at,
                    captured_by=actor,
                    captured_at=captured_at,
                    item_count=len(normalized_items),
                )
                session.add(snapshot)
                # The rows intentionally do not expose an ORM relationship. Flush
                # the immutable parent first so PostgreSQL can enforce the FK
                # without relying on unit-of-work dependency inference.
                session.flush()
                for item in normalized_items:
                    session.add(
                        MarketplaceObservationItemRow(
                            id=new_id("moi"),
                            snapshot_id=snapshot_id,
                            fingerprint=item["fingerprint"],
                            item_sha256=item["item_sha256"],
                            external_item_id=item["external_item_id"],
                            supplier_ref=item["supplier_ref"],
                            title=item["title"],
                            variant_key=item["variant_key"],
                            currency=item["currency"],
                            displayed_price_decimal=Decimal(
                                item["displayed_price"]
                            ),
                            price_kind=item["price_kind"],
                            min_order_quantity=item["min_order_quantity"],
                            availability=item["availability"],
                            specifications_json=item["specifications"],
                            target_product_id=item["target_product_id"],
                            target_offer_id=item["target_offer_id"],
                            source_url=item["source_url"],
                            observed_at=observed_at,
                            evidence_id=evidence_record.id,
                        )
                    )
                session.flush()
                result = self._snapshot(session, snapshot)
        except IntegrityError:
            with Session(self.engine) as session:
                winner = session.scalar(
                    select(MarketplaceObservationSnapshotRow).where(
                        MarketplaceObservationSnapshotRow.source_profile
                        == source_profile,
                        MarketplaceObservationSnapshotRow.idempotency_key
                        == idempotency_key,
                    )
                )
                if winner is None:
                    raise
                if winner.snapshot_sha256 != snapshot_hash:
                    raise ValueError(
                        "Marketplace observation idempotency conflict"
                    ) from None
                result = self._snapshot(session, winner)
        self.evidence.link(
            evidence_id=evidence_record.id,
            target_type="marketplace_observation_snapshot",
            target_id=result["id"],
            relationship="observation_source",
            created_by=actor,
        )
        return result

    def latest(
        self,
        *,
        marketplace: str | None = None,
        source_profile: str | None = None,
        target_product_id: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        if not 1 <= limit <= 1000:
            raise ValueError("Marketplace observation limit must be 1 to 1000")
        query = (
            select(
                MarketplaceObservationItemRow,
                MarketplaceObservationSnapshotRow,
            )
            .join(
                MarketplaceObservationSnapshotRow,
                MarketplaceObservationSnapshotRow.id
                == MarketplaceObservationItemRow.snapshot_id,
            )
            .order_by(
                MarketplaceObservationItemRow.observed_at.desc(),
                MarketplaceObservationItemRow.id,
            )
        )
        if marketplace is not None:
            normalized_marketplace = marketplace.strip().lower()
            if normalized_marketplace not in MARKETPLACES:
                raise ValueError("Unsupported marketplace observation marketplace")
            query = query.where(
                MarketplaceObservationSnapshotRow.marketplace
                == normalized_marketplace
            )
        if source_profile is not None:
            normalized_profile = source_profile.strip()
            if normalized_profile not in SOURCE_PROFILES:
                raise ValueError("Unknown marketplace observation source profile")
            query = query.where(
                MarketplaceObservationSnapshotRow.source_profile
                == normalized_profile
            )
        if target_product_id is not None:
            target = _required_text(
                target_product_id, "target_product_id", max_length=160
            )
            query = query.where(
                MarketplaceObservationItemRow.target_product_id == target
            )
        with Session(self.engine) as session:
            rows = session.execute(query).all()
            latest_by_fingerprint: dict[str, dict[str, Any]] = {}
            for item, snapshot in rows:
                if item.fingerprint in latest_by_fingerprint:
                    continue
                latest_by_fingerprint[item.fingerprint] = self._item(
                    item, snapshot
                )
                if len(latest_by_fingerprint) >= limit:
                    break
            return list(latest_by_fingerprint.values())

    @classmethod
    def _snapshot(
        cls,
        session: Session,
        row: MarketplaceObservationSnapshotRow,
    ) -> dict[str, Any]:
        items = list(
            session.scalars(
                select(MarketplaceObservationItemRow)
                .where(
                    MarketplaceObservationItemRow.snapshot_id == row.id
                )
                .order_by(MarketplaceObservationItemRow.fingerprint)
            )
        )
        return {
            "id": row.id,
            "source_profile": row.source_profile,
            "marketplace": row.marketplace,
            "store_ref": row.store_ref,
            "source_url": row.source_url,
            "idempotency_key": row.idempotency_key,
            "snapshot_sha256": row.snapshot_sha256,
            "contract_version": row.contract_version,
            "evidence_id": row.evidence_id,
            "observed_at": _iso(row.observed_at),
            "captured_by": row.captured_by,
            "captured_at": _iso(row.captured_at),
            "item_count": row.item_count,
            "items": [cls._item(item, row) for item in items],
            "formal_fact_promoted": False,
            "supplier_offer_created": False,
            "actual_cost_created": False,
            "external_write_allowed": False,
        }

    @staticmethod
    def _item(
        item: MarketplaceObservationItemRow,
        snapshot: MarketplaceObservationSnapshotRow,
    ) -> dict[str, Any]:
        return {
            "id": item.id,
            "snapshot_id": item.snapshot_id,
            "fingerprint": item.fingerprint,
            "item_sha256": item.item_sha256,
            "source_profile": snapshot.source_profile,
            "marketplace": snapshot.marketplace,
            "store_ref": snapshot.store_ref,
            "external_item_id": item.external_item_id,
            "supplier_ref": item.supplier_ref,
            "title": item.title,
            "variant_key": item.variant_key,
            "currency": item.currency,
            "displayed_price": format(
                _money(item.displayed_price_decimal),
                "f",
            ),
            "price_kind": item.price_kind,
            "price_basis": "observed",
            "min_order_quantity": item.min_order_quantity,
            "availability": item.availability,
            "specifications": item.specifications_json,
            "target_product_id": item.target_product_id,
            "target_offer_id": item.target_offer_id,
            "source_url": item.source_url,
            "observed_at": _iso(item.observed_at),
            "evidence_id": item.evidence_id,
            "formal_fact_promoted": False,
            "supplier_offer_created": False,
            "actual_cost_created": False,
        }


class PortfolioPilotWorkspace:
    """Prepare one server-owned candidate view from existing truth modules."""

    def __init__(
        self,
        *,
        observations: MarketplaceObservationWorkspace,
        marketplace_catalog,
        sourcing,
        repository,
        operating_tasks,
    ) -> None:
        self.observations = observations
        self.marketplace_catalog = marketplace_catalog
        self.sourcing = sourcing
        self.repository = repository
        self.operating_tasks = operating_tasks

    def prepare(
        self,
        *,
        store_ref: str,
        product_id: str,
        target_specification: dict[str, str],
        policy_id: str,
        candidate_target: int,
        pilot_limit: int,
        max_loss_cny: Decimal,
        cm3_floor_cny: Decimal,
        actor_id: str,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        store = _required_text(store_ref, "store_ref", max_length=160)
        product_ref = _required_text(
            product_id, "product_id", max_length=160
        )
        actor = _required_text(actor_id, "actor_id", max_length=160)
        if policy_id not in SCREENING_POLICIES:
            raise ValueError("Unknown portfolio pilot screening policy")
        if not 1 <= candidate_target <= 1000:
            raise ValueError("candidate_target must be 1 to 1000")
        if not 1 <= pilot_limit <= min(candidate_target, 100):
            raise ValueError("pilot_limit must be 1 to candidate_target and at most 100")
        if (
            not max_loss_cny.is_finite()
            or max_loss_cny <= 0
            or not cm3_floor_cny.is_finite()
        ):
            raise ValueError("Pilot loss and CM3 limits must be finite")
        if not isinstance(target_specification, dict) or not target_specification:
            raise ValueError("target_specification must be a non-empty object")
        if len(target_specification) > 80:
            raise ValueError("target_specification is limited to 80 keys")
        required_specs = {
            _required_text(key, "target specification key", max_length=100):
            _required_text(value, "target specification value", max_length=500)
            for key, value in target_specification.items()
        }
        now = _timestamp(as_of, "as_of") if as_of else datetime.now(UTC)
        product = self.repository.get_product(product_ref)
        catalog_items = self.marketplace_catalog.latest_items(
            store_ref=store, limit=1000
        )
        target_item = next(
            (
                item
                for item in catalog_items
                if item.get("canonical_product_id") == product_ref
            ),
            None,
        )
        if target_item is None:
            raise ValueError(
                "Portfolio pilot requires a current bound marketplace listing"
            )
        prices = target_item.get("prices") or {}
        sale_price = _positive_decimal(
            prices.get("price"), "catalog listing price"
        )
        sale_currency = _currency(target_item.get("currency_code"))
        policy = SCREENING_POLICIES[policy_id]
        candidates = self.observations.latest(
            marketplace="1688",
            target_product_id=product_ref,
            limit=candidate_target,
        )
        comparison = self.sourcing.compare_product_offers(product_ref)
        scenario_by_external: dict[tuple[str, str], dict[str, Any]] = {}
        for row in comparison["rows"]:
            offer = row["offer"]
            scenario = row["scenario"]
            scenario_by_external[
                (offer.supplier_ref, offer.external_id)
            ] = {
                "offer_id": offer.id,
                "scenario_id": scenario.id if scenario else None,
                "cm3_cny": str(scenario.cm3_cny) if scenario else None,
                "release_ready": bool(
                    scenario and self.sourcing.release_ready(scenario)
                ),
            }

        ranked: list[dict[str, Any]] = []
        all_evidence_ids: set[str] = set()
        for candidate in candidates:
            all_evidence_ids.add(candidate["evidence_id"])
            matched, missing, mismatched = self._specification_gap(
                required_specs,
                candidate["specifications"],
            )
            same_currency = candidate["currency"] == sale_currency
            observed_cost = Decimal(candidate["displayed_price"])
            observed_spread = (
                _money(sale_price - observed_cost)
                if same_currency
                else None
            )
            base_contribution = None
            downside_contribution = None
            if same_currency and sale_currency == policy["currency"]:
                base_contribution = self._screen(
                    sale_price, observed_cost, policy["base"]
                )
                downside_contribution = self._screen(
                    sale_price, observed_cost, policy["downside"]
                )
            scenario = scenario_by_external.get(
                (candidate["supplier_ref"], candidate["external_item_id"])
            )
            blockers: list[str] = []
            if not same_currency:
                blockers.append("cross_currency_fx_missing")
            if missing:
                blockers.append("required_specifications_missing")
            if mismatched:
                blockers.append("required_specifications_mismatch")
            if (
                downside_contribution is None
                or downside_contribution <= cm3_floor_cny
            ):
                blockers.append("downside_screening_contribution_not_positive")
            estimated_downside_loss = (
                max(Decimal("0"), -downside_contribution)
                if downside_contribution is not None
                else None
            )
            if (
                estimated_downside_loss is None
                or estimated_downside_loss > max_loss_cny
            ):
                blockers.append("pilot_loss_exceeds_budget")
            if scenario is None or not scenario["release_ready"]:
                blockers.append("full_cost_profit_scenario_missing")
            pilot_ready = not blockers
            state = (
                "ready"
                if pilot_ready
                else "blocked"
                if mismatched
                or (
                    downside_contribution is not None
                    and downside_contribution <= cm3_floor_cny
                )
                or (
                    estimated_downside_loss is not None
                    and estimated_downside_loss > max_loss_cny
                )
                else "partial"
            )
            ranked.append(
                {
                    **candidate,
                    "target": {
                        "product_id": product.id,
                        "offer_id": target_item["offer_id"],
                        "marketplace_sku": target_item["marketplace_sku"],
                    },
                    "specification_match": {
                        "status": (
                            "exact"
                            if not missing and not mismatched
                            else "mismatch"
                            if mismatched
                            else "partial"
                        ),
                        "matched": matched,
                        "missing": missing,
                        "mismatched": mismatched,
                    },
                    "economics": {
                        "currency": sale_currency,
                        "listing_price": format(sale_price, "f"),
                        "observed_display_price": candidate[
                            "displayed_price"
                        ],
                        "observed_spread": (
                            str(observed_spread)
                            if observed_spread is not None
                            else None
                        ),
                        "screening_contribution_base": (
                            str(base_contribution)
                            if base_contribution is not None
                            else None
                        ),
                        "screening_contribution_downside": (
                            str(downside_contribution)
                            if downside_contribution is not None
                            else None
                        ),
                        "estimated_downside_loss": (
                            str(estimated_downside_loss)
                            if estimated_downside_loss is not None
                            else None
                        ),
                        "scenario_cm3": (
                            scenario["cm3_cny"] if scenario else None
                        ),
                        "actual_profit": None,
                        "policy_id": policy_id,
                        "authority": "research_screening_only",
                    },
                    "state": state,
                    "pilot_ready": pilot_ready,
                    "blockers": blockers,
                    "next_action": self._next_action(
                        missing=missing,
                        mismatched=mismatched,
                        downside_contribution=downside_contribution,
                        cm3_floor_cny=cm3_floor_cny,
                        scenario=scenario,
                    ),
                    "automatic_supplier_contact": False,
                    "automatic_listing": False,
                    "external_write_allowed": False,
                }
            )
        ranked.sort(
            key=lambda item: (
                0
                if item["state"] == "ready"
                else 1
                if item["state"] == "partial"
                else 2,
                0
                if item["specification_match"]["status"] == "exact"
                else 1
                if item["specification_match"]["status"] == "partial"
                else 2,
                -Decimal(
                    item["economics"]["screening_contribution_downside"]
                    or "-999999999"
                ),
                item["fingerprint"],
            )
        )
        selected = ranked[:pilot_limit]
        blockers = sorted(
            {blocker for candidate in selected for blocker in candidate["blockers"]}
        )
        task = None
        if blockers:
            task = self.operating_tasks.ensure_internal_task(
                task_kind="portfolio_pilot_blocked",
                scope={
                    "store_ref": store,
                    "product_id": product_ref,
                    "offer_id": target_item["offer_id"],
                },
                title=f"组合 Pilot 阻断 · {product.name}",
                severity="high",
                owner="supply",
                evidence_ids=sorted(all_evidence_ids),
                snapshot={
                    "blockers": blockers,
                    "candidate_count": len(ranked),
                    "next_action": (
                        "完成精确规格询价并补齐版本化十五项成本场景"
                    ),
                    "as_of": _iso(now),
                },
                actor_id=actor,
            )
        payload = {
            "contract_version": PILOT_CONTRACT_VERSION,
            "store_ref": store,
            "product": {
                "id": product.id,
                "sku": product.sku,
                "name": product.name,
            },
            "target_listing": {
                "offer_id": target_item["offer_id"],
                "marketplace_sku": target_item["marketplace_sku"],
                "price": format(sale_price, "f"),
                "currency": sale_currency,
                "stock": target_item["available_stock"],
                "item_hash": target_item["item_hash"],
            },
            "policy": {
                "id": policy_id,
                "assumption_breakdown": policy["assumption_breakdown"],
                "authority": policy["authority"],
            },
            "limits": {
                "candidate_target": candidate_target,
                "pilot_limit": pilot_limit,
                "max_loss_cny": str(max_loss_cny),
                "cm3_floor_cny": str(cm3_floor_cny),
            },
            "counts": {
                "observed": len(candidates),
                "screened": len(ranked),
                "positive_lower_bound": sum(
                    Decimal(
                        item["economics"][
                            "screening_contribution_downside"
                        ]
                        or "0"
                    )
                    > cm3_floor_cny
                    for item in ranked
                ),
                "draft_ready": sum(
                    bool(
                        item["economics"]["scenario_cm3"]
                        and not item["specification_match"]["missing"]
                        and not item["specification_match"]["mismatched"]
                    )
                    for item in ranked
                ),
                "pilot_ready": sum(item["pilot_ready"] for item in ranked),
            },
            "ranked_candidates": selected,
            "blockers": blockers,
            "operating_task": task,
            "next_action": (
                "冻结可执行 Pilot 批次"
                if not blockers
                else "完成精确规格询价并补齐十五项成本证据"
            ),
            "as_of": _iso(now),
            "actual_profit_available": False,
            "automatic_supplier_contact": False,
            "automatic_listing": False,
            "external_write_allowed": False,
        }
        payload["snapshot_sha256"] = _sha256(payload)
        payload["run_id"] = f"ppr_{payload['snapshot_sha256'][:24]}"
        return payload

    @staticmethod
    def _screen(
        revenue: Decimal,
        observed_cost: Decimal,
        policy_case: dict[str, Decimal],
    ) -> Decimal:
        return _money(
            revenue
            - observed_cost
            - _money(revenue * policy_case["variable_rate"])
            - policy_case["fixed_reserve_cny"]
        )

    @staticmethod
    def _specification_gap(
        required: dict[str, str],
        observed: dict[str, str],
    ) -> tuple[list[str], list[str], list[dict[str, str]]]:
        matched: list[str] = []
        missing: list[str] = []
        mismatched: list[dict[str, str]] = []
        for key, required_value in sorted(required.items()):
            observed_value = observed.get(key)
            if observed_value is None:
                missing.append(key)
            elif observed_value.strip().casefold() == required_value.strip().casefold():
                matched.append(key)
            else:
                mismatched.append(
                    {
                        "key": key,
                        "required": required_value,
                        "observed": observed_value,
                    }
                )
        return matched, missing, mismatched

    @staticmethod
    def _next_action(
        *,
        missing: list[str],
        mismatched: list[dict[str, str]],
        downside_contribution: Decimal | None,
        cm3_floor_cny: Decimal,
        scenario: dict[str, Any] | None,
    ) -> str:
        if missing or mismatched:
            return "向供应商确认精确规格、功率、控制方式、插头和包装"
        if (
            downside_contribution is None
            or downside_contribution <= cm3_floor_cny
        ):
            return "淘汰或重新谈价，悲观筛选贡献未过线"
        if scenario is None or not scenario["release_ready"]:
            return "把正式报价、物流和其余成本证据写入十五项 CM3"
        return "生成冻结 Pilot 批次并进入既有批准与执行链"
