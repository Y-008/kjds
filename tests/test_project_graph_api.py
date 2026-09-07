from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from apps.control_plane.api import app, is_write_safety_control_path, registered_routes
from apps.control_plane.autonomous_pm_heartbeat import (
    SERVER_AUTHORITY_FIELDS,
    AuthorityObservation,
    GitWorktreeObservation,
    ServerEconomicGuardRead,
)
from apps.control_plane.economic_guard_service import EconomicGuardInput, evaluate_economic_guard
from apps.control_plane.routers import project_graph
from apps.control_plane.runtime import runtime
from apps.control_plane.security import Principal, WritesDisabled


def test_project_graph_read_routes_are_registered():
    paths = {route.path for route in registered_routes()}
    assert "/v1/project-graph/{project_id}/frontier" in paths
    assert "/v1/project-graph/{project_id}/task-contract" in paths
    assert "/v1/project-graph/{project_id}/release-contract/validate" in paths
    assert "/v1/project-graph/{project_id}/heartbeat/latest" in paths
    assert "/v1/project-graph/{project_id}/critical-path" in paths
    assert "/v1/project-graph/{project_id}/blockers" in paths
    assert "/v1/project-graph/{project_id}/proof-debt" in paths
    assert "/v1/project-graph/{project_id}/replay" in paths
    assert "/v1/project-graph/{project_id}/heartbeat" in paths
    assert "/v1/graph/{project_id}/historical-frontier" in paths
    assert "/v1/project-graph/{project_id}/proposals" in paths
    assert "/v1/project-graph/{project_id}/proposals/replay" in paths
    assert "/v1/project-graph/{project_id}/proposals/{proposal_id}" in paths
    assert is_write_safety_control_path(
        "/v1/project-graph/{project_id}/heartbeat"
    ) is True
    assert is_write_safety_control_path(
        "/v1/project-graph/project-a/heartbeat"
    ) is True
    assert is_write_safety_control_path(
        "/v1/project-graph/project-a/release-contract/validate"
    ) is True
    for suffix in ("signal", "dispatch-wave", "invalidate"):
        assert is_write_safety_control_path(
            f"/v1/project-graph/project-a/{suffix}"
        ) is True


def test_task_contract_is_read_only_projection(monkeypatch):
    principal = Principal(
        actor_id="pm-test",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-a",
        store_refs=frozenset({"store-a"}),
    )
    monkeypatch.setattr(
        project_graph,
        "_graph",
        lambda *_args, **_kwargs: {
            "contract_id": "kjds-agent-harness-workspace-v1",
            "project": {"id": "project-a", "title": "Control tower"},
            "scope": {"tenant_ref": "tenant-a", "entity_ref": "entity-a", "store_ref": "store-a"},
            "snapshot_sha256": "b" * 64,
            "tasks": [
                {
                    "id": "task-a",
                    "title": "Read-only task",
                    "owner": "agent-a",
                    "dependencies": [],
                    "state": "pending",
                    "workspace": "apps/control_plane/project_task_contracts.py",
                    "verification_condition": "focused tests pass",
                }
            ],
        },
    )

    result = project_graph.graph_task_contract(
        project_id="project-a", principal=principal, store_ref="store-a"
    )
    assert result["projection_only"] is True
    assert result["ready_frontier"] == ["task-a"]
    assert result["external_write_allowed"] is False


def test_release_contract_validation_never_grants_release(monkeypatch):
    principal = Principal(
        actor_id="pm-test",
        roles=frozenset({"reviewer"}),
        tenant_ref="tenant-a",
        store_refs=frozenset({"store-a"}),
    )
    monkeypatch.setattr(
        project_graph,
        "_graph",
        lambda *_args, **_kwargs: {
            "snapshot_sha256": "c" * 64,
            "scope": {"tenant_ref": "tenant-a", "entity_ref": "entity-a", "store_ref": "store-a"},
        },
    )
    body = {
        "wave_id": "W-001",
        "goal": "contract validation",
        "included_tasks": ["WP-001"],
        "excluded_tasks": [],
        "dependency_frontier": [],
        "claim_level": "engineering",
        "exact_head": "a" * 40,
        "migration_head": "migration-1",
        "changed_paths": ["apps/control_plane/project_task_contracts.py"],
        "api_schema_diff": {},
        "test_receipts": ["test:contract"],
        "runtime_receipt": None,
        "business_evidence": None,
        "economic_impact": None,
        "open_blockers": [],
        "invalidated_nodes": [],
        "rollback_ref": "git:HEAD",
        "next_wave": [],
        "snapshot_id": "c" * 64,
    }
    result = project_graph.validate_graph_release_contract(
        project_id="project-a", body=body, principal=principal, store_ref="store-a"
    )
    assert result["validation"]["valid"] is True
    assert result["snapshot_binding"] == "bound"
    assert result["release_allowed"] is False
    assert result["external_write_allowed"] is False


