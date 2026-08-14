from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, func, select
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
OWNER = "channel-account-authority-engineering"
EVIDENCE = "docs/project/evidence/20260731_BAS_158_NATIVE_EXACT_SCOPE_CHANNEL_ACCOUNT_AUTHORITY.md"
SCREENSHOTS = (
    "output/playwright/bas158-channel-accounts-desktop.png",
    "output/playwright/bas158-channel-accounts-mobile-390.png",
)
MIGRATION = "migrations/versions/20260731_0081_native_channel_account_authority.py"
BACKEND_FILES = (
    "apps/control_plane/channel_account_authority.py",
    "apps/control_plane/channel_account_runtime_identity.py",
    "apps/control_plane/ozon_read_worker.py",
    "apps/control_plane/ozon_worker.py",
    "apps/control_plane/routers/evidence_governance.py",
    "apps/control_plane/scoped_channel_account_authority.py",
    "apps/control_plane/routers/channel_accounts.py",
    "apps/control_plane/runtime.py",
    "compose.yaml",
    "docs/project/registries/channel_account_adapters.json",
)
FOCUSED_TESTS = (
    "tests/test_channel_account_authority.py",
    "tests/test_channel_account_governance_evidence.py",
    "tests/test_channel_account_runtime_identity.py",
    "tests/test_scoped_channel_account_authority.py",
    "tests/test_channel_accounts_api.py",
    "tests/test_api_contract.py",
    "tests/test_external_contract_replay.py",
    "tests/test_outbox_coverage_registry.py",
    "tests/test_ozon_read_preflight.py",
    "tests/test_ozon_worker.py",
    "tests/test_reserved_evidence_workflows.py",
    "tests/test_security.py",
    "tests/test_write_path_registry.py",
)
SCRIPT_FILES = (
    "scripts/verify_bas158_runtime.py",
    "scripts/verify_bas158_migration_replay.py",
    "scripts/seed_bas158_agent_graph.py",
)
CONTRACT_FILES = ("docs/project/contracts/openapi-v1.json",)
WEB_DIRECTORIES = (
    "web/app/channel-accounts",
    "web/features/channel-accounts",
)
WEB_TEST_GLOB = "web/lib/*channel-account*.test.ts"
REPLAY_MARKER = "BAS-158 empty PostgreSQL replay passed: base -> 0081 -> 0080 -> 0081"

TASK_SPECS = (
    (
        "task-bas158-pytest",
        "BAS-158 channel-account authority and fail-closed composition",
        "tests",
        ("task-bas157-evidence",),
        "/engineering-graph",
    ),
    (
        "task-bas158-database",
        "BAS-158 append-only PostgreSQL 0081 channel-account authority",
        "database",
        ("task-bas158-pytest",),
        "/runtime-graph",
    ),
    (
        "task-bas158-runtime",
        "BAS-158 authenticated deterministic channel-account no-data runtime",
        "runtime",
        ("task-bas158-database",),
        "/runtime-graph",
    ),
    (
        "task-bas158-web",
        "BAS-158 executable channel-account states and responsive workspace",
        "web",
        ("task-bas158-runtime",),
        "/channel-accounts",
    ),
    (
        "task-bas158-evidence",
        "BAS-158 immutable channel-account authority Evidence",
        "evidence",
        ("task-bas158-web",),
        "/evidence-graph",
    ),
)

