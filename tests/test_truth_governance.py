from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.api import app
from apps.control_plane.evidence import (
    EvidenceBlobRow,
    EvidenceGrade,
    EvidenceService,
)
from apps.control_plane.runtime import runtime
from apps.control_plane.security import (
    AuthenticationFailure,
    KillSwitchEventRow,
    KillSwitchService,
    Principal,
)
from apps.control_plane.sql_repository import Base
from apps.control_plane.truth_governance import TruthGovernanceService


class FakeEvidence:
    def __init__(self, *, invalid: set[str] | None = None) -> None:
        self.invalid = invalid or set()

    def require_current(self, evidence_ids, *, as_of):
        assert as_of.tzinfo is not None
        if set(evidence_ids) & self.invalid:
            raise ValueError("invalid evidence")

    @staticmethod
    def get(evidence_id):
        return SimpleNamespace(
            id=evidence_id,
            sha256="a" * 64,
            grade="A",
            source="official-export",
            source_ref=f"official://{evidence_id}",
            effective_at="2026-07-01T00:00:00+00:00",
            effective_until=None,
            created_by="source-owner-1",
            metadata={
                "evidence_scope_contract_id": "kjds-evidence-scope-v1",
                "tenant_ref": "tenant-cn-1",
                "entity_ref": "entity-cn-1",
                "store_ref": "store-cn-1",
                "reviewed_by": "evidence-reviewer-1",
            },
        )


class FakeRules:
    def __init__(self, *, state="ready", missing=None, gaps=None) -> None:
        self.state = state
        self.missing = missing or []
        self.gaps = gaps or []

    def snapshot(self, *, as_of):
        assert as_of == "2026-07-27"
        return {
            "state": self.state,
            "registry_hash": "b" * 64 if self.state != "no_data" else None,
            "compiled_policy_hash": (
                "c" * 64 if self.state != "no_data" else None
            ),
            "effective_rule_count": 12 if self.state != "no_data" else 0,
            "missing_domains": self.missing,
            "source_evidence_gaps": self.gaps,
        }


class FakeLedger:
    def __init__(self, *, rows=None, status="reconciled") -> None:
        self.rows = rows or []
        self.status = status

    def snapshot(self, **values):
        assert values["store_ref"] == "store-cn-1"
        assert values["date_to"] == "2026-07-27"
        return {
            "status": self.status if self.rows else "no_data",
            "currency": "CNY",
            "rows": self.rows,
            "snapshot_sha256": "d" * 64,
        }


class ListAuthority:
    def __init__(self, values):
        self.values = values

    def list(self):
        return self.values


class PostExecutionAuthority:
    def __init__(self, values):
        self.values = values

    def list_windows(self):
        return self.values


class KillAuthority:
    @staticmethod
    def current(*, as_of):
        assert as_of == datetime(2026, 7, 27, 2, 0, tzinfo=UTC)
        return SimpleNamespace(
            engaged=False,
            reason=None,
            changed_at=None,
        )


def service(*, evidence=None, rules=None, ledger=None, scope_grants=None):
    plan = {
        "id": "plan-1",
        "store_ref": "store-cn-1",
        "evidence_ids": ["evd-official-1"],
        "created_by": "operator-1",
        "approval_status": "approved",
        "approval_decided_by": "approver-1",
        "source_approval_status": "approved",
    }
    receipt = {
        "outcome": "succeeded",
        "resulting_state_hash": "e" * 64,
        "evidence_ids": ["evd-readback"],
    }
    commands = [
        {
            "id": "cmd-1",
            "store_ref": "store-cn-1",
            "plan_id": "plan-1",
            "command_kind": "execute",
            "status": "succeeded",
            "permit_expires_at": "2026-07-27T03:00:00+00:00",
            "receipt": receipt,
        },
        {
            "id": "cmd-2",
            "store_ref": "store-cn-1",
            "plan_id": "plan-1",
            "command_kind": "rollback",
            "status": "queued",
            "permit_expires_at": "2026-07-27T03:00:00+00:00",
            "receipt": None,
        },
    ]
    return TruthGovernanceService(
        evidence=evidence or FakeEvidence(),
        rules=rules or FakeRules(),
        profit_ledger=ledger
        or FakeLedger(
            rows=[
                {
                    "scenario_contribution": "10",
                    "accrual_contribution": "9",
                    "settlement_contribution": "8",
                    "cash_contribution": "8",
                    "status": "reconciled",
                }
            ]
        ),
        governance=ListAuthority(
            [
                {
                    "id": "gate-1",
                    "store_ref": "store-cn-1",
                    "evidence_ids": ["evd-official-1"],
                    "decision": "PASS",
                }
            ]
        ),
        execution_plans=ListAuthority([plan]),
        limited_executor=ListAuthority(commands),
        post_execution=PostExecutionAuthority(
            [
                {
                    "id": "window-1",
                    "store_ref": "store-cn-1",
                    "plan_id": "plan-1",
                    "command_id": "cmd-1",
                    "evidence_ids": ["evd-official-1"],
                }
            ]
        ),
        kill_switch=KillAuthority(),
        scope_grants=scope_grants,
    )