def test_latest_heartbeat_replays_scoped_operating_snapshot(monkeypatch):
    principal = Principal(
        actor_id="pm-test",
        roles=frozenset({"monitor"}),
        tenant_ref="tenant-a",
        store_refs=frozenset({"store-a"}),
    )
    monkeypatch.setattr(
        project_graph,
        "_graph",
        lambda *_args, **_kwargs: {
            "scope": {"entity_ref": "entity-a", "store_ref": "store-a"},
        },
    )
    monkeypatch.setattr(
        runtime.project_heartbeat_store,
        "latest",
        lambda **_kwargs: {
            "heartbeat_id": "hb-1",
            "payload": {"operating_snapshot": {"snapshot_sha256": "a" * 64}},
        },
    )
    result = project_graph.latest_project_heartbeat(
        project_id="project-a", principal=principal, store_ref="store-a"
    )
    assert result["status"] == "REPLAYED"
    assert result["operating_snapshot"]["snapshot_sha256"] == "a" * 64
    assert result["external_write_allowed"] is False


def test_heartbeat_rejects_entity_scope_mismatch(monkeypatch):
    principal = Principal(
        actor_id="pm-test",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-a",
        store_refs=frozenset({"store-a"}),
    )
    monkeypatch.setattr(
        project_graph,
        "_graph",
        lambda *_args, **_kwargs: {
            "scope": {"entity_ref": "entity-a", "store_ref": "store-a"},
            "nodes": [],
            "edges": [],
            "tasks": [],
        },
    )
    body = project_graph.ProjectHeartbeatInput(
        entity_ref="entity-b",
        store_ref="store-a",
        head="abc",
    )

    with pytest.raises(HTTPException) as caught:
        project_graph.project_heartbeat(
            project_id="project-a",
            body=body,
            principal=principal,
        )

    assert caught.value.status_code == 403


def test_heartbeat_core_guards_default_to_fail_closed():
    body = project_graph.ProjectHeartbeatInput(entity_ref="entity-a", head="abc")
    assert body.evidence_fresh is False
    assert body.data_quality_valid is False
    assert body.rollback_available is False
    assert body.experiment_clear is False


def test_heartbeat_path_bypasses_kill_switch_for_safety_bookkeeping(monkeypatch):
    principal = Principal(
        actor_id="pm-test",
        roles=frozenset({"monitor"}),
        tenant_ref="tenant-a",
        store_refs=frozenset({"store-a"}),
    )
    monkeypatch.setattr(runtime.authenticator, "authenticate", lambda _key: principal)
    monkeypatch.setattr(
        runtime.kill_switch,
        "ensure_writes_allowed",
        lambda: (_ for _ in ()).throw(WritesDisabled("contained")),
    )

    response = TestClient(app).post(
        "/v1/project-graph/project-a/heartbeat",
        headers={"X-KJDS-API-Key": "monitor-key"},
    )

    # The request reaches route validation/dispatch; the global kill switch
    # must not turn safety bookkeeping into a 423 response.
    assert response.status_code != 423


