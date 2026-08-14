import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
ADR_PATH = ROOT / "docs" / "adr" / "ADR-0094-strategic-intelligence-top1-capital-loop.md"
INTAKE_PATH = (
    ROOT / "docs" / "project" / "registries" / "primary_source_intake.json"
)
BENCHMARK_PATH = (
    ROOT
    / "docs"
    / "project"
    / "registries"
    / "strategic_benchmark_contracts.json"
)


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_primary_source_intake_is_fail_closed_and_private_by_default():
    registry = _load(INTAKE_PATH)
    policy = registry["policy"]

    assert registry["schema_version"] == "kjds-primary-source-intake-v1"
    assert registry["as_of"] == "2026-08-03"
    assert policy["canonical_record_system"].startswith("existing_kjds_")
    assert policy["git_may_store_raw_business_records"] is False
    assert policy["git_may_store_credentials_or_cookies"] is False
    assert policy["git_may_store_bank_or_customer_rows"] is False
    assert policy["model_output_is_primary_source"] is False
    assert policy["marketing_claim_is_benchmark_fact"] is False
    assert policy["external_write_allowed"] is False
    assert policy["outreach_allowed_by_intake"] is False
    assert policy["fact_promotion_requires_independent_review"] is True
    assert policy["lower_grade_may_override_higher_grade"] is False


def test_primary_source_envelope_freezes_integrity_scope_terms_and_review():
    registry = _load(INTAKE_PATH)
    envelope = registry["primary_source_envelope"]
    required = set(envelope["required_fields"])

    assert {
        "source_contract_id",
        "blob_sha256",
        "captured_at",
        "effective_at",
        "as_of",
        "scope",
        "license_and_terms",
        "allowed_purpose",
        "data_classification",
        "conservation_report",
        "reviewer_actor_ref",
        "evidence_refs",
        "lineage_refs",
        "review_due_on",
    } <= required
    assert envelope["integrity"]["sha256_lower_hex_length"] == 64
    assert envelope["integrity"]["raw_blob_reverification_required"] is True
    assert envelope["integrity"]["schema_drift_fails_closed"] is True
    assert envelope["privacy"]["secrets_in_payload_allowed"] is False
    assert (
        envelope["privacy"]["raw_personal_contact_in_contract_fixture_allowed"]
        is False
    )
    assert envelope["privacy"]["do_not_contact_and_withdrawal_state_required"]


def test_source_packs_cover_operating_sales_ai_capital_and_risk_truth():
    registry = _load(INTAKE_PATH)
    packs = {pack["id"]: pack for pack in registry["source_packs"]}

    assert set(packs) == {
        "operating_cash_truth",
        "marketplace_demand_and_catalog",
        "unit_economics_supply_and_logistics",
        "global_trade_lead_intelligence",
        "customer_product_and_revenue",
        "ai_technology_and_cost_benchmark",
        "competitor_enterprise_and_capital",
        "risk_legal_security_and_compliance",
    }
    assert registry["intake_order"][0] == "operating_cash_truth"
    assert "global_trade_lead_intelligence" in registry["intake_order"][:2]
    assert all(pack["minimum_grade_for_fact"] == "A" for pack in packs.values())
    assert all(pack["prohibited_in_git"] for pack in packs.values())


def test_global_trade_sources_are_normalized_without_inventing_buyer_intent():
    packs = {pack["id"]: pack for pack in _load(INTAKE_PATH)["source_packs"]}
    leads = packs["global_trade_lead_intelligence"]
    families = leads["source_families"]
    guards = leads["semantic_guards"]
    controls = leads["collection_controls"]

    assert {
        "amazon",
        "aliexpress",
        "shopee",
        "tiktok_shop",
        "temu",
        "mercado_libre",
        "wildberries",
        "ozon",
        "ebay",
        "lazada",
        "rakuten",
        "yahoo_shopping",
        "walmart_marketplace",
    } <= set(families["retail_marketplaces"])
    assert {"alibaba_com", "global_sources", "made_in_china"} <= set(
        families["b2b_and_export_platforms"]
    )
    assert {
        "yiwugo",
        "1688",
        "global_huapin",
        "baobaoniu",
        "17zwd",
        "souk",
        "eelly",
        "toybaba",
        "meizhuang",
        "zhiai_muying",
        "shipinwang",
        "91jiafang",
        "gongpinhui",
        "global_shoes",
    } <= set(
        families["china_supply_platforms"]
    )
    assert leads["alias_normalization"]["tk"] == "tiktok_shop"
    assert leads["alias_normalization"]["wb"] == "wildberries"
    assert leads["alias_normalization"]["搜款网"] == "souk"
    assert "buyer_signal" in leads["required_entity_types"]
    assert "qualified_opportunity" in leads["required_entity_types"]
    assert guards["seller_presence_implies_buyer_intent"] is False
    assert guards["product_presence_implies_purchase_budget"] is False
    assert guards["public_contact_implies_unlimited_outreach"] is False
    assert guards["qualified_opportunity_requires_first_party_interaction_evidence"]
    assert controls["private_profile_collection_allowed"] is False
    assert controls["captcha_or_login_bypass_allowed"] is False
    assert controls["cookie_or_fingerprint_pool_allowed"] is False
    assert controls["automatic_message_or_platform_write_allowed"] is False
    assert controls["opt_out_suppression_required"] is True


