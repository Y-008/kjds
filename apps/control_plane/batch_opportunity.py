from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    select,
    text,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import ContentStatus, PassportType, Product, new_id
from .evidence import EvidenceGrade
from .evidence_class import classify_evidence_class, policy_for
from .marketplace_observation import exact_identity_complete
from .marketplace_sources import SUPPLIER_MARKETPLACES, is_supplier_marketplace
from .ozon_global_rules import OzonGlobalRuleRegistry
from .risk_adjusted_profit import RiskAdjustedProfitSimulator
from .sale_triggered_procurement import SaleTriggeredProcurementPolicy
from .sku_identity_card import (
    build_identity_card,
    core_spec_mismatches,
    identity_card_summary,
)
from .sql_repository import Base

BATCH_CONTRACT_VERSION = "batch-opportunity/1.3.0"
BATCH_POLICY_ID = "cn-ozon-observed-cost-v1"
BATCH_EVIDENCE_SOURCE = "batch_opportunity_run"
MONEY = Decimal("0.01")
RATE = Decimal("0.000001")
SALES_PROXY_TYPES = frozenset(
    {
        "review_velocity_proxy",
        "review_count_proxy",
        "ranking_proxy",
        "sold_badge_proxy",
        "seller_backend_orders",
    }
)

COMPONENT_ORDER = (
    "procurement",
    "purchase_buffer",
    "domestic_logistics",
    "packaging",
    "international_logistics",
    "customs",
    "marketplace_commission",
    "fulfillment_last_mile",
    "warehousing",
    "advertising",
    "returns_refunds",
    "discounts_promotions",
    "taxes",
    "fx_reserve",
    "loss_damage",
)

# Trial-phase key cost components (operator's list).  The validation stage
# requires evidence for these; the remaining components are interval-simulated
# from policy estimates instead of blocking the run.
KEY_COST_COMPONENTS: frozenset[str] = frozenset(
    {
        "procurement",
        "domestic_logistics",
        "international_logistics",
        "packaging",
        "marketplace_commission",
        "fx_reserve",
        "taxes",
        "returns_refunds",
        "loss_damage",
    }
)

# Trial-phase basic media checks (six items).  Heavy multi-model media QA is
# a scale-up artifact and is intentionally not built here.
BASIC_MEDIA_CHECKS: tuple[str, ...] = (
    "image_matches_target_sku",
    "image_params_match_specs",
    "no_external_watermark_or_contact",
    "no_brand_logo",
    "no_unsubstantiated_claims",
    "accessories_in_image_included",
)

POLICY: dict[str, Any] = {
    "id": BATCH_POLICY_ID,
    "authority": "research_screening_only",
    "resource_mix_target": {
        "refined_or_hero": "0.70",
        "controlled_distribution": "0.20",
        "exploration": "0.10",
        "semantics": "policy_target_not_fact",
    },
    "pilot_inventory_units": {"minimum": 1, "maximum": 3},
    "baseline": {
        "purchase_buffer_rate": "0.05",
        "domestic_logistics_fixed_cny": "5",
        "packaging_fixed_cny": "5",
        "international_logistics_per_kg_cny": "18",
        "international_logistics_fallback_cny": "60",
        "customs_rate": "0.03",
        "marketplace_commission_rate": "0.18",
        "fulfillment_last_mile_rate": "0.08",
        "warehousing_rate": "0.02",
        "advertising_rate": "0.05",
        "returns_refunds_rate": "0.05",
        "discounts_promotions_rate": "0.02",
        "taxes_rate": "0.06",
        "fx_reserve_rate": "0.02",
        "loss_damage_rate": "0.01",
    },
    "downside": {
        "purchase_buffer_rate": "0.12",
        "domestic_logistics_fixed_cny": "15",
        "packaging_fixed_cny": "10",
        "international_logistics_per_kg_cny": "35",
        "international_logistics_fallback_cny": "120",
        "customs_rate": "0.05",
        "marketplace_commission_rate": "0.22",
        "fulfillment_last_mile_rate": "0.12",
        "warehousing_rate": "0.04",
        "advertising_rate": "0.10",
        "returns_refunds_rate": "0.12",
        "discounts_promotions_rate": "0.05",
        "taxes_rate": "0.10",
        "fx_reserve_rate": "0.05",
        "loss_damage_rate": "0.03",
    },
}


class BatchOpportunityRunRow(Base):
    __tablename__ = "batch_opportunity_runs"
    __table_args__ = (
        CheckConstraint(
            "("
            "tenant_ref IS NULL AND entity_ref IS NULL "
            "AND scope_grant_authority_sha256 IS NULL "
            "AND scope_evidence_authority_sha256 IS NULL"
            ") OR ("
            "tenant_ref IS NOT NULL AND length(tenant_ref) > 0 "
            "AND entity_ref IS NOT NULL AND length(entity_ref) > 0 "
            "AND scope_grant_authority_sha256 IS NOT NULL "
            "AND length(scope_grant_authority_sha256) = 64 "
            "AND scope_evidence_authority_sha256 IS NOT NULL "
            "AND length(scope_evidence_authority_sha256) = 64"
            ")",
            name="ck_batch_opportunity_run_scope_complete",
        ),
        Index(
            "uq_batch_opportunity_run_legacy_idempotency",
            "store_ref",
            "idempotency_key",
            unique=True,
            postgresql_where=text("tenant_ref IS NULL"),
            sqlite_where=text("tenant_ref IS NULL"),
        ),
        Index(
            "uq_batch_opportunity_run_scoped_idempotency",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "idempotency_key",
            unique=True,
            postgresql_where=text("tenant_ref IS NOT NULL"),
            sqlite_where=text("tenant_ref IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    store_ref: Mapped[str] = mapped_column(String, nullable=False)
    tenant_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    entity_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    scope_grant_authority_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    scope_evidence_authority_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False)
    policy_id: Mapped[str] = mapped_column(String, nullable=False)
    contract_version: Mapped[str] = mapped_column(String, nullable=False)
    snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_records.id"), nullable=False
    )
    as_of: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    counts_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    policy_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    blockers_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    task_id: Mapped[str | None] = mapped_column(String, nullable=True)


class BatchOpportunityCandidateRow(Base):
    __tablename__ = "batch_opportunity_candidates"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "fingerprint",
            name="uq_batch_opportunity_candidate_fingerprint",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("batch_opportunity_runs.id"), nullable=False
    )
    candidate_key: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False)
    strategy: Mapped[str] = mapped_column(String, nullable=False)
    pilot_ready: Mapped[bool] = mapped_column(Boolean, nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
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


def _sha256_text(value: Any, field: str) -> str:
    normalized = _required_text(value, field, max_length=64)
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef"
        for character in normalized
    ):
        raise ValueError(f"{field} must be lowercase SHA-256")
    return normalized


def _scope_authority(
    value: dict[str, Any] | None,
    *,
    store_ref: str,
) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("scope_authority must be an object")
    scope = {
        "tenant_ref": _required_text(
            value.get("tenant_ref"),
            "scope_authority.tenant_ref",
            max_length=160,
        ),
        "entity_ref": _required_text(
            value.get("entity_ref"),
            "scope_authority.entity_ref",
            max_length=160,
        ),
        "store_ref": _required_text(
            value.get("store_ref"),
            "scope_authority.store_ref",
            max_length=160,
        ),
        "scope_grant_authority_sha256": _sha256_text(
            value.get("scope_grant_authority_sha256"),
            "scope_authority.scope_grant_authority_sha256",
        ),
        "scope_evidence_authority_sha256": _sha256_text(
            value.get("scope_evidence_authority_sha256"),
            "scope_authority.scope_evidence_authority_sha256",
        ),
    }
    if scope["store_ref"] != store_ref:
        raise ValueError("scope_authority store_ref mismatch")
    for field in (
        "scoped_observation_snapshot_sha256",
        "scoped_catalog_snapshot_sha256",
        "scoped_economics_snapshot_sha256",
        "scoped_product_content_snapshot_sha256",
    ):
        raw = value.get(field)
        if raw is not None:
            scope[field] = _sha256_text(
                raw,
                f"scope_authority.{field}",
            )
    return scope


