from __future__ import annotations

from datetime import UTC, datetime

from apps.control_plane.governance_scope import GovernanceScopeAuthority
from apps.control_plane.security import Principal

AS_OF = datetime(2026, 7, 27, 2, 0, tzinfo=UTC)
ENTITY_SCOPE = {
    "status": "ready",
    "entity_ref": "entity-cn-1",
}


class ListAuthority:
    def __init__(self, values):
        self.values = values

    def list(self):
        return self.values


class WindowAuthority:
    def __init__(self, values):
        self.values = values

    def list_windows(self):
        return self.values


class EvidenceScopeStub:
    def project(self, *, evidence_ids, **_values):
        if "evd-bad" in evidence_ids:
            return {
                "status": "blocked",
                "source_gaps": ["invalid_evidence"],
            }
        if "evd-unbound" in evidence_ids:
            return {
                "status": "partial",
                "source_gaps": ["evidence_scope_binding_missing"],
            }
        return {"status": "ready", "source_gaps": []}


def _principal() -> Principal:
    return Principal(
        actor_id="operator-1",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-cn-1",
        store_refs=frozenset({"store-cn-1"}),
    )


def _authority(*, reviews, plans, commands, windows):
    return GovernanceScopeAuthority(
        governance=ListAuthority(reviews),
        execution_plans=ListAuthority(plans),
        limited_executor=ListAuthority(commands),
        post_execution=WindowAuthority(windows),
        scoped_evidence=EvidenceScopeStub(),
    )


def test_governance_scope_uses_evidence_and_exact_parent_chain():
    authority = _authority(
        reviews=[
            {
                "id": "review-1",
                "evidence_ids": ["evd-ready"],
                "decision": "PASS",
            }
        ],
        plans=[
            {
                "id": "plan-1",
                "evidence_ids": ["evd-ready"],
                "approval_status": "approved",
                "source_approval_status": "approved",
                "created_by": "operator-1",
                "approval_decided_by": "approver-1",
            }
        ],
        commands=[
            {
                "id": "command-1",
                "plan_id": "plan-1",
                "command_kind": "execute",
                "status": "succeeded",
                "permit_expires_at": "2026-07-27T03:00:00+00:00",
                "receipt": {
                    "outcome": "succeeded",
                    "resulting_state_hash": "a" * 64,
                    "evidence_ids": ["evd-ready"],
                },
            }
        ],
        windows=[
            {
                "id": "window-1",
                "plan_id": "plan-1",
                "command_id": "command-1",
                "evidence_ids": ["evd-ready"],
                "status": "monitoring",
            }
        ],
    )
    values = {
        "principal": _principal(),
        "entity_scope": ENTITY_SCOPE,
        "store_ref": "store-cn-1",
        "as_of": AS_OF,
    }

    first = authority.project(**values)
    second = authority.project(**values)

    assert first == second
    assert first["status"] == "ready"
    assert first["counts"] == {
        "reviews": 1,
        "plans": 1,
        "commands": 1,
        "windows": 1,
    }
    assert first["source_gaps"] == []
    assert first["authority_sha256"]


def test_nested_store_text_does_not_scope_records_and_orphans_fail_closed():
    result = _authority(
        reviews=[],
        plans=[
            {
                "id": "nested-plan",
                "evidence_ids": [],
                "target": {"store_ref": "store-cn-1"},
            },
            {
                "id": "cross-store-plan",
                "store_ref": "other-store",
                "evidence_ids": ["evd-ready"],
            },
        ],
        commands=[
            {
                "id": "orphan-command",
                "plan_id": "nested-plan",
                "command_kind": "execute",
                "status": "queued",
                "receipt": None,
            }
        ],
        windows=[
            {
                "id": "orphan-window",
                "plan_id": "nested-plan",
                "command_id": "orphan-command",
                "evidence_ids": [],
            }
        ],
    ).project(
        principal=_principal(),
        entity_scope=ENTITY_SCOPE,
        store_ref="store-cn-1",
        as_of=AS_OF,
    )

    assert result["status"] == "blocked"
    assert result["counts"] == {
        "reviews": 0,
        "plans": 0,
        "commands": 0,
        "windows": 0,
    }
    assert "execution_plan:evidence_scope_binding_missing" in (
        result["source_gaps"]
    )
    assert "execution_plan:direct_store_scope_mismatch" in (
        result["source_gaps"]
    )
    assert "command:parent_plan_not_scoped" in result["source_gaps"]
    assert "window:parent_command_not_scoped" in result["source_gaps"]


def test_bad_receipt_evidence_cannot_become_readback():
    result = _authority(
        reviews=[],
        plans=[
            {
                "id": "plan-1",
                "evidence_ids": ["evd-ready"],
            }
        ],
        commands=[
            {
                "id": "command-1",
                "plan_id": "plan-1",
                "command_kind": "execute",
                "status": "succeeded",
                "receipt": {
                    "outcome": "succeeded",
                    "resulting_state_hash": "a" * 64,
                    "evidence_ids": ["evd-bad"],
                },
            }
        ],
        windows=[],
    ).project(
        principal=_principal(),
        entity_scope=ENTITY_SCOPE,
        store_ref="store-cn-1",
        as_of=AS_OF,
    )

    assert result["status"] == "partial"
    assert result["counts"]["plans"] == 1
    assert result["counts"]["commands"] == 0
    assert "command:invalid_evidence" in result["source_gaps"]
    assert result["blockers"][0]["code"] == "governance_scope_conflict"


def test_missing_entity_scope_does_not_query_global_authorities():
    class MustNotRead:
        @staticmethod
        def list():
            raise AssertionError("global authority must not be read")

        @staticmethod
        def list_windows():
            raise AssertionError("global authority must not be read")

    authority = GovernanceScopeAuthority(
        governance=MustNotRead(),
        execution_plans=MustNotRead(),
        limited_executor=MustNotRead(),
        post_execution=MustNotRead(),
        scoped_evidence=EvidenceScopeStub(),
    )

    result = authority.project(
        principal=_principal(),
        entity_scope={
            "status": "no_data",
            "entity_ref": None,
            "reason": "entity_scope_authority_missing",
        },
        store_ref="store-cn-1",
        as_of=AS_OF,
    )

    assert result["status"] == "no_data"
    assert result["counts"] == {
        "reviews": 0,
        "plans": 0,
        "commands": 0,
        "windows": 0,
    }
    assert result["source_gaps"] == [
        "governance_entity_scope_authority_missing"
    ]
