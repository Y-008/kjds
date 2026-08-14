import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.editing_blueprint import (
    PROVIDER_ATTEMPT_STALE_AFTER,
    EditingBlueprintError,
    GovernedEditingBlueprintWorkspace,
    analysis_receipt_snapshot_sha256,
    source_snapshot_sha256,
)
from apps.control_plane.evidence import EvidenceRecordRow, EvidenceService
from apps.control_plane.media_connectors import (
    INTERNAL_BLUEPRINT_PROVIDER,
    MediaConnectorContract,
)
from apps.control_plane.media_jobs import (
    BLUEPRINT_COMPILER_CONNECTOR_BINDING_SHA256,
    BLUEPRINT_COMPILER_CONNECTOR_REF,
    BLUEPRINT_COMPILER_PROVIDER,
    EDITING_MAX_SCENE_DURATION_MS,
    GovernedMediaJobWorkspace,
    MediaJobBindingProjection,
    MediaJobEventRow,
    MediaJobProjection,
    MediaJobResultReceiptProjection,
    MediaJobResultReceiptRow,
    MediaJobRow,
    MediaJobScope,
    canonical_json,
    sha256_bytes,
)
from apps.control_plane.media_workbench import FfmpegMediaWorker
from apps.control_plane.security import Principal
from apps.control_plane.sql_repository import Base, ContentAssetRow

FIXTURE = Path(__file__).parent / "fixtures" / "media_agent" / "bas186_editing_blueprint_v1.json"
REGISTRY = Path(__file__).parents[1] / "docs" / "project" / "registries" / "editing_blueprint_contracts.json"
NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
BLUEPRINT_PROVIDER = MediaConnectorContract().internal_runtime_provider(
    INTERNAL_BLUEPRINT_PROVIDER
)
FFMPEG_PROVIDER_DESCRIPTOR = MediaConnectorContract().internal_runtime_provider("ffmpeg")
SCOPE = MediaJobScope(
    tenant_ref="tenant-bas186",
    entity_ref="entity-bas186",
    store_ref="store-bas186",
    authority_sha256="a" * 64,
    subject_actor_id="actor-bas186",
)
PRINCIPAL = Principal(
    actor_id=SCOPE.subject_actor_id,
    roles=frozenset({"operator"}),
    tenant_ref=SCOPE.tenant_ref,
    store_refs=frozenset({SCOPE.store_ref}),
)


