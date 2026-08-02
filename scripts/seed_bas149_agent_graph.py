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
    "20260729_BAS_149_NATIVE_EXACT_SCOPE_SETTLEMENT_CASH_CONTROL.md"
)
SCREENSHOTS = {
    "output/playwright/bas149-finance-control-desktop.png": (
        "eb15952b3d1136feb4e76573c91f89af7c86072f6ff0e0d3a3994084b8630d25"
    ),
    "output/playwright/bas149-finance-control-mobile-390.png": (
        "ae1e623b3258ac2e6eefe37508b1a31d5d942e3a927c825668c4fd7a1e336cd1"
    ),
}

TASK_SPECS = (
    (
        "task-bas149-pytest",
        "BAS-149 exact-scope settlement and cash contracts",
        "tests",
        ("task-bas148-evidence",),
        "/engineering-graph",
    ),
    (
        "task-bas149-database",
        "BAS-149 PostgreSQL scoped finance authority at single 0075",
        "database",
        ("task-bas149-pytest",),
        "/runtime-graph",
    ),
    (
        "task-bas149-runtime",
        "BAS-149 authenticated deterministic finance no-data runtime",
        "runtime",
        ("task-bas149-database",),
        "/runtime-graph",
    ),
    (
        "task-bas149-web",
        "BAS-149 desktop and 390px settlement cash control",
        "web",
        ("task-bas149-runtime",),
        "/finance-control",
    ),
    (
        "task-bas149-evidence",
        "BAS-149 immutable engineering Evidence",
        "evidence",
        ("task-bas149-web",),
        "/evidence-graph",
    ),
)

NODE_SPECS = (
    (
        "requirements",
        "requirement:BR-123@master-8.52",
        "requirement",
        "BR-123 native exact-scope settlement and cash control",
        "docs/project/MASTER_SPEC.md",
        "task-bas149-pytest",
    ),
    (
        "requirements",
        "adr:ADR-0069",
        "adr",
        "ADR-0069 native exact-scope settlement and cash control",
        "docs/adr/ADR-0069-native-exact-scope-settlement-cash-control.md",
        "task-bas149-pytest",
    ),
    (
        "engineering",
        "service:scoped-settlement-cash-workspace-v1",
        "service",
        "ScopedSettlementCashWorkspace v1",
        "apps/control_plane/scoped_settlement_cash.py",
        "task-bas149-pytest",
    ),
    (
        "engineering",
        "migration:20260729-0075-scoped-finance-authority",
        "migration",
        "0075 complete-or-empty scoped finance authority",
        "migrations/versions/20260729_0075_scoped_finance_authority.py",
        "task-bas149-database",
    ),
    (
        "runtime",
        "api:scoped-settlement-cash-no-data",
        "api_probe",
        "Authenticated settlement and cash no-data boundary",
        "http://127.0.0.1:8000/v1/finance-control/workspace",
        "task-bas149-runtime",
    ),
    (
        "runtime",
        "web:native-settlement-cash-control-390",
        "browser_probe",
        "Native settlement and cash control desktop and 390px",
        "output/playwright/bas149-finance-control-mobile-390.png",
        "task-bas149-web",
    ),
    (
        "evidence",
        "evidence:BAS-149",
        "evidence",
        "BAS-149 native settlement and cash control Evidence",
        EVIDENCE,
        "task-bas149-evidence",
    ),
)

