from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from apps.control_plane.api import app
from apps.control_plane.api_contracts import LineageLinkInput
from apps.control_plane.channel_account_authority import (
    ChannelAccountGovernanceEvidenceAuthority,
)
from apps.control_plane.channel_account_governance import ChannelAccountGovernanceStateMachine
from apps.control_plane.evidence import (
    EvidenceGrade,
    EvidenceRecord,
    EvidenceService,
    LineageEdge,
)
from apps.control_plane.execution_plans import ExecutionPlanService
from apps.control_plane.repository import InMemoryRepository
from apps.control_plane.routers.evidence_governance import (
    evidence_content,
    evidence_lineage,
    link_evidence,
)
from apps.control_plane.runtime import runtime
from apps.control_plane.scoped_channel_account_authority import (
    ScopedChannelAccountAuthorityWorkspace,
)
from apps.control_plane.security import AuthenticationFailure, Principal
from apps.control_plane.services import CommerceService

STORE_REF = "store-cn-1"
AS_OF = datetime(2026, 7, 31, 1, tzinfo=UTC)
READY_SCOPE = {
    "status": "ready",
    "tenant_ref": "tenant-cn-1",
    "entity_ref": "entity-cn-1",
    "store_ref": STORE_REF,
    "authority_sha256": "a" * 64,
}
NO_ENTITY_SCOPE = {
    "status": "no_data",
    "tenant_ref": "tenant-cn-1",
    "entity_ref": None,
    "store_ref": STORE_REF,
    "authority_sha256": None,
    "reason": "entity_scope_authority_missing",
}


def principal(
    actor_id: str,
    *roles: str,
    stores: frozenset[str] = frozenset({STORE_REF}),
) -> Principal:
    return Principal(
        actor_id=actor_id,
        roles=frozenset(roles),
        tenant_ref="tenant-cn-1",
        store_refs=stores,
    )


class ScopeGrantProbe:
    def __init__(self, value: dict) -> None:
        self.value = deepcopy(value)
        self.calls: list[dict] = []

    def current(self, **values):
        self.calls.append(values)
        return deepcopy(self.value)


class WorkspaceProbe:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def project(self, **values):
        self.calls.append(values)
        return {
            "contract_id": ("kjds-native-exact-scope-channel-account-authority-v1"),
            "status": "no_data",
            "scope": {
                "tenant_ref": values["principal"].tenant_ref,
                "entity_ref": values["entity_scope"].get("entity_ref"),
                "store_ref": values["store_ref"],
            },
            "counts": {"total": 0},
            "channel_accounts": [],
            "control_envelope": {
                "upstream_reads": ["channel_account_authority"],
                "external_write_allowed": False,
            },
        }


class NeverReadAuthority:
    def __init__(self) -> None:
        self.calls = 0

    def read_scoped_sources(self, **_values):
        self.calls += 1
        raise AssertionError("raw channel authority must not be read")


class UnusedAdapters:
    def resolve(self, **_values):
        raise AssertionError("adapter must not be read without entity scope")


class UnusedRuntimeIdentity:
    def verify(self, **_values):
        raise AssertionError("runtime identity must not be read without entity scope")


class GovernanceEvidenceProbe:
    def __init__(self) -> None:
        self.submissions: dict[str, str] = {}
        self.submit_calls: list[dict] = []
        self.review_calls: list[dict] = []

    def submit(self, **values):
        self.submit_calls.append(values)
        evidence_id = "evd-channel-submission-a"
        self.submissions[evidence_id] = values["principal"].actor_id
        return {
            "evidence_id": evidence_id,
            "submitted_by": values["principal"].actor_id,
            "status": "pending_review",
        }

    def review(self, **values):
        self.review_calls.append(values)
        submitted_by = self.submissions[values["submission_evidence_id"]]
        reviewed_by = values["principal"].actor_id
        if submitted_by == reviewed_by:
            raise ValueError("Channel account review requires an independent submission")
        return {
            "evidence_id": "evd-channel-review-a",
            "submitted_by": submitted_by,
            "reviewed_by": reviewed_by,
            "status": "accepted" if values["accepted"] else "rejected",
        }


class GovernanceMachineProbe:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def advance(self, **values):
        self.calls.append(values)
        return {
            "contract_id": "kjds-channel-account-governance-transition-v1",
            "transition_id": "cagt_a",
            "to_state": "evidence_pending",
            "external_write_allowed": False,
            "control_envelope": {
                "credential_created_or_read": False,
                "permit_created": False,
                "external_write_allowed": False,
            },
        }

