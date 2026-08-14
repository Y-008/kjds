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
    "docs/project/evidence/20260729_BAS_141_NATIVE_SCOPED_OMS.md"
)

TASK_SPECS = (
    (
        "task-bas141-pytest",
        "BAS-141 native scoped OMS contracts",
        "tests",
        ("task-bas140-evidence",),
        "/engineering-graph",
    ),
    (
        "task-bas141-runtime",
        "BAS-141 authenticated no-data OMS runtime",
        "runtime",
        ("task-bas141-pytest",),
        "/runtime-graph",
    ),
    (
        "task-bas141-web",
        "BAS-141 desktop and 390px OMS workbench",
        "web",
        ("task-bas141-runtime",),
        "/oms",
    ),
    (
        "task-bas141-evidence",
        "BAS-141 immutable engineering Evidence",
        "evidence",
        ("task-bas141-web",),
        "/evidence-graph",
    ),
)

NODE_SPECS = (
    (
        "requirements",
        "requirement:BR-115@master-8.44",
        "requirement",
        "BR-115 native scoped OMS timeline",
        "docs/project/MASTER_SPEC.md",
        "task-bas141-pytest",
    ),
    (
        "requirements",
        "adr:ADR-0061",
        "adr",
        "ADR-0061 native scoped OMS timeline",
        "docs/adr/ADR-0061-native-scoped-oms-timeline.md",
        "task-bas141-pytest",
    ),
    (
        "engineering",
        "service:order-fact-semantics",
        "service",
        "Shared Ozon Order Fact semantics",
        "apps/control_plane/order_fact_semantics.py",
        "task-bas141-pytest",
    ),
    (
        "engineering",
        "service:scoped-oms-v1",
        "service",
        "ScopedOmsWorkspace v1",
        "apps/control_plane/scoped_oms.py",
        "task-bas141-pytest",
    ),
    (
        "engineering",
        "test:scoped-oms",
        "test",
        "Scoped OMS service and API tests",
        "tests/test_scoped_oms.py",
        "task-bas141-pytest",
    ),
    (
        "runtime",
        "api:scoped-oms-no-data",
        "api_probe",
        "Authenticated OMS no-data and no-write boundary",
        "http://127.0.0.1:8000/v1/oms/workspace",
        "task-bas141-runtime",
    ),
    (
        "runtime",
        "web:native-oms-390",
        "browser_probe",
        "Native OMS desktop and 390px workbench",
        "output/playwright/release-0.59.0/native-oms-mobile-390.png",
        "task-bas141-web",
    ),
    (
        "evidence",
        "evidence:BAS-141",
        "evidence",
        "BAS-141 native scoped OMS engineering Evidence",
        EVIDENCE,
        "task-bas141-evidence",
    ),
    (
        "project",
        "plan:BAS-141@plan-9.34",
        "task",
        "BAS-141 DONE_ENGINEERING; real Order Facts no_data",
        "docs/project/03_REMAINING_WORK_AND_PARALLEL_PLAN.md",
        "task-bas141-evidence",
    ),
)

EDGE_SPECS = (
    (
        "requirement:BR-115@master-8.44",
        "specified_by",
        "adr:ADR-0061",
        "requirements",
    ),
    (
        "adr:ADR-0061",
        "uses",
        "service:order-fact-semantics",
        "engineering",
    ),
    (
        "service:order-fact-semantics",
        "implemented_by",
        "service:scoped-oms-v1",
        "engineering",
    ),
    (
        "service:scoped-oms-v1",
        "verified_by",
        "test:scoped-oms",
        "engineering",
    ),
    (
        "test:scoped-oms",
        "observed_as",
        "api:scoped-oms-no-data",
        "runtime",
    ),
    (
        "api:scoped-oms-no-data",
        "rendered_by",
        "web:native-oms-390",
        "runtime",
    ),
    (
        "web:native-oms-390",
        "recorded_in",
        "evidence:BAS-141",
        "evidence",
    ),
    (
        "evidence:BAS-141",
        "closes",
        "plan:BAS-141@plan-9.34",
        "project",
    ),
)


