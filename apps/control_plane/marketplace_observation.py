from __future__ import annotations

import hashlib
import json
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    and_,
    or_,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import new_id
from .evidence import EvidenceGrade
from .marketplace_sources import OBSERVATION_MARKETPLACES
from .sql_repository import Base

OBSERVATION_CONTRACT_VERSION = "marketplace-observation/1.3.0"
PILOT_CONTRACT_VERSION = "portfolio-pilot/1.0.0"
OBSERVATION_SOURCE = "marketplace-observation"
SOURCE_PROFILES = {
    "browser_observation",
    "seller_tool_export",
    "manual_verified_public_page",
    "public_search_index_observation",
}
MARKETPLACES = {"1688", "ozon"}
READ_MARKETPLACES = OBSERVATION_MARKETPLACES
PRICE_KINDS = {
    "public_display_price",
    "new_customer_price",
    "member_price",
    "range_minimum",
    "marketplace_listing_price",
    "observed_checkout_price",
}
PRICE_SCOPES = {"unit_price", "checkout_total"}
MEDIA_RIGHTS_STATUSES = {
    "unverified_external_reference",
    "supplier_authorized",
    "owned",
    "licensed",
}
MONEY = Decimal("0.01")
UNRESOLVED_IDENTITY_VALUES = frozenset(
    {
        "unknown",
        "unspecified",
        "unverified",
        "pending",
        "pending_confirmation",
        "not_confirmed",
        "n/a",
        "na",
        "null",
        "none",
        "未知",
        "未确认",
        "待确认",
        "不详",
    }
)
EXACT_IDENTITY_REQUIRED_FIELDS: dict[str, frozenset[str]] = {
    "under_desk_cable_tray": frozenset(
        {
            "product_type",
            "quantity",
            "construction",
            "mounting",
            "length",
            "width",
            "height",
            "color",
        }
    ),
}


