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
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from .economic_guard_service import EconomicGuardResult
from .stuck_task_detector import StuckTask

_GIT_OBJECT_ID = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$", re.IGNORECASE)
_SHA256 = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)

# These are the server-side facts that a project-manager heartbeat must read
# before it can produce a dispatchable input.  The names intentionally match
# the control-plane vocabulary rather than request-field names: a request may
# claim ``evidence_fresh=True``, but only the corresponding server observation
# can make the claim effective.
SERVER_AUTHORITY_FIELDS: tuple[str, ...] = (
    "task_queue",
    "lease_snapshot",
    "test_receipts",
    "proof_receipts",
    "evidence",
    "data_quality",
    "external_readback",
    "rollback",
    "experiment",
)
_SERVER_AUTHORITY_ALIASES: dict[str, tuple[str, ...]] = {
    "task_queue": ("queue",),
    "lease_snapshot": ("leases", "lease"),
    "test_receipts": ("tests",),
    "proof_receipts": ("proof", "proofs"),
    "external_readback": ("readback",),
}
_AUTHORITY_STATES = frozenset({"valid", "partial", "stale", "blocked", "unknown"})
_SERVER_SOURCE_PREFIX = "server://"


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


def _stable_hash(payload: Any) -> str:
    """Return the canonical digest used by server observation contracts."""

    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _utc_datetime(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{field} must include timezone")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class AuthorityObservation:
    """One server-owned, scope-bound observation used by the PM heartbeat.

    A boolean in a request is a claim.  This object is the smallest accepted
    authority unit: it carries a bounded source reference, the source payload
    digest, the observation time and (optionally) an expiry.  The source URI is
    deliberately required to use ``server://`` so a caller cannot accidentally
    pass a client diagnostic as an operational fact.
    """

    name: str
    status: Literal["valid", "partial", "stale", "blocked", "unknown"]
    scope_key: str
    observed_at: datetime
    source_ref: str
    payload_sha256: str
    expires_at: datetime | None = None
    reason: str | None = None
    snapshot_sha256: str = ""

    def __post_init__(self) -> None:
        name = self.name.strip() if isinstance(self.name, str) else ""
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name):
            raise ValueError("authority observation name is invalid")
        status = self.status.strip().lower() if isinstance(self.status, str) else ""
        if status not in _AUTHORITY_STATES:
            raise ValueError("authority observation status is invalid")
        scope_key = self.scope_key.strip() if isinstance(self.scope_key, str) else ""
        if not scope_key or len(scope_key) > 500:
            raise ValueError("authority observation scope_key is required and bounded")
        observed_at = _utc_datetime(self.observed_at, "authority observation observed_at")
        source_ref = self.source_ref.strip() if isinstance(self.source_ref, str) else ""
        if (
            not source_ref
            or len(source_ref) > 500
            or not source_ref.startswith(_SERVER_SOURCE_PREFIX)
        ):
            raise ValueError("authority observation source_ref must be server-owned")
        payload_sha256 = self.payload_sha256.strip().lower() if isinstance(self.payload_sha256, str) else ""
        if not _SHA256.fullmatch(payload_sha256):
            raise ValueError("authority observation payload_sha256 is invalid")
        expires_at = (
            _utc_datetime(self.expires_at, "authority observation expires_at")
            if self.expires_at is not None
            else None
        )
        if expires_at is not None and expires_at < observed_at:
            raise ValueError("authority observation expires_at precedes observed_at")
        reason = self.reason.strip() if isinstance(self.reason, str) and self.reason.strip() else None
        if status in {"blocked", "unknown"} and reason is None:
            raise ValueError("blocked or unknown authority observation requires a reason")
        expected = _authority_observation_hash(
            name=name,
            status=status,
            scope_key=scope_key,
            observed_at=observed_at.isoformat(),
            source_ref=source_ref,
            payload_sha256=payload_sha256,
            expires_at=expires_at.isoformat() if expires_at is not None else None,
            reason=reason,
        )
        supplied = self.snapshot_sha256.strip().lower() if isinstance(self.snapshot_sha256, str) else ""
        if supplied and supplied != expected:
            raise ValueError("authority observation snapshot digest is invalid")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "scope_key", scope_key)
        object.__setattr__(self, "observed_at", observed_at)
        object.__setattr__(self, "source_ref", source_ref)
        object.__setattr__(self, "payload_sha256", payload_sha256)
        object.__setattr__(self, "expires_at", expires_at)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "snapshot_sha256", expected)

    @property
    def state(self) -> str:
        """Alias used by callers that model the four-state truth graph."""

        return self.status

    def is_current(self, as_of: datetime) -> bool:
        """Whether this server observation is valid at the requested time."""

        current = _utc_datetime(as_of, "authority observation as_of")
        return (
            self.status == "valid"
            and self.observed_at <= current
            and (self.expires_at is None or current <= self.expires_at)
        )

    def failure_reason(self, as_of: datetime) -> str | None:
        """Return a stable, non-secret reason when the observation is unusable."""

        current = _utc_datetime(as_of, "authority observation as_of")
        if self.status != "valid":
            if self.status == "blocked" and self.reason in {
                "reader_unavailable",
                "reader_failed",
            }:
                return f"server_observation_unavailable:{self.name}"
            return f"server_observation_{self.status}:{self.name}"
        if self.observed_at > current:
            return f"server_observation_future:{self.name}"
        if self.expires_at is not None and current > self.expires_at:
            return f"server_observation_stale:{self.name}"
        return None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "scope_key": self.scope_key,
            "observed_at": self.observed_at.isoformat(),
            "source_ref": self.source_ref,
            "payload_sha256": self.payload_sha256,
            "expires_at": self.expires_at.isoformat() if self.expires_at is not None else None,
            "reason": self.reason,
            "snapshot_sha256": self.snapshot_sha256,
        }