def test_heartbeat_persists_and_replays_standard_task_result(monkeypatch):
    principal = Principal(
        actor_id="pm-test",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-a",
        store_refs=frozenset({"store-a"}),
    )
    graph = {
        "scope": {"entity_ref": "entity-a", "store_ref": "store-a"},
        "nodes": [],
        "edges": [],
        "tasks": [],
    }
    monkeypatch.setattr(project_graph, "_graph", lambda *_args, **_kwargs: graph)
    captured: dict[str, object] = {}

    def record(**values):
        captured.update(values)
        return {
            "heartbeat_id": "hb-1",
            "revision": 1,
            "idempotency_key": values.get("idempotency_key"),
            "request_sha256": "a" * 64,
        }

    monkeypatch.setattr(runtime.project_heartbeat_store, "record", record)
    body = project_graph.ProjectHeartbeatInput(
        entity_ref="entity-a",
        store_ref="store-a",
        head="abc",
        idempotency_key="hb-result-1",
        task_result={
            "changed_files": ["apps/control_plane/x.py"],
            "proof_refs": ["proof://x"],
            "evidence_refs": ["evidence://x"],
            "test_receipts": ["pytest://receipt"],
            "new_blockers": [{"id": "blocker-1", "reason": "freshness"}],
            "invalidated_nodes": ["node-y"],
            "economic_impact": "12.50",
            "rollback_ref": "rollback://x",
            "next_dependencies": ["task-z"],
        },
    )

    result = project_graph.project_heartbeat(
        project_id="project-a", body=body, principal=principal
    )

    expected = body.task_result
    assert result["task_result"] == expected
    assert captured["payload"]["task_result"] == expected


def test_heartbeat_ignores_caller_git_attestation_and_binds_server_observation(monkeypatch):
    principal = Principal(
        actor_id="pm-test",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-a",
        store_refs=frozenset({"store-a"}),
    )
    monkeypatch.setattr(
        project_graph,
        "_graph",
        lambda *_args, **_kwargs: {
            "scope": {"entity_ref": "entity-a", "store_ref": "store-a"},
            "nodes": [],
            "edges": [],
            "tasks": [],
        },
    )
    server_observation = GitWorktreeObservation(
        status="observed",
        head="b" * 40,
        worktree_clean=False,
        status_sha256="c" * 64,
        observed_at=datetime(2026, 9, 6, 12, tzinfo=UTC),
    )
    monkeypatch.setattr(
        project_graph,
        "observe_server_git_worktree",
        lambda: server_observation,
    )
    captured: dict[str, object] = {}

    def record(**values):
        captured.update(values)
        return {"heartbeat_id": "hb-server-git", "revision": 1, "payload": values["payload"]}

    monkeypatch.setattr(runtime.project_heartbeat_store, "record", record)
    result = project_graph.project_heartbeat(
        project_id="project-a",
        body=project_graph.ProjectHeartbeatInput(
            entity_ref="entity-a",
            store_ref="store-a",
            # Deliberately claim a matching/clean checkout.  The server
            # observation below must win over these legacy fields.
            head="b" * 40,
            head_verified=True,
            workspace_state_known=True,
            workspace_clean=True,
            idempotency_key="hb-server-git-1",
        ),
        principal=principal,
    )

    operational = captured["payload"]["operational_snapshot"]
    operating = captured["payload"]["operating_snapshot"]
    assert operational["server_git"]["snapshot_sha256"] == server_observation.snapshot_sha256
    assert operating["contract_id"] == "kjds-operating-snapshot-v1"
    assert operating["admission_state"] == "HOLD"
    assert operating["external_write_allowed"] is False
    assert operational["workspace_clean"] is False
    assert operational["caller_claims_ignored"]["workspace_clean"] is True
    assert result["server_observation"]["caller_git_attestation_used"] is False
    assert result["server_observation"]["git"]["head"] == "b" * 40
    assert result["decision"].reasons.count("workspace_dirty") == 1


