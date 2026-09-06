"""Machine-readable proof manifest validation and Lean toolchain probing."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

ProofStatus = Literal["proposed", "blocked", "running", "proved", "failed", "stale"]


@dataclass(frozen=True, slots=True)
class ProofEntry:
    stable_key: str
    theorem: str
    module: str
    status: ProofStatus
    assumptions: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    artifact_sha256: str | None = None
    positive_refs: tuple[str, ...] = ()
    counterexample_refs: tuple[str, ...] = ()
    mutation_test_refs: tuple[str, ...] = ()


def _ref_tuple(raw: Any, *, field: str) -> tuple[str, ...]:
    """Normalize a manifest reference list without accepting character lists."""

    if raw is None:
        return ()
    if isinstance(raw, str) or not isinstance(raw, (list, tuple)):
        raise ValueError(f"{field} must be a list of strings")
    values: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{field} must contain non-empty strings")
        value = item.strip()
        if value not in values:
            values.append(value)
    return tuple(values)


def load_manifest(path: str | Path) -> tuple[ProofEntry, ...]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("entries"), list):
        raise ValueError("proof manifest must contain an entries list")
    entries: list[ProofEntry] = []
    seen: set[str] = set()
    for raw in payload["entries"]:
        if not isinstance(raw, dict):
            raise ValueError("proof manifest entry must be an object")
        key = str(raw.get("stable_key", "")).strip()
        if not key or key in seen:
            raise ValueError("proof stable_key must be unique and non-empty")
        seen.add(key)
        status = str(raw.get("status", "proposed"))
        if status not in {"proposed", "blocked", "running", "proved", "failed", "stale"}:
            raise ValueError(f"unsupported proof status: {status}")
        theorem = str(raw.get("theorem", "")).strip()
        module_name = str(raw.get("module", "")).strip()
        if not theorem or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_'.]*", theorem):
            raise ValueError("proof theorem must be a valid declaration name")
        if not module_name or not module_name.endswith(".lean"):
            raise ValueError("proof module must be a non-empty .lean path")
        artifact_sha256 = raw.get("artifact_sha256")
        if artifact_sha256 is not None and (
            not isinstance(artifact_sha256, str)
            or not re.fullmatch(r"[0-9a-fA-F]{64}", artifact_sha256)
        ):
            raise ValueError("artifact_sha256 must be a 64-character SHA-256 digest")
        entries.append(
            ProofEntry(
                stable_key=key,
                theorem=theorem,
                module=module_name,
                status=status,  # type: ignore[arg-type]
                assumptions=_ref_tuple(raw.get("assumptions", ()), field="assumptions"),
                evidence_refs=_ref_tuple(raw.get("evidence_refs", ()), field="evidence_refs"),
                artifact_sha256=artifact_sha256,
                positive_refs=_ref_tuple(
                    raw.get("positive_refs", raw.get("positive_examples", ())),
                    field="positive_refs",
                ),
                counterexample_refs=_ref_tuple(
                    raw.get("counterexample_refs", raw.get("counterexamples", ())),
                    field="counterexample_refs",
                ),
                mutation_test_refs=_ref_tuple(
                    raw.get("mutation_test_refs", raw.get("mutation_tests", ())),
                    field="mutation_test_refs",
                ),
            )
        )
    return tuple(entries)


def manifest_metadata(path: str | Path) -> dict[str, Any]:
    """Return the optional policy metadata without changing entry parsing."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("proof manifest must be an object")
    metadata = payload.get("metadata", {})
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise ValueError("proof manifest metadata must be an object")
    # ``example_policy`` is intentionally copied as data; callers decide
    # whether a strict policy applies to this manifest version.
    policy = payload.get("example_policy", metadata.get("example_policy", {}))
    if policy is None:
        policy = {}
    if not isinstance(policy, dict):
        raise ValueError("proof manifest example_policy must be an object")
    return {
        "contract_id": str(payload.get("contract_id", "kjds-formal-proof-manifest-v1")),
        "example_policy": dict(policy),
        "metadata": dict(metadata),
    }