NODE_SPECS = (
    (
        "requirements",
        "requirement:BR-132@master-8.63",
        "requirement",
        "BR-132 native exact-scope channel-account authority",
        "docs/project/MASTER_SPEC.md",
        "task-bas158-pytest",
    ),
    (
        "requirements",
        "adr:ADR-0078",
        "adr",
        "ADR-0078 native exact-scope channel-account authority",
        "docs/adr/ADR-0078-native-exact-scope-channel-account-authority.md",
        "task-bas158-pytest",
    ),
    (
        "engineering",
        "service:channel-account-authority-v1",
        "service",
        "Append-only non-secret channel-account authorization authority v1",
        "apps/control_plane/channel_account_authority.py",
        "task-bas158-pytest",
    ),
    (
        "engineering",
        "service:scoped-channel-account-authority-v1",
        "service",
        "ScopedChannelAccountAuthorityWorkspace exact-scope v1",
        "apps/control_plane/scoped_channel_account_authority.py",
        "task-bas158-pytest",
    ),
    (
        "engineering",
        "database:native-channel-account-authority-0081",
        "database_probe",
        "Forward-only append-only channel-account authority at 0081",
        MIGRATION,
        "task-bas158-database",
    ),
    (
        "runtime",
        "api:channel-account-authority-no-data",
        "api_probe",
        "Authenticated deterministic channel-account no-data boundary",
        "http://127.0.0.1:8000/v1/channel-accounts/workspace",
        "task-bas158-runtime",
    ),
    (
        "runtime",
        "web:channel-account-authority-390",
        "browser_probe",
        "Channel-account authority desktop and 390px workspace",
        SCREENSHOTS[1],
        "task-bas158-web",
    ),
    (
        "evidence",
        "evidence:BAS-158",
        "evidence",
        "BAS-158 channel-account contract/no-data Evidence",
        EVIDENCE,
        "task-bas158-evidence",
    ),
)

EDGE_SPECS = (
    (
        "requirement:BR-132@master-8.63",
        "specified_by",
        "adr:ADR-0078",
        "requirements",
    ),
    (
        "adr:ADR-0078",
        "implemented_by",
        "service:channel-account-authority-v1",
        "engineering",
    ),
    (
        "service:channel-account-authority-v1",
        "composed_by",
        "service:scoped-channel-account-authority-v1",
        "engineering",
    ),
    (
        "service:scoped-channel-account-authority-v1",
        "requires",
        "database:native-channel-account-authority-0081",
        "engineering",
    ),
    (
        "database:native-channel-account-authority-0081",
        "observed_as",
        "api:channel-account-authority-no-data",
        "runtime",
    ),
    (
        "api:channel-account-authority-no-data",
        "rendered_by",
        "web:channel-account-authority-390",
        "runtime",
    ),
    (
        "web:channel-account-authority-390",
        "recorded_in",
        "evidence:BAS-158",
        "evidence",
    ),
)

VERIFIER_DEFS = {
    "tests": ("pytest_process", "test_process"),
    "database": ("postgresql_replay", "database"),
    "runtime": ("http_and_docker_probe", "runtime"),
    "web": ("web_test_and_playwright_measurement", "browser"),
    "evidence": ("immutable_artifact", "evidence"),
}


def file_sha(relative: str) -> str:
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def collect_required_artifacts() -> dict[str, list[str]]:
    missing: list[str] = []
    required_files = (
        *BACKEND_FILES,
        *FOCUSED_TESTS,
        *SCRIPT_FILES,
        *CONTRACT_FILES,
        MIGRATION,
        EVIDENCE,
        *SCREENSHOTS,
        "docs/project/MASTER_SPEC.md",
        "docs/adr/ADR-0078-native-exact-scope-channel-account-authority.md",
    )
    for relative in required_files:
        if not (ROOT / relative).is_file():
            missing.append(relative)

    web_files: list[str] = []
    for relative in WEB_DIRECTORIES:
        directory = ROOT / relative
        if not directory.is_dir():
            missing.append(f"{relative}/ (directory)")
            continue
        files = sorted(path for path in directory.rglob("*") if path.is_file())
        if not files:
            missing.append(f"{relative}/ (empty directory)")
            continue
        web_files.extend(_relative(path) for path in files)

    web_tests = sorted(_relative(path) for path in ROOT.glob(WEB_TEST_GLOB) if path.is_file())
    if not web_tests:
        missing.append(f"{WEB_TEST_GLOB} (at least one matching test)")
    if missing:
        raise RuntimeError("BAS-158 required artifacts are missing:\n- " + "\n- ".join(sorted(set(missing))))
    return {
        "backend": sorted(BACKEND_FILES),
        "tests": sorted(FOCUSED_TESTS),
        "scripts": sorted(SCRIPT_FILES),
        "contracts": sorted(CONTRACT_FILES),
        "web": sorted(set(web_files)),
        "web_tests": web_tests,
        "screenshots": sorted(SCREENSHOTS),
        "evidence": [EVIDENCE],
        "migration": [MIGRATION],
    }


