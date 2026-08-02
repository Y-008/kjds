from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
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
from apps.control_plane.security import Principal

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ID = "kjds-059-bas123"
STORE_REF = "ozon-primary"
EVIDENCE = (
    "docs/project/evidence/"
    "20260729_BAS_140_SCOPED_SALE_TRIGGERED_PROCUREMENT.md"
)
POLICY_VERSION = "sale-triggered-jit/1.1.0"

TASK_SPECS = (
    (
        "task-bas140-pytest",
        "BAS-140 exact-scope order procurement contract",
        "tests",
        ("task-bas124-evidence",),
        "/engineering-graph",
    ),
    (
        "task-bas140-database",
        "BAS-140 real PostgreSQL 0072 preservation",
        "database",
        ("task-bas140-pytest",),
        "/runtime-graph",
    ),
    (
        "task-bas140-runtime",
        "BAS-140 authenticated no-write runtime boundary",
        "runtime",
        ("task-bas140-database",),
        "/agent-control",
    ),
    (
        "task-bas140-evidence",
        "BAS-140 immutable engineering Evidence",
        "evidence",
        ("task-bas140-runtime",),
        "/evidence-graph",
    ),
)

NODE_SPECS = (
    (
        "requirements",
        "requirement:BR-114@master-8.42",
        "requirement",
        "BR-114 exact-scope order-triggered procurement review",
        "docs/project/MASTER_SPEC.md",
        "task-bas140-pytest",
    ),
    (
        "requirements",
        "adr:ADR-0060",
        "adr",
        "ADR-0060 scoped sale-triggered procurement review",
        "docs/adr/ADR-0060-scoped-sale-triggered-procurement-review.md",
        "task-bas140-pytest",
    ),
    (
        "engineering",
        "service:sale-triggered-procurement-1.1.0",
        "service",
        "SaleTriggeredProcurementPolicy 1.1.0",
        "apps/control_plane/sale_triggered_procurement.py",
        "task-bas140-pytest",
    ),
    (
        "engineering",
        "test:sale-triggered-procurement",
        "test",
        "Exact-scope order and task handoff tests",
        "tests/test_sale_triggered_procurement.py",
        "task-bas140-pytest",
    ),
    (
        "engineering",
        "migration:0072",
        "migration",
        "0072 scoped current-order lookup index",
        "migrations/versions/20260729_0072_scoped_order_procurement.py",
        "task-bas140-database",
    ),
    (
        "runtime",
        "database:0072-bas140",
        "database_revision",
        "Real PostgreSQL 0072 with preserved business rows",
        "postgres:alembic_version,fact_records,pg_indexes",
        "task-bas140-database",
    ),
    (
        "runtime",
        "api:batch-opportunity-procurement-no-data",
        "api_probe",
        "Authenticated no-data and no-write procurement boundary",
        "http://127.0.0.1:8000/v1/batch-opportunities/latest",
        "task-bas140-runtime",
    ),
    (
        "evidence",
        "evidence:BAS-140",
        "evidence",
        "BAS-140 scoped procurement engineering Evidence",
        EVIDENCE,
        "task-bas140-evidence",
    ),
    (
        "project",
        "plan:BAS-140@plan-9.32",
        "task",
        "BAS-140 DONE_ENGINEERING; real order no_data",
        "docs/project/03_REMAINING_WORK_AND_PARALLEL_PLAN.md",
        "task-bas140-evidence",
    ),
)

EDGE_SPECS = (
    (
        "requirement:BR-114@master-8.42",
        "specified_by",
        "adr:ADR-0060",
        "requirements",
    ),
    (
        "adr:ADR-0060",
        "implemented_by",
        "service:sale-triggered-procurement-1.1.0",
        "engineering",
    ),
    (
        "service:sale-triggered-procurement-1.1.0",
        "verified_by",
        "test:sale-triggered-procurement",
        "engineering",
    ),
    (
        "test:sale-triggered-procurement",
        "migrated_by",
        "migration:0072",
        "engineering",
    ),
    (
        "migration:0072",
        "observed_as",
        "database:0072-bas140",
        "runtime",
    ),
    (
        "database:0072-bas140",
        "precedes",
        "api:batch-opportunity-procurement-no-data",
        "runtime",
    ),
    (
        "api:batch-opportunity-procurement-no-data",
        "recorded_in",
        "evidence:BAS-140",
        "evidence",
    ),
    (
        "evidence:BAS-140",
        "closes",
        "plan:BAS-140@plan-9.32",
        "project",
    ),
)


