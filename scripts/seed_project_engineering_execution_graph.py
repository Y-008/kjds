from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from dotenv import dotenv_values
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from apps.control_plane.agent_harness import (
    AgentHarnessService,
    GoalTaskRow,
    GraphEdgeRow,
    GraphNodeRow,
    GraphNodeStatusBindingRow,
    GraphProjectRow,
    HarnessObservationRow,
    _sha,
)
from apps.control_plane.database import create_database_engine
from apps.control_plane.health_scheduler_verifier import (
    HealthSchedulerDeploymentVerifier,
)
from apps.control_plane.security import Principal

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ID = "kjds-059-bas123"
STORE_REF = "ozon-primary"
TENANT_REF = "default"
VERSION = "1"
EVIDENCE_127 = (
    "docs/project/evidence/"
    "20260728_BAS_127_OPERATING_GATE_OBSERVATION_LOOP.md"
)
EVIDENCE_128 = (
    "docs/project/evidence/"
    "20260728_BAS_128_PROJECT_ENGINEERING_GRAPH_KERNEL.md"
)
EVIDENCE_129 = (
    "docs/project/evidence/"
    "20260728_BAS_129_SCOPE_AUTHORITY_ADMISSION.md"
)
EVIDENCE_131 = (
    "docs/project/evidence/"
    "20260728_BAS_131_OPERATING_SUBJECT_BINDING.md"
)
EVIDENCE_132 = (
    "docs/project/evidence/"
    "20260728_BAS_132_HEALTH_SCHEDULER_GRAPH_OBSERVATION.md"
)
EVIDENCE_133 = (
    "docs/project/evidence/"
    "20260728_BAS_133_SCOPE_AUTHORITY_INTAKE_WORKBENCH.md"
)
EVIDENCE_134 = (
    "docs/project/evidence/"
    "20260729_BAS_134_AUTHORITY_WORKFLOW_TOPOLOGY.md"
)
EVIDENCE_135 = (
    "docs/project/evidence/"
    "20260729_BAS_135_GRAPH_DEPENDENCY_REVERIFICATION.md"
)
SCHEDULER_ARTIFACT_ROOT = "output/graph/bas132-health-scheduler"
AUTHORITY_INTAKE_ARTIFACT_ROOT = "output/graph/bas133-authority-intake"
AUTHORITY_TOPOLOGY_ARTIFACT_ROOT = (
    "output/graph/bas134-authority-workflow-topology"
)
SCHEDULER_RUNTIME_NODE_KEYS = frozenset(
    {
        "scheduler:evidence-integrity-health",
        "observation:bas132-health-scheduler-audit",
        "authority:dedicated-monitor-scheduler-identity",
    }
)
BAS132_NODE_KEYS = frozenset(
    {
        "plan:BAS-132",
        "requirement:BR-108",
        "adr:ADR-0056",
        "change:BAS-132",
        "code:health-scheduler-deployment-verifier",
        "test:health-scheduler-deployment-verifier",
        "scheduler:evidence-integrity-health",
        "observation:bas132-health-scheduler-audit",
        "evidence:BAS-132",
        "authority:dedicated-monitor-scheduler-identity",
    }
)
BAS133_NODE_KEYS = frozenset(
    {
        "plan:BAS-133",
        "requirement:BR-109",
        "adr:ADR-0057",
        "change:BAS-133",
        "code:scope-authority-intake-projection",
        "code:scope-authority-intake-workbench",
        "test:scope-authority-intake",
        "observation:bas133-authority-intake",
        "evidence:BAS-133",
        "authority:scope-authority-intake-verifier",
    }
)
BAS134_NODE_KEYS = frozenset(
    {
        "plan:BAS-134",
        "requirement:BR-110",
        "adr:ADR-0058",
        "change:BAS-134",
        "code:authority-workflow-topology-verifier",
        "code:authority-workflow-topology-workbench",
        "test:authority-workflow-topology",
        "observation:bas134-authority-workflow-topology",
        "evidence:BAS-134",
        "authority:four-party-workflow-topology",
    }
)
BAS135_NODE_KEYS = frozenset(
    {
        "plan:BAS-135",
        "change:BAS-135",
        "code:graph-dependency-reverification",
        "test:graph-dependency-reverification",
        "evidence:BAS-135",
    }
)


def file_sha(relative: str) -> str:
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def database_observation_input(
    *,
    revision: str,
    binding_count: int,
) -> str:
    """Hash every external value that can affect the database observation result."""

    return _sha(
        {
            "database_revision": revision,
            "pre_seed_binding_count": binding_count,
            "migration_sha256": [
                file_sha(
                    "migrations/versions/"
                    "20260728_0068_graph_node_status_bindings.py"
                ),
                file_sha(
                    "migrations/versions/"
                    "20260728_0069_scope_authority_review_lineage.py"
                ),
                file_sha(
                    "migrations/versions/"
                    "20260728_0070_graph_project_operating_subject.py"
                ),
            ],
        }
    )


def _json_process(
    command: list[str],
) -> tuple[dict[str, Any], int]:
    process = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"external JSON observer returned an invalid contract: {command[0]}"
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeError("external JSON observer result must be an object")
    return payload, process.returncode


def observe_health_scheduler() -> dict[str, Any]:
    observed_at = datetime.now(UTC)
    task_audit, task_exit_code = _json_process(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            "scripts/manage-evidence-health-task.ps1",
            "-Mode",
            "Audit",
        ]
    )
    health, health_exit_code = _json_process(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            "scripts/run-24x7-health.ps1",
            "-ControlPlaneOnly",
        ]
    )
    result = HealthSchedulerDeploymentVerifier().evaluate(
        task_audit=task_audit,
        health_preflight=health,
        observed_at=observed_at,
    )
    artifact = {
        "contract_id": result["contract_id"],
        "observed_at": result["observed_at"],
        "task_audit_exit_code": task_exit_code,
        "health_preflight_exit_code": health_exit_code,
        "task_audit": task_audit,
        "health_preflight": health,
        "verification": result,
        "external_write_allowed": False,
        "model_self_certification_allowed": False,
    }
    artifact_dir = ROOT / "output" / "graph" / "bas132-health-scheduler"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / f"{result['input_sha256']}.json"
    artifact_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        **result,
        "artifact_ref": artifact_path.relative_to(ROOT).as_posix(),
    }


def _authority_intake_counts(engine) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            "source": int(
                connection.execute(
                    text(
                        "select count(*) from evidence_records "
                        "where source = 'scope_authority_source'"
                    )
                ).scalar_one()
            ),
            "review": int(
                connection.execute(
                    text(
                        "select count(*) from evidence_records "
                        "where source = 'scope_authority_review'"
                    )
                ).scalar_one()
            ),
            "grant": int(
                connection.execute(
                    text("select count(*) from scope_grant_events")
                ).scalar_one()
            ),
        }


