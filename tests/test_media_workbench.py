import os
import subprocess
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.domain import (
    ContentAsset,
    ContentStatus,
    ContentType,
    Product,
)
from apps.control_plane.evidence import EvidenceGrade, EvidenceRecordRow, EvidenceService
from apps.control_plane.media_jobs import (
    EDITING_MAX_SCENE_DURATION_MS,
    EDITING_TARGET_CHANNELS,
    FFMPEG_RENDER_PROFILE_SHA256,
    GOVERNED_RENDER_RATIOS,
    MediaJobScope,
    canonical_json,
    sha256_bytes,
)
from apps.control_plane.media_workbench import (
    FfmpegMediaWorker,
    MediaExecutionRow,
    MediaWorkbenchService,
)
from apps.control_plane.sql_repository import Base, ContentAssetRow, SqlAlchemyRepository


class FakeEvidence:
    def __init__(self) -> None:
        self.invalid: set[str] = set()
        self.records: dict[str, SimpleNamespace] = {}
        self.links: list[dict] = []
        self.counter = 0

    def require_valid(self, evidence_ids) -> None:
        if set(evidence_ids) & self.invalid:
            raise ValueError("Evidence is expired or invalid")

    def get(self, evidence_id):
        if "script" in evidence_id:
            return SimpleNamespace(
                content_type="text/plain",
                metadata={"language": "ru", "human_approved": True},
            )
        if "subtitle" in evidence_id:
            return SimpleNamespace(
                content_type="application/x-subrip",
                metadata={"language": "ru", "human_approved": True},
            )
        if "audio" in evidence_id:
            return SimpleNamespace(
                content_type="audio/wav",
                metadata={"rights_status": "approved"},
            )
        return SimpleNamespace(content_type="image/png", metadata={})

    def capture(self, **values):
        self.counter += 1
        record = SimpleNamespace(id=f"evd-output-{self.counter}", **values)
        self.records[record.id] = record
        return record

    def link(self, **values) -> None:
        self.links.append(values)


class FakeImageExecution:
    def queue(self, asset_id: str, *, requested_by: str):
        return SimpleNamespace(status=ContentStatus.QUEUED)

    def sync(self, asset_id: str, *, requested_by: str):
        return SimpleNamespace(
            status=ContentStatus.GENERATED,
            artifact_ref=f"evd-image-{asset_id}",
            generation={},
        )


def fixture():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    repository = SqlAlchemyRepository(engine)
    evidence = FakeEvidence()
    service = MediaWorkbenchService(
        engine=engine,
        repository=repository,
        evidence=evidence,
        image_execution=FakeImageExecution(),
    )
    product = repository.add_product(Product("SKU-MEDIA", "媒体测试商品"))
    return engine, repository, evidence, service, product


def image_asset(repository, product_id: str, *, template_id: str) -> ContentAsset:
    return repository.add_content_asset(
        ContentAsset(
            product_id,
            ContentType.IMAGE,
            "ru-RU",
            "OZON",
            {
                "template_id": template_id,
                "variant": "main",
                "rights_evidence_ids": ["evd-rights"],
            },
            {},
        )
    )


def video_asset(
    repository,
    product_id: str,
    approved_image_id: str,
    *,
    suffix: str,
) -> ContentAsset:
    return repository.add_content_asset(
        ContentAsset(
            product_id,
            ContentType.VIDEO,
            "ru-RU",
            "OZON",
            {
                "template_id": "kjds-ffmpeg-product-video-v1",
                "approved_image_asset_ids": [approved_image_id],
                "script_evidence_id": f"evd-script-{suffix}",
                "subtitle_evidence_id": f"evd-subtitle-{suffix}",
                "audio_rights_evidence_id": f"evd-audio-{suffix}",
                "script_human_confirmed": True,
                "aspect_ratios": ["9:16", "1:1", "16:9"],
            },
            {},
        )
    )


