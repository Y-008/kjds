from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane import (
    causal_policies as _causal_policies,
)
from apps.control_plane import policy_shadow as _policy_shadow
from apps.control_plane.domain import Approval, ApprovalStatus
from apps.control_plane.evidence import (
    EvidenceGrade,
    EvidenceRecord,
)
from apps.control_plane.execution_plans import (
    ExecutionDryRunRow,
    ExecutionPlanRow,
    ExecutionPlanService,
)
from apps.control_plane.scoped_listing_lifecycle import (
    ScopedListingLifecycleWorkspace,
)
from apps.control_plane.security import Principal
from apps.control_plane.sourcing import (
    ListingDraft,
    listing_snapshot_sha256,
)
from apps.control_plane.sql_repository import (
    Base,
    SqlAlchemyRepository,
)

AT = datetime(2026, 7, 29, 8, tzinfo=UTC)
SCOPE = {
    "status": "ready",
    "entity_ref": "entity-a",
    "authority_sha256": "a" * 64,
}
SCOPE_VALUE = {
    "tenant_ref": "tenant-a",
    "entity_ref": "entity-a",
    "store_ref": "ozon-primary",
    "scope_grant_authority_sha256": "a" * 64,
}


def database():
    assert (
        _causal_policies.CausalPolicyRow.__table__.metadata
        is Base.metadata
    )
    assert (
        _policy_shadow.PolicyActivationHandoffRow.__table__.metadata
        is Base.metadata
    )
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def principal(stores=frozenset({"ozon-primary"})):
    return Principal(
        actor_id="operator",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-a",
        store_refs=stores,
    )


class Pim:
    def __init__(self, *, groups=None, status="ready"):
        self.calls = 0
        self.groups = groups if groups is not None else [pim_group()]
        self.status = status
        self.next_cursor = None

    def project(self, **_kwargs):
        self.calls += 1
        return {
            "contract_id": (
                "kjds-native-exact-scope-pim-workspace-v1"
            ),
            "status": self.status,
            "as_of": AT.isoformat(),
            "scope": SCOPE_VALUE,
            "query": {"next_cursor": self.next_cursor},
            "product_groups": self.groups,
            "source_gaps": (
                ["pim_no_data"] if self.status == "no_data" else []
            ),
            "blockers": [],
            "snapshot_sha256": "p" * 64,
        }


class ListingStore:
    def __init__(self, drafts=None):
        self.calls = 0
        self.drafts = drafts or []

    def list_listing_drafts_scoped(self, **_kwargs):
        self.calls += 1
        return list(self.drafts)


class ScopedEvidence:
    def __init__(self):
        self.calls = 0
        self.invalid = False

    def project_targets(self, *, evidence_ids, **_kwargs):
        self.calls += 1
        return {
            "status": "blocked" if self.invalid else "ready",
            "invalid_evidence_ids": (
                list(evidence_ids) if self.invalid else []
            ),
            "records": [
                {
                    "evidence_id": item,
                    "scope_binding": {
                        "status": (
                            "blocked"
                            if self.invalid
                            else "ready"
                        )
                    },
                }
                for item in evidence_ids
            ],
            "binding_authority_sha256": "e" * 64,
        }


class Evidence:
    def __init__(self):
        self.by_target = {}
        self.records = {}
        self.bad_ids = set()

    def target_evidence_ids(
        self, *, target_type, target_id, relationship
    ):
        assert target_type == "listing_draft"
        assert relationship == "listing_russian_native_review"
        return list(self.by_target.get(target_id, []))

    def get(self, evidence_id):
        return self.records[evidence_id]

    def require_current(self, evidence_ids, *, as_of):
        assert as_of == AT
        if set(evidence_ids).intersection(self.bad_ids):
            raise ValueError("bad Evidence")


class Approvals:
    def __init__(self):
        self.calls = 0
        self.values = {}

    def get_approval_at(self, approval_id, *, as_of):
        self.calls += 1
        assert as_of == AT
        return self.values[approval_id]


class Plans:
    def __init__(self):
        self.calls = 0
        self.values = []

    def list_for_listing_drafts(self, *, draft_ids, as_of):
        self.calls += 1
        assert as_of == AT
        assert len(draft_ids) == len(set(draft_ids))
        return list(self.values)


