from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from .security import Principal

CONTRACT_ID = "kjds-team-control-tower-v1"
SCHEMA_VERSION = "kjds-team-control-tower-v1"
FLOW_REFS = (
    "project_control_commercialization",
    "sku_closed_loop",
    "dual_engine_commercialization",
    "lg001_exact_scope",
)
ACTIVE_TASK_STATES = frozenset({"open", "acknowledged", "in_progress"})
ADVANCE_RESULTS = frozenset({"take", "done", "blocked", "escalate", "stop"})
TRUTH_STATES = frozenset(
    {"VERIFIED", "PARTIAL", "BLOCKED", "STALE", "CONFLICTED", "UNKNOWN"}
)
BENCHMARK_CONTRACT_ID = "kjds-strategic-benchmark-kernel-v1"
BENCHMARK_SCHEMA_VERSION = "kjds-strategic-benchmark-contracts-v1"
SETTLEMENT_CASH_CONTRACT_ID = (
    "kjds-native-exact-scope-settlement-cash-control-v1"
)
ENTERPRISE_AI_ERP_CONTRACT_ID = "kjds-enterprise-ai-erp-program-v1"
ENTERPRISE_AI_ERP_CONTRACT_VERSION = "1.0.0"
ENTERPRISE_AI_ERP_TRUSTED_REGISTRY_SHA256 = (
    "8ba3f6a2a3293a66416dd474223d538c7dc1ff5a3c57789c34d994be0aa26657"
)
ENTERPRISE_AI_ERP_TRUSTED_SOURCE_BUNDLE_SHA256 = (
    "8bd8d4092508308259f7b6916898d47572af6141875411dbf334f90a0c1a70b1"
)
ENTERPRISE_AI_ERP_TRUSTED_SNAPSHOT_SHA256 = (
    "e9eec2be33b0c7179e7fcd17d41a556969c9427794c2a1fe308ebb96fc0cdbf9"
)
ENTERPRISE_AI_ERP_PROJECTION_KEYS = (
    "squad_readiness",
    "role_conflicts",
    "parallel_execution",
    "integration_queue",
    "capacity_risk",
    "next_release_train",
)
_IDENTIFIER = re.compile(r"[A-Za-z0-9_.:-]+")
_SHA256 = re.compile(r"[0-9a-f]{64}")


class TeamControlTowerError(ValueError):
    """Raised when the team control contract cannot fail closed."""