def principal(*, stores=frozenset({"store-cn-1"})):
    return Principal(
        actor_id="operator-1",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-cn-1",
        store_refs=stores,
    )


def test_truth_governance_is_deterministic_and_does_not_invent_entity_scope():
    truth = service()
    values = {
        "principal": principal(),
        "store_ref": "store-cn-1",
        "as_of": "2026-07-27T02:00:00Z",
        "evidence_ids": ["evd-official-1"],
    }

    first = truth.snapshot(**values)
    second = truth.snapshot(**values)

    assert first == second
    assert first["snapshot_sha256"] == second["snapshot_sha256"]
    assert first["scope"]["tenant_scope"]["tenant_ref"] == "tenant-cn-1"
    assert first["scope"]["entity_scope"] == {
        "status": "no_data",
        "entity_ref": None,
        "authority": None,
        "authority_sha256": None,
        "reason": "entity_scope_authority_missing",
    }
    assert first["scope"]["store_scope"]["store_ref"] == "store-cn-1"
    assert "entity_scope_authority_missing" in first["blocker_codes"]
    assert first["governance"]["scope_authority"]["status"] == "no_data"
    assert first["governance"]["scope_authority"]["counts"] == {
        "reviews": 0,
        "plans": 0,
        "commands": 0,
        "windows": 0,
    }
    assert first["control_envelope"]["external_writes"] is False
    assert first["action_readiness"]["observe_research"]["status"] == "ready"
    assert first["action_readiness"]["external_publish"]["status"] == "blocked"
    assert set(first["contribution_views"]) == {
        "scenario_contribution",
        "accrual_contribution",
        "settlement_contribution",
        "cash_contribution",
    }
    assert all(
        item["status"] == "ready"
        for item in first["contribution_views"].values()
    )


def test_bad_evidence_fails_closed_without_enabling_external_writes():
    truth = service(evidence=FakeEvidence(invalid={"evd-bad"}))

    result = truth.snapshot(
        principal=principal(),
        store_ref="store-cn-1",
        as_of="2026-07-27T02:00:00Z",
        evidence_ids=["evd-bad"],
    )

    assert result["status"] == "blocked"
    assert result["authority_hashes"]["evidence_sha256"] is None
    assert "invalid_evidence:evd-bad" in result["blocker_codes"]
    assert result["action_readiness"]["candidate_score"]["status"] == (
        "research_only"
    )
    assert result["action_readiness"]["pilot_approve"]["status"] == "blocked"
    assert result["control_envelope"]["external_writes"] is False


def test_formal_scope_grant_enables_entity_scope_but_not_external_writes():
    class ReadyScopeGrant:
        @staticmethod
        def current(*, principal, store_ref, as_of):
            assert principal.actor_id == "operator-1"
            assert store_ref == "store-cn-1"
            assert as_of == datetime(2026, 7, 27, 2, 0, tzinfo=UTC)
            return {
                "status": "ready",
                "entity_ref": "entity-cn-1",
                "authority": "kjds-scope-grant-events-v1",
                "authority_sha256": "f" * 64,
                "grant_event_id": "sge-1",
                "grant_effective_at": "2026-07-01T00:00:00+00:00",
                "evidence_id": "evd-scope-1",
                "evidence_sha256": "a" * 64,
                "active_grant_count": 1,
            }

    result = service(scope_grants=ReadyScopeGrant()).snapshot(
        principal=principal(),
        store_ref="store-cn-1",
        as_of="2026-07-27T02:00:00Z",
        evidence_ids=["evd-official-1"],
    )

    assert result["scope"]["entity_scope"]["status"] == "ready"
    assert result["scope"]["entity_scope"]["entity_ref"] == "entity-cn-1"
    assert result["authority_hashes"]["scope_grant_sha256"] == "f" * 64
    assert result["authority_hashes"]["governance_scope_sha256"]
    assert "entity_scope_authority_missing" not in result["blocker_codes"]
    assert result["governance"]["scope_authority"]["status"] == "ready"
    assert result["governance"]["scope_authority"]["counts"] == {
        "reviews": 1,
        "plans": 1,
        "commands": 2,
        "windows": 1,
    }
    assert result["action_readiness"]["pilot_approve"]["status"] == "ready"
    assert result["action_readiness"]["external_publish"]["status"] == "blocked"
    assert result["control_envelope"]["external_writes"] is False