def observe_authority_intake() -> dict[str, Any]:
    """Observe the real read model and Web route without submitting Evidence."""

    engine = create_database_engine()
    before = _authority_intake_counts(engine)
    headers = {"X-KJDS-API-Key": _authorized_api_key()}
    api_url = "http://127.0.0.1:8000/v1/scope-grants/intake"
    api_response = httpx.get(
        api_url,
        params={"store_ref": STORE_REF, "event_type": "grant"},
        headers=headers,
        timeout=15,
    )
    web_response = httpx.get(
        "http://127.0.0.1:3000/authority-intake",
        timeout=15,
    )
    after = _authority_intake_counts(engine)
    if api_response.status_code != 200 or web_response.status_code != 200:
        raise RuntimeError(
            "live Authority Intake route failed: "
            f"api={api_response.status_code}, web={web_response.status_code}"
        )
    snapshot = api_response.json()
    if snapshot.get("contract_id") != "kjds-scope-authority-intake-v1":
        raise RuntimeError("live Authority Intake contract drift")
    if snapshot.get("state") != "input_required":
        raise RuntimeError("entity-free Authority Intake must require exact scope")
    if snapshot.get("blocker_codes") != ["entity_ref_required"]:
        raise RuntimeError("Authority Intake exact-scope blocker drift")
    if (
        snapshot.get("external_write_allowed") is not False
        or snapshot.get("grant_endpoint_exposed") is not False
        or snapshot.get("grant_created") is not False
    ):
        raise RuntimeError("Authority Intake unexpectedly exposes grant authority")
    if before != after:
        raise RuntimeError("read-only Authority Intake observation mutated authority data")
    observation = {
        "contract_id": "kjds-bas133-authority-intake-observation-v1",
        "observed_at": datetime.now(UTC).isoformat(),
        "api_status": api_response.status_code,
        "web_status": web_response.status_code,
        "database_counts_before": before,
        "database_counts_after": after,
        "intake_snapshot": snapshot,
        "external_write_allowed": False,
        "grant_endpoint_exposed": False,
        "model_self_certification_allowed": False,
    }
    input_sha256 = _sha(observation)
    artifact_dir = ROOT / AUTHORITY_INTAKE_ARTIFACT_ROOT
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / f"{input_sha256}.json"
    artifact_path.write_text(
        json.dumps(
            observation,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "state": "passed",
        "summary": (
            "live exact-scope intake API/Web 200; read observation retained "
            f"source/review/grant counts {after['source']}/{after['review']}/"
            f"{after['grant']}"
        ),
        "input_sha256": input_sha256,
        "artifact_ref": artifact_path.relative_to(ROOT).as_posix(),
        "snapshot": observation,
    }


def _contains_sensitive_identity_key(value: Any) -> bool:
    if isinstance(value, list):
        return any(_contains_sensitive_identity_key(item) for item in value)
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower()
            if normalized in {
                "api_key",
                "apikey",
                "credential",
                "secret",
                "user_id",
                "user_ref",
            }:
                return True
            if _contains_sensitive_identity_key(item):
                return True
    return False


def observe_authority_workflow_topology() -> dict[str, Any]:
    """Freeze a live, secret-free Web identity topology observation."""

    observed_at = datetime.now(UTC)
    engine = create_database_engine()
    before = _authority_intake_counts(engine)
    values = dotenv_values(ROOT / ".env")
    raw_users = str(
        values.get("KJDS_SUPABASE_AUTH_USERS_JSON") or ""
    ).strip()
    if not raw_users:
        raise RuntimeError(
            "live Authority topology requires local Supabase verifier users"
        )
    verifier_users = json.loads(raw_users)
    if not isinstance(verifier_users, list):
        raise RuntimeError(
            "KJDS_SUPABASE_AUTH_USERS_JSON must be a user list"
        )
    verifier_user = next(
        (
            user
            for user in verifier_users
            if isinstance(user, dict)
            and user.get("actor") == "r0-requester"
            and str(user.get("email") or "").strip()
            and str(user.get("password") or "")
        ),
        None,
    )
    if verifier_user is None:
        raise RuntimeError(
            "live Authority topology requires the r0-requester verifier user"
        )
    with httpx.Client(
        base_url="http://127.0.0.1:3000",
        follow_redirects=False,
        timeout=15,
    ) as client:
        login_response = client.post(
            "/auth/login",
            data={
                "email": str(verifier_user["email"]),
                "password": str(verifier_user["password"]),
            },
            headers={"X-KJDS-CSRF": "same-origin-fetch"},
        )
        if (
            login_response.status_code != 303
            or httpx.URL(
                login_response.headers.get("location") or "/login?error=missing"
            ).path
            != "/"
        ):
            raise RuntimeError(
                "live Authority topology verifier login failed: "
                f"web={login_response.status_code}"
            )
        response = client.get("/auth/authority-topology")
    after = _authority_intake_counts(engine)
    if response.status_code != 200:
        raise RuntimeError(
            "live Authority topology endpoint failed: "
            f"web={response.status_code}"
        )
    snapshot = response.json()
    if not isinstance(snapshot, dict):
        raise RuntimeError("Authority topology response must be an object")
    if (
        snapshot.get("contract_id")
        != "kjds-authority-workflow-topology-v1"
    ):
        raise RuntimeError("live Authority topology contract drift")
    if snapshot.get("state") not in {"passed", "blocked", "failed"}:
        raise RuntimeError("live Authority topology state drift")
    if (
        snapshot.get("external_write_allowed") is not False
        or snapshot.get("role_switch_allowed") is not False
        or snapshot.get("grant_created") is not False
    ):
        raise RuntimeError("Authority topology expanded execution authority")
    if _contains_sensitive_identity_key(snapshot):
        raise RuntimeError("Authority topology exposed sensitive identity fields")
    if before != after:
        raise RuntimeError(
            "read-only Authority topology observation mutated authority data"
        )
    bucket = observed_at.replace(
        minute=(observed_at.minute // 15) * 15,
        second=0,
        microsecond=0,
    )
    input_sha256 = _sha(
        {
            "topology_input_sha256": snapshot.get("input_sha256"),
            "observation_bucket": bucket.isoformat(),
            "endpoint_status": response.status_code,
        }
    )
    artifact = {
        "contract_id": "kjds-bas134-authority-topology-observation-v1",
        "observed_at": observed_at.isoformat(),
        "observation_bucket": bucket.isoformat(),
        "web_status": response.status_code,
        "database_counts_before": before,
        "database_counts_after": after,
        "topology": snapshot,
        "observation_input_sha256": input_sha256,
        "external_write_allowed": False,
        "model_self_certification_allowed": False,
    }
    artifact_sha256 = _sha(artifact)
    artifact_dir = ROOT / AUTHORITY_TOPOLOGY_ARTIFACT_ROOT
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / f"{artifact_sha256}.json"
    artifact_path.write_text(
        json.dumps(
            artifact,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "state": snapshot["state"],
        "summary": (
            "live Web identity topology: "
            f"API chain ready={snapshot.get('api_chain_ready')}; "
            f"Web chain ready={snapshot.get('web_chain_ready')}; "
            f"blockers={','.join(snapshot.get('blocker_codes', [])) or 'none'}"
        ),
        "input_sha256": input_sha256,
        "artifact_ref": artifact_path.relative_to(ROOT).as_posix(),
        "snapshot": artifact,
    }


def _authorized_api_key(
    required_roles: set[str] | None = None,
) -> str:
    values = dotenv_values(ROOT / ".env")
    web_key = str(values.get("KJDS_API_KEY") or "").strip()
    raw_mapping = str(values.get("KJDS_API_KEYS_JSON") or "").strip()
    if raw_mapping:
        mapping = json.loads(raw_mapping)
        if not isinstance(mapping, dict):
            raise RuntimeError("KJDS_API_KEYS_JSON must be an object")
        preferred_roles = required_roles or {
            "admin",
            "monitor",
            "operator",
            "reviewer",
        }
        for key, profile in mapping.items():
            if not isinstance(key, str) or not isinstance(profile, dict):
                continue
            roles = set(profile.get("roles", []))
            stores = set(profile.get("stores", [STORE_REF]))
            tenant = str(profile.get("tenant", TENANT_REF) or TENANT_REF)
            if (
                roles.intersection(preferred_roles)
                and tenant == TENANT_REF
                and STORE_REF in stores
            ):
                return key
    if web_key and required_roles is None:
        return web_key
    raise RuntimeError("no scoped API credential is available for Graph verification")


def observe_external(
    *,
    require_browser_evidence: bool = True,
) -> dict[str, dict[str, Any]]:
    temp_root = ROOT / ".tmp"
    temp_root.mkdir(exist_ok=True)
    pytest_process = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_agent_harness.py",
            "tests/test_operating_gate_observer.py",
            "tests/test_operating_gate_verifier.py",
            "tests/test_evidence_health_task.py",
            "tests/test_health_scheduler_verifier.py",
            "tests/test_project_execution_graph_seed.py",
            "tests/test_scope_grants.py",
            "tests/test_truth_governance.py",
            "-q",
            "--basetemp",
            str(temp_root / "pytest-bas128-seed"),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    pytest_text = pytest_process.stdout + pytest_process.stderr
    if "[100%]" not in pytest_text or " passed" not in pytest_text:
        raise RuntimeError("BAS-128 verifier pytest process did not pass")
    web_test_process = subprocess.run(
        ["npm.cmd", "test"],
        cwd=ROOT / "web",
        check=True,
        capture_output=True,
        text=True,
    )

    engine = create_database_engine()
    with engine.connect() as connection:
        revision = connection.execute(
            text("select version_num from alembic_version")
        ).scalar_one()
        binding_count = int(
            connection.execute(
                text("select count(*) from graph_node_status_bindings")
            ).scalar_one()
        )
    if revision != "20260728_0070":
        raise RuntimeError("Graph verifier requires real database revision 0070")

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
    image_refs = {
        row["Service"]: row.get("Image", "")
        for row in container_rows
        if row.get("Service") in required
    }

    scheduler_observation = observe_health_scheduler()
    authority_intake_observation = observe_authority_intake()
    authority_topology_observation = (
        observe_authority_workflow_topology()
    )
    observations: dict[str, dict[str, Any]] = {
        "pytest": {
            "state": "passed",
            "summary": "Graph kernel and observer verifier tests passed externally",
            "input_sha256": _sha(
                [
                    file_sha("apps/control_plane/agent_harness.py"),
                    file_sha("apps/control_plane/operating_gate_observer.py"),
                    file_sha("apps/control_plane/security.py"),
                    file_sha("apps/control_plane/routers/agent_control.py"),
                    file_sha("apps/control_plane/routers/system.py"),
                    file_sha("apps/control_plane/runtime.py"),
                    file_sha(
                        "migrations/versions/"
                        "20260728_0070_graph_project_operating_subject.py"
                    ),
                    file_sha(
                        "scripts/seed_project_engineering_execution_graph.py"
                    ),
                    file_sha("tests/test_agent_harness.py"),
                    file_sha("tests/test_operating_gate_observer.py"),
                    file_sha("tests/test_operating_gate_verifier.py"),
                    file_sha("tests/test_evidence_health_task.py"),
                    file_sha("tests/test_health_scheduler_verifier.py"),
                    file_sha("tests/test_project_execution_graph_seed.py"),
                ]
            ),
            "artifact_ref": (
                "process:pytest tests/test_agent_harness.py "
                "tests/test_operating_gate_observer.py "
                "tests/test_operating_gate_verifier.py "
                "tests/test_evidence_health_task.py "
                "tests/test_health_scheduler_verifier.py "
                "tests/test_project_execution_graph_seed.py"
            ),
        },
        "pytest132": {
            "state": "passed",
            "summary": (
                "BAS-132 scheduler deployment verifier tests passed in the "
                "external pytest process"
            ),
            "input_sha256": _sha(
                [
                    file_sha(
                        "apps/control_plane/health_scheduler_verifier.py"
                    ),
                    file_sha("scripts/manage-evidence-health-task.ps1"),
                    file_sha("scripts/run-24x7-health.ps1"),
                    file_sha(
                        "scripts/seed_project_engineering_execution_graph.py"
                    ),
                    file_sha("tests/test_evidence_health_task.py"),
                    file_sha("tests/test_health_scheduler_verifier.py"),
                    file_sha("tests/test_project_execution_graph_seed.py"),
                ]
            ),
            "artifact_ref": (
                "process:pytest tests/test_evidence_health_task.py "
                "tests/test_health_scheduler_verifier.py "
                "tests/test_project_execution_graph_seed.py"
            ),
        },
        "pytest133": {
            "state": "passed",
            "summary": (
                "BAS-133 exact-scope intake, route and Graph seed contract "
                "tests passed in the external pytest process"
            ),
            "input_sha256": _sha(
                [
                    file_sha("apps/control_plane/scope_grants.py"),
                    file_sha("apps/control_plane/routers/system.py"),
                    file_sha(
                        "web/features/agent-control/"
                        "authority-intake-workbench.tsx"
                    ),
                    file_sha(
                        "web/features/agent-control/"
                        "authority-intake-workbench.module.css"
                    ),
                    file_sha("tests/test_scope_grants.py"),
                    file_sha("tests/test_truth_governance.py"),
                    file_sha("tests/test_project_execution_graph_seed.py"),
                    file_sha("web/lib/agent-graph-contract.test.ts"),
                ]
            ),
            "artifact_ref": (
                "process:pytest tests/test_scope_grants.py "
                "tests/test_truth_governance.py "
                "tests/test_project_execution_graph_seed.py"
            ),
        },
        "pytest135": {
            "state": "passed",
            "summary": (
                "BAS-135 complete GoalTask DAG dependency invalidation and "
                "re-verification recovery tests passed externally"
            ),
            "input_sha256": _sha(
                [
                    file_sha("apps/control_plane/agent_harness.py"),
                    file_sha("scripts/manage-evidence-health-task.ps1"),
                    file_sha(
                        "scripts/seed_project_engineering_execution_graph.py"
                    ),
                    file_sha("tests/test_evidence_health_task.py"),
                    file_sha("tests/test_project_execution_graph_seed.py"),
                ]
            ),
            "artifact_ref": (
                "process:pytest tests/test_evidence_health_task.py "
                "tests/test_project_execution_graph_seed.py"
            ),
        },
        "intake": authority_intake_observation,
        "tests134": {
            "state": "passed",
            "summary": (
                "BAS-134 pure topology verifier and Web contract tests passed "
                "in an external Node test process"
            ),
            "input_sha256": _sha(
                [
                    file_sha(
                        "web/lib/authority-workflow-topology.ts"
                    ),
                    file_sha(
                        "web/lib/authority-workflow-topology.test.ts"
                    ),
                    file_sha("web/lib/identity-config.ts"),
                    file_sha(
                        "web/app/auth/authority-topology/route.ts"
                    ),
                    file_sha(
                        "web/features/agent-control/"
                        "authority-intake-workbench.tsx"
                    ),
                    file_sha(
                        "web/features/agent-control/"
                        "authority-intake-workbench.module.css"
                    ),
                    file_sha("web/lib/agent-graph-contract.test.ts"),
                    file_sha(
                        "tests/test_project_execution_graph_seed.py"
                    ),
                    _sha(web_test_process.stdout),
                ]
            ),
            "artifact_ref": "process:npm test",
        },
        "topology": authority_topology_observation,
        "scheduler": scheduler_observation,
        "database": {
            "state": "passed",
            "summary": (
                f"real PostgreSQL {revision}; Graph binding and authority "
                "review indexes readable; "
                f"pre-seed bindings {binding_count}"
            ),
            "input_sha256": database_observation_input(
                revision=revision,
                binding_count=binding_count,
            ),
            "artifact_ref": (
                "postgres:alembic_version,graph_node_status_bindings,"
                "uq_scope_authority_source_ref,"
                "uq_scope_authority_review_ref,"
                "graph_project_subject_binding_events"
            ),
        },
        "containers": {
            "state": "passed",
            "summary": (
                "api, media-worker, postgres and web externally healthy with "
                "resolved delivery images"
            ),
            "input_sha256": _sha(image_refs),
            "artifact_ref": "docker-compose:kjds",
        },
    }
    if not require_browser_evidence:
        return observations

    evidence_text = (ROOT / EVIDENCE_128).read_text(encoding="utf-8")
    browser_markers = (
        "Desktop browser acceptance",
        "390px browser acceptance",
        "horizontal overflow",
        "`Runtime.exceptionThrown`",
        "verifier-owned node detail",
        "Release Gate remains REJECTED",
    )
    if any(marker not in evidence_text for marker in browser_markers):
        raise RuntimeError("BAS-128 browser Evidence is incomplete")
    observations.update(
        {
            "browser": {
            "state": "passed",
            "summary": (
                "desktop and 390px Project/Engineering Graph acceptance frozen "
                "with overflow, console and verifier drilldown checks"
            ),
            "input_sha256": file_sha(EVIDENCE_128),
            "artifact_ref": EVIDENCE_128,
        },
            "evidence": {
            "state": "passed",
            "summary": f"BAS-128 Evidence SHA-256 {file_sha(EVIDENCE_128)}",
            "input_sha256": file_sha(EVIDENCE_128),
            "artifact_ref": EVIDENCE_128,
        },
        }
    )
    return observations


def _task_specs() -> tuple[tuple[str, str, str, tuple[str, ...], str], ...]:
    return (
        (
            "task-bas128-pytest",
            "BAS-128 Graph kernel verifier tests",
            "pytest",
            ("task-bas124-evidence",),
            "/engineering-graph",
        ),
        (
            "task-bas128-database",
            "Real 0068 forward migration",
            "database",
            ("task-bas128-pytest",),
            "/runtime-graph",
        ),
        (
            "task-bas128-containers",
            "BAS-128 rebuilt delivery containers",
            "containers",
            ("task-bas128-database",),
            "/runtime-graph",
        ),
        (
            "task-bas128-api",
            "Live verifier-owned Graph API projection",
            "api",
            ("task-bas128-containers",),
            "/project-graph",
        ),
        (
            "task-bas128-browser",
            "Project and Engineering Graph desktop/390 acceptance",
            "browser",
            ("task-bas128-api",),
            "/engineering-graph",
        ),
        (
            "task-bas128-evidence",
            "BAS-128 immutable Graph kernel Evidence",
            "evidence",
            ("task-bas128-browser",),
            "/evidence-graph",
        ),
    )


def _scheduler_task_specs(
) -> tuple[tuple[str, str, str, str, tuple[str, ...], str], ...]:
    return (
        (
            "task-bas132-verifier-tests",
            "BAS-132 health scheduler verifier tests",
            "bas132-pytest",
            "pytest132",
            (),
            "/engineering-graph",
        ),
        (
            "task-bas040-health-scheduler-deployment",
            "BAS-040 external health scheduler deployment",
            "bas132-health-scheduler",
            "scheduler",
            ("task-bas132-verifier-tests",),
            "/runtime-graph",
        ),
    )


def _intake_task_specs(
) -> tuple[tuple[str, str, str, str, tuple[str, ...], str], ...]:
    return (
        (
            "task-bas133-verifier-tests",
            "BAS-133 exact-scope Authority Intake verifier tests",
            "bas133-pytest",
            "pytest133",
            ("task-bas132-verifier-tests",),
            "/engineering-graph",
        ),
        (
            "task-bas133-authority-intake-live",
            "BAS-133 live Authority Intake API/Web observation",
            "bas133-authority-intake",
            "intake",
            ("task-bas133-verifier-tests",),
            "/authority-intake",
        ),
    )


def _topology_task_specs(
) -> tuple[tuple[str, str, str, str, tuple[str, ...], str], ...]:
    return (
        (
            "task-bas134-verifier-tests",
            "BAS-134 Authority workflow topology verifier tests",
            "bas134-tests",
            "tests134",
            ("task-bas133-verifier-tests",),
            "/engineering-graph",
        ),
        (
            "task-bas134-authority-workflow-topology",
            "BAS-134 live four-party Authority workflow topology",
            "bas134-authority-workflow-topology",
            "topology",
            (
                "task-bas133-authority-intake-live",
                "task-bas134-verifier-tests",
            ),
            "/authority-intake",
        ),
    )


def _dependency_recovery_task_specs(
) -> tuple[tuple[str, str, str, str, tuple[str, ...], str], ...]:
    return (
        (
            "task-bas135-verifier-tests",
            "BAS-135 Graph dependency re-verification recovery",
            "bas135-tests",
            "pytest135",
            ("task-bas134-verifier-tests",),
            "/engineering-graph",
        ),
    )


def _node_specs(
    observations: dict[str, dict[str, Any]],
) -> tuple[tuple[str, str, str, str, str, str], ...]:
    return (
        (
            "project",
            "program:kjds-cross-border-commerce",
            "program",
            "KJDS cross-border commerce program",
            "docs/project/MASTER_SPEC.md",
            "task-m4-actual-cash",
        ),
        (
            "project",
            "project:kjds-059",
            "project",
            "KJDS 0.59 operating system project",
            "docs/project/03_REMAINING_WORK_AND_PARALLEL_PLAN.md",
            "task-m4-actual-cash",
        ),
        (
            "project",
            "workstream:m0-m4-operating-loop",
            "workstream",
            "M0→M4 real operating loop",
            EVIDENCE_128,
            "task-m4-actual-cash",
        ),
        (
            "project",
            "release:0.59",
            "release",
            "Release 0.59 · Gate REJECTED",
            "docs/project/03_REMAINING_WORK_AND_PARALLEL_PLAN.md",
            "task-m4-actual-cash",
        ),
        (
            "project",
            "plan:BAS-131",
            "delivery_task",
            "BAS-131 Graph project operating-subject binding",
            "docs/project/03_REMAINING_WORK_AND_PARALLEL_PLAN.md",
            "task-m0-operating-subject-binding",
        ),
        (
            "project",
            "plan:BAS-132",
            "delivery_task",
            "BAS-132 real health scheduler Graph observation",
            "docs/project/03_REMAINING_WORK_AND_PARALLEL_PLAN.md",
            "task-bas132-verifier-tests",
        ),
        (
            "project",
            "plan:BAS-133",
            "delivery_task",
            "BAS-133 exact-scope Authority Intake workbench",
            "docs/project/03_REMAINING_WORK_AND_PARALLEL_PLAN.md",
            "task-bas133-authority-intake-live",
        ),
        (
            "project",
            "plan:BAS-134",
            "delivery_task",
            "BAS-134 verifier-owned Authority workflow topology",
            "docs/project/03_REMAINING_WORK_AND_PARALLEL_PLAN.md",
            "task-bas134-authority-workflow-topology",
        ),
        (
            "project",
            "plan:BAS-135",
            "delivery_task",
            "BAS-135 complete Graph dependency re-verification recovery",
            "docs/project/03_REMAINING_WORK_AND_PARALLEL_PLAN.md",
            "task-bas135-verifier-tests",
        ),
        (
            "requirements",
            "requirement:BR-103",
            "requirement",
            "BR-103 monitor-owned Gate observation loop",
            "docs/project/MASTER_SPEC.md",
            "task-bas128-api",
        ),
        (
            "requirements",
            "requirement:BR-104",
            "requirement",
            "BR-104 verifier-owned Project/Engineering Graph kernel",
            "docs/project/MASTER_SPEC.md",
            "task-bas128-pytest",
        ),
        (
            "requirements",
            "requirement:BR-107",
            "requirement",
            "BR-107 recorder/operating-subject separation",
            "docs/project/MASTER_SPEC.md",
            "task-m0-operating-subject-binding",
        ),
        (
            "requirements",
            "requirement:BR-108",
            "requirement",
            "BR-108 verifier-owned external health scheduler deployment",
            "docs/project/MASTER_SPEC.md",
            "task-bas132-verifier-tests",
        ),
        (
            "requirements",
            "requirement:BR-109",
            "requirement",
            "BR-109 verifier-owned Scope Authority Intake workbench",
            "docs/project/MASTER_SPEC.md",
            "task-bas133-verifier-tests",
        ),
        (
            "requirements",
            "requirement:BR-110",
            "requirement",
            "BR-110 real four-party Authority identity topology",
            "docs/project/MASTER_SPEC.md",
            "task-bas134-verifier-tests",
        ),
        (
            "engineering",
            "adr:ADR-0051",
            "adr",
            "ADR-0051 monitor-owned operating Gate observation loop",
            "docs/adr/ADR-0051-monitor-owned-operating-gate-observation-loop.md",
            "task-bas128-api",
        ),
        (
            "engineering",
            "adr:ADR-0052",
            "adr",
            "ADR-0052 verifier-owned Graph node status",
            "docs/adr/ADR-0052-verifier-owned-project-engineering-graph-kernel.md",
            "task-bas128-pytest",
        ),
        (
            "engineering",
            "adr:ADR-0055",
            "adr",
            "ADR-0055 Graph project operating-subject binding",
            "docs/adr/ADR-0055-graph-project-operating-subject-binding.md",
            "task-bas128-pytest",
        ),
        (
            "engineering",
            "adr:ADR-0056",
            "adr",
            "ADR-0056 external health scheduler deployment observation",
            (
                "docs/adr/"
                "ADR-0056-verifier-owned-health-scheduler-deployment.md"
            ),
            "task-bas132-verifier-tests",
        ),
        (
            "engineering",
            "adr:ADR-0057",
            "adr",
            "ADR-0057 exact-scope Authority Intake projection",
            "docs/adr/ADR-0057-exact-scope-authority-intake-workbench.md",
            "task-bas133-verifier-tests",
        ),
        (
            "engineering",
            "adr:ADR-0058",
            "adr",
            "ADR-0058 verifier-owned Authority workflow topology",
            (
                "docs/adr/"
                "ADR-0058-verifier-owned-authority-workflow-topology.md"
            ),
            "task-bas134-verifier-tests",
        ),
        (
            "engineering",
            "change:BAS-128",
            "change",
            "BAS-128 Project/Engineering Graph kernel change",
            "apps/control_plane/agent_harness.py",
            "task-bas128-pytest",
        ),
        (
            "engineering",
            "code:graph-node-status-binding",
            "code",
            "GraphNodeStatusBinding verifier projection",
            "apps/control_plane/agent_harness.py",
            "task-bas128-pytest",
        ),
        (
            "engineering",
            "test:graph-node-status-binding",
            "test",
            "Graph status binding and stale propagation tests",
            "tests/test_agent_harness.py",
            "task-bas128-pytest",
        ),
        (
            "engineering",
            "change:BAS-131",
            "change",
            "BAS-131 recorder/operating-subject separation",
            "apps/control_plane/operating_gate_observer.py",
            "task-bas128-pytest",
        ),
        (
            "engineering",
            "code:graph-project-operating-subject",
            "code",
            "Append-only Graph project operating-subject authority",
            "apps/control_plane/agent_harness.py",
            "task-bas128-pytest",
        ),
        (
            "engineering",
            "test:graph-project-operating-subject",
            "test",
            "Operating-subject identity, replay and observer tests",
            "tests/test_operating_gate_observer.py",
            "task-bas128-pytest",
        ),
        (
            "engineering",
            "migration:0070-operating-subject",
            "migration",
            "Alembic 0070 Graph project operating-subject events",
            (
                "migrations/versions/"
                "20260728_0070_graph_project_operating_subject.py"
            ),
            "task-bas128-database",
        ),
        (
            "engineering",
            "change:BAS-132",
            "change",
            "BAS-132 health scheduler external observation",
            "apps/control_plane/health_scheduler_verifier.py",
            "task-bas132-verifier-tests",
        ),
        (
            "engineering",
            "code:health-scheduler-deployment-verifier",
            "code",
            "Pure external health scheduler deployment verifier",
            "apps/control_plane/health_scheduler_verifier.py",
            "task-bas132-verifier-tests",
        ),
        (
            "engineering",
            "test:health-scheduler-deployment-verifier",
            "test",
            "Scheduler contract, anti-spoof and blocked-state tests",
            "tests/test_health_scheduler_verifier.py",
            "task-bas132-verifier-tests",
        ),
        (
            "engineering",
            "change:BAS-133",
            "change",
            "BAS-133 Authority Intake deep slice",
            "apps/control_plane/scope_grants.py",
            "task-bas133-verifier-tests",
        ),
        (
            "engineering",
            "code:scope-authority-intake-projection",
            "code",
            "Exact-scope as-of Authority Intake verifier projection",
            "apps/control_plane/scope_grants.py",
            "task-bas133-verifier-tests",
        ),
        (
            "engineering",
            "code:scope-authority-intake-workbench",
            "code",
            "Role-aware endpoint-backed Authority Intake Web workbench",
            (
                "web/features/agent-control/"
                "authority-intake-workbench.tsx"
            ),
            "task-bas133-verifier-tests",
        ),
        (
            "engineering",
            "test:scope-authority-intake",
            "test",
            "Exact scope, as-of, role and zero-write intake tests",
            "tests/test_scope_grants.py",
            "task-bas133-verifier-tests",
        ),
        (
            "engineering",
            "change:BAS-134",
            "change",
            "BAS-134 Authority identity topology deep slice",
            "web/lib/authority-workflow-topology.ts",
            "task-bas134-verifier-tests",
        ),
        (
            "engineering",
            "code:authority-workflow-topology-verifier",
            "code",
            "Pure four-party exact-scope identity topology verifier",
            "web/lib/authority-workflow-topology.ts",
            "task-bas134-verifier-tests",
        ),
        (
            "engineering",
            "code:authority-workflow-topology-workbench",
            "code",
            "Live Authority topology projection in the Intake workbench",
            (
                "web/features/agent-control/"
                "authority-intake-workbench.tsx"
            ),
            "task-bas134-verifier-tests",
        ),
        (
            "engineering",
            "test:authority-workflow-topology",
            "test",
            "Four-party, Web binding, fail-closed and hash tests",
            "web/lib/authority-workflow-topology.test.ts",
            "task-bas134-verifier-tests",
        ),
        (
            "engineering",
            "change:BAS-135",
            "change",
            "BAS-135 complete GoalTask DAG dependency recovery",
            "scripts/seed_project_engineering_execution_graph.py",
            "task-bas135-verifier-tests",
        ),
        (
            "engineering",
            "code:graph-dependency-reverification",
            "code",
            "Deterministic direct-dependency Observation input chaining",
            "scripts/seed_project_engineering_execution_graph.py",
            "task-bas135-verifier-tests",
        ),
        (
            "engineering",
            "test:graph-dependency-reverification",
            "test",
            "Dependency invalidation and fresh recovery fault tests",
            "tests/test_project_execution_graph_seed.py",
            "task-bas135-verifier-tests",
        ),
        (
            "engineering",
            "build:bas128-delivery-images",
            "build",
            "BAS-128 resolved delivery images",
            observations["containers"]["artifact_ref"],
            "task-bas128-containers",
        ),
        (
            "runtime",
            "deploy:bas128-compose",
            "deploy",
            "BAS-128 healthy Compose deployment",
            observations["containers"]["artifact_ref"],
            "task-bas128-containers",
        ),
        (
            "runtime",
            "observation:bas128-graph-api",
            "observation",
            "Live verifier-owned Graph API observation",
            "http://127.0.0.1:8000/v1/agent-control/projects/"
            f"{PROJECT_ID}",
            "task-bas128-api",
        ),
        (
            "runtime",
            "observation:bas131-operating-subject",
            "observation",
            "Live bound operating-subject verifier observation",
            (
                f"/v1/agent-control/projects/{PROJECT_ID}/"
                "operating-subject"
            ),
            "task-m0-operating-subject-binding",
        ),
        (
            "runtime",
            "scheduler:evidence-integrity-health",
            "scheduler",
            "Windows Task · KJDS Evidence Integrity Health",
            SCHEDULER_ARTIFACT_ROOT,
            "task-bas040-health-scheduler-deployment",
        ),
        (
            "runtime",
            "observation:bas132-health-scheduler-audit",
            "observation",
            "Real read-only Windows Task and health preflight audit",
            SCHEDULER_ARTIFACT_ROOT,
            "task-bas040-health-scheduler-deployment",
        ),
        (
            "runtime",
            "observation:bas133-authority-intake",
            "observation",
            "Live Authority Intake API/Web and database no-mutation observation",
            AUTHORITY_INTAKE_ARTIFACT_ROOT,
            "task-bas133-authority-intake-live",
        ),
        (
            "runtime",
            "observation:bas134-authority-workflow-topology",
            "observation",
            "Live secret-free Web identity topology observation",
            AUTHORITY_TOPOLOGY_ARTIFACT_ROOT,
            "task-bas134-authority-workflow-topology",
        ),
        (
            "evidence",
            "evidence:BAS-127",
            "evidence",
            "BAS-127 operating Gate observation loop Evidence",
            EVIDENCE_127,
            "task-bas128-api",
        ),
        (
            "evidence",
            "evidence:BAS-128",
            "evidence",
            "BAS-128 Project/Engineering Graph kernel Evidence",
            EVIDENCE_128,
            "task-bas128-evidence",
        ),
        (
            "evidence",
            "evidence:BAS-132",
            "evidence",
            "BAS-132 health scheduler Graph observation Evidence",
            EVIDENCE_132,
            "task-bas132-verifier-tests",
        ),
        (
            "evidence",
            "evidence:BAS-133",
            "evidence",
            "BAS-133 Scope Authority Intake workbench Evidence",
            EVIDENCE_133,
            "task-bas133-authority-intake-live",
        ),
        (
            "evidence",
            "evidence:BAS-134",
            "evidence",
            "BAS-134 Authority workflow topology Evidence",
            EVIDENCE_134,
            "task-bas134-authority-workflow-topology",
        ),
        (
            "evidence",
            "evidence:BAS-135",
            "evidence",
            "BAS-135 Graph dependency re-verification Evidence",
            EVIDENCE_135,
            "task-bas135-verifier-tests",
        ),
        (
            "project",
            "risk:release-gate-rejected",
            "risk",
            "Release Gate REJECTED until real M0→M4 closure",
            EVIDENCE_128,
            "task-m0-current-authority",
        ),
        (
            "project",
            "decision:verifier-owned-node-status",
            "decision",
            "Only registered verifier state may advance Graph nodes",
            "docs/adr/ADR-0052-verifier-owned-project-engineering-graph-kernel.md",
            "task-bas128-pytest",
        ),
        (
            "project",
            "owner:business-and-engineering",
            "owner",
            "Business and engineering accountable owner",
            "docs/project/03_REMAINING_WORK_AND_PARALLEL_PLAN.md",
            "task-m0-current-authority",
        ),
        (
            "project",
            "sla:m0-authority-24h",
            "sla",
            "M0 authority next-action SLA · 24h",
            "docs/project/03_REMAINING_WORK_AND_PARALLEL_PLAN.md",
            "task-m0-current-authority",
        ),
        (
            "project",
            "dependency:m0-to-m1",
            "dependency",
            "M1 blocked until M0 is fresh and passed",
            EVIDENCE_128,
            "task-m0-current-authority",
        ),
        (
            "authority",
            "authority:registered-node-status-verifier",
            "authority",
            "Registered verifier is sole Graph node status authority",
            "apps/control_plane/agent_harness.py",
            "task-bas128-api",
        ),
        (
            "authority",
            "authority:operating-subject-binding",
            "authority",
            "Append-only project operating subject binding",
            (
                f"/v1/agent-control/projects/{PROJECT_ID}/"
                "operating-subject"
            ),
            "task-m0-operating-subject-binding",
        ),
        (
            "authority",
            "authority:current-scope-grant",
            "authority",
            "Current tenant/entity/store scope authority",
            "/v1/scope-grants/current",
            "task-m0-scope-authority-admission",
        ),
        (
            "authority",
            "authority:dedicated-monitor-scheduler-identity",
            "authority",
            "Dedicated scheduler-visible monitor identity",
            SCHEDULER_ARTIFACT_ROOT,
            "task-bas040-health-scheduler-deployment",
        ),
        (
            "authority",
            "authority:scope-authority-intake-verifier",
            "authority",
            "Scope Authority Intake verifier and role boundary",
            "/v1/scope-grants/intake",
            "task-bas133-authority-intake-live",
        ),
        (
            "authority",
            "authority:four-party-workflow-topology",
            "authority",
            "Observed subject/owner/reviewer/recorder identity topology",
            "/auth/authority-topology",
            "task-bas134-authority-workflow-topology",
        ),
    )


def _edge_specs() -> tuple[tuple[str, str, str, str], ...]:
    return (
        (
            "program:kjds-cross-border-commerce",
            "contains",
            "project:kjds-059",
            "project",
        ),
        (
            "project:kjds-059",
            "contains",
            "workstream:m0-m4-operating-loop",
            "project",
        ),
        (
            "project:kjds-059",
            "targets",
            "release:0.59",
            "project",
        ),
        (
            "workstream:m0-m4-operating-loop",
            "delivers",
            "release:0.59",
            "project",
        ),
        (
            "project:kjds-059",
            "contains",
            "plan:BAS-131",
            "project",
        ),
        (
            "project:kjds-059",
            "contains",
            "plan:BAS-132",
            "project",
        ),
        (
            "project:kjds-059",
            "contains",
            "plan:BAS-133",
            "project",
        ),
        (
            "project:kjds-059",
            "contains",
            "plan:BAS-134",
            "project",
        ),
        (
            "project:kjds-059",
            "contains",
            "plan:BAS-135",
            "project",
        ),
        (
            "plan:BAS-131",
            "supports",
            "milestone:M0",
            "project",
        ),
        (
            "plan:BAS-132",
            "observes",
            "risk:release-gate-rejected",
            "project",
        ),
        (
            "plan:BAS-133",
            "supports",
            "milestone:M0",
            "project",
        ),
        (
            "plan:BAS-134",
            "blocks_until_verified",
            "milestone:M0",
            "project",
        ),
        (
            "plan:BAS-135",
            "satisfies",
            "requirement:BR-104",
            "project",
        ),
        ("release:0.59", "contains", "milestone:M0", "project"),
        ("release:0.59", "contains", "milestone:M1", "project"),
        ("release:0.59", "contains", "milestone:M2", "project"),
        ("release:0.59", "contains", "milestone:M3", "project"),
        ("release:0.59", "contains", "milestone:M4", "project"),
        ("milestone:M1", "depends_on", "milestone:M0", "project"),
        ("milestone:M2", "depends_on", "milestone:M1", "project"),
        ("milestone:M3", "depends_on", "milestone:M2", "project"),
        ("milestone:M4", "depends_on", "milestone:M3", "project"),
        (
            "project:kjds-059",
            "requires",
            "requirement:BR-104",
            "requirements",
        ),
        (
            "project:kjds-059",
            "requires",
            "requirement:BR-107",
            "requirements",
        ),
        (
            "project:kjds-059",
            "requires",
            "requirement:BR-108",
            "requirements",
        ),
        (
            "project:kjds-059",
            "requires",
            "requirement:BR-109",
            "requirements",
        ),
        (
            "project:kjds-059",
            "requires",
            "requirement:BR-110",
            "requirements",
        ),
        (
            "requirement:BR-103",
            "decided_by",
            "adr:ADR-0051",
            "requirements",
        ),
        (
            "requirement:BR-104",
            "decided_by",
            "adr:ADR-0052",
            "requirements",
        ),
        (
            "requirement:BR-107",
            "decided_by",
            "adr:ADR-0055",
            "requirements",
        ),
        (
            "requirement:BR-108",
            "decided_by",
            "adr:ADR-0056",
            "requirements",
        ),
        (
            "requirement:BR-109",
            "decided_by",
            "adr:ADR-0057",
            "requirements",
        ),
        (
            "requirement:BR-110",
            "decided_by",
            "adr:ADR-0058",
            "requirements",
        ),
        (
            "adr:ADR-0055",
            "authorizes",
            "change:BAS-131",
            "engineering",
        ),
        (
            "change:BAS-131",
            "modifies",
            "code:graph-project-operating-subject",
            "engineering",
        ),
        (
            "code:graph-project-operating-subject",
            "verified_by",
            "test:graph-project-operating-subject",
            "engineering",
        ),
        (
            "change:BAS-131",
            "migrated_by",
            "migration:0070-operating-subject",
            "engineering",
        ),
        (
            "adr:ADR-0056",
            "authorizes",
            "change:BAS-132",
            "engineering",
        ),
        (
            "change:BAS-132",
            "modifies",
            "code:health-scheduler-deployment-verifier",
            "engineering",
        ),
        (
            "code:health-scheduler-deployment-verifier",
            "verified_by",
            "test:health-scheduler-deployment-verifier",
            "engineering",
        ),
        (
            "adr:ADR-0057",
            "authorizes",
            "change:BAS-133",
            "engineering",
        ),
        (
            "change:BAS-133",
            "modifies",
            "code:scope-authority-intake-projection",
            "engineering",
        ),
        (
            "change:BAS-133",
            "modifies",
            "code:scope-authority-intake-workbench",
            "engineering",
        ),
        (
            "code:scope-authority-intake-projection",
            "verified_by",
            "test:scope-authority-intake",
            "engineering",
        ),
        (
            "code:scope-authority-intake-workbench",
            "verified_by",
            "test:scope-authority-intake",
            "engineering",
        ),
        (
            "adr:ADR-0058",
            "authorizes",
            "change:BAS-134",
            "engineering",
        ),
        (
            "change:BAS-134",
            "modifies",
            "code:authority-workflow-topology-verifier",
            "engineering",
        ),
        (
            "change:BAS-134",
            "modifies",
            "code:authority-workflow-topology-workbench",
            "engineering",
        ),
        (
            "code:authority-workflow-topology-verifier",
            "verified_by",
            "test:authority-workflow-topology",
            "engineering",
        ),
        (
            "code:authority-workflow-topology-workbench",
            "verified_by",
            "test:authority-workflow-topology",
            "engineering",
        ),
        (
            "adr:ADR-0052",
            "authorizes",
            "change:BAS-135",
            "engineering",
        ),
        (
            "change:BAS-135",
            "modifies",
            "code:graph-dependency-reverification",
            "engineering",
        ),
        (
            "code:graph-dependency-reverification",
            "verified_by",
            "test:graph-dependency-reverification",
            "engineering",
        ),
        (
            "test:graph-dependency-reverification",
            "recorded_in",
            "evidence:BAS-135",
            "evidence",
        ),
        (
            "adr:ADR-0052",
            "authorizes",
            "change:BAS-128",
            "engineering",
        ),
        (
            "change:BAS-128",
            "modifies",
            "code:graph-node-status-binding",
            "engineering",
        ),
        (
            "code:graph-node-status-binding",
            "verified_by",
            "test:graph-node-status-binding",
            "engineering",
        ),
        (
            "test:graph-node-status-binding",
            "produces",
            "build:bas128-delivery-images",
            "engineering",
        ),
        (
            "build:bas128-delivery-images",
            "deployed_as",
            "deploy:bas128-compose",
            "runtime",
        ),
        (
            "deploy:bas128-compose",
            "observed_as",
            "observation:bas128-graph-api",
            "runtime",
        ),
        (
            "observation:bas128-graph-api",
            "recorded_in",
            "evidence:BAS-128",
            "evidence",
        ),
        (
            "evidence:BAS-128",
            "supports",
            "decision:verifier-owned-node-status",
            "project",
        ),
        (
            "risk:release-gate-rejected",
            "informs",
            "decision:verifier-owned-node-status",
            "project",
        ),
        (
            "authority:operating-subject-binding",
            "enables",
            "authority:current-scope-grant",
            "authority",
        ),
        (
            "migration:0070-operating-subject",
            "enables",
            "observation:bas131-operating-subject",
            "runtime",
        ),
        (
            "observation:bas131-operating-subject",
            "observes",
            "authority:operating-subject-binding",
            "authority",
        ),
        (
            "scheduler:evidence-integrity-health",
            "observed_as",
            "observation:bas132-health-scheduler-audit",
            "runtime",
        ),
        (
            "observation:bas132-health-scheduler-audit",
            "recorded_in",
            "evidence:BAS-132",
            "evidence",
        ),
        (
            "authority:dedicated-monitor-scheduler-identity",
            "governs",
            "scheduler:evidence-integrity-health",
            "authority",
        ),
        (
            "authority:scope-authority-intake-verifier",
            "observes",
            "observation:bas133-authority-intake",
            "authority",
        ),
        (
            "observation:bas133-authority-intake",
            "recorded_in",
            "evidence:BAS-133",
            "evidence",
        ),
        (
            "authority:four-party-workflow-topology",
            "observed_as",
            "observation:bas134-authority-workflow-topology",
            "authority",
        ),
        (
            "observation:bas134-authority-workflow-topology",
            "recorded_in",
            "evidence:BAS-134",
            "evidence",
        ),
        (
            "authority:four-party-workflow-topology",
            "precedes",
            "authority:scope-authority-intake-verifier",
            "authority",
        ),
        (
            "authority:operating-subject-binding",
            "scopes",
            "authority:scope-authority-intake-verifier",
            "authority",
        ),
        (
            "authority:scope-authority-intake-verifier",
            "preflights",
            "authority:current-scope-grant",
            "authority",
        ),
        (
            "owner:business-and-engineering",
            "accountable_for",
            "project:kjds-059",
            "project",
        ),
        (
            "sla:m0-authority-24h",
            "governs",
            "owner:business-and-engineering",
            "project",
        ),
        (
            "dependency:m0-to-m1",
            "blocks",
            "milestone:M1",
            "project",
        ),
        (
            "authority:registered-node-status-verifier",
            "governs",
            "observation:bas128-graph-api",
            "authority",
        ),
        (
            "owner:business-and-engineering",
            "accountable_for",
            "authority:current-scope-grant",
            "authority",
        ),
        (
            "sla:m0-authority-24h",
            "governs",
            "authority:current-scope-grant",
            "authority",
        ),
        (
            "authority:current-scope-grant",
            "blocks",
            "milestone:M0",
            "authority",
        ),
    )


def seed_structure(observations: dict[str, dict[str, Any]]) -> None:
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
                "id": f"bas128-{verifier_id}",
                "version": VERSION,
                "source_type": source_type,
                "authority": authority,
                "success_states": ["passed"],
                "freshness_seconds": 604800,
            }
        )
    service.register_verifier(
        {
            "id": "operating-subject-binding",
            "version": VERSION,
            "source_type": "project_operating_subject_projection",
            "authority": "project_governance",
            "success_states": ["passed"],
            "freshness_seconds": 3600,
        }
    )
    service.register_verifier(
        {
            "id": "scope-grant-current",
            "version": VERSION,
            "source_type": "scope_grant_projection",
            "authority": "identity_governance",
            "success_states": ["passed"],
            "freshness_seconds": 3600,
        }
    )
    service.register_verifier(
        {
            "id": "bas132-pytest",
            "version": VERSION,
            "source_type": "pytest_process",
            "authority": "test_process",
            "success_states": ["passed"],
            "freshness_seconds": 604800,
        }
    )
    service.register_verifier(
        {
            "id": "bas132-health-scheduler",
            "version": VERSION,
            "source_type": "windows_task_and_health_audit",
            "authority": "external_runtime",
            "success_states": ["passed"],
            "freshness_seconds": 1200,
        }
    )
    service.register_verifier(
        {
            "id": "bas133-pytest",
            "version": VERSION,
            "source_type": "pytest_process",
            "authority": "test_process",
            "success_states": ["passed"],
            "freshness_seconds": 604800,
        }
    )
    service.register_verifier(
        {
            "id": "bas133-authority-intake",
            "version": VERSION,
            "source_type": "api_web_database_observation",
            "authority": "identity_governance",
            "success_states": ["passed"],
            "freshness_seconds": 3600,
        }
    )
    service.register_verifier(
        {
            "id": "bas134-tests",
            "version": VERSION,
            "source_type": "web_test_process",
            "authority": "test_process",
            "success_states": ["passed"],
            "freshness_seconds": 604800,
        }
    )
    service.register_verifier(
        {
            "id": "bas134-authority-workflow-topology",
            "version": VERSION,
            "source_type": "live_web_identity_topology",
            "authority": "external_web_identity_configuration",
            "success_states": ["passed"],
            "freshness_seconds": 1200,
        }
    )
    service.register_verifier(
        {
            "id": "bas135-tests",
            "version": VERSION,
            "source_type": "pytest_process",
            "authority": "test_process",
            "success_states": ["passed"],
            "freshness_seconds": 604800,
        }
    )

    task_specs = _task_specs()
    scheduler_task_specs = _scheduler_task_specs()
    intake_task_specs = _intake_task_specs()
    topology_task_specs = _topology_task_specs()
    dependency_recovery_task_specs = _dependency_recovery_task_specs()
    node_specs = _node_specs(observations)
    with Session(engine) as session, session.begin():
        if not session.get(GraphProjectRow, PROJECT_ID):
            raise RuntimeError("canonical Graph project does not exist")
        subject_task = session.get(
            GoalTaskRow,
            "task-m0-operating-subject-binding",
        )
        if subject_task is None:
            session.add(
                GoalTaskRow(
                    id="task-m0-operating-subject-binding",
                    project_id=PROJECT_ID,
                    title="M0 project operating subject binding",
                    owner="project-admin+monitor",
                    verifier_id="operating-subject-binding",
                    verifier_version=VERSION,
                    dependency_ids_json=[],
                    verification_condition=(
                        "fresh append-only project binding resolves one "
                        "registered non-admin operator"
                    ),
                    next_safe_action=(
                        "bind the exact registered operating operator, then "
                        "run the monitor observation"
                    ),
                    workspace="/authority-graph",
                    sla_seconds=86400,
                    fingerprint=_sha(
                        [PROJECT_ID, "task-m0-operating-subject-binding"]
                    ),
                    created_at=now,
                )
            )
        elif (
            subject_task.project_id != PROJECT_ID
            or subject_task.verifier_id != "operating-subject-binding"
            or subject_task.verifier_version != VERSION
        ):
            raise RuntimeError(
                "canonical Goal task drift: "
                "task-m0-operating-subject-binding"
            )
        authority_task = session.get(
            GoalTaskRow,
            "task-m0-scope-authority-admission",
        )
        if authority_task is None:
            session.add(
                GoalTaskRow(
                    id="task-m0-scope-authority-admission",
                    project_id=PROJECT_ID,
                    title="M0 current scope authority admission",
                    owner="account-owner+independent-reviewer+compliance",
                    verifier_id="scope-grant-current",
                    verifier_version=VERSION,
                    dependency_ids_json=[
                        "task-m0-operating-subject-binding"
                    ],
                    verification_condition=(
                        "fresh bound-operating-subject "
                        "ScopeGrantAuthority.current projection resolves "
                        "one current entity grant"
                    ),
                    next_safe_action=(
                        "submit current owner source Evidence, obtain an accepted "
                        "independent review, then run the non-mutating scope grant "
                        "admission preflight"
                    ),
                    workspace="/authority-graph",
                    sla_seconds=86400,
                    fingerprint=_sha(
                        [PROJECT_ID, "task-m0-scope-authority-admission"]
                    ),
                    created_at=now,
                )
            )
        elif (
            authority_task.project_id != PROJECT_ID
            or authority_task.verifier_id != "scope-grant-current"
            or authority_task.verifier_version != VERSION
        ):
            raise RuntimeError(
                "canonical Goal task drift: "
                "task-m0-scope-authority-admission"
            )
        else:
            authority_task.dependency_ids_json = [
                "task-m0-operating-subject-binding"
            ]
            authority_task.verification_condition = (
                "fresh bound-operating-subject "
                "ScopeGrantAuthority.current projection resolves one "
                "current entity grant"
            )
        for task_id, title, verifier, dependencies, workspace in task_specs:
            task = session.get(GoalTaskRow, task_id)
            expected = {
                "title": title,
                "verifier_id": f"bas128-{verifier}",
                "verifier_version": VERSION,
                "dependency_ids_json": list(dependencies),
                "workspace": workspace,
            }
            if task is None:
                session.add(
                    GoalTaskRow(
                        id=task_id,
                        project_id=PROJECT_ID,
                        title=title,
                        owner="engineering",
                        verifier_id=expected["verifier_id"],
                        verifier_version=VERSION,
                        dependency_ids_json=list(dependencies),
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
            elif any(getattr(task, key) != value for key, value in expected.items()):
                raise RuntimeError(f"canonical Goal task drift: {task_id}")
        for (
            task_id,
            title,
            verifier_id,
            _observation_key,
            dependencies,
            workspace,
        ) in scheduler_task_specs:
            task = session.get(GoalTaskRow, task_id)
            expected = {
                "title": title,
                "verifier_id": verifier_id,
                "verifier_version": VERSION,
                "dependency_ids_json": list(dependencies),
                "workspace": workspace,
            }
            owner = (
                "engineering+operations"
                if task_id == "task-bas040-health-scheduler-deployment"
                else "engineering"
            )
            verification_condition = (
                "exact secret-free Windows Task definition, current healthy "
                "preflight, and three consecutive result-0 completions"
                if task_id == "task-bas040-health-scheduler-deployment"
                else "fresh external scheduler verifier test process is passed"
            )
            next_safe_action = (
                "provide scheduler-visible project configuration, run explicit "
                "Install, then observe three consecutive successful completions"
                if task_id == "task-bas040-health-scheduler-deployment"
                else "inspect the exact test-process artifact and rerun it"
            )
            if task is None:
                session.add(
                    GoalTaskRow(
                        id=task_id,
                        project_id=PROJECT_ID,
                        title=title,
                        owner=owner,
                        verifier_id=verifier_id,
                        verifier_version=VERSION,
                        dependency_ids_json=list(dependencies),
                        verification_condition=verification_condition,
                        next_safe_action=next_safe_action,
                        workspace=workspace,
                        sla_seconds=86400,
                        fingerprint=_sha([PROJECT_ID, task_id]),
                        created_at=now,
                    )
                )
            elif any(
                getattr(task, key) != value for key, value in expected.items()
            ):
                raise RuntimeError(f"canonical Goal task drift: {task_id}")
        for (
            task_id,
            title,
            verifier_id,
            _observation_key,
            dependencies,
            workspace,
        ) in topology_task_specs:
            task = session.get(GoalTaskRow, task_id)
            expected = {
                "title": title,
                "verifier_id": verifier_id,
                "verifier_version": VERSION,
                "dependency_ids_json": list(dependencies),
                "workspace": workspace,
            }
            is_runtime = task_id.endswith("-topology")
            if task is None:
                session.add(
                    GoalTaskRow(
                        id=task_id,
                        project_id=PROJECT_ID,
                        title=title,
                        owner=(
                            "account-owner+identity-engineering"
                            if is_runtime
                            else "engineering"
                        ),
                        verifier_id=verifier_id,
                        verifier_version=VERSION,
                        dependency_ids_json=list(dependencies),
                        verification_condition=(
                            "fresh live Web observation proves four distinct "
                            "exact-scope API actors and independently bound "
                            "Supabase users"
                            if is_runtime
                            else "fresh external Web verifier tests pass"
                        ),
                        next_safe_action=(
                            "configure Supabase Web auth and bind four "
                            "distinct users to the observed workflow actors"
                            if is_runtime
                            else "inspect the exact Node test artifact and rerun"
                        ),
                        workspace=workspace,
                        sla_seconds=86400,
                        fingerprint=_sha([PROJECT_ID, task_id]),
                        created_at=now,
                    )
                )
            elif any(
                getattr(task, key) != value for key, value in expected.items()
            ):
                raise RuntimeError(f"canonical Goal task drift: {task_id}")
        for (
            task_id,
            title,
            verifier_id,
            _observation_key,
            dependencies,
            workspace,
        ) in intake_task_specs:
            task = session.get(GoalTaskRow, task_id)
            expected = {
                "title": title,
                "verifier_id": verifier_id,
                "verifier_version": VERSION,
                "dependency_ids_json": list(dependencies),
                "workspace": workspace,
            }
            if task is None:
                session.add(
                    GoalTaskRow(
                        id=task_id,
                        project_id=PROJECT_ID,
                        title=title,
                        owner=(
                            "identity-governance"
                            if task_id.endswith("-live")
                            else "engineering"
                        ),
                        verifier_id=verifier_id,
                        verifier_version=VERSION,
                        dependency_ids_json=list(dependencies),
                        verification_condition=(
                            "fresh exact-scope API/Web/database observation "
                            "passes without authority mutation"
                            if task_id.endswith("-live")
                            else "fresh external intake verifier tests pass"
                        ),
                        next_safe_action=(
                            "open the role-aware Authority Intake workbench; "
                            "submit no synthetic Evidence"
                            if task_id.endswith("-live")
                            else "inspect the exact test process and rerun it"
                        ),
                        workspace=workspace,
                        sla_seconds=86400,
                        fingerprint=_sha([PROJECT_ID, task_id]),
                        created_at=now,
                    )
                )
            elif any(
                getattr(task, key) != value for key, value in expected.items()
            ):
                raise RuntimeError(f"canonical Goal task drift: {task_id}")
        for (
            task_id,
            title,
            verifier_id,
            _observation_key,
            dependencies,
            workspace,
        ) in dependency_recovery_task_specs:
            task = session.get(GoalTaskRow, task_id)
            expected = {
                "title": title,
                "verifier_id": verifier_id,
                "verifier_version": VERSION,
                "dependency_ids_json": list(dependencies),
                "workspace": workspace,
            }
            if task is None:
                session.add(
                    GoalTaskRow(
                        id=task_id,
                        project_id=PROJECT_ID,
                        title=title,
                        owner="engineering",
                        verifier_id=verifier_id,
                        verifier_version=VERSION,
                        dependency_ids_json=list(dependencies),
                        verification_condition=(
                            "fresh external fault tests prove complete GoalTask "
                            "dependency invalidation and re-verification recovery"
                        ),
                        next_safe_action=(
                            "inspect the exact dependency recovery test process "
                            "and append-only Graph observations"
                        ),
                        workspace=workspace,
                        sla_seconds=86400,
                        fingerprint=_sha([PROJECT_ID, task_id]),
                        created_at=now,
                    )
                )
            elif any(
                getattr(task, key) != value for key, value in expected.items()
            ):
                raise RuntimeError(f"canonical Goal task drift: {task_id}")

        for kind, stable_key, node_type, label, artifact, _task_id in node_specs:
            node_id = f"gn_{_sha([PROJECT_ID, kind, stable_key])[:32]}"
            local_path = ROOT / artifact
            artifact_sha = (
                hashlib.sha256(local_path.read_bytes()).hexdigest()
                if local_path.is_file()
                else _sha(
                    {
                        "artifact": artifact,
                        "external_input": observations.get(
                            "containers", {}
                        ).get("input_sha256"),
                    }
                )
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
                            "tenant_ref": TENANT_REF,
                            "store_ref": STORE_REF,
                        },
                        version=artifact_sha[:12],
                        content_sha256=_sha(content),
                        artifact_ref=artifact,
                        created_at=now,
                    )
                )
            else:
                identity_drift = (
                    node.project_id != PROJECT_ID
                    or node.graph_kind != kind
                    or node.stable_key != stable_key
                    or node.node_type != node_type
                    or node.authority != "canonical"
                )
                artifact_drift = (
                    node.source != artifact
                    or node.artifact_ref != artifact
                )
                initial_scheduler_artifact = (
                    stable_key in SCHEDULER_RUNTIME_NODE_KEYS
                    and artifact == SCHEDULER_ARTIFACT_ROOT
                    and node.source == node.artifact_ref
                    and node.source.startswith(
                        f"{SCHEDULER_ARTIFACT_ROOT}/"
                    )
                    and node.source.endswith(".json")
                )
                if identity_drift or (
                    artifact_drift and not initial_scheduler_artifact
                ):
                    raise RuntimeError(
                        f"canonical Graph node drift: {stable_key}"
                    )
                if initial_scheduler_artifact:
                    node.source = artifact
                    node.artifact_ref = artifact
                node.label = label
                node.version = artifact_sha[:12]
                node.content_sha256 = _sha(content)

        session.flush()
        by_key = {
            row.stable_key: row
            for row in session.scalars(
                select(GraphNodeRow).where(
                    GraphNodeRow.project_id == PROJECT_ID
                )
            )
        }
        for source, edge_type, target, kind in _edge_specs():
            if source not in by_key or target not in by_key:
                raise RuntimeError(f"Graph edge endpoint missing: {source}->{target}")
            edge_id = (
                f"ge_{_sha([PROJECT_ID, kind, source, edge_type, target])[:32]}"
            )
            edge_evidence = (
                EVIDENCE_135
                if {source, target}.intersection(BAS135_NODE_KEYS)
                else EVIDENCE_134
                if {source, target}.intersection(BAS134_NODE_KEYS)
                else EVIDENCE_133
                if {source, target}.intersection(BAS133_NODE_KEYS)
                else EVIDENCE_132
                if {source, target}.intersection(BAS132_NODE_KEYS)
                else EVIDENCE_131
                if "authority:operating-subject-binding" in {source, target}
                else EVIDENCE_129
                if "authority:current-scope-grant" in {source, target}
                else EVIDENCE_128
            )
            payload = [source, edge_type, target, "evidence", edge_evidence]
            edge = session.get(GraphEdgeRow, edge_id)
            if edge is None:
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
                        evidence_ref=edge_evidence,
                        effective_from=now,
                        effective_until=None,
                        content_sha256=_sha(payload),
                    )
                )
            elif (
                edge.source_node_id != by_key[source].id
                or edge.target_node_id != by_key[target].id
                or edge.edge_type != edge_type
                or edge.graph_kind != kind
                or edge.content_sha256 != _sha(payload)
            ):
                raise RuntimeError(
                    f"canonical Graph edge drift: {source}->{target}"
                )

    bindings = {
        stable_key: task_id
        for _kind, stable_key, _type, _label, _artifact, task_id in node_specs
    }
    bindings.update(
        {
            "milestone:M0": "task-m0-current-authority",
            "milestone:M1": "task-m1-formal-fact-chain",
            "milestone:M2": "task-m2-content-profit-listing",
            "milestone:M3": "task-m3-pilot-order-settlement",
            "milestone:M4": "task-m4-actual-cash",
            "gate-state:M0": "task-m0-current-authority",
            "gate-state:M1": "task-m1-formal-fact-chain",
            "gate-state:M2": "task-m2-content-profit-listing",
            "gate-state:M3": "task-m3-pilot-order-settlement",
            "gate-state:M4": "task-m4-actual-cash",
        }
    )
    with Session(engine) as session:
        by_key = {
            row.stable_key: row.id
            for row in session.scalars(
                select(GraphNodeRow).where(
                    GraphNodeRow.project_id == PROJECT_ID,
                    GraphNodeRow.stable_key.in_(bindings),
                )
            )
        }
    if set(by_key) != set(bindings):
        missing = sorted(set(bindings) - set(by_key))
        raise RuntimeError(f"Graph status binding nodes missing: {missing}")
    for stable_key, task_id in bindings.items():
        service.bind_node_status(
            project_id=PROJECT_ID,
            node_id=by_key[stable_key],
            task_id=task_id,
        )


