"""Durable, proposal-only media job core for BAS-183 phase A.

This module owns the durable header/event/link contract only. Public HTTP/SSE,
provider dispatch, usage settlement, and runtime wiring are deliberately later
phases and are not imported here.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import new_id
from .evidence import EvidenceBlobRow, EvidenceGrade, EvidenceRecordRow, EvidenceService
from .security import Principal
from .sql_repository import Base, ContentAssetRow, ProductRow

MEDIA_JOB_STATES = frozenset(
    {
        "QUEUED",
        "DISPATCHED",
        "RUNNING",
        "UPLOADING",
        "SUCCEEDED",
        "LOGIN_REQUIRED",
        "LIMITED",
        "FAILED",
        "CANCELLED",
        "UNKNOWN_OUTCOME",
    }
)
TERMINAL_STATES = frozenset({"SUCCEEDED", "FAILED", "CANCELLED", "UNKNOWN_OUTCOME"})
EVENT_STREAM = "job_state"
MEDIA_JOB_TRANSITIONS = {
    "QUEUED": frozenset({"DISPATCHED", "CANCELLED", "LIMITED", "LOGIN_REQUIRED"}),
    "DISPATCHED": frozenset({"RUNNING", "FAILED", "UNKNOWN_OUTCOME"}),
    "RUNNING": frozenset({"UPLOADING", "FAILED", "UNKNOWN_OUTCOME"}),
    "UPLOADING": frozenset({"SUCCEEDED", "FAILED", "UNKNOWN_OUTCOME"}),
    "LOGIN_REQUIRED": frozenset(
        {"DISPATCHED", "RUNNING", "FAILED", "UNKNOWN_OUTCOME"}
    ),
    "LIMITED": frozenset(
        {"DISPATCHED", "RUNNING", "FAILED", "UNKNOWN_OUTCOME"}
    ),
}
MEDIA_JOB_SAFE_REASON_BY_STATE = {
    "QUEUED": None,
    "DISPATCHED": None,
    "RUNNING": None,
    "UPLOADING": None,
    "SUCCEEDED": None,
    "LOGIN_REQUIRED": "connector_login_required",
    "LIMITED": "settled_entitlement_unavailable",
    "FAILED": "provider_failed",
    "CANCELLED": "cancelled_by_request",
    "UNKNOWN_OUTCOME": "provider_outcome_unknown",
}
EVENT_FUTURE_TOLERANCE = timedelta(minutes=5)
REQUEST_SOURCE = "governed-media-job-request"
REQUEST_CONTRACT = "kjds-governed-media-job-request-v1"
COMMANDER_REQUEST_CONTRACT = "kjds-commander-media-job-request-v1"
TOOL_DESCRIPTOR_CONTRACT = "kjds-media-tool-descriptor-seal-v1"
TOOL_DESCRIPTOR_SOURCE = "governed-media-job-tool-descriptor"
TOOL_DESCRIPTOR_EVIDENCE_CONTRACT = "kjds-media-tool-descriptor-evidence-v1"
CAMPAIGN_BRIEF_CONTRACT = "kjds-campaign-brief-v1"
CAMPAIGN_BRIEF_VERSION = "1.0.0"
RESULT_RECEIPT_CONTRACT = "kjds-governed-media-job-result-v1"
BLUEPRINT_COMPILER_PROVIDER = "kjds_internal_blueprint_compiler"
BLUEPRINT_COMPILER_CONNECTOR_REF = "internal://editing-blueprint-compiler-v1"
BLUEPRINT_COMPILER_CONNECTOR_BINDING_SHA256 = hashlib.sha256(
    b"kjds-internal-editing-blueprint-compiler-v1"
).hexdigest()
FFMPEG_RENDER_PROFILE = {
    "contract_id": "kjds-ffmpeg-render-profile-v1",
    "executor": "ffmpeg",
    "template_id": "kjds-ffmpeg-product-video-v1",
    "target_channels": ["ozon"],
    "aspect_ratios": ["9:16", "1:1", "16:9"],
    "video_codec": "libx264",
    "pixel_format": "yuv420p",
    "frame_rate": 30,
    "audio_codec": "aac",
}
FFMPEG_RENDER_PROFILE_SHA256 = hashlib.sha256(
    json.dumps(
        FFMPEG_RENDER_PROFILE,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
).hexdigest()
MAX_GOVERNED_RENDER_OUTPUT_BYTES = 256 * 1024 * 1024
MAX_GOVERNED_RENDER_OUTPUT_TOTAL_BYTES = 512 * 1024 * 1024
EDITING_TARGET_CHANNELS = ("ozon",)
GOVERNED_RENDER_RATIOS = ("1:1", "16:9", "9:16")
EDITING_TARGET_LOCALE = "ru-RU"
EDITING_MAX_SCENE_DURATION_MS = 60_000
EDITING_MAX_TIMELINE_DURATION_MS = 300_000
WORKER_INPUT_CONTRACT = "kjds-governed-media-job-worker-input-v1"
WORKER_INPUT_SOURCE = "governed-media-job-worker-input"
RESULT_RECEIPT_TERMINAL_STATES = frozenset(
    {"SUCCEEDED", "FAILED", "UNKNOWN_OUTCOME"}
)
RESULT_RECEIPT_ADMITTED_STATES = frozenset({"SUCCEEDED"})
RESULT_KIND_BY_STATE = {
    "SUCCEEDED": frozenset(
        {"editing_blueprint_evidence", "video_artifact_evidence", "tutorial_graph_and_media_evidence"}
    ),
    "FAILED": frozenset({"provider_failure"}),
    "UNKNOWN_OUTCOME": frozenset({"unknown_outcome_readback"}),
}
_COMMANDER_REQUEST_FIELDS = frozenset(
    {
        "contract_id",
        "tool_name",
        "tool_version",
        "project_ref",
        "brief_ref",
        "campaign_brief_sha256",
        "provider",
        "connector_ref",
        "connector_binding_sha256",
        "idempotency_sha256",
        "output_contract",
        "tool_descriptor_sha256",
        "tool_inputs_sha256",
        "tool_input_ref_count",
        "safe_reason_codes",
    }
)
_CAMPAIGN_BRIEF_CONTENT_FIELDS = frozenset(
    {
        "contract_id",
        "contract_version",
        "project_ref",
        "graph_snapshot_sha256",
        "tenant_ref",
        "entity_ref",
        "store_ref",
        "authority_sha256",
        "subject_actor_id",
        "scope_binding_sha256",
        "objective",
        "audiences",
        "channel",
        "constraints",
        "content_asset_refs",
    }
)
_WORKER_INPUT_FIELDS = frozenset(
    {
        "contract_id",
        "tool_name",
        "tool_version",
        "project_ref",
        "brief_ref",
        "campaign_content_asset_refs",
        "editing_blueprint_ref",
        "reference_asset_refs",
        "source_asset_refs",
        "audio_asset_refs",
        "target_channels",
        "analysis_evidence_ref",
        "analysis_contract_sha256",
        "render_profile_sha256",
    }
)
_TOOL_DESCRIPTOR_FIELDS = frozenset(
    {
        "contract_id",
        "registry_sha256",
        "tool_name",
        "tool_version",
        "capabilities",
        "cost_upper_bound",
        "output_contract",
        "provider",
        "connector_ref",
        "connector_binding_sha256",
    }
)


def _validate_json(value: Any, *, depth: int = 0) -> None:
    if depth > 32:
        raise ValueError("media_job_request_too_deep")
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("media_job_request_non_finite")
        return
    if isinstance(value, list):
        for item in value:
            _validate_json(item, depth=depth + 1)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise ValueError("media_job_request_key_invalid")
            _validate_json(item, depth=depth + 1)
        return
    raise ValueError("media_job_request_value_invalid")


def canonical_json(value: Any) -> bytes:
    _validate_json(value)
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(encoded) > 1_048_576:
        raise ValueError("media_job_request_too_large")
    return encoded


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def validate_governed_render_output_bytes(contents: Sequence[bytes]) -> None:
    aggregate = 0
    if not isinstance(contents, Sequence) or isinstance(
        contents, (bytes, bytearray, str)
    ):
        raise ValueError("media_job_render_output_invalid")
    for content in contents:
        if (
            not isinstance(content, bytes)
            or len(content) < 12
            or content[4:8] != b"ftyp"
            or len(content) > MAX_GOVERNED_RENDER_OUTPUT_BYTES
        ):
            raise ValueError("media_job_render_output_invalid")
        aggregate += len(content)
    if not contents or aggregate > MAX_GOVERNED_RENDER_OUTPUT_TOTAL_BYTES:
        raise ValueError("media_job_render_output_invalid")


_BLUEPRINT_SCOPE_FIELDS = frozenset(
    {"tenant_ref", "entity_ref", "store_ref", "authority_sha256", "subject_actor_id"}
)
_BLUEPRINT_ANALYSIS_FIELDS = frozenset(
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
_BLUEPRINT_SCENE_FIELDS = frozenset(
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
_BLUEPRINT_FIELDS = frozenset(
    {
        "contract_id",
        "contract_version",
        "job_ref",
        "tool_name",
        "tool_version",
        "provider",
        "connector_ref",
        "connector_binding_sha256",
        "tool_descriptor_sha256",
        "scope",
        "scope_binding_sha256",
        "source_snapshot_sha256",
        "analysis_receipt",
        "campaign_asset_refs",
        "reference_asset_refs",
        "input_artifacts",
        "scenes",
        "audio_asset_ref",
        "subtitle_asset_ref",
        "target_channels",
        "render_profile_sha256",
        "external_write_allowed",
        "listing_eligible",
    }
)
_REFERENCE_ANALYSIS_FIELDS = frozenset(
    {
        "contract_id",
        "schema_version",
        "analysis_run_ref",
        "observed_at",
        "source_video_artifacts",
        "scenes",
        "subtitle_asset_ref",
        "target_channels",
    }
)


def normalize_editing_scenes(
    scenes: Any,
    *,
    reference_asset_refs: list[str],
) -> list[dict[str, Any]]:
    if (
        not isinstance(scenes, list)
        or not scenes
        or len(scenes) > 200
        or not reference_asset_refs
    ):
        raise ValueError("media_job_blueprint_scene_invalid")
    previous_timeline_end = 0
    rendered_duration_ms = 0
    consumed_refs: set[str] = set()
    scene_ids: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, scene in enumerate(scenes):
        if not isinstance(scene, Mapping) or set(scene) != _BLUEPRINT_SCENE_FIELDS:
            raise ValueError("media_job_blueprint_scene_invalid")
        scene_id = scene.get("scene_id")
        source_ref = scene.get("source_asset_ref")
        source_start = scene.get("source_start_ms")
        source_end = scene.get("source_end_ms")
        timeline_start = scene.get("timeline_start_ms")
        timeline_end = scene.get("timeline_end_ms")
        transition = scene.get("transition")
        if (
            not isinstance(scene_id, str)
            or not scene_id
            or len(scene_id) > 160
            or scene_id in scene_ids
            or source_ref not in reference_asset_refs
            or any(
                isinstance(value, bool) or not isinstance(value, int)
                for value in (source_start, source_end, timeline_start, timeline_end)
            )
            or source_start < 0
            or source_end <= source_start
            or timeline_start != previous_timeline_end
            or timeline_end <= timeline_start
            or source_end - source_start != timeline_end - timeline_start
            or source_end - source_start > EDITING_MAX_SCENE_DURATION_MS
            or timeline_end > EDITING_MAX_TIMELINE_DURATION_MS
            or transition not in {"cut", "fade", "crossfade"}
            or (index == 0 and transition == "crossfade")
            or (
                transition == "crossfade"
                and (
                    timeline_end - timeline_start <= 250
                    or rendered_duration_ms < 250
                )
            )
            or not isinstance(scene.get("caption_ref"), str)
            or not scene["caption_ref"].startswith("evidence://")
            or len(scene["caption_ref"]) > 500
        ):
            raise ValueError("media_job_blueprint_scene_invalid")
        normalized.append(dict(scene))
        scene_ids.add(scene_id)
        consumed_refs.add(source_ref)
        previous_timeline_end = timeline_end
        rendered_duration_ms += timeline_end - timeline_start
        if transition == "crossfade":
            rendered_duration_ms -= 250
    if consumed_refs != set(reference_asset_refs):
        raise ValueError("media_job_blueprint_scene_conservation_invalid")
    return normalized


def derive_blueprint_render_plan(blueprint: Mapping[str, Any]) -> dict[str, Any]:
    """Derive the only admitted FFmpeg plan from canonical blueprint content."""

    if not isinstance(blueprint, Mapping) or set(blueprint) != _BLUEPRINT_FIELDS:
        raise ValueError("media_job_blueprint_result_invalid")
    scope = blueprint.get("scope")
    analysis = blueprint.get("analysis_receipt")
    references = blueprint.get("reference_asset_refs")
    campaigns = blueprint.get("campaign_asset_refs")
    artifacts = blueprint.get("input_artifacts")
    scenes = blueprint.get("scenes")
    if (
        blueprint.get("contract_id") != "kjds-editing-blueprint-v1"
        or blueprint.get("contract_version") != "1.0.0"
        or blueprint.get("tool_name") != "media.video_blueprint"
        or blueprint.get("provider") != BLUEPRINT_COMPILER_PROVIDER
        or blueprint.get("connector_ref") != BLUEPRINT_COMPILER_CONNECTOR_REF
        or blueprint.get("connector_binding_sha256")
        != BLUEPRINT_COMPILER_CONNECTOR_BINDING_SHA256
        or not isinstance(scope, Mapping)
        or set(scope) != _BLUEPRINT_SCOPE_FIELDS
        or blueprint.get("scope_binding_sha256")
        != sha256_bytes(canonical_json(dict(scope)))
        or not isinstance(analysis, Mapping)
        or set(analysis) != _BLUEPRINT_ANALYSIS_FIELDS
        or analysis.get("contract_id") != "kjds-reference-video-analysis-v1"
        or not isinstance(references, list)
        or not references
        or len(references) > 100
        or len(set(references)) != len(references)
        or not isinstance(campaigns, list)
        or not campaigns
        or len(campaigns) > 100
        or len(set(campaigns)) != len(campaigns)
        or not isinstance(artifacts, list)
        or not artifacts
        or not isinstance(scenes, list)
        or not scenes
        or len(scenes) > 200
        or blueprint.get("target_channels") != list(EDITING_TARGET_CHANNELS)
        or blueprint.get("render_profile_sha256")
        != FFMPEG_RENDER_PROFILE_SHA256
        or blueprint.get("external_write_allowed") is not False
        or blueprint.get("listing_eligible") is not False
    ):
        raise ValueError("media_job_blueprint_result_invalid")
    for field in (
        "connector_binding_sha256",
        "tool_descriptor_sha256",
        "scope_binding_sha256",
        "source_snapshot_sha256",
        "render_profile_sha256",
    ):
        _sha256_hex(blueprint.get(field), field)
    for field in ("source_snapshot_sha256", "semantic_sha256", "evidence_sha256"):
        _sha256_hex(analysis.get(field), f"analysis_{field}")

    normalized_scenes = normalize_editing_scenes(
        scenes,
        reference_asset_refs=list(references),
    )

    return {
        "contract_id": "kjds-ffmpeg-render-plan-v1",
        "executor": "ffmpeg",
        "job_ref": blueprint["job_ref"],
        "tool_version": blueprint["tool_version"],
        "provider": blueprint["provider"],
        "connector_ref": blueprint["connector_ref"],
        "connector_binding_sha256": blueprint["connector_binding_sha256"],
        "tool_descriptor_sha256": blueprint["tool_descriptor_sha256"],
        "source_snapshot_sha256": blueprint["source_snapshot_sha256"],
        "blueprint_sha256": sha256_bytes(canonical_json(dict(blueprint))),
        "reference_asset_refs": list(references),
        "scenes": normalized_scenes,
        "audio_asset_ref": blueprint.get("audio_asset_ref"),
        "subtitle_asset_ref": blueprint.get("subtitle_asset_ref"),
        "target_channels": list(blueprint["target_channels"]),
        "render_profile_sha256": blueprint["render_profile_sha256"],
        "external_write_allowed": False,
        "automatic_retry": False,
        "automatic_failover": False,
    }


def event_seal(
    *,
    job: MediaJobRow | None,
    job_ref: str,
    tenant_ref: str,
    entity_ref: str,
    store_ref: str,
    authority_sha256: str,
    subject_actor_id: str,
    ordinal: int,
    stream_kind: str,
    state: str,
    safe_reason_code: str | None,
    previous_event_sha256: str | None,
    public_projection_json: Mapping[str, Any],
    occurred_at: datetime,
    recorded_at: datetime,
    command_idempotency_sha256: str,
    command_request_sha256: str,
) -> str:
    del job
    occurred = _utc_datetime(occurred_at).isoformat(timespec="microseconds")
    recorded = _utc_datetime(recorded_at).isoformat(timespec="microseconds")
    return sha256_bytes(
        canonical_json(
            {
                "command_idempotency_sha256": command_idempotency_sha256,
                "command_request_sha256": command_request_sha256,
                "entity_ref": entity_ref,
                "event_ref_scope": authority_sha256,
                "job_ref": job_ref,
                "ordinal": ordinal,
                "occurred_at": occurred,
                "previous_event_sha256": previous_event_sha256,
                "public_projection_json": public_projection_json,
                "recorded_at": recorded,
                "safe_reason_code": safe_reason_code,
                "state": state,
                "store_ref": store_ref,
                "stream_kind": stream_kind,
                "subject_actor_id": subject_actor_id,
                "tenant_ref": tenant_ref,
            }
        )
    )


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def _sha256_hex(value: Any, field: str) -> str:
    result = _required_text(value, field).lower()
    if len(result) != 64 or any(char not in "0123456789abcdef" for char in result):
        raise ValueError(f"{field} must be a SHA-256 hex digest")
    return result


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class MediaJobScope:
    tenant_ref: str
    entity_ref: str
    store_ref: str
    authority_sha256: str
    subject_actor_id: str

    def normalized(self) -> MediaJobScope:
        return MediaJobScope(
            tenant_ref=_required_text(self.tenant_ref, "tenant_ref"),
            entity_ref=_required_text(self.entity_ref, "entity_ref"),
            store_ref=_required_text(self.store_ref, "store_ref"),
            authority_sha256=_sha256_hex(self.authority_sha256, "authority_sha256"),
            subject_actor_id=_required_text(self.subject_actor_id, "subject_actor_id"),
        )


@dataclass(frozen=True, slots=True)
class MediaJobProjection:
    job_ref: str
    state: str
    tool_name: str
    connector_ref: str
    created_at: str
    last_event_ordinal: int
    safe_reason_code: str | None
    state_recorded_at: str | None = None


@dataclass(frozen=True, slots=True)
class MediaJobBindingProjection:
    job_ref: str
    tool_name: str
    tool_version: str
    provider: str
    connector_ref: str
    connector_binding_sha256: str
    tool_descriptor_sha256: str
    campaign_brief_sha256: str
    request_sha256: str


@dataclass(frozen=True, slots=True)
class MediaJobEventProjection:
    event_ref: str
    job_ref: str
    ordinal: int
    state: str
    safe_reason_code: str | None
    occurred_at: str


@dataclass(frozen=True, slots=True)
class MediaJobResultReceiptProjection:
    receipt_ref: str
    job_ref: str
    event_ref: str
    state: str
    provider: str
    connector_ref: str
    result_kind: str
    artifact_evidence_refs: tuple[str, ...]
    content_asset_ref: str | None
    receipt_sha256: str
    recorded_at: str


@dataclass(frozen=True, slots=True)
class MediaJobWorkerInputProjection:
    job_ref: str
    tool_name: str
    tool_version: str
    payload: dict[str, Any]
    worker_input_sha256: str
    evidence_id: str
    recorded_at: str


@dataclass(frozen=True, slots=True)
class RenderBlueprintAuthority:
    evidence_record: EvidenceRecordRow
    source_snapshot_sha256: str
    render_plan_sha256: str
    receipt_recorded_at: datetime


@dataclass(frozen=True, slots=True)
class MediaJobTerminalProjection:
    job_ref: str
    event_ref: str
    event_sha256: str
    state: str
    recorded_at: str


class MediaJobRow(Base):
    __tablename__ = "media_jobs"
    __table_args__ = (
        UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "idempotency_sha256",
            name="uq_media_job_exact_scope_idempotency",
        ),
        UniqueConstraint(
            "job_ref",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            name="uq_media_job_exact_identity",
        ),
        Index("ix_media_job_scope_created", "tenant_ref", "entity_ref", "store_ref", "created_at"),
    )

    job_ref: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_grant_authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_actor_id: Mapped[str] = mapped_column(Text, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(160), nullable=False)
    tool_version: Mapped[str] = mapped_column(String(160), nullable=False)
    project_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    brief_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    provider: Mapped[str] = mapped_column(String(160), nullable=False)
    connector_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    connector_binding_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    request_fingerprint_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    request_evidence_id: Mapped[str] = mapped_column(Text, nullable=False)
    request_evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MediaJobEventRow(Base):
    __tablename__ = "media_job_events"
    __table_args__ = (
        UniqueConstraint("job_ref", "ordinal", name="uq_media_job_event_ordinal"),
        UniqueConstraint("job_ref", "event_sha256", name="uq_media_job_event_hash"),
        UniqueConstraint(
            "event_ref",
            "job_ref",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            name="uq_media_job_event_exact_identity",
        ),
        ForeignKeyConstraint(
            ["job_ref", "tenant_ref", "entity_ref", "store_ref", "scope_grant_authority_sha256"],
            [
                "media_jobs.job_ref",
                "media_jobs.tenant_ref",
                "media_jobs.entity_ref",
                "media_jobs.store_ref",
                "media_jobs.scope_grant_authority_sha256",
            ],
            name="fk_media_job_event_exact_identity",
            ondelete="RESTRICT",
        ),
        Index("ix_media_job_event_job_recorded", "job_ref", "recorded_at", "ordinal"),
    )

    event_ref: Mapped[str] = mapped_column(Text, primary_key=True)
    job_ref: Mapped[str] = mapped_column(Text, nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_grant_authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    stream_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    state: Mapped[str] = mapped_column(String(40), nullable=False)
    safe_reason_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    previous_event_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    command_idempotency_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    command_request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    public_projection_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MediaJobEvidenceLinkRow(Base):
    __tablename__ = "media_job_evidence_links"
    __table_args__ = (
        UniqueConstraint("job_ref", "purpose", "evidence_id", name="uq_media_job_evidence_purpose"),
        CheckConstraint(
            "purpose IN ('request_input','analysis_input','blueprint_input','artifact_terminal',"
            "'usage_authorization','usage_settlement')",
            name="ck_media_job_evidence_purpose",
        ),
        CheckConstraint(
            "source IN ('governed-media-job-request',"
            "'governed-reference-video-analysis',"
            "'governed-media-job-blueprint',"
            "'governed-media-job-transition','governed-media-job-usage')",
            name="ck_media_job_evidence_contract",
        ),
        ForeignKeyConstraint(
            ["job_ref", "tenant_ref", "entity_ref", "store_ref", "scope_grant_authority_sha256"],
            [
                "media_jobs.job_ref",
                "media_jobs.tenant_ref",
                "media_jobs.entity_ref",
                "media_jobs.store_ref",
                "media_jobs.scope_grant_authority_sha256",
            ],
            name="fk_media_job_link_exact_job",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["event_ref", "job_ref", "tenant_ref", "entity_ref", "store_ref", "scope_grant_authority_sha256"],
            [
                "media_job_events.event_ref",
                "media_job_events.job_ref",
                "media_job_events.tenant_ref",
                "media_job_events.entity_ref",
                "media_job_events.store_ref",
                "media_job_events.scope_grant_authority_sha256",
            ],
            name="fk_media_job_link_exact_event",
            ondelete="RESTRICT",
        ),
        Index("ix_media_job_link_scope", "tenant_ref", "entity_ref", "store_ref", "job_ref"),
    )

    link_ref: Mapped[str] = mapped_column(Text, primary_key=True)
    job_ref: Mapped[str] = mapped_column(Text, nullable=False)
    event_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_grant_authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    purpose: Mapped[str] = mapped_column(String(60), nullable=False)
    evidence_id: Mapped[str] = mapped_column(Text, nullable=False)
    blob_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(160), nullable=False)
    source_ref: Mapped[str] = mapped_column(Text, nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fresh_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MediaJobRequestBindingRow(Base):
    """Immutable request-to-descriptor Evidence binding for secure Job intake."""

    __tablename__ = "media_job_request_bindings"
    __table_args__ = (
        UniqueConstraint("job_ref", name="uq_media_job_request_binding_job"),
        ForeignKeyConstraint(
            ["job_ref", "tenant_ref", "entity_ref", "store_ref", "scope_grant_authority_sha256"],
            [
                "media_jobs.job_ref",
                "media_jobs.tenant_ref",
                "media_jobs.entity_ref",
                "media_jobs.store_ref",
                "media_jobs.scope_grant_authority_sha256",
            ],
            name="fk_media_job_request_binding_exact_job",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "length(tool_descriptor_sha256) = 64 AND "
            "length(request_evidence_sha256) = 64 AND "
            "length(descriptor_evidence_sha256) = 64",
            name="ck_media_job_request_binding_hashes",
        ),
    )

    binding_ref: Mapped[str] = mapped_column(Text, primary_key=True)
    job_ref: Mapped[str] = mapped_column(Text, nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_grant_authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    request_evidence_id: Mapped[str] = mapped_column(
        Text, ForeignKey("evidence_records.id", ondelete="RESTRICT"), nullable=False
    )
    request_evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    descriptor_evidence_id: Mapped[str] = mapped_column(
        Text, ForeignKey("evidence_records.id", ondelete="RESTRICT"), nullable=False
    )
    descriptor_evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_descriptor_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MediaJobWorkerInputRow(Base):
    """Immutable safe-ref worker input; raw prompts and commands never enter it."""

    __tablename__ = "media_job_worker_inputs"
    __table_args__ = (
        UniqueConstraint("job_ref", name="uq_media_job_worker_input_job"),
        ForeignKeyConstraint(
            ["job_ref", "tenant_ref", "entity_ref", "store_ref", "scope_grant_authority_sha256"],
            [
                "media_jobs.job_ref",
                "media_jobs.tenant_ref",
                "media_jobs.entity_ref",
                "media_jobs.store_ref",
                "media_jobs.scope_grant_authority_sha256",
            ],
            name="fk_media_job_worker_input_exact_job",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_media_job_worker_input_scope",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "job_ref",
        ),
    )

    input_ref: Mapped[str] = mapped_column(Text, primary_key=True)
    job_ref: Mapped[str] = mapped_column(Text, nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_grant_authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(160), nullable=False)
    tool_version: Mapped[str] = mapped_column(String(160), nullable=False)
    worker_input_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    worker_input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_id: Mapped[str] = mapped_column(
        Text, ForeignKey("evidence_records.id", ondelete="RESTRICT"), nullable=False
    )
    evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MediaJobResultReceiptRow(Base):
    """Immutable provider/result readback seal; no new dispatch authority."""

    __tablename__ = "media_job_result_receipts"
    __table_args__ = (
        UniqueConstraint("job_ref", "event_ref", name="uq_media_job_result_event"),
        CheckConstraint(
            "state IN ('SUCCEEDED','FAILED','UNKNOWN_OUTCOME')",
            name="ck_media_job_result_terminal_state",
        ),
        CheckConstraint(
            "tool_name IN ('media.video_blueprint','media.video_render')",
            name="ck_media_job_result_tool",
        ),
        ForeignKeyConstraint(
            ["job_ref", "tenant_ref", "entity_ref", "store_ref", "scope_grant_authority_sha256"],
            [
                "media_jobs.job_ref",
                "media_jobs.tenant_ref",
                "media_jobs.entity_ref",
                "media_jobs.store_ref",
                "media_jobs.scope_grant_authority_sha256",
            ],
            name="fk_media_job_result_exact_job",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["event_ref", "job_ref", "tenant_ref", "entity_ref", "store_ref", "scope_grant_authority_sha256"],
            [
                "media_job_events.event_ref",
                "media_job_events.job_ref",
                "media_job_events.tenant_ref",
                "media_job_events.entity_ref",
                "media_job_events.store_ref",
                "media_job_events.scope_grant_authority_sha256",
            ],
            name="fk_media_job_result_exact_event",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_media_job_result_scope_recorded",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "recorded_at",
        ),
    )

    receipt_ref: Mapped[str] = mapped_column(Text, primary_key=True)
    job_ref: Mapped[str] = mapped_column(Text, nullable=False)
    event_ref: Mapped[str] = mapped_column(Text, nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_grant_authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(160), nullable=False)
    tool_version: Mapped[str] = mapped_column(String(160), nullable=False)
    provider: Mapped[str] = mapped_column(String(160), nullable=False)
    connector_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    connector_binding_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(40), nullable=False)
    result_kind: Mapped[str] = mapped_column(String(160), nullable=False)
    artifact_evidence_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    content_asset_ref: Mapped[str | None] = mapped_column(
        Text, ForeignKey("content_assets.id", ondelete="RESTRICT"), nullable=True
    )
    receipt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GovernedMediaJobWorkspace:
    """Transactional Job truth used by separately governed execution adapters."""

    def __init__(
        self,
        engine,
        *,
        evidence: EvidenceService | None = None,
        authority: Any | None = None,
        content_assets: Any | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.engine = engine
        self.evidence = evidence or EvidenceService(engine)
        if authority is None:
            raise ValueError("media job scope authority is required")
        self.authority = authority
        self.content_assets = content_assets
        self.clock = clock or (lambda: datetime.now(UTC))

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None:
            raise ValueError("media job clock must be timezone-aware")
        return value.astimezone(UTC)

    @staticmethod
    def _lock_schema_transition_in_session(session: Session) -> None:
        """Serialize every Job writer before it acquires any table/row lock."""

        if session.get_bind().dialect.name == "postgresql":
            session.execute(
                text(
                    "SELECT pg_advisory_xact_lock_shared("
                    "hashtext('kjds-media-jobs-0098-result-readback'))"
                )
            )

    def _resolve_current(self, *, principal: Principal, store_ref: str) -> MediaJobScope:
        store_ref = _required_text(store_ref, "store_ref")
        now = self._now()
        result = self.authority.current(
            principal=principal,
            store_ref=store_ref,
            as_of=now,
        )
        if not isinstance(result, Mapping):
            raise PermissionError("scope_authority_projection_invalid")
        authority_sha256 = result.get("authority_sha256")
        if (
            result.get("status") != "ready"
            or result.get("tenant_ref") != principal.tenant_ref
            or result.get("store_ref") != store_ref
            or not isinstance(result.get("entity_ref"), str)
            or not result["entity_ref"].strip()
            or not isinstance(authority_sha256, str)
        ):
            raise PermissionError("scope_authority_not_current")
        return MediaJobScope(
            tenant_ref=principal.tenant_ref,
            entity_ref=result["entity_ref"],
            store_ref=store_ref,
            authority_sha256=authority_sha256,
            subject_actor_id=principal.actor_id,
        ).normalized()

    def current_scope(self, *, principal: Principal, store_ref: str) -> MediaJobScope:
        """Return only the server-derived current scope used by Job intake."""

        return self._resolve_current(principal=principal, store_ref=store_ref)

    @staticmethod
    def _scope_payload(scope: MediaJobScope) -> dict[str, str]:
        return {
            "tenant_ref": scope.tenant_ref,
            "entity_ref": scope.entity_ref,
            "store_ref": scope.store_ref,
            "authority_sha256": scope.authority_sha256,
            "subject_actor_id": scope.subject_actor_id,
        }

    @classmethod
    def _validate_campaign_brief(
        cls,
        *,
        brief: Mapping[str, Any],
        scope: MediaJobScope,
        request: Mapping[str, Any],
    ) -> None:
        expected_fields = _CAMPAIGN_BRIEF_CONTENT_FIELDS | {
            "brief_ref",
            "content_sha256",
            "external_write_allowed",
        }
        if not isinstance(brief, Mapping) or set(brief) != expected_fields:
            raise ValueError("media_job_campaign_brief_shape_invalid")
        scope_payload = cls._scope_payload(scope)
        if any(brief.get(key) != value for key, value in scope_payload.items()):
            raise PermissionError("media_job_campaign_brief_scope_invalid")
        scope_binding_sha256 = sha256_bytes(canonical_json(scope_payload))
        if brief.get("scope_binding_sha256") != scope_binding_sha256:
            raise PermissionError("media_job_campaign_brief_scope_binding_invalid")
        if (
            brief.get("contract_id") != CAMPAIGN_BRIEF_CONTRACT
            or brief.get("contract_version") != CAMPAIGN_BRIEF_VERSION
            or brief.get("external_write_allowed") is not False
        ):
            raise ValueError("media_job_campaign_brief_contract_invalid")
        content = {key: brief[key] for key in _CAMPAIGN_BRIEF_CONTENT_FIELDS}
        content_sha256 = sha256_bytes(canonical_json(content))
        if (
            brief.get("content_sha256") != content_sha256
            or brief.get("brief_ref") != f"campaign_brief_{content_sha256[:32]}"
            or request.get("brief_ref") != brief.get("brief_ref")
            or request.get("campaign_brief_sha256") != content_sha256
            or request.get("project_ref") != brief.get("project_ref")
        ):
            raise ValueError("media_job_campaign_brief_seal_invalid")

    @staticmethod
    def _validate_tool_descriptor(
        *,
        descriptor: Mapping[str, Any],
        request: Mapping[str, Any],
    ) -> str:
        if not isinstance(descriptor, Mapping) or set(descriptor) != (
            _TOOL_DESCRIPTOR_FIELDS | {"descriptor_sha256"}
        ):
            raise ValueError("media_job_tool_descriptor_shape_invalid")
        content = {key: descriptor[key] for key in _TOOL_DESCRIPTOR_FIELDS}
        descriptor_sha256 = sha256_bytes(canonical_json(content))
        if (
            descriptor.get("contract_id") != TOOL_DESCRIPTOR_CONTRACT
            or descriptor.get("descriptor_sha256") != descriptor_sha256
            or request.get("tool_descriptor_sha256") != descriptor_sha256
        ):
            raise ValueError("media_job_tool_descriptor_seal_invalid")
        mirrors = {
            "tool_name": "tool_name",
            "tool_version": "tool_version",
            "provider": "provider",
            "connector_ref": "connector_ref",
            "connector_binding_sha256": "connector_binding_sha256",
            "output_contract": "output_contract",
        }
        if any(descriptor.get(left) != request.get(right) for left, right in mirrors.items()):
            raise ValueError("media_job_tool_descriptor_binding_invalid")
        return descriptor_sha256

    @staticmethod
    def _validate_commander_request(request: Mapping[str, Any]) -> None:
        if set(request) != _COMMANDER_REQUEST_FIELDS:
            raise ValueError("media_job_commander_request_shape_invalid")
        if request.get("contract_id") != COMMANDER_REQUEST_CONTRACT:
            raise ValueError("media_job_commander_request_contract_invalid")
        for field in (
            "campaign_brief_sha256",
            "connector_binding_sha256",
            "idempotency_sha256",
            "tool_descriptor_sha256",
            "tool_inputs_sha256",
        ):
            _sha256_hex(request.get(field), field)
        count = request.get("tool_input_ref_count")
        if not isinstance(count, int) or isinstance(count, bool) or not 0 <= count <= 1000:
            raise ValueError("media_job_tool_input_ref_count_invalid")
        if request.get("safe_reason_codes") != []:
            raise ValueError("media_job_safe_reason_codes_invalid")

    @staticmethod
    def _worker_ref(value: Any, field: str) -> str:
        result = _required_text(value, field)
        if (
            len(result) > 500
            or result != value
            or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:/-" for char in result)
        ):
            raise ValueError("media_job_worker_input_ref_invalid")
        return result

    @classmethod
    def _worker_refs(cls, value: Any, field: str) -> list[str]:
        if not isinstance(value, list) or len(value) > 100:
            raise ValueError("media_job_worker_input_refs_invalid")
        result = [cls._worker_ref(item, field) for item in value]
        if len(set(result)) != len(result):
            raise ValueError("media_job_worker_input_refs_invalid")
        return result

    @classmethod
    def _normalize_worker_input(
        cls,
        *,
        worker_input: Mapping[str, Any],
        request: Mapping[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(worker_input, Mapping) or set(worker_input) != _WORKER_INPUT_FIELDS:
            raise ValueError("media_job_worker_input_shape_invalid")
        result = dict(worker_input)
        mirrors = ("tool_name", "tool_version", "project_ref", "brief_ref")
        if (
            result.get("contract_id") != WORKER_INPUT_CONTRACT
            or any(result.get(field) != request.get(field) for field in mirrors)
        ):
            raise ValueError("media_job_worker_input_binding_invalid")
        for field in (
            "campaign_content_asset_refs",
            "reference_asset_refs",
            "source_asset_refs",
            "audio_asset_refs",
            "target_channels",
        ):
            result[field] = cls._worker_refs(result[field], field)
        if not result["campaign_content_asset_refs"]:
            raise ValueError("media_job_worker_input_campaign_refs_required")
        editing_ref = result["editing_blueprint_ref"]
        result["editing_blueprint_ref"] = (
            None
            if editing_ref is None
            else cls._worker_ref(editing_ref, "editing_blueprint_ref")
        )
        analysis_ref = result["analysis_evidence_ref"]
        result["analysis_evidence_ref"] = (
            None
            if analysis_ref is None
            else cls._worker_ref(analysis_ref, "analysis_evidence_ref")
        )
        for field in ("analysis_contract_sha256", "render_profile_sha256"):
            value = result[field]
            result[field] = None if value is None else _sha256_hex(value, field)
        tool_name = result["tool_name"]
        if tool_name == "media.video_blueprint":
            if (
                not result["reference_asset_refs"]
                or result["editing_blueprint_ref"] is not None
                or result["source_asset_refs"]
                or len(result["audio_asset_refs"]) != 1
                or result["analysis_evidence_ref"] is None
                or result["analysis_contract_sha256"] is None
                or result["render_profile_sha256"]
                != FFMPEG_RENDER_PROFILE_SHA256
                or result["target_channels"] != list(EDITING_TARGET_CHANNELS)
            ):
                raise ValueError("media_job_blueprint_worker_input_invalid")
        elif tool_name == "media.video_render":
            if (
                result["editing_blueprint_ref"] is None
                or not result["source_asset_refs"]
                or len(result["audio_asset_refs"]) != 1
                or result["reference_asset_refs"]
                or result["analysis_evidence_ref"] is not None
                or result["analysis_contract_sha256"] is not None
                or result["render_profile_sha256"]
                != FFMPEG_RENDER_PROFILE_SHA256
                or result["target_channels"] != list(EDITING_TARGET_CHANNELS)
            ):
                raise ValueError("media_job_render_worker_input_invalid")
        else:
            raise ValueError("media_job_worker_input_tool_not_admitted")
        role_refs = [
            *result["campaign_content_asset_refs"],
            *(
                result["reference_asset_refs"]
                if tool_name == "media.video_blueprint"
                else result["source_asset_refs"]
            ),
            *result["audio_asset_refs"],
        ]
        if len(role_refs) != len(set(role_refs)):
            raise ValueError("media_job_worker_input_asset_roles_overlap")
        _validate_json(result)
        return result

    @staticmethod
    def _validate_blueprint_analysis_input(
        *,
        session: Session,
        scope: MediaJobScope,
        worker_input: Mapping[str, Any],
        blueprint: Mapping[str, Any] | None = None,
    ) -> EvidenceRecordRow:
        evidence_ref = worker_input.get("analysis_evidence_ref")
        analysis_sha256 = worker_input.get("analysis_contract_sha256")
        if (
            not isinstance(evidence_ref, str)
            or not evidence_ref.startswith("evidence://")
            or not isinstance(analysis_sha256, str)
        ):
            raise ValueError("media_job_analysis_input_invalid")
        evidence_id = evidence_ref.removeprefix("evidence://")
        record = session.get(EvidenceRecordRow, evidence_id)
        blob = session.get(EvidenceBlobRow, record.blob_sha256) if record else None
        metadata = record.metadata_json if record is not None else None
        if record is None or blob is None or not isinstance(metadata, dict):
            raise ValueError("media_job_analysis_input_invalid")
        try:
            content = json.loads(blob.content_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("media_job_analysis_input_invalid") from exc
        analysis_run_ref = metadata.get("analysis_run_ref")
        if (
            record.source != "governed-reference-video-analysis"
            or record.grade != EvidenceGrade.B.value
            or record.created_by != scope.subject_actor_id
            or record.content_type != "application/json"
            or record.blob_sha256 != blob.sha256
            or sha256_bytes(blob.content_bytes) != blob.sha256
            or canonical_json(content) != blob.content_bytes
            or blob.sha256 != analysis_sha256
            or not isinstance(analysis_run_ref, str)
            or not analysis_run_ref.strip()
            or record.source_ref
            != f"reference-analysis://{analysis_run_ref}/{analysis_sha256}"
            or metadata.get("contract_id")
            != "kjds-reference-video-analysis-v1"
            or metadata.get("tenant_ref") != scope.tenant_ref
            or metadata.get("entity_ref") != scope.entity_ref
            or metadata.get("store_ref") != scope.store_ref
            or metadata.get("scope_grant_authority_sha256")
            != scope.authority_sha256
            or metadata.get("subject_actor_id") != scope.subject_actor_id
            or metadata.get("rights_status") != "approved"
            or metadata.get("schema_version") != "1.0.0"
            or metadata.get("analysis_contract_sha256") != analysis_sha256
            or not isinstance(content, dict)
            or set(content) != _REFERENCE_ANALYSIS_FIELDS
            or content.get("contract_id")
            != "kjds-reference-video-analysis-v1"
            or content.get("schema_version") != "1.0.0"
            or content.get("analysis_run_ref") != analysis_run_ref
            or content.get("observed_at") != metadata.get("observed_at")
            or sha256_bytes(
                canonical_json(content.get("source_video_artifacts"))
            )
            != metadata.get("source_video_artifacts_sha256")
        ):
            raise ValueError("media_job_analysis_input_invalid")
        reference_refs = worker_input.get("reference_asset_refs")
        campaign_refs = worker_input.get("campaign_content_asset_refs")
        audio_refs = worker_input.get("audio_asset_refs")
        source_artifacts = content.get("source_video_artifacts")
        if (
            not isinstance(reference_refs, list)
            or not reference_refs
            or not isinstance(campaign_refs, list)
            or not campaign_refs
            or not isinstance(audio_refs, list)
            or len(audio_refs) != 1
            or not isinstance(source_artifacts, list)
            or len(source_artifacts) != len(reference_refs)
        ):
            raise ValueError("media_job_analysis_input_asset_binding_invalid")

        all_refs = list(
            dict.fromkeys([*campaign_refs, *reference_refs, *audio_refs])
        )
        asset_ids = [ref.removeprefix("content-asset://") for ref in all_refs]
        locked_assets = session.scalars(
            select(ContentAssetRow)
            .where(ContentAssetRow.id.in_(sorted(asset_ids)))
            .order_by(ContentAssetRow.id)
            .with_for_update()
        ).all()
        assets_by_id = {asset.id: asset for asset in locked_assets}
        product_ids_to_lock = sorted({asset.product_id for asset in locked_assets})
        locked_products = session.scalars(
            select(ProductRow)
            .where(ProductRow.id.in_(product_ids_to_lock))
            .order_by(ProductRow.id)
            .with_for_update()
        ).all()
        products_by_id = {product.id: product for product in locked_products}

        expected_video_artifacts: list[dict[str, str]] = []
        input_artifacts: list[dict[str, str]] = []
        product_ids: set[str] = set()
        for ref, expected_role in (
            *((value, "campaign") for value in campaign_refs),
            *((value, "reference_video") for value in reference_refs),
            *((value, "audio") for value in audio_refs),
        ):
            if not isinstance(ref, str) or not ref.startswith("content-asset://"):
                raise ValueError("media_job_analysis_input_asset_binding_invalid")
            asset = assets_by_id.get(ref.removeprefix("content-asset://"))
            product = products_by_id.get(asset.product_id) if asset else None
            artifact_record = (
                session.get(EvidenceRecordRow, asset.artifact_ref)
                if asset is not None and asset.artifact_ref
                else None
            )
            artifact_blob = (
                session.get(EvidenceBlobRow, artifact_record.blob_sha256)
                if artifact_record is not None
                else None
            )
            artifact_metadata = (
                artifact_record.metadata_json
                if artifact_record is not None
                else None
            )
            if (
                asset is None
                or product is None
                or artifact_record is None
                or artifact_blob is None
                or asset.status != "approved"
                or product.tenant_ref != scope.tenant_ref
                or product.entity_ref != scope.entity_ref
                or product.store_ref != scope.store_ref
                or product.scope_grant_authority_sha256 != scope.authority_sha256
                or artifact_record.grade != EvidenceGrade.B.value
                or artifact_record.blob_sha256 != artifact_blob.sha256
                or sha256_bytes(artifact_blob.content_bytes) != artifact_blob.sha256
                or not isinstance(artifact_metadata, dict)
                or artifact_metadata.get("rights_status") != "approved"
                or artifact_metadata.get("tenant_ref") != scope.tenant_ref
                or artifact_metadata.get("entity_ref") != scope.entity_ref
                or artifact_metadata.get("store_ref") != scope.store_ref
                or artifact_metadata.get("scope_grant_authority_sha256")
                != scope.authority_sha256
                or artifact_metadata.get("subject_actor_id")
                != scope.subject_actor_id
            ):
                raise ValueError("media_job_analysis_input_asset_binding_invalid")
            if expected_role == "reference_video":
                if (
                    asset.content_type != "video"
                    or not artifact_record.content_type.startswith("video/")
                ):
                    raise ValueError("media_job_analysis_input_asset_binding_invalid")
                expected_video_artifacts.append(
                    {
                        "content_asset_ref": ref,
                        "evidence_ref": f"evidence://{artifact_record.id}",
                        "evidence_sha256": artifact_record.blob_sha256,
                    }
                )
            elif expected_role == "audio" and (
                asset.content_type != "audio"
                or not artifact_record.content_type.startswith("audio/")
            ):
                raise ValueError("media_job_analysis_input_asset_binding_invalid")
            input_artifacts.append(
                {
                    "content_asset_ref": ref,
                    "evidence_ref": f"evidence://{artifact_record.id}",
                    "evidence_sha256": artifact_record.blob_sha256,
                    "content_type": artifact_record.content_type,
                    "role": expected_role,
                }
            )
            product_ids.add(product.id)
        if len(product_ids) != 1 or source_artifacts != expected_video_artifacts:
            raise ValueError("media_job_analysis_input_asset_binding_invalid")
        try:
            scenes = normalize_editing_scenes(
                content.get("scenes"),
                reference_asset_refs=list(reference_refs),
            )
        except ValueError as exc:
            raise ValueError("media_job_analysis_input_source_invalid") from exc
        target_channels = content.get("target_channels", list(EDITING_TARGET_CHANNELS))
        subtitle_ref = content.get("subtitle_asset_ref")
        if (
            target_channels != list(EDITING_TARGET_CHANNELS)
            or (subtitle_ref is not None and not isinstance(subtitle_ref, str))
        ):
            raise ValueError("media_job_analysis_input_source_invalid")
        caption_refs = [scene.get("caption_ref") for scene in scenes if isinstance(scene, dict)]
        if (
            len(caption_refs) != len(scenes)
            or any(
                not isinstance(ref, str) or not ref.startswith("evidence://")
                for ref in caption_refs
            )
        ):
            raise ValueError("media_job_analysis_input_source_invalid")
        for governed_ref in [*caption_refs, *([subtitle_ref] if subtitle_ref else [])]:
            governed_record = session.get(
                EvidenceRecordRow,
                governed_ref.removeprefix("evidence://"),
            )
            governed_metadata = (
                governed_record.metadata_json if governed_record is not None else None
            )
            if (
                governed_record is None
                or not isinstance(governed_metadata, dict)
                or governed_metadata.get("rights_status") != "approved"
                or governed_metadata.get("tenant_ref") != scope.tenant_ref
                or governed_metadata.get("entity_ref") != scope.entity_ref
                or governed_metadata.get("store_ref") != scope.store_ref
                or governed_metadata.get("scope_grant_authority_sha256")
                != scope.authority_sha256
                or governed_metadata.get("subject_actor_id")
                != scope.subject_actor_id
            ):
                raise ValueError("media_job_analysis_input_source_invalid")

        observed_at = _utc_datetime(record.effective_at).isoformat()
        analysis_receipt_content = {
            "contract_id": "kjds-reference-video-analysis-v1",
            "semantic_sha256": analysis_sha256,
            "observed_at": observed_at,
            "evidence_ref": f"evidence://{record.id}",
            "evidence_sha256": record.blob_sha256,
            "source_video_artifacts": expected_video_artifacts,
        }
        analysis_receipt = {
            "contract_id": analysis_receipt_content["contract_id"],
            "source_snapshot_sha256": sha256_bytes(
                canonical_json(analysis_receipt_content)
            ),
            "semantic_sha256": analysis_receipt_content["semantic_sha256"],
            "observed_at": analysis_receipt_content["observed_at"],
            "evidence_ref": analysis_receipt_content["evidence_ref"],
            "evidence_sha256": analysis_receipt_content["evidence_sha256"],
            "source_video_artifacts": expected_video_artifacts,
        }
        scope_payload = {
            "tenant_ref": scope.tenant_ref,
            "entity_ref": scope.entity_ref,
            "store_ref": scope.store_ref,
            "authority_sha256": scope.authority_sha256,
            "subject_actor_id": scope.subject_actor_id,
        }
        scope_binding_sha256 = sha256_bytes(canonical_json(scope_payload))
        source_snapshot_content = {
            "contract_id": "kjds-editing-source-receipt-v1",
            "contract_version": "1.0.0",
            "scope": scope_payload,
            "scope_binding_sha256": scope_binding_sha256,
            "rights_status": "approved",
            "product_id": next(iter(product_ids)),
            "campaign_asset_refs": campaign_refs,
            "reference_asset_refs": reference_refs,
            "input_artifacts": input_artifacts,
            "analysis_receipt": analysis_receipt_content,
            "scenes": scenes,
            "audio_asset_ref": audio_refs[0],
            "subtitle_asset_ref": subtitle_ref,
            "target_channels": target_channels,
            "render_profile_sha256": FFMPEG_RENDER_PROFILE_SHA256,
            "editing_blueprint": None,
            "editing_blueprint_sha256": None,
        }
        source_snapshot_sha256 = sha256_bytes(canonical_json(source_snapshot_content))
        if blueprint is not None and (
            blueprint.get("scope") != scope_payload
            or blueprint.get("scope_binding_sha256") != scope_binding_sha256
            or blueprint.get("source_snapshot_sha256") != source_snapshot_sha256
            or blueprint.get("analysis_receipt") != analysis_receipt
            or blueprint.get("campaign_asset_refs") != campaign_refs
            or blueprint.get("reference_asset_refs") != reference_refs
            or blueprint.get("input_artifacts") != input_artifacts
            or blueprint.get("scenes") != scenes
            or blueprint.get("audio_asset_ref") != audio_refs[0]
            or blueprint.get("subtitle_asset_ref") != subtitle_ref
            or blueprint.get("target_channels") != target_channels
            or blueprint.get("render_profile_sha256")
            != FFMPEG_RENDER_PROFILE_SHA256
        ):
            raise ValueError("media_job_blueprint_worker_binding_invalid")
        return record

    def _validate_render_worker_input(
        self,
        *,
        session: Session,
        scope: MediaJobScope,
        worker_input: Mapping[str, Any],
    ) -> RenderBlueprintAuthority:
        blueprint_ref = worker_input.get("editing_blueprint_ref")
        if not isinstance(blueprint_ref, str) or not blueprint_ref.startswith(
            "evidence://"
        ):
            raise ValueError("media_job_render_blueprint_input_invalid")
        blueprint_record = session.get(
            EvidenceRecordRow,
            blueprint_ref.removeprefix("evidence://"),
        )
        blueprint_blob = (
            session.get(EvidenceBlobRow, blueprint_record.blob_sha256)
            if blueprint_record is not None
            else None
        )
        metadata = (
            blueprint_record.metadata_json
            if blueprint_record is not None
            else None
        )
        if (
            blueprint_record is None
            or blueprint_blob is None
            or not isinstance(metadata, dict)
            or blueprint_record.source != "governed-media-job-blueprint"
            or blueprint_record.grade != EvidenceGrade.B.value
            or blueprint_record.blob_sha256 != blueprint_blob.sha256
            or sha256_bytes(blueprint_blob.content_bytes) != blueprint_blob.sha256
            or metadata.get("blueprint_sha256") != blueprint_blob.sha256
        ):
            raise ValueError("media_job_render_blueprint_input_invalid")
        try:
            blueprint = json.loads(blueprint_blob.content_bytes)
            render_plan = derive_blueprint_render_plan(blueprint)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise ValueError("media_job_render_blueprint_input_invalid") from exc

        blueprint_job_ref = metadata.get("media_job_ref")
        blueprint_job = session.scalar(
            select(MediaJobRow)
            .where(
                MediaJobRow.job_ref == blueprint_job_ref,
                MediaJobRow.tenant_ref == scope.tenant_ref,
                MediaJobRow.entity_ref == scope.entity_ref,
                MediaJobRow.store_ref == scope.store_ref,
                MediaJobRow.scope_grant_authority_sha256 == scope.authority_sha256,
                MediaJobRow.subject_actor_id == scope.subject_actor_id,
                MediaJobRow.tool_name == "media.video_blueprint",
            )
            .with_for_update()
        )
        if blueprint_job is None:
            raise ValueError("media_job_render_blueprint_input_invalid")
        events = self._validate_event_chain(session, blueprint_job, scope)
        receipts = session.scalars(
            select(MediaJobResultReceiptRow).where(
                MediaJobResultReceiptRow.job_ref == blueprint_job.job_ref,
                MediaJobResultReceiptRow.state == "SUCCEEDED",
                MediaJobResultReceiptRow.result_kind == "editing_blueprint_evidence",
            )
        ).all()
        if len(receipts) != 1:
            raise ValueError("media_job_render_blueprint_input_invalid")
        receipt_row = receipts[0]
        event = next(
            (item for item in events if item.event_ref == receipt_row.event_ref),
            None,
        )
        if event is None or receipt_row.artifact_evidence_refs != [blueprint_record.id]:
            raise ValueError("media_job_render_blueprint_input_invalid")
        receipt, receipt_sha256 = self._validate_result_receipt(
            receipt={
                "contract_id": RESULT_RECEIPT_CONTRACT,
                "provider": receipt_row.provider,
                "connector_ref": receipt_row.connector_ref,
                "connector_binding_sha256": receipt_row.connector_binding_sha256,
                "result_kind": receipt_row.result_kind,
                "artifact_evidence_refs": list(receipt_row.artifact_evidence_refs),
                "content_asset_ref": receipt_row.content_asset_ref,
                "receipt_sha256": receipt_row.receipt_sha256,
            },
            job=blueprint_job,
            event=event,
        )
        self._validate_result_bindings(
            session=session,
            scope=scope,
            job=blueprint_job,
            event=event,
            content=receipt,
            receipt_sha256=receipt_sha256,
        )
        expected_audio = (
            [blueprint["audio_asset_ref"]]
            if blueprint.get("audio_asset_ref") is not None
            else []
        )
        if (
            worker_input.get("project_ref") != blueprint_job.project_ref
            or worker_input.get("brief_ref") != blueprint_job.brief_ref
            or worker_input.get("campaign_content_asset_refs")
            != blueprint.get("campaign_asset_refs")
            or worker_input.get("source_asset_refs")
            != blueprint.get("reference_asset_refs")
            or worker_input.get("audio_asset_refs") != expected_audio
            or worker_input.get("target_channels")
            != blueprint.get("target_channels")
            or worker_input.get("render_profile_sha256")
            != blueprint.get("render_profile_sha256")
            or render_plan.get("blueprint_sha256") != blueprint_blob.sha256
        ):
            raise ValueError("media_job_render_blueprint_binding_invalid")
        source_snapshot_sha256 = _sha256_hex(
            blueprint.get("source_snapshot_sha256"),
            "source_snapshot_sha256",
        )
        render_plan_sha256 = sha256_bytes(canonical_json(render_plan))
        if (
            metadata.get("source_snapshot_sha256") != source_snapshot_sha256
            or metadata.get("render_plan_sha256") != render_plan_sha256
        ):
            raise ValueError("media_job_render_blueprint_binding_invalid")
        return RenderBlueprintAuthority(
            evidence_record=blueprint_record,
            source_snapshot_sha256=source_snapshot_sha256,
            render_plan_sha256=render_plan_sha256,
            receipt_recorded_at=_utc_datetime(receipt_row.recorded_at),
        )

    @staticmethod
    def _request_bytes(request: Mapping[str, Any]) -> bytes:
        if not isinstance(request, Mapping) or not request:
            raise ValueError("request must be a non-empty object")
        return canonical_json(request)

    @staticmethod
    def _projection(row: MediaJobRow, event: MediaJobEventRow) -> MediaJobProjection:
        return MediaJobProjection(
            job_ref=row.job_ref,
            state=event.state,
            tool_name=row.tool_name,
            connector_ref=row.connector_ref,
            created_at=_utc_datetime(row.created_at).isoformat(),
            last_event_ordinal=event.ordinal,
            safe_reason_code=event.safe_reason_code,
            state_recorded_at=_utc_datetime(event.recorded_at).isoformat(),
        )

    def submit(
        self,
        *,
        principal: Principal,
        store_ref: str,
        request: Mapping[str, Any],
        campaign_brief: Mapping[str, Any] | None = None,
        tool_descriptor: Mapping[str, Any] | None = None,
        worker_input: Mapping[str, Any] | None = None,
    ) -> MediaJobProjection:
        scope = self._resolve_current(principal=principal, store_ref=store_ref)
        secure_submission = campaign_brief is not None or tool_descriptor is not None
        if secure_submission:
            if campaign_brief is None or tool_descriptor is None:
                raise ValueError("media_job_secure_submission_incomplete")
            self._validate_commander_request(request)
        normalized_worker_input = None
        worker_input_sha256 = None
        descriptor_sha256 = None
        descriptor_bytes = None
        if tool_name := request.get("tool_name"):
            if tool_name in {"media.video_blueprint", "media.video_render"}:
                if worker_input is None:
                    raise ValueError("media_job_worker_input_required")
                normalized_worker_input = self._normalize_worker_input(
                    worker_input=worker_input,
                    request=request,
                )
                worker_input_sha256 = sha256_bytes(
                    canonical_json(normalized_worker_input)
                )
            elif worker_input is not None:
                raise ValueError("media_job_worker_input_not_admitted")
        request_bytes = self._request_bytes(request)
        request_sha = sha256_bytes(request_bytes)
        tool_name = _required_text(request.get("tool_name"), "tool_name")
        tool_version = _required_text(request.get("tool_version", "unknown"), "tool_version")
        project_ref = _required_text(request.get("project_ref"), "project_ref")
        brief_ref = _required_text(request.get("brief_ref"), "brief_ref")
        provider = _required_text(request.get("provider"), "provider")
        connector_ref = _required_text(request.get("connector_ref"), "connector_ref")
        connector_binding = _sha256_hex(request.get("connector_binding_sha256"), "connector_binding_sha256")
        idempotency = _sha256_hex(request.get("idempotency_sha256"), "idempotency_sha256")
        scope_payload = self._scope_payload(scope)
        fingerprint = sha256_bytes(
            canonical_json({"scope": scope_payload, "request": request})
        )
        scope_binding = sha256_bytes(canonical_json(scope_payload))
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            self._lock_schema_transition_in_session(session)
            analysis_input_record = None
            blueprint_input_record = None
            render_not_before = None
            self._lock_idempotency_winner(
                session=session,
                scope=scope,
                idempotency_sha256=idempotency,
            )
            EvidenceService.lock_scope_authority_in_session(
                tenant_ref=scope.tenant_ref,
                store_ref=scope.store_ref,
                subject_actor_id=scope.subject_actor_id,
                session=session,
            )
            fresh_scope = self._resolve_current(principal=principal, store_ref=store_ref)
            if fresh_scope != scope:
                raise PermissionError("scope_authority_changed")
            if (
                normalized_worker_input is not None
                and tool_name == "media.video_blueprint"
            ):
                analysis_input_record = self._validate_blueprint_analysis_input(
                    session=session,
                    scope=fresh_scope,
                    worker_input=normalized_worker_input,
                )
            elif (
                normalized_worker_input is not None
                and tool_name == "media.video_render"
            ):
                blueprint_authority = self._validate_render_worker_input(
                    session=session,
                    scope=fresh_scope,
                    worker_input=normalized_worker_input,
                )
                blueprint_input_record = blueprint_authority.evidence_record
                render_not_before = blueprint_authority.receipt_recorded_at
            if secure_submission:
                assert campaign_brief is not None and tool_descriptor is not None
                self._validate_campaign_brief(
                    brief=campaign_brief,
                    scope=fresh_scope,
                    request=request,
                )
                self._validate_tool_descriptor(
                    descriptor=tool_descriptor,
                    request=request,
                )
                descriptor_sha256 = _sha256_hex(
                    tool_descriptor.get("descriptor_sha256"),
                    "descriptor_sha256",
                )
                descriptor_bytes = canonical_json(dict(tool_descriptor))
                prior_scope = session.scalar(
                    select(MediaJobRow).where(
                        MediaJobRow.tenant_ref == scope.tenant_ref,
                        MediaJobRow.store_ref == scope.store_ref,
                        MediaJobRow.idempotency_sha256 == idempotency,
                    )
                )
                if prior_scope is not None and (
                    prior_scope.entity_ref != scope.entity_ref
                    or prior_scope.scope_grant_authority_sha256 != scope.authority_sha256
                    or prior_scope.subject_actor_id != scope.subject_actor_id
                ):
                    raise ValueError("media_job_idempotency_scope_conflict")
            existing = session.scalar(
                select(MediaJobRow).where(
                    MediaJobRow.tenant_ref == scope.tenant_ref,
                    MediaJobRow.entity_ref == scope.entity_ref,
                    MediaJobRow.store_ref == scope.store_ref,
                    MediaJobRow.scope_grant_authority_sha256 == scope.authority_sha256,
                    MediaJobRow.idempotency_sha256 == idempotency,
                )
            )
            if existing is not None:
                if existing.request_fingerprint_sha256 != fingerprint:
                    raise ValueError("media_job_idempotency_conflict")
                event = self._validate_event_chain(session, existing, scope)[-1]
                if secure_submission:
                    self._request_binding(session, existing)
                if worker_input_sha256 is not None:
                    worker_row = session.scalar(
                        select(MediaJobWorkerInputRow).where(
                            MediaJobWorkerInputRow.job_ref == existing.job_ref
                        )
                    )
                    if (
                        worker_row is None
                        or worker_row.worker_input_sha256 != worker_input_sha256
                    ):
                        raise ValueError(
                            "media_job_worker_input_conflict"
                        ) from None
                return self._projection(existing, event)
            now = _utc_datetime(self._now())
            if render_not_before is not None and now < render_not_before:
                raise ValueError("media_job_render_clock_regressed")
            evidence_record = self.evidence.capture_media_job_evidence(
                content=request_bytes,
                filename="media-job-request.json",
                content_type="application/json",
                source=REQUEST_SOURCE,
                source_ref=f"media-job://{scope_binding}/{idempotency}/request",
                grade=EvidenceGrade.B,
                effective_at=now.isoformat(),
                recorded_at=now.isoformat(),
                created_by=scope.subject_actor_id,
                metadata={
                    "contract_id": REQUEST_CONTRACT,
                    "media_job_request_fingerprint_sha256": fingerprint,
                    "tenant_ref": scope.tenant_ref,
                    "entity_ref": scope.entity_ref,
                    "store_ref": scope.store_ref,
                    "scope_grant_authority_sha256": scope.authority_sha256,
                    "subject_actor_id": scope.subject_actor_id,
                },
                session=session,
            )
            job_ref = new_id("media_job")
            row = MediaJobRow(
                job_ref=job_ref,
                tenant_ref=scope.tenant_ref,
                entity_ref=scope.entity_ref,
                store_ref=scope.store_ref,
                scope_grant_authority_sha256=scope.authority_sha256,
                subject_actor_id=scope.subject_actor_id,
                tool_name=tool_name,
                tool_version=tool_version,
                project_ref=project_ref,
                brief_ref=brief_ref,
                provider=provider,
                connector_ref=connector_ref,
                connector_binding_sha256=connector_binding,
                idempotency_sha256=idempotency,
                request_sha256=request_sha,
                request_fingerprint_sha256=fingerprint,
                request_evidence_id=evidence_record.id,
                request_evidence_sha256=evidence_record.sha256,
                created_at=now,
            )
            try:
                with session.begin_nested():
                    session.add(row)
                    session.flush()
            except IntegrityError:
                winner = session.scalar(
                    select(MediaJobRow).where(
                        MediaJobRow.tenant_ref == scope.tenant_ref,
                        MediaJobRow.entity_ref == scope.entity_ref,
                        MediaJobRow.store_ref == scope.store_ref,
                        MediaJobRow.scope_grant_authority_sha256 == scope.authority_sha256,
                        MediaJobRow.idempotency_sha256 == idempotency,
                    )
                )
                if winner is None or winner.request_fingerprint_sha256 != fingerprint:
                    raise ValueError("media_job_idempotency_conflict") from None
                winner_event = self._validate_event_chain(session, winner, scope)[-1]
                if secure_submission:
                    self._request_binding(session, winner)
                if worker_input_sha256 is not None:
                    worker_row = session.scalar(
                        select(MediaJobWorkerInputRow).where(
                            MediaJobWorkerInputRow.job_ref == winner.job_ref
                        )
                    )
                    if (
                        worker_row is None
                        or worker_row.worker_input_sha256 != worker_input_sha256
                    ):
                        raise ValueError(
                            "media_job_worker_input_conflict"
                        ) from None
                return self._projection(winner, winner_event)
            if normalized_worker_input is not None and worker_input_sha256 is not None:
                worker_evidence = self.evidence.capture_media_job_evidence(
                    content=canonical_json(normalized_worker_input),
                    filename="media-job-worker-input.json",
                    content_type="application/json",
                    source=WORKER_INPUT_SOURCE,
                    source_ref=f"media-job://{job_ref}/worker-input",
                    grade=EvidenceGrade.B,
                    effective_at=now.isoformat(),
                    recorded_at=now.isoformat(),
                    created_by=scope.subject_actor_id,
                    metadata={
                        "contract_id": WORKER_INPUT_CONTRACT,
                        "tenant_ref": scope.tenant_ref,
                        "entity_ref": scope.entity_ref,
                        "store_ref": scope.store_ref,
                        "scope_grant_authority_sha256": scope.authority_sha256,
                        "subject_actor_id": scope.subject_actor_id,
                        "media_job_ref": job_ref,
                        "worker_input_sha256": worker_input_sha256,
                    },
                    session=session,
                )
                session.add(
                    MediaJobWorkerInputRow(
                        input_ref=new_id("media_input"),
                        job_ref=job_ref,
                        tenant_ref=scope.tenant_ref,
                        entity_ref=scope.entity_ref,
                        store_ref=scope.store_ref,
                        scope_grant_authority_sha256=scope.authority_sha256,
                        tool_name=tool_name,
                        tool_version=tool_version,
                        worker_input_json=normalized_worker_input,
                        worker_input_sha256=worker_input_sha256,
                        evidence_id=worker_evidence.id,
                        evidence_sha256=worker_evidence.sha256,
                        recorded_at=now,
                    )
                )
            if secure_submission:
                assert descriptor_sha256 is not None and descriptor_bytes is not None
                descriptor_evidence = self.evidence.capture_media_job_evidence(
                    content=descriptor_bytes,
                    filename="media-job-tool-descriptor.json",
                    content_type="application/json",
                    source=TOOL_DESCRIPTOR_SOURCE,
                    source_ref=(
                        f"media-job://{job_ref}/tool-descriptor/{descriptor_sha256}"
                    ),
                    grade=EvidenceGrade.B,
                    effective_at=now.isoformat(),
                    recorded_at=now.isoformat(),
                    created_by=scope.subject_actor_id,
                    metadata={
                        "contract_id": TOOL_DESCRIPTOR_EVIDENCE_CONTRACT,
                        "tenant_ref": scope.tenant_ref,
                        "entity_ref": scope.entity_ref,
                        "store_ref": scope.store_ref,
                        "scope_grant_authority_sha256": scope.authority_sha256,
                        "subject_actor_id": scope.subject_actor_id,
                        "media_job_ref": job_ref,
                        "descriptor_sha256": descriptor_sha256,
                    },
                    session=session,
                )
                session.add(
                    MediaJobRequestBindingRow(
                        binding_ref=new_id("media_binding"),
                        job_ref=job_ref,
                        tenant_ref=scope.tenant_ref,
                        entity_ref=scope.entity_ref,
                        store_ref=scope.store_ref,
                        scope_grant_authority_sha256=scope.authority_sha256,
                        request_evidence_id=evidence_record.id,
                        request_evidence_sha256=evidence_record.sha256,
                        descriptor_evidence_id=descriptor_evidence.id,
                        descriptor_evidence_sha256=descriptor_evidence.sha256,
                        tool_descriptor_sha256=descriptor_sha256,
                        recorded_at=now,
                    )
                )
            event = self._append_event(
                session=session,
                job=row,
                scope=scope,
                state="QUEUED",
                reason=None,
                now=now,
                command_idempotency_sha256=idempotency,
                command_request_sha256=request_sha,
            )
            session.add(MediaJobEvidenceLinkRow(
                link_ref=new_id("media_link"), job_ref=job_ref, event_ref=None,
                tenant_ref=scope.tenant_ref, entity_ref=scope.entity_ref, store_ref=scope.store_ref,
                scope_grant_authority_sha256=scope.authority_sha256, purpose="request_input",
                evidence_id=evidence_record.id, blob_sha256=evidence_record.sha256,
                source=evidence_record.source, source_ref=evidence_record.source_ref,
                effective_at=now, recorded_at=now, fresh_until=None,
            ))
            if analysis_input_record is not None:
                session.add(
                    MediaJobEvidenceLinkRow(
                        link_ref=new_id("media_link"),
                        job_ref=job_ref,
                        event_ref=None,
                        tenant_ref=scope.tenant_ref,
                        entity_ref=scope.entity_ref,
                        store_ref=scope.store_ref,
                        scope_grant_authority_sha256=scope.authority_sha256,
                        purpose="analysis_input",
                        evidence_id=analysis_input_record.id,
                        blob_sha256=analysis_input_record.blob_sha256,
                        source=analysis_input_record.source,
                        source_ref=analysis_input_record.source_ref,
                        effective_at=analysis_input_record.effective_at,
                        recorded_at=analysis_input_record.recorded_at,
                        fresh_until=None,
                    )
                )
            if blueprint_input_record is not None:
                session.add(
                    MediaJobEvidenceLinkRow(
                        link_ref=new_id("media_link"),
                        job_ref=job_ref,
                        event_ref=None,
                        tenant_ref=scope.tenant_ref,
                        entity_ref=scope.entity_ref,
                        store_ref=scope.store_ref,
                        scope_grant_authority_sha256=scope.authority_sha256,
                        purpose="blueprint_input",
                        evidence_id=blueprint_input_record.id,
                        blob_sha256=blueprint_input_record.blob_sha256,
                        source=blueprint_input_record.source,
                        source_ref=blueprint_input_record.source_ref,
                        effective_at=blueprint_input_record.effective_at,
                        recorded_at=blueprint_input_record.recorded_at,
                        fresh_until=None,
                    )
                )
            return self._projection(row, event)

    @staticmethod
    def _lock_idempotency_winner(
        *,
        session: Session,
        scope: MediaJobScope,
        idempotency_sha256: str,
    ) -> None:
        """Serialize one exact-scope idempotency winner before Evidence writes."""

        if session.get_bind().dialect.name != "postgresql":
            return
        session.execute(
            text(
                "SELECT pg_advisory_xact_lock("
                "hashtextextended(concat_ws(chr(31), "
                "CAST(:tenant_ref AS text), CAST(:entity_ref AS text), "
                "CAST(:store_ref AS text), CAST(:authority_sha256 AS text), "
                "CAST(:idempotency_sha256 AS text)), 0))"
            ),
            {
                "tenant_ref": scope.tenant_ref,
                "entity_ref": scope.entity_ref,
                "store_ref": scope.store_ref,
                "authority_sha256": scope.authority_sha256,
                "idempotency_sha256": idempotency_sha256,
            },
        )

    def _append_event(
        self,
        *,
        session: Session,
        job: MediaJobRow,
        scope: MediaJobScope,
        state: str,
        reason: str | None,
        now: datetime,
        command_idempotency_sha256: str,
        command_request_sha256: str,
    ) -> MediaJobEventRow:
        if state not in MEDIA_JOB_STATES:
            raise ValueError("media_job_state_invalid")
        if reason != MEDIA_JOB_SAFE_REASON_BY_STATE[state]:
            raise ValueError("media_job_safe_reason_invalid")
        previous = session.scalar(select(MediaJobEventRow).where(MediaJobEventRow.job_ref == job.job_ref).order_by(MediaJobEventRow.ordinal.desc()))
        if previous is not None and (
            _utc_datetime(now) < _utc_datetime(previous.occurred_at)
            or _utc_datetime(now) < _utc_datetime(previous.recorded_at)
        ):
            raise ValueError("media_job_event_time_regressed")
        ordinal = (previous.ordinal + 1) if previous else 1
        previous_hash = previous.event_sha256 if previous else None
        public_projection = {
            "job_ref": job.job_ref,
            "ordinal": ordinal,
            "state": state,
            "safe_reason_code": reason,
        }
        event_hash = event_seal(
            job=job,
            job_ref=job.job_ref,
            tenant_ref=scope.tenant_ref,
            entity_ref=scope.entity_ref,
            store_ref=scope.store_ref,
            authority_sha256=scope.authority_sha256,
            subject_actor_id=scope.subject_actor_id,
            ordinal=ordinal,
            stream_kind=EVENT_STREAM,
            state=state,
            safe_reason_code=reason,
            previous_event_sha256=previous_hash,
            public_projection_json=public_projection,
            occurred_at=now,
            recorded_at=now,
            command_idempotency_sha256=command_idempotency_sha256,
            command_request_sha256=command_request_sha256,
        )
        event = MediaJobEventRow(
            event_ref=new_id("media_event"), job_ref=job.job_ref,
            tenant_ref=scope.tenant_ref, entity_ref=scope.entity_ref, store_ref=scope.store_ref,
            scope_grant_authority_sha256=scope.authority_sha256, ordinal=ordinal,
            stream_kind=EVENT_STREAM, state=state, safe_reason_code=reason,
            previous_event_sha256=previous_hash, event_sha256=event_hash,
            command_idempotency_sha256=command_idempotency_sha256,
            command_request_sha256=command_request_sha256,
            public_projection_json=public_projection,
            occurred_at=now, recorded_at=now,
        )
        session.add(event)
        session.flush()
        return event

    def _load_job(
        self,
        session: Session,
        scope: MediaJobScope,
        job_ref: str,
        *,
        for_update: bool = False,
    ) -> MediaJobRow:
        statement = select(MediaJobRow).where(
                MediaJobRow.job_ref == _required_text(job_ref, "job_ref"),
                MediaJobRow.tenant_ref == scope.tenant_ref,
                MediaJobRow.entity_ref == scope.entity_ref,
                MediaJobRow.store_ref == scope.store_ref,
                MediaJobRow.scope_grant_authority_sha256 == scope.authority_sha256,
                MediaJobRow.subject_actor_id == scope.subject_actor_id,
            )
        if for_update:
            statement = statement.with_for_update()
        row = session.scalar(statement)
        if row is None:
            raise KeyError("media_job_not_visible")
        return row

    def _validate_event_chain(
        self,
        session: Session,
        job: MediaJobRow,
        scope: MediaJobScope,
    ) -> list[MediaJobEventRow]:
        rows = session.scalars(
            select(MediaJobEventRow)
            .where(MediaJobEventRow.job_ref == job.job_ref)
            .order_by(MediaJobEventRow.ordinal)
        ).all()
        previous: MediaJobEventRow | None = None
        future_limit = self._now() + EVENT_FUTURE_TOLERANCE
        for event in rows:
            occurred_at = _utc_datetime(event.occurred_at)
            recorded_at = _utc_datetime(event.recorded_at)
            transition_invalid = (
                event.state != "QUEUED"
                if previous is None
                else event.state not in MEDIA_JOB_TRANSITIONS.get(previous.state, frozenset())
            )
            if (
                event.tenant_ref != scope.tenant_ref
                or event.entity_ref != scope.entity_ref
                or event.store_ref != scope.store_ref
                or event.scope_grant_authority_sha256 != scope.authority_sha256
                or event.stream_kind != EVENT_STREAM
                or event.state not in MEDIA_JOB_STATES
                or event.safe_reason_code != MEDIA_JOB_SAFE_REASON_BY_STATE[event.state]
                or transition_invalid
                or occurred_at > recorded_at
                or occurred_at > future_limit
                or recorded_at > future_limit
                or (
                    previous is not None
                    and (
                        occurred_at < _utc_datetime(previous.occurred_at)
                        or recorded_at < _utc_datetime(previous.recorded_at)
                    )
                )
                or event.ordinal != (previous.ordinal + 1 if previous else 1)
                or event.previous_event_sha256 != (previous.event_sha256 if previous else None)
                or not isinstance(event.public_projection_json, dict)
                or set(event.public_projection_json) != {
                    "job_ref",
                    "ordinal",
                    "state",
                    "safe_reason_code",
                }
                or event.public_projection_json.get("job_ref") != job.job_ref
                or event.public_projection_json.get("ordinal") != event.ordinal
                or event.public_projection_json.get("state") != event.state
                or event.public_projection_json.get("safe_reason_code") != event.safe_reason_code
            ):
                raise RuntimeError("media_job_event_contract_drifted")
            expected_hash = event_seal(
                job=None,
                job_ref=event.job_ref,
                tenant_ref=event.tenant_ref,
                entity_ref=event.entity_ref,
                store_ref=event.store_ref,
                authority_sha256=event.scope_grant_authority_sha256,
                subject_actor_id=job.subject_actor_id,
                ordinal=event.ordinal,
                stream_kind=event.stream_kind,
                state=event.state,
                safe_reason_code=event.safe_reason_code,
                previous_event_sha256=event.previous_event_sha256,
                public_projection_json=event.public_projection_json,
                occurred_at=event.occurred_at,
                recorded_at=event.recorded_at,
                command_idempotency_sha256=event.command_idempotency_sha256,
                command_request_sha256=event.command_request_sha256,
            )
            if event.event_sha256 != expected_hash:
                raise RuntimeError("media_job_event_contract_drifted")
            previous = event
        if not rows:
            raise RuntimeError("media_job_event_missing")
        return rows

    def _request_binding(
        self,
        session: Session,
        row: MediaJobRow,
    ) -> MediaJobBindingProjection:
        record = session.get(EvidenceRecordRow, row.request_evidence_id)
        if record is None or record.blob_sha256 != row.request_evidence_sha256:
            raise RuntimeError("media_job_request_evidence_drifted")
        blob = session.get(EvidenceBlobRow, record.blob_sha256)
        scope_binding = sha256_bytes(
            canonical_json(
                {
                    "tenant_ref": row.tenant_ref,
                    "entity_ref": row.entity_ref,
                    "store_ref": row.store_ref,
                    "authority_sha256": row.scope_grant_authority_sha256,
                    "subject_actor_id": row.subject_actor_id,
                }
            )
        )
        expected_source_ref = (
            f"media-job://{scope_binding}/{row.idempotency_sha256}/request"
        )
        link = session.scalar(
            select(MediaJobEvidenceLinkRow).where(
                MediaJobEvidenceLinkRow.job_ref == row.job_ref,
                MediaJobEvidenceLinkRow.event_ref.is_(None),
                MediaJobEvidenceLinkRow.purpose == "request_input",
            )
        )
        metadata = record.metadata_json if isinstance(record.metadata_json, dict) else {}
        if (
            blob is None
            or sha256_bytes(blob.content_bytes) != blob.sha256
            or blob.sha256 != row.request_evidence_sha256
            or row.request_sha256 != blob.sha256
            or record.source != REQUEST_SOURCE
            or record.content_type != "application/json"
            or record.source_ref != expected_source_ref
            or record.created_by != row.subject_actor_id
            or _utc_datetime(record.effective_at) != _utc_datetime(row.created_at)
            or _utc_datetime(record.recorded_at) != _utc_datetime(row.created_at)
            or record.effective_until is not None
            or metadata
            != {
                "contract_id": REQUEST_CONTRACT,
                "media_job_request_fingerprint_sha256": row.request_fingerprint_sha256,
                "tenant_ref": row.tenant_ref,
                "entity_ref": row.entity_ref,
                "store_ref": row.store_ref,
                "scope_grant_authority_sha256": row.scope_grant_authority_sha256,
                "subject_actor_id": row.subject_actor_id,
            }
            or link is None
            or link.evidence_id != record.id
            or link.blob_sha256 != blob.sha256
            or link.source != record.source
            or link.source_ref != record.source_ref
            or link.tenant_ref != row.tenant_ref
            or link.entity_ref != row.entity_ref
            or link.store_ref != row.store_ref
            or link.scope_grant_authority_sha256
            != row.scope_grant_authority_sha256
        ):
            raise RuntimeError("media_job_request_evidence_drifted")
        try:
            request = json.loads(blob.content_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("media_job_request_evidence_drifted") from exc
        if not isinstance(request, dict):
            raise RuntimeError("media_job_request_evidence_drifted")
        try:
            self._validate_commander_request(request)
        except ValueError as exc:
            raise RuntimeError("media_job_request_contract_drifted") from exc
        if (
            request.get("tool_name") != row.tool_name
            or request.get("tool_version") != row.tool_version
            or request.get("project_ref") != row.project_ref
            or request.get("brief_ref") != row.brief_ref
            or request.get("provider") != row.provider
            or request.get("connector_ref") != row.connector_ref
            or request.get("connector_binding_sha256")
            != row.connector_binding_sha256
            or request.get("idempotency_sha256") != row.idempotency_sha256
        ):
            raise RuntimeError("media_job_request_header_drifted")
        binding = session.scalar(
            select(MediaJobRequestBindingRow).where(
                MediaJobRequestBindingRow.job_ref == row.job_ref
            )
        )
        descriptor_record = (
            session.get(EvidenceRecordRow, binding.descriptor_evidence_id)
            if binding is not None
            else None
        )
        descriptor_blob = (
            session.get(EvidenceBlobRow, descriptor_record.blob_sha256)
            if descriptor_record is not None
            else None
        )
        descriptor_metadata = (
            descriptor_record.metadata_json
            if descriptor_record is not None
            else None
        )
        if (
            binding is None
            or descriptor_record is None
            or descriptor_blob is None
            or binding.tenant_ref != row.tenant_ref
            or binding.entity_ref != row.entity_ref
            or binding.store_ref != row.store_ref
            or binding.scope_grant_authority_sha256
            != row.scope_grant_authority_sha256
            or binding.request_evidence_id != record.id
            or binding.request_evidence_sha256 != record.blob_sha256
            or _utc_datetime(binding.recorded_at) != _utc_datetime(row.created_at)
            or binding.descriptor_evidence_id != descriptor_record.id
            or binding.descriptor_evidence_sha256 != descriptor_record.blob_sha256
            or descriptor_blob.sha256 != descriptor_record.blob_sha256
            or sha256_bytes(descriptor_blob.content_bytes) != descriptor_blob.sha256
            or descriptor_record.source != TOOL_DESCRIPTOR_SOURCE
            or descriptor_record.content_type != "application/json"
            or descriptor_record.source_ref
            != (
                f"media-job://{row.job_ref}/tool-descriptor/"
                f"{binding.tool_descriptor_sha256}"
            )
            or descriptor_record.grade != EvidenceGrade.B.value
            or descriptor_record.created_by != row.subject_actor_id
            or _utc_datetime(descriptor_record.effective_at)
            != _utc_datetime(row.created_at)
            or _utc_datetime(descriptor_record.recorded_at)
            != _utc_datetime(row.created_at)
            or descriptor_record.effective_until is not None
            or descriptor_metadata
            != {
                "contract_id": TOOL_DESCRIPTOR_EVIDENCE_CONTRACT,
                "tenant_ref": row.tenant_ref,
                "entity_ref": row.entity_ref,
                "store_ref": row.store_ref,
                "scope_grant_authority_sha256": row.scope_grant_authority_sha256,
                "subject_actor_id": row.subject_actor_id,
                "media_job_ref": row.job_ref,
                "descriptor_sha256": binding.tool_descriptor_sha256,
            }
            or request.get("tool_descriptor_sha256")
            != binding.tool_descriptor_sha256
        ):
            raise RuntimeError("media_job_tool_descriptor_evidence_drifted")
        try:
            descriptor = json.loads(descriptor_blob.content_bytes)
            descriptor_sha256 = self._validate_tool_descriptor(
                descriptor=descriptor,
                request=request,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise RuntimeError("media_job_tool_descriptor_evidence_drifted") from exc
        if descriptor_sha256 != binding.tool_descriptor_sha256:
            raise RuntimeError("media_job_tool_descriptor_evidence_drifted")
        return MediaJobBindingProjection(
            job_ref=row.job_ref,
            tool_name=row.tool_name,
            tool_version=row.tool_version,
            provider=row.provider,
            connector_ref=row.connector_ref,
            connector_binding_sha256=row.connector_binding_sha256,
            tool_descriptor_sha256=binding.tool_descriptor_sha256,
            campaign_brief_sha256=request["campaign_brief_sha256"],
            request_sha256=row.request_sha256,
        )

    def _worker_input_projection(
        self,
        *,
        session: Session,
        job: MediaJobRow,
        scope: MediaJobScope,
    ) -> MediaJobWorkerInputProjection:
        row = session.scalar(
            select(MediaJobWorkerInputRow).where(
                MediaJobWorkerInputRow.job_ref == job.job_ref,
                MediaJobWorkerInputRow.tenant_ref == scope.tenant_ref,
                MediaJobWorkerInputRow.entity_ref == scope.entity_ref,
                MediaJobWorkerInputRow.store_ref == scope.store_ref,
                MediaJobWorkerInputRow.scope_grant_authority_sha256
                == scope.authority_sha256,
            )
        )
        if row is None:
            raise KeyError("media_job_worker_input_not_found")
        record = session.get(EvidenceRecordRow, row.evidence_id)
        blob = session.get(EvidenceBlobRow, row.evidence_sha256)
        expected_metadata = {
            "contract_id": WORKER_INPUT_CONTRACT,
            "tenant_ref": scope.tenant_ref,
            "entity_ref": scope.entity_ref,
            "store_ref": scope.store_ref,
            "scope_grant_authority_sha256": scope.authority_sha256,
            "subject_actor_id": scope.subject_actor_id,
            "media_job_ref": job.job_ref,
            "worker_input_sha256": row.worker_input_sha256,
        }
        normalized = self._normalize_worker_input(
            worker_input=row.worker_input_json,
            request={
                "tool_name": job.tool_name,
                "tool_version": job.tool_version,
                "project_ref": job.project_ref,
                "brief_ref": job.brief_ref,
            },
        )
        encoded = canonical_json(normalized)
        if (
            row.tool_name != job.tool_name
            or row.tool_version != job.tool_version
            or row.worker_input_json != normalized
            or row.worker_input_sha256 != sha256_bytes(encoded)
            or record is None
            or blob is None
            or record.blob_sha256 != row.evidence_sha256
            or blob.sha256 != row.evidence_sha256
            or sha256_bytes(blob.content_bytes) != blob.sha256
            or blob.content_bytes != encoded
            or record.source != WORKER_INPUT_SOURCE
            or record.source_ref != f"media-job://{job.job_ref}/worker-input"
            or record.grade != EvidenceGrade.B.value
            or record.created_by != scope.subject_actor_id
            or record.metadata_json != expected_metadata
        ):
            raise RuntimeError("media_job_worker_input_drifted")
        return MediaJobWorkerInputProjection(
            job_ref=job.job_ref,
            tool_name=job.tool_name,
            tool_version=job.tool_version,
            payload=dict(normalized),
            worker_input_sha256=row.worker_input_sha256,
            evidence_id=row.evidence_id,
            recorded_at=_utc_datetime(row.recorded_at).isoformat(),
        )

    def read(self, *, principal: Principal, store_ref: str, job_ref: str) -> MediaJobProjection:
        scope = self._resolve_current(principal=principal, store_ref=store_ref)
        with Session(self.engine) as session:
            row = self._load_job(session, scope, job_ref)
            event = self._validate_event_chain(session, row, scope)[-1]
            return self._projection(row, event)

    def read_worker_input(
        self,
        *,
        principal: Principal,
        store_ref: str,
        job_ref: str,
    ) -> MediaJobWorkerInputProjection:
        scope = self._resolve_current(principal=principal, store_ref=store_ref)
        with Session(self.engine) as session:
            job = self._load_job(session, scope, job_ref)
            self._validate_event_chain(session, job, scope)
            return self._worker_input_projection(
                session=session,
                job=job,
                scope=scope,
            )

    def read_bound(
        self,
        *,
        principal: Principal,
        store_ref: str,
        job_ref: str,
    ) -> tuple[MediaJobProjection, MediaJobBindingProjection]:
        scope = self._resolve_current(principal=principal, store_ref=store_ref)
        with Session(self.engine) as session:
            row = self._load_job(session, scope, job_ref)
            event = self._validate_event_chain(session, row, scope)[-1]
            return self._projection(row, event), self._request_binding(session, row)

    def claim_provider_attempt(
        self,
        *,
        principal: Principal,
        store_ref: str,
        job_ref: str,
    ) -> tuple[MediaJobProjection, bool]:
        """Durably claim the sole provider attempt without executing a provider."""

        scope = self._resolve_current(principal=principal, store_ref=store_ref)
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            self._lock_schema_transition_in_session(session)
            EvidenceService.lock_scope_authority_in_session(
                tenant_ref=scope.tenant_ref,
                store_ref=scope.store_ref,
                subject_actor_id=scope.subject_actor_id,
                session=session,
            )
            fresh_scope = self._resolve_current(
                principal=principal,
                store_ref=store_ref,
            )
            if fresh_scope != scope:
                raise PermissionError("scope_authority_changed")
            row = session.scalar(
                select(MediaJobRow)
                .where(
                    MediaJobRow.job_ref == _required_text(job_ref, "job_ref"),
                    MediaJobRow.tenant_ref == scope.tenant_ref,
                    MediaJobRow.entity_ref == scope.entity_ref,
                    MediaJobRow.store_ref == scope.store_ref,
                    MediaJobRow.scope_grant_authority_sha256
                    == scope.authority_sha256,
                    MediaJobRow.subject_actor_id == scope.subject_actor_id,
                )
                .with_for_update()
            )
            if row is None:
                raise KeyError("media_job_not_visible")
            latest = self._validate_event_chain(session, row, scope)[-1]
            if latest.state != "QUEUED":
                return self._projection(row, latest), False
            dispatched = self._append_event(
                session=session,
                job=row,
                scope=scope,
                state="DISPATCHED",
                reason=None,
                now=self._now(),
                command_idempotency_sha256=row.idempotency_sha256,
                command_request_sha256=row.request_sha256,
            )
            return self._projection(row, dispatched), True

    def guard_provider_attempt_in_session(
        self,
        *,
        session: Session,
        principal: Principal,
        store_ref: str,
        job_ref: str,
        expected_event_ordinal: int,
        expected_recorded_at: str,
    ) -> None:
        """Lock and revalidate the exact durable attempt before artifact writes."""

        scope = self._resolve_current(principal=principal, store_ref=store_ref)
        job = self._load_job(session, scope, job_ref, for_update=True)
        latest = self._validate_event_chain(session, job, scope)[-1]
        if (
            latest.state != "DISPATCHED"
            or latest.ordinal != expected_event_ordinal
            or _utc_datetime(latest.recorded_at).isoformat()
            != expected_recorded_at
        ):
            raise ValueError("media_job_provider_attempt_not_current")

    def _append_provider_terminal_in_session(
        self,
        *,
        session: Session,
        scope: MediaJobScope,
        job: MediaJobRow,
        state: str,
        now: datetime | None = None,
    ) -> MediaJobEventRow:
        latest = self._validate_event_chain(session, job, scope)[-1]
        if latest.state in TERMINAL_STATES:
            if latest.state != state:
                raise ValueError("media_job_provider_terminal_conflict")
            return latest
        if latest.state not in {"DISPATCHED", "RUNNING", "UPLOADING"}:
            raise ValueError("media_job_provider_terminal_not_admitted")
        now = self._now() if now is None else _utc_datetime(now)
        if now < _utc_datetime(latest.recorded_at):
            raise ValueError("media_job_provider_completion_time_invalid")
        if state == "SUCCEEDED":
            if latest.state == "DISPATCHED":
                latest = self._append_event(
                    session=session,
                    job=job,
                    scope=scope,
                    state="RUNNING",
                    reason=None,
                    now=now,
                    command_idempotency_sha256=job.idempotency_sha256,
                    command_request_sha256=job.request_sha256,
                )
            if latest.state == "RUNNING":
                latest = self._append_event(
                    session=session,
                    job=job,
                    scope=scope,
                    state="UPLOADING",
                    reason=None,
                    now=now,
                    command_idempotency_sha256=job.idempotency_sha256,
                    command_request_sha256=job.request_sha256,
                )
        latest = self._append_event(
            session=session,
            job=job,
            scope=scope,
            state=state,
            reason=MEDIA_JOB_SAFE_REASON_BY_STATE[state],
            now=now,
            command_idempotency_sha256=job.idempotency_sha256,
            command_request_sha256=job.request_sha256,
        )
        evidence_record = self.evidence.capture_media_job_evidence(
            content=canonical_json(latest.public_projection_json),
            filename="media-job-transition.json",
            content_type="application/json",
            source="governed-media-job-transition",
            source_ref=f"media-job://{job.job_ref}/transition/{latest.event_ref}",
            grade=EvidenceGrade.B,
            effective_at=now.isoformat(),
            recorded_at=now.isoformat(),
            created_by=scope.subject_actor_id,
            metadata={
                "contract_id": "kjds-governed-media-job-transition-v1",
                "tenant_ref": scope.tenant_ref,
                "entity_ref": scope.entity_ref,
                "store_ref": scope.store_ref,
                "scope_grant_authority_sha256": scope.authority_sha256,
                "subject_actor_id": scope.subject_actor_id,
                "event_sha256": latest.event_sha256,
            },
            session=session,
        )
        session.add(
            MediaJobEvidenceLinkRow(
                link_ref=new_id("media_link"),
                job_ref=job.job_ref,
                event_ref=latest.event_ref,
                tenant_ref=scope.tenant_ref,
                entity_ref=scope.entity_ref,
                store_ref=scope.store_ref,
                scope_grant_authority_sha256=scope.authority_sha256,
                purpose="artifact_terminal",
                evidence_id=evidence_record.id,
                blob_sha256=evidence_record.sha256,
                source=evidence_record.source,
                source_ref=evidence_record.source_ref,
                effective_at=now,
                recorded_at=now,
                fresh_until=None,
            )
        )
        session.flush()
        return latest

    def record_provider_terminal(
        self,
        *,
        principal: Principal,
        store_ref: str,
        job_ref: str,
        state: str,
    ) -> MediaJobTerminalProjection:
        """Reject the legacy self-certified provider terminal entrypoint."""

        del principal, store_ref, job_ref, state
        raise PermissionError("media_job_provider_terminal_authority_required")

    def events(
        self,
        *,
        principal: Principal,
        store_ref: str,
        job_ref: str,
        after_ordinal: int = 0,
        limit: int = 100,
    ) -> list[MediaJobEventProjection]:
        scope = self._resolve_current(principal=principal, store_ref=store_ref)
        if after_ordinal < 0 or not 0 < limit <= 100:
            raise ValueError("media_job_event_page_invalid")
        with Session(self.engine) as session:
            row = self._load_job(session, scope, job_ref)
            self._validate_event_chain(session, row, scope)
            rows = session.scalars(select(MediaJobEventRow).where(MediaJobEventRow.job_ref == row.job_ref, MediaJobEventRow.ordinal > after_ordinal).order_by(MediaJobEventRow.ordinal).limit(limit)).all()
            return [
                MediaJobEventProjection(
                    e.event_ref,
                    e.job_ref,
                    e.ordinal,
                    e.state,
                    e.safe_reason_code,
                    _utc_datetime(e.occurred_at).isoformat(),
                )
                for e in rows
            ]

    def cancel(
        self,
        *,
        principal: Principal,
        store_ref: str,
        job_ref: str,
        idempotency_key: str,
    ) -> MediaJobProjection:
        scope = self._resolve_current(principal=principal, store_ref=store_ref)
        idempotency_key = _required_text(idempotency_key, "idempotency_key")
        command_request_sha = sha256_bytes(canonical_json({"job_ref": job_ref, "idempotency_key": idempotency_key}))
        command_idempotency_sha = sha256_bytes(idempotency_key.encode("utf-8"))
        now = self._now()
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            self._lock_schema_transition_in_session(session)
            EvidenceService.lock_scope_authority_in_session(
                tenant_ref=scope.tenant_ref,
                store_ref=scope.store_ref,
                subject_actor_id=scope.subject_actor_id,
                session=session,
            )
            fresh_scope = self._resolve_current(principal=principal, store_ref=store_ref)
            if fresh_scope != scope:
                raise PermissionError("scope_authority_changed")
            row = self._load_job(session, scope, job_ref, for_update=True)
            previous = self._validate_event_chain(session, row, scope)[-1]
            if previous.state == "CANCELLED":
                if previous.command_idempotency_sha256 == command_idempotency_sha:
                    return self._projection(row, previous)
                raise ValueError("media_job_cancel_idempotency_conflict")
            if previous.state != "QUEUED":
                raise ValueError("media_job_cancel_not_supported")
            event = self._append_event(
                session=session,
                job=row,
                scope=scope,
                state="CANCELLED",
                reason="cancelled_by_request",
                now=now,
                command_idempotency_sha256=command_idempotency_sha,
                command_request_sha256=command_request_sha,
            )
            evidence_record = self.evidence.capture_media_job_evidence(
                content=canonical_json(event.public_projection_json),
                filename="media-job-transition.json",
                content_type="application/json",
                source="governed-media-job-transition",
                source_ref=f"media-job://{row.job_ref}/transition/{event.event_ref}",
                grade=EvidenceGrade.B,
                effective_at=now.isoformat(),
                recorded_at=now.isoformat(),
                created_by=scope.subject_actor_id,
                metadata={
                    "contract_id": "kjds-governed-media-job-transition-v1",
                    "tenant_ref": scope.tenant_ref,
                    "entity_ref": scope.entity_ref,
                    "store_ref": scope.store_ref,
                    "scope_grant_authority_sha256": scope.authority_sha256,
                    "subject_actor_id": scope.subject_actor_id,
                    "event_sha256": event.event_sha256,
                },
                session=session,
            )
            session.add(MediaJobEvidenceLinkRow(
                link_ref=new_id("media_link"), job_ref=row.job_ref, event_ref=event.event_ref,
                tenant_ref=scope.tenant_ref, entity_ref=scope.entity_ref, store_ref=scope.store_ref,
                scope_grant_authority_sha256=scope.authority_sha256, purpose="artifact_terminal",
                evidence_id=evidence_record.id, blob_sha256=evidence_record.sha256,
                source=evidence_record.source, source_ref=evidence_record.source_ref,
                effective_at=now, recorded_at=now, fresh_until=None,
            ))
            return self._projection(row, event)

    @staticmethod
    def _result_receipt_projection(
        row: MediaJobResultReceiptRow,
    ) -> MediaJobResultReceiptProjection:
        return MediaJobResultReceiptProjection(
            receipt_ref=row.receipt_ref,
            job_ref=row.job_ref,
            event_ref=row.event_ref,
            state=row.state,
            provider=row.provider,
            connector_ref=row.connector_ref,
            result_kind=row.result_kind,
            artifact_evidence_refs=tuple(row.artifact_evidence_refs),
            content_asset_ref=row.content_asset_ref,
            receipt_sha256=row.receipt_sha256,
            recorded_at=_utc_datetime(row.recorded_at).isoformat(),
        )

    @staticmethod
    def _validate_result_receipt(
        *,
        receipt: Mapping[str, Any],
        job: MediaJobRow,
        event: MediaJobEventRow,
    ) -> tuple[dict[str, Any], str]:
        expected_fields = {
            "contract_id",
            "provider",
            "connector_ref",
            "connector_binding_sha256",
            "result_kind",
            "artifact_evidence_refs",
            "content_asset_ref",
            "receipt_sha256",
        }
        if not isinstance(receipt, Mapping) or set(receipt) != expected_fields:
            raise ValueError("media_job_result_receipt_shape_invalid")
        if receipt["contract_id"] != RESULT_RECEIPT_CONTRACT:
            raise ValueError("media_job_result_receipt_contract_invalid")
        if event.state not in RESULT_RECEIPT_TERMINAL_STATES:
            raise ValueError("media_job_result_requires_terminal_event")
        if event.state not in RESULT_RECEIPT_ADMITTED_STATES:
            raise PermissionError(
                "media_job_non_success_result_authority_not_admitted"
            )
        if job.tool_name not in {"media.video_blueprint", "media.video_render", "tutorial.build"}:
            raise ValueError("media_job_result_tool_not_admitted")
        if receipt["provider"] != job.provider or receipt["connector_ref"] != job.connector_ref:
            raise ValueError("media_job_result_connector_drifted")
        if receipt["connector_binding_sha256"] != job.connector_binding_sha256:
            raise ValueError("media_job_result_binding_drifted")
        result_kind = _required_text(receipt["result_kind"], "result_kind")
        if result_kind not in RESULT_KIND_BY_STATE[event.state]:
            raise ValueError("media_job_result_kind_invalid")
        if event.state == "SUCCEEDED" and (
            (
                job.tool_name == "media.video_blueprint"
                and result_kind != "editing_blueprint_evidence"
            )
            or (
                job.tool_name == "media.video_render"
                and result_kind != "video_artifact_evidence"
            )
            or (
                job.tool_name == "tutorial.build"
                and result_kind != "tutorial_graph_and_media_evidence"
            )
        ):
            raise ValueError("media_job_result_kind_invalid")
        refs = receipt["artifact_evidence_refs"]
        if not isinstance(refs, list) or len(refs) > 100:
            raise ValueError("media_job_result_evidence_refs_invalid")
        normalized_refs = [
            value.strip() if isinstance(value, str) else value for value in refs
        ]
        if (
            any(
                not isinstance(value, str)
                or not value.strip()
                or len(value.strip()) > 500
                for value in refs
            )
            or len(set(normalized_refs)) != len(normalized_refs)
            or any(
                value != normalized
                for value, normalized in zip(refs, normalized_refs, strict=True)
            )
        ):
            raise ValueError("media_job_result_evidence_refs_invalid")
        content_asset_ref = receipt["content_asset_ref"]
        if content_asset_ref is not None:
            content_asset_ref = _required_text(content_asset_ref, "content_asset_ref")
            if len(content_asset_ref) > 500:
                raise ValueError("media_job_result_content_asset_ref_invalid")
        if event.state == "SUCCEEDED" and not normalized_refs:
            raise ValueError("media_job_result_evidence_required")
        if (
            event.state == "SUCCEEDED"
            and result_kind == "video_artifact_evidence"
            and content_asset_ref is None
        ):
            raise ValueError("media_job_result_content_asset_required")
        if event.state == "SUCCEEDED" and result_kind == "editing_blueprint_evidence" and (
            len(normalized_refs) != 1 or content_asset_ref is not None
        ):
            raise ValueError("media_job_result_blueprint_evidence_invalid")
        if (
            event.state == "SUCCEEDED"
            and result_kind == "tutorial_graph_and_media_evidence"
            and (len(normalized_refs) != 1 or content_asset_ref is not None)
        ):
            raise ValueError("media_job_result_tutorial_evidence_invalid")
        content = {
            "contract_id": RESULT_RECEIPT_CONTRACT,
            "provider": job.provider,
            "connector_ref": job.connector_ref,
            "connector_binding_sha256": job.connector_binding_sha256,
            "result_kind": result_kind,
            "artifact_evidence_refs": list(normalized_refs),
            "content_asset_ref": content_asset_ref,
            "event_ref": event.event_ref,
            "event_sha256": event.event_sha256,
            "job_ref": job.job_ref,
            "state": event.state,
        }
        receipt_sha256 = _sha256_hex(receipt["receipt_sha256"], "receipt_sha256")
        expected_sha256 = sha256_bytes(canonical_json(content))
        if receipt_sha256 != expected_sha256:
            raise ValueError("media_job_result_receipt_seal_invalid")
        return content, receipt_sha256

    def _validate_blueprint_worker_binding(
        self,
        *,
        session: Session,
        scope: MediaJobScope,
        job: MediaJobRow,
        blueprint: Mapping[str, Any],
    ) -> None:
        request_binding = self._request_binding(session, job)
        if blueprint.get("tool_descriptor_sha256") != (
            request_binding.tool_descriptor_sha256
        ):
            raise ValueError("media_job_blueprint_tool_descriptor_invalid")
        worker = session.scalar(
            select(MediaJobWorkerInputRow).where(
                MediaJobWorkerInputRow.job_ref == job.job_ref
            )
        )
        worker_record = (
            session.get(EvidenceRecordRow, worker.evidence_id)
            if worker is not None
            else None
        )
        worker_blob = (
            session.get(EvidenceBlobRow, worker_record.blob_sha256)
            if worker_record is not None
            else None
        )
        worker_metadata = (
            worker_record.metadata_json if worker_record is not None else None
        )
        if (
            worker is None
            or worker_record is None
            or worker_blob is None
            or worker.tenant_ref != scope.tenant_ref
            or worker.entity_ref != scope.entity_ref
            or worker.store_ref != scope.store_ref
            or worker.scope_grant_authority_sha256 != scope.authority_sha256
            or worker.tool_name != job.tool_name
            or worker.tool_version != job.tool_version
            or worker.worker_input_sha256
            != sha256_bytes(canonical_json(worker.worker_input_json))
            or worker_record.source != WORKER_INPUT_SOURCE
            or worker_record.source_ref
            != f"media-job://{job.job_ref}/worker-input"
            or worker_record.blob_sha256 != worker.evidence_sha256
            or worker_blob.sha256 != worker.evidence_sha256
            or worker_blob.content_bytes != canonical_json(worker.worker_input_json)
            or not isinstance(worker_metadata, dict)
            or worker_metadata
            != {
                "contract_id": WORKER_INPUT_CONTRACT,
                "tenant_ref": scope.tenant_ref,
                "entity_ref": scope.entity_ref,
                "store_ref": scope.store_ref,
                "scope_grant_authority_sha256": scope.authority_sha256,
                "subject_actor_id": scope.subject_actor_id,
                "media_job_ref": job.job_ref,
                "worker_input_sha256": worker.worker_input_sha256,
            }
        ):
            raise ValueError("media_job_blueprint_worker_binding_invalid")
        analysis_record = self._validate_blueprint_analysis_input(
            session=session,
            scope=scope,
            worker_input=worker.worker_input_json,
            blueprint=blueprint,
        )
        links = session.scalars(
            select(MediaJobEvidenceLinkRow).where(
                MediaJobEvidenceLinkRow.job_ref == job.job_ref,
                MediaJobEvidenceLinkRow.purpose == "analysis_input",
            )
        ).all()
        if (
            len(links) != 1
            or links[0].event_ref is not None
            or links[0].tenant_ref != scope.tenant_ref
            or links[0].entity_ref != scope.entity_ref
            or links[0].store_ref != scope.store_ref
            or links[0].scope_grant_authority_sha256 != scope.authority_sha256
            or links[0].evidence_id != analysis_record.id
            or links[0].blob_sha256 != analysis_record.blob_sha256
            or links[0].source != analysis_record.source
            or links[0].source_ref != analysis_record.source_ref
        ):
            raise ValueError("media_job_blueprint_analysis_link_invalid")

    def _validate_result_bindings(
        self,
        *,
        session: Session,
        scope: MediaJobScope,
        job: MediaJobRow,
        event: MediaJobEventRow,
        content: Mapping[str, Any],
        receipt_sha256: str,
    ) -> None:
        refs = list(content["artifact_evidence_refs"])
        terminal_links = session.scalars(
            select(MediaJobEvidenceLinkRow).where(
                MediaJobEvidenceLinkRow.job_ref == job.job_ref,
                MediaJobEvidenceLinkRow.event_ref == event.event_ref,
                MediaJobEvidenceLinkRow.tenant_ref == scope.tenant_ref,
                MediaJobEvidenceLinkRow.entity_ref == scope.entity_ref,
                MediaJobEvidenceLinkRow.store_ref == scope.store_ref,
                MediaJobEvidenceLinkRow.scope_grant_authority_sha256
                == scope.authority_sha256,
                MediaJobEvidenceLinkRow.purpose == "artifact_terminal",
            )
        ).all()
        if len(terminal_links) != 1:
            raise ValueError("media_job_result_terminal_evidence_invalid")
        terminal_link = terminal_links[0]
        terminal_record = session.get(EvidenceRecordRow, terminal_link.evidence_id)
        terminal_blob = session.get(EvidenceBlobRow, terminal_link.blob_sha256)
        terminal_metadata = (
            terminal_record.metadata_json if terminal_record is not None else None
        )
        if (
            terminal_record is None
            or terminal_blob is None
            or terminal_record.blob_sha256 != terminal_link.blob_sha256
            or terminal_record.source != "governed-media-job-transition"
            or sha256_bytes(terminal_blob.content_bytes) != terminal_blob.sha256
            or terminal_record.grade != EvidenceGrade.B.value
            or not isinstance(terminal_metadata, dict)
            or terminal_metadata.get("event_sha256") != event.event_sha256
        ):
            raise ValueError("media_job_result_terminal_evidence_invalid")

        content_asset_ref = content.get("content_asset_ref")
        if event.state != "SUCCEEDED":
            return
        if content.get("result_kind") == "editing_blueprint_evidence":
            if len(refs) != 1 or content_asset_ref is not None:
                raise ValueError("media_job_result_blueprint_evidence_invalid")
            evidence_id = refs[0]
            record = session.get(EvidenceRecordRow, evidence_id)
            blob = session.get(EvidenceBlobRow, record.blob_sha256) if record else None
            metadata = record.metadata_json if record is not None else None
            if (
                record is None
                or blob is None
                or record.blob_sha256 != blob.sha256
                or sha256_bytes(blob.content_bytes) != blob.sha256
                or record.grade != EvidenceGrade.B.value
                or record.source != "governed-media-job-blueprint"
                or record.created_by != scope.subject_actor_id
                or record.content_type != "application/json"
                or record.filename != "editing-blueprint.json"
                or record.byte_size != len(blob.content_bytes)
                or _utc_datetime(record.effective_at)
                != _utc_datetime(event.recorded_at)
                or _utc_datetime(record.recorded_at)
                != _utc_datetime(event.recorded_at)
                or record.source_ref
                != f"media-job://{job.job_ref}/blueprint/{blob.sha256}"
                or not isinstance(metadata, dict)
                or metadata
                != {
                    "contract_id": "kjds-editing-blueprint-v1",
                    "tenant_ref": scope.tenant_ref,
                    "entity_ref": scope.entity_ref,
                    "store_ref": scope.store_ref,
                    "scope_grant_authority_sha256": scope.authority_sha256,
                    "subject_actor_id": scope.subject_actor_id,
                    "media_job_ref": job.job_ref,
                    "blueprint_sha256": blob.sha256,
                    "source_snapshot_sha256": metadata.get(
                        "source_snapshot_sha256"
                    ),
                    "analysis_evidence_sha256": metadata.get(
                        "analysis_evidence_sha256"
                    ),
                    "render_plan_sha256": metadata.get(
                        "render_plan_sha256"
                    ),
                }
            ):
                raise ValueError("media_job_result_blueprint_evidence_invalid")
            try:
                blueprint = json.loads(blob.content_bytes)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("media_job_result_blueprint_evidence_invalid") from exc
            try:
                render_plan = derive_blueprint_render_plan(blueprint)
            except ValueError as exc:
                raise ValueError("media_job_result_blueprint_evidence_invalid") from exc
            derived_render_plan_sha256 = sha256_bytes(canonical_json(render_plan))
            self._validate_blueprint_worker_binding(
                session=session,
                scope=scope,
                job=job,
                blueprint=blueprint,
            )
            if (
                not isinstance(blueprint, dict)
                or canonical_json(blueprint) != blob.content_bytes
                or blueprint.get("contract_id") != "kjds-editing-blueprint-v1"
                or blueprint.get("job_ref") != job.job_ref
                or blueprint.get("tool_name") != job.tool_name
                or blueprint.get("tool_version") != job.tool_version
                or blueprint.get("provider") != job.provider
                or blueprint.get("connector_ref") != job.connector_ref
                or blueprint.get("connector_binding_sha256")
                != job.connector_binding_sha256
                or blueprint.get("source_snapshot_sha256")
                != metadata.get("source_snapshot_sha256")
                or blueprint.get("analysis_receipt", {}).get("evidence_sha256")
                != metadata.get("analysis_evidence_sha256")
                or metadata.get("render_plan_sha256")
                != derived_render_plan_sha256
            ):
                raise ValueError("media_job_result_blueprint_evidence_invalid")
            return
        if content_asset_ref is None or not refs:
            raise ValueError("media_job_result_content_asset_required")
        asset = session.get(ContentAssetRow, content_asset_ref)
        product = (
            session.get(ProductRow, asset.product_id)
            if asset is not None
            else None
        )
        generation = asset.generation_json if asset is not None else None
        outputs = generation.get("outputs") if isinstance(generation, Mapping) else None
        worker = self._worker_input_projection(
            session=session,
            job=job,
            scope=scope,
        )
        blueprint_authority = self._validate_render_worker_input(
            session=session,
            scope=scope,
            worker_input=worker.payload,
        )
        expected_generation_fields = {
            "executor",
            "template_id",
            "media_job_ref",
            "execution_id",
            "source_snapshot_sha256",
            "render_plan_sha256",
            "outputs",
            "encoder_version",
            "result_receipt_sha256",
            "listing_eligible",
        }
        if (
            product is None
            or product.tenant_ref != scope.tenant_ref
            or product.entity_ref != scope.entity_ref
            or product.store_ref != scope.store_ref
            or product.scope_grant_authority_sha256 != scope.authority_sha256
            or asset.content_type != "video"
            or asset.status != "generated"
            or asset.locale != "ru-RU"
            or asset.channel != "ozon"
            or asset.source_facts_json != {}
            or asset.qa_results_json != []
            or not isinstance(generation, Mapping)
            or set(generation) != expected_generation_fields
            or generation.get("executor") != "ffmpeg"
            or generation.get("template_id") != "kjds-ffmpeg-product-video-v1"
            or generation.get("media_job_ref") != job.job_ref
            or generation.get("result_receipt_sha256") != receipt_sha256
            or generation.get("listing_eligible") is not False
            or not isinstance(generation.get("source_snapshot_sha256"), str)
            or len(generation["source_snapshot_sha256"]) != 64
            or generation["source_snapshot_sha256"]
            != blueprint_authority.source_snapshot_sha256
            or not isinstance(generation.get("render_plan_sha256"), str)
            or len(generation["render_plan_sha256"]) != 64
            or generation["render_plan_sha256"]
            != blueprint_authority.render_plan_sha256
            or not isinstance(generation.get("encoder_version"), str)
            or not generation["encoder_version"].strip()
            or generation["encoder_version"] != generation["encoder_version"].strip()
            or len(generation["encoder_version"]) > 300
            or not isinstance(outputs, Mapping)
            or tuple(outputs) != GOVERNED_RENDER_RATIOS
            or list(refs) != [outputs[ratio] for ratio in GOVERNED_RENDER_RATIOS]
            or asset.artifact_ref != outputs["9:16"]
            or asset.brief_json
            != {
                "contract_id": "kjds-governed-editing-handoff-v1",
                "job_ref": job.job_ref,
                "source_snapshot_sha256": generation[
                    "source_snapshot_sha256"
                ],
                "render_plan_sha256": generation["render_plan_sha256"],
            }
            or _utc_datetime(asset.created_at)
            != _utc_datetime(event.recorded_at)
        ):
            raise ValueError("media_job_result_content_asset_binding_invalid")
        execution_id = generation.get("execution_id")
        if (
            not isinstance(execution_id, str)
            or not execution_id.strip()
            or execution_id != execution_id.strip()
            or len(execution_id) > 160
        ):
            raise ValueError("media_job_result_content_asset_binding_invalid")
        persisted_output_bytes: list[bytes] = []
        for evidence_id in refs:
            record = session.get(EvidenceRecordRow, evidence_id)
            blob = session.get(EvidenceBlobRow, record.blob_sha256) if record else None
            metadata = record.metadata_json if record is not None else None
            aspect_ratio = (
                metadata.get("aspect_ratio")
                if isinstance(metadata, dict)
                else None
            )
            if (
                record is None
                or blob is None
                or sha256_bytes(blob.content_bytes) != blob.sha256
                or record.grade != EvidenceGrade.B.value
                or record.source != "kjds-ffmpeg-media-worker"
                or record.created_by != scope.subject_actor_id
                or record.content_type != "video/mp4"
                or not isinstance(metadata, dict)
                or not isinstance(aspect_ratio, str)
                or record.filename
                != f"{content_asset_ref}-{aspect_ratio.replace(':', 'x')}.mp4"
                or record.byte_size != len(blob.content_bytes)
                or _utc_datetime(record.effective_at)
                != _utc_datetime(event.recorded_at)
                or _utc_datetime(record.recorded_at)
                != _utc_datetime(event.recorded_at)
                or record.source_ref
                != (
                    f"media-job://{job.job_ref}/artifact/"
                    f"{execution_id}/{aspect_ratio}"
                )
                or outputs.get(aspect_ratio) != evidence_id
                or metadata
                != {
                    "contract_id": "kjds-governed-media-job-artifact-v1",
                    "tenant_ref": scope.tenant_ref,
                    "entity_ref": scope.entity_ref,
                    "store_ref": scope.store_ref,
                    "scope_grant_authority_sha256": scope.authority_sha256,
                    "subject_actor_id": scope.subject_actor_id,
                    "artifact_sha256": blob.sha256,
                    "media_job_ref": job.job_ref,
                    "content_asset_id": content_asset_ref,
                    "execution_id": execution_id,
                    "aspect_ratio": aspect_ratio,
                    "render_plan_sha256": generation.get(
                        "render_plan_sha256"
                    ),
                }
                or metadata.get("content_asset_id") != content_asset_ref
                or metadata.get("execution_id") != execution_id
            ):
                raise ValueError("media_job_result_artifact_evidence_invalid")
            persisted_output_bytes.append(bytes(blob.content_bytes))
        validate_governed_render_output_bytes(persisted_output_bytes)

    @staticmethod
    def _bind_result_receipt_to_content_asset(
        *,
        session: Session,
        job: MediaJobRow,
        event: MediaJobEventRow,
        content: Mapping[str, Any],
        receipt_sha256: str,
    ) -> None:
        if event.state != "SUCCEEDED" or content.get(
            "result_kind"
        ) == "editing_blueprint_evidence":
            return
        content_asset_ref = content.get("content_asset_ref")
        if not isinstance(content_asset_ref, str):
            raise ValueError("media_job_result_content_asset_required")
        asset = session.scalar(
            select(ContentAssetRow)
            .where(ContentAssetRow.id == content_asset_ref)
            .with_for_update()
        )
        generation = asset.generation_json if asset is not None else None
        if (
            asset is None
            or not isinstance(generation, Mapping)
            or generation.get("media_job_ref") != job.job_ref
        ):
            raise ValueError("media_job_result_content_asset_binding_invalid")
        current = generation.get("result_receipt_sha256")
        atomic_asset_ids = session.info.get("kjds_atomic_render_asset_ids", set())
        if current is None and content_asset_ref not in atomic_asset_ids:
            raise ValueError("media_job_result_orphan_asset_not_admitted")
        if current not in {None, receipt_sha256}:
            raise ValueError("media_job_result_receipt_conflict")
        sealed_generation = dict(generation)
        sealed_generation["result_receipt_sha256"] = receipt_sha256
        asset.generation_json = sealed_generation
        session.flush()

    @staticmethod
    def _validate_existing_result_receipt_row(
        *,
        row: MediaJobResultReceiptRow,
        scope: MediaJobScope,
        job: MediaJobRow,
        event: MediaJobEventRow,
        content: Mapping[str, Any],
        receipt_sha256: str,
        validation_now: datetime,
    ) -> None:
        if (
            not isinstance(row.receipt_ref, str)
            or re.fullmatch(r"media_result_[0-9a-f]{32}", row.receipt_ref) is None
            or (
                row.job_ref,
                row.event_ref,
                row.tenant_ref,
                row.entity_ref,
                row.store_ref,
                row.scope_grant_authority_sha256,
                row.tool_name,
                row.tool_version,
                row.provider,
                row.connector_ref,
                row.connector_binding_sha256,
                row.state,
                row.result_kind,
                list(row.artifact_evidence_refs),
                row.content_asset_ref,
                row.receipt_sha256,
            )
            != (
                job.job_ref,
                event.event_ref,
                scope.tenant_ref,
                scope.entity_ref,
                scope.store_ref,
                scope.authority_sha256,
                job.tool_name,
                job.tool_version,
                job.provider,
                job.connector_ref,
                job.connector_binding_sha256,
                event.state,
                content["result_kind"],
                list(content["artifact_evidence_refs"]),
                content["content_asset_ref"],
                receipt_sha256,
            )
        ):
            raise RuntimeError("media_job_result_receipt_row_drifted")
        recorded_at = _utc_datetime(row.recorded_at)
        event_recorded_at = _utc_datetime(event.recorded_at)
        if (
            (row.state == "SUCCEEDED" and recorded_at != event_recorded_at)
            or recorded_at < event_recorded_at
            or recorded_at > validation_now + EVENT_FUTURE_TOLERANCE
        ):
            raise RuntimeError("media_job_result_recorded_at_invalid")

    def _persist_result_receipt_in_session(
        self,
        *,
        session: Session,
        scope: MediaJobScope,
        job: MediaJobRow,
        event: MediaJobEventRow,
        receipt: Mapping[str, Any],
        recorded_at: datetime | None = None,
    ) -> MediaJobResultReceiptProjection:
        content, receipt_sha256 = self._validate_result_receipt(
            receipt=receipt,
            job=job,
            event=event,
        )
        self._bind_result_receipt_to_content_asset(
            session=session,
            job=job,
            event=event,
            content=content,
            receipt_sha256=receipt_sha256,
        )
        self._validate_result_bindings(
            session=session,
            scope=scope,
            job=job,
            event=event,
            content=content,
            receipt_sha256=receipt_sha256,
        )
        existing = session.scalar(
            select(MediaJobResultReceiptRow).where(
                MediaJobResultReceiptRow.job_ref == job.job_ref,
                MediaJobResultReceiptRow.event_ref == event.event_ref,
            )
        )
        if existing is not None:
            self._validate_existing_result_receipt_row(
                row=existing,
                scope=scope,
                job=job,
                event=event,
                content=content,
                receipt_sha256=receipt_sha256,
                validation_now=_utc_datetime(self._now()),
            )
            return self._result_receipt_projection(existing)
        recorded_at = self._now() if recorded_at is None else _utc_datetime(recorded_at)
        event_recorded_at = _utc_datetime(event.recorded_at)
        if (
            event.state == "SUCCEEDED"
            and recorded_at != event_recorded_at
        ) or recorded_at < event_recorded_at:
            raise ValueError("media_job_result_recorded_at_invalid")
        row = MediaJobResultReceiptRow(
            receipt_ref=new_id("media_result"),
            job_ref=job.job_ref,
            event_ref=event.event_ref,
            tenant_ref=scope.tenant_ref,
            entity_ref=scope.entity_ref,
            store_ref=scope.store_ref,
            scope_grant_authority_sha256=scope.authority_sha256,
            tool_name=job.tool_name,
            tool_version=job.tool_version,
            provider=job.provider,
            connector_ref=job.connector_ref,
            connector_binding_sha256=job.connector_binding_sha256,
            state=event.state,
            result_kind=content["result_kind"],
            artifact_evidence_refs=content["artifact_evidence_refs"],
            content_asset_ref=content["content_asset_ref"],
            receipt_sha256=receipt_sha256,
            recorded_at=recorded_at,
        )
        session.add(row)
        session.flush()
        return self._result_receipt_projection(row)

    def record_result_receipt(
        self,
        *,
        principal: Principal,
        store_ref: str,
        job_ref: str,
        receipt: Mapping[str, Any],
    ) -> MediaJobResultReceiptProjection:
        """Validate an already durable receipt without creating a new success."""

        scope = self._resolve_current(principal=principal, store_ref=store_ref)
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            self._lock_schema_transition_in_session(session)
            EvidenceService.lock_scope_authority_in_session(
                tenant_ref=scope.tenant_ref,
                store_ref=scope.store_ref,
                subject_actor_id=scope.subject_actor_id,
                session=session,
            )
            fresh_scope = self._resolve_current(principal=principal, store_ref=store_ref)
            if fresh_scope != scope:
                raise PermissionError("scope_authority_changed")
            job = self._load_job(session, scope, job_ref, for_update=True)
            event = self._validate_event_chain(session, job, scope)[-1]
            existing = session.scalar(
                select(MediaJobResultReceiptRow).where(
                    MediaJobResultReceiptRow.job_ref == job.job_ref,
                    MediaJobResultReceiptRow.event_ref == event.event_ref,
                )
            )
            if existing is None:
                raise ValueError("media_job_result_receipt_missing")
            content, receipt_sha256 = self._validate_result_receipt(
                receipt=receipt,
                job=job,
                event=event,
            )
            self._validate_existing_result_receipt_row(
                row=existing,
                scope=scope,
                job=job,
                event=event,
                content=content,
                receipt_sha256=receipt_sha256,
                validation_now=_utc_datetime(self._now()),
            )
            self._validate_result_bindings(
                session=session,
                scope=scope,
                job=job,
                event=event,
                content=content,
                receipt_sha256=receipt_sha256,
            )
            return self._result_receipt_projection(existing)

    def record_provider_result(
        self,
        *,
        principal: Principal,
        store_ref: str,
        job_ref: str,
        state: str,
        result_kind: str,
        artifact_evidence_refs: tuple[str, ...] = (),
        content_asset_ref: str | None = None,
    ) -> MediaJobResultReceiptProjection:
        """Reject executor-authored terminal claims without independent authority."""

        del (
            principal,
            store_ref,
            job_ref,
            state,
            result_kind,
            artifact_evidence_refs,
            content_asset_ref,
        )
        raise PermissionError("media_job_provider_result_authority_required")

    def record_render_result(
        self,
        *,
        principal: Principal,
        store_ref: str,
        job_ref: str,
        expected_event_ordinal: int,
        expected_recorded_at: str,
        artifact_writer: Callable[
            [Session, MediaJobScope, datetime], Mapping[str, Any]
        ],
    ) -> MediaJobResultReceiptProjection:
        """Commit the rendered asset, terminal chain, and receipt atomically."""

        if not callable(artifact_writer):
            raise ValueError("media_job_render_artifact_writer_invalid")
        scope = self._resolve_current(principal=principal, store_ref=store_ref)
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            self._lock_schema_transition_in_session(session)
            EvidenceService.lock_scope_authority_in_session(
                tenant_ref=scope.tenant_ref,
                store_ref=scope.store_ref,
                subject_actor_id=scope.subject_actor_id,
                session=session,
            )
            fresh_scope = self._resolve_current(
                principal=principal,
                store_ref=store_ref,
            )
            if fresh_scope != scope:
                raise PermissionError("scope_authority_changed")
            job = self._load_job(session, scope, job_ref, for_update=True)
            latest = self._validate_event_chain(session, job, scope)[-1]
            if (
                job.tool_name != "media.video_render"
                or latest.state != "DISPATCHED"
                or latest.ordinal != expected_event_ordinal
                or _utc_datetime(latest.recorded_at).isoformat()
                != expected_recorded_at
                or self._has_governed_artifact(
                    session=session,
                    job_ref=job.job_ref,
                    scope=scope,
                )
            ):
                raise ValueError("media_job_provider_attempt_not_current")

            worker = self._worker_input_projection(
                session=session,
                job=job,
                scope=scope,
            )
            self._validate_render_worker_input(
                session=session,
                scope=scope,
                worker_input=worker.payload,
            )

            completion_now = self._now()
            if completion_now < _utc_datetime(latest.recorded_at):
                raise ValueError("media_job_provider_completion_time_invalid")
            artifact = artifact_writer(session, scope, completion_now)
            refs = artifact.get("artifact_evidence_refs")
            content_asset_ref = artifact.get("content_asset_ref")
            if (
                not isinstance(refs, tuple)
                or not refs
                or any(not isinstance(ref, str) or not ref for ref in refs)
                or not isinstance(content_asset_ref, str)
                or not content_asset_ref
            ):
                raise ValueError("media_job_render_artifact_invalid")
            session.info.setdefault("kjds_atomic_render_asset_ids", set()).add(
                content_asset_ref
            )
            event = self._append_provider_terminal_in_session(
                session=session,
                scope=scope,
                job=job,
                state="SUCCEEDED",
                now=completion_now,
            )
            content = {
                "contract_id": RESULT_RECEIPT_CONTRACT,
                "provider": job.provider,
                "connector_ref": job.connector_ref,
                "connector_binding_sha256": job.connector_binding_sha256,
                "result_kind": "video_artifact_evidence",
                "artifact_evidence_refs": list(refs),
                "content_asset_ref": content_asset_ref,
                "event_ref": event.event_ref,
                "event_sha256": event.event_sha256,
                "job_ref": job.job_ref,
                "state": event.state,
            }
            return self._persist_result_receipt_in_session(
                session=session,
                scope=scope,
                job=job,
                event=event,
                recorded_at=completion_now,
                receipt={
                    "contract_id": RESULT_RECEIPT_CONTRACT,
                    "provider": job.provider,
                    "connector_ref": job.connector_ref,
                    "connector_binding_sha256": job.connector_binding_sha256,
                    "result_kind": "video_artifact_evidence",
                    "artifact_evidence_refs": list(refs),
                    "content_asset_ref": content_asset_ref,
                    "receipt_sha256": sha256_bytes(canonical_json(content)),
                },
            )

    def record_blueprint_result(
        self,
        *,
        principal: Principal,
        store_ref: str,
        job_ref: str,
        blueprint: Mapping[str, Any],
        render_plan_sha256: str,
    ) -> MediaJobResultReceiptProjection:
        """Atomically persist one internally compiled blueprint and its Job result."""

        if not isinstance(blueprint, Mapping):
            raise ValueError("media_job_blueprint_result_invalid")
        blueprint_content = canonical_json(dict(blueprint))
        blueprint_sha256 = sha256_bytes(blueprint_content)
        try:
            derived_render_plan = derive_blueprint_render_plan(blueprint)
        except ValueError as exc:
            raise ValueError("media_job_blueprint_result_invalid") from exc
        derived_render_plan_sha256 = sha256_bytes(canonical_json(derived_render_plan))
        if (
            _sha256_hex(render_plan_sha256, "render_plan_sha256")
            != derived_render_plan_sha256
        ):
            raise ValueError("media_job_blueprint_render_plan_drifted")
        render_plan_sha256 = derived_render_plan_sha256
        analysis_receipt = blueprint.get("analysis_receipt")
        if (
            blueprint.get("contract_id") != "kjds-editing-blueprint-v1"
            or not isinstance(analysis_receipt, Mapping)
            or not isinstance(analysis_receipt.get("evidence_sha256"), str)
        ):
            raise ValueError("media_job_blueprint_result_invalid")
        analysis_evidence_sha256 = _sha256_hex(
            analysis_receipt["evidence_sha256"],
            "analysis_evidence_sha256",
        )
        source_snapshot_sha256 = _sha256_hex(
            blueprint.get("source_snapshot_sha256"),
            "source_snapshot_sha256",
        )
        scope = self._resolve_current(principal=principal, store_ref=store_ref)
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            self._lock_schema_transition_in_session(session)
            EvidenceService.lock_scope_authority_in_session(
                tenant_ref=scope.tenant_ref,
                store_ref=scope.store_ref,
                subject_actor_id=scope.subject_actor_id,
                session=session,
            )
            fresh_scope = self._resolve_current(
                principal=principal,
                store_ref=store_ref,
            )
            if fresh_scope != scope:
                raise PermissionError("scope_authority_changed")
            job = self._load_job(session, scope, job_ref, for_update=True)
            latest = self._validate_event_chain(session, job, scope)[-1]
            if (
                job.tool_name != "media.video_blueprint"
                or job.provider != BLUEPRINT_COMPILER_PROVIDER
                or job.connector_ref != BLUEPRINT_COMPILER_CONNECTOR_REF
                or job.connector_binding_sha256
                != BLUEPRINT_COMPILER_CONNECTOR_BINDING_SHA256
                or blueprint.get("job_ref") != job.job_ref
                or blueprint.get("tool_name") != job.tool_name
                or blueprint.get("tool_version") != job.tool_version
                or blueprint.get("provider") != job.provider
                or blueprint.get("connector_ref") != job.connector_ref
                or blueprint.get("connector_binding_sha256")
                != job.connector_binding_sha256
            ):
                raise ValueError("media_job_blueprint_result_binding_invalid")
            existing = session.scalar(
                select(MediaJobResultReceiptRow).where(
                    MediaJobResultReceiptRow.job_ref == job.job_ref
                )
            )
            if existing is not None:
                events = self._validate_event_chain(session, job, scope)
                existing_event = next(
                    (
                        event
                        for event in events
                        if event.event_ref == existing.event_ref
                    ),
                    None,
                )
                if existing_event is None:
                    raise ValueError("media_job_blueprint_result_conflict")
                existing_receipt = {
                    "contract_id": RESULT_RECEIPT_CONTRACT,
                    "provider": existing.provider,
                    "connector_ref": existing.connector_ref,
                    "connector_binding_sha256": existing.connector_binding_sha256,
                    "result_kind": existing.result_kind,
                    "artifact_evidence_refs": list(existing.artifact_evidence_refs),
                    "content_asset_ref": existing.content_asset_ref,
                    "receipt_sha256": existing.receipt_sha256,
                }
                existing_content, existing_sha256 = self._validate_result_receipt(
                    receipt=existing_receipt,
                    job=job,
                    event=existing_event,
                )
                self._validate_existing_result_receipt_row(
                    row=existing,
                    scope=scope,
                    job=job,
                    event=existing_event,
                    content=existing_content,
                    receipt_sha256=existing_sha256,
                    validation_now=_utc_datetime(self._now()),
                )
                self._validate_result_bindings(
                    session=session,
                    scope=scope,
                    job=job,
                    event=existing_event,
                    content=existing_content,
                    receipt_sha256=existing_sha256,
                )
                projection = self._result_receipt_projection(existing)
                if (
                    projection.state != "SUCCEEDED"
                    or projection.result_kind != "editing_blueprint_evidence"
                    or projection.content_asset_ref is not None
                    or len(projection.artifact_evidence_refs) != 1
                ):
                    raise ValueError("media_job_blueprint_result_conflict")
                record = session.get(
                    EvidenceRecordRow,
                    projection.artifact_evidence_refs[0],
                )
                blob = (
                    session.get(EvidenceBlobRow, record.blob_sha256)
                    if record is not None
                    else None
                )
                if blob is None or blob.content_bytes != blueprint_content:
                    raise ValueError("media_job_blueprint_result_conflict")
                return projection
            if latest.state != "QUEUED":
                raise ValueError("media_job_blueprint_result_not_admitted")
            durable_now = _utc_datetime(self._now())
            if durable_now < max(
                _utc_datetime(latest.recorded_at),
                _utc_datetime(job.created_at),
            ):
                raise ValueError("media_job_provider_completion_time_invalid")
            self._append_event(
                session=session,
                job=job,
                scope=scope,
                state="DISPATCHED",
                reason=None,
                now=durable_now,
                command_idempotency_sha256=job.idempotency_sha256,
                command_request_sha256=job.request_sha256,
            )
            blueprint_record = self.evidence.capture_media_job_evidence(
                content=blueprint_content,
                filename="editing-blueprint.json",
                content_type="application/json",
                source="governed-media-job-blueprint",
                source_ref=(
                    f"media-job://{job.job_ref}/blueprint/{blueprint_sha256}"
                ),
                grade=EvidenceGrade.B,
                effective_at=durable_now.isoformat(),
                recorded_at=durable_now.isoformat(),
                created_by=scope.subject_actor_id,
                metadata={
                    "contract_id": "kjds-editing-blueprint-v1",
                    "tenant_ref": scope.tenant_ref,
                    "entity_ref": scope.entity_ref,
                    "store_ref": scope.store_ref,
                    "scope_grant_authority_sha256": scope.authority_sha256,
                    "subject_actor_id": scope.subject_actor_id,
                    "media_job_ref": job.job_ref,
                    "blueprint_sha256": blueprint_sha256,
                    "source_snapshot_sha256": source_snapshot_sha256,
                    "analysis_evidence_sha256": analysis_evidence_sha256,
                    "render_plan_sha256": render_plan_sha256,
                },
                session=session,
            )
            event = self._append_provider_terminal_in_session(
                session=session,
                scope=scope,
                job=job,
                state="SUCCEEDED",
                now=durable_now,
            )
            content = {
                "contract_id": RESULT_RECEIPT_CONTRACT,
                "provider": job.provider,
                "connector_ref": job.connector_ref,
                "connector_binding_sha256": job.connector_binding_sha256,
                "result_kind": "editing_blueprint_evidence",
                "artifact_evidence_refs": [blueprint_record.id],
                "content_asset_ref": None,
                "event_ref": event.event_ref,
                "event_sha256": event.event_sha256,
                "job_ref": job.job_ref,
                "state": event.state,
            }
            return self._persist_result_receipt_in_session(
                session=session,
                scope=scope,
                job=job,
                event=event,
                recorded_at=durable_now,
                receipt={
                    "contract_id": RESULT_RECEIPT_CONTRACT,
                    "provider": job.provider,
                    "connector_ref": job.connector_ref,
                    "connector_binding_sha256": job.connector_binding_sha256,
                    "result_kind": "editing_blueprint_evidence",
                    "artifact_evidence_refs": [blueprint_record.id],
                    "content_asset_ref": None,
                    "receipt_sha256": sha256_bytes(canonical_json(content)),
                },
            )

    @staticmethod
    def _has_governed_artifact(
        *, session: Session, job_ref: str, scope: MediaJobScope
    ) -> bool:
        generations = session.scalars(
            select(ContentAssetRow.generation_json)
            .join(ProductRow, ProductRow.id == ContentAssetRow.product_id)
            .where(
                ProductRow.tenant_ref == scope.tenant_ref,
                ProductRow.entity_ref == scope.entity_ref,
                ProductRow.store_ref == scope.store_ref,
                ProductRow.scope_grant_authority_sha256 == scope.authority_sha256,
            )
        ).all()
        return any(
            isinstance(generation, dict)
            and generation.get("executor") == "ffmpeg"
            and generation.get("media_job_ref") == job_ref
            for generation in generations
        )

    def read_result_receipt(
        self,
        *,
        principal: Principal,
        store_ref: str,
        job_ref: str,
    ) -> MediaJobResultReceiptProjection:
        """Read a durable result without creating a new provider attempt."""

        scope = self._resolve_current(principal=principal, store_ref=store_ref)
        with Session(self.engine) as session:
            job = self._load_job(session, scope, job_ref)
            events = self._validate_event_chain(session, job, scope)
            row = session.scalar(
                select(MediaJobResultReceiptRow)
                .where(
                    MediaJobResultReceiptRow.job_ref == job.job_ref,
                    MediaJobResultReceiptRow.tenant_ref == scope.tenant_ref,
                    MediaJobResultReceiptRow.entity_ref == scope.entity_ref,
                    MediaJobResultReceiptRow.store_ref == scope.store_ref,
                    MediaJobResultReceiptRow.scope_grant_authority_sha256
                    == scope.authority_sha256,
                )
                .order_by(MediaJobResultReceiptRow.recorded_at.desc())
            )
            if row is None:
                raise KeyError("media_job_result_receipt_not_found")
            event = next((item for item in events if item.event_ref == row.event_ref), None)
            if event is None:
                raise RuntimeError("media_job_result_event_missing")
            if row.state != event.state:
                raise RuntimeError("media_job_result_event_state_drifted")
            receipt = {
                "contract_id": RESULT_RECEIPT_CONTRACT,
                "provider": row.provider,
                "connector_ref": row.connector_ref,
                "connector_binding_sha256": row.connector_binding_sha256,
                "result_kind": row.result_kind,
                "artifact_evidence_refs": list(row.artifact_evidence_refs),
                "content_asset_ref": row.content_asset_ref,
                "receipt_sha256": row.receipt_sha256,
            }
            content, receipt_sha256 = self._validate_result_receipt(
                receipt=receipt,
                job=job,
                event=event,
            )
            self._validate_existing_result_receipt_row(
                row=row,
                scope=scope,
                job=job,
                event=event,
                content=content,
                receipt_sha256=receipt_sha256,
                validation_now=_utc_datetime(self._now()),
            )
            self._validate_result_bindings(
                session=session,
                scope=scope,
                job=job,
                event=event,
                content=content,
                receipt_sha256=receipt_sha256,
            )
            return self._result_receipt_projection(row)

    # The BAS-182 adapter seam is intentionally fail-closed until phase B wires a provider.
    def peek(self, **_: Any) -> Any:
        from .codex_app_server_worker import DurableDispatchPeek

        return DurableDispatchPeek(False, None, "", "", "", None, None, "", "", False)

    def claim(self, **_: Any) -> Any:
        raise RuntimeError("media_job_provider_dispatch_not_admitted")

    def record(self, **_: Any) -> str | None:
        raise RuntimeError("media_job_provider_dispatch_not_admitted")