def test_image_batch_is_idempotent_and_reports_partial_failure():
    _, repository, _, service, product = fixture()
    admitted = image_asset(repository, product.id, template_id="ozon-retouch-v1")

    payload = service.queue_batch(
        idempotency_key="batch-1",
        requested_by="operator-1",
        items=[
            {
                "asset_id": admitted.id,
                "idempotency_key": "asset-1",
                "retry": False,
            },
            {
                "asset_id": "asset-missing",
                "idempotency_key": "asset-2",
                "retry": False,
            },
        ],
    )
    replay = service.queue_batch(
        idempotency_key="batch-1",
        requested_by="operator-1",
        items=[
            {
                "asset_id": admitted.id,
                "idempotency_key": "asset-1",
                "retry": False,
            },
            {
                "asset_id": "asset-missing",
                "idempotency_key": "asset-2",
                "retry": False,
            },
        ],
    )

    assert payload["status"] == "partial"
    assert payload["summary"] == {
        "item_count": 2,
        "accepted_count": 1,
        "failed_count": 1,
    }
    assert replay["batch_id"] == payload["batch_id"]
    assert (
        replay["items"][0]["execution"]["id"]
        == payload["items"][0]["execution"]["id"]
    )
    assert payload["external_side_effect"] is False


def test_blocked_template_and_expired_rights_fail_closed():
    _, repository, evidence, service, product = fixture()
    blocked = image_asset(repository, product.id, template_id="composite-v1")

    result = service.queue(
        blocked.id,
        idempotency_key="blocked-1",
        requested_by="operator-1",
    )

    assert result["status"] == "blocked"
    assert result["error_code"] == "TEMPLATE_NOT_ADMITTED"
    source = image_asset(repository, product.id, template_id="ozon-retouch-v1")
    source.status = ContentStatus.APPROVED
    source.artifact_ref = "evd-approved-image"
    repository.save_content_asset(source)
    video = video_asset(repository, product.id, source.id, suffix="expired")
    evidence.invalid.add("evd-audio-expired")
    with pytest.raises(ValueError, match="expired or invalid"):
        service.queue(
            video.id,
            idempotency_key="video-expired",
            requested_by="operator-1",
        )


def test_video_lease_recovery_failure_retry_hashes_and_manifest():
    engine, repository, _, service, product = fixture()
    source = image_asset(repository, product.id, template_id="ozon-retouch-v1")
    source.status = ContentStatus.APPROVED
    source.artifact_ref = "evd-approved-image"
    repository.save_content_asset(source)
    video = video_asset(repository, product.id, source.id, suffix="ok")
    queued = service.queue(
        video.id,
        idempotency_key="video-1",
        requested_by="operator-1",
    )
    first_claim = service.claim_video(worker_id="media-worker-1")
    assert first_claim["id"] == queued["id"]
    with Session(engine) as session, session.begin():
        row = session.get(MediaExecutionRow, queued["id"])
        row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    recovered = service.claim_video(worker_id="media-worker-2")
    assert recovered["id"] == queued["id"]
    assert recovered["lease_owner"] == "media-worker-2"

    completed = service.complete_video(
        queued["id"],
        worker_id="media-worker-2",
        outputs={
            "9:16": b"vertical-mp4",
            "1:1": b"square-mp4",
            "16:9": b"wide-mp4",
        },
        subtitle_bytes=b"1\n00:00:00,000 --> 00:00:01,000\nTest",
        cover_bytes=b"cover-jpg",
        keyframe_bytes=b"keyframe-jpg",
        encoder_report={"encoder_version": "ffmpeg-7.1", "exit_code": 0},
        cost_amount=Decimal("1.25"),
        cost_currency="CNY",
    )

    assert completed["status"] == "generated"
    assert set(completed["outputs"]["videos"]) == {"9:16", "1:1", "16:9"}
    assert set(completed["outputs"]["output_sha256"]) == {
        "9:16",
        "1:1",
        "16:9",
    }
    assert completed["cost"] == {"amount": "1.25", "currency": "CNY"}
    approved = repository.get_content_asset(video.id)
    approved.status = ContentStatus.APPROVED
    approved.qa_results = [{"check": "all", "passed": True}]
    repository.save_content_asset(approved)
    later_attempt = service.queue(
        video.id,
        idempotency_key="video-later-failure",
        requested_by="operator-1",
    )
    service.claim_video(worker_id="media-worker-later")
    service.fail_video(
        later_attempt["id"],
        worker_id="media-worker-later",
        error_code="FFMPEG_EXIT_1",
        error_detail="later failure must not relabel the approved generation",
    )
    manifest = service.delivery_manifest(video.id, requested_by="reviewer-1")
    replay = service.delivery_manifest(video.id, requested_by="reviewer-1")
    assert manifest["manifest_id"] == replay["manifest_id"]
    assert manifest["listing_eligible"] is True
    assert manifest["encoder_version"] == "ffmpeg-7.1"
    assert manifest["execution_id"] == completed["id"]
    assert manifest["external_marketplace_write"] is False

    retry_video = video_asset(repository, product.id, source.id, suffix="retry")
    failed_queue = service.queue(
        retry_video.id,
        idempotency_key="retry-1",
        requested_by="operator-1",
    )
    service.claim_video(worker_id="media-worker-3")
    failed = service.fail_video(
        failed_queue["id"],
        worker_id="media-worker-3",
        error_code="FFMPEG_EXIT_1",
        error_detail="encoder failed",
    )
    retried = service.queue(
        retry_video.id,
        idempotency_key="retry-2",
        requested_by="operator-1",
        retry=True,
    )
    assert failed["status"] == "failed"
    assert retried["attempt"] == 2