def hash_files(paths: list[str] | tuple[str, ...]) -> str:
    return _sha({path: file_sha(path) for path in sorted(paths)})


def run(command: list[str], *, label: str, cwd: Path = ROOT) -> str:
    process = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    if process.returncode != 0:
        raise RuntimeError(f"BAS-158 {label} failed with exit code {process.returncode}")
    return process.stdout + process.stderr


def _parse_compose_rows(output: str) -> list[dict[str, Any]]:
    stripped = output.strip()
    if not stripped:
        return []
    if stripped.startswith("["):
        parsed = json.loads(stripped)
        if not isinstance(parsed, list) or not all(isinstance(row, dict) for row in parsed):
            raise RuntimeError("BAS-158 Docker Compose status is not a JSON row list")
        return parsed
    rows = []
    for line in stripped.splitlines():
        parsed = json.loads(line)
        if not isinstance(parsed, dict):
            raise RuntimeError("BAS-158 Docker Compose status contains a non-object row")
        rows.append(parsed)
    return rows


def _validate_runtime(runtime: dict[str, Any]) -> None:
    expected = {
        "anonymous": 401,
        "authenticated": 200,
        "forbidden": 403,
        "readiness": 200,
        "status": "no_data",
        "total": 0,
        "channel_accounts": [],
        "verified_native": False,
        "native_implementation_status": "implemented_unverified",
        "read_only_projection": True,
        "deterministic": True,
    }
    drift = [key for key, value in expected.items() if runtime.get(key) != value]
    false_controls = {
        "secret_reference_returned",
        "plaintext_secret_stored",
        "cookie_allowed",
        "internal_token_allowed",
        "device_session_allowed",
        "private_endpoint_allowed",
        "captcha_bypass_allowed",
        "access_control_bypass_allowed",
        "external_write_allowed",
    }
    false_permissions = {
        "secret_read_allowed",
        "authorization_change_allowed",
        "self_approval_allowed",
        "permit_issue_allowed",
        "external_verification_allowed",
        "platform_contact_allowed",
        "fictional_authority_allowed",
        "external_write_allowed",
    }
    control = runtime.get("control_envelope")
    permissions = runtime.get("agent_permissions")
    control = control if isinstance(control, dict) else {}
    permissions = permissions if isinstance(permissions, dict) else {}
    drift.extend(f"control_envelope.{field}" for field in false_controls if control.get(field) is not False)
    drift.extend(f"agent_permissions.{field}" for field in false_permissions if permissions.get(field) is not False)
    snapshot = runtime.get("snapshot_sha256")
    if not isinstance(snapshot, str) or re.fullmatch(r"[0-9a-f]{64}", snapshot) is None:
        drift.append("snapshot_sha256")
    if drift:
        raise RuntimeError("BAS-158 runtime truth boundary drifted at: " + ", ".join(sorted(drift)))


