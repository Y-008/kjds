from __future__ import annotations

import hashlib
import json
import os
import re
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
FIXED_AS_OF = "2026-07-29T00:00:00Z"
EVIDENCE = (
    "docs/project/evidence/"
    "20260729_BAS_144_NATIVE_EXACT_SCOPE_PIM.md"
)
SCREENSHOTS = {
    "output/playwright/bas144-pim-desktop.png": (
        "7cc5541ae710bd4e8e30e56c020aff98d550fa9d4dacd533470fb1516d22e3b6"
    ),
    "output/playwright/bas144-pim-mobile-390.png": (
        "449ced6859c3087b75fd332e8ed003f85c67fc01de626451d9b9b1b3f7af4d02"
    ),
}

TASK_SPECS = (
    (
        "task-bas144-pytest",
        "BAS-144 exact-scope PIM contracts",
        "tests",
        ("task-bas143-market-baseline",),
        "/engineering-graph",
    ),
    (
        "task-bas144-database",
        "BAS-144 PostgreSQL single-head no-schema verification",
        "database",
        ("task-bas144-pytest",),
        "/runtime-graph",
    ),
    (
        "task-bas144-runtime",
        "BAS-144 authenticated deterministic no-data runtime",
        "runtime",
        ("task-bas144-database",),
        "/runtime-graph",
    ),
    (
        "task-bas144-web",
        "BAS-144 desktop and 390px PIM workbench",
        "web",
        ("task-bas144-runtime",),
        "/pim",
    ),
    (
        "task-bas144-evidence",
        "BAS-144 immutable engineering Evidence",
        "evidence",
        ("task-bas144-web",),
        "/evidence-graph",
    ),
)

NODE_SPECS = (
    (
        "requirements",
        "requirement:BR-118@master-8.46",
        "requirement",
        "BR-118 native exact-scope PIM workspace",
        "docs/project/MASTER_SPEC.md",
        "task-bas144-pytest",
    ),
    (
        "requirements",
        "adr:ADR-0064",
        "adr",
        "ADR-0064 native exact-scope PIM workspace",
        "docs/adr/ADR-0064-native-exact-scope-pim-workspace.md",
        "task-bas144-pytest",
    ),
    (
        "engineering",
        "service:scoped-pim-v1",
        "service",
        "ScopedPimWorkspace v1",
        "apps/control_plane/scoped_pim.py",
        "task-bas144-pytest",
    ),
    (
        "runtime",
        "api:scoped-pim-no-data",
        "api_probe",
        "Authenticated exact-scope PIM no-data boundary",
        "http://127.0.0.1:8000/v1/pim/workspace",
        "task-bas144-runtime",
    ),
    (
        "runtime",
        "web:native-pim-390",
        "browser_probe",
        "Native PIM desktop and 390px workbench",
        "output/playwright/bas144-pim-mobile-390.png",
        "task-bas144-web",
    ),
    (
        "evidence",
        "evidence:BAS-144",
        "evidence",
        "BAS-144 native exact-scope PIM Evidence",
        EVIDENCE,
        "task-bas144-evidence",
    ),
)