class FixedRenderAdapter:
    def render_plan(self, **_):
        return (
            {
                "9:16": b"vertical-video",
                "1:1": b"square-video",
                "16:9": b"wide-video",
            },
            {"encoder_version": "ffmpeg-test-v1"},
        )


def test_governed_artifact_writer_freezes_explicit_ratio_order():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    repository = SqlAlchemyRepository(engine)
    evidence = EvidenceService(engine)
    service = MediaWorkbenchService(
        engine=engine,
        repository=repository,
        evidence=evidence,
        image_execution=FakeImageExecution(),
    )
    now = datetime(2026, 8, 9, 12, tzinfo=UTC)
    product = repository.add_product(
        Product(
            "SKU-RATIO-ORDER",
            "Governed ratio order",
            id="product-ratio-order",
            created_at=now.isoformat(),
            tenant_ref="tenant-ratio-order",
            entity_ref="entity-ratio-order",
            store_ref="store-ratio-order",
            scope_grant_authority_sha256="a" * 64,
            scope_as_of=now.isoformat(),
            created_by="actor-ratio-order",
        )
    )
    scope = MediaJobScope(
        tenant_ref="tenant-ratio-order",
        entity_ref="entity-ratio-order",
        store_ref="store-ratio-order",
        authority_sha256="a" * 64,
        subject_actor_id="actor-ratio-order",
    )
    outputs = {
        "9:16": b"\x00\x00\x00\x18ftypisomvertical",
        "1:1": b"\x00\x00\x00\x18ftypisomsquare",
        "16:9": b"\x00\x00\x00\x18ftypisomwide",
    }
    service._lock_governed_editing_inputs_in_session = lambda **_: None
    with Session(engine) as session, session.begin():
        result = service._persist_governed_editing_artifact_in_session(
            session=session,
            scope=scope,
            job_ref="media-job-ratio-order",
            source={"product_id": product.id, "source_snapshot_sha256": "b" * 64},
            render_plan={},
            render_plan_sha256="c" * 64,
            outputs=outputs,
            encoder_report={"encoder_version": "ffmpeg-ratio-order-v1"},
            now=now,
        )

    assert tuple(result["outputs"]) == GOVERNED_RENDER_RATIOS
    assert result["artifact_evidence_refs"] == tuple(
        result["outputs"][ratio] for ratio in GOVERNED_RENDER_RATIOS
    )


