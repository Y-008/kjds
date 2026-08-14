from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.control_plane.enterprise_positioning import (
    EnterprisePositioningAdvisor,
    EnterprisePositioningError,
)

ROOT = Path(__file__).parents[1]
REGISTRY = (
    ROOT
    / "docs"
    / "project"
    / "registries"
    / "enterprise_positioning_profiles.json"
)
MASTER_SPEC = ROOT / "docs" / "project" / "MASTER_SPEC.md"
BAS223_EVIDENCE = (
    ROOT
    / "docs"
    / "project"
    / "evidence"
    / "20260814_BAS_223_BOARD_RESET_ENTERPRISE_POSITIONING_V2.md"
)


def _current_profile() -> dict:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))["current_profile"]


def _roles(projection: dict) -> dict[str, dict]:
    return {item["role_ref"]: item for item in projection["role_roster"]}


def test_current_kjds_is_truth_cash_control_plane_before_enterprise_ai_erp():
    projection = EnterprisePositioningAdvisor().position()

    assert projection["contract_id"] == "kjds-enterprise-positioning-advisor-v2"
    assert projection["version"] == "2.0.0"
    assert projection["status"] == "RECOMMENDATION_ONLY"
    assert projection["enterprise_profile"] == _current_profile()
    positioning = projection["enterprise_positioning"]
    assert positioning["archetype_ref"] == "truth_loop_validation"
    assert positioning["current_positioning"] == (
        "面向跨境电商经营者的、证据优先、真实现金导向、受控自动化的经营控制面"
    )
    assert positioning["promotion_gate_status"] == "BLOCKED_EVIDENCE"
    assert positioning["required_gates"] == [
        "one_truth_sku_cash_verified",
        "commercial_c0_passed",
        "human_accountability_bound",
        "sod_conflicts_cleared",
        "g1_pass_current",
    ]
    assert positioning["automation_ceiling"] == "read_only_recommendation_only"


def test_br149_supersedes_br148_and_freezes_private_readiness_truth():
    spec = MASTER_SPEC.read_text(encoding="utf-8")
    evidence = BAS223_EVIDENCE.read_text(encoding="utf-8")
    br149 = next(line for line in spec.splitlines() if line.startswith("| BR-149 |"))
    supersession = next(
        line for line in spec.splitlines() if line.startswith("BR-148 已由 BR-149")
    )

    assert "BR-148 已由 BR-149 明确取代" in supersession
    assert "`g0-ozon-api-identities.csv` 为 `ready_for_human_review`" in br149
    assert "其余七区保持 `awaiting_inputs`" in br149
    assert "`automatic_import=false`" in br149
    assert "`formal_fact_promoted=false`" in br149
    assert "不等于业务 ready、生产准入或 Fact 晋升" in br149
    assert "Only `g0-ozon-api-identities.csv` is `ready_for_human_review`" in evidence
    assert "the seven `awaiting_inputs` sections" in evidence
    assert "`automatic_import=false`" in evidence
    assert "`formal_fact_promoted=false`" in evidence
    assert "do not make the package business-ready" in evidence
    assert "all eight sections remain" not in evidence
    assert "`ready_sections=[]`" not in evidence


def test_all_35_entries_are_unique_authority_free_capability_templates():
    projection = EnterprisePositioningAdvisor().position()
    roles = projection["role_roster"]

    assert projection["role_summary"] == {
        "catalog_total": 35,
        "required_now": 12,
        "supporting_ai": 9,
        "on_demand": 9,
        "standby": 5,
        "unsupported_gap": 0,
        "core": 18,
        "ai_specialist": 12,
        "independent_control": 5,
    }
    assert len({item["role_ref"] for item in roles}) == 35
    assert len({item["role_template_ref"] for item in roles}) == 35
    assert all("test_principal_ref" not in item for item in roles)
    assert all(item["runtime_mode"] == "capability_template_only" for item in roles)
    assert all(item["human_binding_status"] == "UNKNOWN" for item in roles)
    assert all(item["production_authority_granted"] is False for item in roles)
    assert all(item["external_write_allowed"] is False for item in roles)
    assert all(item["formal_fact_promotion_allowed"] is False for item in roles)


def test_business_model_changes_operating_product_and_customer_success_weight():
    advisor = EnterprisePositioningAdvisor()
    profile = _current_profile()
    merchant = advisor.position({**profile, "business_model": "merchant_operator"})
    provider = advisor.position(
        {**profile, "business_model": "commerce_control_plane_provider"}
    )

    assert _roles(merchant)["global_chief_commerce_officer"][
        "recommendation_status"
    ] == "required_now"
    assert _roles(provider)["product_lead"]["recommendation_status"] == "required_now"
    assert _roles(provider)["backend_integration_engineer"][
        "recommendation_status"
    ] == "required_now"
    assert merchant["enterprise_positioning"]["business_model_emphasis"] != provider[
        "enterprise_positioning"
    ]["business_model_emphasis"]


