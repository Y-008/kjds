"""Fail-closed Lean proof runner descriptor."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any

from .formal_proof_manifest import (
    load_manifest,
    manifest_sha256,
    toolchain_status,
    validate_manifest_artifacts,
    validate_manifest_modules,
)


def run_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path).resolve()
    entries = load_manifest(path)
    toolchain = toolchain_status()
    module_errors = validate_manifest_modules(entries, root=manifest_path.parent)
    artifact_errors = validate_manifest_artifacts(entries, root=manifest_path.parent)
    base = {
        "toolchain": toolchain,
        "manifest_sha256": manifest_sha256(entries),
        "module_errors": list(module_errors),
        "artifact_errors": list(artifact_errors),
    }
    if module_errors or artifact_errors:
        return {
            **base,
            "status": "failed",
            "reason": "proof_artifact_validation_failed" if artifact_errors else "proof_module_validation_failed",
            "proved": [],
            "blocked": [entry.stable_key for entry in entries],
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
    try:
        completed = subprocess.run(
            ["lake", "build"],
            cwd=manifest_path.parent,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        output = ((exc.stdout or "") + "\n" + (exc.stderr or "")).encode("utf-8", "replace")
        return {
            **base,
            "status": "blocked",
            "reason": "lake_build_timeout",
            "exit_code": None,
            "build_output_sha256": hashlib.sha256(output).hexdigest(),
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
            "proved": [],
            "blocked": [entry.stable_key for entry in entries],
        }
    return {
        **base,
        "status": "proved",
        "reason": "lake_build_succeeded",
        "exit_code": completed.returncode,
        "build_output_sha256": output_sha256,
        "proved": [entry.stable_key for entry in entries],
        "blocked": [],
        "proof_receipt_sha256": hashlib.sha256(
            (base["manifest_sha256"] + output_sha256).encode()
        ).hexdigest(),
    }
