import json
from pathlib import Path


def test_loop_engineering_registry_covers_the_six_control_modules():
    path = Path(__file__).parents[1] / "docs" / "project" / "registries" / "loop_engineering_registry.json"
    registry = json.loads(path.read_text(encoding="utf-8"))

    modules = {module["id"]: module for module in registry["modules"]}
    assert set(modules) == {
        "automations",
        "skills",
        "integrations",
        "subagents",
        "worktrees",
        "memory",
    }
    for module in modules.values():
        assert module["state"] in {"partial", "design_only", "process_only", "ready"}
        assert module["required_controls"]
        assert module["promotion_gate"]
    assert len(registry["loop_contract"]) >= 6


def test_team_agent_roles_are_bounded_and_independently_verified():
    path = Path(__file__).parents[1] / "docs" / "project" / "registries" / "loop_engineering_registry.json"
    registry = json.loads(path.read_text(encoding="utf-8"))
    team = registry["team_agent_contract"]

    assert registry["version"] == "2.1"
    assert team["architecture"] == (
        "coordinator_plus_bounded_specialists_plus_independent_verifier"
    )
    assert {"coordinator", "finance", "risk", "execution", "independent_verifier"} <= set(
        team["roles"]
    )
    assert {"exact_scope", "tool_allowlist", "cost_budget", "trace_id"} <= set(
        team["required_per_role"]
    )
    assert all(value is False for value in team["separation_of_duties"].values())


def test_self_learning_requires_eval_shadow_review_and_rollback():
    path = Path(__file__).parents[1] / "docs" / "project" / "registries" / "loop_engineering_registry.json"
    registry = json.loads(path.read_text(encoding="utf-8"))
    evolution = registry["evolution_loop"]

    assert evolution["contract_id"] == "kjds-governed-team-agent-evolution-v1"
    assert {"evaluation", "shadow", "independent_review", "rolled_back"} <= set(
        evolution["states"]
    )
    assert {
        "frozen_eval_set",
        "baseline_comparison",
        "negative_and_scope_tests",
        "independent_review",
        "rollback_artifact",
    } <= set(evolution["promotion_requirements"])
    assert evolution["automatic_promotion_allowed"] is False
    assert evolution["runtime_code_self_modification_allowed"] is False
    assert evolution["runtime_permission_self_modification_allowed"] is False
    assert evolution["formal_fact_self_promotion_allowed"] is False
    assert evolution["external_write_self_enable_allowed"] is False

    allowed_transitions = set(evolution["allowed_transitions"])
    assert allowed_transitions == {
        "observation->skill_candidate",
        "skill_candidate->evaluation",
        "evaluation->shadow",
        "evaluation->rolled_back",
        "shadow->independent_review",
        "shadow->rolled_back",
        "independent_review->promoted",
        "independent_review->rolled_back",
        "promoted->active",
        "promoted->rolled_back",
        "active->rolled_back",
        "active->retired",
        "rolled_back->retired",
    }
    assert "observation->active" not in allowed_transitions
    controls = evolution["transition_controls"]
    assert controls["append_only_audit_required"] is True
    assert controls["atomic_transition_required"] is True
    assert controls["idempotency_key_required"] is True
    assert controls["expected_previous_state_required"] is True
    assert controls["evidence_reference_required"] is True
    assert controls["candidate_author_may_review"] is False
    assert controls["candidate_author_may_promote"] is False
    assert controls["reviewer_must_differ_from_candidate_author"] is True
    assert controls["active_requires_human_owner_and_risk_authority"] is True


def test_graph_learning_and_frontier_updates_remain_observations():
    path = Path(__file__).parents[1] / "docs" / "project" / "registries" / "loop_engineering_registry.json"
    registry = json.loads(path.read_text(encoding="utf-8"))
    graph = registry["graph_learning_contract"]
    updates = registry["continuous_update_contract"]

    assert graph["canonical_graph_remains_authority"] is True
    assert graph["generated_node_or_edge_status"] == (
        "observation_until_independent_promotion"
    )
    assert graph["raw_cross_tenant_learning_allowed"] is False
    assert graph["deidentified_pattern_requires_license_and_revocation"] is True
    assert graph["temporal_validity_and_source_hash_required"] is True
    assert updates["default_review_cadence"] == "weekly"
    assert updates["source_change_creates"] == "observation_or_skill_candidate"
    assert updates["source_change_auto_installs_dependency"] is False
    assert updates["source_change_auto_changes_adoption_decision"] is False
    assert updates["source_change_auto_changes_business_gate"] is False
