from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

from apps.control_plane.proof_frontier_planner import (
    BLOCKED,
    NO_DATA,
    PROVEN,
    STALE,
    classify_node,
    classify_state,
    critical_path,
    critical_path_detail,
    find_blockers,
    plan_proof_frontier,
    proof_frontier,
    propagate_invalidation,
    snapshot_graph,
)

NOW = datetime(2026, 9, 6, 0, 0, tzinfo=UTC)


def test_four_state_classification_is_explicit_and_time_aware() -> None:
    assert classify_state("passed") == PROVEN
    assert classify_state("partial") == NO_DATA
    assert classify_state("unknown_outcome") == NO_DATA
    assert classify_state("invalidated") == BLOCKED
    assert classify_state("expired") == STALE
    assert classify_state({"state": "passed", "fresh_until": NOW - timedelta(seconds=1)}, as_of=NOW) == STALE
    assert classify_state({"state": "passed", "fresh_until": NOW + timedelta(seconds=1)}, as_of=NOW) == PROVEN


def _two_layer_graph() -> dict:
    return {
        "graph_id": "commerce-proof-v1",
        "as_of": NOW.isoformat(),
        "theorem_nodes": [
            {"id": "th-root", "layer": "theorem", "state": "passed", "label": "scope proved"},
            {"id": "th-listing", "layer": "theorem", "state": "no_data", "label": "listing is eligible"},
            {"id": "th-order", "layer": "theorem", "state": "no_data", "label": "order is reconciled"},
        ],
        "business_nodes": [
            {
                "id": "biz-content",
                "layer": "business",
                "state": "no_data",
                "dependencies": ["th-root"],
                "weight": 2,
                "priority": 3,
            },
            {
                "id": "biz-fulfil",
                "layer": "business",
                "state": "no_data",
                "dependencies": ["th-listing"],
                "weight": 4,
                "priority": 1,
            },
        ],
        "edges": [
            {"id": "e-content-proves", "source": "biz-content", "target": "th-listing", "relation": "proves"},
            {"id": "e-fulfil-proves", "source": "biz-fulfil", "target": "th-order", "relation": "proves"},
        ],
    }


def test_frontier_only_contains_next_proof_work_and_keeps_layers() -> None:
    graph = _two_layer_graph()
    result = plan_proof_frontier(graph)

    assert result["status"] == NO_DATA
    assert result["frontier_ids"] == ["biz-content"]
    assert result["theorem"]["status"] == NO_DATA
    assert result["business"]["status"] == NO_DATA
    assert result["states"]["th-listing"] == NO_DATA
    assert result["states"]["th-order"] == NO_DATA
    assert result["frontier"][0]["frontier_kind"] == "prove"
    assert result["external_write_allowed"] is False
    assert proof_frontier(graph) == ["biz-content"]
    assert proof_frontier(graph, detailed=True)[0]["id"] == "biz-content"


def test_proves_edge_is_reversed_into_theorem_dependency() -> None:
    graph = _two_layer_graph()
    graph["business_nodes"][0]["state"] = "passed"
    result = plan_proof_frontier(graph)

    assert result["states"]["th-listing"] == PROVEN
    assert result["frontier_ids"] == ["biz-fulfil"]
    assert all(item["id"] != "biz-content" for item in result["blockers"])


def test_invalidation_propagates_transitively_without_mutating_input() -> None:
    graph = {
        "nodes": [
            {"id": "source", "state": "passed"},
            {"id": "middle", "state": "passed"},
            {"id": "leaf", "state": "passed"},
        ],
        "edges": [
            {"source": "source", "target": "middle", "relation": "invalidates"},
            {"source": "middle", "target": "leaf", "relation": "precedes"},
        ],
    }
    before = deepcopy(graph)
    projection = plan_proof_frontier(graph)

    assert projection["states"] == {"leaf": BLOCKED, "middle": BLOCKED, "source": PROVEN}
    assert (propagation := propagate_invalidation(graph))
    assert propagation["middle"]["causes"] == ["source"]
    assert propagation["leaf"]["causes"] == ["middle"]
    assert graph == before


def test_blockers_explain_missing_dependencies_and_graph_errors() -> None:
    graph = {
        "nodes": [{"id": "a", "state": "no_data"}, {"id": "b", "state": "passed", "dependencies": ["missing"]}],
        "edges": [{"id": "bad", "source": "a", "target": "b", "relation": "mystery"}],
    }
    result = plan_proof_frontier(graph)

    assert result["status"] == BLOCKED
    assert "missing_node_reference:b:missing" in result["graph_errors"]
    assert any(item["id"] == "__graph__" for item in find_blockers(graph))
    assert result["states"]["b"] == BLOCKED


def test_critical_path_is_deterministic_and_prefers_weighted_unresolved_leaf() -> None:
    graph = {
        "nodes": [
            {"id": "root", "state": "passed", "weight": 1},
            {"id": "short", "state": "no_data", "dependencies": ["root"], "weight": 1},
            {"id": "long", "state": "no_data", "dependencies": ["root"], "weight": 5},
            {"id": "tail", "state": "no_data", "dependencies": ["long"], "weight": 2},
        ]
    }
    detail = critical_path_detail(graph)

    assert detail["target_id"] == "tail"
    assert detail["node_ids"] == ["root", "long", "tail"]
    assert critical_path(graph) == detail["node_ids"]
    assert detail["weight"] == 8.0