class TeamControlTower:
    """Project one leadership brief and advance its one current action.

    The Module stores work only in the existing OperatingTask/Event authority.
    It never creates a parallel team-task ledger, business Fact, Approval,
    Permit, finance entry, or external platform action.
    """

    def __init__(
        self,
        *,
        expert_team: Any,
        operating_tasks: Any,
        scoped_evidence: Any | None = None,
        strategic_benchmark: Any | None = None,
        settlement_cash: Any | None = None,
        enterprise_ai_erp_program: Any | None = None,
        registry_path: str | Path | None = None,
        workstream_path: str | Path | None = None,
        benchmark_contract_path: str | Path | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        root = Path(__file__).resolve().parents[2]
        self.registry_path = Path(registry_path) if registry_path else (
            root / "docs" / "project" / "registries" / "team_control_tower_registry.json"
        )
        self.workstream_path = Path(workstream_path) if workstream_path else (
            root / "docs" / "project" / "registries" / "active_workstream_assignments.json"
        )
        self.benchmark_contract_path = (
            Path(benchmark_contract_path)
            if benchmark_contract_path
            else root
            / "docs"
            / "project"
            / "registries"
            / "strategic_benchmark_contracts.json"
        )
        self.expert_team = expert_team
        self.operating_tasks = operating_tasks
        self.scoped_evidence = scoped_evidence
        self.strategic_benchmark = strategic_benchmark
        self.settlement_cash = settlement_cash
        self.enterprise_ai_erp_program = enterprise_ai_erp_program
        self.clock = clock or (lambda: datetime.now(UTC))
        self.registry = self._read_json(self.registry_path, "team control registry")
        self.workstreams = self._read_json(
            self.workstream_path, "active workstream registry"
        )
        self.benchmark_contracts = self._read_json(
            self.benchmark_contract_path,
            "strategic benchmark contracts",
        )
        self._validate_registry(self.registry, self.benchmark_contracts)
        expected_ai_roles = set(
            self.registry["organization_model"]["ai_specialist_role_refs"]
        )
        actual_ai_roles = {
            str(item.get("role_id"))
            for item in self.expert_team.registry.get("specialist_roles", [])
        }
        expected_control_roles = set(
            self.registry["organization_model"]["control_role_refs"]
        )
        actual_control_roles = {
            str(item.get("role_id"))
            for item in self.expert_team.registry.get("control_roles", [])
        }
        if expected_ai_roles != actual_ai_roles:
            raise TeamControlTowerError(
                "AI specialist contracts must map one-to-one to expert team registry"
            )
        if expected_control_roles != actual_control_roles:
            raise TeamControlTowerError(
                "Control roles must map one-to-one to expert team registry"
            )
        required_lane_ids = {
            str(lane_id)
            for flow in self.registry["flows"]
            for lane_id in flow["source_lane_ids"]
        }
        campaign = self.registry["campaign_90d"]
        required_lane_ids.update(campaign["active_lane_ids"])
        required_lane_ids.update(campaign["preparation_only_lane_ids"])
        for phase in campaign["phases"]:
            required_lane_ids.update(phase["source_lane_ids"])
        for gate in self.registry["delivery_gate_profile"]["gates"]:
            required_lane_ids.update(gate["source_lane_ids"])
        self._validate_workstreams(
            self.workstreams,
            required_lane_ids=required_lane_ids,
        )
        self._flows = {
            str(item["flow_ref"]): item for item in self.registry["flows"]
        }
        self._lanes = {
            str(item["id"]): item for item in self.workstreams["lanes"]
        }
        self.registry_sha256 = self._hash(self.registry)
        self.workstream_sha256 = self._hash(self.workstreams)
        self.benchmark_contract_sha256 = self._hash(self.benchmark_contracts)

    def brief(
        self,
        *,
        principal: Principal,
        entity_scope: Mapping[str, Any],
        store_ref: str,
        as_of: str | datetime | None = None,
    ) -> dict[str, Any]:
        checked_at = self._datetime(as_of) if as_of is not None else self._now()
        scope = self._scope(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
        )
        if scope is None:
            unavailable = {
                name: self._unknown_projection(
                    name=name,
                    checked_at=checked_at,
                    reason_code="exact_scope_authority_unavailable",
                )
                for name in (
                    "organization_readiness",
                    "critical_path",
                    "top1_scorecard",
                    "cash_at_risk",
                    "delivery_gate",
                    *ENTERPRISE_AI_ERP_PROJECTION_KEYS,
                )
            }
            result = {
                "contract_id": CONTRACT_ID,
                "contract_version": str(self.registry["version"]),
                "status": "scope_invalid",
                "headline": "当前 exact-scope authority 不可用；总控未读取经营任务。",
                "scope": None,
                "as_of": self._iso(checked_at),
                "executive_summary": self._empty_summary(),
                "next_action": None,
                "flows": [self._unscoped_flow(item) for item in self.registry["flows"]],
                "conflicts": [],
                **unavailable,
                "decision_basis_sha256": None,
                "source_refs": self._source_refs(),
                "control_envelope": self._control_envelope(),
            }
            result["snapshot_sha256"] = self._hash(result)
            return result

        entity = self._entity_scope(scope)
        tasks = self.operating_tasks.tasks(
            limit=1000,
            principal=principal,
            entity_scope=entity,
            store_ref=store_ref,
            as_of=self._iso(checked_at),
        )
        team_tasks = [item for item in tasks if self._team_metadata(item) is not None]
        active_team_tasks = [
            item for item in team_tasks if item.get("status") in ACTIVE_TASK_STATES
        ]
        projected_flows = [
            self._project_flow(flow, team_tasks, checked_at)
            for flow in self.registry["flows"]
        ]
        team_snapshot = self.expert_team.snapshot()
        conflicts = self._conflicts(active_team_tasks)
        organization_readiness = self._organization_readiness(
            team_snapshot=team_snapshot,
            checked_at=checked_at,
        )
        enterprise_ai_erp = self._enterprise_ai_erp_projections(
            checked_at=checked_at
        )
        benchmark = self._benchmark_authority(
            principal=principal,
            scope=scope,
            store_ref=store_ref,
            checked_at=checked_at,
        )
        top1_scorecard = self._top1_scorecard(
            benchmark=benchmark,
            checked_at=checked_at,
        )
        settlement_cash = self._settlement_cash_authority(
            principal=principal,
            scope=scope,
            store_ref=store_ref,
            checked_at=checked_at,
        )
        cash_at_risk = self._cash_at_risk(
            benchmark=benchmark,
            settlement_cash=settlement_cash,
            checked_at=checked_at,
        )
        critical_path = self._critical_path(
            tasks=team_tasks,
            principal=principal,
            entity_scope=entity,
            store_ref=store_ref,
            checked_at=checked_at,
        )
        delivery_gate = self._delivery_gate(
            organization=organization_readiness,
            critical_path=critical_path,
            top1=top1_scorecard,
            cash=cash_at_risk,
            checked_at=checked_at,
        )
        decision_basis_sha256 = self._hash(
            {
                "scope": scope,
                "registry_sha256": self.registry_sha256,
                "workstream_sha256": self.workstream_sha256,
                "benchmark_contract_sha256": self.benchmark_contract_sha256,
                "flows": projected_flows,
                "conflicts": conflicts,
                "projection_sha256": {
                    "organization_readiness": self._decision_projection_sha256(
                        organization_readiness
                    ),
                    "critical_path": self._decision_projection_sha256(
                        critical_path
                    ),
                    "top1_scorecard": self._decision_projection_sha256(
                        top1_scorecard
                    ),
                    "cash_at_risk": self._decision_projection_sha256(
                        cash_at_risk
                    ),
                    "delivery_gate": self._decision_projection_sha256(
                        delivery_gate
                    ),
                    **{
                        name: self._decision_projection_sha256(projection)
                        for name, projection in enterprise_ai_erp.items()
                    },
                },
            }
        )
        next_action = self._next_action(
            scope=scope,
            flows=projected_flows,
            active_tasks=active_team_tasks,
            critical_path=critical_path,
            checked_at=checked_at,
            decision_basis_sha256=decision_basis_sha256,
        )
        awaiting_human = any(
            self._team_metadata(item).get("route_status")
            in {"dual_sign_gate_required", "human_authority_required"}
            for item in active_team_tasks
        )
        blocker_count = sum(len(item["blockers"]) for item in projected_flows)
        status = (
            "awaiting_human"
            if awaiting_human
            else "blocked"
            if conflicts
            else "attention_required"
            if blocker_count or active_team_tasks
            else "on_track"
        )
        summary = {
            "flow_count": len(projected_flows),
            "active_flow_count": sum(
                item["runtime_status"] in {"open", "acknowledged", "in_progress"}
                for item in projected_flows
            ),
            "blocked_flow_count": sum(bool(item["blockers"]) for item in projected_flows),
            "active_team_task_count": len(active_team_tasks),
            "overdue_task_count": sum(item["overdue"] for item in projected_flows),
            "conflict_count": len(conflicts),
            "human_binding_ready": bool(
                team_snapshot["operating_status"].get(
                    "registry_proves_human_appointment"
                )
            ),
        }
        result = {
            "contract_id": CONTRACT_ID,
            "contract_version": str(self.registry["version"]),
            "status": status,
            "headline": self._headline(status=status, next_action=next_action),
            "scope": scope,
            "as_of": self._iso(checked_at),
            "executive_summary": summary,
            "next_action": next_action,
            "flows": projected_flows,
            "conflicts": conflicts,
            "organization_readiness": organization_readiness,
            "critical_path": critical_path,
            "top1_scorecard": top1_scorecard,
            "cash_at_risk": cash_at_risk,
            "delivery_gate": delivery_gate,
            **enterprise_ai_erp,
            "decision_basis_sha256": decision_basis_sha256,
            "team": {
                "leader": team_snapshot["leader"]["role_id"],
                "specialist_count": team_snapshot["counts"]["specialists"],
                "control_role_count": team_snapshot["counts"]["control_roles"],
                "escalation_chain": list(self.registry["escalation_chain"]),
            },
            "source_refs": self._source_refs(),
            "control_envelope": self._control_envelope(),
        }
        result["snapshot_sha256"] = self._hash(result)
        return result

    def advance(
        self,
        *,
        principal: Principal,
        entity_scope: Mapping[str, Any],
        store_ref: str,
        continuation: str,
        result: str,
        rationale: str,
        evidence_ids: Sequence[str],
        idempotency_key: str,
        as_of: str | datetime | None = None,
    ) -> dict[str, Any]:
        continuation = self._sha256(continuation, "continuation")
        result = self._identifier(result, "result")
        if result not in ADVANCE_RESULTS:
            raise TeamControlTowerError("Unsupported team control result")
        rationale = str(rationale).strip()
        if not rationale or len(rationale) > 2000:
            raise TeamControlTowerError("rationale is required and must be bounded")
        idempotency_key = self._identifier(idempotency_key, "idempotency_key")
        evidence = self._identifiers(evidence_ids, "evidence_id", maximum=20)
        checked_at = self._datetime(as_of) if as_of is not None else self._now()
        command_sha256 = self._hash(
            {
                "continuation": continuation,
                "result": result,
                "rationale": rationale,
                "evidence_ids": list(evidence),
            }
        )
        scoped_tasks = self._scoped_tasks(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            checked_at=checked_at,
        )
        replay = self._idempotent_receipt(
            tasks=scoped_tasks,
            idempotency_key=idempotency_key,
            command_sha256=command_sha256,
        )
        if replay is not None:
            return replay

        brief = self.brief(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=checked_at,
        )
        action = brief.get("next_action")
        if action is None or continuation != action.get("continuation"):
            raise TeamControlTowerError("Team control continuation is stale")
        if result not in action["allowed_results"]:
            raise TeamControlTowerError("Result is not allowed for the current action")
        if action.get("evidence_required") and not evidence:
            raise TeamControlTowerError("Current action requires exact-scope Evidence")
        if result in {"done", "stop"} and not evidence:
            raise TeamControlTowerError("Completing or stopping work requires Evidence")
        self._verify_evidence(
            evidence_ids=list(evidence),
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            checked_at=checked_at,
        )

        target = action["target"]
        if target["type"] == "flow":
            task = self._open_flow_task(
                flow=self._flows[target["flow_ref"]],
                principal=principal,
                scope=brief["scope"],
                continuation=continuation,
                rationale=rationale,
                evidence_ids=list(evidence),
                idempotency_key=idempotency_key,
                command_sha256=command_sha256,
                checked_at=checked_at,
            )
            outcome = "accepted"
            event = None
        elif target["type"] == "campaign_phase":
            phase = self._campaign_phase(target["phase_ref"])
            task = self._open_campaign_task(
                phase=phase,
                principal=principal,
                scope=brief["scope"],
                continuation=continuation,
                rationale=rationale,
                evidence_ids=list(evidence),
                idempotency_key=idempotency_key,
                command_sha256=command_sha256,
                checked_at=checked_at,
            )
            outcome = "accepted"
            event = None
        else:
            task, event = self._advance_task(
                task=target["task"],
                result=result,
                rationale=rationale,
                evidence_ids=list(evidence),
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store_ref,
                continuation=continuation,
                idempotency_key=idempotency_key,
                command_sha256=command_sha256,
                checked_at=checked_at,
            )
            outcome = "accepted"
        receipt = self._receipt(
            outcome=outcome,
            task=task,
            event=event,
            continuation=continuation,
            idempotency_key=idempotency_key,
            command_sha256=command_sha256,
        )
        return receipt

    def _open_campaign_task(
        self,
        *,
        phase: Mapping[str, Any],
        principal: Principal,
        scope: Mapping[str, Any],
        continuation: str,
        rationale: str,
        evidence_ids: list[str],
        idempotency_key: str,
        command_sha256: str,
        checked_at: datetime,
    ) -> dict[str, Any]:
        campaign = self.registry["campaign_90d"]
        route = self.expert_team.route(
            task_ref=f"CAMPAIGN-{phase['phase_ref']}",
            task_type="product_management",
            market=str(campaign["market"]),
            platform=str(campaign["platform"]),
            risk_level="L1",
            evidence_refs=evidence_ids,
        )
        if route["status"] == "blocked_scope":
            raise TeamControlTowerError("Campaign execution scope is not admitted")
        task_scope = {
            **scope,
            "dimensions": {
                "control_tower_contract": CONTRACT_ID,
                "campaign_ref": campaign["campaign_ref"],
                "phase_ref": phase["phase_ref"],
            },
        }
        metadata = {
            "contract_id": CONTRACT_ID,
            "campaign_ref": campaign["campaign_ref"],
            "phase_ref": phase["phase_ref"],
            "route_status": route["status"],
            "risk_level": "L1",
            "continuation": continuation,
            "last_command_idempotency_key": idempotency_key,
            "last_command_sha256": command_sha256,
            "last_result": "take",
            "last_rationale": rationale,
        }
        blockers = sorted(
            {
                blocker
                for lane_id in phase["source_lane_ids"]
                for blocker in self._lane_blockers(self._lanes[lane_id])
            }
        )
        return self.operating_tasks.ensure_internal_task(
            task_kind=(
                f"team_control:campaign:{campaign['campaign_ref']}:"
                f"{phase['phase_ref']}"
            ),
            scope=task_scope,
            title=f"90 天战役 · {phase['title']}",
            severity="critical" if phase["day_from"] == 1 else "high",
            owner=str(phase["owner_role"]),
            evidence_ids=evidence_ids,
            snapshot={
                "control_tower": metadata,
                "expert_route": route,
                "blockers": blockers,
                "next_action": (
                    f"补齐 {phase['title']} 的 exact-scope Evidence，"
                    "完成独立复核并请求正式 Gate 决定。"
                ),
                "objective": phase["title"],
                "success_evidence": list(phase["required_evidence"]),
                "gate_refs": list(phase["gate_refs"]),
                "stop_conditions": list(phase["stop_conditions"]),
                "task_completion_proves_gate_pass": False,
            },
            actor_id=principal.actor_id,
            cooldown_minutes=525_600,
            as_of=self._iso(checked_at),
        )

    def _open_flow_task(
        self,
        *,
        flow: Mapping[str, Any],
        principal: Principal,
        scope: Mapping[str, Any],
        continuation: str,
        rationale: str,
        evidence_ids: list[str],
        idempotency_key: str,
        command_sha256: str,
        checked_at: datetime,
    ) -> dict[str, Any]:
        route = self.expert_team.route(
            task_ref=str(flow["default_task_ref"]),
            task_type=str(flow["default_task_type"]),
            market=str(flow["market"]),
            platform=str(flow["platform"]),
            risk_level=str(flow["risk_level"]),
            evidence_refs=evidence_ids,
        )
        if route["status"] == "blocked_scope":
            raise TeamControlTowerError("Expert task execution scope is not admitted")
        task_scope = {
            **scope,
            "dimensions": {
                "control_tower_contract": CONTRACT_ID,
                "flow_ref": flow["flow_ref"],
                "task_ref": flow["default_task_ref"],
            },
        }
        metadata = {
            "contract_id": CONTRACT_ID,
            "flow_ref": flow["flow_ref"],
            "task_ref": flow["default_task_ref"],
            "route_status": route["status"],
            "risk_level": flow["risk_level"],
            "continuation": continuation,
            "last_command_idempotency_key": idempotency_key,
            "last_command_sha256": command_sha256,
            "last_result": "take",
            "last_rationale": rationale,
        }
        return self.operating_tasks.ensure_internal_task(
            task_kind=f"team_control:{flow['flow_ref']}:{flow['default_task_ref']}",
            scope=task_scope,
            title=f"团队协作 · {flow['display_title']}",
            severity=str(flow["severity"]),
            owner=str(route["accountable_specialist"]),
            evidence_ids=evidence_ids,
            snapshot={
                "control_tower": metadata,
                "expert_route": route,
                "blockers": list(route["blockers"]),
                "next_action": flow["default_next_action"],
                "objective": flow["objective"],
                "success_evidence": list(flow["success_evidence"]),
            },
            actor_id=principal.actor_id,
            cooldown_minutes=525_600,
            as_of=self._iso(checked_at),
        )

    def _advance_task(
        self,
        *,
        task: Mapping[str, Any],
        result: str,
        rationale: str,
        evidence_ids: list[str],
        principal: Principal,
        entity_scope: Mapping[str, Any],
        store_ref: str,
        continuation: str,
        idempotency_key: str,
        command_sha256: str,
        checked_at: datetime,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        payload = {
            "team_control_command": {
                "contract_id": CONTRACT_ID,
                "continuation": continuation,
                "idempotency_key": idempotency_key,
                "command_sha256": command_sha256,
                "result": result,
            }
        }
        status = str(task["status"])
        if result == "take":
            event_type = "acknowledge" if status == "open" else "start"
        elif result == "done":
            event_type = "resolve"
        elif result == "stop":
            event_type = "dismiss"
        else:
            metadata = dict(self._team_metadata(task) or {})
            metadata.update(
                {
                    "last_command_idempotency_key": idempotency_key,
                    "last_command_sha256": command_sha256,
                    "last_result": result,
                    "last_rationale": rationale,
                }
            )
            snapshot = dict(task["snapshot"])
            snapshot["control_tower"] = metadata
            snapshot["coordination_state"] = (
                "escalation_requested" if result == "escalate" else "blocked"
            )
            refreshed = self.operating_tasks.ensure_internal_task(
                task_kind=str(task["metric_id"]).removeprefix("internal:"),
                scope=dict(task["scope"]),
                title=str(task["title"]),
                severity=str(task["severity"]),
                owner=str(task["owner"]),
                evidence_ids=evidence_ids,
                snapshot=snapshot,
                actor_id=principal.actor_id,
                cooldown_minutes=525_600,
                as_of=self._iso(checked_at),
            )
            return refreshed, None
        transition = self.operating_tasks.append_task_event(
            str(task["id"]),
            event_type=event_type,
            reason=rationale,
            evidence_ids=evidence_ids,
            actor_id=principal.actor_id,
            principal=principal,
            entity_scope=dict(entity_scope),
            store_ref=store_ref,
            payload=payload,
        )
        return transition["task"], transition["event"]

    def _project_flow(
        self,
        flow: Mapping[str, Any],
        active_tasks: Sequence[Mapping[str, Any]],
        checked_at: datetime,
    ) -> dict[str, Any]:
        lane_rows = [self._lanes[item] for item in flow["source_lane_ids"]]
        assignments = [
            {
                "lane_id": lane["id"],
                "lane_name": lane["name"],
                "accountable_role": lane["accountable_role"],
                "current_task": self._clone(lane.get("current_task")),
                "next_task_id": lane.get("next_task_id"),
            }
            for lane in lane_rows
        ]
        flow_tasks = [
            task
            for task in active_tasks
            if self._team_metadata(task).get("flow_ref") == flow["flow_ref"]
        ]
        active_flow_tasks = [
            task for task in flow_tasks if task.get("status") in ACTIVE_TASK_STATES
        ]
        blockers = sorted(
            {
                blocker
                for lane in lane_rows
                for blocker in [
                    *(lane.get("blocked_on") or []),
                    *((lane.get("current_task") or {}).get("blocked_on") or []),
                ]
            }
            | {
                blocker
                for task in flow_tasks
                for blocker in task.get("snapshot", {}).get("blockers", [])
            }
        )
        selected = (
            self._rank_tasks(active_flow_tasks, checked_at)[0]
            if active_flow_tasks
            else max(
                flow_tasks,
                key=lambda item: (str(item.get("updated_at")), str(item.get("id"))),
                default=None,
            )
        )
        due_at = self._due_at(selected) if selected else None
        overdue = bool(
            selected
            and selected.get("status") in ACTIVE_TASK_STATES
            and due_at
            and checked_at > due_at
        )
        return {
            "flow_ref": flow["flow_ref"],
            "display_title": flow["display_title"],
            "objective": flow["objective"],
            "declared_state": flow["declared_state"],
            "runtime_status": selected["status"] if selected else (
                "blocked" if blockers else "ready_for_dispatch"
            ),
            "accountable_role": selected["owner"] if selected else flow["accountable_role"],
            "risk_level": flow["risk_level"],
            "current_operating_task": self._task_summary(selected),
            "source_assignments": assignments,
            "blockers": blockers,
            "overdue": overdue,
            "due_at": self._iso(due_at) if due_at else None,
            "default_next_action": flow["default_next_action"],
            "success_evidence": list(flow["success_evidence"]),
        }

    def _organization_readiness(
        self,
        *,
        team_snapshot: Mapping[str, Any],
        checked_at: datetime,
    ) -> dict[str, Any]:
        model = self.registry["organization_model"]
        roles = model["core_roles"]
        verified = [
            item
            for item in roles
            if item["binding"]["status"] == "verified_active"
        ]
        missing_primary = [
            item["role_id"]
            for item in roles
            if not item["binding"].get("primary_human_ref")
        ]
        missing_alternate = [
            item["role_id"]
            for item in roles
            if not item["binding"].get("alternate_human_ref")
        ]
        missing_conflict = [
            item["role_id"]
            for item in roles
            if not item["binding"].get("conflict_attestation_evidence_ref")
        ]
        status = "VERIFIED" if len(verified) == len(roles) else "UNKNOWN"
        reason_codes = [] if status == "VERIFIED" else [
            "human_appointments_not_evidenced",
            "alternates_not_evidenced",
            "professional_qualifications_not_evidenced",
            "expert_pool_roster_not_evidenced",
        ]
        projection = {
            "status": status,
            "reason_codes": reason_codes,
            "contract_counts": {
                "human_core_required": model["human_core_required"],
                "ai_specialists_required": model["ai_specialists_required"],
                "expert_pool_target": self._clone(model["expert_pool_target"]),
                "independent_control_roles_required": model[
                    "independent_control_roles_required"
                ],
            },
            "registry_counts": {
                "human_core_contracts": len(roles),
                "ai_specialist_contracts": team_snapshot["counts"]["specialists"],
                "expert_pool_categories": len(model["expert_pool_categories"]),
                "control_role_contracts": team_snapshot["counts"]["control_roles"],
            },
            "verified_bindings": {
                "human_core": len(verified),
                "expert_pool": None,
                "control_roles": 0,
            },
            "missing": {
                "primary_role_refs": missing_primary,
                "alternate_role_refs": missing_alternate,
                "qualification_role_refs": [
                    item["role_id"]
                    for item in roles
                    if not item["binding"].get("professional_scope_evidence_refs")
                ],
                "conflict_attestation_role_refs": missing_conflict,
            },
            "blockers": reason_codes,
            "source_refs": [
                {
                    "ref": "team_control_tower_registry.organization_model",
                    "sha256": self.registry_sha256,
                },
                {
                    "ref": "global_expert_team_registry",
                    "sha256": self.expert_team.registry_sha256,
                },
            ],
            "as_of": self._iso(checked_at),
        }
        return self._seal_projection(projection)

    def _benchmark_authority(
        self,
        *,
        principal: Principal,
        scope: Mapping[str, str],
        store_ref: str,
        checked_at: datetime,
    ) -> dict[str, Any]:
        if self.strategic_benchmark is None:
            return {
                "status": "UNKNOWN",
                "reason_codes": ["strategic_benchmark_authority_unavailable"],
                "snapshot": None,
                "groups": [],
            }
        items: list[Mapping[str, Any]] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        try:
            for _ in range(1000):
                listing = self.strategic_benchmark.list(
                    principal=principal,
                    store_ref=store_ref,
                    as_of=checked_at,
                    limit=100,
                    cursor=cursor,
                    expected_scope_authority_sha256=scope[
                        "scope_authority_sha256"
                    ],
                )
                if (
                    not isinstance(listing, Mapping)
                    or listing.get("contract_id") != BENCHMARK_CONTRACT_ID
                ):
                    raise TeamControlTowerError(
                        "Strategic benchmark list contract drift"
                    )
                page = listing.get("items")
                if not isinstance(page, list) or any(
                    not isinstance(item, Mapping) for item in page
                ):
                    raise TeamControlTowerError(
                        "Strategic benchmark list shape drift"
                    )
                items.extend(page)
                next_cursor = listing.get("next_cursor")
                if next_cursor is None:
                    break
                next_cursor = self._opaque(
                    next_cursor,
                    "strategic_benchmark_cursor",
                )
                if next_cursor in seen_cursors:
                    raise TeamControlTowerError(
                        "Strategic benchmark cursor replay drift"
                    )
                seen_cursors.add(next_cursor)
                cursor = next_cursor
            else:
                raise TeamControlTowerError(
                    "Strategic benchmark pagination exceeds safety bound"
                )
        except TeamControlTowerError:
            raise
        except (PermissionError, RuntimeError, ValueError) as exc:
            return {
                "status": "CONFLICTED",
                "reason_codes": ["strategic_benchmark_authority_drift"],
                "detail": type(exc).__name__,
                "snapshot": None,
                "groups": [],
            }
        if not items:
            return {
                "status": "UNKNOWN",
                "reason_codes": ["strategic_benchmark_no_data"],
                "snapshot": None,
                "groups": [],
            }
        try:
            ranked = sorted(
                items,
                key=lambda item: (
                    self._datetime(item["as_of"]),
                    self._datetime(item["created_at"]),
                    str(item["snapshot_ref"]),
                ),
                reverse=True,
            )
        except (KeyError, TypeError, TeamControlTowerError) as exc:
            raise TeamControlTowerError("Strategic benchmark snapshot shape drift") from exc
        latest_as_of = self._datetime(ranked[0]["as_of"])
        latest = [item for item in ranked if self._datetime(item["as_of"]) == latest_as_of]
        if len(latest) != 1:
            return {
                "status": "CONFLICTED",
                "reason_codes": ["multiple_latest_benchmark_snapshots"],
                "snapshot": None,
                "groups": [],
            }
        snapshot_ref = self._identifier(latest[0].get("snapshot_ref"), "snapshot_ref")
        try:
            projection = self.strategic_benchmark.get(
                principal=principal,
                store_ref=store_ref,
                as_of=checked_at,
                snapshot_ref=snapshot_ref,
                expected_scope_authority_sha256=scope[
                    "scope_authority_sha256"
                ],
            )
        except (PermissionError, RuntimeError, ValueError) as exc:
            return {
                "status": "CONFLICTED",
                "reason_codes": ["strategic_benchmark_authority_drift"],
                "detail": type(exc).__name__,
                "snapshot": None,
                "groups": [],
            }
        if not isinstance(projection, Mapping) or projection.get("contract_id") != BENCHMARK_CONTRACT_ID:
            raise TeamControlTowerError("Strategic benchmark projection contract drift")
        snapshot = projection.get("snapshot")
        groups = projection.get("groups")
        if not isinstance(snapshot, Mapping) or not isinstance(groups, list):
            raise TeamControlTowerError("Strategic benchmark projection shape drift")
        if snapshot.get("registry_schema") != BENCHMARK_SCHEMA_VERSION:
            raise TeamControlTowerError("Strategic benchmark registry schema drift")
        if snapshot.get("global_top1_claim") is not False:
            raise TeamControlTowerError("Strategic benchmark must prohibit global Top1")
        self._sha256(snapshot.get("request_sha256"), "benchmark_request_sha256")
        if any(not isinstance(group, Mapping) for group in groups):
            raise TeamControlTowerError("Strategic benchmark group shape drift")
        for group in groups:
            self._validate_benchmark_group(group)
        return {
            "status": "VERIFIED",
            "reason_codes": [],
            "snapshot": self._clone(snapshot),
            "groups": self._clone(groups),
        }

    @classmethod
    def _validate_benchmark_group(cls, group: Mapping[str, Any]) -> None:
        required = {
            "group_ref",
            "domain",
            "metric_id",
            "cohort_ref",
            "market",
            "window",
            "comparison_state",
            "leader_observation_refs",
            "result_sha256",
            "observations",
            "global_top1_claim",
        }
        if not required <= set(group):
            raise TeamControlTowerError("Strategic benchmark metric group shape drift")
        for field in ("group_ref", "domain", "metric_id", "cohort_ref", "market"):
            cls._identifier(group[field], f"benchmark_{field}")
        if group["comparison_state"] not in {
            "comparable",
            "partial",
            "not_comparable",
            "no_data",
            "stale",
            "invalidated",
        }:
            raise TeamControlTowerError("Strategic benchmark comparison state drift")
        window = group["window"]
        if not isinstance(window, Mapping) or set(window) != {"start", "end"}:
            raise TeamControlTowerError("Strategic benchmark window shape drift")
        cls._datetime(window["start"])
        cls._datetime(window["end"])
        cls._sha256(group["result_sha256"], "benchmark_result_sha256")
        leader_refs = cls._identifiers(
            group["leader_observation_refs"],
            "leader_observation_ref",
            maximum=100,
        )
        observations = group["observations"]
        if not isinstance(observations, list):
            raise TeamControlTowerError("Strategic benchmark observations shape drift")
        observation_refs: list[str] = []
        for observation in observations:
            if not isinstance(observation, Mapping) or not {
                "observation_ref",
                "subject_class",
                "value_projection",
                "freshness_due_at",
                "eligibility_state",
            } <= set(observation):
                raise TeamControlTowerError("Strategic benchmark observation shape drift")
            observation_refs.append(
                cls._identifier(
                    observation["observation_ref"],
                    "benchmark_observation_ref",
                )
            )
            if observation["subject_class"] not in {
                "kjds_current",
                "peer",
                "frontier_candidate",
            }:
                raise TeamControlTowerError("Strategic benchmark subject class drift")
            if observation["eligibility_state"] not in {
                "eligible",
                "ineligible_grade",
                "stale",
                "invalidated_source",
                "ineligible_confidence",
                "ineligible_sample",
            }:
                raise TeamControlTowerError("Strategic benchmark eligibility state drift")
            if not isinstance(observation["value_projection"], Mapping):
                raise TeamControlTowerError("Strategic benchmark value projection drift")
            cls._datetime(observation["freshness_due_at"])
        if len(observation_refs) != len(set(observation_refs)):
            raise TeamControlTowerError("Strategic benchmark observations must be unique")
        if not set(leader_refs) <= set(observation_refs):
            raise TeamControlTowerError("Strategic benchmark leader relation drift")
        if group["global_top1_claim"] is not False:
            raise TeamControlTowerError("Strategic benchmark group claims global Top1")

    def _top1_scorecard(
        self,
        *,
        benchmark: Mapping[str, Any],
        checked_at: datetime,
    ) -> dict[str, Any]:
        profile = self.registry["top1_scorecard_profile"]
        dimensions = [
            self._score_dimension(
                definition=item,
                benchmark=benchmark,
                checked_at=checked_at,
                minimum_peers=int(profile["minimum_comparable_peers"]),
            )
            for item in profile["dimensions"]
        ]
        for item in dimensions:
            item["as_of"] = self._iso(checked_at)
            item["projection_sha256"] = self._hash(item)
        statuses = {item["status"] for item in dimensions}
        if "CONFLICTED" in statuses:
            status = "CONFLICTED"
        elif "STALE" in statuses:
            status = "STALE"
        elif statuses == {"VERIFIED"}:
            status = "VERIFIED"
        elif "VERIFIED" in statuses or "PARTIAL" in statuses:
            status = "PARTIAL"
        elif "BLOCKED" in statuses:
            status = "BLOCKED"
        else:
            status = "UNKNOWN"
        largest_gap = next(
            (
                {
                    "dimension_ref": item["dimension_ref"],
                    "title": item["title"],
                    "gap_status": item["gap_status"],
                }
                for item in dimensions
                if item["gap_status"] == "OPEN"
            ),
            None,
        )
        projection = {
            "status": status,
            "reason_codes": sorted(
                {code for item in dimensions for code in item["reason_codes"]}
            ),
            "profile_ref": profile["profile_ref"],
            "claim_scope": profile["claim_scope"],
            "global_top1_claim": False,
            "minimum_comparable_peers": profile["minimum_comparable_peers"],
            "maximum_comparable_peers": profile["maximum_comparable_peers"],
            "dimension_count": len(dimensions),
            "metric_leader_count": sum(
                item["leadership_status"] == "METRIC_LEADER"
                for item in dimensions
            ),
            "largest_open_gap": largest_gap,
            "dimensions": dimensions,
            "source_refs": self._benchmark_source_refs(benchmark),
            "as_of": self._iso(checked_at),
        }
        return self._seal_projection(projection)

    def _score_dimension(
        self,
        *,
        definition: Mapping[str, Any],
        benchmark: Mapping[str, Any],
        checked_at: datetime,
        minimum_peers: int,
    ) -> dict[str, Any]:
        selector = definition["benchmark_selector"]
        base = {
            "dimension_ref": definition["dimension_ref"],
            "title": definition["title"],
            "metric_definition": definition["metric_definition"],
            "benchmark_selector": self._clone(selector),
            "owner_role": definition["owner_role"],
            "verifier_role": definition["verifier_role"],
            "next_experiment": definition["next_experiment"],
            "current_value": None,
            "cohort_ref": None,
            "market": None,
            "window": None,
            "leadership_status": "UNKNOWN",
            "gap_status": "UNKNOWN",
            "invalidates_at": None,
            "source_refs": self._benchmark_source_refs(benchmark),
        }
        if benchmark["status"] != "VERIFIED":
            return {
                **base,
                "status": benchmark["status"],
                "reason_codes": list(benchmark["reason_codes"]),
            }
        groups = [
            item
            for item in benchmark["groups"]
            if item.get("domain") == selector["domain"]
            and item.get("metric_id") == selector["metric_id"]
        ]
        if not groups:
            return {**base, "status": "UNKNOWN", "reason_codes": ["metric_no_data"]}
        if len(groups) != 1:
            return {
                **base,
                "status": "CONFLICTED",
                "reason_codes": ["multiple_latest_metric_groups"],
            }
        group = groups[0]
        observations = group.get("observations")
        leaders = group.get("leader_observation_refs")
        if not isinstance(observations, list) or not isinstance(leaders, list):
            raise TeamControlTowerError("Strategic benchmark metric group shape drift")
        current = [item for item in observations if item.get("subject_class") == "kjds_current"]
        if len(current) > 1:
            return {
                **base,
                "status": "CONFLICTED",
                "reason_codes": ["multiple_kjds_current_observations"],
            }
        current_item = current[0] if current else None
        peer_count = sum(
            item.get("subject_class") in {"peer", "frontier_candidate"}
            and item.get("eligibility_state") == "eligible"
            for item in observations
        )
        base.update(
            {
                "current_value": (
                    self._clone(current_item.get("value_projection"))
                    if current_item
                    else None
                ),
                "cohort_ref": group.get("cohort_ref"),
                "market": group.get("market"),
                "window": self._clone(group.get("window")),
                "comparable_peer_count": peer_count,
                "invalidates_at": (
                    current_item.get("freshness_due_at") if current_item else None
                ),
                "source_refs": [
                    *self._benchmark_source_refs(benchmark),
                    {
                        "ref": f"benchmark-group:{group.get('group_ref')}",
                        "sha256": str(group.get("result_sha256") or ""),
                    },
                ],
            }
        )
        state = group.get("comparison_state")
        if state == "stale" or (
            current_item and current_item.get("eligibility_state") == "stale"
        ):
            return {**base, "status": "STALE", "reason_codes": ["metric_stale"]}
        if state == "invalidated":
            return {**base, "status": "BLOCKED", "reason_codes": ["metric_invalidated"]}
        if state != "comparable" or current_item is None:
            return {
                **base,
                "status": "UNKNOWN",
                "reason_codes": ["metric_not_comparable"],
            }
        if current_item.get("eligibility_state") != "eligible":
            return {
                **base,
                "status": "PARTIAL",
                "reason_codes": ["kjds_observation_ineligible"],
            }
        if peer_count < minimum_peers:
            return {
                **base,
                "status": "PARTIAL",
                "reason_codes": ["insufficient_comparable_peers"],
            }
        leader = current_item.get("observation_ref") in leaders
        return {
            **base,
            "status": "VERIFIED",
            "reason_codes": [],
            "leadership_status": "METRIC_LEADER" if leader else "NOT_LEADER",
            "gap_status": "CLOSED" if leader else "OPEN",
        }

    def _settlement_cash_authority(
        self,
        *,
        principal: Principal,
        scope: Mapping[str, Any],
        store_ref: str,
        checked_at: datetime,
    ) -> dict[str, Any]:
        policy = self.registry["cash_at_risk_policy"]["actual_cash_authority"]
        if self.settlement_cash is None:
            return self._seal_projection(
                {
                    "status": "UNKNOWN",
                    "reason_codes": ["settlement_cash_authority_unavailable"],
                    "source_status": "unavailable",
                    "verified_cycle_count": 0,
                    "verified_single_sku_cycle_count": 0,
                    "single_sku_attribution_status": "UNKNOWN",
                    "minimum_reconciled_cycles": policy[
                        "minimum_reconciled_cycles"
                    ],
                    "counts": None,
                    "source_refs": [],
                    "as_of": self._iso(checked_at),
                }
            )
        try:
            result = self.settlement_cash.project(
                store_ref=store_ref,
                principal=principal,
                entity_scope=self._entity_scope(scope),
                as_of=self._iso(checked_at),
                query=None,
                stage=None,
                page_size=100,
                cursor=None,
            )
        except Exception:
            return self._seal_projection(
                {
                    "status": "CONFLICTED",
                    "reason_codes": ["settlement_cash_authority_drift"],
                    "source_status": "error",
                    "verified_cycle_count": 0,
                    "verified_single_sku_cycle_count": 0,
                    "single_sku_attribution_status": "UNKNOWN",
                    "minimum_reconciled_cycles": policy[
                        "minimum_reconciled_cycles"
                    ],
                    "counts": None,
                    "source_refs": [],
                    "as_of": self._iso(checked_at),
                }
            )
        if not isinstance(result, Mapping):
            raise TeamControlTowerError("Settlement cash projection shape drift")
        if result.get("contract_id") != policy["contract_id"]:
            raise TeamControlTowerError("Settlement cash contract drift")
        source_status = str(result.get("status") or "")
        if source_status not in {"ready", "partial", "blocked", "no_data"}:
            raise TeamControlTowerError("Settlement cash status drift")
        source_as_of = self._datetime(result.get("as_of"))
        if source_as_of != checked_at:
            raise TeamControlTowerError("Settlement cash as-of authority drift")
        source_scope = result.get("scope")
        if not isinstance(source_scope, Mapping) or {
            "tenant_ref": source_scope.get("tenant_ref"),
            "entity_ref": source_scope.get("entity_ref"),
            "store_ref": source_scope.get("store_ref"),
            "scope_grant_authority_sha256": source_scope.get(
                "scope_grant_authority_sha256"
            ),
        } != {
            "tenant_ref": scope["tenant_ref"],
            "entity_ref": scope["entity_ref"],
            "store_ref": scope["store_ref"],
            "scope_grant_authority_sha256": scope[
                "scope_authority_sha256"
            ],
        }:
            raise TeamControlTowerError("Settlement cash exact scope drift")
        source_hash = str(result.get("snapshot_sha256") or "")
        if not _SHA256.fullmatch(source_hash):
            raise TeamControlTowerError("Settlement cash snapshot hash drift")
        if source_hash != self._hash(
            {key: value for key, value in result.items() if key != "snapshot_sha256"}
        ):
            raise TeamControlTowerError("Settlement cash snapshot content drift")
        envelope = result.get("control_envelope")
        if (
            not isinstance(envelope, Mapping)
            or envelope.get("read_only") is not True
            or envelope.get("scoped_input_read") is not True
            or envelope.get("external_write_allowed") is not False
            or envelope.get("finance_entry_created") is not False
            or envelope.get("reconciliation_created") is not False
            or envelope.get("fact_created") is not False
            or envelope.get("approval_created") is not False
            or envelope.get("permit_created") is not False
            or envelope.get("payment_initiated") is not False
        ):
            raise TeamControlTowerError("Settlement cash control envelope drift")
        counts = result.get("counts")
        required_counts = {
            "total_cycles",
            "order_fact_cycles",
            "settlement_cycles",
            "cash_cycles",
            "reconciled",
            "actual_cash_cm3_available",
            "filtered",
            "page",
        }
        if not isinstance(counts, Mapping) or not required_counts <= set(counts):
            raise TeamControlTowerError("Settlement cash count shape drift")
        projected_counts: dict[str, int] = {}
        for key in sorted(required_counts):
            value = counts[key]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise TeamControlTowerError("Settlement cash count value drift")
            projected_counts[key] = value
        pagination = result.get("pagination")
        if (
            not isinstance(pagination, Mapping)
            or set(pagination) != {"page_size", "next_cursor"}
            or pagination.get("page_size") != 100
            or pagination.get("next_cursor") is not None
        ):
            raise TeamControlTowerError("Settlement cash pagination drift")
        cycles = result.get("cycles")
        if not isinstance(cycles, Sequence) or isinstance(cycles, (str, bytes)):
            raise TeamControlTowerError("Settlement cash cycle shape drift")
        candidate_verified_cycles = 0
        candidate_verified_single_sku_cycles = 0
        authority_cycles: list[dict[str, Any]] = []
        for cycle in cycles:
            if not isinstance(cycle, Mapping):
                raise TeamControlTowerError("Settlement cash cycle shape drift")
            books = cycle.get("books")
            evidence = cycle.get("evidence")
            actual_cash = cycle.get("actual_cash_cm3")
            if not isinstance(books, Mapping):
                raise TeamControlTowerError("Settlement cash book shape drift")
            order_book = books.get("order_accrual")
            settlement_book = books.get("platform_settlement")
            bank_book = books.get("bank_cash")
            if not all(
                isinstance(item, Mapping)
                for item in (order_book, settlement_book, bank_book)
            ):
                raise TeamControlTowerError("Settlement cash book shape drift")
            order_count = order_book.get("order_fact_count")
            if (
                isinstance(order_count, bool)
                or not isinstance(order_count, int)
                or order_count < 0
            ):
                raise TeamControlTowerError("Settlement cash order count drift")
            if settlement_book.get("status") not in {"observed", "missing"}:
                raise TeamControlTowerError("Settlement cash settlement status drift")
            if bank_book.get("status") not in {"observed", "missing"}:
                raise TeamControlTowerError("Settlement cash bank status drift")
            if (
                not isinstance(actual_cash, Mapping)
                or actual_cash.get("status") not in {"available", "no_data"}
                or not isinstance(evidence, Mapping)
                or evidence.get("all_current_and_exact_scope") not in {True, False}
                or not isinstance(cycle.get("blockers"), list)
            ):
                raise TeamControlTowerError("Settlement cash cycle control drift")
            key_hash = str(cycle.get("reconciliation_key_sha256") or "")
            key = str(cycle.get("reconciliation_key") or "")
            if (
                not _SHA256.fullmatch(key_hash)
                or not key
                or self._hash(key) != key_hash
            ):
                raise TeamControlTowerError(
                    "Settlement cash reconciliation identity drift"
                )
            attribution = actual_cash.get("single_sku_attribution")
            if attribution is None:
                attribution = {
                    "schema_version": "single-sku-attribution/2",
                    "status": "no_data",
                    "identity_count": 0,
                    "scope_sha256": None,
                    "scope_grant_authority_sha256": None,
                    "product_sha256": None,
                    "sku_sha256": None,
                    "order_ref_sha256": None,
                    "order_fact_receipt_sha256": None,
                    "profit_row_basis_sha256": None,
                    "profit_row_sha256": None,
                    "profit_receipt_sha256": None,
                    "lineage_sha256": None,
                }
            attribution_fields = {
                "schema_version",
                "status",
                "identity_count",
                "scope_sha256",
                "scope_grant_authority_sha256",
                "product_sha256",
                "sku_sha256",
                "order_ref_sha256",
                "order_fact_receipt_sha256",
                "profit_row_basis_sha256",
                "profit_row_sha256",
                "profit_receipt_sha256",
                "lineage_sha256",
            }
            if (
                not isinstance(attribution, Mapping)
                or set(attribution) != attribution_fields
                or attribution.get("schema_version")
                != "single-sku-attribution/2"
                or attribution.get("status") not in {"verified", "no_data"}
                or attribution.get("identity_count") not in {0, 1}
            ):
                raise TeamControlTowerError(
                    "Settlement cash SKU attribution drift"
                )
            attribution_verified = attribution.get("status") == "verified"
            if attribution_verified:
                if attribution.get("identity_count") != 1 or any(
                    not _SHA256.fullmatch(str(attribution.get(field) or ""))
                    for field in (
                        "scope_sha256",
                        "scope_grant_authority_sha256",
                        "product_sha256",
                        "sku_sha256",
                        "order_ref_sha256",
                        "order_fact_receipt_sha256",
                        "profit_row_basis_sha256",
                        "profit_row_sha256",
                        "profit_receipt_sha256",
                        "lineage_sha256",
                    )
                ):
                    raise TeamControlTowerError(
                        "Settlement cash SKU attribution identity drift"
                    )
                scope_receipt = {
                    "tenant_ref": scope["tenant_ref"],
                    "entity_ref": scope["entity_ref"],
                    "store_ref": scope["store_ref"],
                    "scope_grant_authority_sha256": scope[
                        "scope_authority_sha256"
                    ],
                }
                receipt_payload = {
                    "contract_id": "canonical_order_sku_receipt_v1",
                    "issuer_contract_id": (
                        "kjds-native-exact-scope-actual-profit-ledger-v1"
                    ),
                    "scope_sha256": attribution["scope_sha256"],
                    "scope_grant_authority_sha256": attribution[
                        "scope_grant_authority_sha256"
                    ],
                    "order_ref_sha256": attribution["order_ref_sha256"],
                    "product_sha256": attribution["product_sha256"],
                    "sku_sha256": attribution["sku_sha256"],
                    "order_fact_receipt_sha256": attribution[
                        "order_fact_receipt_sha256"
                    ],
                    "profit_row_basis_sha256": attribution[
                        "profit_row_basis_sha256"
                    ],
                }
                lineage_payload = {
                    field: attribution[field]
                    for field in attribution_fields
                    if field != "lineage_sha256"
                }
                if (
                    order_count != 1
                    or attribution["order_ref_sha256"] != key_hash
                    or attribution["scope_sha256"] != self._hash(scope_receipt)
                    or attribution["scope_grant_authority_sha256"]
                    != scope["scope_authority_sha256"]
                    or attribution["profit_receipt_sha256"]
                    != self._hash(receipt_payload)
                    or attribution["lineage_sha256"]
                    != self._hash(lineage_payload)
                ):
                    raise TeamControlTowerError(
                        "Settlement cash SKU attribution lineage drift"
                    )
            elif (
                attribution.get("identity_count") != 0
                or any(
                    attribution.get(field) is not None
                    for field in attribution_fields
                    if field
                    not in {"schema_version", "status", "identity_count"}
                )
            ):
                raise TeamControlTowerError(
                    "Settlement cash unavailable SKU attribution drift"
                )
            latest_reconciliation = cycle.get("latest_reconciliation")
            authority_cycles.append(
                {
                    "reconciliation_key_sha256": key_hash,
                    "stage": cycle.get("stage"),
                    "latest_effective_at": cycle.get("latest_effective_at"),
                    "order_fact_count": order_count,
                    "platform_settlement_status": settlement_book.get("status"),
                    "bank_cash_status": bank_book.get("status"),
                    "actual_cash_cm3_status": actual_cash.get("status"),
                    "single_sku_attribution_status": attribution.get(
                        "status"
                    ),
                    "single_sku_lineage_sha256": attribution.get(
                        "lineage_sha256"
                    ),
                    "single_sku_product_sha256": attribution.get(
                        "product_sha256"
                    ),
                    "single_sku_sha256": attribution.get("sku_sha256"),
                    "single_sku_order_ref_sha256": attribution.get(
                        "order_ref_sha256"
                    ),
                    "single_sku_scope_sha256": attribution.get(
                        "scope_sha256"
                    ),
                    "single_sku_scope_authority_sha256": attribution.get(
                        "scope_grant_authority_sha256"
                    ),
                    "single_sku_order_fact_receipt_sha256": attribution.get(
                        "order_fact_receipt_sha256"
                    ),
                    "single_sku_profit_row_basis_sha256": attribution.get(
                        "profit_row_basis_sha256"
                    ),
                    "single_sku_profit_row_sha256": attribution.get(
                        "profit_row_sha256"
                    ),
                    "single_sku_profit_receipt_sha256": attribution.get(
                        "profit_receipt_sha256"
                    ),
                    "reconciliation_input_sha256": (
                        latest_reconciliation.get("input_sha256")
                        if isinstance(latest_reconciliation, Mapping)
                        else None
                    ),
                    "evidence_count": evidence.get("count"),
                    "evidence_current_exact_scope": evidence.get(
                        "all_current_and_exact_scope"
                    ),
                    "blockers": list(cycle.get("blockers") or []),
                }
            )
            if (
                cycle.get("stage") == "reconciled"
                and order_count == 1
                and settlement_book.get("status") == "observed"
                and bank_book.get("status") == "observed"
                and actual_cash.get("status") == "available"
                and attribution_verified
                and evidence.get("all_current_and_exact_scope") is True
                and not cycle.get("blockers")
            ):
                candidate_verified_cycles += 1
                candidate_verified_single_sku_cycles += 1
        excluded = result.get("excluded")
        excluded_count = (
            excluded.get("count") if isinstance(excluded, Mapping) else None
        )
        exclusion_reasons = (
            excluded.get("reason_counts")
            if isinstance(excluded, Mapping)
            else None
        )
        if (
            not isinstance(excluded, Mapping)
            or set(excluded)
            != {"count", "reason_counts", "business_values_exposed"}
            or
            isinstance(excluded_count, bool)
            or not isinstance(excluded_count, int)
            or excluded_count < 0
            or not isinstance(exclusion_reasons, Mapping)
            or any(
                not isinstance(key, str)
                or not key
                or isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
                for key, value in (
                    exclusion_reasons.items()
                    if isinstance(exclusion_reasons, Mapping)
                    else []
                )
            )
            or (
                isinstance(exclusion_reasons, Mapping)
                and sum(exclusion_reasons.values()) != excluded_count
            )
            or (excluded_count == 0 and exclusion_reasons != {})
            or excluded.get("business_values_exposed") is not False
        ):
            raise TeamControlTowerError("Settlement cash exclusion shape drift")
        total_cycles = projected_counts["total_cycles"]
        if (
            len(cycles)
            != projected_counts["page"]
            or projected_counts["page"] != projected_counts["filtered"]
            or projected_counts["filtered"] != total_cycles
            or len(cycles) > 100
            or len(cycles) > total_cycles
            or any(
                projected_counts[key] > total_cycles
                for key in required_counts
                if key != "total_cycles"
            )
        ):
            raise TeamControlTowerError("Settlement cash count relationship drift")
        source_gaps = result.get("source_gaps")
        source_blockers = result.get("blockers")
        if (
            not isinstance(source_gaps, list)
            or not all(isinstance(item, str) for item in source_gaps)
            or not isinstance(source_blockers, list)
            or (source_status == "ready" and (source_gaps or source_blockers))
        ):
            raise TeamControlTowerError("Settlement cash source control drift")
        complete_source_authority = (
            source_status == "ready"
            and excluded_count == 0
            and not source_gaps
            and not source_blockers
        )
        verified_cycles = (
            candidate_verified_cycles if complete_source_authority else 0
        )
        verified_single_sku_cycles = (
            candidate_verified_single_sku_cycles
            if complete_source_authority
            else 0
        )
        if verified_cycles > min(
            projected_counts["order_fact_cycles"],
            projected_counts["settlement_cycles"],
            projected_counts["cash_cycles"],
            projected_counts["reconciled"],
            projected_counts["actual_cash_cm3_available"],
        ):
            raise TeamControlTowerError("Settlement cash verified count drift")
        if verified_cycles != verified_single_sku_cycles:
            raise TeamControlTowerError(
                "Settlement cash verified SKU count drift"
            )
        if source_status == "no_data" and total_cycles:
            raise TeamControlTowerError("Settlement cash no-data count drift")
        authority_state_sha256 = self._hash(
            {
                "contract_id": result["contract_id"],
                "status": source_status,
                "scope": dict(source_scope),
                "counts": projected_counts,
                "cycles": authority_cycles,
                "excluded_count": excluded_count,
                "source_gaps": list(source_gaps),
            }
        )
        minimum = int(policy["minimum_reconciled_cycles"])
        if source_status == "blocked" or excluded_count:
            status = "BLOCKED"
            reasons = ["settlement_cash_source_blocked"]
        elif candidate_verified_cycles and not complete_source_authority:
            status = "PARTIAL"
            reasons = ["settlement_cash_source_incomplete"]
        elif verified_cycles >= minimum:
            status = "PARTIAL"
            reasons = [
                "offer_mapping_and_return_window_authority_missing",
                *(
                    ["settlement_cash_source_incomplete"]
                    if source_status != "ready"
                    else []
                ),
            ]
        elif (
            projected_counts["actual_cash_cm3_available"]
            and not verified_single_sku_cycles
        ):
            status = "PARTIAL"
            reasons = ["single_sku_cash_attribution_missing"]
        elif projected_counts["total_cycles"]:
            status = "PARTIAL"
            reasons = ["reconciled_actual_cash_cycle_missing"]
        else:
            status = "UNKNOWN"
            reasons = ["settlement_cash_cycle_missing"]
        return self._seal_projection(
            {
                "status": status,
                "reason_codes": reasons,
                "source_status": source_status,
                "verified_cycle_count": verified_cycles,
                "verified_single_sku_cycle_count": (
                    verified_single_sku_cycles
                ),
                "single_sku_attribution_status": (
                    "VERIFIED"
                    if verified_single_sku_cycles >= minimum
                    and source_status == "ready"
                    and excluded_count == 0
                    and not source_gaps
                    and not source_blockers
                    else "UNKNOWN"
                ),
                "minimum_reconciled_cycles": minimum,
                "counts": projected_counts,
                "source_refs": [
                    {
                        "ref": "scoped-settlement-cash",
                        "sha256": authority_state_sha256,
                        "source_snapshot_sha256": source_hash,
                        "as_of": self._iso(source_as_of),
                    }
                ],
                "as_of": self._iso(checked_at),
            }
        )

    def _cash_at_risk(
        self,
        *,
        benchmark: Mapping[str, Any],
        settlement_cash: Mapping[str, Any],
        checked_at: datetime,
    ) -> dict[str, Any]:
        policy = self.registry["cash_at_risk_policy"]
        measures: dict[str, Any] = {}
        for selector in policy["benchmark_selectors"]:
            key = selector["metric_id"]
            matches = [
                group
                for group in benchmark.get("groups", [])
                if group.get("domain") == selector["domain"]
                and group.get("metric_id") == selector["metric_id"]
            ]
            current = (
                [
                    item
                    for item in matches[0].get("observations", [])
                    if item.get("subject_class") == "kjds_current"
                ]
                if len(matches) == 1
                else []
            )
            measures[key] = {
                "status": "PARTIAL" if len(current) == 1 else "UNKNOWN",
                "value": (
                    self._clone(current[0].get("value_projection"))
                    if len(current) == 1
                    else None
                ),
                "reason_codes": (
                    ["finance_value_withheld_or_not_authoritative"]
                    if len(current) == 1
                    else ["finance_metric_authority_missing"]
                ),
            }
        missing_authorities = list(policy["required_inputs"])
        settlement_counts = settlement_cash.get("counts")
        if (
            settlement_cash["status"] not in {"CONFLICTED", "BLOCKED", "STALE"}
            and isinstance(settlement_counts, Mapping)
        ):
            missing_authorities = [
                item
                for item in missing_authorities
                if not (
                    item == "platform_settlement"
                    and settlement_counts.get("settlement_cycles", 0) > 0
                )
                and not (
                    item == "bank_cash"
                    and settlement_counts.get("cash_cycles", 0) > 0
                )
            ]
        cash_status = "UNKNOWN"
        if benchmark["status"] in {"CONFLICTED", "STALE"}:
            cash_status = str(benchmark["status"])
        elif settlement_cash["status"] in {"CONFLICTED", "BLOCKED", "STALE"}:
            cash_status = str(settlement_cash["status"])
        projection = {
            "status": cash_status,
            "reason_codes": [
                "opening_bank_balance_missing",
                "cash_plan_missing",
                "approved_fx_basis_missing",
                "signed_cash_floor_missing",
                "approved_maximum_loss_missing",
                *benchmark.get("reason_codes", []),
                *settlement_cash.get("reason_codes", []),
            ],
            "forecast_weeks": policy["forecast_weeks"],
            "quote_currency": policy["quote_currency"],
            "thirteen_week_cash": {
                "status": "UNKNOWN",
                "forecast": None,
                "reason_codes": ["cash_forecast_authorities_incomplete"],
            },
            "cash_runway": measures.get("cash_runway"),
            "maximum_loss": measures.get("maximum_loss"),
            "cash_floor": {
                "status": "UNKNOWN",
                "value": None,
                "reason_codes": ["signed_cash_floor_missing"],
            },
            "committed_cash": {
                "status": "UNKNOWN",
                "value": None,
                "reason_codes": ["cash_plan_missing"],
            },
            "actual_cash_truth": self._clone(settlement_cash),
            "missing_authorities": missing_authorities,
            "forecast_invoked": False,
            "source_refs": [
                *self._benchmark_source_refs(benchmark),
                *settlement_cash.get("source_refs", []),
            ],
            "as_of": self._iso(checked_at),
        }
        return self._seal_projection(projection)

    def _critical_path(
        self,
        *,
        tasks: Sequence[Mapping[str, Any]],
        principal: Principal,
        entity_scope: Mapping[str, Any],
        store_ref: str,
        checked_at: datetime,
    ) -> dict[str, Any]:
        campaign = self.registry["campaign_90d"]
        start = date.fromisoformat(campaign["planned_start_on"])
        phase_defs = {
            str(item["phase_ref"]): item for item in campaign["phases"]
        }
        phase_tasks: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        source_rows: list[dict[str, Any]] = []
        kickoff_events: list[dict[str, Any]] = []
        for task in tasks:
            metadata = self._team_metadata(task) or {}
            if metadata.get("campaign_ref") != campaign["campaign_ref"]:
                continue
            phase_ref = str(metadata.get("phase_ref") or "")
            if phase_ref not in phase_defs:
                raise TeamControlTowerError("Campaign task phase reference drift")
            events = [
                event
                for event in self.operating_tasks.task_events(
                    str(task["id"]),
                    principal=principal,
                    entity_scope=dict(entity_scope),
                    store_ref=store_ref,
                )
                if self._datetime(event["occurred_at"]) <= checked_at
            ]
            phase_tasks[phase_ref].append(task)
            event_projection = [
                {
                    "event_type": event.get("event_type"),
                    "occurred_at": event.get("occurred_at"),
                    "evidence_count": len(event.get("evidence_ids") or []),
                }
                for event in events
            ]
            source_rows.append(
                {
                    "task": self._task_summary(task),
                    "phase_ref": phase_ref,
                    "events": event_projection,
                }
            )
            if phase_ref == campaign["coordination"]["kickoff_phase_ref"]:
                kickoff_events.extend(
                    event
                    for event in events
                    if event.get("event_type")
                    == campaign["coordination"]["kickoff_event_type"]
                    and bool(event.get("evidence_ids"))
                )
        kickoff = (
            min(kickoff_events, key=lambda item: self._datetime(item["occurred_at"]))
            if kickoff_events
            else None
        )
        actual_day = (
            (checked_at.date() - self._datetime(kickoff["occurred_at"]).date()).days
            + 1
            if kickoff is not None
            else None
        )
        phases = []
        conflict_found = False
        for definition in campaign["phases"]:
            blockers = sorted(
                {
                    blocker
                    for lane_id in definition["source_lane_ids"]
                    for blocker in self._lane_blockers(self._lanes[lane_id])
                }
            )
            candidates = phase_tasks.get(definition["phase_ref"], [])
            active = [
                item for item in candidates if item.get("status") in ACTIVE_TASK_STATES
            ]
            selected = (
                self._rank_tasks(active, checked_at)[0]
                if active
                else max(
                    candidates,
                    key=lambda item: (
                        str(item.get("updated_at")),
                        str(item.get("id")),
                    ),
                    default=None,
                )
            )
            reasons = ["formal_gate_evidence_unverified"]
            if selected is None:
                status = "BLOCKED"
                reasons.append("campaign_phase_task_not_opened")
            elif len(active) > 1:
                status = "CONFLICTED"
                conflict_found = True
                reasons.append("multiple_active_campaign_phase_tasks")
            elif selected.get("status") == "dismissed":
                status = "BLOCKED"
                reasons.append("campaign_phase_stopped")
            elif selected.get("status") == "resolved":
                status = "PARTIAL"
                reasons.append("campaign_phase_task_resolved")
            elif kickoff is None:
                status = "BLOCKED"
                reasons.append("kickoff_evidence_missing")
            else:
                status = "PARTIAL"
                reasons.append("campaign_phase_work_in_progress")
            if kickoff is None:
                reasons.append("kickoff_evidence_missing")
            if blockers:
                reasons.append("source_lane_blocked")
            phase = {
                "phase_ref": definition["phase_ref"],
                "title": definition["title"],
                "day_from": definition["day_from"],
                "day_to": definition["day_to"],
                "planned_start_on": (start + timedelta(days=definition["day_from"] - 1)).isoformat(),
                "planned_end_on": (start + timedelta(days=definition["day_to"] - 1)).isoformat(),
                "actual_campaign_day": actual_day,
                "status": status,
                "reason_codes": sorted(set(reasons)),
                "owner_role": definition["owner_role"],
                "reviewer_role": definition["reviewer_role"],
                "source_lane_ids": list(definition["source_lane_ids"]),
                "required_evidence": list(definition["required_evidence"]),
                "gate_refs": list(definition["gate_refs"]),
                "stop_conditions": list(definition["stop_conditions"]),
                "blockers": blockers,
                "current_operating_task": self._task_summary(selected),
                "runtime_task_status": (
                    str(selected.get("status")) if selected is not None else None
                ),
                "formal_gate_pass": False,
            }
            phase["projection_sha256"] = self._hash(phase)
            phases.append(phase)
        root_status = (
            "CONFLICTED"
            if conflict_found
            else "BLOCKED"
            if kickoff is None
            else "PARTIAL"
        )
        root_reasons = ["phase_gate_evidence_missing"]
        if kickoff is None:
            root_reasons.append("kickoff_evidence_missing")
        if conflict_found:
            root_reasons.append("campaign_task_authority_conflicted")
        source_hash = self._hash(source_rows)
        projection = {
            "status": root_status,
            "reason_codes": root_reasons,
            "campaign_ref": campaign["campaign_ref"],
            "planned_start_on": campaign["planned_start_on"],
            "planned_end_on": (start + timedelta(days=campaign["duration_days"] - 1)).isoformat(),
            "actual_campaign_day": actual_day,
            "kickoff": {
                "status": "VERIFIED" if kickoff is not None else "UNKNOWN",
                "occurred_at": kickoff.get("occurred_at") if kickoff else None,
                "evidence_count": len(kickoff.get("evidence_ids") or []) if kickoff else 0,
                "reason_codes": [] if kickoff else ["kickoff_evidence_missing"],
            },
            "active_lane_ids": list(campaign["active_lane_ids"]),
            "preparation_only_lane_ids": list(campaign["preparation_only_lane_ids"]),
            "earliest_blocking_phase_ref": phases[0]["phase_ref"] if phases else None,
            "phases": phases,
            "source_refs": [
                {"ref": "team_control_tower_registry.campaign_90d", "sha256": self.registry_sha256},
                {"ref": "active_workstream_assignments", "sha256": self.workstream_sha256},
                {"ref": "operating-task-event-campaign", "sha256": source_hash},
            ],
            "as_of": self._iso(checked_at),
        }
        return self._seal_projection(projection)

    def _delivery_gate(
        self,
        *,
        organization: Mapping[str, Any],
        critical_path: Mapping[str, Any],
        top1: Mapping[str, Any],
        cash: Mapping[str, Any],
        checked_at: datetime,
    ) -> dict[str, Any]:
        gates = []
        for definition in self.registry["delivery_gate_profile"]["gates"]:
            lane_blockers = sorted(
                {
                    blocker
                    for lane_id in definition["source_lane_ids"]
                    for blocker in self._lane_blockers(self._lanes[lane_id])
                }
            )
            reasons = ["canonical_gate_pass_evidence_missing"]
            if lane_blockers:
                reasons.append("source_lane_blocked")
            if definition["gate_ref"] == "organization_binding_gate" and organization["status"] != "VERIFIED":
                reasons.append("organization_not_verified")
            if definition["gate_ref"] == "top1_dimension_audit_gate" and top1["status"] != "VERIFIED":
                reasons.append("top1_dimensions_not_verified")
            if definition["gate_ref"] == "russia_operating_truth_gate" and cash["status"] != "VERIFIED":
                actual_cash = cash["actual_cash_truth"]
                if actual_cash["status"] != "VERIFIED":
                    reasons.append("actual_cash_truth_not_verified")
            readiness_status = "UNKNOWN"
            readiness_reasons: list[str] = []
            if definition["gate_ref"] == "organization_binding_gate":
                readiness_status = str(organization["status"])
                readiness_reasons = list(organization["reason_codes"])
            elif definition["gate_ref"] == "russia_operating_truth_gate":
                readiness_status = str(cash["actual_cash_truth"]["status"])
                readiness_reasons = list(
                    cash["actual_cash_truth"]["reason_codes"]
                )
            elif definition["gate_ref"] == "top1_dimension_audit_gate":
                readiness_status = str(top1["status"])
                readiness_reasons = list(top1["reason_codes"])
            gate = {
                "gate_ref": definition["gate_ref"],
                "title": definition["title"],
                "status": "BLOCKED" if len(reasons) > 1 else "UNKNOWN",
                "reason_codes": reasons,
                "owner_role": definition["owner_role"],
                "source_lane_ids": list(definition["source_lane_ids"]),
                "pass_requires": list(definition["pass_requires"]),
                "blockers": lane_blockers,
                "formal_gate_pass": False,
                "formal_gate_authority_status": "UNKNOWN",
                "readiness_status": readiness_status,
                "readiness_reason_codes": readiness_reasons,
            }
            gate["projection_sha256"] = self._hash(gate)
            gates.append(gate)
        projection = {
            "status": "BLOCKED",
            "reason_codes": ["one_or_more_delivery_gates_not_passed"],
            "gate_count": len(gates),
            "passed_gate_count": 0,
            "gates": gates,
            "source_refs": [
                {"ref": "team_control_tower_registry.delivery_gate_profile", "sha256": self.registry_sha256},
                {
                    "ref": "critical_path",
                    "sha256": self._decision_projection_sha256(critical_path),
                },
            ],
            "as_of": self._iso(checked_at),
        }
        return self._seal_projection(projection)

    @staticmethod
    def _lane_blockers(lane: Mapping[str, Any]) -> list[str]:
        return list(lane.get("blocked_on") or []) + list(
            (lane.get("current_task") or {}).get("blocked_on") or []
        )

    def _benchmark_source_refs(self, benchmark: Mapping[str, Any]) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = [
            {
                "ref": "strategic_benchmark_contracts",
                "sha256": self.benchmark_contract_sha256,
            }
        ]
        snapshot = benchmark.get("snapshot")
        if isinstance(snapshot, Mapping):
            refs.append(
                {
                    "ref": f"strategic-benchmark-snapshot:{snapshot.get('snapshot_ref')}",
                    "sha256": snapshot.get("request_sha256"),
                    "as_of": snapshot.get("as_of"),
                }
            )
        return refs

    def _enterprise_ai_erp_projections(
        self,
        *,
        checked_at: datetime,
    ) -> dict[str, dict[str, Any]]:
        if self.enterprise_ai_erp_program is None:
            return {
                name: self._unknown_projection(
                    name=name,
                    checked_at=checked_at,
                    reason_code="enterprise_ai_erp_program_unavailable",
                )
                for name in ENTERPRISE_AI_ERP_PROJECTION_KEYS
            }
        try:
            raw = self.enterprise_ai_erp_program.project()
        except Exception as exc:
            raise TeamControlTowerError(
                "Enterprise AI ERP program projection unavailable"
            ) from exc
        self._validate_enterprise_ai_erp_projection(raw)

        integrity = raw["contract_integrity"]
        snapshot_sha256 = str(raw["snapshot_sha256"])
        source_refs = [
            {
                "ref": "enterprise_ai_erp_program_registry",
                "sha256": integrity["registry_sha256"],
            },
            {
                "ref": "enterprise_ai_erp_source_bundle",
                "sha256": integrity["source_bundle_sha256"],
            },
            {
                "ref": "enterprise_ai_erp_program_snapshot",
                "sha256": snapshot_sha256,
            },
        ]
        program_contract = {
            "contract_id": raw["contract_id"],
            "contract_version": raw["contract_version"],
            "program_snapshot_sha256": snapshot_sha256,
            "registry_sha256": integrity["registry_sha256"],
            "source_bundle_sha256": integrity["source_bundle_sha256"],
            "static_contract_integrity": "VERIFIED",
            "runtime_authority_connected": False,
        }

        squads = raw["squad_readiness"]
        squad_readiness = self._seal_projection(
            {
                "projection": "squad_readiness",
                "status": "UNKNOWN",
                "contract_count": raw["counts"]["squads"],
                "items": [
                    {
                        key: self._clone(item[key])
                        for key in (
                            "squad_ref",
                            "title",
                            "owner_role_ref",
                            "reviewer_role_ref",
                            "primary_lane_id",
                            "supporting_lane_ids",
                            "required_functions",
                            "capability_atlas_ids",
                            "capability_gap_refs",
                            "work_item_refs",
                            "first_acceptance_contract",
                            "status",
                            "reason_codes",
                        )
                    }
                    for item in squads["items"]
                ],
                "program_contract": self._clone(program_contract),
                "reason_codes": self._clone(squads["reason_codes"]),
                "source_refs": self._clone(source_refs),
                "as_of": self._iso(checked_at),
            }
        )

        conflicts = raw["role_conflicts"]
        role_conflicts = self._seal_projection(
            {
                "projection": "role_conflicts",
                "status": "UNKNOWN",
                "contract_rules_verified": True,
                "rules": [
                    {
                        key: self._clone(rule[key])
                        for key in (
                            "rule_ref",
                            "left_function_ref",
                            "right_function_ref",
                            "same_role_allowed",
                            "same_principal_allowed",
                            "identity_authority_required",
                        )
                    }
                    for rule in conflicts["rules"]
                ],
                "observed_conflicts": None,
                "program_contract": self._clone(program_contract),
                "reason_codes": self._clone(conflicts["reason_codes"]),
                "source_refs": self._clone(source_refs),
                "as_of": self._iso(checked_at),
            }
        )

        parallel = raw["parallel_execution"]
        parallel_execution = self._seal_projection(
            {
                "projection": "parallel_execution",
                "status": "UNKNOWN",
                "policy": {
                    key: self._clone(parallel["policy"][key])
                    for key in (
                        "control_agent_count",
                        "max_parallel_specialist_agents",
                        "max_active_writers",
                        "max_active_tasks_per_specialist",
                        "max_active_tasks_per_writer",
                        "max_current_tasks_per_lane",
                        "max_weekly_company_outcomes",
                        "release_trains_per_week",
                        "single_integrator_domains",
                        "failed_slice_blocks_independent_slices",
                        "path_or_hash_drift_action",
                        "shared_lease_conflict_action",
                    )
                },
                "observed_active_writers": None,
                "observed_writer_wip": None,
                "observed_lane_current_tasks": None,
                "program_contract": self._clone(program_contract),
                "reason_codes": self._clone(parallel["reason_codes"]),
                "source_refs": self._clone(source_refs),
                "as_of": self._iso(checked_at),
            }
        )

        queue = raw["integration_queue"]
        integration_queue = self._seal_projection(
            {
                "projection": "integration_queue",
                "status": "UNKNOWN",
                "planned_initial_state": "NOT_STARTED",
                "items": [
                    {
                        key: self._clone(item[key])
                        for key in (
                            "work_item_ref",
                            "title",
                            "dependency_refs",
                            "squad_refs",
                            "lane_affinity_ids",
                            "execution_status",
                        )
                    }
                    for item in queue["items"]
                ],
                "parallel_waves": self._clone(queue["parallel_waves"]),
                "program_contract": self._clone(program_contract),
                "reason_codes": self._clone(queue["reason_codes"]),
                "source_refs": self._clone(source_refs),
                "as_of": self._iso(checked_at),
            }
        )

        capacity = raw["capacity_risk"]
        capacity_risk = self._seal_projection(
            {
                "projection": "capacity_risk",
                "status": "UNKNOWN",
                "limits": self._clone(capacity["limits"]),
                "observed_active_writers": None,
                "observed_specialist_wip": None,
                "observed_lane_wip": None,
                "observed_weekly_company_outcomes": None,
                "capacity_proven_available": False,
                "program_contract": self._clone(program_contract),
                "reason_codes": self._clone(capacity["reason_codes"]),
                "source_refs": self._clone(source_refs),
                "as_of": self._iso(checked_at),
            }
        )

        release_train = raw["next_release_train"]
        next_release_train = self._seal_projection(
            {
                "projection": "next_release_train",
                "status": "UNKNOWN",
                "release_trains_per_week": release_train[
                    "release_trains_per_week"
                ],
                "scheduled_at": None,
                "eligible_work_item_refs": None,
                "gate_status": "UNKNOWN",
                "registry_proves_schedule": False,
                "program_contract": self._clone(program_contract),
                "reason_codes": self._clone(release_train["reason_codes"]),
                "source_refs": self._clone(source_refs),
                "as_of": self._iso(checked_at),
            }
        )
        return {
            "squad_readiness": squad_readiness,
            "role_conflicts": role_conflicts,
            "parallel_execution": parallel_execution,
            "integration_queue": integration_queue,
            "capacity_risk": capacity_risk,
            "next_release_train": next_release_train,
        }

    def _validate_enterprise_ai_erp_projection(self, value: Any) -> None:
        if not isinstance(value, Mapping):
            raise TeamControlTowerError(
                "Enterprise AI ERP program contract drift"
            )
        if (
            value.get("contract_id") != ENTERPRISE_AI_ERP_CONTRACT_ID
            or value.get("contract_version")
            != ENTERPRISE_AI_ERP_CONTRACT_VERSION
            or value.get("status") != "UNKNOWN"
        ):
            raise TeamControlTowerError(
                "Enterprise AI ERP program contract drift"
            )
        snapshot_sha256 = self._sha256(
            value.get("snapshot_sha256"),
            "enterprise_ai_erp_program.snapshot_sha256",
        )
        basis = self._clone(value)
        basis.pop("snapshot_sha256", None)
        if snapshot_sha256 != self._hash(basis):
            raise TeamControlTowerError(
                "Enterprise AI ERP program snapshot drift"
            )

        integrity = value.get("contract_integrity")
        if not isinstance(integrity, Mapping) or integrity.get("status") != "VERIFIED":
            raise TeamControlTowerError(
                "Enterprise AI ERP program integrity drift"
            )
        registry_sha256 = self._sha256(
            integrity.get("registry_sha256"),
            "enterprise_ai_erp_program.registry_sha256",
        )
        source_bundle_sha256 = self._sha256(
            integrity.get("source_bundle_sha256"),
            "enterprise_ai_erp_program.source_bundle_sha256",
        )
        source_hashes = value.get("source_hashes")
        if not isinstance(source_hashes, Sequence) or isinstance(
            source_hashes, (str, bytes)
        ):
            raise TeamControlTowerError(
                "Enterprise AI ERP program source contract drift"
            )
        source_map: dict[str, str] = {}
        for item in source_hashes:
            if not isinstance(item, Mapping):
                raise TeamControlTowerError(
                    "Enterprise AI ERP program source contract drift"
                )
            source_ref = self._identifier(
                item.get("source_ref"),
                "enterprise_ai_erp_program.source_ref",
            )
            if source_ref in source_map:
                raise TeamControlTowerError(
                    "Enterprise AI ERP program source contract drift"
                )
            source_map[source_ref] = self._sha256(
                item.get("sha256"),
                "enterprise_ai_erp_program.source_sha256",
            )
        if set(source_map) != {
            "capability_atlas",
            "enterprise_ai_erp_program",
            "global_expert_team",
            "team_control_tower",
        }:
            raise TeamControlTowerError(
                "Enterprise AI ERP program source contract drift"
            )
        if (
            source_map["enterprise_ai_erp_program"] != registry_sha256
            or self._hash(source_map) != source_bundle_sha256
        ):
            raise TeamControlTowerError(
                "Enterprise AI ERP program source hash drift"
            )

        counts = value.get("counts")
        if not isinstance(counts, Mapping) or counts != {
            "existing_core_roles": 18,
            "ai_specialists": 12,
            "enterprise_domain_roles": 14,
            "squads": 8,
            "day_0_30_work_items": 6,
            "independent_control_roles": 5,
            "expert_pool_capacity_minimum": 30,
            "expert_pool_capacity_maximum": 60,
            "sod_rules": 6,
            "maturity_levels": 5,
        }:
            raise TeamControlTowerError(
                "Enterprise AI ERP program counts drift"
            )
        envelope = value.get("control_envelope")
        if envelope != {
            "read_only": True,
            "static_registry_is_runtime_authority": False,
            "registry_proves_human_appointment": False,
            "registry_proves_active_wip": False,
            "registry_proves_maturity": False,
            "resolved_task_promotes_maturity": False,
            "operating_task_created": False,
            "fact_created": False,
            "finance_entry_created": False,
            "approval_created": False,
            "permit_created": False,
            "external_write_allowed": False,
        }:
            raise TeamControlTowerError(
                "Enterprise AI ERP program authority boundary drift"
            )

        sections = {
            name: value.get(name) for name in ENTERPRISE_AI_ERP_PROJECTION_KEYS
        }
        if any(
            not isinstance(section, Mapping)
            or section.get("status") != "UNKNOWN"
            for section in sections.values()
        ):
            raise TeamControlTowerError(
                "Enterprise AI ERP dynamic truth drift"
            )
        if any(
            not isinstance(section.get("reason_codes"), list)
            or not section["reason_codes"]
            for section in sections.values()
        ):
            raise TeamControlTowerError(
                "Enterprise AI ERP reason contract drift"
            )
        squads = sections["squad_readiness"]
        squad_fields = {
            "squad_ref",
            "title",
            "owner_role_ref",
            "reviewer_role_ref",
            "primary_lane_id",
            "supporting_lane_ids",
            "required_functions",
            "capability_atlas_ids",
            "capability_gap_refs",
            "work_item_refs",
            "first_acceptance_contract",
            "status",
            "reason_codes",
        }
        if (
            not isinstance(squads.get("items"), list)
            or len(squads["items"]) != 8
            or any(
                not isinstance(item, Mapping)
                or not squad_fields.issubset(item)
                or item.get("status") != "UNKNOWN"
                for item in squads["items"]
            )
        ):
            raise TeamControlTowerError("Enterprise AI ERP squad truth drift")
        conflicts = sections["role_conflicts"]
        rule_fields = {
            "rule_ref",
            "left_function_ref",
            "right_function_ref",
            "same_role_allowed",
            "same_principal_allowed",
            "identity_authority_required",
        }
        if (
            conflicts.get("contract_rules_verified") is not True
            or conflicts.get("observed_conflicts") is not None
            or not isinstance(conflicts.get("rules"), list)
            or len(conflicts["rules"]) != 6
            or any(
                not isinstance(rule, Mapping)
                or not rule_fields.issubset(rule)
                for rule in conflicts["rules"]
            )
        ):
            raise TeamControlTowerError("Enterprise AI ERP SoD truth drift")
        parallel = sections["parallel_execution"]
        expected_parallel_policy = {
            "control_agent_count": 1,
            "max_parallel_specialist_agents": 3,
            "max_active_writers": 3,
            "max_active_tasks_per_specialist": 1,
            "max_active_tasks_per_writer": 1,
            "max_current_tasks_per_lane": 1,
            "max_weekly_company_outcomes": 3,
            "release_trains_per_week": 2,
            "single_integrator_domains": [
                "registry",
                "runtime",
                "router",
                "openapi",
                "alembic_migration",
                "release",
            ],
            "runtime_assignment_authority_connected": False,
            "failed_slice_blocks_independent_slices": False,
            "path_or_hash_drift_action": "STOP_ZERO_WRITE",
            "shared_lease_conflict_action": "STOP_ZERO_WRITE",
        }
        if parallel.get("policy") != expected_parallel_policy:
            raise TeamControlTowerError(
                "Enterprise AI ERP parallel policy drift"
            )
        if any(
            parallel.get(field) is not None
            for field in (
                "observed_active_writers",
                "observed_writer_wip",
                "observed_lane_current_tasks",
            )
        ):
            raise TeamControlTowerError(
                "Enterprise AI ERP parallel truth drift"
            )
        queue = sections["integration_queue"]
        queue_item_fields = {
            "work_item_ref",
            "title",
            "dependency_refs",
            "squad_refs",
            "lane_affinity_ids",
            "execution_status",
        }
        if (
            queue.get("planned_initial_state") != "NOT_STARTED"
            or not isinstance(queue.get("items"), list)
            or len(queue["items"]) != 6
            or any(
                not isinstance(item, Mapping)
                or not queue_item_fields.issubset(item)
                or item.get("execution_status") != "UNKNOWN"
                for item in queue["items"]
            )
            or not isinstance(queue.get("parallel_waves"), list)
        ):
            raise TeamControlTowerError(
                "Enterprise AI ERP integration truth drift"
            )
        capacity = sections["capacity_risk"]
        if (
            capacity.get("limits")
            != {
                key: expected_parallel_policy[key]
                for key in (
                    "control_agent_count",
                    "max_parallel_specialist_agents",
                    "max_active_writers",
                    "max_active_tasks_per_specialist",
                    "max_active_tasks_per_writer",
                    "max_current_tasks_per_lane",
                    "max_weekly_company_outcomes",
                )
            }
            or capacity.get("capacity_proven_available") is not False
            or any(
                capacity.get(field) is not None
                for field in (
                    "observed_active_writers",
                    "observed_specialist_wip",
                    "observed_lane_wip",
                    "observed_weekly_company_outcomes",
                )
            )
        ):
            raise TeamControlTowerError(
                "Enterprise AI ERP capacity truth drift"
            )
        release_train = sections["next_release_train"]
        if (
            release_train.get("release_trains_per_week") != 2
            or release_train.get("scheduled_at") is not None
            or release_train.get("eligible_work_item_refs") is not None
            or release_train.get("gate_status") != "UNKNOWN"
            or release_train.get("registry_proves_schedule") is not False
        ):
            raise TeamControlTowerError(
                "Enterprise AI ERP release truth drift"
            )
        if (
            registry_sha256 != ENTERPRISE_AI_ERP_TRUSTED_REGISTRY_SHA256
            or source_bundle_sha256
            != ENTERPRISE_AI_ERP_TRUSTED_SOURCE_BUNDLE_SHA256
            or snapshot_sha256 != ENTERPRISE_AI_ERP_TRUSTED_SNAPSHOT_SHA256
        ):
            raise TeamControlTowerError(
                "Enterprise AI ERP trusted contract drift"
            )

    def _unknown_projection(
        self,
        *,
        name: str,
        checked_at: datetime,
        reason_code: str,
    ) -> dict[str, Any]:
        return self._seal_projection(
            {
                "projection": name,
                "status": "UNKNOWN",
                "reason_codes": [reason_code],
                "source_refs": [],
                "as_of": self._iso(checked_at),
            }
        )

    def _seal_projection(self, projection: dict[str, Any]) -> dict[str, Any]:
        if projection.get("status") not in TRUTH_STATES:
            raise TeamControlTowerError("Projection truth state is invalid")
        projection["projection_sha256"] = self._hash(projection)
        return projection

    def _decision_projection_sha256(self, projection: Mapping[str, Any]) -> str:
        def stable(value: Any) -> Any:
            if isinstance(value, Mapping):
                return {
                    str(key): stable(item)
                    for key, item in value.items()
                    if key
                    not in {
                        "as_of",
                        "projection_sha256",
                        "source_snapshot_sha256",
                    }
                }
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                return [stable(item) for item in value]
            return value

        return self._hash(stable(projection))

    def _next_action(
        self,
        *,
        scope: Mapping[str, Any],
        flows: Sequence[Mapping[str, Any]],
        active_tasks: Sequence[Mapping[str, Any]],
        critical_path: Mapping[str, Any],
        checked_at: datetime,
        decision_basis_sha256: str,
    ) -> dict[str, Any] | None:
        ranked = self._rank_tasks(active_tasks, checked_at)
        if ranked:
            task = ranked[0]
            metadata = self._team_metadata(task)
            status = str(task["status"])
            if status == "open":
                kind, label, allowed = "take_task", f"确认并领取：{task['title']}", ["take"]
            elif status == "acknowledged":
                kind, label, allowed = "start_task", f"开始执行：{task['title']}", ["take"]
            else:
                kind, label, allowed = (
                    "complete_or_escalate",
                    str(task["snapshot"].get("next_action") or f"推进：{task['title']}"),
                    ["done", "blocked", "escalate", "stop"],
                )
            target = {
                "type": "task",
                "task": self._clone(task),
                "expected_status": status,
            }
            action = {
                "kind": kind,
                "label": label,
                "owner": task["owner"],
                "risk_level": metadata["risk_level"],
                "due_at": self._iso(self._due_at(task)),
                "blocker_refs": list(task["snapshot"].get("blockers", [])),
                "required_evidence": list(task["snapshot"].get("success_evidence", [])),
                "allowed_results": allowed,
                "target": target,
                "evidence_required": False,
            }
            campaign = self.registry["campaign_90d"]
            if (
                status == "acknowledged"
                and metadata.get("campaign_ref") == campaign["campaign_ref"]
                and metadata.get("phase_ref")
                == campaign["coordination"]["kickoff_phase_ref"]
            ):
                action["evidence_required"] = True
                action["required_evidence"] = ["campaign_kickoff_evidence"]
        else:
            campaign_phase = next(
                (
                    item
                    for item in critical_path.get("phases", [])
                    if item.get("phase_ref")
                    == self.registry["campaign_90d"]["coordination"][
                        "kickoff_phase_ref"
                    ]
                    and item.get("current_operating_task") is None
                ),
                None,
            )
            if campaign_phase is not None:
                action = {
                    "kind": "open_campaign_phase",
                    "label": f"启动 90 天战役协调：{campaign_phase['title']}",
                    "owner": campaign_phase["owner_role"],
                    "risk_level": "L1",
                    "due_at": None,
                    "blocker_refs": list(campaign_phase["blockers"]),
                    "required_evidence": ["campaign_kickoff_evidence"],
                    "evidence_required": False,
                    "allowed_results": ["take"],
                    "target": {
                        "type": "campaign_phase",
                        "campaign_ref": critical_path["campaign_ref"],
                        "phase_ref": campaign_phase["phase_ref"],
                        "expected_status": campaign_phase["status"],
                    },
                }
            else:
                action = None
            flow_by_ref = {item["flow_ref"]: item for item in flows}
            flow = next(
                (
                    flow_by_ref[item]
                    for item in self.registry["focus_policy"]["priority_order"]
                    if item in flow_by_ref
                    and flow_by_ref[item]["runtime_status"] not in {"resolved", "dismissed"}
                ),
                None,
            )
            if action is None:
                if flow is None:
                    return None
                action = {
                    "kind": "open_work",
                    "label": flow["default_next_action"],
                    "owner": flow["accountable_role"],
                    "risk_level": flow["risk_level"],
                    "due_at": None,
                    "blocker_refs": list(flow["blockers"]),
                    "required_evidence": list(flow["success_evidence"]),
                    "evidence_required": False,
                    "allowed_results": ["take"],
                    "target": {
                        "type": "flow",
                        "flow_ref": flow["flow_ref"],
                        "expected_status": flow["runtime_status"],
                    },
                }
        action["decision_basis_sha256"] = decision_basis_sha256
        action["continuation"] = self._continuation(
            scope=scope,
            action=action,
            decision_basis_sha256=decision_basis_sha256,
        )
        return action

    def _campaign_phase(self, phase_ref: str) -> Mapping[str, Any]:
        for phase in self.registry["campaign_90d"]["phases"]:
            if phase["phase_ref"] == phase_ref:
                return phase
        raise TeamControlTowerError("Unknown campaign phase")

    def _conflicts(self, active_tasks: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        conflicts: list[dict[str, Any]] = []
        owner_counts = Counter(str(item["owner"]) for item in active_tasks)
        maximum = int(self.registry["focus_policy"]["max_active_tasks_per_specialist"])
        for owner, count in sorted(owner_counts.items()):
            if count > maximum:
                conflicts.append(
                    {
                        "code": "specialist_wip_limit_exceeded",
                        "owner": owner,
                        "active_count": count,
                        "maximum": maximum,
                        "requires_leader_decision": True,
                    }
                )
        write_owners: dict[str, list[str]] = defaultdict(list)
        for lane in self.workstreams["lanes"]:
            task = lane.get("current_task")
            if task:
                for write_scope in task.get("write_scope", []):
                    write_owners[str(write_scope)].append(str(task["task_id"]))
        for write_scope, task_ids in sorted(write_owners.items()):
            if len(set(task_ids)) > 1:
                conflicts.append(
                    {
                        "code": "shared_write_scope_conflict",
                        "write_scope": write_scope,
                        "task_ids": sorted(set(task_ids)),
                        "requires_leader_decision": True,
                    }
                )
        return conflicts

    def _scoped_tasks(
        self,
        *,
        principal: Principal,
        entity_scope: Mapping[str, Any],
        store_ref: str,
        checked_at: datetime,
    ) -> list[dict[str, Any]]:
        if self._scope(principal=principal, entity_scope=entity_scope, store_ref=store_ref) is None:
            raise TeamControlTowerError("Current exact-scope authority is unavailable")
        return self.operating_tasks.tasks(
            limit=1000,
            principal=principal,
            entity_scope=dict(entity_scope),
            store_ref=store_ref,
            as_of=self._iso(checked_at),
        )

    def _idempotent_receipt(
        self,
        *,
        tasks: Sequence[Mapping[str, Any]],
        idempotency_key: str,
        command_sha256: str,
    ) -> dict[str, Any] | None:
        for task in tasks:
            metadata = self._team_metadata(task)
            if metadata and metadata.get("last_command_idempotency_key") == idempotency_key:
                if metadata.get("last_command_sha256") != command_sha256:
                    raise TeamControlTowerError("Idempotency key payload drift")
                return self._receipt(
                    outcome="idempotent_replay",
                    task=task,
                    event=None,
                    continuation=str(metadata.get("continuation") or "0" * 64),
                    idempotency_key=idempotency_key,
                    command_sha256=command_sha256,
                )
            if not metadata:
                continue
            for event in self.operating_tasks.task_events(str(task["id"])):
                command = event.get("payload", {}).get("team_control_command", {})
                if command.get("idempotency_key") != idempotency_key:
                    continue
                if command.get("command_sha256") != command_sha256:
                    raise TeamControlTowerError("Idempotency key payload drift")
                return self._receipt(
                    outcome="idempotent_replay",
                    task=task,
                    event=event,
                    continuation=str(command["continuation"]),
                    idempotency_key=idempotency_key,
                    command_sha256=command_sha256,
                )
        return None

    def _verify_evidence(
        self,
        *,
        evidence_ids: list[str],
        principal: Principal,
        entity_scope: Mapping[str, Any],
        store_ref: str,
        checked_at: datetime,
    ) -> None:
        if not evidence_ids:
            return
        if self.scoped_evidence is None:
            raise TeamControlTowerError("Scoped Evidence authority is unavailable")
        projection = self.scoped_evidence.project(
            evidence_ids=evidence_ids,
            principal=principal,
            entity_scope=dict(entity_scope),
            store_ref=store_ref,
            as_of=checked_at,
        )
        if projection.get("status") != "ready":
            raise TeamControlTowerError("Evidence must be current and bound to exact scope")

    @classmethod
    def _scope(
        cls,
        *,
        principal: Principal,
        entity_scope: Mapping[str, Any],
        store_ref: str,
    ) -> dict[str, str] | None:
        if not principal.can_access_store(store_ref):
            raise PermissionError("Authenticated identity is not authorized for store_ref")
        tenant_ref = principal.tenant_ref.strip()
        entity_ref = str(entity_scope.get("entity_ref") or "").strip()
        authority_sha256 = str(entity_scope.get("authority_sha256") or "").strip()
        if entity_scope.get("status") != "ready" or not tenant_ref or not entity_ref:
            return None
        if not _SHA256.fullmatch(authority_sha256):
            raise TeamControlTowerError("Ready exact scope requires a SHA-256 authority")
        return {
            "tenant_ref": tenant_ref,
            "entity_ref": entity_ref,
            "store_ref": store_ref,
            "scope_authority_sha256": authority_sha256,
        }

    @staticmethod
    def _entity_scope(scope: Mapping[str, str]) -> dict[str, str]:
        return {
            "status": "ready",
            "entity_ref": scope["entity_ref"],
            "authority_sha256": scope["scope_authority_sha256"],
        }

    @staticmethod
    def _team_metadata(task: Mapping[str, Any]) -> dict[str, Any] | None:
        value = task.get("snapshot", {}).get("control_tower")
        return dict(value) if isinstance(value, Mapping) else None

    @staticmethod
    def _task_summary(task: Mapping[str, Any] | None) -> dict[str, Any] | None:
        if task is None:
            return None
        return {
            key: task[key]
            for key in (
                "id",
                "title",
                "severity",
                "owner",
                "status",
                "created_at",
                "updated_at",
            )
        }

    def _rank_tasks(
        self,
        tasks: Sequence[Mapping[str, Any]],
        checked_at: datetime,
    ) -> list[Mapping[str, Any]]:
        severity = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        return sorted(
            tasks,
            key=lambda item: (
                0 if checked_at > self._due_at(item) else 1,
                severity.get(str(item.get("severity")), 9),
                self._due_at(item),
                str(item.get("id")),
            ),
        )

    @staticmethod
    def _due_at(task: Mapping[str, Any]) -> datetime:
        hours = int(task.get("snapshot", {}).get("expert_route", {}).get("default_sla_hours", 24))
        created = TeamControlTower._datetime(task["created_at"])
        return created + timedelta(hours=hours)

    def _continuation(
        self,
        *,
        scope: Mapping[str, Any],
        action: Mapping[str, Any],
        decision_basis_sha256: str,
    ) -> str:
        return self._hash(
            {
                "contract_id": CONTRACT_ID,
                "registry_sha256": self.registry_sha256,
                "workstream_sha256": self.workstream_sha256,
                "decision_basis_sha256": decision_basis_sha256,
                "scope": scope,
                "kind": action["kind"],
                "owner": action["owner"],
                "risk_level": action["risk_level"],
                "allowed_results": action["allowed_results"],
                "target": action["target"],
            }
        )

    def _receipt(
        self,
        *,
        outcome: str,
        task: Mapping[str, Any],
        event: Mapping[str, Any] | None,
        continuation: str,
        idempotency_key: str,
        command_sha256: str,
    ) -> dict[str, Any]:
        receipt = {
            "contract_id": CONTRACT_ID,
            "outcome": outcome,
            "operating_task": self._task_summary(task),
            "event": self._clone(event),
            "continuation": continuation,
            "idempotency_key": idempotency_key,
            "command_sha256": command_sha256,
            "authority_handoff": None,
            "external_write_allowed": False,
            "approval_created": False,
            "permit_issued": False,
        }
        receipt["receipt_sha256"] = self._hash(receipt)
        return receipt

    @staticmethod
    def _headline(*, status: str, next_action: Mapping[str, Any] | None) -> str:
        if next_action is None:
            return "当前没有可推进动作。"
        return f"{status} · 唯一下一动作：{next_action['label']}"

    @staticmethod
    def _empty_summary() -> dict[str, Any]:
        return {
            "flow_count": 4,
            "active_flow_count": 0,
            "blocked_flow_count": 0,
            "active_team_task_count": 0,
            "overdue_task_count": 0,
            "conflict_count": 0,
            "human_binding_ready": False,
        }

    @staticmethod
    def _unscoped_flow(flow: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "flow_ref": flow["flow_ref"],
            "display_title": flow["display_title"],
            "declared_state": flow["declared_state"],
            "runtime_status": "scope_invalid",
            "accountable_role": flow["accountable_role"],
            "blockers": ["exact_scope_authority_unavailable"],
            "current_operating_task": None,
        }

    def _source_refs(self) -> list[dict[str, str]]:
        return [
            {
                "ref": "team_control_tower_registry",
                "sha256": self.registry_sha256,
            },
            {
                "ref": "active_workstream_assignments",
                "sha256": self.workstream_sha256,
            },
            {
                "ref": "global_expert_team_registry",
                "sha256": self.expert_team.registry_sha256,
            },
            {
                "ref": "strategic_benchmark_contracts",
                "sha256": self.benchmark_contract_sha256,
            },
        ]

    @staticmethod
    def _control_envelope() -> dict[str, bool]:
        return {
            "projection_only": True,
            "creates_second_task_ledger": False,
            "creates_fact": False,
            "creates_finance_entry": False,
            "creates_approval": False,
            "issues_permit": False,
            "holds_platform_credentials": False,
            "performs_external_write": False,
            "creates_human_appointment": False,
            "recomputes_benchmark": False,
            "creates_cash_forecast": False,
            "claims_global_top1": False,
        }

    @classmethod
    def _validate_registry(
        cls,
        value: Any,
        benchmark_contracts: Any,
    ) -> None:
        if not isinstance(value, dict):
            raise TeamControlTowerError("Team control registry must be an object")
        if value.get("schema_version") != SCHEMA_VERSION or value.get("contract_id") != CONTRACT_ID:
            raise TeamControlTowerError("Team control registry contract drift")
        if value.get("status") != "active_contract":
            raise TeamControlTowerError("Team control registry must be active")
        policy = value.get("focus_policy")
        if not isinstance(policy, dict):
            raise TeamControlTowerError("Team control focus policy is required")
        if policy.get("one_executive_next_action") is not True:
            raise TeamControlTowerError("Team control must expose one executive next action")
        if tuple(policy.get("priority_order", ())) != (
            "lg001_exact_scope",
            "sku_closed_loop",
            "project_control_commercialization",
            "dual_engine_commercialization",
        ):
            raise TeamControlTowerError("Team control priority order drift")
        maximum = policy.get("max_active_tasks_per_specialist")
        if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum != 1:
            raise TeamControlTowerError("Specialist WIP must remain one")
        flows = value.get("flows")
        if not isinstance(flows, list) or len(flows) != 4:
            raise TeamControlTowerError("Team control requires four frozen flows")
        if tuple(item.get("flow_ref") for item in flows) != FLOW_REFS:
            raise TeamControlTowerError("Team control flow set or order drift")
        required = {
            "flow_ref",
            "display_title",
            "objective",
            "declared_state",
            "accountable_role",
            "source_lane_ids",
            "default_task_ref",
            "default_task_type",
            "market",
            "platform",
            "risk_level",
            "severity",
            "default_next_action",
            "success_evidence",
        }
        for flow in flows:
            if not isinstance(flow, dict) or not required <= set(flow):
                raise TeamControlTowerError("Team control flow is incomplete")
            cls._identifier(flow["flow_ref"], "flow_ref")
            cls._identifier(flow["accountable_role"], "accountable_role")
            cls._identifier(flow["default_task_ref"], "default_task_ref")
            if flow["risk_level"] not in {"L0", "L1", "L2", "L3", "L4"}:
                raise TeamControlTowerError("Team control flow risk is invalid")
            if flow["severity"] not in {"critical", "high", "medium", "low"}:
                raise TeamControlTowerError("Team control flow severity is invalid")
            for field in ("source_lane_ids", "success_evidence"):
                cls._identifiers(flow[field], field, maximum=50)

        metric_specs = cls._benchmark_metric_specs(benchmark_contracts)
        best = value.get("best_solution_assessment")
        if not isinstance(best, dict):
            raise TeamControlTowerError("Best-solution assessment is required")
        if set((best.get("options") or {}).keys()) != {
            "build",
            "buy",
            "partner",
            "defer",
            "no_action",
        }:
            raise TeamControlTowerError("Best-solution option set drift")
        if best.get("selected_option") != "partner":
            raise TeamControlTowerError("Layered hybrid team selection drift")
        if best.get("status") != "proposal_only_requires_human_business_owner":
            raise TeamControlTowerError("Best-solution decision must remain proposal-only")
        for field in (
            "rejected_options_and_reasons",
            "hard_elimination_dimensions",
            "comparison_dimensions",
            "sensitivity",
            "invalidation_conditions",
        ):
            if not best.get(field):
                raise TeamControlTowerError("Best-solution assessment is incomplete")

        organization = value.get("organization_model")
        if not isinstance(organization, dict):
            raise TeamControlTowerError("Organization model is required")
        if (
            organization.get("human_core_required") != 18
            or organization.get("ai_specialists_required") != 12
            or organization.get("independent_control_roles_required") != 5
            or organization.get("expert_pool_target") != {"minimum": 20, "maximum": 40}
        ):
            raise TeamControlTowerError("Organization capacity contract drift")
        ai_role_refs = cls._identifiers(
            organization.get("ai_specialist_role_refs"),
            "ai_specialist_role_ref",
            maximum=12,
        )
        if len(ai_role_refs) != 12:
            raise TeamControlTowerError("Organization requires 12 AI specialist references")
        appointment_contract = organization.get("appointment_evidence_contract")
        expected_appointment_fields = {
            "primary_human_ref",
            "alternate_human_ref",
            "appointment_evidence_refs",
            "professional_scope_evidence_refs",
            "conflict_attestation_evidence_ref",
            "budget_cap_status",
            "maximum_loss_status",
        }
        if (
            not isinstance(appointment_contract, dict)
            or appointment_contract.get("status") not in TRUTH_STATES
            or appointment_contract.get("registry_declaration_proves_appointment") is not False
            or set(appointment_contract.get("required_binding_fields") or ())
            != expected_appointment_fields
        ):
            raise TeamControlTowerError("Appointment Evidence contract drift")
        cls._identifiers(
            appointment_contract.get("current_verified_binding_refs"),
            "verified_binding_ref",
            maximum=18,
        )
        control_refs = cls._identifiers(
            organization.get("control_role_refs"),
            "control_role_ref",
            maximum=5,
        )
        expected_controls = {
            "human_business_owner",
            "independent_verifier",
            "independent_approver",
            "risk_authority",
            "executor",
        }
        if set(control_refs) != expected_controls or len(control_refs) != 5:
            raise TeamControlTowerError("Independent control role set drift")
        roles = organization.get("core_roles")
        if not isinstance(roles, list) or len(roles) != 18:
            raise TeamControlTowerError("Organization requires 18 core role contracts")
        core_ids: list[str] = []
        role_required = {
            "role_id",
            "title",
            "group",
            "mission",
            "outcomes",
            "tool_allowlist",
            "data_allowlist",
            "default_sla_hours",
            "independent_reviewer_role",
            "binding",
            "completion_evidence",
            "handoff_conditions",
        }
        for role in roles:
            if not isinstance(role, dict) or not role_required <= set(role):
                raise TeamControlTowerError("Core role contract is incomplete")
            role_id = cls._identifier(role["role_id"], "role_id")
            core_ids.append(role_id)
            outcomes = role["outcomes"]
            if not isinstance(outcomes, dict) or set(outcomes) != {
                "day_30",
                "day_60",
                "day_90",
            }:
                raise TeamControlTowerError("Core role requires 30/60/90 outcomes")
            for outcome in outcomes.values():
                if not cls._identifiers(outcome, "role_outcome", maximum=20):
                    raise TeamControlTowerError("Core role outcome cannot be empty")
            if not cls._identifiers(role["tool_allowlist"], "tool", maximum=50):
                raise TeamControlTowerError("Core role tool allowlist cannot be empty")
            if not cls._identifiers(role["data_allowlist"], "data", maximum=50):
                raise TeamControlTowerError("Core role data allowlist cannot be empty")
            sla = role["default_sla_hours"]
            if isinstance(sla, bool) or not isinstance(sla, int) or sla <= 0:
                raise TeamControlTowerError("Core role SLA is invalid")
            cls._identifier(role["independent_reviewer_role"], "reviewer_role")
            if not cls._identifiers(role["completion_evidence"], "completion_evidence", maximum=50):
                raise TeamControlTowerError("Core role completion Evidence is required")
            if not cls._identifiers(role["handoff_conditions"], "handoff_condition", maximum=50):
                raise TeamControlTowerError("Core role handoff conditions are required")
            cls._validate_binding(role["binding"])
        if len(core_ids) != len(set(core_ids)):
            raise TeamControlTowerError("Core role identifiers must be unique")
        known_roles = set(core_ids) | expected_controls
        for role in roles:
            if role["independent_reviewer_role"] not in known_roles:
                raise TeamControlTowerError("Core role reviewer reference is unknown")
        council = cls._identifiers(
            organization.get("executive_council_role_refs"),
            "executive_council_role_ref",
            maximum=10,
        )
        if len(council) != 6 or not set(council) <= known_roles:
            raise TeamControlTowerError("Executive council contract drift")
        categories = organization.get("expert_pool_categories")
        if not isinstance(categories, list) or len(categories) < 9:
            raise TeamControlTowerError("Expert pool requires nine capability categories")
        category_refs = []
        for item in categories:
            if not isinstance(item, dict) or not {
                "category_ref",
                "title",
                "required_review_scope",
            } <= set(item):
                raise TeamControlTowerError("Expert pool category is incomplete")
            category_refs.append(cls._identifier(item["category_ref"], "category_ref"))
            if not cls._identifiers(item["required_review_scope"], "review_scope", maximum=20):
                raise TeamControlTowerError("Expert pool review scope is required")
        if len(category_refs) != len(set(category_refs)):
            raise TeamControlTowerError("Expert pool categories must be unique")

        campaign = value.get("campaign_90d")
        if not isinstance(campaign, dict) or campaign.get("duration_days") != 90:
            raise TeamControlTowerError("90-day campaign contract is required")
        try:
            date.fromisoformat(str(campaign["planned_start_on"]))
        except (KeyError, ValueError) as exc:
            raise TeamControlTowerError("Campaign planned start date is invalid") from exc
        if campaign.get("maximum_weekly_company_outcomes") != 3:
            raise TeamControlTowerError("Weekly company outcome limit must remain three")
        coordination = campaign.get("coordination")
        if not isinstance(coordination, dict) or coordination != {
            "task_authority": "operating_task_event",
            "task_kind_prefix": "team_control:campaign",
            "kickoff_phase_ref": "day_1_7_organization_freeze",
            "kickoff_event_type": "start",
            "kickoff_evidence_required": True,
            "task_completion_proves_gate_pass": False,
            "calendar_proves_gate_pass": False,
            "open_next_phase_without_formal_gate_pass": False,
            "creates_campaign_ledger": False,
            "adds_external_interface": False,
        }:
            raise TeamControlTowerError("Campaign coordination authority drift")
        active_lanes = cls._identifiers(campaign.get("active_lane_ids"), "active_lane", maximum=13)
        prep_lanes = cls._identifiers(campaign.get("preparation_only_lane_ids"), "preparation_lane", maximum=13)
        if set(active_lanes) != {"A", "B", "C", "D", "E", "I", "L", "M"}:
            raise TeamControlTowerError("Campaign active lane set drift")
        if set(prep_lanes) != {"F", "G", "H"}:
            raise TeamControlTowerError("Preparation-only lane set drift")
        phases = campaign.get("phases")
        if not isinstance(phases, list) or len(phases) != 4:
            raise TeamControlTowerError("Campaign requires four phases")
        phase_ranges = [(1, 7), (8, 30), (31, 60), (61, 90)]
        phase_refs: list[str] = []
        for phase, expected_range in zip(phases, phase_ranges, strict=True):
            required_phase = {
                "phase_ref",
                "day_from",
                "day_to",
                "title",
                "owner_role",
                "reviewer_role",
                "source_lane_ids",
                "required_evidence",
                "gate_refs",
                "stop_conditions",
            }
            if not isinstance(phase, dict) or not required_phase <= set(phase):
                raise TeamControlTowerError("Campaign phase is incomplete")
            if (phase["day_from"], phase["day_to"]) != expected_range:
                raise TeamControlTowerError("Campaign phase range drift")
            phase_refs.append(cls._identifier(phase["phase_ref"], "phase_ref"))
            for role_field in ("owner_role", "reviewer_role"):
                if phase[role_field] not in known_roles:
                    raise TeamControlTowerError("Campaign phase role reference is unknown")
            for field in ("source_lane_ids", "required_evidence", "gate_refs", "stop_conditions"):
                if not cls._identifiers(phase[field], field, maximum=50):
                    raise TeamControlTowerError("Campaign phase contract list is empty")
        if len(phase_refs) != len(set(phase_refs)):
            raise TeamControlTowerError("Campaign phase identifiers must be unique")
        if coordination["kickoff_phase_ref"] != phase_refs[0]:
            raise TeamControlTowerError("Campaign kickoff phase drift")

        scorecard = value.get("top1_scorecard_profile")
        if not isinstance(scorecard, dict):
            raise TeamControlTowerError("Top1 scorecard profile is required")
        if scorecard.get("global_top1_claim_allowed") is not False:
            raise TeamControlTowerError("Global Top1 claims must remain prohibited")
        if scorecard.get("minimum_comparable_peers") != 5 or scorecard.get("maximum_comparable_peers") != 10:
            raise TeamControlTowerError("Top1 comparable peer contract drift")
        dimensions = scorecard.get("dimensions")
        if not isinstance(dimensions, list) or len(dimensions) != 12:
            raise TeamControlTowerError("Top1 scorecard requires twelve dimensions")
        dimension_refs: list[str] = []
        for item in dimensions:
            required_dimension = {
                "dimension_ref",
                "title",
                "metric_definition",
                "benchmark_selector",
                "owner_role",
                "verifier_role",
                "next_experiment",
                "freshness_days",
            }
            if not isinstance(item, dict) or not required_dimension <= set(item):
                raise TeamControlTowerError("Top1 dimension is incomplete")
            dimension_refs.append(cls._identifier(item["dimension_ref"], "dimension_ref"))
            cls._validate_selector(item["benchmark_selector"], metric_specs)
            if item["owner_role"] not in known_roles or item["verifier_role"] not in known_roles:
                raise TeamControlTowerError("Top1 dimension role reference is unknown")
            freshness = item["freshness_days"]
            if isinstance(freshness, bool) or not isinstance(freshness, int) or freshness <= 0:
                raise TeamControlTowerError("Top1 dimension freshness is invalid")
        if len(dimension_refs) != len(set(dimension_refs)):
            raise TeamControlTowerError("Top1 dimension identifiers must be unique")

        cash = value.get("cash_at_risk_policy")
        if not isinstance(cash, dict) or cash.get("forecast_weeks") != 13:
            raise TeamControlTowerError("13-week cash-at-risk policy is required")
        if cash.get("budget_authority") is not False or cash.get("payment_authority") is not False:
            raise TeamControlTowerError("Cash projection cannot grant authority")
        if not cls._identifiers(cash.get("required_inputs"), "cash_input", maximum=20):
            raise TeamControlTowerError("Cash authority inputs are required")
        actual_cash = cash.get("actual_cash_authority")
        if not isinstance(actual_cash, dict) or actual_cash != {
            "contract_id": SETTLEMENT_CASH_CONTRACT_ID,
            "exact_scope_required": True,
            "read_only": True,
            "minimum_reconciled_cycles": 1,
            "requires_order_fact": True,
            "requires_platform_settlement": True,
            "requires_bank_cash": True,
            "requires_actual_cash_cm3": True,
            "requires_single_sku_attribution": True,
            "offer_mapping_proven": False,
            "return_window_closed_proven": False,
            "satisfies_thirteen_week_forecast": False,
            "satisfies_cash_floor": False,
            "satisfies_maximum_loss": False,
        }:
            raise TeamControlTowerError("Actual cash authority contract drift")
        selectors = cash.get("benchmark_selectors")
        if not isinstance(selectors, list) or len(selectors) != 2:
            raise TeamControlTowerError("Cash projection requires two benchmark selectors")
        for selector in selectors:
            cls._validate_selector(selector, metric_specs)

        gate_profile = value.get("delivery_gate_profile")
        gates = gate_profile.get("gates") if isinstance(gate_profile, dict) else None
        if (
            not isinstance(gate_profile, dict)
            or gate_profile.get("canonical_authority_status") != "unbound"
            or gate_profile.get("task_or_calendar_can_pass") is not False
        ):
            raise TeamControlTowerError("Delivery gate authority contract drift")
        if not isinstance(gates, list) or len(gates) != 5:
            raise TeamControlTowerError("Delivery profile requires five gates")
        gate_refs: list[str] = []
        for gate in gates:
            if not isinstance(gate, dict) or not {
                "gate_ref",
                "title",
                "owner_role",
                "source_lane_ids",
                "pass_requires",
            } <= set(gate):
                raise TeamControlTowerError("Delivery gate contract is incomplete")
            gate_refs.append(cls._identifier(gate["gate_ref"], "gate_ref"))
            if gate["owner_role"] not in known_roles:
                raise TeamControlTowerError("Delivery gate owner reference is unknown")
            if not cls._identifiers(gate["source_lane_ids"], "gate_lane", maximum=13):
                raise TeamControlTowerError("Delivery gate lane list is empty")
            if not cls._identifiers(gate["pass_requires"], "gate_requirement", maximum=50):
                raise TeamControlTowerError("Delivery gate acceptance is empty")
        if len(gate_refs) != len(set(gate_refs)):
            raise TeamControlTowerError("Delivery gate identifiers must be unique")
        boundary = value.get("control_boundary")
        if not isinstance(boundary, dict) or not boundary or any(item is not False for item in boundary.values()):
            raise TeamControlTowerError("Team control boundary must fail closed")

    @classmethod
    def _validate_binding(cls, value: Any) -> None:
        if not isinstance(value, dict):
            raise TeamControlTowerError("Core role binding must be an object")
        required = {
            "status",
            "primary_human_ref",
            "alternate_human_ref",
            "conflict_attestation_evidence_ref",
            "budget_cap_status",
            "maximum_loss_status",
        }
        if not required <= set(value):
            raise TeamControlTowerError("Core role binding is incomplete")
        if value["status"] not in {"unbound", "candidate", "verified_active", "suspended"}:
            raise TeamControlTowerError("Core role binding status is invalid")
        for field in ("budget_cap_status", "maximum_loss_status"):
            if value[field] not in TRUTH_STATES:
                raise TeamControlTowerError("Core role authority truth state is invalid")
        if value["status"] != "verified_active":
            return
        for field in (
            "primary_human_ref",
            "alternate_human_ref",
            "conflict_attestation_evidence_ref",
        ):
            cls._identifier(value[field], field)
        if value["primary_human_ref"] == value["alternate_human_ref"]:
            raise TeamControlTowerError("Core role primary and alternate must differ")
        for field in ("appointment_evidence_refs", "professional_scope_evidence_refs"):
            evidence_refs = value.get(field)
            if not isinstance(evidence_refs, Sequence) or isinstance(
                evidence_refs, (str, bytes)
            ):
                raise TeamControlTowerError("Verified binding Evidence is required")
            if not cls._identifiers(evidence_refs, field, maximum=20):
                raise TeamControlTowerError("Verified binding Evidence is required")
        if value["budget_cap_status"] != "VERIFIED" or value["maximum_loss_status"] != "VERIFIED":
            raise TeamControlTowerError("Verified binding requires budget and maximum loss")

    @classmethod
    def _benchmark_metric_specs(cls, value: Any) -> set[tuple[str, str]]:
        if not isinstance(value, dict) or value.get("schema_version") != BENCHMARK_SCHEMA_VERSION:
            raise TeamControlTowerError("Strategic benchmark registry contract drift")
        if value.get("top1_semantics", {}).get("global_top1_allowed") is not False:
            raise TeamControlTowerError("Strategic benchmark must prohibit global Top1")
        domains = value.get("domains")
        if not isinstance(domains, list) or not domains:
            raise TeamControlTowerError("Strategic benchmark metric registry is empty")
        specs: set[tuple[str, str]] = set()
        for domain in domains:
            if not isinstance(domain, dict) or not isinstance(domain.get("metrics"), list):
                raise TeamControlTowerError("Strategic benchmark domain shape drift")
            domain_id = cls._identifier(domain.get("id"), "benchmark_domain")
            for metric in domain["metrics"]:
                if not isinstance(metric, dict):
                    raise TeamControlTowerError("Strategic benchmark metric shape drift")
                selector = (domain_id, cls._identifier(metric.get("id"), "benchmark_metric"))
                if selector in specs:
                    raise TeamControlTowerError("Strategic benchmark selector duplicated")
                specs.add(selector)
        return specs

    @classmethod
    def _validate_selector(
        cls,
        value: Any,
        metric_specs: set[tuple[str, str]],
    ) -> None:
        if not isinstance(value, dict) or set(value) != {"domain", "metric_id"}:
            raise TeamControlTowerError("Benchmark selector shape drift")
        selector = (
            cls._identifier(value["domain"], "benchmark_domain"),
            cls._identifier(value["metric_id"], "benchmark_metric"),
        )
        if selector not in metric_specs:
            raise TeamControlTowerError("Benchmark selector is unknown")

    @classmethod
    def _validate_workstreams(
        cls,
        value: Any,
        *,
        required_lane_ids: set[str],
    ) -> None:
        if not isinstance(value, dict) or value.get("schema_version") != "kjds-active-workstream-assignments-v1":
            raise TeamControlTowerError("Active workstream registry contract drift")
        policy = value.get("policy")
        if not isinstance(policy, dict) or policy.get("max_current_tasks_per_lane") != 1:
            raise TeamControlTowerError("Active workstream WIP policy drift")
        lanes = value.get("lanes")
        if not isinstance(lanes, list) or not lanes:
            raise TeamControlTowerError("Active workstream lanes are required")
        if any(not isinstance(item, dict) for item in lanes):
            raise TeamControlTowerError("Active workstream lanes must be objects")
        lane_ids = [cls._identifier(item.get("id"), "lane_id") for item in lanes]
        if len(lane_ids) != len(set(lane_ids)):
            raise TeamControlTowerError("Active workstream lane identifiers must be unique")
        known = set(lane_ids)
        if not required_lane_ids <= known:
            raise TeamControlTowerError("Team control references an unknown workstream lane")

    @staticmethod
    def _read_json(path: Path, label: str) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TeamControlTowerError(f"Unable to load {label}: {path}") from exc
        if not isinstance(value, dict):
            raise TeamControlTowerError(f"{label} must be an object")
        return value

    @classmethod
    def _identifiers(
        cls, values: Sequence[str], field: str, *, maximum: int
    ) -> tuple[str, ...]:
        if (
            not isinstance(values, Sequence)
            or isinstance(values, (str, bytes))
            or len(values) > maximum
        ):
            raise TeamControlTowerError(f"{field} must be a bounded sequence")
        result = tuple(cls._identifier(item, field) for item in values)
        if len(result) != len(set(result)):
            raise TeamControlTowerError(f"{field} values must be unique")
        return result

    @staticmethod
    def _identifier(value: Any, field: str) -> str:
        result = str(value or "").strip()
        if not result or len(result) > 200 or _IDENTIFIER.fullmatch(result) is None:
            raise TeamControlTowerError(f"{field} is invalid")
        return result

    @staticmethod
    def _opaque(value: Any, field: str, *, maximum: int = 4096) -> str:
        if not isinstance(value, str):
            raise TeamControlTowerError(f"{field} must be an opaque string")
        result = value.strip()
        if (
            not result
            or len(result) > maximum
            or any(character.isspace() for character in result)
            or any(ord(character) < 33 or ord(character) > 126 for character in result)
        ):
            raise TeamControlTowerError(f"{field} is invalid")
        return result

    @staticmethod
    def _sha256(value: Any, field: str) -> str:
        result = str(value or "").strip()
        if _SHA256.fullmatch(result) is None:
            raise TeamControlTowerError(f"{field} must be lowercase SHA-256")
        return result

    def _now(self) -> datetime:
        return self._datetime(self.clock())

    @staticmethod
    def _datetime(value: str | datetime) -> datetime:
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise TeamControlTowerError("as_of must be ISO-8601") from exc
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise TeamControlTowerError("as_of must be timezone-aware")
        return value.astimezone(UTC)

    @staticmethod
    def _iso(value: datetime) -> str:
        return value.astimezone(UTC).isoformat()

    @staticmethod
    def _clone(value: Any) -> Any:
        return json.loads(json.dumps(value, ensure_ascii=False))

    @staticmethod
    def _hash(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()
