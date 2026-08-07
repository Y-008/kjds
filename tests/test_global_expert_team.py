from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.control_plane.global_expert_team import (
    GlobalExpertTeamRegistryError,
    GlobalPortfolioOrchestrator,
)

REGISTRY_PATH = (
    Path(__file__).parents[1]
    / "docs"
    / "project"
    / "registries"
    / "global_expert_team_registry.json"
)


def _route(
    service: GlobalPortfolioOrchestrator,
    *,
    task_ref: str = "task-global-001",
    task_type: str = "market_research",
    market: str = "GLOBAL",
    platform: str = "all",
    risk_level: str = "L0",
    evidence_refs: tuple[str, ...] = (),
):
    return service.route(
        task_ref=task_ref,
        task_type=task_type,
        market=market,
        platform=platform,
        risk_level=risk_level,
        evidence_refs=evidence_refs,
    )


def _mutated_registry(tmp_path: Path, mutate) -> Path:
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    mutate(payload)
    path = tmp_path / "global-expert-team.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_snapshot_freezes_selected_team_model_and_thirteen_roles():
    snapshot = GlobalPortfolioOrchestrator().snapshot()

    assert snapshot["selection"] == {
        "team_model": "ai_core_human_professional_review",
        "portfolio_scope": "global_research_russia_ozon_execution_first",
        "leader_authority": "business_decision_high_risk_dual_sign",
    }
    assert snapshot["leader"]["role_id"] == "global_chief_commerce_officer"
    assert snapshot["counts"] == {
        "leaders": 1,
        "specialists": 12,
        "control_roles": 5,
        "task_routes": 13,
    }
    assert snapshot["operating_status"]["registry_proves_human_appointment"] is False
    assert all(snapshot["control_boundary"][key] is False for key in snapshot["control_boundary"])
    assert snapshot["role_control_defaults"] == {
        "exact_scope": "task_ref_market_platform_risk_and_evidence_refs",
        "cost_budget": "bounded_by_task_contract",
        "time_budget": "default_sla_hours_and_task_deadline",
        "handoff_contract": "kjds-expert-task-contract-v1",
        "trace_id": "required_for_every_agent_run",
        "eval_policy_version": "kjds-team-agent-eval-v1",
        "human_alternate_binding_required": True,
        "forbidden_inputs": [
            "credential",
            "api_key",
            "cookie",
            "password",
            "bank_account",
            "customer_raw_data",
        ],
    }


def test_global_l0_research_is_proposal_routable_without_external_authority():
    result = _route(GlobalPortfolioOrchestrator())

    assert result["status"] == "proposal_routable"
    assert result["scope"] == {
        "market": "GLOBAL",
        "platform": "all",
        "operating_mode": "global_research_only",
    }
    assert result["accountable_specialist"] == "global_market_intelligence"
    assert result["decision_route"]["leader_may_make_business_disposition"] is True
    assert result["decision_route"]["human_dual_sign_required"] is False
    assert result["blockers"] == []
    assert result["role_controls"]["handoff_contract"] == "kjds-expert-task-contract-v1"
    assert result["role_controls"]["human_alternate_binding_required"] is True
    assert result["role_controls"]["tool_allowlist"] == [
        "official_source_read",
        "authorized_market_analytics_read",
        "evidence_query",
        "internal_analysis",
    ]
    assert result["role_controls"]["data_allowlist"] == [
        "public_sources",
        "authorized_market_aggregates",
        "exact_scope_evidence_metadata",
    ]
    assert all(
        result["control_envelope"][key] is False
        for key in (
            "operating_task_created",
            "business_decision_recorded",
            "formal_fact_promoted",
            "finance_entry_created",
            "approval_created",
            "permit_issued",
            "external_write_allowed",
        )
    )


