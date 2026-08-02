from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pytest

from apps.control_plane.ozon_global_rules import OzonGlobalRuleRegistry
from apps.control_plane.seller_operating_system import (
    MATURITY_ORDER,
    SellerOperatingSystem,
    StrategyPackRegistry,
)


def service() -> SellerOperatingSystem:
    return SellerOperatingSystem(
        ozon_rules=OzonGlobalRuleRegistry(),
        clock=lambda: datetime(2026, 7, 27, 12, tzinfo=UTC),
    )


def seller_facts(**overrides):
    values = {
        "shops": 1,
        "active_skus": 80,
        "users": 1,
        "warehouses": 1,
        "capital_cny": "50000",
        "risk_tolerance": "low",
        "brand_maturity": "unverified",
        "ops_capability": "guided",
    }
    values.update(overrides)
    return {
        "values": values,
        "provenance": {
            "source": "user_self_report",
            "observed_at": "2026-07-27T02:00:00+00:00",
            "evidence_ids": [],
        },
    }


def evaluation_input(**seller_overrides):
    return {
        "seller_facts": seller_facts(**seller_overrides),
        "operating_facts": {
            "downside_cm3_cny": "45",
            "settlement_cycles": 0,
            "data_confidence": "0.72",
            "brand_authorized": False,
            "multi_entity_ready": False,
        },
        "portfolio_items": [
            {
                "sku_ref": "sku-proven",
                "actual_cash_cm3_cny": "80",
                "confidence": "0.95",
                "return_rate": "0.02",
                "fulfillment_status": "verified",
                "settlement_cycles": 2,
            },
            {
                "sku_ref": "sku-experiment",
                "actual_cash_cm3_cny": None,
                "confidence": "0.55",
                "return_rate": None,
                "fulfillment_status": "no_data",
                "settlement_cycles": 0,
            },
            {
                "sku_ref": "sku-exit",
                "actual_cash_cm3_cny": "-1",
                "confidence": "0.90",
                "return_rate": "0.10",
                "fulfillment_status": "verified",
                "settlement_cycles": 2,
            },
        ],
        "advantage_facts": {
            "rule_effective_from": "2026-08-01",
            "affected_sku_count": 12,
            "price_index_frontier": {"status": "ready"},
            "cluster_inventory": {"status": "ready"},
            "content_quality_score": "92",
            "russian_semantic_matrix": {"status": "passed"},
            "qa_insights": {"status": "ready"},
            "advertising_marginal_profit": {"status": "positive"},
            "cash_constrained_replenishment": {"status": "ready"},
            "verified_parent_variant": {"status": "blocked"},
        },
    }


def test_maturity_classifier_uses_facts_not_user_label():
    result = service().classify_maturity(
        {
            **seller_facts(),
            "user_selected_label": "enterprise",
        }
    )

    assert result["classification"] == "novice"
    assert result["scale_segment"] == "novice"
    assert result["operational_maturity"] == "nascent"
    assert result["brand_stage"] == "unverified"
    assert result["risk_posture"] == "low"
    assert result["input_completeness"] == "1.00"
    assert result["evidence_coverage"] == "0.25"
    assert result["classification_confidence"] == "0.34"
    assert result["confidence"] == "0.34"
    assert result["user_label_promoted_to_fact"] is False


def test_same_scale_different_ops_brand_risk_changes_strategy_not_scale():
    basic = service().evaluate(evaluation_input())
    advanced_values = evaluation_input(
        risk_tolerance="moderate",
        brand_maturity="owned",
        ops_capability="standardized",
    )
    advanced_values["operating_facts"]["settlement_cycles"] = 1
    advanced_values["operating_facts"]["data_confidence"] = "0.80"
    advanced = service().evaluate(advanced_values)

    assert basic["seller_profile"]["scale_segment"] == "novice"
    assert advanced["seller_profile"]["scale_segment"] == "novice"
    assert basic["strategy"]["operating_mode"] == (
        "controlled_distribution"
    )
    assert advanced["strategy"]["operating_mode"] == "refined_operation"
    assert basic["strategy"]["axis_basis"] != (
        advanced["strategy"]["axis_basis"]
    )


def test_profiles_change_scale_budget_and_approval_not_truth_kernel():
    seller_os = service()
    novice = seller_os.evaluate(evaluation_input())
    mid_market = seller_os.evaluate(
        evaluation_input(
            shops=20,
            active_skus=150000,
            users=150,
            warehouses=12,
            capital_cny="20000000",
            brand_maturity="portfolio",
            ops_capability="erp_wms",
        )
    )

    assert novice["seller_profile"]["classification"] == "novice"
    assert mid_market["seller_profile"]["classification"] == "mid_market"
    assert novice["policy_envelope"]["scan_batch_max"] == 100
    assert mid_market["policy_envelope"]["scan_batch_max"] == 10000
    assert novice["policy_envelope"]["approval_layers"] == 1
    assert mid_market["policy_envelope"]["approval_layers"] == 3
    assert (
        novice["strategy_pack"]["facts_and_profit_kernel"]
        == mid_market["strategy_pack"]["facts_and_profit_kernel"]
        == "shared"
    )
    assert novice["strategy_pack"]["truth_degraded"] is False
    assert mid_market["external_execution"]["permit_created"] is False


