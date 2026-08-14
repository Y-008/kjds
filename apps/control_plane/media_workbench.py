from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
import time
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    or_,
    select,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import ContentStatus, ContentType, new_id
from .evidence import EvidenceBlobRow, EvidenceGrade, EvidenceRecordRow
from .media_jobs import (
    EDITING_MAX_SCENE_DURATION_MS,
    EDITING_MAX_TIMELINE_DURATION_MS,
    EDITING_TARGET_CHANNELS,
    EDITING_TARGET_LOCALE,
    FFMPEG_RENDER_PROFILE_SHA256,
    GOVERNED_RENDER_RATIOS,
    MediaJobResultReceiptRow,
    MediaJobRow,
    canonical_json,
    validate_governed_render_output_bytes,
)
from .sql_repository import Base, ContentAssetRow, ProductRow

TEMPLATE_CATALOG = (
    {
        "id": "ozon-retouch-v1",
        "kind": "image",
        "version": "1",
        "status": "admitted",
        "executor": "comfyui",
        "modes": ["retouch"],
        "fixed_workflow": True,
    },
    {
        "id": "kjds-ffmpeg-product-video-v1",
        "kind": "video",
        "version": "1",
        "status": "admitted",
        "executor": "ffmpeg",
        "modes": ["approved_stills_script_audio"],
        "fixed_workflow": True,
        "aspect_ratios": ["9:16", "1:1", "16:9"],
        "external_generation_provider": False,
    },
    {
        "id": "composite-v1",
        "kind": "image",
        "version": "1",
        "status": "blocked",
        "executor": "comfyui",
        "modes": ["composite"],
        "fixed_workflow": False,
    },
    {
        "id": "infographic-v1",
        "kind": "image",
        "version": "1",
        "status": "blocked",
        "executor": "comfyui",
        "modes": ["infographic"],
        "fixed_workflow": False,
    },
)