def pim_group():
    return {
        "product": {
            "id": "product-1",
            "sku": "SKU-1",
            "name": "Product one",
        },
        "listings": [
            {
                "offer_id": "offer-1",
                "marketplace_sku": "market-1",
                "listing_status": "active",
                "item_hash": "i" * 64,
                "source_evidence_id": "catalog-evidence",
                "observed_fields": {
                    "title": "Observed title",
                    "description": None,
                    "category_id": None,
                    "attributes": [{"id": 1, "value": "old"}],
                    "images": ["asset://one"],
                },
            }
        ],
        "snapshot_sha256": "g" * 64,
    }


def draft(
    *,
    draft_id="draft-1",
    created_at=AT - timedelta(hours=1),
    approval_id=None,
    title="Observed title",
):
    return ListingDraft(
        product_id="product-1",
        offer_id="offer-1",
        scenario_id="scenario-1",
        target_platform="OZON",
        listing_data={
            "title": title,
            "description": "Desired description",
            "category_id": "category-1",
            "attributes": [{"id": 1, "value": "new"}],
            "images": ["asset://one"],
            "content_asset_ids": ["asset-1"],
        },
        requested_by="operator",
        approval_id=approval_id,
        id=draft_id,
        created_at=created_at.isoformat(),
        tenant_ref="tenant-a",
        entity_ref="entity-a",
        store_ref="ozon-primary",
        scope_grant_authority_sha256="a" * 64,
        scoped_product_content_sha256="g" * 64,
        approval_plan_sha256="d" * 64,
        evidence_ids=["evidence-1"],
        scope_as_of=(AT - timedelta(hours=2)).isoformat(),
    )


def workspace(*, drafts=None):
    pim = Pim()
    store = ListingStore(drafts=drafts)
    scoped = ScopedEvidence()
    evidence = Evidence()
    approvals = Approvals()
    plans = Plans()
    service = ScopedListingLifecycleWorkspace(
        pim=pim,
        listing_store=store,
        scoped_evidence=scoped,
        evidence=evidence,
        approval_repository=approvals,
        execution_plans=plans,
    )
    return service, pim, store, scoped, evidence, approvals, plans


def project(service, **kwargs):
    return service.project(
        principal=principal(),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=AT,
        **kwargs,
    )


def test_missing_entity_performs_zero_upstream_reads():
    service, pim, store, scoped, _evidence, approvals, plans = workspace(
        drafts=[draft()]
    )
    result = service.project(
        principal=principal(),
        entity_scope={
            "status": "no_data",
            "reason": "entity_scope_authority_missing",
        },
        store_ref="ozon-primary",
        as_of=AT,
    )
    assert result["status"] == "no_data"
    assert result["control_envelope"]["scoped_input_read"] is False
    assert (
        pim.calls
        == store.calls
        == scoped.calls
        == approvals.calls
        == plans.calls
        == 0
    )


def test_projects_server_owned_diff_and_no_write_agent_boundary():
    service, *_ = workspace(drafts=[draft()])
    result = project(service)
    item = result["items"][0]
    states = {
        value["field"]: value["state"]
        for value in item["field_diffs"]
    }
    assert states == {
        "title": "same",
        "description": "source_missing",
        "category_id": "source_missing",
        "attributes": "changed",
        "images": "same",
    }
    assert item["lifecycle"]["stage"] == "draft_pending_review"
    assert item["readback"]["status"] == "not_available"
    assert result["control_envelope"]["client_recalculation_allowed"] is False
    assert result["agent_artifact"]["self_approval_allowed"] is False
    assert result["agent_artifact"]["permit_issue_allowed"] is False
    assert result["agent_artifact"]["publish_allowed"] is False
    assert result["control_envelope"]["external_write_allowed"] is False


def test_diff_contract_distinguishes_desired_missing():
    values = ScopedListingLifecycleWorkspace._diff(
        observed={
            "fields": {
                "title": "x",
                "description": "source only",
                "category_id": None,
                "attributes": [],
                "images": [],
            }
        },
        desired={
            "title": "x",
            "description": None,
            "category_id": "2",
            "attributes": [{"id": 1}],
            "images": [],
        },
    )
    assert {
        item["state"] for item in values
    } == {
        "same",
        "desired_missing",
        "source_missing",
        "changed",
    }


def test_latest_draft_wins_and_pagination_hash_is_deterministic():
    old = draft(
        draft_id="draft-old",
        created_at=AT - timedelta(hours=3),
    )
    latest = draft(
        draft_id="draft-new",
        created_at=AT - timedelta(hours=1),
    )
    service, *_ = workspace(drafts=[old, latest])
    first = project(service, page_size=1, query="sku-1")
    second = project(service, page_size=1, query="sku-1")
    assert first["items"][0]["identity"]["draft_id"] == "draft-new"
    assert first["counts"]["superseded"] == 1
    assert first["snapshot_sha256"] == second["snapshot_sha256"]
    with pytest.raises(ValueError, match="cursor"):
        project(service, cursor="bad-cursor")