class FakeJobs:
    def __init__(
        self,
        *,
        tool_name="media.video_blueprint",
        provider=None,
        state="QUEUED",
        state_recorded_at=NOW,
    ):
        self.scope = SCOPE
        provider = provider or (
            BLUEPRINT_COMPILER_PROVIDER
            if tool_name == "media.video_blueprint"
            else "ffmpeg"
        )
        connector_ref = (
            BLUEPRINT_COMPILER_CONNECTOR_REF
            if tool_name == "media.video_blueprint"
            else FFMPEG_PROVIDER_DESCRIPTOR.connector_ref
        )
        connector_binding = (
            BLUEPRINT_COMPILER_CONNECTOR_BINDING_SHA256
            if tool_name == "media.video_blueprint"
            else FFMPEG_PROVIDER_DESCRIPTOR.binding_sha256
        )
        self.job = MediaJobProjection(
            job_ref="media-job-bas186",
            state=state,
            tool_name=tool_name,
            connector_ref=connector_ref,
            created_at=NOW.isoformat(),
            last_event_ordinal=1,
            safe_reason_code=None,
            state_recorded_at=state_recorded_at.isoformat(),
        )
        self.binding = MediaJobBindingProjection(
            job_ref=self.job.job_ref,
            tool_name=tool_name,
            tool_version="1.0.0",
            provider=provider,
            connector_ref=self.job.connector_ref,
            connector_binding_sha256=connector_binding,
            tool_descriptor_sha256="c" * 64,
            campaign_brief_sha256="d" * 64,
            request_sha256="e" * 64,
        )
        self.receipt: MediaJobResultReceiptProjection | None = None
        self.claim_calls = 0
        self.terminal_calls = 0

    def current_scope(self, *, principal, store_ref):
        return self.scope

    def read_bound(self, *, principal, store_ref, job_ref):
        return self.job, self.binding

    def read_result_receipt(self, *, principal, store_ref, job_ref):
        if self.receipt is None:
            raise KeyError("media_job_result_receipt_not_found")
        return self.receipt

    def claim_provider_attempt(self, *, principal, store_ref, job_ref):
        self.claim_calls += 1
        if self.job.state != "QUEUED":
            return self.job, False
        self.job = MediaJobProjection(
            job_ref=self.job.job_ref,
            state="DISPATCHED",
            tool_name=self.job.tool_name,
            connector_ref=self.job.connector_ref,
            created_at=self.job.created_at,
            last_event_ordinal=2,
            safe_reason_code=None,
            state_recorded_at=NOW.isoformat(),
        )
        return self.job, True

    def record_provider_result(
        self,
        *,
        principal,
        store_ref,
        job_ref,
        state,
        result_kind,
        artifact_evidence_refs=(),
        content_asset_ref=None,
    ):
        if state == "SUCCEEDED":
            raise ValueError("media_job_success_requires_atomic_result_writer")
        self.terminal_calls += 1
        self.job = MediaJobProjection(
            job_ref=self.job.job_ref,
            state=state,
            tool_name=self.job.tool_name,
            connector_ref=self.job.connector_ref,
            created_at=self.job.created_at,
            last_event_ordinal=5 if state == "SUCCEEDED" else 3,
            safe_reason_code=None,
            state_recorded_at=NOW.isoformat(),
        )
        self.receipt = MediaJobResultReceiptProjection(
            receipt_ref="media-result-bas186",
            job_ref=job_ref,
            event_ref="media-event-terminal",
            state=state,
            provider=self.binding.provider,
            connector_ref=self.binding.connector_ref,
            result_kind=result_kind,
            artifact_evidence_refs=tuple(artifact_evidence_refs),
            content_asset_ref=content_asset_ref,
            receipt_sha256="f" * 64,
            recorded_at=NOW.isoformat(),
        )
        return self.receipt

    def record_blueprint_result(
        self,
        *,
        principal,
        store_ref,
        job_ref,
        blueprint,
        render_plan_sha256,
    ):
        self.terminal_calls += 1
        self.job = MediaJobProjection(
            job_ref=self.job.job_ref,
            state="SUCCEEDED",
            tool_name=self.job.tool_name,
            connector_ref=self.job.connector_ref,
            created_at=self.job.created_at,
            last_event_ordinal=5,
            safe_reason_code=None,
            state_recorded_at=NOW.isoformat(),
        )
        self.receipt = MediaJobResultReceiptProjection(
            receipt_ref="media-result-bas186",
            job_ref=job_ref,
            event_ref="media-event-terminal",
            state="SUCCEEDED",
            provider=self.binding.provider,
            connector_ref=self.binding.connector_ref,
            result_kind="editing_blueprint_evidence",
            artifact_evidence_refs=("evidence-blueprint-bas186",),
            content_asset_ref=None,
            receipt_sha256="f" * 64,
            recorded_at=NOW.isoformat(),
        )
        return self.receipt

    def record_render_result(
        self,
        *,
        principal,
        store_ref,
        job_ref,
        expected_event_ordinal,
        expected_recorded_at,
        artifact_writer,
    ):
        artifact = artifact_writer(None, self.scope, NOW)
        self.terminal_calls += 1
        self.job = MediaJobProjection(
            job_ref=self.job.job_ref,
            state="SUCCEEDED",
            tool_name=self.job.tool_name,
            connector_ref=self.job.connector_ref,
            created_at=self.job.created_at,
            last_event_ordinal=5,
            safe_reason_code=None,
            state_recorded_at=NOW.isoformat(),
        )
        self.receipt = MediaJobResultReceiptProjection(
            receipt_ref="media-result-bas186",
            job_ref=job_ref,
            event_ref="media-event-terminal",
            state="SUCCEEDED",
            provider=self.binding.provider,
            connector_ref=self.binding.connector_ref,
            result_kind="video_artifact_evidence",
            artifact_evidence_refs=tuple(artifact["artifact_evidence_refs"]),
            content_asset_ref=artifact["content_asset_ref"],
            receipt_sha256="f" * 64,
            recorded_at=NOW.isoformat(),
        )
        return self.receipt


class FakeSourceAuthority:
    def __init__(self, jobs=None):
        jobs = jobs or FakeJobs()
        self.source = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.source["audio_asset_ref"] = "content-asset://audio-001"
        self.source["input_artifacts"].append(
            {
                "content_asset_ref": "content-asset://audio-001",
                "evidence_ref": "evidence://audio-001",
                "evidence_sha256": "3" * 64,
                "content_type": "audio/wav",
                "role": "audio",
            }
        )
        self.source["analysis_receipt"]["source_snapshot_sha256"] = (
            analysis_receipt_snapshot_sha256(self.source["analysis_receipt"])
        )
        self.source["editing_blueprint"] = None
        self.source["editing_blueprint_sha256"] = None
        self.source["source_snapshot_sha256"] = source_snapshot_sha256(self.source)
        if jobs.binding.tool_name == "media.video_render":
            blueprint = {
                "contract_id": "kjds-editing-blueprint-v1",
                "contract_version": "1.0.0",
                "job_ref": "media-job-blueprint-bas186",
                "tool_name": "media.video_blueprint",
                "tool_version": jobs.binding.tool_version,
                "provider": BLUEPRINT_COMPILER_PROVIDER,
                "connector_ref": BLUEPRINT_COMPILER_CONNECTOR_REF,
                "connector_binding_sha256": (
                    BLUEPRINT_COMPILER_CONNECTOR_BINDING_SHA256
                ),
                "tool_descriptor_sha256": jobs.binding.tool_descriptor_sha256,
                "scope": dict(self.source["scope"]),
                "scope_binding_sha256": self.source["scope_binding_sha256"],
                "source_snapshot_sha256": self.source["source_snapshot_sha256"],
                "analysis_receipt": dict(self.source["analysis_receipt"]),
                "campaign_asset_refs": list(self.source["campaign_asset_refs"]),
                "reference_asset_refs": list(self.source["reference_asset_refs"]),
                "input_artifacts": list(self.source["input_artifacts"]),
                "scenes": list(self.source["scenes"]),
                "audio_asset_ref": self.source["audio_asset_ref"],
                "subtitle_asset_ref": self.source["subtitle_asset_ref"],
                "target_channels": list(self.source["target_channels"]),
                "render_profile_sha256": self.source["render_profile_sha256"],
                "external_write_allowed": False,
                "listing_eligible": False,
            }
            self.source["editing_blueprint"] = blueprint
            self.source["editing_blueprint_sha256"] = sha256_bytes(
                canonical_json(blueprint)
            )
            self.source["source_snapshot_sha256"] = source_snapshot_sha256(
                self.source
            )

    def read_editing_source(self, *, principal, store_ref, job_ref, scope, as_of):
        return self.source