def probe_live_graph_api() -> dict[str, Any]:
    headers = {"X-KJDS-API-Key": _authorized_api_key()}
    urls = {
        "workspace": (
            f"http://127.0.0.1:8000/v1/agent-control/projects/{PROJECT_ID}"
            f"?store_ref={STORE_REF}"
        ),
        "project": (
            f"http://127.0.0.1:8000/v1/agent-control/projects/{PROJECT_ID}"
            f"/graphs/project?store_ref={STORE_REF}"
        ),
        "engineering": (
            f"http://127.0.0.1:8000/v1/agent-control/projects/{PROJECT_ID}"
            f"/graphs/engineering?store_ref={STORE_REF}"
        ),
    }
    responses = {
        name: httpx.get(url, headers=headers, timeout=15)
        for name, url in urls.items()
    }
    if any(response.status_code != 200 for response in responses.values()):
        statuses = {
            name: response.status_code
            for name, response in responses.items()
        }
        raise RuntimeError(f"live Graph API probe failed: {statuses}")
    web_project = httpx.get("http://127.0.0.1:3000/project-graph", timeout=15)
    web_engineering = httpx.get(
        "http://127.0.0.1:3000/engineering-graph",
        timeout=15,
    )
    if web_project.status_code != 200 or web_engineering.status_code != 200:
        raise RuntimeError("live Project/Engineering Graph Web route failed")

    payloads = {name: response.json() for name, response in responses.items()}
    workspace = payloads["workspace"]
    if workspace.get("contract_id") != AgentHarnessService.CONTRACT_ID:
        raise RuntimeError("live Graph API contract drift")
    if workspace.get("external_write_allowed") is not False:
        raise RuntimeError("live Graph API unexpectedly allows external writes")
    if workspace.get("model_self_certification_allowed") is not False:
        raise RuntimeError("live Graph API unexpectedly allows model certification")
    if int(workspace.get("counts", {}).get("verified_nodes", 0)) < 20:
        raise RuntimeError("live Graph API does not expose verifier-owned nodes")
    br104 = next(
        (
            node
            for node in payloads["engineering"].get("nodes", [])
            if node.get("stable_key") == "code:graph-node-status-binding"
        ),
        None,
    )
    if not br104 or not br104.get("verification"):
        raise RuntimeError("verifier-owned engineering node drilldown is missing")
    contract_snapshot = {
        "contract_id": workspace["contract_id"],
        "scope": workspace["scope"],
        "counts": {
            name: workspace["counts"][name]
            for name in ("tasks", "nodes", "edges", "verified_nodes")
        },
        "project_graph_nodes": len(payloads["project"].get("nodes", [])),
        "engineering_graph_nodes": len(
            payloads["engineering"].get("nodes", [])
        ),
        "node_binding_sha256": br104["verification"]["binding_sha256"],
        "external_write_allowed": False,
        "model_self_certification_allowed": False,
    }
    return {
        "state": "passed",
        "summary": (
            "authenticated workspace, Project Graph and Engineering Graph 200; "
            f"{contract_snapshot['counts']['verified_nodes']} verifier-owned nodes"
        ),
        "input_sha256": _sha(contract_snapshot),
        "artifact_ref": urls["workspace"],
        "snapshot": contract_snapshot,
    }