def _wire_server_authority_for_heartbeat(monkeypatch, *, observed_at: datetime):
    """Bind deterministic server readers for route-level authority tests."""

    graph = {
        "scope": {"entity_ref": "entity-a", "store_ref": "store-a"},
        "nodes": [],
        "edges": [],
        "tasks": [],
    }
    projection = {
        "status": "PROVEN",
        "as_of": observed_at.isoformat(),
        "snapshot_sha256": "d" * 64,
        "frontier": [],
        "frontier_ids": [],
        "blockers": [],
        "invalidations": {},
    }
    monkeypatch.setattr(project_graph, "_graph", lambda *_args, **_kwargs: graph)
    monkeypatch.setattr(project_graph, "plan_proof_frontier", lambda _graph: projection)
    git = GitWorktreeObservation(
        status="observed",
        head="a" * 40,
        worktree_clean=True,
        status_sha256="b" * 64,
        observed_at=observed_at,
    )
    monkeypatch.setattr(project_graph, "observe_server_git_worktree", lambda: git)

    calls: list[tuple[str, str, datetime]] = []
    readers = {}
    for name in SERVER_AUTHORITY_FIELDS:
        def read(*, scope_key, observed_at, _name=name):
            calls.append((_name, scope_key, observed_at))
            return AuthorityObservation(
                name=_name,
                status="valid",
                scope_key=scope_key,
                observed_at=observed_at,
                source_ref=f"server://heartbeat/{_name}",
                payload_sha256="e" * 64,
            )

        readers[name] = read
    guard = evaluate_economic_guard(
        EconomicGuardInput(cash_available=Decimal("100"))
    )
    economic_observation = AuthorityObservation(
        name="economic_guard",
        status="valid",
        scope_key="tenant-a/entity-a/store-a",
        observed_at=observed_at,
        source_ref="server://heartbeat/economic_guard",
        payload_sha256=guard.snapshot_sha256,
    )
    economic_read = ServerEconomicGuardRead(
        guard=guard,
        observation=economic_observation,
    )
    economic_calls: list[tuple[str, datetime]] = []

    def read_economic(*, scope_key, observed_at):
        economic_calls.append((scope_key, observed_at))
        return economic_read

    monkeypatch.setattr(runtime, "pm_authority_readers", readers)
    monkeypatch.setattr(runtime, "pm_economic_guard_reader", read_economic)
    return git, calls, economic_calls


def test_heartbeat_route_uses_runtime_authority_and_ignores_caller_claims(monkeypatch):
    observed_at = datetime(2026, 9, 7, 12, tzinfo=UTC)
    _git, calls, economic_calls = _wire_server_authority_for_heartbeat(
        monkeypatch, observed_at=observed_at
    )
    principal = Principal(
        actor_id="pm-test",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-a",
        store_refs=frozenset({"store-a"}),
    )
    captured: dict[str, object] = {}

    def record(**values):
        captured.update(values)
        return {"heartbeat_id": "hb-authority", "revision": 1, "payload": values["payload"]}

    monkeypatch.setattr(runtime.project_heartbeat_store, "record", record)
    result = project_graph.project_heartbeat(
        project_id="project-a",
        body=project_graph.ProjectHeartbeatInput(
            entity_ref="entity-a",
            store_ref="store-a",
            head="a" * 40,
            # Every legacy claim is intentionally false.  The server readers
            # below are the only values allowed to influence the decision.
            head_verified=False,
            workspace_state_known=False,
            workspace_clean=False,
            task_queue_known=False,
            lease_snapshot_known=False,
            test_receipts_current=False,
            proof_receipts_current=False,
            evidence_fresh=False,
            data_quality_valid=False,
            external_readback_passed=False,
            rollback_available=False,
            experiment_clear=False,
            economic_state_known=False,
            cash_available=Decimal("0"),
            idempotency_key="hb-authority-1",
        ),
        principal=principal,
    )

    assert result["decision"].status == "dispatch"
    operational = captured["payload"]["operational_snapshot"]
    assert operational["authority_status"] == "ready"
    assert operational["authority_unverified_fields"] == []
    assert all(operational[field] is True for field in (
        "task_queue_known",
        "lease_snapshot_known",
        "test_receipts_current",
        "proof_receipts_current",
        "evidence_fresh",
        "data_quality_valid",
        "external_readback_passed",
        "rollback_available",
        "experiment_clear",
        "economic_state_known",
        "head_verified",
        "workspace_state_known",
        "workspace_clean",
    ))
    assert all(value is False for value in operational["caller_claims_ignored"].values())
    assert captured["payload"]["economic_guard"]["source"] == "server_authority_snapshot"
    assert {name for name, _scope, _time in calls} == set(SERVER_AUTHORITY_FIELDS)
    assert all(scope == "tenant-a/entity-a/store-a" for _name, scope, _time in calls)
    assert economic_calls == [("tenant-a/entity-a/store-a", observed_at)]


