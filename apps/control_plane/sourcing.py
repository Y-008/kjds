from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Any, Protocol

from .action_policies import ActionAuthorizationService, require_action_authorization
from .domain import ContentStatus, ContentType, ProductStatus, new_id, utc_now
from .logistics import LogisticsScopeContext
from .repository import Repository

MONEY = Decimal("0.01")
RATE = Decimal("0.0001")
REQUIRED_COST_EVIDENCE_KEYS = frozenset(
    {
        "product_cost",
        "domestic_logistics",
        "international_logistics",
        "packaging",
        "warehousing",
        "customs",
        "tax",
        "last_mile",
        "platform_fee",
        "advertising",
        "return",
        "fx",
        "capital_cost",
        "aftersales",
        "loss",
    }
)
PROFIT_TEMPLATE_ID = "ozon-ru-full-cost-v1"
ALLOWED_COST_STATES = frozenset({"estimate", "actual", "unknown"})
PROFIT_TEMPLATE_FIELDS = (
    ("product_cost", "采购成本", "CNY/件", "supplier_offer", "供应商报价、合同或采购账单"),
    ("domestic_logistics", "国内物流", "CNY/件", "supplier_offer", "供应商报价或国内物流账单"),
    ("international_logistics", "头程物流", "CNY/kg", "official_or_carrier", "承运商报价、计费规则或物流账单"),
    ("packaging", "包装", "CNY/件", "supplier_or_invoice", "包材报价或采购账单"),
    ("warehousing", "仓储", "CNY/件", "official_or_bill", "Ozon 官方费率或仓储账单"),
    ("customs", "关税", "rate", "official_or_declaration", "海关规则或报关单"),
    ("tax", "税费", "CNY/件", "official_or_tax_record", "税务规则或税务凭证"),
    ("last_mile", "尾程", "CNY/件", "official_or_bill", "Ozon 官方费率或履约账单"),
    ("platform_fee", "平台佣金", "rate", "official_or_bill", "Ozon 官方费率或结算账单"),
    ("advertising", "广告", "rate", "official_or_bill", "广告后台账单或受控预算假设"),
    ("return", "退款退货准备", "rate", "historical_or_bill", "历史退款数据或结算账单"),
    ("fx", "汇兑成本", "CNY/件", "bank_or_payment_bill", "银行或支付机构账单"),
    ("capital_cost", "资金占用", "CNY/件", "finance_policy", "经批准的资金成本规则"),
    ("aftersales", "售后", "CNY/件", "historical_or_bill", "历史售后数据或服务账单"),
    ("loss", "损耗准备", "CNY/件", "historical_or_bill", "历史损耗数据或盘点记录"),
)


def profit_template_contract() -> dict[str, Any]:
    return {
        "id": PROFIT_TEMPLATE_ID,
        "formula_version": "1.0.0",
        "target_platform": "OZON",
        "currency": "CNY",
        "allowed_states": sorted(ALLOWED_COST_STATES),
        "fields": [
            {
                "key": key,
                "label": label,
                "unit": unit,
                "source_class": source_class,
                "source_expectation": source_expectation,
                "evidence_required_for_release": True,
            }
            for key, label, unit, source_class, source_expectation in PROFIT_TEMPLATE_FIELDS
        ],
        "release_rule": "All named costs need evidence and a non-unknown state; unclassified cost must be zero.",
        "automatic_pricing": False,
    }


def money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def _require_finite(name: str, value: Decimal) -> None:
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")