def authenticate_as(monkeypatch, value: Principal) -> None:
    monkeypatch.setattr(
        runtime.authenticator,
        "authenticate",
        lambda _key: value,
    )


def test_channel_account_openapi_exposes_only_frozen_governance_mutation():
    schema = app.openapi()
    snapshot = json.loads(
        (Path(__file__).resolve().parents[1] / "docs" / "project" / "contracts" / "openapi-v1.json").read_text(
            encoding="utf-8"
        )
    )

    def canonical(value):
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()

    assert snapshot == schema
    assert hashlib.sha256(canonical(snapshot)).hexdigest() == hashlib.sha256(canonical(schema)).hexdigest()
    routes = {
        "/v1/channel-accounts/workspace": {"get"},
        "/v1/channel-account-governance/transitions": {"post"},
    }

    for path, methods in routes.items():
        assert set(schema["paths"][path]) == methods
        for method in methods:
            assert schema["paths"][path][method]["security"] == [{"KjdsApiKey": []}]

    assert "/v1/channel-accounts/evidence/submissions" not in schema["paths"]
    assert "/v1/channel-accounts/evidence/reviews" not in schema["paths"]
    assert "/v1/channel-accounts/events" not in schema["paths"]
    assert "/v1/channel-accounts/kill-switch" not in schema["paths"]
    channel_paths = {
        path: set(methods) for path, methods in schema["paths"].items() if path.startswith("/v1/channel-accounts")
    }
    assert channel_paths == {
        "/v1/channel-accounts/workspace": {"get"},
    }
    assert not {
        "post",
        "put",
        "patch",
        "delete",
    }.intersection(method for methods in channel_paths.values() for method in methods)


def test_governance_transition_requires_authentication(monkeypatch):
    def reject(_key):
        raise AuthenticationFailure("API key required", 401)

    monkeypatch.setattr(runtime.authenticator, "authenticate", reject)
    response = TestClient(app).post(
        "/v1/channel-account-governance/transitions",
        json={"store_ref": STORE_REF, "command": {"type": "submit_evidence", "payload": {}}},
    )
    assert response.status_code == 401


def test_governance_transition_rejects_cross_store_before_scope_read(monkeypatch):
    authenticate_as(monkeypatch, principal("operator-a", "operator"))
    grants = ScopeGrantProbe(READY_SCOPE)
    machine = GovernanceMachineProbe()
    monkeypatch.setattr(runtime, "scope_grants", grants)
    monkeypatch.setattr(runtime, "channel_account_governance", machine)
    response = TestClient(app).post(
        "/v1/channel-account-governance/transitions",
        headers={"X-KJDS-API-Key": "operator-key"},
        json={"store_ref": "other-store", "command": {"type": "submit_evidence", "payload": {}}},
    )
    assert response.status_code == 403
    assert grants.calls == []
    assert machine.calls == []


def test_governance_transition_calls_one_deep_module(monkeypatch):
    requester = principal("operator-a", "operator")
    authenticate_as(monkeypatch, requester)
    grants = ScopeGrantProbe(READY_SCOPE)
    machine = GovernanceMachineProbe()
    monkeypatch.setattr(runtime, "scope_grants", grants)
    monkeypatch.setattr(runtime, "channel_account_governance", machine)
    response = TestClient(app).post(
        "/v1/channel-account-governance/transitions",
        headers={"X-KJDS-API-Key": "operator-key"},
        json={
            "store_ref": STORE_REF,
            "as_of": AS_OF.isoformat(),
            "command": {"type": "submit_evidence", "payload": {"opaque": "intent"}},
        },
    )
    assert response.status_code == 201
    assert response.json()["external_write_allowed"] is False
    assert len(machine.calls) == 1
    assert machine.calls[0]["principal"] == requester
    assert machine.calls[0]["entity_scope"] == READY_SCOPE
    assert machine.calls[0]["store_ref"] == STORE_REF
    assert machine.calls[0]["as_of"] == AS_OF


