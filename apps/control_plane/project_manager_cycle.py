"""One deterministic, replayable project-manager control-plane cycle."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from .autonomous_pm_heartbeat import HeartbeatInput, evaluate_heartbeat
from .economic_guard_service import EconomicGuardResult
from .proof_frontier_planner import plan_proof_frontier
from .stuck_task_detector import StuckTask
from .team_agent_result_contract import normalize_team_agent_result

TASK_RESULT_FIELDS = (
    "changed_files",
    "proof_refs",
    "evidence_refs",
    "test_receipts",
    "new_blockers",
    "invalidated_nodes",
    "economic_impact",
    "rollback_ref",
    "next_dependencies",
)


def normalize_task_result(value: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Normalize the PM's standard result envelope.

    The PM heartbeat and TeamAgent terminal result must use one shape so a
    result can be persisted, replayed and handed to the next dependency
    without an adapter silently dropping evidence.  The generic TeamAgent
    result scanner remains the authority for secret/authority rejection;
    this helper adds the bounded, explicit PM fields and deterministic empty
    defaults.
    """

    if value is None:
        source: Mapping[str, Any] = {}
    elif isinstance(value, Mapping):
        source = value
    else:
        raise ValueError("task_result must be an object")

    # JSON requests normally arrive as primitive values. ``default=str``
    # keeps direct Python callers deterministic for Decimal-like values while
    # still rejecting NaN/Infinity through the canonical scanner below.
    import json

    try:
        canonical_source = json.loads(
            json.dumps(
                dict(source),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
                allow_nan=False,
            )
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("task_result must be canonical JSON") from exc
    normalized = normalize_team_agent_result(canonical_source)
    unknown = sorted(set(normalized) - set(TASK_RESULT_FIELDS))
    if unknown:
        raise ValueError(
            "task_result contains unsupported fields: " + ", ".join(unknown)
        )

    result: dict[str, Any] = {
        "changed_files": [],
        "proof_refs": [],
        "evidence_refs": [],
        "test_receipts": [],
        "new_blockers": [],
        "invalidated_nodes": [],
        "economic_impact": None,
        "rollback_ref": None,
        "next_dependencies": [],
    }
    list_fields = {
        "changed_files",
        "proof_refs",
        "evidence_refs",
        "test_receipts",
        "invalidated_nodes",
        "next_dependencies",
    }
    for field in list_fields:
        if field not in normalized:
            continue
        raw = normalized[field]
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
            raise ValueError(f"task_result.{field} must be an array")
        if len(raw) > 200:
            raise ValueError(f"task_result.{field} exceeds 200 items")
        values = []
        for item in raw:
            if not isinstance(item, str) or not item.strip() or len(item) > 1000:
                raise ValueError(f"task_result.{field} must contain bounded strings")
            values.append(item.strip())
        if len(values) != len(set(values)):
            raise ValueError(f"task_result.{field} values must be unique")
        result[field] = values

    if "new_blockers" in normalized:
        blockers = normalized["new_blockers"]
        if not isinstance(blockers, Sequence) or isinstance(
            blockers, (str, bytes, bytearray)
        ):
            raise ValueError("task_result.new_blockers must be an array")
        if len(blockers) > 200:
            raise ValueError("task_result.new_blockers exceeds 200 items")
        result["new_blockers"] = list(blockers)

    if "economic_impact" in normalized:
        impact = normalized["economic_impact"]
        if impact is not None and not isinstance(impact, (str, int, float)):
            raise ValueError("task_result.economic_impact must be a scalar")
        result["economic_impact"] = impact

    if "rollback_ref" in normalized:
        ref = normalized["rollback_ref"]
        if ref is not None and (
            not isinstance(ref, str) or not ref.strip() or len(ref) > 1000
        ):
            raise ValueError("task_result.rollback_ref must be a bounded string")
        result["rollback_ref"] = ref.strip() if isinstance(ref, str) else ref

    return result


@dataclass(frozen=True, slots=True)
class ProjectManagerCycleInput:
    project_id: str
    head: str
    graph: dict[str, Any]
    economic_guard: EconomicGuardResult
    evidence_fresh: bool
    data_quality_valid: bool
    external_readback_passed: bool
    rollback_available: bool
    head_verified: bool = False
    workspace_state_known: bool = False
    workspace_clean: bool = False
    task_queue_known: bool = False
    lease_snapshot_known: bool = False
    test_receipts_current: bool = False
    proof_receipts_current: bool = False
    experiment_clear: bool = True
    stuck_tasks: tuple[StuckTask, ...] = ()
    changed_files: tuple[str, ...] = ()
    proof_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    test_receipts: tuple[str, ...] = ()
    rollback_ref: str | None = None
    economic_impact: Decimal | None = None


def run_project_manager_cycle(values: ProjectManagerCycleInput) -> dict[str, Any]:
    """Return the PM decision and standard Agent result without side effects."""

    if not values.project_id.strip() or not values.head.strip():
        raise ValueError("project_id and head are required")
    projection = plan_proof_frontier(values.graph)
    decision = evaluate_heartbeat(
        HeartbeatInput(
            head=values.head,
            graph_snapshot_sha256=projection["snapshot_sha256"],
            proof_ready=projection["status"] == "PROVEN",
            evidence_fresh=values.evidence_fresh,
            data_quality_valid=values.data_quality_valid,
            external_readback_passed=values.external_readback_passed,
            rollback_available=values.rollback_available,
            economic_guard=values.economic_guard,
            experiment_clear=values.experiment_clear,
            stuck_tasks=values.stuck_tasks,
            head_verified=values.head_verified,
            workspace_state_known=values.workspace_state_known,
            workspace_clean=values.workspace_clean,
            task_queue_known=values.task_queue_known,
            lease_snapshot_known=values.lease_snapshot_known,
            test_receipts_current=values.test_receipts_current,
            proof_receipts_current=values.proof_receipts_current,
        )
    )
    blockers = list(projection.get("blockers", ()))
    blockers.extend(
        {
            "task_ref": item.task_ref,
            "reasons": list(item.reasons),
            "compensation_action": item.compensation_action,
            "recovery_ref": item.recovery_ref,
        }
        for item in values.stuck_tasks
        if item.status == "stuck"
    )
    task_result = normalize_task_result(
        {
            "changed_files": list(values.changed_files),
            "proof_refs": list(values.proof_refs),
            "evidence_refs": list(values.evidence_refs),
            "test_receipts": list(values.test_receipts),
            "new_blockers": blockers,
            "invalidated_nodes": list(
                (projection.get("invalidations") or {}).keys()
                if isinstance(projection.get("invalidations"), Mapping)
                else projection.get("invalidations", [])
            ),
            "economic_impact": (
                str(values.economic_impact)
                if values.economic_impact is not None
                else None
            ),
            "rollback_ref": values.rollback_ref,
            "next_dependencies": list(projection.get("frontier_ids", [])),
        }
    )
    return {
        "contract_id": "kjds-project-manager-cycle-v1",
        "project_id": values.project_id,
        "head": values.head,
        "graph_snapshot_sha256": projection["snapshot_sha256"],
        "decision": {
            "status": decision.status,
            "reasons": list(decision.reasons),
            "next_actions": list(decision.next_actions),
            "recovery_actions": list(decision.recovery_actions),
            "decision_sha256": decision.decision_sha256,
        },
        "proof_frontier": projection,
        "task_result": task_result,
        "dispatch_allowed": decision.status == "dispatch",
        "external_write_allowed": False,
    }


__all__ = [
    "TASK_RESULT_FIELDS",
    "ProjectManagerCycleInput",
    "normalize_task_result",
    "run_project_manager_cycle",
]