@dataclass(frozen=True, slots=True)
class ServerEconomicGuardRead:
    """A server economic guard plus the freshness receipt for that guard."""

    guard: EconomicGuardResult
    observation: AuthorityObservation

    def __post_init__(self) -> None:
        if not isinstance(self.guard, EconomicGuardResult):
            raise ValueError("economic guard read guard is invalid")
        if not isinstance(self.observation, AuthorityObservation):
            raise ValueError("economic guard read observation is invalid")
        if self.observation.name != "economic_guard":
            raise ValueError("economic guard read observation name is invalid")
        if self.observation.payload_sha256 != str(self.guard.snapshot_sha256).strip().lower():
            raise ValueError("economic guard read digest does not match observation")


def _authority_observation_hash(
    *,
    name: str,
    status: str,
    scope_key: str,
    observed_at: str,
    source_ref: str,
    payload_sha256: str,
    expires_at: str | None,
    reason: str | None,
) -> str:
    return _stable_hash(
        {
            "contract_id": "kjds-server-authority-observation-v1",
            "name": name,
            "status": status,
            "scope_key": scope_key,
            "observed_at": observed_at,
            "source_ref": source_ref,
            "payload_sha256": payload_sha256,
            "expires_at": expires_at,
            "reason": reason,
        }
    )