def test_governed_editing_attaches_once_without_legacy_execution_row():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    repository = SqlAlchemyRepository(engine)
    evidence = EvidenceService(engine)
    service = MediaWorkbenchService(
        engine=engine,
        repository=repository,
        evidence=evidence,
        image_execution=FakeImageExecution(),
    )
    now = datetime(2026, 8, 9, 12, tzinfo=UTC)
    product = repository.add_product(
        Product(
            "SKU-GOVERNED",
            "Governed media",
            id="product-governed",
            created_at=now.isoformat(),
            tenant_ref="tenant-1",
            entity_ref="entity-1",
            store_ref="store-1",
            scope_grant_authority_sha256="a" * 64,
            scope_as_of=now.isoformat(),
            created_by="actor-1",
        )
    )
    source_record = evidence.capture(
        content=b"approved-reference-video",
        filename="source.mp4",
        content_type="video/mp4",
        source="https://example.test/reference-video",
        source_ref="reference-video",
        grade=EvidenceGrade.B,
        effective_at=now.isoformat(),
        effective_until=None,
        created_by="actor-1",
        metadata={"rights_status": "approved"},
    )
    caption_record = evidence.capture(
        content=b"1\n00:00:00,000 --> 00:00:03,000\nGoverned scene\n",
        filename="caption.srt",
        content_type="application/x-subrip",
        source="https://example.test/reference-caption",
        source_ref="reference-caption",
        grade=EvidenceGrade.B,
        effective_at=now.isoformat(),
        effective_until=None,
        created_by="actor-1",
        metadata={"rights_status": "approved"},
    )
    repository.add_content_asset(
        ContentAsset(
            product_id=product.id,
            content_type=ContentType.VIDEO,
            locale="ru-RU",
            channel="ozon",
            brief={},
            source_facts={},
            status=ContentStatus.APPROVED,
            artifact_ref=source_record.id,
            id="source-video-1",
            created_at=now.isoformat(),
        )
    )
    scope = MediaJobScope(
        tenant_ref="tenant-1",
        entity_ref="entity-1",
        store_ref="store-1",
        authority_sha256="a" * 64,
        subject_actor_id="actor-1",
    )
    source = {
        "product_id": product.id,
        "reference_asset_refs": ["content-asset://source-video-1"],
        "audio_asset_ref": None,
        "subtitle_asset_ref": None,
        "target_channels": list(EDITING_TARGET_CHANNELS),
        "render_profile_sha256": FFMPEG_RENDER_PROFILE_SHA256,
        "source_snapshot_sha256": "b" * 64,
        "scenes": [
            {
                "scene_id": "scene-1",
                "source_asset_ref": "content-asset://source-video-1",
                "source_start_ms": 0,
                "source_end_ms": 3000,
                "timeline_start_ms": 0,
                "timeline_end_ms": 3000,
                "transition": "cut",
                "caption_ref": f"evidence://{caption_record.id}",
            }
        ],
    }
    render_plan = {
        "contract_id": "kjds-ffmpeg-render-plan-v1",
        "executor": "ffmpeg",
        "blueprint_sha256": "d" * 64,
        "reference_asset_refs": source["reference_asset_refs"],
        "scenes": source["scenes"],
        "audio_asset_ref": None,
        "subtitle_asset_ref": None,
        "target_channels": list(EDITING_TARGET_CHANNELS),
        "render_profile_sha256": FFMPEG_RENDER_PROFILE_SHA256,
        "external_write_allowed": False,
        "automatic_retry": False,
        "automatic_failover": False,
    }
    with pytest.raises(ValueError, match="ffmpeg_render_plan_not_admitted"):
        service.execute_governed_editing(
            principal=SimpleNamespace(actor_id="actor-1"),
            store_ref="store-1",
            job_ref="media-job-1",
            scope=scope,
            source=source,
            render_plan=render_plan,
            render_plan_sha256="c" * 64,
            ffmpeg_adapter=FixedRenderAdapter(),
            result_recorder=lambda _: None,
            now=now,
        )
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ContentAssetRow)) == 1
        evidence_count = session.scalar(
            select(func.count()).select_from(EvidenceRecordRow)
        )
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ContentAssetRow)) == 1
        assert session.scalar(select(func.count()).select_from(EvidenceRecordRow)) == evidence_count
        assert session.scalar(
            select(func.count()).select_from(MediaExecutionRow)
        ) == 0


def test_ffmpeg_filter_graph_consumes_each_scene_source_transition_and_caption(tmp_path):
    refs = (
        "content-asset://source-video-1",
        "content-asset://source-video-2",
    )
    caption_paths = {
        "evidence://caption-1": tmp_path / "caption-1.srt",
        "evidence://caption-2": tmp_path / "caption-2.srt",
    }
    render_plan = {
        "scenes": [
            {
                "scene_id": "scene-1",
                "source_asset_ref": refs[0],
                "source_start_ms": 0,
                "source_end_ms": 3000,
                "timeline_start_ms": 0,
                "timeline_end_ms": 3000,
                "transition": "cut",
                "caption_ref": "evidence://caption-1",
            },
            {
                "scene_id": "scene-2",
                "source_asset_ref": refs[1],
                "source_start_ms": 0,
                "source_end_ms": 3000,
                "timeline_start_ms": 3000,
                "timeline_end_ms": 6000,
                "transition": "crossfade",
                "caption_ref": "evidence://caption-2",
            },
        ]
    }

    graph, output_label, duration = FfmpegMediaWorker._filter_graph(
        render_plan=render_plan,
        reference_asset_refs=refs,
        caption_paths=caption_paths,
        subtitle_path=None,
        width="1080",
        height="1920",
    )

    assert "[0:v]trim=start=0.000:end=3.000" in graph
    assert "[1:v]trim=start=0.000:end=3.000" in graph
    assert "caption-1.srt" in graph and "caption-2.srt" in graph
    assert "xfade=transition=fade:duration=0.250:offset=2.750" in graph
    assert output_label == "[mix1]"
    assert duration == 5.75


