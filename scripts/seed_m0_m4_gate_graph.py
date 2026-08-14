from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from apps.control_plane.agent_harness import (
    AgentHarnessService,
    GoalTaskRow,
    GraphEdgeRow,
    GraphNodeRow,
    GraphProjectRow,
    HarnessObservationRow,
    _sha,
)
from apps.control_plane.database import create_database_engine
from apps.control_plane.operating_gate_verifier import OperatingStageVerifier
from apps.control_plane.runtime import runtime
from apps.control_plane.security import Principal

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ID = "kjds-059-bas123"
STORE_REF = "ozon-primary"
VERIFIER_ID = "m0m4-commerce-os"
VERIFIER_VERSION = "1"
EVIDENCE = (
    "docs/project/evidence/"
    "20260728_BAS_126_DYNAMIC_SCOPED_OPERATING_GATE_VERIFIER.md"
)
OLD_VERIFIER = ("m0m4-real-postgres", "1")


def file_sha(relative: str) -> str:
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def gate_node_label(gate_id: str, gate: dict[str, Any]) -> str:
    return (
        f"{gate_id.upper()} {gate['state']} · "
        f"stages={','.join(gate['source_stage_ids'])} · "
        f"blockers={len(gate['blockers'])}"
    )


def observe() -> dict[str, Any]:
    engine = create_database_engine()
    queries = {
        "revision": "select version_num from alembic_version",
        "scope_grants": "select count(*) from scope_grant_events",
        "native_imports": (
            "select count(*) from import_jobs where tenant_ref is not null"
        ),
        "native_products": (
            "select count(*) from products where tenant_ref is not null"
        ),
        "native_facts": (
            "select count(*) from fact_records where tenant_ref is not null"
        ),
        "content_assets": "select count(*) from content_assets",
        "profit_scenarios": "select count(*) from profit_scenarios",
        "listing_drafts": "select count(*) from listing_drafts",
        "native_pilots": (
            "select count(*) from read_only_pilots where tenant_ref is not null"
        ),
        "limited_execution_receipts": (
            "select count(*) from limited_execution_receipts"
        ),
        "orders": "select count(*) from orders",
        "finance_entries": "select count(*) from finance_entries",
        "reconciliation_runs": "select count(*) from reconciliation_runs",
    }
    with engine.connect() as connection:
        values = {
            name: connection.execute(text(query)).scalar_one()
            for name, query in queries.items()
        }
    if values["revision"] != "20260728_0070":
        raise RuntimeError("gate observation requires real database revision 0070")
    support_counts = {
        name: int(value)
        for name, value in values.items()
        if name != "revision"
    }
    now = datetime.now(UTC)
    bucket = now.replace(minute=0, second=0, microsecond=0)
    monitor = Principal(
        actor_id="m0m4-gate-observer",
        roles=frozenset({"monitor"}),
        tenant_ref="default",
        store_refs=frozenset({STORE_REF}),
    )
    workspace = runtime.commerce_os.workspace(
        principal=monitor,
        store_ref=STORE_REF,
        as_of=bucket.isoformat(),
    )
    result = OperatingStageVerifier().evaluate(
        workspace=workspace,
        support_counts=support_counts,
        observation_bucket=bucket.isoformat(),
    )
    return {
        "observed_at": now,
        "observation_bucket": bucket.isoformat(),
        "database_revision": values["revision"],
        "support_counts": support_counts,
        "workspace": workspace,
        "result": result,
    }