def test_top1_is_dimensioned_comparable_and_never_a_global_marketing_rank():
    registry = _load(BENCHMARK_PATH)
    semantics = registry["top1_semantics"]

    assert registry["schema_version"] == "kjds-strategic-benchmark-contracts-v1"
    assert semantics["global_top1_allowed"] is False
    assert semantics["allowed_labels"] == [
        "metric_leader",
        "frontier_candidate",
        "best_feasible_for_kjds",
    ]
    assert {"cohort", "market", "window", "methodology", "uncertainty"} <= set(
        semantics["required_dimensions"]
    )
    assert "not_comparable" in semantics["comparison_states"]
    assert semantics["marketing_claim_alone_can_win"] is False
    assert semantics["model_output_alone_can_win"] is False
    assert semantics["synthetic_demo_can_set_current_value"] is False


def test_kernel_is_one_read_projection_not_a_second_truth_or_action_plane():
    kernel = _load(BENCHMARK_PATH)["kernel"]

    assert kernel["name"] == "StrategicBenchmarkKernel"
    assert kernel["interface_methods"] == [
        "build_snapshot",
        "compare",
        "propose_portfolio",
        "reconcile",
    ]
    assert {"Evidence", "Fact", "Finance", "OperatingGraph", "AgentRun"} <= set(
        kernel["canonical_inputs"]
    )
    assert kernel["creates_new_truth_store"] is False
    assert kernel["creates_fact_or_finance_entry"] is False
    assert kernel["creates_approval_permit_payment_or_external_write"] is False


def test_nine_domains_have_direction_unit_grade_and_freshness_contracts():
    domains = _load(BENCHMARK_PATH)["domains"]

    assert {domain["id"] for domain in domains} == {
        "technology_architecture",
        "ai_agent",
        "product_experience",
        "global_acquisition_and_sales",
        "commerce_supply_operations",
        "finance_and_capital",
        "organization_execution",
        "security_resilience",
        "data_compliance_governance",
    }
    metric_ids = set()
    for domain in domains:
        assert domain["metrics"]
        for metric in domain["metrics"]:
            assert metric["id"] not in metric_ids
            metric_ids.add(metric["id"])
            assert metric["direction"] in {"higher_is_better", "lower_is_better"}
            assert metric["unit"]
            assert metric["minimum_source_grade"] in {"A", "B"}
            assert metric["freshness_days"] > 0


def test_best_solution_and_capital_proposal_keep_no_action_loss_and_rollback():
    registry = _load(BENCHMARK_PATH)
    profile = registry["best_solution_profile"]
    capital = registry["capital_allocation_proposal"]

    assert {"build", "buy", "partner", "defer", "no_action"} == set(
        profile["required_options"]
    )
    assert profile["equal_weight_total_score_allowed"] is False
    assert {"cash_floor", "maximum_loss", "rollback"} <= set(
        profile["hard_elimination_dimensions"]
    )
    assert capital["proposal_only"] is True
    assert capital["securities_investment_scope"] is False
    assert {"cash_floor", "maximum_loss", "stop_conditions", "rollback"} <= set(
        capital["required_fields"]
    )
    assert capital["self_approval_allowed"] is False
    assert capital["payment_or_external_write_allowed"] is False


def test_constraint_breaker_and_adoption_candidates_are_bounded_and_versioned():
    registry = _load(BENCHMARK_PATH)
    breaker = registry["constraint_breaker"]
    candidates = registry["technology_adoption_candidates"]

    assert breaker["target_scope"].startswith("local_synthetic_kjds_fixtures")
    assert {"prompt_injection", "toolchain_poisoning", "unknown_outcome_replay"} <= set(
        breaker["attack_classes"]
    )
    assert breaker["production_credentials_allowed"] is False
    assert breaker["captcha_or_login_bypass_allowed"] is False
    assert breaker["unbounded_external_network_allowed"] is False
    assert breaker["production_external_write_allowed"] is False
    assert {candidate["id"] for candidate in candidates} == {
        "inspect_ai_eval_adapter",
        "pyrit_red_team_adapter",
        "openai_evals_graders_adapter",
        "opentelemetry_genai_semconv_mapping",
    }
    assert all(candidate["official_source"].startswith("https://") for candidate in candidates)
    assert all(candidate["version_pin_required"] for candidate in candidates)
    assert all(candidate["canonical_owner"] is False for candidate in candidates)


def test_adr_freezes_first_party_top1_leads_capital_and_unknown_boundaries():
    text = ADR_PATH.read_text(encoding="utf-8")

    assert "StrategicBenchmarkKernel" in text
    assert "PrimarySourceEnvelope" in text
    assert "global_trade_lead_intelligence" in text
    assert "seller_account" in text
    assert "buyer_signal" in text
    assert "CapitalAllocationProposal" in text
    assert "Constraint Breaker" in text
    assert "metric_leader" in text
    assert "global_top1" in text
    assert "UNKNOWN" in text
    assert "BAS-198" in text and "BAS-204" in text


def test_contract_freeze_does_not_claim_runtime_top1_or_business_authority():
    boundary = _load(BENCHMARK_PATH)["control_boundary"]

    assert boundary == {
        "contract_is_runtime_implementation": False,
        "contract_is_top1_claim": False,
        "contract_is_business_authority": False,
        "contract_is_capital_approval": False,
        "contract_grants_external_write": False,
        "unknown_current_values_remain_unknown": True,
    }
