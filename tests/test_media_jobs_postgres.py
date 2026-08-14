from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, Event
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from apps.control_plane.evidence import (
    _MEDIA_JOB_CAPTURE_AUTHORITY,
    EvidenceBlobRow,
    EvidenceGrade,
    EvidenceRecordRow,
    EvidenceService,
)
from apps.control_plane.media_jobs import (
    BLUEPRINT_COMPILER_CONNECTOR_BINDING_SHA256,
    BLUEPRINT_COMPILER_CONNECTOR_REF,
    BLUEPRINT_COMPILER_PROVIDER,
    CAMPAIGN_BRIEF_CONTRACT,
    CAMPAIGN_BRIEF_VERSION,
    COMMANDER_REQUEST_CONTRACT,
    FFMPEG_RENDER_PROFILE_SHA256,
    GOVERNED_RENDER_RATIOS,
    TOOL_DESCRIPTOR_CONTRACT,
    GovernedMediaJobWorkspace,
    MediaJobEventRow,
    MediaJobEvidenceLinkRow,
    MediaJobRequestBindingRow,
    MediaJobResultReceiptRow,
    MediaJobRow,
    MediaJobWorkerInputRow,
    canonical_json,
    derive_blueprint_render_plan,
    event_seal,
    sha256_bytes,
)
from apps.control_plane.scope_grants import ScopeGrantEventRow
from apps.control_plane.security import Principal
from apps.control_plane.sql_repository import ContentAssetRow, ProductRow

MIGRATION = (
    Path(__file__).parents[1]
    / "migrations"
    / "versions"
    / "20260808_0097_governed_media_jobs.py"
)
DATABASE_URL = os.getenv("KJDS_BAS183_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL.startswith("postgresql"),
    reason="BAS-183 PostgreSQL lifecycle requires KJDS_BAS183_DATABASE_URL",
)
NOW = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=10)
AUTHORITY = "a" * 64
BINDING = "b" * 64


class _ScopeAuthority:
    def current(self, **kwargs):
        principal = kwargs["principal"]
        return {
            "status": "ready",
            "tenant_ref": principal.tenant_ref,
            "entity_ref": "entity-media-pg",
            "store_ref": kwargs["store_ref"],
            "authority_sha256": AUTHORITY,
        }


class _DatabaseScopeAuthority:
    """Read the committed revoke marker so the lock test observes real state."""

    def __init__(self, engine, *, tenant_ref: str, actor_id: str) -> None:
        self.engine = engine
        self.tenant_ref = tenant_ref
        self.actor_id = actor_id

    def current(self, **kwargs):
        store_ref = kwargs["store_ref"]
        with Session(self.engine) as session:
            revoked = session.scalar(
                select(ScopeGrantEventRow.sequence)
                .where(
                    ScopeGrantEventRow.tenant_ref == self.tenant_ref,
                    ScopeGrantEventRow.store_ref == store_ref,
                    ScopeGrantEventRow.subject_actor_id == self.actor_id,
                    ScopeGrantEventRow.event_type == "revoke",
                )
                .order_by(ScopeGrantEventRow.sequence.desc())
                .limit(1)
            )
        if revoked is not None:
            return {
                "status": "no_data",
                "tenant_ref": self.tenant_ref,
                "entity_ref": None,
                "store_ref": store_ref,
                "authority_sha256": None,
            }
        return {
            "status": "ready",
            "tenant_ref": self.tenant_ref,
            "entity_ref": "entity-media-pg",
            "store_ref": store_ref,
            "authority_sha256": AUTHORITY,
        }


class _DatabaseContentAssetAuthority:
    def __init__(self, engine) -> None:
        self.engine = engine

    def get_content_asset_scoped(
        self, *, asset_id, tenant_ref, entity_ref, store_ref, as_of
    ):
        with Session(self.engine) as session:
            row = session.scalar(
                select(ContentAssetRow)
                .join(ProductRow, ProductRow.id == ContentAssetRow.product_id)
                .where(
                    ContentAssetRow.id == asset_id,
                    ProductRow.tenant_ref == tenant_ref,
                    ProductRow.entity_ref == entity_ref,
                    ProductRow.store_ref == store_ref,
                    ProductRow.scope_grant_authority_sha256 == AUTHORITY,
                )
            )
            if row is None:
                raise KeyError(asset_id)
            return SimpleNamespace(generation=dict(row.generation_json))


def _config() -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", DATABASE_URL)
    return config


def _migrate(direction: str, revision: str) -> None:
    previous = os.environ.get("KJDS_DATABASE_URL")
    os.environ["KJDS_DATABASE_URL"] = DATABASE_URL
    try:
        getattr(command, direction)(_config(), revision)
    finally:
        if previous is None:
            os.environ.pop("KJDS_DATABASE_URL", None)
        else:
            os.environ["KJDS_DATABASE_URL"] = previous


def _sqlstate(error: BaseException) -> str | None:
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        state = getattr(current, "sqlstate", None)
        if state:
            return str(state)
        original = getattr(current, "orig", None)
        if isinstance(original, BaseException) and id(original) not in seen:
            current = original
        else:
            current = current.__cause__ or current.__context__
    return None


@pytest.fixture(scope="module")
def engine():
    target = create_engine(DATABASE_URL, pool_pre_ping=True)
    try:
        with target.connect() as connection:
            assert connection.scalar(text("SELECT current_database()"))
        yield target
    finally:
        target.dispose()


def _principal(actor: str, tenant: str) -> Principal:
    return Principal(
        actor_id=actor,
        roles=frozenset({"operator"}),
        tenant_ref=tenant,
        store_refs=frozenset({"store-media-pg"}),
    )


def _request(idempotency: str, **changes):
    values = {
        "tool_name": "image.generate",
        "tool_version": "v1",
        "project_ref": "project-media-pg",
        "brief_ref": "brief-media-pg",
        "provider": "codex-app-server",
        "connector_ref": "connector-media-pg",
        "connector_binding_sha256": BINDING,
        "idempotency_sha256": idempotency,
        "prompt": "private PostgreSQL prompt",
    }
    values.update(changes)
    return values


def _render_worker_input(
    *,
    campaign_ref: str = "content-asset://campaign-pg",
    blueprint_ref: str = "evidence://editing-blueprint-pg",
    source_ref: str = "content-asset://source-pg",
    audio_ref: str = "content-asset://audio-pg",
) -> dict[str, Any]:
    return {
        "contract_id": "kjds-governed-media-job-worker-input-v1",
        "tool_name": "media.video_render",
        "tool_version": "v1",
        "project_ref": "project-media-pg",
        "brief_ref": "brief-media-pg",
        "campaign_content_asset_refs": [campaign_ref],
        "editing_blueprint_ref": blueprint_ref,
        "reference_asset_refs": [],
        "source_asset_refs": [source_ref],
        "audio_asset_refs": [audio_ref],
        "target_channels": ["ozon"],
        "analysis_evidence_ref": None,
        "analysis_contract_sha256": None,
        "render_profile_sha256": FFMPEG_RENDER_PROFILE_SHA256,
    }