def test_cycle_is_blocked_and_snapshot_is_order_independent() -> None:
    first = {
        "nodes": [
            {"id": "b", "state": "passed", "dependencies": ["a"]},
            {"id": "a", "state": "passed", "dependencies": ["b"]},
        ]
    }
    second = {"nodes": list(reversed(first["nodes"]))}

    result = plan_proof_frontier(first)
    assert result["status"] == BLOCKED
    assert result["cycles"] == [["a", "b", "a"]]
    assert result["states"]["a"] == BLOCKED
    assert result["states"]["b"] == BLOCKED
    assert snapshot_graph(first)["snapshot_sha256"] == snapshot_graph(second)["snapshot_sha256"]


def test_existing_harness_tasks_and_verification_shape_is_consumable() -> None:
    graph = {
        "as_of": NOW.isoformat(),
        "nodes": [
            {"id": "node-code", "kind": "code", "verification": {"state": "passed"}},
            {"id": "node-web", "kind": "code", "verification": {"state": "pending"}},
        ],
        "tasks": [
            {"id": "task-web", "state": "pending", "dependencies": ["task-code"]},
            {"id": "task-code", "state": "passed", "dependencies": []},
        ],
        "edges": [],
    }
    result = plan_proof_frontier(graph)

    assert result["states"]["task-web"] == NO_DATA
    assert result["states"]["task-code"] == PROVEN
    assert "task-web" in result["frontier_ids"]


def test_four_state_admission_is_projected_and_live_only_when_all_gates_pass() -> None:
    graph = {
        "nodes": [
            {
                "id": "repricing",
                "proof_state": "PROVED",
                "evidence_state": "VALID",
                "operational_state": "LIVE",
                "economic_state": "ALLOWED",
                "rollback_available": True,
            }
        ]
    }

    result = plan_proof_frontier(graph)
    node = result["nodes"][0]

    assert result["states"] == {"repricing": PROVEN}
    assert result["admission_states"] == {"repricing": "LIVE"}
    assert node["admission_state"] == "LIVE"
    assert node["proof_state"] == "PROVED"
    assert node["evidence_state"] == "VALID"
    assert node["operational_state"] == "LIVE"
    assert node["economic_state"] == "ALLOWED"
    assert node["rollback_available"] is True
    assert snapshot_graph(graph)["nodes"][0]["admission_state"] == "LIVE"
    assert classify_node(graph["nodes"][0])["state"] == PROVEN


def test_four_state_failures_cannot_be_promoted_to_proven_or_live() -> None:
    graph = {
        "nodes": [
            {
                "id": "stale-evidence",
                "proof_state": "PROVED",
                "evidence_state": "STALE",
                "operational_state": "LIVE",
                "economic_state": "ALLOWED",
                "rollback_available": True,
            },
            {
                "id": "unknown-readback",
                "proof_state": "PROVED",
                "evidence_state": "UNKNOWN_OUTCOME",
                "operational_state": "LIVE",
                "economic_state": "ALLOWED",
                "rollback_available": True,
            },
            {
                "id": "no-rollback",
                "proof_state": "PROVED",
                "evidence_state": "VALID",
                "operational_state": "LIVE",
                "economic_state": "ALLOWED",
                "rollback_available": False,
            },
            {"id": "incomplete", "proof_state": "PROVED"},
        ]
    }

    result = plan_proof_frontier(graph)
    by_id = {item["id"]: item for item in result["nodes"]}

    assert result["states"]["stale-evidence"] == STALE
    assert result["states"]["unknown-readback"] == NO_DATA
    assert result["states"]["no-rollback"] == BLOCKED
    assert result["states"]["incomplete"] == NO_DATA
    assert all(state != PROVEN for state in result["states"].values())
    assert by_id["stale-evidence"]["admission_state"] == "BLOCKED"
    assert by_id["unknown-readback"]["admission_state"] == "UNKNOWN_OUTCOME"
    assert by_id["no-rollback"]["admission_state"] == "BLOCKED"
    assert by_id["incomplete"]["admission_state"] == "HOLD"
    assert "evidence_state_stale" in by_id["stale-evidence"]["reasons"]
    assert "rollback_missing" in by_id["no-rollback"]["reasons"]
    assert "economic_state_missing" in by_id["incomplete"]["reasons"]
    assert all(item["admission_state"] != "LIVE" for item in by_id.values())


def test_governance_hold_survives_proof_dependency_propagation() -> None:
    graph = {
        "nodes": [
            {"id": "proof", "state": "passed"},
            {
                "id": "gated",
                "proof_state": "PROVED",
                "dependencies": ["proof"],
            },
        ],
        "edges": [{"source": "proof", "target": "gated", "relation": "proves"}],
    }

    result = plan_proof_frontier(graph)

    assert result["states"]["proof"] == PROVEN
    assert result["states"]["gated"] == NO_DATA
    gated = next(item for item in result["nodes"] if item["id"] == "gated")
    assert gated["admission_state"] == "HOLD"
    assert "evidence_state_missing" in gated["reasons"]


def test_explicit_direct_staleness_also_downgrades_green_admission() -> None:
    graph = {
        "nodes": [
            {
                "id": "expired",
                "state": "stale",
                "proof_state": "PROVED",
                "evidence_state": "VALID",
                "operational_state": "LIVE",
                "economic_state": "ALLOWED",
                "rollback_available": True,
            }
        ]
    }

    result = plan_proof_frontier(graph)
    node = result["nodes"][0]

    assert result["states"]["expired"] == STALE
    assert node["admission_state"] == "BLOCKED"
    assert snapshot_graph(graph)["nodes"][0]["admission_state"] == "BLOCKED"


def test_legacy_nodes_keep_the_original_projection_shape() -> None:
    graph = {"nodes": [{"id": "legacy", "state": "passed"}]}

    result = plan_proof_frontier(graph)
    node = result["nodes"][0]

    assert result["states"] == {"legacy": PROVEN}
    assert "admission_state" not in node
    assert "admission_states" not in result
