from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from .security import Principal


class ChannelAccountGovernanceError(ValueError):
    pass


class ChannelAccountGovernanceStateMachine:
    """Advance canonical channel-account governance through one command seam.

    This module intentionally exposes no provider execution command.  It makes the
    existing typed Evidence/SoD authority production reachable while keeping the
    runtime identity and every external write fail closed.
    """

    CONTRACT_ID = "kjds-channel-account-governance-transition-v1"
    CHANGE_APPROVAL_CONTRACT_ID = "kjds-channel-account-change-approval-v1"
    COMMANDS = frozenset(
        {
            "submit_evidence",
            "review_evidence",
            "request_change_approval",
            "decide_change_approval",
            "materialize_internal_plan",
        }
    )
    _FORBIDDEN_KEYS = frozenset(
        {
            "api_key",
            "apikey",
            "client_secret",
            "cookie",
            "credential",
            "password",
            "permit",
            "private_token",
            "secret",
            "secret_reference",
            "session_token",
            "token",
        }
    )

    def __init__(self, *, governance_evidence: Any, commerce: Any = None, execution_plans: Any = None) -> None:
        self._governance_evidence = governance_evidence
        self._commerce = commerce
        self._execution_plans = execution_plans

    def advance(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        command: dict[str, Any],
        as_of: datetime,
    ) -> dict[str, Any]:
        cutoff = self._aware(as_of)
        command_type = self._required(command.get("type"), "command.type", 80)
        if command_type not in self.COMMANDS:
            raise ChannelAccountGovernanceError("Unsupported channel-account governance command")
        payload = command.get("payload")
        if not isinstance(payload, dict):
            raise ChannelAccountGovernanceError("command.payload must be an object")
        self._reject_sensitive(payload)

        canonical_refs: dict[str, Any] = {}
        if command_type == "submit_evidence":
            result = self._submit(
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store_ref,
                payload=payload,
                cutoff=cutoff,
            )
            from_state, to_state = "draft", "evidence_pending"
            next_allowed = ["review_evidence"]
        elif command_type == "review_evidence":
            result = self._review(
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store_ref,
                payload=payload,
                cutoff=cutoff,
            )
            from_state = "evidence_pending"
            to_state = "evidence_reviewed" if result["status"] == "accepted" else "evidence_rejected"
            next_allowed = ["request_change_approval"] if result["status"] == "accepted" else []
        elif command_type == "request_change_approval":
            result = self._request_approval(
                principal=principal, entity_scope=entity_scope, store_ref=store_ref, payload=payload, cutoff=cutoff
            )
            from_state, to_state = "evidence_reviewed", "approval_pending"
            next_allowed = ["decide_change_approval"]
            canonical_refs["approval_id"] = result["approval_id"]
        elif command_type == "decide_change_approval":
            result = self._decide_approval(
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store_ref,
                payload=payload,
            )
            from_state = "approval_pending"
            to_state = "approved" if result["status"] == "approved" else "rejected"
            next_allowed = ["materialize_internal_plan"] if result["status"] == "approved" else []
            canonical_refs["approval_id"] = result["approval_id"]
        else:
            result = self._materialize_plan(
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store_ref,
                payload=payload,
            )
            from_state, to_state = "approved", "execution_gated"
            next_allowed = []
            canonical_refs.update(
                approval_id=result["source_approval_id"],
                execution_approval_id=result["approval_id"],
                execution_plan_id=result["id"],
            )

        scope = result["scope"]
        input_basis = {
            "contract_id": self.CONTRACT_ID,
            "command": command_type,
            "scope": scope,
            "actor_id": principal.actor_id,
            "payload": payload,
            "as_of": cutoff.isoformat(),
        }
        input_sha256 = self._hash(input_basis)
        receipt_basis = {
            "contract_id": self.CONTRACT_ID,
            "scope": scope,
            "command": command_type,
            "from_state": from_state,
            "to_state": to_state,
            "canonical_refs": {
                "submission_evidence_id": (
                    result["evidence_id"]
                    if command_type == "submit_evidence"
                    else payload.get("submission_evidence_id")
                ),
                "review_evidence_id": (
                    result["evidence_id"]
                    if command_type == "review_evidence"
                    else payload.get("reviewed_evidence_id")
                ),
                "approval_id": None,
                "execution_plan_id": None,
                "command_id": None,
                "receipt_id": None,
                "authorization_event_ref": None,
                **canonical_refs,
            },
            "input_sha256": input_sha256,
            "next_allowed_transitions": next_allowed,
            "external_write_allowed": False,
            "provider_contact_allowed": False,
            "runtime_identity_verified": False,
        }
        output_sha256 = self._hash(receipt_basis)
        return {
            **receipt_basis,
            "transition_id": f"cagt_{output_sha256[:32]}",
            "output_sha256": output_sha256,
            "idempotent": False,
            "blockers": [
                "managed_channel_credential_resolver_unbound",
                "provider_external_write_not_exposed",
            ],
            "control_envelope": {
                "read_only": False,
                "internal_governance_write": True,
                "business_fact_created": False,
                "approval_created": command_type in {"request_change_approval", "materialize_internal_plan"},
                "permit_created": False,
                "credential_created_or_read": False,
                "provider_contact_allowed": False,
                "external_write_allowed": False,
                "agent_may_invoke": False,
            },
        }

    def _submit(self, *, principal, entity_scope, store_ref, payload, cutoff):
        allowed = {
            "purpose",
            "effective_at",
            "effective_until",
            "idempotency_key",
            "semantic_metadata",
            "canonical_payload",
        }
        self._exact_keys(payload, allowed, "submit_evidence")
        return self._governance_evidence.submit(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            purpose=payload.get("purpose"),
            effective_at=payload.get("effective_at") or cutoff.isoformat(),
            effective_until=payload.get("effective_until"),
            idempotency_key=payload.get("idempotency_key"),
            semantic_metadata=payload.get("semantic_metadata"),
            canonical_payload=payload.get("canonical_payload"),
        )

    def _review(self, *, principal, entity_scope, store_ref, payload, cutoff):
        allowed = {"submission_evidence_id", "accepted", "rationale"}
        self._exact_keys(payload, allowed, "review_evidence")
        if not isinstance(payload.get("accepted"), bool):
            raise ChannelAccountGovernanceError("accepted must be boolean")
        return self._governance_evidence.review(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            submission_evidence_id=payload.get("submission_evidence_id"),
            accepted=payload["accepted"],
            rationale=payload.get("rationale"),
            as_of=cutoff,
        )

    def _request_approval(self, *, principal, entity_scope, store_ref, payload, cutoff):
        if self._commerce is None:
            raise ChannelAccountGovernanceError("Channel-account Approval authority is unbound")
        if not principal.has_any_role("operator", "admin"):
            raise PermissionError("Channel-account change request requires operator")
        allowed = {"reviewed_evidence_id"}
        self._exact_keys(payload, allowed, "request_change_approval")
        reviewed = self._governance_evidence.require_reviewed(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            evidence_id=payload.get("reviewed_evidence_id"),
            purpose="change_proposal",
            as_of=cutoff,
        )
        if principal.actor_id in {reviewed["submitted_by"], reviewed["reviewed_by"]}:
            raise ChannelAccountGovernanceError("Change requester must be independent of Evidence submitter and reviewer")
        proposal = reviewed.get("canonical_payload")
        if not isinstance(proposal, dict):
            raise ChannelAccountGovernanceError("Reviewed change proposal payload is unavailable")
        target = {
            "platform": self._required(proposal.get("platform"), "platform", 80),
            "account_ref": self._required(proposal.get("account_ref"), "account_ref", 240),
            "adapter_id": f"{self._required(proposal.get('platform'), 'platform', 80).lower()}-official",
        }
        capabilities = proposal.get("requested_capabilities")
        if not isinstance(capabilities, list) or not capabilities or not all(
            isinstance(item, str) and item.strip() for item in capabilities
        ):
            raise ChannelAccountGovernanceError("Reviewed change proposal capabilities are invalid")
        intended_patch = {
            "reviewed_evidence_id": reviewed["evidence_id"],
            "change_kind": self._required(proposal.get("change_kind"), "change_kind", 80),
            "requested_capabilities": sorted(set(capabilities)),
        }
        rollback_patch = {
            "reviewed_evidence_id": reviewed["evidence_id"],
            "change_kind": "restore_previous_authority",
            "requested_capabilities": [],
        }
        scope = reviewed["scope"]
        source_basis = {
            "contract_id": self.CHANGE_APPROVAL_CONTRACT_ID,
            "scope": scope,
            "reviewed_evidence_id": reviewed["evidence_id"],
            "reviewed_evidence_sha256": reviewed["evidence_sha256"],
            "reviewed_by": reviewed["reviewed_by"],
            "target": target,
            "intended_patch": intended_patch,
            "rollback_patch": rollback_patch,
        }
        source_snapshot_hash = self._hash(source_basis)
        resource_id = f"cach_{source_snapshot_hash[:32]}"
        approval = self._commerce.request_approval(
            action="channel_account.change",
            resource_type="channel_account_change",
            resource_id=resource_id,
            requested_by=principal.actor_id,
            payload={**source_basis, "source_snapshot_hash": source_snapshot_hash},
        )
        return {"approval_id": approval.id, "status": approval.status.value, "scope": scope}

    def _decide_approval(self, *, principal, entity_scope, store_ref, payload):
        if self._commerce is None:
            raise ChannelAccountGovernanceError("Channel-account Approval authority is unbound")
        self._exact_keys(payload, {"approval_id", "approved", "reason"}, "decide_change_approval")
        if not isinstance(payload.get("approved"), bool):
            raise ChannelAccountGovernanceError("approved must be boolean")
        if not principal.has_any_role("approver", "risk", "admin"):
            raise PermissionError("Channel-account change decision requires approver")
        approval = self._commerce.repo.get_approval(payload.get("approval_id"))
        self._require_change_approval(
            approval=approval,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
        )
        reviewed_by = approval.payload.get("reviewed_by") if isinstance(approval.payload, dict) else None
        if principal.actor_id == reviewed_by:
            raise ChannelAccountGovernanceError("Evidence reviewer cannot decide the same channel-account change")
        decided = self._commerce.decide_approval(
            approval.id,
            approved=payload.get("approved"),
            decided_by=principal.actor_id,
            reason=self._required(payload.get("reason"), "reason", 4000),
        )
        return {"approval_id": decided.id, "status": decided.status.value, "scope": decided.payload["scope"]}

    def _materialize_plan(self, *, principal, entity_scope, store_ref, payload):
        if self._execution_plans is None:
            raise ChannelAccountGovernanceError("Channel-account execution-plan authority is unbound")
        if not principal.has_any_role("operator", "admin"):
            raise PermissionError("Channel-account plan materialization requires operator")
        self._exact_keys(payload, {"approval_id", "idempotency_key"}, "materialize_internal_plan")
        approval_id = self._required(payload.get("approval_id"), "approval_id", 240)
        approval = self._commerce.repo.get_approval(approval_id) if self._commerce is not None else None
        self._require_change_approval(
            approval=approval,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
        )
        plan = self._execution_plans.create_from_approved_channel_account(
            approval_id,
            idempotency_key=self._required(payload.get("idempotency_key"), "idempotency_key", 160),
            created_by=principal.actor_id,
        )
        if approval is None or not isinstance(approval.payload, dict):
            raise ChannelAccountGovernanceError("Channel-account plan scope authority is unavailable")
        plan["scope"] = approval.payload["scope"]
        return plan

    @classmethod
    def _require_change_approval(cls, *, approval, principal, entity_scope, store_ref) -> None:
        if approval is None or not isinstance(approval.payload, dict):
            raise ChannelAccountGovernanceError("Channel-account Approval scope authority is unavailable")
        actual = approval.payload.get("scope")
        expected = {
            "tenant_ref": cls._required(principal.tenant_ref, "tenant_ref", 240),
            "entity_ref": cls._required(entity_scope.get("entity_ref"), "entity_ref", 240),
            "store_ref": cls._required(store_ref, "store_ref", 240),
        }
        if not isinstance(actual, dict) or {
            "tenant_ref": actual.get("tenant_ref"),
            "entity_ref": actual.get("entity_ref"),
            "store_ref": actual.get("store_ref"),
        } != expected:
            raise PermissionError("Channel-account Approval exact-scope binding is invalid")
        payload = approval.payload
        source_basis = {
            key: payload.get(key)
            for key in (
                "contract_id",
                "scope",
                "reviewed_evidence_id",
                "reviewed_evidence_sha256",
                "reviewed_by",
                "target",
                "intended_patch",
                "rollback_patch",
            )
        }
        source_snapshot_hash = cls._hash(source_basis)
        if (
            approval.action != "channel_account.change"
            or approval.resource_type != "channel_account_change"
            or payload.get("contract_id") != cls.CHANGE_APPROVAL_CONTRACT_ID
            or payload.get("source_snapshot_hash") != source_snapshot_hash
            or approval.resource_id != f"cach_{source_snapshot_hash[:32]}"
            or (
                principal.actor_id == approval.requested_by
                and actual.get("scope_grant_authority_sha256")
                != entity_scope.get("authority_sha256")
            )
        ):
            raise PermissionError("Channel-account Approval authority binding is invalid")

    @classmethod
    def _reject_sensitive(cls, value: Any, *, path: str = "command.payload") -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                normalized = str(key).strip().lower().replace("-", "_")
                if normalized in cls._FORBIDDEN_KEYS or any(
                    fragment in normalized for fragment in ("cookie", "password", "private_token", "session_token")
                ):
                    raise ChannelAccountGovernanceError(f"Credential material is forbidden at {path}.{key}")
                cls._reject_sensitive(item, path=f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                cls._reject_sensitive(item, path=f"{path}[{index}]")

    @staticmethod
    def _exact_keys(value: dict[str, Any], allowed: set[str], command: str) -> None:
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ChannelAccountGovernanceError(f"{command} contains unsupported fields: {', '.join(unknown)}")

    @staticmethod
    def _required(value: Any, field: str, limit: int) -> str:
        normalized = str(value or "").strip()
        if not normalized or len(normalized) > limit:
            raise ChannelAccountGovernanceError(f"{field} is required")
        return normalized

    @staticmethod
    def _aware(value: datetime) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ChannelAccountGovernanceError("as_of must be timezone-aware")
        return value.astimezone(UTC)

    @staticmethod
    def _hash(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
