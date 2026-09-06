"""Canonical node kinds and four-state admission contract for the proof graph."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GraphNodeKind(StrEnum):
    TEMPORAL_TRUTH = "temporal_truth"
    DATA_QUALITY = "data_quality"
    ECONOMIC_GUARD = "economic_guard"
    EXPERIMENT = "experiment"
    COUNTEREXAMPLE = "counterexample"
    INCIDENT = "incident"
    RECOVERY = "recovery"
    COMMERCIAL_ENTITLEMENT = "commercial_entitlement"
    MODEL_RISK = "model_risk"
    THEOREM = "theorem"
    BUSINESS = "business"


class ProofState(StrEnum):
    PROVED = "PROVED"
    UNPROVED = "UNPROVED"
    STALE = "STALE"
    BLOCKED = "BLOCKED"
    NO_DATA = "NO_DATA"


class EvidenceState(StrEnum):
    VALID = "VALID"
    PARTIAL = "PARTIAL"
    STALE = "STALE"
    BLOCKED = "BLOCKED"
    NO_DATA = "NO_DATA"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"


class OperationalState(StrEnum):
    LIVE = "LIVE"
    SHADOW = "SHADOW"
    PAUSED = "PAUSED"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


class EconomicState(StrEnum):
    ALLOWED = "ALLOWED"
    AT_RISK = "AT_RISK"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


class GovernedGraphNode(BaseModel):
    """A graph node whose proof, evidence, operation and economics are separate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str = Field(min_length=1, max_length=200)
    kind: GraphNodeKind
    label: str = Field(min_length=1, max_length=500)
    proof_state: ProofState = ProofState.NO_DATA
    evidence_state: EvidenceState = EvidenceState.NO_DATA
    operational_state: OperationalState = OperationalState.UNKNOWN
    economic_state: EconomicState = EconomicState.UNKNOWN
    rollback_available: bool = False
    proof_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    lineage_refs: tuple[str, ...] = ()

    @property
    def admission_state(self) -> str:
        """Return LIVE only when all independent production gates are satisfied."""

        if (
            self.proof_state == ProofState.PROVED
            and self.evidence_state == EvidenceState.VALID
            and self.operational_state == OperationalState.LIVE
            and self.economic_state == EconomicState.ALLOWED
            and self.rollback_available
        ):
            return "LIVE"

        # Explicit hard failures must dominate an unknown external outcome or
        # a refreshable hold.  In particular, a missing rollback path and
        # BLOCKED operational/economic gates are unsafe even when the other
        # states happen to look healthy.
        if (
            self.rollback_available is False
            or self.proof_state
            in {ProofState.BLOCKED, ProofState.STALE, ProofState.NO_DATA}
            or self.evidence_state
            in {
                EvidenceState.BLOCKED,
                EvidenceState.STALE,
                EvidenceState.NO_DATA,
            }
            or self.operational_state == OperationalState.BLOCKED
            or self.economic_state == EconomicState.BLOCKED
        ):
            return "BLOCKED"

        if self.evidence_state == EvidenceState.UNKNOWN_OUTCOME:
            return "UNKNOWN_OUTCOME"
        return "HOLD"

    @model_validator(mode="after")
    def validate_refs(self) -> GovernedGraphNode:
        if self.proof_state == ProofState.PROVED and not self.proof_refs:
            raise ValueError("proved node requires proof_refs")
        if self.evidence_state == EvidenceState.VALID and not self.evidence_refs:
            raise ValueError("valid evidence requires evidence_refs")
        if len(set(self.lineage_refs)) != len(self.lineage_refs):
            raise ValueError("lineage_refs must be unique")
        return self


__all__ = [
    "EconomicState",
    "EvidenceState",
    "GraphNodeKind",
    "GovernedGraphNode",
    "OperationalState",
    "ProofState",
]