def _secure_media_submission(
    *,
    principal: Principal,
    worker_input: dict[str, Any],
    tool_name: str,
    provider: str,
    connector_ref: str,
    connector_binding_sha256: str,
    idempotency_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    scope_payload = {
        "tenant_ref": principal.tenant_ref,
        "entity_ref": "entity-media-pg",
        "store_ref": "store-media-pg",
        "authority_sha256": AUTHORITY,
        "subject_actor_id": principal.actor_id,
    }
    brief_content = {
        "contract_id": CAMPAIGN_BRIEF_CONTRACT,
        "contract_version": CAMPAIGN_BRIEF_VERSION,
        "project_ref": worker_input["project_ref"],
        "graph_snapshot_sha256": "1" * 64,
        **scope_payload,
        "scope_binding_sha256": sha256_bytes(canonical_json(scope_payload)),
        "objective": "Compile and render one governed editing blueprint.",
        "audiences": ["buyer"],
        "channel": "ozon",
        "constraints": ["no external write"],
        "content_asset_refs": list(worker_input["campaign_content_asset_refs"]),
    }
    brief_sha256 = sha256_bytes(canonical_json(brief_content))
    brief = {
        **brief_content,
        "brief_ref": f"campaign_brief_{brief_sha256[:32]}",
        "content_sha256": brief_sha256,
        "external_write_allowed": False,
    }
    worker_input["brief_ref"] = brief["brief_ref"]
    descriptor_content = {
        "contract_id": TOOL_DESCRIPTOR_CONTRACT,
        "registry_sha256": "2" * 64,
        "tool_name": tool_name,
        "tool_version": "v1",
        "capabilities": ["deterministic_editing"],
        "cost_upper_bound": {
            "amount_minor": 0,
            "currency": "USD",
            "basis": "engineering_dispatch_ceiling_not_invoice",
        },
        "output_contract": (
            "editing_blueprint_evidence"
            if tool_name == "media.video_blueprint"
            else "video_artifact_evidence"
        ),
        "provider": provider,
        "connector_ref": connector_ref,
        "connector_binding_sha256": connector_binding_sha256,
    }
    descriptor_sha256 = sha256_bytes(canonical_json(descriptor_content))
    descriptor = {
        **descriptor_content,
        "descriptor_sha256": descriptor_sha256,
    }
    request = {
        "contract_id": COMMANDER_REQUEST_CONTRACT,
        "tool_name": tool_name,
        "tool_version": "v1",
        "project_ref": worker_input["project_ref"],
        "brief_ref": brief["brief_ref"],
        "campaign_brief_sha256": brief_sha256,
        "provider": provider,
        "connector_ref": connector_ref,
        "connector_binding_sha256": connector_binding_sha256,
        "idempotency_sha256": idempotency_sha256,
        "output_contract": descriptor["output_contract"],
        "tool_descriptor_sha256": descriptor_sha256,
        "tool_inputs_sha256": sha256_bytes(canonical_json(worker_input)),
        "tool_input_ref_count": sum(
            len(worker_input[field])
            for field in (
                "campaign_content_asset_refs",
                "reference_asset_refs",
                "source_asset_refs",
                "audio_asset_refs",
            )
        ),
        "safe_reason_codes": [],
    }
    return request, brief, descriptor


def _capture_scoped_asset_evidence(
    engine,
    *,
    principal: Principal,
    suffix: str,
    kind: str,
    content: bytes,
    content_type: str,
):
    extensions = {
        "campaign": ".png",
        "video": ".mp4",
        "audio": ".wav",
        "caption": ".txt",
    }
    return EvidenceService(engine).capture(
        content=content,
        filename=f"{kind}-{suffix}{extensions[kind]}",
        content_type=content_type,
        source="bas186-pg-governed-input",
        source_ref=f"bas186-pg-input://{suffix}/{kind}",
        grade=EvidenceGrade.B,
        effective_at=NOW.isoformat(),
        _recorded_at=NOW.isoformat(),
        effective_until=None,
        created_by=principal.actor_id,
        metadata={
            "rights_status": "approved",
            "tenant_ref": principal.tenant_ref,
            "entity_ref": "entity-media-pg",
            "store_ref": "store-media-pg",
            "scope_grant_authority_sha256": AUTHORITY,
            "subject_actor_id": principal.actor_id,
        },
        _reserved_authority=_MEDIA_JOB_CAPTURE_AUTHORITY,
    )


def _prepare_governed_render_job(engine, *, principal: Principal, suffix: str, service):
    campaign = _capture_scoped_asset_evidence(
        engine,
        principal=principal,
        suffix=suffix,
        kind="campaign",
        content=b"\x89PNG\r\n\x1a\n" + b"campaign image",
        content_type="image/png",
    )
    video = _capture_scoped_asset_evidence(
        engine,
        principal=principal,
        suffix=suffix,
        kind="video",
        content=b"\x00\x00\x00\x18ftypisom" + b"governed video bytes",
        content_type="video/mp4",
    )
    audio = _capture_scoped_asset_evidence(
        engine,
        principal=principal,
        suffix=suffix,
        kind="audio",
        content=b"RIFF\x24\x00\x00\x00WAVE" + b"governed audio bytes",
        content_type="audio/wav",
    )
    caption = _capture_scoped_asset_evidence(
        engine,
        principal=principal,
        suffix=suffix,
        kind="caption",
        content=b"Governed caption",
        content_type="text/plain",
    )
    product_id = f"product-input-{suffix}"
    campaign_ref = f"content-asset://campaign-{suffix}"
    video_ref = f"content-asset://video-{suffix}"
    audio_ref = f"content-asset://audio-{suffix}"
    with Session(engine) as session, session.begin():
        session.add(
            ProductRow(
                id=product_id,
                sku=f"SKU-INPUT-{suffix}",
                name="BAS-186 governed input product",
                market="RU",
                channel="ozon",
                status="draft",
                created_at=NOW,
                tenant_ref=principal.tenant_ref,
                entity_ref="entity-media-pg",
                store_ref="store-media-pg",
                scope_grant_authority_sha256=AUTHORITY,
                scope_as_of=NOW,
                created_by=principal.actor_id,
            )
        )
        session.flush()
        for asset_ref, content_type, artifact_ref in (
            (campaign_ref, "image", campaign.id),
            (video_ref, "video", video.id),
            (audio_ref, "audio", audio.id),
        ):
            session.add(
                ContentAssetRow(
                    id=asset_ref.removeprefix("content-asset://"),
                    product_id=product_id,
                    content_type=content_type,
                    locale="ru-RU",
                    channel="ozon",
                    brief_json={},
                    source_facts_json={},
                    status="approved",
                    artifact_ref=artifact_ref,
                    qa_results_json=[],
                    generation_json={},
                    created_at=NOW,
                )
            )

    source_video_artifacts = [
        {
            "content_asset_ref": video_ref,
            "evidence_ref": f"evidence://{video.id}",
            "evidence_sha256": video.sha256,
        }
    ]
    scenes = [
        {
            "scene_id": "scene-1",
            "source_asset_ref": video_ref,
            "source_start_ms": 0,
            "source_end_ms": 1000,
            "timeline_start_ms": 0,
            "timeline_end_ms": 1000,
            "transition": "cut",
            "caption_ref": f"evidence://{caption.id}",
        }
    ]
    analysis_run_ref = f"analysis-{suffix}"
    analysis_content = {
        "contract_id": "kjds-reference-video-analysis-v1",
        "schema_version": "1.0.0",
        "analysis_run_ref": analysis_run_ref,
        "observed_at": NOW.isoformat(),
        "source_video_artifacts": source_video_artifacts,
        "scenes": scenes,
        "subtitle_asset_ref": None,
        "target_channels": ["ozon"],
    }
    analysis_bytes = canonical_json(analysis_content)
    analysis_sha256 = sha256_bytes(analysis_bytes)
    with Session(engine) as session, session.begin():
        analysis = EvidenceService(engine).capture_media_job_evidence(
            content=analysis_bytes,
            filename="reference-analysis.json",
            content_type="application/json",
            source="governed-reference-video-analysis",
            source_ref=f"reference-analysis://{analysis_run_ref}/{analysis_sha256}",
            grade=EvidenceGrade.B,
            effective_at=NOW.isoformat(),
            recorded_at=NOW.isoformat(),
            created_by=principal.actor_id,
            metadata={
                "contract_id": "kjds-reference-video-analysis-v1",
                "tenant_ref": principal.tenant_ref,
                "entity_ref": "entity-media-pg",
                "store_ref": "store-media-pg",
                "scope_grant_authority_sha256": AUTHORITY,
                "subject_actor_id": principal.actor_id,
                "analysis_contract_sha256": analysis_sha256,
                "analysis_run_ref": analysis_run_ref,
                "source_video_artifacts_sha256": sha256_bytes(
                    canonical_json(source_video_artifacts)
                ),
                "rights_status": "approved",
                "schema_version": "1.0.0",
                "observed_at": NOW.isoformat(),
            },
            session=session,
        )

    blueprint_worker = {
        "contract_id": "kjds-governed-media-job-worker-input-v1",
        "tool_name": "media.video_blueprint",
        "tool_version": "v1",
        "project_ref": "project-media-pg",
        "brief_ref": "pending",
        "campaign_content_asset_refs": [campaign_ref],
        "editing_blueprint_ref": None,
        "reference_asset_refs": [video_ref],
        "source_asset_refs": [],
        "audio_asset_refs": [audio_ref],
        "target_channels": ["ozon"],
        "analysis_evidence_ref": f"evidence://{analysis.id}",
        "analysis_contract_sha256": analysis_sha256,
        "render_profile_sha256": FFMPEG_RENDER_PROFILE_SHA256,
    }
    blueprint_request, blueprint_brief, blueprint_descriptor = _secure_media_submission(
        principal=principal,
        worker_input=blueprint_worker,
        tool_name="media.video_blueprint",
        provider=BLUEPRINT_COMPILER_PROVIDER,
        connector_ref=BLUEPRINT_COMPILER_CONNECTOR_REF,
        connector_binding_sha256=BLUEPRINT_COMPILER_CONNECTOR_BINDING_SHA256,
        idempotency_sha256=sha256_bytes(f"blueprint-{suffix}".encode()),
    )
    blueprint_job = service.submit(
        principal=principal,
        store_ref="store-media-pg",
        request=blueprint_request,
        campaign_brief=blueprint_brief,
        tool_descriptor=blueprint_descriptor,
        worker_input=blueprint_worker,
    )
    scope_payload = {
        "tenant_ref": principal.tenant_ref,
        "entity_ref": "entity-media-pg",
        "store_ref": "store-media-pg",
        "authority_sha256": AUTHORITY,
        "subject_actor_id": principal.actor_id,
    }
    input_artifacts = [
        {
            "content_asset_ref": campaign_ref,
            "evidence_ref": f"evidence://{campaign.id}",
            "evidence_sha256": campaign.sha256,
            "content_type": "image/png",
            "role": "campaign",
        },
        {
            "content_asset_ref": video_ref,
            "evidence_ref": f"evidence://{video.id}",
            "evidence_sha256": video.sha256,
            "content_type": "video/mp4",
            "role": "reference_video",
        },
        {
            "content_asset_ref": audio_ref,
            "evidence_ref": f"evidence://{audio.id}",
            "evidence_sha256": audio.sha256,
            "content_type": "audio/wav",
            "role": "audio",
        },
    ]
    analysis_receipt_content = {
        "contract_id": "kjds-reference-video-analysis-v1",
        "semantic_sha256": analysis_sha256,
        "observed_at": NOW.isoformat(),
        "evidence_ref": f"evidence://{analysis.id}",
        "evidence_sha256": analysis.sha256,
        "source_video_artifacts": source_video_artifacts,
    }
    analysis_receipt = {
        **analysis_receipt_content,
        "source_snapshot_sha256": sha256_bytes(
            canonical_json(analysis_receipt_content)
        ),
    }
    source_snapshot_content = {
        "contract_id": "kjds-editing-source-receipt-v1",
        "contract_version": "1.0.0",
        "scope": scope_payload,
        "scope_binding_sha256": sha256_bytes(canonical_json(scope_payload)),
        "rights_status": "approved",
        "product_id": product_id,
        "campaign_asset_refs": [campaign_ref],
        "reference_asset_refs": [video_ref],
        "input_artifacts": input_artifacts,
        "analysis_receipt": analysis_receipt_content,
        "scenes": scenes,
        "audio_asset_ref": audio_ref,
        "subtitle_asset_ref": None,
        "target_channels": ["ozon"],
        "render_profile_sha256": FFMPEG_RENDER_PROFILE_SHA256,
        "editing_blueprint": None,
        "editing_blueprint_sha256": None,
    }
    blueprint = {
        "contract_id": "kjds-editing-blueprint-v1",
        "contract_version": "1.0.0",
        "job_ref": blueprint_job.job_ref,
        "tool_name": "media.video_blueprint",
        "tool_version": "v1",
        "provider": BLUEPRINT_COMPILER_PROVIDER,
        "connector_ref": BLUEPRINT_COMPILER_CONNECTOR_REF,
        "connector_binding_sha256": BLUEPRINT_COMPILER_CONNECTOR_BINDING_SHA256,
        "tool_descriptor_sha256": blueprint_descriptor["descriptor_sha256"],
        "scope": scope_payload,
        "scope_binding_sha256": sha256_bytes(canonical_json(scope_payload)),
        "source_snapshot_sha256": sha256_bytes(canonical_json(source_snapshot_content)),
        "analysis_receipt": analysis_receipt,
        "campaign_asset_refs": [campaign_ref],
        "reference_asset_refs": [video_ref],
        "input_artifacts": input_artifacts,
        "scenes": scenes,
        "audio_asset_ref": audio_ref,
        "subtitle_asset_ref": None,
        "target_channels": ["ozon"],
        "render_profile_sha256": FFMPEG_RENDER_PROFILE_SHA256,
        "external_write_allowed": False,
        "listing_eligible": False,
    }
    render_plan_sha256 = sha256_bytes(
        canonical_json(derive_blueprint_render_plan(blueprint))
    )
    blueprint_receipt = service.record_blueprint_result(
        principal=principal,
        store_ref="store-media-pg",
        job_ref=blueprint_job.job_ref,
        blueprint=blueprint,
        render_plan_sha256=render_plan_sha256,
    )
    blueprint_evidence_ref = f"evidence://{blueprint_receipt.artifact_evidence_refs[0]}"
    render_worker = _render_worker_input(
        campaign_ref=campaign_ref,
        blueprint_ref=blueprint_evidence_ref,
        source_ref=video_ref,
        audio_ref=audio_ref,
    )
    render_request, render_brief, render_descriptor = _secure_media_submission(
        principal=principal,
        worker_input=render_worker,
        tool_name="media.video_render",
        provider="ffmpeg",
        connector_ref="ffmpeg-local",
        connector_binding_sha256=BINDING,
        idempotency_sha256=sha256_bytes(f"render-{suffix}".encode()),
    )
    render_job = service.submit(
        principal=principal,
        store_ref="store-media-pg",
        request=render_request,
        campaign_brief=render_brief,
        tool_descriptor=render_descriptor,
        worker_input=render_worker,
    )
    return SimpleNamespace(
        job=render_job,
        worker_input=render_worker,
        product_id=product_id,
        render_plan_sha256=render_plan_sha256,
        blueprint=blueprint,
        blueprint_evidence_id=blueprint_receipt.artifact_evidence_refs[0],
        source_snapshot_content=source_snapshot_content,
    )


def _atomic_artifact_writer(
    engine,
    *,
    principal: Principal,
    prepared,
    suffix: str,
    after_flush=None,
    fail_stage: str | None = None,
    result_shape_attack: str | None = None,
):
    asset_ref = f"content-asset-render-{suffix}"
    execution_id = f"media-execution-render-{suffix}"
    artifact_bytes = b"\x00\x00\x00\x18ftypisom" + (
        f"atomic rendered artifact {suffix}".encode()
    )

    def writer(session: Session, scope, completion_now: datetime):
        artifacts = {}
        for ratio in ("1:1", "16:9", "9:16"):
            content = artifact_bytes + ratio.encode()
            artifact = EvidenceService(engine).capture_media_job_evidence(
                content=content,
                filename=f"{asset_ref}-{ratio.replace(':', 'x')}.mp4",
                content_type="video/mp4",
                source="kjds-ffmpeg-media-worker",
                source_ref=(
                    f"media-job://{prepared.job.job_ref}/artifact/"
                    f"{execution_id}/{ratio}"
                ),
                grade=EvidenceGrade.B,
                effective_at=completion_now.isoformat(),
                recorded_at=completion_now.isoformat(),
                created_by=principal.actor_id,
                metadata={
                    "contract_id": "kjds-governed-media-job-artifact-v1",
                    "tenant_ref": scope.tenant_ref,
                    "entity_ref": scope.entity_ref,
                    "store_ref": scope.store_ref,
                    "scope_grant_authority_sha256": scope.authority_sha256,
                    "subject_actor_id": scope.subject_actor_id,
                    "artifact_sha256": sha256_bytes(content),
                    "media_job_ref": prepared.job.job_ref,
                    "content_asset_id": asset_ref,
                    "execution_id": execution_id,
                    "aspect_ratio": ratio,
                    "render_plan_sha256": prepared.render_plan_sha256,
                },
                session=session,
            )
            artifacts[ratio] = artifact.id
            if result_shape_attack in {
                "artifact_metadata_scalar",
                "artifact_metadata_value_number",
                "artifact_metadata_value_bool",
            } and ratio == "1:1":
                session.execute(text("ALTER TABLE evidence_records DISABLE TRIGGER USER"))
                artifact_row = session.get(EvidenceRecordRow, artifact.id)
                assert artifact_row is not None
                if result_shape_attack == "artifact_metadata_scalar":
                    artifact_row.metadata_json = "scalar-metadata"
                else:
                    metadata = dict(artifact_row.metadata_json)
                    metadata["contract_id"] = (
                        7
                        if result_shape_attack == "artifact_metadata_value_number"
                        else True
                    )
                    artifact_row.metadata_json = metadata
        if fail_stage == "artifact_evidence":
            raise RuntimeError("injected_after_artifact_evidence")
        generation_json = {
            "executor": "ffmpeg",
            "template_id": "kjds-ffmpeg-product-video-v1",
            "execution_id": execution_id,
            "media_job_ref": prepared.job.job_ref,
            "source_snapshot_sha256": prepared.blueprint[
                "source_snapshot_sha256"
            ],
            "render_plan_sha256": prepared.render_plan_sha256,
            "result_receipt_sha256": None,
            "outputs": artifacts,
            "encoder_version": "fixture-ffmpeg",
            "listing_eligible": False,
        }
        if result_shape_attack == "outputs_scalar":
            generation_json["outputs"] = "scalar-outputs"
        elif result_shape_attack == "generation_executor_number":
            generation_json["executor"] = 7
        elif result_shape_attack == "generation_receipt_number":
            generation_json["result_receipt_sha256"] = 7
        elif result_shape_attack == "generation_execution_number":
            generation_json["execution_id"] = 7
        elif result_shape_attack == "generation_listing_string":
            generation_json["listing_eligible"] = "false"
        elif result_shape_attack == "generation_listing_number":
            generation_json["listing_eligible"] = 0
        elif result_shape_attack == "outputs_value_number":
            generation_json["outputs"] = {**artifacts, "1:1": 7}
        elif result_shape_attack == "outputs_value_bool":
            generation_json["outputs"] = {**artifacts, "1:1": False}
        session.add(
            ContentAssetRow(
                id=asset_ref,
                product_id=prepared.product_id,
                content_type="video",
                locale="ru-RU",
                channel="ozon",
                brief_json={
                    "contract_id": "kjds-governed-editing-handoff-v1",
                    "job_ref": prepared.job.job_ref,
                    "source_snapshot_sha256": prepared.blueprint[
                        "source_snapshot_sha256"
                    ],
                    "render_plan_sha256": prepared.render_plan_sha256,
                },
                source_facts_json={},
                status="generated",
                artifact_ref=artifacts["9:16"],
                qa_results_json=[],
                generation_json=generation_json,
                created_at=completion_now,
            )
        )
        session.flush()
        if after_flush is not None:
            after_flush()
        return {
            "artifact_evidence_refs": tuple(
                artifacts[ratio] for ratio in GOVERNED_RENDER_RATIOS
            ),
            "content_asset_ref": asset_ref,
        }

    return writer, asset_ref


def _jointly_resealed_blueprint(prepared, case: str) -> dict[str, Any]:
    blueprint = json.loads(canonical_json(prepared.blueprint))
    source_snapshot = json.loads(canonical_json(prepared.source_snapshot_content))
    if case == "analysis_observed_at":
        changed = (NOW + timedelta(seconds=1)).isoformat()
        blueprint["analysis_receipt"]["observed_at"] = changed
        source_snapshot["analysis_receipt"]["observed_at"] = changed
        receipt_content = dict(source_snapshot["analysis_receipt"])
        blueprint["analysis_receipt"]["source_snapshot_sha256"] = sha256_bytes(
            canonical_json(receipt_content)
        )
    elif case == "input_artifact_omitted":
        blueprint["input_artifacts"] = blueprint["input_artifacts"][1:]
        source_snapshot["input_artifacts"] = source_snapshot["input_artifacts"][1:]
    elif case == "input_artifact_role":
        blueprint["input_artifacts"][0]["role"] = "reference_video"
        source_snapshot["input_artifacts"][0]["role"] = "reference_video"
    elif case == "source_snapshot":
        blueprint["source_snapshot_sha256"] = "0" * 64
        return blueprint
    elif case in {"blueprint_noncanonical_bytes", "analysis_noncanonical_bytes"}:
        return blueprint
    elif case == "duplicate_scene_id":
        second = dict(blueprint["scenes"][0])
        second["source_start_ms"] = 1000
        second["source_end_ms"] = 2000
        second["timeline_start_ms"] = 1000
        second["timeline_end_ms"] = 2000
        blueprint["scenes"].append(second)
        source_snapshot["scenes"].append(dict(second))
    elif case == "invalid_scene_id":
        blueprint["scenes"][0]["scene_id"] = ""
        source_snapshot["scenes"][0]["scene_id"] = ""
    elif case == "caption_missing":
        blueprint["scenes"][0]["caption_ref"] = "evidence://missing-caption"
        source_snapshot["scenes"][0]["caption_ref"] = "evidence://missing-caption"
    elif case == "subtitle_missing":
        blueprint["subtitle_asset_ref"] = "evidence://missing-subtitle"
        source_snapshot["subtitle_asset_ref"] = "evidence://missing-subtitle"
    elif case == "audio_binding":
        replacement = blueprint["campaign_asset_refs"][0]
        blueprint["audio_asset_ref"] = replacement
        source_snapshot["audio_asset_ref"] = replacement
    elif case.startswith("scope_numeric_"):
        field = case.removeprefix("scope_numeric_")
        assert field in {
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "authority_sha256",
            "subject_actor_id",
        }
        blueprint["scope"][field] = 7
        source_snapshot["scope"][field] = 7
        scope_binding_sha256 = sha256_bytes(canonical_json(blueprint["scope"]))
        blueprint["scope_binding_sha256"] = scope_binding_sha256
        source_snapshot["scope_binding_sha256"] = scope_binding_sha256
    else:
        raise AssertionError(case)
    blueprint["source_snapshot_sha256"] = sha256_bytes(
        canonical_json(source_snapshot)
    )
    return blueprint


def _invoke_jointly_resealed_blueprint_attack(
    engine,
    *,
    prepared,
    case: str,
) -> None:
    blueprint = _jointly_resealed_blueprint(prepared, case)
    analysis_attack: tuple[str, bytes, str, dict[str, Any]] | None = None
    if case == "analysis_noncanonical_bytes":
        source_snapshot = json.loads(canonical_json(prepared.source_snapshot_content))
        analysis_id = blueprint["analysis_receipt"]["evidence_ref"].removeprefix(
            "evidence://"
        )
        with Session(engine) as read_session:
            analysis_record = read_session.get(EvidenceRecordRow, analysis_id)
            assert analysis_record is not None
            analysis_blob = read_session.get(
                EvidenceBlobRow, analysis_record.blob_sha256
            )
            assert analysis_blob is not None
            analysis_payload = json.loads(analysis_blob.content_bytes)
            analysis_bytes = json.dumps(
                analysis_payload, ensure_ascii=False, indent=2
            ).encode()
            analysis_sha256 = sha256_bytes(analysis_bytes)
            metadata = dict(analysis_record.metadata_json)
        metadata["analysis_contract_sha256"] = analysis_sha256
        blueprint["analysis_receipt"]["semantic_sha256"] = analysis_sha256
        blueprint["analysis_receipt"]["evidence_sha256"] = analysis_sha256
        source_snapshot["analysis_receipt"]["semantic_sha256"] = analysis_sha256
        source_snapshot["analysis_receipt"]["evidence_sha256"] = analysis_sha256
        receipt_content = dict(blueprint["analysis_receipt"])
        receipt_content.pop("source_snapshot_sha256", None)
        receipt_sha256 = sha256_bytes(canonical_json(receipt_content))
        blueprint["analysis_receipt"]["source_snapshot_sha256"] = receipt_sha256
        source_snapshot["analysis_receipt"]["source_snapshot_sha256"] = receipt_sha256
        blueprint["source_snapshot_sha256"] = sha256_bytes(
            canonical_json(source_snapshot)
        )
        analysis_attack = (analysis_id, analysis_bytes, analysis_sha256, metadata)
    blueprint_bytes = (
        json.dumps(blueprint, ensure_ascii=False, indent=2).encode()
        if case == "blueprint_noncanonical_bytes"
        else canonical_json(blueprint)
    )
    blueprint_sha256 = sha256_bytes(blueprint_bytes)
    try:
        render_plan_sha256 = sha256_bytes(
            canonical_json(derive_blueprint_render_plan(blueprint))
        )
    except ValueError:
        render_plan_sha256 = "0" * 64
    with Session(engine) as session, session.begin():
        session.execute(text("ALTER TABLE evidence_records DISABLE TRIGGER USER"))
        session.execute(
            text("ALTER TABLE media_job_evidence_links DISABLE TRIGGER USER")
        )
        if analysis_attack is not None:
            analysis_id, analysis_bytes, analysis_sha256, analysis_metadata = (
                analysis_attack
            )
            session.add(
                EvidenceBlobRow(
                    sha256=analysis_sha256,
                    byte_size=len(analysis_bytes),
                    content_bytes=analysis_bytes,
                    created_at=NOW,
                )
            )
            session.flush()
            session.execute(
                text(
                    "UPDATE evidence_records SET blob_sha256=:sha, byte_size=:size, "
                    "source_ref=:source_ref, metadata_json=CAST(:metadata AS json) "
                    "WHERE id=:evidence_id"
                ),
                {
                    "sha": analysis_sha256,
                    "size": len(analysis_bytes),
                    "source_ref": (
                        "reference-analysis://"
                        f"{analysis_metadata['analysis_run_ref']}/{analysis_sha256}"
                    ),
                    "metadata": json.dumps(
                        analysis_metadata, sort_keys=True, separators=(",", ":")
                    ),
                    "evidence_id": analysis_id,
                },
            )
            session.execute(
                text(
                    "UPDATE media_job_evidence_links SET blob_sha256=:sha "
                    "WHERE evidence_id=:evidence_id AND purpose='analysis_input'"
                ),
                {"sha": analysis_sha256, "evidence_id": analysis_id},
            )
        record = session.get(EvidenceRecordRow, prepared.blueprint_evidence_id)
        assert record is not None
        metadata = dict(record.metadata_json)
        metadata.update(
            {
                "blueprint_sha256": blueprint_sha256,
                "source_snapshot_sha256": blueprint["source_snapshot_sha256"],
                "analysis_evidence_sha256": blueprint["analysis_receipt"][
                    "evidence_sha256"
                ],
                "render_plan_sha256": render_plan_sha256,
            }
        )
        source_ref = (
            f"media-job://{blueprint['job_ref']}/blueprint/{blueprint_sha256}"
        )
        session.add(
            EvidenceBlobRow(
                sha256=blueprint_sha256,
                byte_size=len(blueprint_bytes),
                content_bytes=blueprint_bytes,
                created_at=NOW,
            )
        )
        session.flush()
        session.execute(
            text(
                "UPDATE evidence_records SET blob_sha256=:sha, byte_size=:size, "
                "source_ref=:source_ref, "
                "metadata_json=CAST(:metadata AS json) WHERE id=:evidence_id"
            ),
            {
                "sha": blueprint_sha256,
                "size": len(blueprint_bytes),
                "source_ref": source_ref,
                "metadata": json.dumps(metadata, sort_keys=True, separators=(",", ":")),
                "evidence_id": prepared.blueprint_evidence_id,
            },
        )
        session.execute(
            text(
                "UPDATE media_job_evidence_links SET blob_sha256=:sha, "
                "source_ref=:source_ref WHERE evidence_id=:evidence_id "
                "AND purpose='blueprint_input'"
            ),
            {
                "sha": blueprint_sha256,
                "source_ref": source_ref,
                "evidence_id": prepared.blueprint_evidence_id,
            },
        )
        session.execute(
            text(
                "SELECT kjds_media_job_validate_blueprint_provenance("
                ":evidence_id,:render_job_ref)"
            ),
            {
                "evidence_id": prepared.blueprint_evidence_id,
                "render_job_ref": prepared.job.job_ref,
            },
        )


def _workspace(engine, *, tick: int = 0) -> GovernedMediaJobWorkspace:
    return GovernedMediaJobWorkspace(
        engine,
        evidence=EvidenceService(engine),
        authority=_ScopeAuthority(),
        content_assets=_DatabaseContentAssetAuthority(engine),
        clock=lambda: NOW + timedelta(seconds=tick),
    )


def _authority_workspace(engine, principal: Principal) -> GovernedMediaJobWorkspace:
    return GovernedMediaJobWorkspace(
        engine,
        evidence=EvidenceService(engine),
        authority=_DatabaseScopeAuthority(
            engine,
            tenant_ref=principal.tenant_ref,
            actor_id=principal.actor_id,
        ),
        clock=lambda: NOW,
    )


def _capture_rotation_evidence(engine, suffix: str):
    return EvidenceService(engine).capture(
        content=f"rotation-{suffix}".encode(),
        filename=f"rotation-{suffix}.json",
        content_type="application/json",
        source="media-job-authority-test",
        source_ref=f"media-job-authority-test://{suffix}",
        grade=EvidenceGrade.B,
        effective_at=NOW.isoformat(),
        effective_until=None,
        created_by="bas184-pg-test",
    )


def _hold_revoke(
    engine,
    principal: Principal,
    evidence,
    started: Event,
    acquired: Event,
    release: Event,
) -> None:
    started.set()
    with Session(engine, expire_on_commit=False) as session, session.begin():
        session.add(
            ScopeGrantEventRow(
                id=f"scope-revoke-{uuid4().hex}",
                tenant_ref=principal.tenant_ref,
                entity_ref="entity-media-pg",
                store_ref="store-media-pg",
                subject_actor_id=principal.actor_id,
                event_type="revoke",
                effective_at=NOW,
                evidence_id=evidence.id,
                evidence_sha256=evidence.sha256,
                reason="BAS-184 concurrency test rotation",
                idempotency_key=f"revoke-{uuid4().hex}",
                request_sha256=sha256_bytes(uuid4().hex.encode()),
                created_by="bas184-pg-test",
                recorded_at=NOW,
            )
        )
        session.flush()
        acquired.set()
        assert release.wait(timeout=10)


def _surface_counts(engine) -> tuple[int, ...]:
    existing_tables = set(inspect(engine).get_table_names())
    with Session(engine) as session:
        return tuple(
            (
                int(session.scalar(select(func.count()).select_from(model)) or 0)
                if model.__tablename__ in existing_tables
                else 0
            )
            for model in (
                MediaJobRow,
                MediaJobEventRow,
                MediaJobEvidenceLinkRow,
                MediaJobRequestBindingRow,
                MediaJobWorkerInputRow,
                MediaJobResultReceiptRow,
                EvidenceRecordRow,
                EvidenceBlobRow,
                ContentAssetRow,
            )
        )


def _assert_atomic_render_result_delta(
    before: tuple[int, ...], after: tuple[int, ...]
) -> None:
    # DISPATCHED -> RUNNING -> UPLOADING -> SUCCEEDED, three artifacts, and
    # one terminal Evidence/link/result/asset are the only admitted writes.
    assert tuple(
        current - previous
        for previous, current in zip(before, after, strict=True)
    ) == (
        0,
        3,
        1,
        0,
        0,
        1,
        4,
        4,
        1,
    )


def _catalog_state(engine) -> tuple[tuple[str, ...], tuple[str, ...]]:
    inspector = inspect(engine)
    relations = tuple(
        sorted(
            name
            for name in inspector.get_table_names()
            if name in {"media_jobs", "media_job_events", "media_job_evidence_links"}
        )
    )
    with engine.connect() as connection:
        triggers = tuple(
            sorted(
                connection.scalars(
                    text(
                        "SELECT tgname FROM pg_trigger t "
                        "JOIN pg_class c ON c.oid=t.tgrelid "
                        "WHERE NOT t.tgisinternal AND c.relname IN "
                        "('media_jobs','media_job_events','media_job_evidence_links')"
                    )
                )
            )
        )
    return relations, triggers


def _build_state_event(
    session: Session,
    *,
    job_ref: str,
    state: str,
    command_marker: str,
    occurred_at: datetime,
    recorded_at: datetime | None = None,
    safe_reason_code: str | None = None,
    projection_ordinal: Any | None = None,
) -> MediaJobEventRow:
    job = session.get(MediaJobRow, job_ref)
    assert job is not None
    previous = session.scalar(
        select(MediaJobEventRow)
        .where(MediaJobEventRow.job_ref == job_ref)
        .order_by(MediaJobEventRow.ordinal.desc())
    )
    assert previous is not None
    recorded_at = recorded_at or occurred_at
    ordinal = previous.ordinal + 1
    projection = {
        "job_ref": job_ref,
        "ordinal": ordinal if projection_ordinal is None else projection_ordinal,
        "state": state,
        "safe_reason_code": safe_reason_code,
    }
    event_hash = event_seal(
        job=None,
        job_ref=job_ref,
        tenant_ref=job.tenant_ref,
        entity_ref=job.entity_ref,
        store_ref=job.store_ref,
        authority_sha256=job.scope_grant_authority_sha256,
        subject_actor_id=job.subject_actor_id,
        ordinal=ordinal,
        stream_kind="job_state",
        state=state,
        safe_reason_code=safe_reason_code,
        previous_event_sha256=previous.event_sha256,
        public_projection_json=projection,
        occurred_at=occurred_at,
        recorded_at=recorded_at,
        command_idempotency_sha256=command_marker,
        command_request_sha256=command_marker,
    )
    return MediaJobEventRow(
        event_ref=f"media_event_{uuid4().hex}",
        job_ref=job_ref,
        tenant_ref=job.tenant_ref,
        entity_ref=job.entity_ref,
        store_ref=job.store_ref,
        scope_grant_authority_sha256=job.scope_grant_authority_sha256,
        ordinal=ordinal,
        stream_kind="job_state",
        state=state,
        safe_reason_code=safe_reason_code,
        previous_event_sha256=previous.event_sha256,
        event_sha256=event_hash,
        command_idempotency_sha256=command_marker,
        command_request_sha256=command_marker,
        public_projection_json=projection,
        occurred_at=occurred_at,
        recorded_at=recorded_at,
    )


def _insert_state_event(engine, **kwargs: Any) -> None:
    with Session(engine) as session, session.begin():
        session.add(_build_state_event(session, **kwargs))


def test_00_migration_replays_empty_0096_to_0097(engine):
    with engine.connect() as connection:
        has_version_table = bool(
            connection.scalar(
                text("SELECT to_regclass('public.alembic_version')")
            )
        )
        version = (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            if has_version_table
            else None
        )
    target_tables = {
        "media_jobs",
        "media_job_events",
        "media_job_evidence_links",
    }
    initial_tables = set(inspect(engine).get_table_names())
    if version is None:
        _migrate("upgrade", "20260805_0096")
    elif version != "20260805_0096":
        _migrate("downgrade", "20260805_0096")
    if target_tables <= initial_tables:
        assert _surface_counts(engine) == (0, 0, 0, 0, 0, 0, 0, 0, 0)
    else:
        assert not target_tables & set(inspect(engine).get_table_names())

    _migrate("upgrade", "20260808_0097")
    first = _catalog_state(engine)
    _migrate("downgrade", "20260805_0096")
    _migrate("upgrade", "20260808_0097")
    assert _catalog_state(engine) == first
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "20260808_0097"
        )


