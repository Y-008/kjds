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
    "20260730_BAS_151_NATIVE_EXACT_SCOPE_PROCUREMENT_RECEIVING.md"
)
SCREENSHOTS = {
    "output/playwright/bas151-procurement-desktop.png": (
        "fbb9c1b1c5f6715623a05bbb1e50c9dc09adfe7800a2db9fb3fcbdb6b77bea56"
    ),
    "output/playwright/bas151-procurement-mobile-390.png": (
        "9f04f4360cb0e9aa6518805c538d9b66dc1447f81e8b9a864535bb3cad765e7d"
    ),
}

TASK_SPECS = (
    (
        "task-bas151-pytest",
        "BAS-151 native exact-scope procurement receiving contracts",
        "tests",
        ("task-bas150-evidence",),
        "/engineering-graph",
    ),
    (
        "task-bas151-database",
        "BAS-151 PostgreSQL procurement authority at single 0077",
        "database",
        ("task-bas151-pytest",),
        "/runtime-graph",
    ),
    (
        "task-bas151-runtime",
        "BAS-151 authenticated deterministic procurement no-data runtime",
        "runtime",
        ("task-bas151-database",),
        "/runtime-graph",
    ),
    (
        "task-bas151-web",
        "BAS-151 desktop and 390px procurement receiving workspace",
        "web",
        ("task-bas151-runtime",),
        "/procurement",
    ),
    (
        "task-bas151-evidence",
        "BAS-151 immutable engineering Evidence",
        "evidence",
        ("task-bas151-web",),
        "/evidence-graph",
    ),
)

NODE_SPECS = (
    (
        "requirements",
        "requirement:BR-125@master-8.55",
        "requirement",
        "BR-125 native exact-scope procurement receiving control",
        "docs/project/MASTER_SPEC.md",
        "task-bas151-pytest",
    ),
    (
        "requirements",
        "adr:ADR-0071",
        "adr",
        "ADR-0071 native exact-scope procurement receiving control",
        "docs/adr/ADR-0071-native-exact-scope-procurement-receiving-control.md",
        "task-bas151-pytest",
    ),
    (
        "engineering",
        "service:scoped-procurement-receiving-v1",
        "service",
        "ScopedProcurementReceivingWorkspace exact-scope v1",
        "apps/control_plane/scoped_procurement_receiving.py",
        "task-bas151-pytest",
    ),
    (
        "engineering",
        "migration:20260729-0077-scoped-procurement-authority",
        "migration",
        "0077 native procurement and receiving authority",
        "migrations/versions/20260729_0077_native_scoped_procurement_receiving.py",
        "task-bas151-database",
    ),
    (
        "runtime",
        "api:native-procurement-receiving-no-data",
        "api_probe",
        "Authenticated native procurement receiving no-data boundary",
        "http://127.0.0.1:8000/v1/procurement/workspace",
        "task-bas151-runtime",
    ),
    (
        "runtime",
        "web:native-procurement-receiving-390",
        "browser_probe",
        "Native procurement receiving desktop and 390px",
        "output/playwright/bas151-procurement-mobile-390.png",
        "task-bas151-web",
    ),
    (
        "evidence",
        "evidence:BAS-151",
        "evidence",
        "BAS-151 native procurement receiving Evidence",
        EVIDENCE,
        "task-bas151-evidence",
    ),
)

