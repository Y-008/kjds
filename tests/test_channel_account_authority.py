from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane import causal_policies as _causal_policies  # noqa: F401
from apps.control_plane import policy_shadow as _policy_shadow  # noqa: F401
from apps.control_plane.channel_account_authority import (
    ChannelAccountAdapterRegistry,
    ChannelAccountAuthorizationAuthority,
    ChannelAccountAuthorizationEventRow,
    ChannelAccountKillSwitchStateRow,
    ChannelAccountReviewDecisionRow,
)
from apps.control_plane.evidence_scope import DIRECT_CONTRACT
from apps.control_plane.execution_plans import ExecutionPlanRow
from apps.control_plane.limited_executor import (
    LimitedExecutionCommandRow,
    LimitedExecutionReceiptRow,
)
from apps.control_plane.security import KillSwitchEventRow, Principal
from apps.control_plane.sql_repository import ApprovalRow, Base

NOW = datetime.now(UTC) - timedelta(minutes=5)
EVENT_AT = NOW - timedelta(minutes=1)
AS_OF = NOW
AUTHORITY_SHA = "a" * 64
SCOPE = {
    "tenant_ref": "tenant-a",
    "entity_ref": "entity-a",
    "store_ref": "ozon-primary",
    "scope_grant_authority_sha256": AUTHORITY_SHA,
}
ENTITY_SCOPE = {
    "status": "ready",
    "tenant_ref": "tenant-a",
    "entity_ref": "entity-a",
    "store_ref": "ozon-primary",
    "authority_sha256": AUTHORITY_SHA,
}


class CanonicalMutationScope:
    def resolve(self, *, principal, entity_scope, store_ref, **_values):
        expected_prefix = (
            "tenant-a",
            "entity-a",
            "ozon-primary",
        )
        supplied = (
            principal.tenant_ref,
            entity_scope.get("entity_ref"),
            store_ref,
            entity_scope.get("authority_sha256"),
        )
        if (
            entity_scope.get("status") != "ready"
            or supplied[:3] != expected_prefix
            or supplied[3] not in {AUTHORITY_SHA, "b" * 64}
        ):
            raise PermissionError("canonical mutation scope denied")
        return {
            **SCOPE,
            "scope_grant_authority_sha256": supplied[3],
        }


@dataclass
class Evidence:
    id: str
    sha256: str
    metadata: dict
    content_bytes: bytes
    source: str
    created_by: str


class EvidenceStore:
    def __init__(self):
        self.records: dict[str, Evidence] = {}

    def require_current(self, evidence_ids, *, as_of):
        for evidence_id in evidence_ids:
            record = self.records[evidence_id]
            if record.metadata.get("_revoked") is True:
                raise ValueError("revoked")
            effective_until = record.metadata.get("_effective_until")
            if effective_until and effective_until <= as_of:
                raise ValueError("expired")

    def get(self, evidence_id):
        return self.records[evidence_id]

    def get_metadata(self, evidence_id):
        return self.records[evidence_id]

    def content(self, evidence_id):
        record = self.records[evidence_id]
        return record.content_bytes, record


class ScopedEvidence:
    def project_targets(self, *, evidence_ids, **_kwargs):
        return {
            "status": "ready",
            "records": [
                {
                    "evidence_id": evidence_id,
                    "status": "ready",
                }
                for evidence_id in evidence_ids
            ],
        }


def principal(actor="channel-operator"):
    return Principal(
        actor_id=actor,
        roles=frozenset({"operator", "risk"}),
        tenant_ref="tenant-a",
        store_refs=frozenset({"ozon-primary"}),
    )


def database():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def reviewed(
    authority,
    evidence,
    *,
    evidence_id,
    purpose,
    payload,
    metadata,
):
    content = authority._canonical_bytes(payload)
    digest = authority._hash(payload)
    submission_id = f"submission-{evidence_id}"
    source, contract_id = (
        authority.__class__.__module__
        and __import__(
            "apps.control_plane.channel_account_authority",
            fromlist=["ChannelAccountGovernanceEvidenceAuthority"],
        ).ChannelAccountGovernanceEvidenceAuthority.PURPOSES[purpose]
    )
    evidence.records[submission_id] = Evidence(
        id=submission_id,
        sha256=digest,
        metadata={
            "contract_id": ("kjds-channel-account-governance-submission-v1"),
            "purpose": purpose,
            **{
                key: SCOPE[key]
                for key in (
                    "tenant_ref",
                    "entity_ref",
                    "store_ref",
                )
            },
        },
        content_bytes=content,
        source="channel_account_governance_submission",
        created_by="channel-operator",
    )
    final_metadata = {
        **metadata,
        "contract_id": contract_id,
        "evidence_scope_contract_id": DIRECT_CONTRACT,
        "tenant_ref": SCOPE["tenant_ref"],
        "entity_ref": SCOPE["entity_ref"],
        "store_ref": SCOPE["store_ref"],
        "submitted_by": "channel-operator",
        "reviewed_by": "channel-reviewer",
        "reviewed_submission_id": submission_id,
        "reviewed_submission_sha256": digest,
        "channel_account_review_contract_id": ("kjds-channel-account-sod-review-v1"),
        "canonical_payload_sha256": digest,
        "review_sequence": 1,
        "review_decision_sha256": digest,
    }
    if purpose == "lifecycle":
        final_metadata["event_payload_sha256"] = digest
    if purpose == "kill_switch":
        final_metadata["kill_switch_state_payload_sha256"] = digest
    record = Evidence(
        id=evidence_id,
        sha256=digest,
        metadata=final_metadata,
        content_bytes=content,
        source=source,
        created_by="channel-operator",
    )
    evidence.records[evidence_id] = record
    with Session(authority.engine) as session, session.begin():
        session.add(
            ChannelAccountReviewDecisionRow(
                id=f"review-{evidence_id}",
                submission_evidence_id=submission_id,
                decision_evidence_id=evidence_id,
                sequence=1,
                accepted=True,
                reviewer_id="channel-reviewer",
                decision_sha256=digest,
                decided_at=EVENT_AT - timedelta(minutes=1),
                recorded_at=EVENT_AT - timedelta(minutes=1),
                tenant_ref=SCOPE["tenant_ref"],
                entity_ref=SCOPE["entity_ref"],
                store_ref=SCOPE["store_ref"],
            )
        )
    return record


