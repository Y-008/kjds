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
    "20260729_BAS_146_AUTHORIZED_SELLER_ERP_BRIDGE.md"
)
SCREENSHOTS = {
    "output/playwright/bas146-seller-erp-bridge-desktop.png": (
        "db7a3ecb50ea874de0febb6cce6b8536785f799009f66ba570d990c2b03b64f0"
    ),
    "output/playwright/bas146-seller-erp-bridge-mobile-390.png": (
        "ae2847653e258f5fb3226a4b93e702af3b1c007766c93ad243b856e4866ed8ae"
    ),
}

TASK_SPECS = (
    (
        "task-bas146-pytest",
        "BAS-146 authorized Seller ERP Bridge contracts",
        "tests",
        ("task-bas145-evidence",),
        "/engineering-graph",
    ),
    (
        "task-bas146-database",
        "BAS-146 PostgreSQL 0074 authority uniqueness",
        "database",
        ("task-bas146-pytest",),
        "/runtime-graph",
    ),
    (
        "task-bas146-runtime",
        "BAS-146 authenticated deterministic no-data runtime",
        "runtime",
        ("task-bas146-database",),
        "/runtime-graph",
    ),
    (
        "task-bas146-web",
        "BAS-146 desktop and 390px Seller ERP Bridge",
        "web",
        ("task-bas146-runtime",),
        "/seller-erp-bridge",
    ),
    (
        "task-bas146-evidence",
        "BAS-146 immutable engineering Evidence",
        "evidence",
        ("task-bas146-web",),
        "/evidence-graph",
    ),
)

NODE_SPECS = (
    (
        "requirements",
        "requirement:BR-120@master-8.48",
        "requirement",
        "BR-120 authorized Seller ERP Bridge and Canonical Diff",
        "docs/project/MASTER_SPEC.md",
        "task-bas146-pytest",
    ),
    (
        "requirements",
        "adr:ADR-0066",
        "adr",
        "ADR-0066 authorized Seller ERP Bridge",
        "docs/adr/ADR-0066-authorized-seller-erp-bridge-canonical-diff.md",
        "task-bas146-pytest",
    ),
    (
        "engineering",
        "migration:20260729-0074-seller-erp-bridge",
        "migration",
        "0074 Seller ERP Bridge authority uniqueness",
        (
            "migrations/versions/"
            "20260729_0074_seller_erp_bridge_authority.py"
        ),
        "task-bas146-database",
    ),
    (
        "engineering",
        "service:scoped-seller-erp-bridge-v1",
        "service",
        "ScopedSellerErpBridge v1",
        "apps/control_plane/scoped_seller_erp_bridge.py",
        "task-bas146-pytest",
    ),
    (
        "runtime",
        "api:scoped-seller-erp-bridge-no-data",
        "api_probe",
        "Authenticated Seller ERP Bridge no-data boundary",
        "http://127.0.0.1:8000/v1/seller-erp-bridge/reconcile",
        "task-bas146-runtime",
    ),
    (
        "runtime",
        "web:seller-erp-bridge-390",
        "browser_probe",
        "Seller ERP Bridge desktop and 390px",
        (
            "output/playwright/"
            "bas146-seller-erp-bridge-mobile-390.png"
        ),
        "task-bas146-web",
    ),
    (
        "evidence",
        "evidence:BAS-146",
        "evidence",
        "BAS-146 authorized Seller ERP Bridge Evidence",
        EVIDENCE,
        "task-bas146-evidence",
    ),
)