def test_governance_api_reaches_canonical_submit_and_independent_review(monkeypatch):
    class CanonicalMutationScope:
        def resolve(self, *, principal, entity_scope, store_ref, **_values):
            assert entity_scope == READY_SCOPE
            assert principal.tenant_ref == READY_SCOPE["tenant_ref"]
            assert store_ref == STORE_REF
            return {
                "tenant_ref": READY_SCOPE["tenant_ref"],
                "entity_ref": READY_SCOPE["entity_ref"],
                "store_ref": STORE_REF,
                "scope_grant_authority_sha256": READY_SCOPE["authority_sha256"],
            }

    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    from apps.control_plane.sql_repository import Base

    Base.metadata.create_all(engine)
    evidence = EvidenceService(engine)
    authority = ChannelAccountGovernanceEvidenceAuthority(
        evidence=evidence,
        scope_authority=CanonicalMutationScope(),
    )
    repo = InMemoryRepository()
    commerce = CommerceService(repo, evidence_validator=evidence.require_valid)

    class NoCausalSource:
        def get_handoff(self, _value):
            raise AssertionError("channel-account workflow must not resolve causal handoff")

    plans = ExecutionPlanService(
        engine=engine,
        policy_shadow=NoCausalSource(),
        policies=None,
        evidence=evidence,
        commerce=commerce,
        readiness_provider=lambda _context: {},
    )
    machine = ChannelAccountGovernanceStateMachine(
        governance_evidence=authority,
        commerce=commerce,
        execution_plans=plans,
    )
    grants = ScopeGrantProbe(READY_SCOPE)
    monkeypatch.setattr(runtime, "scope_grants", grants)
    monkeypatch.setattr(runtime, "channel_account_governance", machine)
    client = TestClient(app)

    authenticate_as(monkeypatch, principal("operator-a", "operator"))
    submitted = client.post(
        "/v1/channel-account-governance/transitions",
        headers={"X-KJDS-API-Key": "operator-key"},
        json={
            "store_ref": STORE_REF,
            "as_of": AS_OF.isoformat(),
            "command": {
                "type": "submit_evidence",
                "payload": {
                    "purpose": "change_proposal",
                    "effective_at": AS_OF.isoformat(),
                    "effective_until": None,
                    "idempotency_key": "api-change-proposal-1",
                        "semantic_metadata": {
                            "change_kind": "grant_read_capability",
                        },
                    "canonical_payload": {
                        "contract_id": "kjds-channel-account-change-proposal-v1",
                            "platform": "ozon", "account_ref": "account-a",
                            "change_kind": "grant_read_capability", "requested_capabilities": ["catalog.read"],
                    },
                },
            },
        },
    )
    assert submitted.status_code == 201, submitted.text
    submission_id = submitted.json()["canonical_refs"]["submission_evidence_id"]

    authenticate_as(monkeypatch, principal("reviewer-a", "reviewer"))
    reviewed = client.post(
        "/v1/channel-account-governance/transitions",
        headers={"X-KJDS-API-Key": "reviewer-key"},
        json={
            "store_ref": STORE_REF,
            "as_of": AS_OF.isoformat(),
            "command": {
                "type": "review_evidence",
                "payload": {
                    "submission_evidence_id": submission_id,
                    "accepted": True,
                    "rationale": "Independent exact-scope API review",
                },
            },
        },
    )
    assert reviewed.status_code == 201
    payload = reviewed.json()
    assert payload["to_state"] == "evidence_reviewed"
    assert payload["canonical_refs"]["review_evidence_id"]
    assert payload["control_envelope"]["credential_created_or_read"] is False
    assert payload["external_write_allowed"] is False

    review_id = payload["canonical_refs"]["review_evidence_id"]
    authenticate_as(monkeypatch, principal("change-requester", "operator"))
    requested = client.post(
        "/v1/channel-account-governance/transitions",
        headers={"X-KJDS-API-Key": "requester-key"},
        json={
            "store_ref": STORE_REF,
            "as_of": AS_OF.isoformat(),
            "command": {
                "type": "request_change_approval",
                "payload": {
                    "reviewed_evidence_id": review_id,
                },
            },
        },
    )
    assert requested.status_code == 201, requested.text
    approval_id = requested.json()["canonical_refs"]["approval_id"]

    authenticate_as(monkeypatch, principal("approver-a", "approver"))
    decided = client.post(
        "/v1/channel-account-governance/transitions",
        headers={"X-KJDS-API-Key": "approver-key"},
        json={
            "store_ref": STORE_REF,
            "as_of": AS_OF.isoformat(),
            "command": {
                "type": "decide_change_approval",
                "payload": {"approval_id": approval_id, "approved": True, "reason": "Independent internal-plan approval"},
            },
        },
    )
    assert decided.status_code == 201
    assert decided.json()["to_state"] == "approved"

    authenticate_as(monkeypatch, principal("plan-operator", "operator"))
    planned = client.post(
        "/v1/channel-account-governance/transitions",
        headers={"X-KJDS-API-Key": "plan-key"},
        json={
            "store_ref": STORE_REF,
            "as_of": AS_OF.isoformat(),
            "command": {
                "type": "materialize_internal_plan",
                "payload": {"approval_id": approval_id, "idempotency_key": "api-plan-1"},
            },
        },
    )
    assert planned.status_code == 201
    plan_payload = planned.json()
    assert plan_payload["to_state"] == "execution_gated"
    assert plan_payload["canonical_refs"]["execution_plan_id"]
    assert plan_payload["canonical_refs"]["execution_approval_id"]
    assert plan_payload["control_envelope"]["permit_created"] is False
    assert plan_payload["external_write_allowed"] is False