def prepare(*, approval_output_override=None):
    engine = database()
    evidence = EvidenceStore()
    adapters = ChannelAccountAdapterRegistry()
    authority = ChannelAccountAuthorizationAuthority(
        engine=engine,
        evidence=evidence,
        scoped_evidence=ScopedEvidence(),
        adapters=adapters,
        scope_authority=CanonicalMutationScope(),
    )
    adapter = adapters.resolve(
        platform="ozon",
        adapter_id="ozon-seller-api-read",
        adapter_version="v1",
        as_of=AS_OF,
    )
    consent = reviewed(
        authority,
        evidence,
        evidence_id="consent-a",
        purpose="consent",
        payload={
            "contract_id": ("kjds-channel-account-consent-payload-v1"),
            "platform": "ozon",
            "account_ref": "account-a",
            "adapter_id": adapter["adapter_id"],
            "adapter_version": adapter["adapter_version"],
            "allowed_capabilities": ["orders.read"],
            "scope": SCOPE,
        },
        metadata={
            "status": "authorized",
            "revoked": False,
            "immutable": True,
            "authorization_source": "official",
            "platform": "ozon",
            "account_ref": "account-a",
            "adapter_id": adapter["adapter_id"],
            "adapter_version": adapter["adapter_version"],
            "credential_kind": "api_key_ref",
            "allowed_capabilities": ["orders.read"],
            "role_ref": "seller",
            "subaccount_ref": None,
            "consent_owner": "legal-owner",
        },
    )
    governance = {
        "approval_id": "approval-a",
        "command_id": "command-a",
        "receipt_id": "receipt-a",
        "permit_evidence_id": "permit-a",
        "readback_evidence_id": "readback-a",
        "kill_switch_sequence": 1,
        "kill_switch_state_id": "kill-state-a",
        "kill_switch_evidence_id": "kill-a",
        "compensation_plan_id": "comp-plan-a",
        "compensation_evidence_id": "comp-a",
    }
    context = {"cutoff": AS_OF, "scope": SCOPE}
    authorization_payload = authority._authorization_payload(
        context=context,
        source_event_ref="source-a",
        sequence=1,
        event_type="authorization_granted",
        authorization_source="official",
        platform="ozon",
        account_ref="account-a",
        adapter=adapter,
        credential_kind="api_key_ref",
        capabilities=["orders.read"],
        role_ref="seller",
        subaccount_ref=None,
        secret_reference_sha256=authority._hash_text("msl_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"),
        credential_fingerprint_sha256="c" * 64,
        health_status="healthy",
        readback_outcome="succeeded",
        rate_limit_state="available",
        external_schema_version="v1",
        effective_at=EVENT_AT,
        expires_at=EVENT_AT + timedelta(days=30),
        verified_at=EVENT_AT,
        observation_as_of=AS_OF,
    )
    output_sha256 = authority._hash(authorization_payload)
    previous_authorization = authority._previous_authorization_state(
        row=None,
        scope=SCOPE,
        platform="ozon",
        account_ref="account-a",
        adapter_id=adapter["adapter_id"],
    )
    input_sha256 = authority._hash(previous_authorization)
    previous_binding = authority._previous_authorization_binding(None)
    decision_hash = "d" * 64
    authorization_hash = "e" * 64
    target = {
        "previous_authorization": previous_authorization,
        "previous_authorization_binding": previous_binding,
        "proposed_authorization_sha256": output_sha256,
        "input_sha256": input_sha256,
    }
    with Session(engine) as session, session.begin():
        session.add_all(
            [
                ApprovalRow(
                    id="approval-a",
                    action="channel_authorization_grant",
                    resource_type="channel_account",
                    resource_id="account-a",
                    requested_by="channel-operator",
                    payload_json={
                        "tenant_ref": SCOPE["tenant_ref"],
                        "entity_ref": SCOPE["entity_ref"],
                        "store_ref": SCOPE["store_ref"],
                        "scope_grant_authority_sha256": AUTHORITY_SHA,
                        "platform": "ozon",
                        "account_ref": "account-a",
                        "adapter_id": adapter["adapter_id"],
                        "adapter_version": adapter["adapter_version"],
                        "event_type": "authorization_granted",
                        "source_event_ref": "source-a",
                        "previous_authorization_binding": previous_binding,
                        "input_sha256": input_sha256,
                        "output_sha256": (approval_output_override or output_sha256),
                        "decision_hash": decision_hash,
                        "authorization_hash": authorization_hash,
                    },
                    status="approved",
                    decided_by="channel-approver",
                    decision_reason="independent approval",
                    created_at=EVENT_AT - timedelta(minutes=10),
                ),
                ApprovalRow(
                    id="comp-approval-a",
                    action="channel_authorization_compensate",
                    resource_type="channel_account",
                    resource_id="account-a",
                    requested_by="compensation-planner",
                    payload_json={
                        "contract_id": ("kjds-channel-account-compensation-approval-v1"),
                        "tenant_ref": SCOPE["tenant_ref"],
                        "entity_ref": SCOPE["entity_ref"],
                        "store_ref": SCOPE["store_ref"],
                        "scope_grant_authority_sha256": AUTHORITY_SHA,
                        "platform": "ozon",
                        "account_ref": "account-a",
                        "adapter_id": adapter["adapter_id"],
                        "adapter_version": adapter["adapter_version"],
                        "source_event_ref": "source-a",
                        "primary_approval_id": "approval-a",
                        "command_id": "command-a",
                        "receipt_id": "receipt-a",
                        "compensation_plan_id": "comp-plan-a",
                        "previous_authorization_binding": previous_binding,
                        "precondition_state_sha256": input_sha256,
                        "mutated_state_sha256": output_sha256,
                        "restore_authority_sha256": None,
                        "compensation_mode": "disable_revoke_cleanup",
                        "requires_fresh_approval": True,
                        "automatic_execution_allowed": False,
                    },
                    status="approved",
                    decided_by="compensation-approver",
                    decision_reason="independent compensation approval",
                    created_at=EVENT_AT - timedelta(minutes=9),
                ),
                KillSwitchEventRow(
                    sequence=1,
                    engaged=False,
                    reason="risk controller release",
                    actor_id="risk-controller",
                    created_at=EVENT_AT - timedelta(minutes=8),
                ),
            ]
        )
    kill_scope_as_of = EVENT_AT - timedelta(minutes=5)
    kill_payload = {
        "contract_id": ("kjds-channel-account-kill-switch-state-v1"),
        "schema_version": "1",
        "source_event_ref": "kill-source-a",
        "sequence": 1,
        "kill_switch_sequence": 1,
        "writes_enabled": True,
        "action_id": "channel_authorization_grant",
        "platform": "ozon",
        "account_ref": "account-a",
        "adapter_id": adapter["adapter_id"],
        "adapter_version": adapter["adapter_version"],
        "adapter_contract_sha256": adapter["contract_sha256"],
        "effective_at": (EVENT_AT - timedelta(minutes=6)).isoformat(),
        "scope": {
            **SCOPE,
            "as_of": kill_scope_as_of.isoformat(),
        },
    }
    kill = reviewed(
        authority,
        evidence,
        evidence_id="kill-a",
        purpose="kill_switch",
        payload=kill_payload,
        metadata={
            "purpose": "channel_account_kill_switch_release",
            "status": "released",
            "kill_switch_sequence": 1,
            "kill_switch_actor_id": "risk-controller",
            "action_id": "channel_authorization_grant",
            "source_event_ref": "kill-source-a",
            "adapter_id": adapter["adapter_id"],
            "adapter_version": adapter["adapter_version"],
            "account_ref": "account-a",
        },
    )
    with Session(engine) as session, session.begin():
        session.add(
            ChannelAccountKillSwitchStateRow(
                id="kill-state-a",
                source_event_ref="kill-source-a",
                sequence=1,
                kill_switch_sequence=1,
                writes_enabled=True,
                action_id="channel_authorization_grant",
                platform="ozon",
                account_ref="account-a",
                adapter_id=adapter["adapter_id"],
                adapter_version=adapter["adapter_version"],
                evidence_id=kill.id,
                evidence_sha256=kill.sha256,
                payload_sha256=authority._hash(kill_payload),
                effective_at=EVENT_AT - timedelta(minutes=6),
                recorded_at=EVENT_AT - timedelta(minutes=5),
                created_by="risk-recorder",
                tenant_ref=SCOPE["tenant_ref"],
                entity_ref=SCOPE["entity_ref"],
                store_ref=SCOPE["store_ref"],
                scope_grant_authority_sha256=AUTHORITY_SHA,
                scope_as_of=kill_scope_as_of,
            )
        )
    permit_expires = EVENT_AT + timedelta(minutes=5)
    permit = reviewed(
        authority,
        evidence,
        evidence_id="permit-a",
        purpose="permit",
        payload={
            "contract_id": ("kjds-channel-account-permit-payload-v1"),
            "command_id": "command-a",
            "input_sha256": input_sha256,
            "output_sha256": output_sha256,
        },
        metadata={
            "status": "issued",
            "revoked": False,
            "single_use": True,
            "approval_id": "approval-a",
            "command_id": "command-a",
            "execution_plan_id": "plan-a",
            "action_id": "channel_authorization_grant",
            "event_type": "authorization_granted",
            "source_event_ref": "source-a",
            "platform": "ozon",
            "account_ref": "account-a",
            "adapter_id": adapter["adapter_id"],
            "adapter_version": adapter["adapter_version"],
            "input_sha256": input_sha256,
            "decision_hash": decision_hash,
            "authorization_hash": authorization_hash,
            "issued_at": (EVENT_AT - timedelta(minutes=3)).isoformat(),
            "expires_at": permit_expires.isoformat(),
        },
    )
    receipt_fields = {
        "command_id": "command-a",
        "outcome": "succeeded",
        "remote_operation_id": "remote-auth-a",
        "resulting_state_hash": output_sha256,
        "mutation_applied": True,
        "error_code": None,
        "error_detail": None,
        "evidence_ids": ["readback-a"],
        "recorded_by": "official-adapter-worker",
    }
    receipt_request_hash = authority._hash(receipt_fields)
    readback = reviewed(
        authority,
        evidence,
        evidence_id="readback-a",
        purpose="readback",
        payload={
            "contract_id": ("kjds-channel-account-readback-payload-v1"),
            "receipt_id": "receipt-a",
            "request_hash": receipt_request_hash,
            "output_sha256": output_sha256,
        },
        metadata={
            "outcome": "succeeded",
            "official_or_authorized": True,
            "approval_id": "approval-a",
            "permit_evidence_id": permit.id,
            "command_id": "command-a",
            "receipt_id": "receipt-a",
            "action_id": "channel_authorization_grant",
            "event_type": "authorization_granted",
            "source_event_ref": "source-a",
            "platform": "ozon",
            "account_ref": "account-a",
            "adapter_id": adapter["adapter_id"],
            "adapter_version": adapter["adapter_version"],
            "authorization_changed": True,
            "remote_operation_id": "remote-auth-a",
            "input_sha256": input_sha256,
            "resulting_authority_sha256": output_sha256,
            "request_hash": receipt_request_hash,
            "readback_at": EVENT_AT.isoformat(),
        },
    )
    compensation_target = {
        **target,
        "receipt_id": "receipt-a",
        "output_sha256": output_sha256,
    }
    compensation_mode = "disable_revoke_cleanup"
    compensation = reviewed(
        authority,
        evidence,
        evidence_id="comp-a",
        purpose="compensation",
        payload={
            "contract_id": ("kjds-channel-account-compensation-payload-v2"),
            "compensation_plan_id": "comp-plan-a",
            "compensation_mode": compensation_mode,
            "previous_authorization_binding": previous_binding,
            "precondition_state_sha256": input_sha256,
            "mutated_state_sha256": output_sha256,
            "restore_authority_sha256": None,
            "scope": SCOPE,
            "platform": "ozon",
            "account_ref": "account-a",
            "adapter_id": adapter["adapter_id"],
            "adapter_version": adapter["adapter_version"],
        },
        metadata={
            "purpose": "channel_account_compensation_plan",
            "status": "ready",
            "compensation_plan_id": "comp-plan-a",
            "approval_id": "approval-a",
            "compensation_approval_id": "comp-approval-a",
            "command_id": "command-a",
            "receipt_id": "receipt-a",
            "action_id": "channel_authorization_grant",
            "source_event_ref": "source-a",
            "adapter_id": adapter["adapter_id"],
            "adapter_version": adapter["adapter_version"],
            "account_ref": "account-a",
            "owner": "compensation-owner",
            "compensation_mode": compensation_mode,
            "precondition_state_sha256": input_sha256,
        },
    )
    with Session(engine) as session, session.begin():
        session.add_all(
            [
                ExecutionPlanRow(
                    id="plan-a",
                    request_hash="1" * 64,
                    source_kind="approved_channel_account_change",
                    source_id="source-a",
                    source_approval_id="approval-a",
                    source_snapshot_hash="2" * 64,
                    handoff_id=None,
                    policy_id=None,
                    release_id=None,
                    idempotency_key="plan-a",
                    adapter_id=adapter["adapter_id"],
                    action_id="channel_authorization_grant",
                    action_policy_version="bas158-v1",
                    target_json=target,
                    precondition_state_hash=input_sha256,
                    intended_patch_json={
                        "output_sha256": output_sha256,
                        "authorization_changed": True,
                    },
                    rollback_patch_json={"restore_authority_sha256": input_sha256},
                    risk_limits_json={},
                    risk_values_json={},
                    risk_currency=None,
                    permit_ttl_seconds=300,
                    evidence_json=[permit.id],
                    approval_id="approval-a",
                    created_by="channel-operator",
                    created_at=EVENT_AT - timedelta(minutes=4),
                ),
                ExecutionPlanRow(
                    id="comp-plan-a",
                    request_hash="3" * 64,
                    source_kind=("approved_channel_account_compensation"),
                    source_id="source-a",
                    source_approval_id="approval-a",
                    source_snapshot_hash="4" * 64,
                    handoff_id=None,
                    policy_id=None,
                    release_id=None,
                    idempotency_key="comp-plan-a",
                    adapter_id=adapter["adapter_id"],
                    action_id="channel_authorization_compensate",
                    action_policy_version="bas158-v1",
                    target_json=compensation_target,
                    precondition_state_hash=output_sha256,
                    intended_patch_json={
                        "compensation_mode": compensation_mode,
                        "restore_authority_sha256": None,
                        "requires_fresh_approval": True,
                        "automatic_execution_allowed": False,
                    },
                    rollback_patch_json={},
                    risk_limits_json={},
                    risk_values_json={},
                    risk_currency=None,
                    permit_ttl_seconds=None,
                    evidence_json=[compensation.id],
                    approval_id="comp-approval-a",
                    created_by="compensation-planner",
                    created_at=EVENT_AT - timedelta(minutes=3),
                ),
                LimitedExecutionCommandRow(
                    id="command-a",
                    plan_id="plan-a",
                    parent_command_id=None,
                    command_kind="execute",
                    idempotency_token="5" * 64,
                    adapter_id=adapter["adapter_id"],
                    action_id="channel_authorization_grant",
                    action_policy_version="bas158-v1",
                    decision_hash=decision_hash,
                    authorization_hash=authorization_hash,
                    permit_expires_at=permit_expires,
                    operation=("channel_account.authorization_granted"),
                    target_json=target,
                    patch_json={
                        "output_sha256": output_sha256,
                        "authorization_changed": True,
                    },
                    risk_limits_json={},
                    risk_values_json={},
                    risk_currency=None,
                    portfolio_risk_json={},
                    expected_state_hash=input_sha256,
                    status="succeeded",
                    queued_by="channel-operator",
                    claimed_by="official-adapter-worker",
                    claimed_at=EVENT_AT - timedelta(minutes=2),
                    lease_expires_at=EVENT_AT + timedelta(minutes=1),
                    created_at=EVENT_AT - timedelta(minutes=3),
                ),
                LimitedExecutionReceiptRow(
                    id="receipt-a",
                    request_hash=receipt_request_hash,
                    command_id="command-a",
                    request_id="request-a",
                    trace_id="trace-a",
                    outcome="succeeded",
                    remote_operation_id="remote-auth-a",
                    resulting_state_hash=output_sha256,
                    mutation_applied=True,
                    error_code=None,
                    error_detail=None,
                    evidence_json=[readback.id],
                    recorded_by="official-adapter-worker",
                    recorded_at=EVENT_AT,
                ),
            ]
        )
    observation = authority._observation_payload(
        context=context,
        source_event_ref="source-a",
        sequence=1,
        event_type="authorization_granted",
        authorization_source="official",
        platform="ozon",
        account_ref="account-a",
        adapter=adapter,
        credential_kind="api_key_ref",
        capabilities=["orders.read"],
        role_ref="seller",
        subaccount_ref=None,
        secret_reference_sha256=authorization_payload["secret_reference_sha256"],
        credential_fingerprint_sha256="c" * 64,
        health_status="healthy",
        readback_outcome="succeeded",
        rate_limit_state="available",
        external_schema_version="v1",
        consent_evidence=consent,
        governance=governance,
        effective_at=EVENT_AT,
        expires_at=EVENT_AT + timedelta(days=30),
        verified_at=EVENT_AT,
        observation_as_of=AS_OF,
        authorization_payload=authorization_payload,
    )
    source = reviewed(
        authority,
        evidence,
        evidence_id="lifecycle-a",
        purpose="lifecycle",
        payload=observation,
        metadata={
            **{
                key: observation[key]
                for key in (
                    "source_event_ref",
                    "sequence",
                    "event_type",
                    "authorization_source",
                    "platform",
                    "account_ref",
                    "adapter_id",
                    "adapter_version",
                    "adapter_contract_sha256",
                    "role_ref",
                    "subaccount_ref",
                    "credential_kind",
                    "capabilities",
                    "secret_reference_sha256",
                    "credential_fingerprint_sha256",
                )
            },
            "immutable": True,
            "revoked": False,
            "consent_evidence_id": consent.id,
            "consent_evidence_sha256": consent.sha256,
            "observation_contract_id": observation["contract_id"],
            "observation_schema_version": observation["schema_version"],
            **governance,
            "input_sha256": input_sha256,
            "output_sha256": output_sha256,
        },
    )
    values = {
        "principal": principal(),
        "entity_scope": ENTITY_SCOPE,
        "store_ref": SCOPE["store_ref"],
        "source_event_ref": "source-a",
        "sequence": 1,
        "event_type": "authorization_granted",
        "authorization_source": "official",
        "platform": "ozon",
        "account_ref": "account-a",
        "adapter_id": adapter["adapter_id"],
        "adapter_version": adapter["adapter_version"],
        "credential_kind": "api_key_ref",
        "capabilities": ["orders.read"],
        "secret_reference": "msl_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "credential_fingerprint_sha256": "c" * 64,
        "health_status": "healthy",
        "readback_outcome": "succeeded",
        "rate_limit_state": "available",
        "external_schema_version": "v1",
        "consent_evidence_id": consent.id,
        "evidence_id": source.id,
        "effective_at": EVENT_AT.isoformat(),
        "expires_at": (EVENT_AT + timedelta(days=30)).isoformat(),
        "verified_at": EVENT_AT.isoformat(),
        "role_ref": "seller",
        "subaccount_ref": None,
        **governance,
        "as_of": AS_OF.isoformat(),
    }
    return authority, engine, evidence, values, authorization_payload