def record_observations(
    observations: dict[str, dict[str, Any]],
    *,
    observed_at: datetime,
) -> None:
    engine = create_database_engine()
    service = AgentHarnessService(engine)
    monitor = Principal(
        actor_id="bas128-external-verifier",
        roles=frozenset({"monitor"}),
        tenant_ref=TENANT_REF,
        store_refs=frozenset({STORE_REF}),
    )
    verifier_defs = {
        "pytest": "pytest_process",
        "database": "postgres_query",
        "containers": "docker_health",
        "api": "http_probe",
        "browser": "browser_evidence",
        "evidence": "immutable_artifact",
    }
    for task_id, _title, verifier, _dependencies, _workspace in _task_specs():
        item = observations[verifier]
        service.record_observation(
            {
                "project_id": PROJECT_ID,
                "task_id": task_id,
                "verifier_id": f"bas128-{verifier}",
                "verifier_version": VERSION,
                "source": verifier_defs[verifier],
                "scope": {
                    "tenant_ref": TENANT_REF,
                    "store_ref": STORE_REF,
                },
                "state": item["state"],
                "summary": item["summary"],
                "input_sha256": item["input_sha256"],
                "artifact_ref": item["artifact_ref"],
                "evidence_ref": EVIDENCE_128,
                "observed_at": observed_at.isoformat(),
                "store_ref": STORE_REF,
            },
            principal=monitor,
        )
    scheduler_sources = {
        "pytest132": "pytest_process",
        "scheduler": "windows_task_and_health_audit",
    }
    for (
        task_id,
        _title,
        verifier_id,
        observation_key,
        _dependencies,
        _workspace,
    ) in _scheduler_task_specs():
        item = observations[observation_key]
        service.record_observation(
            {
                "project_id": PROJECT_ID,
                "task_id": task_id,
                "verifier_id": verifier_id,
                "verifier_version": VERSION,
                "source": scheduler_sources[observation_key],
                "scope": {
                    "tenant_ref": TENANT_REF,
                    "store_ref": STORE_REF,
                },
                "state": item["state"],
                "summary": item["summary"],
                "input_sha256": item["input_sha256"],
                "artifact_ref": item["artifact_ref"],
                "evidence_ref": EVIDENCE_132,
                "observed_at": observed_at.isoformat(),
                "store_ref": STORE_REF,
            },
            principal=monitor,
        )
    for (
        task_id,
        _title,
        verifier_id,
        observation_key,
        _dependencies,
        _workspace,
    ) in _dependency_recovery_task_specs():
        item = observations[observation_key]
        service.record_observation(
            {
                "project_id": PROJECT_ID,
                "task_id": task_id,
                "verifier_id": verifier_id,
                "verifier_version": VERSION,
                "source": "pytest_process",
                "scope": {
                    "tenant_ref": TENANT_REF,
                    "store_ref": STORE_REF,
                },
                "state": item["state"],
                "summary": item["summary"],
                "input_sha256": item["input_sha256"],
                "artifact_ref": item["artifact_ref"],
                "evidence_ref": EVIDENCE_135,
                "observed_at": observed_at.isoformat(),
                "store_ref": STORE_REF,
            },
            principal=monitor,
        )
    topology_sources = {
        "tests134": "web_test_process",
        "topology": "live_web_identity_topology",
    }
    for (
        task_id,
        _title,
        verifier_id,
        observation_key,
        _dependencies,
        _workspace,
    ) in _topology_task_specs():
        item = observations[observation_key]
        service.record_observation(
            {
                "project_id": PROJECT_ID,
                "task_id": task_id,
                "verifier_id": verifier_id,
                "verifier_version": VERSION,
                "source": topology_sources[observation_key],
                "scope": {
                    "tenant_ref": TENANT_REF,
                    "store_ref": STORE_REF,
                },
                "state": item["state"],
                "summary": item["summary"],
                "input_sha256": item["input_sha256"],
                "artifact_ref": item["artifact_ref"],
                "evidence_ref": EVIDENCE_134,
                "observed_at": observed_at.isoformat(),
                "store_ref": STORE_REF,
            },
            principal=monitor,
        )
    intake_sources = {
        "pytest133": "pytest_process",
        "intake": "api_web_database_observation",
    }
    for (
        task_id,
        _title,
        verifier_id,
        observation_key,
        _dependencies,
        _workspace,
    ) in _intake_task_specs():
        item = observations[observation_key]
        service.record_observation(
            {
                "project_id": PROJECT_ID,
                "task_id": task_id,
                "verifier_id": verifier_id,
                "verifier_version": VERSION,
                "source": intake_sources[observation_key],
                "scope": {
                    "tenant_ref": TENANT_REF,
                    "store_ref": STORE_REF,
                },
                "state": item["state"],
                "summary": item["summary"],
                "input_sha256": item["input_sha256"],
                "artifact_ref": item["artifact_ref"],
                "evidence_ref": EVIDENCE_133,
                "observed_at": observed_at.isoformat(),
                "store_ref": STORE_REF,
            },
            principal=monitor,
        )