def test_channel_account_workspace_requires_authentication(monkeypatch):
    def reject(_key):
        raise AuthenticationFailure("API key required", 401)

    monkeypatch.setattr(runtime.authenticator, "authenticate", reject)
    response = TestClient(app).get(
        "/v1/channel-accounts/workspace",
    )
    assert response.status_code == 401


@pytest.mark.parametrize(
    "role",
    [
        "operator",
        "reviewer",
        "compliance",
        "approver",
        "risk",
        "monitor",
        "admin",
    ],
)
def test_channel_account_workspace_allows_declared_roles_in_exact_store(
    monkeypatch,
    role,
):
    requester = principal(f"{role}-a", role)
    authenticate_as(monkeypatch, requester)
    grants = ScopeGrantProbe(READY_SCOPE)
    workspace = WorkspaceProbe()
    monkeypatch.setattr(runtime, "scope_grants", grants)
    monkeypatch.setattr(
        runtime,
        "scoped_channel_account_authority",
        workspace,
    )

    response = TestClient(app).get(
        "/v1/channel-accounts/workspace"
        f"?store_ref={STORE_REF}&as_of=2026-07-31T01%3A00%3A00Z"
        "&platform=ozon&account_ref=account-a&adapter_id=adapter-a"
        "&page_size=10",
        headers={"X-KJDS-API-Key": "role-key"},
    )

    assert response.status_code == 200
    assert len(grants.calls) == 1
    assert grants.calls[0]["principal"] == requester
    assert grants.calls[0]["store_ref"] == STORE_REF
    assert grants.calls[0]["as_of"] == AS_OF
    assert len(workspace.calls) == 1
    assert workspace.calls[0]["entity_scope"] == READY_SCOPE
    assert workspace.calls[0]["store_ref"] == STORE_REF
    assert workspace.calls[0]["platform"] == "ozon"
    assert workspace.calls[0]["account_ref"] == "account-a"
    assert workspace.calls[0]["adapter_id"] == "adapter-a"
    assert workspace.calls[0]["page_size"] == 10


def test_channel_account_workspace_rejects_cross_store_before_scope_read(
    monkeypatch,
):
    authenticate_as(
        monkeypatch,
        principal("operator-a", "operator"),
    )
    grants = ScopeGrantProbe(READY_SCOPE)
    workspace = WorkspaceProbe()
    monkeypatch.setattr(runtime, "scope_grants", grants)
    monkeypatch.setattr(
        runtime,
        "scoped_channel_account_authority",
        workspace,
    )

    response = TestClient(app).get(
        "/v1/channel-accounts/workspace?store_ref=other-store",
        headers={"X-KJDS-API-Key": "operator-key"},
    )

    assert response.status_code == 403
    assert grants.calls == []
    assert workspace.calls == []


