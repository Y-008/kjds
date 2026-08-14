from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from .agent_runtime import (
    RUNTIME_CONTRACT_ID,
    AgentRunEvidenceRef,
    AgentRunScopeContext,
    AgentRuntimePolicyError,
    GovernedRunReceipt,
    RuntimeAuditEnvelope,
    RuntimeAuditEvent,
    RuntimeAuditPreparation,
    _assert_event_transition,
    _audit_event_payload,
    _canonical,
    _decimal_string,
    _event_status,
    _iso,
    _run_listing,
    _run_projection,
    _sha256,
    _stable_id,
    _validate_page,
)
from .evidence import EvidenceGrade, EvidenceService
from .sql_repository import Base

AGENT_RUN_EVIDENCE_SOURCE = "governed-agent-run-evidence"
AGENT_RUN_EVIDENCE_CONTRACT = "kjds-governed-agent-run-evidence-v1"
_ZERO_SHA256 = "0" * 64
_TERMINAL_EVENTS = frozenset(
    {"run_succeeded", "run_failed", "run_denied", "unknown_outcome"}
)


class AgentRuntimeRunEnvelopeRow(Base):
    __tablename__ = "agent_runtime_run_envelopes"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "authority_sha256",
            name="uq_agent_runtime_run_exact_scope",
        ),
        UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "authority_sha256",
            "idempotency_sha256",
            name="uq_agent_runtime_scope_idempotency",
        ),
        CheckConstraint("input_bytes >= 0", name="ck_agent_runtime_input_bytes"),
        CheckConstraint("max_cost_usd >= 0", name="ck_agent_runtime_max_cost"),
        CheckConstraint("max_latency_ms > 0", name="ck_agent_runtime_max_latency"),
        CheckConstraint(
            "max_attempts > 0 AND max_attempts <= 8",
            name="ck_agent_runtime_max_attempts",
        ),
        Index(
            "ix_agent_runtime_run_scope_started",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "authority_sha256",
            "started_at",
        ),
    )

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(32), nullable=False)
    root_span_id: Mapped[str] = mapped_column(String(16), nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_as_of: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    task_type: Mapped[str] = mapped_column(String(160), nullable=False)
    registry_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    contract_version: Mapped[str] = mapped_column(String(160), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(160), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(160), nullable=False)
    routing_policy_version: Mapped[str] = mapped_column(String(160), nullable=False)
    prompt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    output_schema_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_contract_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    input_field_names_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    input_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    scoped_evidence_refs_json: Mapped[list[dict[str, str]]] = mapped_column(
        JSON, nullable=False
    )
    evidence_snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    required_capabilities_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    allowed_tools_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    max_cost_usd: Mapped[Decimal] = mapped_column(Numeric(30, 18), nullable=False)
    max_latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class AgentRuntimeRunEventRow(Base):
    __tablename__ = "agent_runtime_run_events"
    __table_args__ = (
        ForeignKeyConstraint(
            [
                "run_id",
                "tenant_ref",
                "entity_ref",
                "store_ref",
                "authority_sha256",
            ],
            [
                "agent_runtime_run_envelopes.run_id",
                "agent_runtime_run_envelopes.tenant_ref",
                "agent_runtime_run_envelopes.entity_ref",
                "agent_runtime_run_envelopes.store_ref",
                "agent_runtime_run_envelopes.authority_sha256",
            ],
            name="fk_agent_runtime_event_exact_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "run_id",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "authority_sha256",
            "event_index",
            name="uq_agent_runtime_event_ordinal",
        ),
        UniqueConstraint(
            "run_id",
            "event_sha256",
            name="uq_agent_runtime_event_hash",
        ),
        UniqueConstraint(
            "evidence_id",
            name="uq_agent_runtime_event_evidence",
        ),
        CheckConstraint("event_index > 0", name="ck_agent_runtime_event_index"),
        CheckConstraint("input_tokens >= 0", name="ck_agent_runtime_input_tokens"),
        CheckConstraint("output_tokens >= 0", name="ck_agent_runtime_output_tokens"),
        CheckConstraint("cost_usd >= 0", name="ck_agent_runtime_event_cost"),
        CheckConstraint("latency_ms >= 0", name="ck_agent_runtime_event_latency"),
        CheckConstraint(
            "event_type IN ('run_started','route_selected','attempt_started',"
            "'attempt_completed','attempt_denied','attempt_failed','eval_completed',"
            "'run_succeeded','run_failed','run_denied','unknown_outcome')",
            name="ck_agent_runtime_event_type",
        ),
        Index("ix_agent_runtime_event_run", "run_id", "event_index"),
    )

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    event_index: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(160), nullable=True)
    adapter_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    adapter_config_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    output_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    eval_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(30, 18), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    safe_payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    previous_event_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    event_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_records.id", ondelete="RESTRICT"), nullable=False
    )
    evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class SqlAgentRuntimeEvidenceLedger:
    """Append-only exact-scope Agent run ledger backed by immutable Evidence."""

    def __init__(self, *, engine, evidence: EvidenceService) -> None:
        self.engine = engine
        self.evidence = evidence

    def prepare(self, envelope: RuntimeAuditEnvelope) -> RuntimeAuditPreparation:
        self._validate_input_evidence(envelope)
        try:
            return self._prepare(envelope, allow_insert=True)
        except IntegrityError:
            return self._prepare(envelope, allow_insert=False)

    def _prepare(
        self,
        envelope: RuntimeAuditEnvelope,
        *,
        allow_insert: bool,
    ) -> RuntimeAuditPreparation:
        with self.evidence.transaction() as session:
            row = session.scalar(
                self._idempotency_query(envelope).with_for_update()
            )
            if row is None:
                if not allow_insert:
                    raise AgentRuntimePolicyError(
                        "idempotency_state_unavailable",
                        "The governed run idempotency winner is unavailable",
                    )
                row = self._new_envelope_row(envelope)
                session.add(row)
                session.flush()
                self._append_in_session(
                    session,
                    row=row,
                    event=RuntimeAuditEvent(
                        event_type="run_started",
                        occurred_at=envelope.started_at,
                    ),
                )
                return RuntimeAuditPreparation("new")
            if row.request_sha256 != envelope.request_sha256:
                raise AgentRuntimePolicyError(
                    "idempotency_conflict",
                    "Idempotency key was already used for different governed input",
                )
            events = self._event_rows(session, row.run_id, lock=True)
            event_payloads = self._verified_events(events)
            if event_payloads[-1]["event_type"] == "run_started":
                return RuntimeAuditPreparation("resume")
            if event_payloads[-1]["event_type"] not in _TERMINAL_EVENTS:
                self._append_in_session(
                    session,
                    row=row,
                    event=RuntimeAuditEvent(
                        event_type="unknown_outcome",
                        reason_code="provider_outcome_not_terminal",
                        occurred_at=envelope.started_at,
                    ),
                )
                events = self._event_rows(session, row.run_id, lock=False)
                event_payloads = self._verified_events(events)
                return RuntimeAuditPreparation(
                    "unknown_outcome",
                    self._receipt(row, event_payloads),
                )
            return RuntimeAuditPreparation(
                "replay",
                self._receipt(row, event_payloads),
            )

    def append(self, *, run_id: str, event: RuntimeAuditEvent) -> None:
        with self.evidence.transaction() as session:
            row = session.scalar(
                select(AgentRuntimeRunEnvelopeRow)
                .where(AgentRuntimeRunEnvelopeRow.run_id == run_id)
                .with_for_update()
            )
            if row is None:
                raise KeyError("Unknown governed Agent run")
            self._append_in_session(session, row=row, event=event)

    def list_runs(
        self,
        *,
        context: AgentRunScopeContext,
        status: str | None,
        task_type: str | None,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        _validate_page(limit=limit, offset=offset)
        with Session(self.engine) as session:
            statement = self._scope_query(context).order_by(
                AgentRuntimeRunEnvelopeRow.started_at.desc(),
                AgentRuntimeRunEnvelopeRow.run_id.desc(),
            )
            if task_type is not None:
                statement = statement.where(
                    AgentRuntimeRunEnvelopeRow.task_type == task_type
                )
            rows = list(session.scalars(statement))
            projections = []
            for row in rows:
                event_rows = self._event_rows(session, row.run_id, lock=False)
                events = self._verified_events(
                    event_rows
                )
                if status is not None and _event_status(
                    str(events[-1]["event_type"])
                ) != status:
                    continue
                projections.append(
                    self._projection(
                        row,
                        events,
                        event_rows=event_rows,
                        include_events=False,
                    )
                )
        total = len(projections)
        return _run_listing(
            rows=projections[offset : offset + limit],
            total=total,
            limit=limit,
            offset=offset,
        )

    def get_run(
        self,
        *,
        context: AgentRunScopeContext,
        run_id: str,
    ) -> dict[str, Any]:
        with Session(self.engine) as session:
            row = session.scalar(
                self._scope_query(context).where(
                    AgentRuntimeRunEnvelopeRow.run_id == run_id
                )
            )
            if row is None:
                raise KeyError("Governed Agent run not found")
            event_rows = self._event_rows(session, row.run_id, lock=False)
            events = self._verified_events(event_rows)
            return self._projection(
                row,
                events,
                event_rows=event_rows,
                include_events=True,
            )

    def replay(
        self,
        *,
        context: AgentRunScopeContext,
        run_id: str,
    ) -> GovernedRunReceipt:
        with Session(self.engine) as session:
            row = session.scalar(
                self._scope_query(context).where(
                    AgentRuntimeRunEnvelopeRow.run_id == run_id
                )
            )
            if row is None:
                raise KeyError("Governed Agent run not found")
            events = self._verified_events(
                self._event_rows(session, row.run_id, lock=False)
            )
            return self._receipt(row, events)

    def _append_in_session(
        self,
        session: Session,
        *,
        row: AgentRuntimeRunEnvelopeRow,
        event: RuntimeAuditEvent,
    ) -> None:
        existing = self._event_rows(session, row.run_id, lock=True)
        if existing:
            payloads = self._verified_events(existing)
        elif event.event_type == "run_started":
            payloads = []
        else:
            raise AgentRuntimePolicyError(
                "audit_event_missing",
                "Governed Agent run has no immutable start event",
            )
        _assert_event_transition(payloads, event.event_type)
        occurred_at = _utc(event.occurred_at or datetime.now(UTC))
        payload = _audit_event_payload(
            event=event,
            event_index=len(existing) + 1,
            previous_event_sha256=(
                str(payloads[-1]["event_sha256"]) if payloads else _ZERO_SHA256
            ),
            occurred_at=occurred_at,
        )
        event_id = _stable_id(
            "agev",
            {"run_id": row.run_id, "event_sha256": payload["event_sha256"]},
            24,
        )
        evidence_payload = {
            "contract_id": AGENT_RUN_EVIDENCE_CONTRACT,
            "run_id": row.run_id,
            "event_id": event_id,
            **payload,
            "payload_status": "not_retained",
            "proposal_only": True,
            "formal_fact": False,
            "external_write_allowed": False,
        }
        evidence = self.evidence.capture(
            content=_canonical(evidence_payload),
            filename=f"{event_id}.json",
            content_type="application/json",
            source=AGENT_RUN_EVIDENCE_SOURCE,
            source_ref=f"agent-run://{row.run_id}/{event_id}",
            grade=EvidenceGrade.B,
            effective_at=_iso(occurred_at),
            effective_until=None,
            created_by="kjds-agent-runtime",
            metadata={
                "contract_id": AGENT_RUN_EVIDENCE_CONTRACT,
                "tenant_ref": row.tenant_ref,
                "entity_ref": row.entity_ref,
                "store_ref": row.store_ref,
                "authority_sha256": row.authority_sha256,
                "run_id": row.run_id,
                "event_id": event_id,
                "event_type": event.event_type,
                "event_sha256": payload["event_sha256"],
                "retention_class": "security",
                "legal_hold": False,
            },
            _session=session,
        )
        session.add(
            AgentRuntimeRunEventRow(
                event_id=event_id,
                run_id=row.run_id,
                tenant_ref=row.tenant_ref,
                entity_ref=row.entity_ref,
                store_ref=row.store_ref,
                authority_sha256=row.authority_sha256,
                event_index=int(payload["event_index"]),
                event_type=str(payload["event_type"]),
                reason_code=payload["reason_code"],
                adapter_sha256=payload["adapter_sha256"],
                provider_sha256=payload["provider_sha256"],
                model_sha256=payload["model_sha256"],
                adapter_config_sha256=payload["adapter_config_sha256"],
                output_sha256=payload["output_sha256"],
                eval_sha256=payload["eval_sha256"],
                input_tokens=int(payload["input_tokens"]),
                output_tokens=int(payload["output_tokens"]),
                cost_usd=Decimal(str(payload["cost_usd"])),
                latency_ms=int(payload["latency_ms"]),
                safe_payload_json=dict(payload["safe_payload"]),
                previous_event_sha256=str(payload["previous_event_sha256"]),
                event_sha256=str(payload["event_sha256"]),
                evidence_id=evidence.id,
                evidence_sha256=evidence.sha256,
                occurred_at=occurred_at,
                recorded_at=datetime.now(UTC),
            )
        )
        session.flush()

    def _verified_events(
        self,
        rows: Sequence[AgentRuntimeRunEventRow],
    ) -> list[dict[str, Any]]:
        payloads: list[dict[str, Any]] = []
        previous = _ZERO_SHA256
        for expected_index, row in enumerate(rows, start=1):
            payload = self._event_payload(row)
            declared_hash = str(payload.pop("event_sha256"))
            if (
                row.event_index != expected_index
                or row.previous_event_sha256 != previous
                or _sha256(payload) != declared_hash
            ):
                raise AgentRuntimePolicyError(
                    "audit_chain_invalid",
                    "Governed Agent run event chain integrity failed",
                )
            payload["event_sha256"] = declared_hash
            self.evidence.require_valid([row.evidence_id])
            evidence = self.evidence.get(row.evidence_id)
            if (
                evidence.sha256 != row.evidence_sha256
                or evidence.source != AGENT_RUN_EVIDENCE_SOURCE
                or evidence.source_ref
                != f"agent-run://{row.run_id}/{row.event_id}"
                or evidence.metadata.get("event_sha256") != declared_hash
            ):
                raise AgentRuntimePolicyError(
                    "audit_evidence_invalid",
                    "Governed Agent run Evidence integrity failed",
                )
            payloads.append(payload)
            previous = declared_hash
        if not payloads:
            raise AgentRuntimePolicyError(
                "audit_event_missing",
                "Governed Agent run has no immutable start event",
            )
        return payloads

    def _validate_input_evidence(self, envelope: RuntimeAuditEnvelope) -> None:
        try:
            ids = [item.evidence_id for item in envelope.scope.evidence_refs]
            self.evidence.require_current(ids, as_of=envelope.scope.scope_as_of)
            for item in envelope.scope.evidence_refs:
                if self.evidence.get(item.evidence_id).sha256 != item.evidence_sha256:
                    raise ValueError("Scoped Evidence hash does not match")
        except (KeyError, RuntimeError, ValueError) as exc:
            raise AgentRuntimePolicyError(
                "scoped_evidence_invalid",
                "Governed runtime requires current untampered scoped Evidence",
            ) from exc

    @staticmethod
    def _event_payload(row: AgentRuntimeRunEventRow) -> dict[str, Any]:
        return {
            "event_index": row.event_index,
            "event_type": row.event_type,
            "reason_code": row.reason_code,
            "adapter_sha256": row.adapter_sha256,
            "provider_sha256": row.provider_sha256,
            "model_sha256": row.model_sha256,
            "adapter_config_sha256": row.adapter_config_sha256,
            "output_sha256": row.output_sha256,
            "eval_sha256": row.eval_sha256,
            "input_tokens": row.input_tokens,
            "output_tokens": row.output_tokens,
            "cost_usd": _decimal_string(row.cost_usd),
            "latency_ms": row.latency_ms,
            "safe_payload": dict(row.safe_payload_json),
            "previous_event_sha256": row.previous_event_sha256,
            "occurred_at": _iso(_utc(row.occurred_at)),
            "event_sha256": row.event_sha256,
        }

    @staticmethod
    def _event_rows(
        session: Session,
        run_id: str,
        *,
        lock: bool,
    ) -> list[AgentRuntimeRunEventRow]:
        statement = (
            select(AgentRuntimeRunEventRow)
            .where(AgentRuntimeRunEventRow.run_id == run_id)
            .order_by(AgentRuntimeRunEventRow.event_index)
        )
        if lock:
            statement = statement.with_for_update()
        return list(session.scalars(statement))

    @staticmethod
    def _idempotency_query(envelope: RuntimeAuditEnvelope):
        return select(AgentRuntimeRunEnvelopeRow).where(
            AgentRuntimeRunEnvelopeRow.tenant_ref == envelope.scope.tenant_ref,
            AgentRuntimeRunEnvelopeRow.entity_ref == envelope.scope.entity_ref,
            AgentRuntimeRunEnvelopeRow.store_ref == envelope.scope.store_ref,
            AgentRuntimeRunEnvelopeRow.authority_sha256
            == envelope.scope.authority_sha256,
            AgentRuntimeRunEnvelopeRow.idempotency_sha256
            == _sha256(envelope.idempotency_key),
        )

    @staticmethod
    def _scope_query(context: AgentRunScopeContext):
        return select(AgentRuntimeRunEnvelopeRow).where(
            AgentRuntimeRunEnvelopeRow.tenant_ref == context.tenant_ref,
            AgentRuntimeRunEnvelopeRow.entity_ref == context.entity_ref,
            AgentRuntimeRunEnvelopeRow.store_ref == context.store_ref,
            AgentRuntimeRunEnvelopeRow.authority_sha256
            == context.authority_sha256,
            AgentRuntimeRunEnvelopeRow.started_at <= context.scope_as_of,
        )

    @staticmethod
    def _new_envelope_row(
        envelope: RuntimeAuditEnvelope,
    ) -> AgentRuntimeRunEnvelopeRow:
        return AgentRuntimeRunEnvelopeRow(
            run_id=envelope.run_id,
            trace_id=envelope.trace_id,
            root_span_id=envelope.root_span_id,
            tenant_ref=envelope.scope.tenant_ref,
            entity_ref=envelope.scope.entity_ref,
            store_ref=envelope.scope.store_ref,
            authority_sha256=envelope.scope.authority_sha256,
            actor_id=envelope.scope.actor_id,
            scope_as_of=envelope.scope.scope_as_of,
            task_type=envelope.task_type,
            registry_sha256=envelope.registry_sha256,
            contract_version=envelope.contract_version,
            prompt_version=envelope.prompt_version,
            schema_version=envelope.schema_version,
            routing_policy_version=envelope.routing_policy_version,
            prompt_sha256=envelope.prompt_sha256,
            output_schema_sha256=envelope.output_schema_sha256,
            tool_contract_sha256=envelope.tool_contract_sha256,
            idempotency_sha256=_sha256(envelope.idempotency_key),
            request_sha256=envelope.request_sha256,
            input_sha256=envelope.input_sha256,
            input_field_names_json=list(envelope.input_field_names),
            input_bytes=envelope.input_bytes,
            scoped_evidence_refs_json=[
                {
                    "evidence_id": item.evidence_id,
                    "evidence_sha256": item.evidence_sha256,
                }
                for item in sorted(
                    envelope.scope.evidence_refs,
                    key=lambda value: value.evidence_id,
                )
            ],
            evidence_snapshot_sha256=envelope.evidence_snapshot_sha256,
            required_capabilities_json=list(envelope.required_capabilities),
            allowed_tools_json=list(envelope.allowed_tools),
            max_cost_usd=envelope.max_cost_usd,
            max_latency_ms=envelope.max_latency_ms,
            max_attempts=envelope.max_attempts,
            started_at=envelope.started_at,
        )

    @staticmethod
    def _envelope(row: AgentRuntimeRunEnvelopeRow) -> RuntimeAuditEnvelope:
        context = AgentRunScopeContext(
            tenant_ref=row.tenant_ref,
            entity_ref=row.entity_ref,
            store_ref=row.store_ref,
            authority_sha256=row.authority_sha256,
            actor_id=row.actor_id,
            scope_as_of=_utc(row.scope_as_of),
            evidence_refs=tuple(
                AgentRunEvidenceRef(
                    evidence_id=str(item["evidence_id"]),
                    evidence_sha256=str(item["evidence_sha256"]),
                )
                for item in row.scoped_evidence_refs_json
            ),
        )
        return RuntimeAuditEnvelope(
            run_id=row.run_id,
            trace_id=row.trace_id,
            root_span_id=row.root_span_id,
            scope=context,
            task_type=row.task_type,
            registry_sha256=row.registry_sha256,
            contract_version=row.contract_version,
            prompt_version=row.prompt_version,
            schema_version=row.schema_version,
            routing_policy_version=row.routing_policy_version,
            prompt_sha256=row.prompt_sha256,
            output_schema_sha256=row.output_schema_sha256,
            tool_contract_sha256=row.tool_contract_sha256,
            idempotency_key=row.idempotency_sha256,
            request_sha256=row.request_sha256,
            input_sha256=row.input_sha256,
            input_field_names=tuple(row.input_field_names_json),
            input_bytes=row.input_bytes,
            evidence_snapshot_sha256=row.evidence_snapshot_sha256,
            required_capabilities=tuple(row.required_capabilities_json),
            allowed_tools=tuple(row.allowed_tools_json),
            max_cost_usd=row.max_cost_usd,
            max_latency_ms=row.max_latency_ms,
            max_attempts=row.max_attempts,
            started_at=_utc(row.started_at),
        )

    def _projection(
        self,
        row: AgentRuntimeRunEnvelopeRow,
        events: Sequence[dict[str, Any]],
        *,
        event_rows: Sequence[AgentRuntimeRunEventRow],
        include_events: bool,
    ) -> dict[str, Any]:
        evidence_refs = [
            {"evidence_id": item.evidence_id, "evidence_sha256": item.evidence_sha256}
            for item in event_rows
        ]
        payload = _run_projection(
            envelope=self._envelope(row),
            events=events,
            evidence_refs=evidence_refs,
        )
        if not include_events:
            payload.pop("events")
        return payload

    @staticmethod
    def _receipt(
        row: AgentRuntimeRunEnvelopeRow,
        events: Sequence[dict[str, Any]],
    ) -> GovernedRunReceipt:
        latest = events[-1]
        return GovernedRunReceipt(
            contract_id=RUNTIME_CONTRACT_ID,
            run_id=row.run_id,
            trace_id=row.trace_id,
            task_type=row.task_type,
            status=_event_status(str(latest["event_type"])),
            input_sha256=row.input_sha256,
            output_sha256=next(
                (
                    str(item["output_sha256"])
                    for item in reversed(events)
                    if item.get("output_sha256")
                ),
                None,
            ),
            eval_sha256=next(
                (
                    str(item["eval_sha256"])
                    for item in reversed(events)
                    if item.get("eval_sha256")
                ),
                None,
            ),
            event_count=len(events),
        )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
