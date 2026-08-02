from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apps.control_plane.agent_harness import (
    GoalTaskRow,
    GraphNodeRow,
    GraphNodeStatusBindingRow,
    GraphProjectRow,
    HarnessObservationRow,
    VerifierRegistryRow,
)
from apps.control_plane.native_parity_acceptance import (
    ACCEPTANCE_DIMENSIONS,
    NativeParityAcceptanceWorkspace,
    RegistryMappingAcceptanceRecords,
)
from apps.control_plane.native_parity_graph import SqlNativeParityAcceptanceRecords
from apps.control_plane.security import Principal
from apps.control_plane.sql_repository import Base

NOW = datetime(2026, 8, 1, 8, tzinfo=UTC)
SCOPE = {
    "tenant_ref": "tenant-1",
    "entity_ref": "entity-1",
    "store_ref": "store-1",
    "provider_id": "dianxiaomi_erp",
    "capability_id": "listing_management",
    "capability_version": "1",
}
DIGEST = "a" * 64


def _hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _seed(engine, *, omitted=None, latest_state="passed", drift=None):
    omitted = omitted or set()
    drift = drift or {}
    with Session(engine) as session, session.begin():
        session.add(
            GraphProjectRow(
                id="project-1",
                tenant_ref=SCOPE["tenant_ref"],
                entity_ref=SCOPE["entity_ref"],
                store_ref=SCOPE["store_ref"],
                title="Native parity acceptance",
                lifecycle="active",
                baseline_sha256=DIGEST,
                goal_contract_sha256="b" * 64,
                created_at=NOW - timedelta(days=2),
            )
        )
        for dimension in ACCEPTANCE_DIMENSIONS:
            if dimension in omitted:
                continue
            verifier_id = f"native-parity-{dimension}"
            contract = {
                "id": verifier_id,
                "version": "1",
                "source_type": "external_graph",
                "authority": "external_verifier",
                "success_states": ["passed"],
                "freshness_seconds": 86400,
            }
            session.add(
                VerifierRegistryRow(
                    id=verifier_id,
                    version="1",
                    source_type=contract["source_type"],
                    authority=contract["authority"],
                    success_states_json=["passed"],
                    freshness_seconds=86400,
                    contract_sha256=_hash(contract),
                    enabled=True,
                    created_at=NOW - timedelta(days=2),
                )
            )
            task_id = f"task-{dimension}"
            node_id = f"node-{dimension}"
            task = GoalTaskRow(
                id=task_id,
                project_id="project-1",
                title=dimension,
                owner="verification",
                verifier_id=verifier_id,
                verifier_version="1",
                dependency_ids_json=[],
                verification_condition="fresh external observation passed",
                next_safe_action="rerun verifier",
                workspace="/native-parity",
                sla_seconds=86400,
                fingerprint=_hash(["project-1", task_id]),
                created_at=NOW - timedelta(days=2),
            )
            session.add(task)
            input_sha = drift.get("input_sha", DIGEST)
            evidence_sha = "d" * 64
            node_scope = {
                **SCOPE,
                "dimension": dimension,
                "acceptance_input_sha256": input_sha,
                "evidence_sha256": evidence_sha,
                "producer_id": "independent-verifier-worker",
            }
            node = GraphNodeRow(
                id=node_id,
                project_id="project-1",
                graph_kind="native_parity_acceptance",
                stable_key=f"native-parity:{dimension}",
                node_type=(
                    "native_parity_external_graph_verifier"
                    if dimension == "external_graph_verifier"
                    else "native_parity_artifact_dimension"
                ),
                label=dimension,
                authority="canonical",
                source=f"native-parity-source:{dimension}",
                scope_json=node_scope,
                version="1",
                content_sha256="e" * 64,
                artifact_ref=f"artifact:{dimension}",
                created_at=NOW - timedelta(days=2),
            )
            session.add(node)
            binding_payload = {
                "project_id": "project-1",
                "node_id": node_id,
                "task_id": task_id,
                "binding_role": "status_source",
            }
            session.add(
                GraphNodeStatusBindingRow(
                    id=f"binding-{dimension}",
                    project_id="project-1",
                    node_id=node_id,
                    task_id=task_id,
                    binding_role="status_source",
                    content_sha256=_hash(binding_payload),
                    created_at=NOW - timedelta(days=2),
                )
            )
            state = latest_state if dimension == "code" else "passed"
            summary = f"{dimension} {state}"
            artifact_ref = f"artifact:{dimension}"
            evidence_ref = f"evidence:{dimension}"
            result_sha = _hash(
                {
                    "state": state,
                    "summary": summary,
                    "artifact_ref": artifact_ref,
                    "evidence_ref": evidence_ref,
                }
            )
            observed_at = NOW - timedelta(hours=1)
            observation_scope = {
                **SCOPE,
                "dimension": dimension,
                "acceptance_input_sha256": input_sha,
                "subject_sha256": node.content_sha256,
                "evidence_sha256": evidence_sha,
                "producer_id": "independent-verifier-worker",
                "verifier_kind": (
                    "external_graph"
                    if dimension == "external_graph_verifier"
                    else "external_harness"
                ),
            }
            observation_scope.update(drift.get("observation_scope", {}))
            session.add(
                HarnessObservationRow(
                    id=f"observation-{dimension}",
                    project_id="project-1",
                    task_id=task_id,
                    verifier_id=verifier_id,
                    verifier_version="1",
                    source=node.source,
                    scope_json=observation_scope,
                    state=state,
                    summary=summary,
                    input_sha256=input_sha,
                    result_sha256=result_sha,
                    authority="external_verifier",
                    artifact_ref=artifact_ref,
                    evidence_ref=evidence_ref,
                    observed_at=observed_at,
                    fresh_until=observed_at + timedelta(days=1),
                    # Server-derived Harness actor bound to this verifier.
                    recorded_by=verifier_id,
                    recorded_at=observed_at + timedelta(minutes=1),
                )
            )