def _observation_dependency_specs(
) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    base = tuple(
        (task_id, observation_key, dependencies)
        for task_id, _title, observation_key, dependencies, _workspace
        in _task_specs()
    )
    extended = tuple(
        (task_id, observation_key, dependencies)
        for specs in (
            _scheduler_task_specs(),
            _intake_task_specs(),
            _topology_task_specs(),
            _dependency_recovery_task_specs(),
        )
        for (
            task_id,
            _title,
            _verifier_id,
            observation_key,
            dependencies,
            _workspace,
        ) in specs
    )
    return base + extended


def latest_external_dependency_inputs() -> dict[str, str | None]:
    specs = _observation_dependency_specs()
    observed_task_ids = {task_id for task_id, _key, _deps in specs}
    dependency_ids = sorted(
        {
            dependency_id
            for _task_id, _key, dependencies in specs
            for dependency_id in dependencies
            if dependency_id not in observed_task_ids
        }
    )
    engine = create_database_engine()
    with Session(engine) as session:
        rows = session.scalars(
            select(HarnessObservationRow)
            .where(HarnessObservationRow.task_id.in_(dependency_ids))
            .order_by(
                HarnessObservationRow.task_id,
                HarnessObservationRow.observed_at.desc(),
                HarnessObservationRow.id.desc(),
            )
        ).all()
    latest: dict[str, str | None] = {
        dependency_id: None for dependency_id in dependency_ids
    }
    for row in rows:
        if latest[row.task_id] is None:
            latest[row.task_id] = row.input_sha256
    return latest


