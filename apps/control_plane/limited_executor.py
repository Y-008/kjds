from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, UniqueConstraint, select, text
from sqlalchemy.orm import Mapped, Session, mapped_column

from .action_policies import ActionPolicyRegistry
from .correlation import correlation_id
from .domain import new_id
from .evidence import EvidenceGrade
from .pilot_readiness import OZON_PRODUCT_READ_CONTRACT_VERSION
from .sql_repository import Base

CommandKind = Literal["execute", "rollback"]
ReceiptOutcome = Literal["succeeded", "failed", "uncertain"]
ExecutionArtifactKind = Literal[
    "before_read",
    "product_import_response",
    "import_status_response",
    "after_read",
]

OZON_EXECUTION_EVIDENCE_SOURCE = "ozon-isolated-execution-worker"
OZON_RESPONSE_BUNDLE_SCHEMA_VERSION = "ozon-response-bundle-v2"
OZON_EXECUTION_CONTRACT_VERSION = "ozon-execution-v1"
MAX_OZON_RESPONSE_BODY_BYTES = 1024 * 1024
EXECUTION_ARTIFACT_RELATIONSHIPS = {
    "before_read": "before_read_response",
    "product_import_response": "product_import_response",
    "import_status_response": "import_status_response",
    "after_read": "after_read_response",
}


