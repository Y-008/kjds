"""Governed deterministic blueprint compilation and FFmpeg execution.

The workspace coordinates existing Job, Product/ContentAsset, Evidence, and
media authorities. It does not become a second truth owner or grant listing
eligibility.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .media_connectors import (
    INTERNAL_BLUEPRINT_PROVIDER,
    RUNTIME_FFMPEG_PROVIDER,
    MediaConnectorContract,
    RuntimeOwnedProviderDescriptor,
)
from .media_jobs import (
    EDITING_MAX_SCENE_DURATION_MS,
    EDITING_MAX_TIMELINE_DURATION_MS,
    EDITING_TARGET_CHANNELS,
    FFMPEG_RENDER_PROFILE_SHA256,
    MediaJobBindingProjection,
    MediaJobProjection,
    MediaJobResultReceiptProjection,
    canonical_json,
    derive_blueprint_render_plan,
    sha256_bytes,
)
from .media_workbench import FfmpegMediaWorker
from .security import Principal

BLUEPRINT_CONTRACT = "kjds-editing-blueprint-v1"
BLUEPRINT_VERSION = "1.0.0"
SOURCE_CONTRACT = "kjds-editing-source-receipt-v1"
SOURCE_VERSION = "1.0.0"
FFMPEG_PROVIDER = "ffmpeg"
SUPPORTED_TOOLS = frozenset({"media.video_blueprint", "media.video_render"})
SAFE_OUTCOME_STATUSES = frozenset(
    {"PROPOSAL_ONLY", "EXECUTED", "READBACK", "BLOCKED"}
)
ALLOWED_TRANSITIONS = frozenset({"cut", "fade", "crossfade"})
PROVIDER_ATTEMPT_STALE_AFTER = timedelta(minutes=25)
_HEX64 = frozenset("0123456789abcdef")
_SOURCE_FIELDS = frozenset(
    {
        "contract_id",
        "contract_version",
        "scope",
        "scope_binding_sha256",
        "rights_status",
        "product_id",
        "campaign_asset_refs",
        "reference_asset_refs",
        "input_artifacts",
        "analysis_receipt",
        "source_snapshot_sha256",
        "scenes",
        "audio_asset_ref",
        "subtitle_asset_ref",
        "target_channels",
        "render_profile_sha256",
        "editing_blueprint",
        "editing_blueprint_sha256",
    }
)
_SCOPE_FIELDS = frozenset(
    {"tenant_ref", "entity_ref", "store_ref", "authority_sha256", "subject_actor_id"}
)
_RECEIPT_FIELDS = frozenset(
    {
        "contract_id",
        "source_snapshot_sha256",
        "semantic_sha256",
        "observed_at",
        "evidence_ref",
        "evidence_sha256",
        "source_video_artifacts",
    }
)
_SOURCE_ARTIFACT_FIELDS = frozenset(
    {"content_asset_ref", "evidence_ref", "evidence_sha256"}
)
_SCENE_FIELDS = frozenset(
    {
        "scene_id",
        "source_asset_ref",
        "source_start_ms",
        "source_end_ms",
        "timeline_start_ms",
        "timeline_end_ms",
        "transition",
        "caption_ref",
    }
)
_FORBIDDEN_KEY_PARTS = frozenset(
    {
        "authorization",
        "credential",
        "password",
        "secret",
        "token",
        "prompt",
        "command",
        "raw",
        "blob",
        "providerresponse",
        "payload",
    }
)
_OPAQUE_REF_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:/-"
)
_BASE64_LIKE = re.compile(r"^[A-Za-z0-9+/=_-]{64,}$")
_SENSITIVE_VALUE_MARKERS = (
    "authorization:",
    "bearer ",
    "oauth_token",
    "provider_response",
    "provider raw",
    "private-body",
)


class EditingBlueprintError(ValueError):
    """Stable, non-sensitive contract failure."""


@dataclass(frozen=True, slots=True)
class EditingBlueprintOutcome:
    status: str
    job_ref: str
    tool_name: str
    provider: str
    blueprint_sha256: str | None
    render_plan_sha256: str | None
    artifact_evidence_refs: tuple[str, ...]
    content_asset_ref: str | None
    result_state: str | None
    result_kind: str | None
    blockers: tuple[str, ...]
    automatic_retry: bool
    automatic_failover: bool
    external_write_allowed: bool
    listing_eligible: bool


def _text(value: Any, name: str, *, maximum: int = 500) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise EditingBlueprintError(f"editing_blueprint_{name}_invalid")
    return value.strip()


def _hex(value: Any, name: str) -> str:
    normalized = _text(value, name, maximum=64).lower()
    if len(normalized) != 64 or any(char not in _HEX64 for char in normalized):
        raise EditingBlueprintError(f"editing_blueprint_{name}_invalid")
    return normalized


def _safe_tree(value: Any, *, depth: int = 0) -> None:
    if depth > 16:
        raise EditingBlueprintError("editing_blueprint_source_too_deep")
    if value is None or isinstance(value, (bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise EditingBlueprintError("editing_blueprint_source_non_finite")
        return
    if isinstance(value, str):
        lowered = value.strip().lower()
        compact = value.strip()
        if any(marker in lowered for marker in _SENSITIVE_VALUE_MARKERS):
            raise EditingBlueprintError("editing_blueprint_sensitive_value_forbidden")
        if len(compact) > 512 or lowered.startswith("data:") or lowered.startswith(("{", "[")):
            raise EditingBlueprintError("editing_blueprint_raw_value_forbidden")
        if _BASE64_LIKE.fullmatch(compact) and not (
            len(compact) == 64 and all(char in _HEX64 for char in compact.lower())
        ) and not any(marker in compact for marker in ("://", ":", "/", ".")):
            raise EditingBlueprintError("editing_blueprint_opaque_value_invalid")
        return
    if isinstance(value, list):
        if len(value) > 200:
            raise EditingBlueprintError("editing_blueprint_source_collection_too_large")
        for item in value:
            _safe_tree(item, depth=depth + 1)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise EditingBlueprintError("editing_blueprint_source_key_invalid")
            normalized = "".join(char for char in key.lower() if char.isalnum())
            if any(part in normalized for part in _FORBIDDEN_KEY_PARTS):
                raise EditingBlueprintError("editing_blueprint_raw_field_forbidden")
            _safe_tree(item, depth=depth + 1)
        return
    raise EditingBlueprintError("editing_blueprint_source_type_invalid")


def source_snapshot_sha256(source: Mapping[str, Any]) -> str:
    """Seal source semantics without recursively hashing the seal itself."""

    receipt = source["analysis_receipt"]
    content = {
        "contract_id": source["contract_id"],
        "contract_version": source["contract_version"],
        "scope": source["scope"],
        "scope_binding_sha256": source["scope_binding_sha256"],
        "rights_status": source["rights_status"],
        "product_id": source["product_id"],
        "campaign_asset_refs": source["campaign_asset_refs"],
        "reference_asset_refs": source["reference_asset_refs"],
        "input_artifacts": source["input_artifacts"],
        "analysis_receipt": {
            "contract_id": receipt["contract_id"],
            "semantic_sha256": receipt["semantic_sha256"],
            "observed_at": receipt["observed_at"],
            "evidence_ref": receipt["evidence_ref"],
            "evidence_sha256": receipt["evidence_sha256"],
            "source_video_artifacts": receipt["source_video_artifacts"],
        },
        "scenes": source["scenes"],
        "audio_asset_ref": source.get("audio_asset_ref"),
        "subtitle_asset_ref": source.get("subtitle_asset_ref"),
        "target_channels": source.get("target_channels", []),
        "render_profile_sha256": source.get("render_profile_sha256"),
        "editing_blueprint": source.get("editing_blueprint"),
        "editing_blueprint_sha256": source.get("editing_blueprint_sha256"),
    }
    return sha256_bytes(canonical_json(content))


def analysis_receipt_snapshot_sha256(receipt: Mapping[str, Any]) -> str:
    return sha256_bytes(
        canonical_json(
            {
                "contract_id": receipt["contract_id"],
                "semantic_sha256": receipt["semantic_sha256"],
                "observed_at": receipt["observed_at"],
                "evidence_ref": receipt["evidence_ref"],
                "evidence_sha256": receipt["evidence_sha256"],
                "source_video_artifacts": receipt["source_video_artifacts"],
            }
        )
    )


class GovernedEditingBlueprintWorkspace:
    """Compile a source receipt into a fixed FFmpeg-only editing plan."""

    def __init__(
        self,
        *,
        jobs: Any,
        product_content: Any,
        evidence: Any,
        media_workbench: Any,
        ffmpeg_adapter: Any,
        media_connector_contract: MediaConnectorContract,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.jobs = jobs
        self.product_content = product_content
        self.evidence = evidence
        self.media_workbench = media_workbench
        self.ffmpeg_adapter = ffmpeg_adapter
        if type(media_connector_contract) is not MediaConnectorContract:
            raise EditingBlueprintError(
                "editing_blueprint_connector_contract_invalid"
            )
        self.media_connector_contract = media_connector_contract
        self.blueprint_provider = self._admit_blueprint_provider(
            media_connector_contract.internal_runtime_provider(
                INTERNAL_BLUEPRINT_PROVIDER
            )
        )
        self.ffmpeg_provider = self._admit_ffmpeg_provider(
            media_connector_contract.internal_runtime_provider(
                RUNTIME_FFMPEG_PROVIDER
            ),
            ffmpeg_adapter,
        )
        self.clock = clock or (lambda: datetime.now(UTC))

    @staticmethod
    def _admit_blueprint_provider(
        descriptor: RuntimeOwnedProviderDescriptor,
    ) -> RuntimeOwnedProviderDescriptor:
        if (
            type(descriptor) is not RuntimeOwnedProviderDescriptor
            or descriptor.provider != "kjds_internal_blueprint_compiler"
            or descriptor.connector_ref
            != "internal://editing-blueprint-compiler-v1"
            or descriptor.binding_sha256
            != hashlib.sha256(
                b"kjds-internal-editing-blueprint-compiler-v1"
            ).hexdigest()
            or descriptor.protocol_version
            != "kjds-internal-blueprint-compiler/1"
            or descriptor.capabilities
            != frozenset({"structured_output", "vision"})
            or descriptor.deterministic is not True
            or descriptor.external_call is not False
            or descriptor.credential_required is not False
            or type(descriptor.cost_amount_minor) is not int
            or descriptor.cost_amount_minor != 0
            or descriptor.cost_currency != "USD"
            or descriptor.cost_basis
            != "internal_deterministic_compiler_no_provider_charge"
            or descriptor.enrollment_allowed is not False
            or descriptor.automatic_retry is not False
            or descriptor.automatic_failover is not False
        ):
            raise EditingBlueprintError(
                "editing_blueprint_provider_contract_invalid"
            )
        return descriptor

    @staticmethod
    def _admit_ffmpeg_provider(
        descriptor: RuntimeOwnedProviderDescriptor,
        adapter: Any,
    ) -> RuntimeOwnedProviderDescriptor:
        expected_identity = (
            "ffmpeg",
            "internal://local-ffmpeg-renderer-v1",
            hashlib.sha256(b"kjds-runtime-owned-local-ffmpeg-v1").hexdigest(),
            "kjds-local-ffmpeg/1",
        )
        if (
            type(descriptor) is not RuntimeOwnedProviderDescriptor
            or descriptor.provider != expected_identity[0]
            or descriptor.connector_ref != expected_identity[1]
            or descriptor.binding_sha256 != expected_identity[2]
            or descriptor.protocol_version != expected_identity[3]
            or descriptor.capabilities != frozenset({"video_render"})
            or descriptor.deterministic is not True
            or descriptor.external_call is not False
            or descriptor.credential_required is not False
            or type(descriptor.cost_amount_minor) is not int
            or descriptor.cost_amount_minor != 0
            or descriptor.cost_currency != "USD"
            or descriptor.cost_basis
            != "internal_deterministic_ffmpeg_no_provider_charge"
            or descriptor.enrollment_allowed is not False
            or descriptor.automatic_retry is not False
            or descriptor.automatic_failover is not False
            or type(adapter) is not FfmpegMediaWorker
            or adapter.runtime_provider_identity != expected_identity
        ):
            raise EditingBlueprintError(
                "editing_ffmpeg_runtime_provider_contract_invalid"
            )
        return descriptor

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None:
            raise EditingBlueprintError("editing_blueprint_clock_invalid")
        return value.astimezone(UTC)

    @staticmethod
    def _scope_binding(scope: Any) -> str:
        payload = {
            "tenant_ref": scope.tenant_ref,
            "entity_ref": scope.entity_ref,
            "store_ref": scope.store_ref,
            "authority_sha256": scope.authority_sha256,
            "subject_actor_id": scope.subject_actor_id,
        }
        return sha256_bytes(canonical_json(payload))

    @staticmethod
    def _hash(value: Any) -> str:
        return hashlib.sha256(canonical_json(value)).hexdigest()

    def _read_source(
        self,
        *,
        principal: Principal,
        store_ref: str,
        job_ref: str,
        scope: Any,
    ) -> Mapping[str, Any]:
        reader = getattr(self.product_content, "read_editing_source", None)
        if not callable(reader):
            raise EditingBlueprintError("editing_source_authority_not_admitted")
        validation_now = self._now()
        source = reader(
            principal=principal,
            store_ref=store_ref,
            job_ref=job_ref,
            scope=scope,
            as_of=validation_now,
        )
        if not isinstance(source, Mapping):
            raise EditingBlueprintError("editing_source_shape_invalid")
        _safe_tree(source)
        if set(source) - _SOURCE_FIELDS:
            raise EditingBlueprintError("editing_source_shape_invalid")
        required = {
            "contract_id",
            "contract_version",
            "scope",
            "scope_binding_sha256",
            "rights_status",
            "product_id",
            "campaign_asset_refs",
            "reference_asset_refs",
            "input_artifacts",
            "analysis_receipt",
            "source_snapshot_sha256",
            "scenes",
            "target_channels",
            "render_profile_sha256",
        }
        if not required <= set(source):
            raise EditingBlueprintError("editing_source_shape_invalid")
        if source["contract_id"] != SOURCE_CONTRACT or source["contract_version"] != SOURCE_VERSION:
            raise EditingBlueprintError("editing_source_contract_invalid")
        source_scope = source["scope"]
        if not isinstance(source_scope, Mapping) or set(source_scope) != _SCOPE_FIELDS:
            raise EditingBlueprintError("editing_source_scope_invalid")
        expected_scope = {
            "tenant_ref": scope.tenant_ref,
            "entity_ref": scope.entity_ref,
            "store_ref": scope.store_ref,
            "authority_sha256": scope.authority_sha256,
            "subject_actor_id": scope.subject_actor_id,
        }
        if dict(source_scope) != expected_scope or source["scope_binding_sha256"] != self._scope_binding(scope):
            raise EditingBlueprintError("editing_source_scope_binding_invalid")
        if source["rights_status"] != "approved":
            raise EditingBlueprintError("editing_source_rights_not_approved")
        if source["target_channels"] != list(EDITING_TARGET_CHANNELS):
            raise EditingBlueprintError("editing_source_target_channels_invalid")
        if source["render_profile_sha256"] != FFMPEG_RENDER_PROFILE_SHA256:
            raise EditingBlueprintError("editing_source_render_profile_invalid")
        _hex(source["scope_binding_sha256"], "scope_binding_sha256")
        _hex(source["source_snapshot_sha256"], "source_snapshot_sha256")
        _text(source["product_id"], "product_id", maximum=500)
        self._validate_analysis_receipt(source, validation_now=validation_now)
        self._validate_input_artifacts(source)
        self._validate_refs(source)
        self._validate_scenes(
            source["scenes"],
            reference_asset_refs=source["reference_asset_refs"],
        )
        if source["source_snapshot_sha256"] != source_snapshot_sha256(source):
            raise EditingBlueprintError("editing_source_snapshot_drifted")
        return source

    def _validate_analysis_receipt(
        self,
        source: Mapping[str, Any],
        *,
        validation_now: datetime,
    ) -> None:
        receipt = source["analysis_receipt"]
        if not isinstance(receipt, Mapping) or set(receipt) != _RECEIPT_FIELDS:
            raise EditingBlueprintError("editing_source_analysis_receipt_invalid")
        if receipt["contract_id"] != "kjds-reference-video-analysis-v1":
            raise EditingBlueprintError("editing_source_analysis_receipt_invalid")
        if receipt["source_snapshot_sha256"] != analysis_receipt_snapshot_sha256(
            receipt
        ):
            raise EditingBlueprintError("editing_source_analysis_receipt_invalid")
        _hex(receipt["semantic_sha256"], "analysis_semantic_sha256")
        _hex(receipt["evidence_sha256"], "analysis_evidence_sha256")
        _hex(receipt["source_snapshot_sha256"], "analysis_source_snapshot_sha256")
        evidence_ref = _text(receipt["evidence_ref"], "analysis_evidence_ref")
        if not evidence_ref.startswith("evidence://"):
            raise EditingBlueprintError("editing_source_analysis_receipt_invalid")
        artifacts = receipt["source_video_artifacts"]
        if not isinstance(artifacts, list) or not artifacts or len(artifacts) > 100:
            raise EditingBlueprintError("editing_source_analysis_receipt_invalid")
        asset_refs: set[str] = set()
        evidence_refs: set[str] = set()
        for artifact in artifacts:
            if not isinstance(artifact, Mapping) or set(artifact) != _SOURCE_ARTIFACT_FIELDS:
                raise EditingBlueprintError("editing_source_analysis_receipt_invalid")
            asset_ref = _text(artifact["content_asset_ref"], "content_asset_ref")
            artifact_evidence_ref = _text(
                artifact["evidence_ref"],
                "source_video_evidence_ref",
            )
            _hex(artifact["evidence_sha256"], "source_video_evidence_sha256")
            if (
                not asset_ref.startswith("content-asset://")
                or not artifact_evidence_ref.startswith("evidence://")
                or asset_ref in asset_refs
                or artifact_evidence_ref in evidence_refs
            ):
                raise EditingBlueprintError("editing_source_analysis_receipt_invalid")
            asset_refs.add(asset_ref)
            evidence_refs.add(artifact_evidence_ref)
        if asset_refs != set(source["reference_asset_refs"]):
            raise EditingBlueprintError("editing_source_analysis_receipt_invalid")
        expected_artifacts = [
            {
                "content_asset_ref": artifact["content_asset_ref"],
                "evidence_ref": artifact["evidence_ref"],
                "evidence_sha256": artifact["evidence_sha256"],
            }
            for artifact in source["input_artifacts"]
            if artifact["role"] == "reference_video"
        ]
        if artifacts != expected_artifacts:
            raise EditingBlueprintError("editing_source_analysis_receipt_invalid")
        observed_at = _text(receipt["observed_at"], "analysis_observed_at", maximum=80)
        try:
            observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise EditingBlueprintError("editing_source_analysis_receipt_invalid") from exc
        if observed.tzinfo is None or observed.astimezone(UTC) > validation_now:
            raise EditingBlueprintError("editing_source_analysis_receipt_invalid")

    @staticmethod
    def _validate_input_artifacts(source: Mapping[str, Any]) -> None:
        artifacts = source["input_artifacts"]
        if not isinstance(artifacts, list) or not artifacts or len(artifacts) > 300:
            raise EditingBlueprintError("editing_source_input_artifacts_invalid")
        campaign_refs = source["campaign_asset_refs"]
        reference_refs = source["reference_asset_refs"]
        if (
            not isinstance(campaign_refs, list)
            or not campaign_refs
            or len(campaign_refs) > 100
            or len(set(campaign_refs)) != len(campaign_refs)
            or not isinstance(reference_refs, list)
            or not reference_refs
            or set(campaign_refs) & set(reference_refs)
        ):
            raise EditingBlueprintError("editing_source_input_artifacts_invalid")
        expected_refs = set(campaign_refs) | set(reference_refs)
        audio_ref = source.get("audio_asset_ref")
        if audio_ref is not None:
            if audio_ref in expected_refs:
                raise EditingBlueprintError("editing_source_input_artifacts_invalid")
            expected_refs.add(audio_ref)
        actual_refs: set[str] = set()
        for artifact in artifacts:
            if not isinstance(artifact, Mapping) or set(artifact) != {
                "content_asset_ref",
                "evidence_ref",
                "evidence_sha256",
                "content_type",
                "role",
            }:
                raise EditingBlueprintError("editing_source_input_artifacts_invalid")
            asset_ref = _text(artifact["content_asset_ref"], "content_asset_ref")
            evidence_ref = _text(artifact["evidence_ref"], "evidence_ref")
            _hex(artifact["evidence_sha256"], "evidence_sha256")
            _text(artifact["content_type"], "content_type", maximum=160)
            expected_role = (
                "campaign"
                if asset_ref in campaign_refs
                else "reference_video"
                if asset_ref in reference_refs
                else "audio"
                if asset_ref == audio_ref
                else None
            )
            if (
                not asset_ref.startswith("content-asset://")
                or not evidence_ref.startswith("evidence://")
                or asset_ref in actual_refs
                or artifact["role"] != expected_role
            ):
                raise EditingBlueprintError("editing_source_input_artifacts_invalid")
            actual_refs.add(asset_ref)
        if actual_refs != expected_refs:
            raise EditingBlueprintError("editing_source_input_artifacts_invalid")

    @staticmethod
    def _validate_refs(source: Mapping[str, Any]) -> None:
        refs = source["reference_asset_refs"]
        if (
            not isinstance(refs, list)
            or not refs
            or len(refs) > 100
            or any(
                not isinstance(ref, str)
                or not ref.strip()
                or len(ref.strip()) > 500
                or any(char not in _OPAQUE_REF_CHARS for char in ref.strip())
                for ref in refs
            )
            or len({ref.strip() for ref in refs}) != len(refs)
            or any(ref != ref.strip() for ref in refs)
        ):
            raise EditingBlueprintError("editing_source_reference_refs_invalid")
        for key in ("audio_asset_ref", "subtitle_asset_ref"):
            if key in source and source[key] is not None:
                value = _text(source[key], key)
                if any(char not in _OPAQUE_REF_CHARS for char in value):
                    raise EditingBlueprintError("editing_source_reference_invalid")

    @staticmethod
    def _validate_scenes(
        scenes: Any,
        *,
        reference_asset_refs: list[str],
    ) -> None:
        if not isinstance(scenes, list) or not scenes or len(scenes) > 200:
            raise EditingBlueprintError("editing_source_scenes_invalid")
        previous_timeline_end = 0
        rendered_duration_ms = 0
        seen: set[str] = set()
        seen_captions: set[str] = set()
        admitted_refs = set(reference_asset_refs)
        consumed_refs: set[str] = set()
        for index, scene in enumerate(scenes):
            if not isinstance(scene, Mapping) or set(scene) != _SCENE_FIELDS:
                raise EditingBlueprintError("editing_source_scene_shape_invalid")
            scene_id = _text(scene["scene_id"], "scene_id", maximum=160)
            if scene_id in seen:
                raise EditingBlueprintError("editing_source_scene_duplicate")
            seen.add(scene_id)
            source_asset_ref = _text(
                scene["source_asset_ref"],
                "scene_source_asset_ref",
            )
            if (
                source_asset_ref not in admitted_refs
                or any(char not in _OPAQUE_REF_CHARS for char in source_asset_ref)
            ):
                raise EditingBlueprintError("editing_source_scene_asset_invalid")
            source_start = scene["source_start_ms"]
            source_end = scene["source_end_ms"]
            timeline_start = scene["timeline_start_ms"]
            timeline_end = scene["timeline_end_ms"]
            if (
                any(
                    isinstance(value, bool) or not isinstance(value, int)
                    for value in (
                        source_start,
                        source_end,
                        timeline_start,
                        timeline_end,
                    )
                )
                or source_start < 0
                or source_end <= source_start
                or timeline_start != previous_timeline_end
                or timeline_end <= timeline_start
                or source_end - source_start != timeline_end - timeline_start
                or source_end - source_start > EDITING_MAX_SCENE_DURATION_MS
                or timeline_end > EDITING_MAX_TIMELINE_DURATION_MS
            ):
                raise EditingBlueprintError("editing_source_scene_timeline_invalid")
            previous_timeline_end = timeline_end
            transition = _text(scene["transition"], "transition", maximum=80)
            if transition not in ALLOWED_TRANSITIONS or (
                index == 0 and transition == "crossfade"
            ) or (
                transition == "crossfade"
                and (
                    timeline_end - timeline_start <= 250
                    or rendered_duration_ms < 250
                )
            ):
                raise EditingBlueprintError("editing_source_transition_invalid")
            rendered_duration_ms += timeline_end - timeline_start
            if transition == "crossfade":
                rendered_duration_ms -= 250
            consumed_refs.add(source_asset_ref)
            caption_ref = _text(scene["caption_ref"], "caption_ref", maximum=500)
            if (
                not caption_ref.startswith("evidence://")
                or any(char not in _OPAQUE_REF_CHARS for char in caption_ref)
                or caption_ref in seen_captions
            ):
                raise EditingBlueprintError("editing_source_caption_ref_invalid")
            seen_captions.add(caption_ref)
        if consumed_refs != admitted_refs:
            raise EditingBlueprintError(
                "editing_source_scene_asset_conservation_invalid"
            )

    def _blueprint(
        self,
        *,
        job: MediaJobProjection,
        binding: MediaJobBindingProjection,
        source: Mapping[str, Any],
    ) -> tuple[dict[str, Any], str, dict[str, Any], str, str | None]:
        if binding.tool_name == "media.video_blueprint":
            content = {
                "contract_id": BLUEPRINT_CONTRACT,
                "contract_version": BLUEPRINT_VERSION,
                "job_ref": job.job_ref,
                "tool_name": binding.tool_name,
                "tool_version": binding.tool_version,
                "provider": binding.provider,
                "connector_ref": binding.connector_ref,
                "connector_binding_sha256": binding.connector_binding_sha256,
                "tool_descriptor_sha256": binding.tool_descriptor_sha256,
                "scope": dict(source["scope"]),
                "scope_binding_sha256": source["scope_binding_sha256"],
                "source_snapshot_sha256": source["source_snapshot_sha256"],
                "analysis_receipt": dict(source["analysis_receipt"]),
                "campaign_asset_refs": list(source["campaign_asset_refs"]),
                "reference_asset_refs": list(source["reference_asset_refs"]),
                "input_artifacts": list(source["input_artifacts"]),
                "scenes": source["scenes"],
                "audio_asset_ref": source.get("audio_asset_ref"),
                "subtitle_asset_ref": source.get("subtitle_asset_ref"),
                "target_channels": list(source["target_channels"]),
                "render_profile_sha256": source["render_profile_sha256"],
                "external_write_allowed": False,
                "listing_eligible": False,
            }
            blueprint_sha256 = self._hash(content)
        else:
            supplied = source.get("editing_blueprint")
            supplied_sha256 = source.get("editing_blueprint_sha256")
            if (
                not isinstance(supplied, Mapping)
                or not isinstance(supplied_sha256, str)
                or self._hash(supplied) != supplied_sha256
            ):
                raise EditingBlueprintError("editing_blueprint_seal_invalid")
            content = dict(supplied)
            blueprint_sha256 = supplied_sha256
        try:
            render_plan = derive_blueprint_render_plan(content)
        except ValueError as exc:
            raise EditingBlueprintError("editing_blueprint_contract_invalid") from exc
        render_plan_sha256 = self._hash(render_plan)
        return (
            content,
            blueprint_sha256,
            render_plan,
            render_plan_sha256,
            binding.provider,
        )

    def _validate_handoff(
        self,
        *,
        principal: Principal,
        store_ref: str,
        job_ref: str,
        source: Mapping[str, Any],
        render_plan: Mapping[str, Any],
        render_plan_sha256: str,
    ) -> None:
        plan_validator = getattr(self.ffmpeg_adapter, "validate_plan", None)
        handoff_validator = getattr(self.media_workbench, "validate_editing_handoff", None)
        if not callable(plan_validator) or not callable(handoff_validator):
            raise EditingBlueprintError("editing_execution_seams_not_admitted")
        try:
            plan_validator(
                render_plan=dict(render_plan),
                render_plan_sha256=render_plan_sha256,
                executor=FFMPEG_PROVIDER,
                reference_asset_refs=tuple(source["reference_asset_refs"]),
            )
            handoff_validator(
                principal=principal,
                store_ref=store_ref,
                job_ref=job_ref,
                reference_asset_refs=tuple(source["reference_asset_refs"]),
                render_plan_sha256=render_plan_sha256,
            )
        except Exception as exc:
            raise EditingBlueprintError("editing_handoff_not_admitted") from exc

    def _provider_attempt_is_stale(self, job: MediaJobProjection) -> bool:
        recorded_at = job.state_recorded_at
        if not isinstance(recorded_at, str):
            raise EditingBlueprintError("editing_attempt_time_missing")
        try:
            recorded = datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise EditingBlueprintError("editing_attempt_time_invalid") from exc
        if recorded.tzinfo is None:
            raise EditingBlueprintError("editing_attempt_time_invalid")
        age = self._now() - recorded.astimezone(UTC)
        if age < timedelta(0):
            raise EditingBlueprintError("editing_attempt_time_invalid")
        return age >= PROVIDER_ATTEMPT_STALE_AFTER

    def _outcome(
        self,
        *,
        status: str,
        job: MediaJobProjection,
        provider: str,
        blueprint_sha256: str | None = None,
        render_plan_sha256: str | None = None,
        receipt: MediaJobResultReceiptProjection | None = None,
        blockers: tuple[str, ...] = (),
    ) -> EditingBlueprintOutcome:
        return EditingBlueprintOutcome(
            status=status,
            job_ref=job.job_ref,
            tool_name=job.tool_name,
            provider=provider,
            blueprint_sha256=blueprint_sha256,
            render_plan_sha256=render_plan_sha256,
            artifact_evidence_refs=receipt.artifact_evidence_refs if receipt else (),
            content_asset_ref=receipt.content_asset_ref if receipt else None,
            result_state=receipt.state if receipt else None,
            result_kind=receipt.result_kind if receipt else None,
            blockers=blockers,
            automatic_retry=False,
            automatic_failover=False,
            external_write_allowed=False,
            listing_eligible=False,
        )

    def _read_or_recover_terminal(
        self,
        *,
        principal: Principal,
        store_ref: str,
        job: MediaJobProjection,
        render_plan_sha256: str,
        scope: Any,
    ) -> MediaJobResultReceiptProjection:
        del render_plan_sha256, scope
        try:
            return self.jobs.read_result_receipt(
                principal=principal,
                store_ref=store_ref,
                job_ref=job.job_ref,
            )
        except KeyError as exc:
            raise EditingBlueprintError("editing_terminal_receipt_missing") from exc

    def process(
        self,
        principal: Principal,
        store_ref: str,
        job_ref: str,
    ) -> EditingBlueprintOutcome:
        scope_before = self.jobs.current_scope(principal=principal, store_ref=store_ref)
        job, binding = self.jobs.read_bound(
            principal=principal,
            store_ref=store_ref,
            job_ref=job_ref,
        )
        scope_after = self.jobs.current_scope(principal=principal, store_ref=store_ref)
        if scope_before != scope_after:
            raise EditingBlueprintError("editing_scope_changed")
        if binding.tool_name not in SUPPORTED_TOOLS:
            raise EditingBlueprintError("editing_tool_not_supported")
        if binding.tool_name == "media.video_blueprint" and (
            binding.provider != self.blueprint_provider.provider
            or binding.connector_ref != self.blueprint_provider.connector_ref
            or binding.connector_binding_sha256
            != self.blueprint_provider.binding_sha256
        ):
            raise EditingBlueprintError("editing_provider_not_admitted")
        if binding.tool_name == "media.video_render" and (
            binding.provider != self.ffmpeg_provider.provider
            or binding.connector_ref != self.ffmpeg_provider.connector_ref
            or binding.connector_binding_sha256
            != self.ffmpeg_provider.binding_sha256
        ):
            raise EditingBlueprintError("editing_provider_not_admitted")
        source = self._read_source(
            principal=principal,
            store_ref=store_ref,
            job_ref=job_ref,
            scope=scope_after,
        )
        scope_final = self.jobs.current_scope(
            principal=principal,
            store_ref=store_ref,
        )
        if scope_final != scope_before or scope_final != scope_after:
            raise EditingBlueprintError("editing_scope_changed")
        (
            content,
            blueprint_sha256,
            render_plan,
            render_plan_sha256,
            provider,
        ) = self._blueprint(
            job=job,
            binding=binding,
            source=source,
        )
        self._validate_handoff(
            principal=principal,
            store_ref=store_ref,
            job_ref=job_ref,
            source=source,
            render_plan=render_plan,
            render_plan_sha256=render_plan_sha256,
        )
        if binding.tool_name == "media.video_blueprint":
            if self.jobs.current_scope(principal=principal, store_ref=store_ref) != scope_final:
                raise EditingBlueprintError("editing_scope_changed")
            try:
                receipt = self.jobs.record_blueprint_result(
                    principal=principal,
                    store_ref=store_ref,
                    job_ref=job_ref,
                    blueprint=content,
                    render_plan_sha256=render_plan_sha256,
                )
            except Exception as exc:
                raise EditingBlueprintError("editing_blueprint_result_not_admitted") from exc
            return self._outcome(
                status="READBACK" if job.state == "SUCCEEDED" else "EXECUTED",
                job=job,
                provider=provider,
                blueprint_sha256=blueprint_sha256,
                render_plan_sha256=render_plan_sha256,
                receipt=receipt,
            )
        blueprint = source.get("editing_blueprint")
        if blueprint is not None and (
            not isinstance(blueprint, Mapping)
            or self._hash(blueprint) != source.get("editing_blueprint_sha256")
        ):
            raise EditingBlueprintError("editing_blueprint_seal_invalid")
        if job.state in {"FAILED", "UNKNOWN_OUTCOME"}:
            raise EditingBlueprintError(
                "editing_non_success_readback_authority_not_admitted"
            )
        if job.state == "SUCCEEDED":
            receipt = self._read_or_recover_terminal(
                principal=principal,
                store_ref=store_ref,
                job=job,
                render_plan_sha256=render_plan_sha256,
                scope=scope_final,
            )
            if (
                receipt.connector_ref != binding.connector_ref
                or receipt.provider != FFMPEG_PROVIDER
                or receipt.state != job.state
            ):
                raise EditingBlueprintError("editing_readback_binding_invalid")
            if (
                receipt.result_kind != "video_artifact_evidence"
                or not receipt.artifact_evidence_refs
                or receipt.content_asset_ref is None
            ):
                raise EditingBlueprintError("editing_readback_artifact_invalid")
            if self.jobs.current_scope(principal=principal, store_ref=store_ref) != scope_final:
                raise EditingBlueprintError("editing_scope_changed")
            return self._outcome(
                status="READBACK",
                job=job,
                provider=provider,
                blueprint_sha256=blueprint_sha256,
                render_plan_sha256=render_plan_sha256,
                receipt=receipt,
            )
        if self.jobs.current_scope(principal=principal, store_ref=store_ref) != scope_final:
            raise EditingBlueprintError("editing_scope_changed")
        preflight = getattr(
            self.media_workbench, "preflight_governed_editing", None
        )
        if not callable(preflight):
            raise EditingBlueprintError("editing_preflight_not_admitted")
        try:
            preflight(
                scope=scope_final,
                source=dict(source),
                render_plan=render_plan,
                render_plan_sha256=render_plan_sha256,
                now=self._now(),
            )
        except Exception as exc:
            raise EditingBlueprintError(
                "editing_preflight_not_admitted"
            ) from exc
        if self.jobs.current_scope(
            principal=principal, store_ref=store_ref
        ) != scope_final:
            raise EditingBlueprintError("editing_scope_changed")
        claimed_job, claimed = self.jobs.claim_provider_attempt(
            principal=principal,
            store_ref=store_ref,
            job_ref=job_ref,
        )
        if claimed:
            refreshed_source = self._read_source(
                principal=principal,
                store_ref=store_ref,
                job_ref=job_ref,
                scope=scope_final,
            )
            if (
                refreshed_source["source_snapshot_sha256"]
                != source["source_snapshot_sha256"]
            ):
                raise EditingBlueprintError("editing_source_changed")
            try:
                self.media_workbench.execute_governed_editing(
                    principal=principal,
                    store_ref=store_ref,
                    job_ref=job_ref,
                    scope=scope_final,
                    source=dict(refreshed_source),
                    render_plan=render_plan,
                    render_plan_sha256=render_plan_sha256,
                    ffmpeg_adapter=self.ffmpeg_adapter,
                    result_recorder=lambda artifact_writer: self.jobs.record_render_result(
                        principal=principal,
                        store_ref=store_ref,
                        job_ref=job_ref,
                        expected_event_ordinal=claimed_job.last_event_ordinal,
                        expected_recorded_at=str(claimed_job.state_recorded_at),
                        artifact_writer=artifact_writer,
                    ),
                    now=self._now(),
                )
                receipt = self.jobs.read_result_receipt(
                    principal=principal,
                    store_ref=store_ref,
                    job_ref=job_ref,
                )
            except Exception:
                current_job, _ = self.jobs.read_bound(
                    principal=principal,
                    store_ref=store_ref,
                    job_ref=job_ref,
                )
                if current_job.state in {"SUCCEEDED", "FAILED", "UNKNOWN_OUTCOME"}:
                    receipt = self._read_or_recover_terminal(
                        principal=principal,
                        store_ref=store_ref,
                        job=current_job,
                        render_plan_sha256=render_plan_sha256,
                        scope=scope_final,
                    )
                    return self._outcome(
                        status="READBACK",
                        job=current_job,
                        provider=provider,
                        blueprint_sha256=blueprint_sha256,
                        render_plan_sha256=render_plan_sha256,
                        receipt=receipt,
                    )
                return self._outcome(
                    status="BLOCKED",
                    job=current_job,
                    provider=provider,
                    blueprint_sha256=blueprint_sha256,
                    render_plan_sha256=render_plan_sha256,
                    blockers=("provider_attempt_outcome_unverified",),
                )
            return self._outcome(
                status="EXECUTED",
                job=claimed_job,
                provider=provider,
                blueprint_sha256=blueprint_sha256,
                render_plan_sha256=render_plan_sha256,
                receipt=receipt,
            )
        elif claimed_job.state == "DISPATCHED":
            if not self._provider_attempt_is_stale(claimed_job):
                return self._outcome(
                    status="BLOCKED",
                    job=claimed_job,
                    provider=provider,
                    blueprint_sha256=blueprint_sha256,
                    render_plan_sha256=render_plan_sha256,
                    blockers=("provider_attempt_in_progress",),
                )
            return self._outcome(
                status="BLOCKED",
                job=claimed_job,
                provider=provider,
                blueprint_sha256=blueprint_sha256,
                render_plan_sha256=render_plan_sha256,
                blockers=("provider_attempt_outcome_unverified",),
            )
        raise EditingBlueprintError("editing_provider_attempt_state_invalid")