def file_sha(relative: str) -> str:
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def run_checked(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def observe() -> dict[str, dict[str, str]]:
    pytest_process = run_checked(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_sale_triggered_procurement.py",
            "tests/test_scoped_oms.py",
            "tests/test_api_contract.py",
            "tests/test_security.py",
            "-q",
            "-p",
            "no:cacheprovider",
            "--basetemp=output/pytest/bas141-graph",
        ]
    )
    pytest_text = pytest_process.stdout + pytest_process.stderr
    if "69 passed" not in pytest_text or "[100%]" not in pytest_text:
        raise RuntimeError("BAS-141 focused pytest observation did not pass")

    engine = create_database_engine()
    with engine.connect() as connection:
        revision = str(
            connection.execute(
                text("select version_num from alembic_version")
            ).scalar_one()
        )
        fact_count = int(
            connection.execute(
                text(
                    "select count(*) from fact_records "
                    "where fact_type in ('ozon_order','ozon_return')"
                )
            ).scalar_one()
        )
        task_count_before = int(
            connection.execute(
                text("select count(*) from operating_tasks")
            ).scalar_one()
        )
    if revision != "20260729_0072" or fact_count != 0:
        raise RuntimeError("BAS-141 runtime truth is not 0072/no_data")

    compose_rows = [
        json.loads(line)
        for line in run_checked(
            ["docker", "compose", "ps", "--format", "json"]
        ).stdout.splitlines()
        if line.strip()
    ]
    required = {"api", "media-worker", "postgres", "web"}
    healthy = {
        row["Service"]
        for row in compose_rows
        if row.get("State") == "running"
        and row.get("Health") == "healthy"
    }
    if not required <= healthy:
        raise RuntimeError("BAS-141 delivery containers are not healthy")

    api_key = run_checked(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "api",
            "printenv",
            "KJDS_API_KEY",
        ]
    ).stdout.strip()
    if not api_key:
        raise RuntimeError("runtime API identity is not configured")
    base = "http://127.0.0.1:8000"
    headers = {"X-KJDS-API-Key": api_key}
    readiness = httpx.get(f"{base}/health/ready", timeout=10)
    anonymous = httpx.get(f"{base}/v1/oms/workspace", timeout=10)
    scoped = httpx.get(
        f"{base}/v1/oms/workspace",
        params={"store_ref": STORE_REF},
        headers=headers,
        timeout=10,
    )
    forbidden = httpx.get(
        f"{base}/v1/oms/workspace",
        params={"store_ref": "other-store"},
        headers=headers,
        timeout=10,
    )
    if (
        readiness.status_code != 200
        or readiness.json().get("version") != "0.59.0"
        or readiness.json().get("database", {}).get("status") != "ok"
        or anonymous.status_code != 401
        or scoped.status_code != 200
        or forbidden.status_code != 403
    ):
        raise RuntimeError("BAS-141 live auth/readiness boundary drifted")
    payload = scoped.json()
    if (
        payload.get("status") != "no_data"
        or payload.get("scope", {}).get("entity_ref") is not None
        or payload.get("counts", {}).get("total_current_orders") != 0
        or payload.get("counts", {}).get("legacy_orders_read") != 0
        or payload.get("control_envelope", {}).get(
            "external_write_allowed"
        )
        is not False
    ):
        raise RuntimeError("BAS-141 no-data/no-write contract drifted")
    with engine.connect() as connection:
        task_count_after = int(
            connection.execute(
                text("select count(*) from operating_tasks")
            ).scalar_one()
        )
    if task_count_after != task_count_before:
        raise RuntimeError("BAS-141 read verification created a task")

    desktop = (
        "output/playwright/release-0.59.0/native-oms-desktop.png"
    )
    mobile = (
        "output/playwright/release-0.59.0/native-oms-mobile-390.png"
    )
    expected = {
        desktop: (
            "1eafede55ea7ff7bd70ebc7735eb2b7ca"
            "67f400b8f6eb27c3c4712bc33007a68"
        ),
        mobile: (
            "17e2dc88d4e4eac186edcb8608debb52c"
            "113b4a90ff7c22431daf1003fde79c2"
        ),
    }
    if any(file_sha(path) != digest for path, digest in expected.items()):
        raise RuntimeError("BAS-141 browser Evidence hash drifted")

    return {
        "tests": {
            "state": "passed",
            "summary": "69 scoped OMS, procurement, API and security tests passed",
            "input_sha256": _sha(
                [
                    file_sha("apps/control_plane/order_fact_semantics.py"),
                    file_sha("apps/control_plane/scoped_oms.py"),
                    file_sha("tests/test_scoped_oms.py"),
                ]
            ),
            "artifact_ref": "process:pytest BAS-141 focused contracts",
        },
        "runtime": {
            "state": "passed",
            "summary": (
                "four containers healthy; PostgreSQL 0072; OMS 401/403/"
                "200-no_data; formal order Facts 0; no task mutation"
            ),
            "input_sha256": _sha(
                {
                    "revision": revision,
                    "fact_count": fact_count,
                    "task_count": task_count_after,
                    "service": file_sha(
                        "apps/control_plane/scoped_oms.py"
                    ),
                }
            ),
            "artifact_ref": f"{base}/v1/oms/workspace",
        },
        "web": {
            "state": "passed",
            "summary": (
                "authenticated desktop 1440 and mobile 390 OMS rendered "
                "no_data with zero horizontal overflow"
            ),
            "input_sha256": _sha(expected),
            "artifact_ref": mobile,
        },
        "evidence": {
            "state": "passed",
            "summary": f"BAS-141 Evidence SHA-256 {file_sha(EVIDENCE)}",
            "input_sha256": file_sha(EVIDENCE),
            "artifact_ref": EVIDENCE,
        },
    }


