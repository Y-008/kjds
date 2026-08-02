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
    "20260730_BAS_152_NATIVE_EXACT_SCOPE_ACCOUNTS_PAYABLE.md"
)
SCREENSHOTS = {
    "output/playwright/bas152-accounts-payable-desktop.png": (
        "b548fa8c8dc415ac1803f1150080fd59d93841a595c0c4ecd4ff18ea8f855d7d"
    ),
    "output/playwright/bas152-accounts-payable-mobile-390.png": (
        "9137c9011b9fc875998a6d62faed257e2502465e57eac7a6460b27312e5f4897"
    ),
}

TASK_SPECS = (
    (
        "task-bas152-pytest",
        "BAS-152 native exact-scope accounts payable contracts",
        "tests",
        ("task-bas151-evidence",),
        "/engineering-graph",
    ),
    (
        "task-bas152-database",
        "BAS-152 PostgreSQL accounts payable authority at single 0078",
        "database",
        ("task-bas152-pytest",),
        "/runtime-graph",
    ),
    (
        "task-bas152-runtime",
        "BAS-152 authenticated deterministic accounts payable no-data runtime",
        "runtime",
        ("task-bas152-database",),
        "/runtime-graph",
    ),
    (
        "task-bas152-web",
        "BAS-152 desktop and 390px accounts payable workspace",
        "web",
        ("task-bas152-runtime",),
        "/accounts-payable",
    ),
    (
        "task-bas152-evidence",
        "BAS-152 immutable engineering Evidence",
        "evidence",
        ("task-bas152-web",),
        "/evidence-graph",
    ),
)

NODE_SPECS = (
    (
        "requirements",
        "requirement:BR-126@master-8.57",
        "requirement",
        "BR-126 native exact-scope accounts payable control",
        "docs/project/MASTER_SPEC.md",
        "task-bas152-pytest",
    ),
    (
        "requirements",
        "adr:ADR-0072",
        "adr",
        "ADR-0072 native exact-scope accounts payable control",
        "docs/adr/ADR-0072-native-exact-scope-accounts-payable-control.md",
        "task-bas152-pytest",
    ),
    (
        "engineering",
        "service:scoped-accounts-payable-v1",
        "service",
        "ScopedAccountsPayableWorkspace exact-scope v1",
        "apps/control_plane/scoped_accounts_payable.py",
        "task-bas152-pytest",
    ),
    (
        "engineering",
        "migration:20260730-0078-scoped-accounts-payable-authority",
        "migration",
        "0078 native accounts payable authority",
        "migrations/versions/20260730_0078_native_scoped_accounts_payable.py",
        "task-bas152-database",
    ),
    (
        "runtime",
        "api:native-accounts-payable-no-data",
        "api_probe",
        "Authenticated native accounts payable no-data boundary",
        "http://127.0.0.1:8000/v1/accounts-payable/workspace",
        "task-bas152-runtime",
    ),
    (
        "runtime",
        "web:native-accounts-payable-390",
        "browser_probe",
        "Native accounts payable desktop and 390px",
        "output/playwright/bas152-accounts-payable-mobile-390.png",
        "task-bas152-web",
    ),
    (
        "evidence",
        "evidence:BAS-152",
        "evidence",
        "BAS-152 native accounts payable Evidence",
        EVIDENCE,
        "task-bas152-evidence",
    ),
)