def test_stage_changes_role_breadth_and_positioning_archetype():
    advisor = EnterprisePositioningAdvisor()
    profile = _current_profile()
    validation = advisor.position(profile)
    repeatable = advisor.position({**profile, "stage": "repeatable"})

    assert validation["enterprise_positioning"]["archetype_ref"] == (
        "truth_loop_validation"
    )
    assert repeatable["enterprise_positioning"]["archetype_ref"] == (
        "repeatable_growth_company"
    )
    assert repeatable["role_summary"]["required_now"] > validation["role_summary"][
        "required_now"
    ]


def test_headcount_band_changes_capacity_and_wip_not_only_validation():
    advisor = EnterprisePositioningAdvisor()
    profile = _current_profile()
    micro = advisor.position(profile)["capacity_plan"]
    medium = advisor.position({**profile, "headcount_band": "medium"})[
        "capacity_plan"
    ]

    assert micro["max_parallel_workstreams"] == 2
    assert micro["max_active_work_per_human"] == 1
    assert micro["role_bundle_mode"] == "four_seat_compressed"
    assert medium["max_parallel_workstreams"] == 6
    assert medium["max_active_work_per_human"] == 2
    assert medium["role_bundle_mode"] == "dedicated_role_bindings_preferred"


def test_markets_activate_supported_role_and_only_emit_gap_when_unsupported():
    advisor = EnterprisePositioningAdvisor()
    profile = _current_profile()
    ru = advisor.position(profile)
    de = advisor.position({**profile, "markets": ["DE"]})

    assert _roles(ru)["russia_ozon_general_manager"][
        "recommendation_status"
    ] == "on_demand"
    assert de["role_gaps"] == [
        {
            "gap_ref": "country_general_manager:DE",
            "recommendation_status": "unsupported_gap",
            "reason_code": "market_specific_role_contract_missing",
            "authority_status": "UNKNOWN",
        }
    ]


def test_platforms_activate_supported_operator_and_never_fake_local_authority():
    advisor = EnterprisePositioningAdvisor()
    profile = _current_profile()
    ozon = advisor.position(profile)
    amazon = advisor.position({**profile, "platforms": ["amazon"]})

    assert _roles(ozon)["ozon_channel_operations_lead"][
        "recommendation_status"
    ] == "required_now"
    assert amazon["role_gaps"] == [
        {
            "gap_ref": "channel_operations_lead:amazon",
            "recommendation_status": "unsupported_gap",
            "reason_code": "platform_specific_role_contract_missing",
            "authority_status": "UNKNOWN",
        }
    ]


def test_risk_class_changes_independent_control_and_automation_ceiling():
    advisor = EnterprisePositioningAdvisor()
    profile = _current_profile()
    standard = advisor.position({**profile, "risk_class": "standard"})
    regulated = advisor.position({**profile, "risk_class": "regulated"})

    assert _roles(standard)["independent_approver"][
        "recommendation_status"
    ] == "on_demand"
    assert _roles(regulated)["independent_approver"][
        "recommendation_status"
    ] == "required_now"
    assert standard["enterprise_positioning"]["automation_ceiling"] == (
        "simulation_only"
    )
    assert regulated["enterprise_positioning"]["automation_ceiling"] == (
        "zero_external_action_without_professional_gate"
    )


def test_primary_objective_changes_the_unique_next_activation_and_gate():
    advisor = EnterprisePositioningAdvisor()
    profile = _current_profile()
    cash = advisor.position(profile)["next_role_activation"]
    growth = advisor.position({**profile, "primary_objective": "repeatable_growth"})[
        "next_role_activation"
    ]

    assert cash == {
        "role_ref": "russia_ozon_general_manager",
        "role_template_ref": (
            "role-template://kjds/enterprise-positioning/v2/"
            "russia_ozon_general_manager"
        ),
        "current_status": "on_demand",
        "target_status": "required_now",
        "reason_code": "primary_objective_next_capability",
        "required_gate": "truth_sku_owner_and_evidence_manifest_bound",
    }
    assert growth["role_ref"] == "growth_sales_customer_success_lead"
    assert growth["required_gate"] == "one_truth_sku_cash_verified"


def test_enterprise_ref_changes_only_stable_non_authoritative_scope_and_hash():
    advisor = EnterprisePositioningAdvisor()
    current = advisor.position()
    scenario = advisor.position({**_current_profile(), "enterprise_ref": "acme-ru"})

    assert scenario["profile_scope"] == {
        "enterprise_ref": "acme-ru",
        "scope_ref": "enterprise-profile://acme-ru",
        "grants_authority": False,
    }
    assert scenario["role_roster"] == current["role_roster"]
    assert scenario["snapshot_sha256"] != current["snapshot_sha256"]


def test_empty_profile_mapping_fails_closed_instead_of_using_current_profile():
    with pytest.raises(EnterprisePositioningError, match="profile fields"):
        EnterprisePositioningAdvisor().position({})