def test_bad_scoped_evidence_fails_closed_and_withholds_payload():
    service, _pim, _store, scoped, *_ = workspace(
        drafts=[draft()]
    )
    scoped.invalid = True
    result = project(service)
    item = result["items"][0]
    assert item["lifecycle"]["stage"] == "blocked"
    assert item["observed_platform_listing"] is None
    assert item["desired_listing_draft"] is None
    assert item["field_diffs"] == []
    assert "listing_evidence_authority_invalid" in item["source_gaps"]


def test_bad_latest_review_fails_closed_instead_of_reusing_old_acceptance():
    current = draft()
    service, _pim, _store, _scoped, evidence, *_ = workspace(
        drafts=[current]
    )
    old = review_record(
        current,
        evidence_id="review-old",
        decision="accepted",
        effective_at=AT - timedelta(minutes=30),
    )
    latest = review_record(
        current,
        evidence_id="review-latest",
        decision="accepted",
        effective_at=AT - timedelta(minutes=10),
    )
    evidence.by_target[current.id] = [old.id, latest.id]
    evidence.records = {old.id: old, latest.id: latest}
    evidence.bad_ids.add(latest.id)
    result = project(service)
    item = result["items"][0]
    assert item["lifecycle"]["stage"] == "blocked"
    assert "listing_review_evidence_invalid" in item["source_gaps"]


def test_independent_approval_and_dry_run_remain_externally_gated():
    current = draft(approval_id="approval-source")
    service, _pim, _store, _scoped, evidence, approvals, plans = (
        workspace(drafts=[current])
    )
    review = review_record(
        current,
        evidence_id="review-accepted",
        decision="accepted",
        effective_at=AT - timedelta(minutes=20),
    )
    evidence.by_target[current.id] = [review.id]
    evidence.records[review.id] = review
    approvals.values["approval-source"] = Approval(
        action="listing.publish",
        resource_type="listing_draft",
        resource_id=current.id,
        requested_by="operator",
        payload={
            "draft_id": current.id,
            "listing_snapshot_sha256": (
                listing_snapshot_sha256(current)
            ),
        },
        status=ApprovalStatus.APPROVED,
        decided_by="reviewer",
        decision_reason="accepted",
        id="approval-source",
        created_at=(AT - timedelta(minutes=15)).isoformat(),
    )
    approvals.values["approval-plan"] = Approval(
        action="listing.publish",
        resource_type="governed_execution_plan",
        resource_id="plan-1",
        requested_by="operator",
        payload={},
        status=ApprovalStatus.APPROVED,
        decided_by="risk-reviewer",
        decision_reason="accepted",
        id="approval-plan",
        created_at=(AT - timedelta(minutes=10)).isoformat(),
    )
    plans.values = [
        {
            "id": "plan-1",
            "request_hash": "r" * 64,
            "source_kind": "approved_listing_draft",
            "source_id": current.id,
            "source_snapshot_hash": listing_snapshot_sha256(current),
            "action_id": "listing_publish",
            "approval_id": "approval-plan",
            "evidence_ids": ["evidence-1"],
            "created_at": (AT - timedelta(minutes=10)).isoformat(),
            "dry_run": {
                "id": "dry-1",
                "passed": True,
            },
        }
    ]
    result = project(service)
    item = result["items"][0]
    assert (
        item["lifecycle"]["stage"]
        == "dry_run_verified_external_gate"
    )
    assert item["execution_plan"]["permit_created"] is False
    assert item["execution_plan"]["external_execution_ready"] is False
    assert item["lifecycle"]["external_write_allowed"] is False


def test_future_scope_drift_and_unauthorized_store_fail_closed():
    current = draft()
    current.scope_as_of = (AT + timedelta(seconds=1)).isoformat()
    service, *_ = workspace(drafts=[current])
    result = project(service)
    assert result["items"][0]["lifecycle"]["stage"] == "blocked"
    assert "listing_draft_scope_as_of_future" in result["items"][0][
        "source_gaps"
    ]
    with pytest.raises(PermissionError):
        service.project(
            principal=principal(frozenset({"other-store"})),
            entity_scope=SCOPE,
            store_ref="ozon-primary",
            as_of=AT,
        )


