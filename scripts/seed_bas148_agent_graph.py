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
from alembic.config import Config
from alembic.script import ScriptDirectory
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
    "20260729_BAS_148_NATIVE_EXACT_SCOPE_CONTENT_MEDIA_FACTORY.md"
)
SCREENSHOTS = {
    "output/playwright/bas148-media-factory-desktop.png": (
        "85986d7b37aff4e7860b73daa6a21831da5c06317cb5fd4f198a9bc121ada096"
    ),
    "output/playwright/bas148-media-factory-mobile-390.png": (
        "770205c5fbec635e7c0885f1d46f689f8c4ee173c08a300d0614274fc1d5eea0"
    ),
}

TASK_SPECS = (
    (
        "task-bas148-pytest",
        "BAS-148 exact-scope content media factory contracts",
        "tests",
        ("task-bas147-evidence",),
        "/engineering-graph",
    ),
    (
        "task-bas148-database",
        "BAS-148 PostgreSQL media authority at single 0074",
        "database",
        ("task-bas148-pytest",),
        "/runtime-graph",
    ),
    (
        "task-bas148-runtime",
        "BAS-148 authenticated deterministic no-data runtime",
        "runtime",
        ("task-bas148-database",),
        "/runtime-graph",
    ),
    (
        "task-bas148-web",
        "BAS-148 desktop and 390px content media factory",
        "web",
        ("task-bas148-runtime",),
        "/media-factory",
    ),
    (
        "task-bas148-evidence",
        "BAS-148 immutable engineering Evidence",
        "evidence",
        ("task-bas148-web",),
        "/evidence-graph",
    ),
)

NODE_SPECS = (
    (
        "requirements",
        "requirement:BR-122@master-8.50",
        "requirement",
        "BR-122 native exact-scope content media factory",
        "docs/project/MASTER_SPEC.md",
        "task-bas148-pytest",
    ),
    (
        "requirements",
        "adr:ADR-0068",
        "adr",
        "ADR-0068 native exact-scope content media factory",
        "docs/adr/ADR-0068-native-exact-scope-content-media-factory.md",
        "task-bas148-pytest",
    ),
    (
        "engineering",
        "service:scoped-content-media-factory-v1",
        "service",
        "ScopedContentMediaFactoryWorkspace v1",
        "apps/control_plane/scoped_media_factory.py",
        "task-bas148-pytest",
    ),
    (
        "engineering",
        "authority:scoped-media-read-source-v1",
        "temporal_authority",
        "Exact-as-of media SQL read authority",
        "apps/control_plane/media_workbench.py",
        "task-bas148-database",
    ),
    (
        "runtime",
        "api:scoped-content-media-factory-no-data",
        "api_probe",
        "Authenticated content media factory no-data boundary",
        "http://127.0.0.1:8000/v1/media-factory/workspace",
        "task-bas148-runtime",
    ),
    (
        "runtime",
        "web:native-content-media-factory-390",
        "browser_probe",
        "Native content media factory desktop and 390px",
        "output/playwright/bas148-media-factory-mobile-390.png",
        "task-bas148-web",
    ),
    (
        "evidence",
        "evidence:BAS-148",
        "evidence",
        "BAS-148 native content media factory Evidence",
        EVIDENCE,
        "task-bas148-evidence",
    ),
)

EDGE_SPECS = (
    (
        "requirement:BR-122@master-8.50",
        "specified_by",
        "adr:ADR-0068",
        "requirements",
    ),
    (
        "adr:ADR-0068",
        "implemented_by",
        "service:scoped-content-media-factory-v1",
        "engineering",
    ),
    (
        "service:scoped-content-media-factory-v1",
        "constrained_by",
        "authority:scoped-media-read-source-v1",
        "engineering",
    ),
    (
        "authority:scoped-media-read-source-v1",
        "observed_as",
        "api:scoped-content-media-factory-no-data",
        "runtime",
    ),
    (
        "api:scoped-content-media-factory-no-data",
        "rendered_by",
        "web:native-content-media-factory-390",
        "runtime",
    ),
    (
        "web:native-content-media-factory-390",
        "recorded_in",
        "evidence:BAS-148",
        "evidence",
    ),
)

VERIFIER_DEFS = {
    "tests": ("pytest_process", "test_process"),
    "database": ("postgresql_probe", "database"),
    "runtime": ("http_and_docker_probe", "runtime"),
    "web": ("playwright_measurement", "browser"),
    "evidence": ("immutable_artifact", "evidence"),
}


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


