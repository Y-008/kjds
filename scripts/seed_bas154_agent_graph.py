from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

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
EVIDENCE = (
    "docs/project/evidence/"
    "20260730_BAS_154_NATIVE_EXACT_SCOPE_CUSTOMER_SERVICE.md"
)
SCREENSHOTS = {
    "output/playwright/bas154-customer-service-desktop.png": (
        "d0b1fecbf686080c6da30ab14aea904d25dfd30f4769f933f252af4a41d05724"
    ),
    "output/playwright/bas154-customer-service-mobile-390.png": (
        "370ba790a1cd620fb68463af46d34843168064be424825b91bcb2326545ffb40"
    ),
}

TASK_SPECS = (
    (
        "task-bas154-pytest",
        "BAS-154 native exact-scope customer-service contracts",
        "tests",
        ("task-bas153-evidence",),
        "/engineering-graph",
    ),
    (
        "task-bas154-database",
        "BAS-154 PostgreSQL customer-service authority at single 0079",
        "database",
        ("task-bas154-pytest",),
        "/runtime-graph",
    ),
    (
        "task-bas154-runtime",
        "BAS-154 authenticated deterministic customer-service no-data runtime",
        "runtime",
        ("task-bas154-database",),
        "/runtime-graph",
    ),
    (
        "task-bas154-web",
        "BAS-154 desktop and 390px customer-service workspace",
        "web",
        ("task-bas154-runtime",),
        "/customer-service",
    ),
    (
        "task-bas154-evidence",
        "BAS-154 immutable engineering Evidence",
        "evidence",
        ("task-bas154-web",),
        "/evidence-graph",
    ),
)

NODE_SPECS = (
    (
        "requirements",
        "requirement:BR-128@master-8.59",
        "requirement",
        "BR-128 native exact-scope customer-service authority",
        "docs/project/MASTER_SPEC.md",
        "task-bas154-pytest",
    ),
    (
        "requirements",
        "adr:ADR-0074",
        "adr",
        "ADR-0074 native exact-scope customer-service authority",
        "docs/adr/ADR-0074-native-exact-scope-customer-service-authority.md",
        "task-bas154-pytest",
    ),
    (
        "engineering",
        "service:scoped-customer-service-v1",
        "service",
        "ScopedCustomerServiceWorkspace exact-scope v1",
        "apps/control_plane/scoped_customer_service.py",
        "task-bas154-pytest",
    ),
    (
        "engineering",
        "database:bas154-customer-service-0079",
        "database_probe",
        "BAS-154 immutable customer-service authority at 0079",
        "migrations/versions/20260730_0079_native_scoped_customer_service.py",
        "task-bas154-database",
    ),
    (
        "runtime",
        "api:native-customer-service-no-data",
        "api_probe",
        "Authenticated native customer-service no-data boundary",
        "http://127.0.0.1:8000/v1/customer-service/workspace",
        "task-bas154-runtime",
    ),
    (
        "runtime",
        "web:native-customer-service-390",
        "browser_probe",
        "Native customer-service desktop and 390px",
        "output/playwright/bas154-customer-service-mobile-390.png",
        "task-bas154-web",
    ),
    (
        "evidence",
        "evidence:BAS-154",
        "evidence",
        "BAS-154 native customer-service Evidence",
        EVIDENCE,
        "task-bas154-evidence",
    ),
)

EDGE_SPECS = (
    (
        "requirement:BR-128@master-8.59",
        "specified_by",
        "adr:ADR-0074",
        "requirements",
    ),
    (
        "adr:ADR-0074",
        "implemented_by",
        "service:scoped-customer-service-v1",
        "engineering",
    ),
    (
        "service:scoped-customer-service-v1",
        "persisted_by",
        "database:bas154-customer-service-0079",
        "engineering",
    ),
    (
        "database:bas154-customer-service-0079",
        "observed_as",
        "api:native-customer-service-no-data",
        "runtime",
    ),
    (
        "api:native-customer-service-no-data",
        "rendered_by",
        "web:native-customer-service-390",
        "runtime",
    ),
    (
        "web:native-customer-service-390",
        "recorded_in",
        "evidence:BAS-154",
        "evidence",
    ),
)