def observations(artifacts: dict[str, list[str]]) -> dict[str, dict[str, str]]:
    pytest_output = run(
        [
            sys.executable,
            "-m",
            "pytest",
            *FOCUSED_TESTS,
            "-q",
            "-p",
            "no:cacheprovider",
            f"--basetemp=output/pytest/bas158-graph-{os.getpid()}",
        ],
        label="focused pytest",
    )
    match = re.search(r"(\d+) passed", pytest_output)
    if match is None:
        raise RuntimeError("BAS-158 focused pytest output has no passed count")
    passed = int(match.group(1))

    heads = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini"))).get_heads()
    if heads != ["20260731_0081"]:
        raise RuntimeError(f"BAS-158 Alembic head drifted: {heads}")
    replay_output = run(
        [sys.executable, "scripts/verify_bas158_migration_replay.py"],
        label="PostgreSQL migration replay",
    )
    if REPLAY_MARKER not in replay_output:
        raise RuntimeError("BAS-158 PostgreSQL replay success marker is missing")

    compose_rows = _parse_compose_rows(
        run(
            ["docker", "compose", "ps", "--format", "json"],
            label="Docker Compose health probe",
        )
    )
    healthy = {
        str(row.get("Service"))
        for row in compose_rows
        if row.get("State") == "running" and row.get("Health") == "healthy"
    }
    required_services = {"api", "media-worker", "postgres", "web"}
    if not required_services <= healthy:
        raise RuntimeError(
            "BAS-158 required containers are not running and healthy: " + ", ".join(sorted(required_services - healthy))
        )

    runtime_output = run(
        [sys.executable, "scripts/verify_bas158_runtime.py"],
        label="GET-only runtime verifier",
    )
    runtime_lines = [line for line in runtime_output.splitlines() if line.strip()]
    if not runtime_lines:
        raise RuntimeError("BAS-158 runtime verifier produced no JSON result")
    try:
        runtime = json.loads(runtime_lines[-1])
    except json.JSONDecodeError as exc:
        raise RuntimeError("BAS-158 runtime verifier result is not JSON") from exc
    if not isinstance(runtime, dict):
        raise RuntimeError("BAS-158 runtime verifier result must be an object")
    _validate_runtime(runtime)

    run(
        ["npm.cmd" if os.name == "nt" else "npm", "test"],
        cwd=ROOT / "web",
        label="Web test suite",
    )
    screenshot_hashes = {path: file_sha(path) for path in SCREENSHOTS}

    evidence_text = (ROOT / EVIDENCE).read_text(encoding="utf-8")
    for marker in (
        "BAS-158",
        "BR-132",
        "DONE_ENGINEERING",
        "20260731_0081",
        "desktop inner/scroll width: `1440/1440`",
        "mobile inner/scroll width: `390/390`",
        "console errors: `0`",
        "external_write_allowed=false",
    ):
        if marker not in evidence_text:
            raise RuntimeError(f"BAS-158 Evidence marker missing: {marker}")

    common = {"state": "passed"}
    return {
        "tests": {
            **common,
            "summary": (
                f"{passed} focused tests executed by this verifier; exact-scope, "
                "authorization Evidence, API/security and write-path closure pass"
            ),
            "input_sha256": _sha(
                {
                    "backend": hash_files(artifacts["backend"]),
                    "tests": hash_files(artifacts["tests"]),
                    "scripts": hash_files(artifacts["scripts"]),
                    "contracts": hash_files(artifacts["contracts"]),
                }
            ),
            "artifact_ref": "process:pytest BAS-158",
        },
        "database": {
            **common,
            "summary": (
                "Alembic single 0081; empty PostgreSQL "
                "base→0081→0080→0081 replay, constraints and append-only triggers pass"
            ),
            "input_sha256": _sha(
                {
                    "heads": heads,
                    "migration": hash_files(artifacts["migration"]),
                    "replay_script": file_sha("scripts/verify_bas158_migration_replay.py"),
                    "replay_output_sha256": hashlib.sha256(replay_output.encode()).hexdigest(),
                }
            ),
            "artifact_ref": "postgres:alembic_version,channel_account_authority",
        },
        "runtime": {
            **common,
            "summary": (
                "Four containers healthy; GET-only 401/200/403 deterministic real "
                "no_data; no secret, bypass, external verification or external write"
            ),
            "input_sha256": _sha(
                {
                    "runtime": runtime,
                    "runtime_script": file_sha("scripts/verify_bas158_runtime.py"),
                    "healthy_services": sorted(healthy),
                }
            ),
            "artifact_ref": ("http://127.0.0.1:8000/v1/channel-accounts/workspace"),
        },
        "web": {
            **common,
            "summary": (
                "Web tests pass; channel-account app/feature contract and desktop/390px "
                "Evidence artifacts are present and hashed"
            ),
            "input_sha256": _sha(
                {
                    "web": hash_files(artifacts["web"]),
                    "web_tests": hash_files(artifacts["web_tests"]),
                    "screenshots": screenshot_hashes,
                }
            ),
            "artifact_ref": SCREENSHOTS[1],
        },
        "evidence": {
            **common,
            "summary": f"BAS-158 Evidence SHA-256 {file_sha(EVIDENCE)}",
            "input_sha256": _sha(
                {
                    "evidence": file_sha(EVIDENCE),
                    "seed_script": file_sha("scripts/seed_bas158_agent_graph.py"),
                }
            ),
            "artifact_ref": EVIDENCE,
        },
    }


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _latest_observation(
    session: Session,
    task_id: str,
) -> HarnessObservationRow | None:
    return session.scalar(
        select(HarnessObservationRow)
        .where(
            HarnessObservationRow.project_id == PROJECT_ID,
            HarnessObservationRow.task_id == task_id,
        )
        .order_by(
            HarnessObservationRow.observed_at.desc(),
            HarnessObservationRow.id.desc(),
        )
        .limit(1)
    )


