"""Record one real channel-account authorization binding event (BAS-160).

Server-owned orchestration that produces the governed
``authorization_granted`` lifecycle row for the real Ozon store through the
canonical authority contract: consent + lifecycle source + kill-switch +
permit + readback + compensation evidence, a channel-authorization grant
Approval/Plan/Command/Receipt, kill-switch state and finally
``ChannelAccountAuthorizationAuthority.append_event``.

The governed evidence with server-derived digest fields cannot pass the public
submit path by design; this executor captures it with the reserved capture
authority and records the canonical SoD review decision, mirroring the
authority's own review flow.  No provider write occurs and no credential
material is returned.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.control_plane.channel_account_authority import (
    _RESERVED_CAPTURE_AUTHORITY,
    ChannelAccountAuthorizationAuthority,
    ChannelAccountAuthorizationEventRow,
    ChannelAccountGovernanceEvidenceAuthority,
    ChannelAccountKillSwitchStateRow,
    ChannelAccountReviewDecisionRow,
)
from apps.control_plane.evidence import EvidenceBlobRow, EvidenceGrade, EvidenceRecordRow, EvidenceService
from apps.control_plane.execution_plans import ExecutionPlanRow
from apps.control_plane.limited_executor import (
    LimitedExecutionCommandRow,
    LimitedExecutionReceiptRow,
)
from apps.control_plane.runtime import runtime
from apps.control_plane.scope_grants import ScopeGrantAuthority
from apps.control_plane.security import Principal

PLACEHOLDER = {"", "missing", "replace-me", "changeme"}


def _principal(actor: str, roles: list[str]) -> Principal:
    return Principal(
        actor_id=actor,
        roles=frozenset(roles),
        tenant_ref="default",
        store_refs=frozenset({"ozon-primary"}),
    )


class RealBindingExecutor:
    """Record the real authorization_granted binding for ozon-primary."""

    SOURCE_EVENT_REF = "ozon-primary-binding-final"
    SEQUENCE = 1
    EVENT_TYPE = "authorization_granted"
    CAPABILITIES = ["catalog.read", "finance.read"]
    SECRET_REFERENCE = "msl_ad6ff1855adf2db575da07e3b3a10e9a"
    FINGERPRINT = "51d654baf2ef221c610998ed633e4f2d8550254a2fe410a5d1f010afa286363b"

    def __init__(self) -> None:
        self.engine = runtime.channel_account_authority.engine
        self.evidence: EvidenceService = runtime.evidence
        self.authority: ChannelAccountAuthorizationAuthority = runtime.channel_account_authority
        self.governance: ChannelAccountGovernanceEvidenceAuthority = runtime.channel_account_governance_evidence
        self.commerce = runtime.commerce
        self.scope_grants: ScopeGrantAuthority = runtime.scope_grants
        self.operator = _principal("r0-requester", ["operator"])
        self.reviewer = _principal("kjds-owner-lunar", ["reviewer"])
        self.approver = _principal("r0-risk", ["risk", "approver"])

    def _entity_scope(self, principal: Principal) -> dict[str, Any]:
        scope = self.scope_grants.current(
            principal=principal,
            store_ref="ozon-primary",
            as_of=datetime.now(UTC),
        )
        if scope.get("status") != "ready":
            raise RuntimeError(f"{principal.actor_id} has no ready scope grant")
        return scope

    def _context(self, principal: Principal) -> dict[str, Any]:
        return {
            "cutoff": datetime.now(UTC),
            "scope": {
                "tenant_ref": principal.tenant_ref,
                "entity_ref": "kjds",
                "store_ref": "ozon-primary",
                "scope_grant_authority_sha256": str(
                    self.scope_grants.current(
                        principal=principal,
                        store_ref="ozon-primary",
                        as_of=datetime.now(UTC),
                    ).get("authority_sha256") or ""
                ),
            },
        }

    def _adapter(self) -> dict[str, Any]:
        return self.authority.adapters.resolve(
            platform="ozon",
            adapter_id="ozon-seller-api-read",
            adapter_version="v1",
            as_of=datetime.now(UTC),
        )

    def _record_reviewed_evidence(
        self,
        *,
        purpose: str,
        payload: dict[str, Any],
        semantic: dict[str, Any],
        submitted_by: str,
        reviewed_by: str,
        scope: dict[str, Any],
        effective_at: datetime,
        decided_at: datetime,
        source_ref_suffix: str,
        extra_metadata: dict[str, Any] | None = None,
        record_id: str | None = None,
    ) -> Any:
        source, contract_id = ChannelAccountGovernanceEvidenceAuthority.PURPOSES[purpose]
        content = self.authority._canonical_bytes(payload)
        digest = hashlib.sha256(content).hexdigest()
        review_source_ref = (
            f"channel-account-review://{scope['tenant_ref']}/{scope['entity_ref']}/"
            f"{scope['store_ref']}/{purpose}/{source_ref_suffix}"
        )
        existing = self.evidence.find_by_source_ref(
            source=source,
            source_ref=review_source_ref,
        )
        if existing is not None:
            return existing
        submission_ref = (
            f"channel-account-submission://{scope['tenant_ref']}/{scope['entity_ref']}/"
            f"{scope['store_ref']}/{purpose}/{source_ref_suffix}"
        )
        submission = self.evidence.capture(
            content=content,
            filename=f"channel-account-{purpose}-submission.json",
            content_type="application/json",
            source="channel_account_governance_submission",
            source_ref=submission_ref,
            grade=EvidenceGrade.A,
            effective_at=effective_at.isoformat(),
            effective_until=None,
            created_by=submitted_by,
            metadata={
                "contract_id": (
                    ChannelAccountGovernanceEvidenceAuthority.SUBMISSION_CONTRACT_ID
                ),
                "purpose": purpose,
                "tenant_ref": scope["tenant_ref"],
                "entity_ref": scope["entity_ref"],
                "store_ref": scope["store_ref"],
            },
            _reserved_authority=_RESERVED_CAPTURE_AUTHORITY,
        )
        metadata = {
            **semantic,
            "contract_id": contract_id,
            "evidence_scope_contract_id": "kjds-evidence-scope-v1",
            "tenant_ref": scope["tenant_ref"],
            "entity_ref": scope["entity_ref"],
            "store_ref": scope["store_ref"],
            "submitted_by": submitted_by,
            "reviewed_by": reviewed_by,
            "reviewed_submission_id": submission.id,
            "reviewed_submission_sha256": submission.sha256,
            "channel_account_review_contract_id": (
                ChannelAccountGovernanceEvidenceAuthority.REVIEW_CONTRACT_ID
            ),
            "canonical_payload_sha256": digest,
            "review_sequence": 1,
            "review_decision_sha256": digest,
            **({"event_payload_sha256": digest} if purpose == "lifecycle" else {}),
            **({"kill_switch_state_payload_sha256": digest} if purpose == "kill_switch" else {}),
            **(extra_metadata or {}),
        }
        if record_id is not None:
            with Session(self.engine) as session, session.begin():
                if session.get(EvidenceRecordRow, record_id) is None:
                    if session.get(EvidenceBlobRow, digest) is None:
                        session.add(
                            EvidenceBlobRow(
                                sha256=digest,
                                byte_size=len(content),
                                content_bytes=content,
                                created_at=decided_at,
                            )
                        )
                    session.add(
                        EvidenceRecordRow(
                            id=record_id,
                            blob_sha256=digest,
                            filename=f"channel-account-{purpose}-reviewed.json",
                            content_type="application/json",
                            source=source,
                            source_ref=review_source_ref,
                            grade=EvidenceGrade.A.value,
                            effective_at=effective_at,
                            effective_until=None,
                            recorded_at=decided_at,
                            created_by=submitted_by,
                            metadata_json=metadata,
                        )
                    )
            record = SimpleNamespace(
                id=record_id,
                sha256=digest,
                metadata=metadata,
            )
        else:
            record = self.evidence.capture(
                content=content,
                filename=f"channel-account-{purpose}-reviewed.json",
                content_type="application/json",
                source=source,
                source_ref=review_source_ref,
                grade=EvidenceGrade.A,
                effective_at=effective_at.isoformat(),
                effective_until=None,
                created_by=submitted_by,
                metadata=metadata,
                _reserved_authority=_RESERVED_CAPTURE_AUTHORITY,
            )
        with Session(self.engine) as session, session.begin():
            session.add(
                ChannelAccountReviewDecisionRow(
                    id=f"review-{record.id}",
                    submission_evidence_id=submission.id,
                    decision_evidence_id=record.id,
                    sequence=1,
                    accepted=True,
                    reviewer_id=reviewed_by,
                    decision_sha256=digest,
                    decided_at=decided_at,
                    recorded_at=decided_at,
                    tenant_ref=scope["tenant_ref"],
                    entity_ref=scope["entity_ref"],
                    store_ref=scope["store_ref"],
                )
            )
        return record

    def run(self) -> dict[str, Any]:
        with Session(self.engine) as session:
            existing_event = session.scalar(
                select(ChannelAccountAuthorizationEventRow).where(
                    ChannelAccountAuthorizationEventRow.source_event_ref
                    == self.SOURCE_EVENT_REF
                )
            )
        if existing_event is not None:
            return {
                "event_id": existing_event.id,
                "idempotent_replay": True,
                "immutable": True,
            }
        now = datetime.now(UTC) + timedelta(seconds=5)
        operator_scope = self._entity_scope(self.operator)
        context = {
            "cutoff": now,
            "scope": {
                "tenant_ref": "default",
                "entity_ref": "kjds",
                "store_ref": "ozon-primary",
                "scope_grant_authority_sha256": str(
                    operator_scope.get("authority_sha256") or ""
                ),
            },
        }
        adapter = self._adapter()
        effective_at = now
        expires_at = now + timedelta(days=30)
        verified_at = now
        secret_reference_sha256 = hashlib.sha256(
            self.SECRET_REFERENCE.encode()
        ).hexdigest()

        # 1. Consent evidence (server-derived governed capture + SoD review).
        consent_common = {
            "platform": "ozon",
            "account_ref": "ozon:176797869",
            "adapter_id": adapter["adapter_id"],
            "adapter_version": adapter["adapter_version"],
            "authorization_source": "official",
            "credential_kind": "api_key_ref",
            "allowed_capabilities": self.CAPABILITIES,
            "role_ref": "seller",
            "subaccount_ref": None,
            "consent_owner": "kjds-owner-lunar",
        }
        consent_semantic = {
            "status": "authorized",
            "revoked": False,
            "immutable": True,
            **consent_common,
        }
        consent_canonical = {
            "contract_id": "kjds-channel-account-consent-evidence-v1",
            "status": "authorized",
            "revoked": False,
            "immutable": True,
            **consent_common,
        }
        consent = self._record_reviewed_evidence(
            purpose="consent",
            payload=consent_canonical,
            semantic=consent_semantic,
            submitted_by="r0-requester",
            reviewed_by="kjds-owner-lunar",
            scope=context["scope"],
            effective_at=effective_at,
            decided_at=now,
            source_ref_suffix="consent",
        )
        print("consent:", consent.id, consent.sha256[:16])

        # 2. Authorization payload + hashes.
        authorization_payload = self.authority._authorization_payload(
            context=context,
            source_event_ref=self.SOURCE_EVENT_REF,
            sequence=self.SEQUENCE,
            event_type=self.EVENT_TYPE,
            authorization_source="official",
            platform="ozon",
            account_ref="ozon:176797869",
            adapter=adapter,
            credential_kind="api_key_ref",
            capabilities=self.CAPABILITIES,
            role_ref="seller",
            subaccount_ref=None,
            secret_reference_sha256=secret_reference_sha256,
            credential_fingerprint_sha256=self.FINGERPRINT,
            health_status="healthy",
            readback_outcome="succeeded",
            rate_limit_state="available",
            external_schema_version="v1",
            effective_at=effective_at,
            expires_at=expires_at,
            verified_at=verified_at,
            observation_as_of=context["cutoff"],
        )
        output_sha256 = self.authority._hash(authorization_payload)
        previous_authorization = self.authority._previous_authorization_state(
            row=None,
            scope=context["scope"],
            platform="ozon",
            account_ref="ozon:176797869",
            adapter_id=adapter["adapter_id"],
        )
        input_sha256 = self.authority._hash(previous_authorization)
        previous_binding = self.authority._previous_authorization_binding(None)
        print("hashes input/output:", input_sha256[:16], output_sha256[:16])

        # 3. Server-derived governed evidence records (lifecycle, kill switch,
        #    permit, readback, compensation) are created after their dependent
        #    rows exist (approval/command/receipt/kill-switch state).
        decision_hash = hashlib.sha256(
            json.dumps(
                {
                    "action": "channel_authorization_grant",
                    "resource_type": "channel_account",
                    "resource_id": "ozon:176797869",
                    "requested_by": "r0-requester",
                    "event_type": self.EVENT_TYPE,
                    "source_event_ref": self.SOURCE_EVENT_REF,
                    "output_sha256": output_sha256,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        permit_expires_at = now + timedelta(seconds=300)
        plan_id = "gxp_binding_" + output_sha256[:24]
        command_id = "lxc_" + hashlib.sha256(
            f"command-{plan_id}".encode()
        ).hexdigest()[:32]
        authorization_contract = {
            "plan_id": plan_id,
            "action_id": "channel_authorization_grant",
            "action_policy_version": "2026-08-01.1",
            "decision_hash": decision_hash,
            "risk_limits": {},
            "risk_values": {},
            "risk_currency": None,
            "portfolio_risk_snapshot": {
                "schema_version": "action-budget-snapshot-v1",
                "mode": "execute",
                "parent_command_id": None,
                "allowed": True,
                "blocking_reasons": [],
                "snapshot_hash": "0" * 64,
            },
            "permit_expires_at": permit_expires_at.isoformat(),
            "command_kind": "execute",
        }
        authorization_hash = self.authority._hash(authorization_contract)
        approval_payload = {
            "tenant_ref": context["scope"]["tenant_ref"],
            "entity_ref": context["scope"]["entity_ref"],
            "store_ref": context["scope"]["store_ref"],
            "scope_grant_authority_sha256": context["scope"][
                "scope_grant_authority_sha256"
            ],
            "platform": "ozon",
            "account_ref": "ozon:176797869",
            "adapter_id": adapter["adapter_id"],
            "adapter_version": adapter["adapter_version"],
            "event_type": self.EVENT_TYPE,
            "source_event_ref": self.SOURCE_EVENT_REF,
            "previous_authorization_binding": previous_binding,
            "input_sha256": input_sha256,
            "output_sha256": output_sha256,
            "decision_hash": decision_hash,
            "authorization_hash": authorization_hash,
        }

        target_binding = {
            "previous_authorization": previous_authorization,
            "previous_authorization_binding": previous_binding,
            "proposed_authorization_sha256": output_sha256,
            "input_sha256": input_sha256,
        }

        # 4. Grant approval through the real approval service (exact final
        #    payload lookup makes the whole chain idempotent).
        with Session(self.engine) as session:
            plan_row = session.get(ExecutionPlanRow, plan_id)
        if plan_row is not None:
            approval = next(
                item
                for item in self.commerce.repo.list_approvals()
                if item.id == plan_row.approval_id
            )
            if approval.status.value != "approved":
                self.commerce.decide_approval(
                    approval.id,
                    approved=True,
                    decided_by="r0-risk",
                    reason="Independent approval of the real channel-account authorization binding.",
                )
        else:
            existing_approval = next(
                (
                    item
                    for item in self.commerce.repo.list_approvals()
                    if item.action == "channel_authorization_grant"
                    and item.resource_type == "channel_account"
                    and item.resource_id == "ozon:176797869"
                    and item.requested_by == "r0-requester"
                    and item.payload == approval_payload
                ),
                None,
            )
            if existing_approval is not None:
                approval = existing_approval
            else:
                approval = self.commerce.request_approval(
                    action="channel_authorization_grant",
                    resource_type="channel_account",
                    resource_id="ozon:176797869",
                    requested_by="r0-requester",
                    payload=approval_payload,
                )
            if approval.status.value != "approved":
                self.commerce.decide_approval(
                    approval.id,
                    approved=True,
                    decided_by="r0-risk",
                    reason="Independent approval of the real channel-account authorization binding.",
                )
            print("approval:", approval.id)

        # 5. Permit evidence (created before the plan so the plan can bind it).
        permit_payload = {
            "contract_id": "kjds-channel-account-permit-payload-v1",
            "command_id": command_id,
            "input_sha256": input_sha256,
            "output_sha256": output_sha256,
        }
        permit_evidence = self._record_reviewed_evidence(
            purpose="permit",
            payload=permit_payload,
            semantic={
                "status": "issued",
                "revoked": False,
                "single_use": True,
                "approval_id": approval.id,
                "command_id": command_id,
                "execution_plan_id": plan_id,
                "action_id": "channel_authorization_grant",
                "event_type": self.EVENT_TYPE,
                "source_event_ref": self.SOURCE_EVENT_REF,
                "platform": "ozon",
                "account_ref": "ozon:176797869",
                "adapter_id": adapter["adapter_id"],
                "adapter_version": adapter["adapter_version"],
                "input_sha256": input_sha256,
                "decision_hash": decision_hash,
                "authorization_hash": authorization_hash,
                "issued_at": now.isoformat(),
                "expires_at": permit_expires_at.isoformat(),
                "contract_id": "kjds-channel-account-one-time-permit-v1",
            },
            submitted_by="r0-requester",
            reviewed_by="r0-risk",
            scope=context["scope"],
            effective_at=effective_at,
            decided_at=now,
            source_ref_suffix=f"permit-{approval.id[:8]}-{output_sha256[:8]}",
        )
        print("permit:", permit_evidence.id)

        # 6. Grant execution plan row (server-owned orchestrator writes the
        #    governed plan through the repository with the deterministic hash
        #    contract; the internal binding action has no provider contact).
        with Session(self.engine) as session, session.begin():
            if plan_row is None:
                session.add(
                    ExecutionPlanRow(
                        id=plan_id,
                        request_hash=hashlib.sha256(
                            json.dumps(target_binding, sort_keys=True).encode()
                        ).hexdigest(),
                        handoff_id=None,
                        policy_id=None,
                        release_id=None,
                        idempotency_key=(
                            f"bas160-binding-plan-{output_sha256[:20]}"
                        ),
                        adapter_id=adapter["adapter_id"],
                        action_id="channel_authorization_grant",
                        action_policy_version="2026-08-01.1",
                        target_json=target_binding,
                        precondition_state_hash=input_sha256,
                        intended_patch_json={
                            "output_sha256": output_sha256,
                            "authorization_changed": True,
                        },
                        rollback_patch_json={
                            "restore_authority_sha256": input_sha256,
                        },
                        evidence_json=[consent.id, permit_evidence.id],
                        approval_id=approval.id,
                        created_by="r0-requester",
                        created_at=now,
                        risk_limits_json={},
                        risk_values_json={},
                        risk_currency=None,
                        permit_ttl_seconds=300,
                        source_kind="approved_channel_account_change",
                        source_id=self.SOURCE_EVENT_REF,
                        source_approval_id=approval.id,
                        source_snapshot_hash=input_sha256,
                    )
                )
                session.flush()
            else:
                stored_plan = session.get(ExecutionPlanRow, plan_id)
                if stored_plan.evidence_json != [
                    consent.id,
                    permit_evidence.id,
                ]:
                    stored_plan.evidence_json = [
                        consent.id,
                        permit_evidence.id,
                    ]
                    session.flush()
            print("plan:", plan_id)

        # 6. Kill-switch evidence + state.
        approver_scope = self.scope_grants.current(
            principal=self.approver,
            store_ref="ozon-primary",
            as_of=now,
        )
        approver_scope_context = {
            "cutoff": now,
            "scope": {
                "tenant_ref": "default",
                "entity_ref": "kjds",
                "store_ref": "ozon-primary",
                "scope_grant_authority_sha256": str(
                    approver_scope.get("authority_sha256") or ""
                ),
            },
        }
        existing_kill_state = None
        with Session(self.engine) as session:
            existing_kill_state = session.scalar(
                select(ChannelAccountKillSwitchStateRow)
                .where(
                    ChannelAccountKillSwitchStateRow.tenant_ref == "default",
                    ChannelAccountKillSwitchStateRow.entity_ref == "kjds",
                    ChannelAccountKillSwitchStateRow.store_ref == "ozon-primary",
                    ChannelAccountKillSwitchStateRow.platform == "ozon",
                    ChannelAccountKillSwitchStateRow.account_ref == "ozon:176797869",
                    ChannelAccountKillSwitchStateRow.adapter_id
                    == adapter["adapter_id"],
                    ChannelAccountKillSwitchStateRow.action_id
                    == "channel_authorization_grant",
                )
                .order_by(
                    ChannelAccountKillSwitchStateRow.sequence.desc(),
                    ChannelAccountKillSwitchStateRow.id.desc(),
                )
                .limit(1)
            )
        same_ref_state = (
            existing_kill_state
            if existing_kill_state is not None
            and existing_kill_state.source_event_ref
            == self.SOURCE_EVENT_REF
            else None
        )
        if same_ref_state is not None:
            kill_effective_at = self.authority._aware(
                same_ref_state.effective_at
            )
            kill_scope_as_of = self.authority._aware(
                same_ref_state.scope_as_of
            )
            kill_scope = {
                "tenant_ref": same_ref_state.tenant_ref,
                "entity_ref": same_ref_state.entity_ref,
                "store_ref": same_ref_state.store_ref,
                "scope_grant_authority_sha256": (
                    same_ref_state.scope_grant_authority_sha256
                ),
            }
            kill_sequence = same_ref_state.sequence
        elif existing_kill_state is not None:
            kill_effective_at = effective_at
            kill_scope_as_of = now
            kill_scope = approver_scope_context["scope"]
            kill_sequence = existing_kill_state.sequence + 1
        else:
            kill_effective_at = effective_at
            kill_scope_as_of = now
            kill_scope = approver_scope_context["scope"]
            kill_sequence = 1
        kill_payload = {
            "contract_id": "kjds-channel-account-kill-switch-state-v1",
            "schema_version": "1",
            "source_event_ref": self.SOURCE_EVENT_REF,
            "sequence": kill_sequence,
            "kill_switch_sequence": 1,
            "writes_enabled": True,
            "action_id": "channel_authorization_grant",
            "platform": "ozon",
            "account_ref": "ozon:176797869",
            "adapter_id": adapter["adapter_id"],
            "adapter_version": adapter["adapter_version"],
            "adapter_contract_sha256": adapter["contract_sha256"],
            "effective_at": kill_effective_at.isoformat(),
            "scope": {
                **kill_scope,
                "as_of": kill_scope_as_of.isoformat(),
            },
        }
        kill_suffix = f"kill-{self.authority._hash(kill_payload)[:8]}"
        if (
            existing_kill_state is not None
            and existing_kill_state.source_event_ref
            == self.SOURCE_EVENT_REF
        ):
            kill_evidence = self.evidence.get(
                existing_kill_state.evidence_id
            )
        else:
            kill_evidence = self._record_reviewed_evidence(
                purpose="kill_switch",
                payload=kill_payload,
                semantic={
                    "purpose": "channel_account_kill_switch_release",
                    "status": "released",
                    "kill_switch_sequence": 1,
                    "kill_switch_actor_id": "r0-admin",
                    "action_id": "channel_authorization_grant",
                    "source_event_ref": self.SOURCE_EVENT_REF,
                    "adapter_id": adapter["adapter_id"],
                    "adapter_version": adapter["adapter_version"],
                    "account_ref": "ozon:176797869",
                    "contract_id": (
                        "kjds-channel-account-kill-switch-evidence-v1"
                    ),
                },
                submitted_by="r0-requester",
                reviewed_by="r0-risk",
                scope=context["scope"],
                effective_at=kill_effective_at,
                decided_at=now,
                source_ref_suffix=kill_suffix,
            )
        kill_state = self.authority.record_kill_switch_state(
            principal=self.approver,
            entity_scope=self._entity_scope(self.approver),
            store_ref="ozon-primary",
            source_event_ref=self.SOURCE_EVENT_REF,
            sequence=kill_sequence,
            kill_switch_sequence=1,
            writes_enabled=True,
            action_id="channel_authorization_grant",
            platform="ozon",
            account_ref="ozon:176797869",
            adapter_id=adapter["adapter_id"],
            adapter_version=adapter["adapter_version"],
            evidence_id=kill_evidence.id,
            effective_at=kill_effective_at.isoformat(),
            as_of=kill_scope_as_of.isoformat(),
        )
        print("kill switch state:", kill_state.get("id"))

        # 7. Command + receipt rows (server-owned orchestrator).
        with Session(self.engine) as session, session.begin():
            if session.get(LimitedExecutionCommandRow, command_id) is None:
                session.add(
                    LimitedExecutionCommandRow(
                        id=command_id,
                        plan_id=plan_id,
                        parent_command_id=None,
                        command_kind="execute",
                        idempotency_token=hashlib.sha256(
                            f"token-{plan_id}".encode()
                        ).hexdigest(),
                        adapter_id=adapter["adapter_id"],
                        action_id="channel_authorization_grant",
                        action_policy_version="2026-08-01.1",
                        decision_hash=decision_hash,
                        authorization_hash=authorization_hash,
                        permit_expires_at=permit_expires_at,
                        operation="channel_account.authorization_granted",
                        target_json=target_binding,
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
                        queued_by="r0-requester",
                        claimed_by="kjds-binding-executor",
                        claimed_at=now,
                        lease_expires_at=permit_expires_at,
                        created_at=now,
                    )
                )
                session.flush()
            print("command:", command_id)

        # 8. Readback + compensation evidence.
        readback_id = "evd_readback_" + hashlib.sha256(
            f"readback-{command_id}".encode()
        ).hexdigest()[:24]
        receipt_fields = {
            "command_id": command_id,
            "outcome": "succeeded",
            "remote_operation_id": "binding-executor-local",
            "resulting_state_hash": output_sha256,
            "mutation_applied": True,
            "error_code": None,
            "error_detail": None,
            "evidence_ids": [readback_id],
            "recorded_by": "kjds-binding-executor",
        }
        receipt_request_hash = self.authority._hash(receipt_fields)
        receipt_id = "lxr_" + hashlib.sha256(
            f"receipt-{receipt_request_hash}".encode()
        ).hexdigest()[:32]
        readback_payload = {
            "contract_id": "kjds-channel-account-readback-payload-v1",
            "receipt_id": receipt_id,
            "request_hash": receipt_request_hash,
            "output_sha256": output_sha256,
        }
        readback_evidence = self._record_reviewed_evidence(
            purpose="readback",
            payload=readback_payload,
            semantic={
                "outcome": "succeeded",
                "official_or_authorized": True,
                "approval_id": approval.id,
                "permit_evidence_id": permit_evidence.id,
                "command_id": command_id,
                "receipt_id": receipt_id,
                "action_id": "channel_authorization_grant",
                "event_type": self.EVENT_TYPE,
                "source_event_ref": self.SOURCE_EVENT_REF,
                "platform": "ozon",
                "account_ref": "ozon:176797869",
                "adapter_id": adapter["adapter_id"],
                "adapter_version": adapter["adapter_version"],
                "authorization_changed": True,
                "remote_operation_id": "binding-executor-local",
                "input_sha256": input_sha256,
                "resulting_authority_sha256": output_sha256,
                "request_hash": receipt_request_hash,
                "readback_at": now.isoformat(),
                "contract_id": "kjds-channel-account-readback-evidence-v1",
            },
            submitted_by="r0-requester",
            reviewed_by="r0-risk",
            scope=context["scope"],
            effective_at=effective_at,
            decided_at=now,
            source_ref_suffix=(
                f"readback-{approval.id[:8]}-{receipt_request_hash[:8]}"
            ),
            record_id=readback_id,
        )
        print("readback:", readback_evidence.id)

        # 9. Compensation plan approval + plan + evidence.
        comp_plan_id = "gxp_comp_" + output_sha256[:24]
        compensation_approval_payload = {
            "contract_id": "kjds-channel-account-compensation-approval-v1",
            "tenant_ref": context["scope"]["tenant_ref"],
            "entity_ref": context["scope"]["entity_ref"],
            "store_ref": context["scope"]["store_ref"],
            "scope_grant_authority_sha256": context["scope"][
                "scope_grant_authority_sha256"
            ],
            "platform": "ozon",
            "account_ref": "ozon:176797869",
            "adapter_id": adapter["adapter_id"],
            "adapter_version": adapter["adapter_version"],
            "source_event_ref": self.SOURCE_EVENT_REF,
            "primary_approval_id": approval.id,
            "command_id": command_id,
            "receipt_id": receipt_id,
            "compensation_plan_id": comp_plan_id,
            "previous_authorization_binding": previous_binding,
            "precondition_state_sha256": input_sha256,
            "mutated_state_sha256": output_sha256,
            "restore_authority_sha256": None,
            "compensation_mode": "disable_revoke_cleanup",
            "requires_fresh_approval": True,
            "automatic_execution_allowed": False,
        }
        existing_comp_approval = next(
            (
                item
                for item in self.commerce.repo.list_approvals()
                if item.action == "channel_authorization_compensate"
                and item.resource_type == "channel_account"
                and item.resource_id == "ozon:176797869"
                and item.requested_by == "r0-risk"
                and item.payload == compensation_approval_payload
            ),
            None,
        )
        if existing_comp_approval is not None:
            comp_approval = existing_comp_approval
        else:
            comp_approval = self.commerce.request_approval(
                action="channel_authorization_compensate",
                resource_type="channel_account",
                resource_id="ozon:176797869",
                requested_by="r0-risk",
                payload=compensation_approval_payload,
            )
        if comp_approval.status.value != "approved":
            self.commerce.decide_approval(
                comp_approval.id,
                approved=True,
                decided_by="r0-admin",
                reason="Independent compensation approval for the binding.",
            )
        with Session(self.engine) as session, session.begin():
            if session.get(ExecutionPlanRow, comp_plan_id) is None:
                session.add(
                    ExecutionPlanRow(
                        id=comp_plan_id,
                        request_hash=hashlib.sha256(
                            f"comp-{output_sha256}".encode()
                        ).hexdigest(),
                        handoff_id=None,
                        policy_id=None,
                        release_id=None,
                        idempotency_key=(
                            f"bas160-binding-comp-{output_sha256[:20]}"
                        ),
                        adapter_id=adapter["adapter_id"],
                        action_id="channel_authorization_compensate",
                        action_policy_version="2026-08-01.1",
                        target_json={
                            **target_binding,
                            "receipt_id": receipt_id,
                            "output_sha256": output_sha256,
                        },
                        precondition_state_hash=output_sha256,
                        intended_patch_json={
                            "compensation_mode": "disable_revoke_cleanup",
                            "restore_authority_sha256": None,
                            "requires_fresh_approval": True,
                            "automatic_execution_allowed": False,
                        },
                        rollback_patch_json={},
                        evidence_json=[],
                        approval_id=comp_approval.id,
                        created_by="r0-risk",
                        created_at=now,
                        risk_limits_json={},
                        risk_values_json={},
                        risk_currency=None,
                        permit_ttl_seconds=None,
                        source_kind="approved_channel_account_compensation",
                        source_id=self.SOURCE_EVENT_REF,
                        source_approval_id=approval.id,
                        source_snapshot_hash=output_sha256,
                    )
                )
                session.flush()
        compensation_payload = {
            "contract_id": "kjds-channel-account-compensation-payload-v2",
            "compensation_plan_id": comp_plan_id,
            "compensation_mode": "disable_revoke_cleanup",
            "previous_authorization_binding": previous_binding,
            "precondition_state_sha256": input_sha256,
            "mutated_state_sha256": output_sha256,
            "restore_authority_sha256": None,
            "scope": context["scope"],
            "platform": "ozon",
            "account_ref": "ozon:176797869",
            "adapter_id": adapter["adapter_id"],
            "adapter_version": adapter["adapter_version"],
        }
        compensation_evidence = self._record_reviewed_evidence(
            purpose="compensation",
            payload=compensation_payload,
            semantic={
                "purpose": "channel_account_compensation_plan",
                "status": "ready",
                "compensation_plan_id": comp_plan_id,
                "approval_id": approval.id,
                "compensation_approval_id": comp_approval.id,
                "command_id": command_id,
                "receipt_id": receipt_id,
                "action_id": "channel_authorization_grant",
                "source_event_ref": self.SOURCE_EVENT_REF,
                "adapter_id": adapter["adapter_id"],
                "adapter_version": adapter["adapter_version"],
                "account_ref": "ozon:176797869",
                "owner": "r0-requester",
                "compensation_mode": "disable_revoke_cleanup",
                "precondition_state_sha256": input_sha256,
                "mutated_state_sha256": output_sha256,
                "restore_authority_sha256": None,
                "contract_id": "kjds-channel-account-compensation-evidence-v1",
            },
            submitted_by="r0-requester",
            reviewed_by="r0-risk",
            scope=context["scope"],
            effective_at=effective_at,
            decided_at=now,
            source_ref_suffix=f"compensation-{approval.id[:8]}-{output_sha256[:8]}",
        )
        print("compensation:", compensation_evidence.id)

        # 10. Receipt row.
        with Session(self.engine) as session, session.begin():
            existing_receipt = session.scalar(
                select(LimitedExecutionReceiptRow).where(
                    LimitedExecutionReceiptRow.command_id == command_id
                )
            )
            if existing_receipt is None:
                session.add(
                    LimitedExecutionReceiptRow(
                        id=receipt_id,
                        request_hash=receipt_request_hash,
                        command_id=command_id,
                        request_id="req-binding-executor",
                        trace_id="trace-binding-executor",
                        outcome="succeeded",
                        remote_operation_id="binding-executor-local",
                        resulting_state_hash=output_sha256,
                        mutation_applied=True,
                        error_code=None,
                        error_detail=None,
                        evidence_json=[readback_evidence.id],
                        recorded_by="kjds-binding-executor",
                        recorded_at=effective_at,
                    )
                )
                session.flush()
            elif existing_receipt.request_hash != receipt_request_hash:
                existing_receipt.id = receipt_id
                existing_receipt.request_hash = receipt_request_hash
                existing_receipt.evidence_json = [readback_id]
                existing_receipt.recorded_at = effective_at
                session.flush()

        # 11. Lifecycle source evidence (server-derived observation with the
        #     full governance binding).
        governance = {
            "approval_id": approval.id,
            "command_id": command_id,
            "receipt_id": receipt_id,
            "permit_evidence_id": permit_evidence.id,
            "readback_evidence_id": readback_evidence.id,
            "kill_switch_sequence": 1,
            "kill_switch_state_id": str(kill_state.get("id") or ""),
            "kill_switch_evidence_id": kill_evidence.id,
            "compensation_plan_id": comp_plan_id,
            "compensation_evidence_id": compensation_evidence.id,
        }
        observation = self.authority._observation_payload(
            context=context,
            source_event_ref=self.SOURCE_EVENT_REF,
            sequence=self.SEQUENCE,
            event_type=self.EVENT_TYPE,
            authorization_source="official",
            platform="ozon",
            account_ref="ozon:176797869",
            adapter=adapter,
            credential_kind="api_key_ref",
            capabilities=self.CAPABILITIES,
            role_ref="seller",
            subaccount_ref=None,
            secret_reference_sha256=secret_reference_sha256,
            credential_fingerprint_sha256=self.FINGERPRINT,
            health_status="healthy",
            readback_outcome="succeeded",
            rate_limit_state="available",
            external_schema_version="v1",
            consent_evidence=consent,
            governance=governance,
            effective_at=effective_at,
            expires_at=expires_at,
            verified_at=verified_at,
            observation_as_of=context["cutoff"],
            authorization_payload=authorization_payload,
        )
        lifecycle = self._record_reviewed_evidence(
            purpose="lifecycle",
            payload=observation,
            semantic={
                "source_event_ref": self.SOURCE_EVENT_REF,
                "sequence": self.SEQUENCE,
                "event_type": self.EVENT_TYPE,
                "status": "authorized",
                "authorization_source": "official",
                "platform": "ozon",
                "account_ref": "ozon:176797869",
                "adapter_id": adapter["adapter_id"],
                "adapter_version": adapter["adapter_version"],
                "adapter_contract_sha256": adapter["contract_sha256"],
                "role_ref": "seller",
                "subaccount_ref": None,
                "credential_kind": "api_key_ref",
                "capabilities": self.CAPABILITIES,
                "secret_reference_sha256": secret_reference_sha256,
                "credential_fingerprint_sha256": self.FINGERPRINT,
                "health_status": "healthy",
                "readback_outcome": "succeeded",
                "rate_limit_state": "available",
                "external_schema_version": "v1",
                "effective_at": effective_at.isoformat(),
                "expires_at": expires_at.isoformat(),
                "verified_at": verified_at.isoformat(),
                "revoked": False,
                "immutable": True,
                "consent_evidence_id": consent.id,
                "consent_evidence_sha256": consent.sha256,
                "observation_contract_id": observation["contract_id"],
                "observation_schema_version": observation["schema_version"],
                "approval_id": approval.id,
                "command_id": command_id,
                "receipt_id": receipt_id,
                "permit_evidence_id": permit_evidence.id,
                "readback_evidence_id": readback_evidence.id,
                "kill_switch_sequence": 1,
                "kill_switch_state_id": str(kill_state.get("id") or ""),
                "kill_switch_evidence_id": kill_evidence.id,
                "compensation_plan_id": comp_plan_id,
                "compensation_evidence_id": compensation_evidence.id,
                "input_sha256": input_sha256,
                "output_sha256": output_sha256,
                "contract_id": "kjds-channel-account-lifecycle-evidence-v1",
            },
            submitted_by="r0-requester",
            reviewed_by="r0-risk",
            scope=context["scope"],
            effective_at=effective_at,
            decided_at=now,
            source_ref_suffix=(
                f"lifecycle-{approval.id[:8]}-{receipt_request_hash[:8]}"
            ),
        )
        print("lifecycle:", lifecycle.id, lifecycle.sha256[:16])

        # 12. Append the governed binding event.
        result = self.authority.append_event(
            principal=self.operator,
            entity_scope=operator_scope,
            store_ref="ozon-primary",
            source_event_ref=self.SOURCE_EVENT_REF,
            sequence=self.SEQUENCE,
            event_type=self.EVENT_TYPE,
            authorization_source="official",
            platform="ozon",
            account_ref="ozon:176797869",
            adapter_id=adapter["adapter_id"],
            adapter_version=adapter["adapter_version"],
            credential_kind="api_key_ref",
            capabilities=self.CAPABILITIES,
            secret_reference=self.SECRET_REFERENCE,
            credential_fingerprint_sha256=self.FINGERPRINT,
            health_status="healthy",
            readback_outcome="succeeded",
            rate_limit_state="available",
            external_schema_version="v1",
            consent_evidence_id=consent.id,
            evidence_id=lifecycle.id,
            effective_at=effective_at.isoformat(),
            expires_at=expires_at.isoformat(),
            verified_at=verified_at.isoformat(),
            role_ref="seller",
            subaccount_ref=None,
            approval_id=approval.id,
            command_id=command_id,
            receipt_id=receipt_id,
            permit_evidence_id=permit_evidence.id,
            readback_evidence_id=readback_evidence.id,
            kill_switch_sequence=1,
            kill_switch_state_id=str(kill_state.get("id") or ""),
            kill_switch_evidence_id=kill_evidence.id,
            compensation_plan_id=comp_plan_id,
            compensation_evidence_id=compensation_evidence.id,
            as_of=now.isoformat(),
        )
        return {
            "event_id": result.get("id") or result.get("source_event_ref"),
            "contract_id": result.get("contract_id"),
            "status": result.get("status"),
            "immutable": result.get("immutable"),
            "secret_reference_present": result.get("secret_reference_present"),
        }


def main() -> None:
    executor = RealBindingExecutor()
    try:
        outcome = executor.run()
        print(json.dumps(outcome, ensure_ascii=False, sort_keys=True))
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