def test_governed_grant_requires_real_rows_and_never_returns_secret_ref():
    authority, _engine, _evidence, values, _payload = prepare()
    result = authority.append_event(**values)
    assert result["idempotent"] is False
    assert "secret_reference" not in result
    assert result["secret_reference_present"] is True
    source = authority.read_scoped_sources(
        tenant_ref=SCOPE["tenant_ref"],
        entity_ref=SCOPE["entity_ref"],
        store_ref=SCOPE["store_ref"],
        scope_grant_authority_sha256=AUTHORITY_SHA,
        as_of=datetime.now(UTC).isoformat(),
    )
    serialized = str(source)
    assert "msl_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" not in serialized
    assert source["events"][0]["kill_switch_state_id"] == ("kill-state-a")


def test_committed_event_retry_returns_original_before_revalidating_expired_governance(
    monkeypatch,
):
    authority, engine, evidence, values, _payload = prepare()
    original = authority.append_event(**values)
    for record in evidence.records.values():
        record.metadata["_revoked"] = True
    with Session(engine) as session, session.begin():
        session.add(
            KillSwitchEventRow(
                sequence=2,
                engaged=True,
                reason="fuse advanced after committed response",
                actor_id="risk-controller-2",
                created_at=AS_OF + timedelta(seconds=1),
            )
        )
    monkeypatch.setattr(
        authority.adapters,
        "resolve",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("adapter retired after commit")),
    )
    replay = authority.append_event(
        **{
            **values,
            "entity_scope": {
                **values["entity_scope"],
                "authority_sha256": "b" * 64,
            },
            "as_of": (AS_OF + timedelta(seconds=2)).isoformat(),
        }
    )
    assert replay["id"] == original["id"]
    assert replay["payload_sha256"] == original["payload_sha256"]
    assert replay["idempotent"] is True

    conflicting = {**values, "health_status": "degraded"}
    with pytest.raises(ValueError, match="conflicts with immutable values"):
        authority.append_event(**conflicting)