@pytest.mark.parametrize("mutation", ["unused_source", "short_crossfade", "oversized_scene"])
def test_ffmpeg_plan_rejects_unconsumed_sources_invalid_transition_and_bounds(mutation):
    refs = ["content-asset://source-1", "content-asset://source-2"]
    plan = {
        "contract_id": "kjds-ffmpeg-render-plan-v1",
        "executor": "ffmpeg",
        "blueprint_sha256": "a" * 64,
        "reference_asset_refs": refs,
        "scenes": [
            {
                "scene_id": "scene-1",
                "source_asset_ref": refs[0],
                "source_start_ms": 0,
                "source_end_ms": 1000,
                "timeline_start_ms": 0,
                "timeline_end_ms": 1000,
                "transition": "cut",
                "caption_ref": "evidence://caption-1",
            },
            {
                "scene_id": "scene-2",
                "source_asset_ref": refs[1],
                "source_start_ms": 0,
                "source_end_ms": 1000,
                "timeline_start_ms": 1000,
                "timeline_end_ms": 2000,
                "transition": "crossfade",
                "caption_ref": "evidence://caption-2",
            },
        ],
        "audio_asset_ref": None,
        "subtitle_asset_ref": None,
        "target_channels": list(EDITING_TARGET_CHANNELS),
        "render_profile_sha256": FFMPEG_RENDER_PROFILE_SHA256,
        "external_write_allowed": False,
        "automatic_retry": False,
        "automatic_failover": False,
    }
    if mutation == "unused_source":
        plan["scenes"][1]["source_asset_ref"] = refs[0]
    elif mutation == "short_crossfade":
        plan["scenes"][0]["source_end_ms"] = 100
        plan["scenes"][0]["timeline_end_ms"] = 100
        plan["scenes"][1]["timeline_start_ms"] = 100
        plan["scenes"][1]["timeline_end_ms"] = 1100
    else:
        plan["scenes"][0]["source_end_ms"] = EDITING_MAX_SCENE_DURATION_MS + 1
        plan["scenes"][0]["timeline_end_ms"] = EDITING_MAX_SCENE_DURATION_MS + 1
        plan["scenes"][1]["timeline_start_ms"] = EDITING_MAX_SCENE_DURATION_MS + 1
        plan["scenes"][1]["timeline_end_ms"] = EDITING_MAX_SCENE_DURATION_MS + 1001
    seal = sha256_bytes(canonical_json(plan))

    with pytest.raises(ValueError, match="ffmpeg_render_plan_not_admitted"):
        FfmpegMediaWorker.validate_plan(
            render_plan=plan,
            render_plan_sha256=seal,
            executor="ffmpeg",
            reference_asset_refs=tuple(refs),
        )


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [
        ("caption.txt", "application/x-subrip"),
        ("caption.srt", "text/plain"),
        ("caption.exe", "text/plain"),
        ("../caption.srt", "application/x-subrip"),
        ("folder/caption.srt", "application/x-subrip"),
        ("caption\x00.srt", "application/x-subrip"),
    ],
)
def test_ffmpeg_text_input_binds_safe_filename_extension_and_mime(
    filename,
    content_type,
):
    with pytest.raises(ValueError, match="ffmpeg_text_input_not_admitted"):
        FfmpegMediaWorker._validate_text_input(
            content=b"1\n00:00:00,000 --> 00:00:01,000\ncaption\n",
            filename=filename,
            content_type=content_type,
        )

    FfmpegMediaWorker._validate_text_input(
        content=b"1\n00:00:00,000 --> 00:00:01,000\ncaption\n",
        filename="caption.srt",
        content_type="application/x-subrip",
    )


@pytest.mark.parametrize(
    ("content", "filename", "content_type"),
    [
        (b"<html>", "campaign.html", "text/html"),
        (b"not-png", "campaign.png", "image/png"),
        (b"\x89PNG\r\n\x1a\n", "campaign.jpg", "image/png"),
        (b"\x89PNG\r\n\x1a\n", "../campaign.png", "image/png"),
        (b"\x89PNG\r\n\x1a\n", "campaign.exe", "application/octet-stream"),
    ],
)
def test_campaign_input_requires_explicit_mime_extension_magic_policy(
    content,
    filename,
    content_type,
):
    with pytest.raises(ValueError, match="ffmpeg_campaign_input_not_admitted"):
        FfmpegMediaWorker._validate_campaign_input(
            content=content,
            filename=filename,
            content_type=content_type,
        )

    assert (
        FfmpegMediaWorker._validate_campaign_input(
            content=b"\x89PNG\r\n\x1a\nvalid",
            filename="campaign.png",
            content_type="image/png",
        )
        == ".png"
    )