@dataclass(frozen=True, slots=True)
class ServerAuthoritySnapshot:
    """Immutable server observation bundle consumed by one PM heartbeat.

    ``readers`` in :func:`observe_server_authority` are server-side adapters;
    their return values are normalized into this bundle before any heartbeat
    boolean is derived.  A missing, stale, malformed or scope-mismatched read
    is represented as a blocked observation, never as a healthy default.
    """

    scope_key: str
    observed_at: datetime
    observations: tuple[AuthorityObservation, ...]
    economic_guard: EconomicGuardResult
    economic_observation: AuthorityObservation | None = None
    git: GitWorktreeObservation | None = None
    snapshot_sha256: str = ""

    def __post_init__(self) -> None:
        scope_key = self.scope_key.strip() if isinstance(self.scope_key, str) else ""
        if not scope_key or len(scope_key) > 500:
            raise ValueError("server authority scope_key is required and bounded")
        observed_at = _utc_datetime(self.observed_at, "server authority observed_at")
        raw_observations: Any = self.observations
        if isinstance(raw_observations, Mapping):
            raw_observations = tuple(raw_observations.values())
        try:
            normalized_observations = tuple(raw_observations)
        except TypeError as exc:
            raise ValueError("server authority observations must be iterable") from exc
        by_name: dict[str, AuthorityObservation] = {}
        for item in normalized_observations:
            if not isinstance(item, AuthorityObservation):
                raise ValueError("server authority observations must use AuthorityObservation")
            if item.scope_key != scope_key:
                raise ValueError("server authority observation scope mismatch")
            if item.name in by_name:
                raise ValueError("duplicate server authority observation")
            by_name[item.name] = item
        economic_observation = self.economic_observation
        if economic_observation is not None:
            if not isinstance(economic_observation, AuthorityObservation):
                raise ValueError("economic_observation must use AuthorityObservation")
            if economic_observation.name != "economic_guard":
                raise ValueError("economic_observation name must be economic_guard")
            if economic_observation.scope_key != scope_key:
                raise ValueError("economic observation scope mismatch")
            existing_economic = by_name.get("economic_guard")
            if existing_economic is not None and existing_economic != economic_observation:
                raise ValueError("economic_guard observation must be supplied once")
            by_name["economic_guard"] = economic_observation
        elif "economic_guard" in by_name:
            economic_observation = by_name["economic_guard"]
        if not isinstance(self.economic_guard, EconomicGuardResult):
            raise ValueError("economic_guard must be an EconomicGuardResult")
        if self.economic_guard.status not in {"allowed", "blocked"}:
            raise ValueError("economic_guard status is invalid")
        if not _SHA256.fullmatch(str(self.economic_guard.snapshot_sha256).lower()):
            raise ValueError("economic_guard snapshot digest is invalid")
        if self.git is not None and not isinstance(self.git, GitWorktreeObservation):
            raise ValueError("git must be a GitWorktreeObservation")
        # Keep the economic observation in its dedicated field.  Excluding it
        # from the general tuple makes ``as_dict``/replay construction
        # idempotent and prevents a duplicate authority row.
        ordered = tuple(
            by_name[name] for name in sorted(by_name) if name != "economic_guard"
        )
        expected = _server_authority_snapshot_hash(
            scope_key=scope_key,
            observed_at=observed_at.isoformat(),
            observations=ordered,
            economic_guard=self.economic_guard,
            economic_observation=economic_observation,
            git=self.git,
        )
        supplied = self.snapshot_sha256.strip().lower() if isinstance(self.snapshot_sha256, str) else ""
        if supplied and supplied != expected:
            raise ValueError("server authority snapshot digest is invalid")
        object.__setattr__(self, "scope_key", scope_key)
        object.__setattr__(self, "observed_at", observed_at)
        object.__setattr__(self, "observations", ordered)
        object.__setattr__(self, "economic_observation", economic_observation)
        object.__setattr__(self, "snapshot_sha256", expected)

    @property
    def status(self) -> Literal["ready", "partial", "blocked"]:
        if self.git is None or not self.git.available:
            return "blocked"
        required = [self.observation(name) for name in SERVER_AUTHORITY_FIELDS]
        if any(item is None for item in required) or self.economic_observation is None:
            return "partial"
        if any(item.status in {"blocked", "unknown"} for item in required):
            return "blocked"
        if self.economic_observation.status in {"blocked", "unknown"}:
            return "blocked"
        if any(not item.is_current(self.observed_at) for item in required):
            return "partial"
        if not self.economic_observation.is_current(self.observed_at):
            return "partial"
        return "ready"

    def observation(self, name: str) -> AuthorityObservation | None:
        normalized = name.strip()
        return next((item for item in self.observations if item.name == normalized), None)

    def authority_reasons(self, *, as_of: datetime | None = None) -> tuple[str, ...]:
        current = _utc_datetime(as_of or self.observed_at, "server authority as_of")
        reasons: list[str] = []
        if self.git is None:
            reasons.append("server_observation_unavailable:git")
        elif not self.git.available:
            reasons.append(f"server_observation_{self.git.reason or 'blocked'}:git")
        elif self.git.observed_at > current:
            reasons.append("server_observation_future:git")
        for name in SERVER_AUTHORITY_FIELDS:
            item = self.observation(name)
            if item is None:
                reasons.append(f"server_observation_unavailable:{name}")
                continue
            failure = item.failure_reason(current)
            if failure:
                reasons.append(failure)
        economic = self.economic_observation
        if economic is None:
            reasons.append("server_observation_unavailable:economic_guard")
        else:
            failure = economic.failure_reason(current)
            if failure:
                reasons.append(failure)
        return tuple(dict.fromkeys(reasons))

    def as_dict(self) -> dict[str, Any]:
        """Return the complete immutable bundle for persistence or replay."""

        return {
            "contract_id": "kjds-server-authority-snapshot-v1",
            "scope_key": self.scope_key,
            "observed_at": self.observed_at.isoformat(),
            "status": self.status,
            "observations": [item.as_dict() for item in self.observations],
            "economic_observation": (
                self.economic_observation.as_dict()
                if self.economic_observation is not None
                else None
            ),
            "economic_guard": {
                "status": self.economic_guard.status,
                "reasons": list(self.economic_guard.reasons),
                "snapshot_sha256": self.economic_guard.snapshot_sha256,
            },
            "git": (
                {
                    "status": self.git.status,
                    "head": self.git.head,
                    "worktree_clean": self.git.worktree_clean,
                    "status_sha256": self.git.status_sha256,
                    "observed_at": self.git.observed_at.isoformat(),
                    "reason": self.git.reason,
                    "snapshot_sha256": self.git.snapshot_sha256,
                }
                if self.git is not None
                else None
            ),
            "snapshot_sha256": self.snapshot_sha256,
        }

    def to_heartbeat_input(
        self,
        *,
        head: str,
        graph_snapshot_sha256: str,
        proof_ready: bool,
        stuck_tasks: tuple[StuckTask, ...] = (),
        as_of: datetime | None = None,
    ) -> HeartbeatInput:
        """Derive heartbeat gates solely from this server snapshot."""

        current = _utc_datetime(as_of or self.observed_at, "server authority as_of")
        if not isinstance(head, str) or not head.strip():
            raise ValueError("heartbeat head is required")
        if not isinstance(graph_snapshot_sha256, str) or not graph_snapshot_sha256.strip():
            raise ValueError("heartbeat graph snapshot is required")

        def current_state(name: str) -> bool:
            item = self.observation(name)
            return item is not None and item.is_current(current)

        git_flags = {
            "head_verified": False,
            "workspace_state_known": False,
            "workspace_clean": False,
        }
        if self.git is not None and self.git.available and self.git.observed_at <= current:
            git_flags = self.git.flags_for(head)
        reasons = list(self.authority_reasons(as_of=current))
        if (
            self.git is not None
            and self.git.available
            and self.git.observed_at <= current
            and self.git.head != head.strip().lower()
        ):
            reasons.append("server_head_mismatch")

        economic = self.economic_guard
        economic_observed = self.economic_observation
        if economic_observed is None or not economic_observed.is_current(current):
            economic = _blocked_economic_guard(
                "server_observation_unavailable:economic_guard"
                if economic_observed is None
                else economic_observed.failure_reason(current)
                or "server_observation_unavailable:economic_guard",
                source_digest=economic.snapshot_sha256,
            )
        return HeartbeatInput(
            head=head,
            graph_snapshot_sha256=graph_snapshot_sha256,
            proof_ready=proof_ready,
            evidence_fresh=current_state("evidence"),
            data_quality_valid=current_state("data_quality"),
            external_readback_passed=current_state("external_readback"),
            rollback_available=current_state("rollback"),
            economic_guard=economic,
            experiment_clear=current_state("experiment"),
            stuck_tasks=stuck_tasks,
            head_verified=git_flags["head_verified"],
            workspace_state_known=git_flags["workspace_state_known"],
            workspace_clean=git_flags["workspace_clean"],
            task_queue_known=current_state("task_queue"),
            lease_snapshot_known=current_state("lease_snapshot"),
            test_receipts_current=current_state("test_receipts"),
            proof_receipts_current=current_state("proof_receipts"),
            authority_reasons=tuple(dict.fromkeys(reasons)),
        )