def validate_manifest_examples(
    entries: tuple[ProofEntry, ...],
    *,
    require_positive: bool = True,
    require_counterexample: bool = True,
) -> tuple[str, ...]:
    """Check the local positive/counterexample obligations for each theorem.

    Legacy manifests can call this with both flags disabled.  The versioned
    manifest policy used by production planning enables both checks before a
    theorem can be admitted.
    """

    errors: list[str] = []
    for entry in entries:
        if require_positive and not entry.positive_refs:
            errors.append(f"positive_example_missing:{entry.stable_key}")
        if require_counterexample and not entry.counterexample_refs:
            errors.append(f"counterexample_missing:{entry.stable_key}")
    return tuple(errors)


def toolchain_status() -> dict[str, Any]:
    lean = shutil.which("lean")
    lake = shutil.which("lake")
    return {
        "status": "ready" if lean and lake else "blocked",
        "lean": lean,
        "lake": lake,
        "reason": None if lean and lake else "lean_toolchain_unavailable",
    }


def validate_manifest_modules(entries: tuple[ProofEntry, ...], *, root: str | Path = ".") -> tuple[str, ...]:
    """Return deterministic module errors without claiming a proof build."""
    base = Path(root)
    errors: list[str] = []
    for entry in entries:
        module = (base / entry.module).resolve()
        try:
            module.relative_to(base.resolve())
        except ValueError:
            errors.append(f"module_outside_root:{entry.stable_key}:{entry.module}")
            continue
        if not module.is_file():
            errors.append(f"missing_module:{entry.stable_key}:{entry.module}")
            continue
        source = module.read_text(encoding="utf-8")
        if "sorry" in source.lower():
            errors.append(f"untrusted_sorry:{entry.stable_key}:{entry.module}")
        declaration = re.compile(
            rf"(?m)^\s*(?:theorem|lemma)\s+{re.escape(entry.theorem)}\b"
        )
        if declaration.search(source) is None:
            errors.append(f"missing_theorem:{entry.stable_key}:{entry.theorem}")
    return tuple(errors)


def validate_manifest_artifacts(
    entries: tuple[ProofEntry, ...], *, root: str | Path = "."
) -> tuple[str, ...]:
    """Validate optional receipt digests before a proof can be admitted.

    An artifact digest in the manifest is a claim about a concrete file.  A
    missing file or changed bytes must invalidate that entry rather than being
    treated as metadata-only.  Paths are constrained to the manifest root to
    keep verification deterministic and prevent out-of-scope reads.
    """
    base = Path(root).resolve()
    errors: list[str] = []
    for entry in entries:
        if entry.artifact_sha256 is None:
            continue
        artifact = (base / entry.module).resolve()
        try:
            artifact.relative_to(base)
        except ValueError:
            errors.append(f"artifact_outside_root:{entry.stable_key}:{entry.module}")
            continue
        if not artifact.is_file():
            errors.append(f"missing_artifact:{entry.stable_key}:{entry.module}")
            continue
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        if digest.lower() != entry.artifact_sha256.lower():
            errors.append(f"artifact_hash_mismatch:{entry.stable_key}:{entry.module}")
    return tuple(errors)


def manifest_sha256(
    entries: tuple[ProofEntry, ...], *, metadata: Mapping[str, Any] | None = None
) -> str:
    canonical = [entry.__dict__ if hasattr(entry, "__dict__") else {
        "stable_key": entry.stable_key,
        "theorem": entry.theorem,
        "module": entry.module,
        "status": entry.status,
        "assumptions": entry.assumptions,
        "evidence_refs": entry.evidence_refs,
        "artifact_sha256": entry.artifact_sha256,
        "positive_refs": entry.positive_refs,
        "counterexample_refs": entry.counterexample_refs,
        "mutation_test_refs": entry.mutation_test_refs,
    } for entry in entries]
    payload: Any = canonical if metadata is None else {
        "entries": canonical,
        "metadata": metadata,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=list, separators=(",", ":")).encode()
    ).hexdigest()


__all__ = [
    "ProofEntry",
    "ProofStatus",
    "load_manifest",
    "manifest_metadata",
    "manifest_sha256",
    "toolchain_status",
    "validate_manifest_artifacts",
    "validate_manifest_examples",
    "validate_manifest_modules",
]
