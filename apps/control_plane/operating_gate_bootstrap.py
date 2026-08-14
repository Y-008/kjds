from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from .agent_harness import (
    AgentHarnessService,
    GoalTaskRow,
    GraphEdgeRow,
    GraphNodeRow,
    GraphProjectRow,
    OperatingSubjectBindingEventRow,
    _sha,
)
from .operating_gate_observer import (
    AUTHORITY_TASK_ID,
    AUTHORITY_VERIFIER_ID,
    AUTHORITY_VERIFIER_VERSION,
    PROJECT_ID,
    STORE_REF,
    SUBJECT_TASK_ID,
    SUBJECT_VERIFIER_ID,
    SUBJECT_VERIFIER_VERSION,
    TASK_IDS,
    VERIFIER_ID,
    VERIFIER_VERSION,
)
from .security import Principal

G1_DATABASE_NAME = "kjds_g1_smoke"
G1_ADMIN_ACTOR_ID = "g1-verifier"
G1_OPERATING_SUBJECT_ACTOR_ID = "g1-operating-subject"
BOOTSTRAP_VERSION = "1"
SUBJECT_IDEMPOTENCY_KEY = "g1-operating-subject-bootstrap-v1"


def require_g1_database(engine: Engine) -> str:
    """Fail closed unless the target is the migrated disposable G1 database."""

    if (
        engine.url.get_backend_name() != "postgresql"
        or engine.url.database != G1_DATABASE_NAME
    ):
        raise RuntimeError(
            "operating Gate bootstrap is restricted to the disposable "
            f"{G1_DATABASE_NAME} PostgreSQL database"
        )
    with engine.connect() as connection:
        revision = str(
            connection.execute(
                text("select version_num from alembic_version")
            ).scalar_one()
        )
    from .operating_gate_observer import OperatingGateObserverService

    if not OperatingGateObserverService._supports_database_revision(revision):
        raise RuntimeError(
            "operating Gate bootstrap requires migration sequence 0070 or later"
        )
    return revision