def test_russia_ozon_l3_routes_to_dual_sign_without_issuing_a_permit():
    result = _route(
        GlobalPortfolioOrchestrator(),
        task_ref="task-ru-ozon-listing-001",
        task_type="platform_operations",
        market="RU",
        platform="OZON",
        risk_level="L3",
        evidence_refs=("evd-platform", "evd-profit", "evd-compliance"),
    )

    assert result["status"] == "dual_sign_gate_required"
    assert result["scope"]["operating_mode"] == "russia_ozon_first_execution_theater"
    assert result["decision_route"]["human_dual_sign_required"] is True
    assert result["decision_route"]["action_approver_roles"] == [
        "human_business_owner",
        "independent_approver",
    ]
    assert result["decision_route"]["executor_role"] == "executor"
    assert "named_human_business_owner_binding_required" in result["blockers"]
    assert result["control_envelope"]["permit_issued"] is False
    assert result["control_envelope"]["external_write_allowed"] is False


def test_non_russia_l3_is_blocked_even_with_evidence():
    result = _route(
        GlobalPortfolioOrchestrator(),
        task_ref="task-us-amazon-write-001",
        task_type="platform_operations",
        market="US",
        platform="amazon",
        risk_level="L3",
        evidence_refs=("evd-amazon-contract",),
    )

    assert result["status"] == "blocked_scope"
    assert "execution_scope_not_admitted_outside_russia_ozon" in result["blockers"]
    assert result["control_envelope"]["external_write_allowed"] is False


def test_l4_remains_human_authority_and_never_routes_an_executor():
    result = _route(
        GlobalPortfolioOrchestrator(),
        task_ref="task-ru-contract-001",
        task_type="legal_compliance",
        market="RU",
        platform="ozon",
        risk_level="L4",
        evidence_refs=("evd-contract",),
    )

    assert result["status"] == "human_authority_required"
    assert result["decision_route"]["leader_may_make_business_disposition"] is False
    assert result["decision_route"]["human_dual_sign_required"] is True
    assert result["decision_route"]["executor_role"] is None
    assert "human_domain_authority_required" in result["blockers"]


def test_task_contract_hash_is_deterministic_and_content_bound():
    service = GlobalPortfolioOrchestrator()
    first = _route(service)
    second = _route(service)
    changed = _route(service, task_ref="task-global-002")

    assert first == second
    assert first["task_contract_sha256"] != changed["task_contract_sha256"]
    sealed = dict(first)
    supplied = sealed.pop("task_contract_sha256")
    assert supplied == service._sha256(sealed)


def test_registry_rejects_missing_specialist(tmp_path: Path):
    path = _mutated_registry(
        tmp_path,
        lambda payload: payload["specialist_roles"].pop(),
    )

    with pytest.raises(GlobalExpertTeamRegistryError, match="twelve"):
        GlobalPortfolioOrchestrator(path)


def test_registry_rejects_a_leader_that_can_issue_permits(tmp_path: Path):
    def mutate(payload):
        payload["leader"]["authority"]["may_issue_permit"] = True

    path = _mutated_registry(tmp_path, mutate)

    with pytest.raises(GlobalExpertTeamRegistryError, match="separation of duties"):
        GlobalPortfolioOrchestrator(path)


def test_registry_rejects_missing_role_control_and_empty_tool_allowlist(tmp_path: Path):
    missing_control = _mutated_registry(
        tmp_path,
        lambda payload: payload["role_control_defaults"].pop("trace_id"),
    )

    with pytest.raises(GlobalExpertTeamRegistryError, match="Role control defaults"):
        GlobalPortfolioOrchestrator(missing_control)

    def empty_allowlist(payload):
        payload["specialist_roles"][0]["tool_allowlist"] = []

    empty_tools = _mutated_registry(tmp_path, empty_allowlist)
    with pytest.raises(GlobalExpertTeamRegistryError, match="tool_allowlist"):
        GlobalPortfolioOrchestrator(empty_tools)


def test_unknown_task_type_and_missing_l2_evidence_fail_closed():
    service = GlobalPortfolioOrchestrator()

    with pytest.raises(GlobalExpertTeamRegistryError, match="Unknown expert task type"):
        _route(service, task_type="unknown_task")
    result = _route(
        service,
        task_ref="task-ru-read-001",
        market="RU",
        platform="ozon",
        risk_level="L2",
    )
    assert result["status"] == "read_gate_required"
    assert result["blockers"] == ["evidence_refs_required_for_l2_plus"]