def file_sha(relative: str) -> str:
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def _run_checked(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def observe() -> dict[str, dict[str, str]]:
    pytest_process = _run_checked(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_sale_triggered_procurement.py",
            "tests/test_batch_opportunity.py",
            "tests/test_scoped_batch_opportunity.py",
            "-q",
            "-p",
            "no:cacheprovider",
            "--basetemp=.runtime/pytest-bas140-graph",
        ]
    )
    pytest_text = pytest_process.stdout + pytest_process.stderr
    if "46 passed" not in pytest_text or "[100%]" not in pytest_text:
        raise RuntimeError("BAS-140 focused pytest observation did not pass")

    engine = create_database_engine()
    with engine.connect() as connection:
        revision = str(
            connection.execute(
                text("select version_num from alembic_version")
            ).scalar_one()
        )
        fact_count = int(
            connection.execute(
                text("select count(*) from fact_records")
            ).scalar_one()
        )
        task_count_before = int(
            connection.execute(
                text("select count(*) from operating_tasks")
            ).scalar_one()
        )
        index_count = int(
            connection.execute(
                text(
                    "select count(*) from pg_indexes "
                    "where schemaname='public' and "
                    "indexname='ix_fact_scope_order_product_effective'"
                )
            ).scalar_one()
        )
    if revision != "20260729_0072" or index_count != 1:
        raise RuntimeError("real database is not at single indexed 0072")
    if fact_count != 0:
        raise RuntimeError("BAS-140 must not synthesize a real Ozon order")

    docker_process = _run_checked(
        ["docker", "compose", "ps", "--format", "json"]
    )
    container_rows = [
        json.loads(line)
        for line in docker_process.stdout.splitlines()
        if line.strip()
    ]
    required = {"api", "media-worker", "postgres", "web"}
    healthy = {
        row["Service"]
        for row in container_rows
        if row.get("State") == "running" and row.get("Health") == "healthy"
    }
    if not required <= healthy:
        raise RuntimeError("delivery containers are not all externally healthy")

    key_process = _run_checked(
        ["docker", "compose", "exec", "-T", "api", "printenv", "KJDS_API_KEY"]
    )
    api_key = key_process.stdout.strip()
    if not api_key:
        raise RuntimeError("runtime API identity is not configured")
    headers = {"X-KJDS-API-Key": api_key}
    base = "http://127.0.0.1:8000"
    readiness = httpx.get(f"{base}/health/ready", timeout=10)
    anonymous = httpx.get(
        f"{base}/v1/batch-opportunities/latest",
        params={"store_ref": STORE_REF},
        timeout=10,
    )
    authenticated = httpx.get(
        f"{base}/v1/batch-opportunities/latest",
        params={"store_ref": STORE_REF},
        headers=headers,
        timeout=10,
    )
    forbidden = httpx.get(
        f"{base}/v1/batch-opportunities/latest",
        params={"store_ref": "other-store"},
        headers=headers,
        timeout=10,
    )
    if (
        readiness.status_code != 200
        or readiness.json().get("version") != "0.59.0"
        or anonymous.status_code != 401
        or authenticated.status_code != 200
        or forbidden.status_code != 403
    ):
        raise RuntimeError("BAS-140 live auth/readiness boundary drifted")
    payload = authenticated.json()
    if (
        payload.get("status") != "no_data"
        or payload.get("control_envelope", {}).get(
            "external_write_allowed"
        )
        is not False
        or payload.get("scope", {}).get("entity_ref") is not None
        or "entity_scope_authority_missing"
        not in payload.get("source_gaps", [])
    ):
        raise RuntimeError("BAS-140 no-data/no-write runtime contract drifted")

    with engine.connect() as connection:
        task_count_after = int(
            connection.execute(
                text("select count(*) from operating_tasks")
            ).scalar_one()
        )
    if task_count_after != task_count_before:
        raise RuntimeError("read-only runtime verification created a task")

    evidence_sha = file_sha(EVIDENCE)
    return {
        "tests": {
            "state": "passed",
            "summary": "46 exact-scope procurement and batch tests passed",
            "input_sha256": _sha(
                [
                    file_sha("tests/test_sale_triggered_procurement.py"),
                    file_sha("tests/test_batch_opportunity.py"),
                    file_sha("tests/test_scoped_batch_opportunity.py"),
                ]
            ),
            "artifact_ref": (
                "process:pytest tests/test_sale_triggered_procurement.py "
                "tests/test_batch_opportunity.py "
                "tests/test_scoped_batch_opportunity.py"
            ),
        },
        "database": {
            "state": "passed",
            "summary": (
                f"real PostgreSQL {revision}; lookup index {index_count}; "
                f"formal Ozon order Facts {fact_count}"
            ),
            "input_sha256": file_sha(
                "migrations/versions/"
                "20260729_0072_scoped_order_procurement.py"
            ),
            "artifact_ref": "postgres:alembic_version,fact_records,pg_indexes",
        },
        "runtime": {
            "state": "passed",
            "summary": (
                "four containers healthy; readiness 200; anonymous 401; "
                "wrong-store 403; authenticated no_data; no task mutation"
            ),
            "input_sha256": _sha(
                {
                    "compose": file_sha("compose.yaml"),
                    "policy": file_sha(
                        "apps/control_plane/"
                        "sale_triggered_procurement.py"
                    ),
                    "policy_version": POLICY_VERSION,
                    "task_count": task_count_after,
                }
            ),
            "artifact_ref": (
                "http://127.0.0.1:8000/"
                "v1/batch-opportunities/latest"
            ),
        },
        "evidence": {
            "state": "passed",
            "summary": f"BAS-140 Evidence SHA-256 {evidence_sha}",
            "input_sha256": evidence_sha,
            "artifact_ref": EVIDENCE,
        },
    }


