"""Pure project-manager heartbeat decisions.

The heartbeat reads immutable observations and returns a decision; persistence,
leases and external execution remain owned by the existing control plane.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal

from .economic_guard_service import EconomicGuardResult
from .stuck_task_detector import StuckTask


@dataclass(frozen=True, slots=True)
class HeartbeatInput:
    head: str
    graph_snapshot_sha256: str
    proof_ready: bool
    evidence_fresh: bool
    data_quality_valid: bool
    external_readback_passed: bool
    rollback_available: bool
    economic_guard: EconomicGuardResult
    # Missing experiment isolation evidence must hold unattended dispatch.
    experiment_clear: bool = False
    stuck_tasks: tuple[StuckTask, ...] = ()
    # A heartbeat is an admission check for unattended work.  These fields are
    # explicit because a caller must not turn a missing checkout/queue/lease
    # observation into an implicit healthy value.  The defaults preserve the
    # pure evaluator's historical call shape while failing closed for new API
    # callers that omit operational snapshots.
    head_verified: bool = False
    workspace_state_known: bool = False
    workspace_clean: bool = False
    task_queue_known: bool = False
    lease_snapshot_known: bool = False
    test_receipts_current: bool = False
    proof_receipts_current: bool = False


@dataclass(frozen=True, slots=True)
class HeartbeatDecision:
    status: Literal["dispatch", "hold", "isolate"]
    reasons: tuple[str, ...]
    next_actions: tuple[str, ...]
    recovery_actions: tuple[str, ...] = ()
    decision_sha256: str = ""


def evaluate_heartbeat(values: HeartbeatInput) -> HeartbeatDecision:
    reasons: list[str] = []
    actions: list[str] = []
    recovery_actions: list[str] = []
    if any(item.status == "stuck" for item in values.stuck_tasks):
        reasons.append("stuck_tasks_detected")
        actions.append("isolate_and_recover_stuck_tasks")
        recovery_actions.extend(
            item.compensation_action
            for item in values.stuck_tasks
            if item.status == "stuck" and item.compensation_action
        )
    if not values.proof_ready:
        reasons.append("proof_not_ready")
    if not values.evidence_fresh:
        reasons.append("evidence_stale")
    if not values.data_quality_valid:
        reasons.append("data_quality_invalid")
    if not values.external_readback_passed:
        reasons.append("external_readback_not_passed")
    if not values.rollback_available:
        reasons.append("rollback_missing")
    if not values.head_verified:
        reasons.append("head_unverified")
    if not values.workspace_state_known:
        reasons.append("workspace_state_unknown")
    elif not values.workspace_clean:
        reasons.append("workspace_dirty")
    if not values.task_queue_known:
        reasons.append("task_queue_unknown")
    if not values.lease_snapshot_known:
        reasons.append("lease_snapshot_unknown")
    if not values.test_receipts_current:
        reasons.append("test_receipts_stale")
    if not values.proof_receipts_current:
        reasons.append("proof_receipts_stale")
    if not values.experiment_clear:
        reasons.append("experiment_contamination_detected")
        actions.append("pause_overlapping_experiments")
    if values.economic_guard.status == "blocked":
        reasons.extend(values.economic_guard.reasons)
        actions.append("switch_to_read_only")
    if reasons:
        status: Literal["dispatch", "hold", "isolate"] = (
            "isolate"
            if values.external_readback_passed is False
            or any(item.status == "stuck" for item in values.stuck_tasks)
            else "hold"
        )
        if not actions:
            actions.append("recompute_frontier")
        deduped_reasons = tuple(dict.fromkeys(reasons))
        deduped_actions = tuple(dict.fromkeys(actions))
        deduped_recovery = tuple(dict.fromkeys(recovery_actions))
        decision_sha = _decision_hash(
            status=status,
            reasons=deduped_reasons,
            next_actions=deduped_actions,
            recovery_actions=deduped_recovery,
        )
        return HeartbeatDecision(
            status=status,
            reasons=deduped_reasons,
            next_actions=deduped_actions,
            recovery_actions=deduped_recovery,
            decision_sha256=decision_sha,
        )
    decision = HeartbeatDecision(
        status="dispatch",
        reasons=(),
        next_actions=("compute_frontier", "dispatch_dependency_free_wave"),
        recovery_actions=(),
    )
    return HeartbeatDecision(
        status=decision.status,
        reasons=decision.reasons,
        next_actions=decision.next_actions,
        recovery_actions=decision.recovery_actions,
        decision_sha256=_decision_hash(
            status=decision.status,
            reasons=decision.reasons,
            next_actions=decision.next_actions,
            recovery_actions=decision.recovery_actions,
        ),
    )


def _decision_hash(
    *,
    status: str,
    reasons: tuple[str, ...],
    next_actions: tuple[str, ...],
    recovery_actions: tuple[str, ...],
) -> str:
    payload = {
        "contract_id": "kjds-autonomous-pm-heartbeat-v2",
        "status": status,
        "reasons": list(reasons),
        "next_actions": list(next_actions),
        "recovery_actions": list(recovery_actions),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


__all__ = ["HeartbeatDecision", "HeartbeatInput", "evaluate_heartbeat"]