class NoopAdapter:
    runtime_provider_identity = FfmpegMediaWorker.runtime_provider_identity

    def __init__(self):
        self.calls = 0

    def validate_plan(self, **kwargs):
        self.calls += 1


class FakeWorkbench:
    def __init__(self):
        self.calls = 0
        self.preflight_calls = 0
        self.execute_calls = 0
        self.artifact = None

    def validate_editing_handoff(self, **kwargs):
        self.calls += 1

    def preflight_governed_editing(self, **kwargs):
        self.preflight_calls += 1

    def read_governed_editing_artifact(self, **kwargs):
        return self.artifact

    def execute_governed_editing(self, **kwargs):
        self.execute_calls += 1
        self.artifact = {
            "content_asset_ref": "asset-bas186",
            "execution_id": "execution-bas186",
            "artifact_evidence_refs": (
                "evidence-video-1",
                "evidence-video-2",
                "evidence-video-3",
            ),
            "outputs": {
                "1:1": "evidence-video-1",
                "16:9": "evidence-video-2",
                "9:16": "evidence-video-3",
            },
            "render_plan_sha256": kwargs["render_plan_sha256"],
            "result_receipt_sha256": None,
        }
        receipt = kwargs["result_recorder"](
            lambda session, scope, completion_now: self.artifact
        )
        self.artifact["result_receipt_sha256"] = receipt.receipt_sha256
        return self.artifact

class FailingWorkbench(FakeWorkbench):
    def execute_governed_editing(self, **kwargs):
        self.execute_calls += 1
        raise RuntimeError("provider-private failure body")


class DurableScopeAuthority:
    def current(self, **kwargs):
        return {
            "status": "ready",
            "tenant_ref": kwargs["principal"].tenant_ref,
            "entity_ref": SCOPE.entity_ref,
            "store_ref": kwargs["store_ref"],
            "authority_sha256": SCOPE.authority_sha256,
        }


class DurableEditingJobsAdapter:
    def __init__(self, jobs):
        self.jobs = jobs

    def current_scope(self, **kwargs):
        return self.jobs.current_scope(**kwargs)

    def read_bound(self, *, principal, store_ref, job_ref):
        return (
            self.jobs.read(
                principal=principal,
                store_ref=store_ref,
                job_ref=job_ref,
            ),
            MediaJobBindingProjection(
                job_ref=job_ref,
                tool_name="media.video_render",
                tool_version="1.0.0",
                provider="ffmpeg",
                connector_ref=FFMPEG_PROVIDER_DESCRIPTOR.connector_ref,
                connector_binding_sha256=FFMPEG_PROVIDER_DESCRIPTOR.binding_sha256,
                tool_descriptor_sha256="c" * 64,
                campaign_brief_sha256="d" * 64,
                request_sha256="e" * 64,
            ),
        )

    def claim_provider_attempt(self, **kwargs):
        return self.jobs.claim_provider_attempt(**kwargs)

    def read_result_receipt(self, **kwargs):
        return self.jobs.read_result_receipt(**kwargs)

    def record_render_result(self, **kwargs):
        return self.jobs.record_render_result(**kwargs)

    def record_blueprint_result(self, **kwargs):
        return self.jobs.record_blueprint_result(**kwargs)


class FailingPreflightWorkbench(FakeWorkbench):
    def preflight_governed_editing(self, **kwargs):
        self.preflight_calls += 1
        raise ValueError("Product SKU Order Bank Amount private canaries")


class CampaignPolicyPreflightWorkbench(FakeWorkbench):
    def __init__(self, *, content, filename, content_type):
        super().__init__()
        self.input = (content, filename, content_type)

    def preflight_governed_editing(self, **kwargs):
        self.preflight_calls += 1
        content, filename, content_type = self.input
        FfmpegMediaWorker._validate_campaign_input(
            content=content,
            filename=filename,
            content_type=content_type,
        )