def exact_identity_complete(
    product_identity: dict[str, Any] | None,
    variant_key: str | None,
) -> bool:
    """Return true only when identity and variant contain no placeholders."""
    if not product_identity or not variant_key:
        return False
    product_type = str(product_identity.get("product_type") or "").strip()
    required_fields = EXACT_IDENTITY_REQUIRED_FIELDS.get(product_type)
    if required_fields and not required_fields.issubset(product_identity):
        return False
    values = [*product_identity.keys(), *product_identity.values(), variant_key]
    return all(
        str(value).strip().lower() not in UNRESOLVED_IDENTITY_VALUES
        for value in values
    )

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
        CheckConstraint(
            "("
            "tenant_ref IS NULL AND entity_ref IS NULL "
            "AND scope_grant_authority_sha256 IS NULL "
            "AND scope_as_of IS NULL AND adapter_id IS NULL "
            "AND adapter_version IS NULL "
            "AND adapter_contract_sha256 IS NULL "
            "AND source_grade IS NULL "
            "AND semantic_authority IS NULL "
            "AND source_evidence_ids_json IS NULL"
            ") OR ("
            "tenant_ref IS NOT NULL AND entity_ref IS NOT NULL "
            "AND scope_grant_authority_sha256 IS NOT NULL "
            "AND length(scope_grant_authority_sha256) = 64 "
            "AND scope_as_of IS NOT NULL AND adapter_id IS NOT NULL "
            "AND adapter_version IS NOT NULL "
            "AND adapter_contract_sha256 IS NOT NULL "
            "AND length(adapter_contract_sha256) = 64 "
            "AND source_grade IN ('A','B','C','D') "
            "AND semantic_authority IS NOT NULL "
            "AND source_evidence_ids_json IS NOT NULL"
            ")",
            name="ck_marketplace_observation_scope_adapter_complete",
        ),
        Index(
            "uq_marketplace_observation_legacy_idempotency",
            "source_profile",
            "idempotency_key",
            unique=True,
            sqlite_where=text("tenant_ref IS NULL"),
            postgresql_where=text("tenant_ref IS NULL"),
        ),
        Index(
            "uq_marketplace_observation_scoped_idempotency",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "source_profile",
            "idempotency_key",
            unique=True,
            sqlite_where=text("tenant_ref IS NOT NULL"),
            postgresql_where=text("tenant_ref IS NOT NULL"),
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
    tenant_ref: Mapped[str | None] = mapped_column(
        String(160), nullable=True
    )
    entity_ref: Mapped[str | None] = mapped_column(
        String(160), nullable=True
    )
    scope_grant_authority_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    scope_as_of: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    adapter_id: Mapped[str | None] = mapped_column(
        String(160), nullable=True
    )
    adapter_version: Mapped[str | None] = mapped_column(
        String(80), nullable=True
    )
    adapter_contract_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    source_grade: Mapped[str | None] = mapped_column(
        String(1), nullable=True
    )
    semantic_authority: Mapped[str | None] = mapped_column(
        String(160), nullable=True
    )
    source_evidence_ids_json: Mapped[list[str] | None] = mapped_column(
        JSON(none_as_null=True), nullable=True
    )


class MarketplaceObservationItemRow(Base):
    __tablename__ = "marketplace_observation_items"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_id",
            "fingerprint",
            name="uq_marketplace_observation_item_fingerprint",
        ),
        CheckConstraint(
            "price_scope IN ('unit_price','checkout_total')",
            name="ck_marketplace_observation_price_scope",
        ),
        CheckConstraint(
            "unit_price_decimal > 0",
            name="ck_marketplace_observation_unit_price_positive",
        ),
        CheckConstraint(
            "(price_scope = 'unit_price' AND "
            "unit_price_decimal = displayed_price_decimal) OR "
            "(price_scope = 'checkout_total' AND "
            "observed_quantity IS NOT NULL AND "
            "abs(unit_price_decimal * observed_quantity - "
            "displayed_price_decimal) <= 0.000001)",
            name="ck_marketplace_observation_unit_price_semantics",
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
    price_scope: Mapped[str] = mapped_column(
        String, nullable=False, default="unit_price"
    )
    unit_price_decimal: Mapped[Decimal] = mapped_column(
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
    candidate_key: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    product_identity_json: Mapped[dict[str, str]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    observed_quantity: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    checkout_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    tax_included: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True
    )
    domestic_freight_included: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True
    )
    purchase_available: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    confidence_decimal: Mapped[Decimal] = mapped_column(
        Numeric(8, 6), nullable=False, default=Decimal("0.5")
    )
    market_signals_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    supply_signals_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    media_rights_status: Mapped[str] = mapped_column(
        String, nullable=False, default="unverified_external_reference"
    )
    experiment_readbacks_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
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


def exact_candidate_key(
    product_identity: dict[str, Any] | None,
    variant_key: str | None,
) -> str | None:
    """Return the one canonical exact identity+variant cohort key."""
    if not exact_identity_complete(product_identity, variant_key):
        return None
    return _sha256(
        {
            "product_identity": product_identity,
            "variant_key": variant_key,
        }
    )


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


def _adapter_url(
    value: str,
    *,
    adapter: dict[str, Any],
    field: str,
) -> None:
    host = (urlparse(value).hostname or "").lower().rstrip(".")
    allowed = {
        str(item).strip().lower().rstrip(".")
        for item in adapter.get("allowed_hosts", [])
        if str(item).strip()
    }
    if not allowed or not any(
        host == suffix or host.endswith(f".{suffix}")
        for suffix in allowed
    ):
        raise ValueError(
            f"{field} host is outside the frozen source adapter"
        )


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


def _bounded_json_object(
    value: Any,
    field: str,
    *,
    max_keys: int = 80,
    max_bytes: int = 20_000,
) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > max_keys:
        raise ValueError(f"{field} must be an object with at most {max_keys} keys")
    normalized = json.loads(json.dumps(value, ensure_ascii=False, default=str))
    if len(_canonical_json(normalized)) > max_bytes:
        raise ValueError(f"{field} exceeds {max_bytes} bytes")
    return normalized


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
        scope_authority: dict[str, Any] | None = None,
        source_contract: dict[str, Any] | None = None,
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
        if (scope_authority is None) != (source_contract is None):
            raise ValueError(
                "Scoped observation requires both scope and source authority"
            )
        scoped = scope_authority is not None
        scope: dict[str, Any] | None = None
        adapter: dict[str, Any] | None = None
        adapter_contract_sha256: str | None = None
        if scoped:
            assert scope_authority is not None
            assert source_contract is not None
            scope = {
                "tenant_ref": _required_text(
                    scope_authority.get("tenant_ref"),
                    "scope.tenant_ref",
                    max_length=160,
                ),
                "entity_ref": _required_text(
                    scope_authority.get("entity_ref"),
                    "scope.entity_ref",
                    max_length=160,
                ),
                "store_ref": _required_text(
                    scope_authority.get("store_ref"),
                    "scope.store_ref",
                    max_length=160,
                ),
                "scope_grant_authority_sha256": _required_text(
                    scope_authority.get(
                        "scope_grant_authority_sha256"
                    ),
                    "scope.scope_grant_authority_sha256",
                    max_length=64,
                ),
                "scope_as_of": _iso(
                    _timestamp(
                        scope_authority.get("scope_as_of"),
                        "scope.scope_as_of",
                    )
                ),
            }
            if (
                len(scope["scope_grant_authority_sha256"]) != 64
                or scope["store_ref"] != store_ref
            ):
                raise ValueError(
                    "Observation scope authority does not match request"
                )
            adapter = source_contract.get("adapter")
            if not isinstance(adapter, dict):
                raise ValueError("Observation source adapter is required")
            if (
                source_contract.get("capture_allowed") is not True
                or source_contract.get("external_write_allowed") is not False
                or source_profile
                not in adapter.get("observation_profiles", [])
                or marketplace not in adapter.get("marketplaces", [])
                or adapter.get("status") != "implemented"
            ):
                raise ValueError(
                    "Observation source adapter does not authorize capture"
                )
            adapter_contract_sha256 = _required_text(
                source_contract.get("adapter_contract_sha256"),
                "adapter_contract_sha256",
                max_length=64,
            )
            if len(adapter_contract_sha256) != 64:
                raise ValueError(
                    "adapter_contract_sha256 must be SHA-256"
                )
        source_url = _url(request.get("source_url"), "source_url")
        if adapter is not None:
            _adapter_url(
                source_url,
                adapter=adapter,
                field="source_url",
            )
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
            if adapter is not None:
                _adapter_url(
                    item_source_url,
                    adapter=adapter,
                    field="item.source_url",
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
            product_identity = {
                _required_text(key, "product identity key", max_length=100):
                _required_text(value, "product identity value", max_length=500)
                for key, value in _bounded_json_object(
                    raw.get("product_identity"),
                    "product_identity",
                    max_keys=40,
                ).items()
            }
            variant_key = _required_text(
                raw.get("variant_key"), "variant_key", max_length=500
            )
            identity_complete = exact_identity_complete(
                product_identity, variant_key
            )
            candidate_key = exact_candidate_key(
                product_identity,
                variant_key,
            )
            observed_quantity_value = raw.get("observed_quantity")
            observed_quantity = (
                int(observed_quantity_value)
                if observed_quantity_value is not None
                else None
            )
            if observed_quantity is not None and observed_quantity < 1:
                raise ValueError("observed_quantity must be positive")
            raw_price_scope = raw.get("price_scope")
            if (
                price_kind == "observed_checkout_price"
                and raw_price_scope is None
            ):
                raise ValueError(
                    "observed_checkout_price requires explicit price_scope"
                )
            price_scope = str(raw_price_scope or "unit_price").strip()
            if price_scope not in PRICE_SCOPES:
                raise ValueError(
                    "price_scope must be unit_price or checkout_total"
                )
            displayed_price = _positive_decimal(
                raw.get("displayed_price"), "displayed_price"
            )
            if price_scope == "checkout_total":
                if observed_quantity is None:
                    raise ValueError(
                        "checkout_total requires observed_quantity"
                    )
                unit_price = displayed_price / Decimal(observed_quantity)
            else:
                unit_price = displayed_price
            checkout_verified = raw.get("checkout_verified") is True
            purchase_available = raw.get("purchase_available") is True
            tax_included = raw.get("tax_included")
            domestic_freight_included = raw.get(
                "domestic_freight_included"
            )
            confidence = _positive_decimal(
                raw.get("confidence", "0.5"), "confidence"
            )
            if confidence > 1:
                raise ValueError("confidence must be greater than 0 and at most 1")
            media_rights_status = _required_text(
                raw.get("media_rights_status")
                or "unverified_external_reference",
                "media_rights_status",
                max_length=80,
            )
            if media_rights_status not in MEDIA_RIGHTS_STATUSES:
                raise ValueError("Unknown media_rights_status")
            natural_key = {
                "store_ref": store_ref,
                "marketplace": marketplace,
                "supplier_ref": _required_text(
                    raw.get("supplier_ref"), "supplier_ref", max_length=240
                ),
                "external_item_id": _required_text(
                    raw.get("external_item_id"),
                    "external_item_id",
                    max_length=240,
                ),
                "variant_key": variant_key,
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
                "displayed_price": format(displayed_price, "f"),
                "price_scope": price_scope,
                "unit_price": format(unit_price, "f"),
                "price_contract": (
                    "displayed_price_scope_and_server_derived_unit_price/v1"
                ),
                "price_kind": price_kind,
                "min_order_quantity": moq,
                "candidate_key": candidate_key,
                "product_identity": product_identity,
                "identity_resolution_status": (
                    "exact" if identity_complete else "unresolved"
                ),
                "observed_quantity": observed_quantity,
                "checkout_verified": checkout_verified,
                "tax_included": tax_included,
                "domestic_freight_included": (
                    domestic_freight_included
                ),
                "purchase_available": purchase_available,
                "confidence": format(confidence, "f"),
                "market_signals": _bounded_json_object(
                    raw.get("market_signals"),
                    "market_signals",
                ),
                "supply_signals": _bounded_json_object(
                    raw.get("supply_signals"),
                    "supply_signals",
                ),
                "media_rights_status": media_rights_status,
                "experiment_readbacks": _bounded_json_object(
                    raw.get("experiment_readbacks"),
                    "experiment_readbacks",
                    max_keys=20,
                ),
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
            if price_kind == "observed_checkout_price":
                if marketplace != "1688":
                    raise ValueError(
                        "observed_checkout_price is only supported for 1688"
                    )
                if (
                    not identity_complete
                    or observed_quantity is None
                    or not checkout_verified
                    or not purchase_available
                    or tax_included is None
                    or domestic_freight_included is None
                ):
                    raise ValueError(
                        "observed_checkout_price requires exact identity, "
                        "quantity, checkout verification, purchasability, "
                        "and explicit tax/freight boundaries"
                    )
                if moq is not None and observed_quantity < moq:
                    raise ValueError(
                        "observed checkout quantity cannot be below MOQ"
                    )
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
            "scope_authority": scope,
            "source_adapter": (
                {
                    **adapter,
                    "adapter_contract_sha256": adapter_contract_sha256,
                    "source_grade": adapter["max_source_grade"],
                    "source_evidence_ids": [],
                }
                if adapter is not None
                else None
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
            source_ref=(
                (
                    f"{scope['tenant_ref']}:{scope['entity_ref']}:"
                    f"{scope['store_ref']}:{source_profile}:"
                    f"{idempotency_key}"
                )
                if scope
                else f"{source_profile}:{idempotency_key}"
            ),
            grade=(
                EvidenceGrade(adapter["max_source_grade"])
                if adapter is not None
                else EvidenceGrade.C
            ),
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
                "tenant_ref": scope["tenant_ref"] if scope else None,
                "entity_ref": scope["entity_ref"] if scope else None,
                "scope_grant_authority_sha256": (
                    scope["scope_grant_authority_sha256"]
                    if scope
                    else None
                ),
                "adapter_id": (
                    adapter["adapter_id"] if adapter else None
                ),
                "adapter_contract_sha256": adapter_contract_sha256,
                "semantic_authority": (
                    adapter["semantic_authority"] if adapter else None
                ),
                "evidence_scope_status": (
                    "pending_independent_binding"
                    if scope
                    else "legacy_unscoped"
                ),
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
                existing_query = select(
                    MarketplaceObservationSnapshotRow
                ).where(
                    MarketplaceObservationSnapshotRow.source_profile
                    == source_profile,
                    MarketplaceObservationSnapshotRow.idempotency_key
                    == idempotency_key,
                )
                if scope is None:
                    existing_query = existing_query.where(
                        MarketplaceObservationSnapshotRow.tenant_ref.is_(
                            None
                        )
                    )
                else:
                    existing_query = existing_query.where(
                        MarketplaceObservationSnapshotRow.tenant_ref
                        == scope["tenant_ref"],
                        MarketplaceObservationSnapshotRow.entity_ref
                        == scope["entity_ref"],
                        MarketplaceObservationSnapshotRow.store_ref
                        == scope["store_ref"],
                    )
                existing = session.scalar(existing_query)
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
                    tenant_ref=(
                        scope["tenant_ref"] if scope else None
                    ),
                    entity_ref=(
                        scope["entity_ref"] if scope else None
                    ),
                    scope_grant_authority_sha256=(
                        scope["scope_grant_authority_sha256"]
                        if scope
                        else None
                    ),
                    scope_as_of=(
                        _timestamp(
                            scope["scope_as_of"],
                            "scope.scope_as_of",
                        )
                        if scope
                        else None
                    ),
                    adapter_id=(
                        adapter["adapter_id"] if adapter else None
                    ),
                    adapter_version=(
                        adapter["adapter_version"] if adapter else None
                    ),
                    adapter_contract_sha256=adapter_contract_sha256,
                    source_grade=(
                        adapter["max_source_grade"]
                        if adapter
                        else None
                    ),
                    semantic_authority=(
                        adapter["semantic_authority"]
                        if adapter
                        else None
                    ),
                    source_evidence_ids_json=[] if scope else None,
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
                            price_scope=item["price_scope"],
                            unit_price_decimal=Decimal(item["unit_price"]),
                            price_kind=item["price_kind"],
                            min_order_quantity=item["min_order_quantity"],
                            availability=item["availability"],
                            specifications_json=item["specifications"],
                            target_product_id=item["target_product_id"],
                            target_offer_id=item["target_offer_id"],
                            source_url=item["source_url"],
                            observed_at=observed_at,
                            evidence_id=evidence_record.id,
                            candidate_key=item["candidate_key"],
                            product_identity_json=item["product_identity"],
                            observed_quantity=item["observed_quantity"],
                            checkout_verified=item["checkout_verified"],
                            tax_included=item["tax_included"],
                            domestic_freight_included=item[
                                "domestic_freight_included"
                            ],
                            purchase_available=item["purchase_available"],
                            confidence_decimal=Decimal(item["confidence"]),
                            market_signals_json=item["market_signals"],
                            supply_signals_json=item["supply_signals"],
                            media_rights_status=item["media_rights_status"],
                            experiment_readbacks_json=item[
                                "experiment_readbacks"
                            ],
                        )
                    )
                session.flush()
                result = self._snapshot(session, snapshot)
        except IntegrityError:
            with Session(self.engine) as session:
                winner_query = select(
                    MarketplaceObservationSnapshotRow
                ).where(
                    MarketplaceObservationSnapshotRow.source_profile
                    == source_profile,
                    MarketplaceObservationSnapshotRow.idempotency_key
                    == idempotency_key,
                )
                if scope is None:
                    winner_query = winner_query.where(
                        MarketplaceObservationSnapshotRow.tenant_ref.is_(
                            None
                        )
                    )
                else:
                    winner_query = winner_query.where(
                        MarketplaceObservationSnapshotRow.tenant_ref
                        == scope["tenant_ref"],
                        MarketplaceObservationSnapshotRow.entity_ref
                        == scope["entity_ref"],
                        MarketplaceObservationSnapshotRow.store_ref
                        == scope["store_ref"],
                    )
                winner = session.scalar(winner_query)
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
        store_refs: set[str] | None = None,
        tenant_ref: str | None = None,
        entity_ref: str | None = None,
        as_of: str | datetime | None = None,
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
            if normalized_marketplace not in READ_MARKETPLACES:
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
        if store_refs is not None:
            normalized_stores = {
                _required_text(value, "store_ref", max_length=160)
                for value in store_refs
            }
            if not normalized_stores:
                raise ValueError("Observation store scope cannot be empty")
            query = query.where(
                MarketplaceObservationSnapshotRow.store_ref.in_(
                    normalized_stores
                )
            )
        if (tenant_ref is None) != (entity_ref is None):
            raise ValueError(
                "Observation tenant/entity query scope must be complete"
            )
        if tenant_ref is not None and entity_ref is not None:
            query = query.where(
                or_(
                    MarketplaceObservationSnapshotRow.tenant_ref.is_(
                        None
                    ),
                    and_(
                        MarketplaceObservationSnapshotRow.tenant_ref
                        == _required_text(
                            tenant_ref,
                            "tenant_ref",
                            max_length=160,
                        ),
                        MarketplaceObservationSnapshotRow.entity_ref
                        == _required_text(
                            entity_ref,
                            "entity_ref",
                            max_length=160,
                        ),
                    ),
                )
            )
        if as_of is not None:
            cutoff = (
                as_of.astimezone(UTC)
                if isinstance(as_of, datetime) and as_of.tzinfo is not None
                else _timestamp(as_of, "as_of")
            )
            query = query.where(
                MarketplaceObservationItemRow.observed_at <= cutoff
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

    def page(
        self,
        *,
        marketplace: str,
        cursor: str | None = None,
        page_size: int = 500,
        store_refs: set[str] | None = None,
        tenant_ref: str | None = None,
        entity_ref: str | None = None,
        as_of: str | datetime | None = None,
    ) -> dict[str, Any]:
        if marketplace not in READ_MARKETPLACES:
            raise ValueError("Unsupported marketplace observation marketplace")
        if not 1 <= page_size <= 1000:
            raise ValueError("Observation page_size must be 1 to 1000")
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
            .where(
                MarketplaceObservationSnapshotRow.marketplace == marketplace
            )
            .order_by(
                MarketplaceObservationItemRow.observed_at.desc(),
                MarketplaceObservationItemRow.id,
            )
            .limit(page_size)
        )
        if store_refs is not None:
            normalized_stores = {
                _required_text(value, "store_ref", max_length=160)
                for value in store_refs
            }
            if not normalized_stores:
                raise ValueError("Observation store scope cannot be empty")
            query = query.where(
                MarketplaceObservationSnapshotRow.store_ref.in_(
                    normalized_stores
                )
            )
        if (tenant_ref is None) != (entity_ref is None):
            raise ValueError(
                "Observation tenant/entity query scope must be complete"
            )
        if tenant_ref is not None and entity_ref is not None:
            query = query.where(
                or_(
                    MarketplaceObservationSnapshotRow.tenant_ref.is_(
                        None
                    ),
                    and_(
                        MarketplaceObservationSnapshotRow.tenant_ref
                        == _required_text(
                            tenant_ref,
                            "tenant_ref",
                            max_length=160,
                        ),
                        MarketplaceObservationSnapshotRow.entity_ref
                        == _required_text(
                            entity_ref,
                            "entity_ref",
                            max_length=160,
                        ),
                    ),
                )
            )
        if as_of is not None:
            cutoff = (
                as_of.astimezone(UTC)
                if isinstance(as_of, datetime) and as_of.tzinfo is not None
                else _timestamp(as_of, "as_of")
            )
            query = query.where(
                MarketplaceObservationItemRow.observed_at <= cutoff
            )
        if cursor:
            try:
                payload = json.loads(
                    urlsafe_b64decode(cursor.encode()).decode()
                )
                cursor_at = _timestamp(payload["observed_at"], "cursor")
                cursor_id = _required_text(
                    payload["item_id"], "cursor item_id", max_length=160
                )
            except Exception as exc:
                raise ValueError("Observation cursor is invalid") from exc
            query = query.where(
                (
                    MarketplaceObservationItemRow.observed_at
                    < cursor_at
                )
                | (
                    (
                        MarketplaceObservationItemRow.observed_at
                        == cursor_at
                    )
                    & (MarketplaceObservationItemRow.id > cursor_id)
                )
            )
        with Session(self.engine) as session:
            rows = session.execute(query).all()
        items = [self._item(item, snapshot) for item, snapshot in rows]
        next_cursor = None
        if len(rows) == page_size:
            last = rows[-1][0]
            next_cursor = urlsafe_b64encode(
                _canonical_json(
                    {
                        "observed_at": _iso(last.observed_at),
                        "item_id": last.id,
                    }
                )
            ).decode()
        return {
            "contract_version": OBSERVATION_CONTRACT_VERSION,
            "marketplace": marketplace,
            "items": items,
            "page_size": page_size,
            "next_cursor": next_cursor,
            "cursor_contract": "observed_at_desc_item_id_asc_v1",
            "store_scope": sorted(store_refs) if store_refs else None,
        }

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
            "scope": {
                "tenant_ref": row.tenant_ref,
                "entity_ref": row.entity_ref,
                "store_ref": row.store_ref,
                "scope_grant_authority_sha256": (
                    row.scope_grant_authority_sha256
                ),
                "scope_as_of": (
                    _iso(row.scope_as_of) if row.scope_as_of else None
                ),
                "authority": (
                    "native_observation_scope"
                    if row.tenant_ref
                    else "legacy_evidence_binding_required"
                ),
            },
            "source_adapter": {
                "adapter_id": row.adapter_id,
                "adapter_version": row.adapter_version,
                "adapter_contract_sha256": (
                    row.adapter_contract_sha256
                ),
                "source_grade": row.source_grade,
                "semantic_authority": row.semantic_authority,
                "source_evidence_ids": (
                    row.source_evidence_ids_json or []
                ),
                "status": (
                    "frozen" if row.adapter_id else "legacy_no_adapter"
                ),
            },
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
            "tenant_ref": snapshot.tenant_ref,
            "entity_ref": snapshot.entity_ref,
            "scope_grant_authority_sha256": (
                snapshot.scope_grant_authority_sha256
            ),
            "scope_as_of": (
                _iso(snapshot.scope_as_of)
                if snapshot.scope_as_of
                else None
            ),
            "adapter_id": snapshot.adapter_id,
            "adapter_version": snapshot.adapter_version,
            "adapter_contract_sha256": (
                snapshot.adapter_contract_sha256
            ),
            "source_grade": snapshot.source_grade,
            "semantic_authority": snapshot.semantic_authority,
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
            "price_scope": item.price_scope,
            "unit_price": format(_money(item.unit_price_decimal), "f"),
            "price_contract": (
                "displayed_price_scope_and_server_derived_unit_price/v1"
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
            "candidate_key": (
                item.candidate_key
                if exact_identity_complete(
                    item.product_identity_json, item.variant_key
                )
                else None
            ),
            "product_identity": item.product_identity_json,
            "identity_resolution_status": (
                "exact"
                if exact_identity_complete(
                    item.product_identity_json, item.variant_key
                )
                else "unresolved"
            ),
            "observed_quantity": item.observed_quantity,
            "checkout_verified": item.checkout_verified,
            "tax_included": item.tax_included,
            "domestic_freight_included": (
                item.domestic_freight_included
            ),
            "purchase_available": item.purchase_available,
            "confidence": format(item.confidence_decimal, "f"),
            "market_signals": item.market_signals_json,
            "supply_signals": item.supply_signals_json,
            "media_rights_status": item.media_rights_status,
            "experiment_readbacks": item.experiment_readbacks_json,
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