def test_compensation_prestate_hash_is_prior_authority_and_stale_after_new_epoch():
    authority, engine, _evidence, values, _payload = prepare()
    authority.append_event(**values)
    with Session(engine) as session, session.begin():
        state_a = session.query(ChannelAccountAuthorizationEventRow).one()
        scope_b = {
            **SCOPE,
            "scope_grant_authority_sha256": "b" * 64,
        }
        physical_predecessor = authority._previous_physical_authorization(
            session=session,
            scope=scope_b,
            platform="ozon",
            account_ref="account-a",
            adapter_id=state_a.adapter_id,
            before_sequence=2,
            exclude_source_event_ref="source-b",
        )
        assert physical_predecessor is state_a
        assert authority._previous_authorization_binding(
            physical_predecessor
        ) == {
            "state": "present",
            "authorization_event_id": state_a.id,
            "physical_sequence": 1,
            "scope_grant_authority_sha256": AUTHORITY_SHA,
            "payload_sha256": state_a.payload_sha256,
        }
        assert (
            authority._previous_physical_authorization(
                session=session,
                scope=scope_b,
                platform="ozon",
                account_ref="different-account",
                adapter_id=state_a.adapter_id,
                before_sequence=2,
                exclude_source_event_ref="source-b",
            )
            is None
        )
        assert (
            authority._previous_physical_authorization(
                session=session,
                scope=scope_b,
                platform="ozon",
                account_ref="account-a",
                adapter_id="different-adapter",
                before_sequence=2,
                exclude_source_event_ref="source-b",
            )
            is None
        )
        previous_a = authority._previous_authorization_state(
            row=physical_predecessor,
            scope=scope_b,
            platform="ozon",
            account_ref="account-a",
            adapter_id=state_a.adapter_id,
        )
        restore_a_sha256 = authority._hash(previous_a)
        binding_a = authority._previous_authorization_binding(state_a)
        authority._require_previous_authorization_binding(
            previous_row=state_a,
            previous_state=previous_a,
            previous_binding=binding_a,
            input_sha256=restore_a_sha256,
        )

        def physical_successor(source, sequence, scope_hash, payload_hash):
            copied = {
                column.name: getattr(state_a, column.name)
                for column in ChannelAccountAuthorizationEventRow.__table__.columns
            }
            copied.update(
                id=f"event-{source}",
                source_event_ref=source,
                sequence=sequence,
                event_type="credential_rotated",
                payload_sha256=payload_hash,
                source_payload_sha256=payload_hash,
                approval_id=f"approval-{source}",
                command_id=f"command-{source}",
                receipt_id=f"receipt-{source}",
                permit_evidence_id=f"permit-{source}",
                readback_evidence_id=f"readback-{source}",
                kill_switch_state_id=f"kill-state-{source}",
                kill_switch_evidence_id=f"kill-evidence-{source}",
                compensation_plan_id=f"comp-plan-{source}",
                compensation_evidence_id=f"comp-evidence-{source}",
                scope_grant_authority_sha256=scope_hash,
                effective_at=state_a.effective_at + timedelta(minutes=sequence),
                verified_at=state_a.verified_at + timedelta(minutes=sequence),
                recorded_at=state_a.recorded_at + timedelta(minutes=sequence),
                scope_as_of=state_a.scope_as_of + timedelta(minutes=sequence),
            )
            return ChannelAccountAuthorizationEventRow(**copied)

        state_b = physical_successor("source-b", 2, "b" * 64, "8" * 64)
        session.add(state_b)
        session.flush()
        predecessor_for_c = authority._previous_physical_authorization(
            session=session,
            scope=SCOPE,
            platform="ozon",
            account_ref="account-a",
            adapter_id=state_a.adapter_id,
            before_sequence=3,
            exclude_source_event_ref="source-c",
        )
        assert predecessor_for_c is state_b
        state_c = physical_successor("source-c", 3, "c" * 64, "7" * 64)
        session.add(state_c)
        session.flush()
        previous_c = authority._previous_authorization_state(
            row=state_c,
            scope={**SCOPE, "scope_grant_authority_sha256": "c" * 64},
            platform="ozon",
            account_ref="account-a",
            adapter_id=state_a.adapter_id,
        )
        with pytest.raises(ValueError, match="binding is stale"):
            authority._require_previous_authorization_binding(
                previous_row=state_c,
                previous_state=previous_a,
                previous_binding=binding_a,
                input_sha256=restore_a_sha256,
            )
    assert previous_a["authorization_event"]["health_status"] == "healthy"
    assert restore_a_sha256 != authority._hash(previous_c)
    assert restore_a_sha256 != authority._hash(_payload)