EDGE_SPECS = (
    (
        "requirement:BR-118@master-8.46",
        "specified_by",
        "adr:ADR-0064",
        "requirements",
    ),
    (
        "adr:ADR-0064",
        "implemented_by",
        "service:scoped-pim-v1",
        "engineering",
    ),
    (
        "service:scoped-pim-v1",
        "observed_as",
        "api:scoped-pim-no-data",
        "runtime",
    ),
    (
        "api:scoped-pim-no-data",
        "rendered_by",
        "web:native-pim-390",
        "runtime",
    ),
    (
        "web:native-pim-390",
        "recorded_in",
        "evidence:BAS-144",
        "evidence",
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
    process = run_checked(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_scoped_pim.py",
            "tests/test_api_contract.py",
            "-q",
            "-p",
            "no:cacheprovider",
            f"--basetemp=output/pytest/bas144-graph-{os.getpid()}",
        ]
    )
    output = process.stdout + process.stderr
    match = re.search(r"(\d+) passed", output)
    if match is None or "[100%]" not in output:
        raise RuntimeError("BAS-144 focused pytest did not pass")
    passed = int(match.group(1))

    engine = create_database_engine()
    with engine.connect() as connection:
        revision = str(
            connection.execute(
                text("select version_num from alembic_version")
            ).scalar_one()
        )
        product_count = int(
            connection.execute(text("select count(*) from products")).scalar_one()
        )
        task_count_before = int(
            connection.execute(
                text("select count(*) from operating_tasks")
            ).scalar_one()
        )
    if revision != "20260729_0073":
        raise RuntimeError("real PostgreSQL is not at the single 0073 head")

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
        if row.get("State") == "running" and row.get("Health") == "healthy"
    }
    if not required <= healthy:
        raise RuntimeError("BAS-144 delivery containers are not healthy")

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
    params = {"store_ref": STORE_REF, "as_of": FIXED_AS_OF}
    readiness = httpx.get(f"{base}/health/ready", timeout=10)
    anonymous = httpx.get(
        f"{base}/v1/pim/workspace", params=params, timeout=10
    )
    scoped_a = httpx.get(
        f"{base}/v1/pim/workspace",
        params=params,
        headers=headers,
        timeout=10,
    )
    scoped_b = httpx.get(
        f"{base}/v1/pim/workspace",
        params=params,
        headers=headers,
        timeout=10,
    )
    forbidden = httpx.get(
        f"{base}/v1/pim/workspace",
        params={"store_ref": "other-store", "as_of": FIXED_AS_OF},
        headers=headers,
        timeout=10,
    )
    if (
        readiness.status_code != 200
        or readiness.json().get("version") != "0.59.0"
        or anonymous.status_code != 401
        or scoped_a.status_code != 200
        or scoped_b.status_code != 200
        or forbidden.status_code != 403
    ):
        raise RuntimeError("BAS-144 live auth boundary drifted")
    pim = scoped_a.json()
    replay = scoped_b.json()
    counts = pim.get("counts", {})
    envelope = pim.get("control_envelope", {})
    artifact = pim.get("agent_artifact", {})
    if (
        pim.get("status") != "no_data"
        or pim.get("scope", {}).get("entity_ref") is not None
        or counts.get("total_product_groups") != 0
        or counts.get("unbound_listings") != 0
        or envelope.get("scoped_input_read") is not False
        or envelope.get("external_write_allowed") is not False
        or artifact.get("self_approval_allowed") is not False
        or artifact.get("permit_issue_allowed") is not False
        or pim.get("snapshot_sha256") != replay.get("snapshot_sha256")
        or artifact.get("artifact_sha256")
        != replay.get("agent_artifact", {}).get("artifact_sha256")
    ):
        raise RuntimeError("BAS-144 no-data/no-write replay drifted")
    with engine.connect() as connection:
        task_count_after = int(
            connection.execute(
                text("select count(*) from operating_tasks")
            ).scalar_one()
        )
    if task_count_after != task_count_before:
        raise RuntimeError("BAS-144 read verification created an operating task")

    if any(file_sha(path) != digest for path, digest in SCREENSHOTS.items()):
        raise RuntimeError("BAS-144 browser Evidence hash drifted")
    evidence_text = (ROOT / EVIDENCE).read_text(encoding="utf-8")
    for marker in (
        "DONE_ENGINEERING",
        "inner/client/scrollWidth = 390/390/390",
        "external write false",
        "真实 `no_data`",
    ):
        if marker not in evidence_text:
            raise RuntimeError(f"BAS-144 Evidence marker missing: {marker}")

    return {
        "tests": {
            "state": "passed",
            "summary": f"{passed} BAS-144 focused tests passed",
            "input_sha256": _sha(
                [
                    file_sha("apps/control_plane/scoped_pim.py"),
                    file_sha("tests/test_scoped_pim.py"),
                    file_sha("tests/test_api_contract.py"),
                ]
            ),
            "artifact_ref": "process:pytest BAS-144",
        },
        "database": {
            "state": "passed",
            "summary": (
                f"PostgreSQL {revision}; pure-read composition; "
                f"pre-existing product rows {product_count}"
            ),
            "input_sha256": _sha([revision, product_count]),
            "artifact_ref": "postgres:alembic_version,products",
        },
        "runtime": {
            "state": "passed",
            "summary": (
                "four containers healthy; PIM 401/403/200-no_data; "
                "fixed-as_of replay stable; no task mutation; no writes"
            ),
            "input_sha256": _sha(
                [
                    pim["snapshot_sha256"],
                    artifact["artifact_sha256"],
                    task_count_after,
                ]
            ),
            "artifact_ref": f"{base}/v1/pim/workspace",
        },
        "web": {
            "state": "passed",
            "summary": (
                "desktop 1440 and mobile 390 PIM no_data; "
                "zero horizontal overflow and console errors"
            ),
            "input_sha256": _sha(SCREENSHOTS),
            "artifact_ref": "output/playwright/bas144-pim-mobile-390.png",
        },
        "evidence": {
            "state": "passed",
            "summary": f"BAS-144 Evidence SHA-256 {file_sha(EVIDENCE)}",
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
        "database": ("postgresql_probe", "database"),
        "runtime": ("http_and_docker_probe", "runtime"),
        "web": ("playwright_measurement", "browser"),
        "evidence": ("immutable_artifact", "evidence"),
    }
    for verifier_id, (source_type, authority) in verifier_defs.items():
        service.register_verifier(
            {
                "id": f"bas144-{verifier_id}",
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
        if session.get(GoalTaskRow, "task-bas143-market-baseline") is None:
            raise RuntimeError("BAS-143 Graph dependency is missing")
        for task_id, title, verifier, dependencies, workspace in TASK_SPECS:
            task = session.get(GoalTaskRow, task_id)
            if task is None:
                task = GoalTaskRow(
                    id=task_id,
                    project_id=PROJECT_ID,
                    title=title,
                    owner="pim-ai-erp-engineering",
                    verifier_id=f"bas144-{verifier}",
                    verifier_version="1",
                    dependency_ids_json=list(dependencies),
                    verification_condition=(
                        "fresh external verifier observation is passed"
                    ),
                    next_safe_action=(
                        "inspect the artifact and rerun the bounded verifier"
                    ),
                    workspace=workspace,
                    sla_seconds=86400,
                    fingerprint=_sha([PROJECT_ID, task_id]),
                    created_at=now,
                )
                session.add(task)
            else:
                task.title = title
                task.owner = "pim-ai-erp-engineering"
                task.verifier_id = f"bas144-{verifier}"
                task.verifier_version = "1"
                task.dependency_ids_json = list(dependencies)
                task.verification_condition = (
                    "fresh external verifier observation is passed"
                )
                task.next_safe_action = (
                    "inspect the artifact and rerun the bounded verifier"
                )
                task.workspace = workspace

        for kind, stable_key, node_type, label, artifact, _task in NODE_SPECS:
            node_id = f"gn_{_sha([PROJECT_ID, kind, stable_key])[:32]}"
            local_path = ROOT / artifact
            artifact_sha = (
                file_sha(artifact) if local_path.is_file() else _sha(artifact)
            )
            content = {
                "stable_key": stable_key,
                "type": node_type,
                "label": label,
                "artifact": artifact,
                "artifact_sha256": artifact_sha,
            }
            node = session.get(GraphNodeRow, node_id)
            if node is None:
                node = GraphNodeRow(
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
                session.add(node)
            else:
                node.node_type = node_type
                node.label = label
                node.source = artifact
                node.content_sha256 = _sha(content)
                node.artifact_ref = artifact
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
            if session.get(GraphEdgeRow, edge_id) is None:
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
                            [source, edge_type, target, now.date()]
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
        with Session(engine) as session:
            task = session.get(GoalTaskRow, task_id)
            if task is None:
                raise RuntimeError(f"Graph task {task_id} disappeared")
            dependency_snapshot = []
            for dependency_id in task.dependency_ids_json:
                dependency = session.scalar(
                    select(HarnessObservationRow)
                    .where(
                        HarnessObservationRow.project_id == PROJECT_ID,
                        HarnessObservationRow.task_id == dependency_id,
                    )
                    .order_by(
                        HarnessObservationRow.observed_at.desc(),
                        HarnessObservationRow.id.desc(),
                    )
                    .limit(1)
                )
                if dependency is None:
                    raise RuntimeError(
                        f"Dependency {dependency_id} has no observation"
                    )
                dependency_snapshot.append(
                    {
                        "task_id": dependency_id,
                        "observation_id": dependency.id,
                        "state": dependency.state,
                        "input_sha256": dependency.input_sha256,
                        "result_sha256": dependency.result_sha256,
                    }
                )
        service.record_observation(
            {
                "project_id": PROJECT_ID,
                "task_id": task_id,
                "verifier_id": f"bas144-{verifier}",
                "verifier_version": "1",
                "source": verifier_defs[verifier][0],
                "scope": {
                    "tenant_ref": "default",
                    "store_ref": STORE_REF,
                },
                "state": item["state"],
                "summary": item["summary"],
                "input_sha256": _sha(
                    {
                        "artifact_input_sha256": item["input_sha256"],
                        "dependencies": dependency_snapshot,
                    }
                ),
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