def test_formal_scope_grant_does_not_upgrade_unbound_legacy_evidence():
    class LegacyEvidence(FakeEvidence):
        @staticmethod
        def get(evidence_id):
            return SimpleNamespace(
                id=evidence_id,
                sha256="a" * 64,
                grade="A",
                source="official-export",
                source_ref=f"official://{evidence_id}",
                effective_at="2026-07-01T00:00:00+00:00",
                effective_until=None,
                created_by="source-owner-1",
                metadata={},
            )

    class ReadyScopeGrant:
        @staticmethod
        def current(*, principal, store_ref, as_of):
            return {
                "status": "ready",
                "entity_ref": "entity-cn-1",
                "authority": "kjds-scope-grant-events-v1",
                "authority_sha256": "f" * 64,
            }

    result = service(
        evidence=LegacyEvidence(),
        scope_grants=ReadyScopeGrant(),
    ).snapshot(
        principal=principal(),
        store_ref="store-cn-1",
        as_of="2026-07-27T02:00:00Z",
        evidence_ids=["evd-legacy-1"],
    )

    assert result["scope"]["entity_scope"]["status"] == "ready"
    assert "entity_scope_authority_missing" not in result["blocker_codes"]
    assert "evidence_scope_binding_missing" in result["blocker_codes"]
    assert result["action_readiness"]["observe_research"]["status"] == "ready"
    assert result["action_readiness"]["candidate_score"]["status"] == (
        "research_only"
    )
    assert result["action_readiness"]["pilot_approve"]["status"] == "blocked"
    assert result["control_envelope"]["external_writes"] is False


def test_corrupted_evidence_blob_fails_closed_through_real_hash_authority():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    evidence = EvidenceService(engine)
    record = evidence.capture(
        content=b"official-source",
        filename="official.json",
        content_type="application/json",
        source="official-export",
        source_ref="official://truth-governance",
        grade=EvidenceGrade.A,
        effective_at="2026-07-01T00:00:00Z",
        effective_until=None,
        created_by="independent-source",
    )
    with Session(engine) as session, session.begin():
        blob = session.get(EvidenceBlobRow, record.sha256)
        assert blob is not None
        blob.content_bytes = b"tampered-source"

    result = service(evidence=evidence).snapshot(
        principal=principal(),
        store_ref="store-cn-1",
        as_of="2026-07-27T02:00:00Z",
        evidence_ids=[record.id],
    )

    assert result["status"] == "blocked"
    assert result["authority_hashes"]["evidence_sha256"] is None
    assert f"invalid_evidence:{record.id}" in result["blocker_codes"]
    assert result["action_readiness"]["pilot_approve"]["status"] == "blocked"
    assert result["control_envelope"]["external_writes"] is False


def test_rule_gap_and_profit_no_data_remain_visible_but_research_stays_ready():
    truth = service(
        rules=FakeRules(
            state="no_data",
            missing=["commissions"],
            gaps=["OZG-CN-FEE-001"],
        ),
        ledger=FakeLedger(rows=[], status="no_data"),
    )

    result = truth.snapshot(
        principal=principal(),
        store_ref="store-cn-1",
        as_of="2026-07-27T02:00:00Z",
        evidence_ids=["evd-official-1"],
    )

    assert result["action_readiness"]["observe_research"]["status"] == "ready"
    assert result["action_readiness"]["candidate_score"]["status"] == (
        "research_only"
    )
    assert result["action_readiness"]["pilot_approve"]["status"] == "blocked"
    assert "effective_rule_domains_missing" in result["blocker_codes"]
    assert "rule_source_evidence_binding_missing" in result["blocker_codes"]
    assert "profit_ledger_no_data" in result["blocker_codes"]
    assert all(
        item["status"] == "no_data"
        for item in result["contribution_views"].values()
    )


