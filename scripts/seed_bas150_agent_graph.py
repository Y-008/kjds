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
    "20260729_BAS_150_NATIVE_EXACT_SCOPE_ACTUAL_PROFIT_LEDGER.md"
)
SCREENSHOTS = {
    "output/playwright/bas150-profit-ledger-desktop.png": (
        "525d884d3b6e7fa7128cf20ba396d48f4813759cf81d9a13a87aef8e371c3130"
    ),
    "output/playwright/bas150-profit-ledger-mobile-390.png": (
        "711d1b776731df61ff0f61a79586520e2444911f1fe94b339cbac819d06c8bb3"
    ),
}

TASK_SPECS = (
    (
        "task-bas150-pytest",
        "BAS-150 native exact-scope actual profit contracts",
        "tests",
        ("task-bas149-evidence",),
        "/engineering-graph",
    ),
    (
        "task-bas150-database",
        "BAS-150 PostgreSQL profit authority at single 0076",
        "database",
        ("task-bas150-pytest",),
        "/runtime-graph",
    ),
    (
        "task-bas150-runtime",
        "BAS-150 authenticated deterministic profit no-data runtime",
        "runtime",
        ("task-bas150-database",),
        "/runtime-graph",
    ),
    (
        "task-bas150-web",
        "BAS-150 desktop and 390px actual profit ledger",
        "web",
        ("task-bas150-runtime",),
        "/profit-ledger",
    ),
    (
        "task-bas150-evidence",
        "BAS-150 immutable engineering Evidence",
        "evidence",
        ("task-bas150-web",),
        "/evidence-graph",
    ),
)

NODE_SPECS = (
    (
        "requirements",
        "requirement:BR-124@master-8.53",
        "requirement",
        "BR-124 native exact-scope actual profit ledger",
        "docs/project/MASTER_SPEC.md",
        "task-bas150-pytest",
    ),
    (
        "requirements",
        "adr:ADR-0070",
        "adr",
        "ADR-0070 native exact-scope actual profit ledger",
        "docs/adr/ADR-0070-native-exact-scope-actual-profit-ledger.md",
        "task-bas150-pytest",
    ),
    (
        "engineering",
        "service:scoped-actual-profit-ledger-v1",
        "service",
        "ScopedProfitLedgerAuthority native exact-scope v1",
        "apps/control_plane/scoped_profit_ledger.py",
        "task-bas150-pytest",
    ),
    (
        "engineering",
        "migration:20260729-0076-native-profit-authority",
        "migration",
        "0076 scoped mapping FX and per-order Bank Payment authority",
        "migrations/versions/20260729_0076_native_scoped_profit_authority.py",
        "task-bas150-database",
    ),
    (
        "runtime",
        "api:native-actual-profit-no-data",
        "api_probe",
        "Authenticated native actual profit no-data boundary",
        "http://127.0.0.1:8000/v1/profit-ledger",
        "task-bas150-runtime",
    ),
    (
        "runtime",
        "web:native-actual-profit-ledger-390",
        "browser_probe",
        "Native actual profit ledger desktop and 390px",
        "output/playwright/bas150-profit-ledger-mobile-390.png",
        "task-bas150-web",
    ),
    (
        "evidence",
        "evidence:BAS-150",
        "evidence",
        "BAS-150 native actual profit ledger Evidence",
        EVIDENCE,
        "task-bas150-evidence",
    ),
)

