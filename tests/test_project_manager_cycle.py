from decimal import Decimal

from apps.control_plane.economic_guard_service import EconomicGuardInput, evaluate_economic_guard
from apps.control_plane.project_manager_cycle import ProjectManagerCycleInput, run_project_manager_cycle


def _graph():
    return {
        "scope": {"tenant_ref": "t1", "entity_ref": "e1", "store_ref": "s1"},
        "nodes": [
            {"id": "proof-a", "layer": "theorem", "state": "PROVEN"},
            {"id": "business-a", "layer": "business", "state": "BLOCKED", "depends_on": ["proof-a"]},
        ],
        "edges": [{"id": "edge-1", "source": "proof-a", "target": "business-a", "relation": "depends_on"}],
    }


def test_pm_cycle_returns_standard_result_and_fails_closed_for_missing_snapshots():
    result = run_project_manager_cycle(
        ProjectManagerCycleInput(
            project_id="p1",
            head="abc",
            graph=_graph(),
            economic_guard=evaluate_economic_guard(EconomicGuardInput(cash_available=Decimal("100"))),
            evidence_fresh=True,
            data_quality_valid=True,
            external_readback_passed=True,
            rollback_available=True,
            changed_files=("apps/control_plane/x.py",),
            proof_refs=("proof-1",),
        )
    )
    assert result["decision"]["status"] == "hold"
    assert "head_unverified" in result["decision"]["reasons"]
    assert result["dispatch_allowed"] is False
    assert result["task_result"]["changed_files"] == ["apps/control_plane/x.py"]
    assert result["external_write_allowed"] is False


def test_pm_cycle_can_dispatch_only_when_all_required_snapshots_are_current():
    result = run_project_manager_cycle(
        ProjectManagerCycleInput(
            project_id="p1",
            head="abc",
            graph={"nodes": [{"id": "proof-a", "layer": "theorem", "state": "PROVEN"}], "edges": []},
            economic_guard=evaluate_economic_guard(EconomicGuardInput(cash_available=Decimal("100"))),
            evidence_fresh=True,
            data_quality_valid=True,
            external_readback_passed=True,
            rollback_available=True,
            head_verified=True,
            workspace_state_known=True,
            workspace_clean=True,
            task_queue_known=True,
                lease_snapshot_known=True,
                test_receipts_current=True,
                proof_receipts_current=True,
                experiment_clear=True,
            )
    )
    assert result["decision"]["status"] == "dispatch"
    assert result["dispatch_allowed"] is True