def test_direct_service_call_rejects_store_outside_principal_scope():
    with pytest.raises(PermissionError, match="not authorized"):
        service().snapshot(
            principal=principal(stores=frozenset({"other-store"})),
            store_ref="store-cn-1",
            as_of="2026-07-27T02:00:00Z",
        )


def test_kill_switch_supports_deterministic_as_of_lookup():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        session.add_all(
            [
                KillSwitchEventRow(
                    engaged=True,
                    reason="guardrail",
                    actor_id="risk-1",
                    created_at=datetime(2026, 7, 27, 1, 0, tzinfo=UTC),
                ),
                KillSwitchEventRow(
                    engaged=False,
                    reason="reviewed",
                    actor_id="admin-1",
                    created_at=datetime(2026, 7, 27, 3, 0, tzinfo=UTC),
                ),
            ]
        )
    kill = KillSwitchService(engine)

    before_release = kill.current(
        as_of=datetime(2026, 7, 27, 2, 0, tzinfo=UTC)
    )
    after_release = kill.current(
        as_of=datetime(2026, 7, 27, 4, 0, tzinfo=UTC)
    )

    assert before_release.engaged is True
    assert before_release.reason == "guardrail"
    assert after_release.engaged is False
    assert after_release.reason == "reviewed"


def test_truth_governance_api_requires_auth_and_enforces_store_scope(monkeypatch):
    client = TestClient(app)

    def reject_missing_key(_key):
        raise AuthenticationFailure("X-KJDS-API-Key is required", 401)

    monkeypatch.setattr(runtime.authenticator, "authenticate", reject_missing_key)
    assert client.get("/v1/truth-governance/snapshot").status_code == 401

    monkeypatch.setattr(
        runtime.authenticator,
        "authenticate",
        lambda _key: principal(stores=frozenset({"other-store"})),
    )
    response = client.get(
        "/v1/truth-governance/snapshot?store_ref=store-cn-1",
        headers={"X-KJDS-API-Key": "test-key"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PERMISSION_DENIED"


def test_truth_governance_openapi_contract_is_read_only_and_protected():
    operation = app.openapi()["paths"]["/v1/truth-governance/snapshot"]["get"]

    assert operation["security"] == [{"KjdsApiKey": []}]
    parameters = {item["name"]: item for item in operation["parameters"]}
    assert set(parameters) == {
        "store_ref",
        "as_of",
        "evidence_id",
        "sku",
        "order_id",
        "currency",
    }
    assert "post" not in app.openapi()["paths"]["/v1/truth-governance/snapshot"]
    assert set(app.openapi()["paths"]["/v1/scope-grants/events"]) == {
        "get",
        "post",
    }
    current_operation = app.openapi()["paths"]["/v1/scope-grants/current"][
        "get"
    ]
    assert set(app.openapi()["paths"]["/v1/scope-grants/current"]) == {"get"}
    assert {
        item["name"] for item in current_operation["parameters"]
    } == {"store_ref", "as_of", "subject_actor_id"}
    intake_operation = app.openapi()["paths"]["/v1/scope-grants/intake"][
        "get"
    ]
    assert set(app.openapi()["paths"]["/v1/scope-grants/intake"]) == {"get"}
    assert {
        item["name"] for item in intake_operation["parameters"]
    } == {
        "store_ref",
        "entity_ref",
        "event_type",
        "as_of",
        "subject_actor_id",
    }
    assert intake_operation["security"] == [{"KjdsApiKey": []}]
    assert set(app.openapi()["paths"]["/v1/scope-grants/preflight"]) == {"post"}
    assert app.openapi()["paths"]["/v1/scope-grants/preflight"]["post"][
        "security"
    ] == [{"KjdsApiKey": []}]
    assert set(app.openapi()["paths"]["/v1/scope-grants/evidence"]) == {"post"}
    assert set(
        app.openapi()["paths"]["/v1/scope-grants/evidence/reviews"]
    ) == {"post"}
    assert set(
        app.openapi()["paths"][
            "/v1/agent-control/projects/{project_id}/operating-subject"
        ]
    ) == {"get"}
    assert set(
        app.openapi()["paths"][
            "/v1/agent-control/projects/{project_id}/"
            "operating-subject/events"
        ]
    ) == {"post"}
