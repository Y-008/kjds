"""Standing autonomous execution profiles with one-time Permit issuance.

The profile is a *policy decision seam*, not a provider client.  It can issue
one short-lived, command-bound :class:`ExternalWritePermit` only when the
same six gates used by the project-manager heartbeat are all fresh.  A caller
must still pass the permit to the existing channel/marketplace adapter, which
performs the final exact-command, expiry and single-use checks.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from .economic_guard_service import EconomicGuardResult
from .growth_channel import ExternalWritePermit


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _required(value: str, name: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class StandingAutonomousExecutionProfile:
    """A one-time governance activation for bounded unattended execution.

    ``enabled`` is deliberately explicit.  A profile does not grant broad
    account access: every request is still constrained by exact tenant,
    entity, store, channel and operation membership.
    """

    profile_id: str
    tenant_ref: str
    entity_ref: str
    store_refs: frozenset[str]
    allowed_channels: frozenset[str]
    allowed_operations: frozenset[str]
    enabled: bool = False
    activated_at: datetime | None = None
    expires_at: datetime | None = None
    max_permit_ttl_seconds: int = 300
    max_command_amount: Decimal | None = None
    profile_version: str = "1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile_id", _required(self.profile_id, "profile_id"))
        object.__setattr__(self, "tenant_ref", _required(self.tenant_ref, "tenant_ref"))
        object.__setattr__(self, "entity_ref", _required(self.entity_ref, "entity_ref"))
        if not self.store_refs:
            raise ValueError("store_refs must not be empty")
        if not self.allowed_channels or not self.allowed_operations:
            raise ValueError("allowed channels and operations must not be empty")
        if self.max_permit_ttl_seconds < 1 or self.max_permit_ttl_seconds > 3600:
            raise ValueError("max_permit_ttl_seconds must be between 1 and 3600")
        if self.activated_at is not None:
            object.__setattr__(self, "activated_at", _aware(self.activated_at, "activated_at"))
        if self.expires_at is not None:
            object.__setattr__(self, "expires_at", _aware(self.expires_at, "expires_at"))
        if self.max_command_amount is not None and self.max_command_amount < 0:
            raise ValueError("max_command_amount must be non-negative")

    @property
    def profile_sha256(self) -> str:
        return _sha(
            {
                "profile_id": self.profile_id,
                "tenant_ref": self.tenant_ref,
                "entity_ref": self.entity_ref,
                "store_refs": sorted(self.store_refs),
                "allowed_channels": sorted(self.allowed_channels),
                "allowed_operations": sorted(self.allowed_operations),
                "enabled": self.enabled,
                "activated_at": self.activated_at.isoformat() if self.activated_at else None,
                "expires_at": self.expires_at.isoformat() if self.expires_at else None,
                "max_permit_ttl_seconds": self.max_permit_ttl_seconds,
                "max_command_amount": str(self.max_command_amount) if self.max_command_amount is not None else None,
                "profile_version": self.profile_version,
            }
        )


@dataclass(frozen=True, slots=True)
class AutonomousPermitRequest:
    tenant_ref: str
    entity_ref: str
    store_ref: str
    channel: str
    operation: str
    idempotency_key: str
    command: dict[str, Any]
    proof_ready: bool
    evidence_fresh: bool
    data_quality_valid: bool
    external_readback_passed: bool
    rollback_available: bool
    economic_guard: EconomicGuardResult
    attribution_id: str = "standing-autonomy"
    recipient_ref: str | None = None
    command_amount: Decimal | None = None
    now: datetime | None = None


@dataclass(frozen=True, slots=True)
class AutonomousPermitDecision:
    status: Literal["issued", "blocked"]
    reasons: tuple[str, ...]
    profile_sha256: str
    command_sha256: str
    permit: ExternalWritePermit | None = None
    decision_sha256: str = ""


def evaluate_standing_profile(
    profile: StandingAutonomousExecutionProfile,
    request: AutonomousPermitRequest,
) -> AutonomousPermitDecision:
    """Evaluate all gates and issue at most one command-bound permit."""

    now = _aware(request.now or datetime.now(UTC), "now")
    command_sha = _sha(
        {
            "idempotency_key": request.idempotency_key.strip(),
            "operation": request.operation.strip(),
            "attribution_id": request.attribution_id.strip(),
            "recipient_ref": request.recipient_ref,
            "payload": request.command,
        }
    )
    reasons: list[str] = []
    if not profile.enabled:
        reasons.append("profile_disabled")
    if request.tenant_ref != profile.tenant_ref:
        reasons.append("tenant_scope_mismatch")
    if request.entity_ref != profile.entity_ref:
        reasons.append("entity_scope_mismatch")
    if request.store_ref not in profile.store_refs:
        reasons.append("store_scope_mismatch")
    channel = request.channel.strip().lower()
    if channel not in profile.allowed_channels:
        reasons.append("channel_not_allowed")
    if request.operation.strip() not in profile.allowed_operations:
        reasons.append("operation_not_allowed")
    if profile.activated_at is None:
        reasons.append("activation_time_missing")
    elif now < profile.activated_at:
        reasons.append("profile_not_yet_active")
    if profile.expires_at is not None and now >= profile.expires_at:
        reasons.append("profile_expired")
    if not request.proof_ready:
        reasons.append("proof_not_ready")
    if not request.evidence_fresh:
        reasons.append("evidence_stale")
    if not request.data_quality_valid:
        reasons.append("data_quality_invalid")
    if not request.external_readback_passed:
        reasons.append("external_readback_not_passed")
    if not request.rollback_available:
        reasons.append("rollback_missing")
    if request.economic_guard.status != "allowed":
        reasons.extend(request.economic_guard.reasons or ("economic_guard_blocked",))
    command_amount: Decimal | None = None
    if request.command_amount is not None:
        try:
            command_amount = (
                request.command_amount
                if isinstance(request.command_amount, Decimal)
                else Decimal(str(request.command_amount))
            )
        except (ArithmeticError, TypeError, ValueError):
            command_amount = None
            reasons.append("command_amount_invalid")
        if command_amount is not None and (
            not command_amount.is_finite() or command_amount < 0
        ):
            reasons.append("command_amount_invalid")
    if (
        command_amount is not None
        and profile.max_command_amount is not None
        and command_amount > profile.max_command_amount
    ):
        reasons.append("command_amount_above_profile_limit")
    if not request.idempotency_key.strip():
        reasons.append("idempotency_key_missing")

    reasons_tuple = tuple(dict.fromkeys(reasons))
    permit: ExternalWritePermit | None = None
    if not reasons_tuple:
        expiry = now + timedelta(seconds=profile.max_permit_ttl_seconds)
        if profile.expires_at is not None:
            expiry = min(expiry, profile.expires_at)
        permit = ExternalWritePermit(
            permit_id=f"standing:{profile.profile_id}:{command_sha[:32]}",
            channel=channel,
            operation=request.operation,
            command_sha256=command_sha,
            expires_at=expiry,
        )
    status: Literal["issued", "blocked"] = "issued" if permit is not None else "blocked"
    decision_sha = _sha(
        {
            "profile_sha256": profile.profile_sha256,
            "command_sha256": command_sha,
            "status": status,
            "reasons": list(reasons_tuple),
            "economic_snapshot_sha256": request.economic_guard.snapshot_sha256,
        }
    )
    return AutonomousPermitDecision(
        status=status,
        reasons=reasons_tuple,
        profile_sha256=profile.profile_sha256,
        command_sha256=command_sha,
        permit=permit,
        decision_sha256=decision_sha,
    )


__all__ = [
    "AutonomousPermitDecision",
    "AutonomousPermitRequest",
    "StandingAutonomousExecutionProfile",
    "evaluate_standing_profile",
]
