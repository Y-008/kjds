from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, UniqueConstraint, select, text
from sqlalchemy.orm import Mapped, Session, mapped_column

from .action_policies import ActionPolicyRegistry
from .correlation import correlation_id
from .domain import new_id
from .sql_repository import Base

CommandKind = Literal["execute", "rollback"]
ReceiptOutcome = Literal["succeeded", "failed", "uncertain"]


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
    ) -> None:
        self.engine = engine
        self.execution_plans = execution_plans
        self.evidence = evidence
        self.kill_switch = kill_switch
        self.action_policies = action_policies or execution_plans.action_policies
        self.action_authorization = execution_plans.action_authorization
        self.enabled = enabled

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
        request_hash = self._hash(canonical)
        rollback_id = None
        lease_expired = False
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
                if existing.request_hash != request_hash:
                    raise ValueError("Execution receipt is immutable")
                return self._receipt(existing, self._rollback_for(session, command_id))
            if row.status != "claimed" or row.claimed_by != recorded_by:
                raise ValueError("Only the worker holding the command lease may record its receipt")
            now = datetime.now(UTC)
            lease_expires = row.lease_expires_at
            if lease_expires and self._utc(lease_expires) < now:
                row.status = "uncertain"
                lease_expired = True
            else:
                receipt = LimitedExecutionReceiptRow(
                    id=new_id("lxr"),
                    request_hash=request_hash,
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
                if outcome in {"failed", "uncertain"} and mutation_applied:
                    rollback = self._build_rollback(session, row, resulting_state_hash, recorded_by)
                    rollback_id = rollback.id
                result = self._receipt(receipt, rollback_id)
        if lease_expired:
            raise ValueError("Execution lease expired; command state is now uncertain")
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
            readiness=self.execution_plans.action_readiness(
                plan["action_id"], plan["target"]
            ),
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
                plan["action_id"], plan["target"]
            ),
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
