from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from calendar import monthrange
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

OZON_RULE_CONTRACT_VERSION = "ozon-global-rule-evaluation/1.1.0"
DEFAULT_REGISTRY_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "project"
    / "registries"
    / "ozon_global_cn_rules.json"
)
ALLOWED_DOMAINS = frozenset(
    {
        "policies",
        "products",
        "prices",
        "fulfillment",
        "promotion",
        "analytics",
        "ratings",
        "commissions",
        "accounting",
        "api",
        "contracts",
    }
)
OFFICIAL_ANALYTICS_FIELDS = (
    "region_cluster_sales",
    "carts",
    "returns",
    "promotion_effect",
    "search_visibility",
    "trend",
    "competitive_position",
    "buyer_profile",
    "hot_products_28d",
    "popular_searches",
    "russia_bestseller_ozon_gap",
    "stockout_subscription",
)
PASSPORT_FACTS = (
    "category_allowed",
    "documents_verified",
    "brand_authorization_verified",
    "quality_safety_verified",
)
CONTENT_REQUIRED_PARTS = (
    "brand_or_manufacturer",
    "product_type",
    "model",
    "key_feature",
)
API_SUPPORTED_DOMAINS = (
    "products",
    "prices",
    "inventory",
    "returns",
    "orders",
    "shipments",
    "finance",
    "analytics",
    "attributes",
)
ACTION_METADATA = {
    "observe_research": {
        "owner": "market_research",
        "sla_hours": 24,
        "next_workspace_href": "/growth-command",
    },
    "candidate_score": {
        "owner": "commerce_finance",
        "sla_hours": 48,
        "next_workspace_href": "/portfolio-cockpit",
    },
    "content_draft": {
        "owner": "product_content",
        "sla_hours": 72,
        "next_workspace_href": "/strategy-center",
    },
    "pilot_approve": {
        "owner": "independent_approver",
        "sla_hours": 24,
        "next_workspace_href": "/growth-command",
    },
    "external_publish": {
        "owner": "executor",
        "sla_hours": 1,
        "next_workspace_href": "/growth-command",
    },
    "scale": {
        "owner": "commerce",
        "sla_hours": 168,
        "next_workspace_href": "/growth-command",
    },
    "settlement_reconcile": {
        "owner": "finance",
        "sla_hours": 120,
        "next_workspace_href": "/portfolio-cockpit",
    },
}


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


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _aware_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if result.tzinfo is None or result.utcoffset() is None:
        return None
    return result.astimezone(UTC)


def _date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _status(blockers: list[str], *, no_data: bool = False) -> str:
    if blockers:
        return "no_data" if no_data else "blocked"
    return "ready"


def _domain(
    *,
    status: str,
    blockers: list[str],
    details: dict[str, Any],
) -> dict[str, Any]:
    return {
        "status": status,
        "blockers": sorted(set(blockers)),
        **details,
    }