def _utc_iso(name: str, value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    return parsed.astimezone(UTC).isoformat()


class SourcePlatform(StrEnum):
    ALIBABA_1688 = "1688"
    TAOBAO = "taobao"
    TMALL = "tmall"
    JD = "jd"
    PINDUODUO = "pinduoduo"
    ALIBABA = "alibaba"
    ALIEXPRESS = "aliexpress"
    AMAZON = "amazon"
    TEMU = "temu"
    SHOPIFY = "shopify"
    WOOCOMMERCE = "woocommerce"
    MANUAL = "manual"


@dataclass(slots=True)
class SupplierOffer:
    product_id: str
    supplier_ref: str
    platform: SourcePlatform
    external_id: str
    source_url: str
    title: str
    currency: str
    unit_price: Decimal
    source_to_cny_rate: Decimal
    min_order_quantity: int
    weight_kg: Decimal
    length_cm: Decimal
    width_cm: Decimal
    height_cm: Decimal
    domestic_logistics_per_unit: Decimal
    evidence_ref: str
    attributes: dict[str, Any] = field(default_factory=dict)
    media: list[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: new_id("off"))
    captured_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        positive = {
            "unit_price": self.unit_price,
            "source_to_cny_rate": self.source_to_cny_rate,
            "weight_kg": self.weight_kg,
        }
        nonnegative = {
            "length_cm": self.length_cm,
            "width_cm": self.width_cm,
            "height_cm": self.height_cm,
            "domestic_logistics_per_unit": self.domestic_logistics_per_unit,
        }
        for name, value in {**positive, **nonnegative}.items():
            _require_finite(name, value)
        if any(value <= 0 for value in positive.values()):
            raise ValueError("Offer price, FX rate, and product weight must be positive")
        if any(value < 0 for value in nonnegative.values()):
            raise ValueError("Offer dimensions and logistics cost must be nonnegative")
        if self.min_order_quantity < 1:
            raise ValueError("Offer MOQ must be positive")
        currency = self.currency.strip().upper()
        if len(currency) != 3 or not currency.isalpha() or not currency.isascii():
            raise ValueError("Offer currency must be a three-letter ISO code")
        self.currency = currency
        self.captured_at = _utc_iso("captured_at", self.captured_at)

    @property
    def unit_cost_cny(self) -> Decimal:
        return money(self.unit_price * self.source_to_cny_rate)

    @property
    def domestic_logistics_cny(self) -> Decimal:
        return money(self.domestic_logistics_per_unit * self.source_to_cny_rate)


@dataclass(frozen=True, slots=True)
class ProfitInputs:
    sale_price_rub: Decimal
    rub_per_cny: Decimal
    international_freight_cny_per_kg: Decimal
    packaging_cny: Decimal
    last_mile_cny: Decimal
    customs_rate: Decimal
    platform_fee_rate: Decimal
    advertising_rate: Decimal
    return_reserve_rate: Decimal
    warehousing_cny: Decimal = Decimal("0")
    tax_cny: Decimal = Decimal("0")
    fx_cost_cny: Decimal = Decimal("0")
    capital_cost_cny: Decimal = Decimal("0")
    aftersales_cny: Decimal = Decimal("0")
    loss_reserve_cny: Decimal = Decimal("0")
    other_cost_cny: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        positive = {
            "sale_price_rub": self.sale_price_rub,
            "rub_per_cny": self.rub_per_cny,
        }
        nonnegative = {
            "international_freight_cny_per_kg": self.international_freight_cny_per_kg,
            "packaging_cny": self.packaging_cny,
            "last_mile_cny": self.last_mile_cny,
            "warehousing_cny": self.warehousing_cny,
            "tax_cny": self.tax_cny,
            "fx_cost_cny": self.fx_cost_cny,
            "capital_cost_cny": self.capital_cost_cny,
            "aftersales_cny": self.aftersales_cny,
            "loss_reserve_cny": self.loss_reserve_cny,
            "other_cost_cny": self.other_cost_cny,
        }
        rates = {
            "customs_rate": self.customs_rate,
            "platform_fee_rate": self.platform_fee_rate,
            "advertising_rate": self.advertising_rate,
            "return_reserve_rate": self.return_reserve_rate,
        }
        for name, value in {**positive, **nonnegative, **rates}.items():
            _require_finite(name, value)
        if any(value <= 0 for value in positive.values()):
            raise ValueError("Sale price and RUB/CNY rate must be positive")
        if any(value < 0 for value in nonnegative.values()):
            raise ValueError("Profit cost assumptions must be nonnegative")
        if any(value < 0 or value >= 1 for value in rates.values()):
            raise ValueError("All rates must be between 0 and 1")
        variable_rate = self.platform_fee_rate + self.advertising_rate + self.return_reserve_rate
        if variable_rate >= 1:
            raise ValueError("Combined platform, advertising, and return rates must be below 1")


@dataclass(slots=True)
class ProfitScenario:
    offer_id: str
    target_platform: str
    inputs: ProfitInputs
    revenue_cny: Decimal
    purchase_cny: Decimal
    domestic_logistics_cny: Decimal
    international_logistics_cny: Decimal
    packaging_cny: Decimal
    warehousing_cny: Decimal
    customs_cny: Decimal
    tax_cny: Decimal
    last_mile_cny: Decimal
    platform_fee_cny: Decimal
    advertising_cny: Decimal
    return_reserve_cny: Decimal
    fx_cost_cny: Decimal
    capital_cost_cny: Decimal
    aftersales_cny: Decimal
    loss_reserve_cny: Decimal
    other_cost_cny: Decimal
    total_cost_cny: Decimal
    cm3_cny: Decimal
    cm3_rate: Decimal
    break_even_price_rub: Decimal
    evidence: list[str]
    cost_evidence: dict[str, str] = field(default_factory=dict)
    template_id: str = PROFIT_TEMPLATE_ID
    cost_states: dict[str, str] = field(default_factory=dict)
    logistics_calculation_id: str | None = None
    id: str = field(default_factory=lambda: new_id("scn"))
    created_at: str = field(default_factory=utc_now)

    @property
    def missing_cost_evidence(self) -> list[str]:
        return sorted(REQUIRED_COST_EVIDENCE_KEYS - self.cost_evidence.keys())

    @property
    def unknown_costs(self) -> list[str]:
        return sorted(
            key for key in REQUIRED_COST_EVIDENCE_KEYS if self.cost_states.get(key, "unknown") == "unknown"
        )

    @property
    def cost_complete(self) -> bool:
        return not self.missing_cost_evidence and not self.unknown_costs and self.other_cost_cny == 0

    def cost_breakdown(self) -> dict[str, str]:
        return {
            "product_cost": str(self.purchase_cny),
            "domestic_logistics": str(self.domestic_logistics_cny),
            "international_logistics": str(self.international_logistics_cny),
            "packaging": str(self.packaging_cny),
            "warehousing": str(self.warehousing_cny),
            "customs": str(self.customs_cny),
            "tax": str(self.tax_cny),
            "last_mile": str(self.last_mile_cny),
            "platform_fee": str(self.platform_fee_cny),
            "advertising": str(self.advertising_cny),
            "return": str(self.return_reserve_cny),
            "fx": str(self.fx_cost_cny),
            "capital_cost": str(self.capital_cost_cny),
            "aftersales": str(self.aftersales_cny),
            "loss": str(self.loss_reserve_cny),
            "other_unclassified": str(self.other_cost_cny),
        }

    def explain(self) -> dict[str, Any]:
        breakdown = self.cost_breakdown()
        fixed_costs = self.total_cost_cny - self.platform_fee_cny - self.advertising_cny - self.return_reserve_cny
        variable_rate = (
            self.inputs.platform_fee_rate + self.inputs.advertising_rate + self.inputs.return_reserve_rate
        )

        def price_case(multiplier: Decimal) -> dict[str, str]:
            sale_price_rub = money(self.inputs.sale_price_rub * multiplier)
            revenue = money(sale_price_rub / self.inputs.rub_per_cny)
            cm3 = money(revenue - fixed_costs - money(revenue * variable_rate))
            return {"sale_price_rub": str(sale_price_rub), "cm3_cny": str(cm3)}

        return {
            "scenario_id": self.id,
            "template_id": self.template_id,
            "formula_version": profit_template_contract()["formula_version"],
            "items": [
                {
                    "key": key,
                    "label": label,
                    "amount_cny": breakdown[key],
                    "state": self.cost_states.get(key, "unknown"),
                    "evidence_id": self.cost_evidence.get(key),
                }
                for key, label, *_ in PROFIT_TEMPLATE_FIELDS
            ],
            "revenue_cny": str(self.revenue_cny),
            "total_cost_cny": str(self.total_cost_cny),
            "cm3_cny": str(self.cm3_cny),
            "cm3_rate": str(self.cm3_rate),
            "break_even_price_rub": str(self.break_even_price_rub),
            "margin_of_safety_rub": str(money(self.inputs.sale_price_rub - self.break_even_price_rub)),
            "sensitivity": {
                "price_minus_10_percent": price_case(Decimal("0.90")),
                "baseline": price_case(Decimal("1.00")),
                "price_plus_10_percent": price_case(Decimal("1.10")),
            },
            "missing_cost_evidence": self.missing_cost_evidence,
            "unknown_costs": self.unknown_costs,
            "unclassified_cost_cny": str(self.other_cost_cny),
            "release_ready": self.cost_complete,
            "automatic_pricing": False,
            "logistics_calculation_id": self.logistics_calculation_id,
        }


@dataclass(slots=True)
class ListingDraft:
    product_id: str
    offer_id: str
    scenario_id: str
    target_platform: str
    listing_data: dict[str, Any]
    requested_by: str
    status: str = "approval_pending"
    approval_id: str | None = None
    id: str = field(default_factory=lambda: new_id("lst"))
    created_at: str = field(default_factory=utc_now)
    tenant_ref: str | None = None
    entity_ref: str | None = None
    store_ref: str | None = None
    scope_grant_authority_sha256: str | None = None
    scoped_product_content_sha256: str | None = None
    approval_plan_sha256: str | None = None
    evidence_ids: list[str] = field(default_factory=list)
    scope_as_of: str | None = None


def listing_snapshot(draft: ListingDraft) -> dict[str, Any]:
    return {
        "product_id": draft.product_id,
        "offer_id": draft.offer_id,
        "scenario_id": draft.scenario_id,
        "target_platform": draft.target_platform,
        "listing_data": draft.listing_data,
        "scope": {
            "tenant_ref": draft.tenant_ref,
            "entity_ref": draft.entity_ref,
            "store_ref": draft.store_ref,
            "scope_grant_authority_sha256": (
                draft.scope_grant_authority_sha256
            ),
            "scoped_product_content_sha256": (
                draft.scoped_product_content_sha256
            ),
            "scope_as_of": draft.scope_as_of,
        },
        "approval_plan_sha256": draft.approval_plan_sha256,
        "evidence_ids": sorted(draft.evidence_ids),
    }


def listing_snapshot_sha256(draft: ListingDraft) -> str:
    canonical = json.dumps(
        listing_snapshot(draft),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def listing_approval_payload(draft: ListingDraft, scenario: ProfitScenario) -> dict[str, Any]:
    return {
        "draft_id": draft.id,
        "target_platform": draft.target_platform,
        "product_id": draft.product_id,
        "offer_id": draft.offer_id,
        "scenario_id": draft.scenario_id,
        "title": draft.listing_data["title"],
        "description": draft.listing_data["description"],
        "category_id": draft.listing_data["category_id"],
        "attributes": draft.listing_data["attributes"],
        "content_asset_ids": list(draft.listing_data["content_asset_ids"]),
        "image_evidence_refs": list(draft.listing_data["images"]),
        "expected_cm3_cny": str(scenario.cm3_cny),
        "expected_cm3_rate": str(scenario.cm3_rate),
        "cost_complete": scenario.cost_complete,
        "cost_breakdown_cny": scenario.cost_breakdown(),
        "cost_evidence": dict(scenario.cost_evidence),
        "cost_states": dict(scenario.cost_states),
        "profit_template_id": scenario.template_id,
        "missing_cost_evidence": scenario.missing_cost_evidence,
        "unknown_costs": scenario.unknown_costs,
        "scenario_evidence_ids": list(scenario.evidence),
        "evidence_ids": sorted(draft.evidence_ids),
        "tenant_ref": draft.tenant_ref,
        "entity_ref": draft.entity_ref,
        "store_ref": draft.store_ref,
        "scope_grant_authority_sha256": (
            draft.scope_grant_authority_sha256
        ),
        "scoped_product_content_sha256": (
            draft.scoped_product_content_sha256
        ),
        "approval_plan_sha256": draft.approval_plan_sha256,
        "scope_as_of": draft.scope_as_of,
        "listing_snapshot_sha256": listing_snapshot_sha256(draft),
        "platform_write_executed": False,
    }


class SourcingStore(Protocol):
    def save_offer(self, offer: SupplierOffer) -> SupplierOffer: ...
    def get_offer(self, offer_id: str) -> SupplierOffer: ...
    def list_offers(self, limit: int = 100) -> list[SupplierOffer]: ...
    def save_scenario(self, scenario: ProfitScenario) -> ProfitScenario: ...
    def get_scenario(self, scenario_id: str) -> ProfitScenario: ...
    def list_scenarios(self, limit: int = 1000) -> list[ProfitScenario]: ...
    def save_listing_draft(self, draft: ListingDraft) -> ListingDraft: ...
    def attach_listing_approval(self, draft: ListingDraft) -> ListingDraft: ...
    def get_listing_draft(self, draft_id: str) -> ListingDraft: ...
    def list_listing_drafts(self, limit: int = 100) -> list[ListingDraft]: ...
    def list_listing_drafts_scoped(
        self,
        *,
        tenant_ref: str,
        entity_ref: str,
        store_ref: str,
        as_of: datetime,
        limit: int = 100,
    ) -> list[ListingDraft]: ...
    def get_listing_draft_scoped(
        self,
        *,
        draft_id: str,
        tenant_ref: str,
        entity_ref: str,
        store_ref: str,
        as_of: datetime,
    ) -> ListingDraft: ...


class SourcingService:
    def __init__(
        self,
        store: SourcingStore,
        repository: Repository,
        evidence_validator: Callable[[list[str]], None],
        actual_cost_validator: Callable[[str, str], Any] | None = None,
        offer_authority_validator: Callable[[str], Any] | None = None,
        action_authorization: ActionAuthorizationService | None = None,
        logistics_profit_resolver: Callable[..., Any] | None = None,
    ) -> None:
        self.store = store
        self.repository = repository
        self.evidence_validator = evidence_validator
        self.actual_cost_validator = actual_cost_validator
        self.offer_authority_validator = offer_authority_validator
        self.action_authorization = action_authorization or ActionAuthorizationService()
        self.logistics_profit_resolver = logistics_profit_resolver

    def capture_offer(self, offer: SupplierOffer) -> SupplierOffer:
        self.repository.get_product(offer.product_id)
        if not offer.supplier_ref.strip():
            raise ValueError("Offer supplier_ref is required")
        if not offer.source_url.startswith(("http://", "https://")):
            raise ValueError("Offer source_url must be HTTP(S)")
        if not offer.evidence_ref:
            raise ValueError("Offer evidence is required")
        self.evidence_validator([offer.evidence_ref])
        if self.offer_authority_validator is not None:
            original = self.offer_authority_validator(offer.evidence_ref)
            frozen_terms = original.metadata.get("offer_data", {})
            comparable = {
                "product_id": offer.product_id,
                "supplier_ref": offer.supplier_ref,
                "platform": offer.platform.value,
                "external_id": offer.external_id,
                "source_url": offer.source_url,
                "title": offer.title,
                "currency": offer.currency,
                "unit_price": str(offer.unit_price),
                "source_to_cny_rate": str(offer.source_to_cny_rate),
                "min_order_quantity": offer.min_order_quantity,
                "weight_kg": str(offer.weight_kg),
                "length_cm": str(offer.length_cm),
                "width_cm": str(offer.width_cm),
                "height_cm": str(offer.height_cm),
                "domestic_logistics_per_unit": str(
                    offer.domestic_logistics_per_unit
                ),
                "attributes": offer.attributes,
                "media": offer.media,
            }
            if frozen_terms != comparable:
                raise ValueError("Supplier offer terms differ from the accepted immutable quote")
        return self.store.save_offer(offer)

    def calculate_profit(
        self,
        offer_id: str,
        inputs: ProfitInputs,
        assumption_evidence: list[str],
        cost_evidence: dict[str, str] | None = None,
        cost_states: dict[str, str] | None = None,
        template_id: str = PROFIT_TEMPLATE_ID,
        logistics_calculation_id: str | None = None,
        logistics_context: LogisticsScopeContext | None = None,
    ) -> ProfitScenario:
        if template_id != PROFIT_TEMPLATE_ID:
            raise ValueError(f"Unsupported profit template: {template_id}")
        offer = self.store.get_offer(offer_id)
        normalized_assumptions = [item.strip() for item in assumption_evidence if item.strip()]
        if not normalized_assumptions:
            raise ValueError("Profit assumptions require at least one immutable evidence record")
        normalized_cost_evidence = {
            key.strip(): value.strip()
            for key, value in (cost_evidence or {}).items()
            if key.strip() and value.strip()
        }
        unknown_costs = sorted(normalized_cost_evidence.keys() - REQUIRED_COST_EVIDENCE_KEYS)
        if unknown_costs:
            raise ValueError(f"Unknown cost evidence keys: {', '.join(unknown_costs)}")
        normalized_cost_evidence.update(
            {
                "product_cost": offer.evidence_ref,
                "domestic_logistics": offer.evidence_ref,
            }
        )
        normalized_cost_states = {
            key.strip(): value.strip().lower()
            for key, value in (cost_states or {}).items()
            if key.strip() and value.strip()
        }
        logistics_calculation = None
        if logistics_calculation_id:
            if self.logistics_profit_resolver is None:
                raise ValueError("Logistics calculation workspace is not configured")
            if logistics_context is None:
                raise ValueError("Logistics calculation requires exact scope context")
            if inputs.international_freight_cny_per_kg != 0:
                raise ValueError(
                    "Set manual international freight rate to zero when using a logistics calculation"
                )
            logistics_calculation = self.logistics_profit_resolver(
                logistics_context,
                logistics_calculation_id,
                marketplace="OZON",
                destination_country="RU",
                declared_value_currency="RUB",
                declared_value=inputs.sale_price_rub,
                physical_weight_kg=offer.weight_kg,
                length_cm=offer.length_cm,
                width_cm=offer.width_cm,
                height_cm=offer.height_cm,
            )
            normalized_cost_evidence["international_logistics"] = (
                logistics_calculation.evidence_id
            )
            normalized_cost_states["international_logistics"] = "estimate"
            if fx_evidence_id := getattr(
                logistics_calculation, "fx_evidence_id", None
            ):
                normalized_assumptions.append(fx_evidence_id)
        unknown_state_keys = sorted(normalized_cost_states.keys() - REQUIRED_COST_EVIDENCE_KEYS)
        if unknown_state_keys:
            raise ValueError(f"Unknown cost state keys: {', '.join(unknown_state_keys)}")
        invalid_states = sorted(
            f"{key}={value}"
            for key, value in normalized_cost_states.items()
            if value not in ALLOWED_COST_STATES
        )
        if invalid_states:
            raise ValueError(f"Invalid cost states: {', '.join(invalid_states)}")
        normalized_cost_states = {
            key: normalized_cost_states.get(
                key,
                "estimate" if key in normalized_cost_evidence else "unknown",
            )
            for key in REQUIRED_COST_EVIDENCE_KEYS
        }
        inconsistent_states = sorted(
            key
            for key, state in normalized_cost_states.items()
            if (state == "unknown") == (key in normalized_cost_evidence)
        )
        if inconsistent_states:
            raise ValueError(
                "Unknown costs must not have evidence, while estimate/actual costs require evidence: "
                + ", ".join(inconsistent_states)
            )
        evidence_ids = list(
            dict.fromkeys(
                [offer.evidence_ref, *normalized_assumptions, *normalized_cost_evidence.values()]
            )
        )
        self.evidence_validator(evidence_ids)
        self._validate_actual_costs(normalized_cost_evidence, normalized_cost_states)
        for existing in self.store.list_scenarios():
            if (
                existing.offer_id == offer.id
                and existing.inputs == inputs
                and existing.evidence == evidence_ids
                and existing.cost_evidence == normalized_cost_evidence
                and existing.template_id == template_id
                and existing.cost_states == normalized_cost_states
                and existing.logistics_calculation_id == logistics_calculation_id
            ):
                return existing
        revenue = money(inputs.sale_price_rub / inputs.rub_per_cny)
        purchase = offer.unit_cost_cny
        domestic = offer.domestic_logistics_cny
        international = (
            money(logistics_calculation.total_charge_cny)
            if logistics_calculation is not None
            else money(offer.weight_kg * inputs.international_freight_cny_per_kg)
        )
        landed_before_customs = purchase + domestic + international + inputs.packaging_cny
        customs = money(landed_before_customs * inputs.customs_rate)
        platform_fee = money(revenue * inputs.platform_fee_rate)
        advertising = money(revenue * inputs.advertising_rate)
        returns = money(revenue * inputs.return_reserve_rate)
        named_fixed_costs = (
            landed_before_customs
            + inputs.warehousing_cny
            + customs
            + inputs.tax_cny
            + inputs.last_mile_cny
            + inputs.fx_cost_cny
            + inputs.capital_cost_cny
            + inputs.aftersales_cny
            + inputs.loss_reserve_cny
        )
        fixed_costs = money(named_fixed_costs + inputs.other_cost_cny)
        variable_costs = platform_fee + advertising + returns
        total_cost = money(fixed_costs + variable_costs)
        cm3 = money(revenue - total_cost)
        cm3_rate = (cm3 / revenue).quantize(RATE, rounding=ROUND_HALF_UP)
        variable_rate = inputs.platform_fee_rate + inputs.advertising_rate + inputs.return_reserve_rate
        break_even_revenue = fixed_costs / (Decimal("1") - variable_rate)
        break_even_rub = money(break_even_revenue * inputs.rub_per_cny)
        scenario = ProfitScenario(
            offer_id=offer.id,
            target_platform="OZON",
            inputs=inputs,
            revenue_cny=revenue,
            purchase_cny=purchase,
            domestic_logistics_cny=domestic,
            international_logistics_cny=international,
            packaging_cny=money(inputs.packaging_cny),
            warehousing_cny=money(inputs.warehousing_cny),
            customs_cny=customs,
            tax_cny=money(inputs.tax_cny),
            last_mile_cny=money(inputs.last_mile_cny),
            platform_fee_cny=platform_fee,
            advertising_cny=advertising,
            return_reserve_cny=returns,
            fx_cost_cny=money(inputs.fx_cost_cny),
            capital_cost_cny=money(inputs.capital_cost_cny),
            aftersales_cny=money(inputs.aftersales_cny),
            loss_reserve_cny=money(inputs.loss_reserve_cny),
            other_cost_cny=money(inputs.other_cost_cny),
            total_cost_cny=total_cost,
            cm3_cny=cm3,
            cm3_rate=cm3_rate,
            break_even_price_rub=break_even_rub,
            evidence=evidence_ids,
            cost_evidence=normalized_cost_evidence,
            template_id=template_id,
            cost_states=normalized_cost_states,
            logistics_calculation_id=logistics_calculation_id,
        )
        return self.store.save_scenario(scenario)

    def compare_product_offers(self, product_id: str) -> dict:
        product = self.repository.get_product(product_id)
        offer_snapshots = [item for item in self.store.list_offers(limit=500) if item.product_id == product_id]
        latest_by_supplier = {}
        for offer in offer_snapshots:
            current = latest_by_supplier.get(offer.supplier_ref)
            if current is None or offer.captured_at > current.captured_at:
                latest_by_supplier[offer.supplier_ref] = offer
        offers = list(latest_by_supplier.values())
        latest_scenarios = {}
        for scenario in self.store.list_scenarios(limit=5000):
            current = latest_scenarios.get(scenario.offer_id)
            if current is None or scenario.created_at > current.created_at:
                latest_scenarios[scenario.offer_id] = scenario
        rows = []
        for offer in offers:
            scenario = latest_scenarios.get(offer.id)
            rows.append(
                {
                    "offer": offer,
                    "scenario": scenario,
                    "has_positive_cm3": bool(scenario and scenario.cm3_cny > 0),
                }
            )
        rows.sort(key=lambda item: item["scenario"].cm3_cny if item["scenario"] else Decimal("-999999"), reverse=True)
        supplier_count = len({item.supplier_ref for item in offers})
        return {
            "product": {"id": product.id, "sku": product.sku, "name": product.name},
            "supplier_count": supplier_count,
            "offer_count": len(offers),
            "scenario_count": sum(item["scenario"] is not None for item in rows),
            "ready_for_procurement_review": (
                supplier_count >= 3
                and len(rows) >= 3
                and all(item["scenario"] and self.release_ready(item["scenario"]) for item in rows)
            ),
            "rows": rows,
        }

    def require_release_ready(self, scenario: ProfitScenario) -> ProfitScenario:
        if not scenario.cost_complete:
            raise ValueError("Profit scenario full cost evidence: incomplete or unclassified costs")
        self.evidence_validator(scenario.evidence)
        self._validate_actual_costs(scenario.cost_evidence, scenario.cost_states)
        return scenario

    def release_ready(self, scenario: ProfitScenario) -> bool:
        try:
            self.require_release_ready(scenario)
        except (KeyError, RuntimeError, ValueError):
            return False
        return True

    def _validate_actual_costs(
        self,
        cost_evidence: dict[str, str],
        cost_states: dict[str, str],
    ) -> None:
        actual_costs = [key for key, state in cost_states.items() if state == "actual"]
        if not actual_costs:
            return
        if self.actual_cost_validator is None:
            raise ValueError("Actual costs require an authority validator")
        for cost_type in actual_costs:
            self.actual_cost_validator(cost_evidence[cost_type], cost_type)

    def create_ozon_listing_draft(
        self,
        *,
        product_id: str,
        offer_id: str,
        scenario_id: str,
        content_asset_ids: list[str],
        listing_data: dict[str, Any],
        requested_by: str,
        scope_authority: dict[str, Any] | None = None,
        approval_plan_sha256: str | None = None,
        evidence_ids: list[str] | None = None,
    ) -> ListingDraft:
        if scope_authority is not None:
            required_scope = {
                "tenant_ref",
                "entity_ref",
                "store_ref",
                "scope_grant_authority_sha256",
                "scoped_product_content_sha256",
                "scope_as_of",
            }
            missing_scope = sorted(
                key
                for key in required_scope
                if not str(scope_authority.get(key) or "").strip()
            )
            if missing_scope:
                raise ValueError(
                    "Listing draft scope authority is incomplete: "
                    + ", ".join(missing_scope)
                )
            if (
                not isinstance(approval_plan_sha256, str)
                or len(approval_plan_sha256) != 64
            ):
                raise ValueError(
                    "Scoped Listing draft requires approval plan SHA-256"
                )
            evidence_ids = sorted(
                {
                    str(item).strip()
                    for item in evidence_ids or []
                    if str(item).strip()
                }
            )
            if not evidence_ids:
                raise ValueError(
                    "Scoped Listing draft requires frozen Evidence references"
                )
        require_action_authorization(
            self.action_authorization,
            self.repository,
            action="listing_draft",
            subject_id=product_id,
            actor_id=requested_by,
            occurred_at=datetime.now(UTC),
            phase="request",
        )
        product = self.repository.get_product(product_id)
        if product.status not in {ProductStatus.VALIDATED, ProductStatus.APPROVED_FOR_LISTING}:
            raise ValueError("Product must pass all approved passports before listing")
        offer = self.store.get_offer(offer_id)
        scenario = self.store.get_scenario(scenario_id)
        if offer.product_id != product.id:
            raise ValueError("Supplier offer does not belong to the requested product")
        if scenario.offer_id != offer.id:
            raise ValueError("Profit scenario does not belong to this supplier offer")
        if not content_asset_ids or len(set(content_asset_ids)) != len(content_asset_ids):
            raise ValueError("Listing draft requires unique approved content asset IDs")
        content_assets = [self.repository.get_content_asset(asset_id) for asset_id in content_asset_ids]
        invalid_assets = [
            asset.id
            for asset in content_assets
            if asset.product_id != product.id
            or asset.content_type != ContentType.IMAGE
            or asset.status != ContentStatus.APPROVED
            or not asset.artifact_ref
        ]
        if invalid_assets:
            raise ValueError(
                "Listing draft content assets must be approved images for the requested product: "
                + ", ".join(invalid_assets)
            )
        required = {"title", "description", "category_id", "attributes", "images"}
        missing = sorted(required - listing_data.keys())
        if missing:
            raise ValueError(f"Listing draft missing fields: {', '.join(missing)}")
        images = listing_data["images"]
        artifact_refs = [asset.artifact_ref for asset in content_assets]
        if not isinstance(images, list) or images != artifact_refs:
            raise ValueError("Listing draft images must exactly match the approved content asset evidence")
        if scenario.cm3_cny <= 0:
            raise ValueError("Listing draft blocked because expected CM3 is not positive")
        self.require_release_ready(scenario)
        listing_data = dict(listing_data)
        listing_data["content_asset_ids"] = list(content_asset_ids)
        draft_id = "lst_" + hashlib.sha256(
            json.dumps(
                {
                    "product_id": product_id,
                    "offer_id": offer.id,
                    "scenario_id": scenario.id,
                    "target_platform": "OZON",
                    "listing_data": listing_data,
                    "requested_by": requested_by,
                    "scope_authority": scope_authority,
                    "approval_plan_sha256": approval_plan_sha256,
                    "evidence_ids": evidence_ids,
                },
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        ).hexdigest()[:32]
        require_action_authorization(
            self.action_authorization,
            self.repository,
            action="listing_draft",
            subject_id=product_id,
            actor_id=requested_by,
            occurred_at=datetime.now(UTC),
            phase="execute",
            executor_id="control_plane",
        )
        draft = ListingDraft(
            product_id=product_id,
            offer_id=offer.id,
            scenario_id=scenario.id,
            target_platform="OZON",
            listing_data=listing_data,
            requested_by=requested_by,
            id=draft_id,
            tenant_ref=(
                scope_authority.get("tenant_ref")
                if scope_authority
                else None
            ),
            entity_ref=(
                scope_authority.get("entity_ref")
                if scope_authority
                else None
            ),
            store_ref=(
                scope_authority.get("store_ref")
                if scope_authority
                else None
            ),
            scope_grant_authority_sha256=(
                scope_authority.get("scope_grant_authority_sha256")
                if scope_authority
                else None
            ),
            scoped_product_content_sha256=(
                scope_authority.get("scoped_product_content_sha256")
                if scope_authority
                else None
            ),
            approval_plan_sha256=approval_plan_sha256,
            evidence_ids=evidence_ids or [],
            scope_as_of=(
                scope_authority.get("scope_as_of")
                if scope_authority
                else None
            ),
        )
        saved = self.store.save_listing_draft(draft)
        if listing_snapshot(saved) != listing_snapshot(draft):
            raise ValueError("Listing draft idempotency conflict")
        return self.store.get_listing_draft(saved.id)

    def verify_listing_approval(
        self,
        *,
        draft_id: str,
        approval_id: str,
        approval_payload: dict[str, Any],
    ) -> ListingDraft:
        draft = self.store.get_listing_draft(draft_id)
        if draft.approval_id != approval_id or approval_payload.get("draft_id") != draft.id:
            raise ValueError("Listing approval does not match the stored draft")
        approved_digest = approval_payload.get("listing_snapshot_sha256")
        current_digest = listing_snapshot_sha256(draft)
        if not isinstance(approved_digest, str) or not hmac.compare_digest(approved_digest, current_digest):
            raise ValueError("Listing draft changed after the approval request")
        return draft
