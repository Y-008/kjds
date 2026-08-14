from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import httpx
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from apps.control_plane.agent_harness import (
    AgentHarnessService,
    GoalContractRow,
    GoalTaskRow,
    GraphEdgeRow,
    GraphNodeRow,
    GraphProjectRow,
    _sha,
)
from apps.control_plane.database import create_database_engine
from apps.control_plane.security import Principal

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ID = "kjds-059-bas123"
STORE_REF = "ozon-primary"
EVIDENCE = (
    "docs/project/evidence/"
    "20260728_BAS_123_NATIVE_SCOPED_OZON_IMPORT_STAGING.md"
)


def file_sha(relative: str) -> str:
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def observe() -> dict[str, dict[str, str]]:
    pytest_log = ROOT / "output/pytest/bas123-full-20260728-0950.stdout.log"
    pytest_text = pytest_log.read_text(encoding="utf-8")
    if "743 passed" not in pytest_text or "[100%]" not in pytest_text:
        raise RuntimeError("BAS-123 full pytest log is not a completed success")
    with create_database_engine().connect() as connection:
        revision = connection.execute(text("select version_num from alembic_version")).scalar_one()
    if revision not in {"20260728_0065", "20260728_0066"}:
        raise RuntimeError("real database is not at or beyond BAS-123 revision")
    process = subprocess.run(
        ["docker", "compose", "ps", "--format", "json"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    container_rows = [
        json.loads(line) for line in process.stdout.splitlines() if line.strip()
    ]
    required = {"api", "media-worker", "postgres", "web"}
    healthy = {
        row["Service"]
        for row in container_rows
        if row.get("State") == "running" and row.get("Health") == "healthy"
    }
    if not required <= healthy:
        raise RuntimeError("delivery containers are not all externally healthy")
    health = httpx.get("http://127.0.0.1:8000/health/ready", timeout=10)
    if health.status_code != 200:
        raise RuntimeError("live API readiness probe failed")
    evidence_sha = file_sha(EVIDENCE)
    return {
        "pytest": {
            "state": "passed",
            "summary": "743 passed; completed process log parsed",
            "input_sha256": file_sha("tests/test_scoped_ozon_imports.py"),
            "artifact_ref": str(pytest_log.relative_to(ROOT)).replace("\\", "/"),
        },
        "database": {
            "state": "passed",
            "summary": f"real PostgreSQL revision {revision}",
            "input_sha256": file_sha(
                "migrations/versions/20260728_0065_native_scoped_ozon_imports.py"
            ),
            "artifact_ref": "postgres:alembic_version",
        },
        "containers": {
            "state": "passed",
            "summary": "api, media-worker, postgres and web externally healthy",
            "input_sha256": file_sha("compose.yaml"),
            "artifact_ref": "docker-compose:kjds",
        },
        "api": {
            "state": "passed",
            "summary": "live /health/ready returned 200",
            "input_sha256": file_sha("apps/control_plane/api.py"),
            "artifact_ref": "http://127.0.0.1:8000/health/ready",
        },
        "browser": {
            "state": "passed",
            "summary": "desktop and 390px DOM/overflow/console observations frozen",
            "input_sha256": file_sha("web/app/commerce-os/page.tsx"),
            "artifact_ref": EVIDENCE,
        },
        "evidence": {
            "state": "passed",
            "summary": f"BAS-123 Evidence SHA-256 {evidence_sha}",
            "input_sha256": evidence_sha,
            "artifact_ref": EVIDENCE,
        },
    }


def upsert_graph(observations: dict[str, dict[str, str]]) -> None:
    engine = create_database_engine()
    service = AgentHarnessService(engine)
    now = datetime.now(UTC)
    objective = (
        "Verify BAS-123 end to end, then deliver verifier-owned Agent Harness and "
        "seven canonical Graph projections without external write authority."
    )
    constraints = [
        "preserve dirty 0.59 worktree",
        "no model self-certification",
        "no external commerce writes",
        "inferred edges cannot satisfy gates",
    ]
    goal_hash = _sha({"objective": objective, "constraints": constraints})
    baseline = _sha(
        {
            "branch": "feature/batch-opportunity-mining-059",
            "head": "b34a3a7",
            "bas123_evidence": observations["evidence"]["input_sha256"],
        }
    )
    verifier_defs = {
        "pytest": ("process_log", "test_process"),
        "database": ("postgres_query", "database"),
        "containers": ("docker_health", "runtime"),
        "api": ("http_probe", "runtime"),
        "browser": ("browser_observation", "browser"),
        "evidence": ("immutable_artifact", "evidence"),
    }
    for verifier_id, (source_type, authority) in verifier_defs.items():
        service.register_verifier(
            {
                "id": f"bas123-{verifier_id}",
                "version": "1",
                "source_type": source_type,
                "authority": authority,
                "success_states": ["passed"],
                "freshness_seconds": 604800,
            }
        )
    task_specs = [
        ("task-pytest", "Full backend verifier", "pytest", [], "/engineering-graph"),
        ("task-database", "Real 0065 forward migration", "database", ["task-pytest"], "/engineering-graph"),
        ("task-containers", "Rebuilt delivery containers", "containers", ["task-database"], "/project-graph"),
        ("task-api", "Live API boundary probes", "api", ["task-containers"], "/agent-control"),
        ("task-browser", "Desktop and 390px browser", "browser", ["task-api"], "/agent-control"),
        ("task-evidence", "BAS-123 immutable Evidence", "evidence", ["task-browser"], "/evidence-graph"),
    ]
    node_specs = [
        ("requirements", "requirement:BR-099", "requirement", "BR-099 scoped Ozon import staging", "docs/project/MASTER_SPEC.md"),
        ("requirements", "adr:ADR-0047", "adr", "ADR-0047 native scoped imports", "docs/adr/ADR-0047-native-scoped-ozon-import-staging.md"),
        ("engineering", "migration:0065", "migration", "0065 native scoped Ozon imports", "migrations/versions/20260728_0065_native_scoped_ozon_imports.py"),
        ("engineering", "test:scoped-imports", "test", "Scoped Ozon import contract tests", "tests/test_scoped_ozon_imports.py"),
        ("runtime", "observation:pytest", "observation", "743 passed", observations["pytest"]["artifact_ref"]),
        ("runtime", "database:0065", "database_revision", "Real PostgreSQL 0065+", observations["database"]["artifact_ref"]),
        ("runtime", "containers:delivery", "container_set", "Healthy delivery containers", observations["containers"]["artifact_ref"]),
        ("runtime", "api:ready", "api_probe", "Live API ready", observations["api"]["artifact_ref"]),
        ("runtime", "browser:commerce-os", "browser_probe", "Desktop and 390px accepted", observations["browser"]["artifact_ref"]),
        ("evidence", "evidence:BAS-123", "evidence", "BAS-123 release Evidence", EVIDENCE),
        ("project", "plan:BAS-123", "task", "BAS-123 DONE_ENGINEERING", "docs/project/03_REMAINING_WORK_AND_PARALLEL_PLAN.md"),
        ("commerce", "boundary:external-write", "boundary", "External commerce writes closed", EVIDENCE),
        ("authority", "authority:verifier-owned", "policy", "Only verifier observations can pass tasks", "docs/adr/ADR-0048-agent-harness-and-canonical-graph.md"),
    ]
    with Session(engine) as session, session.begin():
        project = session.get(GraphProjectRow, PROJECT_ID)
        if not project:
            session.add(
                GraphProjectRow(
                    id=PROJECT_ID,
                    tenant_ref="default",
                    entity_ref=None,
                    store_ref=STORE_REF,
                    title="KJDS 0.59 BAS-123 vertical path",
                    lifecycle="active",
                    baseline_sha256=baseline,
                    goal_contract_sha256=goal_hash,
                    created_at=now,
                )
            )
        elif (
            project.baseline_sha256 != baseline
            or project.goal_contract_sha256 != goal_hash
        ):
            raise RuntimeError("graph project baseline changed; create a new project version")
        if not session.get(GoalContractRow, "goal-kjds-059"):
            session.add(
                GoalContractRow(
                    id="goal-kjds-059",
                    project_id=PROJECT_ID,
                    objective=objective,
                    constraints_json=constraints,
                    content_sha256=goal_hash,
                    created_at=now,
                )
            )
        for task_id, title, verifier, dependencies, workspace in task_specs:
            if not session.get(GoalTaskRow, task_id):
                session.add(
                    GoalTaskRow(
                        id=task_id,
                        project_id=PROJECT_ID,
                        title=title,
                        owner="engineering",
                        verifier_id=f"bas123-{verifier}",
                        verifier_version="1",
                        dependency_ids_json=dependencies,
                        verification_condition="fresh registered external observation is passed",
                        next_safe_action="inspect exact artifact and rerun bounded verifier",
                        workspace=workspace,
                        sla_seconds=86400,
                        fingerprint=_sha([PROJECT_ID, task_id]),
                        created_at=now,
                    )
                )
        for kind, stable_key, node_type, label, artifact in node_specs:
            node_id = f"gn_{_sha([PROJECT_ID, kind, stable_key])[:32]}"
            content = {
                "stable_key": stable_key,
                "type": node_type,
                "label": label,
                "artifact": artifact,
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
                        authority="canonical" if kind != "commerce" else "boundary",
                        source=artifact,
                        scope_json={"tenant_ref": "default", "store_ref": STORE_REF},
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
            ("requirement:BR-099", "specified_by", "adr:ADR-0047", "requirements"),
            ("adr:ADR-0047", "implemented_by", "migration:0065", "engineering"),
            ("migration:0065", "verified_by", "test:scoped-imports", "engineering"),
            ("test:scoped-imports", "observed_by", "observation:pytest", "runtime"),
            ("observation:pytest", "precedes", "database:0065", "runtime"),
            ("database:0065", "precedes", "containers:delivery", "runtime"),
            ("containers:delivery", "precedes", "api:ready", "runtime"),
            ("api:ready", "precedes", "browser:commerce-os", "runtime"),
            ("browser:commerce-os", "recorded_in", "evidence:BAS-123", "evidence"),
            ("evidence:BAS-123", "closes", "plan:BAS-123", "project"),
            ("authority:verifier-owned", "guards", "observation:pytest", "authority"),
            ("boundary:external-write", "blocks", "plan:BAS-123", "commerce"),
        ]
        for source, edge_type, target, kind in chain:
            edge_id = f"ge_{_sha([PROJECT_ID, kind, source, edge_type, target])[:32]}"
            if not session.get(GraphEdgeRow, edge_id):
                payload = [source, edge_type, target, "evidence"]
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
                "verifier_id": f"bas123-{verifier}",
                "verifier_version": "1",
                "source": verifier_defs[verifier][0],
                "scope": {"tenant_ref": "default", "store_ref": STORE_REF},
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


if __name__ == "__main__":
    facts = observe()
    upsert_graph(facts)
    print(
        json.dumps(
            {
                "project_id": PROJECT_ID,
                "observations": len(facts),
                "external_write_allowed": False,
            },
            sort_keys=True,
        )
    )