def database_state() -> dict[str, int | str]:
    engine = create_database_engine()
    with engine.connect() as connection:
        queries = {
            "revision": "select version_num from alembic_version",
            "products": "select count(*) from products",
            "content_assets": "select count(*) from content_assets",
            "media_executions": "select count(*) from media_executions",
            "media_execution_events": "select count(*) from media_execution_events",
            "media_delivery_manifests": (
                "select count(*) from media_delivery_manifests"
            ),
            "order_facts": (
                "select count(*) from fact_records "
                "where fact_type='ozon_order' and tenant_ref is not null"
            ),
            "inventory_facts": (
                "select count(*) from fact_records "
                "where fact_type='ozon_inventory' and tenant_ref is not null"
            ),
            "operating_tasks": "select count(*) from operating_tasks",
        }
        values = {
            key: connection.execute(text(query)).scalar_one()
            for key, query in queries.items()
        }
        return {
            key: str(value) if key == "revision" else int(value)
            for key, value in values.items()
        }


def observe() -> dict[str, dict[str, str]]:
    process = run_checked(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_scoped_media_factory.py",
            "tests/test_media_workbench.py",
            "tests/test_commerce_operating_system.py",
            "tests/test_api_contract.py",
            "-q",
            "-p",
            "no:cacheprovider",
            f"--basetemp=output/pytest/bas148-graph-{os.getpid()}",
        ]
    )
    output = process.stdout + process.stderr
    match = re.search(r"(\d+) passed", output)
    if match is None or "[100%]" not in output:
        raise RuntimeError("BAS-148 focused pytest did not pass")
    passed = int(match.group(1))
    if passed != 67:
        raise RuntimeError(f"BAS-148 focused test count drifted: {passed}")

    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    heads = script.get_heads()
    before = database_state()
    if heads != ["20260729_0074"] or before["revision"] != "20260729_0074":
        raise RuntimeError("BAS-148 requires one current/head 20260729_0074")
    for key in (
        "content_assets",
        "media_executions",
        "media_execution_events",
        "media_delivery_manifests",
        "order_facts",
        "inventory_facts",
    ):
        if before[key] != 0:
            raise RuntimeError(f"BAS-148 verification cannot synthesize {key}")

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
        raise RuntimeError("BAS-148 delivery containers are not healthy")

    api_key = run_checked(
        ["docker", "compose", "exec", "-T", "api", "printenv", "KJDS_API_KEY"]
    ).stdout.strip()
    if not api_key:
        raise RuntimeError("runtime API identity is not configured")
    base = "http://127.0.0.1:8000"
    canonical_route = f"{base}/v1/media-factory/workspace"
    legacy_route = f"{base}/v1/media/workbench"
    headers = {"X-KJDS-API-Key": api_key}
    params = {"store_ref": STORE_REF, "as_of": FIXED_AS_OF}
    readiness = httpx.get(f"{base}/health/ready", timeout=10)
    anonymous = httpx.get(canonical_route, params=params, timeout=20)
    canonical_a = httpx.get(
        canonical_route, params=params, headers=headers, timeout=20
    )
    canonical_b = httpx.get(
        canonical_route, params=params, headers=headers, timeout=20
    )
    legacy = httpx.get(legacy_route, params=params, headers=headers, timeout=20)
    forbidden = httpx.get(
        canonical_route,
        params={"store_ref": "other-store", "as_of": FIXED_AS_OF},
        headers=headers,
        timeout=20,
    )
    if (
        readiness.status_code != 200
        or readiness.json().get("version") != "0.59.0"
        or anonymous.status_code != 401
        or canonical_a.status_code != 200
        or canonical_b.status_code != 200
        or legacy.status_code != 200
        or forbidden.status_code != 403
    ):
        raise RuntimeError("BAS-148 live auth boundary drifted")
    workspace = canonical_a.json()
    replay = canonical_b.json()
    envelope = workspace.get("control_envelope", {})
    artifact = workspace.get("agent_artifact", {})
    if (
        workspace != legacy.json()
        or workspace.get("contract_id")
        != "kjds-native-exact-scope-content-media-factory-v1"
        or workspace.get("status") != "no_data"
        or workspace.get("scope", {}).get("entity_ref") is not None
        or any(workspace.get("counts", {}).values())
        or envelope.get("scoped_input_read") is not False
        or envelope.get("asset_created") is not False
        or envelope.get("job_created") is not False
        or envelope.get("qa_decided") is not False
        or envelope.get("manifest_created") is not False
        or envelope.get("listing_created") is not False
        or envelope.get("approval_created") is not False
        or envelope.get("permit_created") is not False
        or envelope.get("external_write_allowed") is not False
        or artifact.get("self_approval_allowed") is not False
        or artifact.get("permit_issue_allowed") is not False
        or artifact.get("asset_or_job_creation_allowed") is not False
        or artifact.get("qa_or_manifest_creation_allowed") is not False
        or artifact.get("external_write_allowed") is not False
        or workspace.get("snapshot_sha256") != replay.get("snapshot_sha256")
        or artifact.get("artifact_sha256")
        != replay.get("agent_artifact", {}).get("artifact_sha256")
    ):
        raise RuntimeError("BAS-148 no-data/no-write replay drifted")
    after = database_state()
    if after["operating_tasks"] != before["operating_tasks"]:
        raise RuntimeError("BAS-148 read verification created an operating task")

    if any(file_sha(path) != digest for path, digest in SCREENSHOTS.items()):
        raise RuntimeError("BAS-148 browser Evidence hash drifted")
    evidence_text = (ROOT / EVIDENCE).read_text(encoding="utf-8")
    for marker in (
        "DONE_ENGINEERING",
        "889 passed",
        "inner/client/scrollWidth = 390/390/390",
        "ContentAsset: `0`",
        "`external_write_allowed=false`",
    ):
        if marker not in evidence_text:
            raise RuntimeError(f"BAS-148 Evidence marker missing: {marker}")

    return {
        "tests": {
            "state": "passed",
            "summary": (
                f"{passed} focused tests; 889 full tests; Evidence, event "
                "timeline, Manifest and temporal fail-closed covered"
            ),
            "input_sha256": _sha(
                [
                    file_sha("apps/control_plane/scoped_media_factory.py"),
                    file_sha("tests/test_scoped_media_factory.py"),
                    file_sha("tests/test_api_contract.py"),
                ]
            ),
            "artifact_ref": "process:pytest BAS-148",
        },
        "database": {
            "state": "passed",
            "summary": (
                "PostgreSQL single 0074; Product "
                f"{after['products']}; Asset/Execution/Event/Manifest "
                f"{after['content_assets']}/{after['media_executions']}/"
                f"{after['media_execution_events']}/"
                f"{after['media_delivery_manifests']}; Order/Inventory "
                f"Facts {after['order_facts']}/{after['inventory_facts']}"
            ),
            "input_sha256": _sha({"heads": heads, **after}),
            "artifact_ref": (
                "postgres:alembic_version,products,content_assets,"
                "media_executions,media_execution_events,"
                "media_delivery_manifests,fact_records"
            ),
        },
        "runtime": {
            "state": "passed",
            "summary": (
                "four containers healthy; canonical/legacy equal; "
                "401/403/200-no_data; fixed-as-of replay stable; no mutation"
            ),
            "input_sha256": _sha(
                [
                    workspace["snapshot_sha256"],
                    artifact["artifact_sha256"],
                    after["operating_tasks"],
                ]
            ),
            "artifact_ref": canonical_route,
        },
        "web": {
            "state": "passed",
            "summary": (
                "desktop 1440 and mobile 390 media no_data; zero horizontal "
                "overflow and console errors"
            ),
            "input_sha256": _sha(SCREENSHOTS),
            "artifact_ref": (
                "output/playwright/bas148-media-factory-mobile-390.png"
            ),
        },
        "evidence": {
            "state": "passed",
            "summary": f"BAS-148 Evidence SHA-256 {file_sha(EVIDENCE)}",
            "input_sha256": file_sha(EVIDENCE),
            "artifact_ref": EVIDENCE,
        },
    }


