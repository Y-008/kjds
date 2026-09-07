from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..api_contracts import current_principal, ensure_role, ensure_store_scope, run
from ..autonomous_pm_heartbeat import (
    HeartbeatInput,
    ServerAuthoritySnapshot,
    ServerEconomicGuardRead,
    evaluate_heartbeat,
    observe_server_authority,
    observe_server_git_worktree,
)
from ..economic_guard_service import (
    EconomicGuardInput,
    EconomicGuardResult,
    evaluate_economic_guard,
)
from ..operating_snapshot import build_operating_snapshot
from ..project_manager_cycle import normalize_task_result
from ..project_task_contracts import (
    ProjectTaskContractError,
    WorkItem,
    project_harness_graph,
    validate_task_brief,
    validate_wip,
)
from ..proof_frontier_planner import plan_proof_frontier
from ..runtime import runtime
from ..security import Principal
from ..wave_release_packet import (
    build_release_packet,
    derive_claim_level,
    validate_release_packet,
)

router = APIRouter()


# These request fields remain in the wire contract for old PM clients.  The
# route records them for replay diagnostics, while effective values come only
# from the server-owned runtime readers below.  If a deployment has not bound
# a reader, the corresponding observation is blocked; a caller cannot promote
# itself by posting ``true``.
_UNOBSERVED_HEARTBEAT_FIELDS: tuple[str, ...] = (
    "task_queue_known",
    "lease_snapshot_known",
    "test_receipts_current",
    "proof_receipts_current",
    "evidence_fresh",
    "data_quality_valid",
    "external_readback_passed",
    "rollback_available",
    "experiment_clear",
    "economic_state_known",
)
_UNOBSERVED_HEARTBEAT_REASONS: dict[str, str] = {
    field: f"server_observation_unavailable:{field}"
    for field in _UNOBSERVED_HEARTBEAT_FIELDS
}
_SERVER_AUTHORITY_TO_HEARTBEAT_FIELD: dict[str, str] = {
    "task_queue": "task_queue_known",
    "lease_snapshot": "lease_snapshot_known",
    "test_receipts": "test_receipts_current",
    "proof_receipts": "proof_receipts_current",
    "evidence": "evidence_fresh",
    "data_quality": "data_quality_valid",
    "external_readback": "external_readback_passed",
    "rollback": "rollback_available",
    "experiment": "experiment_clear",
    "economic_guard": "economic_state_known",
}


def _force_unverified_economic_guard(
    observed_claim_guard: EconomicGuardResult,
    *,
    caller_claimed_state: bool,
) -> EconomicGuardResult:
    """Turn caller-provided economic numbers into an explicit hold gate.

    The numeric guard remains useful as a diagnostic (for example, it can
    expose a cash-floor breach), but it is not an authority source.  Bind a
    new digest to both the diagnostic digest and the unverified reason so a
    replay cannot mistake the caller projection for a server balance.
    """

    reasons = list(observed_claim_guard.reasons)
    if not caller_claimed_state:
        # Preserve the historical reason used by clients that omitted the
        # optional economic-state attestation.
        reasons.append("economic_state_unknown")
    reasons.append(_UNOBSERVED_HEARTBEAT_REASONS["economic_state_known"])
    reasons.append("server_observation_unavailable:economic_guard")
    deduped_reasons = tuple(dict.fromkeys(reasons))
    snapshot_sha256 = _stable_hash(
        {
            "contract_id": "kjds-project-heartbeat-economic-guard-v2",
            "status": "blocked",
            "reasons": list(deduped_reasons),
            "caller_projection_sha256": observed_claim_guard.snapshot_sha256,
        }
    )
    return EconomicGuardResult(
        status="blocked",
        reasons=deduped_reasons,
        snapshot_sha256=snapshot_sha256,
    )


class ProjectHeartbeatInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_ref: str = Field(min_length=1, max_length=160)
    store_ref: str = Field(default="ozon-primary", min_length=1, max_length=160)
    head: str = Field(min_length=1, max_length=200)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=300)
    expected_revision: int | None = Field(default=None, ge=0)
    # Legacy compatibility claims.  The heartbeat route records them for
    # diagnostics but derives the checkout from its own server observer and
    # keeps every other unbound authority gate false.
    head_verified: bool = False
    workspace_state_known: bool = False
    workspace_clean: bool = False
    task_queue_known: bool = False
    lease_snapshot_known: bool = False
    test_receipts_current: bool = False
    proof_receipts_current: bool = False
    evidence_fresh: bool = False
    data_quality_valid: bool = False
    external_readback_passed: bool = False
    rollback_available: bool = False
    experiment_clear: bool = False
    liveness_deadline: datetime | None = None
    heartbeat_at: datetime | None = None
    progress_cursor: str | None = Field(default=None, max_length=500)
    expected_next_event: str | None = Field(default=None, max_length=300)
    stuck_detector_version: str | None = Field(default=None, max_length=100)
    compensation_action: str | None = Field(default=None, max_length=300)
    recovery_ref: str | None = Field(default=None, max_length=300)
    # The PM and TeamAgent share this immutable result envelope.  It is
    # normalized before persistence so evidence/dependency references survive
    # heartbeat replay instead of being hidden in an unvalidated blob.
    task_result: dict[str, Any] | None = None
    # Economic state is an explicit fact.  A missing balance/margin snapshot
    # must not be interpreted as zero risk merely because the request omitted
    # optional fields.
    economic_state_known: bool = False
    cash_available: Decimal = Decimal("0")
    min_cash: Decimal = Decimal("0")
    margin_rate: Decimal | None = None
    min_margin_rate: Decimal | None = None
    budget_remaining: Decimal | None = None
    min_budget_remaining: Decimal = Decimal("0")

    @field_validator("task_result")
    @classmethod
    def validate_task_result(cls, value: dict[str, Any] | None):
        if value is None:
            return None
        return normalize_task_result(value)


class ProjectGraphSignalInput(BaseModel):
    """A verifier-backed observation for one graph task/node.

    Signals deliberately reuse the Harness observation authority.  A signal
    without a registered verifier would create an unverifiable second source
    of truth, so the verifier identity and input digest are required.
    """

    model_config = ConfigDict(extra="forbid")

    signal_type: str = Field(default="operational", min_length=1, max_length=80)
    node_id: str | None = Field(default=None, min_length=1, max_length=180)
    task_id: str | None = Field(default=None, min_length=1, max_length=180)
    verifier_id: str = Field(min_length=1, max_length=180)
    verifier_version: str = Field(min_length=1, max_length=80)
    state: Literal["pending", "running", "blocked", "passed", "failed", "no_data"]
    summary: str = Field(min_length=1, max_length=4000)
    artifact_ref: str = Field(min_length=1, max_length=500)
    evidence_ref: str | None = Field(default=None, min_length=1, max_length=500)
    input_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-fA-F]{64}$",
    )
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    store_ref: str = Field(default="ozon-primary", min_length=1, max_length=160)
    idempotency_key: str = Field(min_length=1, max_length=300)
    expected_snapshot_sha256: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-fA-F]{64}$",
    )


class DispatchWaveInput(BaseModel):
    """Bounded, proposal-only frontier dispatch request."""

    model_config = ConfigDict(extra="forbid")

    max_tasks: int = Field(default=8, ge=1, le=64)
    expected_head: str | None = Field(default=None, min_length=1, max_length=200)
    expected_snapshot_sha256: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-fA-F]{64}$",
    )
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=300)
    expected_revision: int | None = Field(default=None, ge=0)
    budget_units: Decimal | None = Field(default=None, ge=0)
    mode: Literal["propose"] = "propose"


