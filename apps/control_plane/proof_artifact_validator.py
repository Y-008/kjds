"""Validate proof receipts without treating unverified artifacts as proofs.

The formal runner deliberately produces a *receipt* instead of mutating a
manifest.  A receipt is useful only when it is bound to the exact source
module and manifest that were checked.  This module contains the small,
side-effect-free contract used to validate and replay those receipts.  It
does not invoke Lean and therefore cannot manufacture a successful proof.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_RECEIPT_CONTRACT = "kjds-proof-receipt-v1"
ProofReceiptStatus = Literal["proved", "failed", "blocked"]


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _canonical(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            dict(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("proof receipt is not canonical JSON") from exc


@dataclass(frozen=True, slots=True)
class ProofArtifactReceipt:
    """A deterministic binding between one theorem build and its inputs.

    ``status=proved`` is meaningful only after the caller has observed a
    successful Lean/Lake process.  The validator below only checks the
    resulting claim and current bytes; it never upgrades a blocked receipt.
    """

    stable_key: str
    theorem: str
    module: str
    manifest_sha256: str
    artifact_sha256: str
    build_output_sha256: str
    status: ProofReceiptStatus
    contract_id: str = _RECEIPT_CONTRACT
    command_sha256: str | None = None
    evidence_refs_sha256: str | None = None
    examples_sha256: str | None = None
    receipt_sha256: str | None = None

    def payload(self) -> dict[str, Any]:
        """Return the hashable receipt payload, excluding its self-digest."""

        return {
            "contract_id": self.contract_id,
            "stable_key": self.stable_key,
            "theorem": self.theorem,
            "module": self.module,
            "manifest_sha256": self.manifest_sha256,
            "artifact_sha256": self.artifact_sha256,
            "build_output_sha256": self.build_output_sha256,
            "status": self.status,
            "command_sha256": self.command_sha256,
            "evidence_refs_sha256": self.evidence_refs_sha256,
            "examples_sha256": self.examples_sha256,
        }

    def as_dict(self) -> dict[str, Any]:
        payload = self.payload()
        payload["receipt_sha256"] = self.receipt_sha256 or receipt_sha256(payload)
        return payload


def receipt_sha256(receipt: ProofArtifactReceipt | Mapping[str, Any]) -> str:
    """Compute the deterministic digest of a receipt without self-reference."""

    if isinstance(receipt, ProofArtifactReceipt):
        payload = receipt.payload()
    elif isinstance(receipt, Mapping):
        payload = {
            str(key): value
            for key, value in receipt.items()
            if key != "receipt_sha256"
        }
    else:
        raise TypeError("receipt must be a ProofArtifactReceipt or mapping")
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _receipt_mapping(receipt: ProofArtifactReceipt | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(receipt, ProofArtifactReceipt):
        return receipt.as_dict()
    if isinstance(receipt, Mapping):
        return dict(receipt)
    raise TypeError("receipt must be a ProofArtifactReceipt or mapping")


def validate_proof_receipt(
    receipt: ProofArtifactReceipt | Mapping[str, Any],
    *,
    root: str | Path | None = None,
    expected_manifest_sha256: str | None = None,
    expected_stable_key: str | None = None,
    expected_theorem: str | None = None,
    expected_module: str | None = None,
) -> tuple[str, ...]:
    """Return deterministic validation errors for one proof receipt.

    A tuple is returned instead of raising for ordinary invalid input so
    callers can persist all blockers in a project graph.  Type errors still
    raise because they indicate a programming-contract violation.
    """

    item = _receipt_mapping(receipt)
    errors: list[str] = []
    if item.get("contract_id") != _RECEIPT_CONTRACT:
        errors.append("receipt_contract_invalid")
    for field in ("stable_key", "theorem", "module"):
        value = item.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"receipt_{field}_missing")
    status = item.get("status")
    if status not in {"proved", "failed", "blocked"}:
        errors.append("receipt_status_invalid")
    for field in ("manifest_sha256", "artifact_sha256", "build_output_sha256"):
        if not _is_sha256(item.get(field)):
            errors.append(f"receipt_{field}_invalid")
    for field in ("command_sha256", "evidence_refs_sha256", "examples_sha256"):
        value = item.get(field)
        if value is not None and not _is_sha256(value):
            errors.append(f"receipt_{field}_invalid")
    supplied_digest = item.get("receipt_sha256")
    if supplied_digest is not None:
        if not _is_sha256(supplied_digest):
            errors.append("receipt_digest_invalid")
        elif supplied_digest.lower() != receipt_sha256(item):
            errors.append("receipt_digest_mismatch")
    if expected_manifest_sha256 is not None and item.get("manifest_sha256") != expected_manifest_sha256:
        errors.append("receipt_manifest_mismatch")
    if expected_stable_key is not None and item.get("stable_key") != expected_stable_key:
        errors.append("receipt_stable_key_mismatch")
    if expected_theorem is not None and item.get("theorem") != expected_theorem:
        errors.append("receipt_theorem_mismatch")
    if expected_module is not None and item.get("module") != expected_module:
        errors.append("receipt_module_mismatch")

    if root is not None and isinstance(item.get("module"), str):
        base = Path(root).resolve()
        module = (base / item["module"]).resolve()
        try:
            module.relative_to(base)
        except ValueError:
            errors.append("receipt_module_outside_root")
        else:
            if not module.is_file():
                errors.append("receipt_module_missing")
            elif _is_sha256(item.get("artifact_sha256")):
                current_digest = hashlib.sha256(module.read_bytes()).hexdigest()
                if current_digest != item["artifact_sha256"].lower():
                    errors.append("receipt_artifact_stale")
    return tuple(dict.fromkeys(errors))


def verify_proof_receipt(
    receipt: ProofArtifactReceipt | Mapping[str, Any],
    **kwargs: Any,
) -> bool:
    """Raise on an invalid receipt and return ``True`` only when valid."""

    errors = validate_proof_receipt(receipt, **kwargs)
    if errors:
        raise ValueError("proof receipt invalid: " + ",".join(errors))
    return True


def replay_proof_receipt(
    receipt: ProofArtifactReceipt | Mapping[str, Any],
    *,
    root: str | Path | None = None,
    expected_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    """Re-evaluate whether a stored receipt is still admissible.

    Replay is intentionally read-only.  A changed module or manifest yields a
    ``stale`` result, while malformed claims yield ``blocked``.  Even a valid
    receipt with a non-proved status cannot be promoted during replay.
    """

    item = _receipt_mapping(receipt)
    errors = validate_proof_receipt(
        item,
        root=root,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    if errors:
        stale = any(error in {"receipt_manifest_mismatch", "receipt_artifact_stale"} for error in errors)
        status = "stale" if stale else "blocked"
        reason = "receipt_inputs_changed" if stale else "receipt_validation_failed"
    elif item.get("status") == "proved":
        status = "replayable"
        reason = "receipt_inputs_match"
    else:
        status = "blocked"
        reason = "receipt_was_not_proved"
    return {
        "contract_id": "kjds-proof-receipt-replay-v1",
        "status": status,
        "reason": reason,
        "errors": list(errors),
        "replay_allowed": status == "replayable",
        "receipt_sha256": receipt_sha256(item),
        "external_write_allowed": False,
    }


def validate_artifact(path: str | Path, expected_sha256: str) -> bool:
    """Validate one artifact's bytes against an explicit SHA-256 digest."""

    if not _is_sha256(expected_sha256):
        raise ValueError("proof artifact digest must be a 64-character SHA-256")
    artifact = Path(path)
    if not artifact.is_file():
        raise ValueError("proof artifact is missing")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    if digest != expected_sha256.lower():
        raise ValueError("proof artifact hash mismatch")
    return True


__all__ = [
    "ProofArtifactReceipt",
    "ProofReceiptStatus",
    "replay_proof_receipt",
    "receipt_sha256",
    "validate_artifact",
    "validate_proof_receipt",
    "verify_proof_receipt",
]
