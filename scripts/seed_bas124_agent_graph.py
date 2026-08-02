from __future__ import annotations

import hashlib
import json
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
    "docs/project/evidence/"
    "20260728_BAS_124_NATIVE_SCOPED_FORMAL_FACTS.md"
)


def file_sha(relative: str) -> str:
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def observe() -> dict[str, dict[str, str]]:
    pytest_process = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_scoped_facts.py",
            "-q",
            "--basetemp",
            ".pytest-bas124-graph",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    pytest_text = pytest_process.stdout + pytest_process.stderr
    if "7 passed" not in pytest_text or "[100%]" not in pytest_text:
        raise RuntimeError("BAS-124 scoped Fact pytest observation did not pass")

    engine = create_database_engine()
    with engine.connect() as connection:
        revision = connection.execute(
            text("select version_num from alembic_version")
        ).scalar_one()
        fact_count = int(
            connection.execute(text("select count(*) from fact_records")).scalar_one()
        )
        promotion_count = int(
            connection.execute(text("select count(*) from promotion_runs")).scalar_one()
        )
    if revision != "20260728_0067":
        raise RuntimeError("real database is not at BAS-124 revision 0067")
    if fact_count != 0 or promotion_count != 0:
        raise RuntimeError("unexpected real Fact/PromotionRun mutation")

    docker_process = subprocess.run(
        ["docker", "compose", "ps", "--format", "json"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    container_rows = [
        json.loads(line)
        for line in docker_process.stdout.splitlines()
        if line.strip()
    ]
    required = {"api", "media-worker", "postgres", "web"}
    healthy = {
        row["Service"]
        for row in container_rows
        if row.get("State") == "running" and row.get("Health") == "healthy"
    }
    if not required <= healthy:
        raise RuntimeError("delivery containers are not all externally healthy")

    readiness = httpx.get("http://127.0.0.1:8000/health/ready", timeout=10)
    anonymous_facts = httpx.get("http://127.0.0.1:8000/v1/facts", timeout=10)
    formal_facts_page = httpx.get("http://127.0.0.1:3000/formal-facts", timeout=10)
    if readiness.status_code != 200:
        raise RuntimeError("live API readiness probe failed")
    if anonymous_facts.status_code != 401:
        raise RuntimeError("anonymous native Fact API did not fail closed")
    if formal_facts_page.status_code != 200:
        raise RuntimeError("live formal Facts Web route failed")

    evidence_text = (ROOT / EVIDENCE).read_text(encoding="utf-8")
    browser_markers = (
        "Desktop `1440x1000`",
        "Mobile `390x844`",
        "no horizontal overflow",
        "no console warning/error",
        "server state `blocked`",
    )
    if any(marker not in evidence_text for marker in browser_markers):
        raise RuntimeError("BAS-124 browser Evidence is incomplete")

    evidence_sha = file_sha(EVIDENCE)
    return {
        "pytest": {
            "state": "passed",
            "summary": "7 scoped Fact tests passed in an external pytest process",
            "input_sha256": file_sha("tests/test_scoped_facts.py"),
            "artifact_ref": "process:pytest tests/test_scoped_facts.py",
        },
        "database": {
            "state": "passed",
            "summary": (
                f"real PostgreSQL {revision}; Facts {fact_count}; "
                f"PromotionRuns {promotion_count}"
            ),
            "input_sha256": file_sha(
                "migrations/versions/20260728_0067_native_scoped_formal_facts.py"
            ),
            "artifact_ref": "postgres:alembic_version,fact_records,promotion_runs",
        },
        "containers": {
            "state": "passed",
            "summary": "api, media-worker, postgres and web externally healthy",
            "input_sha256": file_sha("compose.yaml"),
            "artifact_ref": "docker-compose:kjds",
        },
        "api": {
            "state": "passed",
            "summary": "readiness 200; anonymous Facts 401; formal Facts Web 200",
            "input_sha256": file_sha("docs/project/contracts/openapi-v1.json"),
            "artifact_ref": "http://127.0.0.1:8000/v1/facts",
        },
        "browser": {
            "state": "passed",
            "summary": (
                "desktop 1440 and mobile 390 blocked-state, overflow and console "
                "observations frozen"
            ),
            "input_sha256": file_sha(
                "web/features/formal-facts/formal-facts-console.tsx"
            ),
            "artifact_ref": EVIDENCE,
        },
        "evidence": {
            "state": "passed",
            "summary": f"BAS-124 Evidence SHA-256 {evidence_sha}",
            "input_sha256": evidence_sha,
            "artifact_ref": EVIDENCE,
        },
    }


def upsert_graph(observations: dict[str, dict[str, str]]) -> None:
    engine = create_database_engine()
    service = AgentHarnessService(engine)
    now = datetime.now(UTC)
    verifier_defs = {
        "pytest": ("pytest_process", "test_process"),
        "database": ("postgres_query", "database"),
        "containers": ("docker_health", "runtime"),
        "api": ("http_probe", "runtime"),
        "browser": ("browser_evidence", "browser"),
        "evidence": ("immutable_artifact", "evidence"),
    }
    for verifier_id, (source_type, authority) in verifier_defs.items():
        service.register_verifier(
            {
                "id": f"bas124-{verifier_id}",
                "version": "1",
                "source_type": source_type,
                "authority": authority,
                "success_states": ["passed"],
                "freshness_seconds": 604800,
            }
        )

    task_specs = [
        (
            "task-bas124-pytest",
            "BAS-124 scoped Fact tests",
            "pytest",
            ["task-evidence"],
            "/engineering-graph",
        ),
        (
            "task-bas124-database",
            "Real 0067 forward migration",
            "database",
            ["task-bas124-pytest"],
            "/runtime-graph",
        ),
        (
            "task-bas124-containers",
            "BAS-124 delivery containers",
            "containers",
            ["task-bas124-database"],
            "/runtime-graph",
        ),
        (
            "task-bas124-api",
            "Scoped Fact live API boundary",
            "api",
            ["task-bas124-containers"],
            "/agent-control",
        ),
        (
            "task-bas124-browser",
            "Formal Facts desktop and 390px",
            "browser",
            ["task-bas124-api"],
            "/agent-control",
        ),
        (
            "task-bas124-evidence",
            "BAS-124 immutable Evidence",
            "evidence",
            ["task-bas124-browser"],
            "/evidence-graph",
        ),
    ]
    node_specs = [
        (
            "requirements",
            "requirement:BR-101",
            "requirement",
            "BR-101 native scoped formal Facts",
            "docs/project/MASTER_SPEC.md",
        ),
        (
            "requirements",
            "adr:ADR-0049",
            "adr",
            "ADR-0049 formal Fact promotion authority",
            "docs/adr/ADR-0049-native-scoped-formal-fact-promotion.md",
        ),
        (
            "engineering",
            "migration:0067",
            "migration",
            "0067 native scoped formal Facts",
            "migrations/versions/20260728_0067_native_scoped_formal_facts.py",
        ),
        (
            "engineering",
            "service:scoped-facts",
            "service",
            "ScopedFactPromotionAuthority",
            "apps/control_plane/scoped_facts.py",
        ),
        (
            "engineering",
            "test:scoped-facts",
            "test",
            "Scoped formal Fact contract tests",
            "tests/test_scoped_facts.py",
        ),
        (
            "runtime",
            "observation:bas124-pytest",
            "observation",
            "7 scoped Fact tests passed",
            observations["pytest"]["artifact_ref"],
        ),
        (
            "runtime",
            "database:0067",
            "database_revision",
            "Real PostgreSQL 0067",
            observations["database"]["artifact_ref"],
        ),
        (
            "runtime",
            "containers:bas124-delivery",
            "container_set",
            "BAS-124 delivery containers healthy",
            observations["containers"]["artifact_ref"],
        ),
        (
            "runtime",
            "api:formal-facts",
            "api_probe",
            "Scoped formal Fact live boundary",
            observations["api"]["artifact_ref"],
        ),
        (
            "runtime",
            "browser:formal-facts",
            "browser_probe",
            "Formal Facts desktop and 390px accepted",
            observations["browser"]["artifact_ref"],
        ),
        (
            "evidence",
            "evidence:BAS-124",
            "evidence",
            "BAS-124 release Evidence",
            EVIDENCE,
        ),
        (
            "project",
            "plan:BAS-124",
            "task",
            "BAS-124 DONE_ENGINEERING",
            "docs/project/03_REMAINING_WORK_AND_PARALLEL_PLAN.md",
        ),
    ]

    with Session(engine) as session, session.begin():
        if not session.get(GraphProjectRow, PROJECT_ID):
            raise RuntimeError("BAS-123 graph project must exist before BAS-124")
        for task_id, title, verifier, dependencies, workspace in task_specs:
            if not session.get(GoalTaskRow, task_id):
                session.add(
                    GoalTaskRow(
                        id=task_id,
                        project_id=PROJECT_ID,
                        title=title,
                        owner="engineering",
                        verifier_id=f"bas124-{verifier}",
                        verifier_version="1",
                        dependency_ids_json=dependencies,
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
        for kind, stable_key, node_type, label, artifact in node_specs:
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
            if not session.get(GraphNodeRow, node_id):
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
        session.flush()
        by_key = {
            row.stable_key: row
            for row in session.scalars(
                select(GraphNodeRow).where(GraphNodeRow.project_id == PROJECT_ID)
            )
        }
        chain = [
            ("requirement:BR-101", "specified_by", "adr:ADR-0049", "requirements"),
            ("adr:ADR-0049", "implemented_by", "migration:0067", "engineering"),
            (
                "migration:0067",
                "implemented_by",
                "service:scoped-facts",
                "engineering",
            ),
            (
                "service:scoped-facts",
                "verified_by",
                "test:scoped-facts",
                "engineering",
            ),
            (
                "test:scoped-facts",
                "observed_by",
                "observation:bas124-pytest",
                "runtime",
            ),
            (
                "observation:bas124-pytest",
                "precedes",
                "database:0067",
                "runtime",
            ),
            (
                "database:0067",
                "precedes",
                "containers:bas124-delivery",
                "runtime",
            ),
            (
                "containers:bas124-delivery",
                "precedes",
                "api:formal-facts",
                "runtime",
            ),
            (
                "api:formal-facts",
                "precedes",
                "browser:formal-facts",
                "runtime",
            ),
            (
                "browser:formal-facts",
                "recorded_in",
                "evidence:BAS-124",
                "evidence",
            ),
            (
                "evidence:BAS-124",
                "closes",
                "plan:BAS-124",
                "project",
            ),
        ]
        for source, edge_type, target, kind in chain:
            edge_id = (
                f"ge_{_sha([PROJECT_ID, kind, source, edge_type, target])[:32]}"
            )
            if not session.get(GraphEdgeRow, edge_id):
                payload = [source, edge_type, target, "evidence", EVIDENCE]
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
                        content_sha256=_sha(payload),
                    )
                )

    monitor = Principal(
        actor_id="harness-seed",
        roles=frozenset({"admin"}),
        tenant_ref="default",
        store_refs=frozenset({STORE_REF}),
    )
    for task_id, _title, verifier, _dependencies, _workspace in task_specs:
        item = observations[verifier]
        service.record_observation(
            {
                "project_id": PROJECT_ID,
                "task_id": task_id,
                "verifier_id": f"bas124-{verifier}",
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
        filters = {"project_id": PROJECT_ID}
        return {
            "tasks": int(
                session.scalar(
                    select(func.count())
                    .select_from(GoalTaskRow)
                    .filter_by(**filters)
                )
                or 0
            ),
            "observations": int(
                session.scalar(
                    select(func.count())
                    .select_from(HarnessObservationRow)
                    .filter_by(**filters)
                )
                or 0
            ),
            "nodes": int(
                session.scalar(
                    select(func.count())
                    .select_from(GraphNodeRow)
                    .filter_by(**filters)
                )
                or 0
            ),
            "edges": int(
                session.scalar(
                    select(func.count())
                    .select_from(GraphEdgeRow)
                    .filter_by(**filters)
                )
                or 0
            ),
        }


if __name__ == "__main__":
    facts = observe()
    upsert_graph(facts)
    print(
        json.dumps(
            {
                "project_id": PROJECT_ID,
                **counts(),
                "external_write_allowed": False,
            },
            sort_keys=True,
        )
    )