def upsert_graph(observations: dict[str, dict[str, str]]) -> None:
    engine = create_database_engine()
    service = AgentHarnessService(engine)
    now = datetime.now(UTC)
    verifier_defs = {
        "tests": ("pytest_process", "test_process"),
        "runtime": ("http_and_docker_probe", "runtime"),
        "web": ("playwright_measurement", "browser"),
        "evidence": ("immutable_artifact", "evidence"),
    }
    for verifier_id, (source_type, authority) in verifier_defs.items():
        service.register_verifier(
            {
                "id": f"bas141-{verifier_id}",
                "version": "1",
                "source_type": source_type,
                "authority": authority,
                "success_states": ["passed"],
                "freshness_seconds": 604800,
            }
        )

    with Session(engine) as session, session.begin():
        if session.get(GraphProjectRow, PROJECT_ID) is None:
            raise RuntimeError("canonical KJDS 0.59 Graph project is missing")
        if session.get(GoalTaskRow, "task-bas140-evidence") is None:
            raise RuntimeError("BAS-140 dependency is missing")
        for task_id, title, verifier, dependencies, workspace in TASK_SPECS:
            if session.get(GoalTaskRow, task_id) is None:
                session.add(
                    GoalTaskRow(
                        id=task_id,
                        project_id=PROJECT_ID,
                        title=title,
                        owner="oms-engineering",
                        verifier_id=f"bas141-{verifier}",
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

        for kind, stable_key, node_type, label, artifact, _task in NODE_SPECS:
            node_id = f"gn_{_sha([PROJECT_ID, kind, stable_key])[:32]}"
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
            existing_node = session.get(GraphNodeRow, node_id)
            if existing_node is None:
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
            else:
                existing_node.node_type = node_type
                existing_node.label = label
                existing_node.source = artifact
                existing_node.content_sha256 = _sha(content)
                existing_node.artifact_ref = artifact
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

    for kind, stable_key, _type, _label, _artifact, task_id in NODE_SPECS:
        service.bind_node_status(
            project_id=PROJECT_ID,
            node_id=f"gn_{_sha([PROJECT_ID, kind, stable_key])[:32]}",
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
                "verifier_id": f"bas141-{verifier}",
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
            label: int(
                session.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(model.project_id == PROJECT_ID)
                )
                or 0
            )
            for label, model in (
                ("tasks", GoalTaskRow),
                ("nodes", GraphNodeRow),
                ("edges", GraphEdgeRow),
                ("observations", HarnessObservationRow),
            )
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
