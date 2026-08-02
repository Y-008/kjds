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
INVENTORY_EVIDENCE = (
    "docs/project/evidence/"
    "20260729_BAS_142_NATIVE_SCOPED_INVENTORY_FULFILLMENT.md"
)
BASELINE_EVIDENCE = (
    "docs/project/evidence/"
    "20260729_BAS_143_MARKET_VALIDATED_AI_ERP_BASELINE.md"
)

TASK_SPECS = (
    (
        "task-bas142-pytest",
        "BAS-142 inventory and fulfillment contracts",
        "tests",
        ("task-bas140-pytest",),
        "/engineering-graph",
    ),
    (
        "task-bas142-database",
        "BAS-142 PostgreSQL 0073 migration and row preservation",
        "database",
        ("task-bas142-pytest",),
        "/runtime-graph",
    ),
    (
        "task-bas142-runtime",
        "BAS-142 exact-scope inventory runtime",
        "runtime",
        ("task-bas142-database",),
        "/runtime-graph",
    ),
    (
        "task-bas142-web",
        "BAS-142 desktop and 390px inventory workbench",
        "web",
        ("task-bas142-runtime",),
        "/inventory",
    ),
    (
        "task-bas142-evidence",
        "BAS-142 immutable engineering Evidence",
        "evidence",
        ("task-bas142-web",),
        "/evidence-graph",
    ),
    (
        "task-bas143-market-baseline",
        "BAS-143 market-validated Must-have AI ERP baseline",
        "baseline",
        ("task-bas142-evidence",),
        "/commerce-os",
    ),
)

NODE_SPECS = (
    (
        "requirements",
        "requirement:BR-116@master-8.46",
        "requirement",
        "BR-116 native scoped inventory and fulfillment",
        "docs/project/MASTER_SPEC.md",
        "task-bas142-pytest",
    ),
    (
        "requirements",
        "adr:ADR-0062",
        "adr",
        "ADR-0062 native scoped inventory and fulfillment",
        "docs/adr/ADR-0062-native-scoped-inventory-fulfillment.md",
        "task-bas142-pytest",
    ),
    (
        "engineering",
        "service:scoped-inventory-v1",
        "service",
        "ScopedInventoryFulfillmentWorkspace v1",
        "apps/control_plane/scoped_inventory.py",
        "task-bas142-pytest",
    ),
    (
        "engineering",
        "migration:0073",
        "migration",
        "0073 exact-scope inventory lookup index",
        "migrations/versions/20260729_0073_scoped_inventory_fulfillment.py",
        "task-bas142-database",
    ),
    (
        "runtime",
        "api:scoped-inventory-no-data",
        "api_probe",
        "Authenticated inventory no-data and no-write boundary",
        "http://127.0.0.1:8000/v1/inventory/workspace",
        "task-bas142-runtime",
    ),
    (
        "runtime",
        "web:native-inventory-390",
        "browser_probe",
        "Native inventory desktop and 390px workbench",
        "output/playwright/release-0.59.0/native-inventory-mobile-390.png",
        "task-bas142-web",
    ),
    (
        "evidence",
        "evidence:BAS-142",
        "evidence",
        "BAS-142 native inventory engineering Evidence",
        INVENTORY_EVIDENCE,
        "task-bas142-evidence",
    ),
    (
        "requirements",
        "requirement:BR-117@master-8.46",
        "requirement",
        "BR-117 market-validated Must-have Agentized ERP",
        "docs/project/MASTER_SPEC.md",
        "task-bas143-market-baseline",
    ),
    (
        "requirements",
        "adr:ADR-0063",
        "adr",
        "ADR-0063 native parity and Agentization",
        "docs/adr/ADR-0063-market-validated-native-parity-and-agentization.md",
        "task-bas143-market-baseline",
    ),
    (
        "engineering",
        "registry:market-validated-native-parity-v2.1",
        "registry",
        "Eight-provider Must-have native parity registry",
        "docs/project/registries/competitive_capability_patterns.json",
        "task-bas143-market-baseline",
    ),
    (
        "runtime",
        "web:market-validated-native-parity",
        "browser_probe",
        "Commerce OS eight-provider Must-have baseline",
        (
            "output/playwright/release-0.59.0/"
            "native-must-have-baseline-desktop.png"
        ),
        "task-bas143-market-baseline",
    ),
    (
        "evidence",
        "evidence:BAS-143",
        "evidence",
        "BAS-143 AI ERP baseline Evidence",
        BASELINE_EVIDENCE,
        "task-bas143-market-baseline",
    ),
)

