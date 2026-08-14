"""COM-001 commercial discovery contract kernel tests (prep-only slice)."""

from __future__ import annotations

import pytest

from apps.control_plane.commercial_discovery import (
    ALLOWED_SALES_FRAMINGS,
    CONTRACT_CHECKLIST_ITEMS,
    PROHIBITED_SALES_CLAIMS,
    REJECT_CONDITIONS,
    ZERO_AUTHORITY_KEYS,
    CommercialDiscoveryError,
    GovernedCommercialDiscovery,
)


def _discovery() -> GovernedCommercialDiscovery:
    return GovernedCommercialDiscovery()


def _qualified_profile(**overrides) -> dict:
    profile = {
        "country": "cn",
        "ozon_stores": 1,
        "active_skus": 200,
        "team_size": 5,
        "has_real_account": True,
        "provides_evidence": True,
        "sells_prohibited_or_infringing": False,
        "requests_blackhat": False,
        "requests_unapproved_direct_write": False,
        "demands_profit_guarantee": False,
    }
    profile.update(overrides)
    return profile


def test_standard_icp_qualifies():
    result = _discovery().qualify(profile=_qualified_profile())
    assert result.status == "qualified"
    assert result.qualified is True
    assert result.reject_reasons == ()
    assert result.defer_reasons == ()
    assert result.unknowns == ()
    assert result.external_action_allowed is False


def test_reject_priority_overrides_defer_and_unknown():
    result = _discovery().qualify(
        profile=_qualified_profile(
            has_real_account=False,
            is_novice_insufficient_data_or_payment=True,
        )
    )
    assert result.status == "rejected"
    assert "no_real_account" in result.reject_reasons


def test_defer_condition():
    result = _discovery().qualify(
        profile=_qualified_profile(is_novice_insufficient_data_or_payment=True)
    )
    assert result.status == "deferred"
    assert "novice_insufficient_data_or_payment" in result.defer_reasons


def test_large_enterprise_defers():
    result = _discovery().qualify(
        profile=_qualified_profile(has_large_enterprise_requirements=True)
    )
    assert result.status == "deferred"
    assert "large_enterprise_requirements" in result.defer_reasons


def test_unknown_field_becomes_needs_evidence():
    result = _discovery().qualify(profile=_qualified_profile(active_skus=None))
    assert result.status == "needs_evidence"
    assert "active_skus" in result.unknowns


def test_missing_reject_flag_becomes_needs_evidence():
    profile = _qualified_profile()
    del profile["has_real_account"]
    result = _discovery().qualify(profile=profile)
    assert result.status == "needs_evidence"
    assert "has_real_account" in result.unknowns


def test_refuses_evidence_rejects():
    result = _discovery().qualify(profile=_qualified_profile(provides_evidence=False))
    assert result.status == "rejected"
    assert "refuses_evidence" in result.reject_reasons


def test_prohibited_or_infringing_rejects():
    result = _discovery().qualify(
        profile=_qualified_profile(sells_prohibited_or_infringing=True)
    )
    assert result.status == "rejected"
    assert "sells_prohibited_or_infringing" in result.reject_reasons


def test_blackhat_rejects():
    result = _discovery().qualify(profile=_qualified_profile(requests_blackhat=True))
    assert result.status == "rejected"
    assert "requests_blackhat" in result.reject_reasons


def test_unapproved_direct_write_rejects():
    result = _discovery().qualify(
        profile=_qualified_profile(requests_unapproved_direct_write=True)
    )
    assert result.status == "rejected"
    assert "requests_unapproved_direct_write" in result.reject_reasons


def test_profit_guarantee_rejects():
    result = _discovery().qualify(
        profile=_qualified_profile(demands_profit_guarantee=True)
    )
    assert result.status == "rejected"
    assert "demands_profit_guarantee" in result.reject_reasons


def test_sensitive_profile_fail_closed():
    with pytest.raises(CommercialDiscoveryError):
        _discovery().qualify(profile={"country": "cn", "note": "password=hunter2"})


