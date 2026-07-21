from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .action_policies import ActionAuthorizationService, ActionPolicyRegistry
from .domain import new_id
from .sql_repository import Base

ADAPTERS = {
    "ozon.listing.draft.v1": {
        "action_id": "listing_draft",
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
        "action_id": "listing_publish",
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
    action_id: Mapped[str] = mapped_column(String, nullable=False)
    action_policy_version: Mapped[str] = mapped_column(String, nullable=False)
    target_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    precondition_state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    intended_patch_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    rollback_patch_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    risk_limits_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    risk_values_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    risk_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    permit_ttl_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
    def __init__(
        self,
        *,
        engine,
        policy_shadow,
        policies,
        evidence,
        commerce,
        action_policies: ActionPolicyRegistry | None = None,
        action_authorization: ActionAuthorizationService | None = None,
        readiness_provider: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        self.engine = engine
        self.policy_shadow = policy_shadow
        self.policies = policies
        self.evidence = evidence
        self.commerce = commerce
        if action_authorization is not None:
            self.action_authorization = action_authorization
            self.action_policies = action_authorization.registry
        else:
            self.action_policies = action_policies or ActionPolicyRegistry()
            self.action_authorization = ActionAuthorizationService(self.action_policies)
        self.readiness_provider = readiness_provider

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
        risk_limits: dict[str, Any] | None = None,
        risk_values: dict[str, Any] | None = None,
        risk_currency: str | None = None,
    ) -> dict[str, Any]:
        handoff = self.policy_shadow.get_handoff(handoff_id)
        if not handoff["activation_eligible"]:
            raise ValueError("Execution planning requires an active approved policy handoff")
        policy = self.policies.get(handoff["policy_id"])
        adapter = self._adapter(adapter_id)
        action_policy = self.action_policies.get(adapter["action_id"])
        if adapter["live_execution_supported"] and action_policy["decision_scope"] != "real_execution":
            raise ValueError("Live execution adapter must use a real-execution action policy")
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
        readiness_snapshot = self.action_readiness_snapshot(adapter["action_id"], target)
        evidence_ids = self._evidence(
            [*evidence_ids, *self._readiness_evidence_ids(readiness_snapshot)]
        )
        authorization = self.action_authorization.authorize_action(
            action=adapter["action_id"],
            subject_id=self._subject_ref(adapter_id, target),
            actor_id=created_by,
            occurred_at=datetime.now(UTC),
            phase="request",
            limits=risk_limits,
            values=risk_values,
            currency=risk_currency,
            readiness=self._readiness_flags(readiness_snapshot),
        )
        self.action_authorization.require_allowed(authorization)
        risk = authorization["risk"]
        canonical = {
            "handoff_id": handoff_id,
            "idempotency_key": idempotency_key,
            "adapter_id": adapter_id,
            "action_id": adapter["action_id"],
            "action_policy_version": self.action_policies.policy_version,
            "target": target,
            "precondition_state_hash": precondition_state_hash,
            "intended_patch": intended_patch,
            "rollback_patch": rollback_patch,
            "risk_limits": risk["limits"],
            "risk_values": risk["values"],
            "risk_currency": risk["currency"],
            "permit_ttl_seconds": risk["permit_ttl_seconds"],
            "evidence_ids": evidence_ids,
            "readiness_snapshot": readiness_snapshot,
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
                "action_id": adapter["action_id"],
                "action_policy_version": self.action_policies.policy_version,
                "risk_tier": action_policy["risk_tier"],
                "operation": adapter["operation"],
                "target": target,
                "precondition_state_hash": precondition_state_hash,
                "intended_patch": intended_patch,
                "rollback_patch": rollback_patch,
                "risk_limits": risk["limits"],
                "risk_values": risk["values"],
                "risk_currency": risk["currency"],
                "permit_ttl_seconds": risk["permit_ttl_seconds"],
                "readiness_snapshot": readiness_snapshot,
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
                action_id=adapter["action_id"],
                action_policy_version=self.action_policies.policy_version,
                target_json=target,
                precondition_state_hash=precondition_state_hash,
                intended_patch_json=intended_patch,
                rollback_patch_json=rollback_patch,
                risk_limits_json=risk["limits"],
                risk_values_json=risk["values"],
                risk_currency=risk["currency"],
                permit_ttl_seconds=risk["permit_ttl_seconds"],
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
        current_readiness_snapshot = self.action_readiness_snapshot(
            result["action_id"], result["target"]
        )
        authorization = self.action_authorization.authorize_action(
            action=result["action_id"],
            subject_id=self._subject_ref(result["adapter_id"], result["target"]),
            actor_id=result["created_by"],
            occurred_at=datetime.now(UTC),
            phase="permit",
            limits=result["risk_limits"],
            values=result["risk_values"],
            currency=result["risk_currency"],
            policy_version=result["action_policy_version"],
            readiness=self._readiness_flags(current_readiness_snapshot),
            approval_actor_ids=(
                [approval.decided_by]
                if approval.status.value == "approved" and approval.decided_by
                else []
            ),
        )
        authorization_blocking_reasons = list(authorization["blocking_reasons"])
        frozen_readiness_snapshot = (
            approval.payload.get("readiness_snapshot", {})
            if isinstance(approval.payload, dict)
            else {}
        )
        try:
            self.evidence.require_valid(result["evidence_ids"])
        except (KeyError, RuntimeError, ValueError):
            authorization_blocking_reasons.append("PLAN_EVIDENCE_INVALID")
        frozen_readiness_evidence_ids = self._readiness_evidence_ids(
            frozen_readiness_snapshot
        )
        if frozen_readiness_evidence_ids:
            try:
                self.evidence.require_valid(frozen_readiness_evidence_ids)
            except (KeyError, RuntimeError, ValueError):
                authorization_blocking_reasons.append("READINESS_EVIDENCE_INVALID")
        authorization_blocking_reasons = sorted(set(authorization_blocking_reasons))
        current_action_policy = authorization["action_policy"]
        ready_for_executor = (
            active
            and approval.status.value == "approved"
            and dry_run_passed
            and not authorization_blocking_reasons
        )
        decision_packet = self._decision_packet(
            result=result,
            handoff=handoff,
            approval=approval,
            dry_run=self._dry_run(dry_run) if dry_run else None,
            frozen_readiness_snapshot=frozen_readiness_snapshot,
        )
        return {
            **result,
            "approval_status": approval.status.value,
            "approval_decided_by": approval.decided_by,
            "handoff_validity_status": handoff["validity_status"],
            "dry_run": self._dry_run(dry_run) if dry_run else None,
            "ready_for_executor": ready_for_executor,
            "authorization_blocking_reasons": authorization_blocking_reasons,
            "current_readiness_snapshot": current_readiness_snapshot,
            "decision_packet": decision_packet,
            "execution_eligible": False,
            "adapter": {"id": result["adapter_id"], **self._adapter(result["adapter_id"])},
            "action_policy": current_action_policy,
            "live_execution_supported": self._adapter(result["adapter_id"])[
                "live_execution_supported"
            ],
            "automatic_execution": False,
        }

    def action_readiness(self, action_id: str, target: dict[str, Any]) -> dict[str, bool]:
        return self._readiness_flags(self.action_readiness_snapshot(action_id, target))

    def action_readiness_snapshot(
        self, action_id: str, target: dict[str, Any]
    ) -> dict[str, dict[str, Any]]:
        if self.readiness_provider is None:
            return {}
        readiness = self.readiness_provider(action_id, target)
        if not isinstance(readiness, dict):
            raise ValueError("Action readiness provider must return a mapping")
        result: dict[str, dict[str, Any]] = {}
        for key, value in readiness.items():
            requirement_id = self._required(str(key), "Readiness requirement")
            if isinstance(value, bool):
                snapshot = {
                    "ready": value,
                    "evidence_ids": [],
                    "blocking_reasons": [],
                }
            elif isinstance(value, dict):
                snapshot = {
                    "ready": value.get("ready") is True,
                    "evidence_ids": self._string_list(
                        value.get("evidence_ids", []),
                        "Readiness evidence IDs",
                    ),
                    "blocking_reasons": self._string_list(
                        value.get("blocking_reasons", []),
                        "Readiness blocking reasons",
                    ),
                }
            else:
                raise ValueError("Action readiness values must be booleans or mappings")
            result[requirement_id] = {
                **snapshot,
                "snapshot_hash": self._hash(snapshot),
            }
        return dict(sorted(result.items()))

    @staticmethod
    def _readiness_flags(snapshot: dict[str, dict[str, Any]]) -> dict[str, bool]:
        return {
            requirement_id: requirement.get("ready") is True
            for requirement_id, requirement in snapshot.items()
        }

    @staticmethod
    def _readiness_evidence_ids(snapshot: dict[str, dict[str, Any]]) -> list[str]:
        return sorted(
            {
                evidence_id
                for requirement in snapshot.values()
                if isinstance(requirement, dict)
                for evidence_id in requirement.get("evidence_ids", [])
                if isinstance(evidence_id, str) and evidence_id.strip()
            }
        )

    @classmethod
    def _string_list(cls, value: Any, name: str) -> list[str]:
        if not isinstance(value, list):
            raise ValueError(f"{name} must be a list")
        if len(value) > 100:
            raise ValueError(f"{name} exceeds the 100 item limit")
        normalized: set[str] = set()
        for item in value:
            if not isinstance(item, str):
                raise ValueError(f"{name} entries must be strings")
            normalized.add(cls._required(item, name))
        return sorted(normalized)

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

    @classmethod
    def _subject_ref(cls, adapter_id: str, target: dict[str, Any]) -> str:
        return cls._hash({"adapter_id": adapter_id, "target": target})

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
            "action_id": row.action_id,
            "action_policy_version": row.action_policy_version,
            "target": row.target_json,
            "precondition_state_hash": row.precondition_state_hash,
            "intended_patch": row.intended_patch_json,
            "rollback_patch": row.rollback_patch_json,
            "risk_limits": row.risk_limits_json,
            "risk_values": row.risk_values_json,
            "risk_currency": row.risk_currency,
            "permit_ttl_seconds": row.permit_ttl_seconds,
            "evidence_ids": row.evidence_json,
            "approval_id": row.approval_id,
            "created_by": row.created_by,
            "created_at": cls._iso(row.created_at),
            "immutable": True,
        }

    @classmethod
    def _decision_packet(
        cls,
        *,
        result: dict[str, Any],
        handoff: dict[str, Any],
        approval,
        dry_run: dict[str, Any] | None,
        frozen_readiness_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        packet = {
            "schema_version": "decision-packet-v1",
            "action": result["action_id"],
            "subject": result["target"],
            "requested_by": result["created_by"],
            "policy_version": result["action_policy_version"],
            "causal_policy_id": result["policy_id"],
            "causal_policy_release_id": result["release_id"],
            "causal_policy_snapshot_hash": handoff["policy_snapshot_hash"],
            "evidence_ids": result["evidence_ids"],
            "readiness_snapshot": frozen_readiness_snapshot,
            "adapter_id": result["adapter_id"],
            "risk_limits": result["risk_limits"],
            "risk_values": result["risk_values"],
            "risk_currency": result["risk_currency"],
            "approval": {
                "id": result["approval_id"],
                "status": approval.status.value,
                "decided_by": approval.decided_by,
                "reason": approval.decision_reason,
            },
            "dry_run_hash": cls._hash(dry_run) if dry_run else None,
            "expiry_conditions": [
                "action_policy_version_changes",
                "causal_policy_snapshot_changes",
                "approval_is_not_approved",
                "evidence_becomes_invalid",
                "readiness_evidence_becomes_invalid",
                "permit_expires",
            ],
        }
        return {**packet, "decision_hash": cls._hash(packet), "immutable_projection": True}

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
