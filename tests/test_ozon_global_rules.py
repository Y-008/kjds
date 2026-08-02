from __future__ import annotations

import json

from apps.control_plane.ozon_global_rules import (
    DEFAULT_REGISTRY_PATH,
    OzonGlobalRuleRegistry,
)


def complete_input() -> dict:
    analytics_fields = {
        field: {"value": "verified", "evidence_id": f"evd-{field}"}
        for field in (
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
    }
    return {
        "sku_ref": "sku-global-cn-1",
        "country": "CN",
        "locale": "zh",
        "passport": {
            "category_allowed": True,
            "documents_verified": True,
            "brand_authorization_verified": True,
            "quality_safety_verified": True,
            "category_status": "public",
            "brand_restricted": False,
        },
        "content": {
            "title": "KJDS Лестница складная M2 для дома 120 см",
            "title_parts": {
                "brand_or_manufacturer": "KJDS",
                "product_type": "Лестница",
                "model": "M2",
                "key_feature": "120 см",
            },
            "images": [
                {
                    "kind": "main",
                    "aspect_ratio": "3:4",
                    "size_bytes": 1_000_000,
                    "rights_evidence_id": "evd-main",
                },
                {
                    "kind": "additional",
                    "aspect_ratio": "3:4",
                    "size_bytes": 1_000_000,
                    "rights_evidence_id": "evd-detail-1",
                },
                {
                    "kind": "additional",
                    "aspect_ratio": "3:4",
                    "size_bytes": 1_000_000,
                    "rights_evidence_id": "evd-detail-2",
                },
            ],
            "russian_grammar_status": "passed",
            "category_template_status": "passed",
            "forbidden_words_status": "passed",
        },
        "prices": {
            "seller_price": "1000",
            "list_price": "1200",
            "buyer_price": "1000",
            "minimum_price": "900",
            "minimum_price_renewed_at": "2026-07-20T00:00:00+00:00",
            "exact_product_match": True,
            "comparison_source_url": "https://www.ozon.ru/product/1/",
            "match_confidence": "0.98",
            "external_lowest_price": "990",
            "promotion_requested": False,
            "autopricing_requested": False,
        },
        "fulfillment": {
            "mode": "realFBS",
            "seller_delivery_and_returns_verified": True,
            "warehouse_priorities": ["cn-hb-1", "cn-zj-1"],
        },
        "quality": {
            "orders_14d": 100,
            "seller_cancelled_14d": 2,
            "on_time_delivery_rate": "0.98",
            "return_rate": "0.03",
            "csat": "4.8",
            "warehouse_block_status": "clear",
            "account_block_status": "clear",
        },
        "fee": {
            "category": "home",
            "mode": "realFBS",
            "price_band": "500-1500",
            "order_date": "2026-07-20",
            "commission_rate": "0.18",
            "evidence_id": "evd-fee-row",
            "effective_from": "2025-12-01",
            "effective_to": None,
            "settlement_status": "delivered",
        },
        "settlement": {
            "currency": "CNY",
            "period_end": "2026-07-15",
            "statement_published_at": "2026-07-16",
            "remittance_cny": "7000",
            "reconciliation_status": "reconciled",
            "actual_cash_cm3_cny": "82.20",
        },
        "api_access": {
            "auth_source": "seller_api",
            "key_roles": ["analytics-read", "products-read"],
            "ip_cidr_allowlist": ["203.0.113.0/28"],
            "enabled_domains": ["products", "analytics"],
        },
        "analytics": {
            "source": "ozon_seller_api",
            "fields": analytics_fields,
            "reviews_labeled_as_sales": False,
        },
        "downside_cm3_cny": "50.00",
    }


def test_registry_is_versioned_hashed_and_isolates_ru_rules():
    registry = OzonGlobalRuleRegistry()

    snapshot = registry.snapshot(as_of="2026-07-27")
    ru = registry.snapshot(country="RU", locale="ru")

    assert snapshot["state"] == "ready_with_constraints"
    assert snapshot["source_evidence_gaps"]
    assert snapshot["country"] == "CN"
    assert snapshot["locale"] == "zh"
    assert len(snapshot["registry_hash"]) == 64
    assert snapshot["ru_local_rules_applied"] is False
    assert set(snapshot["domains"]) == {
        "accounting",
        "analytics",
        "api",
        "commissions",
        "contracts",
        "fulfillment",
        "policies",
        "prices",
        "products",
        "promotion",
        "ratings",
    }
    assert ru["state"] == "no_data"
    assert ru["rules"] == []


def test_complete_global_cn_evaluation_is_ready_and_write_free():
    result = OzonGlobalRuleRegistry().evaluate(
        complete_input(),
        as_of="2026-07-27T00:00:00+00:00",
    )

    assert result["state"] == "ready_with_constraints"
    assert result["blockers"] == []
    assert result["domains"]["price_guard"]["index_band"] == "green"
    assert result["actions"]["observe_research"]["status"] == "ready"
    assert result["actions"]["candidate_score"]["status"] == "no_data"
    assert result["actions"]["content_draft"]["status"] == "ready"
    assert result["actions"]["pilot_approve"]["status"] == "blocked"
    assert "rule_source_evidence_binding_incomplete" in (
        result["actions"]["pilot_approve"]["blockers"]
    )
    assert result["actions"]["external_publish"]["status"] == "blocked"
    assert result["domains"]["settlement"]["scheduled_pay_by"] == (
        "2026-07-25"
    )
    assert result["domains"]["settlement"]["dispute_deadline"] == (
        "2026-08-06"
    )
    assert result["authority"]["permit_created"] is False
    assert result["authority"]["external_write_performed"] is False


def test_prelaunch_quality_and_fee_estimate_do_not_create_action_cycle():
    values = complete_input()
    values["quality"] = {
        "lifecycle": "prelaunch",
        "orders_14d": 0,
        "seller_cancelled_14d": 0,
    }
    values["fee"].pop("settlement_status")
    values["settlement"] = {}

    result = OzonGlobalRuleRegistry().evaluate(
        values,
        as_of="2026-07-27T00:00:00+00:00",
    )

    assert result["domains"]["quality"]["status"] == (
        "not_applicable_prelaunch"
    )
    assert result["domains"]["fee"]["estimate"]["status"] == "ready"
    assert result["domains"]["fee"]["actual_accrual"]["status"] == (
        "not_applicable_prelaunch"
    )
    assert result["domains"]["fee"]["reconciled_cash"]["status"] == (
        "not_applicable_prelaunch"
    )
    assert result["actions"]["observe_research"]["status"] == "ready"
    assert result["actions"]["candidate_score"]["status"] == "no_data"
    assert result["actions"]["pilot_approve"]["status"] == "blocked"
    assert result["actions"]["scale"]["status"] == "no_data"
    assert result["actions"]["settlement_reconcile"]["status"] == (
        "not_applicable_prelaunch"
    )


def test_content_and_passport_fail_closed_on_claims_rights_and_restriction():
    values = complete_input()
    values["passport"]["category_status"] = "restricted"
    values["content"]["title"] = (
        "Лучшая скидка <b>KJDS</b> лестница лестница лестница 1:1"
    )
    values["content"]["images"][0]["has_price"] = True
    values["content"]["images"][1]["rights_evidence_id"] = ""

    result = OzonGlobalRuleRegistry().evaluate(
        values,
        as_of="2026-07-27T00:00:00+00:00",
    )

    assert result["state"] == "ready_with_constraints"
    assert "passport_category_fail_closed" in result["blockers"]
    assert "content_title_forbidden_claim" in result["blockers"]
    assert "content_title_html_forbidden" in result["blockers"]
    assert "content_title_keyword_stuffing" in result["blockers"]
    assert "content_image_forbidden_overlay" in result["blockers"]
    assert "content_image_rights_evidence_missing" in result["blockers"]


def test_price_index_boundaries_never_override_downside_profit():
    registry = OzonGlobalRuleRegistry()
    values = complete_input()
    values["prices"]["buyer_price"] = "102"
    values["prices"]["external_lowest_price"] = "100"

    green = registry.evaluate(
        values,
        as_of="2026-07-27T00:00:00+00:00",
    )
    values["prices"]["buyer_price"] = "105"
    yellow = registry.evaluate(
        values,
        as_of="2026-07-27T00:00:00+00:00",
    )
    values["prices"]["buyer_price"] = "106"
    high_yellow = registry.evaluate(
        values,
        as_of="2026-07-27T00:00:00+00:00",
    )
    values["prices"]["buyer_price"] = "107"
    values["downside_cm3_cny"] = "-0.01"
    red_loss = registry.evaluate(
        values,
        as_of="2026-07-27T00:00:00+00:00",
    )

    assert green["domains"]["price_guard"]["index_band"] == "green"
    assert yellow["domains"]["price_guard"]["index_band"] == "yellow"
    assert high_yellow["domains"]["price_guard"]["index_band"] == "yellow"
    assert high_yellow["domains"]["price_guard"]["index"] == "1.0566"
    assert red_loss["domains"]["price_guard"]["index_band"] == "red"
    assert "price_downside_cm3_floor_failed" in red_loss["blockers"]
    assert (
        red_loss["domains"]["price_guard"]["profit_floor_override_allowed"]
        is False
    )


def test_quality_internal_freeze_and_global_fulfillment_modes():
    values = complete_input()
    values["quality"]["seller_cancelled_14d"] = 10
    values["fulfillment"] = {"mode": "FBO"}

    result = OzonGlobalRuleRegistry().evaluate(
        values,
        as_of="2026-07-27T00:00:00+00:00",
    )

    assert "quality_internal_freeze_threshold_reached" in result["blockers"]
    assert (
        "fulfillment_global_cn_mode_missing_or_invalid"
        in result["blockers"]
    )
    assert (
        result["domains"]["fulfillment"]["ru_local_default_applied"] is False
    )


def test_fee_analytics_and_api_missing_data_are_not_inferred_from_reviews():
    values = complete_input()
    values["fee"] = {}
    values["analytics"] = {
        "source": "public_search_page",
        "fields": {"reviews": 1000},
        "reviews_labeled_as_sales": True,
    }
    values["api_access"] = {
        "auth_source": "cookie",
        "key_roles": [],
        "ip_cidr_allowlist": [],
        "enabled_domains": [],
    }

    result = OzonGlobalRuleRegistry().evaluate(
        values,
        as_of="2026-07-27T00:00:00+00:00",
    )

    assert result["domains"]["fee"]["status"] == "no_data"
    assert result["domains"]["analytics"]["status"] == "no_data"
    assert result["domains"]["analytics"]["review_count_is_sales"] is False
    assert "analytics_reviews_mislabeled_as_sales" in result["blockers"]
    assert "api_official_seller_api_required" in result["blockers"]


def test_settlement_deadline_is_explicitly_estimated_without_holidays():
    result = OzonGlobalRuleRegistry().evaluate(
        complete_input(),
        as_of="2026-07-27T00:00:00+00:00",
    )
    settlement = result["domains"]["settlement"]

    assert settlement["dispute_deadline"] == "2026-08-06"
    assert settlement["deadline_semantics"] == (
        "estimated_weekdays_only_no_official_holiday_calendar"
    )
    assert settlement["authoritative_holiday_calendar_bound"] is False


def test_order_with_blocked_accrual_blocks_cash_and_reconciliation():
    values = complete_input()
    values["fee"]["order_id"] = "order-1"
    values["fee"]["order_status"] = "delivered"

    result = OzonGlobalRuleRegistry().evaluate(
        values,
        as_of="2026-07-27T00:00:00+00:00",
    )

    fee = result["domains"]["fee"]
    assert fee["actual_accrual"]["status"] == "blocked"
    assert fee["reconciled_cash"]["status"] == "blocked_dependency"
    assert "fee_actual_accrual_not_ready" in (
        result["actions"]["settlement_reconcile"]["blockers"]
    )


def test_registry_change_changes_hash_and_forces_sku_fingerprint():
    original = json.loads(DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))
    first = OzonGlobalRuleRegistry(registry=original)
    changed = json.loads(json.dumps(original))
    changed["version"] = "2026.07.27.2"
    second = OzonGlobalRuleRegistry(registry=changed)

    first_result = first.evaluate(
        complete_input(),
        as_of="2026-07-27T00:00:00+00:00",
    )
    second_result = second.evaluate(
        complete_input(),
        as_of="2026-07-27T00:00:00+00:00",
    )

    assert first.registry_hash != second.registry_hash
    assert (
        first_result["evaluation_fingerprint"]
        != second_result["evaluation_fingerprint"]
    )
    assert first_result["rule_change_requires_sku_reevaluation"] is True


