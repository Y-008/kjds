from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    or_,
    select,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from .agent_inference import (
    AgentArtifact,
    AgentRunEventRow,
    AgentRunRow,
    InferenceAttemptError,
    InferencePolicyError,
    build_task_spec,
)
from .domain import ApprovalStatus, ContentStatus, PassportType, ProductStatus, new_id
from .intake import PRODUCT_MEDIA_ROLES
from .sourcing import listing_approval_payload
from .sql_repository import Base, add_outbox_event

AI_LISTING_STATES = (
    "queued",
    "capture_locked",
    "product_proposed",
    "evidence_review_required",
    "taxonomy_ready",
    "economics_ready",
    "content_ready",
    "media_running",
    "media_review_required",
    "listing_plan_ready",
    "listing_draft_created",
    "listing_approved",
    "dry_run_passed",
    "blocked",
    "failed",
    "cancelled",
)
TERMINAL_STATES = frozenset({"dry_run_passed", "blocked", "failed", "cancelled"})
AI_TASKS = (
    "extract_1688_product_v1",
    "map_ozon_taxonomy_v1",
    "draft_ru_listing_v1",
    "build_media_brief_v1",
    "vision_consistency_qa_v1",
    "listing_quality_qa_v1",
)
RESUME_BINDINGS = frozenset(
    {
        "product_id",
        "offer_id",
        "scenario_id",
        "official_category_candidates",
        "official_attribute_contract",
        "official_listing_rules",
        "taxonomy_evidence_ids",
        "listing_rules_evidence_ids",
        "execution_precondition_state_hash",
        "execution_evidence_ids",
        "risk_limits",
        "risk_values",
        "risk_currency",
    }
)
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_VISION_BYTES = 32 * 1024 * 1024