EDGE_SPECS = (
    (
        "requirement:BR-125@master-8.55",
        "specified_by",
        "adr:ADR-0071",
        "requirements",
    ),
    (
        "adr:ADR-0071",
        "implemented_by",
        "service:scoped-procurement-receiving-v1",
        "engineering",
    ),
    (
        "service:scoped-procurement-receiving-v1",
        "constrained_by",
        "migration:20260729-0077-scoped-procurement-authority",
        "engineering",
    ),
    (
        "migration:20260729-0077-scoped-procurement-authority",
        "observed_as",
        "api:native-procurement-receiving-no-data",
        "runtime",
    ),
    (
        "api:native-procurement-receiving-no-data",
        "rendered_by",
        "web:native-procurement-receiving-390",
        "runtime",
    ),
    (
        "web:native-procurement-receiving-390",
        "recorded_in",
        "evidence:BAS-151",
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
            "scoped_sample_orders": (
                "select count(*) from sample_purchase_orders "
                "where tenant_ref is not null"
            ),
            "scoped_procurement_events": (
                "select count(*) from sample_procurement_events "
                "where tenant_ref is not null"
            ),
            "procurement_indexes": (
                "select count(*) from pg_indexes where schemaname='public' "
                "and indexname in ('ix_sample_order_scope_created',"
                "'ix_sample_order_scope_product',"
                "'ix_sample_event_scope_timeline')"
            ),
            "procurement_constraints": (
                "select count(*) from pg_constraint where conname in "
                "('ck_sample_purchase_orders_scope_complete',"
                "'ck_sample_procurement_events_scope_complete')"
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


def runtime_api_key() -> str:
    direct = run_checked(
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
    if direct:
        return direct
    mapping_raw = run_checked(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "api",
            "printenv",
            "KJDS_API_KEYS_JSON",
        ]
    ).stdout.strip()
    mapping = json.loads(mapping_raw)
    return next(
        key
        for key, profile in mapping.items()
        if "operator" in profile.get("roles", [])
        or "admin" in profile.get("roles", [])
    )


def observe() -> dict[str, dict[str, str]]:
    process = run_checked(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_scoped_procurement_receiving.py",
            "tests/test_procurement.py",
            "tests/test_api_contract.py",
            "-q",
            "-p",
            "no:cacheprovider",
            f"--basetemp=output/pytest/bas151-graph-{os.getpid()}",
        ]
    )
    output = process.stdout + process.stderr
    match = re.search(r"(\d+) passed", output)
    if match is None or "[100%]" not in output:
        raise RuntimeError("BAS-151 focused pytest did not pass")
    passed = int(match.group(1))
    if passed != 55:
        raise RuntimeError(f"BAS-151 focused test count drifted: {passed}")

    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    heads = script.get_heads()
    before = database_state()
    if heads != ["20260729_0077"] or before["revision"] != "20260729_0077":
        raise RuntimeError("BAS-151 requires one current/head 20260729_0077")
    if (
        before["procurement_indexes"] != 3
        or before["procurement_constraints"] != 2
    ):
        raise RuntimeError("BAS-151 database authority is incomplete")
    if (
        before["scoped_sample_orders"] != 0
        or before["scoped_procurement_events"] != 0
    ):
        raise RuntimeError("BAS-151 cannot synthesize procurement truth")

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
        raise RuntimeError("BAS-151 delivery containers are not healthy")

    api_key = runtime_api_key()
    base = "http://127.0.0.1:8000"
    route = f"{base}/v1/procurement/workspace"
    headers = {"X-KJDS-API-Key": api_key}
    params = {"store_ref": STORE_REF, "as_of": FIXED_AS_OF}
    readiness = httpx.get(f"{base}/health/ready", timeout=10)
    anonymous = httpx.get(route, params=params, timeout=20)
    first = httpx.get(route, params=params, headers=headers, timeout=20)
    replay = httpx.get(route, params=params, headers=headers, timeout=20)
    forbidden = httpx.get(
        route,
        params={"store_ref": "other-store", "as_of": FIXED_AS_OF},
        headers=headers,
        timeout=20,
    )
    if (
        readiness.status_code != 200
        or readiness.json().get("version") != "0.59.0"
        or anonymous.status_code != 401
        or first.status_code != 200
        or replay.status_code != 200
        or forbidden.status_code != 403
    ):
        raise RuntimeError("BAS-151 live auth boundary drifted")

    workspace = first.json()
    repeated = replay.json()
    envelope = workspace.get("control_envelope", {})
    artifact = workspace.get("agent_artifact", {})
    finance = workspace.get("financial_authority", {})
    if (
        workspace.get("contract_id")
        != "kjds-native-exact-scope-procurement-receiving-workspace-v1"
        or workspace.get("status") != "no_data"
        or workspace.get("scope", {}).get("entity_ref") is not None
        or any(workspace.get("counts", {}).values())
        or workspace.get("orders")
        or envelope.get("scoped_input_read") is not False
        or envelope.get("legacy_procurement_rows_admitted") is not False
        or envelope.get("client_recalculation_allowed") is not False
        or envelope.get("purchase_order_created") is not False
        or envelope.get("receipt_confirmed") is not False
        or envelope.get("payment_initiated") is not False
        or envelope.get("external_write_allowed") is not False
        or finance.get("accounts_payable_invoice_authority_available")
        is not False
        or finance.get("supplier_payment_authority_available") is not False
        or artifact.get("self_approval_allowed") is not False
        or artifact.get("permit_issue_allowed") is not False
        or artifact.get("external_write_allowed") is not False
        or workspace.get("snapshot_sha256")
        != repeated.get("snapshot_sha256")
        or artifact.get("artifact_sha256")
        != repeated.get("agent_artifact", {}).get("artifact_sha256")
    ):
        raise RuntimeError("BAS-151 no-data/no-write replay drifted")

    after = database_state()
    if after != before:
        raise RuntimeError("BAS-151 read verification mutated PostgreSQL")
    if any(file_sha(path) != digest for path, digest in SCREENSHOTS.items()):
        raise RuntimeError("BAS-151 browser Evidence hash drifted")
    evidence_text = (ROOT / EVIDENCE).read_text(encoding="utf-8")
    for marker in (
        "DONE_ENGINEERING",
        "915 passed",
        "inner/scrollWidth = 390/390",
        "scoped Sample Purchase Order: `0`",
        "`external_write_allowed=false`",
    ):
        if marker not in evidence_text:
            raise RuntimeError(f"BAS-151 Evidence marker missing: {marker}")

    return {
        "tests": {
            "state": "passed",
            "summary": (
                f"{passed} focused tests; 915 full tests; exact scope, "
                "latest Evidence, transitions and quantity conservation covered"
            ),
            "input_sha256": _sha(
                [
                    file_sha(
                        "apps/control_plane/scoped_procurement_receiving.py"
                    ),
                    file_sha("apps/control_plane/procurement.py"),
                    file_sha(
                        "tests/test_scoped_procurement_receiving.py"
                    ),
                    file_sha("tests/test_procurement.py"),
                    file_sha("tests/test_api_contract.py"),
                ]
            ),
            "artifact_ref": "process:pytest BAS-151",
        },
        "database": {
            "state": "passed",
            "summary": (
                "PostgreSQL single 0077; three indexes and two complete-scope "
                "constraints; native procurement authority rows zero"
            ),
            "input_sha256": _sha({"heads": heads, **after}),
            "artifact_ref": (
                "postgres:alembic_version,sample_purchase_orders,"
                "sample_procurement_events"
            ),
        },
        "runtime": {
            "state": "passed",
            "summary": (
                "four containers healthy; 401/403/200-no_data; fixed-as-of "
                "replay stable; AP/payment gated; all writes false"
            ),
            "input_sha256": _sha(
                [
                    workspace["snapshot_sha256"],
                    artifact["artifact_sha256"],
                    after["operating_tasks"],
                ]
            ),
            "artifact_ref": route,
        },
        "web": {
            "state": "passed",
            "summary": (
                "desktop 1440 and mobile 390 procurement no_data; zero "
                "horizontal overflow, console errors and page errors"
            ),
            "input_sha256": _sha(SCREENSHOTS),
            "artifact_ref": (
                "output/playwright/bas151-procurement-mobile-390.png"
            ),
        },
        "evidence": {
            "state": "passed",
            "summary": f"BAS-151 Evidence SHA-256 {file_sha(EVIDENCE)}",
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
                "id": f"bas151-{verifier_id}",
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
        if session.get(GoalTaskRow, "task-bas150-evidence") is None:
            raise RuntimeError("BAS-150 Graph dependency is missing")
        for task_id, title, verifier, dependencies, workspace in TASK_SPECS:
            task = session.get(GoalTaskRow, task_id)
            if task is None:
                task = GoalTaskRow(
                    id=task_id,
                    project_id=PROJECT_ID,
                    title=title,
                    owner="procurement-control-engineering",
                    verifier_id=f"bas151-{verifier}",
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
                task.owner = "procurement-control-engineering"
                task.verifier_id = f"bas151-{verifier}"
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
                "verifier_id": f"bas151-{verifier}",
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
        result["tasks"] != 86
        or result["nodes"] != 197
        or result["edges"] != 198
        or result["observations"] < 331
    ):
        raise RuntimeError(f"BAS-151 Graph count drifted: {result}")
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
