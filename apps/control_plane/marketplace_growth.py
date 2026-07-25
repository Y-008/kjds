from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

MONEY = Decimal("0.01")
RATE = Decimal("0.0001")
MAX_OBSERVATION_AGE = timedelta(days=7)
MIN_COMPETITOR_COUNT = 3
MIN_AD_REVIEW_COUNT = 5
MIN_AD_CONTENT_SCORE = Decimal("90")
MIN_AD_RATING = Decimal("4.5")


class MarketplaceGrowthPlanner:
    """Build one evidence-aware commercial plan without executing marketplace writes."""

    def __init__(self, *, sourcing_store, sourcing, repository, evidence) -> None:
        self.sourcing_store = sourcing_store
        self.sourcing = sourcing
        self.repository = repository
        self.evidence = evidence

    def normalize_observation(
        self,
        observation: dict[str, Any],
        *,
        evaluated_at: str | None = None,
    ) -> dict[str, Any]:
        """Validate and canonicalize one marketplace observation for durable storage."""
        scenario_id = self._text(observation.get("scenario_id"), "scenario_id")
        marketplace_sku = self._text(
            observation.get("marketplace_sku"), "marketplace_sku"
        )
        category = self._text(observation.get("category"), "category").lower()
        observed_at = self._datetime(observation.get("observed_at"), "observed_at")
        evaluation_time = self._datetime(
            evaluated_at or datetime.now(UTC).isoformat(), "evaluated_at"
        )
        if observed_at > evaluation_time:
            raise ValueError(f"Marketplace observation for {marketplace_sku} is in the future")

        evidence_ids = self._evidence_ids(observation.get("evidence_ids"))
        self.evidence.require_valid(evidence_ids)
        scenario = self.sourcing_store.get_scenario(scenario_id)
        if scenario.target_platform != "OZON":
            raise ValueError("Marketplace growth planner only supports Ozon scenarios")
        offer = self.sourcing_store.get_offer(scenario.offer_id)
        self.repository.get_product(offer.product_id)

        competitor_prices = self._positive_decimals(
            observation.get("competitor_prices_rub"),
            "competitor_prices_rub",
            minimum=MIN_COMPETITOR_COUNT,
        )
        stock = self._integer(observation.get("stock"), "stock", minimum=0)
        reviews = self._integer(observation.get("review_count"), "review_count", minimum=0)
        orders_14d = self._integer(
            observation.get("orders_14d"), "orders_14d", minimum=0
        )
        rating = self._decimal(observation.get("rating"), "rating")
        if rating < 0 or rating > 5:
            raise ValueError("rating must be between 0 and 5")
        content_score = self._decimal(
            observation.get("content_score"), "content_score"
        )
        if content_score < 0 or content_score > 100:
            raise ValueError("content_score must be between 0 and 100")
        conversion_rate = self._optional_rate(
            observation.get("conversion_rate"), "conversion_rate"
        )
        compliance_risk = self._text(
            observation.get("compliance_risk", "low"), "compliance_risk"
        ).lower()
        if compliance_risk not in {"low", "medium", "high"}:
            raise ValueError("compliance_risk must be low, medium, or high")

        return {
            "scenario_id": scenario_id,
            "marketplace_sku": marketplace_sku,
            "category": category,
            "competitor_prices_rub": [str(item) for item in competitor_prices],
            "stock": stock,
            "review_count": reviews,
            "orders_14d": orders_14d,
            "rating": str(rating),
            "content_score": str(content_score),
            "conversion_rate": (
                str(conversion_rate) if conversion_rate is not None else None
            ),
            "compliance_risk": compliance_risk,
            "observed_at": observed_at.isoformat(),
            "evidence_ids": evidence_ids,
        }

    def plan_portfolio(
        self,
        *,
        observations: list[dict[str, Any]],
        target_cm3_rate: Decimal,
        created_by: str,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        if not observations:
            raise ValueError("Marketplace growth plan requires at least one SKU observation")
        target_cm3 = self._rate(target_cm3_rate, "Target CM3 rate")
        if target_cm3 <= 0 or target_cm3 >= Decimal("0.5"):
            raise ValueError("Target CM3 rate must be greater than 0 and below 0.5")
        actor = created_by.strip()
        if not actor:
            raise ValueError("Marketplace growth plan requires an accountable actor")
        evaluated_at = self._datetime(as_of or datetime.now(UTC).isoformat(), "as_of")

        rows = [
            self._plan_sku(
                observation,
                target_cm3_rate=target_cm3,
                evaluated_at=evaluated_at,
            )
            for observation in observations
        ]
        duplicate_skus = self._duplicates(row["marketplace_sku"] for row in rows)
        if duplicate_skus:
            raise ValueError(
                "Marketplace growth plan contains duplicate SKUs: "
                + ", ".join(duplicate_skus)
            )
        rows.sort(
            key=lambda row: (
                -row["priority_score"],
                row["marketplace_sku"],
            )
        )
        canonical = {
            "target_cm3_rate": str(target_cm3),
            "evaluated_at": evaluated_at.isoformat(),
            "created_by": actor,
            "sku_snapshots": [
                {
                    "marketplace_sku": row["marketplace_sku"],
                    "snapshot_hash": row["snapshot_hash"],
                }
                for row in rows
            ],
        }
        snapshot_hash = self._hash(canonical)
        return {
            "plan_id": f"mgp_{snapshot_hash[:24]}",
            "snapshot_hash": snapshot_hash,
            "created_by": actor,
            "evaluated_at": evaluated_at.isoformat(),
            "target_cm3_rate": str(target_cm3),
            "execution_mode": "recommendation_only",
            "automatic_marketplace_write": False,
            "automatic_ad_spend": False,
            "portfolio": rows,
            "summary": {
                "sku_count": len(rows),
                "blocked_count": sum(row["ad_eligible"] is False for row in rows),
                "price_reset_count": sum(
                    row["commercial_status"] == "price_reset_required" for row in rows
                ),
                "source_mismatch_count": sum(
                    row["commercial_status"] == "source_cost_uncompetitive"
                    for row in rows
                ),
                "ad_test_eligible_count": sum(row["ad_eligible"] is True for row in rows),
            },
        }

    def _plan_sku(
        self,
        observation: dict[str, Any],
        *,
        target_cm3_rate: Decimal,
        evaluated_at: datetime,
    ) -> dict[str, Any]:
        normalized = self.normalize_observation(
            observation, evaluated_at=evaluated_at.isoformat()
        )
        scenario_id = normalized["scenario_id"]
        marketplace_sku = normalized["marketplace_sku"]
        category = normalized["category"]
        observed_at = self._datetime(normalized["observed_at"], "observed_at")
        observation_age = evaluated_at - observed_at
        snapshot_fresh = observation_age <= MAX_OBSERVATION_AGE

        evidence_ids = normalized["evidence_ids"]
        scenario = self.sourcing_store.get_scenario(scenario_id)
        offer = self.sourcing_store.get_offer(scenario.offer_id)
        product = self.repository.get_product(offer.product_id)
        cost_release_ready = self.sourcing.release_ready(scenario)

        competitor_prices = self._positive_decimals(
            normalized["competitor_prices_rub"],
            "competitor_prices_rub",
            minimum=MIN_COMPETITOR_COUNT,
        )
        stock = self._integer(normalized["stock"], "stock", minimum=0)
        reviews = self._integer(normalized["review_count"], "review_count", minimum=0)
        orders_14d = self._integer(
            normalized["orders_14d"], "orders_14d", minimum=0
        )
        rating = self._decimal(normalized["rating"], "rating")
        content_score = self._decimal(
            normalized["content_score"], "content_score"
        )
        conversion_rate = self._optional_rate(
            normalized["conversion_rate"], "conversion_rate"
        )
        compliance_risk = normalized["compliance_risk"]

        market_p25 = self._percentile(competitor_prices, Decimal("0.25"))
        market_median = self._percentile(competitor_prices, Decimal("0.50"))
        market_p75 = self._percentile(competitor_prices, Decimal("0.75"))
        current_price_rub = self._money(scenario.inputs.sale_price_rub)
        current_revenue_cny = self._money(scenario.revenue_cny)
        fixed_costs_cny = self._money(
            scenario.total_cost_cny
            - scenario.platform_fee_cny
            - scenario.advertising_cny
            - scenario.return_reserve_cny
        )
        non_ad_variable_rate = self._rate(
            scenario.inputs.platform_fee_rate + scenario.inputs.return_reserve_rate,
            "Non-advertising variable rate",
        )
        target_denominator = Decimal("1") - non_ad_variable_rate - target_cm3_rate
        if target_denominator <= 0:
            raise ValueError("Target CM3 leaves no room for fixed costs")
        target_floor_revenue_cny = fixed_costs_cny / target_denominator
        target_floor_rub = self._money(
            target_floor_revenue_cny * scenario.inputs.rub_per_cny
        )

        break_even_acos = max(
            Decimal("0"),
            Decimal("1")
            - non_ad_variable_rate
            - (fixed_costs_cny / current_revenue_cny),
        ).quantize(RATE, rounding=ROUND_HALF_UP)
        target_acos_ceiling = max(
            Decimal("0"), break_even_acos - target_cm3_rate
        ).quantize(RATE, rounding=ROUND_HALF_UP)
        max_ad_spend_per_order_cny = self._money(
            current_revenue_cny * target_acos_ceiling
        )
        max_cpc_cny = (
            self._money(max_ad_spend_per_order_cny * conversion_rate)
            if conversion_rate is not None
            else None
        )

        if target_floor_rub > market_p75:
            recommended_price_rub = None
        else:
            recommended_price_rub = self._money(
                min(max(target_floor_rub, market_p25), market_median)
            )
        price_gap_to_median = (
            (current_price_rub / market_median) - Decimal("1")
        ).quantize(RATE, rounding=ROUND_HALF_UP)
        if current_price_rub > market_p75:
            price_position = "above_market"
        elif current_price_rub < market_p25:
            price_position = "below_market"
        else:
            price_position = "market_aligned"

        gates = {
            "snapshot_fresh": snapshot_fresh,
            "cost_release_ready": cost_release_ready,
            "compliance_clear": compliance_risk == "low",
            "stock_available": stock > 0,
            "price_economically_competitive": target_floor_rub <= market_p75,
            "price_market_aligned": price_position == "market_aligned",
            "content_ready": content_score >= MIN_AD_CONTENT_SCORE,
            "rating_ready": rating >= MIN_AD_RATING,
            "review_depth_ready": reviews >= MIN_AD_REVIEW_COUNT,
            "conversion_observed": conversion_rate is not None and conversion_rate > 0,
            "orders_observed": orders_14d > 0,
            "positive_target_acos": target_acos_ceiling > 0,
        }
        ad_eligible = all(
            gates[key]
            for key in (
                "snapshot_fresh",
                "cost_release_ready",
                "compliance_clear",
                "stock_available",
                "price_economically_competitive",
                "price_market_aligned",
                "content_ready",
                "rating_ready",
                "review_depth_ready",
                "conversion_observed",
                "positive_target_acos",
            )
        )
        commercial_status = self._commercial_status(
            compliance_risk=compliance_risk,
            stock=stock,
            snapshot_fresh=snapshot_fresh,
            cost_release_ready=cost_release_ready,
            target_floor_rub=target_floor_rub,
            market_p75=market_p75,
            price_position=price_position,
            content_score=content_score,
            reviews=reviews,
            ad_eligible=ad_eligible,
        )
        actions = self._actions(
            commercial_status=commercial_status,
            price_position=price_position,
            content_score=content_score,
            reviews=reviews,
            orders_14d=orders_14d,
            ad_eligible=ad_eligible,
        )
        priority_score = self._priority_score(
            price_gap_to_median=price_gap_to_median,
            orders_14d=orders_14d,
            stock=stock,
            reviews=reviews,
            content_score=content_score,
            compliance_risk=compliance_risk,
            snapshot_fresh=snapshot_fresh,
        )
        snapshot = {
            "scenario_id": scenario_id,
            "marketplace_sku": marketplace_sku,
            "category": category,
            "observed_at": observed_at.isoformat(),
            "evidence_ids": evidence_ids,
            "competitor_prices_rub": [str(item) for item in competitor_prices],
            "stock": stock,
            "review_count": reviews,
            "orders_14d": orders_14d,
            "rating": str(rating),
            "content_score": str(content_score),
            "conversion_rate": str(conversion_rate) if conversion_rate is not None else None,
            "compliance_risk": compliance_risk,
        }
        return {
            "marketplace_sku": marketplace_sku,
            "product_id": product.id,
            "product_name": product.name,
            "scenario_id": scenario_id,
            "snapshot_hash": self._hash(snapshot),
            "evidence_ids": evidence_ids,
            "commercial_status": commercial_status,
            "priority_score": priority_score,
            "current": {
                "price_rub": str(current_price_rub),
                "price_cny": str(
                    self._money(current_price_rub / scenario.inputs.rub_per_cny)
                ),
                "stock": stock,
                "orders_14d": orders_14d,
                "review_count": reviews,
                "rating": str(rating),
                "content_score": str(content_score),
                "price_position": price_position,
                "price_gap_to_median": str(price_gap_to_median),
            },
            "market": {
                "competitor_count": len(competitor_prices),
                "p25_rub": str(market_p25),
                "median_rub": str(market_median),
                "p75_rub": str(market_p75),
                "observation_age_days": observation_age.days,
            },
            "economics": {
                "cost_release_ready": cost_release_ready,
                "fixed_costs_cny": str(fixed_costs_cny),
                "target_floor_price_rub": str(target_floor_rub),
                "recommended_test_price_rub": (
                    str(recommended_price_rub)
                    if recommended_price_rub is not None
                    else None
                ),
                "break_even_acos": str(break_even_acos),
                "target_acos_ceiling": str(target_acos_ceiling),
                "max_ad_spend_per_order_cny": str(max_ad_spend_per_order_cny),
                "max_cpc_cny": str(max_cpc_cny) if max_cpc_cny is not None else None,
            },
            "gates": gates,
            "ad_eligible": ad_eligible,
            "content_plan": {
                "image_roles": self._image_roles(category),
                "copy_requirements": [
                    "Use only approved passport facts",
                    "Use native Russian review before publication",
                    "State dimensions, package contents, warranty, and safety limits explicitly",
                    "Do not copy supplier or competitor creative without verified rights",
                ],
            },
            "actions": actions,
        }

    @staticmethod
    def _commercial_status(
        *,
        compliance_risk: str,
        stock: int,
        snapshot_fresh: bool,
        cost_release_ready: bool,
        target_floor_rub: Decimal,
        market_p75: Decimal,
        price_position: str,
        content_score: Decimal,
        reviews: int,
        ad_eligible: bool,
    ) -> str:
        if compliance_risk == "high":
            return "compliance_hold"
        if compliance_risk == "medium":
            return "compliance_review_required"
        if stock == 0:
            return "out_of_stock"
        if not snapshot_fresh:
            return "market_snapshot_stale"
        if not cost_release_ready:
            return "cost_authority_required"
        if target_floor_rub > market_p75:
            return "source_cost_uncompetitive"
        if price_position == "above_market":
            return "price_reset_required"
        if content_score < MIN_AD_CONTENT_SCORE:
            return "content_rebuild_required"
        if reviews < MIN_AD_REVIEW_COUNT:
            return "review_depth_required"
        if ad_eligible:
            return "ad_test_eligible"
        return "organic_conversion_required"

    @staticmethod
    def _actions(
        *,
        commercial_status: str,
        price_position: str,
        content_score: Decimal,
        reviews: int,
        orders_14d: int,
        ad_eligible: bool,
    ) -> list[dict[str, str]]:
        actions: list[dict[str, str]] = []
        if commercial_status == "compliance_hold":
            return [
                {
                    "type": "hold_listing",
                    "reason": "Resolve product compliance or intellectual-property risk before growth work",
                }
            ]
        if commercial_status == "compliance_review_required":
            actions.append(
                {
                    "type": "complete_compliance_review",
                    "reason": "Medium compliance risk must be cleared before conversion or advertising work",
                }
            )
        if commercial_status == "out_of_stock":
            actions.append(
                {
                    "type": "replenishment_review",
                    "reason": "Do not buy traffic for an unavailable SKU",
                }
            )
        if commercial_status == "market_snapshot_stale":
            actions.append(
                {
                    "type": "refresh_market_snapshot",
                    "reason": "Competitor evidence is older than seven days",
                }
            )
        if commercial_status == "cost_authority_required":
            actions.append(
                {
                    "type": "verify_actual_landed_cost",
                    "reason": "Supplier listing price is not an independently reviewed actual landed cost",
                }
            )
        if commercial_status == "source_cost_uncompetitive":
            actions.append(
                {
                    "type": "replace_supplier_or_bundle",
                    "reason": "Target-margin floor exceeds the upper market quartile",
                }
            )
        if (
            price_position == "above_market"
            and commercial_status != "source_cost_uncompetitive"
        ):
            actions.append(
                {
                    "type": "run_price_reset_experiment",
                    "reason": "Current price is above the observed upper market quartile",
                }
            )
        if content_score < Decimal("100"):
            actions.append(
                {
                    "type": "complete_content_roles",
                    "reason": "Listing content is not at the platform maximum",
                }
            )
        if reviews < MIN_AD_REVIEW_COUNT:
            actions.append(
                {
                    "type": "build_verified_review_depth",
                    "reason": "Delay paid scale until the product has enough verified buyer proof",
                }
            )
        if orders_14d == 0:
            actions.append(
                {
                    "type": "prove_organic_conversion",
                    "reason": "No recent order proves the current offer converts",
                }
            )
        actions.append(
            {
                "type": "start_capped_ad_experiment" if ad_eligible else "keep_ads_off",
                "reason": (
                    "All commercial and evidence gates passed"
                    if ad_eligible
                    else "Advertising remains blocked until every economic and conversion gate passes"
                ),
            }
        )
        return actions

    @staticmethod
    def _image_roles(category: str) -> list[dict[str, str]]:
        if "ladder" in category or "стремян" in category or "梯" in category:
            return [
                {"role": "hero", "objective": "White-background full product, no unsupported text"},
                {"role": "dimensions", "objective": "Open and folded dimensions with unit labels"},
                {"role": "anti_slip", "objective": "Close-up of feet, tread, lock, and contact surfaces"},
                {"role": "load_proof", "objective": "Approved safe-load evidence, never an invented claim"},
                {"role": "storage", "objective": "Folded thickness and realistic home storage scene"},
                {"role": "use_cases", "objective": "Kitchen, wardrobe, and maintenance use at true scale"},
                {"role": "package", "objective": "Exact package contents, protection, and after-sales path"},
            ]
        return [
            {"role": "hero", "objective": "White-background full product, no unsupported text"},
            {"role": "dimensions", "objective": "Exact dimensions and scale reference"},
            {"role": "benefits", "objective": "Three approved customer benefits"},
            {"role": "proof", "objective": "Material, mechanism, or performance evidence"},
            {"role": "use_cases", "objective": "Two realistic use scenes"},
            {"role": "package", "objective": "Exact included items and packaging"},
            {"role": "aftersales", "objective": "Warranty, support, and safety limitations"},
        ]

    @staticmethod
    def _priority_score(
        *,
        price_gap_to_median: Decimal,
        orders_14d: int,
        stock: int,
        reviews: int,
        content_score: Decimal,
        compliance_risk: str,
        snapshot_fresh: bool,
    ) -> int:
        if compliance_risk == "high":
            return -100
        score = 0
        if price_gap_to_median > 0:
            score += min(40, int(price_gap_to_median * 100))
        if orders_14d == 0:
            score += 25
        if stock > 0:
            score += 10
        if reviews < MIN_AD_REVIEW_COUNT:
            score += 10
        score += int((Decimal("100") - content_score) * Decimal("0.15"))
        if not snapshot_fresh:
            score -= 20
        if compliance_risk == "medium":
            score -= 30
        return score

    @staticmethod
    def _percentile(values: list[Decimal], fraction: Decimal) -> Decimal:
        ordered = sorted(values)
        if len(ordered) == 1:
            return ordered[0]
        position = Decimal(len(ordered) - 1) * fraction
        lower = int(position)
        upper = min(lower + 1, len(ordered) - 1)
        weight = position - Decimal(lower)
        return MarketplaceGrowthPlanner._money(
            ordered[lower] + (ordered[upper] - ordered[lower]) * weight
        )

    @staticmethod
    def _duplicates(values) -> list[str]:
        seen: set[str] = set()
        duplicates: set[str] = set()
        for value in values:
            if value in seen:
                duplicates.add(value)
            seen.add(value)
        return sorted(duplicates)

    @staticmethod
    def _evidence_ids(value: Any) -> list[str]:
        if not isinstance(value, list) or not value:
            raise ValueError("Marketplace growth observation requires evidence_ids")
        normalized = [
            item.strip() for item in value if isinstance(item, str) and item.strip()
        ]
        if len(normalized) != len(value) or len(set(normalized)) != len(normalized):
            raise ValueError("Marketplace growth evidence_ids are invalid or duplicated")
        return normalized

    @classmethod
    def _positive_decimals(
        cls, value: Any, name: str, *, minimum: int
    ) -> list[Decimal]:
        if not isinstance(value, list) or len(value) < minimum:
            raise ValueError(f"{name} requires at least {minimum} observations")
        result = [cls._decimal(item, name) for item in value]
        if any(item <= 0 for item in result):
            raise ValueError(f"{name} values must be positive")
        return result

    @staticmethod
    def _integer(value: Any, name: str, *, minimum: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise ValueError(f"{name} must be an integer greater than or equal to {minimum}")
        return value

    @staticmethod
    def _text(value: Any, name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} is required")
        return value.strip()

    @classmethod
    def _optional_rate(cls, value: Any, name: str) -> Decimal | None:
        if value is None:
            return None
        rate = cls._rate(value, name)
        if rate < 0 or rate > 1:
            raise ValueError(f"{name} must be between 0 and 1")
        return rate

    @classmethod
    def _rate(cls, value: Any, name: str) -> Decimal:
        return cls._decimal(value, name).quantize(RATE, rounding=ROUND_HALF_UP)

    @staticmethod
    def _money(value: Decimal) -> Decimal:
        return value.quantize(MONEY, rounding=ROUND_HALF_UP)

    @staticmethod
    def _decimal(value: Any, name: str) -> Decimal:
        try:
            result = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be numeric") from exc
        if not result.is_finite():
            raise ValueError(f"{name} must be finite")
        return result

    @staticmethod
    def _datetime(value: Any, name: str) -> datetime:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be an ISO-8601 timestamp")
        try:
            result = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{name} must be an ISO-8601 timestamp") from exc
        if result.tzinfo is None:
            raise ValueError(f"{name} must include a timezone")
        return result.astimezone(UTC)

    @staticmethod
    def _hash(payload: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