def _require_fresh_passed(
    *,
    task: GoalTaskRow,
    observation: HarnessObservationRow | None,
    now: datetime,
) -> HarnessObservationRow:
    if observation is None:
        raise RuntimeError(f"Graph dependency {task.id} has no Observation")
    if observation.state != "passed":
        raise RuntimeError(f"Graph dependency {task.id} latest Observation is not passed")
    if observation.verifier_id != task.verifier_id or observation.verifier_version != task.verifier_version:
        raise RuntimeError(f"Graph dependency {task.id} Observation verifier drifted")
    if _aware(observation.observed_at) > now or _aware(observation.fresh_until) <= now:
        raise RuntimeError(f"Graph dependency {task.id} latest Observation is stale")
    return observation


def require_bas157_dependency(
    engine: Engine,
    *,
    now: datetime,
) -> dict[str, str]:
    with Session(engine) as session:
        project = session.get(GraphProjectRow, PROJECT_ID)
        if project is None:
            raise RuntimeError("canonical KJDS 0.59 Graph project is missing")
        task = session.get(GoalTaskRow, "task-bas157-evidence")
        if task is None or task.project_id != PROJECT_ID:
            raise RuntimeError("BAS-157 Graph Evidence dependency is missing")
        observation = _require_fresh_passed(
            task=task,
            observation=_latest_observation(session, task.id),
            now=now,
        )
        return {
            "task_id": task.id,
            "observation_id": observation.id,
            "state": observation.state,
            "input_sha256": observation.input_sha256,
            "result_sha256": observation.result_sha256,
        }


def _node_id(kind: str, stable_key: str) -> str:
    return f"gn_{_sha([PROJECT_ID, kind, stable_key])[:32]}"


def _edge_id(kind: str, source: str, edge_type: str, target: str) -> str:
    return f"ge_{_sha([PROJECT_ID, kind, source, edge_type, target])[:32]}"