EDGE_SPECS = (
    (
        "requirement:BR-116@master-8.46",
        "specified_by",
        "adr:ADR-0062",
        "requirements",
    ),
    (
        "adr:ADR-0062",
        "implemented_by",
        "service:scoped-inventory-v1",
        "engineering",
    ),
    (
        "service:scoped-inventory-v1",
        "indexed_by",
        "migration:0073",
        "engineering",
    ),
    (
        "migration:0073",
        "observed_as",
        "api:scoped-inventory-no-data",
        "runtime",
    ),
    (
        "api:scoped-inventory-no-data",
        "rendered_by",
        "web:native-inventory-390",
        "runtime",
    ),
    (
        "web:native-inventory-390",
        "recorded_in",
        "evidence:BAS-142",
        "evidence",
    ),
    (
        "requirement:BR-117@master-8.46",
        "specified_by",
        "adr:ADR-0063",
        "requirements",
    ),
    (
        "adr:ADR-0063",
        "compiled_as",
        "registry:market-validated-native-parity-v2.1",
        "engineering",
    ),
    (
        "registry:market-validated-native-parity-v2.1",
        "rendered_by",
        "web:market-validated-native-parity",
        "runtime",
    ),
    (
        "web:market-validated-native-parity",
        "recorded_in",
        "evidence:BAS-143",
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
    pytest_process = run_checked(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_scoped_inventory.py",
            "tests/test_ozon_contracts.py",
            "tests/test_imports.py",
            "tests/test_scoped_facts.py",
            "tests/test_api_contract.py",
            "tests/test_security.py",
            "tests/test_competitive_capability_patterns.py",
            "tests/test_commerce_operating_system.py",
            "-q",
            "-p",
            "no:cacheprovider",
            (
                "--basetemp=output/pytest/"
                f"bas142-graph-{os.getpid()}"
            ),
        ]
    )
    pytest_text = pytest_process.stdout + pytest_process.stderr
    match = re.search(r"(\d+) passed", pytest_text)
    if match is None or "[100%]" not in pytest_text:
        raise RuntimeError("BAS-142/143 focused pytest did not pass")
    passed = int(match.group(1))

    engine = create_database_engine()
    with engine.connect() as connection:
        revision = str(
            connection.execute(
                text("select version_num from alembic_version")
            ).scalar_one()
        )
        index_count = int(
            connection.execute(
                text(
                    "select count(*) from pg_indexes "
                    "where schemaname='public' and "
                    "indexname="
                    "'ix_fact_scope_inventory_product_effective'"
                )
            ).scalar_one()
        )
        inventory_fact_count = int(
            connection.execute(
                text(
                    "select count(*) from fact_records "
                    "where fact_type='ozon_inventory'"
                )
            ).scalar_one()
        )
        task_count_before = int(
            connection.execute(
                text("select count(*) from operating_tasks")
            ).scalar_one()
        )
    if revision != "20260729_0073" or index_count != 1:
        raise RuntimeError("real database is not at single indexed 0073")
    if inventory_fact_count != 0:
        raise RuntimeError("BAS-142 must not synthesize inventory Facts")

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
        raise RuntimeError("BAS-142 delivery containers are not healthy")

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
    anonymous = httpx.get(
        f"{base}/v1/inventory/workspace",
        params={"store_ref": STORE_REF},
        timeout=10,
    )
    scoped = httpx.get(
        f"{base}/v1/inventory/workspace",
        params={"store_ref": STORE_REF},
        headers=headers,
        timeout=10,
    )
    forbidden = httpx.get(
        f"{base}/v1/inventory/workspace",
        params={"store_ref": "other-store"},
        headers=headers,
        timeout=10,
    )
    commerce = httpx.get(
        f"{base}/v1/commerce-os/workspace",
        params={"store_ref": STORE_REF},
        headers=headers,
        timeout=10,
    )
    if (
        readiness.status_code != 200
        or readiness.json().get("version") != "0.59.0"
        or anonymous.status_code != 401
        or scoped.status_code != 200
        or forbidden.status_code != 403
        or commerce.status_code != 200
    ):
        raise RuntimeError("BAS-142/143 live auth boundary drifted")
    inventory = scoped.json()
    baseline = commerce.json()
    if (
        inventory.get("status") != "no_data"
        or inventory.get("scope", {}).get("entity_ref") is not None
        or inventory.get("counts", {}).get("raw_inventory_facts") != 0
        or inventory.get("counts", {}).get(
            "legacy_inventory_rows_read"
        )
        != 0
        or inventory.get("counts", {}).get(
            "marketplace_observations_inferred"
        )
        != 0
        or inventory.get("control_envelope", {}).get(
            "external_write_allowed"
        )
        is not False
    ):
        raise RuntimeError("BAS-142 no-data/no-write contract drifted")
    policy = baseline.get("benchmark_baseline_policy", {})
    if (
        len(baseline.get("benchmark_coverage", [])) != 8
        or policy.get("requirement") != "must_have_native_parity"
        or policy.get("safe_capability_omission_allowed") is not False
        or policy.get("external_write_allowed") is not False
    ):
        raise RuntimeError("BAS-143 market baseline drifted")
    with engine.connect() as connection:
        task_count_after = int(
            connection.execute(
                text("select count(*) from operating_tasks")
            ).scalar_one()
        )
    if task_count_after != task_count_before:
        raise RuntimeError("BAS-142 read verification created a task")

    screenshots = {
        (
            "output/playwright/release-0.59.0/"
            "native-inventory-desktop.png"
        ): (
            "c1c5f901483c19399bb79f7d4dff3c8571ee386867e1a78b"
            "1bbc8ecade7406fe"
        ),
        (
            "output/playwright/release-0.59.0/"
            "native-inventory-mobile-390.png"
        ): (
            "9b92198ce985f8bbcea315520ee6a748f32f7e19ce0552725"
            "bc443ffa1f1eb3d"
        ),
    }
    baseline_screenshot = (
        "output/playwright/release-0.59.0/"
        "native-must-have-baseline-desktop.png"
    )
    if any(file_sha(path) != digest for path, digest in screenshots.items()):
        raise RuntimeError("BAS-142 browser Evidence hash drifted")
    if file_sha(baseline_screenshot) != (
        "06079d9c46446be7703e836c959ebb810f6d5fe85ee6e596a2bf24e068935a05"
    ):
        raise RuntimeError("BAS-143 browser Evidence hash drifted")

    return {
        "tests": {
            "state": "passed",
            "summary": f"{passed} inventory/baseline focused tests passed",
            "input_sha256": _sha(
                [
                    file_sha("apps/control_plane/scoped_inventory.py"),
                    file_sha("tests/test_scoped_inventory.py"),
                ]
            ),
            "artifact_ref": "process:pytest BAS-142/143",
        },
        "database": {
            "state": "passed",
            "summary": (
                "PostgreSQL 0073; exact inventory index 1; "
                "inventory Facts 0"
            ),
            "input_sha256": _sha(
                [revision, index_count, inventory_fact_count]
            ),
            "artifact_ref": "postgres:alembic_version,pg_indexes",
        },
        "runtime": {
            "state": "passed",
            "summary": (
                "four containers healthy; inventory 401/403/200-no_data; "
                "no task mutation; external write false"
            ),
            "input_sha256": _sha(
                [inventory["snapshot_sha256"], task_count_after]
            ),
            "artifact_ref": f"{base}/v1/inventory/workspace",
        },
        "web": {
            "state": "passed",
            "summary": (
                "desktop 1440 and mobile 390 inventory no_data; "
                "zero horizontal overflow/errors/failed responses"
            ),
            "input_sha256": _sha(screenshots),
            "artifact_ref": next(reversed(screenshots)),
        },
        "evidence": {
            "state": "passed",
            "summary": f"BAS-142 Evidence {file_sha(INVENTORY_EVIDENCE)}",
            "input_sha256": file_sha(INVENTORY_EVIDENCE),
            "artifact_ref": INVENTORY_EVIDENCE,
        },
        "baseline": {
            "state": "passed",
            "summary": (
                "eight-provider Must-have native parity contract projected; "
                "mapping remains separate from implementation"
            ),
            "input_sha256": _sha(
                [
                    file_sha(
                        "docs/project/registries/"
                        "competitive_capability_patterns.json"
                    ),
                    file_sha(BASELINE_EVIDENCE),
                    file_sha(baseline_screenshot),
                ]
            ),
            "artifact_ref": BASELINE_EVIDENCE,
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
        "baseline": ("registry_and_browser_probe", "architecture"),
    }
    for verifier_id, (source_type, authority) in verifier_defs.items():
        service.register_verifier(
            {
                "id": f"bas142-{verifier_id}",
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
        if session.get(GoalTaskRow, "task-bas140-pytest") is None:
            raise RuntimeError("shared order-semantics test dependency is missing")
        for task_id, title, verifier, dependencies, workspace in TASK_SPECS:
            existing_task = session.get(GoalTaskRow, task_id)
            if existing_task is None:
                session.add(
                    GoalTaskRow(
                        id=task_id,
                        project_id=PROJECT_ID,
                        title=title,
                        owner="inventory-ai-erp-engineering",
                        verifier_id=f"bas142-{verifier}",
                        verifier_version="1",
                        dependency_ids_json=list(dependencies),
                        verification_condition=(
                            "fresh external verifier observation is passed"
                        ),
                        next_safe_action=(
                            "inspect artifact and rerun bounded verifier"
                        ),
                        workspace=workspace,
                        sla_seconds=86400,
                        fingerprint=_sha([PROJECT_ID, task_id]),
                        created_at=now,
                    )
                )
            else:
                existing_task.title = title
                existing_task.owner = "inventory-ai-erp-engineering"
                existing_task.verifier_id = f"bas142-{verifier}"
                existing_task.verifier_version = "1"
                existing_task.dependency_ids_json = list(dependencies)
                existing_task.verification_condition = (
                    "fresh external verifier observation is passed"
                )
                existing_task.next_safe_action = (
                    "inspect artifact and rerun bounded verifier"
                )
                existing_task.workspace = workspace

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
            existing = session.get(GraphNodeRow, node_id)
            if existing is None:
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
                existing.node_type = node_type
                existing.label = label
                existing.source = artifact
                existing.content_sha256 = _sha(content)
                existing.artifact_ref = artifact
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
                        evidence_ref=(
                            BASELINE_EVIDENCE
                            if "BR-117" in source
                            or "0063" in source
                            or "native-parity" in source
                            else INVENTORY_EVIDENCE
                        ),
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
                "verifier_id": f"bas142-{verifier}",
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
                "evidence_ref": (
                    BASELINE_EVIDENCE
                    if verifier == "baseline"
                    else INVENTORY_EVIDENCE
                ),
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
                "market_baseline_status": "in_progress",
                "external_write_allowed": False,
            },
            sort_keys=True,
        )
    )
