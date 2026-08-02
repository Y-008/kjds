from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .agent_harness import (
    AgentHarnessService,
    GoalTaskRow,
    GraphEdgeRow,
    GraphNodeRow,
    GraphProjectRow,
    HarnessObservationRow,
    _sha,
)
from .operating_gate_verifier import OperatingStageVerifier
from .security import Principal

PROJECT_ID = "kjds-059-bas123"
VERIFIER_ID = "m0m4-commerce-os"
VERIFIER_VERSION = "1"
AUTHORITY_VERIFIER_ID = "scope-grant-current"
AUTHORITY_VERIFIER_VERSION = "1"
AUTHORITY_TASK_ID = "task-m0-scope-authority-admission"
SUBJECT_VERIFIER_ID = "operating-subject-binding"
SUBJECT_VERIFIER_VERSION = "1"
SUBJECT_TASK_ID = "task-m0-operating-subject-binding"
STORE_REF = "ozon-primary"
MINIMUM_DATABASE_REVISION_SEQUENCE = 70
EVIDENCE_REF = (
    "docs/project/evidence/"
    "20260728_BAS_126_DYNAMIC_SCOPED_OPERATING_GATE_VERIFIER.md"
)
OLD_VERIFIER = ("m0m4-real-postgres", "1")
TASK_IDS = (
    "task-m0-current-authority",
    "task-m1-formal-fact-chain",
    "task-m2-content-profit-listing",
    "task-m3-pilot-order-settlement",
    "task-m4-actual-cash",
)
SUPPORT_QUERIES = {
    "revision": "select version_num from alembic_version",
    "scope_grants": "select count(*) from scope_grant_events",
    "native_imports": (
        "select count(*) from import_jobs where tenant_ref is not null"
    ),
    "native_products": (
        "select count(*) from products where tenant_ref is not null"
    ),
    "native_facts": (
        "select count(*) from fact_records where tenant_ref is not null"
    ),
    "content_assets": "select count(*) from content_assets",
    "profit_scenarios": "select count(*) from profit_scenarios",
    "listing_drafts": "select count(*) from listing_drafts",
    "native_pilots": (
        "select count(*) from read_only_pilots where tenant_ref is not null"
    ),
    "limited_execution_receipts": (
        "select count(*) from limited_execution_receipts"
    ),
    "orders": "select count(*) from orders",
    "finance_entries": "select count(*) from finance_entries",
    "reconciliation_runs": "select count(*) from reconciliation_runs",
}
SupportReader = Callable[[], tuple[str, dict[str, int]]]
IdentityResolver = Callable[[str], Principal]


def gate_node_label(gate_id: str, gate: dict[str, Any]) -> str:
    return (
        f"{gate_id.upper()} {gate['state']} · "
        f"stages={','.join(gate['source_stage_ids'])} · "
        f"blockers={len(gate['blockers'])}"
    )


