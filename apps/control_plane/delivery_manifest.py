"""Governed deterministic DeliveryManifest assembly (BAS-188 first slice).

Assembles admitted media artifacts (image, video blueprint, tutorial) into a
frozen, content-addressed DeliveryManifest for a social delivery target.

The social delivery target (BAS-178 SocialCommerceIntelligenceWorkspace) is not
admitted in this slice: publish, campaign grant, readback, revoke and
kill-switch remain not_admitted and produce zero external writes.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

DELIVERY_MANIFEST_CONTRACT = "kjds-governed-delivery-manifest-v1"
DELIVERY_MANIFEST_VERSION = "1.0.0"
DELIVERY_TARGET_CONTRACT = "kjds-social-delivery-target-v1"
DELIVERY_TARGET_VERSION = "1.0.0"

SOCIAL_TARGET_PROVIDER = "social_commerce_intelligence_workspace"

# Mirror media_agent_contracts.json artifact_contract.type_specific_metadata.
ARTIFACT_KINDS = frozenset({"image", "video", "editing_blueprint", "tutorial"})
KIND_REQUIRED_METADATA = {
    "image": frozenset({"width", "height"}),
    "video": frozenset({"width", "height", "duration_ms", "encoder_manifest_sha256"}),
    "editing_blueprint": frozenset({"schema_version", "source_asset_refs"}),
    "tutorial": frozenset({"tutorial_graph_version", "capture_manifest_sha256"}),
}

SOCIAL_TARGET_ADMITTED = False

IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,159}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
SCOPE_KEYS = frozenset({"tenant_ref", "entity_ref", "store_ref"})

SENSITIVE_MARKERS = (
    "authorization:",
    "bearer ",
    "cookie=",
    "api_key=",
    "access_token=",
    "refresh_token=",
    "client_secret=",
    "password=",
    "private_key=",
    "sk-",
)

SAFE_OUTCOME_STATUSES = frozenset({"COMPILED", "PROPOSAL_ONLY", "BLOCKED", "INVALIDATED", "STALE"})

ZERO_AUTHORITY_KEYS = frozenset(
    {
        "formal_fact",
        "finance_entry",
        "approval",
        "permit",
        "pilot",
        "outbox",
        "canonical_graph_write",
        "dependency_install",
        "network",
        "external_write",
    }
)


class DeliveryManifestError(ValueError):
    """Stable, non-sensitive contract failure for delivery manifest assembly."""


@dataclass(frozen=True)
class DeliveryArtifactRef:
    kind: str
    artifact_ref: str
    contract_id: str
    contract_version: str
    sha256: str
    metadata: tuple[tuple[str, Any], ...]
    depends_on: tuple[str, ...]


@dataclass(frozen=True)
class DeliveryTargetDescriptor:
    channel_ref: str
    contract_id: str
    contract_version: str
    provider: str
    admitted: bool
    external_write_allowed: bool


@dataclass(frozen=True)
class DeliveryManifestOutcome:
    status: str
    reason_code: str
    manifest_sha256: str
    delivery_target_admitted: bool
    external_write_allowed: bool
    listing_eligible: bool
    artifacts: tuple[DeliveryArtifactRef, ...]
    zero_authority: dict[str, bool]


def _text(value: Any, name: str, *, maximum: int = 300) -> str:
    if not isinstance(value, str) or not value:
        raise DeliveryManifestError(f"{name}_invalid")
    if len(value) > maximum:
        raise DeliveryManifestError(f"{name}_too_long")
    return value


def _hex64(value: Any, name: str) -> str:
    text = _text(value, name, maximum=64)
    if len(text) != 64 or HEX64.fullmatch(text) is None:
        raise DeliveryManifestError(f"{name}_invalid")
    return text


def _token(value: Any, name: str) -> str:
    text = _text(value, name, maximum=160)
    if IDEMPOTENCY_PATTERN.fullmatch(text) is None:
        raise DeliveryManifestError(f"{name}_invalid")
    return text


def _safe_tree(value: Any, *, depth: int = 0) -> None:
    if depth > 16:
        raise DeliveryManifestError("input_nesting_too_deep")
    if isinstance(value, str):
        lowered = value.lower()
        if any(marker in lowered for marker in SENSITIVE_MARKERS):
            raise DeliveryManifestError("sensitive_value_rejected")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise DeliveryManifestError("input_key_invalid")
            _safe_tree(child, depth=depth + 1)
        return
    if isinstance(value, (list, tuple)):
        for child in value:
            _safe_tree(child, depth=depth + 1)
        return
    if value is None or isinstance(value, (bool, int, float)):
        return
    raise DeliveryManifestError("input_type_invalid")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


class GovernedDeliveryManifestWorkspace:
    """Deterministic, exact-scope media delivery manifest assembler (BAS-188)."""

    def __init__(self, *, clock: Any = None) -> None:
        self.clock = clock or (lambda: datetime.now(UTC))
        self.social_target = self._admit_social_target()

    def _admit_social_target(self) -> DeliveryTargetDescriptor:
        return DeliveryTargetDescriptor(
            channel_ref="social://delivery-target-v1",
            contract_id=DELIVERY_TARGET_CONTRACT,
            contract_version=DELIVERY_TARGET_VERSION,
            provider=SOCIAL_TARGET_PROVIDER,
            admitted=SOCIAL_TARGET_ADMITTED,
            external_write_allowed=False,
        )

    def _validate_scope(self, scope: Any) -> dict[str, str]:
        if not isinstance(scope, Mapping):
            raise DeliveryManifestError("scope_invalid")
        extra = set(scope.keys()) - SCOPE_KEYS
        if extra:
            raise DeliveryManifestError("scope_unknown_key")
        missing = SCOPE_KEYS - set(scope.keys())
        if missing:
            raise DeliveryManifestError("scope_missing_key")
        return {
            "tenant_ref": _token(scope.get("tenant_ref"), "tenant_ref"),
            "entity_ref": _token(scope.get("entity_ref"), "entity_ref"),
            "store_ref": _token(scope.get("store_ref"), "store_ref"),
        }

    def _validate_metadata(self, kind: str, metadata: Any) -> tuple[tuple[str, Any], ...]:
        if not isinstance(metadata, Mapping):
            raise DeliveryManifestError("metadata_invalid")
        required = KIND_REQUIRED_METADATA[kind]
        missing = required - set(metadata.keys())
        if missing:
            raise DeliveryManifestError("metadata_missing_key")
        _safe_tree(dict(metadata))
        normalized: list[tuple[str, Any]] = []
        for key in sorted(metadata.keys()):
            value = metadata[key]
            if isinstance(value, (list, tuple)):
                value = tuple(value)
            normalized.append((str(key), value))
        return tuple(normalized)

    def _validate_artifacts(self, artifact_refs: Any) -> list[DeliveryArtifactRef]:
        if not isinstance(artifact_refs, list) or not artifact_refs:
            raise DeliveryManifestError("artifact_refs_invalid")
        artifacts: list[DeliveryArtifactRef] = []
        seen_refs: set[str] = set()
        for raw in artifact_refs:
            if not isinstance(raw, Mapping):
                raise DeliveryManifestError("artifact_invalid")
            kind = _text(raw.get("kind"), "kind", maximum=40)
            if kind not in ARTIFACT_KINDS:
                raise DeliveryManifestError("artifact_kind_not_recognized")
            artifact_ref = _token(raw.get("artifact_ref"), "artifact_ref")
            if artifact_ref in seen_refs:
                raise DeliveryManifestError("duplicate_artifact_ref")
            seen_refs.add(artifact_ref)
            contract_id = _text(raw.get("contract_id"), "contract_id", maximum=160)
            contract_version = _text(raw.get("contract_version"), "contract_version", maximum=40)
            sha256 = _hex64(raw.get("sha256"), "artifact_sha256")
            metadata = self._validate_metadata(kind, raw.get("metadata"))
            depends_on = raw.get("depends_on", [])
            if not isinstance(depends_on, list):
                raise DeliveryManifestError("depends_on_invalid")
            normalized_deps: list[str] = []
            for dep in depends_on:
                text = _token(dep, "depends_on")
                if text not in normalized_deps:
                    normalized_deps.append(text)
            artifacts.append(
                DeliveryArtifactRef(
                    kind=kind,
                    artifact_ref=artifact_ref,
                    contract_id=contract_id,
                    contract_version=contract_version,
                    sha256=sha256,
                    metadata=metadata,
                    depends_on=tuple(normalized_deps),
                )
            )
        return artifacts

    def _topological_order(self, artifacts: list[DeliveryArtifactRef]) -> list[DeliveryArtifactRef]:
        by_ref = {artifact.artifact_ref: artifact for artifact in artifacts}
        indegree = {artifact.artifact_ref: 0 for artifact in artifacts}
        children: dict[str, list[str]] = {artifact.artifact_ref: [] for artifact in artifacts}
        for artifact in artifacts:
            for dep in artifact.depends_on:
                if dep == artifact.artifact_ref:
                    raise DeliveryManifestError("self_dependency")
                if dep not in by_ref:
                    raise DeliveryManifestError("dependency_unknown")
                children[dep].append(artifact.artifact_ref)
                indegree[artifact.artifact_ref] += 1
        available = sorted(ref for ref, degree in indegree.items() if degree == 0)
        order: list[DeliveryArtifactRef] = []
        while available:
            ref = available.pop(0)
            order.append(by_ref[ref])
            for child in children[ref]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    available.append(child)
                    available.sort()
        if len(order) != len(artifacts):
            raise DeliveryManifestError("dependency_cycle")
        return order

    def _validate_delivery_target(self, delivery_target: Any) -> DeliveryTargetDescriptor:
        if delivery_target is None:
            return self.social_target
        if not isinstance(delivery_target, Mapping):
            raise DeliveryManifestError("delivery_target_invalid")
        channel_ref = _token(delivery_target.get("channel_ref"), "channel_ref")
        contract_id = _text(delivery_target.get("contract_id"), "contract_id", maximum=160)
        contract_version = _text(delivery_target.get("contract_version"), "contract_version", maximum=40)
        _safe_tree(dict(delivery_target))
        return DeliveryTargetDescriptor(
            channel_ref=channel_ref,
            contract_id=contract_id,
            contract_version=contract_version,
            provider=SOCIAL_TARGET_PROVIDER,
            admitted=self.social_target.admitted,
            external_write_allowed=False,
        )

    def _zero_authority(self) -> dict[str, bool]:
        return {key: False for key in sorted(ZERO_AUTHORITY_KEYS)}

    def assemble(
        self,
        *,
        scope: dict[str, str],
        as_of: datetime,
        artifact_refs: list[dict[str, Any]],
        delivery_target: dict[str, Any] | None = None,
        idempotency_key: str,
    ) -> DeliveryManifestOutcome:
        if not isinstance(as_of, datetime):
            raise DeliveryManifestError("as_of_invalid")
        normalized_scope = self._validate_scope(scope)
        _token(idempotency_key, "idempotency_key")
        _safe_tree(
            {
                "scope": normalized_scope,
                "artifact_refs": artifact_refs,
                "delivery_target": delivery_target,
                "idempotency_key": idempotency_key,
            }
        )

        artifacts = self._validate_artifacts(artifact_refs)
        ordered = self._topological_order(artifacts)
        target = self._validate_delivery_target(delivery_target)

        manifest_document = {
            "contract_id": DELIVERY_MANIFEST_CONTRACT,
            "contract_version": DELIVERY_MANIFEST_VERSION,
            "scope": normalized_scope,
            "as_of": as_of.isoformat(),
            "delivery_target": {
                "channel_ref": target.channel_ref,
                "contract_id": target.contract_id,
                "contract_version": target.contract_version,
                "admitted": target.admitted,
            },
            "idempotency_key": idempotency_key,
            "artifacts": [
                {
                    "kind": artifact.kind,
                    "artifact_ref": artifact.artifact_ref,
                    "contract_id": artifact.contract_id,
                    "contract_version": artifact.contract_version,
                    "sha256": artifact.sha256,
                    "metadata": dict(artifact.metadata),
                    "depends_on": list(artifact.depends_on),
                }
                for artifact in ordered
            ],
        }
        manifest_sha256 = _hash(manifest_document)

        reason_code = (
            "social_delivery_target_not_admitted"
            if not target.admitted
            else "assembled"
        )

        return DeliveryManifestOutcome(
            status="COMPILED" if target.admitted else "PROPOSAL_ONLY",
            reason_code=reason_code,
            manifest_sha256=manifest_sha256,
            delivery_target_admitted=target.admitted,
            external_write_allowed=target.external_write_allowed,
            listing_eligible=False,
            artifacts=tuple(ordered),
            zero_authority=self._zero_authority(),
        )

    def readback(
        self,
        outcome: DeliveryManifestOutcome,
        *,
        observed_manifest_sha256: str | None = None,
    ) -> dict[str, Any]:
        if observed_manifest_sha256 is None:
            return {"manifest_sha256": outcome.manifest_sha256, "readback_state": "PENDING", "integrity_ok": True}
        observed = _hex64(observed_manifest_sha256, "observed_manifest_sha256")
        integrity_ok = observed == outcome.manifest_sha256
        return {
            "manifest_sha256": outcome.manifest_sha256,
            "readback_state": "VERIFIED" if integrity_ok else "INVALIDATED",
            "integrity_ok": integrity_ok,
        }

    def invalidate(self, outcome: DeliveryManifestOutcome, *, reason: str) -> DeliveryManifestOutcome:
        _text(reason, "invalidation_reason", maximum=200)
        return DeliveryManifestOutcome(
            status="INVALIDATED",
            reason_code=reason,
            manifest_sha256=outcome.manifest_sha256,
            delivery_target_admitted=outcome.delivery_target_admitted,
            external_write_allowed=outcome.external_write_allowed,
            listing_eligible=outcome.listing_eligible,
            artifacts=outcome.artifacts,
            zero_authority=outcome.zero_authority,
        )

    def mark_stale(self, outcome: DeliveryManifestOutcome, *, reason: str) -> DeliveryManifestOutcome:
        _text(reason, "stale_reason", maximum=200)
        return DeliveryManifestOutcome(
            status="STALE",
            reason_code=reason,
            manifest_sha256=outcome.manifest_sha256,
            delivery_target_admitted=outcome.delivery_target_admitted,
            external_write_allowed=outcome.external_write_allowed,
            listing_eligible=outcome.listing_eligible,
            artifacts=outcome.artifacts,
            zero_authority=outcome.zero_authority,
        )


__all__ = [
    "DeliveryArtifactRef",
    "DeliveryManifestError",
    "DeliveryManifestOutcome",
    "DeliveryTargetDescriptor",
    "GovernedDeliveryManifestWorkspace",
    "DELIVERY_MANIFEST_CONTRACT",
    "DELIVERY_MANIFEST_VERSION",
]