def _server_authority_snapshot_hash(
    *,
    scope_key: str,
    observed_at: str,
    observations: tuple[AuthorityObservation, ...],
    economic_guard: EconomicGuardResult,
    economic_observation: AuthorityObservation | None,
    git: GitWorktreeObservation | None,
) -> str:
    return _stable_hash(
        {
            "contract_id": "kjds-server-authority-snapshot-v1",
            "scope_key": scope_key,
            "observed_at": observed_at,
            "observations": [item.as_dict() for item in observations],
            "economic_guard": {
                "status": economic_guard.status,
                "reasons": list(economic_guard.reasons),
                "snapshot_sha256": economic_guard.snapshot_sha256,
            },
            "economic_observation": (
                economic_observation.as_dict()
                if economic_observation is not None
                else None
            ),
            "git_snapshot_sha256": git.snapshot_sha256 if git is not None else None,
        }
    )


def _blocked_authority_observation(
    name: str,
    *,
    scope_key: str,
    observed_at: datetime,
    reason: str,
) -> AuthorityObservation:
    digest = _stable_hash(
        {
            "contract_id": "kjds-server-authority-blocked-v1",
            "name": name,
            "scope_key": scope_key,
            "reason": reason,
        }
    )
    return AuthorityObservation(
        name=name,
        status="blocked",
        scope_key=scope_key,
        observed_at=observed_at,
        source_ref=f"server://authority/{name}",
        payload_sha256=digest,
        reason=reason,
    )