def test_effective_registry_price_threshold_changes_compiled_evaluation():
    original = json.loads(DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))
    changed = json.loads(json.dumps(original))
    price_rule = next(
        rule
        for rule in changed["rules"]
        if rule["rule_id"] == "prices.types_and_index"
    )
    price_rule["facts"]["green_max_inclusive"] = "1.01"
    values = complete_input()
    values["prices"]["buyer_price"] = "102"
    values["prices"]["external_lowest_price"] = "100"

    original_result = OzonGlobalRuleRegistry(registry=original).evaluate(
        values,
        as_of="2026-07-27T00:00:00+00:00",
    )
    changed_result = OzonGlobalRuleRegistry(registry=changed).evaluate(
        values,
        as_of="2026-07-27T00:00:00+00:00",
    )

    assert original_result["domains"]["price_guard"]["index_band"] == (
        "green"
    )
    assert changed_result["domains"]["price_guard"]["index_band"] == (
        "yellow"
    )


def test_as_of_without_all_effective_domains_is_fail_closed_no_data():
    result = OzonGlobalRuleRegistry().snapshot(as_of="2025-12-01")

    assert result["state"] == "no_data"
    assert result["missing_domains"]


def test_rule_impact_requires_diff_and_domain_bound_sku_evidence():
    original = json.loads(DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))
    changed = json.loads(json.dumps(original))
    changed["version"] = "2026.07.27.2"
    next(
        rule
        for rule in changed["rules"]
        if rule["rule_id"] == "prices.types_and_index"
    )["facts"]["green_max_inclusive"] = "1.01"
    current = OzonGlobalRuleRegistry(registry=changed)
    previous_hash = OzonGlobalRuleRegistry(
        registry=original
    ).registry_hash

    result = current.impact(
        previous_registry=original,
        previous_registry_hash=previous_hash,
        sku_bindings=[
            {
                "sku_ref": "sku-price",
                "rule_domains": ["prices"],
                "evidence_ids": ["evd-binding"],
            },
            {
                "sku_ref": "sku-content",
                "rule_domains": ["products"],
                "evidence_ids": ["evd-content"],
            },
        ],
        as_of="2026-07-27",
    )

    assert result["changed_domains"] == ["prices"]
    assert result["affected_sku_count"] == 1
    assert result["affected_skus"][0]["sku_ref"] == "sku-price"
    assert result["all_candidates_assumed_affected"] is False