def workspace(
    jobs=None, source=None, workbench=None, media_connector_contract=None
):
    jobs = jobs or FakeJobs()
    source_authority = source or FakeSourceAuthority(jobs)
    return GovernedEditingBlueprintWorkspace(
        jobs=jobs,
        product_content=source_authority,
        evidence=SimpleNamespace(),
        media_workbench=workbench or FakeWorkbench(),
        ffmpeg_adapter=FfmpegMediaWorker(),
        media_connector_contract=(
            media_connector_contract or MediaConnectorContract()
        ),
        clock=lambda: NOW,
    )


def test_noncanonical_connector_contract_fails_before_claim_terminal_or_workbench():
    jobs = FakeJobs()
    workbench = FakeWorkbench()

    with pytest.raises(
        EditingBlueprintError, match="editing_blueprint_connector_contract_invalid"
    ):
        workspace(
            jobs=jobs,
            workbench=workbench,
            media_connector_contract=object(),
        )

    assert jobs.claim_calls == 0
    assert jobs.terminal_calls == 0
    assert workbench.execute_calls == 0


@pytest.mark.parametrize("field", ["connector_ref", "connector_binding_sha256"])
def test_render_runtime_connector_drift_fails_before_claim_or_execute(field):
    jobs = FakeJobs(tool_name="media.video_render")
    workbench = FakeWorkbench()
    if field == "connector_ref":
        jobs.binding = replace(jobs.binding, connector_ref="mcn_" + "0" * 32)
    else:
        jobs.binding = replace(jobs.binding, connector_binding_sha256="0" * 64)

    with pytest.raises(EditingBlueprintError, match="editing_provider_not_admitted"):
        workspace(jobs=jobs, workbench=workbench).process(
            PRINCIPAL, SCOPE.store_ref, jobs.job.job_ref
        )

    assert jobs.claim_calls == 0
    assert jobs.terminal_calls == 0
    assert workbench.preflight_calls == 0
    assert workbench.execute_calls == 0


def test_forged_ffmpeg_adapter_identity_is_rejected_during_composition():
    adapter = NoopAdapter()
    adapter.runtime_provider_identity = FfmpegMediaWorker.runtime_provider_identity

    with pytest.raises(
        EditingBlueprintError,
        match="editing_ffmpeg_runtime_provider_contract_invalid",
    ):
        GovernedEditingBlueprintWorkspace(
            jobs=FakeJobs(),
            product_content=FakeSourceAuthority(FakeJobs()),
            evidence=SimpleNamespace(),
            media_workbench=FakeWorkbench(),
            ffmpeg_adapter=adapter,
            media_connector_contract=MediaConnectorContract(),
            clock=lambda: NOW,
        )


def test_valid_blueprint_is_deterministic_durable_result():
    contract = MediaConnectorContract()
    service = workspace(media_connector_contract=contract)

    assert service.media_connector_contract is contract
    assert service.blueprint_provider is contract.internal_runtime_provider(
        INTERNAL_BLUEPRINT_PROVIDER
    )

    first = service.process(PRINCIPAL, SCOPE.store_ref, "media-job-bas186")
    second = service.process(PRINCIPAL, SCOPE.store_ref, "media-job-bas186")

    assert first.status == "EXECUTED"
    assert second.status == "READBACK"
    assert first.blueprint_sha256 == second.blueprint_sha256
    assert first.render_plan_sha256 == second.render_plan_sha256
    assert first.blueprint_sha256 and len(first.blueprint_sha256) == 64
    assert first.render_plan_sha256 and len(first.render_plan_sha256) == 64
    assert first.external_write_allowed is False
    assert first.listing_eligible is False
    assert first.automatic_retry is False
    assert first.automatic_failover is False
    assert first.result_state == "SUCCEEDED"
    assert first.result_kind == "editing_blueprint_evidence"


def test_editing_registry_keeps_existing_authorities_and_ffmpeg_boundary():
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))

    assert registry["status"] == (
        "internal_execution_validated_not_production_admitted"
    )
    assert registry["job_truth_owner"] == "GovernedMediaJobWorkspace"
    assert registry["artifact_truth_owner"] == "ContentAsset/Evidence"
    assert registry["render_contract"]["accepted_providers"] == ["ffmpeg"]
    assert registry["render_contract"]["remotion_status"] == "watch_not_admitted"
    assert registry["render_contract"]["execution_boundary_recomputes_plan_sha256"] is True
    assert registry["render_contract"]["all_declared_source_assets_must_be_consumed"] is True
    assert registry["render_contract"]["scene_transitions"] == [
        "cut",
        "fade",
        "crossfade",
    ]
    assert registry["render_contract"]["external_write_allowed"] is False
    assert registry["execution_admission"] == {
        "internal_runtime_composition": True,
        "single_job_truth": "GovernedMediaJobWorkspace",
        "worker_input_source": "governed-media-job-worker-input",
        "artifact_source": "kjds-ffmpeg-media-worker",
        "legacy_media_execution_is_job_truth": False,
        "governed_worker_cli_requires_explicit_job_actor_and_store": True,
        "active_dispatched_attempt_grace_seconds": 1500,
        "governed_render_budget_seconds": 1200,
        "active_dispatched_attempt_is_not_unknown_outcome": True,
        "same_connector_provider_readback_only": True,
        "production_admitted": False,
        "representative_live_render_verified": False,
        "external_write_allowed": False,
    }
    result_readback = registry["result_readback"]
    assert result_readback["terminal_asset_and_receipt_atomic_transaction"] is True
    assert result_readback["terminal_receipt_deferred_conservation"] is True
    assert result_readback["rotation_or_revoke_before_terminal_commit_mutates_nothing"] is True
    assert (
        PROVIDER_ATTEMPT_STALE_AFTER.total_seconds()
        > FfmpegMediaWorker.RENDER_BUDGET_SECONDS
    )