def test_01_media_job_migration_freezes_exact_contract():
    source = MIGRATION.read_text(encoding="utf-8")
    result_source = RESULT_MIGRATION.read_text(encoding="utf-8")

    assert 'revision = "20260808_0097"' in source
    assert 'down_revision = "20260805_0096"' in source
    assert "kjds_media_job_validate_event" in source
    assert "kjds_media_job_validate_evidence_binding" in source
    assert "kjds_media_job_terminal_evidence_conservation" in source
    assert "kjds_media_job_prevent_mutation" in source
    assert "WHEN 'LOGIN_REQUIRED'" in source
    assert "WHEN 'LIMITED'" in source
    assert "ERRCODE='23514'" in source
    assert "ERRCODE='55000'" in source
    assert "DROP OWNED" not in source
    assert "revision = '20260809_0098'" in result_source
    assert "down_revision = '20260808_0097'" in result_source
    assert "kjds_media_job_validate_result_receipt" in result_source
    assert "kjds_media_job_validate_worker_input" in result_source
    assert "media_job_worker_inputs" in result_source
    assert "artifact_evidence_refs" in result_source
    assert "content_assets" in result_source
    assert "state IN ('SUCCEEDED','FAILED','UNKNOWN_OUTCOME')" in result_source
    assert "CANCELLED" not in result_source.split("ck_media_job_result_terminal_state", 1)[1].split(
        "),", 1
    )[0]
    assert "ERRCODE='23514'" in result_source
    assert "ERRCODE='55000'" in result_source


def test_02_schema_has_exact_0097_relations_and_triggers(engine):
    relations, triggers = _catalog_state(engine)
    assert relations == (
        "media_job_events",
        "media_job_evidence_links",
        "media_jobs",
    )
    assert {
        "trg_media_jobs_immutable",
        "trg_media_job_events_immutable",
        "trg_media_job_evidence_links_immutable",
        "trg_media_job_event_contract",
        "trg_media_job_request_evidence",
        "trg_media_job_link_evidence",
        "trg_media_job_terminal_evidence_conservation",
    } <= set(triggers)


def test_03_service_submit_replay_cancel_and_append_only_are_real(engine):
    service = _workspace(engine)
    principal = _principal("actor-service-pg", "tenant-service-pg")
    request = _request("1" * 64)
    before = _surface_counts(engine)

    first = service.submit(
        principal=principal,
        store_ref="store-media-pg",
        request=request,
    )
    replay = service.submit(
        principal=principal,
        store_ref="store-media-pg",
        request=request,
    )
    cancelled = service.cancel(
        principal=principal,
        store_ref="store-media-pg",
        job_ref=first.job_ref,
        idempotency_key="cancel-service-pg",
    )
    cancel_replay = service.cancel(
        principal=principal,
        store_ref="store-media-pg",
        job_ref=first.job_ref,
        idempotency_key="cancel-service-pg",
    )

    assert replay == first
    assert cancel_replay == cancelled
    assert cancelled.state == "CANCELLED"
    after = _surface_counts(engine)
    assert tuple(end - start for start, end in zip(before, after, strict=True)) == (
        1,
        2,
        2,
        0,
        0,
        0,
        2,
        2,
        0,
    )
    with pytest.raises(DBAPIError) as error, engine.begin() as connection:
        connection.execute(
            text("UPDATE media_jobs SET tool_version='drift' WHERE job_ref=:job"),
            {"job": first.job_ref},
        )
    assert _sqlstate(error.value) == "23514"
    assert _surface_counts(engine) == after