class AiListingPipelineError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class AiListingRunRow(Base):
    __tablename__ = "ai_listing_runs"
    __table_args__ = (
        UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "idempotency_key",
            name="uq_ai_listing_scope_idempotency",
        ),
        CheckConstraint(
            "status IN (" + ",".join(f"'{item}'" for item in AI_LISTING_STATES) + ")",
            name="ck_ai_listing_status",
        ),
        CheckConstraint(
            "target_marketplace = 'ozon' AND target_locale = 'ru-RU' "
            "AND mode = 'internal_dry_run'",
            name="ck_ai_listing_target_mode",
        ),
        CheckConstraint(
            "length(scope_grant_authority_sha256) = 64 "
            "AND length(input_snapshot_sha256) = 64 "
            "AND length(capture_request_sha256) = 64 "
            "AND length(request_sha256) = 64",
            name="ck_ai_listing_hashes",
        ),
        CheckConstraint(
            "tenant_ref <> '' AND entity_ref <> '' AND store_ref <> ''",
            name="ck_ai_listing_scope_complete",
        ),
        Index("ix_ai_listing_scope_created", "tenant_ref", "entity_ref", "store_ref", "created_at"),
        Index("ix_ai_listing_worker", "work_requested", "lease_until", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(180), primary_key=True)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_grant_authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    capture_submission_id: Mapped[str] = mapped_column(
        ForeignKey("browser_capture_inbox_submissions.id"), nullable=False
    )
    capture_evidence_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_records.id"), nullable=False
    )
    capture_request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    selected_variant_key: Mapped[str] = mapped_column(String(500), nullable=False)
    target_marketplace: Mapped[str] = mapped_column(String(40), nullable=False)
    target_locale: Mapped[str] = mapped_column(String(20), nullable=False)
    mode: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    current_stage: Mapped[str] = mapped_column(String(50), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    frozen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    selected_item_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    bindings_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    artifact_ids_json: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    internal_refs_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    blockers_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_by: Mapped[str] = mapped_column(String(240), nullable=False)
    work_requested: Mapped[bool] = mapped_column(Boolean, nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(240), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(160), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AiListingPipeline:
    """Govern one 1688 variant through an internal Ozon Listing dry-run.

    This service may create internal briefs, Listing drafts, approvals, plans and
    dry-run receipts only through the existing deep modules. It never calls a
    marketplace write adapter, issues a Permit, or queues the limited executor.
    """

    CONTRACT_ID = "kjds-ai-listing-pipeline-v1"

    def __init__(
        self,
        *,
        engine,
        browser_capture_inbox,
        inference,
        repository,
        sourcing,
        sourcing_store,
        product_media,
        content,
        image_execution,
        scoped_product_content,
        listing_execution_authority,
        commerce,
        execution_plans,
        evidence,
        enabled: bool,
        lease_seconds: int = 300,
    ) -> None:
        self.engine = engine
        self.browser_capture_inbox = browser_capture_inbox
        self.inference = inference
        self.repository = repository
        self.sourcing = sourcing
        self.sourcing_store = sourcing_store
        self.product_media = product_media
        self.content = content
        self.image_execution = image_execution
        self.scoped_product_content = scoped_product_content
        self.listing_execution_authority = listing_execution_authority
        self.commerce = commerce
        self.execution_plans = execution_plans
        self.evidence = evidence
        self.enabled = enabled
        self.lease_seconds = min(max(int(lease_seconds), 60), 900)

    def preflight(
        self,
        *,
        capture_submission_id: str,
        store_ref: str,
        selected_variant_key: str,
        target_marketplace: str,
        target_locale: str,
        mode: str,
        as_of: datetime,
        principal,
        entity_scope: dict[str, Any],
    ) -> dict[str, Any]:
        scope = self._scope(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        blockers: list[dict[str, Any]] = []
        if not self.enabled:
            blockers.append(self._blocker("ai_listing_feature_disabled"))
        if target_marketplace != "ozon" or target_locale != "ru-RU" or mode != "internal_dry_run":
            blockers.append(self._blocker("ai_listing_target_mode_invalid"))
        capture = self.browser_capture_inbox.get(
            capture_submission_id,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        if capture["marketplace"] != "1688":
            blockers.append(self._blocker("capture_marketplace_not_1688"))
        if capture["promotion_readiness"]["status"] != "ready":
            blockers.extend(capture["promotion_readiness"]["blockers"])
        if capture["scope"].get("entity_ref") != scope["entity_ref"]:
            blockers.append(self._blocker("capture_scope_mismatch"))
        matches = [
            item
            for item in capture["items"]
            if item.get("variant_key") == selected_variant_key
        ]
        if len(matches) != 1:
            blockers.append(self._blocker("selected_variant_not_unique"))
        provider_checks = [
            self.inference.preflight(
                task_type=task_type,
                data_classification="internal_minimized",
            )
            for task_type in AI_TASKS
        ]
        for check in provider_checks:
            blockers.extend(self._blocker(code) for code in check["blockers"])
        blockers = self._dedupe_blockers(blockers)
        selected = matches[0] if len(matches) == 1 else None
        frozen = {
            "capture_submission_id": capture_submission_id,
            "capture_request_sha256": capture["request_sha256"],
            "capture_evidence_id": capture["evidence"]["evidence_id"],
            "selected_item_sha256": selected.get("item_sha256") if selected else None,
            "selected_variant_key": selected_variant_key,
            "scope": scope,
            "as_of": as_of.astimezone(UTC).isoformat(),
        }
        return {
            "contract_id": self.CONTRACT_ID,
            "status": "ready" if not blockers else "blocked",
            "scope": scope,
            "capture": {
                "id": capture["id"],
                "source_url": capture["source_url"],
                "observed_at": capture["observed_at"],
                "evidence": capture["evidence"],
                "request_sha256": capture["request_sha256"],
            },
            "selected_item": selected,
            "input_snapshot_sha256": self._hash(frozen),
            "provider_checks": provider_checks,
            "blockers": blockers,
            "next_action": None if not blockers else blockers[0],
            "control_envelope": self._control_envelope(),
        }

    def create(
        self,
        *,
        capture_submission_id: str,
        store_ref: str,
        selected_variant_key: str,
        target_marketplace: str,
        target_locale: str,
        mode: str,
        as_of: datetime,
        idempotency_key: str,
        principal,
        entity_scope: dict[str, Any],
    ) -> dict[str, Any]:
        idempotency_key = self._text(idempotency_key, "idempotency_key", 160)
        preflight = self.preflight(
            capture_submission_id=capture_submission_id,
            store_ref=store_ref,
            selected_variant_key=selected_variant_key,
            target_marketplace=target_marketplace,
            target_locale=target_locale,
            mode=mode,
            as_of=as_of,
            principal=principal,
            entity_scope=entity_scope,
        )
        if preflight["status"] != "ready":
            raise AiListingPipelineError(
                "ai_listing_preflight_blocked",
                "AI Listing preflight is blocked: "
                + ", ".join(item["code"] for item in preflight["blockers"]),
            )
        request = {
            "capture_submission_id": capture_submission_id,
            "store_ref": store_ref,
            "selected_variant_key": selected_variant_key,
            "target_marketplace": target_marketplace,
            "target_locale": target_locale,
            "mode": mode,
            "as_of": as_of.astimezone(UTC).isoformat(),
            "idempotency_key": idempotency_key,
            "requested_by": principal.actor_id,
            "input_snapshot_sha256": preflight["input_snapshot_sha256"],
        }
        request_sha256 = self._hash(request)
        scope = preflight["scope"]
        now = datetime.now(UTC)
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            existing = session.scalar(
                select(AiListingRunRow).where(
                    AiListingRunRow.tenant_ref == scope["tenant_ref"],
                    AiListingRunRow.entity_ref == scope["entity_ref"],
                    AiListingRunRow.store_ref == scope["store_ref"],
                    AiListingRunRow.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                if existing.request_sha256 != request_sha256:
                    raise AiListingPipelineError(
                        "ai_listing_idempotency_conflict",
                        "AI Listing idempotency key already has different immutable content",
                    )
                run_id = existing.id
            else:
                run = AiListingRunRow(
                    id=new_id("air"),
                    tenant_ref=scope["tenant_ref"],
                    entity_ref=scope["entity_ref"],
                    store_ref=scope["store_ref"],
                    scope_grant_authority_sha256=scope["scope_grant_authority_sha256"],
                    capture_submission_id=capture_submission_id,
                    capture_evidence_id=preflight["capture"]["evidence"]["evidence_id"],
                    capture_request_sha256=preflight["capture"]["request_sha256"],
                    selected_variant_key=selected_variant_key,
                    target_marketplace=target_marketplace,
                    target_locale=target_locale,
                    mode=mode,
                    status="queued",
                    current_stage="queued",
                    as_of=as_of.astimezone(UTC),
                    frozen_at=now,
                    input_snapshot_sha256=preflight["input_snapshot_sha256"],
                    selected_item_json=preflight["selected_item"],
                    bindings_json={},
                    artifact_ids_json={},
                    internal_refs_json={"capture_source_url": preflight["capture"]["source_url"]},
                    blockers_json=[],
                    idempotency_key=idempotency_key,
                    request_sha256=request_sha256,
                    requested_by=principal.actor_id,
                    work_requested=True,
                    lease_owner=None,
                    lease_until=None,
                    error_code=None,
                    error_detail=None,
                    created_at=now,
                    updated_at=now,
                    completed_at=None,
                )
                session.add(run)
                self._event(
                    session,
                    run=run,
                    event_type="ai_listing.run.created",
                    state="queued",
                    reason=None,
                    actor_id=principal.actor_id,
                    idempotency_key=f"{run.id}:created",
                    source_evidence_id=run.capture_evidence_id,
                )
                run_id = run.id
        return self.get(
            run_id,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
        )

    def list(
        self,
        *,
        principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        limit: int = 100,
    ) -> dict[str, Any]:
        scope = self._scope(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=datetime.now(UTC),
        )
        limit = min(max(int(limit), 1), 200)
        with Session(self.engine) as session:
            ids = list(
                session.scalars(
                    select(AiListingRunRow.id)
                    .where(
                        AiListingRunRow.tenant_ref == scope["tenant_ref"],
                        AiListingRunRow.entity_ref == scope["entity_ref"],
                        AiListingRunRow.store_ref == scope["store_ref"],
                    )
                    .order_by(AiListingRunRow.created_at.desc(), AiListingRunRow.id.desc())
                    .limit(limit)
                )
            )
        return {
            "contract_id": self.CONTRACT_ID,
            "status": "ready",
            "scope": scope,
            "items": [self._projection(run_id) for run_id in ids],
            "control_envelope": self._control_envelope(),
        }

    def get(
        self,
        run_id: str,
        *,
        principal,
        entity_scope: dict[str, Any],
        store_ref: str,
    ) -> dict[str, Any]:
        scope = self._scope(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=datetime.now(UTC),
        )
        with Session(self.engine) as session:
            row = session.scalar(
                select(AiListingRunRow).where(
                    AiListingRunRow.id == run_id,
                    AiListingRunRow.tenant_ref == scope["tenant_ref"],
                    AiListingRunRow.entity_ref == scope["entity_ref"],
                    AiListingRunRow.store_ref == scope["store_ref"],
                )
            )
            if row is None:
                raise KeyError(f"Unknown AI Listing run: {run_id}")
        result = self._projection(run_id)
        result["scope_authority_status"] = (
            "ready"
            if row.scope_grant_authority_sha256
            == scope["scope_grant_authority_sha256"]
            else "changed_blocked"
        )
        return result

    def resume(
        self,
        run_id: str,
        *,
        bindings: dict[str, Any],
        idempotency_key: str,
        principal,
        entity_scope: dict[str, Any],
        store_ref: str,
    ) -> dict[str, Any]:
        scope = self._scope(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=datetime.now(UTC),
        )
        idempotency_key = self._text(idempotency_key, "idempotency_key", 160)
        if not isinstance(bindings, dict) or not set(bindings).issubset(RESUME_BINDINGS):
            raise AiListingPipelineError(
                "resume_binding_not_allowed",
                "AI Listing resume contains a binding outside the admitted contract",
            )
        with Session(self.engine) as session, session.begin():
            row = session.get(AiListingRunRow, run_id, with_for_update=True)
            if row is None or not self._row_in_scope(row, scope):
                raise KeyError(f"Unknown AI Listing run: {run_id}")
            self._assert_scope_authority(row, scope)
            if row.status in TERMINAL_STATES:
                raise AiListingPipelineError(
                    "ai_listing_terminal",
                    f"AI Listing run cannot resume from {row.status}",
                )
            existing_event = session.scalar(
                select(AgentRunEventRow).where(
                    AgentRunEventRow.ai_listing_run_id == row.id,
                    AgentRunEventRow.idempotency_key == idempotency_key,
                )
            )
            if existing_event is None:
                merged = dict(row.bindings_json or {})
                for key, value in bindings.items():
                    if key in merged and self._hash(merged[key]) != self._hash(value):
                        raise AiListingPipelineError(
                            "immutable_binding_conflict",
                            f"AI Listing binding {key} is already frozen; cancel and create a new run",
                        )
                    merged[key] = value
                row.bindings_json = merged
                row.blockers_json = []
                row.work_requested = True
                row.updated_at = datetime.now(UTC)
                self._event(
                    session,
                    run=row,
                    event_type="ai_listing.run.resumed",
                    state=row.status,
                    reason=None,
                    actor_id=principal.actor_id,
                    idempotency_key=idempotency_key,
                )
        return self.get(
            run_id,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
        )

    def cancel(
        self,
        run_id: str,
        *,
        reason: str,
        idempotency_key: str,
        principal,
        entity_scope: dict[str, Any],
        store_ref: str,
    ) -> dict[str, Any]:
        scope = self._scope(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=datetime.now(UTC),
        )
        reason = self._text(reason, "reason", 1000)
        idempotency_key = self._text(idempotency_key, "idempotency_key", 160)
        with Session(self.engine) as session, session.begin():
            row = session.get(AiListingRunRow, run_id, with_for_update=True)
            if row is None or not self._row_in_scope(row, scope):
                raise KeyError(f"Unknown AI Listing run: {run_id}")
            if row.status == "dry_run_passed":
                raise AiListingPipelineError(
                    "completed_run_cannot_cancel",
                    "A completed AI Listing dry-run cannot be cancelled",
                )
            if row.status != "cancelled":
                now = datetime.now(UTC)
                row.status = "cancelled"
                row.current_stage = "cancelled"
                row.work_requested = False
                row.lease_owner = None
                row.lease_until = None
                row.blockers_json = [self._blocker("run_cancelled")]
                row.error_code = "run_cancelled"
                row.error_detail = reason
                row.updated_at = now
                row.completed_at = now
                for attempt in session.scalars(
                    select(AgentRunRow).where(
                        AgentRunRow.ai_listing_run_id == row.id,
                        AgentRunRow.status == "calling",
                    )
                ):
                    attempt.status = "cancelled"
                    attempt.error_code = "parent_run_cancelled"
                    attempt.error_detail = "Provider result must be discarded"
                    attempt.lease_owner = None
                    attempt.lease_until = None
                    attempt.finished_at = now
                self._event(
                    session,
                    run=row,
                    event_type="ai_listing.run.cancelled",
                    state="cancelled",
                    reason=reason,
                    actor_id=principal.actor_id,
                    idempotency_key=idempotency_key,
                )
        return self.get(
            run_id,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
        )

    def process_next(
        self,
        *,
        worker_id: str,
        principal,
        entity_scope: dict[str, Any],
        store_ref: str,
    ) -> dict[str, Any] | None:
        now = datetime.now(UTC)
        with Session(self.engine) as session:
            run_id = session.scalar(
                select(AiListingRunRow.id)
                .where(
                    AiListingRunRow.tenant_ref == principal.tenant_ref,
                    AiListingRunRow.entity_ref == str(entity_scope.get("entity_ref") or ""),
                    AiListingRunRow.store_ref == store_ref,
                    AiListingRunRow.work_requested.is_(True),
                    AiListingRunRow.status.not_in(TERMINAL_STATES),
                    or_(AiListingRunRow.lease_until.is_(None), AiListingRunRow.lease_until < now),
                )
                .order_by(AiListingRunRow.updated_at, AiListingRunRow.id)
                .limit(1)
            )
        if not run_id:
            return None
        return self.process(
            run_id,
            worker_id=worker_id,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
        )

    def process(
        self,
        run_id: str,
        *,
        worker_id: str,
        principal,
        entity_scope: dict[str, Any],
        store_ref: str,
    ) -> dict[str, Any]:
        worker_id = self._text(worker_id, "worker_id", 240)
        scope = self._scope(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=datetime.now(UTC),
        )
        self._claim(run_id, worker_id=worker_id, scope=scope)
        try:
            for _ in range(20):
                row = self._row(run_id)
                if row.status in TERMINAL_STATES or not row.work_requested:
                    break
                handler = getattr(self, f"_stage_{row.status}", None)
                if handler is None:
                    self._fail(
                        row.id,
                        worker_id=worker_id,
                        code="pipeline_state_not_supported",
                        detail=f"No handler for state {row.status}",
                    )
                    break
                try:
                    handler(
                        row,
                        worker_id=worker_id,
                        principal=principal,
                        entity_scope=entity_scope,
                        scope=scope,
                    )
                except (InferencePolicyError, InferenceAttemptError) as exc:
                    self._block(
                        row.id,
                        worker_id=worker_id,
                        code=getattr(exc, "code", "agent_inference_failed"),
                        detail=str(exc),
                    )
                    break
                except AiListingPipelineError as exc:
                    self._pause(
                        row.id,
                        worker_id=worker_id,
                        code=exc.code,
                        detail=str(exc),
                    )
                    break
                except (KeyError, PermissionError, RuntimeError, ValueError) as exc:
                    self._pause(
                        row.id,
                        worker_id=worker_id,
                        code="existing_business_gate_blocked",
                        detail=str(exc),
                    )
                    break
            return self.get(
                run_id,
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store_ref,
            )
        finally:
            self._release(run_id, worker_id=worker_id)

    def _stage_queued(self, row: AiListingRunRow, **context: Any) -> None:
        principal = context["principal"]
        entity_scope = context["entity_scope"]
        capture = self.browser_capture_inbox.get(
            row.capture_submission_id,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=row.store_ref,
            as_of=datetime.now(UTC),
        )
        selected = [
            item for item in capture["items"] if item.get("variant_key") == row.selected_variant_key
        ]
        if (
            capture["request_sha256"] != row.capture_request_sha256
            or capture["evidence"]["evidence_id"] != row.capture_evidence_id
            or capture["promotion_readiness"]["status"] != "ready"
            or len(selected) != 1
            or selected[0].get("item_sha256") != row.selected_item_json.get("item_sha256")
        ):
            raise AiListingPipelineError(
                "capture_snapshot_drifted",
                "Frozen browser capture no longer matches the admitted snapshot",
            )
        self._transition(
            row.id,
            worker_id=context["worker_id"],
            state="capture_locked",
            reason=None,
        )

    def _stage_capture_locked(self, row: AiListingRunRow, **context: Any) -> None:
        item = row.selected_item_json
        model_input = {
            "canonical_url": item["source_url"],
            "observed_at": row.as_of.isoformat(),
            "title": item["title"],
            "selected_variant_key": row.selected_variant_key,
            "visible_attributes": item.get("specifications", {}),
            "displayed_price_observation": {
                "displayed_price": item["displayed_price"],
                "currency": item["currency"],
                "price_scope": item["price_scope"],
                "price_kind": item["price_kind"],
                "formal_supplier_cost": False,
            },
            "min_order_quantity": item.get("min_order_quantity"),
            "public_image_references": item.get("image_references", []),
        }
        artifact = self._infer(row, "extract_1688_product_v1", model_input)
        self._transition(
            row.id,
            worker_id=context["worker_id"],
            state="product_proposed",
            reason=None,
            artifact=artifact,
        )

    def _stage_product_proposed(self, row: AiListingRunRow, **context: Any) -> None:
        self._transition(
            row.id,
            worker_id=context["worker_id"],
            state="evidence_review_required",
            reason="operator_product_and_passport_binding_required",
        )
        self._pause(
            row.id,
            worker_id=context["worker_id"],
            code="operator_product_and_passport_binding_required",
            detail="Confirm the proposal and use the existing Product/Passport intake before resuming",
        )

    def _stage_evidence_review_required(self, row: AiListingRunRow, **context: Any) -> None:
        bindings = row.bindings_json or {}
        required = {
            "product_id",
            "official_category_candidates",
            "official_attribute_contract",
            "taxonomy_evidence_ids",
        }
        missing = sorted(required - set(bindings))
        if missing:
            raise AiListingPipelineError(
                "product_taxonomy_evidence_required",
                "Resume requires: " + ", ".join(missing),
            )
        self._product(row, bindings["product_id"])
        taxonomy_evidence = self._evidence_ids(bindings["taxonomy_evidence_ids"])
        self.evidence.require_valid(taxonomy_evidence)
        product_artifact = self._latest_artifact(row.id, "extract_1688_product_v1")
        model_input = {
            "product_proposal": product_artifact.output["result"],
            "official_category_candidates": bindings["official_category_candidates"],
            "official_attribute_contract": bindings["official_attribute_contract"],
            "target_locale": row.target_locale,
        }
        artifact = self._infer(
            row,
            "map_ozon_taxonomy_v1",
            model_input,
            evidence_ids=[row.capture_evidence_id, *taxonomy_evidence],
        )
        self._validate_taxonomy(
            artifact.output["result"],
            candidates=bindings["official_category_candidates"],
            attributes=bindings["official_attribute_contract"],
        )
        self._transition(
            row.id,
            worker_id=context["worker_id"],
            state="taxonomy_ready",
            reason=None,
            artifact=artifact,
        )

    def _stage_taxonomy_ready(self, row: AiListingRunRow, **context: Any) -> None:
        bindings = row.bindings_json or {}
        missing = sorted({"product_id", "offer_id", "scenario_id"} - set(bindings))
        if missing:
            raise AiListingPipelineError(
                "formal_economics_binding_required",
                "Resume requires real supplier and cost Evidence bindings: " + ", ".join(missing),
            )
        product = self._product(row, bindings["product_id"])
        offer = self.sourcing_store.get_offer(bindings["offer_id"])
        scenario = self.sourcing_store.get_scenario(bindings["scenario_id"])
        if offer.product_id != product.id or scenario.offer_id != offer.id:
            raise AiListingPipelineError(
                "economics_scope_mismatch",
                "Supplier offer and ProfitScenario must belong to the selected Product",
            )
        self.sourcing.require_release_ready(scenario)
        if scenario.cm3_cny <= 0:
            raise AiListingPipelineError(
                "positive_downside_cm3_required",
                "Deterministic ProfitScenario CM3 must be positive",
            )
        economics = scenario.explain()
        economics["supplier_offer_id"] = offer.id
        economics["displayed_page_price_promoted"] = False
        self._transition(
            row.id,
            worker_id=context["worker_id"],
            state="economics_ready",
            reason=None,
            internal_refs={"deterministic_economics": economics},
        )

    def _stage_economics_ready(self, row: AiListingRunRow, **context: Any) -> None:
        bindings = row.bindings_json or {}
        required = {"product_id", "official_listing_rules", "listing_rules_evidence_ids"}
        missing = sorted(required - set(bindings))
        if missing:
            raise AiListingPipelineError(
                "content_evidence_required",
                "Resume requires official Listing rules and Evidence: " + ", ".join(missing),
            )
        product = self._product(row, bindings["product_id"])
        passports = self.repository.latest_passports(product.id)
        if set(passports) != set(PassportType) or not all(item.is_approved for item in passports.values()):
            raise AiListingPipelineError(
                "approved_passports_required",
                "All three current Product Passports must be independently approved",
            )
        media = self.product_media.readiness(product.id)
        if media["ready_for_full_production"] is not True:
            raise AiListingPipelineError(
                "approved_media_rights_required",
                media["next_action"],
            )
        listing_rule_evidence = self._evidence_ids(bindings["listing_rules_evidence_ids"])
        taxonomy_evidence = self._evidence_ids(bindings.get("taxonomy_evidence_ids", []))
        passport_evidence = sorted(
            {evidence_id for passport in passports.values() for evidence_id in passport.evidence}
        )
        evidence_ids = sorted(
            {row.capture_evidence_id, *listing_rule_evidence, *taxonomy_evidence, *passport_evidence}
        )
        self.evidence.require_valid(evidence_ids)
        facts = self._approved_facts(product, passports)
        taxonomy = self._latest_artifact(row.id, "map_ozon_taxonomy_v1")
        listing = self._infer(
            row,
            "draft_ru_listing_v1",
            {
                "approved_product_facts": facts,
                "taxonomy_proposal": taxonomy.output["result"],
                "official_listing_rules": bindings["official_listing_rules"],
                "deterministic_economics_summary": row.internal_refs_json["deterministic_economics"],
                "target_locale": row.target_locale,
            },
            evidence_ids=evidence_ids,
        )
        media_manifest = {
            item["role"]: {
                "source_asset_evidence_id": item["source_asset_evidence_id"],
                "rights_evidence_id": item["rights_evidence_id"],
            }
            for item in media["roles"]
        }
        media_brief = self._infer(
            row,
            "build_media_brief_v1",
            {
                "approved_passport_facts": facts,
                "approved_material_manifest": media_manifest,
                "allowed_image_roles": list(PRODUCT_MEDIA_ROLES),
                "workflow_template": "ozon-retouch-v1",
                "target_marketplace": "ozon",
            },
            evidence_ids=evidence_ids,
        )
        self._transition(
            row.id,
            worker_id=context["worker_id"],
            state="content_ready",
            reason=None,
            artifacts=[listing, media_brief],
            internal_refs={"approved_media_manifest": media_manifest},
        )

    def _stage_content_ready(self, row: AiListingRunRow, **context: Any) -> None:
        product_id = row.bindings_json["product_id"]
        media_artifact = self._latest_artifact(row.id, "build_media_brief_v1")
        media_manifest = row.internal_refs_json["approved_media_manifest"]
        existing = {
            str(item.brief.get("ai_listing_role")): item
            for item in self.repository.content_assets_for_product(product_id)
            if item.brief.get("ai_listing_run_id") == row.id
            and item.brief.get("ai_media_brief_artifact_id") == media_artifact.id
        }
        asset_ids: list[str] = []
        for role in PRODUCT_MEDIA_ROLES:
            asset = existing.get(role)
            source = media_manifest[role]
            if asset is None:
                asset = self.content.create_content_brief(
                    product_id=product_id,
                    content_type=self._image_content_type(),
                    locale=row.target_locale,
                    channel="OZON",
                    brief={
                        "generation_mode": "retouch",
                        "preserve_product_facts": True,
                        "source_asset_evidence_ids": [source["source_asset_evidence_id"]],
                        "rights_evidence_ids": [source["rights_evidence_id"]],
                        "workflow_template": "ozon-retouch-v1",
                        "ai_listing_run_id": row.id,
                        "ai_listing_role": role,
                        "ai_media_brief_artifact_id": media_artifact.id,
                        "preservation_constraints": media_artifact.output["result"][
                            "preservation_constraints"
                        ],
                        "qa_checklist": media_artifact.output["result"]["qa_checklist"],
                    },
                )
            asset_ids.append(asset.id)
        self._transition(
            row.id,
            worker_id=context["worker_id"],
            state="media_running",
            reason=None,
            internal_refs={"content_asset_ids": asset_ids},
        )
        for asset_id in asset_ids:
            asset = self.repository.get_content_asset(asset_id)
            if asset.status in {
                ContentStatus.BRIEF,
                ContentStatus.QA_FAILED,
                ContentStatus.EXECUTION_FAILED,
            }:
                self.image_execution.queue(asset_id, requested_by=row.requested_by)

    def _stage_media_running(self, row: AiListingRunRow, **context: Any) -> None:
        asset_ids = self._evidence_ids(row.internal_refs_json.get("content_asset_ids", []))
        assets = []
        for asset_id in asset_ids:
            asset = self.repository.get_content_asset(asset_id)
            if asset.status == ContentStatus.QUEUED:
                asset = self.image_execution.sync(asset_id, requested_by=row.requested_by)
            assets.append(asset)
        failed = [item.id for item in assets if item.status == ContentStatus.EXECUTION_FAILED]
        if failed:
            raise AiListingPipelineError(
                "media_generation_failed",
                "ComfyUI generation failed for: " + ", ".join(failed),
            )
        pending = [item.id for item in assets if item.status == ContentStatus.QUEUED]
        if pending:
            raise AiListingPipelineError(
                "media_generation_pending",
                "ComfyUI generation is still running for: " + ", ".join(pending),
            )
        if any(item.status != ContentStatus.GENERATED for item in assets):
            raise AiListingPipelineError(
                "media_generation_state_invalid",
                "Every generated image must be ready for machine QA",
            )
        original_refs = [
            value["source_asset_evidence_id"]
            for value in row.internal_refs_json["approved_media_manifest"].values()
        ]
        generated_refs = [self._text(item.artifact_ref, "artifact_ref", 180) for item in assets]
        image_inputs = self._image_inputs([*original_refs, *generated_refs])
        facts = self._approved_facts_for_row(row)
        artifact = self._infer(
            row,
            "vision_consistency_qa_v1",
            {
                "approved_product_facts": facts,
                "original_image_refs": original_refs,
                "generated_image_refs": generated_refs,
                "fixed_qa_items": [
                    "subject_identity",
                    "color",
                    "dimensions_and_specification",
                    "accessories",
                    "text_and_logo",
                    "geometry",
                ],
            },
            evidence_ids=[*original_refs, *generated_refs],
            image_inputs=image_inputs,
        )
        result = artifact.output["result"]
        if result["verdict"] != "pass_proposed" or result["conflicts"]:
            raise AiListingPipelineError(
                "vision_consistency_qa_rejected",
                "Generated media failed machine consistency QA",
            )
        self._transition(
            row.id,
            worker_id=context["worker_id"],
            state="media_review_required",
            reason="independent_human_media_qa_required",
            artifact=artifact,
        )
        self._pause(
            row.id,
            worker_id=context["worker_id"],
            code="independent_human_media_qa_required",
            detail="Review all generated assets with the existing image QA workflow",
        )

    def _stage_media_review_required(self, row: AiListingRunRow, **context: Any) -> None:
        asset_ids = self._evidence_ids(row.internal_refs_json.get("content_asset_ids", []))
        assets = [self.repository.get_content_asset(item) for item in asset_ids]
        not_approved = [item.id for item in assets if item.status != ContentStatus.APPROVED]
        if not_approved:
            raise AiListingPipelineError(
                "independent_human_media_qa_required",
                "Approve image assets in the existing QA workflow: " + ", ".join(not_approved),
            )
        generated_refs = [self._text(item.artifact_ref, "artifact_ref", 180) for item in assets]
        self.evidence.require_valid(generated_refs)
        listing = self._latest_artifact(row.id, "draft_ru_listing_v1")
        evidence_ids = self._business_evidence(row, include_media=True)
        qa = self._infer(
            row,
            "listing_quality_qa_v1",
            {
                "listing_draft_proposal": listing.output["result"],
                "approved_product_facts": self._approved_facts_for_row(row),
                "official_listing_rules": row.bindings_json["official_listing_rules"],
                "deterministic_economics_summary": row.internal_refs_json["deterministic_economics"],
                "approved_media_manifest": {
                    item.id: {"artifact_ref": item.artifact_ref, "status": item.status.value}
                    for item in assets
                },
            },
            evidence_ids=evidence_ids,
        )
        result = qa.output["result"]
        blocking = [item for item in result["issues"] if item["severity"] == "blocking"]
        if result["verdict"] != "pass_proposed" or blocking:
            raise AiListingPipelineError(
                "listing_quality_qa_rejected",
                "Russian Listing proposal failed machine quality QA",
            )
        self._transition(
            row.id,
            worker_id=context["worker_id"],
            state="listing_plan_ready",
            reason=None,
            artifact=qa,
        )

    def _stage_listing_plan_ready(self, row: AiListingRunRow, **context: Any) -> None:
        bindings = row.bindings_json
        content_asset_ids = self._evidence_ids(row.internal_refs_json["content_asset_ids"])
        assets = [self.repository.get_content_asset(item) for item in content_asset_ids]
        listing = self._latest_artifact(row.id, "draft_ru_listing_v1").output["result"]
        taxonomy = self._latest_artifact(row.id, "map_ozon_taxonomy_v1").output["result"]
        category_id = taxonomy["candidates"][0]["category_id"]
        listing_data = {
            "title": listing["title"],
            "description": self._description(listing),
            "category_id": category_id,
            "attributes": taxonomy["attribute_mapping"],
            "images": [item.artifact_ref for item in assets],
        }
        cutoff = datetime.now(UTC)
        plan = self.scoped_product_content.listing_approval_plan(
            principal=context["principal"],
            entity_scope=context["entity_scope"],
            store_ref=row.store_ref,
            as_of=cutoff,
            product_id=bindings["product_id"],
            offer_id=bindings["offer_id"],
            scenario_id=bindings["scenario_id"],
            content_asset_ids=content_asset_ids,
            listing_data=listing_data,
        )
        if not plan["allowed"]:
            raise AiListingPipelineError(
                "listing_approval_plan_blocked",
                "Existing Listing approval plan is blocked: " + ", ".join(plan["reasons"]),
            )
        draft = self.sourcing.create_ozon_listing_draft(
            product_id=bindings["product_id"],
            offer_id=bindings["offer_id"],
            scenario_id=bindings["scenario_id"],
            content_asset_ids=content_asset_ids,
            listing_data=listing_data,
            requested_by=row.requested_by,
            scope_authority={
                **plan["scope"],
                "scoped_product_content_sha256": plan["product_snapshot_sha256"],
                "scope_as_of": plan["as_of"],
            },
            approval_plan_sha256=plan["approval_plan_sha256"],
            evidence_ids=plan["evidence_ids"],
        )
        scenario = self.sourcing_store.get_scenario(draft.scenario_id)
        approval = self.commerce.request_approval(
            action="listing.publish",
            resource_type="listing_draft",
            resource_id=draft.id,
            requested_by=row.requested_by,
            payload=listing_approval_payload(draft, scenario),
        )
        draft.approval_id = approval.id
        self.sourcing_store.attach_listing_approval(draft)
        self._transition(
            row.id,
            worker_id=context["worker_id"],
            state="listing_draft_created",
            reason="independent_listing_and_russian_review_required",
            internal_refs={
                "listing_draft_id": draft.id,
                "listing_approval_id": approval.id,
                "listing_approval_plan_sha256": plan["approval_plan_sha256"],
            },
        )
        self._pause(
            row.id,
            worker_id=context["worker_id"],
            code="independent_listing_and_russian_review_required",
            detail="Complete existing Russian-native Review and Listing Approval",
        )

    def _stage_listing_draft_created(self, row: AiListingRunRow, **context: Any) -> None:
        draft = self.sourcing_store.get_listing_draft(row.internal_refs_json["listing_draft_id"])
        if not draft.approval_id:
            raise AiListingPipelineError(
                "listing_approval_required",
                "Listing draft has no approval request",
            )
        approval = self.repository.get_approval(draft.approval_id)
        review = self.listing_execution_authority.listing_status(draft)
        if approval.status != ApprovalStatus.APPROVED or review["status"] != "accepted":
            raise AiListingPipelineError(
                "independent_listing_and_russian_review_required",
                "Listing Approval and accepted Russian-native Review are both required",
            )
        self._transition(
            row.id,
            worker_id=context["worker_id"],
            state="listing_approved",
            reason=None,
            internal_refs={"russian_review_ids": review["review_ids"]},
        )

    def _stage_listing_approved(self, row: AiListingRunRow, **context: Any) -> None:
        bindings = row.bindings_json
        required = {"execution_precondition_state_hash", "execution_evidence_ids"}
        missing = sorted(required - set(bindings))
        if missing:
            raise AiListingPipelineError(
                "execution_before_state_evidence_required",
                "Governed Execution Plan requires: " + ", ".join(missing),
            )
        evidence_ids = self._evidence_ids(bindings["execution_evidence_ids"])
        self.evidence.require_valid(evidence_ids)
        plan = self.execution_plans.create_from_approved_listing(
            row.internal_refs_json["listing_draft_id"],
            idempotency_key=f"{row.id}:governed-execution-plan",
            precondition_state_hash=bindings["execution_precondition_state_hash"],
            evidence_ids=evidence_ids,
            created_by=row.requested_by,
            risk_limits=bindings.get("risk_limits"),
            risk_values=bindings.get("risk_values"),
            risk_currency=bindings.get("risk_currency"),
        )
        dry_run = self.execution_plans.dry_run(
            plan["id"],
            current_state_hash=bindings["execution_precondition_state_hash"],
            evidence_ids=evidence_ids,
            performed_by=row.requested_by,
        )
        if dry_run["passed"] is not True:
            raise AiListingPipelineError(
                "internal_dry_run_failed",
                "Governed Execution Plan dry-run did not pass",
            )
        self._transition(
            row.id,
            worker_id=context["worker_id"],
            state="dry_run_passed",
            reason=None,
            internal_refs={
                "governed_execution_plan_id": plan["id"],
                "dry_run_id": dry_run["id"],
                "dry_run_request_hash": dry_run["request_hash"],
            },
        )

    def _infer(
        self,
        row: AiListingRunRow,
        task_type: str,
        model_input: dict[str, Any],
        *,
        evidence_ids: list[str] | None = None,
        image_inputs: list[str] | None = None,
    ) -> AgentArtifact:
        task = build_task_spec(
            registry=self.inference.registry,
            task_type=task_type,
            scope={
                "tenant_ref": row.tenant_ref,
                "entity_ref": row.entity_ref,
                "store_ref": row.store_ref,
            },
            as_of=row.as_of.isoformat(),
            evidence_ids=evidence_ids or [row.capture_evidence_id],
            model_input=model_input,
            requested_by=row.requested_by,
            idempotency_key=f"{row.id}:{task_type}:{self._hash(model_input)}",
            ai_listing_run_id=row.id,
            image_inputs=image_inputs,
        )
        return self.inference.infer(task)

    def _product(self, row: AiListingRunRow, product_id: str):
        product = self.repository.get_product_scoped(
            product_id=product_id,
            tenant_ref=row.tenant_ref,
            entity_ref=row.entity_ref,
            store_ref=row.store_ref,
            as_of=datetime.now(UTC),
        )
        if product.channel.strip().upper() != "OZON" or product.market.strip().upper() != "RU":
            raise AiListingPipelineError(
                "product_target_mismatch",
                "Selected Product must be scoped to RU/OZON",
            )
        if product.status not in {
            ProductStatus.CANDIDATE,
            ProductStatus.VALIDATED,
            ProductStatus.APPROVED_FOR_LISTING,
        }:
            raise AiListingPipelineError(
                "product_state_not_admitted",
                "Selected Product is not eligible for this Listing workflow",
            )
        return product

    def _approved_facts_for_row(self, row: AiListingRunRow) -> dict[str, Any]:
        product = self._product(row, row.bindings_json["product_id"])
        passports = self.repository.latest_passports(product.id)
        if set(passports) != set(PassportType) or not all(item.is_approved for item in passports.values()):
            raise AiListingPipelineError(
                "approved_passports_required",
                "All three current Product Passports must remain approved",
            )
        return self._approved_facts(product, passports)

    @staticmethod
    def _approved_facts(product, passports: dict[Any, Any]) -> dict[str, Any]:
        return {
            "product": {"id": product.id, "sku": product.sku, "name": product.name},
            "passports": {
                kind.value: {
                    "passport_id": passport.id,
                    "version": passport.version,
                    "facts": passport.facts,
                    "evidence_ids": passport.evidence,
                    "approved_by": passport.approved_by,
                }
                for kind, passport in passports.items()
            },
        }

    def _business_evidence(self, row: AiListingRunRow, *, include_media: bool) -> list[str]:
        product = self._product(row, row.bindings_json["product_id"])
        passports = self.repository.latest_passports(product.id)
        values = {row.capture_evidence_id}
        values.update(item for passport in passports.values() for item in passport.evidence)
        values.update(self._evidence_ids(row.bindings_json.get("taxonomy_evidence_ids", [])))
        values.update(self._evidence_ids(row.bindings_json.get("listing_rules_evidence_ids", [])))
        offer = self.sourcing_store.get_offer(row.bindings_json["offer_id"])
        scenario = self.sourcing_store.get_scenario(row.bindings_json["scenario_id"])
        values.add(offer.evidence_ref)
        values.update(scenario.evidence)
        values.update(scenario.cost_evidence.values())
        if include_media:
            for asset_id in row.internal_refs_json.get("content_asset_ids", []):
                asset = self.repository.get_content_asset(asset_id)
                if asset.artifact_ref:
                    values.add(asset.artifact_ref)
        result = sorted(item.strip() for item in values if item and item.strip())
        self.evidence.require_valid(result)
        return result

    def _validate_taxonomy(
        self,
        result: dict[str, Any],
        *,
        candidates: Any,
        attributes: Any,
    ) -> None:
        if not isinstance(candidates, list):
            raise AiListingPipelineError(
                "official_taxonomy_contract_invalid",
                "Official category candidates must be a list",
            )
        allowed_categories = {
            str(item.get("category_id") or item.get("id") or "").strip()
            for item in candidates
            if isinstance(item, dict)
        }
        proposed = {str(item["category_id"]).strip() for item in result["candidates"]}
        if not proposed or not proposed.issubset(allowed_categories):
            raise AiListingPipelineError(
                "invented_taxonomy_id_rejected",
                "AI taxonomy output contains a category outside the official candidates",
            )
        definitions: dict[str, dict[str, Any]] = {}
        if isinstance(attributes, dict):
            raw = attributes.get("attributes", attributes)
            if isinstance(raw, dict):
                definitions = {
                    str(key): value for key, value in raw.items() if isinstance(value, dict)
                }
            elif isinstance(raw, list):
                definitions = {
                    str(item.get("attribute_id") or item.get("id")): item
                    for item in raw
                    if isinstance(item, dict) and (item.get("attribute_id") or item.get("id"))
                }
        mapping = result["attribute_mapping"]
        if definitions and not set(mapping).issubset(definitions):
            raise AiListingPipelineError(
                "invented_attribute_id_rejected",
                "AI attribute output contains an ID outside the official contract",
            )
        for key, value in mapping.items():
            definition = definitions.get(str(key), {})
            admitted = definition.get("enum") or definition.get("values")
            if isinstance(admitted, list) and value is not None:
                allowed_values = {
                    self._hash(item) if isinstance(item, dict) else str(item)
                    for item in admitted
                }
                probe = self._hash(value) if isinstance(value, dict) else str(value)
                if probe not in allowed_values:
                    raise AiListingPipelineError(
                        "invented_attribute_enum_rejected",
                        f"AI attribute {key} contains a value outside the official enum",
                    )
        if result["missing_required_attributes"]:
            raise AiListingPipelineError(
                "required_ozon_attributes_missing",
                "Required official Ozon attributes are still unknown",
            )

    def _image_inputs(self, evidence_ids: list[str]) -> list[str]:
        encoded: list[str] = []
        total = 0
        for evidence_id in evidence_ids:
            content, record = self.evidence.content(evidence_id)
            if record.content_type not in {"image/jpeg", "image/png", "image/webp"}:
                raise AiListingPipelineError(
                    "vision_input_type_invalid",
                    "Vision QA accepts JPEG, PNG or WebP Evidence only",
                )
            if not content or len(content) > MAX_IMAGE_BYTES:
                raise AiListingPipelineError(
                    "vision_input_size_invalid",
                    "Vision QA image is empty or exceeds the admitted size",
                )
            total += len(content)
            if total > MAX_VISION_BYTES:
                raise AiListingPipelineError(
                    "vision_input_budget_exceeded",
                    "Vision QA image bytes exceed the governed request budget",
                )
            encoded.append(
                f"data:{record.content_type};base64,{base64.b64encode(content).decode('ascii')}"
            )
        return encoded

    def _latest_artifact(self, run_id: str, task_type: str) -> AgentArtifact:
        matches = [
            item for item in self.inference.artifacts_for_run(run_id) if item.task_type == task_type
        ]
        if not matches:
            raise AiListingPipelineError(
                "agent_artifact_missing",
                f"AI artifact is missing for {task_type}",
            )
        return max(matches, key=lambda item: (item.version, item.id))

    def _claim(self, run_id: str, *, worker_id: str, scope: dict[str, str]) -> None:
        now = datetime.now(UTC)
        with Session(self.engine) as session, session.begin():
            row = session.get(AiListingRunRow, run_id, with_for_update=True)
            if row is None or not self._row_in_scope(row, scope):
                raise KeyError(f"Unknown AI Listing run: {run_id}")
            self._assert_scope_authority(row, scope)
            if row.status in TERMINAL_STATES:
                return
            if row.lease_until and row.lease_until >= now and row.lease_owner != worker_id:
                raise AiListingPipelineError(
                    "ai_listing_lease_busy",
                    "AI Listing run is already leased by another worker",
                )
            row.lease_owner = worker_id
            row.lease_until = now + timedelta(seconds=self.lease_seconds)
            row.work_requested = True
            row.updated_at = now

    def _release(self, run_id: str, *, worker_id: str) -> None:
        with Session(self.engine) as session, session.begin():
            row = session.get(AiListingRunRow, run_id, with_for_update=True)
            if row is not None and row.lease_owner == worker_id:
                row.lease_owner = None
                row.lease_until = None
                row.updated_at = datetime.now(UTC)

    def _transition(
        self,
        run_id: str,
        *,
        worker_id: str,
        state: str,
        reason: str | None,
        artifact: AgentArtifact | None = None,
        artifacts: list[AgentArtifact] | None = None,
        internal_refs: dict[str, Any] | None = None,
    ) -> None:
        if state not in AI_LISTING_STATES:
            raise ValueError("Unknown AI Listing state")
        with Session(self.engine) as session, session.begin():
            row = session.get(AiListingRunRow, run_id, with_for_update=True)
            if row is None:
                raise KeyError(f"Unknown AI Listing run: {run_id}")
            if row.status in TERMINAL_STATES:
                return
            if row.lease_owner != worker_id:
                raise AiListingPipelineError(
                    "ai_listing_lease_lost",
                    "AI Listing worker lease was lost",
                )
            previous = row.status
            artifact_ids = dict(row.artifact_ids_json or {})
            for item in [value for value in [artifact, *(artifacts or [])] if value is not None]:
                artifact_ids[item.task_type] = item.id
            refs = dict(row.internal_refs_json or {})
            refs.update(internal_refs or {})
            now = datetime.now(UTC)
            row.status = state
            row.current_stage = state
            row.artifact_ids_json = artifact_ids
            row.internal_refs_json = refs
            row.blockers_json = []
            row.error_code = None
            row.error_detail = None
            row.updated_at = now
            if state in TERMINAL_STATES:
                row.work_requested = False
                row.completed_at = now
            self._event(
                session,
                run=row,
                event_type="ai_listing.stage.changed",
                state=state,
                reason=reason,
                actor_id=worker_id,
                idempotency_key=f"{row.id}:transition:{previous}:{state}",
                source_evidence_id=(artifact.raw_response_evidence_id if artifact else None),
            )

    def _pause(self, run_id: str, *, worker_id: str, code: str, detail: str) -> None:
        blocker = self._blocker(code, detail=detail)
        with Session(self.engine) as session, session.begin():
            row = session.get(AiListingRunRow, run_id, with_for_update=True)
            if row is None or row.status in TERMINAL_STATES:
                return
            if row.lease_owner != worker_id:
                raise AiListingPipelineError("ai_listing_lease_lost", "AI Listing worker lease was lost")
            row.blockers_json = [blocker]
            row.error_code = code
            row.error_detail = self._safe(detail, 2000)
            row.work_requested = False
            row.updated_at = datetime.now(UTC)
            event_key = f"{row.id}:pause:{row.status}:{code}"
            exists = session.scalar(
                select(AgentRunEventRow.id).where(
                    AgentRunEventRow.ai_listing_run_id == row.id,
                    AgentRunEventRow.idempotency_key == event_key,
                )
            )
            if not exists:
                self._event(
                    session,
                    run=row,
                    event_type="ai_listing.stage.paused",
                    state=row.status,
                    reason=code,
                    actor_id=worker_id,
                    idempotency_key=event_key,
                )

    def _block(self, run_id: str, *, worker_id: str, code: str, detail: str) -> None:
        self._terminal_failure(
            run_id,
            worker_id=worker_id,
            state="blocked",
            code=code,
            detail=detail,
        )

    def _fail(self, run_id: str, *, worker_id: str, code: str, detail: str) -> None:
        self._terminal_failure(
            run_id,
            worker_id=worker_id,
            state="failed",
            code=code,
            detail=detail,
        )

    def _terminal_failure(
        self,
        run_id: str,
        *,
        worker_id: str,
        state: str,
        code: str,
        detail: str,
    ) -> None:
        with Session(self.engine) as session, session.begin():
            row = session.get(AiListingRunRow, run_id, with_for_update=True)
            if row is None or row.status in TERMINAL_STATES:
                return
            previous = row.status
            now = datetime.now(UTC)
            row.current_stage = previous
            row.status = state
            row.blockers_json = [self._blocker(code, detail=detail)]
            row.error_code = self._safe(code, 160)
            row.error_detail = self._safe(detail, 2000)
            row.work_requested = False
            row.updated_at = now
            row.completed_at = now
            self._event(
                session,
                run=row,
                event_type=f"ai_listing.run.{state}",
                state=state,
                reason=code,
                actor_id=worker_id,
                idempotency_key=f"{row.id}:{state}:{previous}:{code}",
            )

    def _projection(self, run_id: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            row = session.get(AiListingRunRow, run_id)
            if row is None:
                raise KeyError(f"Unknown AI Listing run: {run_id}")
            attempts = list(
                session.scalars(
                    select(AgentRunRow)
                    .where(AgentRunRow.ai_listing_run_id == row.id)
                    .order_by(AgentRunRow.started_at, AgentRunRow.attempt)
                )
            )
            events = list(
                session.scalars(
                    select(AgentRunEventRow)
                    .where(AgentRunEventRow.ai_listing_run_id == row.id)
                    .order_by(AgentRunEventRow.occurred_at, AgentRunEventRow.id)
                )
            )
            artifacts = self.inference.artifacts_for_run(row.id)
            cost = sum((item.cost_usd for item in attempts), Decimal("0"))
            return {
                "contract_id": self.CONTRACT_ID,
                "id": row.id,
                "status": row.status,
                "current_stage": row.current_stage,
                "scope": {
                    "tenant_ref": row.tenant_ref,
                    "entity_ref": row.entity_ref,
                    "store_ref": row.store_ref,
                    "scope_grant_authority_sha256": row.scope_grant_authority_sha256,
                },
                "capture_submission_id": row.capture_submission_id,
                "capture_evidence_id": row.capture_evidence_id,
                "selected_variant_key": row.selected_variant_key,
                "target_marketplace": row.target_marketplace,
                "target_locale": row.target_locale,
                "mode": row.mode,
                "as_of": self._iso(row.as_of),
                "frozen_at": self._iso(row.frozen_at),
                "input_snapshot_sha256": row.input_snapshot_sha256,
                "selected_item": row.selected_item_json,
                "bindings": row.bindings_json,
                "artifact_ids": row.artifact_ids_json,
                "internal_refs": row.internal_refs_json,
                "artifacts": [item.to_dict() for item in artifacts],
                "model_trace": [
                    {
                        "id": item.id,
                        "task_type": item.task_type,
                        "attempt": item.attempt,
                        "provider": item.provider,
                        "model": item.model,
                        "prompt_version": item.prompt_version,
                        "input_snapshot_sha256": item.input_snapshot_sha256,
                        "status": item.status,
                        "fallback_reason": item.fallback_reason,
                        "input_tokens": item.input_tokens,
                        "output_tokens": item.output_tokens,
                        "cost_usd": str(item.cost_usd),
                        "latency_ms": item.latency_ms,
                        "error_code": item.error_code,
                    }
                    for item in attempts
                ],
                "total_cost_usd": str(cost),
                "blockers": row.blockers_json,
                "next_action": row.blockers_json[0] if row.blockers_json else None,
                "work_requested": row.work_requested,
                "error": (
                    {"code": row.error_code, "detail": row.error_detail}
                    if row.error_code
                    else None
                ),
                "events": [
                    {
                        "id": item.id,
                        "event_type": item.event_type,
                        "state": item.state,
                        "reason": item.reason,
                        "actor_id": item.actor_id,
                        "occurred_at": self._iso(item.occurred_at),
                    }
                    for item in events
                ],
                "requested_by": row.requested_by,
                "created_at": self._iso(row.created_at),
                "updated_at": self._iso(row.updated_at),
                "completed_at": self._iso(row.completed_at) if row.completed_at else None,
                "control_envelope": self._control_envelope(),
            }

    def _event(
        self,
        session: Session,
        *,
        run: AiListingRunRow,
        event_type: str,
        state: str,
        reason: str | None,
        actor_id: str,
        idempotency_key: str,
        source_evidence_id: str | None = None,
    ) -> None:
        now = datetime.now(UTC)
        body = {
            "ai_listing_run_id": run.id,
            "event_type": event_type,
            "state": state,
            "reason": reason,
            "actor_id": actor_id,
            "occurred_at": now.isoformat(),
        }
        outbox = add_outbox_event(
            session,
            event_type,
            run.id,
            {
                "state": state,
                "current_stage": run.current_stage,
                "reason": reason,
                "external_write_allowed": False,
            },
            actor_id=actor_id,
            source_evidence_id=source_evidence_id,
        )
        session.flush()
        session.add(
            AgentRunEventRow(
                id=new_id("age"),
                ai_listing_run_id=run.id,
                agent_run_id=None,
                event_type=event_type,
                state=state,
                reason=self._safe(reason, 500) if reason else None,
                actor_id=actor_id,
                idempotency_key=idempotency_key,
                event_sha256=self._hash(body),
                outbox_event_id=outbox.event_id,
                occurred_at=now,
            )
        )

    def _scope(
        self,
        *,
        principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, str]:
        if as_of.tzinfo is None:
            raise ValueError("as_of must include a timezone")
        if not principal.can_access_store(store_ref):
            raise PermissionError("Authenticated identity is not authorized for store_ref")
        if entity_scope.get("status") != "ready" or not entity_scope.get("entity_ref"):
            raise AiListingPipelineError(
                "entity_scope_authority_missing",
                "AI Listing requires one current independently reviewed entity scope",
            )
        authority = str(entity_scope.get("authority_sha256") or "").strip()
        if len(authority) != 64:
            raise AiListingPipelineError(
                "entity_scope_authority_invalid",
                "Entity scope authority SHA-256 is missing or invalid",
            )
        return {
            "tenant_ref": principal.tenant_ref,
            "entity_ref": str(entity_scope["entity_ref"]),
            "store_ref": store_ref,
            "scope_grant_authority_sha256": authority,
        }

    @staticmethod
    def _row_in_scope(row: AiListingRunRow, scope: dict[str, str]) -> bool:
        return (
            row.tenant_ref == scope["tenant_ref"]
            and row.entity_ref == scope["entity_ref"]
            and row.store_ref == scope["store_ref"]
        )

    @staticmethod
    def _assert_scope_authority(row: AiListingRunRow, scope: dict[str, str]) -> None:
        if row.scope_grant_authority_sha256 != scope["scope_grant_authority_sha256"]:
            raise AiListingPipelineError(
                "scope_authority_changed",
                "AI Listing scope authority changed; the frozen run cannot continue",
            )

    @classmethod
    def _blocker(cls, code: str, *, detail: str | None = None) -> dict[str, Any]:
        routes = {
            "ai_listing_feature_disabled": ("platform-governance", "/ai-listing"),
            "entity_scope_authority_missing": ("identity-governance", "/authority-intake"),
            "entity_scope_authority_invalid": ("identity-governance", "/authority-intake"),
            "capture_scope_mismatch": ("evidence-governance", "/capture-inbox"),
            "selected_variant_not_unique": ("market-intelligence", "/capture-inbox"),
            "capture_marketplace_not_1688": ("market-intelligence", "/capture-inbox"),
            "operator_product_and_passport_binding_required": ("catalog-operator", "/product-content"),
            "product_taxonomy_evidence_required": ("catalog-operator", "/ai-listing"),
            "formal_economics_binding_required": ("finance-operator", "/sourcing"),
            "positive_downside_cm3_required": ("finance-review", "/profit"),
            "content_evidence_required": ("content-governance", "/ai-listing"),
            "approved_passports_required": ("passport-review", "/product-content"),
            "approved_media_rights_required": ("media-rights", "/media-factory"),
            "media_generation_pending": ("media-worker", "/media-factory"),
            "media_generation_failed": ("media-worker", "/media-factory"),
            "independent_human_media_qa_required": ("media-reviewer", "/media-factory"),
            "independent_listing_and_russian_review_required": ("listing-approver", "/listing-ops"),
            "execution_before_state_evidence_required": ("execution-governance", "/execution-ops"),
            "run_cancelled": ("requester", "/ai-listing"),
        }
        owner, workspace = routes.get(code, ("ai-listing-operator", "/ai-listing"))
        return {
            "code": code,
            "severity": "P0" if any(token in code for token in ("scope", "integrity", "invented")) else "P1",
            "owner": owner,
            "next_workspace": workspace,
            "resume_when": detail or code.replace("_", " "),
        }

    @staticmethod
    def _dedupe_blockers(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in items:
            code = str(item.get("code") or "unknown_blocker")
            if code not in seen:
                seen.add(code)
                result.append(item)
        return result

    @staticmethod
    def _description(listing: dict[str, Any]) -> str:
        bullets = [str(item).strip() for item in listing.get("bullet_points", []) if str(item).strip()]
        return listing["description"] + ("\n\n" + "\n".join(f"• {item}" for item in bullets) if bullets else "")

    @staticmethod
    def _image_content_type():
        from .domain import ContentType

        return ContentType.IMAGE

    @staticmethod
    def _evidence_ids(value: Any) -> list[str]:
        if not isinstance(value, list) or not value:
            raise AiListingPipelineError("evidence_ids_required", "Evidence IDs must be a non-empty list")
        result = [str(item or "").strip() for item in value]
        if any(not item for item in result) or len(result) != len(set(result)):
            raise AiListingPipelineError(
                "evidence_ids_invalid",
                "Evidence IDs must be non-empty and unique",
            )
        return result

    @staticmethod
    def _control_envelope() -> dict[str, Any]:
        return {
            "proposal_only": True,
            "formal_fact": False,
            "internal_listing_draft_allowed_after_existing_gates": True,
            "execution_plan_allowed_after_existing_gates": True,
            "dry_run_only": True,
            "execution_approval_created": False,
            "permit_created": False,
            "external_write_allowed": False,
            "ozon_request_created": False,
            "purchase_order_created": False,
            "payment_created": False,
        }

    def _row(self, run_id: str) -> AiListingRunRow:
        with Session(self.engine) as session:
            row = session.get(AiListingRunRow, run_id)
            if row is None:
                raise KeyError(f"Unknown AI Listing run: {run_id}")
            session.expunge(row)
            return row

    @staticmethod
    def _hash(value: Any) -> str:
        canonical = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    @staticmethod
    def _text(value: Any, field: str, limit: int) -> str:
        text = str(value or "").strip()
        if not text or len(text) > limit:
            raise ValueError(f"{field} must contain 1 to {limit} characters")
        return text

    @staticmethod
    def _safe(value: Any, limit: int) -> str:
        return " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())[:limit]

    @staticmethod
    def _iso(value: datetime) -> str:
        return value.astimezone(UTC).isoformat()