@pytest.mark.parametrize("field", ["tenant_ref", "entity_ref", "store_ref", "authority_sha256"])
def test_source_scope_drift_fails_closed(field):
    source = FakeSourceAuthority()
    source.source["scope"][field] = "drifted"
    with pytest.raises(EditingBlueprintError, match="scope_binding"):
        workspace(source=source).process(PRINCIPAL, SCOPE.store_ref, "media-job-bas186")


def test_unapproved_reference_rights_fail_closed():
    source = FakeSourceAuthority()
    source.source["rights_status"] = "unknown"

    with pytest.raises(EditingBlueprintError, match="rights"):
        workspace(source=source).process(PRINCIPAL, SCOPE.store_ref, "media-job-bas186")


@pytest.mark.parametrize(
    "scenes",
    [
        [
            {
                "scene_id": "scene-001",
                "source_asset_ref": "content-asset://reference-video-001",
                "source_start_ms": 0,
                "source_end_ms": 3000,
                "timeline_start_ms": 0,
                "timeline_end_ms": 3000,
                "transition": "cut",
                "caption_ref": "evidence://caption-001",
            },
            {
                "scene_id": "scene-001",
                "source_asset_ref": "content-asset://reference-video-001",
                "source_start_ms": 3000,
                "source_end_ms": 6000,
                "timeline_start_ms": 3000,
                "timeline_end_ms": 6000,
                "transition": "fade",
                "caption_ref": "evidence://caption-002",
            },
        ],
        [
            {
                "scene_id": "scene-001",
                "source_asset_ref": "content-asset://reference-video-001",
                "source_start_ms": 0,
                "source_end_ms": 4000,
                "timeline_start_ms": 0,
                "timeline_end_ms": 4000,
                "transition": "cut",
                "caption_ref": "evidence://caption-001",
            },
            {
                "scene_id": "scene-002",
                "source_asset_ref": "content-asset://reference-video-001",
                "source_start_ms": 3000,
                "source_end_ms": 6000,
                "timeline_start_ms": 3000,
                "timeline_end_ms": 6000,
                "transition": "fade",
                "caption_ref": "evidence://caption-002",
            },
        ],
    ],
)
def test_scene_overlap_or_duplicate_fails_closed(scenes):
    source = FakeSourceAuthority()
    source.source["scenes"] = scenes

    with pytest.raises(EditingBlueprintError, match="scene"):
        workspace(source=source).process(PRINCIPAL, SCOPE.store_ref, "media-job-bas186")


def test_scene_gap_and_unsealed_source_mutation_fail_closed():
    source = FakeSourceAuthority()
    source.source["scenes"][1]["timeline_start_ms"] = 4000
    with pytest.raises(EditingBlueprintError, match="timeline"):
        workspace(source=source).process(PRINCIPAL, SCOPE.store_ref, "media-job-bas186")


def test_unused_declared_source_channel_profile_and_duration_fail_before_claim():
    jobs = FakeJobs(tool_name="media.video_render", provider="ffmpeg")
    mutations = (
        lambda source: source["reference_asset_refs"].append(
            "content-asset://unused-reference"
        ),
        lambda source: source.update(target_channels=["amazon"]),
        lambda source: source.update(render_profile_sha256="f" * 64),
        lambda source: source["scenes"][0].update(
            source_end_ms=EDITING_MAX_SCENE_DURATION_MS + 1,
            timeline_end_ms=EDITING_MAX_SCENE_DURATION_MS + 1,
        ),
    )
    for mutate in mutations:
        source = FakeSourceAuthority()
        mutate(source.source)
        jobs.claim_calls = 0
        with pytest.raises(EditingBlueprintError):
            workspace(jobs=jobs, source=source).process(
                PRINCIPAL,
                SCOPE.store_ref,
                jobs.job.job_ref,
            )
        assert jobs.claim_calls == 0

    source = FakeSourceAuthority()
    source.source["scenes"][0].update(
        source_start_ms=0,
        source_end_ms=100,
        timeline_start_ms=0,
        timeline_end_ms=100,
    )
    source.source["scenes"][1].update(
        source_asset_ref="content-asset://reference-video-001",
        source_start_ms=100,
        source_end_ms=1100,
        timeline_start_ms=100,
        timeline_end_ms=1100,
        transition="crossfade",
    )
    with pytest.raises(EditingBlueprintError, match="transition"):
        workspace(jobs=jobs, source=source).process(
            PRINCIPAL,
            SCOPE.store_ref,
            jobs.job.job_ref,
        )
    assert jobs.claim_calls == 0

    source = FakeSourceAuthority()
    source.source["target_channels"] = ["ozon", "unsealed-channel"]
    with pytest.raises(EditingBlueprintError, match="target_channels_invalid"):
        workspace(source=source).process(PRINCIPAL, SCOPE.store_ref, "media-job-bas186")