def chain_observation_inputs(
    observations: dict[str, dict[str, Any]],
    *,
    external_dependency_inputs: dict[str, str | None] | None = None,
) -> None:
    specs = _observation_dependency_specs()
    task_input_sha256: dict[str, str] = {}
    external_inputs = external_dependency_inputs or {}
    observed_task_ids = {task_id for task_id, _key, _deps in specs}
    for task_id, observation_key, dependencies in specs:
        item = observations.get(observation_key)
        if item is None:
            continue
        dependency_inputs: dict[str, str | None] = {}
        for dependency_id in dependencies:
            if dependency_id in observed_task_ids:
                if dependency_id not in task_input_sha256:
                    raise RuntimeError(
                        "observation dependency order drift: "
                        f"{task_id} before {dependency_id}"
                    )
                dependency_inputs[dependency_id] = task_input_sha256[
                    dependency_id
                ]
            else:
                dependency_inputs[dependency_id] = external_inputs.get(
                    dependency_id
                )
        item["input_sha256"] = _sha(
            {
                "source_input_sha256": item["input_sha256"],
                "dependency_input_sha256": dependency_inputs,
            }
        )
        task_input_sha256[task_id] = item["input_sha256"]


def counts() -> dict[str, int]:
    engine = create_database_engine()
    with Session(engine) as session:
        return {
            name: int(
                session.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(model.project_id == PROJECT_ID)
                )
                or 0
            )
            for name, model in (
                ("tasks", GoalTaskRow),
                ("observations", HarnessObservationRow),
                ("nodes", GraphNodeRow),
                ("edges", GraphEdgeRow),
                ("bindings", GraphNodeStatusBindingRow),
            )
        }