def upsert_graph(
    engine: Engine,
    observed: dict[str, dict[str, str]],
) -> None:
    now = datetime.now(UTC)
    require_bas157_dependency(engine, now=now)
    service = AgentHarnessService(engine)
    for verifier, (source_type, authority) in VERIFIER_DEFS.items():
        service.register_verifier(
            {
                "id": f"bas158-{verifier}",
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
        for task_id, title, verifier, dependencies, workspace in TASK_SPECS:
            task = session.get(GoalTaskRow, task_id)
            if task is None:
                task = GoalTaskRow(
                    id=task_id,
                    project_id=PROJECT_ID,
                    title=title,
                    owner=OWNER,
                    verifier_id=f"bas158-{verifier}",
                    verifier_version="1",
                    dependency_ids_json=list(dependencies),
                    verification_condition=("fresh external verifier observation is passed"),
                    next_safe_action=("inspect the artifact and rerun the bounded verifier"),
                    workspace=workspace,
                    sla_seconds=86400,
                    fingerprint=_sha([PROJECT_ID, task_id]),
                    created_at=now,
                )
                session.add(task)
            else:
                if task.project_id != PROJECT_ID:
                    raise RuntimeError(f"Graph task {task_id} belongs to another project")
                task.title = title
                task.owner = OWNER
                task.verifier_id = f"bas158-{verifier}"
                task.verifier_version = "1"
                task.dependency_ids_json = list(dependencies)
                task.verification_condition = "fresh external verifier observation is passed"
                task.next_safe_action = "inspect the artifact and rerun the bounded verifier"
                task.workspace = workspace

        for kind, stable_key, node_type, label, artifact, _task in NODE_SPECS:
            node_id = _node_id(kind, stable_key)
            local_path = ROOT / artifact
            artifact_sha = file_sha(artifact) if local_path.is_file() else _sha(artifact)
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
                if node.project_id != PROJECT_ID or node.graph_kind != kind:
                    raise RuntimeError(f"Graph node {stable_key} identity drifted")
                node.node_type = node_type
                node.label = label
                node.authority = "canonical"
                node.source = artifact
                node.scope_json = {
                    "tenant_ref": "default",
                    "store_ref": STORE_REF,
                }
                node.content_sha256 = _sha(content)
                node.artifact_ref = artifact
        session.flush()
        by_key = {
            row.stable_key: row
            for row in session.scalars(
                select(GraphNodeRow).where(
                    GraphNodeRow.project_id == PROJECT_ID,
                    GraphNodeRow.id.in_([_node_id(kind, stable_key) for kind, stable_key, *_ in NODE_SPECS]),
                )
            )
        }
        for source, edge_type, target, kind in EDGE_SPECS:
            if source not in by_key or target not in by_key:
                raise RuntimeError(f"BAS-158 Graph edge endpoint is missing: {source} -> {target}")
            edge_id = _edge_id(kind, source, edge_type, target)
            existing = session.get(GraphEdgeRow, edge_id)
            if existing is None:
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
                        content_sha256=_sha([source, edge_type, target, EVIDENCE]),
                    )
                )
            elif (
                existing.project_id != PROJECT_ID
                or existing.graph_kind != kind
                or existing.source_node_id != by_key[source].id
                or existing.target_node_id != by_key[target].id
                or existing.edge_type != edge_type
            ):
                raise RuntimeError(f"BAS-158 Graph edge identity drifted: {edge_id}")

    for kind, stable_key, _type, _label, _artifact, task_id in NODE_SPECS:
        service.bind_node_status(
            project_id=PROJECT_ID,
            node_id=_node_id(kind, stable_key),
            task_id=task_id,
        )

    monitor = Principal(
        actor_id="harness-seed",
        roles=frozenset({"admin"}),
        tenant_ref="default",
        store_refs=frozenset({STORE_REF}),
    )
    for task_id, _title, verifier, _dependencies, _workspace in TASK_SPECS:
        item = observed[verifier]
        with Session(engine) as session:
            task = session.get(GoalTaskRow, task_id)
            if task is None:
                raise RuntimeError(f"Graph task {task_id} disappeared")
            dependency_snapshot = []
            for dependency_id in task.dependency_ids_json:
                dependency_task = session.get(GoalTaskRow, dependency_id)
                if dependency_task is None:
                    raise RuntimeError(f"Graph dependency {dependency_id} is missing")
                dependency = _require_fresh_passed(
                    task=dependency_task,
                    observation=_latest_observation(session, dependency_id),
                    now=now,
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
                "verifier_id": f"bas158-{verifier}",
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
                        "verified_at": now.isoformat(),
                    }
                ),
                "artifact_ref": item["artifact_ref"],
                "evidence_ref": EVIDENCE,
                "observed_at": now.isoformat(),
                "store_ref": STORE_REF,
            },
            principal=monitor,
        )


