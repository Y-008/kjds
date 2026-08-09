from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    or_,
    select,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from .security import Principal
from .sql_repository import Base

GRAPH_KINDS = frozenset(
    {
        "project",
        "requirements",
        "engineering",
        "runtime",
        "evidence",
        "commerce",
        "authority",
    }
)
OBSERVATION_STATES = frozenset(
    {"pending", "running", "blocked", "passed", "failed", "stale", "no_data"}
)
DERIVATION_METHODS = frozenset(
    {"declared", "parsed", "runtime", "evidence", "inferred"}
)


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class GraphProjectRow(Base):
    __tablename__ = "graph_projects"
    id: Mapped[str] = mapped_column(String(180), primary_key=True)
    tenant_ref: Mapped[str] = mapped_column(String(160), index=True)
    entity_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    store_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    title: Mapped[str] = mapped_column(String(240))
    lifecycle: Mapped[str] = mapped_column(String(40))
    baseline_sha256: Mapped[str] = mapped_column(String(64))
    goal_contract_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class VerifierRegistryRow(Base):
    __tablename__ = "verifier_registry"
    id: Mapped[str] = mapped_column(String(180), primary_key=True)
    version: Mapped[str] = mapped_column(String(80), primary_key=True)
    source_type: Mapped[str] = mapped_column(String(80))
    authority: Mapped[str] = mapped_column(String(80))
    success_states_json: Mapped[list[str]] = mapped_column(JSON)
    freshness_seconds: Mapped[int] = mapped_column(Integer)
    contract_sha256: Mapped[str] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GoalContractRow(Base):
    __tablename__ = "goal_contracts"
    id: Mapped[str] = mapped_column(String(180), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("graph_projects.id"))
    objective: Mapped[str] = mapped_column(Text)
    constraints_json: Mapped[list[str]] = mapped_column(JSON)
    content_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OperatingSubjectBindingEventRow(Base):
    __tablename__ = "graph_project_subject_binding_events"
    __table_args__ = (
        CheckConstraint(
            "event_type in ('bind', 'revoke')",
            name="ck_graph_project_subject_binding_event_type",
        ),
        UniqueConstraint(
            "project_id",
            "idempotency_key",
            name="uq_graph_project_subject_binding_idempotency",
        ),
    )
    sequence: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    id: Mapped[str] = mapped_column(String(180), unique=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("graph_projects.id"), index=True
    )
    tenant_ref: Mapped[str] = mapped_column(String(160))
    store_ref: Mapped[str] = mapped_column(String(160))
    subject_actor_id: Mapped[str] = mapped_column(String(160))
    event_type: Mapped[str] = mapped_column(String(20))
    effective_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True
    )
    reason: Mapped[str] = mapped_column(Text)
    recorded_by: Mapped[str] = mapped_column(String(160))
    idempotency_key: Mapped[str] = mapped_column(String(300))
    request_sha256: Mapped[str] = mapped_column(String(64))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GoalTaskRow(Base):
    __tablename__ = "goal_tasks"
    __table_args__ = (
        UniqueConstraint("project_id", "fingerprint", name="uq_goal_task_fingerprint"),
    )
    id: Mapped[str] = mapped_column(String(180), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("graph_projects.id"))
    title: Mapped[str] = mapped_column(String(300))
    owner: Mapped[str] = mapped_column(String(160))
    verifier_id: Mapped[str] = mapped_column(String(180))
    verifier_version: Mapped[str] = mapped_column(String(80))
    dependency_ids_json: Mapped[list[str]] = mapped_column(JSON)
    verification_condition: Mapped[str] = mapped_column(Text)
    next_safe_action: Mapped[str] = mapped_column(Text)
    workspace: Mapped[str] = mapped_column(String(180))
    sla_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class HarnessObservationRow(Base):
    __tablename__ = "harness_observations"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "verifier_id",
            "verifier_version",
            "input_sha256",
            "result_sha256",
            name="uq_harness_observation_replay",
        ),
    )
    id: Mapped[str] = mapped_column(String(180), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("graph_projects.id"), index=True)
    task_id: Mapped[str | None] = mapped_column(
        ForeignKey("goal_tasks.id"), nullable=True, index=True
    )
    verifier_id: Mapped[str] = mapped_column(String(180))
    verifier_version: Mapped[str] = mapped_column(String(80))
    source: Mapped[str] = mapped_column(String(240))
    scope_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(40))
    summary: Mapped[str] = mapped_column(Text)
    input_sha256: Mapped[str] = mapped_column(String(64))
    result_sha256: Mapped[str] = mapped_column(String(64))
    authority: Mapped[str] = mapped_column(String(80))
    artifact_ref: Mapped[str] = mapped_column(String(500))
    evidence_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    fresh_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    recorded_by: Mapped[str] = mapped_column(String(160))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GraphNodeRow(Base):
    __tablename__ = "graph_nodes"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "graph_kind", "stable_key", name="uq_graph_node_stable_key"
        ),
    )
    id: Mapped[str] = mapped_column(String(180), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("graph_projects.id"), index=True)
    graph_kind: Mapped[str] = mapped_column(String(40), index=True)
    stable_key: Mapped[str] = mapped_column(String(300))
    node_type: Mapped[str] = mapped_column(String(80))
    label: Mapped[str] = mapped_column(String(300))
    authority: Mapped[str] = mapped_column(String(80))
    source: Mapped[str] = mapped_column(String(300))
    scope_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    version: Mapped[str] = mapped_column(String(80))
    content_sha256: Mapped[str] = mapped_column(String(64))
    artifact_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GraphEdgeRow(Base):
    __tablename__ = "graph_edges"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "graph_kind",
            "source_node_id",
            "edge_type",
            "target_node_id",
            name="uq_graph_edge_stable",
        ),
    )
    id: Mapped[str] = mapped_column(String(180), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("graph_projects.id"), index=True)
    graph_kind: Mapped[str] = mapped_column(String(40), index=True)
    source_node_id: Mapped[str] = mapped_column(ForeignKey("graph_nodes.id"))
    target_node_id: Mapped[str] = mapped_column(ForeignKey("graph_nodes.id"))
    edge_type: Mapped[str] = mapped_column(String(100))
    derivation_method: Mapped[str] = mapped_column(String(40))
    confidence: Mapped[int] = mapped_column(Integer)
    evidence_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    effective_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    content_sha256: Mapped[str] = mapped_column(String(64))