def test_heartbeat_route_blocks_when_runtime_authority_readers_are_unbound(monkeypatch):
    observed_at = datetime(2026, 9, 7, 12, tzinfo=UTC)
    graph = {
        "scope": {"entity_ref": "entity-a", "store_ref": "store-a"},
        "nodes": [],
        "edges": [],
        "tasks": [],
    }
    projection = {
        "status": "PROVEN",
        "snapshot_sha256": "f" * 64,
        "frontier_ids": [],
        "frontier": [],
        "blockers": [],
        "invalidations": {},
    }
    monkeypatch.setattr(project_graph, "_graph", lambda *_args, **_kwargs: graph)
    monkeypatch.setattr(project_graph, "plan_proof_frontier", lambda _graph: projection)
    monkeypatch.setattr(
        project_graph,
        "observe_server_git_worktree",
        lambda: GitWorktreeObservation(
            status="observed",
            head="a" * 40,
            worktree_clean=True,
            status_sha256="b" * 64,
            observed_at=observed_at,
        ),
    )
    monkeypatch.setattr(runtime, "pm_authority_readers", None)
    monkeypatch.setattr(runtime, "pm_economic_guard_reader", None)
    monkeypatch.setattr(
        runtime.project_heartbeat_store,
        "record",
        lambda **values: {"heartbeat_id": "hb-blocked", "revision": 1, "payload": values["payload"]},
    )
    principal = Principal(
        actor_id="pm-test",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-a",
        store_refs=frozenset({"store-a"}),
    )
    result = project_graph.project_heartbeat(
        project_id="project-a",
        body=project_graph.ProjectHeartbeatInput(
            entity_ref="entity-a",
            store_ref="store-a",
            head="a" * 40,
            # False or true caller claims must have the same blocked result.
            head_verified=True,
            workspace_state_known=True,
            workspace_clean=True,
            task_queue_known=True,
            lease_snapshot_known=True,
            test_receipts_current=True,
            proof_receipts_current=True,
            evidence_fresh=True,
            data_quality_valid=True,
            external_readback_passed=True,
            rollback_available=True,
            experiment_clear=True,
            economic_state_known=True,
            cash_available=Decimal("100000"),
            idempotency_key="hb-blocked-1",
        ),
        principal=principal,
    )

    assert result["decision"].status == "isolate"
    assert "server_observation_unavailable:task_queue" in result["decision"].reasons
    assert "server_observation_unavailable:economic_guard" in result["decision"].reasons
    assert result["server_observation"]["authority_status"] == "blocked"
    assert result["server_observation"]["authority_unverified_fields"]


def test_heartbeat_task_result_carries_graph_debt_and_frontier(monkeypatch):
    principal = Principal(
        actor_id="pm-test",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-a",
        store_refs=frozenset({"store-a"}),
    )
    monkeypatch.setattr(
        project_graph,
        "_graph",
        lambda *_args, **_kwargs: {
            "scope": {"entity_ref": "entity-a", "store_ref": "store-a"},
            "nodes": [
                {
                    "id": "blocked-node",
                    "layer": "business",
                    "state": "BLOCKED",
                    "label": "Blocked business gate",
                },
                {
                    "id": "frontier-node",
                    "layer": "business",
                    "state": "NO_DATA",
                    "label": "Actionable frontier",
                },
            ],
            "edges": [],
            "tasks": [],
        },
    )
    monkeypatch.setattr(
        runtime.project_heartbeat_store,
        "record",
        lambda **values: {
            "heartbeat_id": "hb-derived",
            "revision": 1,
            "idempotency_key": values.get("idempotency_key"),
            "request_sha256": "b" * 64,
            "payload": values["payload"],
        },
    )

    result = project_graph.project_heartbeat(
        project_id="project-a",
        body=project_graph.ProjectHeartbeatInput(
            entity_ref="entity-a",
            store_ref="store-a",
            head="abc",
            idempotency_key="hb-derived-1",
        ),
        principal=principal,
    )

    task_result = result["task_result"]
    assert task_result["invalidated_nodes"] == []
    assert task_result["next_dependencies"] == ["frontier-node"]
    assert any(item["id"] == "blocked-node" for item in task_result["new_blockers"])


def test_task_result_rejects_authority_fields_before_heartbeat_persistence():
    with pytest.raises(ValidationError, match="TeamAgent results cannot mint authority"):
        project_graph.ProjectHeartbeatInput(
            entity_ref="entity-a",
            store_ref="store-a",
            head="abc",
            task_result={"external_write_allowed": True},
        )