def test_forged_metadata_cannot_replace_canonical_command_row():
    authority, engine, _evidence, values, _payload = prepare()
    with Session(engine) as session, session.begin():
        session.delete(session.get(LimitedExecutionCommandRow, "command-a"))
    with pytest.raises(
        ValueError,
        match="command Permit",
    ):
        authority.append_event(**values)


def test_full_authorization_hash_catches_single_omitted_field():
    authority, _engine, _evidence, values, payload = prepare(approval_output_override="9" * 64)
    assert "health_status" in payload
    assert "capabilities" in payload
    assert "secret_reference_sha256" in payload
    assert "credential_fingerprint_sha256" in payload
    assert "expires_at" in payload
    with pytest.raises(
        ValueError,
        match="Approval",
    ):
        authority.append_event(**values)


@pytest.mark.parametrize(
    "field,value",
    [
        ("health_status", "degraded"),
        ("rate_limit_state", "limited"),
        ("external_schema_version", "v2"),
        ("verified_at", (EVENT_AT - timedelta(hours=2)).isoformat()),
    ],
)
def test_observation_single_field_tamper_cannot_match_blob(
    field,
    value,
):
    authority, _engine, _evidence, values, _payload = prepare()
    values[field] = value
    with pytest.raises(
        ValueError,
        match="lifecycle Evidence",
    ):
        authority.append_event(**values)