class GraphNodeStatusBindingRow(Base):
    __tablename__ = "graph_node_status_bindings"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "node_id",
            "binding_role",
            name="uq_graph_node_status_binding",
        ),
    )
    id: Mapped[str] = mapped_column(String(180), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("graph_projects.id"), index=True
    )
    node_id: Mapped[str] = mapped_column(ForeignKey("graph_nodes.id"), index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("goal_tasks.id"), index=True)
    binding_role: Mapped[str] = mapped_column(String(40))
    content_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AgentHarnessService:
    CONTRACT_ID = "kjds-agent-harness-graph-v1"
    CAMPAIGN_BRIEF_CONTRACT_ID = "kjds-campaign-brief-v1"
    CAMPAIGN_BRIEF_CONTRACT_VERSION = "1.0.0"
    OPERATING_SUBJECT_CONTRACT_ID = (
        "kjds-graph-project-operating-subject-events-v1"
    )

    def __init__(self, engine):
        self.engine = engine

    @staticmethod
    def _authorize(project: GraphProjectRow, principal: Principal, store_ref: str | None):
        if project.tenant_ref != principal.tenant_ref:
            raise PermissionError("project tenant is outside authorized scope")
        if store_ref and store_ref not in principal.store_refs:
            raise PermissionError("store is outside authorized scope")
        if project.store_ref and store_ref != project.store_ref:
            raise PermissionError("project store is outside authorized scope")

    def register_verifier(self, contract: dict[str, Any]) -> dict[str, Any]:
        required = {
            "id",
            "version",
            "source_type",
            "authority",
            "success_states",
            "freshness_seconds",
        }
        if set(contract) != required:
            raise ValueError("verifier contract fields do not match")
        success = sorted(set(contract["success_states"]))
        if not success or not set(success) <= OBSERVATION_STATES:
            raise ValueError("invalid verifier success states")
        if int(contract["freshness_seconds"]) <= 0:
            raise ValueError("freshness_seconds must be positive")
        digest = _sha(contract)
        now = datetime.now(UTC)
        with Session(self.engine) as session, session.begin():
            row = session.get(
                VerifierRegistryRow,
                {"id": contract["id"], "version": contract["version"]},
            )
            if row:
                if row.contract_sha256 != digest:
                    raise ValueError("verifier version contract changed")
            else:
                row = VerifierRegistryRow(
                    id=contract["id"],
                    version=contract["version"],
                    source_type=contract["source_type"],
                    authority=contract["authority"],
                    success_states_json=success,
                    freshness_seconds=int(contract["freshness_seconds"]),
                    contract_sha256=digest,
                    enabled=True,
                    created_at=now,
                )
                session.add(row)
        return {"id": contract["id"], "version": contract["version"], "sha256": digest}

    def record_operating_subject_event(
        self,
        *,
        project_id: str,
        principal: Principal,
        subject: Principal,
        event_type: str,
        effective_at: str | datetime,
        reason: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Append a project operating-subject bind/revoke event."""

        if not principal.has_any_role("admin"):
            raise PermissionError(
                "admin role required for project operating-subject binding"
            )
        if event_type not in {"bind", "revoke"}:
            raise ValueError("event_type must be bind or revoke")
        cutoff = self._binding_timestamp(effective_at)
        if cutoff > datetime.now(UTC):
            raise ValueError("effective_at cannot be in the future")
        reason = reason.strip()
        idempotency_key = idempotency_key.strip()
        if not reason:
            raise ValueError("operating-subject event requires a reason")
        if not idempotency_key:
            raise ValueError(
                "operating-subject event requires an idempotency key"
            )
        if principal.actor_id == subject.actor_id:
            raise ValueError(
                "project operating subject must differ from the recorder"
            )
        if not subject.has_any_role("operator") or subject.has_any_role(
            "admin", "monitor"
        ):
            raise ValueError(
                "project operating subject must be a non-admin, non-monitor "
                "operator"
            )

        with Session(self.engine) as session, session.begin():
            project = session.get(
                GraphProjectRow,
                project_id,
                with_for_update=True,
            )
            if project is None:
                raise KeyError("graph project not found")
            self._authorize(project, principal, project.store_ref)
            if (
                subject.tenant_ref != project.tenant_ref
                or project.store_ref is None
                or not subject.can_access_store(project.store_ref)
            ):
                raise PermissionError(
                    "operating subject is outside project tenant/store scope"
                )
            request = {
                "contract_id": self.OPERATING_SUBJECT_CONTRACT_ID,
                "project_id": project.id,
                "tenant_ref": project.tenant_ref,
                "store_ref": project.store_ref,
                "subject_actor_id": subject.actor_id,
                "event_type": event_type,
                "effective_at": cutoff.isoformat(),
                "reason": reason,
                "recorded_by": principal.actor_id,
                "idempotency_key": idempotency_key,
            }
            request_sha256 = _sha(request)
            existing = session.scalar(
                select(OperatingSubjectBindingEventRow).where(
                    OperatingSubjectBindingEventRow.project_id == project.id,
                    OperatingSubjectBindingEventRow.idempotency_key
                    == idempotency_key,
                )
            )
            if existing is not None:
                if existing.request_sha256 != request_sha256:
                    raise ValueError(
                        "operating-subject idempotency key conflicts with "
                        "immutable event"
                    )
                return self._project_subject_event(existing, idempotent=True)

            latest = session.scalar(
                select(OperatingSubjectBindingEventRow)
                .where(
                    OperatingSubjectBindingEventRow.project_id == project.id
                )
                .order_by(
                    OperatingSubjectBindingEventRow.effective_at.desc(),
                    OperatingSubjectBindingEventRow.sequence.desc(),
                )
                .limit(1)
            )
            if latest is not None and _utc(latest.effective_at) > cutoff:
                raise ValueError(
                    "operating-subject event cannot precede the latest event"
                )
            current = self._current_subject_event(
                session,
                project_id=project.id,
                as_of=cutoff,
            )
            if event_type == "bind" and current is not None:
                raise ValueError(
                    "revoke the current operating subject before rebinding"
                )
            if event_type == "revoke" and (
                current is None
                or current.subject_actor_id != subject.actor_id
            ):
                raise ValueError(
                    "revoke must match the current operating subject"
                )

            event_id = f"gosb_{request_sha256[:32]}"
            row = OperatingSubjectBindingEventRow(
                id=event_id,
                project_id=project.id,
                tenant_ref=project.tenant_ref,
                store_ref=project.store_ref,
                subject_actor_id=subject.actor_id,
                event_type=event_type,
                effective_at=cutoff,
                reason=reason,
                recorded_by=principal.actor_id,
                idempotency_key=idempotency_key,
                request_sha256=request_sha256,
                recorded_at=datetime.now(UTC),
            )
            session.add(row)
            session.flush()
            return self._project_subject_event(row, idempotent=False)

    def operating_subject(
        self,
        *,
        project_id: str,
        principal: Principal,
        as_of: datetime,
    ) -> dict[str, Any]:
        """Resolve the one append-only operating subject for a project."""

        if not principal.has_any_role("monitor", "admin"):
            raise PermissionError(
                "monitor or admin role required for operating-subject projection"
            )
        cutoff = self._binding_timestamp(as_of)
        with Session(self.engine) as session:
            project = session.get(GraphProjectRow, project_id)
            if project is None:
                raise KeyError("graph project not found")
            self._authorize(project, principal, project.store_ref)
            rows = list(
                session.scalars(
                    select(OperatingSubjectBindingEventRow)
                    .where(
                        OperatingSubjectBindingEventRow.project_id
                        == project.id,
                        OperatingSubjectBindingEventRow.effective_at
                        <= cutoff,
                    )
                    .order_by(
                        OperatingSubjectBindingEventRow.effective_at,
                        OperatingSubjectBindingEventRow.sequence,
                    )
                )
            )
        authority_sha256 = (
            _sha(
                [
                    {
                        "id": row.id,
                        "request_sha256": row.request_sha256,
                        "event_type": row.event_type,
                        "effective_at": _utc(
                            row.effective_at
                        ).isoformat(),
                    }
                    for row in rows
                ]
            )
            if rows
            else None
        )
        if not rows or rows[-1].event_type == "revoke":
            return {
                "contract_id": self.OPERATING_SUBJECT_CONTRACT_ID,
                "status": "no_data",
                "project_id": project_id,
                "subject_actor_id": None,
                "authority_sha256": authority_sha256,
                "reason": "operating_subject_binding_missing",
                "as_of": cutoff.isoformat(),
                "external_write_allowed": False,
            }
        row = rows[-1]
        return {
            "contract_id": self.OPERATING_SUBJECT_CONTRACT_ID,
            "status": "ready",
            "project_id": project_id,
            "tenant_ref": row.tenant_ref,
            "store_ref": row.store_ref,
            "subject_actor_id": row.subject_actor_id,
            "event_id": row.id,
            "effective_at": _utc(row.effective_at).isoformat(),
            "authority_sha256": authority_sha256,
            "as_of": cutoff.isoformat(),
            "external_write_allowed": False,
        }

    @staticmethod
    def _binding_timestamp(value: str | datetime) -> datetime:
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(
                    value.replace("Z", "+00:00")
                )
            except ValueError as exc:
                raise ValueError(
                    "effective_at must be an ISO-8601 timestamp"
                ) from exc
        else:
            parsed = value
        if parsed.tzinfo is None:
            raise ValueError("effective_at must include timezone")
        return parsed.astimezone(UTC)

    @staticmethod
    def _current_subject_event(
        session: Session,
        *,
        project_id: str,
        as_of: datetime,
    ) -> OperatingSubjectBindingEventRow | None:
        row = session.scalar(
            select(OperatingSubjectBindingEventRow)
            .where(
                OperatingSubjectBindingEventRow.project_id == project_id,
                OperatingSubjectBindingEventRow.effective_at <= as_of,
            )
            .order_by(
                OperatingSubjectBindingEventRow.effective_at.desc(),
                OperatingSubjectBindingEventRow.sequence.desc(),
            )
            .limit(1)
        )
        return row if row is not None and row.event_type == "bind" else None

    @staticmethod
    def _project_subject_event(
        row: OperatingSubjectBindingEventRow,
        *,
        idempotent: bool,
    ) -> dict[str, Any]:
        return {
            "contract_id": (
                AgentHarnessService.OPERATING_SUBJECT_CONTRACT_ID
            ),
            "id": row.id,
            "project_id": row.project_id,
            "tenant_ref": row.tenant_ref,
            "store_ref": row.store_ref,
            "subject_actor_id": row.subject_actor_id,
            "event_type": row.event_type,
            "effective_at": _utc(row.effective_at).isoformat(),
            "reason": row.reason,
            "recorded_by": row.recorded_by,
            "idempotency_key": row.idempotency_key,
            "request_sha256": row.request_sha256,
            "recorded_at": _utc(row.recorded_at).isoformat(),
            "idempotent": idempotent,
            "external_write_allowed": False,
        }

    def record_observation(
        self,
        payload: dict[str, Any],
        *,
        principal: Principal,
    ) -> dict[str, Any]:
        if not principal.roles.intersection({"admin", "monitor"}):
            raise PermissionError("monitor or admin role required")
        state = str(payload["state"])
        if state not in OBSERVATION_STATES - {"stale"}:
            raise ValueError("invalid observed state")
        observed_at = datetime.fromisoformat(str(payload["observed_at"]).replace("Z", "+00:00"))
        if observed_at.tzinfo is None:
            raise ValueError("observed_at must include timezone")
        with Session(self.engine) as session, session.begin():
            project = session.get(GraphProjectRow, payload["project_id"])
            if not project:
                raise KeyError("graph project not found")
            self._authorize(project, principal, payload.get("store_ref"))
            verifier = session.get(
                VerifierRegistryRow,
                {
                    "id": payload["verifier_id"],
                    "version": payload["verifier_version"],
                },
            )
            if not verifier or not verifier.enabled:
                raise ValueError("registered verifier required")
            task = session.get(GoalTaskRow, payload.get("task_id")) if payload.get("task_id") else None
            if task and (
                task.project_id != project.id
                or task.verifier_id != verifier.id
                or task.verifier_version != verifier.version
            ):
                raise ValueError("task verifier binding mismatch")
            result_sha = _sha(
                {
                    "state": state,
                    "summary": payload["summary"],
                    "artifact_ref": payload["artifact_ref"],
                    "evidence_ref": payload.get("evidence_ref"),
                }
            )
            obs_id = f"obs_{_sha([project.id, verifier.id, verifier.version, payload['input_sha256'], result_sha])[:32]}"
            row = session.get(HarnessObservationRow, obs_id)
            if not row:
                row = HarnessObservationRow(
                    id=obs_id,
                    project_id=project.id,
                    task_id=task.id if task else None,
                    verifier_id=verifier.id,
                    verifier_version=verifier.version,
                    source=payload["source"],
                    scope_json=payload["scope"],
                    state=state,
                    summary=payload["summary"],
                    input_sha256=payload["input_sha256"],
                    result_sha256=result_sha,
                    authority=verifier.authority,
                    artifact_ref=payload["artifact_ref"],
                    evidence_ref=payload.get("evidence_ref"),
                    observed_at=observed_at.astimezone(UTC),
                    fresh_until=observed_at.astimezone(UTC)
                    + timedelta(seconds=verifier.freshness_seconds),
                    recorded_by=principal.actor_id,
                    recorded_at=datetime.now(UTC),
                )
                session.add(row)
        return {"id": obs_id, "state": state, "result_sha256": result_sha}

    def bind_node_status(
        self,
        *,
        project_id: str,
        node_id: str,
        task_id: str,
        binding_role: str = "status_source",
    ) -> dict[str, str]:
        if binding_role != "status_source":
            raise ValueError("unsupported Graph node status binding role")
        content = {
            "project_id": project_id,
            "node_id": node_id,
            "task_id": task_id,
            "binding_role": binding_role,
        }
        digest = _sha(content)
        binding_id = f"gnsb_{digest[:32]}"
        with Session(self.engine) as session, session.begin():
            project = session.get(GraphProjectRow, project_id)
            node = session.get(GraphNodeRow, node_id)
            task = session.get(GoalTaskRow, task_id)
            if project is None:
                raise KeyError("graph project not found")
            if node is None or node.project_id != project_id:
                raise KeyError("Graph node is outside project")
            if task is None or task.project_id != project_id:
                raise KeyError("Goal task is outside project")
            existing = session.scalar(
                select(GraphNodeStatusBindingRow).where(
                    GraphNodeStatusBindingRow.project_id == project_id,
                    GraphNodeStatusBindingRow.node_id == node_id,
                    GraphNodeStatusBindingRow.binding_role == binding_role,
                )
            )
            if existing:
                if (
                    existing.task_id != task_id
                    or existing.content_sha256 != digest
                ):
                    raise ValueError(
                        "Graph node status binding changed; create a new node version"
                    )
                return {"id": existing.id, "content_sha256": digest}
            session.add(
                GraphNodeStatusBindingRow(
                    id=binding_id,
                    project_id=project_id,
                    node_id=node_id,
                    task_id=task_id,
                    binding_role=binding_role,
                    content_sha256=digest,
                    created_at=datetime.now(UTC),
                )
            )
        return {"id": binding_id, "content_sha256": digest}

    def workspace(
        self,
        project_id: str,
        *,
        principal: Principal,
        store_ref: str | None,
        as_of: datetime,
        graph_kind: str | None = None,
    ) -> dict[str, Any]:
        if graph_kind and graph_kind not in GRAPH_KINDS:
            raise ValueError("unknown graph kind")
        with Session(self.engine) as session:
            project = session.get(GraphProjectRow, project_id)
            if not project:
                raise KeyError("graph project not found")
            self._authorize(project, principal, store_ref)
            tasks = session.scalars(
                select(GoalTaskRow)
                .where(GoalTaskRow.project_id == project.id)
                .order_by(GoalTaskRow.id)
            ).all()
            observations = session.scalars(
                select(HarnessObservationRow)
                .where(
                    HarnessObservationRow.project_id == project.id,
                    HarnessObservationRow.observed_at <= as_of,
                )
                .order_by(
                    HarnessObservationRow.task_id,
                    HarnessObservationRow.observed_at.desc(),
                    HarnessObservationRow.id.desc(),
                )
            ).all()
            latest: dict[str, HarnessObservationRow] = {}
            for observation in observations:
                key = observation.task_id or f"verifier:{observation.verifier_id}"
                latest.setdefault(key, observation)
            edges_query = select(GraphEdgeRow).where(
                GraphEdgeRow.project_id == project.id,
                GraphEdgeRow.effective_from <= as_of,
                or_(
                    GraphEdgeRow.effective_until.is_(None),
                    GraphEdgeRow.effective_until > as_of,
                ),
            )
            if graph_kind:
                edges_query = edges_query.where(GraphEdgeRow.graph_kind == graph_kind)
            edges = session.scalars(edges_query.order_by(GraphEdgeRow.id)).all()
            nodes_query = select(GraphNodeRow).where(
                GraphNodeRow.project_id == project.id,
                GraphNodeRow.created_at <= as_of,
            )
            if graph_kind:
                connected_ids = {
                    node_id
                    for edge in edges
                    for node_id in (edge.source_node_id, edge.target_node_id)
                }
                nodes_query = nodes_query.where(
                    or_(
                        GraphNodeRow.graph_kind == graph_kind,
                        GraphNodeRow.id.in_(connected_ids),
                    )
                )
            nodes = session.scalars(nodes_query.order_by(GraphNodeRow.id)).all()
            verifier_keys = {(t.verifier_id, t.verifier_version) for t in tasks}
            verifiers = {
                (v.id, v.version): v
                for v in session.scalars(select(VerifierRegistryRow)).all()
                if (v.id, v.version) in verifier_keys
            }
            task_items = []
            for task in tasks:
                observation = latest.get(task.id)
                state = "pending"
                freshness = "no_data"
                blockers = []
                if observation:
                    freshness = (
                        "fresh" if _utc(observation.fresh_until) >= _utc(as_of) else "stale"
                    )
                    state = observation.state if freshness == "fresh" else "stale"
                    if state == "stale":
                        blockers.append("verifier_observation_stale")
                    elif state in {"blocked", "failed", "no_data"}:
                        blockers.append(f"verifier_state:{state}")
                    verifier = verifiers.get((task.verifier_id, task.verifier_version))
                    if (
                        state == "passed"
                        and verifier
                        and observation.state not in verifier.success_states_json
                    ):
                        state = "failed"
                        blockers.append("verifier_success_contract_mismatch")
                else:
                    blockers.append("verifier_observation_missing")
                task_items.append(
                    {
                        "id": task.id,
                        "title": task.title,
                        "owner": task.owner,
                        "sla_seconds": task.sla_seconds,
                        "dependencies": task.dependency_ids_json,
                        "verification_condition": task.verification_condition,
                        "verifier": {
                            "id": task.verifier_id,
                            "version": task.verifier_version,
                        },
                        "state": state,
                        "freshness": freshness,
                        "blockers": blockers,
                        "next_safe_action": task.next_safe_action,
                        "workspace": task.workspace,
                        "observation_id": observation.id if observation else None,
                        "artifact_ref": observation.artifact_ref if observation else None,
                        "evidence_ref": observation.evidence_ref if observation else None,
                    }
                )
            task_by_id = {item["id"]: item for item in task_items}
            observations_by_task = {
                task.id: latest.get(task.id)
                for task in tasks
            }
            for _ in range(len(task_items)):
                changed_state = False
                for item in task_items:
                    observation = observations_by_task[item["id"]]
                    for dependency_id in item["dependencies"]:
                        dependency = task_by_id.get(dependency_id)
                        if dependency is None:
                            blocker = f"upstream_task_missing:{dependency_id}"
                            if blocker not in item["blockers"]:
                                item["blockers"].append(blocker)
                            if item["state"] == "passed":
                                item["state"] = "stale"
                                changed_state = True
                            continue
                        if dependency["state"] != "passed":
                            blocker = (
                                f"upstream_not_passed:{dependency_id}:"
                                f"{dependency['state']}"
                            )
                            if blocker not in item["blockers"]:
                                item["blockers"].append(blocker)
                            if item["state"] == "passed":
                                item["state"] = "stale"
                                changed_state = True
                            continue
                        dependency_observation = observations_by_task[dependency_id]
                        if (
                            observation
                            and dependency_observation
                            and _utc(dependency_observation.observed_at)
                            > _utc(observation.observed_at)
                        ):
                            blocker = f"upstream_changed:{dependency_id}"
                            if blocker not in item["blockers"]:
                                item["blockers"].append(blocker)
                            if item["state"] == "passed":
                                item["state"] = "stale"
                                changed_state = True
                if not changed_state:
                    break
            node_ids = {node.id for node in nodes}
            bindings = {
                row.node_id: row
                for row in session.scalars(
                    select(GraphNodeStatusBindingRow).where(
                        GraphNodeStatusBindingRow.project_id == project.id,
                        GraphNodeStatusBindingRow.node_id.in_(node_ids),
                        GraphNodeStatusBindingRow.binding_role
                        == "status_source",
                    )
                ).all()
            }
            node_items = []
            for node in nodes:
                binding = bindings.get(node.id)
                task_item = (
                    task_by_id.get(binding.task_id)
                    if binding is not None
                    else None
                )
                observation = (
                    observations_by_task.get(binding.task_id)
                    if binding is not None
                    else None
                )
                verification = None
                if binding is not None:
                    if task_item is None:
                        verification = {
                            "state": "failed",
                            "freshness": "no_data",
                            "why": "bound Goal task is missing",
                            "blockers": [
                                f"bound_task_missing:{binding.task_id}"
                            ],
                            "owner": None,
                            "sla_seconds": None,
                            "dependencies": [],
                            "verifier": None,
                            "observation_id": None,
                            "artifact_ref": None,
                            "evidence_ref": None,
                            "next_safe_action": (
                                "repair the immutable node status binding"
                            ),
                            "workspace": "/project-graph",
                            "binding_sha256": binding.content_sha256,
                        }
                    else:
                        verification = {
                            "state": task_item["state"],
                            "freshness": task_item["freshness"],
                            "why": (
                                observation.summary
                                if observation is not None
                                else "registered verifier observation missing"
                            ),
                            "blockers": list(task_item["blockers"]),
                            "owner": task_item["owner"],
                            "sla_seconds": task_item["sla_seconds"],
                            "dependencies": list(
                                task_item["dependencies"]
                            ),
                            "verifier": dict(task_item["verifier"]),
                            "observation_id": task_item["observation_id"],
                            "artifact_ref": task_item["artifact_ref"],
                            "evidence_ref": task_item["evidence_ref"],
                            "next_safe_action": task_item[
                                "next_safe_action"
                            ],
                            "workspace": task_item["workspace"],
                            "binding_sha256": binding.content_sha256,
                        }
                node_items.append(
                    {
                        "id": node.id,
                        "kind": node.graph_kind,
                        "stable_key": node.stable_key,
                        "type": node.node_type,
                        "label": node.label,
                        "authority": node.authority,
                        "source": node.source,
                        "version": node.version,
                        "content_sha256": node.content_sha256,
                        "artifact_ref": node.artifact_ref,
                        "verification": verification,
                    }
                )
            edge_items = [
                {
                    "id": e.id,
                    "kind": e.graph_kind,
                    "source": e.source_node_id,
                    "target": e.target_node_id,
                    "type": e.edge_type,
                    "derivation": e.derivation_method,
                    "confidence": e.confidence,
                    "evidence_ref": e.evidence_ref,
                    "can_satisfy_gate": e.derivation_method != "inferred",
                    "effective_from": _utc(e.effective_from).isoformat(),
                    "effective_until": (
                        _utc(e.effective_until).isoformat()
                        if e.effective_until is not None
                        else None
                    ),
                    "content_sha256": e.content_sha256,
                }
                for e in edges
            ]
        counts = {
            state: sum(1 for item in task_items if item["state"] == state)
            for state in OBSERVATION_STATES
        }
        changed = [
            item
            for item in task_items
            if item["state"] in {"failed", "blocked", "stale", "pending", "no_data"}
        ]
        if not task_items:
            workspace_status = "no_data"
        elif counts["failed"]:
            workspace_status = "failed"
        elif counts["blocked"]:
            workspace_status = "blocked"
        elif counts["stale"]:
            workspace_status = "stale"
        elif counts["pending"] or counts["running"]:
            workspace_status = "pending"
        elif counts["no_data"]:
            workspace_status = "no_data"
        else:
            workspace_status = "ready"
        snapshot = {
            "contract_id": self.CONTRACT_ID,
            "project": {
                "id": project.id,
                "title": project.title,
                "lifecycle": project.lifecycle,
                "baseline_sha256": project.baseline_sha256,
                "goal_contract_sha256": project.goal_contract_sha256,
            },
            "scope": {
                "tenant_ref": project.tenant_ref,
                "entity_ref": project.entity_ref,
                "store_ref": project.store_ref,
            },
            "as_of": as_of.astimezone(UTC).isoformat(),
            "status": workspace_status,
            "counts": {
                "tasks": len(task_items),
                "nodes": len(node_items),
                "edges": len(edge_items),
                "verified_nodes": sum(
                    item["verification"] is not None
                    for item in node_items
                ),
                **counts,
            },
            "status_rail": changed[:12],
            "tasks": task_items,
            "nodes": node_items,
            "edges": edge_items,
            "external_write_allowed": False,
            "model_self_certification_allowed": False,
        }
        snapshot["snapshot_sha256"] = _sha(snapshot)
        return snapshot

    def compile_campaign_brief(
        self,
        *,
        project_id: str,
        principal: Principal,
        store_ref: str,
        as_of: datetime,
        campaign: Mapping[str, Any],
        current_scope: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Compile a versioned brief without creating a second campaign truth."""

        if as_of.tzinfo is None:
            raise ValueError("campaign_brief_as_of_timezone_required")
        expected = {
            "objective",
            "audiences",
            "channel",
            "constraints",
            "content_asset_refs",
        }
        if not isinstance(campaign, Mapping) or set(campaign) != expected:
            raise ValueError("campaign_brief_shape_invalid")
        objective = campaign["objective"]
        channel = campaign["channel"]
        if not isinstance(objective, str) or not 0 < len(objective.strip()) <= 2000:
            raise ValueError("campaign_brief_objective_invalid")
        if not isinstance(channel, str) or not 0 < len(channel.strip()) <= 120:
            raise ValueError("campaign_brief_channel_invalid")

        def normalized_texts(name: str, *, maximum: int) -> list[str]:
            values = campaign[name]
            if (
                not isinstance(values, list)
                or len(values) > maximum
                or any(
                    not isinstance(item, str)
                    or not item.strip()
                    or len(item.strip()) > 500
                    for item in values
                )
            ):
                raise ValueError(f"campaign_brief_{name}_invalid")
            normalized = [item.strip() for item in values]
            if len(set(normalized)) != len(normalized):
                raise ValueError(f"campaign_brief_{name}_invalid")
            return normalized

        audiences = normalized_texts("audiences", maximum=20)
        constraints = normalized_texts("constraints", maximum=40)
        content_asset_refs = normalized_texts("content_asset_refs", maximum=100)
        snapshot = self.workspace(
            project_id,
            principal=principal,
            store_ref=store_ref,
            as_of=as_of,
        )
        if snapshot["status"] != "ready":
            raise ValueError(f"campaign_brief_graph_{snapshot['status']}")
        expected_scope_fields = {
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "authority_sha256",
            "subject_actor_id",
        }
        if not isinstance(current_scope, Mapping) or set(current_scope) != expected_scope_fields:
            raise ValueError("campaign_brief_scope_shape_invalid")
        scope = {
            key: current_scope[key].strip()
            if isinstance(current_scope[key], str)
            else current_scope[key]
            for key in expected_scope_fields
        }
        if any(not isinstance(value, str) or not value for value in scope.values()):
            raise ValueError("campaign_brief_scope_invalid")
        if (
            scope["tenant_ref"] != principal.tenant_ref
            or scope["store_ref"] != store_ref
            or scope["subject_actor_id"] != principal.actor_id
            or snapshot["scope"]
            != {
                "tenant_ref": scope["tenant_ref"],
                "entity_ref": scope["entity_ref"],
                "store_ref": scope["store_ref"],
            }
        ):
            raise PermissionError("campaign_brief_scope_not_current")
        if len(scope["authority_sha256"]) != 64 or any(
            char not in "0123456789abcdef" for char in scope["authority_sha256"].lower()
        ):
            raise ValueError("campaign_brief_authority_invalid")
        scope["authority_sha256"] = scope["authority_sha256"].lower()
        scope_binding_sha256 = _sha(scope)
        content = {
            "contract_id": self.CAMPAIGN_BRIEF_CONTRACT_ID,
            "contract_version": self.CAMPAIGN_BRIEF_CONTRACT_VERSION,
            "project_ref": project_id,
            "graph_snapshot_sha256": snapshot["snapshot_sha256"],
            **scope,
            "scope_binding_sha256": scope_binding_sha256,
            "objective": objective.strip(),
            "audiences": audiences,
            "channel": channel.strip(),
            "constraints": constraints,
            "content_asset_refs": content_asset_refs,
        }
        content_sha256 = _sha(content)
        return {
            **content,
            "brief_ref": f"campaign_brief_{content_sha256[:32]}",
            "content_sha256": content_sha256,
            "external_write_allowed": False,
        }

    def temporal_graph_projection(
        self,
        project_id: str,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        graph_kind: str | None = None,
    ) -> dict[str, Any]:
        """Project the canonical Graph under exact current scope and valid time.

        This is a read seam for governed retrieval. It does not infer or persist
        edges. Rows with incomplete authority remain visible only as blockers,
        never as gate-satisfying knowledge.
        """

        contract_id = "kjds-canonical-graph-temporal-read-v1"
        if as_of.tzinfo is None:
            raise ValueError("as_of must include a timezone")
        if graph_kind and graph_kind not in GRAPH_KINDS:
            raise ValueError("unknown graph kind")
        cutoff = as_of.astimezone(UTC)
        if not principal.can_access_store(store_ref):
            raise PermissionError("store is outside authorized scope")

        status = str(entity_scope.get("status", "no_data"))
        authority_sha256 = entity_scope.get("authority_sha256")
        entity_ref = entity_scope.get("entity_ref")
        exact_scope = (
            status == "ready"
            and entity_scope.get("tenant_ref") == principal.tenant_ref
            and entity_scope.get("store_ref") == store_ref
            and isinstance(entity_ref, str)
            and bool(entity_ref)
            and isinstance(authority_sha256, str)
            and len(authority_sha256) == 64
            and all(
                character in "0123456789abcdef"
                for character in authority_sha256.lower()
            )
        )
        scope = {
            "tenant_ref": principal.tenant_ref,
            "entity_ref": entity_ref if exact_scope else None,
            "store_ref": store_ref,
            "scope_grant_authority_sha256": (
                authority_sha256 if exact_scope else None
            ),
        }

        def empty_projection(result_status: str, reason: str) -> dict[str, Any]:
            result = {
                "contract_id": contract_id,
                "status": result_status,
                "reason": reason,
                "project_id": project_id,
                "scope": scope,
                "as_of": cutoff.isoformat(),
                "nodes": [],
                "edges": [],
                "generated_edges_are_observations": True,
                "formal_fact_allowed": False,
                "external_write_allowed": False,
            }
            result["snapshot_sha256"] = _sha(result)
            return result

        if not exact_scope:
            result_status = "blocked" if status == "blocked" else "no_data"
            return empty_projection(
                result_status,
                "exact_current_scope_authority_required",
            )

        expected_scope = {
            "tenant_ref": principal.tenant_ref,
            "entity_ref": entity_ref,
            "store_ref": store_ref,
            "scope_grant_authority_sha256": authority_sha256,
        }
        with Session(self.engine) as session:
            project = session.scalar(
                select(GraphProjectRow).where(
                    GraphProjectRow.id == project_id,
                    GraphProjectRow.tenant_ref == principal.tenant_ref,
                    GraphProjectRow.entity_ref == entity_ref,
                    GraphProjectRow.store_ref == store_ref,
                )
            )
            if project is None:
                return empty_projection(
                    "no_data",
                    "exact_scope_project_not_found",
                )

            all_edges_query = select(GraphEdgeRow).where(
                GraphEdgeRow.project_id == project.id
            )
            valid_edges_query = all_edges_query.where(
                GraphEdgeRow.effective_from <= cutoff,
                or_(
                    GraphEdgeRow.effective_until.is_(None),
                    GraphEdgeRow.effective_until > cutoff,
                ),
            )
            if graph_kind:
                all_edges_query = all_edges_query.where(
                    GraphEdgeRow.graph_kind == graph_kind
                )
                valid_edges_query = valid_edges_query.where(
                    GraphEdgeRow.graph_kind == graph_kind
                )
            all_edges = list(session.scalars(all_edges_query))
            edges = list(
                session.scalars(valid_edges_query.order_by(GraphEdgeRow.id))
            )
            connected_ids = {
                node_id
                for edge in edges
                for node_id in (edge.source_node_id, edge.target_node_id)
            }
            nodes_query = select(GraphNodeRow).where(
                GraphNodeRow.project_id == project.id,
                GraphNodeRow.created_at <= cutoff,
                GraphNodeRow.id.in_(connected_ids),
            )
            nodes = list(session.scalars(nodes_query.order_by(GraphNodeRow.id)))

        if not edges:
            reason = (
                "no_valid_edges_as_of" if all_edges else "graph_edges_missing"
            )
            return empty_projection("no_data", reason)

        node_by_id = {node.id: node for node in nodes}
        missing_endpoint_ids = {
            node_id
            for edge in edges
            for node_id in (edge.source_node_id, edge.target_node_id)
            if node_id not in node_by_id
        }
        if missing_endpoint_ids:
            return empty_projection(
                "blocked",
                "edge_endpoint_outside_exact_project_scope_or_as_of",
            )

        invalid_node_ids = {
            node.id
            for node in nodes
            if node.scope_json != expected_scope
        }
        if invalid_node_ids:
            return empty_projection(
                "blocked",
                "graph_node_exact_scope_authority_mismatch",
            )

        node_items = [
            {
                "id": node.id,
                "kind": node.graph_kind,
                "stable_key": node.stable_key,
                "type": node.node_type,
                "label": node.label,
                "authority": node.authority,
                "source": node.source,
                "version": node.version,
                "content_sha256": node.content_sha256,
            }
            for node in nodes
        ]
        edge_items: list[dict[str, Any]] = []
        eligible_count = 0
        for edge in edges:
            blockers: list[str] = []
            if edge.derivation_method == "inferred":
                blockers.append("inferred_edge_observation_only")
            if not edge.evidence_ref:
                blockers.append("edge_evidence_missing")
            eligible = not blockers
            eligible_count += int(eligible)
            edge_items.append(
                {
                    "id": edge.id,
                    "kind": edge.graph_kind,
                    "source": edge.source_node_id,
                    "target": edge.target_node_id,
                    "type": edge.edge_type,
                    "derivation": edge.derivation_method,
                    "confidence": edge.confidence,
                    "evidence_ref": edge.evidence_ref,
                    "effective_from": _utc(edge.effective_from).isoformat(),
                    "effective_until": (
                        _utc(edge.effective_until).isoformat()
                        if edge.effective_until is not None
                        else None
                    ),
                    "eligible_for_retrieval": eligible,
                    "blockers": blockers,
                    "content_sha256": edge.content_sha256,
                }
            )
        result = {
            "contract_id": contract_id,
            "status": "ready" if eligible_count else "blocked",
            "reason": (
                None if eligible_count else "no_evidence_backed_edge_available"
            ),
            "project_id": project_id,
            "scope": scope,
            "as_of": cutoff.isoformat(),
            "nodes": node_items,
            "edges": edge_items,
            "generated_edges_are_observations": True,
            "formal_fact_allowed": False,
            "external_write_allowed": False,
        }
        result["snapshot_sha256"] = _sha(result)
        return result