def test_04_postgres_rejects_illegal_resigned_transition_with_zero_residue(engine):
    service = _workspace(engine, tick=10)
    principal = _principal("actor-transition-pg", "tenant-transition-pg")
    created = service.submit(
        principal=principal,
        store_ref="store-media-pg",
        request=_request("2" * 64),
    )
    before = _surface_counts(engine)

    with pytest.raises(DBAPIError) as error:
        _insert_state_event(
            engine,
            job_ref=created.job_ref,
            state="SUCCEEDED",
            command_marker="3" * 64,
            occurred_at=NOW + timedelta(seconds=11),
        )
    assert _sqlstate(error.value) == "23514"
    assert _surface_counts(engine) == before


@pytest.mark.parametrize("paused", ["LOGIN_REQUIRED", "LIMITED"])
def test_05_paused_states_resume_by_controlled_dispatch_and_reject_success_jump(
    engine,
    paused,
):
    marker = "4" if paused == "LOGIN_REQUIRED" else "5"
    service = _workspace(engine, tick=20)
    principal = _principal(f"actor-{paused.lower()}", f"tenant-{paused.lower()}")
    created = service.submit(
        principal=principal,
        store_ref="store-media-pg",
        request=_request(marker * 64),
    )
    _insert_state_event(
        engine,
        job_ref=created.job_ref,
        state=paused,
        safe_reason_code=(
            "connector_login_required"
            if paused == "LOGIN_REQUIRED"
            else "settled_entitlement_unavailable"
        ),
        command_marker="6" * 64,
        occurred_at=NOW + timedelta(seconds=21),
    )
    _insert_state_event(
        engine,
        job_ref=created.job_ref,
        state="DISPATCHED",
        command_marker="7" * 64,
        occurred_at=NOW + timedelta(seconds=22),
    )
    assert [event.state for event in service.events(
        principal=principal,
        store_ref="store-media-pg",
        job_ref=created.job_ref,
    )] == ["QUEUED", paused, "DISPATCHED"]

    readback_started = _workspace(engine, tick=30).submit(
        principal=principal,
        store_ref="store-media-pg",
        request=_request(("8" if paused == "LOGIN_REQUIRED" else "9") * 64),
    )
    _insert_state_event(
        engine,
        job_ref=readback_started.job_ref,
        state=paused,
        safe_reason_code=(
            "connector_login_required"
            if paused == "LOGIN_REQUIRED"
            else "settled_entitlement_unavailable"
        ),
        command_marker="a" * 64,
        occurred_at=NOW + timedelta(seconds=31),
    )
    _insert_state_event(
        engine,
        job_ref=readback_started.job_ref,
        state="RUNNING",
        command_marker="b" * 64,
        occurred_at=NOW + timedelta(seconds=32),
    )

    for offset, denied_state in enumerate(("SUCCEEDED", "CANCELLED"), start=40):
        denied = _workspace(engine, tick=offset).submit(
            principal=principal,
            store_ref="store-media-pg",
            request=_request(f"{offset:064x}"),
        )
        _insert_state_event(
            engine,
            job_ref=denied.job_ref,
            state=paused,
            safe_reason_code=(
                "connector_login_required"
                if paused == "LOGIN_REQUIRED"
                else "settled_entitlement_unavailable"
            ),
            command_marker="c" * 64,
            occurred_at=NOW + timedelta(seconds=offset + 1),
        )
        before = _surface_counts(engine)
        with pytest.raises(DBAPIError) as error:
            _insert_state_event(
                engine,
                job_ref=denied.job_ref,
                state=denied_state,
                safe_reason_code=(
                    "cancelled_by_request" if denied_state == "CANCELLED" else None
                ),
                command_marker="d" * 64,
                occurred_at=NOW + timedelta(seconds=offset + 2),
            )
        assert _sqlstate(error.value) == "23514"
        assert _surface_counts(engine) == before


def test_05b_malformed_projection_ordinal_is_23514_with_zero_residue(engine):
    service = _workspace(engine, tick=35)
    principal = _principal("actor-projection-pg", "tenant-projection-pg")
    created = service.submit(
        principal=principal,
        store_ref="store-media-pg",
        request=_request("0" * 64),
    )
    before = _surface_counts(engine)
    with pytest.raises(DBAPIError) as error:
        _insert_state_event(
            engine,
            job_ref=created.job_ref,
            state="DISPATCHED",
            command_marker="1" * 64,
            occurred_at=NOW + timedelta(seconds=36),
            projection_ordinal="not-an-integer",
        )
    assert _sqlstate(error.value) == "23514"
    assert _surface_counts(engine) == before


def test_05c_terminal_event_without_evidence_is_23514_and_atomic(engine):
    service = _workspace(engine, tick=37)
    principal = _principal("actor-terminal-pg", "tenant-terminal-pg")
    created = service.submit(
        principal=principal,
        store_ref="store-media-pg",
        request=_request("2" * 64),
    )
    _insert_state_event(
        engine,
        job_ref=created.job_ref,
        state="DISPATCHED",
        command_marker="3" * 64,
        occurred_at=NOW + timedelta(seconds=38),
    )
    before = _surface_counts(engine)
    with pytest.raises(DBAPIError) as error:
        _insert_state_event(
            engine,
            job_ref=created.job_ref,
            state="FAILED",
            safe_reason_code="provider_failed",
            command_marker="4" * 64,
            occurred_at=NOW + timedelta(seconds=39),
        )
    assert _sqlstate(error.value) == "23514"
    assert _surface_counts(engine) == before


@pytest.mark.parametrize(
    "field,drifted_value",
    [
        ("tenant_ref", "tenant-foreign"),
        ("entity_ref", "entity-foreign"),
        ("store_ref", "store-foreign"),
        ("scope_grant_authority_sha256", "f" * 64),
        ("subject_actor_id", "actor-foreign"),
    ],
)
def test_06_request_evidence_scope_metadata_drift_is_23514_and_atomic(
    engine,
    field,
    drifted_value,
):
    service = _workspace(engine, tick=40)
    suffix = uuid4().hex
    principal = _principal(f"actor-binding-{suffix}", f"tenant-binding-{suffix}")
    created = service.submit(
        principal=principal,
        store_ref="store-media-pg",
        request=_request(sha256_bytes(f"original-{suffix}".encode())),
    )
    before = _surface_counts(engine)

    with pytest.raises(DBAPIError) as error, Session(engine) as session, session.begin():
        job = session.get(MediaJobRow, created.job_ref)
        assert job is not None
        source = session.get(EvidenceRecordRow, job.request_evidence_id)
        assert source is not None
        idempotency = sha256_bytes(f"forged-{field}-{suffix}".encode())
        request = _request(idempotency)
        request_bytes = canonical_json(request)
        request_sha256 = sha256_bytes(request_bytes)
        scope_payload = {
            "tenant_ref": job.tenant_ref,
            "entity_ref": job.entity_ref,
            "store_ref": job.store_ref,
            "authority_sha256": job.scope_grant_authority_sha256,
            "subject_actor_id": job.subject_actor_id,
        }
        request_fingerprint = sha256_bytes(
            canonical_json({"scope": scope_payload, "request": request})
        )
        scope_binding = sha256_bytes(canonical_json(scope_payload))
        forged_evidence_id = f"evd_{uuid4().hex}"
        forged_metadata = {
            "contract_id": "kjds-governed-media-job-request-v1",
            "media_job_request_fingerprint_sha256": request_fingerprint,
            "tenant_ref": job.tenant_ref,
            "entity_ref": job.entity_ref,
            "store_ref": job.store_ref,
            "scope_grant_authority_sha256": job.scope_grant_authority_sha256,
            "subject_actor_id": job.subject_actor_id,
        }
        forged_metadata[field] = drifted_value
        session.add(
            EvidenceBlobRow(
                sha256=request_sha256,
                byte_size=len(request_bytes),
                content_bytes=request_bytes,
                created_at=job.created_at,
            )
        )
        session.add(
            EvidenceRecordRow(
                id=forged_evidence_id,
                blob_sha256=request_sha256,
                filename=source.filename,
                content_type=source.content_type,
                source=source.source,
                source_ref=f"media-job://{scope_binding}/{idempotency}/request",
                grade=source.grade,
                effective_at=job.created_at,
                effective_until=None,
                recorded_at=job.created_at,
                created_by=job.subject_actor_id,
                metadata_json=forged_metadata,
            )
        )
        session.flush()
        session.add(
            MediaJobRow(
                job_ref=f"media_job_{uuid4().hex}",
                tenant_ref=job.tenant_ref,
                entity_ref=job.entity_ref,
                store_ref=job.store_ref,
                scope_grant_authority_sha256=job.scope_grant_authority_sha256,
                subject_actor_id=job.subject_actor_id,
                tool_name=job.tool_name,
                tool_version=job.tool_version,
                project_ref=job.project_ref,
                brief_ref=job.brief_ref,
                provider=job.provider,
                connector_ref=job.connector_ref,
                connector_binding_sha256=job.connector_binding_sha256,
                idempotency_sha256=idempotency,
                request_sha256=request_sha256,
                request_fingerprint_sha256=request_fingerprint,
                request_evidence_id=forged_evidence_id,
                request_evidence_sha256=request_sha256,
                created_at=job.created_at,
            )
        )
        session.flush()
    assert _sqlstate(error.value) == "23514"
    assert _surface_counts(engine) == before


def test_06b_request_evidence_content_swap_is_23514_and_atomic(engine):
    suffix = uuid4().hex
    service = _workspace(engine, tick=45)
    principal = _principal(f"actor-content-{suffix}", f"tenant-content-{suffix}")
    created = service.submit(
        principal=principal,
        store_ref="store-media-pg",
        request=_request(sha256_bytes(f"seed-{suffix}".encode())),
    )
    before = _surface_counts(engine)

    with pytest.raises(DBAPIError) as error, Session(engine) as session, session.begin():
        template = session.get(MediaJobRow, created.job_ref)
        assert template is not None
        idempotency = sha256_bytes(f"swap-{suffix}".encode())
        request = _request(idempotency)
        request_bytes = canonical_json(request)
        request_sha256 = sha256_bytes(request_bytes)
        swapped_bytes = canonical_json({"swapped": suffix})
        swapped_sha256 = sha256_bytes(swapped_bytes)
        scope_payload = {
            "tenant_ref": template.tenant_ref,
            "entity_ref": template.entity_ref,
            "store_ref": template.store_ref,
            "authority_sha256": template.scope_grant_authority_sha256,
            "subject_actor_id": template.subject_actor_id,
        }
        fingerprint = sha256_bytes(
            canonical_json({"scope": scope_payload, "request": request})
        )
        scope_binding = sha256_bytes(canonical_json(scope_payload))
        evidence_id = f"evd_{uuid4().hex}"
        session.add(
            EvidenceBlobRow(
                sha256=swapped_sha256,
                byte_size=len(swapped_bytes),
                content_bytes=swapped_bytes,
                created_at=template.created_at,
            )
        )
        session.add(
            EvidenceRecordRow(
                id=evidence_id,
                blob_sha256=swapped_sha256,
                filename="media-job-request.json",
                content_type="application/json",
                source="governed-media-job-request",
                source_ref=f"media-job://{scope_binding}/{idempotency}/request",
                grade="B",
                effective_at=template.created_at,
                effective_until=None,
                recorded_at=template.created_at,
                created_by=template.subject_actor_id,
                metadata_json={
                    "contract_id": "kjds-governed-media-job-request-v1",
                    "media_job_request_fingerprint_sha256": fingerprint,
                    "tenant_ref": template.tenant_ref,
                    "entity_ref": template.entity_ref,
                    "store_ref": template.store_ref,
                    "scope_grant_authority_sha256": (
                        template.scope_grant_authority_sha256
                    ),
                    "subject_actor_id": template.subject_actor_id,
                },
            )
        )
        session.flush()
        session.add(
            MediaJobRow(
                job_ref=f"media_job_{uuid4().hex}",
                tenant_ref=template.tenant_ref,
                entity_ref=template.entity_ref,
                store_ref=template.store_ref,
                scope_grant_authority_sha256=(
                    template.scope_grant_authority_sha256
                ),
                subject_actor_id=template.subject_actor_id,
                tool_name=template.tool_name,
                tool_version=template.tool_version,
                project_ref=template.project_ref,
                brief_ref=template.brief_ref,
                provider=template.provider,
                connector_ref=template.connector_ref,
                connector_binding_sha256=template.connector_binding_sha256,
                idempotency_sha256=idempotency,
                request_sha256=request_sha256,
                request_fingerprint_sha256=fingerprint,
                request_evidence_id=evidence_id,
                request_evidence_sha256=swapped_sha256,
                created_at=template.created_at,
            )
        )
        session.flush()
    assert _sqlstate(error.value) == "23514"
    assert _surface_counts(engine) == before


def test_06c_terminal_evidence_content_swap_is_23514_and_atomic(engine):
    service = _workspace(engine, tick=50)
    principal = _principal("actor-terminal-swap", "tenant-terminal-swap")
    created = service.submit(
        principal=principal,
        store_ref="store-media-pg",
        request=_request("5" * 64),
    )
    _insert_state_event(
        engine,
        job_ref=created.job_ref,
        state="DISPATCHED",
        command_marker="6" * 64,
        occurred_at=NOW + timedelta(seconds=51),
    )
    before = _surface_counts(engine)

    with pytest.raises(DBAPIError) as error, Session(engine) as session, session.begin():
        job = session.get(MediaJobRow, created.job_ref)
        assert job is not None
        event = _build_state_event(
            session,
            job_ref=created.job_ref,
            state="FAILED",
            safe_reason_code="provider_failed",
            command_marker="7" * 64,
            occurred_at=NOW + timedelta(seconds=52),
        )
        session.add(event)
        session.flush()
        swapped_bytes = canonical_json({"forged_terminal": True})
        swapped_sha256 = sha256_bytes(swapped_bytes)
        evidence_id = f"evd_{uuid4().hex}"
        session.add(
            EvidenceBlobRow(
                sha256=swapped_sha256,
                byte_size=len(swapped_bytes),
                content_bytes=swapped_bytes,
                created_at=event.recorded_at,
            )
        )
        session.add(
            EvidenceRecordRow(
                id=evidence_id,
                blob_sha256=swapped_sha256,
                filename="media-job-transition.json",
                content_type="application/json",
                source="governed-media-job-transition",
                source_ref=f"media-job://{job.job_ref}/transition/{event.event_ref}",
                grade="B",
                effective_at=event.occurred_at,
                effective_until=None,
                recorded_at=event.recorded_at,
                created_by=job.subject_actor_id,
                metadata_json={
                    "contract_id": "kjds-governed-media-job-transition-v1",
                    "tenant_ref": job.tenant_ref,
                    "entity_ref": job.entity_ref,
                    "store_ref": job.store_ref,
                    "scope_grant_authority_sha256": (
                        job.scope_grant_authority_sha256
                    ),
                    "subject_actor_id": job.subject_actor_id,
                    "event_sha256": event.event_sha256,
                },
            )
        )
        session.flush()
        session.add(
            MediaJobEvidenceLinkRow(
                link_ref=f"media_link_{uuid4().hex}",
                job_ref=job.job_ref,
                event_ref=event.event_ref,
                tenant_ref=job.tenant_ref,
                entity_ref=job.entity_ref,
                store_ref=job.store_ref,
                scope_grant_authority_sha256=job.scope_grant_authority_sha256,
                purpose="artifact_terminal",
                evidence_id=evidence_id,
                blob_sha256=swapped_sha256,
                source="governed-media-job-transition",
                source_ref=f"media-job://{job.job_ref}/transition/{event.event_ref}",
                effective_at=event.occurred_at,
                recorded_at=event.recorded_at,
                fresh_until=None,
            )
        )
    assert _sqlstate(error.value) == "23514"
    assert _surface_counts(engine) == before