def test_channel_account_workspace_missing_entity_reads_only_canonical_scope(
    monkeypatch,
):
    requester = principal("operator-a", "operator")
    authenticate_as(monkeypatch, requester)
    grants = ScopeGrantProbe(NO_ENTITY_SCOPE)
    authority = NeverReadAuthority()
    workspace = ScopedChannelAccountAuthorityWorkspace(
        authority=authority,
        adapters=UnusedAdapters(),
        scope_grants=grants,
        runtime_identity=UnusedRuntimeIdentity(),
    )
    monkeypatch.setattr(runtime, "scope_grants", grants)
    monkeypatch.setattr(
        runtime,
        "scoped_channel_account_authority",
        workspace,
    )

    response = TestClient(app).get(
        f"/v1/channel-accounts/workspace?store_ref={STORE_REF}&as_of=2026-07-31T01%3A00%3A00Z",
        headers={"X-KJDS-API-Key": "operator-key"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "no_data"
    assert payload["scope"]["entity_ref"] is None
    assert payload["counts"]["total"] == 0
    assert payload["channel_accounts"] == []
    assert payload["verified_native"] is False
    assert payload["control_envelope"]["upstream_reads"] == [
        "canonical_scope_grant"
    ]
    assert payload["control_envelope"]["external_write_allowed"] is False
    assert authority.calls == 0
    # Router authorization and the real deep module each resolve canonical
    # scope; neither result is trusted merely because it was supplied.
    assert len(grants.calls) == 2


def test_reserved_channel_evidence_lineage_is_cross_tenant_isolated_before_blob_read(
    monkeypatch,
):
    class EvidenceProbe:
        def __init__(self):
            self.content_reads = 0
            self.lineage_reads = 0
            self.links = 0
            self.record = type(
                "Record",
                (),
                {
                    "id": "foreign-channel-evidence",
                    "source": "channel_account_authorization_consent",
                    "metadata": {
                        "tenant_ref": "tenant-foreign",
                        "entity_ref": "entity-foreign",
                        "store_ref": "store-foreign",
                    },
                },
            )()

        def get(self, _evidence_id):
            return self.record

        def get_metadata(self, _evidence_id):
            return self.record

        def content(self, _evidence_id):
            self.content_reads += 1
            raise AssertionError("foreign reserved blob must not be read")

        def lineage(self, _evidence_id):
            self.lineage_reads += 1
            raise AssertionError("foreign lineage must not be read")

        def link(self, **_values):
            self.links += 1
            raise AssertionError("foreign lineage must not be written")

    evidence = EvidenceProbe()
    grants = ScopeGrantProbe(READY_SCOPE)
    monkeypatch.setattr(runtime, "evidence", evidence)
    monkeypatch.setattr(runtime, "scope_grants", grants)
    actor = principal("operator-a", "operator")
    for call in (
        lambda: evidence_content(
            "foreign-channel-evidence",
            actor,
        ),
        lambda: evidence_lineage(
            "foreign-channel-evidence",
            actor,
        ),
        lambda: link_evidence(
            "foreign-channel-evidence",
            LineageLinkInput(
                target_type="evidence",
                target_id="foreign-channel-evidence",
                relationship="supports",
            ),
            actor,
        ),
    ):
        with pytest.raises(HTTPException) as raised:
            call()
        assert raised.value.status_code == 403
    assert evidence.content_reads == 0
    assert evidence.lineage_reads == 0
    assert evidence.links == 0
    assert grants.calls == []


def test_lineage_router_keeps_dataclass_metadata_internal_until_access_check(
    monkeypatch,
):
    record = EvidenceRecord(
        id="evd-lineage-source",
        sha256="a" * 64,
        byte_size=12,
        filename="source.txt",
        content_type="text/plain",
        source="g1_verification",
        source_ref="g1://lineage-source",
        grade=EvidenceGrade.A,
        effective_at="2026-08-02T00:00:00+00:00",
        effective_until=None,
        recorded_at="2026-08-02T00:00:00+00:00",
        created_by="operator-a",
        metadata={},
    )
    edge = LineageEdge(
        id="lin-g1",
        from_type="evidence",
        from_id=record.id,
        to_type="verification",
        to_id="g1-api-database-write",
        relationship="supports",
        created_by="operator-a",
        recorded_at="2026-08-02T00:00:00+00:00",
    )

    class EvidenceProbe:
        def get_metadata(self, _evidence_id):
            return record

        def link(self, **_values):
            return edge

        def lineage(self, _evidence_id):
            return [edge]

    monkeypatch.setattr(runtime, "evidence", EvidenceProbe())
    actor = principal("operator-a", "operator")
    linked = link_evidence(
        record.id,
        LineageLinkInput(
            target_type="verification",
            target_id="g1-api-database-write",
            relationship="supports",
        ),
        actor,
    )

    assert linked["to_id"] == "g1-api-database-write"
    assert evidence_lineage(record.id, actor) == [
        {
            "id": "lin-g1",
            "from_type": "evidence",
            "from_id": record.id,
            "to_type": "verification",
            "to_id": "g1-api-database-write",
            "relationship": "supports",
            "created_by": "operator-a",
            "recorded_at": "2026-08-02T00:00:00+00:00",
        }
    ]