@pytest.mark.parametrize(
    "payload",
    [
        {"provider_response": "private-body"},
        {"render_profile": {"command": "ffmpeg -i secret"}},
        {"reference_asset_refs": ["data:video/mp4;base64,AAAA"]},
    ],
)
def test_raw_provider_payload_and_body_refs_are_rejected(payload):
    source = FakeSourceAuthority()
    source.source.update(payload)

    with pytest.raises(EditingBlueprintError):
        workspace(source=source).process(PRINCIPAL, SCOPE.store_ref, "media-job-bas186")


def test_remotion_render_is_not_admitted():
    jobs = FakeJobs(tool_name="media.video_render", provider="remotion")

    with pytest.raises(EditingBlueprintError, match="provider"):
        workspace(jobs=jobs).process(PRINCIPAL, SCOPE.store_ref, "media-job-bas186")


def test_render_claims_and_executes_one_governed_job():
    jobs = FakeJobs(tool_name="media.video_render", provider="ffmpeg")
    workbench = FakeWorkbench()
    result = workspace(jobs=jobs, workbench=workbench).process(
        PRINCIPAL, SCOPE.store_ref, "media-job-bas186"
    )

    assert result.status == "EXECUTED"
    assert result.result_state == "SUCCEEDED"
    assert result.content_asset_ref == "asset-bas186"
    assert jobs.claim_calls == 1
    assert jobs.terminal_calls == 1
    assert workbench.execute_calls == 1
    assert result.external_write_allowed is False


def test_render_preflight_failure_has_zero_claim_terminal_and_execution():
    jobs = FakeJobs(tool_name="media.video_render", provider="ffmpeg")
    workbench = FailingPreflightWorkbench()

    with pytest.raises(
        EditingBlueprintError, match="editing_preflight_not_admitted"
    ) as error:
        workspace(jobs=jobs, workbench=workbench).process(
            PRINCIPAL, SCOPE.store_ref, jobs.job.job_ref
        )

    assert str(error.value) == "editing_preflight_not_admitted"
    assert workbench.preflight_calls == 1
    assert jobs.claim_calls == 0
    assert jobs.terminal_calls == 0
    assert workbench.execute_calls == 0


@pytest.mark.parametrize("case", ["wrong_mime", "wrong_magic", "oversize"])
def test_campaign_authority_drift_fails_before_claim_terminal_or_workbench(
    case,
):
    content, filename, content_type = {
        "wrong_mime": (b"<html>", "campaign.html", "text/html"),
        "wrong_magic": (b"not-png", "campaign.png", "image/png"),
        "oversize": (
            b"\x89PNG\r\n\x1a\n"
            + b"x" * (FfmpegMediaWorker.MAX_CAMPAIGN_INPUT_BYTES + 1),
            "campaign.png",
            "image/png",
        ),
    }[case]
    jobs = FakeJobs(tool_name="media.video_render", provider="ffmpeg")
    workbench = CampaignPolicyPreflightWorkbench(
        content=content,
        filename=filename,
        content_type=content_type,
    )

    with pytest.raises(EditingBlueprintError, match="editing_preflight_not_admitted"):
        workspace(jobs=jobs, workbench=workbench).process(
            PRINCIPAL, SCOPE.store_ref, jobs.job.job_ref
        )

    assert workbench.preflight_calls == 1
    assert jobs.claim_calls == 0
    assert jobs.terminal_calls == 0
    assert workbench.execute_calls == 0


def test_orphan_artifact_is_not_promoted_and_stale_attempt_remains_blocked():
    jobs = FakeJobs(
        tool_name="media.video_render",
        provider="ffmpeg",
        state="DISPATCHED",
        state_recorded_at=NOW - timedelta(minutes=26),
    )
    workbench = FakeWorkbench()
    workbench.artifact = {
        "content_asset_ref": "asset-bas186",
        "execution_id": "execution-bas186",
        "artifact_evidence_refs": (
            "evidence-video-1",
            "evidence-video-2",
            "evidence-video-3",
        ),
        "outputs": {
            "1:1": "evidence-video-1",
            "16:9": "evidence-video-2",
            "9:16": "evidence-video-3",
        },
        "render_plan_sha256": "unused-by-fake",
        "result_receipt_sha256": None,
    }

    result = workspace(jobs=jobs, workbench=workbench).process(
        PRINCIPAL, SCOPE.store_ref, jobs.job.job_ref
    )

    assert result.status == "BLOCKED"
    assert result.result_state is None
    assert result.result_kind is None
    assert result.content_asset_ref is None
    assert result.artifact_evidence_refs == ()
    assert result.blockers == ("provider_attempt_outcome_unverified",)
    assert jobs.claim_calls == 1
    assert jobs.terminal_calls == 0
    assert workbench.execute_calls == 0