if __name__ == "__main__":
    prepare_only = "--prepare" in sys.argv[1:]
    unknown_args = set(sys.argv[1:]) - {"--prepare"}
    if unknown_args:
        raise SystemExit(f"unsupported arguments: {sorted(unknown_args)}")
    observed = observe_external(require_browser_evidence=not prepare_only)
    seed_structure(observed)
    if prepare_only:
        print(
            json.dumps(
                {
                    "project_id": PROJECT_ID,
                    **counts(),
                    "prepared_only": True,
                    "release_gate": "REJECTED",
                    "external_write_allowed": False,
                    "model_self_certification_allowed": False,
                },
                sort_keys=True,
            )
        )
        raise SystemExit(0)
    observed["api"] = probe_live_graph_api()
    chain_observation_inputs(
        observed,
        external_dependency_inputs=latest_external_dependency_inputs(),
    )
    now = datetime.now(UTC)
    record_observations(observed, observed_at=now)
    engine = create_database_engine()
    principal = Principal(
        actor_id="bas128-acceptance",
        roles=frozenset({"monitor"}),
        tenant_ref=TENANT_REF,
        store_refs=frozenset({STORE_REF}),
    )
    workspace = AgentHarnessService(engine).workspace(
        PROJECT_ID,
        principal=principal,
        store_ref=STORE_REF,
        as_of=now + timedelta(seconds=1),
    )
    print(
        json.dumps(
            {
                "project_id": PROJECT_ID,
                **counts(),
                "database_revision": "20260728_0070",
                "workspace_status": workspace["status"],
                "workspace_snapshot_sha256": workspace["snapshot_sha256"],
                "verified_nodes": workspace["counts"]["verified_nodes"],
                "states": {
                    task["id"]: task["state"]
                    for task in workspace["tasks"]
                    if task["id"].startswith("task-bas128")
                    or task["id"].startswith("task-bas132")
                    or task["id"].startswith("task-bas133")
                    or task["id"].startswith("task-bas134")
                    or task["id"].startswith("task-bas135")
                    or task["id"].startswith("task-bas040")
                    or task["id"].startswith("task-m")
                },
                "release_gate": "REJECTED",
                "external_write_allowed": False,
                "model_self_certification_allowed": False,
            },
            sort_keys=True,
        )
    )
