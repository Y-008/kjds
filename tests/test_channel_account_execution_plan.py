from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from apps.control_plane.causal_policies import CausalPolicyRow  # noqa: F401
from apps.control_plane.evidence import EvidenceGrade, EvidenceService
from apps.control_plane.execution_plans import ExecutionPlanService
from apps.control_plane.policy_shadow import PolicyActivationHandoffRow  # noqa: F401
from apps.control_plane.repository import InMemoryRepository
from apps.control_plane.services import CommerceService
from apps.control_plane.sql_repository import Base


class NoCausalSource:
    def get_handoff(self, _value):
        raise AssertionError("channel-account plan must not resolve a causal handoff")


def test_approved_channel_account_plan_is_created_without_direct_row_insertion():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    evidence = EvidenceService(engine)
    repo = InMemoryRepository()
    commerce = CommerceService(repo, evidence_validator=evidence.require_valid)
    reviewed = evidence.capture(
        content=b'{"status":"authorized"}',
        filename="reviewed.json",
        content_type="application/json",
        source="test-reviewed-channel-account",
        source_ref="reviewed://channel-account/1",
        grade=EvidenceGrade.A,
        effective_at=datetime(2026, 8, 1, tzinfo=UTC).isoformat(),
        effective_until=None,
        created_by="evidence-submitter",
        metadata={},
    )
    scope = {
        "tenant_ref": "tenant-a",
        "entity_ref": "entity-a",
        "store_ref": "ozon-primary",
        "scope_grant_authority_sha256": "a" * 64,
    }
    target = {
        "platform": "ozon",
        "account_ref": "account-a",
        "adapter_id": "ozon-seller-api",
    }
    intended = {
        "reviewed_evidence_id": reviewed.id,
        "change_kind": "grant_read_capability",
        "requested_capabilities": ["catalog.read"],
    }
    rollback = {
        "reviewed_evidence_id": reviewed.id,
        "change_kind": "restore_previous_authority",
        "requested_capabilities": [],
    }
    source_basis = {
        "contract_id": "kjds-channel-account-change-approval-v1",
        "scope": scope,
        "reviewed_evidence_id": reviewed.id,
        "reviewed_evidence_sha256": reviewed.sha256,
        "reviewed_by": "evidence-reviewer",
        "target": target,
        "intended_patch": intended,
        "rollback_patch": rollback,
    }
    source_hash = ExecutionPlanService._hash(source_basis)
    approval = commerce.request_approval(
        action="channel_account.change",
        resource_type="channel_account_change",
        resource_id=f"cach_{source_hash[:32]}",
        requested_by="change-requester",
        payload={**source_basis, "source_snapshot_hash": source_hash},
    )
    commerce.decide_approval(
        approval.id,
        approved=True,
        decided_by="independent-approver",
        reason="Exact reviewed change approved for internal planning only",
    )
    plans = ExecutionPlanService(
        engine=engine,
        policy_shadow=NoCausalSource(),
        policies=None,
        evidence=evidence,
        commerce=commerce,
        readiness_provider=lambda _context: {},
    )

    plan = plans.create_from_approved_channel_account(
        approval.id,
        idempotency_key="channel-plan-1",
        created_by="plan-operator",
    )
    replay = plans.create_from_approved_channel_account(
        approval.id,
        idempotency_key="channel-plan-1",
        created_by="plan-operator",
    )

    assert replay["id"] == plan["id"]
    assert plan["source_kind"] == "approved_channel_account_change"
    assert plan["source_approval_id"] == approval.id
    assert plan["adapter_id"] == "kjds.channel-account.change.v1"
    assert plan["action_id"] == "channel_authorization_change"
    assert plan["source_validity_status"] == "active"
    assert plan["live_execution_supported"] is False
    assert plan["execution_eligible"] is False
    assert plan["automatic_execution"] is False