def test_dispatch_wave_validates_snapshot_before_planning(monkeypatch):
    principal = Principal(
        actor_id="pm-test",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-a",
        store_refs=frozenset({"store-a"}),
    )
    monkeypatch.setattr(
        project_graph,
        "_graph",
        lambda *_args, **_kwargs: {
            "scope": {"entity_ref": "entity-a", "store_ref": "store-a"},
            "snapshot_sha256": "a" * 64,
            "nodes": [],
            "edges": [],
            "tasks": [],
        },
    )
    body = project_graph.DispatchWaveInput(
        expected_snapshot_sha256="b" * 64,
        idempotency_key="dispatch-1",
    )

    with pytest.raises(HTTPException) as caught:
        project_graph.dispatch_wave(
            project_id="project-a", body=body, principal=principal, store_ref="store-a"
        )

    assert caught.value.status_code == 422
    assert "dispatch snapshot is stale" in str(caught.value.detail)


def test_invalidation_validates_snapshot_before_building_overlay(monkeypatch):
    principal = Principal(
        actor_id="reviewer",
        roles=frozenset({"reviewer"}),
        tenant_ref="tenant-a",
        store_refs=frozenset({"store-a"}),
    )
    monkeypatch.setattr(
        project_graph,
        "_graph",
        lambda *_args, **_kwargs: {
            "scope": {"entity_ref": "entity-a", "store_ref": "store-a"},
            "snapshot_sha256": "a" * 64,
            "nodes": [{"id": "source"}, {"id": "target"}],
            "edges": [],
            "tasks": [],
        },
    )
    body = project_graph.InvalidateGraphInput(
        source_node_id="source",
        target_node_ids=("target",),
        reason="upstream evidence changed",
        idempotency_key="invalidate-1",
        expected_snapshot_sha256="b" * 64,
    )

    with pytest.raises(HTTPException) as caught:
        project_graph.invalidate_graph(
            project_id="project-a", body=body, principal=principal, store_ref="store-a"
        )

    assert caught.value.status_code == 422
    assert "invalidation snapshot is stale" in str(caught.value.detail)


def test_dispatch_wave_persists_and_replays_the_immutable_proposal(monkeypatch):
    principal = Principal(
        actor_id="pm-test",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-a",
        store_refs=frozenset({"store-a"}),
    )
    graph = {
        "scope": {"entity_ref": "entity-a", "store_ref": "store-a"},
        "project": {"baseline_sha256": "h" * 64},
        "snapshot_sha256": "a" * 64,
        "nodes": [],
        "edges": [],
        "tasks": [],
    }
    projection = {
        "status": "NO_DATA",
        "as_of": "2026-09-06T00:00:00+00:00",
        "snapshot_sha256": "a" * 64,
        "frontier": [],
        "frontier_ids": [],
        "blockers": [],
    }
    monkeypatch.setattr(project_graph, "_graph", lambda *_args, **_kwargs: graph)
    monkeypatch.setattr(project_graph, "plan_proof_frontier", lambda _graph: projection)

    class FakeLedger:
        def __init__(self):
            self.calls = []
            self.payload = None

        def record(self, **values):
            self.calls.append(values)
            if self.payload is None:
                self.payload = dict(values["proposal"])
                replayed = False
            else:
                replayed = True
            return {
                "proposal_id": "pgp-test",
                "revision": 1,
                "idempotency_key": values["idempotency_key"],
                "request_sha256": values["request_sha256"],
                "proposal_sha256": values["proposal_sha256"],
                "payload_sha256": "c" * 64,
                "payload": dict(self.payload),
                "replayed": replayed,
            }

    fake = FakeLedger()
    monkeypatch.setattr(runtime, "project_graph_proposal_ledger", fake)
    body = project_graph.DispatchWaveInput(idempotency_key="dispatch-1")
    first = project_graph.dispatch_wave(
        project_id="project-a",
        body=body,
        principal=principal,
        store_ref="store-a",
    )
    second = project_graph.dispatch_wave(
        project_id="project-a",
        body=body,
        principal=principal,
        store_ref="store-a",
    )

    assert first["persisted"] is True
    assert first["replay"]["replayed"] is False
    assert second["replay"]["replayed"] is True
    assert second["proposal_id"] == "pgp-test"
    assert second["tasks"] == first["tasks"]
    assert all(call["kind"] == "dispatch-wave" for call in fake.calls)
    assert all(call["proposal"]["external_write_allowed"] is False for call in fake.calls)


