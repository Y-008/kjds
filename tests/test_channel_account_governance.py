from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from apps.control_plane.channel_account_governance import (
    ChannelAccountGovernanceError,
    ChannelAccountGovernanceStateMachine,
)
from apps.control_plane.security import Principal

NOW = datetime(2026, 8, 1, tzinfo=UTC)
SCOPE = {
    "status": "ready",
    "tenant_ref": "tenant-a",
    "entity_ref": "entity-a",
    "store_ref": "ozon-primary",
    "authority_sha256": "a" * 64,
}


class EvidenceAuthority:
    def __init__(self):
        self.calls = []

    def submit(self, **values):
        self.calls.append(("submit", values))
        return {
            "status": "submitted",
            "evidence_id": "evidence-submission-1",
            "evidence_sha256": "b" * 64,
            "scope": {
                "tenant_ref": "tenant-a", "entity_ref": "entity-a", "store_ref": "ozon-primary",
                "scope_grant_authority_sha256": "a" * 64,
            },
        }

    def review(self, **values):
        self.calls.append(("review", values))
        return {
            "status": "accepted" if values["accepted"] else "rejected",
            "evidence_id": "evidence-review-1",
            "evidence_sha256": "c" * 64,
            "scope": {
                "tenant_ref": "tenant-a", "entity_ref": "entity-a", "store_ref": "ozon-primary",
                "scope_grant_authority_sha256": "a" * 64,
            },
        }

    def require_reviewed(self, **values):
        self.calls.append(("require_reviewed", values))
        return {
            "evidence_id": values["evidence_id"],
            "evidence_sha256": "d" * 64,
            "submitted_by": "operator-a",
            "reviewed_by": "reviewer-a",
            "scope": {
                "tenant_ref": "tenant-a", "entity_ref": "entity-a", "store_ref": "ozon-primary",
                "scope_grant_authority_sha256": "a" * 64,
            },
            "canonical_payload": {
                "contract_id": "kjds-channel-account-change-proposal-v1",
                "platform": "ozon",
                "account_ref": "account-a",
                "change_kind": "grant_read_capability",
                "requested_capabilities": ["catalog.read"],
            },
        }


class Commerce:
    def __init__(self):
        self.approvals = {}
        self.repo = self

    def request_approval(self, **values):
        approval = SimpleNamespace(
            id="approval-a",
            action=values["action"],
            resource_type=values["resource_type"],
            resource_id=values["resource_id"],
            requested_by=values["requested_by"],
            payload=values["payload"],
            status=SimpleNamespace(value="pending"),
            decided_by=None,
        )
        self.approvals[approval.id] = approval
        return approval

    def get_approval(self, approval_id):
        return self.approvals[approval_id]

    def decide_approval(self, approval_id, *, approved, decided_by, reason):
        approval = self.approvals[approval_id]
        if approval.requested_by == decided_by:
            raise ValueError("self approval")
        approval.status = SimpleNamespace(value="approved" if approved else "rejected")
        approval.decided_by = decided_by
        approval.reason = reason
        return approval


class Plans:
    def __init__(self):
        self.calls = []

    def create_from_approved_channel_account(self, approval_id, **values):
        self.calls.append((approval_id, values))
        return {
            "id": "plan-a",
            "source_approval_id": approval_id,
            "approval_id": "execution-approval-a",
            "live_execution_supported": False,
            "execution_eligible": False,
            **values,
        }


def principal(actor="operator-a", *roles):
    return Principal(actor_id=actor, tenant_ref="tenant-a", roles=frozenset(roles or ("operator",)), store_refs=frozenset({"ozon-primary"}))