def test_newer_disabled_kill_switch_blocks_old_released_state():
    authority, engine, evidence, values, _payload = prepare()
    with Session(engine) as session, session.begin():
        session.add(
            KillSwitchEventRow(
                sequence=2,
                engaged=True,
                reason="latest incident lock",
                actor_id="risk-controller-2",
                created_at=EVENT_AT - timedelta(seconds=20),
            )
        )
    adapter = authority.adapters.resolve(
        platform="ozon",
        adapter_id="ozon-seller-api-read",
        adapter_version="v1",
        as_of=AS_OF,
    )
    latest_scope_as_of = EVENT_AT - timedelta(seconds=5)
    payload = {
        "contract_id": ("kjds-channel-account-kill-switch-state-v1"),
        "schema_version": "1",
        "source_event_ref": "kill-source-b",
        "sequence": 2,
        "kill_switch_sequence": 2,
        "writes_enabled": False,
        "action_id": "channel_authorization_grant",
        "platform": "ozon",
        "account_ref": "account-a",
        "adapter_id": adapter["adapter_id"],
        "adapter_version": adapter["adapter_version"],
        "adapter_contract_sha256": adapter["contract_sha256"],
        "effective_at": (EVENT_AT - timedelta(seconds=10)).isoformat(),
        "scope": {
            **SCOPE,
            "as_of": latest_scope_as_of.isoformat(),
        },
    }
    latest = reviewed(
        authority,
        evidence,
        evidence_id="kill-b",
        purpose="kill_switch",
        payload=payload,
        metadata={
            "purpose": "channel_account_kill_switch_release",
            "status": "engaged",
            "kill_switch_sequence": 2,
            "kill_switch_actor_id": "risk-controller-2",
            "action_id": "channel_authorization_grant",
            "source_event_ref": "kill-source-b",
            "adapter_id": adapter["adapter_id"],
            "adapter_version": adapter["adapter_version"],
            "account_ref": "account-a",
        },
    )
    with Session(engine) as session, session.begin():
        session.add(
            ChannelAccountKillSwitchStateRow(
                id="kill-state-b",
                source_event_ref="kill-source-b",
                sequence=2,
                kill_switch_sequence=2,
                writes_enabled=False,
                action_id="channel_authorization_grant",
                platform="ozon",
                account_ref="account-a",
                adapter_id=adapter["adapter_id"],
                adapter_version=adapter["adapter_version"],
                evidence_id=latest.id,
                evidence_sha256=latest.sha256,
                payload_sha256=authority._hash(payload),
                effective_at=EVENT_AT - timedelta(seconds=10),
                recorded_at=EVENT_AT - timedelta(seconds=5),
                created_by="risk-recorder-2",
                tenant_ref=SCOPE["tenant_ref"],
                entity_ref=SCOPE["entity_ref"],
                store_ref=SCOPE["store_ref"],
                scope_grant_authority_sha256=AUTHORITY_SHA,
                scope_as_of=latest_scope_as_of,
            )
        )
    with pytest.raises(
        ValueError,
        match="Kill Switch authority",
    ):
        authority.append_event(**values)