@pytest.mark.parametrize(
    "case",
    [
        "reason_mismatch",
        "occurred_after_recorded",
        "previous_time_regression",
        "future_time",
    ],
)
def test_06d_event_reason_and_time_drift_is_23514_and_atomic(engine, case):
    suffix = uuid4().hex
    service = _workspace(engine, tick=70)
    principal = _principal(f"actor-time-{suffix}", f"tenant-time-{suffix}")
    created = service.submit(
        principal=principal,
        store_ref="store-media-pg",
        request=_request(sha256_bytes(f"time-{suffix}".encode())),
    )
    occurred_at = NOW + timedelta(seconds=71)
    recorded_at = occurred_at
    reason = None
    if case == "reason_mismatch":
        reason = "unfrozen_internal_text"
    elif case == "occurred_after_recorded":
        recorded_at = occurred_at - timedelta(seconds=1)
    elif case == "previous_time_regression":
        occurred_at = NOW + timedelta(seconds=69)
        recorded_at = occurred_at
    else:
        occurred_at = datetime.now(UTC) + timedelta(days=1)
        recorded_at = occurred_at
    before = _surface_counts(engine)
    with pytest.raises(DBAPIError) as error:
        _insert_state_event(
            engine,
            job_ref=created.job_ref,
            state="DISPATCHED",
            safe_reason_code=reason,
            command_marker=sha256_bytes(case.encode()),
            occurred_at=occurred_at,
            recorded_at=recorded_at,
        )
    assert _sqlstate(error.value) == "23514"
    assert _surface_counts(engine) == before


def test_07_two_session_same_key_has_one_winner_and_exact_replay(engine):
    tenant = f"tenant-concurrent-{uuid4().hex}"
    principal = _principal("actor-concurrent-pg", tenant)
    request = _request("e" * 64)
    services = (_workspace(engine, tick=50), _workspace(engine, tick=50))
    barrier = Barrier(2)
    before = _surface_counts(engine)

    def compete(service):
        barrier.wait(timeout=10)
        return service.submit(
            principal=principal,
            store_ref="store-media-pg",
            request=request,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(compete, services))

    assert results[0] == results[1]
    after = _surface_counts(engine)
    assert tuple(end - start for start, end in zip(before, after, strict=True)) == (
        1,
        1,
        1,
        0,
        0,
        0,
        1,
        1,
        0,
    )


def test_08_two_session_actor_drift_has_one_winner_and_zero_loser_residue(engine):
    tenant = f"tenant-drift-{uuid4().hex}"
    principals = (
        _principal("actor-drift-a", tenant),
        _principal("actor-drift-b", tenant),
    )
    services = (_workspace(engine, tick=60), _workspace(engine, tick=60))
    request = _request("f" * 64)
    barrier = Barrier(2)
    before = _surface_counts(engine)

    def compete(pair):
        service, principal = pair
        barrier.wait(timeout=10)
        try:
            return service.submit(
                principal=principal,
                store_ref="store-media-pg",
                request=request,
            )
        except ValueError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(compete, zip(services, principals, strict=True)))

    assert sum(not isinstance(result, Exception) for result in results) == 1
    errors = [result for result in results if isinstance(result, Exception)]
    assert len(errors) == 1
    assert str(errors[0]) == "media_job_idempotency_conflict"
    after = _surface_counts(engine)
    assert tuple(end - start for start, end in zip(before, after, strict=True)) == (
        1,
        1,
        1,
        0,
        0,
        0,
        1,
        1,
        0,
    )


def test_09_rotation_committed_before_claim_blocks_stale_dispatch(engine):
    suffix = uuid4().hex
    tenant = f"tenant-claim-rotation-{suffix}"
    principal = _principal(f"actor-claim-rotation-{suffix}", tenant)
    service = _authority_workspace(engine, principal)
    created = service.submit(
        principal=principal,
        store_ref="store-media-pg",
        request=_request(sha256_bytes(f"claim-rotation-{suffix}".encode())),
    )
    evidence = _capture_rotation_evidence(engine, suffix)
    before = _surface_counts(engine)
    rotation_started = Event()
    rotation_acquired = Event()
    release_rotation = Event()
    claim_started = Event()
    provider_attempts = []

    with ThreadPoolExecutor(max_workers=2) as executor:
        rotation = executor.submit(
            _hold_revoke,
            engine,
            principal,
            evidence,
            rotation_started,
            rotation_acquired,
            release_rotation,
        )
        assert rotation_acquired.wait(timeout=10)

        def claim():
            claim_started.set()
            projection, claimed = service.claim_provider_attempt(
                principal=principal,
                store_ref="store-media-pg",
                job_ref=created.job_ref,
            )
            if claimed:
                provider_attempts.append(projection.job_ref)
            return projection, claimed

        claim_future = executor.submit(claim)
        assert claim_started.wait(timeout=10)
        with pytest.raises(FuturesTimeoutError):
            claim_future.result(timeout=0.25)
        release_rotation.set()
        rotation.result(timeout=10)
        with pytest.raises(PermissionError, match="scope_authority_not_current"):
            claim_future.result(timeout=10)

    assert provider_attempts == []
    assert _surface_counts(engine) == before


def test_10_claim_authority_lock_blocks_rotation_until_dispatch_commit(engine, monkeypatch):
    suffix = uuid4().hex
    tenant = f"tenant-claim-first-{suffix}"
    principal = _principal(f"actor-claim-first-{suffix}", tenant)
    service = _authority_workspace(engine, principal)
    created = service.submit(
        principal=principal,
        store_ref="store-media-pg",
        request=_request(sha256_bytes(f"claim-first-{suffix}".encode())),
    )
    evidence = _capture_rotation_evidence(engine, suffix)
    before = _surface_counts(engine)
    claim_at_event = Event()
    allow_claim = Event()
    rotation_started = Event()
    rotation_acquired = Event()
    release_rotation = Event()
    provider_attempts = []
    original_validate = service._validate_event_chain

    def pause_after_chain(session, row, scope):
        result = original_validate(session, row, scope)
        claim_at_event.set()
        assert allow_claim.wait(timeout=10)
        return result

    monkeypatch.setattr(service, "_validate_event_chain", pause_after_chain)

    def claim():
        projection, claimed = service.claim_provider_attempt(
            principal=principal,
            store_ref="store-media-pg",
            job_ref=created.job_ref,
        )
        if claimed:
            provider_attempts.append(projection.job_ref)
        return projection, claimed

    with ThreadPoolExecutor(max_workers=2) as executor:
        claim_future = executor.submit(claim)
        assert claim_at_event.wait(timeout=10)
        rotation = executor.submit(
            _hold_revoke,
            engine,
            principal,
            evidence,
            rotation_started,
            rotation_acquired,
            release_rotation,
        )
        assert rotation_started.wait(timeout=10)
        assert not rotation_acquired.wait(timeout=0.25)
        allow_claim.set()
        projection, claimed = claim_future.result(timeout=10)
        assert projection.job_ref == created.job_ref
        assert claimed is True
        assert rotation_acquired.wait(timeout=10)
        release_rotation.set()
        rotation.result(timeout=10)

    assert provider_attempts == [created.job_ref]
    after = _surface_counts(engine)
    assert tuple(end - start for start, end in zip(before, after, strict=True)) == (
        0,
        1,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
    )


def test_99_populated_downgrade_is_55000_and_preserves_0097(engine):
    before = _surface_counts(engine)
    assert before[0] > 0

    with pytest.raises(BaseException) as error:
        _migrate("downgrade", "20260805_0096")
    assert _sqlstate(error.value) == "55000"
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "20260808_0097"
        )
    assert _surface_counts(engine) == before


RESULT_MIGRATION = (
    Path(__file__).parents[1]
    / "migrations"
    / "versions"
    / "20260809_0098_media_job_result_readback.py"
)
SCHEMA_TRANSITION_ADVISORY_KEY = "kjds-media-jobs-0098-result-readback"


def _wait_for_schema_transition_advisory(
    engine, *, mode: str, granted: bool
) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        with engine.connect() as connection:
            observed = connection.scalar(
                text(
                    "SELECT count(*) FROM pg_locks "
                    "WHERE locktype='advisory' AND mode=:mode AND granted=:granted "
                    "AND classid=((hashtext(:key)::bigint >> 32) "
                    "& 4294967295)::oid "
                    "AND objid=(hashtext(:key)::bigint & 4294967295)::oid"
                ),
                {
                    "mode": mode,
                    "granted": granted,
                    "key": SCHEMA_TRANSITION_ADVISORY_KEY,
                },
            )
        if int(observed or 0) > 0:
            return
        Event().wait(0.05)
    raise AssertionError(
        f"schema transition advisory lock not observed: {mode}/{granted}"
    )


def _wait_for_migration_table_locks(engine, *table_names: str) -> None:
    deadline = time.monotonic() + 10
    expected = set(table_names)
    while time.monotonic() < deadline:
        with engine.connect() as connection:
            owner = connection.execute(
                text(
                    "SELECT locks.pid, array_agg(DISTINCT c.relname) AS relations "
                    "FROM pg_locks locks "
                    "JOIN pg_class c ON c.oid=locks.relation "
                    "WHERE locks.granted "
                    "AND locks.mode IN ('ShareRowExclusiveLock','ExclusiveLock',"
                    "'AccessExclusiveLock') "
                    "AND c.relname = ANY(:tables) "
                    "GROUP BY locks.pid "
                    "HAVING count(DISTINCT c.relname)=:expected_count"
                ),
                {"tables": list(expected), "expected_count": len(expected)},
            ).first()
        if owner is not None and expected <= set(owner.relations):
            return
        Event().wait(0.05)
    raise AssertionError(f"migration table locks not observed: {sorted(expected)}")


def _legacy_job_copy_statement() -> str:
    return (
        "INSERT INTO media_jobs ("
        "job_ref,tenant_ref,entity_ref,store_ref,scope_grant_authority_sha256,"
        "subject_actor_id,tool_name,tool_version,project_ref,brief_ref,provider,"
        "connector_ref,connector_binding_sha256,idempotency_sha256,request_sha256,"
        "request_fingerprint_sha256,request_evidence_id,request_evidence_sha256,"
        "created_at) SELECT :job_ref,tenant_ref,entity_ref,store_ref,"
        "scope_grant_authority_sha256,subject_actor_id,'media.video_render',"
        "tool_version,project_ref,brief_ref,provider,connector_ref,"
        "connector_binding_sha256,:idempotency,request_sha256,"
        "request_fingerprint_sha256,request_evidence_id,request_evidence_sha256,"
        "created_at FROM media_jobs ORDER BY created_at LIMIT 1"
    )


def test_100_upgrade_waits_for_inflight_0097_writer_and_rolls_back_ddl(engine):
    assert inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "20260808_0097"
        )
    before = _surface_counts(engine)
    before_catalog = _catalog_state(engine)
    job_ref = f"media_job_{uuid4().hex}"
    idempotency = sha256_bytes(uuid4().hex.encode())
    writer = engine.connect()
    transaction = writer.begin()
    try:
        writer.execute(text("SET LOCAL session_replication_role = replica"))
        writer.execute(
            text(_legacy_job_copy_statement()),
            {"job_ref": job_ref, "idempotency": idempotency},
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            migration = executor.submit(_migrate, "upgrade", "20260809_0098")
            with pytest.raises(FuturesTimeoutError):
                migration.result(timeout=0.25)
            transaction.commit()
            with pytest.raises(RuntimeError, match="0098 upgrade blocked"):
                migration.result(timeout=10)
    finally:
        if transaction.is_active:
            transaction.rollback()
        writer.close()

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "20260808_0097"
        )
    assert "media_job_result_receipts" not in inspect(engine).get_table_names()
    assert "byte_size" not in {
        column["name"] for column in inspect(engine).get_columns("evidence_records")
    }
    assert _catalog_state(engine) == before_catalog
    assert _surface_counts(engine)[0] == before[0] + 1
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        connection.execute(
            text("DELETE FROM media_jobs WHERE job_ref=:job_ref"),
            {"job_ref": job_ref},
        )
    assert _surface_counts(engine) == before


def test_100a_upgrade_lock_blocks_old_writer_until_0098_conservation(engine):
    with Session(engine) as session:
        template = session.scalar(select(MediaJobRow).order_by(MediaJobRow.created_at))
        assert template is not None
        template_values = {
            "tenant_ref": template.tenant_ref,
            "entity_ref": template.entity_ref,
            "store_ref": template.store_ref,
            "authority": template.scope_grant_authority_sha256,
            "actor": template.subject_actor_id,
        }
    suffix = uuid4().hex
    job_ref = f"media_job_{suffix}"
    evidence_id = f"evd_{suffix}"
    idempotency = sha256_bytes(f"upgrade-first-{suffix}".encode())
    request = _request(
        idempotency,
        tool_name="media.video_render",
        provider="ffmpeg",
        connector_ref="ffmpeg-local",
    )
    request_bytes = canonical_json(request)
    request_sha256 = sha256_bytes(request_bytes)
    scope_payload = {
        "tenant_ref": template_values["tenant_ref"],
        "entity_ref": template_values["entity_ref"],
        "store_ref": template_values["store_ref"],
        "authority_sha256": template_values["authority"],
        "subject_actor_id": template_values["actor"],
    }
    scope_binding = sha256_bytes(canonical_json(scope_payload))
    fingerprint = sha256_bytes(
        canonical_json({"scope": scope_payload, "request": request})
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO evidence_blobs "
                "(sha256,byte_size,content_bytes,created_at) "
                "VALUES (:sha,:size,:content,:created_at)"
            ),
            {
                "sha": request_sha256,
                "size": len(request_bytes),
                "content": request_bytes,
                "created_at": NOW,
            },
        )
        connection.execute(
            text(
                "INSERT INTO evidence_records "
                "(id,blob_sha256,filename,content_type,source,source_ref,grade,"
                "effective_at,effective_until,recorded_at,created_by,metadata_json) "
                "VALUES (:id,:sha,'media-job-request.json','application/json',"
                "'governed-media-job-request',:source_ref,'B',:recorded_at,NULL,"
                ":recorded_at,:actor,CAST(:metadata AS jsonb))"
            ),
            {
                "id": evidence_id,
                "sha": request_sha256,
                "source_ref": f"media-job://{scope_binding}/{idempotency}/request",
                "recorded_at": NOW,
                "actor": template_values["actor"],
                "metadata": json.dumps(
                    {
                        "contract_id": "kjds-governed-media-job-request-v1",
                        "media_job_request_fingerprint_sha256": fingerprint,
                        "tenant_ref": scope_payload["tenant_ref"],
                        "entity_ref": scope_payload["entity_ref"],
                        "store_ref": scope_payload["store_ref"],
                        "scope_grant_authority_sha256": scope_payload[
                            "authority_sha256"
                        ],
                        "subject_actor_id": scope_payload["subject_actor_id"],
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            },
        )
    blocker = engine.connect()
    blocker_tx = blocker.begin()
    blocker.execute(text("LOCK TABLE media_job_evidence_links IN ACCESS EXCLUSIVE MODE"))

    def old_writer() -> None:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO media_jobs ("
                    "job_ref,tenant_ref,entity_ref,store_ref,"
                    "scope_grant_authority_sha256,subject_actor_id,tool_name,"
                    "tool_version,project_ref,brief_ref,provider,connector_ref,"
                    "connector_binding_sha256,idempotency_sha256,request_sha256,"
                    "request_fingerprint_sha256,request_evidence_id,"
                    "request_evidence_sha256,created_at) VALUES ("
                    ":job_ref,:tenant_ref,:entity_ref,:store_ref,:authority,:actor,"
                    "'media.video_render','v1','project-media-pg','brief-media-pg',"
                    "'ffmpeg','ffmpeg-local',:binding,:idempotency,:request_sha,"
                    ":fingerprint,:evidence_id,:request_sha,:created_at)"
                ),
                {
                    "job_ref": job_ref,
                    **template_values,
                    "binding": BINDING,
                    "idempotency": idempotency,
                    "request_sha": request_sha256,
                    "fingerprint": fingerprint,
                    "evidence_id": evidence_id,
                    "created_at": NOW,
                },
            )

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            migration = executor.submit(_migrate, "upgrade", "20260809_0098")
            _wait_for_migration_table_locks(engine, "evidence_records", "media_jobs")
            writer = executor.submit(old_writer)
            with pytest.raises(FuturesTimeoutError):
                writer.result(timeout=0.25)
            blocker_tx.commit()
            migration.result(timeout=10)
            with pytest.raises(DBAPIError) as error:
                writer.result(timeout=10)
            assert _sqlstate(error.value) == "23514"
    finally:
        if blocker_tx.is_active:
            blocker_tx.rollback()
        blocker.close()

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "20260809_0098"
        )
        assert connection.scalar(
            text("SELECT count(*) FROM media_jobs WHERE job_ref=:job_ref"),
            {"job_ref": job_ref},
        ) == 0
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        connection.execute(
            text("DELETE FROM evidence_records WHERE id=:id"), {"id": evidence_id}
        )
        connection.execute(
            text("DELETE FROM evidence_blobs WHERE sha256=:sha"),
            {"sha": request_sha256},
        )
    _migrate("downgrade", "20260808_0097")