def test_restart_without_durable_receipt_stays_blocked_without_redispatch():
    jobs = FakeJobs(
        tool_name="media.video_render",
        provider="ffmpeg",
        state="DISPATCHED",
        state_recorded_at=NOW - timedelta(minutes=26),
    )
    workbench = FakeWorkbench()

    result = workspace(jobs=jobs, workbench=workbench).process(
        PRINCIPAL, SCOPE.store_ref, jobs.job.job_ref
    )

    assert result.status == "BLOCKED"
    assert result.result_state is None
    assert result.result_kind is None
    assert result.blockers == ("provider_attempt_outcome_unverified",)
    assert jobs.claim_calls == 1
    assert jobs.terminal_calls == 0
    assert workbench.execute_calls == 0
    assert result.artifact_evidence_refs == ()


def test_real_engine_restart_without_receipt_never_redispatches_or_self_signs():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    authority = DurableScopeAuthority()
    jobs1 = GovernedMediaJobWorkspace(
        engine,
        evidence=EvidenceService(engine),
        authority=authority,
        clock=lambda: NOW,
    )
    created = jobs1.submit(
        principal=PRINCIPAL,
        store_ref=SCOPE.store_ref,
        request={
            "tool_name": "image.generate",
            "tool_version": "1.0.0",
            "project_ref": "project-bas186",
            "brief_ref": "brief-bas186",
            "provider": "ffmpeg",
            "connector_ref": FFMPEG_PROVIDER_DESCRIPTOR.connector_ref,
            "connector_binding_sha256": FFMPEG_PROVIDER_DESCRIPTOR.binding_sha256,
            "idempotency_sha256": "c" * 64,
            "prompt": "private render request",
        },
    )
    with Session(engine) as session, session.begin():
        job = session.get(MediaJobRow, created.job_ref)
        assert job is not None
        job.tool_name = "media.video_render"
        job.provider = "ffmpeg"
        job.connector_ref = FFMPEG_PROVIDER_DESCRIPTOR.connector_ref
        job.connector_binding_sha256 = FFMPEG_PROVIDER_DESCRIPTOR.binding_sha256

    source = FakeSourceAuthority(FakeJobs(tool_name="media.video_render"))
    failing = FailingWorkbench()
    first_workspace = GovernedEditingBlueprintWorkspace(
        jobs=DurableEditingJobsAdapter(jobs1),
        product_content=source,
        evidence=EvidenceService(engine),
        media_workbench=failing,
        ffmpeg_adapter=FfmpegMediaWorker(),
        media_connector_contract=MediaConnectorContract(),
        clock=lambda: NOW,
    )
    first = first_workspace.process(PRINCIPAL, SCOPE.store_ref, created.job_ref)
    assert first.status == "BLOCKED"
    assert first.blockers == ("provider_attempt_outcome_unverified",)
    assert failing.execute_calls == 1

    with Session(engine) as session:
        before = (
            session.scalar(select(func.count()).select_from(MediaJobEventRow)),
            session.scalar(select(func.count()).select_from(EvidenceRecordRow)),
            session.scalar(select(func.count()).select_from(ContentAssetRow)),
            session.scalar(select(func.count()).select_from(MediaJobResultReceiptRow)),
        )
        latest = session.scalar(
            select(MediaJobEventRow)
            .where(MediaJobEventRow.job_ref == created.job_ref)
            .order_by(MediaJobEventRow.ordinal.desc())
        )
        assert latest is not None and latest.state == "DISPATCHED"

    jobs2 = GovernedMediaJobWorkspace(
        engine,
        evidence=EvidenceService(engine),
        authority=DurableScopeAuthority(),
        clock=lambda: NOW,
    )
    second_workbench = FailingWorkbench()
    restarted = GovernedEditingBlueprintWorkspace(
        jobs=DurableEditingJobsAdapter(jobs2),
        product_content=FakeSourceAuthority(FakeJobs(tool_name="media.video_render")),
        evidence=EvidenceService(engine),
        media_workbench=second_workbench,
        ffmpeg_adapter=FfmpegMediaWorker(),
        media_connector_contract=MediaConnectorContract(),
        clock=lambda: NOW,
    )
    second = restarted.process(PRINCIPAL, SCOPE.store_ref, created.job_ref)

    assert second.status == "BLOCKED"
    assert second.blockers == ("provider_attempt_in_progress",)
    assert second_workbench.execute_calls == 0
    assert failing.execute_calls == 1
    with Session(engine) as session:
        after = (
            session.scalar(select(func.count()).select_from(MediaJobEventRow)),
            session.scalar(select(func.count()).select_from(EvidenceRecordRow)),
            session.scalar(select(func.count()).select_from(ContentAssetRow)),
            session.scalar(select(func.count()).select_from(MediaJobResultReceiptRow)),
        )
    assert after == before