def seed(observation: dict[str, Any]) -> None:
    engine = create_database_engine()
    service = AgentHarnessService(engine)
    now = observation["observed_at"]
    result = observation["result"]
    service.register_verifier(
        {
            "id": VERIFIER_ID,
            "version": VERIFIER_VERSION,
            "source_type": "commerce_os_projection",
            "authority": "runtime",
            "success_states": ["passed"],
            "freshness_seconds": 3600,
        }
    )
    task_specs = (
        (
            "task-m0-current-authority",
            "M0 current authority and real candidate",
            ("task-bas124-evidence",),
        ),
        (
            "task-m1-formal-fact-chain",
            "M1 native import, Product and formal Fact",
            ("task-m0-current-authority",),
        ),
        (
            "task-m2-content-profit-listing",
            "M2 Evidence-complete content, profit and listing",
            ("task-m1-formal-fact-chain",),
        ),
        (
            "task-m3-pilot-order-settlement",
            "M3 governed Pilot, order and settlement",
            ("task-m2-content-profit-listing",),
        ),
        (
            "task-m4-actual-cash",
            "M4 bank-reconciled actual-cash CM3",
            ("task-m3-pilot-order-settlement",),
        ),
    )
    gates = result["gates"]
    node_specs = (
        (
            "requirements",
            "requirement:BR-102",
            "business_requirement",
            "BR-102 Dynamic scoped M0→M4 verifier",
            "docs/project/MASTER_SPEC.md",
            file_sha("docs/project/MASTER_SPEC.md"),
            "canonical",
        ),
        (
            "engineering",
            "adr:ADR-0050",
            "architecture_decision",
            "ADR-0050 Dynamic scoped operating Gate verifier",
            "docs/adr/ADR-0050-dynamic-scoped-operating-gate-verifier.md",
            file_sha(
                "docs/adr/ADR-0050-dynamic-scoped-operating-gate-verifier.md"
            ),
            "canonical",
        ),
        (
            "engineering",
            "module:operating-stage-verifier",
            "deep_module",
            "OperatingStageVerifier pure verification seam",
            "apps/control_plane/operating_gate_verifier.py",
            file_sha("apps/control_plane/operating_gate_verifier.py"),
            "canonical",
        ),
        (
            "runtime",
            "observation:m0m4-commerce-os",
            "verifier_observation",
            (
                "Scoped Commerce OS and PostgreSQL M0→M4 observation "
                f"{observation['observation_bucket']}"
            ),
            f"verifier:{VERIFIER_ID}@{VERIFIER_VERSION}",
            result["result_sha256"],
            "observed",
        ),
        (
            "evidence",
            "evidence:BAS-126",
            "release_evidence",
            "BAS-126 dynamic scoped operating Gate verifier Evidence",
            EVIDENCE,
            file_sha(EVIDENCE),
            "canonical",
        ),
        (
            "project",
            "plan:BAS-126",
            "delivery_task",
            "BAS-126 dynamic scoped M0→M4 Gate verifier",
            "docs/project/03_REMAINING_WORK_AND_PARALLEL_PLAN.md",
            file_sha("docs/project/03_REMAINING_WORK_AND_PARALLEL_PLAN.md"),
            "canonical",
        ),
    )
    graph_edges = (
        (
            "requirement:BR-102",
            "decided_by",
            "adr:ADR-0050",
            "requirements",
        ),
        (
            "adr:ADR-0050",
            "implemented_by",
            "module:operating-stage-verifier",
            "engineering",
        ),
        (
            "module:operating-stage-verifier",
            "observed_as",
            "observation:m0m4-commerce-os",
            "runtime",
        ),
        (
            "observation:m0m4-commerce-os",
            "recorded_in",
            "evidence:BAS-126",
            "evidence",
        ),
        (
            "evidence:BAS-126",
            "closes_engineering",
            "plan:BAS-126",
            "project",
        ),
    )

    with Session(engine) as session, session.begin():
        if not session.get(GraphProjectRow, PROJECT_ID):
            raise RuntimeError("canonical graph project does not exist")
        for index, (
            task_id,
            _title,
            dependencies,
        ) in enumerate(task_specs):
            gate = gates[f"m{index}"]
            task = session.get(GoalTaskRow, task_id)
            if task is None:
                raise RuntimeError(f"canonical Gate task missing: {task_id}")
            binding = (task.verifier_id, task.verifier_version)
            if binding not in {OLD_VERIFIER, (VERIFIER_ID, VERIFIER_VERSION)}:
                raise RuntimeError(
                    f"unexpected Gate task verifier binding: {task_id}={binding}"
                )
            if tuple(task.dependency_ids_json) != dependencies:
                raise RuntimeError(
                    f"unexpected Gate task dependencies: {task_id}"
                )
            task.verifier_id = VERIFIER_ID
            task.verifier_version = VERIFIER_VERSION
            task.verification_condition = (
                "fresh scoped Commerce OS stages and real PostgreSQL support "
                "counts satisfy this exact sequential Gate"
            )
            task.next_safe_action = gate["next_action"]
            task.workspace = gate["workspace"]

        for (
            kind,
            stable_key,
            node_type,
            label,
            artifact,
            content_sha,
            authority,
        ) in node_specs:
            node_id = f"gn_{_sha([PROJECT_ID, kind, stable_key])[:32]}"
            node = session.get(GraphNodeRow, node_id)
            if node is None:
                session.add(
                    GraphNodeRow(
                        id=node_id,
                        project_id=PROJECT_ID,
                        graph_kind=kind,
                        stable_key=stable_key,
                        node_type=node_type,
                        label=label,
                        authority=authority,
                        source=artifact,
                        scope_json={
                            "tenant_ref": "default",
                            "store_ref": STORE_REF,
                        },
                        version=VERIFIER_VERSION,
                        content_sha256=content_sha,
                        artifact_ref=artifact,
                        created_at=now,
                    )
                )
            elif (
                node.graph_kind != kind
                or node.stable_key != stable_key
                or node.node_type != node_type
                or node.authority != authority
                or node.source != artifact
                or node.artifact_ref != artifact
            ):
                raise RuntimeError(f"canonical Graph node drift: {stable_key}")
            elif authority == "observed":
                node.label = label
                node.version = observation["observation_bucket"]
                node.content_sha256 = content_sha
            else:
                node.version = content_sha[:12]
                node.content_sha256 = content_sha

        for index in range(5):
            stable_key = f"gate-state:M{index}"
            gate_node = session.scalar(
                select(GraphNodeRow).where(
                    GraphNodeRow.project_id == PROJECT_ID,
                    GraphNodeRow.stable_key == stable_key,
                )
            )
            if gate_node is None or gate_node.authority != "observed":
                raise RuntimeError(f"observed Gate node missing or drifted: {stable_key}")
            gate = gates[f"m{index}"]
            gate_node.label = gate_node_label(f"m{index}", gate)
            gate_node.source = gate["artifact_ref"]
            gate_node.artifact_ref = gate["artifact_ref"]
            gate_node.version = observation["observation_bucket"]
            gate_node.content_sha256 = _sha(
                {
                    "stable_key": stable_key,
                    "state": gate["state"],
                    "summary": gate["summary"],
                    "input_sha256": gate["input_sha256"],
                    "artifact_ref": gate["artifact_ref"],
                }
            )

        session.flush()
        by_key = {
            row.stable_key: row
            for row in session.scalars(
                select(GraphNodeRow).where(
                    GraphNodeRow.project_id == PROJECT_ID
                )
            )
        }
        for source, edge_type, target, kind in graph_edges:
            edge_id = (
                f"ge_{_sha([PROJECT_ID, kind, source, edge_type, target])[:32]}"
            )
            if session.get(GraphEdgeRow, edge_id):
                continue
            session.add(
                GraphEdgeRow(
                    id=edge_id,
                    project_id=PROJECT_ID,
                    graph_kind=kind,
                    source_node_id=by_key[source].id,
                    target_node_id=by_key[target].id,
                    edge_type=edge_type,
                    derivation_method="runtime",
                    confidence=100,
                    evidence_ref=EVIDENCE,
                    effective_from=now,
                    effective_until=None,
                    content_sha256=_sha(
                        [source, edge_type, target, "runtime", EVIDENCE]
                    ),
                )
            )

    monitor = Principal(
        actor_id="m0m4-gate-observer",
        roles=frozenset({"monitor"}),
        tenant_ref="default",
        store_refs=frozenset({STORE_REF}),
    )
    for index, task in enumerate(task_specs):
        gate = gates[f"m{index}"]
        service.record_observation(
            {
                "project_id": PROJECT_ID,
                "task_id": task[0],
                "verifier_id": VERIFIER_ID,
                "verifier_version": VERIFIER_VERSION,
                "source": "commerce_os_projection",
                "scope": {
                    "tenant_ref": "default",
                    "entity_ref": observation["workspace"]["scope"].get(
                        "entity_ref"
                    ),
                    "store_ref": STORE_REF,
                    "workspace_snapshot_sha256": observation["workspace"][
                        "snapshot_sha256"
                    ],
                },
                "state": gate["state"],
                "summary": gate["summary"],
                "input_sha256": gate["input_sha256"],
                "artifact_ref": gate["artifact_ref"],
                "evidence_ref": EVIDENCE,
                "observed_at": now.isoformat(),
                "store_ref": STORE_REF,
            },
            principal=monitor,
        )


def counts() -> dict[str, int]:
    engine = create_database_engine()
    with Session(engine) as session:
        return {
            name: int(
                session.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(model.project_id == PROJECT_ID)
                )
                or 0
            )
            for name, model in (
                ("tasks", GoalTaskRow),
                ("observations", HarnessObservationRow),
                ("nodes", GraphNodeRow),
                ("edges", GraphEdgeRow),
            )
        }


if __name__ == "__main__":
    observed = observe()
    seed(observed)
    print(
        json.dumps(
            {
                "project_id": PROJECT_ID,
                **counts(),
                "database_revision": observed["database_revision"],
                "observation_bucket": observed["observation_bucket"],
                "workspace_snapshot_sha256": observed["workspace"][
                    "snapshot_sha256"
                ],
                "result_sha256": observed["result"]["result_sha256"],
                "states": {
                    gate_id: gate["state"]
                    for gate_id, gate in observed["result"]["gates"].items()
                },
                "external_write_allowed": False,
                "model_self_certification_allowed": False,
            },
            sort_keys=True,
        )
    )
