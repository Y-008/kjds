"""Machine-readable proof manifest validation and Lean toolchain probing."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
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
                assumptions=tuple(str(item) for item in raw.get("assumptions", ())),
                evidence_refs=tuple(str(item) for item in raw.get("evidence_refs", ())),
                artifact_sha256=artifact_sha256,
            )
        )
    return tuple(entries)


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


def manifest_sha256(entries: tuple[ProofEntry, ...]) -> str:
    canonical = [entry.__dict__ if hasattr(entry, "__dict__") else {
        "stable_key": entry.stable_key,
        "theorem": entry.theorem,
        "module": entry.module,
        "status": entry.status,
        "assumptions": entry.assumptions,
        "evidence_refs": entry.evidence_refs,
        "artifact_sha256": entry.artifact_sha256,
    } for entry in entries]
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, default=list, separators=(",", ":")).encode()).hexdigest()