def test_portfolio_buckets_require_actual_cash_for_proven():
    result = service().evaluate(evaluation_input())

    portfolio = result["portfolio"]
    assert portfolio["buckets"]["proven"] == ["sku-proven"]
    assert portfolio["buckets"]["experiment"] == []
    assert portfolio["buckets"]["exit"] == ["sku-exit"]
    assert portfolio["unclassified"] == ["sku-experiment"]
    assert portfolio["unclassified_receives_allocation"] is False
    assert portfolio["allocation_policy"]["proven"] == "0.60"
    assert (
        portfolio["allocation_policy"]["semantics"]
        == "configurable_internal_policy_not_current_fact"
    )


def test_all_incomplete_portfolio_items_do_not_establish_snapshot():
    values = evaluation_input()
    values["portfolio_items"] = [
        {
            "sku_ref": "sku-no-cash",
            "actual_cash_cm3_cny": None,
            "confidence": "0.8",
            "return_rate": None,
            "fulfillment_status": "no_data",
            "settlement_cycles": 0,
        }
    ]

    portfolio = service().evaluate(values)["portfolio"]

    assert portfolio["status"] == "no_data"
    assert portfolio["snapshot_established"] is False
    assert portfolio["classified_snapshot_established"] is False
    assert portfolio["unclassified"] == ["sku-no-cash"]
    assert all(value == 0 for value in portfolio["counts"].values())


def test_policy_override_cannot_expand_pack_or_remove_safety():
    values = evaluation_input()
    values["policy_overrides"] = {
        "single_sku_budget_cny": "5000",
        "permit_ttl_minutes": "600",
    }

    result = service().evaluate(values)

    assert "policy_override_single_sku_budget_cny_expands_default" in (
        result["blockers"]
    )
    assert "policy_override_permit_ttl_minutes_not_allowed" in (
        result["blockers"]
    )
    assert result["policy_envelope"]["kill_switch_required"] is True
    assert result["external_execution"]["readback_required"] is True


def test_missing_maturity_facts_are_no_data_not_guessed():
    result = service().evaluate(
        {
            "seller_facts": {
                "values": {"shops": 1, "active_skus": 10},
                "provenance": {
                    "source": "user_self_report",
                    "observed_at": "2026-07-27T00:00:00+00:00",
                },
            }
        }
    )

    assert result["status"] == "no_data"
    assert result["seller_profile"]["classification"] is None
    assert "capital_cny" in result["seller_profile"]["missing_facts"]
    assert result["external_write_performed"] is False


def test_maturity_rejects_arbitrary_scales_and_negative_counts():
    facts = seller_facts()
    facts["values"]["risk_tolerance"] = "whatever"
    facts["values"]["shops"] = -1

    try:
        service().classify_maturity(facts)
    except ValueError as error:
        assert "shops" in str(error)
    else:
        raise AssertionError("invalid maturity facts must fail")


def test_action_scopes_allow_research_and_draft_without_settlement():
    values = evaluation_input()
    values["portfolio_items"] = []
    values["operating_facts"] = {}
    values["advantage_facts"] = {}

    result = service().evaluate(values)

    assert result["status"] == "ready_with_constraints"
    assert result["action_readiness"]["observe_research"]["status"] == "ready"
    assert result["action_readiness"]["content_draft"]["status"] == "ready"
    assert result["action_readiness"]["candidate_score"]["status"] == (
        "blocked"
    )
    assert result["action_readiness"]["external_publish"]["status"] == (
        "blocked"
    )
    assert result["action_readiness"]["settlement_reconcile"]["status"] == (
        "not_applicable_prelaunch"
    )


def test_candidate_matrix_keeps_same_facts_and_varies_envelope():
    candidate = {
        "fingerprint": "f" * 64,
        "economics": {
            "downside": {"inventory_cash_cny": "1200"},
            "actual_profit": None,
        },
        "ozon_global_cn": {"state": "ready"},
        "pilot_ready": True,
    }

    matrix = service().candidate_matrix(candidate)

    assert [row["maturity"] for row in matrix["rows"]] == list(
        MATURITY_ORDER
    )
    assert matrix["rows"][0]["decision"] == "blocked"
    assert matrix["rows"][1]["decision"] == (
        "eligible_for_independent_approval"
    )
    assert matrix["rows"][0]["approval_layers"] == 1
    assert matrix["rows"][-1]["approval_layers"] == 4
    assert matrix["same_candidate_facts"] is True
    assert matrix["automatic_listing_count_is_success_metric"] is False
    assert all(row["initial_pilot_units_max"] == 3 for row in matrix["rows"])
    assert matrix["rows"][-1]["scaled_inventory_cap"] > 3


def test_strategy_pack_history_hash_and_as_of_are_replayable():
    registry = StrategyPackRegistry(as_of="2026-07-27")
    snapshot = registry.snapshot()
    artifact = registry.path.parent / snapshot["artifact_path"]

    assert hashlib.sha256(artifact.read_bytes()).hexdigest() == (
        snapshot["registry_hash"]
    )
    assert snapshot["commercial_status"] == (
        "hypothesis_internal_preview_not_for_sale"
    )
    with pytest.raises(RuntimeError, match="effective for as_of"):
        StrategyPackRegistry(as_of="2026-07-26")


def test_strategy_pack_history_rejects_overlapping_versions():
    index = json.loads(
        StrategyPackRegistry().path.read_text(encoding="utf-8")
    )
    duplicate = dict(index["versions"][0])
    duplicate["version"] = "overlap"
    index["versions"].append(duplicate)

    with pytest.raises(RuntimeError, match="overlap"):
        StrategyPackRegistry(payload=index, as_of="2026-07-27")