def test_sod_and_supported_role_map_drift_fail_closed(tmp_path):
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    registry["supported_market_role_map"]["RU"] = "finance_controller"
    drifted_registry = tmp_path / "positioning.json"
    drifted_registry.write_text(json.dumps(registry), encoding="utf-8")
    with pytest.raises(EnterprisePositioningError, match="not bijective"):
        EnterprisePositioningAdvisor(registry_path=drifted_registry)

    program_path = (
        ROOT
        / "docs"
        / "project"
        / "registries"
        / "enterprise_ai_erp_program.json"
    )
    program = json.loads(program_path.read_text(encoding="utf-8"))
    program["sod_rules"][1] = dict(program["sod_rules"][0])
    drifted_program = tmp_path / "program.json"
    drifted_program.write_text(json.dumps(program), encoding="utf-8")
    with pytest.raises(EnterprisePositioningError, match="Canonical SoD"):
        EnterprisePositioningAdvisor(enterprise_program_path=drifted_program)


def test_four_human_accountability_seats_and_sod_never_self_certify():
    projection = EnterprisePositioningAdvisor().position()
    seats = projection["seat_plan"]

    assert 2 <= len(seats) <= 4
    assert [item["seat_ref"] for item in seats] == [
        "business_accountability",
        "operations_and_delivery",
        "finance_control",
        "independent_control",
    ]
    assert all(item["binding_status"] == "UNKNOWN" for item in seats)
    assert all(item["ai_templates_excluded"] is True for item in seats)
    assert all(item["appointment_evidence_present"] is False for item in seats)
    assert all(item["sod_conflict_refs"] == [] for item in seats)
    assert len(projection["minimum_human_accountability"]) == 4
    assert all(
        item["role_template_is_appointment_evidence"] is False
        for item in projection["minimum_human_accountability"]
    )
    assert len(projection["separation_of_duties"]) == 6
    assert all(
        rule["same_role_allowed"] is False
        and rule["same_principal_allowed"] is False
        for rule in projection["separation_of_duties"]
    )
    seat_by_ref = {item["seat_ref"]: item for item in seats}
    assert "finance_controller" in seat_by_ref["finance_control"]["role_bundle_refs"]
    assert "independent_approver" in seat_by_ref["independent_control"][
        "role_bundle_refs"
    ]
    assert "executor" not in seat_by_ref["independent_control"]["role_bundle_refs"]

    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    registry_seats = {
        item["seat_ref"]: item["role_bundle_refs"]
        for item in registry["seat_templates"]
    }
    assert "qa_release_lead" in registry_seats["independent_control"]
    assert "qa_release_lead" not in registry_seats["operations_and_delivery"]


def test_system_actions_are_all_false_and_contain_no_identity_creation_semantics():
    projection = EnterprisePositioningAdvisor().position()

    assert projection["system_actions"] == {
        "identities_created": False,
        "agents_created": False,
        "humans_appointed": False,
        "appointments_created": False,
        "roles_bound": False,
        "tasks_started": False,
        "budgets_created": False,
        "approvals_created": False,
        "permits_issued": False,
        "production_authority_granted": False,
        "facts_promoted": False,
        "external_write_performed": False,
    }
    assert projection["enterprise_positioning"]["boundaries"] == {
        "is_erp_replacement": False,
        "is_unattended_autonomous_company": False,
        "is_generic_ai_outsourcing": False,
        "is_business_truth_authority": False,
        "system_may_appoint_humans": False,
        "system_may_grant_production_authority": False,
        "role_templates_may_external_write": False,
        "profile_scope_grants_authority": False,
    }


def test_projection_is_deterministic_content_bound_and_defensive():
    advisor = EnterprisePositioningAdvisor()
    first = advisor.position()
    second = advisor.position()

    assert first == second
    basis = dict(first)
    supplied = basis.pop("snapshot_sha256")
    assert supplied == advisor._hash(basis)
    first["role_roster"][0]["title"] = "mutated"
    first["source_hashes"]["team_control_tower"] = "0" * 64
    assert advisor.position() == second


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update(extra="forbidden"),
        lambda value: value.update(stage="unknown"),
        lambda value: value.update(markets=[]),
        lambda value: value.update(platforms=["ozon", "ozon"]),
        lambda value: value.update(enterprise_ref="not allowed"),
    ],
)
def test_invalid_enterprise_profiles_fail_closed(mutate):
    profile = _current_profile()
    mutate(profile)

    with pytest.raises(EnterprisePositioningError):
        EnterprisePositioningAdvisor().position(profile)


def test_registry_cannot_grant_role_or_external_authority(tmp_path):
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    payload["positioning_boundaries"]["system_may_grant_production_authority"] = True
    path = tmp_path / "positioning.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(EnterprisePositioningError, match="authority boundary"):
        EnterprisePositioningAdvisor(path)


def test_registry_rejects_duplicate_or_identity_like_role_template_contract(tmp_path):
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    payload["control_role_templates"][0]["role_ref"] = "finance_controller"
    path = tmp_path / "positioning.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(EnterprisePositioningError, match="35 unique templates"):
        EnterprisePositioningAdvisor(path)