def upsert_graph(observations: dict[str, dict[str, str]]) -> None:
    engine = create_database_engine()
    service = AgentHarnessService(engine)
    now = datetime.now(UTC)
    verifier_defs = {
        "tests": ("pytest_process", "test_process"),
        "database": ("postgres_query", "database"),
        "runtime": ("http_and_docker_probe", "runtime"),
        "evidence": ("immutable_artifact", "evidence"),
    }
    for verifier_id, (source_type, authority) in verifier_defs.items():
        service.register_verifier(
            {
                "id": f"bas140-{verifier_id}",
                "version": "1",
                "source_type": source_type,
                "authority": authority,
                "success_states": ["passed"],
                "freshness_seconds": 604800,
            }
        )

    with Session(engine) as session, session.begin():
        project = session.get(GraphProjectRow, PROJECT_ID)
        if project is None:
            raise RuntimeError("canonical KJDS 0.59 Graph project is missing")
        if session.get(GoalTaskRow, "task-bas124-evidence") is None:
            raise RuntimeError("BAS-124 formal Fact dependency is missing")
        for task_id, title, verifier, dependencies, workspace in TASK_SPECS:
            existing = session.get(GoalTaskRow, task_id)
            if existing is None:
                session.add(
                    GoalTaskRow(
                        id=task_id,
                        project_id=PROJECT_ID,
                        title=title,
                        owner="oms-procurement-engineering",
                        verifier_id=f"bas140-{verifier}",
                        verifier_version="1",
                        dependency_ids_json=list(dependencies),
                        verification_condition=(
                            "fresh registered external observation is passed"
                        ),
                        next_safe_action=(
                            "inspect exact artifact and rerun bounded verifier"
                        ),
                        workspace=workspace,
                        sla_seconds=86400,
                        fingerprint=_sha([PROJECT_ID, task_id]),
                        created_at=now,
                    )
                )

        for kind, stable_key, node_type, label, artifact, _task_id in NODE_SPECS:
            node_id = f"gn_{_sha([PROJECT_ID, kind, stable_key])[:32]}"
            if session.get(GraphNodeRow, node_id) is not None:
                continue
            local_path = ROOT / artifact
            artifact_sha = (
                hashlib.sha256(local_path.read_bytes()).hexdigest()
                if local_path.is_file()
                else _sha(artifact)
            )
            content = {
                "stable_key": stable_key,
                "type": node_type,
                "label": label,
                "artifact": artifact,
                "artifact_sha256": artifact_sha,
            }
            session.add(
                GraphNodeRow(
                    id=node_id,
                    project_id=PROJECT_ID,
                    graph_kind=kind,
                    stable_key=stable_key,
                    node_type=node_type,
                    label=label,
                    authority="canonical",
                    source=artifact,
                    scope_json={
                        "tenant_ref": "default",
                        "store_ref": STORE_REF,
                    },
                    version="1",
                    content_sha256=_sha(content),
                    artifact_ref=artifact,
                    created_at=now,
                )
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
        for source, edge_type, target, kind in EDGE_SPECS:
            edge_id = (
                f"ge_{_sha([PROJECT_ID, kind, source, edge_type, target])[:32]}"
            )
            if session.get(GraphEdgeRow, edge_id) is not None:
                continue
            session.add(
                GraphEdgeRow(
                    id=edge_id,
                    project_id=PROJECT_ID,
                    graph_kind=kind,
                    source_node_id=by_key[source].id,
                    target_node_id=by_key[target].id,
                    edge_type=edge_type,
                    derivation_method="evidence",
                    confidence=100,
                    evidence_ref=EVIDENCE,
                    effective_from=now,
                    effective_until=None,
                    content_sha256=_sha(
                        [source, edge_type, target, EVIDENCE]
                    ),
                )
            )

    for (
        kind,
        stable_key,
        _node_type,
        _label,
        _artifact,
        task_id,
    ) in NODE_SPECS:
        node_id = f"gn_{_sha([PROJECT_ID, kind, stable_key])[:32]}"
        service.bind_node_status(
            project_id=PROJECT_ID,
            node_id=node_id,
            task_id=task_id,
        )

    monitor = Principal(
        actor_id="harness-seed",
        roles=frozenset({"admin"}),
        tenant_ref="default",
        store_refs=frozenset({STORE_REF}),
    )
    for task_id, _title, verifier, _dependencies, _workspace in TASK_SPECS:
        item = observations[verifier]
        service.record_observation(
            {
                "project_id": PROJECT_ID,
                "task_id": task_id,
                "verifier_id": f"bas140-{verifier}",
                "verifier_version": "1",
                "source": verifier_defs[verifier][0],
                "scope": {
                    "tenant_ref": "default",
                    "store_ref": STORE_REF,
                },
                "state": item["state"],
                "summary": item["summary"],
                "input_sha256": item["input_sha256"],
                "artifact_ref": item["artifact_ref"],
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
            "tasks": int(
                session.scalar(
                    select(func.count())
                    .select_from(GoalTaskRow)
                    .where(GoalTaskRow.project_id == PROJECT_ID)
                )
                or 0
            ),
            "observations": int(
                session.scalar(
                    select(func.count())
                    .select_from(HarnessObservationRow)
                    .where(HarnessObservationRow.project_id == PROJECT_ID)
                )
                or 0
            ),
            "nodes": int(
                session.scalar(
                    select(func.count())
                    .select_from(GraphNodeRow)
                    .where(GraphNodeRow.project_id == PROJECT_ID)
                )
                or 0
            ),
            "edges": int(
                session.scalar(
                    select(func.count())
                    .select_from(GraphEdgeRow)
                    .where(GraphEdgeRow.project_id == PROJECT_ID)
                )
                or 0
            ),
        }


if __name__ == "__main__":
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    observed = observe()
    upsert_graph(observed)
    print(
        json.dumps(
            {
                "project_id": PROJECT_ID,
                **counts(),
                "business_state": "no_data",
                "external_write_allowed": False,
            },
            sort_keys=True,
        )
    )