EDGE_SPECS = (
    (
        "requirement:BR-126@master-8.57",
        "specified_by",
        "adr:ADR-0072",
        "requirements",
    ),
    (
        "adr:ADR-0072",
        "implemented_by",
        "service:scoped-accounts-payable-v1",
        "engineering",
    ),
    (
        "service:scoped-accounts-payable-v1",
        "constrained_by",
        "migration:20260730-0078-scoped-accounts-payable-authority",
        "engineering",
    ),
    (
        "migration:20260730-0078-scoped-accounts-payable-authority",
        "observed_as",
        "api:native-accounts-payable-no-data",
        "runtime",
    ),
    (
        "api:native-accounts-payable-no-data",
        "rendered_by",
        "web:native-accounts-payable-390",
        "runtime",
    ),
    (
        "web:native-accounts-payable-390",
        "recorded_in",
        "evidence:BAS-152",
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
            "invoices": "select count(*) from supplier_invoices",
            "lines": "select count(*) from supplier_invoice_lines",
            "bound_payments": (
                "select count(*) from finance_entries "
                "where supplier_invoice_id is not null"
            ),
            "authority_indexes": (
                "select count(*) from pg_indexes where schemaname='public' "
                "and indexname in ('ix_supplier_invoice_scope_order',"
                "'ix_supplier_invoice_line_scope_invoice',"
                "'ix_supplier_invoice_line_scope_product',"
                "'ix_finance_entry_scope_supplier_invoice')"
            ),
            "authority_constraints": (
                "select count(*) from pg_constraint where conname in "
                "('ck_supplier_invoices_scope_required',"
                "'ck_supplier_invoices_payload_sha256',"
                "'ck_supplier_invoices_amounts',"
                "'ck_supplier_invoices_dates',"
                "'ck_supplier_invoice_lines_scope_required',"
                "'ck_supplier_invoice_lines_amounts',"
                "'ck_finance_entries_supplier_payment_binding')"
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
            "tests/test_scoped_accounts_payable.py",
            "tests/test_finance.py",
            "tests/test_scoped_procurement_receiving.py",
            "tests/test_api_contract.py",
            "-q",
            "-p",
            "no:cacheprovider",
            f"--basetemp=output/pytest/bas152-graph-{os.getpid()}",
        ]
    )
    output = process.stdout + process.stderr
    match = re.search(r"(\d+) passed", output)
    if match is None or "[100%]" not in output:
        raise RuntimeError("BAS-152 focused pytest did not pass")
    passed = int(match.group(1))
    if passed != 73:
        raise RuntimeError(f"BAS-152 focused test count drifted: {passed}")

    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    heads = script.get_heads()
    before = database_state()
    if heads != ["20260730_0078"] or before["revision"] != "20260730_0078":
        raise RuntimeError("BAS-152 requires one current/head 20260730_0078")
    if (
        before["authority_indexes"] != 4
        or before["authority_constraints"] != 7
    ):
        raise RuntimeError("BAS-152 database authority is incomplete")
    if (
        before["invoices"] != 0
        or before["lines"] != 0
        or before["bound_payments"] != 0
    ):
        raise RuntimeError("BAS-152 cannot synthesize AP truth")

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
        raise RuntimeError("BAS-152 delivery containers are not healthy")

    api_key = runtime_api_key()
    base = "http://127.0.0.1:8000"
    route = f"{base}/v1/accounts-payable/workspace"
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
        raise RuntimeError("BAS-152 live auth boundary drifted")

    workspace = first.json()
    repeated = replay.json()
    envelope = workspace.get("control_envelope", {})
    artifact = workspace.get("agent_artifact", {})
    if (
        workspace.get("contract_id")
        != "kjds-native-exact-scope-accounts-payable-workspace-v1"
        or workspace.get("status") != "no_data"
        or workspace.get("scope", {}).get("entity_ref") is not None
        or any(workspace.get("counts", {}).values())
        or workspace.get("invoices")
        or envelope.get("scoped_input_read") is not False
        or envelope.get("client_recalculation_allowed") is not False
        or envelope.get("legacy_invoice_rows_admitted") is not False
        or envelope.get("invoice_created") is not False
        or envelope.get("invoice_review_created") is not False
        or envelope.get("approval_created") is not False
        or envelope.get("permit_created") is not False
        or envelope.get("payment_initiated") is not False
        or envelope.get("bank_entry_created") is not False
        or envelope.get("external_write_allowed") is not False
        or envelope.get("private_erp_interface_allowed") is not False
        or artifact.get("self_approval_allowed") is not False
        or artifact.get("permit_issue_allowed") is not False
        or artifact.get("payment_allowed") is not False
        or artifact.get("external_write_allowed") is not False
        or workspace.get("snapshot_sha256")
        != repeated.get("snapshot_sha256")
        or artifact.get("artifact_sha256")
        != repeated.get("agent_artifact", {}).get("artifact_sha256")
    ):
        raise RuntimeError("BAS-152 no-data/no-write replay drifted")

    after = database_state()
    if after != before:
        raise RuntimeError("BAS-152 read verification mutated PostgreSQL")
    if any(file_sha(path) != digest for path, digest in SCREENSHOTS.items()):
        raise RuntimeError("BAS-152 browser Evidence hash drifted")
    evidence_text = (ROOT / EVIDENCE).read_text(encoding="utf-8")
    for marker in (
        "DONE_ENGINEERING",
        "926 passed",
        "inner/scrollWidth = 390/390",
        "Supplier Invoice: `0`",
        "`external_write_allowed=false`",
    ):
        if marker not in evidence_text:
            raise RuntimeError(f"BAS-152 Evidence marker missing: {marker}")

    return {
        "tests": {
            "state": "passed",
            "summary": (
                f"{passed} focused tests; 926 full tests; exact scope, "
                "immutable review, three-way match and payment binding covered"
            ),
            "input_sha256": _sha(
                [
                    file_sha("apps/control_plane/accounts_payable.py"),
                    file_sha("apps/control_plane/scoped_accounts_payable.py"),
                    file_sha("apps/control_plane/finance.py"),
                    file_sha("tests/test_scoped_accounts_payable.py"),
                    file_sha("tests/test_finance.py"),
                    file_sha("tests/test_api_contract.py"),
                ]
            ),
            "artifact_ref": "process:pytest BAS-152",
        },
        "database": {
            "state": "passed",
            "summary": (
                "PostgreSQL single 0078; four authority indexes and seven "
                "checks; invoice, line and bound payment rows zero"
            ),
            "input_sha256": _sha({"heads": heads, **after}),
            "artifact_ref": (
                "postgres:alembic_version,supplier_invoices,"
                "supplier_invoice_lines,finance_entries"
            ),
        },
        "runtime": {
            "state": "passed",
            "summary": (
                "four containers healthy; 401/403/200-no_data; fixed-as-of "
                "replay stable; private ERP and all writes false"
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
                "desktop 1440 and mobile 390 AP no_data; zero horizontal "
                "overflow, console errors and page errors"
            ),
            "input_sha256": _sha(SCREENSHOTS),
            "artifact_ref": (
                "output/playwright/bas152-accounts-payable-mobile-390.png"
            ),
        },
        "evidence": {
            "state": "passed",
            "summary": f"BAS-152 Evidence SHA-256 {file_sha(EVIDENCE)}",
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
                "id": f"bas152-{verifier_id}",
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
        if session.get(GoalTaskRow, "task-bas151-evidence") is None:
            raise RuntimeError("BAS-151 Graph dependency is missing")
        for task_id, title, verifier, dependencies, workspace in TASK_SPECS:
            task = session.get(GoalTaskRow, task_id)
            if task is None:
                task = GoalTaskRow(
                    id=task_id,
                    project_id=PROJECT_ID,
                    title=title,
                    owner="accounts-payable-control-engineering",
                    verifier_id=f"bas152-{verifier}",
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
                task.owner = "accounts-payable-control-engineering"
                task.verifier_id = f"bas152-{verifier}"
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
                "verifier_id": f"bas152-{verifier}",
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
        result["tasks"] != 91
        or result["nodes"] != 204
        or result["edges"] != 204
        or result["observations"] < 338
    ):
        raise RuntimeError(f"BAS-152 Graph count drifted: {result}")
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
