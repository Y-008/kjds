from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
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
from .evidence import EvidenceGrade
from .sql_repository import Base, ContentAssetRow

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
        for ratio, content in sorted(outputs.items()):
            record = self.evidence.capture(
                content=content,
                filename=f"{asset.id}-{ratio.replace(':', 'x')}.mp4",
                content_type="video/mp4",
                source="kjds-ffmpeg-media-worker",
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
                source="kjds-ffmpeg-media-worker",
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
            execution = session.scalar(
                select(MediaExecutionRow)
                .where(MediaExecutionRow.asset_id == asset_id)
                .order_by(MediaExecutionRow.queued_at.desc())
            )
            payload = {
                "contract_id": "kjds-media-delivery-manifest-v1",
                "manifest_id": None,
                "asset_id": asset.id,
                "product_id": asset.product_id,
                "content_type": asset.content_type.value,
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
    RATIO_SIZES = {
        "9:16": "1080:1920",
        "1:1": "1080:1080",
        "16:9": "1920:1080",
    }

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