def _blocked_economic_guard(reason: str, *, source_digest: str | None = None) -> EconomicGuardResult:
    reasons = tuple(dict.fromkeys((reason.strip() or "economic_state_unknown",)))
    return EconomicGuardResult(
        status="blocked",
        reasons=reasons,
        snapshot_sha256=_stable_hash(
            {
                "contract_id": "kjds-server-economic-guard-blocked-v1",
                "reasons": list(reasons),
                "source_digest": source_digest,
            }
        ),
    )


def _coerce_server_observation(
    name: str,
    value: Any,
    *,
    scope_key: str,
    observed_at: datetime,
) -> AuthorityObservation:
    if isinstance(value, AuthorityObservation):
        if value.name != name:
            raise ValueError("authority observation name mismatch")
        if value.scope_key != scope_key:
            raise ValueError("authority observation scope mismatch")
        return value
    if not isinstance(value, Mapping):
        raise ValueError("server authority reader must return AuthorityObservation")
    raw_observed = value.get("observed_at", observed_at)
    if isinstance(raw_observed, str):
        raw_observed = datetime.fromisoformat(raw_observed)
    raw_expires = value.get("expires_at")
    if isinstance(raw_expires, str):
        raw_expires = datetime.fromisoformat(raw_expires)
    status = value.get("status", value.get("state"))
    return AuthorityObservation(
        name=name,
        status=status,
        scope_key=value.get("scope_key", scope_key),
        observed_at=raw_observed,
        source_ref=value.get("source_ref", ""),
        payload_sha256=value.get("payload_sha256", ""),
        expires_at=raw_expires,
        reason=value.get("reason"),
        snapshot_sha256=value.get("snapshot_sha256", ""),
    )


def _coerce_economic_guard(value: Any) -> EconomicGuardResult:
    if not isinstance(value, EconomicGuardResult):
        raise ValueError("economic guard reader must return EconomicGuardResult")
    if value.status not in {"allowed", "blocked"}:
        raise ValueError("economic guard status is invalid")
    if not _SHA256.fullmatch(str(value.snapshot_sha256).lower()):
        raise ValueError("economic guard snapshot digest is invalid")
    return value


def _coerce_economic_guard_read(
    value: Any,
    *,
    scope_key: str,
    observed_at: datetime,
) -> ServerEconomicGuardRead:
    """Normalize a guard reader result and bind its freshness receipt."""

    if isinstance(value, ServerEconomicGuardRead):
        read = value
    elif isinstance(value, EconomicGuardResult):
        guard = _coerce_economic_guard(value)
        read = ServerEconomicGuardRead(
            guard=guard,
            observation=AuthorityObservation(
                name="economic_guard",
                status="valid",
                scope_key=scope_key,
                observed_at=observed_at,
                source_ref="server://authority/economic_guard",
                payload_sha256=guard.snapshot_sha256,
            ),
        )
    else:
        guard_value: Any = None
        observation_value: Any = None
        if isinstance(value, (tuple, list)) and len(value) == 2:
            first, second = value
            if isinstance(first, EconomicGuardResult):
                guard_value, observation_value = first, second
            else:
                observation_value, guard_value = first, second
        elif isinstance(value, Mapping):
            guard_value = value.get("economic_guard", value.get("guard"))
            observation_value = value.get("economic_observation", value.get("observation"))
        if guard_value is None or observation_value is None:
            raise ValueError("economic guard reader must return a server guard read")
        guard = _coerce_economic_guard(guard_value)
        observation = _coerce_server_observation(
            "economic_guard",
            observation_value,
            scope_key=scope_key,
            observed_at=observed_at,
        )
        read = ServerEconomicGuardRead(guard=guard, observation=observation)
    if read.observation.scope_key != scope_key:
        raise ValueError("economic guard observation scope mismatch")
    return read