def bootstrap_operating_gate(
    *,
    engine: Engine,
    admin: Principal,
    operating_subject: Principal,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Create only the canonical graph needed for a real no-data Gate observation."""

    observed_at = _utc(now or datetime.now(UTC))
    _validate_principals(admin, operating_subject)
    scope = {"tenant_ref": admin.tenant_ref, "store_ref": STORE_REF}
    project_contract = {
        "id": PROJECT_ID,
        "tenant_ref": admin.tenant_ref,
        "entity_ref": None,
        "store_ref": STORE_REF,
        "title": "KJDS real operating Gate verification",
        "lifecycle": "active",
        "baseline_sha256": _sha(
            {
                "contract": "g1-operating-gate-bootstrap",
                "version": BOOTSTRAP_VERSION,
                "scope": scope,
            }
        ),
        "goal_contract_sha256": _sha(
            {
                "objective": "observe M0-M4 truth without external writes",
                "scope": scope,
            }
        ),
    }

    task_specs = _task_specs()
    node_specs = _node_specs(scope)
    edge_specs = _edge_specs()
    with Session(engine) as session, session.begin():
        project = session.get(GraphProjectRow, PROJECT_ID)
        if project is None:
            session.add(GraphProjectRow(**project_contract, created_at=observed_at))
        else:
            _assert_fields(project, project_contract, "graph project")

        for spec in task_specs:
            task = session.get(GoalTaskRow, spec["id"])
            if task is None:
                session.add(GoalTaskRow(**spec, created_at=observed_at))
                continue
            _assert_fields(
                task,
                {
                    "project_id": spec["project_id"],
                    "verifier_id": spec["verifier_id"],
                    "verifier_version": spec["verifier_version"],
                    "fingerprint": spec["fingerprint"],
                },
                f"Gate task {spec['id']}",
            )

        for spec in node_specs:
            node = session.get(GraphNodeRow, spec["id"])
            if node is None:
                session.add(GraphNodeRow(**spec, created_at=observed_at))
                continue
            _assert_fields(
                node,
                {
                    "project_id": spec["project_id"],
                    "graph_kind": spec["graph_kind"],
                    "stable_key": spec["stable_key"],
                    "node_type": spec["node_type"],
                    "authority": spec["authority"],
                },
                f"Gate node {spec['stable_key']}",
            )
            if spec["stable_key"].startswith("authority:"):
                _assert_fields(
                    node,
                    {"artifact_ref": spec["artifact_ref"]},
                    f"authority node {spec['stable_key']}",
                )

        session.flush()
        for spec in edge_specs:
            edge = session.get(GraphEdgeRow, spec["id"])
            if edge is None:
                session.add(
                    GraphEdgeRow(
                        **spec,
                        effective_from=observed_at,
                        effective_until=None,
                    )
                )
                continue
            _assert_fields(
                edge,
                {
                    key: spec[key]
                    for key in (
                        "project_id",
                        "graph_kind",
                        "source_node_id",
                        "target_node_id",
                        "edge_type",
                        "derivation_method",
                        "confidence",
                        "content_sha256",
                    )
                },
                f"Gate edge {spec['id']}",
            )

    binding = _ensure_subject_binding(
        engine=engine,
        admin=admin,
        operating_subject=operating_subject,
        observed_at=observed_at,
    )
    with Session(engine) as session:
        counts = {
            "projects": _count(session, GraphProjectRow),
            "tasks": _count(session, GoalTaskRow),
            "nodes": _count(session, GraphNodeRow),
            "edges": _count(session, GraphEdgeRow),
            "subject_binding_events": _count(
                session, OperatingSubjectBindingEventRow
            ),
        }
    return {
        "contract_id": "kjds-g1-operating-gate-bootstrap-v1",
        "project_id": PROJECT_ID,
        "operating_subject_actor_id": operating_subject.actor_id,
        "subject_binding_sha256": binding["authority_sha256"],
        "counts": counts,
        "external_write_allowed": False,
        "model_self_certification_allowed": False,
    }


def _task_specs() -> list[dict[str, Any]]:
    titles = (
        "M0 current authority and real candidate",
        "M1 formal Fact chain",
        "M2 content, profit and listing",
        "M3 governed Pilot, order and settlement",
        "M4 actual cash and learning",
    )
    specs: list[dict[str, Any]] = []
    for index, task_id in enumerate(TASK_IDS):
        specs.append(
            {
                "id": task_id,
                "project_id": PROJECT_ID,
                "title": titles[index],
                "owner": "operating-gate",
                "verifier_id": VERIFIER_ID,
                "verifier_version": VERIFIER_VERSION,
                "dependency_ids_json": (
                    [] if index == 0 else [TASK_IDS[index - 1]]
                ),
                "verification_condition": (
                    "fresh scoped Commerce OS and PostgreSQL observation"
                ),
                "next_safe_action": "run the bounded operating Gate observer",
                "workspace": "/commerce-os",
                "sla_seconds": None,
                "fingerprint": _sha([PROJECT_ID, task_id]),
            }
        )
    specs.extend(
        [
            {
                "id": SUBJECT_TASK_ID,
                "project_id": PROJECT_ID,
                "title": "M0 project operating subject binding",
                "owner": "project-admin+monitor",
                "verifier_id": SUBJECT_VERIFIER_ID,
                "verifier_version": SUBJECT_VERIFIER_VERSION,
                "dependency_ids_json": [],
                "verification_condition": (
                    "current append-only binding resolves one registered operator"
                ),
                "next_safe_action": "observe the bound operating subject",
                "workspace": "/authority-graph",
                "sla_seconds": 3600,
                "fingerprint": _sha([PROJECT_ID, SUBJECT_TASK_ID]),
            },
            {
                "id": AUTHORITY_TASK_ID,
                "project_id": PROJECT_ID,
                "title": "M0 current scope authority admission",
                "owner": "account-owner+compliance",
                "verifier_id": AUTHORITY_VERIFIER_ID,
                "verifier_version": AUTHORITY_VERIFIER_VERSION,
                "dependency_ids_json": [SUBJECT_TASK_ID],
                "verification_condition": (
                    "current bound-subject scope authority projection"
                ),
                "next_safe_action": "submit independently reviewed scope Evidence",
                "workspace": "/authority-graph",
                "sla_seconds": 3600,
                "fingerprint": _sha([PROJECT_ID, AUTHORITY_TASK_ID]),
            },
        ]
    )
    return specs


def _node_specs(scope: dict[str, str]) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for index in range(5):
        stable_key = f"gate-state:M{index}"
        source = f"g1-bootstrap:{PROJECT_ID}#m{index}"
        specs.append(
            {
                "id": f"g1-gate-node-m{index}",
                "project_id": PROJECT_ID,
                "graph_kind": "commerce",
                "stable_key": stable_key,
                "node_type": "gate_state",
                "label": f"M{index} awaiting runtime observation",
                "authority": "observed",
                "source": source,
                "scope_json": scope,
                "version": BOOTSTRAP_VERSION,
                "content_sha256": _sha(
                    {"stable_key": stable_key, "source": source, "scope": scope}
                ),
                "artifact_ref": source,
            }
        )
    subject_artifact = (
        f"/v1/agent-control/projects/{PROJECT_ID}/operating-subject"
    )
    specs.extend(
        [
            {
                "id": "g1-authority-node-operating-subject",
                "project_id": PROJECT_ID,
                "graph_kind": "authority",
                "stable_key": "authority:operating-subject-binding",
                "node_type": "authority",
                "label": "Append-only project operating subject binding",
                "authority": "canonical",
                "source": subject_artifact,
                "scope_json": scope,
                "version": BOOTSTRAP_VERSION,
                "content_sha256": _sha(
                    {"artifact_ref": subject_artifact, "scope": scope}
                ),
                "artifact_ref": subject_artifact,
            },
            {
                "id": "g1-authority-node-current-scope",
                "project_id": PROJECT_ID,
                "graph_kind": "authority",
                "stable_key": "authority:current-scope-grant",
                "node_type": "authority",
                "label": "Current tenant, entity and store scope authority",
                "authority": "canonical",
                "source": "/v1/scope-grants/current",
                "scope_json": scope,
                "version": BOOTSTRAP_VERSION,
                "content_sha256": _sha(
                    {"artifact_ref": "/v1/scope-grants/current", "scope": scope}
                ),
                "artifact_ref": "/v1/scope-grants/current",
            },
        ]
    )
    return specs


def _edge_specs() -> list[dict[str, Any]]:
    relationships = [
        (
            "g1-authority-node-operating-subject",
            "g1-authority-node-current-scope",
            "precedes",
        ),
        ("g1-authority-node-current-scope", "g1-gate-node-m0", "blocks"),
        *[
            (f"g1-gate-node-m{index}", f"g1-gate-node-m{index + 1}", "precedes")
            for index in range(4)
        ],
    ]
    return [
        {
            "id": f"g1-gate-edge-{index}",
            "project_id": PROJECT_ID,
            "graph_kind": "commerce",
            "source_node_id": source,
            "target_node_id": target,
            "edge_type": edge_type,
            "derivation_method": "declared",
            "confidence": 100,
            "evidence_ref": None,
            "content_sha256": _sha(
                {
                    "project_id": PROJECT_ID,
                    "source": source,
                    "target": target,
                    "edge_type": edge_type,
                }
            ),
        }
        for index, (source, target, edge_type) in enumerate(relationships)
    ]


def _ensure_subject_binding(
    *,
    engine: Engine,
    admin: Principal,
    operating_subject: Principal,
    observed_at: datetime,
) -> dict[str, Any]:
    harness = AgentHarnessService(engine)
    with Session(engine) as session:
        events = list(
            session.scalars(
                select(OperatingSubjectBindingEventRow)
                .where(
                    OperatingSubjectBindingEventRow.project_id == PROJECT_ID
                )
                .order_by(OperatingSubjectBindingEventRow.sequence)
            )
        )
    if not events:
        harness.record_operating_subject_event(
            project_id=PROJECT_ID,
            principal=admin,
            subject=operating_subject,
            event_type="bind",
            effective_at=observed_at - timedelta(seconds=1),
            reason="bind the disposable G1 operating observer subject",
            idempotency_key=SUBJECT_IDEMPOTENCY_KEY,
        )
    elif (
        len(events) != 1
        or events[0].event_type != "bind"
        or events[0].subject_actor_id != operating_subject.actor_id
        or events[0].idempotency_key != SUBJECT_IDEMPOTENCY_KEY
    ):
        raise RuntimeError("disposable G1 operating-subject binding drifted")
    binding = harness.operating_subject(
        project_id=PROJECT_ID,
        principal=admin,
        as_of=observed_at,
    )
    if (
        binding["status"] != "ready"
        or binding["subject_actor_id"] != operating_subject.actor_id
    ):
        raise RuntimeError("disposable G1 operating subject is not ready")
    return binding


def _validate_principals(admin: Principal, subject: Principal) -> None:
    if not admin.has_any_role("admin"):
        raise PermissionError("G1 bootstrap recorder requires the admin role")
    if (
        subject.actor_id == admin.actor_id
        or not subject.has_any_role("operator")
        or subject.has_any_role("admin", "monitor")
    ):
        raise PermissionError(
            "G1 operating subject must be a separate non-admin operator"
        )
    if (
        admin.tenant_ref != subject.tenant_ref
        or not admin.can_access_store(STORE_REF)
        or not subject.can_access_store(STORE_REF)
    ):
        raise PermissionError("G1 principals must share the exact project scope")


def _assert_fields(row: Any, expected: dict[str, Any], label: str) -> None:
    drift = [
        key for key, value in expected.items() if getattr(row, key) != value
    ]
    if drift:
        raise RuntimeError(f"{label} drifted: {', '.join(sorted(drift))}")


def _count(session: Session, model: type[Any]) -> int:
    scope_column = (
        model.id if model is GraphProjectRow else model.project_id
    )
    return int(
        session.scalar(
            select(func.count())
            .select_from(model)
            .where(scope_column == PROJECT_ID)
        )
        or 0
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("bootstrap timestamp must include a timezone")
    return value.astimezone(UTC)