def test_invalidation_persists_with_expected_revision_and_stays_proposal_only(monkeypatch):
    principal = Principal(
        actor_id="reviewer",
        roles=frozenset({"reviewer"}),
        tenant_ref="tenant-a",
        store_refs=frozenset({"store-a"}),
    )
    graph = {
        "scope": {"entity_ref": "entity-a", "store_ref": "store-a"},
        "snapshot_sha256": "a" * 64,
        "nodes": [{"id": "source"}, {"id": "target"}],
        "edges": [],
        "tasks": [],
    }
    projection = {
        "status": "BLOCKED",
        "as_of": "2026-09-06T00:00:00+00:00",
        "snapshot_sha256": "b" * 64,
        "frontier": [],
        "frontier_ids": [],
        "blockers": [],
    }
    monkeypatch.setattr(project_graph, "_graph", lambda *_args, **_kwargs: graph)
    monkeypatch.setattr(project_graph, "plan_proof_frontier", lambda _graph: projection)
    captured = {}

    class FakeLedger:
        def record(self, **values):
            captured.update(values)
            return {
                "proposal_id": "pgp-invalidate",
                "revision": 3,
                "idempotency_key": values["idempotency_key"],
                "request_sha256": values["request_sha256"],
                "proposal_sha256": values["proposal_sha256"],
                "payload_sha256": "d" * 64,
                "payload": dict(values["proposal"]),
                "replayed": False,
            }

    monkeypatch.setattr(runtime, "project_graph_proposal_ledger", FakeLedger())
    result = project_graph.invalidate_graph(
        project_id="project-a",
        body=project_graph.InvalidateGraphInput(
            source_node_id="source",
            target_node_ids=("target",),
            reason="source evidence changed",
            idempotency_key="invalidate-1",
            expected_revision=2,
        ),
        principal=principal,
        store_ref="store-a",
    )

    assert result["persisted"] is True
    assert result["external_write_allowed"] is False
    assert result["replay"]["revision"] == 3
    assert captured["kind"] == "invalidation"
    assert captured["expected_revision"] == 2
    assert captured["proposal"]["external_write_allowed"] is False


def test_proposal_ledger_reads_reauthorize_graph_scope(monkeypatch):
    principal = Principal(
        actor_id="monitor",
        roles=frozenset({"monitor"}),
        tenant_ref="tenant-a",
        store_refs=frozenset({"store-a"}),
    )
    graph = {
        "scope": {"entity_ref": "entity-a", "store_ref": "store-a"},
        "nodes": [],
        "edges": [],
        "tasks": [],
    }
    monkeypatch.setattr(project_graph, "_graph", lambda *_args, **_kwargs: graph)

    class FakeLedger:
        def history(self, **values):
            assert values["tenant_id"] == "tenant-a"
            assert values["entity_id"] == "entity-a"
            return ({"proposal_id": "pgp-1", "external_write_allowed": False},)

        def replay(self, **values):
            assert values["entity_id"] == "entity-a"
            return {
                "proposal_id": "pgp-1",
                "payload": {"status": "proposed", "external_write_allowed": False},
                "replayed": True,
            }

        def get(self, **values):
            assert values["entity_id"] == "entity-a"
            return {
                "proposal_id": values["proposal_id"],
                "payload": {"status": "proposed", "external_write_allowed": False},
                "replayed": False,
            }

    monkeypatch.setattr(runtime, "project_graph_proposal_ledger", FakeLedger())
    listed = project_graph.graph_proposals(
        project_id="project-a", principal=principal, store_ref="store-a"
    )
    replayed = project_graph.replay_graph_proposal(
        project_id="project-a",
        principal=principal,
        idempotency_key="dispatch-1",
        kind="dispatch-wave",
        store_ref="store-a",
    )
    detail = project_graph.graph_proposal(
        project_id="project-a",
        proposal_id="pgp-1",
        principal=principal,
        store_ref="store-a",
    )

    assert listed["status"] == "valid"
    assert listed["items"][0]["proposal_id"] == "pgp-1"
    assert replayed["status"] == "replayed"
    assert detail["proposal"]["status"] == "proposed"
    assert detail["external_write_allowed"] is False