EDGE_SPECS = (
    (
        "requirement:BR-120@master-8.48",
        "specified_by",
        "adr:ADR-0066",
        "requirements",
    ),
    (
        "adr:ADR-0066",
        "persisted_by",
        "migration:20260729-0074-seller-erp-bridge",
        "engineering",
    ),
    (
        "migration:20260729-0074-seller-erp-bridge",
        "implemented_by",
        "service:scoped-seller-erp-bridge-v1",
        "engineering",
    ),
    (
        "service:scoped-seller-erp-bridge-v1",
        "observed_as",
        "api:scoped-seller-erp-bridge-no-data",
        "runtime",
    ),
    (
        "api:scoped-seller-erp-bridge-no-data",
        "rendered_by",
        "web:seller-erp-bridge-390",
        "runtime",
    ),
    (
        "web:seller-erp-bridge-390",
        "recorded_in",
        "evidence:BAS-146",
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
            "tests/test_scoped_seller_erp_bridge.py",
            "tests/test_api_contract.py",
            "-q",
            "-p",
            "no:cacheprovider",
            f"--basetemp=output/pytest/bas146-graph-{os.getpid()}",
        ]
    )
    output = process.stdout + process.stderr
    match = re.search(r"(\d+) passed", output)
    if match is None or "[100%]" not in output:
        raise RuntimeError("BAS-146 focused pytest did not pass")
    passed = int(match.group(1))
    if passed != 49:
        raise RuntimeError(
            f"BAS-146 focused test count drifted: {passed}"
        )

    engine = create_database_engine()
    with engine.connect() as connection:
        revision = str(
            connection.execute(
                text("select version_num from alembic_version")
            ).scalar_one()
        )
        bridge_indexes = int(
            connection.execute(
                text(
                    "select count(*) from pg_indexes "
                    "where tablename='evidence_records' "
                    "and indexname in ("
                    "'uq_seller_erp_bridge_source_ref',"
                    "'uq_seller_erp_bridge_review_ref',"
                    "'uq_seller_erp_bridge_binding_ref',"
                    "'uq_seller_erp_bridge_revocation_ref')"
                )
            ).scalar_one()
        )
        bridge_evidence = int(
            connection.execute(
                text(
                    "select count(*) from evidence_records "
                    "where source in ("
                    "'seller_erp_bridge_source',"
                    "'seller_erp_bridge_review',"
                    "'seller_erp_bridge_binding',"
                    "'seller_erp_bridge_revocation')"
                )
            ).scalar_one()
        )
        order_facts = int(
            connection.execute(
                text(
                    "select count(*) from fact_records "
                    "where fact_type='ozon_order' "
                    "and tenant_ref is not null"
                )
            ).scalar_one()
        )
        inventory_facts = int(
            connection.execute(
                text(
                    "select count(*) from fact_records "
                    "where fact_type='ozon_inventory' "
                    "and tenant_ref is not null"
                )
            ).scalar_one()
        )
        operating_tasks_before = int(
            connection.execute(
                text("select count(*) from operating_tasks")
            ).scalar_one()
        )
    if revision != "20260729_0074" or bridge_indexes != 4:
        raise RuntimeError(
            "real PostgreSQL is not at single 0074 with four Bridge indexes"
        )
    if bridge_evidence or order_facts or inventory_facts:
        raise RuntimeError(
            "BAS-146 verification cannot synthesize Bridge/order/inventory data"
        )

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
        raise RuntimeError("BAS-146 delivery containers are not healthy")

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
    route = f"{base}/v1/seller-erp-bridge/reconcile"
    headers = {"X-KJDS-API-Key": api_key}
    params = {"store_ref": STORE_REF, "as_of": FIXED_AS_OF}
    readiness = httpx.get(f"{base}/health/ready", timeout=10)
    anonymous = httpx.get(route, params=params, timeout=20)
    scoped_a = httpx.get(
        route, params=params, headers=headers, timeout=20
    )
    scoped_b = httpx.get(
        route, params=params, headers=headers, timeout=20
    )
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
        or scoped_a.status_code != 200
        or scoped_b.status_code != 200
        or forbidden.status_code != 403
    ):
        raise RuntimeError("BAS-146 live auth boundary drifted")
    bridge = scoped_a.json()
    replay = scoped_b.json()
    counts = bridge.get("counts", {})
    envelope = bridge.get("control_envelope", {})
    artifact = bridge.get("agent_artifact", {})
    if (
        bridge.get("status") != "no_data"
        or bridge.get("scope", {}).get("entity_ref") is not None
        or any(counts.values())
        or envelope.get("scoped_input_read") is not False
        or envelope.get("formal_fact_promoted") is not False
        or envelope.get("private_interface_used") is not False
        or envelope.get("external_write_allowed") is not False
        or artifact.get("self_approval_allowed") is not False
        or artifact.get("permit_issue_allowed") is not False
        or artifact.get("formal_fact_promotion_allowed") is not False
        or bridge.get("snapshot_sha256")
        != replay.get("snapshot_sha256")
        or artifact.get("artifact_sha256")
        != replay.get("agent_artifact", {}).get("artifact_sha256")
    ):
        raise RuntimeError("BAS-146 no-data/no-write replay drifted")
    with engine.connect() as connection:
        operating_tasks_after = int(
            connection.execute(
                text("select count(*) from operating_tasks")
            ).scalar_one()
        )
    if operating_tasks_after != operating_tasks_before:
        raise RuntimeError(
            "BAS-146 read verification created an operating task"
        )

    if any(file_sha(path) != digest for path, digest in SCREENSHOTS.items()):
        raise RuntimeError("BAS-146 browser Evidence hash drifted")
    evidence_text = (ROOT / EVIDENCE).read_text(encoding="utf-8")
    for marker in (
        "DONE_ENGINEERING",
        "865 passed",
        "inner/client/scrollWidth = 390/390/390",
        "Bridge Evidence 0",
        "external_write_allowed=false",
    ):
        if marker not in evidence_text:
            raise RuntimeError(f"BAS-146 Evidence marker missing: {marker}")

    return {
        "tests": {
            "state": "passed",
            "summary": (
                f"{passed} focused tests; 865 full tests; "
                "CSV/XLSX and three-domain authority chain covered"
            ),
            "input_sha256": _sha(
                [
                    file_sha(
                        "apps/control_plane/"
                        "scoped_seller_erp_bridge.py"
                    ),
                    file_sha(
                        "tests/test_scoped_seller_erp_bridge.py"
                    ),
                    file_sha("tests/test_api_contract.py"),
                ]
            ),
            "artifact_ref": "process:pytest BAS-146",
        },
        "database": {
            "state": "passed",
            "summary": (
                f"PostgreSQL {revision}; {bridge_indexes} authority indexes; "
                f"Bridge Evidence {bridge_evidence}; "
                f"Order/Inventory Facts {order_facts}/{inventory_facts}"
            ),
            "input_sha256": _sha(
                [
                    revision,
                    bridge_indexes,
                    bridge_evidence,
                    order_facts,
                    inventory_facts,
                ]
            ),
            "artifact_ref": (
                "postgres:alembic_version,pg_indexes,"
                "evidence_records,fact_records"
            ),
        },
        "runtime": {
            "state": "passed",
            "summary": (
                "four containers healthy; Bridge 401/403/200-no_data; "
                "fixed-as_of replay stable; no task mutation or writes"
            ),
            "input_sha256": _sha(
                [
                    bridge["snapshot_sha256"],
                    artifact["artifact_sha256"],
                    operating_tasks_after,
                ]
            ),
            "artifact_ref": route,
        },
        "web": {
            "state": "passed",
            "summary": (
                "desktop 1440 and mobile 390 Bridge no_data; "
                "zero horizontal overflow and console errors"
            ),
            "input_sha256": _sha(SCREENSHOTS),
            "artifact_ref": (
                "output/playwright/"
                "bas146-seller-erp-bridge-mobile-390.png"
            ),
        },
        "evidence": {
            "state": "passed",
            "summary": f"BAS-146 Evidence SHA-256 {file_sha(EVIDENCE)}",
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
                "id": f"bas146-{verifier_id}",
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
        if session.get(GoalTaskRow, "task-bas145-evidence") is None:
            raise RuntimeError("BAS-145 Graph dependency is missing")
        for task_id, title, verifier, dependencies, workspace in TASK_SPECS:
            task = session.get(GoalTaskRow, task_id)
            if task is None:
                task = GoalTaskRow(
                    id=task_id,
                    project_id=PROJECT_ID,
                    title=title,
                    owner="seller-erp-bridge-engineering",
                    verifier_id=f"bas146-{verifier}",
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
                task.owner = "seller-erp-bridge-engineering"
                task.verifier_id = f"bas146-{verifier}"
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
                "verifier_id": f"bas146-{verifier}",
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