def test_future_rule_is_scheduled_until_effective_date():
    original = json.loads(DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))
    changed = json.loads(json.dumps(original))
    future = json.loads(
        json.dumps(
            next(
                rule
                for rule in original["rules"]
                if rule["rule_id"] == "prices.types_and_index"
            )
        )
    )
    future["rule_id"] = "prices.types_and_index.future"
    future["effective_from"] = "2026-08-01"
    future["facts"]["green_max_inclusive"] = "1.01"
    changed["rules"].append(future)
    current = OzonGlobalRuleRegistry(registry=changed)
    previous_hash = OzonGlobalRuleRegistry(
        registry=original
    ).registry_hash
    binding = [
        {
            "sku_ref": "sku-price",
            "rule_domains": ["prices"],
            "evidence_ids": ["evd-binding"],
        }
    ]

    before = current.impact(
        previous_registry=original,
        previous_registry_hash=previous_hash,
        sku_bindings=binding,
        as_of="2026-07-31",
    )
    effective = current.impact(
        previous_registry=original,
        previous_registry_hash=previous_hash,
        sku_bindings=binding,
        as_of="2026-08-01",
    )

    assert before["state"] == "no_change"
    assert before["affected_sku_count"] == 0
    assert before["scheduled_changes"][0]["effective_at"] == "2026-08-01"
    assert effective["state"] == "change_detected"
    assert effective["affected_sku_count"] == 1
    assert previous_hash == OzonGlobalRuleRegistry(
        registry=original
    ).registry_hash