def test_newer_global_fuse_blocks_without_waiting_for_scoped_refresh():
    authority, engine, _evidence, values, _payload = prepare()
    with Session(engine) as session, session.begin():
        session.add(
            KillSwitchEventRow(
                sequence=2,
                engaged=True,
                reason="global emergency stop",
                actor_id="risk-controller-2",
                created_at=EVENT_AT - timedelta(seconds=20),
            )
        )
    with pytest.raises(ValueError, match="Kill Switch authority"):
        authority.append_event(**values)


def _committed_kill_replay_values(engine):
    with Session(engine) as session:
        row = session.get(ChannelAccountKillSwitchStateRow, "kill-state-a")
        assert row is not None
        return {
            "principal": principal("risk-replayer"),
            "entity_scope": ENTITY_SCOPE,
            "store_ref": row.store_ref,
            "source_event_ref": row.source_event_ref,
            "sequence": row.sequence,
            "kill_switch_sequence": row.kill_switch_sequence,
            "writes_enabled": row.writes_enabled,
            "action_id": row.action_id,
            "platform": row.platform,
            "account_ref": row.account_ref,
            "adapter_id": row.adapter_id,
            "adapter_version": row.adapter_version,
            "evidence_id": row.evidence_id,
            "effective_at": (ChannelAccountAuthorizationAuthority._aware(row.effective_at).isoformat()),
            "as_of": (ChannelAccountAuthorizationAuthority._aware(row.scope_as_of).isoformat()),
        }