def test_real_ffmpeg_executes_governed_multi_source_scene_plan(tmp_path, monkeypatch):
    ffmpeg = os.getenv("KJDS_FFMPEG_PATH")
    ffprobe = os.getenv("KJDS_FFPROBE_PATH")
    if not ffmpeg or not ffprobe:
        pytest.skip("BAS-186 real FFmpeg gate requires explicit binary paths")
    refs = (
        "content-asset://source-video-red",
        "content-asset://source-video-blue",
    )
    source_inputs = {}
    for index, color in enumerate(("red", "blue")):
        path = tmp_path / f"source-{color}.mp4"
        subprocess.run(
            [
                ffmpeg,
                "-nostdin",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c={color}:s=320x240:d=3:r=30",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(path),
            ],
            check=True,
            capture_output=True,
        )
        source_inputs[refs[index]] = (path.read_bytes(), path.name)
    caption_inputs = {
        "evidence://caption-red": (
            b"1\n00:00:00,000 --> 00:00:00,900\nRED\n",
            "caption-red.srt",
        ),
        "evidence://caption-blue": (
            b"1\n00:00:00,000 --> 00:00:00,900\nBLUE\n",
            "caption-blue.srt",
        ),
    }
    render_plan = {
        "contract_id": "kjds-ffmpeg-render-plan-v1",
        "executor": "ffmpeg",
        "blueprint_sha256": "a" * 64,
        "reference_asset_refs": list(refs),
        "scenes": [
            {
                "scene_id": "scene-red",
                "source_asset_ref": refs[0],
                "source_start_ms": 0,
                "source_end_ms": 1000,
                "timeline_start_ms": 0,
                "timeline_end_ms": 1000,
                "transition": "cut",
                "caption_ref": "evidence://caption-red",
            },
            {
                "scene_id": "scene-blue",
                "source_asset_ref": refs[1],
                "source_start_ms": 0,
                "source_end_ms": 1000,
                "timeline_start_ms": 1000,
                "timeline_end_ms": 2000,
                "transition": "crossfade",
                "caption_ref": "evidence://caption-blue",
            },
        ],
        "audio_asset_ref": None,
        "subtitle_asset_ref": None,
        "target_channels": list(EDITING_TARGET_CHANNELS),
        "render_profile_sha256": FFMPEG_RENDER_PROFILE_SHA256,
        "external_write_allowed": False,
        "automatic_retry": False,
        "automatic_failover": False,
    }
    render_plan_sha256 = sha256_bytes(canonical_json(render_plan))
    monkeypatch.setenv("KJDS_FFMPEG_PATH", ffmpeg)
    monkeypatch.setenv("KJDS_FFPROBE_PATH", ffprobe)

    outputs, report = FfmpegMediaWorker.render_plan(
        render_plan=render_plan,
        render_plan_sha256=render_plan_sha256,
        source_inputs=source_inputs,
        caption_inputs=caption_inputs,
        audio_bytes=None,
        audio_filename=None,
        subtitle_bytes=None,
    )

    assert set(outputs) == {"9:16", "1:1", "16:9"}
    assert all(content for content in outputs.values())
    assert report["scene_count"] == 2
    assert report["source_count"] == 2
    assert report["render_plan_sha256"] == render_plan_sha256
    assert len(set(report["output_sha256"].values())) == 3
    output_path = tmp_path / "governed-output.mp4"
    output_path.write_bytes(outputs["1:1"])
    duration = float(
        subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(output_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )

    def sampled_rgb(at: float) -> bytes:
        return subprocess.run(
            [
                ffmpeg,
                "-v",
                "error",
                "-i",
                str(output_path),
                "-ss",
                f"{at:.3f}",
                "-frames:v",
                "1",
                "-vf",
                "scale=1:1",
                "-pix_fmt",
                "rgb24",
                "-f",
                "rawvideo",
                "pipe:1",
            ],
            check=True,
            capture_output=True,
        ).stdout

    red = sampled_rgb(0.1)
    blue = sampled_rgb(1.5)
    assert duration == pytest.approx(1.75, abs=0.15)
    assert len(red) == len(blue) == 3
    assert red[0] > red[2]
    assert blue[2] > blue[0]