class InvalidateGraphInput(BaseModel):
    """Describe an invalidation overlay without mutating canonical graph rows."""

    model_config = ConfigDict(extra="forbid")

    source_node_id: str = Field(min_length=1, max_length=180)
    target_node_ids: tuple[str, ...] = ()
    # ``node_ids`` is accepted as a compatibility spelling used by PM clients.
    node_ids: tuple[str, ...] = ()
    reason: str = Field(min_length=1, max_length=2000)
    idempotency_key: str = Field(min_length=1, max_length=300)
    expected_revision: int | None = Field(default=None, ge=0)
    expected_snapshot_sha256: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-fA-F]{64}$",
    )
    compensation_action: str | None = Field(default=None, min_length=1, max_length=300)
    mode: Literal["propose"] = "propose"

    @model_validator(mode="after")
    def require_targets(self):
        targets = tuple(dict.fromkeys((*self.target_node_ids, *self.node_ids)))
        if not targets:
            raise ValueError("at least one target node is required")
        if self.source_node_id in targets:
            raise ValueError("source node cannot invalidate itself")
        return self


def _as_of(value: str | None):
    from datetime import UTC, datetime

    if value is None:
        return datetime.now(UTC)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(422, "as_of must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise HTTPException(422, "as_of must include timezone")
    return parsed.astimezone(UTC)


def _graph(project_id: str, principal: Principal, store_ref: str | None, as_of: str | None) -> dict[str, Any]:
    if store_ref:
        ensure_store_scope(principal, store_ref)
    return runtime.agent_harness.workspace(
        project_id,
        principal=principal,
        store_ref=store_ref,
        as_of=_as_of(as_of),
    )


def _stable_hash(value: Any) -> str:
    """Hash a JSON-safe projection without allowing non-finite values."""

    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _heartbeat_scope_key(
    *,
    principal: Principal,
    entity_ref: str,
    store_ref: str,
) -> str:
    """Build the compact exact scope passed to server-side PM readers."""

    tenant = principal.tenant_ref.strip()
    entity = entity_ref.strip()
    store = store_ref.strip()
    if not tenant or not entity or not store:
        raise ValueError("heartbeat authority scope is incomplete")
    scope_key = f"{tenant}/{entity}/{store}"
    if len(scope_key) > 500:
        raise ValueError("heartbeat authority scope is too long")
    return scope_key


def _runtime_pm_economic_reader() -> Any:
    """Return the explicitly bound runtime economic reader, if any."""

    value = getattr(runtime, "pm_economic_guard_reader", None)
    if isinstance(value, ServerEconomicGuardRead):
        # A static read remains subject to its own observed_at/expiry checks.
        def read_static(**_values: Any) -> ServerEconomicGuardRead:
            return value

        return read_static
    return value if callable(value) else None


def _runtime_pm_authority_readers() -> Mapping[str, Any]:
    """Return only the server-owned PM reader registry, never request data."""

    value = getattr(runtime, "pm_authority_readers", None)
    return value if isinstance(value, Mapping) else {}


def _heartbeat_authority_fields(
    snapshot: ServerAuthoritySnapshot,
    heartbeat: HeartbeatInput,
) -> tuple[list[str], list[str], dict[str, bool]]:
    """Project server observation status into the legacy response fields."""

    flags = {
        field: bool(getattr(heartbeat, field, False))
        for field in (
            *(_SERVER_AUTHORITY_TO_HEARTBEAT_FIELD.values()),
            "head_verified",
            "workspace_state_known",
            "workspace_clean",
        )
    }
    economic = snapshot.economic_observation
    flags["economic_state_known"] = bool(
        economic is not None and economic.is_current(snapshot.observed_at)
    )
    verified: list[str] = []
    unverified: list[str] = []
    for _source, target in _SERVER_AUTHORITY_TO_HEARTBEAT_FIELD.items():
        if flags.get(target, False):
            verified.append(target)
        else:
            unverified.append(target)
    for target in ("head_verified", "workspace_state_known", "workspace_clean"):
        if flags.get(target, False):
            verified.append(target)
        else:
            unverified.append(target)
    return verified, unverified, flags


def _operating_snapshot_from_heartbeat(
    *,
    project_id: str,
    graph: Mapping[str, Any],
    projection: Mapping[str, Any],
    server_git: Any,
    authority_snapshot: ServerAuthoritySnapshot,
    decision: Any,
    guard: EconomicGuardResult,
) -> Any:
    """Join heartbeat observations into the immutable replay projection."""

    def authority_state(name: str) -> str:
        observation = authority_snapshot.observation(name)
        if observation is None:
            return "NO_DATA"
        if observation.status == "valid" and observation.is_current(authority_snapshot.observed_at):
            return "VALID"
        return {
            "partial": "PARTIAL",
            "stale": "STALE",
            "blocked": "BLOCKED",
            "unknown": "UNKNOWN_OUTCOME",
        }.get(observation.status, "NO_DATA")

    proof_status = str(projection.get("status") or "NO_DATA").upper()
    if proof_status not in {"PROVED", "UNPROVED", "STALE", "BLOCKED", "NO_DATA"}:
        proof_status = "NO_DATA"
    operational = "UNKNOWN"
    if getattr(server_git, "available", False):
        operational = "LIVE" if (
            decision.status == "dispatch"
            and getattr(server_git, "worktree_clean", False) is True
            and bool(graph.get("migration_head"))
        ) else "PAUSED"
    elif authority_snapshot.status == "blocked":
        operational = "BLOCKED"
    economic = "ALLOWED" if guard.status == "allowed" else "BLOCKED"

    def string_ids(value: Any) -> list[str]:
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
            return []
        return [
            str(item.get("id")) if isinstance(item, Mapping) and item.get("id") is not None else str(item)
            for item in value
            if (isinstance(item, Mapping) and item.get("id") is not None) or isinstance(item, str)
        ]

    return build_operating_snapshot(
        {
            "project_id": project_id,
            "tenant_ref": str((graph.get("scope") or {}).get("tenant_ref") or "unknown"),
            "entity_ref": str((graph.get("scope") or {}).get("entity_ref") or "unknown"),
            "store_ref": str((graph.get("scope") or {}).get("store_ref") or "unknown"),
            "observed_at": authority_snapshot.observed_at,
            "exact_head": str(getattr(server_git, "head", None) or "unobserved"),
            "migration_head": str(graph.get("migration_head") or "unbound"),
            "graph_snapshot_sha256": str(projection.get("snapshot_sha256") or ""),
            "proof_state": proof_status,
            "evidence_state": authority_state("evidence"),
            "operational_state": operational,
            "economic_state": economic,
            "rollback_available": authority_snapshot.observation("rollback") is not None
            and authority_snapshot.observation("rollback").is_current(authority_snapshot.observed_at),
            "external_readback_passed": authority_snapshot.observation("external_readback") is not None
            and authority_snapshot.observation("external_readback").is_current(authority_snapshot.observed_at),
            "task_frontier": string_ids(projection.get("frontier_ids")),
            "critical_path": string_ids(projection.get("critical_path")),
            "blockers": projection.get("blockers") or [],
            "test_receipts": string_ids(
                [authority_snapshot.observation("test_receipts").snapshot_sha256]
                if authority_snapshot.observation("test_receipts") is not None
                else []
            ),
            "proof_receipts": string_ids(
                [authority_snapshot.observation("proof_receipts").snapshot_sha256]
                if authority_snapshot.observation("proof_receipts") is not None
                else []
            ),
            "evidence_refs": string_ids(
                [authority_snapshot.observation("evidence").snapshot_sha256]
                if authority_snapshot.observation("evidence") is not None
                else []
            ),
        }
    )


def _proposal_request_hash(
    *,
    project_id: str,
    tenant_ref: str,
    store_ref: str,
    kind: str,
    idempotency_key: str,
    request: Any,
) -> str:
    """Hash the immutable proposal input independently of its graph output.

    Proposal responses are read-only, but callers still need a durable
    identity to compare a replay with the request that produced it.  Keeping
    this digest separate from ``proposal_sha256`` means a changed graph can be
    distinguished from changed request parameters without trusting a mutable
    dashboard response.
    """

    return _stable_hash(
        {
            "contract_id": "kjds-project-graph-proposal-request-v1",
            "kind": kind,
            "project_id": project_id,
            "tenant_ref": tenant_ref,
            "store_ref": store_ref,
            "idempotency_key": idempotency_key,
            "request": request,
        }
    )


def _proposal_entity_id(graph: Mapping[str, Any]) -> str:
    """Resolve the graph's registered operating entity for ledger scoping.

    A proposal without an entity binding cannot be safely replayed or
    attributed to an operating subject.  Keep the ledger fail-closed instead
    of inventing a tenant-wide placeholder scope.
    """

    scope = graph.get("scope")
    entity_id = scope.get("entity_ref") if isinstance(scope, Mapping) else None
    if not isinstance(entity_id, str) or not entity_id.strip():
        raise ValueError("project graph entity scope is required for proposal persistence")
    return entity_id.strip()


def _persist_graph_proposal(
    *,
    project_id: str,
    principal: Principal,
    store_ref: str,
    graph: Mapping[str, Any],
    kind: str,
    proposal: Mapping[str, Any],
    request_sha256: str,
    idempotency_key: str,
    expected_revision: int | None,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    """Persist one proposal and return the immutable winner on replay.

    The ledger stores only the planning response.  No queue, provider,
    approval, permit or external write is reached from this helper.
    """

    proposal_payload = dict(proposal)
    proposal_sha256 = proposal_payload.get("proposal_sha256")
    if not isinstance(proposal_sha256, str):
        raise ValueError("proposal_sha256 is required before proposal persistence")
    ledger = runtime.project_graph_proposal_ledger
    entry = ledger.record(
        project_id=project_id,
        tenant_id=principal.tenant_ref,
        entity_id=_proposal_entity_id(graph),
        store_ref=store_ref,
        kind=kind,
        idempotency_key=idempotency_key,
        request_sha256=request_sha256,
        proposal=proposal_payload,
        proposal_sha256=proposal_sha256,
        graph_snapshot_sha256=(
            proposal_payload.get("graph_snapshot_sha256")
            or (
                proposal_payload.get("projection", {}).get("snapshot_sha256")
                if isinstance(proposal_payload.get("projection"), Mapping)
                else None
            )
        ),
        status=str(proposal_payload.get("status") or "proposed"),
        recorded_by=principal.actor_id,
        observed_at=observed_at or datetime.now(UTC),
        expected_revision=expected_revision,
    )
    stored_payload = entry.get("payload")
    if not isinstance(stored_payload, Mapping):
        raise ValueError("proposal ledger returned an invalid payload")
    # Return the persisted JSON projection even for the first call.  Decimal
    # fields are represented as exact strings by the ledger, so a retry is
    # byte-for-byte equivalent to the original response.
    response = dict(stored_payload)
    response["persisted"] = True
    response["proposal_id"] = entry["proposal_id"]
    response["ledger_revision"] = entry["revision"]
    response["replay"] = {
        "proposal_id": entry["proposal_id"],
        "idempotency_key": entry["idempotency_key"],
        "request_sha256": entry["request_sha256"],
        "proposal_sha256": entry["proposal_sha256"],
        "payload_sha256": entry["payload_sha256"],
        "revision": entry["revision"],
        "replayed": bool(entry.get("replayed", False)),
        "replayable": True,
    }
    response["external_write_allowed"] = False
    return response


def _dispatch_task_contract(
    *,
    project_id: str,
    item: Mapping[str, Any],
    contract_node: Mapping[str, Any] | None,
    graph: Mapping[str, Any],
    projection: Mapping[str, Any],
) -> dict[str, Any]:
    """Attach a bounded WBS/DoR projection to one dispatch proposal task."""

    if contract_node is None:
        return {
            "task_contract_status": "unavailable",
            "task_brief": None,
            "definition_of_ready": {
                "valid": False,
                "errors": ["task is missing from five-level WBS projection"],
                "warnings": [],
            },
        }
    scope = graph.get("scope") if isinstance(graph.get("scope"), Mapping) else {}
    task_id = str(item.get("id") or contract_node.get("node_id"))
    brief = {
        "task_id": task_id,
        "parent_id": contract_node.get("parent_id"),
        "scope": dict(scope),
        "owner": contract_node.get("owner") or "",
        "reviewer": contract_node.get("reviewer") or "",
        "objective": str(item.get("label") or contract_node.get("title") or task_id),
        "business_context": f"project graph {project_id}",
        "allowed_scope": list(contract_node.get("exact_write_set") or ()),
        "prohibited_scope": ["external_write", "permit", "approval", "credential"],
        "dependencies": list(contract_node.get("dependencies") or ()),
        "input_snapshot": {"graph_snapshot_sha256": projection.get("snapshot_sha256")},
        "exact_files_or_domain": list(contract_node.get("exact_write_set") or ()),
        "expected_outputs": ["TaskResult", "test_receipt"],
        "acceptance_tests": list(contract_node.get("acceptance_tests") or ()),
        "budget": {},
        "lease": {},
        "deadline": None,
        "risk_tier": contract_node.get("risk_tier") or "R0",
        "rollback_ref": contract_node.get("rollback_ref"),
        "reporting_format": ["TaskResult"],
    }
    report = validate_task_brief(brief)
    return {
        "task_contract_status": "ready" if report.valid else "blocked",
        "work_breakdown": {
            "node_id": contract_node.get("node_id"),
            "level": contract_node.get("level"),
            "parent_id": contract_node.get("parent_id"),
            "status": contract_node.get("status"),
            "claim_level": contract_node.get("claim_level"),
        },
        "task_brief": brief,
        "definition_of_ready": {
            "valid": report.valid,
            "errors": list(report.errors),
            "warnings": list(report.warnings),
            "snapshot_sha256": report.snapshot_sha256,
        },
    }


def _graph_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Produce a deterministic, field-level diff for two planner results."""

    def indexed(items: Any) -> dict[str, dict[str, Any]]:
        if not isinstance(items, list):
            return {}
        return {
            str(item.get("id")): item
            for item in items
            if isinstance(item, dict) and item.get("id") is not None
        }

    before_nodes = indexed(before.get("nodes"))
    after_nodes = indexed(after.get("nodes"))
    before_edges = indexed((before.get("snapshot") or {}).get("edges"))
    after_edges = indexed((after.get("snapshot") or {}).get("edges"))

    added_nodes = [after_nodes[key] for key in sorted(set(after_nodes) - set(before_nodes))]
    removed_nodes = [before_nodes[key] for key in sorted(set(before_nodes) - set(after_nodes))]
    changed_nodes: list[dict[str, Any]] = []
    state_changes: list[dict[str, Any]] = []
    for key in sorted(set(before_nodes) & set(after_nodes)):
        old = before_nodes[key]
        new = after_nodes[key]
        fields = sorted(
            field
            for field in set(old) | set(new)
            if old.get(field) != new.get(field)
        )
        if fields:
            changed_nodes.append(
                {
                    "id": key,
                    "fields": fields,
                    "before": old,
                    "after": new,
                }
            )
        if old.get("state") != new.get("state"):
            state_changes.append(
                {
                    "id": key,
                    "before": old.get("state"),
                    "after": new.get("state"),
                }
            )

    added_edges = [after_edges[key] for key in sorted(set(after_edges) - set(before_edges))]
    removed_edges = [before_edges[key] for key in sorted(set(before_edges) - set(after_edges))]
    changed_edges: list[dict[str, Any]] = []
    for key in sorted(set(before_edges) & set(after_edges)):
        old = before_edges[key]
        new = after_edges[key]
        fields = sorted(
            field
            for field in set(old) | set(new)
            if old.get(field) != new.get(field)
        )
        if fields:
            changed_edges.append(
                {"id": key, "fields": fields, "before": old, "after": new}
            )

    diff = {
        "contract_id": "kjds-project-graph-diff-v1",
        "status": (
            "changed"
            if any((added_nodes, removed_nodes, changed_nodes, added_edges, removed_edges, changed_edges))
            else "unchanged"
        ),
        "from": {
            "as_of": before.get("as_of"),
            "snapshot_sha256": before.get("snapshot_sha256"),
            "status": before.get("status"),
        },
        "to": {
            "as_of": after.get("as_of"),
            "snapshot_sha256": after.get("snapshot_sha256"),
            "status": after.get("status"),
        },
        "nodes": {
            "added": added_nodes,
            "removed": removed_nodes,
            "changed": changed_nodes,
        },
        "edges": {
            "added": added_edges,
            "removed": removed_edges,
            "changed": changed_edges,
        },
        "state_changes": state_changes,
        "external_write_allowed": False,
    }
    diff["diff_sha256"] = _stable_hash(diff)
    return diff


@router.get("/v1/project-graph/{project_id}/frontier")
def graph_frontier(
    project_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str | None = None,
    as_of: str | None = None,
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin", "monitor")
    return run(lambda: plan_proof_frontier(_graph(project_id, principal, store_ref, as_of)))


@router.get("/v1/project-graph/{project_id}/task-contract")
def graph_task_contract(
    project_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str | None = None,
    as_of: str | None = None,
):
    """Return the five-level WBS as a read-only projection of Harness.

    This endpoint exposes planning contracts without creating a second task
    ledger.  It never assigns work, acquires a lease, reserves budget, or
    reaches an external connector.
    """

    ensure_role(principal, "operator", "reviewer", "compliance", "admin", "monitor")
    return run(
        lambda: project_harness_graph(
            _graph(project_id, principal, store_ref, as_of)
        )
    )


@router.post("/v1/project-graph/{project_id}/release-contract/validate")
def validate_graph_release_contract(
    project_id: str,
    body: dict[str, Any],
    principal: Annotated[Principal, Depends(current_principal)] = None,
    store_ref: str = "ozon-primary",
    as_of: str | None = None,
):
    """Validate a wave packet against the release contract without publishing it.

    This is a read-only contract check.  A valid packet remains evidence for
    review only: it cannot mint a Permit, acquire a lease, enqueue an Agent,
    or perform an Ozon/platform write.
    """

    ensure_role(principal, "operator", "reviewer", "compliance", "admin", "monitor")
    ensure_store_scope(principal, store_ref)

    def validate() -> dict[str, Any]:
        graph = _graph(project_id, principal, store_ref, as_of)
        report = validate_release_packet(body)
        result: dict[str, Any] = {
            "contract_id": "kjds-project-graph-release-contract-validation-v1",
            "project_id": project_id,
            "validation": report.as_dict(),
            "source_snapshot_sha256": graph.get("snapshot_sha256"),
            "snapshot_binding": (
                "bound"
                if body.get("snapshot_id") == graph.get("snapshot_sha256")
                else "unbound"
            ),
            "claim_level": derive_claim_level(body),
            "release_allowed": False,
            "external_write_allowed": False,
        }
        if report.valid:
            result["packet"] = build_release_packet(body).as_dict()
        result["result_sha256"] = _stable_hash(result)
        return result

    return run(validate)


@router.get("/v1/graph/{project_id}/historical-frontier")
def historical_graph_frontier(
    project_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    as_of: str,
    store_ref: str | None = None,
):
    """Return the proof frontier known at an explicit historical cutoff."""

    ensure_role(principal, "operator", "reviewer", "compliance", "admin", "monitor")
    cutoff = _as_of(as_of)
    return run(
        lambda: plan_proof_frontier(
            _graph(project_id, principal, store_ref, cutoff.isoformat())
        )
    )


@router.get("/v1/project-graph/{project_id}/critical-path")
def graph_critical_path(
    project_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str | None = None,
    as_of: str | None = None,
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin", "monitor")
    return run(lambda: plan_proof_frontier(_graph(project_id, principal, store_ref, as_of))["critical_path"])


@router.get("/v1/project-graph/{project_id}/blockers")
def graph_blockers(
    project_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str | None = None,
    as_of: str | None = None,
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin", "monitor")
    return run(lambda: plan_proof_frontier(_graph(project_id, principal, store_ref, as_of))["blockers"])


@router.get("/v1/project-graph/{project_id}/proof-debt")
def graph_proof_debt(
    project_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str | None = None,
    as_of: str | None = None,
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin", "monitor")
    def project():
        result = plan_proof_frontier(_graph(project_id, principal, store_ref, as_of))
        return {
            "project_id": project_id,
            "status": result["status"],
            "items": result["blockers"],
            "count": len(result["blockers"]),
            "snapshot_sha256": result["snapshot_sha256"],
        }
    return run(project)


@router.get("/v1/project-graph/{project_id}/next-wave")
def graph_next_wave(
    project_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
    as_of: str | None = None,
    max_tasks: int = 8,
):
    """Compile the next safe wave as a read-only control-tower projection.

    This intentionally mirrors the dispatch planner's selection rules without
    persisting a proposal, acquiring a lease, reserving budget, or invoking a
    TeamAgent/provider.  A caller can therefore render the next wave on a
    dashboard while the actual dispatch path remains separately governed.
    """

    ensure_role(principal, "operator", "reviewer", "compliance", "admin", "monitor")
    ensure_store_scope(principal, store_ref)
    if max_tasks < 1 or max_tasks > 64:
        raise HTTPException(status_code=422, detail="max_tasks must be between 1 and 64")

    def project() -> dict[str, Any]:
        graph = _graph(project_id, principal, store_ref, as_of)
        projection = plan_proof_frontier(graph)
        contract_projection: dict[str, Any] | None = None
        contract_error: str | None = None
        try:
            contract_projection = project_harness_graph(graph)
        except ProjectTaskContractError as exc:
            contract_error = str(exc)
        contract_nodes = {
            str(item.get("node_id")): item
            for item in (contract_projection or {}).get("nodes", [])
            if isinstance(item, Mapping) and item.get("node_id") is not None
        }
        wip_report: Any | None = None
        wip_error: str | None = None
        if contract_nodes:
            try:
                wip_report = validate_wip(
                    tuple(WorkItem.from_mapping(item) for item in contract_nodes.values())
                )
            except ProjectTaskContractError as exc:
                wip_error = str(exc)
        frontier = sorted(
            projection.get("frontier", []),
            key=lambda item: (
                -float(item.get("priority", 0) or 0),
                -float(item.get("weight", 0) or 0),
                str(item.get("id", "")),
            ),
        )
        selected = frontier[:max_tasks]
        wip_blocked = bool(wip_report is not None and not wip_report.valid)
        if wip_blocked:
            selected = []
        tasks = [
            {
                "task_ref": item.get("id"),
                "title": item.get("label"),
                "priority": item.get("priority"),
                "weight": item.get("weight"),
                "dependencies": item.get("dependencies", []),
                "unresolved_dependencies": item.get("unresolved_dependencies", []),
                "next_safe_action": item.get("next_safe_action"),
                "agent_binding": None,
                "lease_binding": None,
                "dispatch_allowed": False,
                **_dispatch_task_contract(
                    project_id=project_id,
                    item=item,
                    contract_node=contract_nodes.get(str(item.get("id"))),
                    graph=graph,
                    projection=projection,
                ),
            }
            for item in selected
        ]
        result: dict[str, Any] = {
            "contract_id": "kjds-project-graph-next-wave-v1",
            "project_id": project_id,
            "store_ref": store_ref,
            "as_of": projection.get("as_of"),
            "source_snapshot_sha256": projection.get("snapshot_sha256"),
            "status": (
                "blocked_wip"
                if wip_blocked
                else "proposed" if tasks else str(projection.get("status", "NO_DATA")).lower()
            ),
            "frontier": frontier,
            "critical_path": projection.get("critical_path", []),
            "minimum_blocker_set": projection.get("blockers", []),
            "tasks": tasks,
            "task_contract": {
                "status": (
                    "blocked_wip"
                    if wip_blocked
                    else "valid"
                    if contract_projection and contract_projection.get("validation", {}).get("valid")
                    else "blocked" if contract_projection else "unavailable"
                ),
                "projection_sha256": (contract_projection or {}).get("projection_sha256"),
                "validation": (contract_projection or {}).get("validation"),
                "error": contract_error,
                "wip": (
                    {
                        "valid": wip_report.valid,
                        "counts": dict(wip_report.counts),
                        "violations": list(wip_report.violations),
                        "active_task_ids": list(wip_report.active_task_ids),
                        "snapshot_sha256": wip_report.snapshot_sha256,
                    }
                    if wip_report is not None
                    else None
                ),
                "wip_error": wip_error,
            },
            "projection_only": True,
            "dispatch_allowed": False,
            "external_write_allowed": False,
        }
        result["projection_sha256"] = _stable_hash(result)
        return result

    return run(project)


@router.get("/v1/project-graph/{project_id}/replay")
def graph_replay(
    project_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str | None = None,
    as_of: str | None = None,
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin", "monitor")
    return run(lambda: plan_proof_frontier(_graph(project_id, principal, store_ref, as_of))["snapshot"])


@router.get("/v1/project-graph/{project_id}/diff")
def graph_diff(
    project_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    from_as_of: str | None = None,
    to_as_of: str | None = None,
    as_of: str | None = None,
    store_ref: str | None = None,
):
    """Compare two immutable graph frontiers at explicit cutoffs.

    A baseline is mandatory.  Returning an empty diff for a missing baseline
    would make a current snapshot look historically complete, so the API
    fails validation instead.
    """

    ensure_role(principal, "operator", "reviewer", "compliance", "admin", "monitor")

    def compare() -> dict[str, Any]:
        if from_as_of is None:
            raise ValueError("from_as_of is required for a graph diff")
        before_cutoff = _as_of(from_as_of)
        after_cutoff = _as_of(to_as_of or as_of)
        if after_cutoff < before_cutoff:
            raise ValueError("to_as_of must not precede from_as_of")
        before = plan_proof_frontier(
            _graph(project_id, principal, store_ref, before_cutoff.isoformat())
        )
        after = plan_proof_frontier(
            _graph(project_id, principal, store_ref, after_cutoff.isoformat())
        )
        return _graph_diff(before, after)

    return run(compare)


@router.post("/v1/project-graph/{project_id}/signal")
def graph_signal(
    project_id: str,
    body: ProjectGraphSignalInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    """Record a verifier-backed signal through the existing Harness authority."""

    ensure_role(principal, "monitor", "admin")
    ensure_store_scope(principal, body.store_ref)

    def record() -> dict[str, Any]:
        observed_at = body.observed_at
        if observed_at.tzinfo is None:
            raise ValueError("observed_at must include a timezone")
        observed_at = observed_at.astimezone(UTC)
        if observed_at > datetime.now(UTC):
            raise ValueError("observed_at cannot be in the future")
        graph = _graph(project_id, principal, body.store_ref, observed_at.isoformat())
        if body.expected_snapshot_sha256 and body.expected_snapshot_sha256.lower() != str(
            graph.get("snapshot_sha256") or ""
        ).lower():
            raise ValueError("signal snapshot is stale; refresh the project graph")
        node_ids = {
            str(item.get("id"))
            for item in graph.get("nodes", [])
            if isinstance(item, dict) and item.get("id") is not None
        }
        task_ids = {
            str(item.get("id"))
            for item in graph.get("tasks", [])
            if isinstance(item, dict) and item.get("id") is not None
        }
        if body.node_id and body.node_id not in node_ids:
            raise KeyError("graph node not found in authorized project")
        if body.task_id and body.task_id not in task_ids:
            raise KeyError("graph task not found in authorized project")
        # A missing key is upgraded to a deterministic key derived from the
        # verifier input.  This preserves old clients while ensuring retries
        # resolve to one observation row in the Harness.
        idempotency_key = body.idempotency_key or (
            f"signal:{project_id}:{body.signal_type}:{body.node_id or body.task_id or 'project'}:"
            f"{body.input_sha256.lower()}"
        )
        scope = {
            "tenant_ref": principal.tenant_ref,
            "entity_ref": (graph.get("scope") or {}).get("entity_ref"),
            "store_ref": body.store_ref,
            "signal_type": body.signal_type,
            "node_id": body.node_id,
            "idempotency_key": idempotency_key,
        }
        payload = {
            "project_id": project_id,
            "task_id": body.task_id,
            "verifier_id": body.verifier_id,
            "verifier_version": body.verifier_version,
            "source": f"project-graph-signal/{body.signal_type}",
            "scope": scope,
            "state": body.state,
            "summary": body.summary,
            "artifact_ref": body.artifact_ref,
            "evidence_ref": body.evidence_ref,
            "input_sha256": body.input_sha256.lower(),
            "observed_at": observed_at.isoformat(),
            "store_ref": body.store_ref,
        }
        observation = runtime.agent_harness.record_observation(
            payload,
            principal=principal,
        )
        # Re-evaluate at the signal cutoff so the response is a replayable
        # projection rather than a claim that the signal changed a node.
        projection = plan_proof_frontier(
            _graph(project_id, principal, body.store_ref, observed_at.isoformat())
        )
        return {
            "contract_id": "kjds-project-graph-signal-v1",
            "status": "recorded",
            "signal": {
                "signal_type": body.signal_type,
                "node_id": body.node_id,
                "task_id": body.task_id,
                "observed_at": observed_at.isoformat(),
                "idempotency_key": idempotency_key,
            },
            "observation": observation,
            "projection": projection,
            "node_binding": "bound" if body.node_id and body.task_id else "unbound",
            "external_write_allowed": False,
        }

    return run(record)


@router.post("/v1/project-graph/{project_id}/dispatch-wave")
def dispatch_wave(
    project_id: str,
    body: DispatchWaveInput,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
    as_of: str | None = None,
):
    """Compile a bounded dependency-free wave as a proposal.

    Queue submission, lease acquisition and provider invocation remain owned
    by TeamAgent routes.  This endpoint only produces a deterministic plan.
    """

    ensure_role(principal, "operator", "reviewer", "admin", "monitor")
    ensure_store_scope(principal, store_ref)

    def propose() -> dict[str, Any]:
        graph = _graph(project_id, principal, store_ref, as_of)
        if body.expected_snapshot_sha256 and body.expected_snapshot_sha256.lower() != str(
            graph.get("snapshot_sha256") or ""
        ).lower():
            raise ValueError("dispatch snapshot is stale; refresh the project graph")
        projection = plan_proof_frontier(graph)
        task_contract_projection: dict[str, Any] | None = None
        task_contract_error: str | None = None
        try:
            task_contract_projection = project_harness_graph(graph)
        except ProjectTaskContractError as exc:
            # A legacy or incomplete graph can still produce a proof proposal,
            # but the missing WBS contract must remain explicit in the packet.
            task_contract_error = str(exc)
        contract_nodes = {
            str(item.get("node_id")): item
            for item in (task_contract_projection or {}).get("nodes", [])
            if isinstance(item, Mapping) and item.get("node_id") is not None
        }
        wip_report: Any | None = None
        wip_error: str | None = None
        if contract_nodes:
            try:
                wip_report = validate_wip(
                    tuple(WorkItem.from_mapping(item) for item in contract_nodes.values())
                )
            except ProjectTaskContractError as exc:
                wip_error = str(exc)
        proposal_key = body.idempotency_key or (
            f"dispatch:{project_id}:{store_ref}:{body.expected_head or 'current'}:"
            f"{body.max_tasks}:{body.budget_units or 'unbounded'}"
        )
        request_sha256 = _proposal_request_hash(
            project_id=project_id,
            tenant_ref=principal.tenant_ref,
            store_ref=store_ref,
            kind="dispatch-wave",
            idempotency_key=proposal_key,
            request={
                "max_tasks": body.max_tasks,
                "expected_head": body.expected_head,
                "expected_snapshot_sha256": body.expected_snapshot_sha256,
                "expected_revision": body.expected_revision,
                "budget_units": body.budget_units,
                "mode": body.mode,
                "as_of": as_of,
            },
        )
        current_head = str(
            (graph.get("project") or {}).get("baseline_sha256")
            or projection.get("snapshot_sha256")
        )
        if body.expected_head and body.expected_head not in {
            current_head,
            projection.get("snapshot_sha256"),
        }:
            stale_proposal = {
                "contract_id": "kjds-project-graph-dispatch-wave-v1",
                "status": "stale_request",
                "reason": "expected_head_does_not_match_snapshot",
                "expected_head": body.expected_head,
                "current_head": current_head,
                "snapshot_sha256": projection.get("snapshot_sha256"),
                "graph_snapshot_sha256": projection.get("snapshot_sha256"),
                "idempotency_key": proposal_key,
                "request_sha256": request_sha256,
                "tasks": [],
                "dispatch_allowed": False,
                "external_write_allowed": False,
            }
            stale_proposal["proposal_sha256"] = _stable_hash(stale_proposal)
            return _persist_graph_proposal(
                project_id=project_id,
                principal=principal,
                store_ref=store_ref,
                graph=graph,
                kind="dispatch-wave",
                proposal=stale_proposal,
                request_sha256=request_sha256,
                idempotency_key=proposal_key,
                expected_revision=body.expected_revision,
                observed_at=_as_of(as_of),
            )
        frontier = sorted(
            projection.get("frontier", []),
            key=lambda item: (
                -float(item.get("priority", 0) or 0),
                -float(item.get("weight", 0) or 0),
                str(item.get("id", "")),
            ),
        )
        selected: list[dict[str, Any]] = []
        remaining_budget = body.budget_units
        for item in frontier:
            if len(selected) >= body.max_tasks:
                break
            weight = Decimal(str(item.get("weight", 0) or 0))
            if remaining_budget is not None and weight > remaining_budget:
                continue
            selected.append(item)
            if remaining_budget is not None:
                remaining_budget -= weight
        wip_blocked = bool(wip_report is not None and not wip_report.valid)
        if wip_blocked:
            selected = []
        status = "proposed" if selected else projection.get("status", "NO_DATA").lower()
        if wip_blocked:
            status = "blocked_wip"
        tasks = [
            {
                "task_ref": item.get("id"),
                "title": item.get("label"),
                "priority": item.get("priority"),
                "weight": item.get("weight"),
                "dependencies": item.get("dependencies", []),
                "unresolved_dependencies": item.get("unresolved_dependencies", []),
                "next_safe_action": item.get("next_safe_action"),
                "agent_binding": None,
                "lease_binding": None,
                "requires_idempotency_key": True,
                "requires_fresh_head": True,
                "requires_recovery_on_unknown_outcome": True,
                **_dispatch_task_contract(
                    project_id=project_id,
                    item=item,
                    contract_node=contract_nodes.get(str(item.get("id"))),
                    graph=graph,
                    projection=projection,
                ),
            }
            for item in selected
        ]
        proposal = {
            "contract_id": "kjds-project-graph-dispatch-wave-v1",
            "status": status,
            "project_id": project_id,
            "as_of": projection.get("as_of"),
            "graph_snapshot_sha256": projection.get("snapshot_sha256"),
            "tasks": tasks,
            "requested_max_tasks": body.max_tasks,
            "budget_units": body.budget_units,
            "remaining_budget_units": remaining_budget,
            "idempotency_key": proposal_key,
            "request_sha256": request_sha256,
            "expected_revision": body.expected_revision,
            "dispatch_allowed": False,
            "requires_team_agent_submission": bool(tasks),
            "recovery": {
                "required": projection.get("status") in {"BLOCKED", "STALE", "NO_DATA"},
                "actions": (
                    ["repair_or_refresh_graph_before_dispatch"]
                    if projection.get("status") in {"BLOCKED", "STALE", "NO_DATA"}
                    else []
                ),
            },
            "external_write_allowed": False,
            "task_contract": {
                "status": (
                    "blocked_wip"
                    if wip_blocked
                    else "valid"
                    if task_contract_projection and task_contract_projection.get("validation", {}).get("valid")
                    else "blocked" if task_contract_projection else "unavailable"
                ),
                "projection_sha256": (task_contract_projection or {}).get("projection_sha256"),
                "validation": (task_contract_projection or {}).get("validation"),
                "error": task_contract_error,
                "wip": (
                    {
                        "valid": wip_report.valid,
                        "counts": dict(wip_report.counts),
                        "violations": list(wip_report.violations),
                        "active_task_ids": list(wip_report.active_task_ids),
                        "snapshot_sha256": wip_report.snapshot_sha256,
                    }
                    if wip_report is not None
                    else None
                ),
                "wip_error": wip_error,
            },
        }
        proposal["proposal_sha256"] = _stable_hash(proposal)
        return _persist_graph_proposal(
            project_id=project_id,
            principal=principal,
            store_ref=store_ref,
            graph=graph,
            kind="dispatch-wave",
            proposal=proposal,
            request_sha256=request_sha256,
            idempotency_key=proposal_key,
            expected_revision=body.expected_revision,
            observed_at=_as_of(as_of),
        )

    return run(propose)


@router.post("/v1/project-graph/{project_id}/invalidate")
def invalidate_graph(
    project_id: str,
    body: InvalidateGraphInput,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
    as_of: str | None = None,
):
    """Evaluate an invalidation overlay and return its proof debt.

    Canonical graph rows are append-only and are not overwritten by this
    proposal endpoint.  A reviewed graph event can later be persisted by the
    graph authority with the returned proposal hash.
    """

    ensure_role(principal, "reviewer", "compliance", "admin")
    ensure_store_scope(principal, store_ref)

    def propose() -> dict[str, Any]:
        graph = _graph(project_id, principal, store_ref, as_of)
        if body.expected_snapshot_sha256 and body.expected_snapshot_sha256.lower() != str(
            graph.get("snapshot_sha256") or ""
        ).lower():
            raise ValueError(
                "invalidation snapshot is stale; refresh the project graph"
            )
        known = {
            str(item.get("id"))
            for item in graph.get("nodes", [])
            if isinstance(item, dict) and item.get("id") is not None
        }
        targets = tuple(dict.fromkeys((*body.target_node_ids, *body.node_ids)))
        request_sha256 = _proposal_request_hash(
            project_id=project_id,
            tenant_ref=principal.tenant_ref,
            store_ref=store_ref,
            kind="invalidation",
            idempotency_key=body.idempotency_key,
            request={
                "source_node_id": body.source_node_id,
                "target_node_ids": list(targets),
                "reason": body.reason,
                "expected_snapshot_sha256": body.expected_snapshot_sha256,
                "expected_revision": body.expected_revision,
                "compensation_action": body.compensation_action,
                "mode": body.mode,
                "as_of": as_of,
            },
        )
        if body.source_node_id not in known:
            raise KeyError("invalidation source node not found in authorized project")
        missing = sorted(set(targets) - known)
        if missing:
            raise ValueError("invalidation target node not found: " + ", ".join(missing))
        overlay = dict(graph)
        overlay["edges"] = list(graph.get("edges", [])) + [
            {
                "id": f"proposal-invalidates:{body.idempotency_key}:{target}",
                "source": body.source_node_id,
                "target": target,
                "relation": "invalidates",
                "derivation": "declared",
                "evidence_ref": None,
            }
            for target in targets
        ]
        projection = plan_proof_frontier(overlay)
        result = {
            "contract_id": "kjds-project-graph-invalidation-v1",
            "status": "proposed",
            "project_id": project_id,
            "source_node_id": body.source_node_id,
            "target_node_ids": list(targets),
            "reason": body.reason,
            "idempotency_key": body.idempotency_key,
            "request_sha256": request_sha256,
            "expected_revision": body.expected_revision,
            "graph_snapshot_sha256": graph.get("snapshot_sha256"),
            "expected_snapshot_sha256": body.expected_snapshot_sha256,
            "compensation_action": body.compensation_action
            or "recompute_invalidated_dependents_before_dispatch",
            "projection": projection,
            "recovery": {
                "required": True,
                "action": body.compensation_action
                or "recompute_invalidated_dependents_before_dispatch",
                "external_write_allowed": False,
            },
            "external_write_allowed": False,
        }
        result["proposal_sha256"] = _stable_hash(result)
        return _persist_graph_proposal(
            project_id=project_id,
            principal=principal,
            store_ref=store_ref,
            graph=graph,
            kind="invalidation",
            proposal=result,
            request_sha256=request_sha256,
            idempotency_key=body.idempotency_key,
            expected_revision=body.expected_revision,
            observed_at=_as_of(as_of),
        )

    return run(propose)


@router.get("/v1/project-graph/{project_id}/proposals")
def graph_proposals(
    project_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
    kind: Literal["dispatch-wave", "invalidation"] | None = None,
    limit: int = 100,
):
    """List immutable proposal ledger entries in the authorized graph scope."""

    ensure_role(principal, "operator", "reviewer", "compliance", "admin", "monitor")
    ensure_store_scope(principal, store_ref)

    def read() -> dict[str, Any]:
        graph = _graph(project_id, principal, store_ref, None)
        items = runtime.project_graph_proposal_ledger.history(
            tenant_id=principal.tenant_ref,
            project_id=project_id,
            entity_id=_proposal_entity_id(graph),
            store_ref=store_ref,
            kind=kind,
            limit=limit,
        )
        return {
            "contract_id": "kjds-project-graph-proposal-ledger-v1",
            "status": "valid" if items else "no_data",
            "project_id": project_id,
            "store_ref": store_ref,
            "kind": kind,
            "items": list(items),
            "count": len(items),
            "external_write_allowed": False,
        }

    return run(read)


@router.get("/v1/project-graph/{project_id}/proposals/replay")
def replay_graph_proposal(
    project_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    idempotency_key: str,
    kind: Literal["dispatch-wave", "invalidation"],
    store_ref: str = "ozon-primary",
):
    """Replay one persisted proposal by its scoped idempotency key."""

    ensure_role(principal, "operator", "reviewer", "compliance", "admin", "monitor")
    ensure_store_scope(principal, store_ref)

    def read() -> dict[str, Any]:
        graph = _graph(project_id, principal, store_ref, None)
        entry = runtime.project_graph_proposal_ledger.replay(
            tenant_id=principal.tenant_ref,
            project_id=project_id,
            entity_id=_proposal_entity_id(graph),
            store_ref=store_ref,
            kind=kind,
            idempotency_key=idempotency_key,
        )
        return {
            "contract_id": "kjds-project-graph-proposal-replay-v1",
            "status": "replayed",
            "project_id": project_id,
            "proposal": entry.get("payload"),
            "ledger": entry,
            "external_write_allowed": False,
        }

    return run(read)


@router.get("/v1/project-graph/{project_id}/proposals/{proposal_id}")
def graph_proposal(
    project_id: str,
    proposal_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
):
    """Read one immutable proposal after exact graph-scope authorization."""

    ensure_role(principal, "operator", "reviewer", "compliance", "admin", "monitor")
    ensure_store_scope(principal, store_ref)

    def read() -> dict[str, Any]:
        graph = _graph(project_id, principal, store_ref, None)
        entry = runtime.project_graph_proposal_ledger.get(
            proposal_id=proposal_id,
            tenant_id=principal.tenant_ref,
            project_id=project_id,
            store_ref=store_ref,
            entity_id=_proposal_entity_id(graph),
        )
        return {
            "contract_id": "kjds-project-graph-proposal-replay-v1",
            "status": "replayed",
            "project_id": project_id,
            "proposal": entry.get("payload"),
            "ledger": entry,
            "external_write_allowed": False,
        }

    return run(read)


@router.post("/v1/project-graph/{project_id}/heartbeat")
def project_heartbeat(
    project_id: str,
    body: ProjectHeartbeatInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin", "monitor")
    ensure_store_scope(principal, body.store_ref)

    def record():
        graph = _graph(project_id, principal, body.store_ref, None)
        graph_scope = graph.get("scope", {})
        graph_entity = graph_scope.get("entity_ref")
        if graph_entity and graph_entity != body.entity_ref:
            # Keep the heartbeat ledger bound to the graph's immutable
            # operating subject.  Accepting an arbitrary entity here would
            # create a heartbeat that cannot be reconciled with the project
            # snapshot and could mix scopes in later monitoring queries.
            raise PermissionError("heartbeat entity is outside project scope")
        graph_store = graph_scope.get("store_ref")
        if graph_store and graph_store != body.store_ref:
            raise PermissionError("heartbeat store is outside project scope")
        projection = plan_proof_frontier(graph)
        economic_claim_guard = evaluate_economic_guard(EconomicGuardInput(
            cash_available=body.cash_available,
            min_cash=body.min_cash,
            margin_rate=body.margin_rate,
            min_margin_rate=body.min_margin_rate,
            budget_remaining=body.budget_remaining,
            min_budget_remaining=body.min_budget_remaining,
        ))
        # ``head_verified`` and ``workspace_*`` used to be caller assertions.
        # Read the checkout from the API process itself so a worker cannot
        # claim a clean/current source tree by posting ``true`` flags.  A
        # failed probe remains an explicit hold condition; it never falls back
        # to the legacy request values.
        server_git = observe_server_git_worktree()
        # Queue, lease, receipt, evidence, readback, rollback, experiment and
        # economic facts are read only from the explicitly bound runtime
        # adapters.  The adapter returns blocked observations when a
        # deployment has not wired one; request claims are never consulted.
        authority_snapshot = observe_server_authority(
            _runtime_pm_authority_readers(),
            scope_key=_heartbeat_scope_key(
                principal=principal,
                entity_ref=body.entity_ref,
                store_ref=body.store_ref,
            ),
            economic_guard_reader=_runtime_pm_economic_reader(),
            git_observation=server_git,
            observed_at=server_git.observed_at,
        )
        heartbeat_input = HeartbeatInput.from_server_authority(
            authority_snapshot,
            head=body.head,
            graph_snapshot_sha256=projection["snapshot_sha256"],
            proof_ready=projection["status"] == "PROVEN",
        )
        authority_verified_fields, authority_unverified_fields, authority_flags = (
            _heartbeat_authority_fields(authority_snapshot, heartbeat_input)
        )
        authority_reasons = authority_snapshot.authority_reasons(
            as_of=authority_snapshot.observed_at
        )
        decision = evaluate_heartbeat(heartbeat_input)
        guard = heartbeat_input.economic_guard
        operating_snapshot = _operating_snapshot_from_heartbeat(
            project_id=project_id,
            graph=graph,
            projection=projection,
            server_git=server_git,
            authority_snapshot=authority_snapshot,
            decision=decision,
            guard=guard,
        )
        submitted_task_result = normalize_task_result(body.task_result)
        # The PM itself is responsible for carrying graph-derived debt and
        # dependencies.  A caller-supplied result may add detail, but it
        # cannot hide a blocker or invalidation discovered during this exact
        # heartbeat evaluation.
        invalidation_projection = projection.get("invalidations")
        derived_invalidated_nodes = (
            list(invalidation_projection.keys())
            if isinstance(invalidation_projection, dict)
            else list(invalidation_projection or ())
        )
        derived_task_result = normalize_task_result(
            {
                "new_blockers": projection.get("blockers", []),
                "invalidated_nodes": derived_invalidated_nodes,
                "next_dependencies": projection.get("frontier_ids", []),
            }
        )
        task_result = dict(submitted_task_result)
        task_result["new_blockers"] = [
            *derived_task_result["new_blockers"],
            *submitted_task_result["new_blockers"],
        ]
        task_result["invalidated_nodes"] = list(
            dict.fromkeys(
                [
                    *derived_task_result["invalidated_nodes"],
                    *submitted_task_result["invalidated_nodes"],
                ]
            )
        )
        task_result["next_dependencies"] = list(
            dict.fromkeys(
                [
                    *derived_task_result["next_dependencies"],
                    *submitted_task_result["next_dependencies"],
                ]
            )
        )
        task_result = normalize_task_result(task_result)
        heartbeat = runtime.project_heartbeat_store.record(
            project_id=project_id,
            tenant_id=principal.tenant_ref,
            entity_id=body.entity_ref,
            store_ref=body.store_ref,
            head=body.head,
            graph_snapshot_sha256=projection["snapshot_sha256"],
            status=decision.status,
            idempotency_key=body.idempotency_key,
            expected_revision=body.expected_revision,
            liveness_deadline=body.liveness_deadline,
            heartbeat_at=body.heartbeat_at,
            progress_cursor=body.progress_cursor,
            expected_next_event=body.expected_next_event,
            stuck_detector_version=body.stuck_detector_version,
            compensation_action=body.compensation_action,
            recovery_ref=body.recovery_ref,
            payload={
                "decision": {
                    "status": decision.status,
                    "reasons": list(decision.reasons),
                    "next_actions": list(decision.next_actions),
                    "recovery_actions": list(decision.recovery_actions),
                    "decision_sha256": decision.decision_sha256,
                },
                "proof_frontier": projection["frontier_ids"],
                "economic_guard": {
                    "status": guard.status,
                    "reasons": list(guard.reasons),
                    "snapshot_sha256": guard.snapshot_sha256,
                    "diagnostic_snapshot_sha256": economic_claim_guard.snapshot_sha256,
                    "source": "server_authority_snapshot",
                    "diagnostic_source": "caller_claim_diagnostic",
                },
                "operational_snapshot": {
                    "server_git": {
                        "status": server_git.status,
                        "head": server_git.head,
                        "worktree_clean": server_git.worktree_clean,
                        "status_sha256": server_git.status_sha256,
                        "observed_at": server_git.observed_at.isoformat(),
                        "reason": server_git.reason,
                        "snapshot_sha256": server_git.snapshot_sha256,
                    },
                    "authority_snapshot": authority_snapshot.as_dict(),
                    "authority_snapshot_sha256": authority_snapshot.snapshot_sha256,
                    "authority_status": authority_snapshot.status,
                    "authority_verified_fields": authority_verified_fields,
                    "authority_unverified_fields": authority_unverified_fields,
                    "authority_reasons": list(authority_reasons),
                    "head_verified": authority_flags["head_verified"],
                    "workspace_state_known": authority_flags["workspace_state_known"],
                    "workspace_clean": authority_flags["workspace_clean"],
                    # These legacy request fields remain visible for replay
                    # diagnostics, but are never promoted to server facts.
                    "caller_claims_ignored": {
                        "head_verified": body.head_verified,
                        "workspace_state_known": body.workspace_state_known,
                        "workspace_clean": body.workspace_clean,
                        "task_queue_known": body.task_queue_known,
                        "lease_snapshot_known": body.lease_snapshot_known,
                        "test_receipts_current": body.test_receipts_current,
                        "proof_receipts_current": body.proof_receipts_current,
                        "evidence_fresh": body.evidence_fresh,
                        "data_quality_valid": body.data_quality_valid,
                        "external_readback_passed": body.external_readback_passed,
                        "rollback_available": body.rollback_available,
                        "experiment_clear": body.experiment_clear,
                        "economic_state_known": body.economic_state_known,
                    },
                    "caller_claim_rejection_reasons": {
                        field: _UNOBSERVED_HEARTBEAT_REASONS[field]
                        for field in _UNOBSERVED_HEARTBEAT_FIELDS
                    },
                    "caller_economic_inputs_ignored": [
                        "cash_available",
                        "min_cash",
                        "margin_rate",
                        "min_margin_rate",
                        "budget_remaining",
                        "min_budget_remaining",
                    ],
                    **authority_flags,
                },
                "operating_snapshot": operating_snapshot.as_dict(),
                # Keep the standard Agent result inside the immutable
                # heartbeat payload.  This makes the PM decision replayable
                # together with changed files, evidence and dependencies.
                "task_result": task_result,
            },
        )
        return {
            "heartbeat": heartbeat,
            "decision": decision,
            "proof": projection,
            "task_result": task_result,
            "operating_snapshot": operating_snapshot.as_dict(),
            "server_observation": {
                "git": {
                    "status": server_git.status,
                    "head": server_git.head,
                    "worktree_clean": server_git.worktree_clean,
                    "status_sha256": server_git.status_sha256,
                    "observed_at": server_git.observed_at.isoformat(),
                    "reason": server_git.reason,
                    "snapshot_sha256": server_git.snapshot_sha256,
                },
                "source": "server",
                "caller_git_attestation_used": False,
                "authority_snapshot": authority_snapshot.as_dict(),
                "authority_snapshot_sha256": authority_snapshot.snapshot_sha256,
                "authority_status": authority_snapshot.status,
                "authority_verified_fields": authority_verified_fields,
                "authority_unverified_fields": authority_unverified_fields,
                "authority_reasons": list(authority_reasons),
                "caller_claims_ignored": {
                    field: getattr(body, field) for field in _UNOBSERVED_HEARTBEAT_FIELDS
                },
            },
            "replay": {
                "idempotency_key": heartbeat.get("idempotency_key"),
                "request_sha256": heartbeat.get("request_sha256"),
                "revision": heartbeat.get("revision"),
            },
        }

    return run(record)


@router.get("/v1/project-graph/{project_id}/heartbeat/latest")
def latest_project_heartbeat(
    project_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
):
    """Replay the latest scoped PM heartbeat without recomputing or mutating it."""

    ensure_role(principal, "operator", "reviewer", "compliance", "admin", "monitor")
    ensure_store_scope(principal, store_ref)

    def read() -> dict[str, Any]:
        graph = _graph(project_id, principal, store_ref, None)
        entity_ref = _proposal_entity_id(graph)
        heartbeat = runtime.project_heartbeat_store.latest(
            project_id=project_id,
            tenant_id=principal.tenant_ref,
            entity_id=entity_ref,
            store_ref=store_ref,
        )
        if heartbeat is None:
            return {
                "contract_id": "kjds-project-heartbeat-replay-v1",
                "status": "NO_DATA",
                "project_id": project_id,
                "entity_ref": entity_ref,
                "store_ref": store_ref,
                "heartbeat": None,
                "external_write_allowed": False,
            }
        payload = heartbeat.get("payload") if isinstance(heartbeat.get("payload"), Mapping) else {}
        operating = payload.get("operating_snapshot") if isinstance(payload, Mapping) else None
        return {
            "contract_id": "kjds-project-heartbeat-replay-v1",
            "status": "REPLAYED",
            "project_id": project_id,
            "entity_ref": entity_ref,
            "store_ref": store_ref,
            "heartbeat": heartbeat,
            "operating_snapshot": operating,
            "replay_sha256": _stable_hash(heartbeat),
            "external_write_allowed": False,
        }

    return run(read)