def test_non_bool_reject_field_fail_closed():
    with pytest.raises(CommercialDiscoveryError):
        _discovery().qualify(profile=_qualified_profile(has_real_account="yes"))


def test_non_int_numeric_field_fail_closed():
    with pytest.raises(CommercialDiscoveryError):
        _discovery().qualify(profile=_qualified_profile(ozon_stores="many"))


def test_diagnostic_deliverable_read_only_not_for_sale():
    deliverable = _discovery().diagnostic_scope()
    assert deliverable.not_for_sale is True
    assert deliverable.external_write_allowed is False
    assert deliverable.scope == ("single_store", "read_only")
    assert deliverable.outputs == ("data_quality_report", "sku_profit_gap")
    assert deliverable.delivery_format == "one_delivery_meeting"
    assert deliverable.success_condition == "customer_accepted_problem_and_next_action_within_5_working_days"


def test_pricing_hypothesis_all_not_for_sale():
    items = _discovery().pricing_hypothesis()
    assert len(items) == 4
    assert all(item.not_for_sale is True for item in items)
    by_product = {item.product: item for item in items}
    assert by_product["profit_truth_diagnostic"].price_cny == 4800
    assert by_product["profit_truth_diagnostic"].unit == "per_run"
    assert by_product["design_partner_pilot"].price_cny == 19800
    assert by_product["design_partner_pilot"].unit == "per_store"
    assert by_product["team_edition"].price_cny == 39900
    assert by_product["team_edition"].unit == "per_store_per_year"
    assert by_product["enterprise"].price_cny is None
    assert by_product["enterprise"].unit is None
    assert by_product["enterprise"].note == "post_g7_quote"


def test_contract_checklist_all_unknown():
    result = _discovery().contract_checklist()
    assert len(result.items) == 8
    assert set(CONTRACT_CHECKLIST_ITEMS) == {item["key"] for item in result.items}
    assert all(item["status"] == "UNKNOWN" for item in result.items)
    assert result.all_unknown is True


def test_sales_copy_rejects_prohibited_claims():
    result = _discovery().sales_copy_contract(
        copy=["guaranteed_profit", "market_leader", "traceable_sku_cash_profit"]
    )
    assert set(result.rejected) == {"guaranteed_profit", "market_leader"}
    assert result.accepted == ("traceable_sku_cash_profit",)
    assert result.external_write_allowed is False


def test_sales_copy_allows_framings():
    result = _discovery().sales_copy_contract(copy=list(ALLOWED_SALES_FRAMINGS))
    assert set(result.accepted) == set(ALLOWED_SALES_FRAMINGS)
    assert result.rejected == ()


def test_sales_copy_unknown_phrase():
    result = _discovery().sales_copy_contract(copy=["some_unrecognized_phrase"])
    assert "some_unrecognized_phrase" in result.unknowns


def test_readback_pending_verified_invalidated():
    discovery = _discovery()
    deliverable = discovery.diagnostic_scope()
    assert discovery.readback(deliverable)["readback_state"] == "PENDING"
    assert (
        discovery.readback(deliverable, observed=deliverable.deliverable_sha256)["readback_state"]
        == "VERIFIED"
    )
    assert discovery.readback(deliverable, observed="0" * 64)["readback_state"] == "INVALIDATED"


def test_zero_authority_all_false():
    authority = _discovery().zero_authority()
    assert set(authority) == set(ZERO_AUTHORITY_KEYS)
    assert all(value is False for value in authority.values())
    assert {"invoice", "payment", "receivable"} <= set(authority)


def test_reject_conditions_frozen():
    assert {
        "no_real_account",
        "refuses_evidence",
        "sells_prohibited_or_infringing",
        "requests_blackhat",
        "requests_unapproved_direct_write",
        "demands_profit_guarantee",
    } == REJECT_CONDITIONS


def test_prohibited_sales_claims_frozen():
    assert {
        "guaranteed_profit",
        "fully_automated_store_takeover",
        "ai_guaranteed_growth",
        "market_leader",
    } == PROHIBITED_SALES_CLAIMS