def observe_server_authority(
    readers: Mapping[str, Callable[..., Any]] | None = None,
    *,
    scope_key: str,
    economic_guard_reader: Callable[..., Any] | None = None,
    git_observation: GitWorktreeObservation | None = None,
    repository_root: str | Path | None = None,
    git_runner: Callable[..., Any] | None = None,
    observed_at: datetime | None = None,
) -> ServerAuthoritySnapshot:
    """Read all PM authority inputs through explicit server-side adapters.

    Every reader receives the exact scope and heartbeat observation time.  A
    missing reader, exception, malformed result or scope mismatch produces a
    deterministic blocked observation.  No caller-supplied boolean or payload
    is accepted by this function.
    """

    now = _utc_datetime(observed_at or datetime.now(UTC), "server authority observed_at")
    normalized_scope = scope_key.strip() if isinstance(scope_key, str) else ""
    if not normalized_scope or len(normalized_scope) > 500:
        raise ValueError("scope_key is required and bounded")
    if readers is not None and not isinstance(readers, Mapping):
        raise ValueError("readers must be a mapping")
    source_readers = readers or {}
    observations: list[AuthorityObservation] = []
    for name in SERVER_AUTHORITY_FIELDS:
        reader = source_readers.get(name)
        if reader is None:
            for alias in _SERVER_AUTHORITY_ALIASES.get(name, ()):
                reader = source_readers.get(alias)
                if reader is not None:
                    break
        if not callable(reader):
            observations.append(
                _blocked_authority_observation(
                    name,
                    scope_key=normalized_scope,
                    observed_at=now,
                    reason="reader_unavailable",
                )
            )
            continue
        try:
            raw = reader(scope_key=normalized_scope, observed_at=now)
            observations.append(
                _coerce_server_observation(
                    name,
                    raw,
                    scope_key=normalized_scope,
                    observed_at=now,
                )
            )
        except Exception:
            # Do not expose adapter exception text; it may contain credentials
            # or platform payloads, and a failed read is enough to hold work.
            observations.append(
                _blocked_authority_observation(
                    name,
                    scope_key=normalized_scope,
                    observed_at=now,
                    reason="reader_failed",
                )
            )

    if git_observation is None:
        try:
            git_observation = observe_server_git_worktree(
                repository_root,
                observed_at=now,
                runner=git_runner,
            )
        except Exception:
            git_observation = _blocked_git_observation(now, "git_probe_failed")
    elif not isinstance(git_observation, GitWorktreeObservation):
        git_observation = _blocked_git_observation(now, "git_observation_invalid")

    if economic_guard_reader is None:
        economic_guard = _blocked_economic_guard("reader_unavailable:economic_guard")
        economic_observation = _blocked_authority_observation(
            "economic_guard",
            scope_key=normalized_scope,
            observed_at=now,
            reason="reader_unavailable",
        )
    else:
        try:
            economic_read = _coerce_economic_guard_read(
                economic_guard_reader(scope_key=normalized_scope, observed_at=now),
                scope_key=normalized_scope,
                observed_at=now,
            )
            economic_guard = economic_read.guard
            economic_observation = economic_read.observation
        except Exception:
            economic_guard = _blocked_economic_guard("reader_failed:economic_guard")
            economic_observation = _blocked_authority_observation(
                "economic_guard",
                scope_key=normalized_scope,
                observed_at=now,
                reason="reader_failed",
            )
    return ServerAuthoritySnapshot(
        scope_key=normalized_scope,
        observed_at=now,
        observations=tuple(observations),
        economic_guard=economic_guard,
        economic_observation=economic_observation,
        git=git_observation,
    )


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

    @classmethod
    def from_server_authority(
        cls,
        authority: ServerAuthoritySnapshot,
        *,
        head: str,
        graph_snapshot_sha256: str,
        proof_ready: bool,
        stuck_tasks: tuple[StuckTask, ...] = (),
        as_of: datetime | None = None,
    ) -> HeartbeatInput:
        """Build a heartbeat input without accepting caller attestations."""

        if not isinstance(authority, ServerAuthoritySnapshot):
            raise ValueError("authority must be a ServerAuthoritySnapshot")
        return authority.to_heartbeat_input(
            head=head,
            graph_snapshot_sha256=graph_snapshot_sha256,
            proof_ready=proof_ready,
            stuck_tasks=stuck_tasks,
            as_of=as_of,
        )


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
    "AuthorityObservation",
    "GitWorktreeObservation",
    "HeartbeatDecision",
    "HeartbeatInput",
    "SERVER_AUTHORITY_FIELDS",
    "ServerEconomicGuardRead",
    "ServerAuthoritySnapshot",
    "evaluate_heartbeat",
    "observe_server_authority",
    "observe_server_git_worktree",
]