VERIFIER_DEFS = {
    "tests": ("pytest_process", "test_process"),
    "database": ("postgresql_replay", "database"),
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
        row = (
            connection.execute(
                text(
                    "SELECT "
                    "(SELECT version_num FROM alembic_version) AS revision, "
                    "(SELECT count(1) FROM customer_service_cases) AS cases, "
                    "(SELECT count(1) FROM customer_service_events) AS events"
                )
            )
            .mappings()
            .one()
        )
    return {
        "revision": str(row["revision"]),
        "cases": int(row["cases"]),
        "events": int(row["events"]),
    }


def observe() -> dict[str, dict[str, str]]:
    process = run_checked(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_scoped_customer_service.py",
            "tests/test_api_contract.py",
            "tests/test_write_path_registry.py",
            "-q",
            "-p",
            "no:cacheprovider",
            f"--basetemp=output/pytest/bas154-graph-{os.getpid()}",
        ]
    )
    output = process.stdout + process.stderr
    match = re.search(r"(\d+) passed", output)
    if match is None or "[100%]" not in output:
        raise RuntimeError("BAS-154 focused pytest did not pass")
    passed = int(match.group(1))
    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    heads = script.get_heads()
    before = database_state()
    if heads != ["20260730_0079"] or before != {
        "revision": "20260730_0079",
        "cases": 0,
        "events": 0,
    }:
        raise RuntimeError("BAS-154 requires one current/head 0079 and zero rows")
    replay = run_checked(
        [sys.executable, "scripts/verify_bas154_migration_replay.py"]
    )
    if "base -> 0079 -> 0078 -> 0079" not in (
        replay.stdout + replay.stderr
    ):
        raise RuntimeError("BAS-154 empty PostgreSQL replay marker is missing")

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
        raise RuntimeError("BAS-154 delivery containers are not healthy")

    runtime_process = run_checked(
        [sys.executable, "scripts/verify_bas154_runtime.py"]
    )
    runtime = json.loads(runtime_process.stdout.strip().splitlines()[-1])
    if (
        runtime.get("anonymous") != 401
        or runtime.get("authenticated") != 200
        or runtime.get("forbidden") != 403
        or runtime.get("readiness") != 200
        or runtime.get("status") != "no_data"
        or runtime.get("total_cases") != 0
        or runtime.get("scoped_input_read") is not False
        or runtime.get("message_adapter_enabled") is not False
        or runtime.get("raw_message_body_exposed") is not False
        or runtime.get("external_write_allowed") is not False
        or runtime.get("private_erp_interface_allowed") is not False
    ):
        raise RuntimeError("BAS-154 runtime truth or control boundary drifted")
    after = database_state()
    if after != before:
        raise RuntimeError("BAS-154 verification mutated the live database")

    if any(file_sha(path) != digest for path, digest in SCREENSHOTS.items()):
        raise RuntimeError("BAS-154 browser Evidence hash drifted")
    evidence_text = (ROOT / EVIDENCE).read_text(encoding="utf-8")
    for marker in (
        "DONE_ENGINEERING",
        "979 passed",
        "production runtime remains unbound",
        "independent versioned message Readback Evidence",
        "inner/scrollWidth = 390/390",
        "Case/Event counts `0`",
        "`message_adapter_enabled=false`",
        "`external_write_allowed=false`",
        "`policy_only`",
    ):
        if marker not in evidence_text:
            raise RuntimeError(f"BAS-154 Evidence marker missing: {marker}")

    return {
        "tests": {
            "state": "passed",
            "summary": (
                f"{passed} focused tests executed by this verifier; "
                "exact scope, PII, transition, independent Approval and "
                "trusted message Readback closure covered; the separate "
                "current full gate is recorded in immutable Evidence"
            ),
            "input_sha256": _sha(
                [
                    file_sha("apps/control_plane/customer_service.py"),
                    file_sha("apps/control_plane/scoped_customer_service.py"),
                    file_sha("tests/test_scoped_customer_service.py"),
                    file_sha("tests/test_api_contract.py"),
                    file_sha("tests/test_write_path_registry.py"),
                    file_sha(
                        "docs/project/registries/action_policy_registry.json"
                    ),
                    file_sha(
                        "docs/project/registries/write_path_registry.json"
                    ),
                ]
            ),
            "artifact_ref": "process:pytest BAS-154",
        },
        "database": {
            "state": "passed",
            "summary": (
                "PostgreSQL single 0079; empty base/0079/0078/0079 replay; "
                "Customer Service Case and Event rows remain zero"
            ),
            "input_sha256": _sha(
                {
                    "heads": heads,
                    **after,
                    "migration": file_sha(
                        "migrations/versions/"
                        "20260730_0079_native_scoped_customer_service.py"
                    ),
                }
            ),
            "artifact_ref": (
                "postgres:alembic_version,customer_service_cases,"
                "customer_service_events"
            ),
        },
        "runtime": {
            "state": "passed",
            "summary": (
                "four containers healthy; 401/403/200-no_data; no PII, "
                "message Adapter, private ERP interface or external write"
            ),
            "input_sha256": _sha(runtime),
            "artifact_ref": (
                "http://127.0.0.1:8000/v1/customer-service/workspace"
            ),
        },
        "web": {
            "state": "passed",
            "summary": (
                "desktop 1440 and mobile 390 Customer Service no_data; "
                "zero horizontal overflow and console errors"
            ),
            "input_sha256": _sha(SCREENSHOTS),
            "artifact_ref": (
                "output/playwright/"
                "bas154-customer-service-mobile-390.png"
            ),
        },
        "evidence": {
            "state": "passed",
            "summary": f"BAS-154 Evidence SHA-256 {file_sha(EVIDENCE)}",
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
                "id": f"bas154-{verifier_id}",
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
        if session.get(GoalTaskRow, "task-bas153-evidence") is None:
            raise RuntimeError("BAS-153 Graph dependency is missing")
        for task_id, title, verifier, dependencies, workspace in TASK_SPECS:
            task = session.get(GoalTaskRow, task_id)
            if task is None:
                task = GoalTaskRow(
                    id=task_id,
                    project_id=PROJECT_ID,
                    title=title,
                    owner="customer-service-engineering",
                    verifier_id=f"bas154-{verifier}",
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
                task.owner = "customer-service-engineering"
                task.verifier_id = f"bas154-{verifier}"
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
                "verifier_id": f"bas154-{verifier}",
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
        result["tasks"] < 101
        or result["nodes"] < 218
        or result["edges"] < 216
        or result["observations"] < 349
    ):
        raise RuntimeError(f"BAS-154 Graph count drifted: {result}")
    print(
        json.dumps(
            {
                "project_id": PROJECT_ID,
                **result,
                "business_state": "no_data",
                "message_adapter_enabled": False,
                "external_write_allowed": False,
            },
            sort_keys=True,
        )
    )