def test_100aa_real_submit_first_blocks_upgrade_without_deadlock(
    engine, monkeypatch
):
    before_catalog = _catalog_state(engine)
    original = GovernedMediaJobWorkspace._lock_schema_transition_in_session
    entered = Event()
    release_writer = Event()

    def gated(session):
        original(session)
        entered.set()
        assert release_writer.wait(10)

    monkeypatch.setattr(
        GovernedMediaJobWorkspace,
        "_lock_schema_transition_in_session",
        staticmethod(gated),
    )
    service = _workspace(engine, tick=68)
    suffix = uuid4().hex
    principal = _principal(f"actor-upgrade-writer-{suffix}", f"tenant-{suffix}")
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            writer = executor.submit(
                service.submit,
                principal=principal,
                store_ref="store-media-pg",
                request=_request(sha256_bytes(f"writer-first-{suffix}".encode())),
            )
            assert entered.wait(5)
            migration = executor.submit(_migrate, "upgrade", "20260809_0098")
            _wait_for_schema_transition_advisory(
                engine, mode="ExclusiveLock", granted=False
            )
            with pytest.raises(FuturesTimeoutError):
                migration.result(timeout=0.25)
            release_writer.set()
            submitted = writer.result(timeout=10)
            migration.result(timeout=10)
    finally:
        release_writer.set()
        monkeypatch.setattr(
            GovernedMediaJobWorkspace,
            "_lock_schema_transition_in_session",
            staticmethod(original),
        )

    assert submitted.state == "QUEUED"
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "20260809_0098"
        )
        assert connection.scalar(
            text("SELECT count(*) FROM media_jobs WHERE job_ref=:job_ref"),
            {"job_ref": submitted.job_ref},
        ) == 1
    assert _catalog_state(engine) != before_catalog
    _migrate("downgrade", "20260808_0097")


def test_100ab_real_upgrade_first_blocks_submit_until_new_schema_commits(engine):
    before_catalog = _catalog_state(engine)
    blocker = engine.connect()
    blocker_tx = blocker.begin()
    blocker.execute(text("LOCK TABLE evidence_records IN ACCESS EXCLUSIVE MODE"))
    service = _workspace(engine, tick=69)
    suffix = uuid4().hex
    principal = _principal(f"actor-upgrade-first-{suffix}", f"tenant-{suffix}")
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            migration = executor.submit(_migrate, "upgrade", "20260809_0098")
            _wait_for_schema_transition_advisory(
                engine, mode="ExclusiveLock", granted=True
            )
            writer = executor.submit(
                service.submit,
                principal=principal,
                store_ref="store-media-pg",
                request=_request(sha256_bytes(f"migration-first-{suffix}".encode())),
            )
            _wait_for_schema_transition_advisory(
                engine, mode="ShareLock", granted=False
            )
            with pytest.raises(FuturesTimeoutError):
                writer.result(timeout=0.25)
            blocker_tx.commit()
            migration.result(timeout=10)
            submitted = writer.result(timeout=10)
    finally:
        if blocker_tx.is_active:
            blocker_tx.rollback()
        blocker.close()

    assert submitted.state == "QUEUED"
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "20260809_0098"
        )
        assert connection.scalar(
            text("SELECT count(*) FROM media_jobs WHERE job_ref=:job_ref"),
            {"job_ref": submitted.job_ref},
        ) == 1
    assert _catalog_state(engine) != before_catalog
    _migrate("downgrade", "20260808_0097")


def _result_count(engine) -> int:
    if MediaJobResultReceiptRow.__tablename__ not in set(
        inspect(engine).get_table_names()
    ):
        return 0
    with Session(engine) as session:
        return int(session.scalar(select(func.count()).select_from(MediaJobResultReceiptRow)) or 0)


def test_100_empty_0097_to_0098_replay_and_schema(engine):
    migration_source = RESULT_MIGRATION.read_text(encoding="utf-8")
    assert (
        "LOCK TABLE {quoted_schema}.evidence_records, "
        in migration_source
    )
    assert (
        "{quoted_schema}.media_jobs IN SHARE ROW EXCLUSIVE MODE"
        in migration_source
    )
    assert (
        "{quoted_schema}.media_job_result_receipts, "
        in migration_source
    )
    assert "byte_size" not in {
        column["name"] for column in inspect(engine).get_columns("evidence_records")
    }
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "20260808_0097"
        )
    _migrate("upgrade", "20260809_0098")
    inspector = inspect(engine)
    assert "media_job_result_receipts" in inspector.get_table_names()
    assert "media_job_worker_inputs" in inspector.get_table_names()
    byte_size_column = next(
        column
        for column in inspector.get_columns("evidence_records")
        if column["name"] == "byte_size"
    )
    assert str(byte_size_column["type"]).upper() == "INTEGER"
    assert byte_size_column["nullable"] is True
    with engine.connect() as connection:
        triggers = set(
            connection.scalars(
                text(
                    "SELECT tgname FROM pg_trigger t "
                    "JOIN pg_class c ON c.oid=t.tgrelid "
                    "WHERE NOT t.tgisinternal AND c.relname='media_job_result_receipts'"
                )
            )
        )
        assert triggers == {
            "trg_media_job_result_receipt_immutable",
            "trg_media_job_result_receipt_validate",
        }
        worker_triggers = set(
            connection.scalars(
                text(
                    "SELECT tgname FROM pg_trigger t "
                    "JOIN pg_class c ON c.oid=t.tgrelid "
                    "WHERE NOT t.tgisinternal AND "
                    "c.relname='media_job_worker_inputs'"
                )
            )
        )
        assert worker_triggers == {
            "trg_media_job_analysis_link_conserved",
            "trg_media_job_worker_input_immutable",
            "trg_media_job_worker_input_validate",
        }
        event_triggers = set(
            connection.scalars(
                text(
                    "SELECT tgname FROM pg_trigger t "
                    "JOIN pg_class c ON c.oid=t.tgrelid "
                    "WHERE NOT t.tgisinternal AND c.relname='media_job_events'"
                )
            )
        )
        assert "trg_media_job_result_terminal_conserved" in event_triggers
        byte_size_function = str(
            connection.scalar(
                text(
                    "SELECT pg_get_functiondef("
                    "'public.kjds_evidence_record_fill_byte_size()'::regprocedure)"
                )
            )
        ).lower()
        assert "set search_path to 'pg_catalog'" in byte_size_function
        assert "from public.evidence_blobs" in byte_size_function
        byte_size_trigger_function_schema = connection.scalar(
            text(
                "SELECT n.nspname FROM pg_trigger t "
                "JOIN pg_class c ON c.oid=t.tgrelid "
                "JOIN pg_proc p ON p.oid=t.tgfoid "
                "JOIN pg_namespace n ON n.oid=p.pronamespace "
                "WHERE c.relname='evidence_records' "
                "AND t.tgname='trg_evidence_record_fill_byte_size'"
            )
        )
        assert byte_size_trigger_function_schema == "public"
    _migrate("downgrade", "20260808_0097")
    assert "media_job_result_receipts" not in inspect(engine).get_table_names()
    assert "media_job_worker_inputs" not in inspect(engine).get_table_names()
    assert "byte_size" not in {
        column["name"] for column in inspect(engine).get_columns("evidence_records")
    }
    _migrate("upgrade", "20260809_0098")
    byte_size_column = next(
        column
        for column in inspect(engine).get_columns("evidence_records")
        if column["name"] == "byte_size"
    )
    assert str(byte_size_column["type"]).upper() == "INTEGER"
    assert byte_size_column["nullable"] is True


def test_100b_worker_input_is_reserved_exact_and_immutable(engine):
    suffix = uuid4().hex
    principal = _principal(f"actor-worker-{suffix}", f"tenant-worker-{suffix}")
    service = _workspace(engine, tick=70)
    prepared = _prepare_governed_render_job(
        engine,
        principal=principal,
        suffix=suffix,
        service=service,
    )
    created = prepared.job

    projection = service.read_worker_input(
        principal=principal,
        store_ref="store-media-pg",
        job_ref=created.job_ref,
    )
    assert projection.payload == prepared.worker_input
    with Session(engine) as session:
        assert session.scalar(
            select(func.count())
            .select_from(MediaJobWorkerInputRow)
            .where(MediaJobWorkerInputRow.job_ref == created.job_ref)
        ) == 1
    with pytest.raises(DBAPIError) as error, Session(engine) as session, session.begin():
        row = session.scalar(
            select(MediaJobWorkerInputRow).where(
                MediaJobWorkerInputRow.job_ref == created.job_ref
            )
        )
        assert row is not None
        row.tool_version = "drift"
        session.flush()
    assert _sqlstate(error.value) == "23514"


