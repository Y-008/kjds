"""Pure project-manager heartbeat decisions.

The heartbeat reads immutable observations and returns a decision; persistence,
leases and external execution remain owned by the existing control plane.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from .economic_guard_service import EconomicGuardResult
from .stuck_task_detector import StuckTask

_GIT_OBJECT_ID = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class GitWorktreeObservation:
    """A server-owned, read-only observation of the running source checkout.

    The heartbeat request may carry a claimed ``head`` and legacy boolean
    attestations, but those values are not evidence.  The API boundary calls
    :func:`observe_server_git_worktree` and derives its operational flags from
    this object.  A failed command is represented explicitly as ``blocked``;
    callers must never turn an unavailable Git probe into a healthy default.
    """

    status: Literal["observed", "blocked"]
    head: str | None
    worktree_clean: bool | None
    status_sha256: str | None
    observed_at: datetime
    reason: str | None = None
    snapshot_sha256: str = ""

    def __post_init__(self) -> None:
        observed = self.observed_at
        if observed.tzinfo is None:
            raise ValueError("Git observation timestamp must include timezone")
        normalized_head = self.head.lower().strip() if isinstance(self.head, str) else None
        if normalized_head is not None and not _GIT_OBJECT_ID.fullmatch(normalized_head):
            raise ValueError("Git observation head must be a full object ID")
        if self.status not in {"observed", "blocked"}:
            raise ValueError("Git observation status is invalid")
        if self.status == "observed":
            if normalized_head is None or self.worktree_clean is None:
                raise ValueError("Observed Git state requires head and worktree state")
            if not isinstance(self.worktree_clean, bool):
                raise ValueError("Observed worktree state must be boolean")
            if not isinstance(self.status_sha256, str) or not _is_sha256(self.status_sha256):
                raise ValueError("Observed Git status requires a SHA-256 digest")
        else:
            if self.reason is None or not self.reason.strip():
                raise ValueError("Blocked Git observation requires a reason")
        expected = _git_observation_hash(
            status=self.status,
            head=normalized_head,
            worktree_clean=self.worktree_clean,
            status_sha256=self.status_sha256,
            observed_at=observed.astimezone(UTC).isoformat(),
            reason=self.reason,
        )
        if self.snapshot_sha256 and self.snapshot_sha256 != expected:
            raise ValueError("Git observation snapshot digest is invalid")
        object.__setattr__(self, "head", normalized_head)
        object.__setattr__(self, "observed_at", observed.astimezone(UTC))
        object.__setattr__(self, "status_sha256", self.status_sha256.lower() if self.status_sha256 else None)
        object.__setattr__(self, "snapshot_sha256", expected)

    @property
    def available(self) -> bool:
        return self.status == "observed"

    def flags_for(self, claimed_head: str) -> dict[str, bool]:
        """Derive heartbeat flags from this observation, never from caller claims."""

        claimed = claimed_head.strip().lower()
        return {
            "head_verified": self.available and self.head == claimed,
            "workspace_state_known": self.available,
            "workspace_clean": self.available and self.worktree_clean is True,
        }


def observe_server_git_worktree(
    repository_root: str | Path | None = None,
    *,
    observed_at: datetime | None = None,
    timeout_seconds: float = 2.0,
    runner: Callable[..., Any] | None = None,
) -> GitWorktreeObservation:
    """Read the server checkout's HEAD and porcelain state without mutation.

    ``runner`` is injectable for deterministic contract tests.  The default
    uses argument arrays and ``shell=False`` so a repository path or Git output
    can never become shell code.  Only the exact command failures are exposed
    as stable reason codes; stderr is intentionally not returned.
    """

    now = observed_at or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("observed_at must include timezone")
    now = now.astimezone(UTC)
    if timeout_seconds <= 0 or timeout_seconds > 30:
        raise ValueError("timeout_seconds must be between 0 and 30")
    root = _resolve_repository_root(repository_root)
    if root is None:
        return _blocked_git_observation(now, "repository_root_unavailable")
    execute = runner or subprocess.run
    try:
        head_result = execute(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=str(root),
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        status_result = execute(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=str(root),
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        # Re-read HEAD after the worktree probe.  A checkout switch during the
        # two commands would otherwise pair a new commit with an old status
        # listing and let an inconsistent snapshot influence dispatch.
        head_after_result = execute(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=str(root),
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        return _blocked_git_observation(now, "git_probe_failed")
    if getattr(head_result, "returncode", 1) != 0:
        return _blocked_git_observation(now, "git_head_probe_failed")
    if getattr(status_result, "returncode", 1) != 0:
        return _blocked_git_observation(now, "git_worktree_probe_failed")
    head = str(getattr(head_result, "stdout", "") or "").strip().lower()
    head_after = str(getattr(head_after_result, "stdout", "") or "").strip().lower()
    if not _GIT_OBJECT_ID.fullmatch(head):
        return _blocked_git_observation(now, "git_head_invalid")
    if not _GIT_OBJECT_ID.fullmatch(head_after):
        return _blocked_git_observation(now, "git_head_invalid")
    if head_after != head:
        return _blocked_git_observation(now, "git_state_changed_during_probe")
    status_text = str(getattr(status_result, "stdout", "") or "")
    status_sha256 = hashlib.sha256(status_text.encode("utf-8")).hexdigest()
    return GitWorktreeObservation(
        status="observed",
        head=head,
        worktree_clean=status_text == "",
        status_sha256=status_sha256,
        observed_at=now,
    )


def _resolve_repository_root(value: str | Path | None) -> Path | None:
    candidate = value or os.getenv("KJDS_SOURCE_ROOT")
    root = Path(candidate) if candidate else Path(__file__).resolve().parents[2]
    try:
        root = root.expanduser().resolve()
    except (OSError, RuntimeError):
        return None
    return root if root.is_dir() else None


def _blocked_git_observation(observed_at: datetime, reason: str) -> GitWorktreeObservation:
    return GitWorktreeObservation(
        status="blocked",
        head=None,
        worktree_clean=None,
        status_sha256=None,
        observed_at=observed_at,
        reason=reason,
    )


def _is_sha256(value: str) -> bool:
    return len(value.strip()) == 64 and all(char in "0123456789abcdefABCDEF" for char in value.strip())


def _git_observation_hash(
    *,
    status: str,
    head: str | None,
    worktree_clean: bool | None,
    status_sha256: str | None,
    observed_at: str,
    reason: str | None,
) -> str:
    payload = {
        "contract_id": "kjds-server-git-observation-v1",
        "status": status,
        "head": head,
        "worktree_clean": worktree_clean,
        "status_sha256": status_sha256.lower() if status_sha256 else None,
        "observed_at": observed_at,
        "reason": reason,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


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
    # Reasons emitted by an API boundary when a caller claim has no
    # server-owned authority behind it.  Keeping these separate from the
    # boolean gates lets the pure evaluator remain backwards compatible while
    # making an unverified production request auditable and replayable.
    authority_reasons: tuple[str, ...] = ()


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
    reasons.extend(
        reason.strip()
        for reason in values.authority_reasons
        if isinstance(reason, str) and reason.strip()
    )
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


__all__ = [
    "GitWorktreeObservation",
    "HeartbeatDecision",
    "HeartbeatInput",
    "evaluate_heartbeat",
    "observe_server_git_worktree",
]
