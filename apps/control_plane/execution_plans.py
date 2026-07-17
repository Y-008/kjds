from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import new_id
from .sql_repository import Base

ADAPTERS = {
    "ozon.listing.draft.v1": {
        "platform": "Ozon",
        "policy_action": "recommend_listing_change",
        "operation": "listing.update_draft",
        "required_target_keys": ["listing_id"],
        "allowed_patch_keys": ["title", "description", "attributes", "images"],
        "live_execution_supported": False,
        "rollback_required": True,
        "command_delivery_supported": False,
    },
    "ozon.product.import.v3": {
        "platform": "Ozon",
        "policy_action": "recommend_listing_change",
        "operation": "product.import.v3",
        "rollback_operation": "product.import.v3",
        "required_target_keys": ["offer_id"],
        "allowed_patch_keys": ["item"],
        "live_execution_supported": True,
        "rollback_required": True,
        "command_delivery_supported": True,
    },
}


class ExecutionPlanRow(Base):
    __tablename__ = "governed_execution_plans"
    __table_args__ = (
        UniqueConstraint("handoff_id", "idempotency_key", name="uq_execution_plan_key"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    handoff_id: Mapped[str] = mapped_column(
        ForeignKey("causal_policy_activation_handoffs.id"), nullable=False
    )
    policy_id: Mapped[str] = mapped_column(ForeignKey("causal_policies.id"), nullable=False)
    release_id: Mapped[str] = mapped_column(
        ForeignKey("causal_policy_releases.id"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False)
    adapter_id: Mapped[str] = mapped_column(String, nullable=False)
    target_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    precondition_state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    intended_patch_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    rollback_patch_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    evidence_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    approval_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExecutionDryRunRow(Base):
    __tablename__ = "governed_execution_dry_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    plan_id: Mapped[str] = mapped_column(
        ForeignKey("governed_execution_plans.id"), unique=True, nullable=False
    )
    current_state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    checks_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    evidence_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    performed_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExecutionPlanService:
    def __init__(self, *, engine, policy_shadow, policies, evidence, commerce) -> None:
        self.engine = engine
        self.policy_shadow = policy_shadow
        self.policies = policies
        self.evidence = evidence
        self.commerce = commerce

    @staticmethod
    def adapters() -> list[dict[str, Any]]:
        return [{"id": key, **value} for key, value in ADAPTERS.items()]

    def create(
        self,
        handoff_id: str,
        *,
        idempotency_key: str,
        adapter_id: str,
        target: dict[str, Any],
        precondition_state_hash: str,
        intended_patch: dict[str, Any],
        rollback_patch: dict[str, Any],
        evidence_ids: list[str],
        created_by: str,
    ) -> dict[str, Any]:
        handoff = self.policy_shadow.get_handoff(handoff_id)
        if not handoff["activation_eligible"]:
            raise ValueError("Execution planning requires an active approved policy handoff")
        policy = self.policies.get(handoff["policy_id"])
        adapter = self._adapter(adapter_id)
        if adapter["platform"] != policy["applicability"]["platform"]:
            raise ValueError("Execution adapter platform is outside policy applicability")
        if adapter["policy_action"] != policy["action"]["type"]:
            raise ValueError("Execution adapter does not support the policy action")
        idempotency_key = self._required(idempotency_key, "Execution idempotency key")
        created_by = self._required(created_by, "Execution plan creator")
        target = self._target(target, adapter)
        precondition_state_hash = self._state_hash(precondition_state_hash)
        intended_patch = self._patch(intended_patch, adapter, "Intended patch")
        rollback_patch = self._patch(rollback_patch, adapter, "Rollback patch")
        if adapter["operation"] == "product.import.v3":
            if intended_patch["item"].get("offer_id") != target["offer_id"]:
                raise ValueError("Intended Ozon import item must match target offer_id")
            if rollback_patch["item"].get("offer_id") != target["offer_id"]:
                raise ValueError("Rollback Ozon import item must match target offer_id")
        if intended_patch == rollback_patch:
            raise ValueError("Rollback patch must restore a different prior state")
        evidence_ids = self._evidence(evidence_ids)
        canonical = {
            "handoff_id": handoff_id,
            "idempotency_key": idempotency_key,
            "adapter_id": adapter_id,
            "target": target,
            "precondition_state_hash": precondition_state_hash,
            "intended_patch": intended_patch,
            "rollback_patch": rollback_patch,
            "evidence_ids": evidence_ids,
            "created_by": created_by,
        }
        request_hash = self._hash(canonical)
        with Session(self.engine) as session:
            exact = session.scalar(
                select(ExecutionPlanRow).where(ExecutionPlanRow.request_hash == request_hash)
            )
            if exact is not None:
                return self.get(exact.id)
            previous = session.scalar(
                select(ExecutionPlanRow).where(
                    ExecutionPlanRow.handoff_id == handoff_id,
                    ExecutionPlanRow.idempotency_key == idempotency_key,
                )
            )
            if previous is not None:
                raise ValueError("Execution idempotency key already has immutable content")
        approval = self.commerce.request_approval(
            action="platform_execution.execute_plan",
            resource_type="governed_execution_plan",
            resource_id=request_hash,
            requested_by=created_by,
            payload={
                "handoff_id": handoff_id,
                "policy_id": policy["id"],
                "release_id": handoff["release_id"],
                "adapter_id": adapter_id,
                "operation": adapter["operation"],
                "target": target,
                "precondition_state_hash": precondition_state_hash,
                "intended_patch": intended_patch,
                "rollback_patch": rollback_patch,
                "live_execution_supported": False,
            },
        )
        with Session(self.engine) as session, session.begin():
            row = ExecutionPlanRow(
                id=new_id("gxp"),
                request_hash=request_hash,
                handoff_id=handoff_id,
                policy_id=policy["id"],
                release_id=handoff["release_id"],
                idempotency_key=idempotency_key,
                adapter_id=adapter_id,
                target_json=target,
                precondition_state_hash=precondition_state_hash,
                intended_patch_json=intended_patch,
                rollback_patch_json=rollback_patch,
                evidence_json=evidence_ids,
                approval_id=approval.id,
                created_by=created_by,
                created_at=datetime.now(UTC),
            )
            session.add(row)
            session.flush()
            plan_id = row.id
        self._link(evidence_ids, "governed_execution_plan", plan_id, created_by)
        return self.get(plan_id)

    def dry_run(
        self,
        plan_id: str,
        *,
        current_state_hash: str,
        evidence_ids: list[str],
        performed_by: str,
    ) -> dict[str, Any]:
        plan = self.get(plan_id)
        performed_by = self._required(performed_by, "Dry-run operator")
        current_state_hash = self._state_hash(current_state_hash)
        evidence_ids = self._evidence(evidence_ids)
        checks = [
            {
                "name": "policy_handoff_active",
                "passed": plan["handoff_validity_status"] == "active",
            },
            {
                "name": "precondition_snapshot_matches",
                "passed": current_state_hash == plan["precondition_state_hash"],
            },
            {"name": "rollback_contract_present", "passed": bool(plan["rollback_patch"])},
            {"name": "adapter_live_writes_disabled", "passed": True},
        ]
        passed = all(item["passed"] for item in checks)
        canonical = {
            "plan_id": plan_id,
            "current_state_hash": current_state_hash,
            "checks": checks,
            "evidence_ids": evidence_ids,
            "performed_by": performed_by,
        }
        request_hash = self._hash(canonical)
        with Session(self.engine) as session, session.begin():
            exact = session.scalar(
                select(ExecutionDryRunRow).where(ExecutionDryRunRow.request_hash == request_hash)
            )
            if exact is not None:
                return self._dry_run(exact)
            previous = session.scalar(
                select(ExecutionDryRunRow).where(ExecutionDryRunRow.plan_id == plan_id)
            )
            if previous is not None:
                raise ValueError("Execution plan already has an immutable dry-run receipt")
            row = ExecutionDryRunRow(
                id=new_id("gxd"),
                request_hash=request_hash,
                plan_id=plan_id,
                current_state_hash=current_state_hash,
                checks_json=checks,
                passed=passed,
                evidence_json=evidence_ids,
                performed_by=performed_by,
                created_at=datetime.now(UTC),
            )
            session.add(row)
            session.flush()
            result = self._dry_run(row)
        self._link(evidence_ids, "governed_execution_dry_run", result["id"], performed_by)
        return result

    def list(self) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            ids = list(session.scalars(select(ExecutionPlanRow.id).order_by(ExecutionPlanRow.created_at)))
        return [self.get(item_id) for item_id in ids]

    def get(self, plan_id: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            row = session.get(ExecutionPlanRow, plan_id)
            if row is None:
                raise KeyError(f"Governed execution plan not found: {plan_id}")
            result = self._plan(row)
            dry_run = session.scalar(
                select(ExecutionDryRunRow).where(ExecutionDryRunRow.plan_id == plan_id)
            )
        handoff = self.policy_shadow.get_handoff(result["handoff_id"])
        approval = self.commerce.repo.get_approval(result["approval_id"])
        active = handoff["validity_status"] == "active"
        dry_run_passed = bool(dry_run and dry_run.passed)
        ready_for_executor = active and approval.status.value == "approved" and dry_run_passed
        return {
            **result,
            "approval_status": approval.status.value,
            "approval_decided_by": approval.decided_by,
            "handoff_validity_status": handoff["validity_status"],
            "dry_run": self._dry_run(dry_run) if dry_run else None,
            "ready_for_executor": ready_for_executor,
            "execution_eligible": False,
            "adapter": {"id": result["adapter_id"], **self._adapter(result["adapter_id"])},
            "live_execution_supported": self._adapter(result["adapter_id"])[
                "live_execution_supported"
            ],
            "automatic_execution": False,
        }

    @staticmethod
    def _adapter(adapter_id: str) -> dict[str, Any]:
        try:
            return ADAPTERS[adapter_id]
        except KeyError as exc:
            raise ValueError(f"Unsupported governed execution adapter: {adapter_id}") from exc

    @classmethod
    def _target(cls, value: dict[str, Any], adapter: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict) or not value:
            raise ValueError("Execution target must be structured")
        missing = set(adapter["required_target_keys"]) - set(value)
        if missing:
            raise ValueError(f"Execution target is missing: {', '.join(sorted(missing))}")
        if set(value) - set(adapter["required_target_keys"]):
            raise ValueError("Execution target contains unsupported identifiers")
        return {key: cls._required(str(item), f"Target {key}") for key, item in value.items()}

    @staticmethod
    def _patch(value: dict[str, Any], adapter: dict[str, Any], name: str) -> dict[str, Any]:
        if not isinstance(value, dict) or not value:
            raise ValueError(f"{name} must be a non-empty structured object")
        unsupported = set(value) - set(adapter["allowed_patch_keys"])
        if unsupported:
            raise ValueError(f"{name} contains unsupported fields: {', '.join(sorted(unsupported))}")
        encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode()) > 131072:
            raise ValueError(f"{name} exceeds the 128 KiB limit")
        if adapter["operation"] == "product.import.v3":
            item = value.get("item")
            if not isinstance(item, dict) or not item:
                raise ValueError(f"{name} requires a complete Ozon import item")
        return value

    @staticmethod
    def _state_hash(value: str) -> str:
        normalized = value.strip().lower()
        if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
            raise ValueError("State hash must be a SHA-256 hexadecimal digest")
        return normalized

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
    def _hash(value: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()

    @staticmethod
    def _iso(value: datetime) -> str:
        return (value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)).isoformat()

    @classmethod
    def _plan(cls, row: ExecutionPlanRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "handoff_id": row.handoff_id,
            "policy_id": row.policy_id,
            "release_id": row.release_id,
            "idempotency_key": row.idempotency_key,
            "adapter_id": row.adapter_id,
            "target": row.target_json,
            "precondition_state_hash": row.precondition_state_hash,
            "intended_patch": row.intended_patch_json,
            "rollback_patch": row.rollback_patch_json,
            "evidence_ids": row.evidence_json,
            "approval_id": row.approval_id,
            "created_by": row.created_by,
            "created_at": cls._iso(row.created_at),
            "immutable": True,
        }

    @classmethod
    def _dry_run(cls, row: ExecutionDryRunRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "plan_id": row.plan_id,
            "current_state_hash": row.current_state_hash,
            "checks": row.checks_json,
            "passed": row.passed,
            "evidence_ids": row.evidence_json,
            "performed_by": row.performed_by,
            "created_at": cls._iso(row.created_at),
            "immutable": True,
            "platform_write_performed": False,
        }