def test_100ba_blueprint_replay_revalidates_evidence_row_binding(engine):
    suffix = uuid4().hex
    principal = _principal(f"actor-replay-{suffix}", f"tenant-replay-{suffix}")
    service = _workspace(engine, tick=71)
    prepared = _prepare_governed_render_job(
        engine,
        principal=principal,
        suffix=suffix,
        service=service,
    )
    evidence_id = prepared.blueprint_evidence_id
    with Session(engine) as session:
        record = session.get(EvidenceRecordRow, evidence_id)
        assert record is not None
        original_metadata = dict(record.metadata_json)
    before = (_surface_counts(engine), _result_count(engine))
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        connection.execute(
            text(
                "UPDATE evidence_records SET metadata_json=CAST(:metadata AS jsonb) "
                "WHERE id=:evidence_id"
            ),
            {
                "evidence_id": evidence_id,
                "metadata": json.dumps(
                    {**original_metadata, "subject_actor_id": "foreign-actor"},
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            },
        )
    try:
        with pytest.raises(
            ValueError, match="media_job_result_blueprint_evidence_invalid"
        ):
            service.record_blueprint_result(
                principal=principal,
                store_ref="store-media-pg",
                job_ref=prepared.blueprint["job_ref"],
                blueprint=prepared.blueprint,
                render_plan_sha256=prepared.render_plan_sha256,
            )
        assert (_surface_counts(engine), _result_count(engine)) == before
    finally:
        with engine.begin() as connection:
            connection.execute(text("SET LOCAL session_replication_role = replica"))
            connection.execute(
                text(
                    "UPDATE evidence_records SET metadata_json=CAST(:metadata AS jsonb) "
                    "WHERE id=:evidence_id"
                ),
                {
                    "evidence_id": evidence_id,
                    "metadata": json.dumps(
                        original_metadata, separators=(",", ":"), sort_keys=True
                    ),
                },
            )


@pytest.mark.parametrize(
    "case",
    [
        "analysis_observed_at",
        "analysis_noncanonical_bytes",
        "blueprint_noncanonical_bytes",
        "input_artifact_omitted",
        "input_artifact_role",
        "source_snapshot",
        "duplicate_scene_id",
        "invalid_scene_id",
        "caption_missing",
        "subtitle_missing",
        "audio_binding",
        "scope_numeric_tenant_ref",
        "scope_numeric_entity_ref",
        "scope_numeric_store_ref",
        "scope_numeric_authority_sha256",
        "scope_numeric_subject_actor_id",
    ],
)
def test_100bb_jointly_resealed_blueprint_provenance_is_23514_and_atomic(
    engine,
    case,
):
    suffix = uuid4().hex
    principal = _principal(f"actor-blueprint-attack-{suffix}", f"tenant-{suffix}")
    service = _workspace(engine, tick=72)
    prepared = _prepare_governed_render_job(
        engine,
        principal=principal,
        suffix=suffix,
        service=service,
    )
    before = (_surface_counts(engine), _result_count(engine))
    with pytest.raises(DBAPIError) as error:
        _invoke_jointly_resealed_blueprint_attack(
            engine,
            prepared=prepared,
            case=case,
        )
    assert _sqlstate(error.value) == "23514"
    if case.startswith("scope_numeric_"):
        assert "governed blueprint scope scalar shape invalid" in str(error.value)
        assert "kjds_media_job_validate_blueprint_provenance" in str(error.value)
    assert (_surface_counts(engine), _result_count(engine)) == before


def test_100c_terminal_without_result_receipt_rolls_back_all_terminal_residue(engine):
    suffix = uuid4().hex
    principal = _principal(f"actor-terminal-{suffix}", f"tenant-terminal-{suffix}")
    service = _workspace(engine, tick=75)
    prepared = _prepare_governed_render_job(
        engine,
        principal=principal,
        suffix=suffix,
        service=service,
    )
    created = prepared.job
    _, claimed = service.claim_provider_attempt(
        principal=principal,
        store_ref="store-media-pg",
        job_ref=created.job_ref,
    )
    assert claimed is True
    before = (_surface_counts(engine), _result_count(engine))

    with pytest.raises(
        PermissionError,
        match="media_job_provider_terminal_authority_required",
    ):
        service.record_provider_terminal(
            principal=principal,
            store_ref="store-media-pg",
            job_ref=created.job_ref,
            state="FAILED",
        )

    assert (_surface_counts(engine), _result_count(engine)) == before
    assert service.read(
        principal=principal,
        store_ref="store-media-pg",
        job_ref=created.job_ref,
    ).state == "DISPATCHED"


@pytest.mark.parametrize(
    ("state", "result_kind"),
    (("FAILED", "provider_failure"), ("UNKNOWN_OUTCOME", "unknown_outcome_readback")),
)
def test_100ca_joint_non_success_terminal_and_receipt_is_23514_and_atomic(
    engine,
    state,
    result_kind,
):
    suffix = uuid4().hex
    principal = _principal(f"actor-non-success-{suffix}", f"tenant-{suffix}")
    service = _workspace(engine, tick=76)
    prepared = _prepare_governed_render_job(
        engine,
        principal=principal,
        suffix=suffix,
        service=service,
    )
    claimed, created_attempt = service.claim_provider_attempt(
        principal=principal,
        store_ref="store-media-pg",
        job_ref=prepared.job.job_ref,
    )
    assert created_attempt is True and claimed.state == "DISPATCHED"
    before = (_surface_counts(engine), _result_count(engine))

    with pytest.raises(DBAPIError) as error, Session(engine) as session, session.begin():
        scope = service.current_scope(
            principal=principal,
            store_ref="store-media-pg",
        )
        job = session.get(MediaJobRow, prepared.job.job_ref)
        assert job is not None
        event = service._append_provider_terminal_in_session(
            session=session,
            scope=scope,
            job=job,
            state=state,
        )
        content = {
            "contract_id": "kjds-governed-media-job-result-v1",
            "provider": job.provider,
            "connector_ref": job.connector_ref,
            "connector_binding_sha256": job.connector_binding_sha256,
            "result_kind": result_kind,
            "artifact_evidence_refs": [],
            "content_asset_ref": None,
            "event_ref": event.event_ref,
            "event_sha256": event.event_sha256,
            "job_ref": job.job_ref,
            "state": state,
        }
        session.add(
            MediaJobResultReceiptRow(
                receipt_ref=f"media_result_{uuid4().hex}",
                job_ref=job.job_ref,
                event_ref=event.event_ref,
                tenant_ref=job.tenant_ref,
                entity_ref=job.entity_ref,
                store_ref=job.store_ref,
                scope_grant_authority_sha256=job.scope_grant_authority_sha256,
                tool_name=job.tool_name,
                tool_version=job.tool_version,
                provider=job.provider,
                connector_ref=job.connector_ref,
                connector_binding_sha256=job.connector_binding_sha256,
                state=state,
                result_kind=result_kind,
                artifact_evidence_refs=[],
                content_asset_ref=None,
                receipt_sha256=sha256_bytes(canonical_json(content)),
                recorded_at=event.recorded_at,
            )
        )
        session.flush()

    assert _sqlstate(error.value) == "23514"
    assert "media-job non-success result authority not admitted" in str(error.value)
    assert (_surface_counts(engine), _result_count(engine)) == before


@pytest.mark.parametrize(
    "case",
    (
        "outputs_scalar",
        "artifact_metadata_scalar",
        "generation_executor_number",
        "generation_receipt_number",
        "generation_execution_number",
        "generation_listing_string",
        "generation_listing_number",
        "outputs_value_number",
        "outputs_value_bool",
        "artifact_metadata_value_number",
        "artifact_metadata_value_bool",
    ),
)
def test_100cb_result_json_scalars_are_23514_and_atomic(engine, monkeypatch, case):
    suffix = uuid4().hex
    principal = _principal(f"actor-result-shape-{suffix}", f"tenant-{suffix}")
    service = _workspace(engine, tick=77)
    prepared = _prepare_governed_render_job(
        engine,
        principal=principal,
        suffix=suffix,
        service=service,
    )
    claimed, created_attempt = service.claim_provider_attempt(
        principal=principal,
        store_ref="store-media-pg",
        job_ref=prepared.job.job_ref,
    )
    assert created_attempt is True
    writer, _ = _atomic_artifact_writer(
        engine,
        principal=principal,
        prepared=prepared,
        suffix=suffix,
        result_shape_attack=case,
    )
    monkeypatch.setattr(service, "_validate_result_bindings", lambda **_: None)
    if case == "generation_receipt_number":
        monkeypatch.setattr(
            service,
            "_bind_result_receipt_to_content_asset",
            lambda **_: None,
        )
    before = (_surface_counts(engine), _result_count(engine))

    with pytest.raises(DBAPIError) as error:
        service.record_render_result(
            principal=principal,
            store_ref="store-media-pg",
            job_ref=prepared.job.job_ref,
            expected_event_ordinal=claimed.last_event_ordinal,
            expected_recorded_at=claimed.state_recorded_at,
            artifact_writer=writer,
        )

    assert _sqlstate(error.value) == "23514"
    assert "kjds_media_job_validate_result_receipt" in str(error.value)
    assert (_surface_counts(engine), _result_count(engine)) == before


def test_101_result_receipt_evidence_binding_and_trigger_rejects_forgery(engine):
    suffix = uuid4().hex
    tenant = f"tenant-result-{suffix}"
    principal = _principal(f"actor-result-{suffix}", tenant)
    service = _workspace(engine, tick=80)
    prepared = _prepare_governed_render_job(
        engine,
        principal=principal,
        suffix=suffix,
        service=service,
    )
    created = prepared.job
    claimed, created_attempt = service.claim_provider_attempt(
        principal=principal,
        store_ref="store-media-pg",
        job_ref=created.job_ref,
    )
    assert created_attempt is True
    assert claimed.state == "DISPATCHED"
    with Session(engine, expire_on_commit=False) as session:
        job = session.get(MediaJobRow, created.job_ref)
        assert job is not None
    writer, asset_ref = _atomic_artifact_writer(
        engine,
        principal=principal,
        prepared=prepared,
        suffix=suffix,
    )
    first = service.record_render_result(
        principal=principal,
        store_ref="store-media-pg",
        job_ref=created.job_ref,
        expected_event_ordinal=claimed.last_event_ordinal,
        expected_recorded_at=claimed.state_recorded_at,
        artifact_writer=writer,
    )
    assert first.state == "SUCCEEDED"
    with Session(engine) as session:
        event = session.get(MediaJobEventRow, first.event_ref)
        asset = session.get(ContentAssetRow, asset_ref)
        artifact = session.get(EvidenceRecordRow, first.artifact_evidence_refs[0])
        assert event is not None
        assert asset is not None
        assert artifact is not None
        assert asset.generation_json["result_receipt_sha256"] == first.receipt_sha256
    content = {
        "contract_id": "kjds-governed-media-job-result-v1",
        "provider": job.provider,
        "connector_ref": job.connector_ref,
        "connector_binding_sha256": job.connector_binding_sha256,
        "result_kind": "video_artifact_evidence",
        "artifact_evidence_refs": [artifact.id],
        "content_asset_ref": asset_ref,
        "event_ref": event.event_ref,
        "event_sha256": event.event_sha256,
        "job_ref": job.job_ref,
        "state": "SUCCEEDED",
    }
    product_id = prepared.product_id
    forged_asset_ref = f"content-asset-forged-{suffix}"
    forged_evidence_ref = f"evidence-forged-{suffix}"
    forged_content = {
        **content,
        "artifact_evidence_refs": [forged_evidence_ref],
        "content_asset_ref": forged_asset_ref,
    }
    forged_receipt_sha256 = sha256_bytes(canonical_json(forged_content))
    with Session(engine) as session, session.begin():
        session.add(
            ContentAssetRow(
                id=forged_asset_ref,
                product_id=product_id,
                content_type="video",
                locale="ru-RU",
                channel="ozon",
                brief_json={},
                source_facts_json={},
                status="generated",
                artifact_ref=forged_evidence_ref,
                qa_results_json=[],
                generation_json={
                    "executor": "ffmpeg",
                    "execution_id": f"forged-execution-{suffix}",
                    "media_job_ref": job.job_ref,
                    "result_receipt_sha256": forged_receipt_sha256,
                    "outputs": {"9:16": forged_evidence_ref},
                },
                created_at=NOW,
            )
        )
    before = _result_count(engine)
    invalid_cases = (
        {
            "name": "seal",
            "state": "SUCCEEDED",
            "result_kind": "video_artifact_evidence",
            "artifact_evidence_refs": [artifact.id],
            "content_asset_ref": asset_ref,
            "receipt_sha256": "0" * 64,
        },
        {
            "name": "event-state",
            "state": "FAILED",
            "result_kind": "provider_failure",
            "artifact_evidence_refs": [],
            "content_asset_ref": None,
            "receipt_sha256": sha256_bytes(
                canonical_json(
                    {
                        **content,
                        "state": "FAILED",
                        "result_kind": "provider_failure",
                        "artifact_evidence_refs": [],
                        "content_asset_ref": None,
                    }
                )
            ),
        },
        {
            "name": "content-asset",
            "state": "SUCCEEDED",
            "result_kind": "video_artifact_evidence",
            "artifact_evidence_refs": [artifact.id],
            "content_asset_ref": None,
            "receipt_sha256": sha256_bytes(
                canonical_json({**content, "content_asset_ref": None})
            ),
        },
        {
            "name": "artifact-evidence",
            "state": "SUCCEEDED",
            "result_kind": "video_artifact_evidence",
            "artifact_evidence_refs": [forged_evidence_ref],
            "content_asset_ref": forged_asset_ref,
            "receipt_sha256": forged_receipt_sha256,
        },
        {
            "name": "artifact-refs-object",
            "state": "SUCCEEDED",
            "result_kind": "video_artifact_evidence",
            "artifact_evidence_refs": {"artifact": artifact.id},
            "content_asset_ref": asset_ref,
            "receipt_sha256": sha256_bytes(
                canonical_json(
                    {
                        **content,
                        "artifact_evidence_refs": {"artifact": artifact.id},
                    }
                )
            ),
        },
        {
            "name": "artifact-refs-scalar",
            "state": "SUCCEEDED",
            "result_kind": "video_artifact_evidence",
            "artifact_evidence_refs": "artifact-ref-scalar",
            "content_asset_ref": asset_ref,
            "receipt_sha256": sha256_bytes(
                canonical_json(
                    {
                        **content,
                        "artifact_evidence_refs": "artifact-ref-scalar",
                    }
                )
            ),
        },
    )
    surface_before = _surface_counts(engine)
    for case in invalid_cases:
        with pytest.raises(DBAPIError) as error, Session(engine) as session, session.begin():
            session.add(
                MediaJobResultReceiptRow(
                    receipt_ref=f"media_result_{uuid4().hex}",
                    job_ref=job.job_ref,
                    event_ref=event.event_ref,
                    tenant_ref=job.tenant_ref,
                    entity_ref=job.entity_ref,
                    store_ref=job.store_ref,
                    scope_grant_authority_sha256=job.scope_grant_authority_sha256,
                    tool_name=job.tool_name,
                    tool_version=job.tool_version,
                    provider=job.provider,
                    connector_ref=job.connector_ref,
                    connector_binding_sha256=job.connector_binding_sha256,
                    state=case["state"],
                    result_kind=case["result_kind"],
                    artifact_evidence_refs=case["artifact_evidence_refs"],
                    content_asset_ref=case["content_asset_ref"],
                    receipt_sha256=case["receipt_sha256"],
                    recorded_at=event.recorded_at,
                )
            )
        assert _sqlstate(error.value) == "23514"
        if case["name"].startswith("artifact-refs-"):
            assert "media-job result Evidence refs must be an array" in str(
                error.value
            )
        assert _result_count(engine) == before
        assert _surface_counts(engine) == surface_before


def test_101b_rotation_wins_before_atomic_result_and_leaves_zero_artifact(engine):
    suffix = uuid4().hex
    tenant = f"tenant-result-rotation-{suffix}"
    principal = _principal(f"actor-result-rotation-{suffix}", tenant)
    service = _authority_workspace(engine, principal)
    prepared = _prepare_governed_render_job(
        engine,
        principal=principal,
        suffix=suffix,
        service=service,
    )
    claimed, created_attempt = service.claim_provider_attempt(
        principal=principal,
        store_ref="store-media-pg",
        job_ref=prepared.job.job_ref,
    )
    assert created_attempt is True
    writer, asset_ref = _atomic_artifact_writer(
        engine,
        principal=principal,
        prepared=prepared,
        suffix=suffix,
    )
    evidence = _capture_rotation_evidence(engine, suffix)
    before = (_surface_counts(engine), _result_count(engine))
    rotation_started = Event()
    rotation_acquired = Event()
    release_rotation = Event()

    with ThreadPoolExecutor(max_workers=2) as executor:
        rotation = executor.submit(
            _hold_revoke,
            engine,
            principal,
            evidence,
            rotation_started,
            rotation_acquired,
            release_rotation,
        )
        assert rotation_acquired.wait(timeout=10)
        result = executor.submit(
            service.record_render_result,
            principal=principal,
            store_ref="store-media-pg",
            job_ref=prepared.job.job_ref,
            expected_event_ordinal=claimed.last_event_ordinal,
            expected_recorded_at=claimed.state_recorded_at,
            artifact_writer=writer,
        )
        with pytest.raises(FuturesTimeoutError):
            result.result(timeout=0.25)
        release_rotation.set()
        rotation.result(timeout=10)
        with pytest.raises(PermissionError, match="scope_authority_not_current"):
            result.result(timeout=10)

    assert (_surface_counts(engine), _result_count(engine)) == before
    with Session(engine) as session:
        asset = session.get(ContentAssetRow, asset_ref)
        latest = session.scalar(
            select(MediaJobEventRow)
            .where(MediaJobEventRow.job_ref == prepared.job.job_ref)
            .order_by(MediaJobEventRow.ordinal.desc())
        )
        assert asset is None
        assert latest is not None
        assert latest.state == "DISPATCHED"


def test_101c_atomic_result_lock_blocks_rotation_until_asset_and_receipt_commit(
    engine,
):
    suffix = uuid4().hex
    tenant = f"tenant-result-first-{suffix}"
    principal = _principal(f"actor-result-first-{suffix}", tenant)
    service = _authority_workspace(engine, principal)
    prepared = _prepare_governed_render_job(
        engine,
        principal=principal,
        suffix=suffix,
        service=service,
    )
    claimed, created_attempt = service.claim_provider_attempt(
        principal=principal,
        store_ref="store-media-pg",
        job_ref=prepared.job.job_ref,
    )
    assert created_attempt is True
    evidence = _capture_rotation_evidence(engine, suffix)
    result_at_terminal = Event()
    allow_result = Event()
    rotation_started = Event()
    rotation_acquired = Event()
    release_rotation = Event()
    def pause_after_artifact_flush():
        result_at_terminal.set()
        assert allow_result.wait(timeout=10)
    writer, asset_ref = _atomic_artifact_writer(
        engine,
        principal=principal,
        prepared=prepared,
        suffix=suffix,
        after_flush=pause_after_artifact_flush,
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        result = executor.submit(
            service.record_render_result,
            principal=principal,
            store_ref="store-media-pg",
            job_ref=prepared.job.job_ref,
            expected_event_ordinal=claimed.last_event_ordinal,
            expected_recorded_at=claimed.state_recorded_at,
            artifact_writer=writer,
        )
        assert result_at_terminal.wait(timeout=10)
        rotation = executor.submit(
            _hold_revoke,
            engine,
            principal,
            evidence,
            rotation_started,
            rotation_acquired,
            release_rotation,
        )
        assert rotation_started.wait(timeout=10)
        assert not rotation_acquired.wait(timeout=0.25)
        allow_result.set()
        receipt = result.result(timeout=10)
        assert receipt.state == "SUCCEEDED"
        assert rotation_acquired.wait(timeout=10)
        release_rotation.set()
        rotation.result(timeout=10)

    with Session(engine) as session:
        asset = session.get(ContentAssetRow, asset_ref)
        assert asset is not None
        assert asset.generation_json["result_receipt_sha256"] == receipt.receipt_sha256
        assert session.scalar(
            select(func.count())
            .select_from(MediaJobResultReceiptRow)
            .where(MediaJobResultReceiptRow.job_ref == prepared.job.job_ref)
        ) == 1


@pytest.mark.parametrize("fail_stage", ["artifact_evidence", "terminal_event"])
def test_101d_atomic_result_failure_rolls_back_every_result_domain(
    engine,
    monkeypatch,
    fail_stage,
):
    suffix = uuid4().hex
    principal = _principal(f"actor-result-rollback-{suffix}", f"tenant-{suffix}")
    service = _workspace(engine, tick=92)
    prepared = _prepare_governed_render_job(
        engine,
        principal=principal,
        suffix=suffix,
        service=service,
    )
    claimed, created_attempt = service.claim_provider_attempt(
        principal=principal,
        store_ref="store-media-pg",
        job_ref=prepared.job.job_ref,
    )
    assert created_attempt is True
    writer, asset_ref = _atomic_artifact_writer(
        engine,
        principal=principal,
        prepared=prepared,
        suffix=suffix,
        fail_stage=("artifact_evidence" if fail_stage == "artifact_evidence" else None),
    )
    if fail_stage == "terminal_event":
        original = service._append_provider_terminal_in_session

        def append_then_fail(**kwargs):
            original(**kwargs)
            raise RuntimeError("injected_after_terminal_event")

        monkeypatch.setattr(
            service,
            "_append_provider_terminal_in_session",
            append_then_fail,
        )
    before = (_surface_counts(engine), _result_count(engine))
    with pytest.raises(RuntimeError, match="injected_after"):
        service.record_render_result(
            principal=principal,
            store_ref="store-media-pg",
            job_ref=prepared.job.job_ref,
            expected_event_ordinal=claimed.last_event_ordinal,
            expected_recorded_at=claimed.state_recorded_at,
            artifact_writer=writer,
        )
    assert (_surface_counts(engine), _result_count(engine)) == before
    with Session(engine) as session:
        assert session.get(ContentAssetRow, asset_ref) is None
    assert service.read(
        principal=principal,
        store_ref="store-media-pg",
        job_ref=prepared.job.job_ref,
    ).state == "DISPATCHED"


def test_101e_render_result_uses_trusted_completion_time_after_slow_render(engine):
    suffix = uuid4().hex
    principal = _principal(f"actor-completion-{suffix}", f"tenant-{suffix}")
    current = [NOW]
    service = GovernedMediaJobWorkspace(
        engine,
        evidence=EvidenceService(engine),
        authority=_ScopeAuthority(),
        content_assets=_DatabaseContentAssetAuthority(engine),
        clock=lambda: current[0],
    )
    prepared = _prepare_governed_render_job(
        engine,
        principal=principal,
        suffix=suffix,
        service=service,
    )
    claimed, created_attempt = service.claim_provider_attempt(
        principal=principal,
        store_ref="store-media-pg",
        job_ref=prepared.job.job_ref,
    )
    assert created_attempt is True
    current[0] += timedelta(minutes=5)
    writer, asset_ref = _atomic_artifact_writer(
        engine,
        principal=principal,
        prepared=prepared,
        suffix=suffix,
    )
    receipt = service.record_render_result(
        principal=principal,
        store_ref="store-media-pg",
        job_ref=prepared.job.job_ref,
        expected_event_ordinal=claimed.last_event_ordinal,
        expected_recorded_at=claimed.state_recorded_at,
        artifact_writer=writer,
    )
    with Session(engine) as session:
        asset = session.get(ContentAssetRow, asset_ref)
        artifact = session.get(EvidenceRecordRow, receipt.artifact_evidence_refs[0])
        event = session.get(MediaJobEventRow, receipt.event_ref)
        assert asset is not None and artifact is not None and event is not None
        assert asset.created_at == current[0]
        assert artifact.effective_at == current[0]
        assert artifact.recorded_at == current[0]
        assert event.occurred_at == current[0]
        assert event.recorded_at == current[0]


def test_101f_backdated_completion_fails_before_artifact_writer(engine):
    suffix = uuid4().hex
    principal = _principal(f"actor-backdated-{suffix}", f"tenant-{suffix}")
    current = [NOW + timedelta(seconds=200)]
    service = GovernedMediaJobWorkspace(
        engine,
        evidence=EvidenceService(engine),
        authority=_ScopeAuthority(),
        content_assets=_DatabaseContentAssetAuthority(engine),
        clock=lambda: current[0],
    )
    prepared = _prepare_governed_render_job(
        engine,
        principal=principal,
        suffix=suffix,
        service=service,
    )
    claimed, created_attempt = service.claim_provider_attempt(
        principal=principal,
        store_ref="store-media-pg",
        job_ref=prepared.job.job_ref,
    )
    assert created_attempt is True
    current[0] = NOW
    called = False

    def writer(session, scope, completion_now):
        nonlocal called
        called = True
        raise AssertionError((session, scope, completion_now))

    before = (_surface_counts(engine), _result_count(engine))
    with pytest.raises(ValueError, match="media_job_provider_completion_time_invalid"):
        service.record_render_result(
            principal=principal,
            store_ref="store-media-pg",
            job_ref=prepared.job.job_ref,
            expected_event_ordinal=claimed.last_event_ordinal,
            expected_recorded_at=claimed.state_recorded_at,
            artifact_writer=writer,
        )
    assert called is False
    assert (_surface_counts(engine), _result_count(engine)) == before


def _hold_exclusive_schema_transition(engine, acquired: Event, release: Event) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "SELECT pg_advisory_xact_lock("
                "hashtext('kjds-media-jobs-0098-result-readback'))"
            )
        )
        acquired.set()
        assert release.wait(10)


