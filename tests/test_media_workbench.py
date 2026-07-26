from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.domain import (
    ContentAsset,
    ContentStatus,
    ContentType,
    Product,
)
from apps.control_plane.media_workbench import (
    MediaExecutionRow,
    MediaWorkbenchService,
)
from apps.control_plane.sql_repository import Base, SqlAlchemyRepository


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
    manifest = service.delivery_manifest(video.id, requested_by="reviewer-1")
    replay = service.delivery_manifest(video.id, requested_by="reviewer-1")
    assert manifest["manifest_id"] == replay["manifest_id"]
    assert manifest["listing_eligible"] is True
    assert manifest["encoder_version"] == "ffmpeg-7.1"
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