def test_submit_and_independent_review_use_one_transition_seam():
    authority = EvidenceAuthority()
    machine = ChannelAccountGovernanceStateMachine(governance_evidence=authority)
    submitted = machine.advance(
        principal=principal(), entity_scope=SCOPE, store_ref="ozon-primary", as_of=NOW,
        command={"type": "submit_evidence", "payload": {
            "purpose": "consent", "effective_at": NOW.isoformat(), "effective_until": None,
            "idempotency_key": "submit-1", "semantic_metadata": {"status": "authorized", "revoked": False, "immutable": True},
            "canonical_payload": {"contract_id": "kjds-channel-account-consent-evidence-v1", "status": "authorized", "revoked": False, "immutable": True},
        }},
    )
    reviewed = machine.advance(
        principal=principal("reviewer-a", "reviewer"), entity_scope=SCOPE, store_ref="ozon-primary", as_of=NOW,
        command={"type": "review_evidence", "payload": {"submission_evidence_id": "evidence-submission-1", "accepted": True, "rationale": "independent review"}},
    )
    assert submitted["to_state"] == "evidence_pending"
    assert reviewed["to_state"] == "evidence_reviewed"
    assert reviewed["next_allowed_transitions"] == ["request_change_approval"]
    assert all(item["external_write_allowed"] is False for item in (submitted, reviewed))
    assert all(item["control_envelope"]["credential_created_or_read"] is False for item in (submitted, reviewed))
    assert [call[0] for call in authority.calls] == ["submit", "review"]


@pytest.mark.parametrize("key", ["api_key", "cookie", "private-token", "session_token"])
def test_sensitive_material_is_rejected_before_authority_call(key):
    authority = EvidenceAuthority()
    machine = ChannelAccountGovernanceStateMachine(governance_evidence=authority)
    with pytest.raises(ChannelAccountGovernanceError, match="Credential material"):
        machine.advance(
            principal=principal(), entity_scope=SCOPE, store_ref="ozon-primary", as_of=NOW,
            command={"type": "submit_evidence", "payload": {key: "not-allowed"}},
        )
    assert authority.calls == []


def test_unknown_transition_is_rejected_without_side_effect():
    authority = EvidenceAuthority()
    machine = ChannelAccountGovernanceStateMachine(governance_evidence=authority)
    with pytest.raises(ChannelAccountGovernanceError, match="Unsupported"):
        machine.advance(
            principal=principal(), entity_scope=SCOPE, store_ref="ozon-primary", as_of=NOW,
            command={"type": "execute_provider_write", "payload": {}},
        )
    assert authority.calls == []


def test_reviewed_change_reaches_approved_internal_plan_but_not_execution():
    authority = EvidenceAuthority()
    commerce = Commerce()
    machine = ChannelAccountGovernanceStateMachine(
        governance_evidence=authority,
        commerce=commerce,
        execution_plans=Plans(),
    )
    requested = machine.advance(
        principal=principal("change-requester", "operator"),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=NOW,
        command={
            "type": "request_change_approval",
            "payload": {
                "reviewed_evidence_id": "reviewed-a",
            },
        },
    )
    decided = machine.advance(
        principal=principal("approver-a", "approver"),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=NOW,
        command={
            "type": "decide_change_approval",
            "payload": {"approval_id": "approval-a", "approved": True, "reason": "independent decision"},
        },
    )
    planned = machine.advance(
        principal=principal("plan-operator", "operator"),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=NOW,
        command={
            "type": "materialize_internal_plan",
            "payload": {"approval_id": "approval-a", "idempotency_key": "plan-1"},
        },
    )
    assert requested["to_state"] == "approval_pending"
    assert decided["to_state"] == "approved"
    assert planned["to_state"] == "execution_gated"
    assert planned["canonical_refs"]["execution_plan_id"] == "plan-a"
    assert requested["control_envelope"]["approval_created"] is True
    assert planned["control_envelope"]["approval_created"] is True
    assert planned["control_envelope"]["permit_created"] is False
    assert planned["external_write_allowed"] is False