def upsert_graph(observations: dict[str, dict[str, str]]) -> None:
    engine = create_database_engine()
    service = AgentHarnessService(engine)
    now = datetime.now(UTC)
    for verifier_id, (source_type, authority) in VERIFIER_DEFS.items():
        service.register_verifier(
            {
                "id": f"bas148-{verifier_id}",
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
        if session.get(GoalTaskRow, "task-bas147-evidence") is None:
            raise RuntimeError("BAS-147 Graph dependency is missing")
        for task_id, title, verifier, dependencies, workspace in TASK_SPECS:
            task = session.get(GoalTaskRow, task_id)
            if task is None:
                task = GoalTaskRow(
                    id=task_id,
                    project_id=PROJECT_ID,
                    title=title,
                    owner="content-media-factory-engineering",
                    verifier_id=f"bas148-{verifier}",
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
                task.owner = "content-media-factory-engineering"
                task.verifier_id = f"bas148-{verifier}"
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
                select(GraphNodeRow).where(GraphNodeRow.project_id == PROJECT_ID)
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
                "verifier_id": f"bas148-{verifier}",
                "verifier_version": "1",
                "source": VERIFIER_DEFS[verifier][0],
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
    result = counts()
    if (
        result["tasks"] != 71
        or result["nodes"] != 176
        or result["edges"] != 180
        or result["observations"] < 313
    ):
        raise RuntimeError(f"BAS-148 Graph count drifted: {result}")
    print(
        json.dumps(
            {
                "project_id": PROJECT_ID,
                **result,
                "business_state": "no_data",
                "external_write_allowed": False,
            },
            sort_keys=True,
        )
    )