def _adapter(engine):
    return SqlNativeParityAcceptanceRecords(
        engine=engine,
        mappings=RegistryMappingAcceptanceRecords(
            [(SCOPE["provider_id"], SCOPE["capability_id"], SCOPE["capability_version"])]
        ),
    )


def _workspace(engine):
    return NativeParityAcceptanceWorkspace(
        records=_adapter(engine),
        external_verifier_ids={f"native-parity-{item}" for item in ACCEPTANCE_DIMENSIONS},
    ).project(
        principal=Principal(
            actor_id="operator-1",
            tenant_ref=SCOPE["tenant_ref"],
            roles=frozenset({"operator"}),
            store_refs=frozenset({SCOPE["store_ref"]}),
        ),
        entity_scope={
            "status": "ready",
            "tenant_ref": SCOPE["tenant_ref"],
            "entity_ref": SCOPE["entity_ref"],
            "store_ref": SCOPE["store_ref"],
            "authority_sha256": "f" * 64,
        },
        store_ref=SCOPE["store_ref"],
        as_of=NOW,
    )


def test_complete_exact_scope_graph_bundle_is_consumable_and_verified():
    engine = _engine()
    _seed(engine)

    records = _adapter(engine).read_records(
        tenant_ref=SCOPE["tenant_ref"],
        entity_ref=SCOPE["entity_ref"],
        store_ref=SCOPE["store_ref"],
        as_of=NOW,
    )
    assert len(records) == 9
    assert {row.get("dimension") for row in records[1:]} == set(ACCEPTANCE_DIMENSIONS)
    projected = _workspace(engine)
    assert projected["counts"]["states"]["verified_native"] == 1
    assert projected["items"][0]["state"] == "verified_native"


def test_incomplete_graph_bundle_emits_only_mapping_and_stays_gated():
    engine = _engine()
    _seed(engine, omitted={"web"})

    records = _adapter(engine).read_records(
        tenant_ref=SCOPE["tenant_ref"],
        entity_ref=SCOPE["entity_ref"],
        store_ref=SCOPE["store_ref"],
        as_of=NOW,
    )
    assert len(records) == 1
    projected = _workspace(engine)
    assert projected["items"][0]["state"] == "gated"


def test_latest_failed_is_emitted_and_blocks_acceptance():
    engine = _engine()
    _seed(engine, latest_state="failed")
    projected = _workspace(engine)
    assert projected["items"][0]["state"] == "blocked"
    assert projected["items"][0]["failed_dimensions"] == ["code"]


def test_cross_scope_observation_is_explicitly_blocked():
    engine = _engine()
    _seed(engine, drift={"observation_scope": {"store_ref": "other-store"}})
    projected = _workspace(engine)
    assert projected["items"][0]["state"] == "blocked"
    assert projected["items"][0]["invalid_records"]


def test_input_hash_drift_is_explicitly_blocked():
    engine = _engine()
    _seed(engine, drift={"input_sha": "9" * 64})
    with Session(engine) as session, session.begin():
        node = session.get(GraphNodeRow, "node-web")
        node.scope_json = {**node.scope_json, "acceptance_input_sha256": DIGEST}
    projected = _workspace(engine)
    assert projected["items"][0]["state"] == "blocked"
    assert projected["items"][0]["invalid_records"]


def test_stale_latest_observation_is_preserved_for_workspace_stale_state():
    engine = _engine()
    _seed(engine)
    with Session(engine) as session, session.begin():
        observation = session.get(HarnessObservationRow, "observation-code")
        observation.observed_at = NOW - timedelta(days=2)
        observation.fresh_until = NOW - timedelta(days=1)
        observation.recorded_at = NOW - timedelta(days=2) + timedelta(minutes=1)
    projected = _workspace(engine)
    assert projected["items"][0]["state"] == "stale"
    assert projected["items"][0]["stale_dimensions"] == ["code"]


def test_present_node_contract_corruption_is_explicitly_blocked():
    engine = _engine()
    _seed(engine)
    with Session(engine) as session, session.begin():
        session.get(GraphNodeRow, "node-code").content_sha256 = "not-a-digest"
    assert _workspace(engine)["items"][0]["state"] == "blocked"


def test_latest_verifier_kind_corruption_is_explicitly_blocked():
    engine = _engine()
    _seed(engine)
    with Session(engine) as session, session.begin():
        observation = session.get(HarnessObservationRow, "observation-code")
        observation.scope_json = {**observation.scope_json, "verifier_kind": "self_report"}
    assert _workspace(engine)["items"][0]["state"] == "blocked"