def test_101g_submit_and_schema_transition_advisory_lock_serialize_both_directions(
    engine, monkeypatch
):
    original = GovernedMediaJobWorkspace._lock_schema_transition_in_session
    entered = Event()
    release_writer = Event()

    def gated(session):
        original(session)
        entered.set()
        assert release_writer.wait(10)

    monkeypatch.setattr(
        GovernedMediaJobWorkspace,
        "_lock_schema_transition_in_session",
        staticmethod(gated),
    )
    service = _workspace(engine, tick=80)
    principal = _principal(f"actor-lock-{uuid4().hex}", f"tenant-{uuid4().hex}")
    request = _request(sha256_bytes(uuid4().bytes))
    with ThreadPoolExecutor(max_workers=2) as executor:
        writer = executor.submit(
            service.submit,
            principal=principal,
            store_ref="store-media-pg",
            request=request,
        )
        assert entered.wait(5)
        exclusive_acquired = Event()
        exclusive_release = Event()
        exclusive = executor.submit(
            _hold_exclusive_schema_transition,
            engine,
            exclusive_acquired,
            exclusive_release,
        )
        assert not exclusive_acquired.wait(0.25)
        release_writer.set()
        assert writer.result(timeout=10).state == "QUEUED"
        assert exclusive_acquired.wait(5)
        exclusive_release.set()
        exclusive.result(timeout=10)

    monkeypatch.setattr(
        GovernedMediaJobWorkspace,
        "_lock_schema_transition_in_session",
        staticmethod(original),
    )
    acquired = Event()
    release_migration = Event()
    with ThreadPoolExecutor(max_workers=2) as executor:
        exclusive = executor.submit(
            _hold_exclusive_schema_transition,
            engine,
            acquired,
            release_migration,
        )
        assert acquired.wait(5)
        writer = executor.submit(
            service.submit,
            principal=principal,
            store_ref="store-media-pg",
            request=_request(sha256_bytes(uuid4().bytes)),
        )
        with pytest.raises(FuturesTimeoutError):
            writer.result(timeout=0.25)
        release_migration.set()
        exclusive.result(timeout=10)
        assert writer.result(timeout=10).state == "QUEUED"


def test_101h_render_result_and_schema_transition_lock_serialize_both_directions(
    engine, monkeypatch
):
    def prepared_case(label: str):
        suffix = uuid4().hex
        principal = _principal(f"actor-lock-{label}-{suffix}", f"tenant-{suffix}")
        service = _workspace(engine, tick=82)
        prepared = _prepare_governed_render_job(
            engine, principal=principal, suffix=suffix, service=service
        )
        claimed, created = service.claim_provider_attempt(
            principal=principal,
            store_ref="store-media-pg",
            job_ref=prepared.job.job_ref,
        )
        assert created is True
        writer, _ = _atomic_artifact_writer(
            engine, principal=principal, prepared=prepared, suffix=suffix
        )
        return principal, service, prepared, claimed, writer

    first = prepared_case("writer-first")
    original = GovernedMediaJobWorkspace._lock_schema_transition_in_session
    entered = Event()
    release_writer = Event()

    def gated(session):
        original(session)
        entered.set()
        assert release_writer.wait(10)

    monkeypatch.setattr(
        GovernedMediaJobWorkspace,
        "_lock_schema_transition_in_session",
        staticmethod(gated),
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        result = executor.submit(
            first[1].record_render_result,
            principal=first[0],
            store_ref="store-media-pg",
            job_ref=first[2].job.job_ref,
            expected_event_ordinal=first[3].last_event_ordinal,
            expected_recorded_at=first[3].state_recorded_at,
            artifact_writer=first[4],
        )
        assert entered.wait(5)
        acquired = Event()
        release_exclusive = Event()
        exclusive = executor.submit(
            _hold_exclusive_schema_transition, engine, acquired, release_exclusive
        )
        assert not acquired.wait(0.25)
        release_writer.set()
        assert result.result(timeout=10).state == "SUCCEEDED"
        assert acquired.wait(5)
        release_exclusive.set()
        exclusive.result(timeout=10)

    monkeypatch.setattr(
        GovernedMediaJobWorkspace,
        "_lock_schema_transition_in_session",
        staticmethod(original),
    )
    second = prepared_case("migration-first")
    acquired = Event()
    release_exclusive = Event()
    with ThreadPoolExecutor(max_workers=2) as executor:
        exclusive = executor.submit(
            _hold_exclusive_schema_transition, engine, acquired, release_exclusive
        )
        assert acquired.wait(5)
        result = executor.submit(
            second[1].record_render_result,
            principal=second[0],
            store_ref="store-media-pg",
            job_ref=second[2].job.job_ref,
            expected_event_ordinal=second[3].last_event_ordinal,
            expected_recorded_at=second[3].state_recorded_at,
            artifact_writer=second[4],
        )
        with pytest.raises(FuturesTimeoutError):
            result.result(timeout=0.25)
        release_exclusive.set()
        exclusive.result(timeout=10)
        assert result.result(timeout=10).state == "SUCCEEDED"


def test_101i_real_render_result_first_blocks_downgrade_without_deadlock(
    engine, monkeypatch
):
    suffix = uuid4().hex
    principal = _principal(f"actor-real-result-first-{suffix}", f"tenant-{suffix}")
    service = _workspace(engine, tick=84)
    prepared = _prepare_governed_render_job(
        engine, principal=principal, suffix=suffix, service=service
    )
    claimed, created = service.claim_provider_attempt(
        principal=principal,
        store_ref="store-media-pg",
        job_ref=prepared.job.job_ref,
    )
    assert created is True
    writer, _ = _atomic_artifact_writer(
        engine, principal=principal, prepared=prepared, suffix=suffix
    )
    original = GovernedMediaJobWorkspace._lock_schema_transition_in_session
    entered = Event()
    release_writer = Event()

    def gated(session):
        original(session)
        entered.set()
        assert release_writer.wait(10)

    monkeypatch.setattr(
        GovernedMediaJobWorkspace,
        "_lock_schema_transition_in_session",
        staticmethod(gated),
    )
    before_catalog = _catalog_state(engine)
    before = (_surface_counts(engine), _result_count(engine))
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            result = executor.submit(
                service.record_render_result,
                principal=principal,
                store_ref="store-media-pg",
                job_ref=prepared.job.job_ref,
                expected_event_ordinal=claimed.last_event_ordinal,
                expected_recorded_at=claimed.state_recorded_at,
                artifact_writer=writer,
            )
            assert entered.wait(5)
            migration = executor.submit(_migrate, "downgrade", "20260808_0097")
            _wait_for_schema_transition_advisory(
                engine, mode="ExclusiveLock", granted=False
            )
            with pytest.raises(FuturesTimeoutError):
                migration.result(timeout=0.25)
            release_writer.set()
            assert result.result(timeout=10).state == "SUCCEEDED"
            with pytest.raises(BaseException) as error:
                migration.result(timeout=10)
            assert _sqlstate(error.value) == "55000"
    finally:
        release_writer.set()
        monkeypatch.setattr(
            GovernedMediaJobWorkspace,
            "_lock_schema_transition_in_session",
            staticmethod(original),
        )

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "20260809_0098"
        )
    assert _catalog_state(engine) == before_catalog
    after = (_surface_counts(engine), _result_count(engine))
    _assert_atomic_render_result_delta(before[0], after[0])
    assert after[1] == before[1] + 1


def test_101j_real_downgrade_first_blocks_render_result_then_fails_closed(engine):
    suffix = uuid4().hex
    principal = _principal(f"actor-real-downgrade-first-{suffix}", f"tenant-{suffix}")
    service = _workspace(engine, tick=85)
    prepared = _prepare_governed_render_job(
        engine, principal=principal, suffix=suffix, service=service
    )
    claimed, created = service.claim_provider_attempt(
        principal=principal,
        store_ref="store-media-pg",
        job_ref=prepared.job.job_ref,
    )
    assert created is True
    writer, _ = _atomic_artifact_writer(
        engine, principal=principal, prepared=prepared, suffix=suffix
    )
    before_catalog = _catalog_state(engine)
    before = (_surface_counts(engine), _result_count(engine))
    blocker = engine.connect()
    blocker_tx = blocker.begin()
    blocker.execute(text("LOCK TABLE media_jobs IN ACCESS EXCLUSIVE MODE"))
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            migration = executor.submit(_migrate, "downgrade", "20260808_0097")
            _wait_for_schema_transition_advisory(
                engine, mode="ExclusiveLock", granted=True
            )
            result = executor.submit(
                service.record_render_result,
                principal=principal,
                store_ref="store-media-pg",
                job_ref=prepared.job.job_ref,
                expected_event_ordinal=claimed.last_event_ordinal,
                expected_recorded_at=claimed.state_recorded_at,
                artifact_writer=writer,
            )
            _wait_for_schema_transition_advisory(
                engine, mode="ShareLock", granted=False
            )
            with pytest.raises(FuturesTimeoutError):
                result.result(timeout=0.25)
            blocker_tx.commit()
            with pytest.raises(BaseException) as error:
                migration.result(timeout=10)
            assert _sqlstate(error.value) == "55000"
            assert result.result(timeout=10).state == "SUCCEEDED"
    finally:
        if blocker_tx.is_active:
            blocker_tx.rollback()
        blocker.close()

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "20260809_0098"
        )
    assert _catalog_state(engine) == before_catalog
    after = (_surface_counts(engine), _result_count(engine))
    _assert_atomic_render_result_delta(before[0], after[0])
    assert after[1] == before[1] + 1


def test_102_populated_0098_downgrade_is_55000_and_preserves_receipts(engine):
    before = _result_count(engine)
    assert before > 0
    with pytest.raises(BaseException) as error:
        _migrate("downgrade", "20260808_0097")
    assert _sqlstate(error.value) == "55000"
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "20260809_0098"
        )
    assert _result_count(engine) == before
