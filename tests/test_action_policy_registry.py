import ast
import json
from pathlib import Path

import pytest

from apps.control_plane.action_policies import (
    ActionAuthorizationService,
    ActionPolicyError,
    ActionPolicyRegistry,
)
from apps.control_plane.readiness import LISTING_EXECUTION_READINESS_KEYS

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "docs" / "project" / "registries" / "action_policy_registry.json"
EXECUTION_PLANS = ROOT / "apps" / "control_plane" / "execution_plans.py"


def _load_adapter_literals() -> dict[str, dict[str, object]]:
    module = ast.parse(EXECUTION_PLANS.read_text(encoding="utf-8"))
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "ADAPTERS"
            for target in node.targets
        ):
            continue
        value = ast.literal_eval(node.value)
        assert isinstance(value, dict)
        return value
    raise AssertionError("ADAPTERS literal not found")


def test_action_policy_registry_fails_closed_for_high_risk_actions():
    service = ActionPolicyRegistry(REGISTRY)
    registry = service.snapshot()
    tiers = {item["id"]: item for item in registry["risk_tiers"]}
    actions = {item["id"]: item for item in registry["actions"]}

    assert list(tiers) == ["L0", "L1", "L2", "L3", "L4"]
    assert len(actions) == len(registry["actions"])
    assert {"sample_pay", "listing_publish", "purchase_commit", "ledger_post"} <= set(
        actions
    )
    for action in actions.values():
        assert action["fail_closed"] is True
        if action["decision_scope"] == "research":
            assert action["external_business_side_effect"] is False
        if action["risk_tier"] in {"L3", "L4"}:
            tier = tiers[action["risk_tier"]]
            assert tier["minimum_distinct_identities"] >= 2
            assert tier["minimum_approval_decisions"] >= 1
            assert 30 <= tier["permit_ttl_seconds"] <= 900
            assert action["execution_permit_required"] is True
            assert action["permit_ttl_policy"] == "subject_policy_required"
            assert action["request_revalidation"] is True
            assert action["execution_revalidation"] is True
            assert action["idempotency_required"] is True
            assert action["readback_required"] is True
            assert "max_daily_runs" in action["limit_keys"]
            assert action["limit_keys"]
            assert action["required_value_keys"]
            assert action["required_readiness_keys"]


def test_execution_adapters_use_registered_action_ids():
    service = ActionPolicyRegistry(REGISTRY)
    for adapter in _load_adapter_literals().values():
        policy = service.get(adapter["action_id"])
        if adapter["live_execution_supported"]:
            assert policy["decision_scope"] == "real_execution"
            assert policy["risk_tier"] in {"L3", "L4"}
            assert policy["execution_permit_required"] is True
            assert policy["readback_required"] is True


def test_unknown_action_cannot_fall_back_to_a_default_policy():
    service = ActionPolicyRegistry(REGISTRY)
    with pytest.raises(ActionPolicyError, match="Unknown governed action"):
        service.get("free_form_platform_write")


def test_risk_context_is_bound_to_exact_limits_and_values():
    service = ActionPolicyRegistry(REGISTRY)
    bound = service.bind_risk_context(
        "listing_publish",
        limits={
            "max_quantity": "1",
            "max_daily_runs": "5",
            "max_expected_loss": "500.00",
        },
        values={"quantity": "1", "expected_loss": "300"},
        currency="cny",
    )
    assert bound == {
        "limits": {
            "max_daily_runs": "5",
            "max_expected_loss": "500",
            "max_quantity": "1",
        },
        "values": {"expected_loss": "300", "quantity": "1"},
        "currency": "CNY",
        "permit_ttl_seconds": 300,
    }
    with pytest.raises(ActionPolicyError, match="exceeds"):
        service.bind_risk_context(
            "listing_publish",
            limits={
                "max_quantity": "1",
                "max_daily_runs": "5",
                "max_expected_loss": "299",
            },
            values={"quantity": "1", "expected_loss": "300"},
            currency="CNY",
        )


def test_authorize_action_is_the_single_phase_aware_policy_decision():
    service = ActionAuthorizationService(ActionPolicyRegistry(REGISTRY))
    context = {
        "action": "listing_publish",
        "subject_id": "offer-1",
        "actor_id": "requester-1",
        "occurred_at": "2026-07-21T08:00:00+00:00",
        "limits": {
            "max_quantity": "1",
            "max_daily_runs": "5",
            "max_expected_loss": "500",
        },
        "values": {"quantity": "1", "expected_loss": "300"},
        "currency": "CNY",
        "readiness": {"demand.real_execution": True},
        "source_kind": "causal_policy_handoff",
    }

    request = service.authorize_action(phase="request", **context)
    assert request["allowed"] is True
    assert request["risk_tier"] == "L3"

    missing_approval = service.authorize_action(phase="permit", **context)
    assert missing_approval["allowed"] is False
    assert missing_approval["blocking_reasons"] == [
        "APPROVAL_DECISION_REQUIRED",
        "INDEPENDENT_APPROVAL_REQUIRED",
    ]

    permit = service.authorize_action(
        phase="permit",
        approval_actor_ids=["approver-1"],
        **context,
    )
    assert permit["allowed"] is True

    same_executor = service.authorize_action(
        phase="execute",
        approval_actor_ids=["approver-1"],
        executor_id="approver-1",
        **context,
    )
    assert same_executor["allowed"] is False
    assert same_executor["blocking_reasons"] == ["EXECUTOR_INDEPENDENCE_REQUIRED"]

    execute = service.authorize_action(
        phase="execute",
        approval_actor_ids=["approver-1"],
        executor_id="worker-1",
        **context,
    )
    assert execute["allowed"] is True


def test_l4_authorization_fails_closed_without_mfa():
    service = ActionAuthorizationService(ActionPolicyRegistry(REGISTRY))
    decision = service.authorize_action(
        action="purchase_commit",
        subject_id="purchase-1",
        actor_id="requester-1",
        occurred_at="2026-07-21T08:00:00+00:00",
        phase="permit",
        limits={
            "max_amount": "1000",
            "max_quantity": "10",
            "max_daily_runs": "2",
            "max_inventory_exposure": "1000",
            "max_expected_loss": "500",
        },
        values={
            "amount": "900",
            "quantity": "10",
            "inventory_exposure": "900",
            "expected_loss": "300",
        },
        currency="CNY",
        readiness={"demand.real_execution": True},
        approval_actor_ids=["approver-1"],
    )

    assert decision["allowed"] is False
    assert decision["blocking_reasons"] == ["MFA_REQUIRED"]


def test_real_execution_fails_closed_when_required_readiness_is_missing():
    service = ActionAuthorizationService(ActionPolicyRegistry(REGISTRY))
    decision = service.authorize_action(
        action="listing_publish",
        subject_id="offer-1",
        actor_id="requester-1",
        occurred_at="2026-07-21T08:00:00+00:00",
        phase="request",
        limits={
            "max_quantity": "1",
            "max_daily_runs": "5",
            "max_expected_loss": "500",
        },
        values={"quantity": "1", "expected_loss": "300"},
        currency="CNY",
        source_kind="approved_listing_draft",
    )

    assert decision["allowed"] is False
    assert decision["blocking_reasons"] == [
        f"READINESS_REQUIRED:{key}" for key in LISTING_EXECUTION_READINESS_KEYS
    ]


def test_registry_rejects_a_research_action_with_external_side_effect():
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    registry["actions"][0]["external_business_side_effect"] = True

    with pytest.raises(ActionPolicyError, match="Research action cannot"):
        ActionPolicyRegistry._validate(registry)