def _timestamp(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def _decimal(value: Any, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except Exception as exc:
        raise ValueError(f"{field} must be a decimal") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field} must be finite")
    return parsed


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def _basic_evidence_status(
    *,
    market: dict[str, Any],
    supplier: dict[str, Any],
    candidate_key: str | None,
    media_ready: bool,
    market_signals: dict[str, Any],
    supply_signals: dict[str, Any],
    product_id: str | None,
    scoped_product_content: dict[str, dict[str, Any]] | None,
) -> dict[str, bool]:
    """Six basic evidence roles from the operator's scenario one.

    Every role is evaluated against observable, verifiable inputs only:
    observation records, evidence ids and scoped product content.  A role
    with no data source is False (fail-closed), never guessed.
    """
    scoped = (
        scoped_product_content.get(product_id)
        if scoped_product_content is not None and product_id
        else None
    ) or {}
    scoped_basic = {
        str(item.get("role") or ""): item.get("status") == "approved"
        for item in scoped.get("basic_evidence", [])
        if isinstance(item, dict) and str(item.get("role") or "")
    }

    def has_evidence_key(*keys: str) -> bool:
        for source in (market_signals, supply_signals):
            for key in keys:
                if str(source.get(key) or "").strip():
                    return True
        return False

    return {
        "supplier_identity": bool(
            supplier.get("supplier_ref") and supplier.get("evidence_id")
        ),
        "purchase_link": bool(
            supplier.get("source_url") and supplier.get("evidence_id")
        ),
        "product_certificate": (
            scoped_basic.get("product_certificate", False)
            or has_evidence_key(
                "certificate_evidence_id",
                "certification_evidence_id",
            )
        ),
        "sku_mapping": bool(candidate_key),
        "image_source": media_ready,
        "basic_qc_result": (
            scoped_basic.get("basic_qc_result", False)
            or has_evidence_key("qc_evidence_id", "quality_evidence_id")
        ),
    }


def _basic_media_checks_status(
    market_signals: dict[str, Any],
) -> dict[str, str]:
    """Six basic media checks with passed/failed/unknown states.

    Statuses come from the captured page data (``media_checks`` signal
    object).  Missing data is ``unknown`` and is reported as a gap, never
    guessed.  A ``failed`` check is a hard media blocker in every class.
    """
    provided = market_signals.get("media_checks")
    if not isinstance(provided, dict):
        provided = {}
    statuses: dict[str, str] = {}
    for name in BASIC_MEDIA_CHECKS:
        status = str(provided.get(name, "unknown")).strip().lower()
        statuses[name] = (
            status if status in {"passed", "failed", "unknown"} else "unknown"
        )
    return statuses


def _rate(value: Any, field: str) -> Decimal:
    parsed = _decimal(value, field)
    if parsed < 0 or parsed > 1:
        raise ValueError(f"{field} must be between 0 and 1")
    return parsed.quantize(RATE, rounding=ROUND_HALF_UP)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _number(
    values: dict[str, Any],
    key: str,
    *,
    minimum: Decimal = Decimal("0"),
) -> Decimal | None:
    raw = values.get(key)
    if raw is None or raw == "":
        return None
    parsed = _decimal(raw, key)
    if parsed < minimum:
        raise ValueError(f"{key} must be at least {minimum}")
    return parsed


def _geo_coordinate(
    values: dict[str, Any],
    key: str,
    *,
    minimum: Decimal,
    maximum: Decimal,
) -> Decimal | None:
    value = _number(values, key, minimum=minimum)
    if value is None or value > maximum:
        return None
    return value


class BatchOpportunityWorkspace:
    """Scan, score, classify and persist evidence-backed batch opportunities."""

    def __init__(
        self,
        *,
        engine,
        observations,
        evidence,
        finance,
        repository,
        operating_tasks,
        facts=None,
        ozon_rules=None,
        seller_os=None,
    ) -> None:
        self.engine = engine
        self.observations = observations
        self.evidence = evidence
        self.finance = finance
        self.repository = repository
        self.operating_tasks = operating_tasks
        self.sale_triggered_procurement = (
            SaleTriggeredProcurementPolicy(
                facts=facts,
                evidence=evidence,
                repository=repository,
                engine=engine,
            )
            if facts is not None
            else None
        )
        self.ozon_rules = ozon_rules or OzonGlobalRuleRegistry()
        self.seller_os = seller_os

    def prepare(
        self,
        *,
        store_ref: str,
        policy_id: str,
        idempotency_key: str,
        candidate_limit: int,
        pilot_limit: int,
        target_purchase_quantity: int = 3,
        max_age_hours: int,
        max_inventory_cash_cny: Decimal,
        cm3_floor_cny: Decimal,
        actor_id: str,
        as_of: str | None = None,
        full_evaluate_limit: int = 500,
        scan_page_size: int = 500,
        scan_shard_count: int = 1,
        scan_shard_index: int = 0,
        max_batch_inventory_cash_cny: Decimal | None = None,
        evidence_class: str | None = None,
        scope_authority: dict[str, Any] | None = None,
        scoped_observations: list[dict[str, Any]] | None = None,
        scoped_catalog: list[dict[str, Any]] | None = None,
        scoped_fx_rates: dict[str, dict[str, Any]] | None = None,
        scoped_product_content: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        store = _required_text(store_ref, "store_ref", max_length=160)
        authority_scope = _scope_authority(
            scope_authority,
            store_ref=store,
        )
        scoped_input = any(
            value is not None
            for value in (
                scope_authority,
                scoped_observations,
                scoped_catalog,
                scoped_fx_rates,
                scoped_product_content,
            )
        )
        if scoped_input and (
            authority_scope is None
            or scoped_observations is None
            or scoped_catalog is None
            or scoped_fx_rates is None
            or scoped_product_content is None
        ):
            raise ValueError(
                "Scoped Batch Opportunity requires authority, "
                "Observation, Catalog, FX and Product/content inputs together"
            )
        actor = _required_text(actor_id, "actor_id", max_length=160)
        if evidence_class is not None:
            classify_evidence_class(evidence_class=evidence_class)
        key = _required_text(
            idempotency_key, "idempotency_key", max_length=160
        )
        if policy_id != BATCH_POLICY_ID:
            raise ValueError("Unknown batch opportunity policy")
        if not 1 <= candidate_limit <= 50000:
            raise ValueError("candidate_limit must be 1 to 50000")
        if not 1 <= full_evaluate_limit <= min(candidate_limit, 5000):
            raise ValueError(
                "full_evaluate_limit must be 1 to candidate_limit "
                "and at most 5000"
            )
        if not 1 <= scan_page_size <= 1000:
            raise ValueError("scan_page_size must be 1 to 1000")
        if not 1 <= scan_shard_count <= 100:
            raise ValueError("scan_shard_count must be 1 to 100")
        if not 0 <= scan_shard_index < scan_shard_count:
            raise ValueError("scan_shard_index must be within shard count")
        if not 1 <= pilot_limit <= min(candidate_limit, 100):
            raise ValueError(
                "pilot_limit must be 1 to candidate_limit and at most 100"
            )
        if not 1 <= target_purchase_quantity <= 3:
            raise ValueError(
                "target_purchase_quantity must be 1 to 3 for first Pilot"
            )
        if not 1 <= max_age_hours <= 720:
            raise ValueError("max_age_hours must be 1 to 720")
        max_cash = _decimal(
            max_inventory_cash_cny, "max_inventory_cash_cny"
        )
        floor = _decimal(cm3_floor_cny, "cm3_floor_cny")
        if max_cash <= 0:
            raise ValueError("max_inventory_cash_cny must be positive")
        batch_cash = (
            _decimal(
                max_batch_inventory_cash_cny,
                "max_batch_inventory_cash_cny",
            )
            if max_batch_inventory_cash_cny is not None
            else max_cash * pilot_limit
        )
        if batch_cash <= 0:
            raise ValueError(
                "max_batch_inventory_cash_cny must be positive"
            )
        now = _timestamp(as_of, "as_of") if as_of else datetime.now(UTC)
        request_fingerprint = _sha256(
            {
                "store_ref": store,
                "policy_id": policy_id,
                "candidate_limit": candidate_limit,
                "full_evaluate_limit": full_evaluate_limit,
                "scan_page_size": scan_page_size,
                "scan_shard_count": scan_shard_count,
                "scan_shard_index": scan_shard_index,
                "pilot_limit": pilot_limit,
                "target_purchase_quantity": target_purchase_quantity,
                "max_age_hours": max_age_hours,
                "max_inventory_cash_cny": str(max_cash),
                "max_batch_inventory_cash_cny": str(batch_cash),
                "cm3_floor_cny": str(floor),
                "evidence_class": evidence_class or "inferred",
                "as_of": _iso(now),
                "ozon_rule_registry_hash": (
                    self.ozon_rules.registry_hash
                ),
                "scope_authority": authority_scope,
            }
        )

        with Session(self.engine) as session:
            existing_query = select(BatchOpportunityRunRow).where(
                BatchOpportunityRunRow.store_ref == store,
                BatchOpportunityRunRow.idempotency_key == key,
            )
            if authority_scope is None:
                existing_query = existing_query.where(
                    BatchOpportunityRunRow.tenant_ref.is_(None)
                )
            else:
                existing_query = existing_query.where(
                    BatchOpportunityRunRow.tenant_ref
                    == authority_scope["tenant_ref"],
                    BatchOpportunityRunRow.entity_ref
                    == authority_scope["entity_ref"],
                )
            existing = session.scalar(existing_query)
            if existing is not None:
                if (
                    existing.payload_json.get("request_fingerprint")
                    != request_fingerprint
                ):
                    raise ValueError(
                        "Batch opportunity idempotency conflict"
                    )
                return self._run(session, existing)

        if scoped_observations is None:
            ozon_loaded = self._load_observations(
                marketplace="ozon",
                page_size=scan_page_size,
                store_refs={store, "external"},
            )
            supplier_projections = [
                self._load_observations(
                    marketplace=marketplace,
                    page_size=scan_page_size,
                    store_refs={"external"},
                )
                for marketplace in sorted(SUPPLIER_MARKETPLACES)
            ]
            supplier_loaded = {
                "items": [
                    item
                    for projection in supplier_projections
                    for item in projection["items"]
                ],
                "pages": sum(
                    projection["pages"] for projection in supplier_projections
                ),
                "raw_rows": sum(
                    projection["raw_rows"]
                    for projection in supplier_projections
                ),
            }
        else:
            ozon_rows = [
                item
                for item in scoped_observations
                if item.get("marketplace") == "ozon"
            ]
            supplier_rows = [
                item
                for item in scoped_observations
                if is_supplier_marketplace(item.get("marketplace"))
            ]
            ozon_loaded = {
                "items": ozon_rows,
                "pages": 1,
                "raw_rows": len(ozon_rows),
            }
            supplier_loaded = {
                "items": supplier_rows,
                "pages": 1,
                "raw_rows": len(supplier_rows),
            }
        ozon = ozon_loaded["items"]
        suppliers = supplier_loaded["items"]
        own_offer_ids = (
            {
                str(item.get("offer_id", "")).strip()
                for item in scoped_catalog or []
                if str(item.get("offer_id", "")).strip()
            }
            if scoped_observations is not None
            else None
        )
        own_product_ids = (
            {
                str(item.get("canonical_product_id", "")).strip()
                for item in scoped_catalog or []
                if str(item.get("canonical_product_id", "")).strip()
            }
            if scoped_observations is not None
            else None
        )
        scanned = self._scan(
            ozon=ozon,
            suppliers=suppliers,
            store_ref=store,
            target_purchase_quantity=target_purchase_quantity,
            as_of=now,
            max_age=timedelta(hours=max_age_hours),
            shard_count=scan_shard_count,
            shard_index=scan_shard_index,
            own_offer_ids=own_offer_ids,
            own_product_ids=own_product_ids,
        )
        candidates = [
            self._evaluate(
                match,
                store_ref=store,
                as_of=now,
                max_inventory_cash_cny=max_cash,
                cm3_floor_cny=floor,
                evidence_class=evidence_class,
                scoped_fx_rates=scoped_fx_rates,
                scoped_product_content=scoped_product_content,
                scope_authority=authority_scope,
            )
            for match in scanned["matches"][:full_evaluate_limit]
        ]
        candidates.sort(
            key=lambda item: (
                0 if item["state"] == "pilot" else 1,
                0 if item["state"] == "content_ready" else 1,
                0 if item["state"] == "evaluate" else 1,
                -Decimal(item["score"]["total"]),
                -Decimal(
                    item["economics"]["downside"]["cm3_cny"] or "-999999"
                ),
                item["fingerprint"],
            )
        )
        for rank, candidate in enumerate(candidates, start=1):
            candidate["rank"] = rank
        selection = self._select_pilots(
            candidates,
            pilot_limit=pilot_limit,
            max_batch_inventory_cash_cny=batch_cash,
        )

        counts = {
            "observed": len(ozon) + len(suppliers),
            "observed_listings": len(ozon) + len(suppliers),
            "ozon_observed": len(ozon),
            "own_listings": scanned["own_listing_count"],
            "competitor_listings": scanned[
                "competitor_listing_count"
            ],
            "supplier_observed": len(suppliers),
            "identity_eligible": scanned["identity_eligible"],
            "exact_identity_matched": scanned[
                "exact_identity_matched"
            ],
            "spec_mismatch_excluded": scanned["spec_mismatch_excluded"],
            "checkout_cost_eligible": scanned[
                "checkout_cost_eligible"
            ],
            # Deprecated compatibility alias. Exact matching is an identity
            # fact; checkout readiness is reported separately above.
            "exact_matched": scanned["exact_identity_matched"],
            "unique_exact_identities": scanned["unique_exact_identities"],
            "competitor_cohort_size": scanned["competitor_cohort_size"],
            "supplier_identity_cohort_size": scanned[
                "supplier_identity_cohort_size"
            ],
            "checkout_cost_cohort_size": scanned[
                "checkout_cost_cohort_size"
            ],
            # Deprecated compatibility alias for supplier identity rows.
            "supplier_cohort_size": scanned["supplier_cohort_size"],
            "cheap_prescored": len(scanned["matches"]),
            "fully_costed_candidates": sum(
                candidate["economics"]["cost_evidence_complete"]
                for candidate in candidates
            ),
            "downside_positive": sum(
                candidate["economics"]["downside"]["cm3_cny"] is not None
                and Decimal(
                    candidate["economics"]["downside"]["cm3_cny"]
                )
                > floor
                for candidate in candidates
            ),
            "content_ready": sum(
                candidate["content"]["content_ready"]
                for candidate in candidates
            ),
            "pilot_ready": sum(
                candidate["pilot_ready"] for candidate in candidates
            ),
            "eligible_for_approval": selection[
                "eligible_for_approval"
            ],
            "approval_allocation_selected": selection[
                "approval_allocation_selected"
            ],
            "approval_waitlist": selection["approval_waitlist"],
            "pilot_eligible": selection["eligible"],
            "pilot_selected": selection["selected"],
            "eligible_waitlist": selection["waitlisted"],
            "published": 0,
            "ordered": 0,
            "settled_proven": 0,
            "official_rule_ready": sum(
                candidate["ozon_global_cn"]["actions"]["pilot_approve"][
                    "status"
                ]
                == "ready"
                for candidate in candidates
            ),
            "unmatched_ozon": scanned["unmatched_ozon"],
            "unmatched_supplier": scanned["unmatched_supplier"],
        }
        blockers = sorted(
            {
                blocker
                for candidate in candidates
                for blocker in candidate["blockers"]
            }
        )
        if counts["exact_identity_matched"] == 0:
            blockers.append("exact_cross_market_match_missing")
        elif counts["checkout_cost_eligible"] == 0:
            blockers.append("observed_checkout_cost_evidence_missing")
        blockers = sorted(set(blockers))
        evidence_ids = sorted(
            {
                evidence_id
                for candidate in candidates
                for evidence_id in candidate["evidence_ids"]
            }
        )
        procurement_tasks = self._project_procurement_tasks(
            candidates=candidates,
            scope_authority=authority_scope,
            store_ref=store,
            actor_id=actor,
            as_of=now,
        )
        counts["procurement_review_tasks"] = sum(
            task["task_kind"] == "sale_triggered_procurement_review"
            for task in procurement_tasks
        )
        counts["procurement_escalation_tasks"] = sum(
            task["task_kind"] == "sale_triggered_procurement_escalation"
            for task in procurement_tasks
        )
        task = None
        if blockers:
            if "exact_cross_market_match_missing" in blockers:
                run_next_action = (
                    "补充同一 canonical identity + exact variant 的 "
                    "Ozon/1688 观察；不创建采购"
                )
            elif "observed_checkout_cost_evidence_missing" in blockers:
                run_next_action = (
                    "不下单，仅在供应仍有货时补充目标数量、MOQ、税与目标仓运费绑定的 "
                    "observed checkout Evidence"
                )
            else:
                run_next_action = (
                    "补齐十五项成本、Passport、媒体权利与治理 Evidence；"
                    "真实出单前不采购"
                )
            task = self.operating_tasks.ensure_internal_task(
                task_kind="batch_opportunity_blocked",
                scope={
                    **(
                        {
                            "tenant_ref": authority_scope["tenant_ref"],
                            "entity_ref": authority_scope["entity_ref"],
                            "scope_authority_sha256": authority_scope[
                                "scope_grant_authority_sha256"
                            ],
                        }
                        if authority_scope is not None
                        else {}
                    ),
                    "store_ref": store,
                    "policy_id": policy_id,
                },
                title="批量机会挖掘阻断",
                severity="high",
                owner="commerce",
                evidence_ids=evidence_ids,
                snapshot={
                    "counts": counts,
                    "blockers": blockers,
                    "next_action": run_next_action,
                    "as_of": _iso(now),
                },
                actor_id=actor,
            )
        payload = {
            "contract_version": BATCH_CONTRACT_VERSION,
            "request_fingerprint": request_fingerprint,
            "store_ref": store,
            "scope": authority_scope,
            "policy": POLICY,
            "procurement_policy": (
                self.sale_triggered_procurement.contract()
                if self.sale_triggered_procurement is not None
                else {
                    **SaleTriggeredProcurementPolicy.contract(),
                    "state": "no_data",
                    "source_gaps": ["formal_order_fact_adapter_missing"],
                }
            ),
            "ozon_global_cn_rule_registry": self.ozon_rules.snapshot(
                as_of=now.date().isoformat()
            ),
            "limits": {
                "candidate_limit": candidate_limit,
                "full_evaluate_limit": full_evaluate_limit,
                "scan_page_size": scan_page_size,
                "scan_shard_count": scan_shard_count,
                "scan_shard_index": scan_shard_index,
                "pilot_limit": pilot_limit,
                "target_purchase_quantity": target_purchase_quantity,
                "max_age_hours": max_age_hours,
                "max_inventory_cash_cny": str(max_cash),
                "max_batch_inventory_cash_cny": str(batch_cash),
                "cm3_floor_cny": str(floor),
            },
            "counts": counts,
            "scan_contract": {
                "pagination": "keyset_cursor",
                "cheap_prescore_before_full_evaluate": True,
                "ozon_pages": ozon_loaded["pages"],
                "supplier_pages": supplier_loaded["pages"],
                "ozon_raw_rows": ozon_loaded["raw_rows"],
                "supplier_raw_rows": supplier_loaded["raw_rows"],
                "input_mode": (
                    "scoped_authority"
                    if scoped_observations is not None
                    else "legacy_internal"
                ),
                "scoped_catalog_items": len(scoped_catalog or []),
                "shard_count": scan_shard_count,
                "shard_index": scan_shard_index,
            },
            "pilot_selection": selection,
            "supply_map": self._supply_map(suppliers),
            "market_summary": self._market_summary(ozon),
            "funnel": self._funnel(counts),
            "strategy_distribution": self._strategy_distribution(candidates),
            "candidates": candidates,
            "blockers": blockers,
            "bottlenecks": self._bottlenecks(counts),
            "operating_task": task,
            "procurement_tasks": procurement_tasks,
            "as_of": _iso(now),
            "authority": {
                "supplier_offer_created": False,
                "actual_cost_created": False,
                "formal_cm3_created": False,
                "listing_created": False,
                "permit_created": False,
                "ozon_write_performed": False,
                "automatic_execution": False,
            },
        }
        snapshot_hash = _sha256(payload)
        payload["snapshot_sha256"] = snapshot_hash
        run_id = f"bor_{snapshot_hash[:24]}"
        payload["run_id"] = run_id
        artifact = _canonical_json(payload)
        record = self.evidence.capture(
            content=artifact,
            filename=f"{run_id}-batch-opportunity-run.json",
            content_type="application/json",
            source=BATCH_EVIDENCE_SOURCE,
            source_ref=f"batch-opportunity://{store}/{key}",
            grade=EvidenceGrade.C,
            effective_at=_iso(now),
            effective_until=None,
            created_by=actor,
            metadata={
                "retention_class": "operational",
                "contract_version": BATCH_CONTRACT_VERSION,
                "policy_id": policy_id,
                "store_ref": store,
                "tenant_ref": (
                    authority_scope["tenant_ref"]
                    if authority_scope is not None
                    else None
                ),
                "entity_ref": (
                    authority_scope["entity_ref"]
                    if authority_scope is not None
                    else None
                ),
                "scope_grant_authority_sha256": (
                    authority_scope[
                        "scope_grant_authority_sha256"
                    ]
                    if authority_scope is not None
                    else None
                ),
                "scope_evidence_authority_sha256": (
                    authority_scope[
                        "scope_evidence_authority_sha256"
                    ]
                    if authority_scope is not None
                    else None
                ),
                "formal_fact_promoted": False,
                "permit_created": False,
                "external_write_allowed": False,
                "ozon_global_cn_rule_registry_hash": (
                    self.ozon_rules.registry_hash
                ),
            },
        )
        created_at = datetime.now(UTC)
        with Session(
            self.engine, expire_on_commit=False
        ) as session, session.begin():
            row = BatchOpportunityRunRow(
                id=run_id,
                store_ref=store,
                tenant_ref=(
                    authority_scope["tenant_ref"]
                    if authority_scope is not None
                    else None
                ),
                entity_ref=(
                    authority_scope["entity_ref"]
                    if authority_scope is not None
                    else None
                ),
                scope_grant_authority_sha256=(
                    authority_scope[
                        "scope_grant_authority_sha256"
                    ]
                    if authority_scope is not None
                    else None
                ),
                scope_evidence_authority_sha256=(
                    authority_scope[
                        "scope_evidence_authority_sha256"
                    ]
                    if authority_scope is not None
                    else None
                ),
                idempotency_key=key,
                policy_id=policy_id,
                contract_version=BATCH_CONTRACT_VERSION,
                snapshot_sha256=snapshot_hash,
                evidence_id=record.id,
                as_of=now,
                created_by=actor,
                created_at=created_at,
                counts_json=counts,
                policy_json=POLICY,
                blockers_json=blockers,
                payload_json=payload,
                task_id=task["id"] if task else None,
            )
            session.add(row)
            session.flush()
            for candidate in candidates:
                session.add(
                    BatchOpportunityCandidateRow(
                        id=new_id("boc"),
                        run_id=run_id,
                        candidate_key=candidate["candidate_key"],
                        fingerprint=candidate["fingerprint"],
                        rank=candidate["rank"],
                        state=candidate["state"],
                        strategy=candidate["strategy"]["classification"],
                        pilot_ready=candidate["pilot_ready"],
                        payload_json=candidate,
                        evidence_id=record.id,
                    )
                )
            session.flush()
            result = self._run(session, row)
        self.evidence.link(
            evidence_id=record.id,
            target_type="batch_opportunity_run",
            target_id=run_id,
            relationship="batch_opportunity_source",
            created_by=actor,
        )
        return result

    def latest(self, *, store_ref: str) -> dict[str, Any]:
        store = _required_text(store_ref, "store_ref", max_length=160)
        with Session(self.engine) as session:
            row = session.scalar(
                select(BatchOpportunityRunRow)
                .where(BatchOpportunityRunRow.store_ref == store)
                .order_by(
                    BatchOpportunityRunRow.as_of.desc(),
                    BatchOpportunityRunRow.id.desc(),
                )
                .limit(1)
            )
            if row is None:
                return {
                    "contract_version": BATCH_CONTRACT_VERSION,
                    "store_ref": store,
                    "state": "no_data",
                    "counts": {
                        "observed": 0,
                        "exact_identity_matched": 0,
                        "checkout_cost_eligible": 0,
                        "exact_matched": 0,
                        "downside_positive": 0,
                        "content_ready": 0,
                        "pilot_ready": 0,
                    },
                    "candidates": [],
                    "permit_created": False,
                    "ozon_write_performed": False,
                }
            return self._run(session, row)

    def latest_scoped(
        self,
        *,
        tenant_ref: str,
        entity_ref: str,
        store_ref: str,
        scope_grant_authority_sha256: str,
        as_of: datetime,
    ) -> dict[str, Any] | None:
        tenant = _required_text(
            tenant_ref,
            "tenant_ref",
            max_length=160,
        )
        entity = _required_text(
            entity_ref,
            "entity_ref",
            max_length=160,
        )
        store = _required_text(
            store_ref,
            "store_ref",
            max_length=160,
        )
        authority = _sha256_text(
            scope_grant_authority_sha256,
            "scope_grant_authority_sha256",
        )
        if as_of.tzinfo is None:
            raise ValueError("as_of must include a timezone")
        cutoff = as_of.astimezone(UTC)
        with Session(self.engine) as session:
            row = session.scalar(
                select(BatchOpportunityRunRow)
                .where(
                    BatchOpportunityRunRow.tenant_ref == tenant,
                    BatchOpportunityRunRow.entity_ref == entity,
                    BatchOpportunityRunRow.store_ref == store,
                    BatchOpportunityRunRow.scope_grant_authority_sha256
                    == authority,
                    BatchOpportunityRunRow.as_of <= cutoff,
                )
                .order_by(
                    BatchOpportunityRunRow.as_of.desc(),
                    BatchOpportunityRunRow.id.desc(),
                )
                .limit(1)
            )
            if row is None:
                return None
            self.evidence.require_current(
                [row.evidence_id],
                as_of=cutoff,
            )
            result = self._run(session, row)
        expected_scope = {
            "tenant_ref": tenant,
            "entity_ref": entity,
            "store_ref": store,
            "scope_grant_authority_sha256": authority,
            "scope_evidence_authority_sha256": (
                row.scope_evidence_authority_sha256
            ),
        }
        actual_scope = result.get("scope") or {}
        if any(
            actual_scope.get(key) != value
            for key, value in expected_scope.items()
        ):
            raise ValueError(
                "Batch Opportunity scoped payload authority mismatch"
            )
        return result

    def create_kjds_item_master_candidates(
        self,
        *,
        run_id: str,
        store_ref: str,
        tenant_ref: str,
        entity_ref: str,
        scope_grant_authority_sha256: str,
        idempotency_key: str,
        actor_id: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        """Create candidate Products from an immutable KJDS shortlist."""

        run_ref = _required_text(run_id, "run_id", max_length=160)
        store = _required_text(store_ref, "store_ref", max_length=160)
        tenant = _required_text(tenant_ref, "tenant_ref", max_length=160)
        entity = _required_text(entity_ref, "entity_ref", max_length=160)
        authority = _sha256_text(
            scope_grant_authority_sha256,
            "scope_grant_authority_sha256",
        )
        actor = _required_text(actor_id, "actor_id", max_length=160)
        key = _required_text(
            idempotency_key,
            "idempotency_key",
            max_length=160,
        )
        cutoff = _timestamp(as_of, "as_of")
        with Session(self.engine) as session:
            run = session.scalar(
                select(BatchOpportunityRunRow).where(
                    BatchOpportunityRunRow.id == run_ref,
                    BatchOpportunityRunRow.store_ref == store,
                    BatchOpportunityRunRow.tenant_ref == tenant,
                    BatchOpportunityRunRow.entity_ref == entity,
                    BatchOpportunityRunRow.scope_grant_authority_sha256
                    == authority,
                    BatchOpportunityRunRow.as_of <= cutoff,
                )
            )
            if run is None:
                raise KeyError(
                    "Batch opportunity run not found in authorized scope"
                )
            rows = list(
                session.scalars(
                    select(BatchOpportunityCandidateRow)
                    .where(BatchOpportunityCandidateRow.run_id == run.id)
                    .order_by(
                        BatchOpportunityCandidateRow.rank,
                        BatchOpportunityCandidateRow.fingerprint,
                    )
                )
            )
            evidence_id = run.evidence_id

        self.evidence.require_current([evidence_id], as_of=cutoff)
        artifact_bytes, _ = self.evidence.content(evidence_id)
        try:
            artifact = json.loads(artifact_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(
                "Batch opportunity Evidence is not valid JSON"
            ) from exc
        artifact_scope = artifact.get("scope") or {}
        if (
            artifact.get("run_id") != run_ref
            or artifact.get("store_ref") != store
            or artifact_scope.get("tenant_ref") != tenant
            or artifact_scope.get("entity_ref") != entity
            or artifact_scope.get("scope_grant_authority_sha256")
            != authority
        ):
            raise ValueError(
                "Batch opportunity Evidence scope or run binding mismatch"
            )
        artifact_candidates = artifact.get("candidates")
        if not isinstance(artifact_candidates, list):
            raise ValueError("Batch opportunity candidate Evidence is missing")
        candidates_by_fingerprint = {
            item.get("fingerprint"): item
            for item in artifact_candidates
            if isinstance(item, dict) and item.get("fingerprint")
        }
        if (
            len(candidates_by_fingerprint) != len(artifact_candidates)
            or set(candidates_by_fingerprint)
            != {row.fingerprint for row in rows}
            or any(
                _canonical_json(candidates_by_fingerprint[row.fingerprint])
                != _canonical_json(row.payload_json)
                for row in rows
            )
        ):
            raise ValueError(
                "Batch opportunity candidate Evidence does not match storage"
            )
        selection_target = artifact.get("screening", {}).get(
            "selection_target"
        )
        if selection_target not in SELECTION_TARGETS:
            raise ValueError("Batch opportunity selection target is invalid")
        selected = [
            row
            for row in rows
            if candidates_by_fingerprint[row.fingerprint]
            .get("screening", {})
            .get("accepted")
            is True
            and candidates_by_fingerprint[row.fingerprint]
            .get("screening", {})
            .get("selection_status")
            == "selected_for_kjds_item_master_review"
        ]
        if len(selected) > selection_target:
            raise ValueError("Batch opportunity shortlist exceeds its target")

        by_sku = {
            product.sku: product for product in self.repository.list_products()
        }
        result_items: list[dict[str, Any]] = []
        pending: list[tuple[BatchOpportunityCandidateRow, Product]] = []
        for row in selected:
            sku = f"KJDS-{row.fingerprint[:16].upper()}"
            existing = by_sku.get(sku)
            if existing is not None:
                if (
                    existing.tenant_ref,
                    existing.entity_ref,
                    existing.store_ref,
                ) != (tenant, entity, store):
                    raise ValueError(
                        "Stable KJDS candidate SKU belongs to another scope"
                    )
                result_items.append(
                    {
                        "candidate_id": row.id,
                        "product_id": existing.id,
                        "sku": existing.sku,
                        "status": "already_exists",
                    }
                )
                continue
            title = str(
                row.payload_json.get("market", {}).get("title")
                or f"KJDS candidate {row.rank}"
            ).strip()[:300]
            product = Product(
                sku=sku,
                name=title,
                tenant_ref=tenant,
                entity_ref=entity,
                store_ref=store,
                scope_grant_authority_sha256=authority,
                scope_as_of=cutoff.isoformat(),
                created_by=actor,
            )
            pending.append((row, product))
            by_sku[sku] = product

        if pending:
            with self.repository.transaction():
                for row, product in pending:
                    self.repository.add_product(product)
                    self.repository.append_event(
                        "product.created_from_batch_opportunity",
                        product.id,
                        {
                            "sku": product.sku,
                            "run_id": run_ref,
                            "candidate_id": row.id,
                            "candidate_fingerprint": row.fingerprint,
                            "idempotency_key": key,
                            "authority": (
                                "kjds_canonical_product_candidate_only"
                            ),
                            "external_write_allowed": False,
                        },
                        actor_id=actor,
                        source_evidence_id=evidence_id,
                    )
                    result_items.append(
                        {
                            "candidate_id": row.id,
                            "product_id": product.id,
                            "sku": product.sku,
                            "status": "created",
                        }
                    )
        result_items.sort(key=lambda item: item["candidate_id"])
        return {
            "contract_version": "kjds-item-master-batch/1.0.0",
            "run_id": run_ref,
            "store_ref": store,
            "selection_target": selection_target,
            "selected": len(selected),
            "created": sum(
                item["status"] == "created" for item in result_items
            ),
            "already_exists": sum(
                item["status"] == "already_exists" for item in result_items
            ),
            "items": result_items,
            "authority": {
                "system_of_record": "kjds_canonical_product_pim",
                "product_status": "candidate",
                "third_party_erp_called": False,
                "supplier_offer_created": False,
                "inventory_created": False,
                "purchase_created": False,
                "listing_created": False,
                "ozon_write_performed": False,
                "external_write_allowed": False,
            },
        }

    def _load_observations(
        self,
        *,
        marketplace: str,
        page_size: int,
        store_refs: set[str],
    ) -> dict[str, Any]:
        if not hasattr(self.observations, "page"):
            items = self.observations.latest(
                marketplace=marketplace,
                limit=min(page_size, 1000),
            )
            items = [
                item
                for item in items
                if item["store_ref"] in store_refs
            ]
            return {
                "items": items,
                "pages": 1,
                "raw_rows": len(items),
            }
        cursor = None
        seen_cursors: set[str] = set()
        latest_by_fingerprint: dict[str, dict[str, Any]] = {}
        pages = 0
        raw_rows = 0
        while True:
            page = self.observations.page(
                marketplace=marketplace,
                cursor=cursor,
                page_size=page_size,
                store_refs=store_refs,
            )
            pages += 1
            raw_rows += len(page["items"])
            for item in page["items"]:
                latest_by_fingerprint.setdefault(
                    item["fingerprint"], item
                )
            next_cursor = page["next_cursor"]
            if next_cursor is None:
                break
            if next_cursor in seen_cursors:
                raise RuntimeError("Observation cursor did not advance")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        return {
            "items": list(latest_by_fingerprint.values()),
            "pages": pages,
            "raw_rows": raw_rows,
        }

    def _scan(
        self,
        *,
        ozon: list[dict[str, Any]],
        suppliers: list[dict[str, Any]],
        store_ref: str,
        target_purchase_quantity: int,
        as_of: datetime,
        max_age: timedelta,
        shard_count: int,
        shard_index: int,
        own_offer_ids: set[str] | None = None,
        own_product_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        supplier_identity_by_key: dict[
            str, list[dict[str, Any]]
        ] = {}
        supplier_by_key: dict[str, list[dict[str, Any]]] = {}
        for item in suppliers:
            if not exact_identity_complete(
                item.get("product_identity"), item.get("variant_key")
            ):
                continue
            key = item.get("candidate_key")
            if key:
                supplier_identity_by_key.setdefault(key, []).append(item)
            if (
                key
                and item.get("price_kind") == "observed_checkout_price"
                and item.get("checkout_verified") is True
                and item.get("purchase_available") is True
            ):
                supplier_by_key.setdefault(key, []).append(item)
        market_by_key: dict[str, list[dict[str, Any]]] = {}
        for market in ozon:
            if not exact_identity_complete(
                market.get("product_identity"), market.get("variant_key")
            ):
                continue
            key = market.get("candidate_key")
            if key and market.get("price_kind") == "marketplace_listing_price":
                market_by_key.setdefault(key, []).append(market)
        matches: list[dict[str, Any]] = []

        def is_own_listing(item: dict[str, Any]) -> bool:
            if own_offer_ids is None or own_product_ids is None:
                return item.get("store_ref") == store_ref
            offer_refs = {
                str(item.get("external_item_id", "")).strip(),
                str(item.get("target_offer_id", "")).strip(),
            }
            product_ref = str(
                item.get("target_product_id", "")
            ).strip()
            return bool(
                own_offer_ids.intersection(offer_refs)
                or (
                    product_ref
                    and product_ref in own_product_ids
                )
            )

        spec_mismatch_excluded = 0
        for key, market_options in sorted(market_by_key.items()):
            if int(key[:8], 16) % shard_count != shard_index:
                continue
            supplier_options = supplier_by_key.get(key) or []
            if not supplier_options:
                continue
            own_options = [
                item
                for item in market_options
                if is_own_listing(item)
            ]
            competitor_options = [
                item
                for item in market_options
                if not is_own_listing(item)
            ]
            if own_options:
                market = max(
                    own_options,
                    key=lambda item: (
                        _timestamp(item["observed_at"], "own observed_at"),
                        Decimal(item["confidence"]),
                        item["fingerprint"],
                    ),
                )
                revenue_scenario = {
                    "kind": "own_listing_current_fact",
                    "authority": "observed_own_listing_price",
                    "unit_price": market.get(
                        "unit_price", market["displayed_price"]
                    ),
                    "currency": market["currency"],
                    "is_actual_sale_or_settlement": False,
                }
            elif competitor_options:
                market, competitor_cohort = self._market_cohort(
                    competitor_options
                )
                revenue_scenario = {
                    "kind": "proposed_price_scenario",
                    "authority": "estimate_from_external_competitor_p50",
                    "unit_price": competitor_cohort[
                        "price_distribution"
                    ]["median"],
                    "currency": competitor_cohort["currency"],
                    "is_actual_sale_or_settlement": False,
                    "profit_floor_status": "pending_full_economics",
                }
                market = {
                    **market,
                    "displayed_price": revenue_scenario["unit_price"],
                    "unit_price": revenue_scenario["unit_price"],
                }
            else:
                continue
            market_card = build_identity_card(market)
            observed_supplier_options = [
                option
                for option in supplier_identity_by_key.get(key, [])
                if not core_spec_mismatches(
                    market_card,
                    build_identity_card(option),
                )
            ]
            compatible_suppliers = [
                option
                for option in supplier_options
                if not core_spec_mismatches(
                    market_card,
                    build_identity_card(option),
                )
            ]
            if not compatible_suppliers:
                spec_mismatch_excluded += 1
                continue
            supplier_options = compatible_suppliers
            if competitor_options:
                _, competitor_cohort = self._market_cohort(
                    competitor_options
                )
            else:
                competitor_cohort = self._empty_market_cohort(
                    market
                )
            supplier, supplier_selection = self._supplier_selection(
                supplier_options,
                comparison_quantity=target_purchase_quantity,
                as_of=as_of,
                max_age=max_age,
            )
            sku_identity = identity_card_summary(
                market_card,
                build_identity_card(supplier),
            )
            market_age = as_of - _timestamp(
                market["observed_at"], "market observed_at"
            )
            supplier_age = as_of - _timestamp(
                supplier["observed_at"], "supplier observed_at"
            )
            matches.append(
                {
                    "candidate_key": key,
                    "market": market,
                    "supplier": supplier,
                    "market_cohort": competitor_cohort,
                    "own_listing_current_fact": (
                        market if own_options else None
                    ),
                    "revenue_scenario": revenue_scenario,
                    "supplier_options": supplier_options,
                    "observed_supplier_options": observed_supplier_options,
                    "supplier_selection": supplier_selection,
                    "sku_identity_card": sku_identity,
                    "fresh": (
                        timedelta(0) <= market_age <= max_age
                        and timedelta(0) <= supplier_age <= max_age
                    ),
                    "cheap_prescore": self._cheap_prescore(
                        market_cohort=competitor_cohort,
                        supplier_selection=supplier_selection,
                    ),
                }
            )
        matches.sort(
            key=lambda item: (
                0 if item["fresh"] else 1,
                -Decimal(item["cheap_prescore"]),
                -Decimal(item["market"]["confidence"]),
                -item["market_cohort"]["listing_count"],
                -item["supplier_selection"]["supplier_count"],
                item["candidate_key"],
            )
        )
        checkout_matched_keys = {
            item["candidate_key"] for item in matches
        }
        eligible_ozon = len(market_by_key)
        identity_matched_keys = set(market_by_key) & set(
            supplier_identity_by_key
        )
        return {
            "matches": matches,
            "identity_eligible": eligible_ozon
            + len(supplier_identity_by_key),
            "exact_identity_matched": len(identity_matched_keys),
            "spec_mismatch_excluded": spec_mismatch_excluded,
            "checkout_cost_eligible": len(checkout_matched_keys),
            "unique_exact_identities": len(market_by_key),
            "own_listing_count": sum(
                is_own_listing(item) for item in ozon
            ),
            "competitor_listing_count": sum(
                not is_own_listing(item) for item in ozon
            ),
            "competitor_cohort_size": sum(
                len(
                    [
                        item
                        for item in values
                        if not is_own_listing(item)
                    ]
                )
                for values in market_by_key.values()
            ),
            "supplier_identity_cohort_size": sum(
                len(values)
                for values in supplier_identity_by_key.values()
            ),
            "checkout_cost_cohort_size": sum(
                len(values) for values in supplier_by_key.values()
            ),
            "supplier_cohort_size": sum(
                len(values)
                for values in supplier_identity_by_key.values()
            ),
            "unmatched_ozon": max(
                0, eligible_ozon - len(identity_matched_keys)
            ),
            "unmatched_supplier": sum(
                1
                for key in supplier_identity_by_key
                if key not in identity_matched_keys
            ),
        }

    @staticmethod
    def _market_cohort(
        options: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        by_currency: dict[str, list[dict[str, Any]]] = {}
        for item in options:
            by_currency.setdefault(item["currency"], []).append(item)
        currency, comparable = max(
            by_currency.items(),
            key=lambda item: (len(item[1]), item[0]),
        )
        comparable.sort(
            key=lambda item: (
                Decimal(item.get("unit_price", item["displayed_price"])),
                item["fingerprint"],
            )
        )
        prices = [
            Decimal(item.get("unit_price", item["displayed_price"]))
            for item in comparable
        ]

        def percentile(fraction: Decimal) -> str:
            index = int(
                ((len(prices) - 1) * fraction).to_integral_value(
                    rounding=ROUND_HALF_UP
                )
            )
            return str(_money(prices[index]))

        representative = comparable[len(comparable) // 2]
        confidence = min(
            Decimal(item["confidence"]) for item in comparable
        )
        promotion_count = sum(
            bool((item.get("market_signals") or {}).get("promotion"))
            for item in comparable
        )
        cohort = {
            "candidate_key": representative["candidate_key"],
            "identity": representative["product_identity"],
            "variant_key": representative["variant_key"],
            "currency": currency,
            "listing_count": len(options),
            "comparable_listing_count": len(comparable),
            "competitor_count": len(
                {
                    item["supplier_ref"]
                    for item in comparable
                    if item["supplier_ref"]
                }
            ),
            "price_distribution": {
                "minimum": str(_money(prices[0])),
                "p25": percentile(Decimal("0.25")),
                "median": percentile(Decimal("0.50")),
                "p75": percentile(Decimal("0.75")),
                "maximum": str(_money(prices[-1])),
            },
            "promotion_listing_count": promotion_count,
            "source_urls": sorted(
                {item["source_url"] for item in comparable}
            ),
            "evidence_ids": sorted(
                {item["evidence_id"] for item in comparable}
            ),
            "confidence": str(confidence),
            "sales_is_actual": all(
                (item.get("market_signals") or {}).get(
                    "sales_proxy_type"
                )
                == "seller_backend_orders"
                for item in comparable
            ),
            "cohort_semantics": (
                "exact_product_identity_and_variant_comparable_listings"
            ),
        }
        representative = {
            **representative,
            "market_signals": {
                **(representative.get("market_signals") or {}),
                "competitor_count": cohort["competitor_count"],
                "cohort_price_median": cohort["price_distribution"][
                    "median"
                ],
            },
        }
        return representative, cohort

    @classmethod
    def market_price_bands(
        cls,
        options: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Expose the canonical price-band math without creating a candidate."""
        by_currency: dict[str, list[dict[str, Any]]] = {}
        for item in options:
            currency = str(item.get("currency") or "").strip().upper()
            if currency:
                by_currency.setdefault(currency, []).append(item)
        bands: list[dict[str, Any]] = []
        for currency, comparable in sorted(by_currency.items()):
            _, cohort = cls._market_cohort(comparable)
            bands.append(
                {
                    "currency": currency,
                    "listing_count": cohort["listing_count"],
                    "comparable_listing_count": cohort[
                        "comparable_listing_count"
                    ],
                    "price_distribution": cohort[
                        "price_distribution"
                    ],
                    "confidence_floor": cohort["confidence"],
                    "promotion_listing_count": cohort[
                        "promotion_listing_count"
                    ],
                    "evidence_ids": cohort["evidence_ids"],
                    "source_urls": cohort["source_urls"],
                    "sales_is_actual": cohort["sales_is_actual"],
                }
            )
        return bands

    @staticmethod
    def _empty_market_cohort(market: dict[str, Any]) -> dict[str, Any]:
        return {
            "candidate_key": market["candidate_key"],
            "identity": market["product_identity"],
            "variant_key": market["variant_key"],
            "currency": market["currency"],
            "listing_count": 0,
            "comparable_listing_count": 0,
            "competitor_count": 0,
            "price_distribution": None,
            "promotion_listing_count": 0,
            "source_urls": [],
            "evidence_ids": [],
            "confidence": "0",
            "sales_is_actual": False,
            "state": "no_data",
            "cohort_semantics": (
                "external_competitor_exact_identity_and_variant_only"
            ),
        }

    @staticmethod
    def _supplier_selection(
        options: list[dict[str, Any]],
        *,
        comparison_quantity: int,
        as_of: datetime,
        max_age: timedelta,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if not 1 <= comparison_quantity <= 3:
            raise ValueError(
                "comparison_quantity must be the frozen 1-3 unit Pilot "
                "purchase quantity"
            )
        ranked = []
        excluded = []
        for item in options:
            signals = item.get("supply_signals") or {}
            missing: list[str] = []
            observed_quantity = int(
                item.get("observed_quantity")
                or item.get("min_order_quantity")
                or 1
            )
            moq = int(item.get("min_order_quantity") or 1)
            if observed_quantity != comparison_quantity:
                missing.append("comparison_quantity_mismatch")
            if moq > comparison_quantity:
                missing.append("moq_exceeds_comparison_quantity")
            if item.get("price_scope") not in {
                "unit_price",
                "checkout_total",
            }:
                missing.append("price_scope_missing")
            unit_price_raw = item.get("unit_price")
            if unit_price_raw is None:
                missing.append("server_derived_unit_price_missing")
                unit_price = None
            else:
                unit_price = Decimal(unit_price_raw)
            freight_included = item.get("domestic_freight_included")
            freight_scope = signals.get("domestic_freight_scope")
            freight_amount = _number(signals, "domestic_freight_cny")
            freight_per_unit: Decimal | None
            if freight_included is True:
                freight_per_unit = Decimal("0")
            elif freight_included is False:
                if freight_amount is None:
                    missing.append("domestic_freight_amount_missing")
                    freight_per_unit = None
                elif freight_scope == "per_unit":
                    freight_per_unit = freight_amount
                elif freight_scope == "checkout_total":
                    freight_per_unit = (
                        freight_amount / Decimal(observed_quantity)
                    )
                else:
                    missing.append("domestic_freight_scope_missing")
                    freight_per_unit = None
            else:
                missing.append("domestic_freight_boundary_unknown")
                freight_per_unit = None
            tax_included = item.get("tax_included")
            tax_per_unit: Decimal | None
            if tax_included is True:
                tax_per_unit = Decimal("0")
            elif tax_included is False:
                tax_amount = _number(signals, "purchase_tax_cny_per_unit")
                tax_rate = _number(signals, "purchase_tax_rate")
                if tax_amount is not None:
                    tax_per_unit = tax_amount
                elif tax_rate is not None and unit_price is not None:
                    tax_per_unit = unit_price * tax_rate
                else:
                    missing.append("purchase_tax_amount_or_rate_missing")
                    tax_per_unit = None
            else:
                missing.append("purchase_tax_boundary_unknown")
                tax_per_unit = None
            if missing:
                excluded.append(
                    {
                        "external_item_id": item["external_item_id"],
                        "supplier_ref": item["supplier_ref"],
                        "observed_quantity": observed_quantity,
                        "min_order_quantity": moq,
                        "reasons": sorted(set(missing)),
                        "evidence_id": item["evidence_id"],
                    }
                )
                continue
            assert unit_price is not None
            assert freight_per_unit is not None
            assert tax_per_unit is not None
            landed = unit_price + freight_per_unit + tax_per_unit
            confidence = Decimal(item["confidence"])
            reliability = (
                _number(signals, "supplier_reliability")
                or confidence
            )
            reliability = min(Decimal("1"), reliability)
            lead_days = _number(signals, "lead_time_days") or Decimal("30")
            observed_at = _timestamp(
                item["observed_at"], "supplier observed_at"
            )
            stale = not (
                timedelta(0) <= as_of - observed_at <= max_age
            )
            risk_rate = (
                (Decimal("1") - confidence) * Decimal("0.20")
                + (Decimal("1") - reliability) * Decimal("0.15")
                + min(Decimal("0.15"), lead_days / Decimal("200"))
                + (Decimal("0.20") if stale else Decimal("0"))
                + (
                    Decimal("0.05")
                    if signals.get("return_terms_verified") is not True
                    else Decimal("0")
                )
            )
            risk_adjusted = _money(landed * (Decimal("1") + risk_rate))
            ranked.append(
                {
                    "item": item,
                    "unit_price": _money(unit_price),
                    "freight_per_unit": _money(freight_per_unit),
                    "tax_per_unit": _money(tax_per_unit),
                    "landed_price": _money(landed),
                    "risk_adjusted_landed": risk_adjusted,
                    "confidence": confidence,
                    "reliability": reliability,
                    "lead_days": lead_days,
                    "stale": stale,
                    "risk_rate": risk_rate,
                }
            )
        if not ranked:
            fallback = max(
                options,
                key=lambda item: (
                    Decimal(item["confidence"]),
                    _timestamp(item["observed_at"], "supplier observed_at"),
                    item["fingerprint"],
                ),
            )
            return fallback, {
                "status": "no_data",
                "supplier_count": len(options),
                "comparison_quantity": comparison_quantity,
                "selected": None,
                "selection_reason": (
                    "No supplier has comparable exact-quantity unit price "
                    "with explicit tax and domestic-freight boundaries"
                ),
                "pareto_frontier": [],
                "alternatives": [],
                "excluded": excluded,
                "lowest_displayed_price_is_automatically_best": False,
            }
        ranked.sort(
            key=lambda row: (
                row["stale"],
                row["risk_adjusted_landed"],
                -row["reliability"],
                row["lead_days"],
                row["item"]["fingerprint"],
            )
        )
        pareto = []
        for row in ranked:
            dominated = any(
                other is not row
                and other["risk_adjusted_landed"]
                <= row["risk_adjusted_landed"]
                and other["lead_days"] <= row["lead_days"]
                and other["reliability"] >= row["reliability"]
                and (
                    other["risk_adjusted_landed"]
                    < row["risk_adjusted_landed"]
                    or other["lead_days"] < row["lead_days"]
                    or other["reliability"] > row["reliability"]
                )
                for other in ranked
            )
            if not dominated:
                pareto.append(row)
        selected = ranked[0]

        def view(row: dict[str, Any]) -> dict[str, Any]:
            return {
                "external_item_id": row["item"]["external_item_id"],
                "supplier_ref": row["item"]["supplier_ref"],
                "platform": row["item"].get("marketplace", "unknown"),
                "source_url": row["item"].get("source_url"),
                "exact_variant": row["item"]["variant_key"],
                "displayed_price": row["item"]["displayed_price"],
                "price_scope": row["item"]["price_scope"],
                "unit_price": str(row["unit_price"]),
                "comparison_quantity": comparison_quantity,
                "freight_per_unit": str(row["freight_per_unit"]),
                "tax_per_unit": str(row["tax_per_unit"]),
                "currency": row["item"]["currency"],
                "risk_adjusted_landed": str(
                    row["risk_adjusted_landed"]
                ),
                "risk_rate": str(
                    row["risk_rate"].quantize(RATE)
                ),
                "lead_time_days": str(row["lead_days"]),
                "reliability": str(row["reliability"]),
                "stale": row["stale"],
                "evidence_id": row["item"]["evidence_id"],
            }

        selection = {
            "status": "selected",
            "supplier_count": len(ranked),
            "observed_supplier_count": len(options),
            "comparison_quantity": comparison_quantity,
            "selected": view(selected),
            "selection_reason": (
                "lowest risk-adjusted landed cost after exact variant, "
                "MOQ, tax/freight, freshness, lead-time, reliability "
                "and return-term controls"
            ),
            "pareto_frontier": [view(row) for row in pareto],
            "alternatives": [view(row) for row in ranked[1:10]],
            "excluded": excluded,
            "lowest_displayed_price_is_automatically_best": False,
        }
        return selected["item"], selection

    @staticmethod
    def _cheap_prescore(
        *,
        market_cohort: dict[str, Any],
        supplier_selection: dict[str, Any],
    ) -> str:
        confidence = Decimal(market_cohort["confidence"])
        supplier = supplier_selection["selected"]
        if supplier is None:
            return "0.00"
        reliability = Decimal(supplier["reliability"])
        cohort_depth = min(
            Decimal("1"),
            Decimal(market_cohort["comparable_listing_count"])
            / Decimal("10"),
        )
        score = (confidence * 45) + (reliability * 35) + (cohort_depth * 20)
        return str(score.quantize(MONEY))

    def _evaluate(
        self,
        match: dict[str, Any],
        *,
        store_ref: str,
        as_of: datetime,
        max_inventory_cash_cny: Decimal,
        cm3_floor_cny: Decimal,
        evidence_class: str | None = None,
        scoped_fx_rates: dict[str, dict[str, Any]] | None = None,
        scoped_product_content: dict[str, dict[str, Any]] | None = None,
        scope_authority: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        market = match["market"]
        supplier = match["supplier"]
        market_signals = market.get("market_signals") or {}
        supply_signals = supplier.get("supply_signals") or {}
        evidence_ids = sorted(
            {
                market["evidence_id"],
                supplier["evidence_id"],
                *match["market_cohort"]["evidence_ids"],
                *(
                    item["evidence_id"]
                    for item in match["supplier_selection"][
                        "pareto_frontier"
                    ]
                ),
                *self._signal_evidence_ids(market_signals),
                *self._signal_evidence_ids(supply_signals),
                *self._signal_evidence_ids(
                    market.get("experiment_readbacks") or {}
                ),
            }
        )
        valid_evidence, invalid_evidence = self._valid_evidence(evidence_ids)
        sale_cny, sale_fx = self._to_cny(
            Decimal(match["revenue_scenario"]["unit_price"]),
            market["currency"],
            as_of,
            scoped_fx_rates=scoped_fx_rates,
        )
        selected_supplier_cost = match["supplier_selection"]["selected"]
        if selected_supplier_cost is None:
            purchase_cny, purchase_fx = None, None
        else:
            purchase_cny, purchase_fx = self._to_cny(
                Decimal(selected_supplier_cost["unit_price"]),
                supplier["currency"],
                as_of,
                scoped_fx_rates=scoped_fx_rates,
            )
        economics = self._economics(
            sale_cny=sale_cny,
            purchase_cny=purchase_cny,
            market_signals=market_signals,
            supply_signals={
                **supply_signals,
                "checkout_evidence_id": supplier["evidence_id"],
            },
            valid_evidence=valid_evidence,
        )
        score = self._score(
            market_signals=market_signals,
            supply_signals=supply_signals,
            economics=economics,
            confidence=min(
                Decimal(market["confidence"]),
                Decimal(supplier["confidence"]),
            ),
            supplier_density=len(match["supplier_options"]),
        )
        raw_flags = market_signals.get("category_flags") or []
        if isinstance(raw_flags, str):
            raw_flags = [raw_flags]
        supply_flags = supply_signals.get("category_flags") or []
        if isinstance(supply_flags, str):
            supply_flags = [supply_flags]
        identity = market.get("product_identity") or {}
        category_flags = [*raw_flags, *supply_flags]
        if isinstance(identity, dict):
            category_flags.extend(
                value
                for key, value in identity.items()
                if str(key).strip().lower() == "category"
            )
        resolved_class = classify_evidence_class(
            evidence_class=evidence_class,
            category_flags=category_flags,
            product_kind=market_signals.get("product_kind"),
            operation_mode="auto",
            target_market=self._target_market(store_ref),
        )
        content = self._content(
            market=market,
            supplier=supplier,
            candidate_key=match.get("candidate_key"),
            evidence_class=resolved_class.value,
            scoped_product_content=scoped_product_content,
        )
        ozon_global = self.ozon_rules.evaluate(
            {
                "sku_ref": str(
                    market.get("target_product_id")
                    or market["external_item_id"]
                ),
                "country": "CN",
                "locale": "zh",
                "passport": market_signals.get("ozon_passport") or {},
                "content": market_signals.get("ozon_content") or {},
                "prices": market_signals.get("ozon_prices") or {},
                "fulfillment": (
                    market_signals.get("ozon_fulfillment") or {}
                ),
                "quality": market_signals.get("ozon_quality") or {},
                "fee": market_signals.get("ozon_fee") or {},
                "settlement": (
                    market_signals.get("ozon_settlement") or {}
                ),
                "api_access": (
                    market_signals.get("ozon_api_access") or {}
                ),
                "analytics": (
                    market_signals.get("ozon_official_analytics") or {}
                ),
                "downside_cm3_cny": economics["downside"]["cm3_cny"],
            },
            as_of=_iso(as_of),
        )
        variants = self._variants(
            market=market,
            valid_evidence=valid_evidence,
        )
        blockers: list[str] = []
        if not match["fresh"]:
            blockers.append("observation_stale")
        if sale_cny is None or purchase_cny is None:
            blockers.append("fx_rate_or_date_missing")
        if selected_supplier_cost is None:
            blockers.append("supplier_cost_boundaries_not_comparable")
        if invalid_evidence:
            blockers.append("evidence_integrity_failed")
        if economics["downside"]["cm3_cny"] is None:
            blockers.append("downside_cm3_unavailable")
        elif Decimal(economics["downside"]["cm3_cny"]) <= cm3_floor_cny:
            blockers.append("downside_cm3_not_positive")
        if content["passport_required"]:
            if not economics["cost_evidence_complete"]:
                blockers.append(
                    "fifteen_component_cost_evidence_incomplete"
                )
        elif not economics["key_cost_evidence_complete"]:
            blockers.append("key_cost_evidence_incomplete")
        cash = economics["downside"]["inventory_cash_cny"]
        if cash is None or Decimal(cash) > max_inventory_cash_cny:
            blockers.append("inventory_cash_exceeds_budget")
        required_market = {
            "competitor_count",
            "review_count",
            "rating",
            "stock",
        }
        if required_market - market_signals.keys():
            blockers.append("market_signal_minimum_missing")
        sales_proxy_type = market_signals.get("sales_proxy_type")
        sales_proxy_value = _number(market_signals, "sales_proxy_value")
        if (
            sales_proxy_type not in SALES_PROXY_TYPES
            or sales_proxy_value is None
            or sales_proxy_value <= 0
        ):
            blockers.append("market_demand_proxy_no_data")
        if content["passport_required"]:
            if not content["passport_ready"]:
                blockers.append("passport_incomplete")
        else:
            missing_basics = sorted(
                role
                for role, ready in content["basic_evidence_status"].items()
                if not ready
            )
            if missing_basics:
                blockers.append("basic_evidence_incomplete")
        if not content["media_ready"]:
            blockers.append("media_rights_or_qa_incomplete")
        if not content["content_ready"]:
            blockers.append("listing_content_not_ready")
        if (
            ozon_global["actions"]["pilot_approve"]["status"]
            != "ready"
        ):
            blockers.append("ozon_global_cn_rule_gate_blocked")
        eligible_for_approval = not blockers
        blockers.append("independent_approval_missing")
        pilot_ready = not blockers
        fingerprint = _sha256(
            {
                "candidate_key": match["candidate_key"],
                "market": market["fingerprint"],
                "supplier": supplier["fingerprint"],
                "policy": BATCH_POLICY_ID,
                "ozon_global_cn_rule_registry": (
                    self.ozon_rules.registry_hash
                ),
            }
        )
        strategy = self._strategy(
            score=score,
            economics=economics,
            market_signals=market_signals,
            supply_signals=supply_signals,
            variants=variants,
            pilot_ready=pilot_ready,
            blockers=blockers,
            supplier_density=len(match["supplier_options"]),
            max_inventory_cash_cny=max_inventory_cash_cny,
        )
        state = (
            "pilot"
            if pilot_ready
            else "stop"
            if economics["downside"]["cm3_cny"] is not None
            and Decimal(economics["downside"]["cm3_cny"]) <= cm3_floor_cny
            else "content_ready"
            if content["content_ready"]
            else "evaluate"
        )
        automation = self._automation_state(
            state=state,
            fingerprint=fingerprint,
            evidence_ids=evidence_ids,
            blockers=blockers,
            economics=economics,
            content=content,
            variants=variants,
        )
        procurement = (
            self.sale_triggered_procurement.evaluate(
                store_ref=store_ref,
                product_id=market.get("target_product_id"),
                supply=self._supply_view(
                    supplier,
                    supply_signals,
                    density=len(match["supplier_options"]),
                ),
                economics=economics,
                fresh=match["fresh"],
                as_of=as_of,
                scope_authority=scope_authority,
            )
            if self.sale_triggered_procurement is not None
            else {
                **SaleTriggeredProcurementPolicy.contract(),
                "state": "no_data",
                "source_gaps": ["formal_order_fact_adapter_missing"],
                "external_purchase_write": False,
            }
        )
        candidate = {
            "candidate_key": match["candidate_key"],
            "fingerprint": fingerprint,
            "canonical_product_id": market.get("target_product_id"),
            "identity_match": {
                "status": "exact",
                "product_identity": market["product_identity"],
                "market_item_id": market["id"],
                "supplier_item_id": supplier["id"],
            },
            "sku_identity_card": match["sku_identity_card"],
            "market": {
                **self._market_view(market, market_signals),
                "cohort": match["market_cohort"],
                "own_listing_current_fact": (
                    match["own_listing_current_fact"]
                ),
                "revenue_scenario": {
                    **match["revenue_scenario"],
                    "downside_profit_floor_cny": str(cm3_floor_cny),
                    "profit_floor_status": (
                        "meets_downside_floor"
                        if economics["downside"]["cm3_cny"] is not None
                        and Decimal(
                            economics["downside"]["cm3_cny"]
                        )
                        > cm3_floor_cny
                        else "blocked_or_no_data"
                    ),
                },
            },
            "supply": {
                **self._supply_view(
                    supplier,
                    supply_signals,
                    density=len(match["supplier_options"]),
                ),
                "observed_supplier_density": len(
                    match["observed_supplier_options"]
                ),
                "observed_supplier_marketplaces": sorted(
                    {
                        str(item.get("marketplace"))
                        for item in match["observed_supplier_options"]
                    }
                ),
                "selection": match["supplier_selection"],
            },
            "economics": {
                **economics,
                "sale_fx": sale_fx,
                "purchase_fx": purchase_fx,
                "actual_profit": None,
                "formal_cm3": None,
                "authority": "observed_cost_research_screening",
            },
            "score": score,
            "strategy": strategy,
            "content": content,
            "ozon_global_cn": ozon_global,
            "variant_plan": variants,
            "state": state,
            "eligible_for_approval": eligible_for_approval,
            "pilot_eligible": eligible_for_approval,
            "pilot_eligible_semantics": (
                "deprecated_alias_for_eligible_for_approval"
            ),
            "pilot_ready": pilot_ready,
            "pilot_selection": {
                "status": "ineligible",
                "reason": "approval_allocation_not_run",
                "semantics": (
                    "budget_slot_only_not_approval_permit_or_pilot"
                ),
            },
            "blockers": sorted(set(blockers)),
            "next_action": self._next_action(blockers, strategy),
            "evidence_ids": evidence_ids,
            "invalid_evidence_ids": invalid_evidence,
            "readbacks": market.get("experiment_readbacks") or {},
            "automation": automation,
            "sale_triggered_procurement": procurement,
            "authority": {
                "supplier_offer_created": False,
                "actual_cost_created": False,
                "formal_cm3_created": False,
                "listing_created": False,
                "permit_created": False,
                "ozon_write_performed": False,
            },
        }
        if self.seller_os is not None:
            candidate["seller_os"] = self.seller_os.candidate_matrix(
                candidate
            )
        return candidate

    def _project_procurement_tasks(
        self,
        *,
        candidates: list[dict[str, Any]],
        scope_authority: dict[str, str] | None,
        store_ref: str,
        actor_id: str,
        as_of: datetime,
    ) -> list[dict[str, Any]]:
        if scope_authority is None:
            return []
        tasks: list[dict[str, Any]] = []
        for candidate in candidates:
            procurement = candidate.get("sale_triggered_procurement") or {}
            state = procurement.get("state")
            if state not in {
                "eligible_for_procurement_review",
                "order_received_cost_or_supply_escalation",
            }:
                continue
            order_ids = sorted(
                {
                    str(item)
                    for item in (
                        procurement.get("trigger_order_external_ids") or []
                    )
                    if str(item).strip()
                }
            )
            order_set_sha256 = _sha256(order_ids)
            task_kind = (
                "sale_triggered_procurement_review"
                if state == "eligible_for_procurement_review"
                else "sale_triggered_procurement_escalation"
            )
            task = self.operating_tasks.ensure_internal_task(
                task_kind=task_kind,
                scope={
                    "tenant_ref": scope_authority["tenant_ref"],
                    "entity_ref": scope_authority["entity_ref"],
                    "store_ref": store_ref,
                    "scope_authority_sha256": scope_authority[
                        "scope_grant_authority_sha256"
                    ],
                    "product_id": candidate.get("canonical_product_id"),
                    "order_set_sha256": order_set_sha256,
                },
                title=(
                    "真实 Ozon 订单待采购复核"
                    if state == "eligible_for_procurement_review"
                    else "真实 Ozon 订单供货/利润异常"
                ),
                severity=(
                    "high"
                    if state == "eligible_for_procurement_review"
                    else "critical"
                ),
                owner="procurement",
                evidence_ids=list(
                    procurement.get("trigger_evidence_ids") or []
                ),
                snapshot={
                    "state": state,
                    "product_id": candidate.get("canonical_product_id"),
                    "order_external_ids": order_ids,
                    "fact_ids": list(
                        procurement.get("trigger_fact_ids") or []
                    ),
                    "recommended_review_quantity": procurement.get(
                        "recommended_review_quantity",
                        0,
                    ),
                    "blockers": list(procurement.get("blockers") or []),
                    "next_action": procurement.get("next_action"),
                    "supplier_order_created": False,
                    "payment_created": False,
                    "approval_created": False,
                    "permit_created": False,
                    "external_purchase_write": False,
                },
                actor_id=actor_id,
                as_of=_iso(as_of),
            )
            task_projection = {
                "id": task["id"],
                "status": task["status"],
                "owner": task["owner"],
                "task_kind": task_kind,
                "order_set_sha256": order_set_sha256,
                "external_write_allowed": False,
            }
            procurement["operating_task"] = task_projection
            tasks.append(task_projection)
        return tasks

    @staticmethod
    def _select_pilots(
        candidates: list[dict[str, Any]],
        *,
        pilot_limit: int,
        max_batch_inventory_cash_cny: Decimal,
    ) -> dict[str, Any]:
        selected = []
        waitlisted = []
        cumulative_cash = Decimal("0")
        eligible = [
            candidate
            for candidate in candidates
            if candidate["eligible_for_approval"] is True
        ]
        for candidate in eligible:
            raw_cash = candidate["economics"]["downside"].get(
                "inventory_cash_cny"
            )
            cash = _decimal(raw_cash, "inventory_cash_cny")
            within_count = len(selected) < pilot_limit
            within_cash = (
                cumulative_cash + cash <= max_batch_inventory_cash_cny
            )
            if within_count and within_cash:
                cumulative_cash += cash
                candidate["pilot_selection"] = {
                    "status": "approval_allocation_selected",
                    "reason": (
                        "stable rank within approval allocation and batch "
                        "cash budget; no Approval or Permit created"
                    ),
                    "semantics": (
                        "budget_slot_only_not_approval_permit_or_pilot"
                    ),
                    "cumulative_inventory_cash_cny": str(
                        _money(cumulative_cash)
                    ),
                }
                selected.append(candidate["fingerprint"])
            else:
                reason = (
                    "pilot_limit_reached"
                    if not within_count
                    else "batch_inventory_cash_budget_reached"
                )
                candidate["pilot_selection"] = {
                    "status": "approval_waitlist",
                    "reason": reason,
                    "semantics": (
                        "waitlist_only_not_approval_permit_or_pilot"
                    ),
                    "cumulative_inventory_cash_cny": str(
                        _money(cumulative_cash)
                    ),
                }
                waitlisted.append(candidate["fingerprint"])
        return {
            "pilot_limit": pilot_limit,
            "max_batch_inventory_cash_cny": str(
                _money(max_batch_inventory_cash_cny)
            ),
            "eligible_for_approval": len(eligible),
            "approval_allocation_selected": len(selected),
            "approval_waitlist": len(waitlisted),
            "eligible": len(eligible),
            "selected": len(selected),
            "waitlisted": len(waitlisted),
            "compatibility_aliases": {
                "eligible": "eligible_for_approval",
                "selected": "approval_allocation_selected",
                "waitlisted": "approval_waitlist",
                "deprecated": True,
            },
            "selected_fingerprints": selected,
            "waitlisted_fingerprints": waitlisted,
            "selected_inventory_cash_cny": str(_money(cumulative_cash)),
            "independent_approval_created": False,
            "permit_created": False,
            "pilot_started": False,
            "external_write_performed": False,
        }

    def _to_cny(
        self,
        amount: Decimal,
        currency: str,
        as_of: datetime,
        *,
        scoped_fx_rates: dict[str, dict[str, Any]] | None = None,
    ) -> tuple[Decimal | None, dict[str, Any] | None]:
        if currency == "CNY":
            return _money(amount), {
                "base_currency": "CNY",
                "quote_currency": "CNY",
                "rate": "1",
                "effective_at": _iso(as_of),
                "evidence_id": None,
            }
        if scoped_fx_rates is not None:
            selected = scoped_fx_rates.get(currency)
            if selected is None:
                return None, None
            if (
                selected.get("base_currency") != currency
                or selected.get("quote_currency") != "CNY"
                or _timestamp(
                    selected.get("effective_at"),
                    "Scoped FX effective_at",
                )
                > as_of
            ):
                return None, None
            evidence_id = str(selected.get("evidence_id") or "").strip()
            if not evidence_id or not self.evidence.verify(evidence_id).valid:
                return None, None
            rate = _decimal(selected.get("rate"), "Scoped FX rate")
            if rate <= 0:
                return None, None
            return _money(amount * rate), {
                "id": selected.get("id"),
                "base_currency": currency,
                "quote_currency": "CNY",
                "rate": str(rate),
                "effective_at": selected["effective_at"],
                "evidence_id": evidence_id,
                "authority": "scoped_evidence_bound_fx_snapshot",
            }
        rates = [
            rate
            for rate in self.finance.list_fx_rates(base_currency=currency)
            if rate.quote_currency == "CNY"
            and _timestamp(rate.effective_at, "FX effective_at") <= as_of
        ]
        if not rates:
            return None, None
        selected = max(
            rates,
            key=lambda item: _timestamp(
                item.effective_at, "FX effective_at"
            ),
        )
        if not self.evidence.verify(selected.evidence_id).valid:
            return None, None
        rate = Decimal(selected.rate)
        return _money(amount * rate), {
            "id": selected.id,
            "base_currency": selected.base_currency,
            "quote_currency": selected.quote_currency,
            "rate": selected.rate,
            "effective_at": selected.effective_at,
            "evidence_id": selected.evidence_id,
        }

    def _economics(
        self,
        *,
        sale_cny: Decimal | None,
        purchase_cny: Decimal | None,
        market_signals: dict[str, Any],
        supply_signals: dict[str, Any],
        valid_evidence: set[str],
    ) -> dict[str, Any]:
        if sale_cny is None or purchase_cny is None:
            empty = {
                "revenue_cny": (
                    str(sale_cny) if sale_cny is not None else None
                ),
                "total_cost_cny": None,
                "cm3_cny": None,
                "cm3_rate": None,
                "inventory_cash_cny": None,
                "components": [],
                "conservation_delta_cny": None,
            }
            return {
                "baseline": empty,
                "downside": empty,
                "cost_evidence_complete": False,
                "key_cost_evidence_complete": False,
                "missing_key_cost_components": sorted(KEY_COST_COMPONENTS),
                "estimated_component_names": [],
                "landed_cost_interval_cny": None,
                "profit_interval_cny": None,
                "turnover": self._turnover(market_signals),
            }
        baseline = self._cost_case(
            case="baseline",
            revenue=sale_cny,
            purchase=purchase_cny,
            market_signals=market_signals,
            supply_signals=supply_signals,
            valid_evidence=valid_evidence,
        )
        downside = self._cost_case(
            case="downside",
            revenue=sale_cny,
            purchase=purchase_cny,
            market_signals=market_signals,
            supply_signals=supply_signals,
            valid_evidence=valid_evidence,
        )
        all_observed = all(
            component["authority"] == "evidence_backed_observation"
            for component in downside["components"]
            if component["name"] != "purchase_buffer"
        )
        baseline_backed = {
            component["name"]
            for component in baseline["components"]
            if component["authority"] == "evidence_backed_observation"
        }
        downside_backed = {
            component["name"]
            for component in downside["components"]
            if component["authority"] == "evidence_backed_observation"
        }
        backed_names = baseline_backed & downside_backed
        missing_key = sorted(KEY_COST_COMPONENTS - backed_names)
        estimated_component_names = sorted(
            {
                component["name"]
                for component in downside["components"]
                if component["authority"] != "evidence_backed_observation"
            }
        )
        baseline_total = Decimal(baseline["total_cost_cny"])
        downside_total = Decimal(downside["total_cost_cny"])
        landed_low = _money(min(baseline_total, downside_total))
        landed_high = _money(max(baseline_total, downside_total))
        profit_low = _money(sale_cny - landed_high)
        profit_high = _money(sale_cny - landed_low)
        risk_adjusted = RiskAdjustedProfitSimulator().simulate(
            revenue_cny=sale_cny,
            baseline_components=baseline["components"],
            downside_components=downside["components"],
            seed_input=f"{str(sale_cny)}:{str(purchase_cny)}",
            return_rate=Decimal(
                str(
                    market_signals.get("returns_refunds_rate")
                    or POLICY["baseline"]["returns_refunds_rate"]
                )
            ),
            supply_failure_prob=Decimal(
                str(supply_signals.get("supply_failure_prob") or "0.05")
            ),
            price_war_prob=Decimal(
                str(market_signals.get("price_war_prob") or "0.10")
            ),
        )
        return {
            "baseline": baseline,
            "downside": downside,
            "risk_adjusted": risk_adjusted,
            "cost_evidence_complete": all_observed,
            "key_cost_evidence_complete": not missing_key,
            "missing_key_cost_components": missing_key,
            "estimated_component_names": estimated_component_names,
            "landed_cost_interval_cny": {
                "low": str(landed_low),
                "high": str(landed_high),
            },
            "profit_interval_cny": {
                "low": str(profit_low),
                "high": str(profit_high),
            },
            "turnover": self._turnover(market_signals),
        }

    def _cost_case(
        self,
        *,
        case: str,
        revenue: Decimal,
        purchase: Decimal,
        market_signals: dict[str, Any],
        supply_signals: dict[str, Any],
        valid_evidence: set[str],
    ) -> dict[str, Any]:
        policy = POLICY[case]
        components: list[dict[str, Any]] = []
        precision_blockers: list[str] = []

        def add(
            name: str,
            amount: Decimal,
            *,
            evidence_key: str | None = None,
            observed: bool = False,
        ) -> None:
            evidence_id = None
            if evidence_key:
                evidence_id = (
                    market_signals.get(evidence_key)
                    or supply_signals.get(evidence_key)
                )
            backed = bool(
                observed and evidence_id and evidence_id in valid_evidence
            )
            components.append(
                {
                    "name": name,
                    "amount_cny": str(_money(amount)),
                    "authority": (
                        "evidence_backed_observation"
                        if backed
                        else "policy_estimate"
                    ),
                    "evidence_id": evidence_id if backed else None,
                }
            )

        add(
            "procurement",
            purchase,
            evidence_key="checkout_evidence_id",
            observed=True,
        )
        add(
            "purchase_buffer",
            purchase * Decimal(policy["purchase_buffer_rate"]),
        )
        domestic = _number(supply_signals, "domestic_freight_cny")
        add(
            "domestic_logistics",
            domestic
            if domestic is not None
            else Decimal(policy["domestic_logistics_fixed_cny"]),
            evidence_key="domestic_freight_evidence_id",
            observed=domestic is not None,
        )
        packaging = _number(supply_signals, "packaging_cny")
        add(
            "packaging",
            packaging
            if packaging is not None
            else Decimal(policy["packaging_fixed_cny"]),
            evidence_key="packaging_evidence_id",
            observed=packaging is not None,
        )
        international = _number(
            supply_signals, "international_logistics_cny"
        )
        weight = _number(supply_signals, "package_gross_weight_kg")
        if international is None:
            international = (
                weight
                * Decimal(policy["international_logistics_per_kg_cny"])
                if weight is not None
                else Decimal(
                    policy["international_logistics_fallback_cny"]
                )
            )
        add(
            "international_logistics",
            international,
            evidence_key="international_logistics_evidence_id",
            observed=(
                "international_logistics_cny" in supply_signals
                or weight is not None
            ),
        )
        for name in (
            "customs",
            "marketplace_commission",
            "fulfillment_last_mile",
            "warehousing",
            "advertising",
            "returns_refunds",
            "discounts_promotions",
            "taxes",
            "fx_reserve",
            "loss_damage",
        ):
            signal_key = f"{name}_rate"
            observed_rate = _number(market_signals, signal_key)
            if name == "marketplace_commission":
                required_fee_dimensions = (
                    "fee_category",
                    "fee_mode",
                    "fee_price_band",
                    "fee_effective_from",
                    "fee_order_date",
                )
                fee_evidence = market_signals.get(
                    "marketplace_commission_evidence_id"
                )
                if (
                    observed_rate is None
                    or fee_evidence not in valid_evidence
                    or any(
                        not market_signals.get(field)
                        for field in required_fee_dimensions
                    )
                ):
                    precision_blockers.append(
                        "versioned_fee_row_evidence_missing"
                    )
            rate = (
                _rate(observed_rate, signal_key)
                if observed_rate is not None
                else Decimal(policy[f"{name}_rate"])
            )
            add(
                name,
                revenue * rate,
                evidence_key=f"{name}_evidence_id",
                observed=observed_rate is not None,
            )
        if [component["name"] for component in components] != list(
            COMPONENT_ORDER
        ):
            raise RuntimeError("Fifteen-component cost order drift")
        total = _money(
            sum(
                Decimal(component["amount_cny"])
                for component in components
            )
        )
        cm3 = _money(revenue - total)
        delta = _money(revenue - total - cm3)
        if delta != Decimal("0.00"):
            raise RuntimeError("Fifteen-component cost conservation failed")
        inventory_units = POLICY["pilot_inventory_units"]["maximum"]
        return {
            "revenue_cny": str(_money(revenue)),
            "total_cost_cny": str(total),
            "cm3_cny": None if precision_blockers else str(cm3),
            "cm3_rate": (
                None
                if precision_blockers
                else str(
                    (cm3 / revenue).quantize(
                        RATE, rounding=ROUND_HALF_UP
                    )
                )
            ),
            "screening_cm3_cny": str(cm3),
            "screening_cm3_rate": str(
                (cm3 / revenue).quantize(RATE, rounding=ROUND_HALF_UP)
            ),
            "precision_status": (
                "wide_policy_screening_only"
                if precision_blockers
                else "evidence_bound_estimate"
            ),
            "precision_blockers": sorted(set(precision_blockers)),
            "inventory_cash_cny": str(
                _money(
                    sum(
                        Decimal(component["amount_cny"])
                        for component in components[:5]
                    )
                    * inventory_units
                )
            ),
            "components": components,
            "conservation_delta_cny": (
                None if precision_blockers else str(delta)
            ),
            "screening_conservation_delta_cny": str(delta),
        }

    def _score(
        self,
        *,
        market_signals: dict[str, Any],
        supply_signals: dict[str, Any],
        economics: dict[str, Any],
        confidence: Decimal,
        supplier_density: int,
    ) -> dict[str, str]:
        market = Decimal("0")
        if _number(market_signals, "competitor_count") is not None:
            competitors = _number(
                market_signals, "competitor_count"
            ) or Decimal("0")
            market += min(Decimal("8"), competitors / Decimal("2"))
        rating = _number(market_signals, "rating")
        if rating is not None:
            market += min(Decimal("8"), rating / Decimal("5") * 8)
        reviews = _number(market_signals, "review_count")
        if reviews is not None:
            market += min(Decimal("6"), reviews / Decimal("50"))
        if market_signals.get("stockout_opportunity") is True:
            market += Decimal("4")
        if market_signals.get("seasonality_status") == "in_season":
            market += Decimal("4")
        supply = min(Decimal("8"), Decimal(supplier_density) * 2)
        lead = _number(supply_signals, "lead_time_days")
        if lead is not None:
            supply += max(
                Decimal("0"), Decimal("6") - lead / Decimal("5")
            )
        distance = _number(
            supply_signals, "distance_to_consolidation_km"
        )
        if distance is not None:
            supply += max(
                Decimal("0"), Decimal("6") - distance / Decimal("500")
            )
        economics_score = Decimal("0")
        downside_rate = economics["downside"]["cm3_rate"]
        if downside_rate is not None:
            economics_score = max(
                Decimal("0"),
                min(Decimal("35"), Decimal(downside_rate) * 100),
            )
        risk = min(Decimal("15"), confidence * 15)
        total = min(
            Decimal("100"),
            market + supply + economics_score + risk,
        )
        return {
            "total": str(total.quantize(MONEY)),
            "market": str(market.quantize(MONEY)),
            "supply": str(supply.quantize(MONEY)),
            "economics": str(economics_score.quantize(MONEY)),
            "evidence_confidence": str(risk.quantize(MONEY)),
            "authority": "server_owned_versioned_score",
        }

    def _strategy(
        self,
        *,
        score: dict[str, str],
        economics: dict[str, Any],
        market_signals: dict[str, Any],
        supply_signals: dict[str, Any],
        variants: dict[str, Any],
        pilot_ready: bool,
        blockers: list[str],
        supplier_density: int,
        max_inventory_cash_cny: Decimal,
    ) -> dict[str, Any]:
        downside = economics["downside"]["cm3_cny"]
        total = Decimal(score["total"])
        classification = "exploration"
        reason = "精确匹配已形成，但证据或经营门仍需补齐"
        tactics: list[str] = []
        if market_signals.get("bundle_relationship_verified") is True:
            tactics.append("bundle")
        if market_signals.get("accessory_relationship_verified") is True:
            tactics.append("accessory")
        if variants["ready"]:
            tactics.append("verified_parent_variant")
        if downside is not None and Decimal(downside) <= 0:
            classification = "eliminate"
            reason = "悲观 CM3 不为正"
        elif (
            market_signals.get("store_group_copy_eligible") is True
            and variants["readback_evidence_complete"]
            and variants["settlement_cycles"] >= 2
        ):
            classification = "store_cluster"
            reason = "赢家回读和两个结算周期已完成，可提出店群复制评审"
        elif (
            market_signals.get("brand_strategy_eligible") is True
            and variants["settlement_cycles"] >= 2
        ):
            classification = "brand"
            reason = "品牌授权、回读与两个结算周期已形成品牌评审依据"
        elif pilot_ready and total >= 85:
            classification = "hero"
            reason = "高评分、完整门禁和真实回读满足 Hero SKU 评审"
        elif pilot_ready and total >= 75:
            classification = "refined"
            reason = "高评分且所有 Pilot 门已满足"
        elif pilot_ready and total >= 60:
            classification = "controlled_distribution"
            reason = "标准品通过观察成本与全部治理门"
        elif supplier_density >= 3 and total >= 55 and downside is not None:
            classification = "controlled_distribution"
            reason = "供应密度与评分可探索，但仍需完成治理门"
        return {
            "classification": classification,
            "tactics": tactics,
            "reason": reason,
            "evidence_gaps": sorted(set(blockers)),
            "policy_target": POLICY["resource_mix_target"],
            "budget": {
                "inventory_units": "1-3",
                "maximum_inventory_cash_cny": str(
                    _money(max_inventory_cash_cny)
                ),
                "advertising": "0 or independently approved strict cap",
            },
            "promotion_gates": [
                "downside CM3 > 0 and fifteen-component evidence complete",
                "Passport + owned/licensed media + Media QA",
                "independent approval + one-time Permit + Readback + stop-loss",
                (
                    "24h/72h/7d readback plus two settlement cycles "
                    "before category/store-group replication"
                ),
            ],
            "automatic_strategy_execution": False,
        }

    @staticmethod
    def _automation_state(
        *,
        state: str,
        fingerprint: str,
        evidence_ids: list[str],
        blockers: list[str],
        economics: dict[str, Any],
        content: dict[str, Any],
        variants: dict[str, Any],
    ) -> dict[str, Any]:
        evaluate_complete = (
            economics["downside"]["cm3_cny"] is not None
            and economics["downside"]["conservation_delta_cny"] == "0.00"
            and economics["cost_evidence_complete"]
        )
        reconciled = variants["settlement_cycles"] >= 2
        completed = {
            "observe": True,
            "match": True,
            "evaluate": evaluate_complete,
            "content_ready": content["content_ready"],
            "pilot": False,
            "scale": False,
            "stop": state == "stop",
            "reconcile": reconciled,
        }
        definitions = (
            (
                "observe",
                "market_research",
                24,
                ["source", "observed_at", "Evidence", "confidence"],
            ),
            (
                "match",
                "product_data",
                24,
                ["candidate_key", "exact product identity", "exact variant"],
            ),
            (
                "evaluate",
                "commerce_finance",
                48,
                ["15 components", "FX date", "conservation"],
            ),
            (
                "content_ready",
                "product_content",
                72,
                ["three Passports", "media rights", "Media QA"],
            ),
            (
                "pilot",
                "independent_approver",
                24,
                ["approval", "one-time Permit", "stop-loss"],
            ),
            (
                "scale",
                "commerce",
                168,
                ["24h", "72h", "7d readbacks"],
            ),
            (
                "stop",
                "commerce",
                24,
                ["stop reason", "Readback", "Compensation if required"],
            ),
            (
                "reconcile",
                "finance",
                504,
                ["settlement", "fees", "bank evidence"],
            ),
        )
        stages = []
        for name, owner, sla_hours, required in definitions:
            status = (
                "current"
                if name == state
                else "completed"
                if completed[name]
                else "blocked"
                if name in {"pilot", "scale", "reconcile"} and blockers
                else "pending"
            )
            stages.append(
                {
                    "state": name,
                    "status": status,
                    "owner": owner,
                    "sla_hours": sla_hours,
                    "evidence_required": required,
                    "evidence_ids": evidence_ids
                    if status == "completed"
                    else [],
                    "budget": (
                        {
                            "inventory_units": "1-3",
                            "advertising": (
                                "0 or independently approved strict cap"
                            ),
                        }
                        if name in {"pilot", "scale"}
                        else {"external_spend_allowed": False}
                    ),
                    "fingerprint": _sha256(
                        {
                            "candidate": fingerprint,
                            "state": name,
                            "contract": BATCH_CONTRACT_VERSION,
                        }
                    ),
                }
            )
        return {
            "current_state": state,
            "stages": stages,
            "queue_authority": "existing OperationsQueue/OperatingTask",
            "execution_authority": (
                "existing Approval/Permit/Readback/Kill Switch/Compensation"
            ),
            "new_workflow_engine_created": False,
            "external_side_effect": False,
        }

    def _content(
        self,
        *,
        market: dict[str, Any],
        supplier: dict[str, Any],
        candidate_key: str | None = None,
        evidence_class: str = "auto_scale",
        scoped_product_content: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        identity = market.get("product_identity") or {}
        market_signals = market.get("market_signals") or {}
        supply_signals = supplier.get("supply_signals") or {}
        title = market["title"].strip()
        russian_ready = any("\u0400" <= char <= "\u04ff" for char in title)
        attributes = [
            {"name": key, "value": value}
            for key, value in sorted(identity.items())
        ]
        bullets = [
            f"Точная характеристика: {key} — {value}"
            for key, value in sorted(identity.items())[:5]
        ]
        product_id = market.get("target_product_id")
        evidence_policy = policy_for(evidence_class)
        passport_required = evidence_policy.requires_full_passports
        passport_ready = False
        media_ready = False
        passport_status: dict[str, bool] = {}
        approved_assets: list[str] = []
        content_authority = (
            "legacy_repository"
            if scoped_product_content is None
            else "scoped_product_content"
        )
        approved_types: set[str] = set()
        if product_id:
            if scoped_product_content is not None:
                scoped = scoped_product_content.get(product_id)
                if scoped is not None:
                    passport_status = {
                        item["kind"]: item["status"] == "approved"
                        for item in scoped.get("passports", [])
                    }
                    passport_ready = bool(passport_status) and all(
                        passport_status.get(kind.value, False)
                        for kind in PassportType
                    )
                    assets = scoped.get("content_assets", [])
                    approved_assets = [
                        item["id"]
                        for item in assets
                        if item.get("status")
                        == ContentStatus.APPROVED.value
                        and item.get("evidence_ready") is True
                    ]
                    approved_types = {
                        item["content_type"]
                        for item in assets
                        if item["id"] in approved_assets
                    }
                    media_ready = (
                        "image" in approved_types
                        and "copy" in approved_types
                    )
            else:
                try:
                    passports = self.repository.latest_passports(product_id)
                    passport_status = {
                        kind.value: bool(
                            passports.get(kind)
                            and passports[kind].is_approved
                        )
                        for kind in PassportType
                    }
                    passport_ready = all(passport_status.values())
                    assets = self.repository.content_assets_for_product(
                        product_id
                    )
                    approved_assets = [
                        asset.id
                        for asset in assets
                        if asset.status is ContentStatus.APPROVED
                    ]
                    approved_types = {
                        asset.content_type.value
                        for asset in assets
                        if asset.id in approved_assets
                    }
                    media_ready = bool(approved_assets) and market.get(
                        "media_rights_status"
                    ) in {"owned", "licensed"}
                except KeyError:
                    passport_ready = False
                    media_ready = False
        basic_media_checks = _basic_media_checks_status(market_signals)
        basic_media_failed = sorted(
            name
            for name, status in basic_media_checks.items()
            if status == "failed"
        )
        basic_media_gaps = sorted(
            name
            for name, status in basic_media_checks.items()
            if status != "passed"
        )
        if not passport_required:
            # Trial phase: the six basic media checks are the media gate.
            # Approved-asset machinery remains a scale-up requirement.
            media_ready = not basic_media_failed
        basic_evidence_status = _basic_evidence_status(
            market=market,
            supplier=supplier,
            candidate_key=candidate_key,
            media_ready=media_ready,
            market_signals=market_signals,
            supply_signals=supply_signals,
            product_id=product_id,
            scoped_product_content=scoped_product_content,
        )
        basic_evidence_ready = all(basic_evidence_status.values())
        governance_ready = (
            passport_ready if passport_required else basic_evidence_ready
        )
        content_ready = bool(
            russian_ready
            and attributes
            and governance_ready
            and media_ready
        )
        return {
            "russian_title": title if russian_ready else None,
            "translation_required": not russian_ready,
            "attributes": attributes,
            "selling_points": bullets,
            "detail_sections": [
                "Назначение и сценарий использования",
                "Точные характеристики и комплектация",
                "Размеры, вес и упаковка",
                "Безопасность, сертификация и гарантия",
            ],
            "media_brief": {
                "main_image": "owned/licensed neutral-background product image",
                "detail_images": [
                    "dimensions",
                    "materials",
                    "package contents",
                    "usage scenario",
                ],
                "video": "9:16/1:1/16:9 brief from approved assets only",
                "source_media_rights": [
                    market.get("media_rights_status"),
                    supplier.get("media_rights_status"),
                ],
            },
            "evidence_class": evidence_class,
            "passport_required": passport_required,
            "passport_status": passport_status,
            "passport_ready": passport_ready,
            "basic_evidence_status": basic_evidence_status,
            "basic_evidence_ready": basic_evidence_ready,
            "basic_media_checks": basic_media_checks,
            "basic_media_failed": basic_media_failed,
            "basic_media_gaps": basic_media_gaps,
            "approved_asset_ids": approved_assets,
            "approved_content_types": sorted(approved_types),
            "media_ready": media_ready,
            "content_ready": content_ready,
            "content_authority": content_authority,
            "observed_title_not_content_draft": (
                scoped_product_content is not None
            ),
            "listing_created": False,
        }

    @staticmethod
    def _target_market(store_ref: str) -> str:
        lowered = str(store_ref or "").strip().lower()
        if "eu" in lowered or lowered.startswith("europe"):
            return "eu"
        return "ru"

    @staticmethod
    def _variants(
        *,
        market: dict[str, Any],
        valid_evidence: set[str],
    ) -> dict[str, Any]:
        signals = market.get("market_signals") or {}
        dimensions = signals.get("verified_variant_dimensions") or {}
        readbacks = market.get("experiment_readbacks") or {}
        checkpoints = {
            checkpoint: readbacks.get(checkpoint)
            for checkpoint in ("24h", "72h", "7d")
        }
        winner = all(
            isinstance(value, dict) and value.get("decision") == "scale"
            for value in checkpoints.values()
        )
        readback_evidence_complete = all(
            isinstance(value, dict)
            and isinstance(value.get("evidence_id"), str)
            and value["evidence_id"] in valid_evidence
            for value in checkpoints.values()
        )
        settlement_cycles = int(readbacks.get("settlement_cycles") or 0)
        settlement_evidence_id = readbacks.get("settlement_evidence_id")
        parent_verified = bool(
            market.get("target_product_id")
            and signals.get("parent_sku_verified") is True
            and signals.get("parent_sku_evidence_id") in valid_evidence
        )
        dimension_evidence_valid = bool(
            signals.get("verified_variant_dimensions_evidence_id")
            in valid_evidence
        )
        ready = bool(
            parent_verified
            and winner
            and readback_evidence_complete
            and settlement_cycles >= 2
            and settlement_evidence_id in valid_evidence
            and isinstance(dimensions, dict)
            and dimensions
            and dimension_evidence_valid
        )
        existing_keys = {
            str(value)
            for value in signals.get("existing_variant_candidate_keys", [])
            if isinstance(value, str)
        }
        identity = market.get("product_identity") or {}
        parent_category = str(identity.get("category") or "")
        suggestions: list[dict[str, Any]] = []
        duplicates: list[str] = []
        if ready:
            for name, values in sorted(dimensions.items()):
                if not isinstance(values, list):
                    continue
                for value in values[:20]:
                    attribute = str(name).strip()
                    attribute_value = str(value).strip()
                    if not attribute or not attribute_value:
                        continue
                    child_identity = {
                        **identity,
                        attribute: attribute_value,
                    }
                    if str(child_identity.get("category") or "") != (
                        parent_category
                    ):
                        continue
                    child_key = _sha256(child_identity)
                    if child_key in existing_keys:
                        duplicates.append(child_key)
                        continue
                    suggestions.append(
                        {
                            "dimension": attribute,
                            "value": attribute_value,
                            "candidate_key": child_key,
                            "source": "verified_parent_attribute",
                            "category": parent_category,
                        }
                    )
        return {
            "ready": ready,
            "parent_verified": parent_verified,
            "checkpoints": checkpoints,
            "readback_evidence_complete": readback_evidence_complete,
            "settlement_cycles": settlement_cycles,
            "suggestions": suggestions,
            "duplicate_candidate_keys": sorted(set(duplicates)),
            "duplicate_prevention": (
                "server candidate_key + verified parent attribute + "
                "unchanged category"
            ),
            "category_pollution_allowed": False,
            "fake_attribute_allowed": False,
            "automatic_variant_creation": False,
            "blockers": []
            if ready
            else [
                "verified_parent_attribute_or_evidence_missing",
                "24h_72h_7d_readback_evidence_missing",
                "two_settlement_cycles_evidence_missing",
            ],
        }

    @staticmethod
    def _turnover(signals: dict[str, Any]) -> dict[str, Any]:
        proxy = _number(signals, "sales_proxy_value")
        proxy_type = signals.get("sales_proxy_type")
        stock = _number(signals, "stock")
        if (
            proxy is None
            or proxy <= 0
            or stock is None
            or not proxy_type
        ):
            return {
                "status": "no_data",
                "days_of_inventory_proxy": None,
                "sales_is_actual": False,
            }
        return {
            "status": "proxy",
            "days_of_inventory_proxy": str(
                (stock / proxy * 30).quantize(MONEY)
            ),
            "proxy_type": proxy_type,
            "sales_is_actual": False,
        }

    @staticmethod
    def _market_view(
        market: dict[str, Any], signals: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "marketplace": "ozon",
            "external_item_id": market["external_item_id"],
            "title": market["title"],
            "variant_key": market["variant_key"],
            "price": market["displayed_price"],
            "currency": market["currency"],
            "source_url": market["source_url"],
            "observed_at": market["observed_at"],
            "signals": signals,
            "sales_is_actual": False,
            "sales_semantics": signals.get(
                "sales_proxy_type", "no_data"
            ),
        }

    @staticmethod
    def _supply_view(
        supplier: dict[str, Any],
        signals: dict[str, Any],
        *,
        density: int,
    ) -> dict[str, Any]:
        return {
            "marketplace": supplier["marketplace"],
            "supplier_ref": supplier["supplier_ref"],
            "external_item_id": supplier["external_item_id"],
            "variant_key": supplier["variant_key"],
            "observed_checkout_price": supplier["displayed_price"],
            "currency": supplier["currency"],
            "observed_quantity": supplier["observed_quantity"],
            "moq": supplier["min_order_quantity"],
            "checkout_verified": supplier["checkout_verified"],
            "purchase_available": supplier["purchase_available"],
            "tax_included": supplier["tax_included"],
            "domestic_freight_included": (
                supplier["domestic_freight_included"]
            ),
            "supplier_density": density,
            "signals": signals,
            "source_url": supplier["source_url"],
            "observed_at": supplier["observed_at"],
            "counts_as_supplier_offer": False,
            "counts_as_actual_cost": False,
        }

    def _valid_evidence(
        self, evidence_ids: list[str]
    ) -> tuple[set[str], list[str]]:
        valid: set[str] = set()
        invalid: list[str] = []
        for evidence_id in evidence_ids:
            try:
                if self.evidence.verify(evidence_id).valid:
                    valid.add(evidence_id)
                else:
                    invalid.append(evidence_id)
            except (KeyError, RuntimeError):
                invalid.append(evidence_id)
        return valid, sorted(invalid)

    @staticmethod
    def _signal_evidence_ids(values: dict[str, Any]) -> list[str]:
        found: set[str] = set()

        def collect(value: Any, key: str = "") -> None:
            if (
                (key == "evidence_id" or key.endswith("_evidence_id"))
                and isinstance(value, str)
                and value.strip()
            ):
                found.add(value)
                return
            if isinstance(value, dict):
                for child_key, child_value in value.items():
                    collect(child_value, str(child_key))
            elif isinstance(value, list):
                for child in value:
                    collect(child)

        collect(values)
        return sorted(found)

    @staticmethod
    def _supply_map(
        suppliers: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
        for supplier in suppliers:
            signals = supplier.get("supply_signals") or {}
            key = (
                str(signals.get("province") or "UNKNOWN"),
                str(signals.get("city") or "UNKNOWN"),
                str(signals.get("industry_belt") or "UNKNOWN"),
            )
            row = grouped.setdefault(
                key,
                {
                    "province": key[0],
                    "city": key[1],
                    "industry_belt": key[2],
                    "_supplier_refs": set(),
                    "_longitudes": [],
                    "_latitudes": [],
                    "items": 0,
                    "status": "observed"
                    if key[0] != "UNKNOWN"
                    else "no_data",
                },
            )
            row["items"] += 1
            row["_supplier_refs"].add(supplier["supplier_ref"])
            longitude = _geo_coordinate(
                signals,
                "longitude",
                minimum=Decimal("73"),
                maximum=Decimal("135"),
            )
            latitude = _geo_coordinate(
                signals,
                "latitude",
                minimum=Decimal("18"),
                maximum=Decimal("54"),
            )
            if longitude is not None and latitude is not None:
                row["_longitudes"].append(longitude)
                row["_latitudes"].append(latitude)
        result = []
        for row in grouped.values():
            longitudes = row.pop("_longitudes")
            latitudes = row.pop("_latitudes")
            row["supplier_count"] = len(row.pop("_supplier_refs"))
            if longitudes and latitudes:
                row["longitude"] = str(
                    (
                        sum(longitudes) / Decimal(len(longitudes))
                    ).quantize(RATE)
                )
                row["latitude"] = str(
                    (
                        sum(latitudes) / Decimal(len(latitudes))
                    ).quantize(RATE)
                )
                row["position_status"] = "observed"
            else:
                row["longitude"] = None
                row["latitude"] = None
                row["position_status"] = "no_data"
            result.append(row)
        return sorted(
            result,
            key=lambda item: (
                0 if item["status"] == "observed" else 1,
                -item["supplier_count"],
                item["province"],
                item["city"],
            ),
        )

    @staticmethod
    def _market_summary(
        ozon: list[dict[str, Any]]
    ) -> dict[str, Any]:
        prices_by_currency: dict[str, list[Decimal]] = {}
        signal_coverage = {
            "competitor_count": 0,
            "review_count": 0,
            "sales_proxy": 0,
            "promotion": 0,
            "seasonality": 0,
            "stockout": 0,
        }
        for item in ozon:
            prices_by_currency.setdefault(item["currency"], []).append(
                Decimal(item["displayed_price"])
            )
            signals = item.get("market_signals") or {}
            signal_coverage["competitor_count"] += (
                "competitor_count" in signals
            )
            signal_coverage["review_count"] += "review_count" in signals
            signal_coverage["sales_proxy"] += (
                "sales_proxy_type" in signals
                and "sales_proxy_value" in signals
            )
            signal_coverage["promotion"] += "promotion" in signals
            signal_coverage["seasonality"] += (
                "seasonality_status" in signals
            )
            signal_coverage["stockout"] += (
                "stockout_opportunity" in signals
            )
        bands = []
        for currency, prices in sorted(prices_by_currency.items()):
            ordered = sorted(prices)
            bands.append(
                {
                    "currency": currency,
                    "minimum": str(_money(ordered[0])),
                    "median": str(
                        _money(ordered[(len(ordered) - 1) // 2])
                    ),
                    "maximum": str(_money(ordered[-1])),
                    "sample": len(ordered),
                }
            )
        return {
            "observed_items": len(ozon),
            "price_bands": bands,
            "signal_coverage": signal_coverage,
            "actual_sales_available": False,
            "sales_status": (
                "proxy"
                if signal_coverage["sales_proxy"] > 0
                else "no_data"
            ),
        }

    @staticmethod
    def _funnel(counts: dict[str, int]) -> list[dict[str, Any]]:
        return [
            {
                "stage": "observed_listings",
                "count": counts["observed_listings"],
            },
            {
                "stage": "unique_exact_identities",
                "count": counts["unique_exact_identities"],
            },
            {
                "stage": "competitor_cohort",
                "count": counts["competitor_cohort_size"],
            },
            {
                "stage": "exact_identity_matched",
                "count": counts["exact_identity_matched"],
            },
            {
                "stage": "supplier_identity_cohort",
                "count": counts["supplier_identity_cohort_size"],
            },
            {
                "stage": "checkout_cost_eligible",
                "count": counts["checkout_cost_eligible"],
            },
            {
                "stage": "fully_costed",
                "count": counts["fully_costed_candidates"],
            },
            {
                "stage": "eligible_for_approval",
                "count": counts["eligible_for_approval"],
            },
            {
                "stage": "approval_allocation_selected",
                "count": counts["approval_allocation_selected"],
            },
            {
                "stage": "approval_waitlist",
                "count": counts["approval_waitlist"],
            },
            {"stage": "published", "count": counts["published"]},
            {"stage": "ordered", "count": counts["ordered"]},
            {
                "stage": "settled_proven",
                "count": counts["settled_proven"],
            },
        ]

    @staticmethod
    def _strategy_distribution(
        candidates: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        counts: dict[str, int] = {}
        for candidate in candidates:
            strategy = candidate["strategy"]["classification"]
            counts[strategy] = counts.get(strategy, 0) + 1
        return [
            {"strategy": strategy, "count": count}
            for strategy, count in sorted(counts.items())
        ]

    @staticmethod
    def _bottlenecks(counts: dict[str, int]) -> list[str]:
        result: list[str] = []
        if counts["observed"] < 100:
            result.append("observed_sample_below_100")
        if (
            counts["exact_identity_matched"]
            < counts["unique_exact_identities"]
        ):
            result.append("exact_cross_market_match_gap")
        if (
            counts["checkout_cost_eligible"]
            < counts["exact_identity_matched"]
        ):
            result.append("observed_checkout_cost_evidence_gap")
        if counts["content_ready"] < counts["downside_positive"]:
            result.append("passport_media_content_gap")
        if counts["pilot_ready"] == 0:
            result.append("pilot_governance_gate_not_satisfied")
        return result

    @staticmethod
    def _next_action(
        blockers: list[str], strategy: dict[str, Any]
    ) -> str:
        if "downside_cm3_not_positive" in blockers:
            return "淘汰或重新寻找精确变体与可复核 checkout 成本"
        if "fifteen_component_cost_evidence_incomplete" in blockers:
            return "补齐十五项费用 Evidence 与有效 FX 日期"
        if "passport_incomplete" in blockers:
            return "建立 Product 并完成三类 Passport"
        if "media_rights_or_qa_incomplete" in blockers:
            return "取得媒体权利并通过现有 Media QA"
        if "independent_approval_missing" in blockers:
            return "冻结 1–3 件 Pilot 草稿并进入独立批准"
        return f"按 {strategy['classification']} 策略继续受控验证"

    @classmethod
    def _run(
        cls,
        session: Session,
        row: BatchOpportunityRunRow,
    ) -> dict[str, Any]:
        candidates = list(
            session.scalars(
                select(BatchOpportunityCandidateRow)
                .where(BatchOpportunityCandidateRow.run_id == row.id)
                .order_by(
                    BatchOpportunityCandidateRow.rank,
                    BatchOpportunityCandidateRow.fingerprint,
                )
            )
        )
        payloads = [
            {
                **candidate.payload_json,
                "candidate_id": candidate.id,
                "candidate_evidence_id": candidate.evidence_id,
            }
            for candidate in candidates
        ]
        payload = dict(row.payload_json)
        payload.update(
            {
                "run_id": row.id,
                "contract_version": row.contract_version,
                "store_ref": row.store_ref,
                "scope": (
                    {
                        **(
                            payload.get("scope")
                            if isinstance(payload.get("scope"), dict)
                            else {}
                        ),
                        "tenant_ref": row.tenant_ref,
                        "entity_ref": row.entity_ref,
                        "store_ref": row.store_ref,
                        "scope_grant_authority_sha256": (
                            row.scope_grant_authority_sha256
                        ),
                        "scope_evidence_authority_sha256": (
                            row.scope_evidence_authority_sha256
                        ),
                    }
                    if row.tenant_ref is not None
                    else None
                ),
                "policy": row.policy_json,
                "counts": row.counts_json,
                "candidates": payloads,
                "blockers": row.blockers_json,
                "snapshot_sha256": row.snapshot_sha256,
                "evidence_id": row.evidence_id,
                "as_of": _iso(row.as_of),
                "created_by": row.created_by,
                "created_at": _iso(row.created_at),
            }
        )
        if row.task_id and not payload.get("operating_task"):
            payload["operating_task"] = {"id": row.task_id}
        return payload
