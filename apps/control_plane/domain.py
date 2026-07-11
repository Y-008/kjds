from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import uuid4


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class PassportType(StrEnum):
    PRODUCT = "product"
    COMPLIANCE = "compliance"
    QUALITY = "quality"


class ProductStatus(StrEnum):
    CANDIDATE = "candidate"
    VALIDATED = "validated"
    APPROVED_FOR_LISTING = "approved_for_listing"
    ACTIVE = "active"
    PAUSED = "paused"
    RETIRED = "retired"


class OrderStatus(StrEnum):
    CREATED = "created"
    PAID = "paid"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    RETURNED = "returned"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class AgentMode(StrEnum):
    READ_ONLY = "read_only"
    DRAFT = "draft"
    LIMITED_EXECUTION = "limited_execution"


class ContentType(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    COPY = "copy"


class ContentStatus(StrEnum):
    BRIEF = "brief"
    GENERATED = "generated"
    QA_FAILED = "qa_failed"
    APPROVED = "approved"
    PUBLISHED = "published"


class ExperimentStatus(StrEnum):
    DRAFT = "draft"
    RUNNING = "running"
    STOPPED = "stopped"
    CONCLUDED = "concluded"


class ChargeType(StrEnum):
    DISCOUNT = "discount"
    REFUND = "refund"
    PRODUCT_COST = "product_cost"
    PLATFORM_FEE = "platform_fee"
    DOMESTIC_LOGISTICS = "domestic_logistics"
    PACKAGING = "packaging"
    CUSTOMS = "customs"
    INTERNATIONAL_LOGISTICS = "international_logistics"
    LAST_MILE = "last_mile"
    FX = "fx"
    ADVERTISING = "advertising"
    RETURN = "return"
    UNCLAIMED = "unclaimed"
    DAMAGE = "damage"
    CUSTOMER_COMPENSATION = "customer_compensation"


CM1_COSTS = {ChargeType.PRODUCT_COST}
CM2_COSTS = {
    ChargeType.PLATFORM_FEE,
    ChargeType.DOMESTIC_LOGISTICS,
    ChargeType.PACKAGING,
    ChargeType.CUSTOMS,
    ChargeType.INTERNATIONAL_LOGISTICS,
    ChargeType.LAST_MILE,
    ChargeType.FX,
}
CM3_COSTS = {
    ChargeType.ADVERTISING,
    ChargeType.RETURN,
    ChargeType.UNCLAIMED,
    ChargeType.DAMAGE,
    ChargeType.CUSTOMER_COMPENSATION,
}


@dataclass(slots=True)
class Product:
    sku: str
    name: str
    market: str = "RU"
    channel: str = "OZON"
    status: ProductStatus = ProductStatus.CANDIDATE
    id: str = field(default_factory=lambda: new_id("prd"))
    created_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class Passport:
    product_id: str
    kind: PassportType
    version: int
    facts: dict[str, Any]
    evidence: list[str]
    approved_by: str | None = None
    id: str = field(default_factory=lambda: new_id("pass"))
    created_at: str = field(default_factory=utc_now)

    @property
    def is_approved(self) -> bool:
        return bool(self.approved_by and self.evidence)


@dataclass(slots=True)
class Order:
    external_id: str
    product_id: str
    quantity: int
    currency: str
    gross_revenue: Decimal
    booked_fx_rate: Decimal
    status: OrderStatus = OrderStatus.CREATED
    id: str = field(default_factory=lambda: new_id("ord"))
    created_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class Charge:
    order_id: str
    kind: ChargeType
    amount: Decimal
    currency: str
    fx_rate: Decimal
    evidence_ref: str
    id: str = field(default_factory=lambda: new_id("chg"))
    created_at: str = field(default_factory=utc_now)

    @property
    def amount_cny(self) -> Decimal:
        return self.amount * self.fx_rate


@dataclass(slots=True)
class ProfitSnapshot:
    order_id: str
    gross_cny: Decimal
    net_revenue_cny: Decimal
    cm1_cny: Decimal
    cm2_cny: Decimal
    cm3_cny: Decimal
    cm3_rate: Decimal


@dataclass(slots=True)
class Approval:
    action: str
    resource_type: str
    resource_id: str
    requested_by: str
    payload: dict[str, Any]
    status: ApprovalStatus = ApprovalStatus.PENDING
    decided_by: str | None = None
    decision_reason: str | None = None
    id: str = field(default_factory=lambda: new_id("apr"))
    created_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class AgentTask:
    agent: str
    mode: AgentMode
    task_type: str
    input_data: dict[str, Any]
    requested_by: str
    idempotency_key: str
    id: str = field(default_factory=lambda: new_id("agt"))
    created_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class MarketObservation:
    source: str
    market: str
    category: str
    metric: str
    value: Decimal
    observed_at: str
    source_ref: str
    confidence: Decimal
    dimensions: dict[str, str] = field(default_factory=dict)
    id: str = field(default_factory=lambda: new_id("obs"))
    ingested_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class OpportunityInsight:
    market: str
    category: str
    title: str
    score: Decimal
    rationale: list[str]
    evidence_ids: list[str]
    recommended_action: str
    id: str = field(default_factory=lambda: new_id("opp"))
    created_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class ContentAsset:
    product_id: str
    content_type: ContentType
    locale: str
    channel: str
    brief: dict[str, Any]
    source_facts: dict[str, Any]
    status: ContentStatus = ContentStatus.BRIEF
    artifact_ref: str | None = None
    qa_results: list[dict[str, Any]] = field(default_factory=list)
    id: str = field(default_factory=lambda: new_id("asset"))
    created_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class GrowthExperiment:
    product_id: str
    channel: str
    hypothesis: str
    primary_metric: str
    budget_cap_cny: Decimal
    stop_loss_cny: Decimal
    variants: list[str]
    status: ExperimentStatus = ExperimentStatus.DRAFT
    id: str = field(default_factory=lambda: new_id("exp"))
    created_at: str = field(default_factory=utc_now)