class OzonGlobalRuleRegistry:
    """Versioned Global CN rule snapshot and fail-closed SKU evaluator."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        registry: dict[str, Any] | None = None,
    ) -> None:
        registry_path = path or DEFAULT_REGISTRY_PATH
        raw = registry or json.loads(
            registry_path.read_text(encoding="utf-8")
        )
        self._validate_registry(raw)
        self.path = registry_path
        self.registry = raw
        self.registry_hash = _sha256(raw)

    @staticmethod
    def _validate_registry(registry: dict[str, Any]) -> None:
        if registry.get("country") != "CN" or registry.get("locale") != "zh":
            raise RuntimeError("Ozon rule registry must be scoped to CN/zh")
        rules = registry.get("rules")
        if not isinstance(rules, list) or not rules:
            raise RuntimeError("Ozon rule registry must contain rules")
        rule_ids: set[str] = set()
        domains: set[str] = set()
        for rule in rules:
            rule_id = str(rule.get("rule_id") or "")
            domain = str(rule.get("domain") or "")
            if not rule_id or rule_id in rule_ids:
                raise RuntimeError("Ozon rule ids must be unique and non-empty")
            if domain not in ALLOWED_DOMAINS:
                raise RuntimeError(f"Unsupported Ozon rule domain: {domain}")
            if not str(rule.get("source_url") or "").startswith(
                ("https://docs.ozon.", "https://seller.ozon.ru/")
            ):
                raise RuntimeError("Ozon registry sources must be official URLs")
            if _decimal(rule.get("confidence")) is None:
                raise RuntimeError("Ozon registry confidence must be decimal")
            rule_ids.add(rule_id)
            domains.add(domain)
        if domains != ALLOWED_DOMAINS:
            missing = sorted(ALLOWED_DOMAINS - domains)
            raise RuntimeError(f"Ozon rule domains missing: {missing}")

    @staticmethod
    def _effective_rules(
        registry: dict[str, Any], cutoff: date
    ) -> list[dict[str, Any]]:
        return [
            rule
            for rule in registry["rules"]
            if (
                (_date(rule["effective_from"]) or date.max) <= cutoff
                and (
                    _date(rule.get("effective_to")) is None
                    or cutoff
                    <= (_date(rule.get("effective_to")) or date.min)
                )
            )
        ]

    def snapshot(
        self,
        *,
        country: str = "CN",
        locale: str = "zh",
        as_of: str | None = None,
    ) -> dict[str, Any]:
        if country != "CN" or locale != "zh":
            return {
                "contract_version": OZON_RULE_CONTRACT_VERSION,
                "country": country,
                "locale": locale,
                "state": "no_data",
                "reason": "global_cn_and_ru_local_rule_sets_are_isolated",
                "registry_hash": None,
                "rules": [],
            }
        cutoff = _date(as_of) if as_of else datetime.now(UTC).date()
        if cutoff is None:
            raise ValueError("as_of must be an ISO date")
        rules = self._effective_rules(self.registry, cutoff)
        effective_domains = {rule["domain"] for rule in rules}
        missing_domains = sorted(ALLOWED_DOMAINS - effective_domains)
        source_evidence_gaps = sorted(
            rule["rule_id"]
            for rule in rules
            if not (
                rule.get("source_content_sha256")
                and rule.get("source_evidence_id")
                and rule.get("source_observed_at")
            )
        )
        state = (
            "no_data"
            if not rules or missing_domains
            else "ready_with_constraints"
            if source_evidence_gaps
            else "ready"
        )
        return {
            "contract_version": OZON_RULE_CONTRACT_VERSION,
            "registry_id": self.registry["registry_id"],
            "version": self.registry["version"],
            "country": "CN",
            "locale": "zh",
            "market_scope": "global_cn",
            "state": state,
            "observed_at": self.registry["observed_at"],
            "registry_hash": self.registry_hash,
            "effective_rule_count": len(rules),
            "domains": sorted(effective_domains),
            "missing_domains": missing_domains,
            "source_evidence_gaps": source_evidence_gaps,
            "compiled_policy_hash": _sha256(rules),
            "rules": rules,
            "ru_local_rules_applied": False,
        }

    def evaluate(
        self,
        values: dict[str, Any],
        *,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        country = str(values.get("country") or "CN")
        locale = str(values.get("locale") or "zh")
        evaluated_at = (
            _aware_datetime(as_of)
            if as_of
            else datetime.now(UTC)
        )
        if evaluated_at is None:
            raise ValueError("as_of must be an ISO timestamp with timezone")
        snapshot = self.snapshot(
            country=country,
            locale=locale,
            as_of=evaluated_at.date().isoformat(),
        )
        sku_ref = str(values.get("sku_ref") or "").strip()
        if not sku_ref:
            raise ValueError("sku_ref is required")
        if snapshot["state"] == "no_data":
            return {
                "contract_version": OZON_RULE_CONTRACT_VERSION,
                "sku_ref": sku_ref,
                "state": "no_data",
                "registry": snapshot,
                "blockers": [
                    snapshot.get("reason")
                    or "effective_global_cn_rule_domains_missing"
                ],
                "permit_created": False,
                "external_write_performed": False,
            }

        policy = {
            rule["rule_id"]: rule["facts"] for rule in snapshot["rules"]
        }
        domains = {
            "passport": self._passport(
                values.get("passport") or {},
                policy=policy["products.passport.fail_closed"],
            ),
            "content": self._content(
                values.get("content") or {},
                title_policy=policy["products.content.title"],
                image_policy=policy["products.content.images"],
            ),
            "price_guard": self._prices(
                values.get("prices") or {},
                downside_cm3=_decimal(values.get("downside_cm3_cny")),
                as_of=evaluated_at,
                policy=policy["prices.types_and_index"],
            ),
            "fulfillment": self._fulfillment(
                values.get("fulfillment") or {},
                policy=policy["fulfillment.global_cn.default_modes"],
            ),
            "quality": self._quality(
                values.get("quality") or {},
                policy=policy["ratings.seller_cancellation_quality"],
            ),
            "fee": self._fee(
                values.get("fee") or {},
                as_of=evaluated_at,
                policy=policy["commissions.effective_dated_lookup"],
            ),
            "settlement": self._settlement(
                values.get("settlement") or {},
                as_of=evaluated_at,
                policy=policy["accounting.cn_settlement"],
            ),
            "api_access": self._api(
                values.get("api_access") or {},
                policy=policy["api.seller_api_only"],
            ),
            "analytics": self._analytics(
                values.get("analytics") or {},
                policy=policy["analytics.official_demand_fields"],
            ),
        }
        actions = self._action_readiness(
            domains,
            values,
            source_evidence_gaps=snapshot["source_evidence_gaps"],
        )
        blockers = sorted(
            {
                blocker
                for result in domains.values()
                for blocker in result["blockers"]
            }
        )
        no_data_domains = sorted(
            name
            for name, result in domains.items()
            if result["status"] == "no_data"
        )
        state = (
            "ready"
            if actions["external_publish"]["status"] == "ready"
            else "ready_with_constraints"
            if any(
                action["status"] == "ready" for action in actions.values()
            )
            else "no_data"
        )
        evaluation_basis = {
            "sku_ref": sku_ref,
            "registry_hash": self.registry_hash,
            "input": values,
        }
        return {
            "contract_version": OZON_RULE_CONTRACT_VERSION,
            "sku_ref": sku_ref,
            "state": state,
            "registry": {
                key: snapshot[key]
                for key in (
                    "registry_id",
                    "version",
                    "country",
                    "locale",
                    "market_scope",
                    "registry_hash",
                    "observed_at",
                    "effective_rule_count",
                    "compiled_policy_hash",
                    "source_evidence_gaps",
                )
            },
            "evaluation_fingerprint": _sha256(evaluation_basis),
            "evaluated_at": evaluated_at.isoformat(),
            "domains": domains,
            "actions": actions,
            "blockers": blockers,
            "no_data_domains": no_data_domains,
            "rule_change_requires_sku_reevaluation": True,
            "authority": {
                "downside_cm3_may_be_overridden": False,
                "promotion_created": False,
                "autopricing_created": False,
                "listing_created": False,
                "permit_created": False,
                "external_write_performed": False,
            },
        }

    def impact(
        self,
        *,
        previous_registry: dict[str, Any] | None,
        previous_registry_hash: str | None,
        sku_bindings: list[dict[str, Any]],
        as_of: str | None = None,
    ) -> dict[str, Any]:
        current = self.snapshot(as_of=as_of)
        if previous_registry is None or not previous_registry_hash:
            return {
                "contract_version": OZON_RULE_CONTRACT_VERSION,
                "state": "no_data",
                "reason": "previous_registry_snapshot_missing",
                "previous_registry_hash": previous_registry_hash,
                "current_registry_hash": self.registry_hash,
                "changed_domains": [],
                "affected_skus": [],
                "affected_sku_count": 0,
            }
        if _sha256(previous_registry) != previous_registry_hash:
            raise ValueError("previous_registry_hash does not match snapshot")
        self._validate_registry(previous_registry)
        cutoff = _date(as_of) if as_of else datetime.now(UTC).date()
        if cutoff is None:
            raise ValueError("as_of must be an ISO date")
        previous_effective = self._effective_rules(
            previous_registry, cutoff
        )
        current_effective = self._effective_rules(self.registry, cutoff)
        previous_by_domain = {
            domain: [
                rule
                for rule in previous_effective
                if rule["domain"] == domain
            ]
            for domain in ALLOWED_DOMAINS
        }
        current_by_domain = {
            domain: [
                rule
                for rule in current_effective
                if rule["domain"] == domain
            ]
            for domain in ALLOWED_DOMAINS
        }
        changed_domains = sorted(
            domain
            for domain in ALLOWED_DOMAINS
            if _sha256(previous_by_domain[domain])
            != _sha256(current_by_domain[domain])
        )
        affected = []
        for binding in sku_bindings:
            sku_ref = str(binding.get("sku_ref") or "").strip()
            domains = {
                str(value)
                for value in binding.get("rule_domains") or []
                if str(value) in ALLOWED_DOMAINS
            }
            matched = sorted(domains.intersection(changed_domains))
            if sku_ref and matched:
                affected.append(
                    {
                        "sku_ref": sku_ref,
                        "changed_domains": matched,
                        "binding_evidence_ids": sorted(
                            {
                                str(value)
                                for value in (
                                    binding.get("evidence_ids") or []
                                )
                                if str(value)
                            }
                        ),
                    }
                )
        scheduled_changes = []
        future_dates = sorted(
            {
                _date(rule["effective_from"])
                for rule in self.registry["rules"]
                if (_date(rule["effective_from"]) or date.min) > cutoff
            }
        )
        for future_date in future_dates:
            assert future_date is not None
            before = future_date - timedelta(days=1)
            before_rules = self._effective_rules(self.registry, before)
            on_rules = self._effective_rules(self.registry, future_date)
            changed = sorted(
                domain
                for domain in ALLOWED_DOMAINS
                if _sha256(
                    [
                        rule
                        for rule in before_rules
                        if rule["domain"] == domain
                    ]
                )
                != _sha256(
                    [
                        rule
                        for rule in on_rules
                        if rule["domain"] == domain
                    ]
                )
            )
            if changed:
                scheduled_changes.append(
                    {
                        "effective_at": future_date.isoformat(),
                        "changed_domains": changed,
                        "state": "scheduled_change",
                    }
                )
        return {
            "contract_version": OZON_RULE_CONTRACT_VERSION,
            "state": (
                "change_detected"
                if changed_domains
                else "no_change"
            ),
            "previous_registry_hash": previous_registry_hash,
            "current_registry_hash": self.registry_hash,
            "current_compiled_policy_hash": current.get(
                "compiled_policy_hash"
            ),
            "changed_domains": changed_domains,
            "affected_skus": affected,
            "affected_sku_count": len(affected),
            "scheduled_changes": scheduled_changes,
            "all_candidates_assumed_affected": False,
            "external_write_performed": False,
        }

    @staticmethod
    def _passport(
        values: dict[str, Any], *, policy: dict[str, Any]
    ) -> dict[str, Any]:
        required_facts = tuple(policy["required_statuses"])
        blockers = [
            f"passport_{key}_missing"
            for key in required_facts
            if values.get(key) is not True
        ]
        if values.get("category_status") in {
            "prohibited",
            "restricted",
            "non_public",
        }:
            blockers.append("passport_category_fail_closed")
        if (
            values.get("brand_restricted") is True
            and values.get("brand_authorization_verified") is not True
        ):
            blockers.append("passport_brand_authorization_fail_closed")
        return _domain(
            status=_status(blockers, no_data=not values),
            blockers=blockers,
            details={
                "required_facts": list(required_facts),
                "fail_closed": True,
            },
        )

    @staticmethod
    def _content(
        values: dict[str, Any],
        *,
        title_policy: dict[str, Any],
        image_policy: dict[str, Any],
    ) -> dict[str, Any]:
        title = str(values.get("title") or "").strip()
        parts = values.get("title_parts") or {}
        images = values.get("images") or []
        blockers: list[str] = []
        if not title:
            blockers.append("content_title_missing")
        maximum_characters = int(title_policy["maximum_characters"])
        if len(title) > maximum_characters:
            blockers.append("content_title_exceeds_200_characters")
        if not any("\u0400" <= character <= "\u04ff" for character in title):
            blockers.append("content_title_russian_missing")
        if re.search(r"<[^>]*>", title):
            blockers.append("content_title_html_forbidden")
        lowered = title.casefold()
        forbidden_terms = tuple(title_policy["forbidden_terms"])
        if any(term in lowered for term in forbidden_terms):
            blockers.append("content_title_forbidden_claim")
        if any(
            character in title
            for character in title_policy["forbidden_characters"]
        ):
            blockers.append("content_title_forbidden_character")
        tokens = re.findall(r"[\w-]+", lowered, flags=re.UNICODE)
        repeated = {
            token
            for token in tokens
            if len(token) > 2
            and tokens.count(token)
            > int(title_policy["maximum_repeated_token"])
        }
        if repeated:
            blockers.append("content_title_keyword_stuffing")
        missing_parts = [
            part
            for part in title_policy["required_parts"]
            if not str(parts.get(part) or "").strip()
        ]
        if missing_parts:
            blockers.append("content_title_template_incomplete")

        main_images = sum(
            1 for image in images if image.get("kind") == "main"
        )
        additional_images = sum(
            1 for image in images if image.get("kind") == "additional"
        )
        if main_images != int(image_policy["main_image_count"]):
            blockers.append("content_main_image_count_invalid")
        if additional_images > int(image_policy["additional_maximum"]):
            blockers.append("content_additional_image_limit_exceeded")
        if additional_images < int(
            image_policy["recommended_additional_minimum"]
        ):
            blockers.append("content_additional_images_below_recommendation")
        for image in images:
            if image.get("aspect_ratio") != image_policy["aspect_ratio"]:
                blockers.append("content_image_aspect_ratio_invalid")
            size_bytes = image.get("size_bytes")
            if (
                not isinstance(size_bytes, int)
                or size_bytes > int(image_policy["maximum_bytes"])
            ):
                blockers.append("content_image_size_invalid")
            if not str(image.get("rights_evidence_id") or "").strip():
                blockers.append("content_image_rights_evidence_missing")
            if any(
                image.get(flag) is True
                for flag in (
                    "has_watermark",
                    "has_price",
                    "has_discount",
                    "has_contact",
                    "has_value_judgement",
                    "has_sales_claim",
                )
            ):
                blockers.append("content_image_forbidden_overlay")
        if values.get("russian_grammar_status") != "passed":
            blockers.append("content_russian_grammar_not_passed")
        if values.get("category_template_status") != "passed":
            blockers.append("content_category_template_not_passed")
        if values.get("forbidden_words_status") != "passed":
            blockers.append("content_forbidden_words_not_passed")
        return _domain(
            status=_status(blockers, no_data=not values),
            blockers=blockers,
            details={
                "title_characters": len(title),
                "missing_title_parts": missing_parts,
                "main_image_count": main_images,
                "additional_image_count": additional_images,
                "machine_gate": True,
            },
        )

    @staticmethod
    def _prices(
        values: dict[str, Any],
        *,
        downside_cm3: Decimal | None,
        as_of: datetime,
        policy: dict[str, Any],
    ) -> dict[str, Any]:
        required = (
            "seller_price",
            "list_price",
            "buyer_price",
            "minimum_price",
        )
        blockers = [
            f"price_{name}_missing"
            for name in required
            if _decimal(values.get(name)) is None
        ]
        renewed_at = _aware_datetime(values.get("minimum_price_renewed_at"))
        if renewed_at is None:
            blockers.append("price_minimum_renewal_missing")
        elif as_of - renewed_at > timedelta(
            days=int(policy["minimum_price_valid_days"])
        ):
            blockers.append("price_minimum_expired")
        exact_match = values.get("exact_product_match") is True
        public_source = str(values.get("comparison_source_url") or "")
        match_confidence = _decimal(values.get("match_confidence"))
        external_low = _decimal(values.get("external_lowest_price"))
        buyer_price = _decimal(values.get("buyer_price"))
        index_value = None
        index_band = "no_data"
        if (
            exact_match
            and public_source.startswith("http")
            and match_confidence is not None
            and external_low is not None
            and external_low > 0
            and buyer_price is not None
        ):
            index_value = (
                buyer_price / external_low
                if buyer_price <= external_low
                else Decimal("2") - external_low / buyer_price
            )
            if index_value <= Decimal(policy["green_max_inclusive"]):
                index_band = "green"
            elif index_value < Decimal(policy["yellow_max_exclusive"]):
                index_band = "yellow"
            else:
                index_band = "red"
        else:
            blockers.append("price_index_exact_public_match_no_data")
        if downside_cm3 is None:
            blockers.append("price_downside_cm3_no_data")
        elif downside_cm3 <= 0:
            blockers.append("price_downside_cm3_floor_failed")
        if values.get("promotion_requested") is True:
            blockers.append("price_promotion_permit_missing")
        if values.get("autopricing_requested") is True:
            blockers.append("price_autopricing_permit_missing")
        return _domain(
            status=_status(blockers, no_data=not values),
            blockers=blockers,
            details={
                "price_types_separated": all(
                    _decimal(values.get(name)) is not None for name in required
                ),
                "index": (
                    str(index_value.quantize(Decimal("0.0001")))
                    if index_value is not None
                    else None
                ),
                "index_band": index_band,
                "index_formula": (
                    "own_price / competitor_price"
                    if (
                        buyer_price is not None
                        and external_low is not None
                        and buyer_price <= external_low
                    )
                    else "2 - competitor_price / own_price"
                ),
                "downside_cm3_cny": (
                    str(downside_cm3) if downside_cm3 is not None else None
                ),
                "profit_floor_override_allowed": False,
            },
        )

    @staticmethod
    def _fulfillment(
        values: dict[str, Any], *, policy: dict[str, Any]
    ) -> dict[str, Any]:
        mode = str(values.get("mode") or "")
        allowed_modes = set(policy["allowed_modes"])
        blockers: list[str] = []
        if mode not in allowed_modes:
            blockers.append("fulfillment_global_cn_mode_missing_or_invalid")
        if mode == "FBP" and values.get("partner_warehouse_verified") is not True:
            blockers.append("fulfillment_fbp_partner_warehouse_unverified")
        if mode == "realFBS":
            if values.get("seller_delivery_and_returns_verified") is not True:
                blockers.append(
                    "fulfillment_realfbs_delivery_returns_unverified"
                )
            priorities = values.get("warehouse_priorities")
            if not isinstance(priorities, list) or not priorities:
                blockers.append("fulfillment_realfbs_warehouse_priority_missing")
        return _domain(
            status=_status(blockers, no_data=not values),
            blockers=blockers,
            details={
                "mode": mode or None,
                "allowed_modes": sorted(allowed_modes),
                "ru_local_default_applied": False,
            },
        )

    @staticmethod
    def _quality(
        values: dict[str, Any], *, policy: dict[str, Any]
    ) -> dict[str, Any]:
        total = _decimal(values.get("orders_14d"))
        cancelled = _decimal(values.get("seller_cancelled_14d"))
        warning = _decimal(values.get("internal_warning_percent"))
        freeze = _decimal(values.get("internal_freeze_percent"))
        warning = (
            warning
            if warning is not None
            else Decimal(policy["internal_warning_percent"])
        )
        freeze = (
            freeze
            if freeze is not None
            else Decimal(policy["internal_freeze_percent"])
        )
        blockers: list[str] = []
        rate = None
        state = "no_data"
        lifecycle = values.get("lifecycle")
        if lifecycle == "prelaunch" or total == 0:
            return _domain(
                status="not_applicable_prelaunch",
                blockers=[],
                details={
                    "window_days": int(policy["rolling_days"]),
                    "seller_cancellation_percent": None,
                    "internal_warning_percent": str(warning),
                    "internal_freeze_percent": str(freeze),
                    "official_block_threshold_percent_exclusive": policy[
                        "official_block_threshold_percent_exclusive"
                    ],
                    "denominator_status": "prelaunch_zero_orders",
                },
            )
        if total is None or cancelled is None:
            blockers.append("quality_cancellation_rate_no_data")
            state = "insufficient_denominator"
        else:
            rate = cancelled / total * 100
            state = "ready"
            if rate >= freeze:
                blockers.append("quality_internal_freeze_threshold_reached")
                state = "blocked"
            elif rate >= warning:
                blockers.append("quality_internal_warning_threshold_reached")
                state = "blocked"
            if rate > Decimal(
                policy["official_block_threshold_percent_exclusive"]
            ):
                blockers.append("quality_official_block_risk_over_40_percent")
                state = "blocked"
        for metric in (
            "on_time_delivery_rate",
            "return_rate",
            "csat",
            "warehouse_block_status",
            "account_block_status",
        ):
            if metric not in values:
                blockers.append(f"quality_{metric}_no_data")
        return _domain(
            status=state,
            blockers=blockers,
            details={
                "window_days": int(policy["rolling_days"]),
                "seller_cancellation_percent": (
                    str(rate.quantize(Decimal("0.01")))
                    if rate is not None
                    else None
                ),
                "internal_warning_percent": str(warning),
                "internal_freeze_percent": str(freeze),
                "official_block_threshold_percent_exclusive": policy[
                    "official_block_threshold_percent_exclusive"
                ],
            },
        )

    @staticmethod
    def _fee(
        values: dict[str, Any],
        *,
        as_of: datetime,
        policy: dict[str, Any],
    ) -> dict[str, Any]:
        estimate_blockers = []
        dimension_fields = {
            "fulfillment_mode": "mode",
            **{
                dimension: dimension
                for dimension in policy["lookup_dimensions"]
                if dimension != "fulfillment_mode"
            },
        }
        for field in (
            *dimension_fields.values(),
            "commission_rate",
            "evidence_id",
            "effective_from",
        ):
            if values.get(field) in (None, ""):
                estimate_blockers.append(f"fee_{field}_missing")
        order_date = _date(values.get("order_date"))
        effective_from = _date(values.get("effective_from"))
        effective_to = _date(values.get("effective_to"))
        if (
            order_date is None
            or effective_from is None
            or order_date < effective_from
            or (effective_to is not None and order_date > effective_to)
        ):
            estimate_blockers.append("fee_effective_date_mismatch")
        if values.get("mode") not in {"FBP", "realFBS"}:
            estimate_blockers.append("fee_global_cn_mode_invalid")
        commission = _decimal(values.get("commission_rate"))
        if commission is None or commission < 0 or commission > 1:
            estimate_blockers.append("fee_commission_rate_invalid")

        order_id = str(values.get("order_id") or "")
        actual_blockers = []
        if not order_id:
            actual_status = "not_applicable_prelaunch"
        else:
            if values.get("order_status") not in {"delivered", "returned"}:
                actual_blockers.append("fee_actual_order_not_delivered")
            if not str(values.get("accrual_evidence_id") or ""):
                actual_blockers.append("fee_actual_accrual_evidence_missing")
            actual_status = _status(actual_blockers)

        cash_blockers = []
        if not order_id:
            cash_status = "not_applicable_prelaunch"
        elif actual_status != "ready":
            cash_status = "blocked_dependency"
            cash_blockers.append("fee_actual_accrual_not_ready")
        else:
            if values.get("cash_status") != "reconciled":
                cash_blockers.append("fee_cash_not_reconciled")
            if not str(values.get("cash_evidence_id") or ""):
                cash_blockers.append("fee_cash_evidence_missing")
            cash_status = _status(cash_blockers)
        blockers = estimate_blockers + actual_blockers + cash_blockers
        return _domain(
            status=(
                "no_data"
                if not values
                else "blocked"
                if estimate_blockers
                else "ready"
            ),
            blockers=blockers,
            details={
                "lookup_dimensions": policy["lookup_dimensions"],
                "fixed_fallback_rate_used": False,
                "evaluated_on": as_of.date().isoformat(),
                "estimate": {
                    "status": _status(
                        estimate_blockers, no_data=not values
                    ),
                    "authority": "estimated_evidence_bound_fee_row",
                    "blockers": sorted(set(estimate_blockers)),
                },
                "actual_accrual": {
                    "status": actual_status,
                    "authority": "delivered_or_returned_order_accrual",
                    "blockers": sorted(set(actual_blockers)),
                },
                "reconciled_cash": {
                    "status": cash_status,
                    "authority": "settled_reconciled_cash_only",
                    "blockers": sorted(set(cash_blockers)),
                },
            },
        )

    @staticmethod
    def _settlement(
        values: dict[str, Any],
        *,
        as_of: datetime,
        policy: dict[str, Any],
    ) -> dict[str, Any]:
        blockers = []
        period_end = _date(values.get("period_end"))
        statement_at = _date(values.get("statement_published_at"))
        remittance = _decimal(values.get("remittance_cny"))
        actual_cash_cm3 = _decimal(values.get("actual_cash_cm3_cny"))
        if values.get("currency") != policy["currency"]:
            blockers.append("settlement_cny_currency_missing")
        if period_end is None:
            blockers.append("settlement_period_end_missing")
        if statement_at is None:
            blockers.append("settlement_statement_date_missing")
        if remittance is None:
            blockers.append("settlement_remittance_no_data")
        elif remittance < Decimal(policy["minimum_remittance_cny"]):
            blockers.append("settlement_minimum_remittance_not_reached")
        if values.get("reconciliation_status") != "reconciled":
            blockers.append("settlement_not_reconciled")
        if actual_cash_cm3 is None:
            blockers.append("settlement_actual_cash_cm3_no_data")
        pay_by = (
            OzonGlobalRuleRegistry._pay_by(period_end)
            if period_end
            else None
        )
        estimated_dispute_deadline = (
            OzonGlobalRuleRegistry._add_business_days(
                statement_at,
                int(policy["statement_dispute_business_days"]),
            )
            if statement_at
            else None
        )
        return _domain(
            status=_status(blockers, no_data=not values),
            blockers=blockers,
            details={
                "scheduled_pay_by": pay_by.isoformat() if pay_by else None,
                "dispute_deadline": (
                    estimated_dispute_deadline.isoformat()
                    if estimated_dispute_deadline
                    else None
                ),
                "deadline_semantics": (
                    "estimated_weekdays_only_no_official_holiday_calendar"
                ),
                "authoritative_holiday_calendar_bound": False,
                "dispute_open": (
                    as_of.date() <= estimated_dispute_deadline
                    if estimated_dispute_deadline
                    else None
                ),
                "minimum_remittance_cny": policy[
                    "minimum_remittance_cny"
                ],
                "lianlian_example_rate": policy[
                    "lianlian_example_fee_rate"
                ],
                "lianlian_rate_is_universal_fact": False,
                "actual_cash_cm3_cny": (
                    str(actual_cash_cm3)
                    if actual_cash_cm3 is not None
                    else None
                ),
            },
        )

    @staticmethod
    def _action_readiness(
        domains: dict[str, dict[str, Any]],
        values: dict[str, Any],
        *,
        source_evidence_gaps: list[str],
    ) -> dict[str, dict[str, Any]]:
        def action(
            blockers: list[str],
            *,
            no_data: bool = False,
            not_applicable: bool = False,
        ) -> dict[str, Any]:
            status = (
                "not_applicable_prelaunch"
                if not_applicable
                else "no_data"
                if no_data and blockers
                else "blocked"
                if blockers
                else "ready"
            )
            return {
                "status": status,
                "blockers": sorted(set(blockers)),
                "why": (
                    "all_action_scoped_gates_satisfied"
                    if not blockers
                    else "action_scoped_gates_missing_or_failed"
                ),
            }

        passport = domains["passport"]["blockers"]
        content = domains["content"]["blockers"]
        price = [
            blocker
            for blocker in domains["price_guard"]["blockers"]
            if blocker
            not in {
                "price_promotion_permit_missing",
                "price_autopricing_permit_missing",
            }
        ]
        fulfillment = domains["fulfillment"]["blockers"]
        quality = domains["quality"]["blockers"]
        fee_estimate = domains["fee"]["estimate"]["blockers"]
        analytics = domains["analytics"]["blockers"]
        pilot = (
            passport
            + content
            + price
            + fulfillment
            + quality
            + fee_estimate
            + analytics
        )
        source_blockers = (
            ["rule_source_evidence_binding_incomplete"]
            if source_evidence_gaps
            else []
        )
        pilot = pilot + source_blockers
        publish = pilot + [
            "independent_approval_missing",
            "one_time_permit_missing",
            "readback_plan_missing",
            "kill_switch_check_missing",
            "compensation_plan_missing",
        ]
        order_id = str((values.get("fee") or {}).get("order_id") or "")
        scale = (
            publish
            + domains["fee"]["actual_accrual"]["blockers"]
            + domains["fee"]["reconciled_cash"]["blockers"]
            + domains["settlement"]["blockers"]
        )
        if values.get("scale_readbacks_verified") is not True:
            scale.append("scale_24h_72h_7d_readbacks_missing")
        settlement = (
            domains["settlement"]["blockers"]
            + domains["fee"]["actual_accrual"]["blockers"]
            + domains["fee"]["reconciled_cash"]["blockers"]
        )
        result = {
            "observe_research": action([]),
            "candidate_score": action(
                price + fee_estimate + analytics + source_blockers,
                no_data=(
                    not bool(values.get("prices"))
                    or bool(source_blockers)
                ),
            ),
            "content_draft": action(
                [
                    blocker
                    for blocker in passport
                    if blocker
                    in {
                        "passport_category_fail_closed",
                        "passport_brand_authorization_fail_closed",
                    }
                ]
            ),
            "pilot_approve": action(pilot),
            "external_publish": action(publish),
            "scale": action(scale, no_data=not order_id),
            "settlement_reconcile": action(
                settlement,
                not_applicable=not order_id,
            ),
        }
        for name, row in result.items():
            row.update(ACTION_METADATA[name])
            row["missing_evidence"] = [
                blocker
                for blocker in row["blockers"]
                if any(
                    token in blocker
                    for token in (
                        "evidence",
                        "approval",
                        "permit",
                        "readback",
                        "statement",
                        "reconciled",
                    )
                )
            ]
        return result

    @staticmethod
    def _pay_by(period_end: date) -> date:
        if period_end.day <= 15:
            day = min(25, monthrange(period_end.year, period_end.month)[1])
            return period_end.replace(day=day)
        if period_end.month == 12:
            return date(period_end.year + 1, 1, 16)
        return date(period_end.year, period_end.month + 1, 16)

    @staticmethod
    def _add_business_days(start: date, days: int) -> date:
        current = start
        remaining = days
        while remaining:
            current += timedelta(days=1)
            if current.weekday() < 5:
                remaining -= 1
        return current

    @staticmethod
    def _api(
        values: dict[str, Any], *, policy: dict[str, Any]
    ) -> dict[str, Any]:
        blockers = []
        if values.get("auth_source") != "seller_api":
            blockers.append("api_official_seller_api_required")
        roles = values.get("key_roles")
        if not isinstance(roles, list) or not roles:
            blockers.append("api_minimum_role_keys_missing")
        cidrs = values.get("ip_cidr_allowlist")
        if not isinstance(cidrs, list) or not cidrs:
            blockers.append("api_ip_cidr_allowlist_missing")
        else:
            for cidr in cidrs:
                try:
                    ipaddress.ip_network(str(cidr), strict=False)
                except ValueError:
                    blockers.append("api_ip_cidr_allowlist_invalid")
                    break
        domains = set(values.get("enabled_domains") or [])
        supported_domains = set(policy["supported_domains"])
        unsupported = domains - supported_domains
        if unsupported:
            blockers.append("api_unsupported_domain_requested")
        if not domains:
            blockers.append("api_enabled_domains_missing")
        return _domain(
            status=_status(blockers, no_data=not values),
            blockers=blockers,
            details={
                "supported_domains": sorted(supported_domains),
                "cookie_allowed": False,
                "local_storage_allowed": False,
                "internal_api_allowed": False,
            },
        )

    @staticmethod
    def _analytics(
        values: dict[str, Any], *, policy: dict[str, Any]
    ) -> dict[str, Any]:
        source = values.get("source")
        fields = values.get("fields") or {}
        blockers = []
        if source not in {"ozon_seller_api", "ozon_official_export"}:
            blockers.append("analytics_official_source_no_data")
        missing = [
            field
            for field in policy["required_fields"]
            if fields.get(field) in (None, "", "no_data")
        ]
        if missing:
            blockers.append("analytics_official_fields_no_data")
        if values.get("reviews_labeled_as_sales") is True:
            blockers.append("analytics_reviews_mislabeled_as_sales")
        return _domain(
            status=_status(blockers, no_data=not values or bool(missing)),
            blockers=blockers,
            details={
                "required_fields": list(policy["required_fields"]),
                "missing_fields": missing,
                "sales_is_actual": source
                in {"ozon_seller_api", "ozon_official_export"}
                and not missing,
                "review_count_is_sales": False,
            },
        )