class OperatingGateObserverService:
    """Adapt real runtime authorities into append-only Harness observations."""

    CONTRACT_ID = "kjds-operating-gate-observer-v1"

    def __init__(
        self,
        *,
        engine,
        commerce_os,
        scope_grants,
        agent_harness: AgentHarnessService,
        identity_resolver: IdentityResolver,
        verifier: OperatingStageVerifier | None = None,
        support_reader: SupportReader | None = None,
    ) -> None:
        self.engine = engine
        self.commerce_os = commerce_os
        self.scope_grants = scope_grants
        self.agent_harness = agent_harness
        self.identity_resolver = identity_resolver
        self.verifier = verifier or OperatingStageVerifier()
        self.support_reader = support_reader or self._read_support

    def observe(
        self,
        *,
        project_id: str,
        principal: Principal,
        store_ref: str,
        observed_at: datetime | None = None,
    ) -> dict[str, Any]:
        if project_id != PROJECT_ID:
            raise KeyError("operating Gate observer project not found")
        if not principal.roles.intersection({"monitor", "admin"}):
            raise PermissionError("monitor or admin role required")
        if store_ref != STORE_REF or not principal.can_access_store(store_ref):
            raise PermissionError("store is outside authorized scope")
        now = self._utc(observed_at or datetime.now(UTC))
        if now > datetime.now(UTC):
            raise ValueError("observed_at cannot be in the future")
        bucket = now.replace(minute=0, second=0, microsecond=0)
        revision, support_counts = self.support_reader()
        if not self._supports_database_revision(revision):
            raise ValueError(
                "operating Gate observation requires migration sequence 0070 or later"
            )
        subject_binding = self.agent_harness.operating_subject(
            project_id=project_id,
            principal=principal,
            as_of=now,
        )
        if subject_binding["status"] != "ready":
            raise ValueError(
                "project operating-subject binding is required"
            )
        operating_principal = self.identity_resolver(
            subject_binding["subject_actor_id"]
        )
        if (
            operating_principal.tenant_ref != principal.tenant_ref
            or not operating_principal.can_access_store(store_ref)
            or not operating_principal.has_any_role("operator")
            or operating_principal.has_any_role("admin", "monitor")
        ):
            raise ValueError(
                "bound operating subject identity no longer matches the "
                "project operator contract"
            )
        workspace = self.commerce_os.workspace(
            principal=operating_principal,
            store_ref=store_ref,
            as_of=bucket.isoformat(),
        )
        authority = self.scope_grants.current(
            principal=operating_principal,
            store_ref=store_ref,
            as_of=now,
        )
        result = self.verifier.evaluate(
            workspace=workspace,
            support_counts=support_counts,
            observation_bucket=bucket.isoformat(),
        )
        self._record(
            project_id=project_id,
            principal=principal,
            operating_principal=operating_principal,
            store_ref=store_ref,
            observed_at=now,
            workspace=workspace,
            authority=authority,
            subject_binding=subject_binding,
            result=result,
        )
        counts = self._counts(project_id)
        return {
            "contract_id": self.CONTRACT_ID,
            "project_id": project_id,
            "database_revision": revision,
            "observation_bucket": bucket.isoformat(),
            "operating_subject_actor_id": operating_principal.actor_id,
            "subject_binding_sha256": subject_binding[
                "authority_sha256"
            ],
            "workspace_snapshot_sha256": workspace["snapshot_sha256"],
            "result_sha256": result["result_sha256"],
            "status": result["status"],
            "states": {
                "operating_subject": "passed",
                "scope_authority": self._authority_state(authority),
                **{
                    gate_id: gate["state"]
                    for gate_id, gate in result["gates"].items()
                },
            },
            "counts": counts,
            "external_write_allowed": False,
            "model_self_certification_allowed": False,
        }

    def _record(
        self,
        *,
        project_id: str,
        principal: Principal,
        operating_principal: Principal,
        store_ref: str,
        observed_at: datetime,
        workspace: dict[str, Any],
        authority: dict[str, Any],
        subject_binding: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        self.agent_harness.register_verifier(
            {
                "id": VERIFIER_ID,
                "version": VERIFIER_VERSION,
                "source_type": "commerce_os_projection",
                "authority": "runtime",
                "success_states": ["passed"],
                "freshness_seconds": 3600,
            }
        )
        self.agent_harness.register_verifier(
            {
                "id": SUBJECT_VERIFIER_ID,
                "version": SUBJECT_VERIFIER_VERSION,
                "source_type": "project_operating_subject_projection",
                "authority": "project_governance",
                "success_states": ["passed"],
                "freshness_seconds": 3600,
            }
        )
        self.agent_harness.register_verifier(
            {
                "id": AUTHORITY_VERIFIER_ID,
                "version": AUTHORITY_VERIFIER_VERSION,
                "source_type": "scope_grant_projection",
                "authority": "identity_governance",
                "success_states": ["passed"],
                "freshness_seconds": 3600,
            }
        )
        with Session(self.engine) as session, session.begin():
            project = session.get(GraphProjectRow, project_id)
            if project is None:
                raise KeyError("canonical graph project not found")
            if (
                project.tenant_ref != principal.tenant_ref
                or project.store_ref != store_ref
            ):
                raise PermissionError("project is outside authorized scope")
            for index, task_id in enumerate(TASK_IDS):
                task = session.get(GoalTaskRow, task_id)
                if task is None or task.project_id != project_id:
                    raise KeyError(f"canonical Gate task not found: {task_id}")
                binding = (task.verifier_id, task.verifier_version)
                if binding not in {
                    OLD_VERIFIER,
                    (VERIFIER_ID, VERIFIER_VERSION),
                }:
                    raise ValueError(
                        f"unexpected Gate task verifier binding: {task_id}"
                    )
                gate = result["gates"][f"m{index}"]
                task.verifier_id = VERIFIER_ID
                task.verifier_version = VERIFIER_VERSION
                task.verification_condition = (
                    "fresh scoped Commerce OS stages and real PostgreSQL "
                    "support counts satisfy this exact sequential Gate"
                )
                task.next_safe_action = gate["next_action"]
                task.workspace = gate["workspace"]
                stable_key = f"gate-state:M{index}"
                node = session.scalar(
                    select(GraphNodeRow).where(
                        GraphNodeRow.project_id == project_id,
                        GraphNodeRow.stable_key == stable_key,
                    )
                )
                if node is None or node.authority != "observed":
                    raise KeyError(
                        f"observed Gate Graph node not found: {stable_key}"
                    )
                node.label = gate_node_label(f"m{index}", gate)
                node.source = gate["artifact_ref"]
                node.artifact_ref = gate["artifact_ref"]
                node.version = result["observation_bucket"]
                node.content_sha256 = _sha(
                    {
                        "stable_key": stable_key,
                        "state": gate["state"],
                        "summary": gate["summary"],
                        "input_sha256": gate["input_sha256"],
                        "artifact_ref": gate["artifact_ref"],
                    }
                )
            authority_task = session.get(GoalTaskRow, AUTHORITY_TASK_ID)
            if (
                authority_task is None
                or authority_task.project_id != project_id
                or (
                    authority_task.verifier_id,
                    authority_task.verifier_version,
                )
                != (AUTHORITY_VERIFIER_ID, AUTHORITY_VERIFIER_VERSION)
            ):
                raise KeyError(
                    "canonical scope authority admission task not found"
                )
            subject_task = session.get(GoalTaskRow, SUBJECT_TASK_ID)
            if (
                subject_task is None
                or subject_task.project_id != project_id
                or (
                    subject_task.verifier_id,
                    subject_task.verifier_version,
                )
                != (SUBJECT_VERIFIER_ID, SUBJECT_VERIFIER_VERSION)
            ):
                raise KeyError(
                    "canonical operating-subject binding task not found"
                )
            subject_task.verification_condition = (
                "fresh append-only project binding resolves one current "
                "registered non-admin operator"
            )
            subject_task.next_safe_action = (
                "Observe the bound operating subject scope authority."
            )
            subject_node = session.scalar(
                select(GraphNodeRow).where(
                    GraphNodeRow.project_id == project_id,
                    GraphNodeRow.stable_key
                    == "authority:operating-subject-binding",
                )
            )
            if (
                subject_node is None
                or subject_node.authority != "canonical"
                or subject_node.artifact_ref
                != (
                    f"/v1/agent-control/projects/{project_id}/"
                    "operating-subject"
                )
            ):
                raise KeyError(
                    "canonical operating-subject Graph node not found"
                )
            authority_task.dependency_ids_json = [SUBJECT_TASK_ID]
            authority_task.verification_condition = (
                "fresh bound-operating-subject ScopeGrantAuthority.current "
                "projection resolves one current entity grant"
            )
            authority_task.next_safe_action = (
                "Continue scoped M1 ingestion."
                if authority.get("status") == "ready"
                else "Submit current owner source Evidence, obtain an accepted "
                "independent review, then run the non-mutating scope grant "
                "admission preflight."
            )
            authority_node = session.scalar(
                select(GraphNodeRow).where(
                    GraphNodeRow.project_id == project_id,
                    GraphNodeRow.stable_key
                    == "authority:current-scope-grant",
                )
            )
            if (
                authority_node is None
                or authority_node.authority != "canonical"
                or authority_node.artifact_ref
                != "/v1/scope-grants/current"
            ):
                raise KeyError(
                    "canonical scope authority Graph node not found"
                )

        subject_artifact = (
            f"/v1/agent-control/projects/{project_id}/operating-subject"
        )
        subject_input_sha256 = _sha(
            {
                "contract_id": self.agent_harness.OPERATING_SUBJECT_CONTRACT_ID,
                "observation_bucket": result["observation_bucket"],
                "project_id": project_id,
                "tenant_ref": principal.tenant_ref,
                "store_ref": store_ref,
                "subject_actor_id": operating_principal.actor_id,
                "authority_sha256": subject_binding["authority_sha256"],
            }
        )
        self.agent_harness.record_observation(
            {
                "project_id": project_id,
                "task_id": SUBJECT_TASK_ID,
                "verifier_id": SUBJECT_VERIFIER_ID,
                "verifier_version": SUBJECT_VERIFIER_VERSION,
                "source": "project_operating_subject_projection",
                "scope": {
                    "tenant_ref": principal.tenant_ref,
                    "store_ref": store_ref,
                    "subject_actor_id": operating_principal.actor_id,
                    "subject_binding_sha256": subject_binding[
                        "authority_sha256"
                    ],
                },
                "state": "passed",
                "summary": (
                    "Append-only project operating-subject binding resolved "
                    f"registered operator {operating_principal.actor_id}."
                ),
                "input_sha256": subject_input_sha256,
                "artifact_ref": subject_artifact,
                "evidence_ref": subject_binding["event_id"],
                "observed_at": observed_at.isoformat(),
                "store_ref": store_ref,
            },
            principal=principal,
        )
        authority_state = self._authority_state(authority)
        subject_query = quote(
            operating_principal.actor_id,
            safe="",
        )
        authority_artifact = (
            "/v1/scope-grants/current?"
            f"store_ref={quote(store_ref, safe='')}&"
            f"subject_actor_id={subject_query}"
        )
        authority_summary = (
            "One current independently evidenced entity/store grant resolved "
            f"for operating subject {operating_principal.actor_id}."
            if authority_state == "passed"
            else "Bound operating subject has no admissible entity/store "
            "scope grant: "
            f"{authority.get('reason', 'scope_authority_unavailable')}."
        )
        authority_input_sha256 = _sha(
            {
                "contract_id": "kjds-scope-grant-events-v1",
                "observation_bucket": result["observation_bucket"],
                "tenant_ref": principal.tenant_ref,
                "store_ref": store_ref,
                "subject_actor_id": operating_principal.actor_id,
                "subject_binding_sha256": subject_binding[
                    "authority_sha256"
                ],
                "projection": authority,
            }
        )
        self.agent_harness.record_observation(
            {
                "project_id": project_id,
                "task_id": AUTHORITY_TASK_ID,
                "verifier_id": AUTHORITY_VERIFIER_ID,
                "verifier_version": AUTHORITY_VERIFIER_VERSION,
                "source": "scope_grant_projection",
                "scope": {
                    "tenant_ref": principal.tenant_ref,
                    "entity_ref": authority.get("entity_ref"),
                    "store_ref": store_ref,
                    "subject_actor_id": operating_principal.actor_id,
                    "subject_binding_sha256": subject_binding[
                        "authority_sha256"
                    ],
                },
                "state": authority_state,
                "summary": authority_summary,
                "input_sha256": authority_input_sha256,
                "artifact_ref": authority_artifact,
                "evidence_ref": authority.get("evidence_id"),
                "observed_at": observed_at.isoformat(),
                "store_ref": store_ref,
            },
            principal=principal,
        )
        for index, task_id in enumerate(TASK_IDS):
            gate = result["gates"][f"m{index}"]
            observation_input_sha256 = _sha(
                {
                    "gate_input_sha256": gate["input_sha256"],
                    "subject_actor_id": operating_principal.actor_id,
                    "subject_binding_sha256": subject_binding[
                        "authority_sha256"
                    ],
                }
            )
            self.agent_harness.record_observation(
                {
                    "project_id": project_id,
                    "task_id": task_id,
                    "verifier_id": VERIFIER_ID,
                    "verifier_version": VERIFIER_VERSION,
                    "source": "commerce_os_projection",
                    "scope": {
                        "tenant_ref": principal.tenant_ref,
                        "entity_ref": workspace["scope"].get("entity_ref"),
                        "store_ref": store_ref,
                        "subject_actor_id": operating_principal.actor_id,
                        "subject_binding_sha256": subject_binding[
                            "authority_sha256"
                        ],
                        "workspace_snapshot_sha256": workspace[
                            "snapshot_sha256"
                        ],
                    },
                    "state": gate["state"],
                    "summary": gate["summary"],
                    "input_sha256": observation_input_sha256,
                    "artifact_ref": gate["artifact_ref"],
                    "evidence_ref": EVIDENCE_REF,
                    "observed_at": observed_at.isoformat(),
                    "store_ref": store_ref,
                },
                principal=principal,
            )

    def _read_support(self) -> tuple[str, dict[str, int]]:
        with self.engine.connect() as connection:
            values = {
                name: connection.execute(text(query)).scalar_one()
                for name, query in SUPPORT_QUERIES.items()
            }
        return str(values["revision"]), {
            name: int(value)
            for name, value in values.items()
            if name != "revision"
        }

    def _counts(self, project_id: str) -> dict[str, int]:
        with Session(self.engine) as session:
            return {
                name: int(
                    session.scalar(
                        select(func.count())
                        .select_from(model)
                        .where(model.project_id == project_id)
                    )
                    or 0
                )
                for name, model in (
                    ("tasks", GoalTaskRow),
                    ("observations", HarnessObservationRow),
                    ("nodes", GraphNodeRow),
                    ("edges", GraphEdgeRow),
                )
            }

    @staticmethod
    def _authority_state(authority: dict[str, Any]) -> str:
        return {
            "ready": "passed",
            "no_data": "no_data",
            "blocked": "blocked",
        }.get(str(authority.get("status")), "failed")

    @staticmethod
    def _supports_database_revision(revision: str) -> bool:
        match = re.fullmatch(r"\d{8}_(\d{4})", str(revision))
        return bool(
            match
            and int(match.group(1)) >= MINIMUM_DATABASE_REVISION_SEQUENCE
        )

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("observed_at must include timezone")
        return value.astimezone(UTC)
