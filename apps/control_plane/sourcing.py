from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Any, Protocol

from .domain import ProductStatus, new_id, utc_now
from .repository import Repository

MONEY = Decimal("0.01")
RATE = Decimal("0.0001")


def money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


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
    other_cost_cny: Decimal = Decimal("0")


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
    customs_cny: Decimal
    last_mile_cny: Decimal
    platform_fee_cny: Decimal
    advertising_cny: Decimal
    return_reserve_cny: Decimal
    other_cost_cny: Decimal
    total_cost_cny: Decimal
    cm3_cny: Decimal
    cm3_rate: Decimal
    break_even_price_rub: Decimal
    evidence: list[str]
    id: str = field(default_factory=lambda: new_id("scn"))
    created_at: str = field(default_factory=utc_now)


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


class SourcingStore(Protocol):
    def save_offer(self, offer: SupplierOffer) -> SupplierOffer: ...
    def get_offer(self, offer_id: str) -> SupplierOffer: ...
    def list_offers(self, limit: int = 100) -> list[SupplierOffer]: ...
    def save_scenario(self, scenario: ProfitScenario) -> ProfitScenario: ...
    def get_scenario(self, scenario_id: str) -> ProfitScenario: ...
    def save_listing_draft(self, draft: ListingDraft) -> ListingDraft: ...
    def attach_listing_approval(self, draft: ListingDraft) -> ListingDraft: ...
    def list_listing_drafts(self, limit: int = 100) -> list[ListingDraft]: ...


class SourcingService:
    def __init__(
        self,
        store: SourcingStore,
        repository: Repository,
        evidence_validator: Callable[[list[str]], None],
    ) -> None:
        self.store = store
        self.repository = repository
        self.evidence_validator = evidence_validator

    def capture_offer(self, offer: SupplierOffer) -> SupplierOffer:
        if offer.unit_price <= 0 or offer.source_to_cny_rate <= 0:
            raise ValueError("Offer price and FX rate must be positive")
        if offer.min_order_quantity < 1 or offer.weight_kg <= 0:
            raise ValueError("MOQ and product weight must be positive")
        if not offer.source_url.startswith(("http://", "https://")):
            raise ValueError("Offer source_url must be HTTP(S)")
        if not offer.evidence_ref:
            raise ValueError("Offer evidence is required")
        self.evidence_validator([offer.evidence_ref])
        return self.store.save_offer(offer)

    def calculate_profit(
        self,
        offer_id: str,
        inputs: ProfitInputs,
        assumption_evidence: list[str],
    ) -> ProfitScenario:
        offer = self.store.get_offer(offer_id)
        normalized_assumptions = [item.strip() for item in assumption_evidence if item.strip()]
        if not normalized_assumptions:
            raise ValueError("Profit assumptions require at least one immutable evidence record")
        evidence_ids = list(dict.fromkeys([offer.evidence_ref, *normalized_assumptions]))
        self.evidence_validator(evidence_ids)
        if inputs.sale_price_rub <= 0 or inputs.rub_per_cny <= 0:
            raise ValueError("Sale price and RUB/CNY rate must be positive")
        rates = [
            inputs.customs_rate,
            inputs.platform_fee_rate,
            inputs.advertising_rate,
            inputs.return_reserve_rate,
        ]
        if any(rate < 0 or rate >= 1 for rate in rates):
            raise ValueError("All rates must be between 0 and 1")

        revenue = money(inputs.sale_price_rub / inputs.rub_per_cny)
        purchase = offer.unit_cost_cny
        domestic = offer.domestic_logistics_cny
        international = money(offer.weight_kg * inputs.international_freight_cny_per_kg)
        landed_before_customs = purchase + domestic + international + inputs.packaging_cny
        customs = money(landed_before_customs * inputs.customs_rate)
        platform_fee = money(revenue * inputs.platform_fee_rate)
        advertising = money(revenue * inputs.advertising_rate)
        returns = money(revenue * inputs.return_reserve_rate)
        fixed_costs = money(landed_before_customs + customs + inputs.last_mile_cny + inputs.other_cost_cny)
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
            customs_cny=customs,
            last_mile_cny=money(inputs.last_mile_cny),
            platform_fee_cny=platform_fee,
            advertising_cny=advertising,
            return_reserve_cny=returns,
            other_cost_cny=money(inputs.other_cost_cny),
            total_cost_cny=total_cost,
            cm3_cny=cm3,
            cm3_rate=cm3_rate,
            break_even_price_rub=break_even_rub,
            evidence=evidence_ids,
        )
        return self.store.save_scenario(scenario)

    def create_ozon_listing_draft(
        self,
        *,
        product_id: str,
        offer_id: str,
        scenario_id: str,
        listing_data: dict[str, Any],
        requested_by: str,
    ) -> ListingDraft:
        product = self.repository.get_product(product_id)
        if product.status not in {ProductStatus.VALIDATED, ProductStatus.APPROVED_FOR_LISTING}:
            raise ValueError("Product must pass all approved passports before listing")
        offer = self.store.get_offer(offer_id)
        scenario = self.store.get_scenario(scenario_id)
        if scenario.offer_id != offer.id:
            raise ValueError("Profit scenario does not belong to this supplier offer")
        required = {"title", "description", "category_id", "attributes", "images"}
        missing = sorted(required - listing_data.keys())
        if missing:
            raise ValueError(f"Listing draft missing fields: {', '.join(missing)}")
        if scenario.cm3_cny <= 0:
            raise ValueError("Listing draft blocked because expected CM3 is not positive")
        return self.store.save_listing_draft(
            ListingDraft(
                product_id=product_id,
                offer_id=offer.id,
                scenario_id=scenario.id,
                target_platform="OZON",
                listing_data=listing_data,
                requested_by=requested_by,
            )
        )
