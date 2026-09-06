"""Explicit bridge between proof obligations and evidence references."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProofEvidenceBinding:
    stable_key: str
    evidence_refs: tuple[str, ...]
    assumptions: tuple[str, ...]


def bind_evidence(stable_key: str, evidence_refs: tuple[str, ...], assumptions: tuple[str, ...]) -> ProofEvidenceBinding:
    if not stable_key.strip():
        raise ValueError("stable_key is required")
    if not assumptions and not evidence_refs:
        raise ValueError("proof binding requires explicit assumptions or evidence")
    return ProofEvidenceBinding(stable_key.strip(), tuple(dict.fromkeys(evidence_refs)), tuple(dict.fromkeys(assumptions)))
