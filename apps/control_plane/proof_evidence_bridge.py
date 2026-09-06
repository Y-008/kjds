"""Explicit, hashable bridge between proof obligations and evidence.

The bridge is deliberately independent of the evidence store.  It validates
the *shape* and identity of references and records a deterministic digest;
the evidence authority can later resolve the references and compare payload
hashes.  A non-empty string supplied by an agent is therefore never silently
treated as a validated external fact.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

_REF_RE = re.compile(r"^[^\x00-\x1f\x7f\s]+$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _normalise_values(values: Any, *, field: str) -> tuple[str, ...]:
    if isinstance(values, str):
        values = (values,)
    if values is None:
        values = ()
    if not isinstance(values, (tuple, list, set, frozenset)):
        raise ValueError(f"{field} must be a sequence of strings")
    result: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise ValueError(f"{field} must contain strings")
        item = value.strip()
        if not item or _REF_RE.fullmatch(item) is None:
            raise ValueError(f"{field} contains an invalid reference")
        if item not in result:
            result.append(item)
    return tuple(result)


def _canonical(payload: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            dict(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("proof evidence binding is not canonical JSON") from exc


def _sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class ProofEvidenceBinding:
    stable_key: str
    evidence_refs: tuple[str, ...]
    assumptions: tuple[str, ...]
    evidence_digests: tuple[tuple[str, str], ...] = ()

    def payload(self) -> dict[str, Any]:
        return {
            "contract_id": "kjds-proof-evidence-binding-v1",
            "stable_key": self.stable_key,
            "evidence_refs": list(self.evidence_refs),
            "assumptions": list(self.assumptions),
            "evidence_digests": {
                key: value for key, value in self.evidence_digests
            },
        }

    @property
    def evidence_refs_sha256(self) -> str:
        """Digest of ordered references, independent of evidence payloads."""

        return _sha256({"evidence_refs": list(self.evidence_refs)})

    @property
    def binding_sha256(self) -> str:
        return _sha256(self.payload())

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.payload(),
            "evidence_refs_sha256": self.evidence_refs_sha256,
            "binding_sha256": self.binding_sha256,
        }


def _normalise_digests(
    evidence_digests: Mapping[str, str] | None,
    refs: tuple[str, ...],
) -> tuple[tuple[str, str], ...]:
    if evidence_digests is None:
        return ()
    if not isinstance(evidence_digests, Mapping):
        raise ValueError("evidence_digests must be a mapping")
    normalised: list[tuple[str, str]] = []
    for raw_ref, digest in evidence_digests.items():
        ref = _normalise_values((raw_ref,), field="evidence_digests")[0]
        if ref not in refs:
            raise ValueError("evidence digest reference is not bound")
        if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest.strip()) is None:
            raise ValueError("evidence digest must be a 64-character SHA-256")
        normalised.append((ref, digest.strip().lower()))
    return tuple(sorted(normalised))


def bind_evidence(
    stable_key: str,
    evidence_refs: tuple[str, ...] | list[str] | str,
    assumptions: tuple[str, ...] | list[str] | str,
    *,
    evidence_digests: Mapping[str, str] | None = None,
) -> ProofEvidenceBinding:
    """Create a normalized proof/evidence binding.

    At least one explicit assumption or evidence reference is required for
    backwards compatibility with the original bridge.  Callers that need an
    externally verifiable proof should provide both and attach payload
    digests once the evidence authority has admitted them.
    """

    if not isinstance(stable_key, str) or not stable_key.strip() or _REF_RE.fullmatch(stable_key.strip()) is None:
        raise ValueError("stable_key is required and must not contain whitespace")
    refs = _normalise_values(evidence_refs, field="evidence_refs")
    normalized_assumptions = _normalise_values(assumptions, field="assumptions")
    if not normalized_assumptions and not refs:
        raise ValueError("proof binding requires explicit assumptions or evidence")
    digests = _normalise_digests(evidence_digests, refs)
    return ProofEvidenceBinding(
        stable_key.strip(),
        refs,
        normalized_assumptions,
        digests,
    )


def validate_binding(
    binding: ProofEvidenceBinding | Mapping[str, Any],
    *,
    require_evidence: bool = False,
    require_assumptions: bool = False,
) -> tuple[str, ...]:
    """Return deterministic errors for a persisted binding projection."""

    if isinstance(binding, ProofEvidenceBinding):
        item = binding.as_dict()
    elif isinstance(binding, Mapping):
        item = dict(binding)
    else:
        raise TypeError("binding must be a ProofEvidenceBinding or mapping")
    errors: list[str] = []
    try:
        key = item.get("stable_key")
        if not isinstance(key, str) or not key.strip() or _REF_RE.fullmatch(key.strip()) is None:
            errors.append("stable_key_invalid")
        refs = _normalise_values(item.get("evidence_refs", ()), field="evidence_refs")
        assumptions = _normalise_values(item.get("assumptions", ()), field="assumptions")
        if require_evidence and not refs:
            errors.append("evidence_refs_missing")
        if require_assumptions and not assumptions:
            errors.append("assumptions_missing")
        raw_digests = item.get("evidence_digests", {})
        digests = _normalise_digests(raw_digests, refs)
        if isinstance(item.get("evidence_refs_sha256"), str):
            expected_refs_digest = _sha256({"evidence_refs": list(refs)})
            if item["evidence_refs_sha256"].lower() != expected_refs_digest:
                errors.append("evidence_refs_digest_mismatch")
        if isinstance(item.get("binding_sha256"), str):
            expected_binding = _sha256(
                {
                    "contract_id": "kjds-proof-evidence-binding-v1",
                    "stable_key": key.strip() if isinstance(key, str) else key,
                    "evidence_refs": list(refs),
                    "assumptions": list(assumptions),
                    "evidence_digests": dict(digests),
                }
            )
            if item["binding_sha256"].lower() != expected_binding:
                errors.append("binding_digest_mismatch")
    except ValueError as exc:
        errors.append(str(exc))
    return tuple(dict.fromkeys(errors))


def evidence_payload_sha256(payload: bytes | bytearray | str) -> str:
    """Hash the exact evidence bytes before binding them to a proof."""

    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    if not isinstance(payload, (bytes, bytearray)):
        raise TypeError("evidence payload must be bytes or text")
    return hashlib.sha256(bytes(payload)).hexdigest()


def validate_evidence_payload(payload: bytes | bytearray | str, expected_sha256: str) -> bool:
    if not isinstance(expected_sha256, str) or _SHA256_RE.fullmatch(expected_sha256.strip()) is None:
        raise ValueError("evidence digest must be a 64-character SHA-256")
    if evidence_payload_sha256(payload) != expected_sha256.strip().lower():
        raise ValueError("evidence payload hash mismatch")
    return True


__all__ = [
    "ProofEvidenceBinding",
    "bind_evidence",
    "evidence_payload_sha256",
    "validate_binding",
    "validate_evidence_payload",
]