class LimitedExecutionCommandRow(Base):
    __tablename__ = "limited_execution_commands"
    __table_args__ = (
        UniqueConstraint("plan_id", "command_kind", name="uq_limited_command_kind"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    plan_id: Mapped[str] = mapped_column(
        ForeignKey("governed_execution_plans.id"), nullable=False
    )
    parent_command_id: Mapped[str | None] = mapped_column(
        ForeignKey("limited_execution_commands.id"), nullable=True
    )
    command_kind: Mapped[str] = mapped_column(String, nullable=False)
    idempotency_token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    adapter_id: Mapped[str] = mapped_column(String, nullable=False)
    action_id: Mapped[str] = mapped_column(String, nullable=False)
    action_policy_version: Mapped[str] = mapped_column(String, nullable=False)
    decision_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    permit_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    operation: Mapped[str] = mapped_column(String, nullable=False)
    target_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    patch_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    risk_limits_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    risk_values_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    risk_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    portfolio_risk_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    expected_state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    queued_by: Mapped[str] = mapped_column(String, nullable=False)
    claimed_by: Mapped[str | None] = mapped_column(String, nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LimitedExecutionReceiptRow(Base):
    __tablename__ = "limited_execution_receipts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    command_id: Mapped[str] = mapped_column(
        ForeignKey("limited_execution_commands.id"), unique=True, nullable=False
    )
    request_id: Mapped[str] = mapped_column(
        String(128), default=lambda: correlation_id(None, "req"), nullable=False
    )
    trace_id: Mapped[str] = mapped_column(
        String(128), default=lambda: correlation_id(None, "trace"), nullable=False
    )
    outcome: Mapped[str] = mapped_column(String, nullable=False)
    remote_operation_id: Mapped[str | None] = mapped_column(String, nullable=True)
    resulting_state_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mutation_applied: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    error_detail: Mapped[str | None] = mapped_column(String, nullable=True)
    evidence_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    recorded_by: Mapped[str] = mapped_column(String, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LimitedExecutorService:
    def __init__(
        self,
        *,
        engine,
        execution_plans,
        evidence,
        kill_switch,
        action_policies: ActionPolicyRegistry | None = None,
        enabled: bool = False,
        credential_grant_issuer=None,
    ) -> None:
        self.engine = engine
        self.execution_plans = execution_plans
        self.evidence = evidence
        self.kill_switch = kill_switch
        self.action_policies = action_policies or execution_plans.action_policies
        self.action_authorization = execution_plans.action_authorization
        self.enabled = enabled
        self.credential_grant_issuer = credential_grant_issuer

    def queue(self, plan_id: str, *, queued_by: str) -> dict[str, Any]:
        self._enabled()
        self.kill_switch.ensure_writes_allowed()
        queued_by = self._required(queued_by, "Command requester")
        plan = self.execution_plans.get(plan_id)
        if not plan["ready_for_executor"]:
            raise ValueError("Execution plan is not ready for the limited executor")
        if not plan["adapter"].get("command_delivery_supported"):
            raise ValueError("Execution adapter does not support live command delivery")
        self._authorize_plan(plan, queued_by=queued_by)
        existing = self._command_for(plan_id, "execute")
        if existing is not None:
            return self.get(existing.id)
        return self._insert_command(
            plan=plan,
            command_kind="execute",
            parent_command_id=None,
            operation=plan["adapter"]["operation"],
            patch=plan["intended_patch"],
            expected_state_hash=plan["precondition_state_hash"],
            queued_by=queued_by,
        )

    def claim(
        self,
        command_id: str,
        *,
        current_state_hash: str,
        worker_id: str,
        lease_seconds: int = 120,
    ) -> dict[str, Any]:
        self._enabled()
        self.kill_switch.ensure_writes_allowed()
        worker_id = self._required(worker_id, "Executor worker identity")
        current_state_hash = self._state_hash(current_state_hash)
        if not 30 <= lease_seconds <= 600:
            raise ValueError("Execution lease must be between 30 and 600 seconds")
        precondition_failed = False
        result = None
        with Session(self.engine) as session, session.begin():
            row = session.get(LimitedExecutionCommandRow, command_id, with_for_update=True)
            if row is None:
                raise KeyError(f"Limited execution command not found: {command_id}")
            if row.status != "queued":
                if row.status == "claimed" and row.claimed_by == worker_id:
                    self._authorize_command(
                        session, row, self.execution_plans.get(row.plan_id), worker_id
                    )
                    return self._command(row, None)
                raise ValueError("Execution command is not available for claim")
            plan = self.execution_plans.get(row.plan_id)
            if row.command_kind == "execute" and not plan["ready_for_executor"]:
                raise ValueError("Execution plan became invalid before claim")
            permit_expired = self._utc(row.permit_expires_at) <= datetime.now(UTC)
            if permit_expired:
                row.status = "expired"
            else:
                self._authorize_command(session, row, plan, worker_id)
            if permit_expired:
                precondition_failed = False
            elif current_state_hash != row.expected_state_hash:
                row.status = "precondition_failed"
                precondition_failed = True
            else:
                now = datetime.now(UTC)
                row.status = "claimed"
                row.claimed_by = worker_id
                row.claimed_at = now
                row.lease_expires_at = now + timedelta(seconds=lease_seconds)
                session.flush()
                result = self._command(row, None)
        if permit_expired:
            raise ValueError("Execution permit expired before claim")
        if precondition_failed:
            raise ValueError("Current platform state does not match the command precondition")
        if result is None:
            raise RuntimeError("Execution claim did not produce a command")
        return result

    def begin_write_attempt(self, command_id: str, *, worker_id: str) -> dict[str, Any]:
        """Consume the command's single external-write authorization."""
        self._enabled()
        self.kill_switch.ensure_writes_allowed()
        worker_id = self._required(worker_id, "Executor worker identity")
        lease_expired = False
        credential_grant = None
        result = None
        with Session(self.engine) as session, session.begin():
            row = session.get(LimitedExecutionCommandRow, command_id, with_for_update=True)
            if row is None:
                raise KeyError(f"Limited execution command not found: {command_id}")
            if row.status != "claimed" or row.claimed_by != worker_id:
                raise ValueError("Execution write attempt is not available")
            now = datetime.now(UTC)
            if row.lease_expires_at is None or self._utc(row.lease_expires_at) <= now:
                row.status = "uncertain"
                lease_expired = True
            else:
                plan = self.execution_plans.get(row.plan_id)
                if row.command_kind == "execute" and not plan["ready_for_executor"]:
                    raise ValueError("Execution plan became invalid before the write attempt")
                self._authorize_command(session, row, plan, worker_id)
                self.kill_switch.ensure_writes_allowed()
                row.status = "write_started"
                session.flush()
                if self.credential_grant_issuer is not None:
                    scope = self.execution_plans.scope_for(plan)
                    credential_grant = self.credential_grant_issuer.issue_for_execution_command(
                        session=session,
                        command=row,
                        scope=scope,
                        worker_id=worker_id,
                        as_of=now,
                    )
                result = self._command(row, None)
        if lease_expired:
            raise ValueError("Execution lease expired before the write attempt; command is uncertain")
        if result is None:
            raise RuntimeError("Execution write attempt did not produce a command")
        result["credential_grant"] = credential_grant
        result["credential_grant_bound"] = credential_grant is not None
        return result

    def capture_execution_artifact(
        self,
        command_id: str,
        *,
        artifact_kind: ExecutionArtifactKind,
        content: bytes,
        response_sha256: str,
        sequence_number: int | None,
        worker_id: str,
    ) -> dict[str, Any]:
        """Capture one immutable Ozon response artifact bound to its command."""
        self._enabled()
        worker_id = self._required(worker_id, "Executor worker identity")
        if artifact_kind not in EXECUTION_ARTIFACT_RELATIONSHIPS:
            raise ValueError("Unsupported execution artifact kind")
        if not content:
            raise ValueError("Execution artifact content cannot be empty")
        if len(content) > MAX_OZON_RESPONSE_BODY_BYTES * 3:
            raise ValueError("Execution artifact exceeds the bounded response contract")
        response_sha256 = self._state_hash(response_sha256)
        actual_sha256 = hashlib.sha256(content).hexdigest()
        if not hmac.compare_digest(response_sha256, actual_sha256):
            raise ValueError("Execution artifact SHA-256 does not match its content")
        if artifact_kind == "import_status_response":
            if (
                isinstance(sequence_number, bool)
                or not isinstance(sequence_number, int)
                or not 0 <= sequence_number < 60
            ):
                raise ValueError("Import status artifact requires a bounded sequence number")
        elif sequence_number is not None:
            raise ValueError("Only import status artifacts may have a sequence number")

        with Session(self.engine) as session:
            row = session.get(LimitedExecutionCommandRow, command_id)
            if row is None:
                raise KeyError(f"Limited execution command not found: {command_id}")
            if row.adapter_id != "ozon.product.import.v3":
                raise ValueError("Execution artifacts are only supported for the Ozon import adapter")
            if row.claimed_by != worker_id:
                raise ValueError("Only the worker that claimed the command may capture its artifacts")
            allowed_statuses = (
                {"claimed"}
                if artifact_kind == "before_read"
                else {"write_started", "succeeded", "failed", "uncertain"}
            )
            if row.status not in allowed_statuses:
                raise ValueError("Execution artifact is not valid for the command state")
            offer_id = self._required(
                str(row.target_json.get("offer_id", "")),
                "Ozon command offer id",
            )
            effective_at = self._iso(row.claimed_at or row.created_at)

        parsed = self._parse_execution_artifact(
            content,
            artifact_kind=artifact_kind,
            offer_id=offer_id,
        )
        source_ref = self._artifact_source_ref(
            command_id,
            artifact_kind,
            sequence_number,
        )
        existing = self.evidence.find_by_source_ref(
            source=OZON_EXECUTION_EVIDENCE_SOURCE,
            source_ref=source_ref,
        )
        if existing is not None:
            if not hmac.compare_digest(existing.sha256, response_sha256):
                raise ValueError("Execution artifact already has different immutable content")
            self._verify_execution_artifact_record(
                existing.id,
                command_id=command_id,
                artifact_kind=artifact_kind,
                sequence_number=sequence_number,
            )
            return self._artifact_result(existing.id, artifact_kind, sequence_number, parsed)

        captured = self.evidence.capture(
            content=content,
            filename=f"{command_id}-{artifact_kind}"
            + (f"-{sequence_number}" if sequence_number is not None else "")
            + ".json",
            content_type="application/json",
            source=OZON_EXECUTION_EVIDENCE_SOURCE,
            source_ref=source_ref,
            grade=EvidenceGrade.A,
            effective_at=effective_at,
            effective_until=None,
            created_by=worker_id,
            metadata={
                "retention_class": "operational",
                "raw_response_stored": True,
                "response_sha256": response_sha256,
                "response_byte_size": len(content),
                "artifact_kind": artifact_kind,
                "sequence_number": sequence_number,
                "command_id": command_id,
                "adapter_id": "ozon.product.import.v3",
                **parsed,
            },
        )
        self.evidence.link(
            evidence_id=captured.id,
            target_type="limited_execution_command",
            target_id=command_id,
            relationship=EXECUTION_ARTIFACT_RELATIONSHIPS[artifact_kind],
            created_by=worker_id,
        )
        return self._artifact_result(
            captured.id,
            artifact_kind,
            sequence_number,
            parsed,
        )

    def record_receipt(
        self,
        command_id: str,
        *,
        outcome: ReceiptOutcome,
        remote_operation_id: str | None,
        resulting_state_hash: str | None,
        mutation_applied: bool,
        error_code: str | None,
        error_detail: str | None,
        evidence_ids: list[str],
        recorded_by: str,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        self._enabled()
        recorded_by = self._required(recorded_by, "Receipt recorder")
        request_id = correlation_id(request_id, "req")
        trace_id = correlation_id(trace_id, "trace")
        evidence_ids = self._evidence(evidence_ids)
        remote_operation_id = self._optional(remote_operation_id)
        error_code = self._optional(error_code)
        error_detail = self._optional(error_detail)
        resulting_state_hash = (
            self._state_hash(resulting_state_hash) if resulting_state_hash else None
        )
        if outcome == "succeeded" and (not mutation_applied or not resulting_state_hash):
            raise ValueError("Successful execution requires applied mutation and resulting state hash")
        if outcome == "failed" and not error_code:
            raise ValueError("Failed execution requires an error code")
        canonical = {
            "command_id": command_id,
            "outcome": outcome,
            "remote_operation_id": remote_operation_id,
            "resulting_state_hash": resulting_state_hash,
            "mutation_applied": mutation_applied,
            "error_code": error_code,
            "error_detail": error_detail,
            "evidence_ids": evidence_ids,
            "recorded_by": recorded_by,
        }
        requested_hash = self._hash(canonical)
        rollback_id = None
        result = None
        with Session(self.engine) as session, session.begin():
            row = session.get(LimitedExecutionCommandRow, command_id, with_for_update=True)
            if row is None:
                raise KeyError(f"Limited execution command not found: {command_id}")
            existing = session.scalar(
                select(LimitedExecutionReceiptRow).where(
                    LimitedExecutionReceiptRow.command_id == command_id
                )
            )
            if existing is not None:
                if existing.request_hash != requested_hash:
                    raise ValueError("Execution receipt is immutable")
                return self._receipt(existing, self._rollback_for(session, command_id))
            if row.status != "write_started" or row.claimed_by != recorded_by:
                raise ValueError(
                    "Only the worker that consumed the command write attempt may record its receipt"
                )
            now = datetime.now(UTC)
            lease_expires = row.lease_expires_at
            if lease_expires and self._utc(lease_expires) < now:
                outcome = "uncertain"
                error_code = "EXECUTION_LEASE_EXPIRED"
                error_detail = "Execution lease expired before the receipt was durably accepted"
            self._verify_execution_receipt_evidence(
                row,
                evidence_ids=evidence_ids,
                outcome=outcome,
                remote_operation_id=remote_operation_id,
                resulting_state_hash=resulting_state_hash,
                error_code=error_code,
            )
            receipt = LimitedExecutionReceiptRow(
                id=new_id("lxr"),
                request_hash=requested_hash,
                command_id=command_id,
                request_id=request_id,
                trace_id=trace_id,
                outcome=outcome,
                remote_operation_id=remote_operation_id,
                resulting_state_hash=resulting_state_hash,
                mutation_applied=mutation_applied,
                error_code=error_code,
                error_detail=error_detail,
                evidence_json=evidence_ids,
                recorded_by=recorded_by,
                recorded_at=now,
            )
            session.add(receipt)
            row.status = outcome
            session.flush()
            if outcome in {"failed", "uncertain"} and mutation_applied and resulting_state_hash:
                rollback = self._build_rollback(session, row, resulting_state_hash, recorded_by)
                rollback_id = rollback.id
            result = self._receipt(receipt, rollback_id)
        if result is None:
            raise RuntimeError("Execution receipt did not produce a result")
        self._link(evidence_ids, "limited_execution_receipt", result["id"], recorded_by)
        return result

    def request_rollback(self, command_id: str, *, requested_by: str) -> dict[str, Any]:
        self._enabled()
        self.kill_switch.ensure_writes_allowed()
        requested_by = self._required(requested_by, "Rollback requester")
        with Session(self.engine) as session, session.begin():
            row = session.get(LimitedExecutionCommandRow, command_id, with_for_update=True)
            if row is None:
                raise KeyError(f"Limited execution command not found: {command_id}")
            if row.command_kind != "execute" or row.status != "succeeded":
                raise ValueError("Manual rollback requires a successful execution command")
            receipt = session.scalar(
                select(LimitedExecutionReceiptRow).where(
                    LimitedExecutionReceiptRow.command_id == command_id
                )
            )
            if receipt is None or not receipt.resulting_state_hash:
                raise ValueError("Rollback requires the resulting platform state hash")
            rollback = self._build_rollback(
                session,
                row,
                receipt.resulting_state_hash,
                requested_by,
            )
            rollback_id = rollback.id
        return self.get(rollback_id)

    def list(self) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            ids = list(
                session.scalars(
                    select(LimitedExecutionCommandRow.id).order_by(
                        LimitedExecutionCommandRow.created_at
                    )
                )
            )
        return [self.get(item_id) for item_id in ids]

    def get(self, command_id: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            row = session.get(LimitedExecutionCommandRow, command_id)
            if row is None:
                raise KeyError(f"Limited execution command not found: {command_id}")
            receipt = session.scalar(
                select(LimitedExecutionReceiptRow).where(
                    LimitedExecutionReceiptRow.command_id == command_id
                )
            )
            return self._command(row, receipt)

    def _insert_command(
        self,
        *,
        plan: dict[str, Any],
        command_kind: CommandKind,
        parent_command_id: str | None,
        operation: str,
        patch: dict[str, Any],
        expected_state_hash: str,
        queued_by: str,
    ) -> dict[str, Any]:
        token = self._hash(
            {"plan_id": plan["id"], "command_kind": command_kind, "patch": patch}
        )
        with Session(self.engine) as session, session.begin():
            now = datetime.now(UTC)
            if command_kind == "execute":
                self._lock_action_day(session, plan["action_id"], now)
                existing = session.scalar(
                    select(LimitedExecutionCommandRow).where(
                        LimitedExecutionCommandRow.plan_id == plan["id"],
                        LimitedExecutionCommandRow.command_kind == command_kind,
                    )
                )
                if existing is not None:
                    receipt = session.scalar(
                        select(LimitedExecutionReceiptRow).where(
                            LimitedExecutionReceiptRow.command_id == existing.id
                        )
                    )
                    return self._command(existing, receipt)
                portfolio_risk = self._action_budget_snapshot(
                    session,
                    action_id=plan["action_id"],
                    risk_limits=plan["risk_limits"],
                    risk_values=plan["risk_values"],
                    risk_currency=plan["risk_currency"],
                    occurred_at=now,
                )
                if "ACTION_DAILY_RUN_LIMIT_EXHAUSTED" in portfolio_risk["blocking_reasons"]:
                    raise ValueError("Action daily execution limit is exhausted")
                if not portfolio_risk["allowed"]:
                    raise ValueError(
                        "Action daily risk budget is exhausted: "
                        + ", ".join(portfolio_risk["blocking_reasons"])
                    )
            else:
                portfolio_risk = {
                    "schema_version": "action-budget-snapshot-v1",
                    "mode": "compensating_rollback",
                    "parent_command_id": parent_command_id,
                    "allowed": True,
                    "blocking_reasons": [],
                }
                portfolio_risk["snapshot_hash"] = self._hash(portfolio_risk)
            permit_expires_at = now + timedelta(seconds=plan["permit_ttl_seconds"])
            authorization = {
                "plan_id": plan["id"],
                "action_id": plan["action_id"],
                "action_policy_version": plan["action_policy_version"],
                "decision_hash": plan["decision_packet"]["decision_hash"],
                "risk_limits": plan["risk_limits"],
                "risk_values": plan["risk_values"],
                "risk_currency": plan["risk_currency"],
                "portfolio_risk_snapshot": portfolio_risk,
                "permit_expires_at": self._iso(permit_expires_at),
                "command_kind": command_kind,
            }
            row = LimitedExecutionCommandRow(
                id=new_id("lxc"),
                plan_id=plan["id"],
                parent_command_id=parent_command_id,
                command_kind=command_kind,
                idempotency_token=token,
                adapter_id=plan["adapter_id"],
                action_id=plan["action_id"],
                action_policy_version=plan["action_policy_version"],
                decision_hash=plan["decision_packet"]["decision_hash"],
                authorization_hash=self._hash(authorization),
                permit_expires_at=permit_expires_at,
                operation=operation,
                target_json=plan["target"],
                patch_json=patch,
                risk_limits_json=plan["risk_limits"],
                risk_values_json=plan["risk_values"],
                risk_currency=plan["risk_currency"],
                portfolio_risk_json=portfolio_risk,
                expected_state_hash=expected_state_hash,
                status="queued",
                queued_by=queued_by,
                created_at=now,
            )
            session.add(row)
            session.flush()
            return self._command(row, None)

    def _build_rollback(
        self,
        session: Session,
        parent: LimitedExecutionCommandRow,
        resulting_state_hash: str | None,
        queued_by: str,
    ) -> LimitedExecutionCommandRow:
        existing = session.scalar(
            select(LimitedExecutionCommandRow).where(
                LimitedExecutionCommandRow.plan_id == parent.plan_id,
                LimitedExecutionCommandRow.command_kind == "rollback",
            )
        )
        if existing is not None:
            return existing
        if not resulting_state_hash:
            parent.status = "uncertain"
            raise ValueError("Applied mutation without resulting state hash requires manual recovery")
        plan = self.execution_plans.get(parent.plan_id)
        token = self._hash(
            {"plan_id": parent.plan_id, "command_kind": "rollback", "patch": plan["rollback_patch"]}
        )
        now = datetime.now(UTC)
        permit_expires_at = now + timedelta(seconds=plan["permit_ttl_seconds"])
        authorization = {
            "parent_command_id": parent.id,
            "action_id": parent.action_id,
            "action_policy_version": parent.action_policy_version,
            "decision_hash": parent.decision_hash,
            "risk_limits": parent.risk_limits_json,
            "risk_values": parent.risk_values_json,
            "risk_currency": parent.risk_currency,
            "portfolio_risk_snapshot": {
                "schema_version": "action-budget-snapshot-v1",
                "mode": "compensating_rollback",
                "parent_command_id": parent.id,
                "allowed": True,
                "blocking_reasons": [],
            },
            "permit_expires_at": self._iso(permit_expires_at),
            "command_kind": "rollback",
        }
        authorization["portfolio_risk_snapshot"]["snapshot_hash"] = self._hash(
            authorization["portfolio_risk_snapshot"]
        )
        row = LimitedExecutionCommandRow(
            id=new_id("lxc"),
            plan_id=parent.plan_id,
            parent_command_id=parent.id,
            command_kind="rollback",
            idempotency_token=token,
            adapter_id=parent.adapter_id,
            action_id=parent.action_id,
            action_policy_version=parent.action_policy_version,
            decision_hash=parent.decision_hash,
            authorization_hash=self._hash(authorization),
            permit_expires_at=permit_expires_at,
            operation=plan["adapter"]["rollback_operation"],
            target_json=parent.target_json,
            patch_json=plan["rollback_patch"],
            risk_limits_json=parent.risk_limits_json,
            risk_values_json=parent.risk_values_json,
            risk_currency=parent.risk_currency,
            portfolio_risk_json=authorization["portfolio_risk_snapshot"],
            expected_state_hash=resulting_state_hash,
            status="queued",
            queued_by=queued_by,
            created_at=now,
        )
        session.add(row)
        session.flush()
        return row

    def _command_for(self, plan_id: str, command_kind: str):
        with Session(self.engine) as session:
            return session.scalar(
                select(LimitedExecutionCommandRow).where(
                    LimitedExecutionCommandRow.plan_id == plan_id,
                    LimitedExecutionCommandRow.command_kind == command_kind,
                )
            )

    @staticmethod
    def _rollback_for(session: Session, command_id: str) -> str | None:
        return session.scalar(
            select(LimitedExecutionCommandRow.id).where(
                LimitedExecutionCommandRow.parent_command_id == command_id,
                LimitedExecutionCommandRow.command_kind == "rollback",
            )
        )

    def _enabled(self) -> None:
        if not self.enabled:
            raise ValueError("Limited execution is disabled by the global execution gate")

    def _authorize_plan(self, plan: dict[str, Any], *, queued_by: str) -> None:
        if plan["adapter"]["action_id"] != plan["action_id"]:
            raise ValueError("Execution adapter action does not match the approved plan")
        authorization = self.action_authorization.authorize_action(
            action=plan["action_id"],
            subject_id=plan["id"],
            actor_id=queued_by,
            occurred_at=datetime.now(UTC),
            phase="permit",
            limits=plan["risk_limits"],
            values=plan["risk_values"],
            currency=plan["risk_currency"],
            policy_version=plan["action_policy_version"],
            readiness=self.execution_plans.action_readiness(plan),
            source_kind=plan["source_kind"],
            approval_actor_ids=[plan["approval_decided_by"]]
            if plan["approval_decided_by"]
            else [],
        )
        self.action_authorization.require_allowed(authorization)
        policy = authorization["action_policy"]
        if not policy["execution_permit_required"]:
            raise ValueError("Limited executor requires a permit-controlled action")

    def _authorize_command(
        self,
        session: Session,
        row: LimitedExecutionCommandRow,
        plan: dict[str, Any],
        worker_id: str,
    ) -> None:
        if self._utc(row.permit_expires_at) <= datetime.now(UTC):
            raise ValueError("Execution permit expired before use")
        if row.action_id != plan["action_id"] or row.adapter_id != plan["adapter_id"]:
            raise ValueError("Execution command no longer matches its approved action")
        if row.action_policy_version != self.action_policies.policy_version:
            raise ValueError("Execution command action policy is stale")
        if row.decision_hash != plan["decision_packet"]["decision_hash"]:
            raise ValueError("Execution command decision packet no longer matches")
        authorization = {
            "action_id": row.action_id,
            "action_policy_version": row.action_policy_version,
            "decision_hash": row.decision_hash,
            "risk_limits": row.risk_limits_json,
            "risk_values": row.risk_values_json,
            "risk_currency": row.risk_currency,
            "portfolio_risk_snapshot": row.portfolio_risk_json,
            "permit_expires_at": self._iso(row.permit_expires_at),
            "command_kind": row.command_kind,
        }
        if row.command_kind == "execute":
            authorization["plan_id"] = row.plan_id
        else:
            authorization["parent_command_id"] = row.parent_command_id
        if row.authorization_hash != self._hash(authorization):
            raise ValueError("Execution command authorization snapshot changed")
        if row.command_kind == "execute":
            current_risk = self._action_budget_snapshot(
                session,
                action_id=row.action_id,
                risk_limits=row.risk_limits_json,
                risk_values=row.risk_values_json,
                risk_currency=row.risk_currency,
                occurred_at=datetime.now(UTC),
                current_command=row,
            )
            if not current_risk["allowed"]:
                raise ValueError(
                    "Action daily risk budget changed before execution: "
                    + ", ".join(current_risk["blocking_reasons"])
                )
        authorization = self.action_authorization.authorize_action(
            action=row.action_id,
            subject_id=plan["id"],
            actor_id=row.queued_by,
            occurred_at=datetime.now(UTC),
            phase="execute",
            limits=row.risk_limits_json,
            values=row.risk_values_json,
            currency=row.risk_currency,
            policy_version=row.action_policy_version,
            readiness=self.execution_plans.action_readiness(
                plan,
                executor_identity_ref=worker_id,
            ),
            source_kind=plan["source_kind"],
            approval_actor_ids=[plan["approval_decided_by"]]
            if plan["approval_decided_by"]
            else [],
            executor_id=worker_id,
        )
        self.action_authorization.require_allowed(authorization)

    def _action_budget_snapshot(
        self,
        session: Session,
        *,
        action_id: str,
        risk_limits: dict[str, Any],
        risk_values: dict[str, Any],
        risk_currency: str | None,
        occurred_at: datetime,
        current_command: LimitedExecutionCommandRow | None = None,
    ) -> dict[str, Any]:
        day_start = occurred_at.replace(hour=0, minute=0, second=0, microsecond=0)
        rows = list(
            session.scalars(
                select(LimitedExecutionCommandRow)
                .where(
                    LimitedExecutionCommandRow.action_id == action_id,
                    LimitedExecutionCommandRow.command_kind == "execute",
                    LimitedExecutionCommandRow.created_at >= day_start,
                )
                .order_by(LimitedExecutionCommandRow.created_at, LimitedExecutionCommandRow.id)
            )
        )
        if current_command is not None and all(row.id != current_command.id for row in rows):
            rows.append(current_command)
        proposed = current_command is None
        command_count = len(rows) + int(proposed)
        max_daily_runs = int(Decimal(risk_limits["max_daily_runs"]))
        same_currency = [row for row in rows if row.risk_currency == risk_currency]
        totals = {key: Decimal("0") for key in risk_values}
        for row in same_currency:
            for key in totals:
                totals[key] += Decimal(str(row.risk_values_json[key]))
        if proposed:
            for key, value in risk_values.items():
                totals[key] += Decimal(str(value))
        aggregate_limits = {
            key: Decimal(str(risk_limits[f"max_{key}"])) * max_daily_runs
            for key in risk_values
        }
        blockers = []
        if command_count > max_daily_runs:
            blockers.append("ACTION_DAILY_RUN_LIMIT_EXHAUSTED")
        blockers.extend(
            f"ACTION_DAILY_RISK_LIMIT_EXCEEDED:{key}"
            for key in sorted(totals)
            if totals[key] > aggregate_limits[key]
        )
        snapshot = {
            "schema_version": "action-budget-snapshot-v1",
            "mode": "queue_reservation" if proposed else "execution_revalidation",
            "occurred_at": self._iso(occurred_at),
            "utc_day": day_start.date().isoformat(),
            "action_id": action_id,
            "currency": risk_currency,
            "prior_command_ids": [row.id for row in same_currency],
            "command_count": command_count,
            "max_daily_runs": max_daily_runs,
            "risk_totals": {key: self._decimal_text(value) for key, value in totals.items()},
            "derived_daily_limits": {
                key: self._decimal_text(value) for key, value in aggregate_limits.items()
            },
            "coverage": "action_utc_day_currency",
            "unmodeled_axes": ["sku", "category", "store", "legal_entity", "cash_floor"],
            "allowed": not blockers,
            "blocking_reasons": blockers,
        }
        snapshot["snapshot_hash"] = self._hash(snapshot)
        return snapshot

    @staticmethod
    def _lock_action_day(session: Session, action_id: str, occurred_at: datetime) -> None:
        if session.bind is None or session.bind.dialect.name != "postgresql":
            return
        day = occurred_at.date().isoformat()
        lock_key = int.from_bytes(
            hashlib.sha256(f"{action_id}:{day}".encode()).digest()[:8],
            byteorder="big",
            signed=True,
        )
        session.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key})

    @staticmethod
    def _decimal_text(value: Decimal) -> str:
        return format(value.normalize(), "f") if value else "0"

    def _verify_execution_receipt_evidence(
        self,
        row: LimitedExecutionCommandRow,
        *,
        evidence_ids: list[str],
        outcome: ReceiptOutcome,
        remote_operation_id: str | None,
        resulting_state_hash: str | None,
        error_code: str | None,
    ) -> None:
        if row.adapter_id != "ozon.product.import.v3":
            return
        artifacts: dict[str, list[dict[str, Any]]] = {}
        for evidence_id in evidence_ids:
            record = self.evidence.get(evidence_id)
            if record.source != OZON_EXECUTION_EVIDENCE_SOURCE:
                continue
            record = self._verify_execution_artifact_record(
                evidence_id,
                command_id=row.id,
            )
            artifact_kind = str(record.metadata["artifact_kind"])
            artifacts.setdefault(artifact_kind, []).append(record.metadata)
        plan = self.execution_plans.get(row.plan_id)
        if plan["source_kind"] != "approved_listing_draft" and not artifacts:
            return
        if len(artifacts.get("before_read", [])) != 1:
            raise ValueError("Ozon execution receipt requires exactly one before-read Evidence")
        if len(artifacts.get("product_import_response", [])) > 1:
            raise ValueError("Ozon execution receipt has duplicate import response Evidence")
        if len(artifacts.get("after_read", [])) > 1:
            raise ValueError("Ozon execution receipt has duplicate after-read Evidence")
        statuses = sorted(
            artifacts.get("import_status_response", []),
            key=lambda item: item["sequence_number"],
        )
        if [item["sequence_number"] for item in statuses] != list(range(len(statuses))):
            raise ValueError("Ozon import-status Evidence sequence is not contiguous")
        import_artifacts = artifacts.get("product_import_response", [])
        evidence_task_id = import_artifacts[0].get("remote_operation_id") if import_artifacts else None
        if import_artifacts and evidence_task_id != remote_operation_id:
            raise ValueError("Receipt remote operation id does not match Ozon import Evidence")
        if (
            not import_artifacts
            and remote_operation_id is not None
            and error_code != "CONTROL_PLANE_CHECKPOINT_FAILED"
        ):
            raise ValueError("Receipt remote operation id requires Ozon import Evidence")
        if (
            import_artifacts
            and import_artifacts[0].get("import_outcome") == "request_failed"
            and remote_operation_id is not None
        ):
            raise ValueError("Rejected Ozon import Evidence cannot prove a remote task id")
        if statuses and any(item.get("remote_operation_id") != evidence_task_id for item in statuses):
            raise ValueError("Ozon import-status Evidence refers to a different task")
        after_artifacts = artifacts.get("after_read", [])
        if after_artifacts and after_artifacts[0].get("state_hash") != resulting_state_hash:
            raise ValueError("Receipt resulting state hash does not match after-read Evidence")
        if outcome == "succeeded":
            if len(import_artifacts) != 1 or not statuses:
                raise ValueError("Successful Ozon receipt requires import and status Evidence")
            if statuses[-1].get("import_outcome") != "succeeded":
                raise ValueError("Successful Ozon receipt requires terminal imported status Evidence")
            if len(after_artifacts) != 1:
                raise ValueError("Successful Ozon receipt requires exactly one after-read Evidence")
        if error_code == "OZON_READBACK_DIVERGENT" and len(after_artifacts) != 1:
            raise ValueError("Divergent Ozon receipt requires after-read Evidence")

    def _verify_execution_artifact_record(
        self,
        evidence_id: str,
        *,
        command_id: str,
        artifact_kind: str | None = None,
        sequence_number: int | None = None,
    ):
        content, record = self.evidence.content(evidence_id)
        verification = self.evidence.verify(evidence_id)
        metadata = record.metadata
        kind = str(metadata.get("artifact_kind", ""))
        sequence = metadata.get("sequence_number")
        expected_ref = self._artifact_source_ref(command_id, kind, sequence)
        expected_relationship = EXECUTION_ARTIFACT_RELATIONSHIPS.get(kind)
        linked_ids = (
            self.evidence.target_evidence_ids(
                target_type="limited_execution_command",
                target_id=command_id,
                relationship=expected_relationship,
            )
            if expected_relationship
            else []
        )
        if (
            not verification.valid
            or record.source != OZON_EXECUTION_EVIDENCE_SOURCE
            or record.source_ref != expected_ref
            or record.grade != EvidenceGrade.A
            or record.content_type != "application/json"
            or record.created_by == ""
            or metadata.get("raw_response_stored") is not True
            or metadata.get("response_sha256") != record.sha256
            or metadata.get("response_byte_size") != len(content)
            or metadata.get("command_id") != command_id
            or metadata.get("adapter_id") != "ozon.product.import.v3"
            or expected_relationship is None
            or evidence_id not in linked_ids
            or (artifact_kind is not None and kind != artifact_kind)
            or (artifact_kind is not None and sequence != sequence_number)
        ):
            raise ValueError("Ozon execution Evidence contract is invalid")
        return record

    @classmethod
    def _parse_execution_artifact(
        cls,
        content: bytes,
        *,
        artifact_kind: str,
        offer_id: str,
    ) -> dict[str, Any]:
        try:
            bundle = json.loads(content)
            if bundle.get("schema_version") != OZON_RESPONSE_BUNDLE_SCHEMA_VERSION:
                raise ValueError
            responses = bundle["responses"]
            expected_contract = (
                OZON_PRODUCT_READ_CONTRACT_VERSION
                if artifact_kind in {"before_read", "after_read"}
                else OZON_EXECUTION_CONTRACT_VERSION
            )
            if bundle.get("contract_version") != expected_contract:
                raise ValueError
            allowed_bundle_keys = {"schema_version", "contract_version", "responses"}
            if artifact_kind == "import_status_response":
                allowed_bundle_keys.add("request_context")
            if set(bundle) != allowed_bundle_keys:
                raise ValueError
            expected_count = 2 if artifact_kind in {"before_read", "after_read"} else 1
            if not isinstance(responses, list) or len(responses) != expected_count:
                raise ValueError
            decoded: dict[str, Any] = {}
            status_codes: dict[str, int] = {}
            for item in responses:
                if not isinstance(item, dict) or set(item) != {
                    "path",
                    "status_code",
                    "headers",
                    "body_sha256",
                    "body_base64",
                }:
                    raise ValueError
                path = item["path"]
                if not isinstance(path, str) or path in decoded:
                    raise ValueError
                status_code = item["status_code"]
                if (
                    isinstance(status_code, bool)
                    or not isinstance(status_code, int)
                    or not 100 <= status_code <= 599
                    or not isinstance(item["headers"], dict)
                ):
                    raise ValueError
                body = base64.b64decode(item["body_base64"], validate=True)
                if len(body) > MAX_OZON_RESPONSE_BODY_BYTES:
                    raise ValueError
                body_sha256 = item["body_sha256"]
                if not isinstance(body_sha256, str) or not hmac.compare_digest(
                    body_sha256,
                    hashlib.sha256(body).hexdigest(),
                ):
                    raise ValueError
                decoded[path] = json.loads(body)
                status_codes[path] = status_code
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("Ozon execution Evidence has an unsupported response contract") from exc

        if artifact_kind in {"before_read", "after_read"}:
            info = decoded.get("/v3/product/info/list")
            attribute_paths = {
                "/v4/product/info/attributes",
                "/v3/products/info/attributes",
            }.intersection(decoded)
            if len(attribute_paths) != 1 or len(decoded) != 2:
                raise ValueError("Ozon product-state Evidence has unexpected endpoints")
            if any(not 200 <= code < 300 for code in status_codes.values()):
                raise ValueError("Ozon product-state Evidence contains an unsuccessful response")
            attributes = decoded[attribute_paths.pop()]
            info_items = info.get("items") if isinstance(info, dict) else None
            result = attributes.get("result") if isinstance(attributes, dict) else None
            attribute_items = result.get("items") if isinstance(result, dict) else result
            for items in (info_items, attribute_items):
                if (
                    not isinstance(items, list)
                    or len(items) != 1
                    or not isinstance(items[0], dict)
                    or str(items[0].get("offer_id", "")).strip() != offer_id
                ):
                    raise ValueError("Ozon product-state Evidence does not prove one target offer")
            state = {
                "contract_version": OZON_PRODUCT_READ_CONTRACT_VERSION,
                "offer_id": offer_id,
                "info": info,
                "attributes": attributes,
            }
            return {"state_hash": cls._hash(state)}

        expected_path = (
            "/v3/product/import"
            if artifact_kind == "product_import_response"
            else "/v1/product/import/info"
        )
        if set(decoded) != {expected_path}:
            raise ValueError("Ozon execution Evidence has an unexpected endpoint")
        response = decoded[expected_path]
        result = response.get("result") if isinstance(response, dict) else None
        if artifact_kind == "product_import_response":
            if not 200 <= status_codes[expected_path] < 300:
                return {
                    "remote_operation_id": None,
                    "import_outcome": "request_failed",
                }
            task_id = result.get("task_id") if isinstance(result, dict) else None
            if task_id is None:
                raise ValueError("Ozon import Evidence does not contain a task id")
            return {
                "remote_operation_id": str(task_id),
                "import_outcome": "accepted",
            }
        request_context = bundle.get("request_context")
        task_id = (
            request_context.get("task_id")
            if isinstance(request_context, dict)
            else None
        )
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("Ozon import-status Evidence does not identify its requested task")
        if set(request_context) != {"task_id"}:
            raise ValueError("Ozon import-status Evidence has an invalid request context")
        if not 200 <= status_codes[expected_path] < 300:
            return {
                "remote_operation_id": task_id,
                "import_outcome": "status_request_failed",
            }
        items = result.get("items") if isinstance(result, dict) else None
        if not isinstance(items, list):
            raise ValueError("Ozon import-status Evidence does not contain result.items")
        statuses = [
            str(item.get("status", "")).casefold()
            for item in items
            if isinstance(item, dict)
        ]
        if statuses and all(status == "imported" for status in statuses):
            import_outcome = "succeeded"
        elif any(status in {"failed", "error", "declined"} for status in statuses):
            import_outcome = "failed"
        else:
            import_outcome = "pending"
        return {
            "remote_operation_id": str(task_id),
            "import_outcome": import_outcome,
        }

    @staticmethod
    def _artifact_source_ref(
        command_id: str,
        artifact_kind: str,
        sequence_number: int | None,
    ) -> str:
        if artifact_kind not in EXECUTION_ARTIFACT_RELATIONSHIPS:
            raise ValueError("Unsupported execution artifact kind")
        suffix = (
            f"import-status/{sequence_number}"
            if artifact_kind == "import_status_response"
            else artifact_kind.replace("_", "-")
        )
        return f"{command_id}/{suffix}"

    @staticmethod
    def _artifact_result(
        evidence_id: str,
        artifact_kind: str,
        sequence_number: int | None,
        parsed: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "evidence_id": evidence_id,
            "artifact_kind": artifact_kind,
            "sequence_number": sequence_number,
            **parsed,
            "immutable": True,
        }

    def _evidence(self, values: list[str]) -> list[str]:
        normalized = sorted({item.strip() for item in values if item.strip()})
        if not normalized:
            raise ValueError("Evidence is required")
        self.evidence.require_valid(normalized)
        return normalized

    def _link(self, evidence_ids: list[str], target_type: str, target_id: str, actor: str) -> None:
        for evidence_id in evidence_ids:
            self.evidence.link(
                evidence_id=evidence_id,
                target_type=target_type,
                target_id=target_id,
                relationship="supports",
                created_by=actor,
            )

    @staticmethod
    def _required(value: str, name: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError(f"{name} is required")
        return cleaned

    @staticmethod
    def _optional(value: str | None) -> str | None:
        cleaned = value.strip() if value else ""
        return cleaned or None

    @staticmethod
    def _state_hash(value: str) -> str:
        normalized = value.strip().lower()
        if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
            raise ValueError("State hash must be a SHA-256 hexadecimal digest")
        return normalized

    @staticmethod
    def _hash(value: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()

    @staticmethod
    def _utc(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    @classmethod
    def _iso(cls, value: datetime | None) -> str | None:
        return cls._utc(value).isoformat() if value else None

    @classmethod
    def _command(
        cls,
        row: LimitedExecutionCommandRow,
        receipt: LimitedExecutionReceiptRow | None,
    ) -> dict[str, Any]:
        return {
            "id": row.id,
            "plan_id": row.plan_id,
            "parent_command_id": row.parent_command_id,
            "command_kind": row.command_kind,
            "idempotency_token": row.idempotency_token,
            "adapter_id": row.adapter_id,
            "action_id": row.action_id,
            "action_policy_version": row.action_policy_version,
            "decision_hash": row.decision_hash,
            "authorization_hash": row.authorization_hash,
            "permit_expires_at": cls._iso(row.permit_expires_at),
            "operation": row.operation,
            "target": row.target_json,
            "patch": row.patch_json,
            "risk_limits": row.risk_limits_json,
            "risk_values": row.risk_values_json,
            "risk_currency": row.risk_currency,
            "portfolio_risk": row.portfolio_risk_json,
            "expected_state_hash": row.expected_state_hash,
            "status": row.status,
            "queued_by": row.queued_by,
            "claimed_by": row.claimed_by,
            "claimed_at": cls._iso(row.claimed_at),
            "lease_expires_at": cls._iso(row.lease_expires_at),
            "created_at": cls._iso(row.created_at),
            "receipt": cls._receipt(receipt, None) if receipt else None,
            "write_attempt_consumed": row.status
            in {"write_started", "succeeded", "failed", "uncertain"},
            "platform_write_performed": bool(receipt and receipt.mutation_applied),
            "immutable_payload": True,
        }

    @classmethod
    def _receipt(
        cls,
        row: LimitedExecutionReceiptRow,
        rollback_command_id: str | None,
    ) -> dict[str, Any]:
        return {
            "id": row.id,
            "command_id": row.command_id,
            "request_id": row.request_id,
            "trace_id": row.trace_id,
            "outcome": row.outcome,
            "remote_operation_id": row.remote_operation_id,
            "resulting_state_hash": row.resulting_state_hash,
            "mutation_applied": row.mutation_applied,
            "error_code": row.error_code,
            "error_detail": row.error_detail,
            "evidence_ids": row.evidence_json,
            "recorded_by": row.recorded_by,
            "recorded_at": cls._iso(row.recorded_at),
            "rollback_command_id": rollback_command_id,
            "immutable": True,
        }