EDGE_SPECS = (
    (
        "requirement:BR-123@master-8.52",
        "specified_by",
        "adr:ADR-0069",
        "requirements",
    ),
    (
        "adr:ADR-0069",
        "implemented_by",
        "service:scoped-settlement-cash-workspace-v1",
        "engineering",
    ),
    (
        "service:scoped-settlement-cash-workspace-v1",
        "constrained_by",
        "migration:20260729-0075-scoped-finance-authority",
        "engineering",
    ),
    (
        "migration:20260729-0075-scoped-finance-authority",
        "observed_as",
        "api:scoped-settlement-cash-no-data",
        "runtime",
    ),
    (
        "api:scoped-settlement-cash-no-data",
        "rendered_by",
        "web:native-settlement-cash-control-390",
        "runtime",
    ),
    (
        "web:native-settlement-cash-control-390",
        "recorded_in",
        "evidence:BAS-149",
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
            "finance_entries": "select count(*) from finance_entries",
            "scoped_finance_entries": (
                "select count(*) from finance_entries "
                "where tenant_ref is not null"
            ),
            "reconciliation_runs": (
                "select count(*) from reconciliation_runs"
            ),
            "scoped_reconciliation_runs": (
                "select count(*) from reconciliation_runs "
                "where tenant_ref is not null"
            ),
            "cash_plan_items": "select count(*) from cash_plan_items",
            "scoped_cash_plan_items": (
                "select count(*) from cash_plan_items "
                "where tenant_ref is not null"
            ),
            "scoped_finance_facts": (
                "select count(*) from fact_records "
                "where tenant_ref is not null and fact_type in "
                "('ozon_order','ozon_accrual','ozon_settlement',"
                "'ozon_fee','ozon_return','ozon_inventory')"
            ),
            "scope_indexes": (
                "select count(*) from pg_indexes where schemaname='public' "
                "and indexname in "
                "('ix_finance_entry_scope_reconciliation',"
                "'ix_reconciliation_scope_key_recorded',"
                "'ix_cash_plan_scope_window',"
                "'uq_finance_entry_scoped_source',"
                "'uq_finance_entry_scoped_fact',"
                "'uq_cash_plan_scoped_source')"
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
            "tests/test_scoped_settlement_cash.py",
            "tests/test_finance.py",
            "tests/test_profit_ledger.py",
            "tests/test_scoped_profit_ledger.py",
            "tests/test_api_contract.py",
            "-q",
            "-p",
            "no:cacheprovider",
            f"--basetemp=output/pytest/bas149-graph-{os.getpid()}",
        ]
    )
    output = process.stdout + process.stderr
    match = re.search(r"(\d+) passed", output)
    if match is None or "[100%]" not in output:
        raise RuntimeError("BAS-149 focused pytest did not pass")
    passed = int(match.group(1))
    if passed != 74:
        raise RuntimeError(f"BAS-149 focused test count drifted: {passed}")

    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    heads = script.get_heads()
    before = database_state()
    if heads != ["20260729_0075"] or before["revision"] != "20260729_0075":
        raise RuntimeError("BAS-149 requires one current/head 20260729_0075")
    if before["scope_indexes"] != 6:
        raise RuntimeError("BAS-149 scoped finance indexes are incomplete")
    for key in (
        "finance_entries",
        "scoped_finance_entries",
        "reconciliation_runs",
        "scoped_reconciliation_runs",
        "cash_plan_items",
        "scoped_cash_plan_items",
        "scoped_finance_facts",
    ):
        if before[key] != 0:
            raise RuntimeError(f"BAS-149 verification cannot synthesize {key}")

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
        raise RuntimeError("BAS-149 delivery containers are not healthy")

    api_key = run_checked(
        ["docker", "compose", "exec", "-T", "api", "printenv", "KJDS_API_KEY"]
    ).stdout.strip()
    if not api_key:
        raise RuntimeError("runtime API identity is not configured")
    base = "http://127.0.0.1:8000"
    route = f"{base}/v1/finance-control/workspace"
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
        raise RuntimeError("BAS-149 live auth boundary drifted")

    workspace = first.json()
    repeated = replay.json()
    envelope = workspace.get("control_envelope", {})
    artifact = workspace.get("agent_artifact", {})
    if (
        workspace.get("contract_id")
        != "kjds-native-exact-scope-settlement-cash-control-v1"
        or workspace.get("status") != "no_data"
        or workspace.get("scope", {}).get("entity_ref") is not None
        or any(workspace.get("counts", {}).values())
        or workspace.get("cycles")
        or envelope.get("scoped_input_read") is not False
        or envelope.get("legacy_finance_rows_admitted") is not False
        or envelope.get("proportional_allocation_allowed") is not False
        or envelope.get("finance_entry_created") is not False
        or envelope.get("reconciliation_created") is not False
        or envelope.get("fact_created") is not False
        or envelope.get("cash_plan_created") is not False
        or envelope.get("approval_created") is not False
        or envelope.get("permit_created") is not False
        or envelope.get("payment_initiated") is not False
        or envelope.get("collection_initiated") is not False
        or envelope.get("refund_initiated") is not False
        or envelope.get("dispute_initiated") is not False
        or envelope.get("external_write_allowed") is not False
        or artifact.get("self_approval_allowed") is not False
        or artifact.get("permit_issue_allowed") is not False
        or artifact.get("finance_record_creation_allowed") is not False
        or artifact.get("payment_or_refund_allowed") is not False
        or artifact.get("external_write_allowed") is not False
        or workspace.get("snapshot_sha256")
        != repeated.get("snapshot_sha256")
        or artifact.get("artifact_sha256")
        != repeated.get("agent_artifact", {}).get("artifact_sha256")
    ):
        raise RuntimeError("BAS-149 no-data/no-write replay drifted")

    after = database_state()
    if after != before:
        raise RuntimeError("BAS-149 read verification mutated PostgreSQL")
    if any(file_sha(path) != digest for path, digest in SCREENSHOTS.items()):
        raise RuntimeError("BAS-149 browser Evidence hash drifted")
    evidence_text = (ROOT / EVIDENCE).read_text(encoding="utf-8")
    for marker in (
        "DONE_ENGINEERING",
        "900 passed",
        "inner/client/scrollWidth = 390/390/390",
        "FinanceEntry: `0`",
        "`external_write_allowed=false`",
    ):
        if marker not in evidence_text:
            raise RuntimeError(f"BAS-149 Evidence marker missing: {marker}")

    return {
        "tests": {
            "state": "passed",
            "summary": (
                f"{passed} focused tests; 900 full tests; latest authority, "
                "three-book conflict and accounting-bypass controls covered"
            ),
            "input_sha256": _sha(
                [
                    file_sha(
                        "apps/control_plane/scoped_settlement_cash.py"
                    ),
                    file_sha("apps/control_plane/finance.py"),
                    file_sha("tests/test_scoped_settlement_cash.py"),
                    file_sha("tests/test_api_contract.py"),
                ]
            ),
            "artifact_ref": "process:pytest BAS-149",
        },
        "database": {
            "state": "passed",
            "summary": (
                "PostgreSQL single 0075; six scoped indexes; "
                "FinanceEntry/Reconciliation/CashPlan "
                f"{after['finance_entries']}/{after['reconciliation_runs']}/"
                f"{after['cash_plan_items']}; scoped finance Facts "
                f"{after['scoped_finance_facts']}"
            ),
            "input_sha256": _sha({"heads": heads, **after}),
            "artifact_ref": (
                "postgres:alembic_version,finance_entries,"
                "reconciliation_runs,cash_plan_items,fact_records"
            ),
        },
        "runtime": {
            "state": "passed",
            "summary": (
                "four containers healthy; 401/403/200-no_data; "
                "fixed-as-of replay stable; all writes false; no mutation"
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
                "desktop 1440 and mobile 390 finance no_data; zero "
                "horizontal overflow and finance-page console errors"
            ),
            "input_sha256": _sha(SCREENSHOTS),
            "artifact_ref": (
                "output/playwright/bas149-finance-control-mobile-390.png"
            ),
        },
        "evidence": {
            "state": "passed",
            "summary": f"BAS-149 Evidence SHA-256 {file_sha(EVIDENCE)}",
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
                "id": f"bas149-{verifier_id}",
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
        if session.get(GoalTaskRow, "task-bas148-evidence") is None:
            raise RuntimeError("BAS-148 Graph dependency is missing")
        for task_id, title, verifier, dependencies, workspace in TASK_SPECS:
            task = session.get(GoalTaskRow, task_id)
            if task is None:
                task = GoalTaskRow(
                    id=task_id,
                    project_id=PROJECT_ID,
                    title=title,
                    owner="finance-control-engineering",
                    verifier_id=f"bas149-{verifier}",
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
                task.owner = "finance-control-engineering"
                task.verifier_id = f"bas149-{verifier}"
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
                "verifier_id": f"bas149-{verifier}",
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
        result["tasks"] != 76
        or result["nodes"] != 183
        or result["edges"] != 186
        or result["observations"] < 320
    ):
        raise RuntimeError(f"BAS-149 Graph count drifted: {result}")
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
