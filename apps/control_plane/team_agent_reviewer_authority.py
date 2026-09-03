"""Server-owned reviewer appointment seam for TeamAgent completion admission."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .enterprise_control import ExactScope

CONTRACT_ID = "team-agent-reviewer-appointment@1"


class TeamAgentReviewerAuthorityUnavailable(RuntimeError):
    """No server authority can currently prove the requested appointment."""


@dataclass(frozen=True, slots=True)
class TeamAgentReviewerAttestation:
    contract_id: str
    scope: ExactScope
    session_ref: str
    task_ref: str
    reviewer_id: str
    reviewer_role: str
    appointment_evidence_ref: str
    authority_sha256: str


class TeamAgentReviewerAuthority(Protocol):
    def admit(
        self,
        *,
        scope: ExactScope,
        authority_sha256: str,
        session_ref: str,
        task_ref: str,
        reviewer_role: str | None,
        requested_reviewer_id: str | None,
        principal: Any,
    ) -> TeamAgentReviewerAttestation: ...


class UnavailableTeamAgentReviewerAuthority:
    """Fail-closed default until a durable appointment authority is composed."""

    def admit(self, **_: Any) -> TeamAgentReviewerAttestation:
        raise TeamAgentReviewerAuthorityUnavailable(
            "server-verified reviewer appointment authority is unavailable"
        )


__all__ = [
    "CONTRACT_ID",
    "TeamAgentReviewerAttestation",
    "TeamAgentReviewerAuthority",
    "TeamAgentReviewerAuthorityUnavailable",
    "UnavailableTeamAgentReviewerAuthority",
]