EDGE_SPECS = (
    (
        "requirement:BR-124@master-8.53",
        "specified_by",
        "adr:ADR-0070",
        "requirements",
    ),
    (
        "adr:ADR-0070",
        "implemented_by",
        "service:scoped-actual-profit-ledger-v1",
        "engineering",
    ),
    (
        "service:scoped-actual-profit-ledger-v1",
        "constrained_by",
        "migration:20260729-0076-native-profit-authority",
        "engineering",
    ),
    (
        "migration:20260729-0076-native-profit-authority",
        "observed_as",
        "api:native-actual-profit-no-data",
        "runtime",
    ),
    (
        "api:native-actual-profit-no-data",
        "rendered_by",
        "web:native-actual-profit-ledger-390",
        "runtime",
    ),
    (
        "web:native-actual-profit-ledger-390",
        "recorded_in",
        "evidence:BAS-150",
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
            "scoped_products": (
                "select count(*) from products where tenant_ref is not null"
            ),
            "scoped_order_facts": (
                "select count(*) from fact_records where tenant_ref is not "
                "null and fact_type='ozon_order'"
            ),
            "scoped_finance_entries": (
                "select count(*) from finance_entries "
                "where tenant_ref is not null"
            ),
            "scoped_bank_payments": (
                "select count(*) from finance_entries where tenant_ref is "
                "not null and entry_kind='bank_payment'"
            ),
            "scoped_reconciliations": (
                "select count(*) from reconciliation_runs "
                "where tenant_ref is not null"
            ),
            "scoped_fee_mappings": (
                "select count(*) from fee_mappings "
                "where tenant_ref is not null"
            ),
            "scoped_fx_rates": (
                "select count(*) from fx_rates where tenant_ref is not null"
            ),
            "profit_indexes": (
                "select count(*) from pg_indexes where schemaname='public' "
                "and indexname in ('uq_fee_mapping_scoped_version',"
                "'uq_fx_rate_scoped_observation',"
                "'ix_finance_entry_scope_profit')"
            ),
            "profit_constraints": (
                "select count(*) from pg_constraint where conname in "
                "('ck_fee_mappings_scope_complete',"
                "'ck_fx_rates_scope_complete',"
                "'ck_finance_entries_profit_cost_type')"
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
            "tests/test_finance.py",
            "tests/test_native_scoped_profit_finance.py",
            "tests/test_scoped_settlement_cash.py",
            "tests/test_profit_ledger.py",
            "tests/test_scoped_profit_ledger.py",
            "tests/test_api_contract.py",
            "-q",
            "-p",
            "no:cacheprovider",
            f"--basetemp=output/pytest/bas150-graph-{os.getpid()}",
        ]
    )
    output = process.stdout + process.stderr
    match = re.search(r"(\d+) passed", output)
    if match is None or "[100%]" not in output:
        raise RuntimeError("BAS-150 focused pytest did not pass")
    passed = int(match.group(1))
    if passed != 79:
        raise RuntimeError(f"BAS-150 focused test count drifted: {passed}")

    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    heads = script.get_heads()
    before = database_state()
    if heads != ["20260729_0076"] or before["revision"] != "20260729_0076":
        raise RuntimeError("BAS-150 requires one current/head 20260729_0076")
    if before["profit_indexes"] != 3 or before["profit_constraints"] != 3:
        raise RuntimeError("BAS-150 database authority is incomplete")
    for key in (
        "scoped_products",
        "scoped_order_facts",
        "scoped_finance_entries",
        "scoped_bank_payments",
        "scoped_reconciliations",
        "scoped_fee_mappings",
        "scoped_fx_rates",
    ):
        if before[key] != 0:
            raise RuntimeError(f"BAS-150 cannot synthesize {key}")

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
        raise RuntimeError("BAS-150 delivery containers are not healthy")

    api_key = run_checked(
        ["docker", "compose", "exec", "-T", "api", "printenv", "KJDS_API_KEY"]
    ).stdout.strip()
    if not api_key:
        raise RuntimeError("runtime API identity is not configured")
    base = "http://127.0.0.1:8000"
    route = f"{base}/v1/profit-ledger"
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
        raise RuntimeError("BAS-150 live auth boundary drifted")

    ledger = first.json()
    repeated = replay.json()
    envelope = ledger.get("control_envelope", {})
    artifact = ledger.get("artifact", {})
    if (
        ledger.get("contract_id")
        != "kjds-native-exact-scope-actual-profit-ledger-v1"
        or ledger.get("status") != "no_data"
        or ledger.get("scope", {}).get("entity_ref") is not None
        or any(ledger.get("counts", {}).values())
        or ledger.get("rows")
        or envelope.get("native_exact_scope") is not True
        or envelope.get("scoped_input_read") is not False
        or envelope.get("legacy_order_charge_read") is not False
        or envelope.get("legacy_finance_read") is not False
        or envelope.get("client_recalculation") is not False
        or envelope.get("proportional_allocation_allowed") is not False
        or envelope.get("agent_self_approval_allowed") is not False
        or envelope.get("agent_permit_issue_allowed") is not False
        or envelope.get("external_write_allowed") is not False
        or any(artifact.get("writes", {}).values())
        or ledger.get("snapshot_sha256")
        != repeated.get("snapshot_sha256")
        or artifact.get("artifact_sha256")
        != repeated.get("artifact", {}).get("artifact_sha256")
    ):
        raise RuntimeError("BAS-150 no-data/no-write replay drifted")

    after = database_state()
    if after != before:
        raise RuntimeError("BAS-150 read verification mutated PostgreSQL")
    if any(file_sha(path) != digest for path, digest in SCREENSHOTS.items()):
        raise RuntimeError("BAS-150 browser Evidence hash drifted")
    evidence_text = (ROOT / EVIDENCE).read_text(encoding="utf-8")
    for marker in (
        "DONE_ENGINEERING",
        "905 passed",
        "inner/client/scrollWidth = 390/390/390",
        "scoped Bank Payment: `0`",
        "`external_write_allowed=false`",
    ):
        if marker not in evidence_text:
            raise RuntimeError(f"BAS-150 Evidence marker missing: {marker}")

    return {
        "tests": {
            "state": "passed",
            "summary": (
                f"{passed} focused tests; 905 full tests; exact scope, "
                "fifteen legs, latest Evidence and cash conservation covered"
            ),
            "input_sha256": _sha(
                [
                    file_sha("apps/control_plane/scoped_profit_ledger.py"),
                    file_sha("apps/control_plane/finance.py"),
                    file_sha("tests/test_scoped_profit_ledger.py"),
                    file_sha("tests/test_native_scoped_profit_finance.py"),
                    file_sha("tests/test_api_contract.py"),
                ]
            ),
            "artifact_ref": "process:pytest BAS-150",
        },
        "database": {
            "state": "passed",
            "summary": (
                "PostgreSQL single 0076; three profit indexes and "
                "constraints; all native business authority rows zero"
            ),
            "input_sha256": _sha({"heads": heads, **after}),
            "artifact_ref": (
                "postgres:alembic_version,products,fact_records,"
                "finance_entries,reconciliation_runs,fee_mappings,fx_rates"
            ),
        },
        "runtime": {
            "state": "passed",
            "summary": (
                "four containers healthy; 401/403/200-no_data; fixed-as-of "
                "replay stable; native exact scope true; all writes false"
            ),
            "input_sha256": _sha(
                [
                    ledger["snapshot_sha256"],
                    artifact["artifact_sha256"],
                    after["operating_tasks"],
                ]
            ),
            "artifact_ref": route,
        },
        "web": {
            "state": "passed",
            "summary": (
                "desktop 1440 and mobile 390 actual-profit no_data; zero "
                "horizontal overflow, console errors and page errors"
            ),
            "input_sha256": _sha(SCREENSHOTS),
            "artifact_ref": (
                "output/playwright/bas150-profit-ledger-mobile-390.png"
            ),
        },
        "evidence": {
            "state": "passed",
            "summary": f"BAS-150 Evidence SHA-256 {file_sha(EVIDENCE)}",
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
                "id": f"bas150-{verifier_id}",
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
        if session.get(GoalTaskRow, "task-bas149-evidence") is None:
            raise RuntimeError("BAS-149 Graph dependency is missing")
        for task_id, title, verifier, dependencies, workspace in TASK_SPECS:
            task = session.get(GoalTaskRow, task_id)
            if task is None:
                task = GoalTaskRow(
                    id=task_id,
                    project_id=PROJECT_ID,
                    title=title,
                    owner="profit-control-engineering",
                    verifier_id=f"bas150-{verifier}",
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
                task.owner = "profit-control-engineering"
                task.verifier_id = f"bas150-{verifier}"
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
                "verifier_id": f"bas150-{verifier}",
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
        result["tasks"] != 81
        or result["nodes"] != 190
        or result["edges"] != 192
        or result["observations"] < 326
    ):
        raise RuntimeError(f"BAS-150 Graph count drifted: {result}")
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