def test_distinct_subject_authority_hash_can_decide_and_materialize_same_scope():
    authority = EvidenceAuthority()
    commerce = Commerce()
    machine = ChannelAccountGovernanceStateMachine(
        governance_evidence=authority,
        commerce=commerce,
        execution_plans=Plans(),
    )
    requested = machine.advance(
        principal=principal("change-requester", "operator"),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=NOW,
        command={
            "type": "request_change_approval",
            "payload": {"reviewed_evidence_id": "reviewed-a"},
        },
    )
    approval_id = requested["canonical_refs"]["approval_id"]
    other_scope = {**SCOPE, "authority_sha256": "b" * 64}
    decided = machine.advance(
        principal=principal("approver-b", "approver"),
        entity_scope=other_scope,
        store_ref="ozon-primary",
        as_of=NOW,
        command={
            "type": "decide_change_approval",
            "payload": {"approval_id": approval_id, "approved": True, "reason": "independent decision"},
        },
    )
    assert decided["to_state"] == "approved"
    planned = machine.advance(
        principal=principal("plan-operator", "operator"),
        entity_scope=other_scope,
        store_ref="ozon-primary",
        as_of=NOW,
        command={
            "type": "materialize_internal_plan",
            "payload": {"approval_id": approval_id, "idempotency_key": "plan-distinct-subject"},
        },
    )
    assert planned["to_state"] == "execution_gated"


@pytest.mark.parametrize("command_type", ["decide_change_approval", "materialize_internal_plan"])
def test_approval_id_cannot_cross_exact_scope_before_decision_or_plan(command_type):
    authority = EvidenceAuthority()
    commerce = Commerce()
    plans = Plans()
    machine = ChannelAccountGovernanceStateMachine(
        governance_evidence=authority,
        commerce=commerce,
        execution_plans=plans,
    )
    commerce.request_approval(
        action="channel_account.change",
        resource_type="channel_account_change",
        resource_id="change-other-store",
        requested_by="requester-a",
        payload={
            "scope": {
                "tenant_ref": "tenant-a",
                "entity_ref": "entity-a",
                "store_ref": "ozon-other",
            },
            "reviewed_by": "reviewer-a",
        },
    )
    payload = (
        {"approval_id": "approval-a", "approved": True, "reason": "must fail closed"}
        if command_type == "decide_change_approval"
        else {"approval_id": "approval-a", "idempotency_key": "cross-scope-plan"}
    )
    actor = principal("approver-a", "approver") if command_type == "decide_change_approval" else principal("operator-b", "operator")

    with pytest.raises(PermissionError, match="exact-scope"):
        machine.advance(
            principal=actor,
            entity_scope=SCOPE,
            store_ref="ozon-primary",
            as_of=NOW,
            command={"type": command_type, "payload": payload},
        )

    assert commerce.approvals["approval-a"].status.value == "pending"
    assert plans.calls == []


def test_same_scope_approval_for_another_action_cannot_be_decided_by_channel_route():
    authority = EvidenceAuthority()
    commerce = Commerce()
    machine = ChannelAccountGovernanceStateMachine(
        governance_evidence=authority,
        commerce=commerce,
        execution_plans=Plans(),
    )
    approval = commerce.request_approval(
        action="purchase.commit",
        resource_type="purchase_order",
        resource_id="purchase-a",
        requested_by="buyer-a",
        payload={
            "scope": {
                "tenant_ref": "tenant-a", "entity_ref": "entity-a", "store_ref": "ozon-primary",
                "scope_grant_authority_sha256": "a" * 64,
            }
        },
    )

    with pytest.raises(PermissionError, match="authority binding"):
        machine.advance(
            principal=principal("approver-a", "approver"),
            entity_scope=SCOPE,
            store_ref="ozon-primary",
            as_of=NOW,
            command={
                "type": "decide_change_approval",
                "payload": {"approval_id": approval.id, "approved": True, "reason": "must fail closed"},
            },
        )

    assert approval.status.value == "pending"