def test_committed_kill_state_replays_before_expired_evidence_and_advanced_fuse():
    authority, engine, evidence, _values, _payload = prepare()
    replay_values = _committed_kill_replay_values(engine)
    evidence.records["kill-a"].metadata["_revoked"] = True
    with Session(engine) as session, session.begin():
        session.add(
            KillSwitchEventRow(
                sequence=2,
                engaged=True,
                reason="global fuse advanced after committed response",
                actor_id="risk-controller-2",
                created_at=AS_OF + timedelta(seconds=1),
            )
        )
    result = authority.record_kill_switch_state(**replay_values)
    assert result["id"] == "kill-state-a"
    assert result["idempotent"] is True
    with Session(engine) as session:
        assert session.query(ChannelAccountKillSwitchStateRow).count() == 1


def test_committed_kill_state_same_key_different_payload_conflicts():
    authority, engine, _evidence, _values, _payload = prepare()
    replay_values = _committed_kill_replay_values(engine)
    replay_values["writes_enabled"] = False
    with pytest.raises(ValueError, match="conflicts with immutable state"):
        authority.record_kill_switch_state(**replay_values)
    with Session(engine) as session:
        assert session.query(ChannelAccountKillSwitchStateRow).count() == 1


def test_concurrent_first_kill_insert_recovers_as_committed_replay(monkeypatch):
    authority, engine, _evidence, _values, _payload = prepare()
    replay_values = _committed_kill_replay_values(engine)
    with Session(engine) as session, session.begin():
        session.delete(session.get(ChannelAccountKillSwitchStateRow, "kill-state-a"))
    committed = {
        "id": "kill-state-winner",
        "source_event_ref": replay_values["source_event_ref"],
        "payload_sha256": "b" * 64,
        "idempotent": True,
    }
    replay_calls = 0

    def replay_after_unique_race(**_kwargs):
        nonlocal replay_calls
        replay_calls += 1
        return None if replay_calls == 1 else committed

    original_flush = Session.flush

    def race_flush(session, *args, **kwargs):
        if any(isinstance(row, ChannelAccountKillSwitchStateRow) for row in session.new):
            raise IntegrityError("concurrent unique winner", {}, Exception())
        return original_flush(session, *args, **kwargs)

    monkeypatch.setattr(
        authority,
        "_idempotent_kill_switch_replay",
        replay_after_unique_race,
    )
    monkeypatch.setattr(Session, "flush", race_flush)
    assert authority.record_kill_switch_state(**replay_values) == committed
    assert replay_calls == 2