def test_concurrent_worker_observes_active_dispatch_without_forcing_unknown():
    jobs = FakeJobs(
        tool_name="media.video_render",
        provider="ffmpeg",
        state="DISPATCHED",
    )
    workbench = FakeWorkbench()

    result = workspace(jobs=jobs, workbench=workbench).process(
        PRINCIPAL, SCOPE.store_ref, jobs.job.job_ref
    )

    assert result.status == "BLOCKED"
    assert result.blockers == ("provider_attempt_in_progress",)
    assert jobs.terminal_calls == 0
    assert workbench.execute_calls == 0


def test_full_governed_render_budget_remains_active_not_unknown():
    jobs = FakeJobs(
        tool_name="media.video_render",
        provider="ffmpeg",
        state="DISPATCHED",
        state_recorded_at=NOW - timedelta(minutes=24),
    )
    result = workspace(jobs=jobs).process(
        PRINCIPAL,
        SCOPE.store_ref,
        jobs.job.job_ref,
    )

    assert result.status == "BLOCKED"
    assert result.blockers == ("provider_attempt_in_progress",)
    assert jobs.terminal_calls == 0


def test_local_provider_exception_cannot_self_sign_failure_receipt():
    jobs = FakeJobs(tool_name="media.video_render", provider="ffmpeg")
    workbench = FailingWorkbench()

    result = workspace(jobs=jobs, workbench=workbench).process(
        PRINCIPAL, SCOPE.store_ref, jobs.job.job_ref
    )

    assert result.status == "BLOCKED"
    assert result.result_state is None
    assert result.result_kind is None
    assert result.artifact_evidence_refs == ()
    assert result.content_asset_ref is None
    assert result.blockers == ("provider_attempt_outcome_unverified",)
    assert jobs.claim_calls == 1
    assert jobs.terminal_calls == 0
    assert workbench.execute_calls == 1


def test_unknown_outcome_receipt_is_not_admitted_without_typed_authority():
    jobs = FakeJobs(tool_name="media.video_render", provider="ffmpeg", state="UNKNOWN_OUTCOME")
    jobs.receipt = MediaJobResultReceiptProjection(
        receipt_ref="media-result-bas186",
        job_ref=jobs.job.job_ref,
        event_ref="media-event-bas186",
        state="UNKNOWN_OUTCOME",
        provider="ffmpeg",
        connector_ref=jobs.binding.connector_ref,
        result_kind="unknown_outcome_readback",
        artifact_evidence_refs=(),
        content_asset_ref=None,
        receipt_sha256="f" * 64,
        recorded_at=NOW.isoformat(),
    )

    with pytest.raises(
        EditingBlueprintError,
        match="editing_non_success_readback_authority_not_admitted",
    ):
        workspace(jobs=jobs).process(
            PRINCIPAL, SCOPE.store_ref, jobs.job.job_ref
        )

    assert jobs.terminal_calls == 0


def test_scope_rotation_after_source_read_fails_before_handoff():
    jobs = FakeJobs()
    source = FakeSourceAuthority()
    original = jobs.current_scope
    calls = 0

    def rotating_current_scope(*, principal, store_ref):
        nonlocal calls
        calls += 1
        if calls == 3:
            return MediaJobScope(
                tenant_ref=SCOPE.tenant_ref,
                entity_ref=SCOPE.entity_ref,
                store_ref=SCOPE.store_ref,
                authority_sha256="f" * 64,
                subject_actor_id=SCOPE.subject_actor_id,
            )
        return original(principal=principal, store_ref=store_ref)

    jobs.current_scope = rotating_current_scope

    with pytest.raises(EditingBlueprintError, match="scope_changed"):
        workspace(jobs=jobs, source=source).process(
            PRINCIPAL, SCOPE.store_ref, jobs.job.job_ref
        )


def test_scope_rotation_during_handoff_fails_before_projection():
    jobs = FakeJobs(tool_name="media.video_render", provider="ffmpeg")
    original = jobs.current_scope
    calls = 0

    def rotating_current_scope(*, principal, store_ref):
        nonlocal calls
        calls += 1
        if calls == 4:
            return MediaJobScope(
                tenant_ref=SCOPE.tenant_ref,
                entity_ref=SCOPE.entity_ref,
                store_ref=SCOPE.store_ref,
                authority_sha256="f" * 64,
                subject_actor_id=SCOPE.subject_actor_id,
            )
        return original(principal=principal, store_ref=store_ref)

    jobs.current_scope = rotating_current_scope

    with pytest.raises(EditingBlueprintError, match="scope_changed"):
        workspace(jobs=jobs).process(PRINCIPAL, SCOPE.store_ref, jobs.job.job_ref)