def global_counts(engine: Engine) -> dict[str, int]:
    with Session(engine) as session:
        return {
            label: int(
                session.scalar(select(func.count()).select_from(model).where(model.project_id == PROJECT_ID)) or 0
            )
            for label, model in (
                ("tasks", GoalTaskRow),
                ("nodes", GraphNodeRow),
                ("edges", GraphEdgeRow),
                ("observations", HarnessObservationRow),
            )
        }


def verify_bas158_graph(engine: Engine) -> dict[str, Any]:
    now = datetime.now(UTC)
    task_specs = {item[0]: item for item in TASK_SPECS}
    expected_node_ids = {_node_id(kind, stable_key): (kind, stable_key) for kind, stable_key, *_ in NODE_SPECS}
    expected_edge_ids = {
        _edge_id(kind, source, edge_type, target): (
            kind,
            source,
            edge_type,
            target,
        )
        for source, edge_type, target, kind in EDGE_SPECS
    }
    with Session(engine) as session:
        tasks = {
            row.id: row
            for row in session.scalars(
                select(GoalTaskRow).where(
                    GoalTaskRow.project_id == PROJECT_ID,
                    GoalTaskRow.id.in_(list(task_specs)),
                )
            )
        }
        if set(tasks) != set(task_specs):
            raise RuntimeError("BAS-158 Graph task set is incomplete")
        for task_id, spec in task_specs.items():
            task = tasks[task_id]
            _id, title, verifier, dependencies, workspace = spec
            if (
                task.title != title
                or task.owner != OWNER
                or task.verifier_id != f"bas158-{verifier}"
                or task.verifier_version != "1"
                or task.dependency_ids_json != list(dependencies)
                or task.workspace != workspace
            ):
                raise RuntimeError(f"BAS-158 Graph task drifted: {task_id}")
            _require_fresh_passed(
                task=task,
                observation=_latest_observation(session, task_id),
                now=now,
            )

        nodes = {
            row.id: row
            for row in session.scalars(
                select(GraphNodeRow).where(
                    GraphNodeRow.project_id == PROJECT_ID,
                    GraphNodeRow.id.in_(list(expected_node_ids)),
                )
            )
        }
        if set(nodes) != set(expected_node_ids):
            raise RuntimeError("BAS-158 Graph node set is incomplete")
        for node_id, (kind, stable_key) in expected_node_ids.items():
            node = nodes[node_id]
            if node.graph_kind != kind or node.stable_key != stable_key:
                raise RuntimeError(f"BAS-158 Graph node drifted: {stable_key}")

        edges = {
            row.id: row
            for row in session.scalars(
                select(GraphEdgeRow).where(
                    GraphEdgeRow.project_id == PROJECT_ID,
                    GraphEdgeRow.id.in_(list(expected_edge_ids)),
                )
            )
        }
        if set(edges) != set(expected_edge_ids):
            raise RuntimeError("BAS-158 Graph edge set is incomplete")
        by_key = {node.stable_key: node for node in nodes.values()}
        for edge_id, (kind, source, edge_type, target) in expected_edge_ids.items():
            edge = edges[edge_id]
            if (
                edge.graph_kind != kind
                or edge.source_node_id != by_key[source].id
                or edge.target_node_id != by_key[target].id
                or edge.edge_type != edge_type
            ):
                raise RuntimeError(f"BAS-158 Graph edge drifted: {edge_id}")

    return {
        "global_counts": global_counts(engine),
        "bas158_counts": {
            "tasks": len(task_specs),
            "nodes": len(expected_node_ids),
            "edges": len(expected_edge_ids),
            "fresh_passed_observations": len(task_specs),
        },
    }


def main() -> None:
    artifacts = collect_required_artifacts()
    engine = create_database_engine()
    try:
        require_bas157_dependency(engine, now=datetime.now(UTC))
        observed = observations(artifacts)
        upsert_graph(engine, observed)
        graph_state = verify_bas158_graph(engine)
    finally:
        engine.dispose()
    print(
        json.dumps(
            {
                "project_id": PROJECT_ID,
                **graph_state,
                "business_state": "no_data",
                "authorized_channel_account_bound": False,
                "external_write_allowed": False,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