class MediaExecutionRow(Base):
    __tablename__ = "media_executions"
    __table_args__ = (
        UniqueConstraint(
            "asset_id", "idempotency_key", name="uq_media_asset_idempotency"
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    asset_id: Mapped[str] = mapped_column(
        ForeignKey("content_assets.id"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False)
    media_kind: Mapped[str] = mapped_column(String, nullable=False)
    template_id: Mapped[str] = mapped_column(String, nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    queued_by: Mapped[str] = mapped_column(String, nullable=False)
    queued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    lease_owner: Mapped[str | None] = mapped_column(String, nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_amount: Mapped[Decimal] = mapped_column(
        Numeric(38, 12), nullable=False
    )
    cost_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    outputs_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)


class MediaDeliveryManifestRow(Base):
    __tablename__ = "media_delivery_manifests"
    __table_args__ = (
        UniqueConstraint("asset_id", "asset_state_sha256", name="uq_media_manifest_state"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    asset_id: Mapped[str] = mapped_column(
        ForeignKey("content_assets.id"), nullable=False
    )
    execution_id: Mapped[str | None] = mapped_column(
        ForeignKey("media_executions.id"), nullable=True
    )
    asset_state_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class MediaExecutionEventRow(Base):
    __tablename__ = "media_execution_events"
    __table_args__ = (
        UniqueConstraint(
            "execution_id",
            "sequence",
            name="uq_media_execution_event_sequence",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    execution_id: Mapped[str] = mapped_column(
        ForeignKey("media_executions.id"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    from_status: Mapped[str | None] = mapped_column(String, nullable=True)
    to_status: Mapped[str] = mapped_column(String, nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class MediaWorkbenchService:
    CONTRACT_ID = "kjds-media-workbench-v1"
    READ_SOURCE_CONTRACT_ID = "kjds-scoped-media-read-source-v1"

    def __init__(
        self,
        *,
        engine,
        repository,
        evidence,
        image_execution,
    ) -> None:
        self.engine = engine
        self.repo = repository
        self.evidence = evidence
        self.image_execution = image_execution

    def snapshot(self, *, product_id: str | None = None) -> dict[str, Any]:
        with Session(self.engine) as session:
            query = select(MediaExecutionRow).order_by(
                MediaExecutionRow.queued_at.desc()
            )
            executions = list(session.scalars(query.limit(200)).all())
            asset_query = select(ContentAssetRow).order_by(
                ContentAssetRow.created_at.desc(),
                ContentAssetRow.id,
            )
            if product_id:
                asset_query = asset_query.where(
                    ContentAssetRow.product_id == product_id
                )
            assets = list(session.scalars(asset_query.limit(500)).all())
            manifests = list(
                session.scalars(
                    select(MediaDeliveryManifestRow).order_by(
                        MediaDeliveryManifestRow.created_at.desc()
                    )
                ).all()
            )
        payload = {
            "contract_id": self.CONTRACT_ID,
            "status": (
                "no_data"
                if not executions and not assets
                else "partial"
                if any(row.status in {"blocked", "failed"} for row in executions)
                else "ready"
            ),
            "product_id": product_id,
            "templates": [dict(template) for template in TEMPLATE_CATALOG],
            "assets": [self._asset_row(asset) for asset in assets],
            "executions": [self._execution(row) for row in executions],
            "manifests": [row.payload_json for row in manifests[:100]],
            "summary": {
                "asset_count": len(assets),
                "execution_count": len(executions),
                "failed_count": sum(
                    row.status == "failed" for row in executions
                ),
                "blocked_count": sum(
                    row.status == "blocked" for row in executions
                ),
                "manifest_count": len(manifests),
            },
            "control_envelope": {
                "external_video_provider_enabled": False,
                "postgres_lease_only": True,
                "redis_kafka_temporal_used": False,
                "listing_requires_all_qa_passed": True,
                "external_marketplace_write_allowed": False,
            },
        }
        payload["snapshot_sha256"] = self._hash(payload)
        return payload

    def read_sources(
        self,
        *,
        asset_ids: list[str],
        as_of: datetime,
        max_assets: int = 2000,
        max_executions: int = 5000,
        max_events: int = 10000,
        max_manifests: int = 2000,
    ) -> dict[str, Any]:
        """Read only pre-authorized media rows at an exact temporal cutoff."""

        if as_of.tzinfo is None:
            raise ValueError("Media read-source as_of must include a timezone")
        cutoff = as_of.astimezone(UTC)
        normalized = sorted(
            {
                str(asset_id).strip()
                for asset_id in asset_ids
                if str(asset_id).strip()
            }
        )
        for value, field in (
            (max_assets, "max_assets"),
            (max_executions, "max_executions"),
            (max_events, "max_events"),
            (max_manifests, "max_manifests"),
        ):
            if not 1 <= value <= 20000:
                raise ValueError(f"{field} must be between 1 and 20000")
        if not normalized:
            payload = {
                "contract_id": self.READ_SOURCE_CONTRACT_ID,
                "as_of": cutoff.isoformat(),
                "authorized_asset_ids": [],
                "assets": [],
                "executions": [],
                "events": [],
                "manifests": [],
                "truncated": {
                    "assets": False,
                    "executions": False,
                    "events": False,
                    "manifests": False,
                },
                "raw_read": False,
            }
            payload["snapshot_sha256"] = self._hash(payload)
            return payload

        with Session(self.engine) as session:
            asset_rows = list(
                session.scalars(
                    select(ContentAssetRow)
                    .where(
                        ContentAssetRow.id.in_(normalized),
                        ContentAssetRow.created_at <= cutoff,
                    )
                    .order_by(ContentAssetRow.created_at, ContentAssetRow.id)
                    .limit(max_assets + 1)
                ).all()
            )
            execution_rows = list(
                session.scalars(
                    select(MediaExecutionRow)
                    .where(
                        MediaExecutionRow.asset_id.in_(normalized),
                        MediaExecutionRow.queued_at <= cutoff,
                    )
                    .order_by(
                        MediaExecutionRow.asset_id,
                        MediaExecutionRow.queued_at,
                        MediaExecutionRow.id,
                    )
                    .limit(max_executions + 1)
                ).all()
            )
            execution_ids = [row.id for row in execution_rows[:max_executions]]
            event_rows = (
                list(
                    session.scalars(
                        select(MediaExecutionEventRow)
                        .where(
                            MediaExecutionEventRow.execution_id.in_(
                                execution_ids
                            ),
                            MediaExecutionEventRow.occurred_at <= cutoff,
                        )
                        .order_by(
                            MediaExecutionEventRow.execution_id,
                            MediaExecutionEventRow.sequence,
                            MediaExecutionEventRow.occurred_at,
                            MediaExecutionEventRow.id,
                        )
                        .limit(max_events + 1)
                    ).all()
                )
                if execution_ids
                else []
            )
            manifest_rows = list(
                session.scalars(
                    select(MediaDeliveryManifestRow)
                    .where(
                        MediaDeliveryManifestRow.asset_id.in_(normalized),
                        MediaDeliveryManifestRow.created_at <= cutoff,
                    )
                    .order_by(
                        MediaDeliveryManifestRow.asset_id,
                        MediaDeliveryManifestRow.created_at,
                        MediaDeliveryManifestRow.id,
                    )
                    .limit(max_manifests + 1)
                ).all()
            )

        truncated = {
            "assets": len(asset_rows) > max_assets,
            "executions": len(execution_rows) > max_executions,
            "events": len(event_rows) > max_events,
            "manifests": len(manifest_rows) > max_manifests,
        }
        payload = {
            "contract_id": self.READ_SOURCE_CONTRACT_ID,
            "as_of": cutoff.isoformat(),
            "authorized_asset_ids": normalized,
            "assets": [
                {
                    **self._asset_row(row),
                    "source_facts": row.source_facts_json,
                    "created_at": self._iso(row.created_at),
                }
                for row in asset_rows[:max_assets]
            ],
            "executions": [
                self._execution(row)
                for row in execution_rows[:max_executions]
            ],
            "events": [
                self._event(row)
                for row in event_rows[:max_events]
            ],
            "manifests": [
                self._manifest_source(row)
                for row in manifest_rows[:max_manifests]
            ],
            "truncated": truncated,
            "raw_read": True,
        }
        payload["snapshot_sha256"] = self._hash(payload)
        return payload

    def queue(
        self,
        asset_id: str,
        *,
        idempotency_key: str,
        requested_by: str,
        retry: bool = False,
    ) -> dict[str, Any]:
        key = self._text(idempotency_key, "idempotency_key")
        actor = self._text(requested_by, "requested_by")
        asset = self.repo.get_content_asset(asset_id)
        template = self._template(asset)
        input_sha = self._hash(
            {
                "asset_id": asset.id,
                "product_id": asset.product_id,
                "content_type": asset.content_type.value,
                "brief": asset.brief,
                "template_id": template["id"],
            }
        )
        with Session(self.engine) as session:
            existing = session.scalar(
                select(MediaExecutionRow).where(
                    MediaExecutionRow.asset_id == asset_id,
                    MediaExecutionRow.idempotency_key == key,
                )
            )
            if existing is not None:
                if existing.input_sha256 != input_sha:
                    raise ValueError(
                        "Media execution idempotency conflict"
                    )
                return self._execution(existing)
            latest = session.scalar(
                select(MediaExecutionRow)
                .where(MediaExecutionRow.asset_id == asset_id)
                .order_by(MediaExecutionRow.queued_at.desc())
            )
            if retry and (
                latest is None or latest.status not in {"failed", "blocked"}
            ):
                raise ValueError("Retry requires a failed or blocked execution")

        now = datetime.now(UTC)
        if template["status"] != "admitted":
            status = "blocked"
            error_code = "TEMPLATE_NOT_ADMITTED"
            error_detail = "Template is not admitted for execution"
        elif asset.content_type is ContentType.IMAGE:
            generated = self.image_execution.queue(
                asset.id, requested_by=actor
            )
            status = generated.status.value
            error_code = None
            error_detail = None
        elif asset.content_type is ContentType.VIDEO:
            self._validate_video_brief(asset)
            status = "queued"
            error_code = None
            error_detail = None
        else:
            status = "blocked"
            error_code = "UNSUPPORTED_MEDIA_KIND"
            error_detail = "Only image and video assets use the media workbench"
        row = MediaExecutionRow(
            id=new_id("mex"),
            asset_id=asset.id,
            idempotency_key=key,
            media_kind=asset.content_type.value,
            template_id=template["id"],
            input_sha256=input_sha,
            status=status,
            attempt=(latest.attempt + 1 if latest is not None else 1),
            queued_by=actor,
            queued_at=now,
            lease_owner=None,
            lease_expires_at=None,
            started_at=None,
            completed_at=None,
            latency_ms=None,
            cost_amount=Decimal("0"),
            cost_currency="CNY",
            outputs_json={},
            error_code=error_code,
            error_detail=error_detail,
        )
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            session.add(row)
            session.flush()
            self._append_event(
                session,
                row=row,
                event_type="queued" if status == "queued" else status,
                from_status=None,
                to_status=status,
                payload={
                    "input_sha256": input_sha,
                    "automatic_business_action": False,
                },
                actor_id=actor,
                occurred_at=now,
            )
            return self._execution(row)

    def queue_batch(
        self,
        *,
        idempotency_key: str,
        items: list[dict[str, Any]],
        requested_by: str,
    ) -> dict[str, Any]:
        key = self._text(idempotency_key, "idempotency_key")
        actor = self._text(requested_by, "requested_by")
        if not 1 <= len(items) <= 100:
            raise ValueError("Media batch must contain between 1 and 100 items")
        normalized = [
            {
                "asset_id": self._text(item.get("asset_id"), "asset_id"),
                "idempotency_key": self._text(
                    item.get("idempotency_key"), "item.idempotency_key"
                ),
                "retry": bool(item.get("retry", False)),
            }
            for item in items
        ]
        batch_sha = self._hash(
            {
                "idempotency_key": key,
                "items": normalized,
                "requested_by": actor,
            }
        )
        results: list[dict[str, Any]] = []
        for item in normalized:
            try:
                execution = self.queue(
                    item["asset_id"],
                    idempotency_key=item["idempotency_key"],
                    requested_by=actor,
                    retry=item["retry"],
                )
                results.append(
                    {
                        "asset_id": item["asset_id"],
                        "status": execution["status"],
                        "execution": execution,
                        "error": None,
                    }
                )
            except (KeyError, ValueError) as exc:
                results.append(
                    {
                        "asset_id": item["asset_id"],
                        "status": "failed",
                        "execution": None,
                        "error": {
                            "code": type(exc).__name__,
                            "detail": str(exc),
                        },
                    }
                )
        completed = sum(item["execution"] is not None for item in results)
        failed = len(results) - completed
        return {
            "contract_id": "kjds-media-batch-execution-v1",
            "batch_id": f"mbt_{batch_sha[:24]}",
            "idempotency_key": key,
            "input_sha256": batch_sha,
            "status": (
                "failed"
                if completed == 0
                else "partial"
                if failed
                else "accepted"
            ),
            "summary": {
                "item_count": len(results),
                "accepted_count": completed,
                "failed_count": failed,
            },
            "items": results,
            "external_side_effect": False,
        }

    def sync(self, asset_id: str, *, requested_by: str) -> dict[str, Any]:
        actor = self._text(requested_by, "requested_by")
        asset = self.repo.get_content_asset(asset_id)
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            row = session.scalar(
                select(MediaExecutionRow)
                .where(MediaExecutionRow.asset_id == asset_id)
                .order_by(MediaExecutionRow.queued_at.desc())
            )
            if row is None:
                raise KeyError(f"Unknown media execution for asset: {asset_id}")
            if asset.content_type is ContentType.IMAGE:
                previous = row.status
                synced = self.image_execution.sync(
                    asset_id, requested_by=actor
                )
                row.status = synced.status.value
                if synced.artifact_ref:
                    row.outputs_json = {
                        "artifact_evidence_id": synced.artifact_ref
                    }
                if synced.status in {
                    ContentStatus.GENERATED,
                    ContentStatus.APPROVED,
                    ContentStatus.QA_FAILED,
                    ContentStatus.EXECUTION_FAILED,
                }:
                    row.completed_at = datetime.now(UTC)
                    row.latency_ms = self._latency(
                        row.queued_at, row.completed_at
                    )
                if synced.status is ContentStatus.EXECUTION_FAILED:
                    row.status = "failed"
                    row.error_code = str(
                        synced.generation.get(
                            "failure_code", "IMAGE_EXECUTION_FAILED"
                        )
                    )
                if row.status != previous:
                    self._append_event(
                        session,
                        row=row,
                        event_type="synced",
                        from_status=previous,
                        to_status=row.status,
                        payload={"outputs": row.outputs_json},
                        actor_id=actor,
                        occurred_at=datetime.now(UTC),
                    )
            session.flush()
            return self._execution(row)

    def claim_video(
        self,
        *,
        worker_id: str,
        lease_seconds: int = 300,
    ) -> dict[str, Any] | None:
        worker = self._text(worker_id, "worker_id")
        if not 30 <= lease_seconds <= 1800:
            raise ValueError("lease_seconds must be between 30 and 1800")
        now = datetime.now(UTC)
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            row = session.scalar(
                select(MediaExecutionRow)
                .where(
                    MediaExecutionRow.media_kind == ContentType.VIDEO.value,
                    or_(
                        MediaExecutionRow.status == "queued",
                        (
                            (MediaExecutionRow.status == "claimed")
                            & (MediaExecutionRow.lease_expires_at <= now)
                        ),
                    ),
                )
                .order_by(MediaExecutionRow.queued_at)
                .with_for_update(skip_locked=True)
            )
            if row is None:
                return None
            previous = row.status
            row.status = "claimed"
            row.lease_owner = worker
            row.lease_expires_at = now + timedelta(seconds=lease_seconds)
            row.started_at = row.started_at or now
            session.flush()
            self._append_event(
                session,
                row=row,
                event_type="claimed",
                from_status=previous,
                to_status="claimed",
                payload={
                    "lease_expires_at": self._iso(row.lease_expires_at),
                },
                actor_id=worker,
                occurred_at=now,
            )
            result = self._execution(row)
            asset_id = row.asset_id
        asset = self.repo.get_content_asset(asset_id)
        result["ffmpeg_commands"] = FfmpegMediaWorker.commands(asset.brief)
        return result

    def complete_video(
        self,
        execution_id: str,
        *,
        worker_id: str,
        outputs: dict[str, bytes],
        subtitle_bytes: bytes,
        cover_bytes: bytes,
        keyframe_bytes: bytes,
        encoder_report: dict[str, Any],
        cost_amount: Decimal,
        cost_currency: str,
    ) -> dict[str, Any]:
        worker = self._text(worker_id, "worker_id")
        expected = {"9:16", "1:1", "16:9"}
        if set(outputs) != expected or any(not value for value in outputs.values()):
            raise ValueError("Video worker must return all three non-empty ratios")
        amount = self._decimal(cost_amount, "cost_amount")
        currency = self._currency(cost_currency)
        now = datetime.now(UTC)
        with Session(self.engine) as session:
            row = session.get(MediaExecutionRow, execution_id)
            if row is None:
                raise KeyError(f"Unknown media execution: {execution_id}")
            if row.status != "claimed" or row.lease_owner != worker:
                raise ValueError("Video execution requires the active lease owner")
            if row.lease_expires_at is None or self._aware(
                row.lease_expires_at
            ) <= now:
                raise ValueError("Video execution lease expired")
            asset = self.repo.get_content_asset(row.asset_id)
        captured: dict[str, str] = {}
        for ratio in GOVERNED_RENDER_RATIOS:
            content = outputs[ratio]
            record = self.evidence.capture(
                content=content,
                filename=f"{asset.id}-{ratio.replace(':', 'x')}.mp4",
                content_type="video/mp4",
                source="kjds-ffmpeg-legacy-media-worker",
                source_ref=f"media://{execution_id}/{ratio}",
                grade=EvidenceGrade.B,
                effective_at=now.isoformat(),
                effective_until=None,
                created_by=worker,
                metadata={
                    "retention_class": "operational",
                    "content_asset_id": asset.id,
                    "execution_id": execution_id,
                    "template_id": "kjds-ffmpeg-product-video-v1",
                    "aspect_ratio": ratio,
                    "input_sha256": row.input_sha256,
                    "encoder_version": encoder_report.get(
                        "encoder_version", "unknown"
                    ),
                },
            )
            self.evidence.link(
                evidence_id=record.id,
                target_type="content_asset",
                target_id=asset.id,
                relationship=f"generated_video_{ratio}",
                created_by=worker,
            )
            captured[ratio] = record.id
        auxiliaries = {}
        for label, content, filename, content_type in (
            ("subtitle", subtitle_bytes, f"{asset.id}.srt", "application/x-subrip"),
            ("cover", cover_bytes, f"{asset.id}-cover.jpg", "image/jpeg"),
            ("keyframe", keyframe_bytes, f"{asset.id}-keyframe.jpg", "image/jpeg"),
            (
                "encoder_report",
                json.dumps(
                    encoder_report, ensure_ascii=False, sort_keys=True
                ).encode(),
                f"{asset.id}-encoder-report.json",
                "application/json",
            ),
        ):
            if not content:
                raise ValueError(f"Video worker output {label} is empty")
            record = self.evidence.capture(
                content=content,
                filename=filename,
                content_type=content_type,
                source="kjds-ffmpeg-legacy-media-worker",
                source_ref=f"media://{execution_id}/{label}",
                grade=EvidenceGrade.B,
                effective_at=now.isoformat(),
                effective_until=None,
                created_by=worker,
                metadata={
                    "retention_class": "operational",
                    "content_asset_id": asset.id,
                    "execution_id": execution_id,
                    "template_id": "kjds-ffmpeg-product-video-v1",
                    "input_sha256": row.input_sha256,
                },
            )
            auxiliaries[label] = record.id
        asset.status = ContentStatus.GENERATED
        asset.artifact_ref = captured["9:16"]
        asset.generation = {
            **asset.generation,
            "executor": "ffmpeg",
            "template_id": "kjds-ffmpeg-product-video-v1",
            "execution_id": execution_id,
            "input_sha256": row.input_sha256,
            "outputs": captured,
            "auxiliaries": auxiliaries,
            "encoder_version": encoder_report.get(
                "encoder_version", "unknown"
            ),
            "completed_at": now.isoformat(),
        }
        with self.repo.transaction():
            self.repo.save_content_asset(asset)
            self.repo.append_event(
                "content.video_generation_completed",
                asset.id,
                {
                    "execution_id": execution_id,
                    "output_evidence_ids": captured,
                },
                actor_id=worker,
                source_evidence_id=captured["9:16"],
            )
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            row = session.get(MediaExecutionRow, execution_id)
            if row is None:
                raise KeyError(f"Unknown media execution: {execution_id}")
            row.status = "generated"
            row.completed_at = now
            row.latency_ms = self._latency(row.queued_at, now)
            row.cost_amount = amount
            row.cost_currency = currency
            row.outputs_json = {
                "videos": captured,
                "auxiliaries": auxiliaries,
                "output_sha256": {
                    ratio: hashlib.sha256(content).hexdigest()
                    for ratio, content in outputs.items()
                },
                "encoder_report": encoder_report,
            }
            row.lease_owner = None
            row.lease_expires_at = None
            self._append_event(
                session,
                row=row,
                event_type="generated",
                from_status="claimed",
                to_status="generated",
                payload={
                    "output_evidence_ids": {
                        **captured,
                        **auxiliaries,
                    },
                    "encoder_report": encoder_report,
                },
                actor_id=worker,
                occurred_at=now,
            )
            session.flush()
            return self._execution(row)

    def fail_video(
        self,
        execution_id: str,
        *,
        worker_id: str,
        error_code: str,
        error_detail: str,
    ) -> dict[str, Any]:
        worker = self._text(worker_id, "worker_id")
        code = self._text(error_code, "error_code")
        detail = self._text(error_detail, "error_detail", maximum=2000)
        now = datetime.now(UTC)
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            row = session.get(MediaExecutionRow, execution_id)
            if row is None:
                raise KeyError(f"Unknown media execution: {execution_id}")
            if row.lease_owner != worker:
                raise ValueError("Only the active lease owner may fail the job")
            row.status = "failed"
            row.completed_at = now
            row.latency_ms = self._latency(row.queued_at, now)
            row.error_code = code
            row.error_detail = detail
            row.lease_owner = None
            row.lease_expires_at = None
            self._append_event(
                session,
                row=row,
                event_type="failed",
                from_status="claimed",
                to_status="failed",
                payload={"error_code": code, "error_detail": detail},
                actor_id=worker,
                occurred_at=now,
            )
            session.flush()
            return self._execution(row)

    def execute_video(
        self,
        execution_id: str,
        *,
        worker_id: str,
    ) -> dict[str, Any]:
        worker = self._text(worker_id, "worker_id")
        ffmpeg = os.getenv("KJDS_FFMPEG_PATH") or shutil.which("ffmpeg")
        ffprobe = os.getenv("KJDS_FFPROBE_PATH") or shutil.which("ffprobe")
        if ffmpeg is None or ffprobe is None:
            self.fail_video(
                execution_id,
                worker_id=worker,
                error_code="FFMPEG_UNAVAILABLE",
                error_detail="Local FFmpeg and ffprobe executables are required",
            )
            raise RuntimeError("Local FFmpeg and ffprobe executables are required")
        with Session(self.engine) as session:
            row = session.get(MediaExecutionRow, execution_id)
            if row is None:
                raise KeyError(f"Unknown media execution: {execution_id}")
            if row.status != "claimed" or row.lease_owner != worker:
                raise ValueError("Video execution requires the active lease owner")
            asset = self.repo.get_content_asset(row.asset_id)
        try:
            with tempfile.TemporaryDirectory(prefix=f"kjds-{execution_id}-") as raw_dir:
                workdir = Path(raw_dir)
                image_id = str(asset.brief["approved_image_asset_ids"][0])
                image_asset = self.repo.get_content_asset(image_id)
                if not image_asset.artifact_ref:
                    raise ValueError("Approved source image has no Evidence artifact")
                image_bytes, image_record = self.evidence.content(
                    image_asset.artifact_ref
                )
                subtitle_bytes, subtitle_record = self.evidence.content(
                    str(asset.brief["subtitle_evidence_id"])
                )
                audio_bytes, audio_record = self.evidence.content(
                    str(asset.brief["audio_rights_evidence_id"])
                )
                image_path = workdir / self._input_filename(
                    "source", image_record.filename, ".png"
                )
                subtitle_path = workdir / "subtitles.srt"
                audio_path = workdir / self._input_filename(
                    "audio", audio_record.filename, ".wav"
                )
                image_path.write_bytes(image_bytes)
                subtitle_path.write_bytes(subtitle_bytes)
                audio_path.write_bytes(audio_bytes)
                duration = int(asset.brief.get("duration_seconds", 6))
                if not 3 <= duration <= 30:
                    raise ValueError(
                        "Video duration_seconds must be between 3 and 30"
                    )
                encoded: dict[str, bytes] = {}
                commands: list[list[str]] = []
                for ratio, size in FfmpegMediaWorker.RATIO_SIZES.items():
                    output_path = workdir / (
                        f"output-{ratio.replace(':', 'x')}.mp4"
                    )
                    command = FfmpegMediaWorker.encode_command(
                        ffmpeg=ffmpeg,
                        image_path=image_path,
                        audio_path=audio_path,
                        subtitle_path=subtitle_path,
                        output_path=output_path,
                        size=size,
                        duration=duration,
                    )
                    self._run_media_command(command, workdir=workdir)
                    commands.append(command)
                    encoded[ratio] = output_path.read_bytes()
                primary_path = workdir / "output-9x16.mp4"
                cover_path = workdir / "cover.jpg"
                keyframe_path = workdir / "keyframe.jpg"
                for second, target in (
                    ("0", cover_path),
                    (str(max(1, duration // 2)), keyframe_path),
                ):
                    command = [
                        ffmpeg,
                        "-nostdin",
                        "-y",
                        "-ss",
                        second,
                        "-i",
                        str(primary_path),
                        "-frames:v",
                        "1",
                        "-q:v",
                        "2",
                        str(target),
                    ]
                    self._run_media_command(command, workdir=workdir)
                    commands.append(command)
                probe = subprocess.run(
                    [
                        ffprobe,
                        "-v",
                        "error",
                        "-show_format",
                        "-show_streams",
                        "-of",
                        "json",
                        str(primary_path),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                )
                encoder_report = {
                    "encoder_version": self._ffmpeg_version(ffmpeg),
                    "template_id": FfmpegMediaWorker.VERSION,
                    "input_evidence_ids": [
                        image_asset.artifact_ref,
                        str(asset.brief["script_evidence_id"]),
                        str(asset.brief["subtitle_evidence_id"]),
                        str(asset.brief["audio_rights_evidence_id"]),
                    ],
                    "script_language": "ru",
                    "duration_seconds": duration,
                    "commands_sha256": self._hash(
                        {"commands": commands}
                    ),
                    "probe": json.loads(probe.stdout),
                }
                return self.complete_video(
                    execution_id,
                    worker_id=worker,
                    outputs=encoded,
                    subtitle_bytes=subtitle_bytes,
                    cover_bytes=cover_path.read_bytes(),
                    keyframe_bytes=keyframe_path.read_bytes(),
                    encoder_report=encoder_report,
                    cost_amount=Decimal("0"),
                    cost_currency="CNY",
                )
        except Exception as exc:
            with suppress(KeyError, ValueError):
                self.fail_video(
                    execution_id,
                    worker_id=worker,
                    error_code="FFMPEG_EXECUTION_FAILED",
                    error_detail=str(exc)[:2000],
                )
            raise

    def delivery_manifest(
        self, asset_id: str, *, requested_by: str
    ) -> dict[str, Any]:
        actor = self._text(requested_by, "requested_by")
        asset = self.repo.get_content_asset(asset_id)
        if asset.status is not ContentStatus.APPROVED:
            raise ValueError("Delivery manifest requires all QA checks to pass")
        evidence_ids = list(
            dict.fromkeys(
                [
                    asset.artifact_ref,
                    *asset.generation.get("outputs", {}).values(),
                    *asset.generation.get("auxiliaries", {}).values(),
                ]
            )
        )
        evidence_ids = [value for value in evidence_ids if value]
        self.evidence.require_valid(evidence_ids)
        state = {
            "asset_id": asset.id,
            "product_id": asset.product_id,
            "content_type": asset.content_type.value,
            "status": asset.status.value,
            "artifact_evidence_ids": sorted(evidence_ids),
            "qa_results": asset.qa_results,
            "generation": asset.generation,
        }
        state_sha = self._hash(state)
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            existing = session.scalar(
                select(MediaDeliveryManifestRow).where(
                    MediaDeliveryManifestRow.asset_id == asset_id,
                    MediaDeliveryManifestRow.asset_state_sha256 == state_sha,
                )
            )
            if existing is not None:
                return existing.payload_json
            generation_execution_id = asset.generation.get("execution_id")
            execution = None
            if generation_execution_id:
                execution = session.scalar(
                    select(MediaExecutionRow).where(
                        MediaExecutionRow.id == generation_execution_id,
                        MediaExecutionRow.asset_id == asset_id,
                    )
                )
                if execution is None or execution.status != "generated":
                    raise ValueError("Delivery manifest generation seal is not admitted")
                if execution.input_sha256 != asset.generation.get("input_sha256"):
                    raise ValueError("Delivery manifest generation input drifted")
            payload = {
                "contract_id": "kjds-media-delivery-manifest-v1",
                "manifest_id": None,
                "asset_id": asset.id,
                "product_id": asset.product_id,
                "content_type": asset.content_type.value,
                "execution_id": execution.id if execution else None,
                "qa_status": "passed",
                "listing_eligible": True,
                "artifact_evidence_ids": sorted(evidence_ids),
                "input_sha256": (
                    execution.input_sha256 if execution else None
                ),
                "template_id": (
                    execution.template_id if execution else None
                ),
                "encoder_version": asset.generation.get(
                    "encoder_version"
                ),
                "latency_ms": execution.latency_ms if execution else None,
                "cost": {
                    "amount": str(execution.cost_amount)
                    if execution
                    else "0",
                    "currency": execution.cost_currency
                    if execution
                    else "CNY",
                },
                "created_at": datetime.now(UTC).isoformat(),
                "external_marketplace_write": False,
            }
            manifest_id = new_id("mdm")
            payload["manifest_id"] = manifest_id
            manifest_sha = self._hash(payload)
            payload["manifest_sha256"] = manifest_sha
            row = MediaDeliveryManifestRow(
                id=manifest_id,
                asset_id=asset.id,
                execution_id=execution.id if execution else None,
                asset_state_sha256=state_sha,
                manifest_sha256=manifest_sha,
                payload_json=payload,
                created_by=actor,
                created_at=datetime.now(UTC),
            )
            session.add(row)
            return payload

    def validate_editing_handoff(
        self,
        *,
        principal,
        store_ref: str,
        job_ref: str,
        reference_asset_refs: tuple[str, ...],
        render_plan_sha256: str,
    ) -> None:
        """Validate a blueprint handoff without claiming or executing a Job."""

        self._text(store_ref, "store_ref")
        self._text(job_ref, "job_ref")
        if (
            not isinstance(reference_asset_refs, tuple)
            or not reference_asset_refs
            or len(set(reference_asset_refs)) != len(reference_asset_refs)
            or any(
                not isinstance(ref, str)
                or not ref.strip()
                or len(ref.strip()) > 500
                or any(char in ref for char in ("\x00", "\n", "\r"))
                for ref in reference_asset_refs
            )
            or not isinstance(render_plan_sha256, str)
            or len(render_plan_sha256) != 64
            or any(char not in "0123456789abcdef" for char in render_plan_sha256.lower())
        ):
            raise ValueError("editing_handoff_contract_invalid")

    @staticmethod
    def _governed_execution_id(job_ref: str, render_plan_sha256: str) -> str:
        digest = hashlib.sha256(
            f"{job_ref}:{render_plan_sha256}".encode()
        ).hexdigest()
        return f"media_job_exec_{digest[:32]}"

    def read_governed_editing_artifact(
        self,
        *,
        job_ref: str,
        render_plan_sha256: str,
        scope: Any,
        as_of: datetime,
    ) -> dict[str, Any] | None:
        """Read the immutable ContentAsset handoff for one governed Job."""

        execution_id = self._governed_execution_id(
            self._text(job_ref, "job_ref"),
            self._text(render_plan_sha256, "render_plan_sha256"),
        )
        with Session(self.engine) as session:
            rows = list(
                session.scalars(
                    select(ContentAssetRow)
                    .where(
                        ContentAssetRow.content_type == ContentType.VIDEO.value,
                        ContentAssetRow.created_at <= as_of,
                    )
                    .order_by(ContentAssetRow.created_at, ContentAssetRow.id)
                ).all()
            )
            matches = [
                row
                for row in rows
                if isinstance(row.generation_json, dict)
                and row.generation_json.get("execution_id") == execution_id
                and row.generation_json.get("media_job_ref") == job_ref
            ]
            receipt = session.scalar(
                select(MediaJobResultReceiptRow).where(
                    MediaJobResultReceiptRow.job_ref == job_ref
                )
            )
            if not matches:
                if receipt is not None:
                    raise RuntimeError("governed_editing_receipt_without_artifact")
                return None
            if len(matches) != 1:
                raise RuntimeError("governed_editing_artifact_ambiguous")
            row = matches[0]
            generation = row.generation_json
            outputs = generation.get("outputs") if isinstance(generation, dict) else None
            job = session.get(MediaJobRow, job_ref)
            product = session.get(ProductRow, row.product_id)
            receipt_sha256 = generation.get("result_receipt_sha256")
            if (
                receipt is None
                or job is None
                or product is None
                or row.status != ContentStatus.GENERATED.value
                or generation.get("executor") != "ffmpeg"
                or generation.get("render_plan_sha256") != render_plan_sha256
                or not isinstance(receipt_sha256, str)
                or len(receipt_sha256) != 64
                or receipt.receipt_sha256 != receipt_sha256
                or receipt.state != "SUCCEEDED"
                or receipt.result_kind != "video_artifact_evidence"
                or receipt.content_asset_ref != row.id
                or receipt.tenant_ref != scope.tenant_ref
                or receipt.entity_ref != scope.entity_ref
                or receipt.store_ref != scope.store_ref
                or receipt.scope_grant_authority_sha256 != scope.authority_sha256
                or job.subject_actor_id != scope.subject_actor_id
                or product.tenant_ref != scope.tenant_ref
                or product.entity_ref != scope.entity_ref
                or product.store_ref != scope.store_ref
                or product.scope_grant_authority_sha256 != scope.authority_sha256
                or not isinstance(outputs, dict)
                or set(outputs) != set(FfmpegMediaWorker.RATIO_SIZES)
                or len(set(outputs.values())) != len(outputs)
                or receipt.artifact_evidence_refs
                != [outputs[ratio] for ratio in GOVERNED_RENDER_RATIOS]
            ):
                raise RuntimeError("governed_editing_artifact_drifted")
            for ratio, evidence_id in outputs.items():
                record = session.get(EvidenceRecordRow, str(evidence_id))
                blob = (
                    session.get(EvidenceBlobRow, record.blob_sha256)
                    if record is not None
                    else None
                )
                metadata = record.metadata_json if record is not None else None
                if (
                    record is None
                    or blob is None
                    or record.source != "kjds-ffmpeg-media-worker"
                    or record.source_ref
                    != f"media-job://{job_ref}/artifact/{execution_id}/{ratio}"
                    or hashlib.sha256(blob.content_bytes).hexdigest() != blob.sha256
                    or metadata
                    != {
                        "contract_id": "kjds-governed-media-job-artifact-v1",
                        "tenant_ref": scope.tenant_ref,
                        "entity_ref": scope.entity_ref,
                        "store_ref": scope.store_ref,
                        "scope_grant_authority_sha256": scope.authority_sha256,
                        "subject_actor_id": scope.subject_actor_id,
                        "artifact_sha256": blob.sha256,
                        "media_job_ref": job_ref,
                        "content_asset_id": row.id,
                        "execution_id": execution_id,
                        "aspect_ratio": ratio,
                        "render_plan_sha256": render_plan_sha256,
                    }
                ):
                    raise RuntimeError("governed_editing_artifact_evidence_drifted")
            return {
                "content_asset_ref": row.id,
                "execution_id": execution_id,
                "artifact_evidence_refs": tuple(
                    outputs[ratio] for ratio in GOVERNED_RENDER_RATIOS
                ),
                "outputs": dict(outputs),
                "render_plan_sha256": render_plan_sha256,
                "result_receipt_sha256": receipt_sha256,
            }

    def preflight_governed_editing(
        self,
        *,
        scope: Any,
        source: dict[str, Any],
        render_plan: dict[str, Any],
        render_plan_sha256: str,
        now: datetime,
    ) -> None:
        """Read and validate every immutable render input before Job claim."""

        validation_now = now.astimezone(UTC)

        base_metadata = {
            "rights_status": "approved",
            "tenant_ref": scope.tenant_ref,
            "entity_ref": scope.entity_ref,
            "store_ref": scope.store_ref,
            "scope_grant_authority_sha256": scope.authority_sha256,
            "subject_actor_id": scope.subject_actor_id,
        }

        def validate_record_authority(
            record: Any,
            *,
            error: str,
            expected_metadata: dict[str, Any] | None = None,
        ) -> None:
            metadata = getattr(record, "metadata", None)
            if not isinstance(metadata, dict) or metadata != (
                expected_metadata if expected_metadata is not None else base_metadata
            ):
                raise ValueError(error)
            if getattr(record, "created_by", None) != scope.subject_actor_id:
                raise ValueError(error)
            try:
                effective_at = datetime.fromisoformat(
                    str(record.effective_at).replace("Z", "+00:00")
                )
                recorded_at = datetime.fromisoformat(
                    str(record.recorded_at).replace("Z", "+00:00")
                )
                effective_until = (
                    datetime.fromisoformat(
                        str(record.effective_until).replace("Z", "+00:00")
                    )
                    if record.effective_until
                    else None
                )
            except (AttributeError, TypeError, ValueError) as exc:
                raise ValueError(error) from exc
            if (
                effective_at.tzinfo is None
                or recorded_at.tzinfo is None
                or effective_at.astimezone(UTC) > validation_now
                or recorded_at.astimezone(UTC) > validation_now
                or effective_at.astimezone(UTC) > recorded_at.astimezone(UTC)
                or (
                    effective_until is not None
                    and (
                        effective_until.tzinfo is None
                        or validation_now >= effective_until.astimezone(UTC)
                    )
                )
            ):
                raise ValueError(error)

        def read_record(record_id: str, *, error: str) -> tuple[Any, bytes, Any]:
            record = self.evidence.get(record_id)
            validate_record_authority(record, error=error)
            content, content_record = self.evidence.content(record.id)
            if (
                content_record.id != record.id
                or content_record.byte_size != len(content)
                or record.byte_size != len(content)
                or record.sha256 != hashlib.sha256(content).hexdigest()
                or content_record.sha256 != record.sha256
                or content_record.content_type != record.content_type
                or content_record.filename != record.filename
            ):
                raise ValueError(error)
            return record, content, content_record

        if (
            source.get("target_channels") != list(EDITING_TARGET_CHANNELS)
            or source.get("render_profile_sha256")
            != FFMPEG_RENDER_PROFILE_SHA256
        ):
            raise ValueError("governed_editing_channel_profile_invalid")
        refs = tuple(source.get("reference_asset_refs", ()))
        FfmpegMediaWorker.validate_plan(
            render_plan=dict(render_plan),
            render_plan_sha256=render_plan_sha256,
            executor="ffmpeg",
            reference_asset_refs=refs,
        )
        if not refs or len(refs) > FfmpegMediaWorker.MAX_SOURCE_COUNT:
            raise ValueError("governed_editing_source_asset_invalid")

        declared_artifacts = source.get("input_artifacts")
        if not isinstance(declared_artifacts, list):
            raise ValueError("governed_editing_source_artifact_invalid")
        declared_by_ref = {
            artifact.get("content_asset_ref"): artifact
            for artifact in declared_artifacts
            if isinstance(artifact, dict)
        }
        if len(declared_by_ref) != len(declared_artifacts):
            raise ValueError("governed_editing_source_artifact_invalid")

        expected_roles = {
            **{ref: "campaign" for ref in source.get("campaign_asset_refs", ())},
            **{ref: "reference_video" for ref in refs},
        }
        audio_ref = source.get("audio_asset_ref")
        if isinstance(audio_ref, str):
            expected_roles[audio_ref] = "audio"
        if set(declared_by_ref) != set(expected_roles):
            raise ValueError("governed_editing_source_artifact_invalid")

        video_total = 0
        campaign_total = 0
        actual_reference_artifacts: list[dict[str, str]] = []
        for ref, role in expected_roles.items():
            asset = self.repo.get_content_asset_scoped(
                asset_id=ref.removeprefix("content-asset://"),
                tenant_ref=scope.tenant_ref,
                entity_ref=scope.entity_ref,
                store_ref=scope.store_ref,
                as_of=now,
            )
            if (
                asset.status is not ContentStatus.APPROVED
                or not asset.artifact_ref
                or asset.product_id != source.get("product_id")
            ):
                raise ValueError("governed_editing_source_asset_invalid")
            record, content, content_record = read_record(
                str(asset.artifact_ref), error="governed_editing_source_asset_invalid"
            )
            actual = {
                "content_asset_ref": ref,
                "evidence_ref": f"evidence://{record.id}",
                "evidence_sha256": record.sha256,
                "content_type": record.content_type,
                "role": role,
            }
            if declared_by_ref[ref] != actual:
                raise ValueError("governed_editing_source_artifact_invalid")
            if role == "reference_video":
                FfmpegMediaWorker._validate_video_input(
                    content=content,
                    filename=content_record.filename,
                    content_type=content_record.content_type,
                )
                video_total += len(content)
                actual_reference_artifacts.append(
                    {key: actual[key] for key in (
                        "content_asset_ref", "evidence_ref", "evidence_sha256"
                    )}
                )
            elif role == "audio":
                FfmpegMediaWorker._validate_audio_input(
                    content=content,
                    filename=content_record.filename,
                    content_type=content_record.content_type,
                )
            else:
                FfmpegMediaWorker._validate_campaign_input(
                    content=content,
                    filename=content_record.filename,
                    content_type=content_record.content_type,
                )
                campaign_total += len(content)
        if video_total > FfmpegMediaWorker.MAX_TOTAL_VIDEO_INPUT_BYTES:
            raise ValueError("ffmpeg_video_input_budget_exceeded")
        if campaign_total > FfmpegMediaWorker.MAX_TOTAL_CAMPAIGN_INPUT_BYTES:
            raise ValueError("ffmpeg_campaign_input_budget_exceeded")
        analysis = source.get("analysis_receipt")
        if (
            not isinstance(analysis, dict)
            or analysis.get("source_video_artifacts") != actual_reference_artifacts
        ):
            raise ValueError("governed_editing_analysis_artifact_invalid")
        analysis_ref = analysis.get("evidence_ref")
        if not isinstance(analysis_ref, str) or not analysis_ref.startswith(
            "evidence://"
        ):
            raise ValueError("governed_editing_analysis_artifact_invalid")
        analysis_id = analysis_ref.removeprefix("evidence://")
        analysis_record = self.evidence.get(analysis_id)
        analysis_content, analysis_content_record = self.evidence.content(analysis_id)
        try:
            analysis_payload = json.loads(analysis_content)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("governed_editing_analysis_artifact_invalid") from exc
        semantic_sha = hashlib.sha256(
            canonical_json(analysis_payload)
        ).hexdigest()
        analysis_run_ref = (
            analysis_record.metadata.get("analysis_run_ref")
            if isinstance(analysis_record.metadata, dict)
            else None
        )
        expected_analysis_metadata = {
            **base_metadata,
            "contract_id": "kjds-reference-video-analysis-v1",
            "analysis_run_ref": analysis_run_ref,
            "analysis_contract_sha256": semantic_sha,
            "source_video_artifacts_sha256": hashlib.sha256(
                canonical_json(actual_reference_artifacts)
            ).hexdigest(),
            "schema_version": "1.0.0",
            "observed_at": analysis_record.effective_at,
        }
        validate_record_authority(
            analysis_record,
            error="governed_editing_analysis_artifact_invalid",
            expected_metadata=expected_analysis_metadata,
        )
        if (
            not isinstance(analysis_payload, dict)
            or set(analysis_payload) != {
                "contract_id",
                "schema_version",
                "analysis_run_ref",
                "observed_at",
                "source_video_artifacts",
                "scenes",
                "subtitle_asset_ref",
                "target_channels",
            }
            or analysis_content != canonical_json(analysis_payload)
            or analysis_content_record.id != analysis_record.id
            or analysis_content_record.sha256 != analysis_record.sha256
            or analysis_record.sha256 != hashlib.sha256(analysis_content).hexdigest()
            or analysis_record.sha256 != semantic_sha
            or analysis_record.content_type != "application/json"
            or analysis_record.source != "governed-reference-video-analysis"
            or analysis_record.source_ref
            != f"reference-analysis://{analysis_run_ref}/{semantic_sha}"
            or analysis_payload.get("contract_id")
            != "kjds-reference-video-analysis-v1"
            or analysis_payload.get("schema_version") != "1.0.0"
            or analysis_payload.get("analysis_run_ref") != analysis_run_ref
            or analysis_payload.get("observed_at") != analysis_record.effective_at
            or analysis_payload.get("source_video_artifacts")
            != actual_reference_artifacts
            or analysis_payload.get("scenes") != source.get("scenes")
            or analysis_payload.get("subtitle_asset_ref")
            != source.get("subtitle_asset_ref")
            or analysis_payload.get("target_channels")
            != list(EDITING_TARGET_CHANNELS)
            or analysis.get("semantic_sha256") != semantic_sha
            or analysis.get("evidence_sha256") != semantic_sha
            or analysis.get("observed_at") != analysis_record.effective_at
        ):
            raise ValueError("governed_editing_analysis_artifact_invalid")

        text_total = 0
        caption_refs = {
            str(scene.get("caption_ref", ""))
            for scene in render_plan.get("scenes", ())
        }
        if not caption_refs or any(
            not ref.startswith("evidence://") for ref in caption_refs
        ):
            raise ValueError("governed_editing_caption_invalid")
        for ref in caption_refs:
            _, content, content_record = read_record(
                ref.removeprefix("evidence://"),
                error="governed_editing_caption_invalid",
            )
            FfmpegMediaWorker._validate_text_input(
                content=content,
                filename=content_record.filename,
                content_type=content_record.content_type,
            )
            text_total += len(content)

        subtitle_ref = source.get("subtitle_asset_ref")
        if subtitle_ref is not None:
            if not isinstance(subtitle_ref, str) or not subtitle_ref.startswith(
                "evidence://"
            ):
                raise ValueError("governed_editing_subtitle_invalid")
            _, content, content_record = read_record(
                subtitle_ref.removeprefix("evidence://"),
                error="governed_editing_subtitle_invalid",
            )
            FfmpegMediaWorker._validate_text_input(
                content=content,
                filename=content_record.filename,
                content_type=content_record.content_type,
            )
            text_total += len(content)
        if text_total > FfmpegMediaWorker.MAX_TOTAL_TEXT_INPUT_BYTES:
            raise ValueError("ffmpeg_text_input_budget_exceeded")

    def execute_governed_editing(
        self,
        *,
        principal: Any,
        store_ref: str,
        job_ref: str,
        scope: Any,
        source: dict[str, Any],
        render_plan: dict[str, Any],
        render_plan_sha256: str,
        ffmpeg_adapter: Any,
        result_recorder: Any,
        now: datetime,
    ) -> dict[str, Any]:
        """Render once and attach outputs to the existing ContentAsset truth."""

        deadline = time.monotonic() + FfmpegMediaWorker.RENDER_BUDGET_SECONDS
        existing = self.read_governed_editing_artifact(
            job_ref=job_ref,
            render_plan_sha256=render_plan_sha256,
            scope=scope,
            as_of=now,
        )
        if existing is not None:
            return existing
        if not callable(result_recorder):
            raise ValueError("governed_editing_guard_not_admitted")
        self.preflight_governed_editing(
            scope=scope,
            source=source,
            render_plan=render_plan,
            render_plan_sha256=render_plan_sha256,
            now=now,
        )
        if (
            source.get("target_channels") != list(EDITING_TARGET_CHANNELS)
            or source.get("render_profile_sha256")
            != FFMPEG_RENDER_PROFILE_SHA256
        ):
            raise ValueError("governed_editing_channel_profile_invalid")
        refs = tuple(source["reference_asset_refs"])
        FfmpegMediaWorker.validate_plan(
            render_plan=dict(render_plan),
            render_plan_sha256=render_plan_sha256,
            executor="ffmpeg",
            reference_asset_refs=refs,
        )
        source_assets = []
        source_records: dict[str, Any] = {}
        for ref in refs:
            FfmpegMediaWorker._remaining_timeout(deadline)
            asset_id = ref.removeprefix("content-asset://")
            asset = self.repo.get_content_asset_scoped(
                asset_id=asset_id,
                tenant_ref=scope.tenant_ref,
                entity_ref=scope.entity_ref,
                store_ref=scope.store_ref,
                as_of=now,
            )
            source_assets.append(asset)
            if asset.artifact_ref:
                source_records[ref] = self.evidence.get(str(asset.artifact_ref))
        if (
            not source_assets
            or any(
                asset.status is not ContentStatus.APPROVED
                or not asset.artifact_ref
                for asset in source_assets
            )
            or {asset.product_id for asset in source_assets}
            != {source["product_id"]}
        ):
            raise ValueError("governed_editing_source_asset_invalid")
        if (
            set(source_records) != set(refs)
            or any(
                record.byte_size <= 0
                or record.byte_size > FfmpegMediaWorker.MAX_VIDEO_INPUT_BYTES
                for record in source_records.values()
            )
            or sum(record.byte_size for record in source_records.values())
            > FfmpegMediaWorker.MAX_TOTAL_VIDEO_INPUT_BYTES
        ):
            raise ValueError("governed_editing_source_asset_invalid")
        source_inputs: dict[str, tuple[bytes, str, str]] = {}
        for ref in refs:
            FfmpegMediaWorker._remaining_timeout(deadline)
            content, record = self.evidence.content(source_records[ref].id)
            if len(content) != source_records[ref].byte_size:
                raise ValueError("governed_editing_source_asset_invalid")
            source_inputs[ref] = (content, record.filename, record.content_type)
        audio_bytes = None
        audio_filename = None
        audio_content_type = None
        if source.get("audio_asset_ref"):
            audio_asset = self.repo.get_content_asset_scoped(
                asset_id=str(source["audio_asset_ref"]).removeprefix(
                    "content-asset://"
                ),
                tenant_ref=scope.tenant_ref,
                entity_ref=scope.entity_ref,
                store_ref=scope.store_ref,
                as_of=now,
            )
            if (
                audio_asset.status is not ContentStatus.APPROVED
                or not audio_asset.artifact_ref
                or audio_asset.product_id != source["product_id"]
            ):
                raise ValueError("governed_editing_audio_asset_invalid")
            audio_record = self.evidence.get(str(audio_asset.artifact_ref))
            if (
                audio_record.byte_size <= 0
                or audio_record.byte_size > FfmpegMediaWorker.MAX_AUDIO_INPUT_BYTES
            ):
                raise ValueError("governed_editing_audio_asset_invalid")
            FfmpegMediaWorker._remaining_timeout(deadline)
            audio_bytes, audio_record = self.evidence.content(audio_record.id)
            audio_filename = audio_record.filename
            audio_content_type = audio_record.content_type
        subtitle_bytes = None
        subtitle_filename = None
        subtitle_content_type = None
        if source.get("subtitle_asset_ref"):
            subtitle_id = str(source["subtitle_asset_ref"]).removeprefix(
                "evidence://"
            )
            subtitle_record = self.evidence.get(subtitle_id)
            if (
                subtitle_record.byte_size <= 0
                or subtitle_record.byte_size > FfmpegMediaWorker.MAX_TEXT_INPUT_BYTES
            ):
                raise ValueError("governed_editing_subtitle_invalid")
            FfmpegMediaWorker._remaining_timeout(deadline)
            subtitle_bytes, subtitle_record = self.evidence.content(subtitle_id)
            subtitle_filename = subtitle_record.filename
            subtitle_content_type = subtitle_record.content_type
        caption_inputs: dict[str, tuple[bytes, str, str]] = {}
        caption_records: dict[str, Any] = {}
        for scene in render_plan["scenes"]:
            caption_ref = str(scene["caption_ref"])
            caption_id = caption_ref.removeprefix("evidence://")
            if caption_ref not in caption_records:
                caption_records[caption_ref] = self.evidence.get(caption_id)
        text_total = sum(record.byte_size for record in caption_records.values()) + (
            len(subtitle_bytes) if subtitle_bytes is not None else 0
        )
        if (
            any(
                record.byte_size <= 0
                or record.byte_size > FfmpegMediaWorker.MAX_TEXT_INPUT_BYTES
                for record in caption_records.values()
            )
            or text_total > FfmpegMediaWorker.MAX_TOTAL_TEXT_INPUT_BYTES
        ):
            raise ValueError("governed_editing_caption_invalid")
        for caption_ref, caption_record in caption_records.items():
            FfmpegMediaWorker._remaining_timeout(deadline)
            caption_id = caption_ref.removeprefix("evidence://")
            caption_bytes, caption_record = self.evidence.content(caption_id)
            caption_inputs[caption_ref] = (
                caption_bytes,
                caption_record.filename,
                caption_record.content_type,
            )
        outputs, encoder_report = ffmpeg_adapter.render_plan(
            render_plan=render_plan,
            render_plan_sha256=render_plan_sha256,
            source_inputs=source_inputs,
            caption_inputs=caption_inputs,
            audio_bytes=audio_bytes,
            audio_filename=audio_filename,
            audio_content_type=audio_content_type,
            subtitle_bytes=subtitle_bytes,
            subtitle_filename=subtitle_filename,
            subtitle_content_type=subtitle_content_type,
            deadline=deadline,
        )
        expected_ratios = set(FfmpegMediaWorker.RATIO_SIZES)
        if (
            not isinstance(outputs, dict)
            or set(outputs) != expected_ratios
            or any(not isinstance(value, bytes) or not value for value in outputs.values())
            or not isinstance(encoder_report, dict)
        ):
            raise ValueError("governed_editing_ffmpeg_output_invalid")
        artifact_box: dict[str, Any] = {}
        completion_box: dict[str, datetime] = {}

        def artifact_writer(
            session: Session,
            committed_scope: Any,
            completion_now: datetime,
        ) -> dict[str, Any]:
            artifact = self._persist_governed_editing_artifact_in_session(
                session=session,
                scope=committed_scope,
                job_ref=job_ref,
                source=source,
                render_plan=render_plan,
                render_plan_sha256=render_plan_sha256,
                outputs=outputs,
                encoder_report=encoder_report,
                now=completion_now,
            )
            artifact_box.update(artifact)
            completion_box["completed_at"] = completion_now
            return artifact

        receipt = result_recorder(artifact_writer)
        receipt_sha256 = getattr(receipt, "receipt_sha256", None)
        if not isinstance(receipt_sha256, str) or len(receipt_sha256) != 64:
            raise RuntimeError("governed_editing_result_receipt_invalid")
        completed_at = completion_box.get("completed_at")
        if completed_at is None:
            raise RuntimeError("governed_editing_completion_time_missing")
        result = self.read_governed_editing_artifact(
            job_ref=job_ref,
            render_plan_sha256=render_plan_sha256,
            scope=scope,
            as_of=completed_at,
        )
        if result is None:
            raise RuntimeError("governed_editing_artifact_missing")
        if (
            result.get("content_asset_ref") != artifact_box.get("content_asset_ref")
            or result.get("result_receipt_sha256") != receipt_sha256
        ):
            raise RuntimeError("governed_editing_artifact_receipt_drifted")
        return result

    def _persist_governed_editing_artifact_in_session(
        self,
        *,
        session: Session,
        scope: Any,
        job_ref: str,
        source: dict[str, Any],
        render_plan: dict[str, Any],
        render_plan_sha256: str,
        outputs: dict[str, bytes],
        encoder_report: dict[str, Any],
        now: datetime,
    ) -> dict[str, Any]:
        """Write the asset and artifacts inside the caller's terminal transaction."""

        self._lock_governed_editing_inputs_in_session(
            session=session,
            scope=scope,
            source=source,
            render_plan=render_plan,
        )
        execution_id = self._governed_execution_id(job_ref, render_plan_sha256)
        asset_id = f"asset_{hashlib.sha256(execution_id.encode()).hexdigest()[:32]}"
        if session.get(ContentAssetRow, asset_id) is not None:
            raise RuntimeError("governed_editing_artifact_concurrent_winner")
        captured: dict[str, str] = {}
        for ratio in GOVERNED_RENDER_RATIOS:
            content = outputs[ratio]
            artifact_sha = hashlib.sha256(content).hexdigest()
            record = self.evidence.capture_media_job_evidence(
                content=content,
                filename=f"{asset_id}-{ratio.replace(':', 'x')}.mp4",
                content_type="video/mp4",
                source="kjds-ffmpeg-media-worker",
                source_ref=f"media-job://{job_ref}/artifact/{execution_id}/{ratio}",
                grade=EvidenceGrade.B,
                effective_at=now.isoformat(),
                recorded_at=now.isoformat(),
                created_by=scope.subject_actor_id,
                metadata={
                    "contract_id": "kjds-governed-media-job-artifact-v1",
                    "tenant_ref": scope.tenant_ref,
                    "entity_ref": scope.entity_ref,
                    "store_ref": scope.store_ref,
                    "scope_grant_authority_sha256": scope.authority_sha256,
                    "subject_actor_id": scope.subject_actor_id,
                    "artifact_sha256": artifact_sha,
                    "media_job_ref": job_ref,
                    "content_asset_id": asset_id,
                    "execution_id": execution_id,
                    "aspect_ratio": ratio,
                    "render_plan_sha256": render_plan_sha256,
                },
                session=session,
            )
            captured[ratio] = record.id
        row = ContentAssetRow(
            id=asset_id,
            product_id=source["product_id"],
            content_type=ContentType.VIDEO.value,
            locale=EDITING_TARGET_LOCALE,
            channel=EDITING_TARGET_CHANNELS[0],
            brief_json={
                "contract_id": "kjds-governed-editing-handoff-v1",
                "job_ref": job_ref,
                "source_snapshot_sha256": source["source_snapshot_sha256"],
                "render_plan_sha256": render_plan_sha256,
            },
            source_facts_json={},
            status=ContentStatus.GENERATED.value,
            artifact_ref=captured["9:16"],
            qa_results_json=[],
            generation_json={
                "executor": "ffmpeg",
                "template_id": FfmpegMediaWorker.VERSION,
                "media_job_ref": job_ref,
                "execution_id": execution_id,
                "source_snapshot_sha256": source["source_snapshot_sha256"],
                "render_plan_sha256": render_plan_sha256,
                "outputs": captured,
                "encoder_version": str(
                    encoder_report.get("encoder_version", "unknown")
                )[:300],
                "result_receipt_sha256": None,
                "listing_eligible": False,
            },
            created_at=now,
        )
        session.add(row)
        session.flush()
        return {
            "content_asset_ref": asset_id,
            "execution_id": execution_id,
            "artifact_evidence_refs": tuple(
                captured[ratio] for ratio in GOVERNED_RENDER_RATIOS
            ),
            "outputs": dict(captured),
            "render_plan_sha256": render_plan_sha256,
        }

    def _lock_governed_editing_inputs_in_session(
        self,
        *,
        session: Session,
        scope: Any,
        source: dict[str, Any],
        render_plan: dict[str, Any],
    ) -> None:
        """Lock and revalidate every mutable input before the terminal write."""

        scope_payload = source.get("scope")
        expected_scope = {
            "tenant_ref": scope.tenant_ref,
            "entity_ref": scope.entity_ref,
            "store_ref": scope.store_ref,
            "authority_sha256": scope.authority_sha256,
            "subject_actor_id": scope.subject_actor_id,
        }
        artifacts = source.get("input_artifacts")
        campaign_refs = source.get("campaign_asset_refs")
        reference_refs = source.get("reference_asset_refs")
        audio_ref = source.get("audio_asset_ref")
        declared_refs = [
            *(campaign_refs if isinstance(campaign_refs, list) else []),
            *(reference_refs if isinstance(reference_refs, list) else []),
            *([audio_ref] if isinstance(audio_ref, str) else []),
        ]
        if (
            scope_payload != expected_scope
            or not isinstance(artifacts, list)
            or not artifacts
            or not isinstance(campaign_refs, list)
            or not isinstance(reference_refs, list)
            or not reference_refs
            or not isinstance(audio_ref, str)
            or len(set(declared_refs)) != len(declared_refs)
            or set(render_plan.get("reference_asset_refs", ()))
            != set(reference_refs)
        ):
            raise ValueError("governed_editing_source_changed")
        artifact_by_ref: dict[str, dict[str, Any]] = {}
        for artifact in artifacts:
            if (
                not isinstance(artifact, dict)
                or set(artifact)
                != {
                    "content_asset_ref",
                    "evidence_ref",
                    "evidence_sha256",
                    "content_type",
                    "role",
                }
                or not isinstance(artifact.get("content_asset_ref"), str)
                or artifact["content_asset_ref"] in artifact_by_ref
            ):
                raise ValueError("governed_editing_source_changed")
            artifact_by_ref[artifact["content_asset_ref"]] = artifact
        if set(artifact_by_ref) != set(declared_refs):
            raise ValueError("governed_editing_source_changed")

        product = session.scalar(
            select(ProductRow)
            .where(ProductRow.id == source.get("product_id"))
            .with_for_update()
        )
        if (
            product is None
            or product.tenant_ref != scope.tenant_ref
            or product.entity_ref != scope.entity_ref
            or product.store_ref != scope.store_ref
            or product.scope_grant_authority_sha256 != scope.authority_sha256
        ):
            raise ValueError("governed_editing_product_changed")
        asset_ids = sorted(ref.removeprefix("content-asset://") for ref in declared_refs)
        rows = list(
            session.scalars(
                select(ContentAssetRow)
                .where(ContentAssetRow.id.in_(asset_ids))
                .order_by(ContentAssetRow.id)
                .with_for_update()
            ).all()
        )
        rows_by_id = {row.id: row for row in rows}
        if set(rows_by_id) != set(asset_ids):
            raise ValueError("governed_editing_source_changed")
        for ref in declared_refs:
            artifact = artifact_by_ref[ref]
            row = rows_by_id[ref.removeprefix("content-asset://")]
            evidence_ref = artifact.get("evidence_ref")
            evidence_id = (
                evidence_ref.removeprefix("evidence://")
                if isinstance(evidence_ref, str)
                else ""
            )
            record = session.get(EvidenceRecordRow, evidence_id)
            blob = (
                session.get(EvidenceBlobRow, record.blob_sha256)
                if record is not None
                else None
            )
            if (
                row.product_id != product.id
                or row.status != ContentStatus.APPROVED.value
                or row.artifact_ref != evidence_id
                or record is None
                or blob is None
                or record.blob_sha256 != artifact.get("evidence_sha256")
                or record.content_type != artifact.get("content_type")
                or record.metadata_json.get("rights_status") != "approved"
                or hashlib.sha256(blob.content_bytes).hexdigest() != blob.sha256
                or (
                    artifact.get("role") == "reference_video"
                    and (
                        row.content_type != ContentType.VIDEO.value
                        or not record.content_type.startswith("video/")
                    )
                )
                or (
                    artifact.get("role") == "audio"
                    and not record.content_type.startswith("audio/")
                )
            ):
                raise ValueError("governed_editing_source_changed")

        evidence_seals: list[tuple[str, str | None]] = []
        analysis_receipt = source.get("analysis_receipt")
        if isinstance(analysis_receipt, dict):
            evidence_seals.append(
                (
                    str(analysis_receipt.get("evidence_ref", "")),
                    analysis_receipt.get("evidence_sha256"),
                )
            )
        for scene in render_plan.get("scenes", []):
            evidence_seals.append((str(scene.get("caption_ref", "")), None))
        if source.get("subtitle_asset_ref") is not None:
            evidence_seals.append((str(source["subtitle_asset_ref"]), None))
        for evidence_ref, expected_sha in evidence_seals:
            if not evidence_ref.startswith("evidence://"):
                raise ValueError("governed_editing_evidence_changed")
            record = session.get(
                EvidenceRecordRow,
                evidence_ref.removeprefix("evidence://"),
            )
            blob = (
                session.get(EvidenceBlobRow, record.blob_sha256)
                if record is not None
                else None
            )
            if (
                record is None
                or blob is None
                or record.metadata_json.get("rights_status") != "approved"
                or (expected_sha is not None and blob.sha256 != expected_sha)
                or hashlib.sha256(blob.content_bytes).hexdigest() != blob.sha256
            ):
                raise ValueError("governed_editing_evidence_changed")

    @staticmethod
    def _template(asset) -> dict[str, Any]:
        requested = str(asset.brief.get("template_id", "")).strip()
        if not requested:
            requested = (
                "ozon-retouch-v1"
                if asset.content_type is ContentType.IMAGE
                else "kjds-ffmpeg-product-video-v1"
            )
        for template in TEMPLATE_CATALOG:
            if template["id"] == requested:
                if template["kind"] != asset.content_type.value:
                    raise ValueError("Media template kind does not match asset")
                return template
        return {
            "id": requested,
            "kind": asset.content_type.value,
            "version": "unknown",
            "status": "blocked",
            "executor": "unknown",
        }

    def _validate_video_brief(self, asset) -> None:
        if asset.content_type is not ContentType.VIDEO:
            raise ValueError("Video brief validation requires a video asset")
        image_ids = asset.brief.get("approved_image_asset_ids")
        if not isinstance(image_ids, list) or not image_ids:
            raise ValueError("Video requires approved product image assets")
        image_evidence_ids: list[str] = []
        for image_id in image_ids:
            source = self.repo.get_content_asset(str(image_id))
            if (
                source.product_id != asset.product_id
                or source.content_type is not ContentType.IMAGE
                or source.status is not ContentStatus.APPROVED
                or not source.artifact_ref
            ):
                raise ValueError(
                    "Video source images must be approved for the same product"
                )
            image_evidence_ids.append(source.artifact_ref)
        required = (
            "script_evidence_id",
            "subtitle_evidence_id",
            "audio_rights_evidence_id",
        )
        evidence_ids = [
            str(asset.brief.get(key, "")).strip() for key in required
        ]
        if any(not value for value in evidence_ids):
            raise ValueError(
                "Video requires confirmed Russian script, subtitle, and "
                "audio-rights Evidence"
            )
        self.evidence.require_valid([*image_evidence_ids, *evidence_ids])
        if asset.brief.get("script_human_confirmed") is not True:
            raise ValueError("Russian video script requires human confirmation")
        script = self.evidence.get(evidence_ids[0])
        subtitle = self.evidence.get(evidence_ids[1])
        audio = self.evidence.get(evidence_ids[2])
        for record, label in ((script, "script"), (subtitle, "subtitle")):
            if (
                record.metadata.get("language") != "ru"
                or record.metadata.get("human_approved") is not True
            ):
                raise ValueError(
                    f"Russian {label} Evidence must be human approved"
                )
        if not script.content_type.startswith("text/"):
            raise ValueError("Russian script Evidence must be text")
        if subtitle.content_type not in {
            "application/x-subrip",
            "text/plain",
        }:
            raise ValueError("Subtitle Evidence must be SRT or plain text")
        if (
            not audio.content_type.startswith("audio/")
            or audio.metadata.get("rights_status") != "approved"
        ):
            raise ValueError(
                "Audio Evidence must have approved usage rights"
            )
        ratios = asset.brief.get("aspect_ratios")
        if ratios != ["9:16", "1:1", "16:9"]:
            raise ValueError(
                "Video aspect ratios must be exactly 9:16, 1:1, and 16:9"
            )

    @staticmethod
    def _asset(asset) -> dict[str, Any]:
        return {
            "id": asset.id,
            "product_id": asset.product_id,
            "content_type": asset.content_type.value,
            "locale": asset.locale,
            "channel": asset.channel,
            "status": asset.status.value,
            "artifact_ref": asset.artifact_ref,
            "brief": asset.brief,
            "qa_results": asset.qa_results,
            "generation": asset.generation,
        }

    @staticmethod
    def _asset_row(asset: ContentAssetRow) -> dict[str, Any]:
        return {
            "id": asset.id,
            "product_id": asset.product_id,
            "content_type": asset.content_type,
            "locale": asset.locale,
            "channel": asset.channel,
            "status": asset.status,
            "artifact_ref": asset.artifact_ref,
            "brief": asset.brief_json,
            "qa_results": asset.qa_results_json,
            "generation": asset.generation_json,
        }

    @classmethod
    def _execution(cls, row: MediaExecutionRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "asset_id": row.asset_id,
            "media_kind": row.media_kind,
            "template_id": row.template_id,
            "input_sha256": row.input_sha256,
            "status": row.status,
            "attempt": row.attempt,
            "queued_by": row.queued_by,
            "queued_at": cls._iso(row.queued_at),
            "lease_owner": row.lease_owner,
            "lease_expires_at": cls._iso(row.lease_expires_at),
            "started_at": cls._iso(row.started_at),
            "completed_at": cls._iso(row.completed_at),
            "latency_ms": row.latency_ms,
            "cost": {
                "amount": str(row.cost_amount),
                "currency": row.cost_currency,
            },
            "outputs": row.outputs_json,
            "error_code": row.error_code,
            "error_detail": row.error_detail,
            "external_side_effect": False,
        }

    @classmethod
    def _event(cls, row: MediaExecutionEventRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "execution_id": row.execution_id,
            "sequence": row.sequence,
            "event_type": row.event_type,
            "from_status": row.from_status,
            "to_status": row.to_status,
            "payload": row.payload_json,
            "actor_id": row.actor_id,
            "occurred_at": cls._iso(row.occurred_at),
        }

    @classmethod
    def _manifest_source(
        cls, row: MediaDeliveryManifestRow
    ) -> dict[str, Any]:
        return {
            "id": row.id,
            "asset_id": row.asset_id,
            "execution_id": row.execution_id,
            "asset_state_sha256": row.asset_state_sha256,
            "manifest_sha256": row.manifest_sha256,
            "payload": row.payload_json,
            "created_by": row.created_by,
            "created_at": cls._iso(row.created_at),
        }

    @staticmethod
    def _latency(start: datetime, end: datetime) -> int:
        return max(
            0,
            int(
                (
                    MediaWorkbenchService._aware(end)
                    - MediaWorkbenchService._aware(start)
                ).total_seconds()
                * 1000
            ),
        )

    @staticmethod
    def _decimal(value: Decimal, field: str) -> Decimal:
        try:
            parsed = Decimal(value)
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError(f"{field} must be Decimal-compatible") from exc
        if not parsed.is_finite() or parsed < 0:
            raise ValueError(f"{field} must be finite and non-negative")
        return parsed

    @staticmethod
    def _currency(value: str) -> str:
        normalized = value.strip().upper()
        if (
            len(normalized) != 3
            or not normalized.isascii()
            or not normalized.isalpha()
        ):
            raise ValueError("cost_currency must be a three-letter ASCII code")
        return normalized

    @staticmethod
    def _text(
        value: str, field: str, *, maximum: int = 300
    ) -> str:
        normalized = value.strip()
        if not normalized or len(normalized) > maximum:
            raise ValueError(f"{field} must be 1 to {maximum} characters")
        return normalized

    @staticmethod
    def _aware(value: datetime) -> datetime:
        return (
            value.replace(tzinfo=UTC)
            if value.tzinfo is None
            else value.astimezone(UTC)
        )

    @classmethod
    def _iso(cls, value: datetime | None) -> str | None:
        return cls._aware(value).isoformat() if value is not None else None

    @staticmethod
    def _hash(payload: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode()
        ).hexdigest()

    @staticmethod
    def _input_filename(prefix: str, filename: str, fallback: str) -> str:
        suffix = Path(filename).suffix.lower()
        if not suffix or len(suffix) > 10:
            suffix = fallback
        return f"{prefix}{suffix}"

    @staticmethod
    def _run_media_command(command: list[str], *, workdir: Path) -> None:
        subprocess.run(
            command,
            cwd=workdir,
            check=True,
            capture_output=True,
            timeout=180,
        )

    @staticmethod
    def _ffmpeg_version(ffmpeg: str) -> str:
        result = subprocess.run(
            [ffmpeg, "-version"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return result.stdout.splitlines()[0][:300]

    @staticmethod
    def _append_event(
        session: Session,
        *,
        row: MediaExecutionRow,
        event_type: str,
        from_status: str | None,
        to_status: str,
        payload: dict[str, Any],
        actor_id: str,
        occurred_at: datetime,
    ) -> MediaExecutionEventRow:
        sequence = (
            session.scalar(
                select(func.max(MediaExecutionEventRow.sequence)).where(
                    MediaExecutionEventRow.execution_id == row.id
                )
            )
            or 0
        ) + 1
        event = MediaExecutionEventRow(
            id=new_id("mee"),
            execution_id=row.id,
            sequence=sequence,
            event_type=event_type,
            from_status=from_status,
            to_status=to_status,
            payload_json=payload,
            actor_id=actor_id,
            occurred_at=occurred_at,
        )
        session.add(event)
        session.flush()
        return event


class FfmpegMediaWorker:
    """Build the fixed, non-generative FFmpeg product-video chain."""

    VERSION = "kjds-ffmpeg-product-video-v1"
    runtime_provider_identity = (
        "ffmpeg",
        "internal://local-ffmpeg-renderer-v1",
        "d39f725911da61e70ab388cf2a42fbd2941ebbcc196cdf4b390e5d0f4c468493",
        "kjds-local-ffmpeg/1",
    )
    RATIO_SIZES = {
        "9:16": "1080:1920",
        "1:1": "1080:1080",
        "16:9": "1920:1080",
    }
    PLAN_FIELDS = frozenset(
        {
            "contract_id",
            "executor",
            "job_ref",
            "tool_version",
            "provider",
            "connector_ref",
            "connector_binding_sha256",
            "tool_descriptor_sha256",
            "source_snapshot_sha256",
            "blueprint_sha256",
            "reference_asset_refs",
            "scenes",
            "audio_asset_ref",
            "subtitle_asset_ref",
            "target_channels",
            "render_profile_sha256",
            "external_write_allowed",
            "automatic_retry",
            "automatic_failover",
        }
    )
    SCENE_FIELDS = frozenset(
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
    TRANSITION_SECONDS = 0.25
    SUBPROCESS_TIMEOUT_SECONDS = 180
    RENDER_BUDGET_SECONDS = 1200
    MAX_SOURCE_COUNT = 20
    MAX_VIDEO_INPUT_BYTES = 256 * 1024 * 1024
    MAX_TOTAL_VIDEO_INPUT_BYTES = 512 * 1024 * 1024
    MAX_AUDIO_INPUT_BYTES = 64 * 1024 * 1024
    MAX_CAMPAIGN_INPUT_BYTES = 32 * 1024 * 1024
    MAX_TOTAL_CAMPAIGN_INPUT_BYTES = 128 * 1024 * 1024
    MAX_TEXT_INPUT_BYTES = 2 * 1024 * 1024
    MAX_TOTAL_TEXT_INPUT_BYTES = 8 * 1024 * 1024
    MAX_OUTPUT_BYTES = 256 * 1024 * 1024
    MAX_TOTAL_OUTPUT_BYTES = 512 * 1024 * 1024
    PROTOCOL_WHITELIST = "file,pipe"
    PROTOCOL_BLACKLIST = "http,https,tcp,tls,udp,ftp,crypto,concat,subfile,data"
    VIDEO_FORMATS = {
        ".mp4": ("video/mp4", "mp4"),
        ".mov": ("video/quicktime", "mov"),
        ".webm": ("video/webm", "webm"),
    }
    AUDIO_FORMATS = {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".ogg": "audio/ogg",
    }

    @classmethod
    def validate_plan(
        cls,
        *,
        render_plan: dict[str, Any],
        render_plan_sha256: str,
        executor: str,
        reference_asset_refs: tuple[str, ...],
    ) -> None:
        try:
            plan_bytes = json.dumps(
                render_plan,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError("ffmpeg_render_plan_not_admitted") from exc
        refs = render_plan.get("reference_asset_refs")
        scenes = render_plan.get("scenes")
        if (
            executor != "ffmpeg"
            or not isinstance(render_plan, dict)
            or set(render_plan) != cls.PLAN_FIELDS
            or render_plan.get("contract_id") != "kjds-ffmpeg-render-plan-v1"
            or render_plan.get("executor") != executor
            or render_plan.get("external_write_allowed") is not False
            or render_plan.get("automatic_retry") is not False
            or render_plan.get("automatic_failover") is not False
            or render_plan.get("target_channels")
            != list(EDITING_TARGET_CHANNELS)
            or render_plan.get("render_profile_sha256")
            != FFMPEG_RENDER_PROFILE_SHA256
            or not isinstance(render_plan_sha256, str)
            or len(render_plan_sha256) != 64
            or any(
                char not in "0123456789abcdef"
                for char in render_plan_sha256.lower()
            )
            or not isinstance(reference_asset_refs, tuple)
            or not reference_asset_refs
            or len(reference_asset_refs) > cls.MAX_SOURCE_COUNT
            or len(set(reference_asset_refs)) != len(reference_asset_refs)
            or refs != list(reference_asset_refs)
            or not isinstance(scenes, list)
            or not scenes
            or len(scenes) > 200
            or hashlib.sha256(plan_bytes).hexdigest() != render_plan_sha256
        ):
            raise ValueError("ffmpeg_render_plan_not_admitted")
        previous_timeline_end = 0
        rendered_duration = 0.0
        seen: set[str] = set()
        consumed_refs: set[str] = set()
        for index, scene in enumerate(scenes):
            if not isinstance(scene, dict) or set(scene) != cls.SCENE_FIELDS:
                raise ValueError("ffmpeg_render_plan_not_admitted")
            source_start = scene.get("source_start_ms")
            source_end = scene.get("source_end_ms")
            timeline_start = scene.get("timeline_start_ms")
            timeline_end = scene.get("timeline_end_ms")
            transition = scene.get("transition")
            if (
                not isinstance(scene.get("scene_id"), str)
                or not scene["scene_id"]
                or scene["scene_id"] in seen
                or scene.get("source_asset_ref") not in reference_asset_refs
                or any(
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
                or transition not in {"cut", "fade", "crossfade"}
                or (index == 0 and transition == "crossfade")
                or not isinstance(scene.get("caption_ref"), str)
                or not scene["caption_ref"].startswith("evidence://")
            ):
                raise ValueError("ffmpeg_render_plan_not_admitted")
            duration = (timeline_end - timeline_start) / 1000
            if transition == "crossfade" and (
                duration <= cls.TRANSITION_SECONDS
                or rendered_duration < cls.TRANSITION_SECONDS
            ):
                raise ValueError("ffmpeg_render_plan_not_admitted")
            seen.add(scene["scene_id"])
            consumed_refs.add(scene["source_asset_ref"])
            previous_timeline_end = timeline_end
            rendered_duration += duration
            if transition == "crossfade":
                rendered_duration -= cls.TRANSITION_SECONDS
        if consumed_refs != set(reference_asset_refs):
            raise ValueError("ffmpeg_render_plan_not_admitted")

    @classmethod
    def _validate_video_input(
        cls,
        *,
        content: bytes,
        filename: str,
        content_type: str,
    ) -> str:
        suffix = Path(filename).suffix.lower()
        admitted = cls.VIDEO_FORMATS.get(suffix)
        manifest_prefixes = (b"#EXTM3U", b"ffconcat", b"v=0\r\n", b"v=0\n")
        if (
            admitted is None
            or admitted[0] != content_type
            or not content
            or len(content) > cls.MAX_VIDEO_INPUT_BYTES
            or any(content.startswith(prefix) for prefix in manifest_prefixes)
            or b"://" in content[:4096]
            or b"file:" in content[:4096].lower()
        ):
            raise ValueError("ffmpeg_video_input_not_admitted")
        if suffix in {".mp4", ".mov"}:
            if len(content) < 12 or content[4:8] != b"ftyp":
                raise ValueError("ffmpeg_video_input_not_admitted")
        elif suffix == ".webm" and not content.startswith(b"\x1aE\xdf\xa3"):
            raise ValueError("ffmpeg_video_input_not_admitted")
        return suffix

    @classmethod
    def _validate_audio_input(
        cls,
        *,
        content: bytes,
        filename: str,
        content_type: str,
    ) -> str:
        suffix = Path(filename).suffix.lower()
        if (
            cls.AUDIO_FORMATS.get(suffix) != content_type
            or not content
            or len(content) > cls.MAX_AUDIO_INPUT_BYTES
        ):
            raise ValueError("ffmpeg_audio_input_not_admitted")
        signatures = {
            ".wav": len(content) >= 12
            and content.startswith(b"RIFF")
            and content[8:12] == b"WAVE",
            ".mp3": content.startswith(b"ID3")
            or (len(content) >= 2 and content[0] == 0xFF and content[1] & 0xE0 == 0xE0),
            ".m4a": len(content) >= 12 and content[4:8] == b"ftyp",
            ".ogg": content.startswith(b"OggS"),
        }
        if not signatures[suffix]:
            raise ValueError("ffmpeg_audio_input_not_admitted")
        return suffix

    @classmethod
    def _validate_campaign_input(
        cls,
        *,
        content: bytes,
        filename: str,
        content_type: str,
    ) -> str:
        suffix = Path(filename).suffix.lower()
        admitted = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
        }
        if (
            not isinstance(filename, str)
            or not filename
            or len(filename) > 180
            or filename != Path(filename).name
            or any(char in filename for char in ("/", "\\"))
            or ".." in filename
            or any(ord(char) < 32 or ord(char) == 127 for char in filename)
            or admitted.get(suffix) != content_type
            or not content
            or len(content) > cls.MAX_CAMPAIGN_INPUT_BYTES
        ):
            raise ValueError("ffmpeg_campaign_input_not_admitted")
        valid_magic = (
            (suffix == ".png" and content.startswith(b"\x89PNG\r\n\x1a\n"))
            or (suffix in {".jpg", ".jpeg"} and content.startswith(b"\xff\xd8\xff"))
            or (
                suffix == ".webp"
                and len(content) >= 12
                and content.startswith(b"RIFF")
                and content[8:12] == b"WEBP"
            )
        )
        if not valid_magic:
            raise ValueError("ffmpeg_campaign_input_not_admitted")
        return suffix

    @classmethod
    def _validate_text_input(
        cls,
        *,
        content: bytes,
        filename: str,
        content_type: str,
    ) -> None:
        suffix = Path(filename).suffix.lower()
        admitted = {
            ".srt": "application/x-subrip",
            ".txt": "text/plain",
        }
        if (
            not isinstance(filename, str)
            or not filename
            or len(filename) > 180
            or filename != Path(filename).name
            or any(char in filename for char in ("/", "\\"))
            or ".." in filename
            or any(ord(char) < 32 or ord(char) == 127 for char in filename)
            or admitted.get(suffix) != content_type
            or not content
            or len(content) > cls.MAX_TEXT_INPUT_BYTES
            or b"\x00" in content
        ):
            raise ValueError("ffmpeg_text_input_not_admitted")
        try:
            content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("ffmpeg_text_input_not_admitted") from exc

    @classmethod
    def render_plan(
        cls,
        *,
        render_plan: dict[str, Any],
        render_plan_sha256: str,
        source_inputs: dict[str, tuple[bytes, str, str]],
        caption_inputs: dict[str, tuple[bytes, str, str]],
        audio_bytes: bytes | None,
        audio_filename: str | None,
        audio_content_type: str | None,
        subtitle_bytes: bytes | None,
        subtitle_filename: str | None,
        subtitle_content_type: str | None,
        deadline: float | None = None,
    ) -> tuple[dict[str, bytes], dict[str, Any]]:
        """Execute a fixed local FFmpeg plan without provider failover."""

        refs = tuple(render_plan.get("reference_asset_refs", ()))
        cls.validate_plan(
            render_plan=render_plan,
            render_plan_sha256=render_plan_sha256,
            executor="ffmpeg",
            reference_asset_refs=refs,
        )
        expected_captions = {scene["caption_ref"] for scene in render_plan["scenes"]}
        if (
            set(source_inputs) != set(refs)
            or set(caption_inputs) != expected_captions
            or any(
                not isinstance(content, bytes)
                or not content
                or not isinstance(filename, str)
                or not isinstance(content_type, str)
                for content, filename, content_type in source_inputs.values()
            )
            or any(
                not isinstance(content, bytes)
                or not content
                or not isinstance(filename, str)
                or not isinstance(content_type, str)
                for content, filename, content_type in caption_inputs.values()
            )
            or audio_bytes is None
            or not isinstance(audio_filename, str)
            or not isinstance(audio_content_type, str)
            or len(
                {
                    subtitle_bytes is None,
                    subtitle_filename is None,
                    subtitle_content_type is None,
                }
            )
            != 1
        ):
            raise ValueError("ffmpeg_render_plan_not_admitted")
        deadline = min(
            deadline if deadline is not None else float("inf"),
            time.monotonic() + cls.RENDER_BUDGET_SECONDS,
        )
        if len(refs) > cls.MAX_SOURCE_COUNT:
            raise ValueError("ffmpeg_render_plan_not_admitted")
        video_total = 0
        source_suffixes: dict[str, str] = {}
        for ref in refs:
            content, filename, content_type = source_inputs[ref]
            source_suffixes[ref] = cls._validate_video_input(
                content=content,
                filename=filename,
                content_type=content_type,
            )
            video_total += len(content)
        if video_total > cls.MAX_TOTAL_VIDEO_INPUT_BYTES:
            raise ValueError("ffmpeg_video_input_budget_exceeded")
        audio_suffix = cls._validate_audio_input(
            content=audio_bytes,
            filename=audio_filename,
            content_type=audio_content_type,
        )
        text_total = 0
        for content, filename, content_type in caption_inputs.values():
            cls._validate_text_input(
                content=content,
                filename=filename,
                content_type=content_type,
            )
            text_total += len(content)
        if (
            subtitle_bytes is not None
            and subtitle_filename is not None
            and subtitle_content_type is not None
        ):
            cls._validate_text_input(
                content=subtitle_bytes,
                filename=subtitle_filename,
                content_type=subtitle_content_type,
            )
            text_total += len(subtitle_bytes)
        if text_total > cls.MAX_TOTAL_TEXT_INPUT_BYTES:
            raise ValueError("ffmpeg_text_input_budget_exceeded")
        ffmpeg = os.getenv("KJDS_FFMPEG_PATH") or shutil.which("ffmpeg")
        ffprobe = os.getenv("KJDS_FFPROBE_PATH") or shutil.which("ffprobe")
        if ffmpeg is None or ffprobe is None:
            raise RuntimeError("ffmpeg_runtime_unavailable")
        with tempfile.TemporaryDirectory(prefix="kjds-governed-editing-") as raw_dir:
            workdir = Path(raw_dir)
            source_paths: dict[str, Path] = {}
            for index, ref in enumerate(refs):
                cls._remaining_timeout(deadline)
                content, _, _ = source_inputs[ref]
                source_path = workdir / f"source-{index}{source_suffixes[ref]}"
                source_path.write_bytes(content)
                source_paths[ref] = source_path
            caption_paths: dict[str, Path] = {}
            for index, ref in enumerate(sorted(expected_captions)):
                cls._remaining_timeout(deadline)
                content, _, _ = caption_inputs[ref]
                caption_path = workdir / f"caption-{index}.srt"
                caption_path.write_bytes(content)
                caption_paths[ref] = caption_path
            cls._remaining_timeout(deadline)
            audio_path = workdir / f"audio{audio_suffix}"
            audio_path.write_bytes(audio_bytes)
            subtitle_path = None
            if subtitle_bytes is not None:
                cls._remaining_timeout(deadline)
                subtitle_path = workdir / "subtitles.srt"
                subtitle_path.write_bytes(subtitle_bytes)
            required_source_seconds: dict[str, float] = {}
            for scene in render_plan["scenes"]:
                ref = scene["source_asset_ref"]
                required_source_seconds[ref] = max(
                    required_source_seconds.get(ref, 0.0),
                    scene["source_end_ms"] / 1000,
                )
            for ref in refs:
                cls._probe_media(
                    ffprobe=ffprobe,
                    path=source_paths[ref],
                    kind="video",
                    suffix=source_suffixes[ref],
                    minimum_duration=required_source_seconds[ref],
                    workdir=workdir,
                    timeout=cls._remaining_timeout(deadline),
                )
            cls._probe_media(
                ffprobe=ffprobe,
                path=audio_path,
                kind="audio",
                suffix=audio_suffix,
                minimum_duration=0.0,
                workdir=workdir,
                timeout=cls._remaining_timeout(deadline),
            )
            outputs: dict[str, bytes] = {}
            commands: list[list[str]] = []
            aggregate_output_bytes = 0
            for ratio, size in cls.RATIO_SIZES.items():
                width, height = size.split(":")
                output_path = workdir / f"output-{ratio.replace(':', 'x')}.mp4"
                filter_graph, output_label, duration_seconds = cls._filter_graph(
                    render_plan=render_plan,
                    reference_asset_refs=refs,
                    caption_paths=caption_paths,
                    subtitle_path=subtitle_path,
                    width=width,
                    height=height,
                )
                command = [
                    ffmpeg,
                    "-nostdin",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-nostats",
                    "-y",
                ]
                for ref in refs:
                    command.extend(
                        [
                            "-protocol_whitelist",
                            cls.PROTOCOL_WHITELIST,
                            "-protocol_blacklist",
                            cls.PROTOCOL_BLACKLIST,
                            "-i",
                            str(source_paths[ref]),
                        ]
                    )
                command.extend(
                    [
                        "-protocol_whitelist",
                        cls.PROTOCOL_WHITELIST,
                        "-protocol_blacklist",
                        cls.PROTOCOL_BLACKLIST,
                        "-i",
                        str(audio_path),
                    ]
                )
                command.extend(
                    [
                        "-filter_complex",
                        filter_graph,
                        "-map",
                        output_label,
                        "-map_metadata",
                        "-1",
                        "-fflags",
                        "+bitexact",
                        "-c:v",
                        "libx264",
                        "-preset",
                        "medium",
                        "-crf",
                        "20",
                        "-pix_fmt",
                        "yuv420p",
                        "-r",
                        "30",
                    ]
                )
                command.extend(
                    [
                        "-map",
                        f"{len(refs)}:a:0",
                        "-c:a",
                        "aac",
                        "-b:a",
                        "128k",
                        "-t",
                        f"{duration_seconds:.3f}",
                        "-movflags",
                        "+faststart",
                        "-fs",
                        str(cls.MAX_OUTPUT_BYTES),
                        str(output_path),
                    ]
                )
                cls._run(
                    command,
                    workdir=workdir,
                    timeout=cls._remaining_timeout(deadline),
                )
                cls._probe_media(
                    ffprobe=ffprobe,
                    path=output_path,
                    kind="video",
                    suffix=".mp4",
                    minimum_duration=max(0.001, duration_seconds - 0.1),
                    workdir=workdir,
                    timeout=cls._remaining_timeout(deadline),
                )
                output_size = output_path.stat().st_size
                aggregate_output_bytes += output_size
                if (
                    output_size <= 0
                    or output_size > cls.MAX_OUTPUT_BYTES
                    or aggregate_output_bytes > cls.MAX_TOTAL_OUTPUT_BYTES
                ):
                    raise ValueError("ffmpeg_output_budget_exceeded")
                outputs[ratio] = output_path.read_bytes()
                commands.append(command)
            validate_governed_render_output_bytes(list(outputs.values()))
            return outputs, {
                "encoder_version": cls._version(
                    ffmpeg,
                    timeout=cls._remaining_timeout(deadline),
                ),
                "command_count": len(commands),
                "scene_count": len(render_plan["scenes"]),
                "source_count": len(refs),
                "render_plan_sha256": render_plan_sha256,
                "output_sha256": {
                    ratio: hashlib.sha256(content).hexdigest()
                    for ratio, content in outputs.items()
                },
            }

    @classmethod
    def _filter_graph(
        cls,
        *,
        render_plan: dict[str, Any],
        reference_asset_refs: tuple[str, ...],
        caption_paths: dict[str, Path],
        subtitle_path: Path | None,
        width: str,
        height: str,
    ) -> tuple[str, str, float]:
        filters: list[str] = []
        durations: list[float] = []
        for index, scene in enumerate(render_plan["scenes"]):
            source_index = reference_asset_refs.index(scene["source_asset_ref"])
            source_start = scene["source_start_ms"] / 1000
            source_end = scene["source_end_ms"] / 1000
            duration = (
                scene["timeline_end_ms"] - scene["timeline_start_ms"]
            ) / 1000
            durations.append(duration)
            chain = [
                f"[{source_index}:v]trim=start={source_start:.3f}:end={source_end:.3f}",
                "setpts=PTS-STARTPTS",
                f"scale={width}:{height}:force_original_aspect_ratio=decrease",
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
            ]
            if scene["transition"] == "fade":
                fade_out = max(0.0, duration - cls.TRANSITION_SECONDS)
                chain.extend(
                    [
                        f"fade=t=in:st=0:d={cls.TRANSITION_SECONDS:.3f}",
                        f"fade=t=out:st={fade_out:.3f}:d={cls.TRANSITION_SECONDS:.3f}",
                    ]
                )
            caption_path = caption_paths[scene["caption_ref"]]
            chain.append(
                f"subtitles=filename='{cls._filter_path(caption_path)}'"
            )
            filters.append(",".join(chain) + f"[scene{index}]")

        current = "scene0"
        total = durations[0]
        for index in range(1, len(render_plan["scenes"])):
            scene = render_plan["scenes"][index]
            output = f"mix{index}"
            if scene["transition"] == "crossfade":
                offset = total - cls.TRANSITION_SECONDS
                filters.append(
                    f"[{current}][scene{index}]xfade=transition=fade:"
                    f"duration={cls.TRANSITION_SECONDS:.3f}:offset={offset:.3f}"
                    f"[{output}]"
                )
                total += durations[index] - cls.TRANSITION_SECONDS
            else:
                filters.append(
                    f"[{current}][scene{index}]concat=n=2:v=1:a=0[{output}]"
                )
                total += durations[index]
            current = output
        if subtitle_path is not None:
            filters.append(
                f"[{current}]subtitles=filename='{cls._filter_path(subtitle_path)}'"
                "[final]"
            )
            current = "final"
        return ";".join(filters), f"[{current}]", total

    @staticmethod
    def _safe_input_name(prefix: str, filename: str, fallback: str) -> str:
        suffix = Path(str(filename)).suffix.lower()
        if not suffix or len(suffix) > 10:
            suffix = fallback
        return f"{prefix}{suffix}"

    @classmethod
    def _probe_media(
        cls,
        *,
        ffprobe: str,
        path: Path,
        kind: str,
        suffix: str,
        minimum_duration: float,
        workdir: Path,
        timeout: float,
    ) -> None:
        probe_path = workdir / (
            "probe-" + hashlib.sha256(str(path).encode()).hexdigest()[:16] + ".json"
        )
        command = [
            ffprobe,
            "-v",
            "error",
            "-protocol_whitelist",
            cls.PROTOCOL_WHITELIST,
            "-protocol_blacklist",
            cls.PROTOCOL_BLACKLIST,
            "-show_entries",
            "format=format_name,duration:stream=codec_type,width,height",
            "-of",
            "json",
            str(path),
        ]
        try:
            with probe_path.open("wb") as output:
                subprocess.run(
                    command,
                    cwd=workdir,
                    check=True,
                    stdout=output,
                    stderr=subprocess.DEVNULL,
                    timeout=timeout,
                )
            if probe_path.stat().st_size > 64 * 1024:
                raise ValueError("ffmpeg_probe_output_invalid")
            payload = json.loads(probe_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
            raise ValueError("ffmpeg_probe_failed") from exc
        finally:
            with suppress(OSError):
                probe_path.unlink()
        streams = payload.get("streams") if isinstance(payload, dict) else None
        format_payload = payload.get("format") if isinstance(payload, dict) else None
        if not isinstance(streams, list) or not isinstance(format_payload, dict):
            raise ValueError("ffmpeg_probe_output_invalid")
        matching_streams = [
            stream
            for stream in streams
            if isinstance(stream, dict) and stream.get("codec_type") == kind
        ]
        if len(matching_streams) != 1:
            raise ValueError("ffmpeg_probe_stream_invalid")
        if kind == "video" and (
            not isinstance(matching_streams[0].get("width"), int)
            or matching_streams[0]["width"] <= 0
            or not isinstance(matching_streams[0].get("height"), int)
            or matching_streams[0]["height"] <= 0
        ):
            raise ValueError("ffmpeg_probe_stream_invalid")
        format_name = format_payload.get("format_name")
        expected_format = {
            ".mp4": "mp4",
            ".mov": "mov",
            ".webm": "webm",
            ".wav": "wav",
            ".mp3": "mp3",
            ".m4a": "m4a",
            ".ogg": "ogg",
        }.get(suffix)
        if (
            not isinstance(format_name, str)
            or expected_format is None
            or expected_format not in set(format_name.split(","))
        ):
            raise ValueError("ffmpeg_probe_format_invalid")
        try:
            duration = float(format_payload.get("duration"))
        except (TypeError, ValueError) as exc:
            raise ValueError("ffmpeg_probe_duration_invalid") from exc
        if (
            not math.isfinite(duration)
            or duration <= 0
            or duration + 0.001 < minimum_duration
        ):
            raise ValueError("ffmpeg_probe_duration_invalid")

    @classmethod
    def _remaining_timeout(cls, deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("ffmpeg_render_budget_exceeded")
        return min(float(cls.SUBPROCESS_TIMEOUT_SECONDS), remaining)

    @staticmethod
    def _run(command: list[str], *, workdir: Path, timeout: float) -> None:
        subprocess.run(
            command,
            cwd=workdir,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        )

    @staticmethod
    def _version(ffmpeg: str, *, timeout: float) -> str:
        result = subprocess.run(
            [ffmpeg, "-version"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            timeout=timeout,
        )
        return result.stdout.splitlines()[0][:300]

    @classmethod
    def encode_command(
        cls,
        *,
        ffmpeg: str,
        image_path: Path,
        audio_path: Path,
        subtitle_path: Path,
        output_path: Path,
        size: str,
        duration: int,
    ) -> list[str]:
        width, height = size.split(":")
        escaped_subtitle = cls._filter_path(subtitle_path)
        filter_graph = (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
            f"subtitles=filename='{escaped_subtitle}'"
        )
        return [
            ffmpeg,
            "-nostdin",
            "-y",
            "-loop",
            "1",
            "-framerate",
            "30",
            "-i",
            str(image_path),
            "-i",
            str(audio_path),
            "-t",
            str(duration),
            "-vf",
            filter_graph,
            "-map_metadata",
            "-1",
            "-fflags",
            "+bitexact",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "30",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-shortest",
            "-movflags",
            "+faststart",
            str(output_path),
        ]

    @classmethod
    def commands(cls, brief: dict[str, Any]) -> list[list[str]]:
        subtitle_path = cls._safe_path(
            str(brief.get("subtitle_path", "subtitles.srt"))
        )
        input_path = cls._safe_path(
            str(brief.get("approved_stills_input", "approved-stills.mp4"))
        )
        audio_path = cls._safe_path(
            str(brief.get("rights_cleared_audio_path", "rights-audio.wav"))
        )
        commands = []
        for ratio, size in cls.RATIO_SIZES.items():
            width, height = size.split(":")
            output = f"output-{ratio.replace(':', 'x')}.mp4"
            filter_graph = (
                f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
                f"subtitles={subtitle_path}"
            )
            commands.append(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-y",
                    "-i",
                    input_path,
                    "-i",
                    audio_path,
                    "-vf",
                    filter_graph,
                    "-c:v",
                    "libx264",
                    "-profile:v",
                    "high",
                    "-pix_fmt",
                    "yuv420p",
                    "-r",
                    "30",
                    "-c:a",
                    "aac",
                    "-movflags",
                    "+faststart",
                    output,
                ]
            )
        return commands

    @staticmethod
    def _safe_path(value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("FFmpeg work paths must remain relative to the job")
        return path.as_posix()

    @staticmethod
    def _filter_path(path: Path) -> str:
        return (
            path.resolve()
            .as_posix()
            .replace("\\", "\\\\")
            .replace(":", "\\:")
            .replace("'", "\\'")
        )
