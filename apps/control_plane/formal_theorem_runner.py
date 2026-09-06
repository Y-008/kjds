"""Fail-closed Lean proof runner descriptor.

The runner never edits a manifest and never turns a caller assertion into a
proof.  A successful Lake invocation is projected into one immutable receipt
per manifest entry, each receipt carrying the exact module and manifest
digests needed for later replay.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from .formal_proof_manifest import (
    load_manifest,
    manifest_metadata,
    manifest_sha256,
    toolchain_status,
    validate_manifest_artifacts,
    validate_manifest_examples,
    validate_manifest_modules,
)
from .proof_artifact_validator import (
    ProofArtifactReceipt,
    replay_proof_receipt,
)
from .proof_evidence_bridge import bind_evidence


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _lake_root(manifest_path: Path, entries: tuple[Any, ...]) -> Path:
    """Find the nearest Lake project while keeping the manifest root in scope."""

    base = manifest_path.parent
    candidates: list[Path] = []
    for entry in entries:
        module = (base / entry.module).resolve()
        candidates.extend((module.parent, *module.parents))
    candidates.extend((base, *base.parents))
    for candidate in candidates:
        if (candidate / "lakefile.toml").is_file() or (candidate / "lakefile.lean").is_file():
            return candidate
    return base


def _entry_receipts(
    entries: tuple[Any, ...],
    *,
    root: Path,
    manifest_digest: str,
    build_output_sha256: str,
    status: str,
    command_sha256: str,
) -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    for entry in entries:
        module = (root / entry.module).resolve()
        if not module.is_file():
            continue
        artifact_sha256 = hashlib.sha256(module.read_bytes()).hexdigest()
        binding = bind_evidence(entry.stable_key, entry.evidence_refs, entry.assumptions)
        receipt = ProofArtifactReceipt(
            stable_key=entry.stable_key,
            theorem=entry.theorem,
            module=entry.module,
            manifest_sha256=manifest_digest,
            artifact_sha256=artifact_sha256,
            build_output_sha256=build_output_sha256,
            status=status,
            command_sha256=command_sha256,
            evidence_refs_sha256=binding.evidence_refs_sha256,
            examples_sha256=_digest(
                {
                    "positive_refs": list(entry.positive_refs),
                    "counterexample_refs": list(entry.counterexample_refs),
                    "mutation_test_refs": list(entry.mutation_test_refs),
                }
            ),
        )
        receipts.append(receipt.as_dict())
    return receipts


def replay_manifest_receipts(
    path: str | Path,
    receipts: list[ProofArtifactReceipt | dict[str, Any]],
) -> dict[str, Any]:
    """Replay stored receipts against the current manifest and module bytes."""

    manifest_path = Path(path).resolve()
    entries = load_manifest(path)
    metadata = manifest_metadata(path)
    digest = manifest_sha256(entries, metadata=metadata)
    entry_by_key = {entry.stable_key: entry for entry in entries}
    results: list[dict[str, Any]] = []
    for receipt in receipts:
        key = receipt.stable_key if isinstance(receipt, ProofArtifactReceipt) else receipt.get("stable_key")
        entry = entry_by_key.get(key)
        if entry is None:
            results.append(
                {
                    "stable_key": key,
                    "status": "blocked",
                    "reason": "receipt_entry_missing",
                    "replay_allowed": False,
                }
            )
            continue
        result = replay_proof_receipt(
            receipt,
            root=manifest_path.parent,
            expected_manifest_sha256=digest,
        )
        results.append({"stable_key": key, **result})
    return {
        "contract_id": "kjds-proof-manifest-replay-v1",
        "manifest_sha256": digest,
        "status": "ready" if results and all(item["replay_allowed"] for item in results) else "blocked",
        "results": results,
        "external_write_allowed": False,
    }


def run_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path).resolve()
    entries = load_manifest(path)
    metadata = manifest_metadata(path)
    manifest_digest = manifest_sha256(entries, metadata=metadata)
    toolchain = toolchain_status()
    module_errors = validate_manifest_modules(entries, root=manifest_path.parent)
    artifact_errors = validate_manifest_artifacts(entries, root=manifest_path.parent)
    policy = metadata.get("example_policy", {})
    require_positive = bool(policy.get("require_positive", False))
    require_counterexample = bool(policy.get("require_counterexample", False))
    example_errors = validate_manifest_examples(
        entries,
        require_positive=require_positive,
        require_counterexample=require_counterexample,
    )
    base = {
        "toolchain": toolchain,
        "manifest_sha256": manifest_digest,
        "module_errors": list(module_errors),
        "artifact_errors": list(artifact_errors),
        "example_errors": list(example_errors),
        "example_policy": {
            "require_positive": require_positive,
            "require_counterexample": require_counterexample,
        },
    }
    if module_errors or artifact_errors:
        return {
            **base,
            "status": "failed",
            "reason": "proof_artifact_validation_failed" if artifact_errors else "proof_module_validation_failed",
            "proved": [],
            "blocked": [entry.stable_key for entry in entries],
        }
    if example_errors:
        example_blocked = sorted(
            {
                error.split(":", 1)[1]
                for error in example_errors
                if ":" in error
            }
        )
        return {
            **base,
            "status": "blocked",
            "reason": "proof_examples_missing",
            "proved": [],
            "blocked": example_blocked or [entry.stable_key for entry in entries],
        }
    missing_evidence = [entry.stable_key for entry in entries if not entry.evidence_refs]
    if missing_evidence:
        return {
            **base,
            "status": "blocked",
            "reason": "proof_evidence_binding_missing",
            "proved": [],
            "blocked": missing_evidence,
        }
    # Validate the bridge before invoking a toolchain.  This only checks
    # reference shape and binding identity; it does not claim the referenced
    # evidence is fresh or externally admitted.
    binding_errors: list[str] = []
    for entry in entries:
        try:
            bind_evidence(entry.stable_key, entry.evidence_refs, entry.assumptions)
        except ValueError as exc:
            binding_errors.append(f"{entry.stable_key}:{exc}")
    if binding_errors:
        return {
            **base,
            "status": "blocked",
            "reason": "proof_evidence_binding_invalid",
            "binding_errors": binding_errors,
            "proved": [],
            "blocked": [entry.stable_key for entry in entries],
        }
    non_runnable = [
        entry.stable_key
        for entry in entries
        if entry.status not in {"proposed", "running"}
    ]
    if non_runnable:
        return {
            **base,
            "status": "blocked",
            "reason": "proof_status_not_eligible",
            "proved": [],
            "blocked": non_runnable,
        }
    if toolchain["status"] != "ready":
        return {
            **base,
            "status": "blocked",
            "reason": toolchain["reason"],
            "proved": [],
            "blocked": [entry.stable_key for entry in entries],
        }
    # Run the repository's pinned Lake build when the toolchain is present.
    # Only an exit code of zero is admitted as a proof receipt; output is
    # represented by a digest so compiler paths or accidental secrets are not
    # copied into API responses.
    command = ["lake", "build"]
    command_sha256 = _digest(command)
    build_root = _lake_root(manifest_path, entries)
    try:
        completed = subprocess.run(
            command,
            cwd=build_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        output = ((exc.stdout or "") + "\n" + (exc.stderr or "")).encode("utf-8", "replace")
        output_sha256 = hashlib.sha256(output).hexdigest()
        return {
            **base,
            "status": "blocked",
            "reason": "lake_build_timeout",
            "exit_code": None,
            "build_output_sha256": output_sha256,
            "build_root": str(build_root),
            "entry_receipts": _entry_receipts(
                entries,
                root=manifest_path.parent,
                manifest_digest=manifest_digest,
                build_output_sha256=output_sha256,
                status="blocked",
                command_sha256=command_sha256,
            ),
            "proved": [],
            "blocked": [entry.stable_key for entry in entries],
        }
    output = (completed.stdout + "\n" + completed.stderr).encode("utf-8", "replace")
    output_sha256 = hashlib.sha256(output).hexdigest()
    if completed.returncode != 0:
        return {
            **base,
            "status": "failed",
            "reason": "lake_build_failed",
            "exit_code": completed.returncode,
            "build_output_sha256": output_sha256,
            "build_root": str(build_root),
            "entry_receipts": _entry_receipts(
                entries,
                root=manifest_path.parent,
                manifest_digest=manifest_digest,
                build_output_sha256=output_sha256,
                status="failed",
                command_sha256=command_sha256,
            ),
            "proved": [],
            "blocked": [entry.stable_key for entry in entries],
        }
    receipts = _entry_receipts(
        entries,
        root=manifest_path.parent,
        manifest_digest=manifest_digest,
        build_output_sha256=output_sha256,
        status="proved",
        command_sha256=command_sha256,
    )
    return {
        **base,
        "status": "proved",
        "reason": "lake_build_succeeded",
        "exit_code": completed.returncode,
        "build_output_sha256": output_sha256,
        "build_root": str(build_root),
        "entry_receipts": receipts,
        "proof_receipts": receipts,
        "proved": [entry.stable_key for entry in entries],
        "blocked": [],
        "proof_receipt_sha256": _digest(receipts),
    }


__all__ = ["replay_manifest_receipts", "run_manifest"]