def test_approval_projection_uses_append_only_decision_cutoff():
    engine = database()
    repository = SqlAlchemyRepository(engine)
    created_at = datetime.now(UTC) - timedelta(hours=1)
    approval = Approval(
        action="listing.publish",
        resource_type="listing_draft",
        resource_id="draft-temporal",
        requested_by="operator",
        payload={"draft_id": "draft-temporal"},
        id="approval-temporal",
        created_at=created_at.isoformat(),
    )
    repository.add_approval(approval)
    approval.status = ApprovalStatus.APPROVED
    approval.decided_by = "reviewer"
    approval.decision_reason = "accepted"
    with repository.transaction():
        repository.save_approval(approval)
        repository.append_event(
            "approval.decided",
            approval.id,
            {"status": ApprovalStatus.APPROVED},
            actor_id="reviewer",
        )

    before = repository.get_approval_at(
        approval.id,
        as_of=created_at + timedelta(minutes=1),
    )
    after = repository.get_approval_at(
        approval.id,
        as_of=datetime.now(UTC) + timedelta(seconds=1),
    )
    assert before.status == ApprovalStatus.PENDING
    assert before.decided_by is None
    assert after.status == ApprovalStatus.APPROVED
    assert after.decided_by == "reviewer"


def test_execution_plan_source_projection_reads_only_requested_drafts_at_cutoff():
    engine = database()
    service = object.__new__(ExecutionPlanService)
    service.engine = engine
    created_at = AT - timedelta(minutes=20)
    with Session(engine) as session, session.begin():
        for plan_id, source_id in (
            ("plan-in-scope", "draft-in-scope"),
            ("plan-other", "draft-other"),
        ):
            session.add(
                ExecutionPlanRow(
                    id=plan_id,
                    request_hash=(plan_id[-1] * 64),
                    source_kind="approved_listing_draft",
                    source_id=source_id,
                    source_approval_id=f"source-{plan_id}",
                    source_snapshot_hash="s" * 64,
                    handoff_id=None,
                    policy_id=None,
                    release_id=None,
                    idempotency_key=f"key-{plan_id}",
                    adapter_id="ozon.product.import.v3",
                    action_id="listing_publish",
                    action_policy_version="v1",
                    target_json={"offer_id": "offer-1"},
                    precondition_state_hash="p" * 64,
                    intended_patch_json={"item": {}},
                    rollback_patch_json={"item": {}},
                    risk_limits_json={},
                    risk_values_json={},
                    risk_currency=None,
                    permit_ttl_seconds=None,
                    evidence_json=["evidence-1"],
                    approval_id=f"approval-{plan_id}",
                    created_by="operator",
                    created_at=created_at,
                )
            )
        session.add(
            ExecutionDryRunRow(
                id="dry-in-scope",
                request_hash="d" * 64,
                plan_id="plan-in-scope",
                current_state_hash="c" * 64,
                checks_json=[{"check": "scope", "passed": True}],
                passed=True,
                evidence_json=["evidence-1"],
                performed_by="verifier",
                created_at=created_at + timedelta(minutes=1),
            )
        )
    rows = service.list_for_listing_drafts(
        draft_ids=["draft-in-scope"],
        as_of=AT,
    )
    assert [item["id"] for item in rows] == ["plan-in-scope"]
    assert rows[0]["dry_run"]["passed"] is True
    assert rows[0]["source_id"] == "draft-in-scope"


def review_record(
    current: ListingDraft,
    *,
    evidence_id: str,
    decision: str,
    effective_at: datetime,
) -> EvidenceRecord:
    checks = {
        "native_russian_verified": True,
        "listing_snapshot_reviewed": True,
        "terminology_accepted": True,
        "claims_grounded": True,
        "ozon_policy_checked": True,
    }
    return EvidenceRecord(
        id=evidence_id,
        sha256=(evidence_id[-1] * 64),
        byte_size=10,
        filename=f"{evidence_id}.json",
        content_type="application/json",
        source="listing_russian_native_review",
        source_ref=f"listing://{current.id}/{evidence_id}",
        grade=EvidenceGrade.A,
        effective_at=effective_at.isoformat(),
        effective_until=None,
        recorded_at=effective_at.isoformat(),
        created_by="russian-reviewer",
        metadata={
            "evidence_role": (
                "listing_russian_native_review_attestation"
            ),
            "decision": decision,
            "draft_id": current.id,
            "listing_snapshot_sha256": (
                listing_snapshot_sha256(current)
            ),
            "submitted_by": current.requested_by,
            "reviewed_by": "russian-reviewer",
            "rationale": "native Russian review",
            "checks": checks,
        },
    )
