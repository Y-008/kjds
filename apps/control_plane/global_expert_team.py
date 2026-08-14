from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

CONTRACT_ID = "kjds-global-portfolio-orchestrator-v1"
SCHEMA_VERSION = "kjds-global-expert-team-v1"
TEAM_MODEL = "ai_core_human_professional_review"
PORTFOLIO_SCOPE = "global_research_russia_ozon_execution_first"
LEADER_AUTHORITY = "business_decision_high_risk_dual_sign"
RISK_LEVELS = ("L0", "L1", "L2", "L3", "L4")
REQUIRED_CONTROL_ROLES = frozenset(
    {
        "human_business_owner",
        "independent_verifier",
        "independent_approver",
        "risk_authority",
        "executor",
    }
)
REQUIRED_ROLE_CONTROL_FIELDS = frozenset(
    {
        "exact_scope",
        "cost_budget",
        "time_budget",
        "handoff_contract",
        "trace_id",
        "eval_policy_version",
        "human_alternate_binding_required",
        "forbidden_inputs",
    }
)
REQUIRED_FORBIDDEN_INPUTS = frozenset(
    {
        "credential",
        "api_key",
        "cookie",
        "password",
        "bank_account",
        "customer_raw_data",
    }
)
_IDENTIFIER = re.compile(r"[A-Za-z0-9_.:-]+")
_MARKET = re.compile(r"(?:GLOBAL|[A-Z]{2})")
_PLATFORM = re.compile(r"[a-z0-9_.:-]+")


class GlobalExpertTeamRegistryError(ValueError):
    """Raised when the global expert team contract is missing or unsafe."""


class GlobalPortfolioOrchestrator:
    """Compile expert-team snapshots and proposal-only task routes.

    The module never creates an operating task, business fact, approval, permit,
    or external action. Existing authorities remain responsible for those
    operations after the route has passed their independent gates.
    """

    def __init__(self, registry_path: str | Path | None = None) -> None:
        self.registry_path = (
            Path(registry_path) if registry_path is not None else self._default_path()
        )
        self.registry = self._load()
        self._specialists = {
            str(item["role_id"]): item for item in self.registry["specialist_roles"]
        }
        self._routes = dict(self.registry["task_routes"])
        self._levels = {
            str(item["level"]): item for item in self.registry["decision_levels"]
        }
        self._role_controls = dict(self.registry["role_control_defaults"])
        self.registry_sha256 = self._sha256(self.registry)

    @staticmethod
    def _default_path() -> Path:
        return (
            Path(__file__).resolve().parents[2]
            / "docs"
            / "project"
            / "registries"
            / "global_expert_team_registry.json"
        )

    def _load(self) -> dict[str, Any]:
        try:
            value = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GlobalExpertTeamRegistryError(
                f"Unable to load global expert team registry: {self.registry_path}"
            ) from exc
        self._validate_registry(value)
        return value

    @classmethod
    def _validate_registry(cls, value: Any) -> None:
        if not isinstance(value, dict):
            raise GlobalExpertTeamRegistryError("Global expert team registry must be an object")
        if value.get("schema_version") != SCHEMA_VERSION:
            raise GlobalExpertTeamRegistryError("Global expert team schema version drift")
        if value.get("contract_id") != CONTRACT_ID:
            raise GlobalExpertTeamRegistryError("Global expert team contract identifier drift")
        if value.get("status") != "active_contract":
            raise GlobalExpertTeamRegistryError("Global expert team registry must be active")
        selection = value.get("selection")
        if selection != {
            "team_model": TEAM_MODEL,
            "portfolio_scope": PORTFOLIO_SCOPE,
            "leader_authority": LEADER_AUTHORITY,
        }:
            raise GlobalExpertTeamRegistryError("Frozen global expert team selection drift")
        cls._validate_leader(value.get("leader"))
        cls._validate_role_control_defaults(value.get("role_control_defaults"))
        specialist_ids, task_owners = cls._validate_specialists(value)
        control_ids = cls._validate_control_roles(value.get("control_roles"))
        cls._validate_routes(value.get("task_routes"), specialist_ids, control_ids, task_owners)
        cls._validate_decision_levels(value.get("decision_levels"))
        cls._validate_russia_cell(value.get("russia_execution_cell"))
        boundary = value.get("control_boundary")
        if not isinstance(boundary, dict) or not boundary:
            raise GlobalExpertTeamRegistryError("Control boundary is required")
        if any(item is not False for item in boundary.values()):
            raise GlobalExpertTeamRegistryError("Global expert team control boundary must fail closed")

    @staticmethod
    def _validate_leader(value: Any) -> None:
        if not isinstance(value, dict):
            raise GlobalExpertTeamRegistryError("Global expert team leader is required")
        if value.get("role_id") != "global_chief_commerce_officer":
            raise GlobalExpertTeamRegistryError("Global expert team leader identifier drift")
        if value.get("human_accountable_owner_required") is not True:
            raise GlobalExpertTeamRegistryError("Leader requires a human accountable owner")
        authority = value.get("authority")
        if not isinstance(authority, dict):
            raise GlobalExpertTeamRegistryError("Leader authority is required")
        allowed = {
            "may_set_objectives",
            "may_prioritize",
            "may_allocate_internal_budget",
            "may_assign_accountable_specialist",
            "may_continue_pause_pivot_or_stop",
            "may_trigger_kill_switch_request",
        }
        prohibited = {
            "may_verify_own_proposal",
            "may_approve_own_proposal",
            "may_override_failed_professional_gate",
            "may_issue_permit",
            "may_hold_marketplace_credentials",
            "may_perform_external_write",
        }
        if any(authority.get(item) is not True for item in allowed):
            raise GlobalExpertTeamRegistryError("Leader business authority is incomplete")
        if any(authority.get(item) is not False for item in prohibited):
            raise GlobalExpertTeamRegistryError("Leader separation of duties drift")

    @classmethod
    def _validate_role_control_defaults(cls, value: Any) -> None:
        if not isinstance(value, dict) or set(value) != REQUIRED_ROLE_CONTROL_FIELDS:
            raise GlobalExpertTeamRegistryError("Role control defaults drift")
        for field in (
            "exact_scope",
            "cost_budget",
            "time_budget",
            "handoff_contract",
            "trace_id",
            "eval_policy_version",
        ):
            cls._identifier(value.get(field), f"role control {field}")
        if value.get("human_alternate_binding_required") is not True:
            raise GlobalExpertTeamRegistryError(
                "Role controls require a named human alternate"
            )
        forbidden = value.get("forbidden_inputs")
        if (
            not isinstance(forbidden, list)
            or len(forbidden) != len(set(forbidden))
            or not set(forbidden) >= REQUIRED_FORBIDDEN_INPUTS
        ):
            raise GlobalExpertTeamRegistryError("Role control forbidden inputs drift")
        for item in forbidden:
            cls._identifier(item, "forbidden input")

    @classmethod
    def _validate_specialists(
        cls, value: dict[str, Any]
    ) -> tuple[set[str], dict[str, str]]:
        fields = value.get("required_specialist_fields")
        roles = value.get("specialist_roles")
        expected_fields = {
            "role_id",
            "title",
            "mission",
            "task_types",
            "deliverables",
            "human_review_roles",
            "tool_allowlist",
            "data_allowlist",
            "default_sla_hours",
        }
        if not isinstance(fields, list) or set(fields) != expected_fields:
            raise GlobalExpertTeamRegistryError("Required specialist fields drift")
        if not isinstance(roles, list) or len(roles) != 12:
            raise GlobalExpertTeamRegistryError("Exactly twelve specialist roles are required")
        required = set(fields)
        role_ids: set[str] = set()
        task_owners: dict[str, str] = {}
        for role in roles:
            if not isinstance(role, dict) or not required <= set(role):
                raise GlobalExpertTeamRegistryError("Specialist role contract is incomplete")
            role_id = cls._identifier(role.get("role_id"), "specialist role_id")
            if role_id in role_ids:
                raise GlobalExpertTeamRegistryError("Specialist role identifiers must be unique")
            role_ids.add(role_id)
            task_types = role.get("task_types")
            if not isinstance(task_types, list) or not task_types:
                raise GlobalExpertTeamRegistryError("Specialist task types are required")
            for task_type_value in task_types:
                task_type = cls._identifier(task_type_value, "task_type")
                if task_type in task_owners:
                    raise GlobalExpertTeamRegistryError(
                        "Each task type must have one accountable specialist"
                    )
                task_owners[task_type] = role_id
            for list_field in (
                "deliverables",
                "human_review_roles",
                "tool_allowlist",
                "data_allowlist",
            ):
                items = role.get(list_field)
                if (
                    not isinstance(items, list)
                    or not items
                    or len(items) != len(set(items))
                ):
                    raise GlobalExpertTeamRegistryError(
                        f"Specialist {list_field} must be non-empty and unique"
                    )
                for item in items:
                    cls._identifier(item, list_field)
            sla = role.get("default_sla_hours")
            if not isinstance(sla, int) or isinstance(sla, bool) or sla <= 0:
                raise GlobalExpertTeamRegistryError("Specialist SLA must be a positive integer")
        return role_ids, task_owners

    @classmethod
    def _validate_control_roles(cls, value: Any) -> set[str]:
        if not isinstance(value, list):
            raise GlobalExpertTeamRegistryError("Control roles are required")
        role_ids: set[str] = set()
        for role in value:
            if not isinstance(role, dict):
                raise GlobalExpertTeamRegistryError("Control role must be an object")
            role_id = cls._identifier(role.get("role_id"), "control role_id")
            if role_id in role_ids or not str(role.get("purpose", "")).strip():
                raise GlobalExpertTeamRegistryError("Control roles must be unique and documented")
            role_ids.add(role_id)
        if role_ids != REQUIRED_CONTROL_ROLES:
            raise GlobalExpertTeamRegistryError("Control role set drift")
        return role_ids

    @classmethod
    def _validate_routes(
        cls,
        value: Any,
        specialist_ids: set[str],
        control_ids: set[str],
        task_owners: dict[str, str],
    ) -> None:
        if not isinstance(value, dict) or set(value) != set(task_owners):
            raise GlobalExpertTeamRegistryError("Task routes must cover every specialist task type")
        for task_type, route in value.items():
            if not isinstance(route, dict):
                raise GlobalExpertTeamRegistryError("Task route must be an object")
            if route.get("accountable_role") != task_owners[task_type]:
                raise GlobalExpertTeamRegistryError("Task route accountable specialist drift")
            consulted = route.get("consulted_roles")
            reviewers = route.get("independent_review_roles")
            if (
                not isinstance(consulted, list)
                or len(consulted) != len(set(consulted))
                or not set(consulted) <= specialist_ids
            ):
                raise GlobalExpertTeamRegistryError("Task route consulted roles are invalid")
            if (
                not isinstance(reviewers, list)
                or "independent_verifier" not in reviewers
                or len(reviewers) != len(set(reviewers))
                or not set(reviewers) <= control_ids
            ):
                raise GlobalExpertTeamRegistryError("Task route independent review is invalid")

    @staticmethod
    def _validate_decision_levels(value: Any) -> None:
        if (
            not isinstance(value, list)
            or any(not isinstance(item, dict) for item in value)
            or tuple(item.get("level") for item in value) != RISK_LEVELS
        ):
            raise GlobalExpertTeamRegistryError("Decision levels must be L0 through L4")
        for item in value:
            if item.get("autonomous_external_action_allowed") is not False:
                raise GlobalExpertTeamRegistryError("Autonomous external actions must remain disabled")
        if value[3].get("human_dual_sign_required") is not True:
            raise GlobalExpertTeamRegistryError("L3 must require human dual sign")
        if value[4].get("human_dual_sign_required") is not True:
            raise GlobalExpertTeamRegistryError("L4 must require human dual sign")
        if value[4].get("leader_may_make_business_disposition") is not False:
            raise GlobalExpertTeamRegistryError("L4 remains a human authority")

    @staticmethod
    def _validate_russia_cell(value: Any) -> None:
        if not isinstance(value, dict):
            raise GlobalExpertTeamRegistryError("Russia execution cell is required")
        if value.get("market") != "RU" or value.get("primary_platform") != "ozon":
            raise GlobalExpertTeamRegistryError("Russia/Ozon must remain the first execution cell")
        bindings = value.get("required_human_bindings")
        if not isinstance(bindings, list) or not bindings:
            raise GlobalExpertTeamRegistryError("Russia execution cell needs human bindings")
        if value.get("execution_gate_status") != "unchanged_existing_gates_apply":
            raise GlobalExpertTeamRegistryError("Russia execution cell cannot change existing gates")

    def snapshot(self) -> dict[str, Any]:
        result = self._clone(self.registry)
        result["registry_sha256"] = self.registry_sha256
        result["counts"] = {
            "leaders": 1,
            "specialists": len(self._specialists),
            "control_roles": len(self.registry["control_roles"]),
            "task_routes": len(self._routes),
        }
        return result

    def route(
        self,
        *,
        task_ref: str,
        task_type: str,
        market: str,
        platform: str,
        risk_level: str,
        evidence_refs: Sequence[str] = (),
    ) -> dict[str, Any]:
        task_ref = self._identifier(task_ref, "task_ref")
        task_type = self._identifier(task_type, "task_type")
        if task_type not in self._routes:
            raise GlobalExpertTeamRegistryError(f"Unknown expert task type: {task_type}")
        market = str(market).strip().upper()
        if not _MARKET.fullmatch(market):
            raise GlobalExpertTeamRegistryError("market must be GLOBAL or ISO alpha-2")
        platform = str(platform).strip().lower()
        if not platform or len(platform) > 80 or not _PLATFORM.fullmatch(platform):
            raise GlobalExpertTeamRegistryError("platform identifier is invalid")
        if risk_level not in self._levels:
            raise GlobalExpertTeamRegistryError(f"Unknown risk level: {risk_level}")
        evidence = self._evidence_refs(evidence_refs)

        route = self._routes[task_type]
        specialist = self._specialists[str(route["accountable_role"])]
        level = self._levels[risk_level]
        is_russia_ozon = market == "RU" and platform == "ozon"
        blockers: list[str] = []
        if risk_level in {"L2", "L3", "L4"} and not evidence:
            blockers.append("evidence_refs_required_for_l2_plus")
        if risk_level in {"L2", "L3", "L4"} and not is_russia_ozon:
            blockers.append("execution_scope_not_admitted_outside_russia_ozon")
        if risk_level in {"L3", "L4"}:
            blockers.extend(
                [
                    "named_human_business_owner_binding_required",
                    "existing_professional_and_action_gates_must_pass",
                ]
            )
        if risk_level == "L4":
            blockers.append("human_domain_authority_required")

        status = self._route_status(
            risk_level=risk_level,
            is_russia_ozon=is_russia_ozon,
        )
        dual_sign = bool(level["human_dual_sign_required"])
        decision_route = {
            "leader_role": self.registry["leader"]["role_id"],
            "leader_may_make_business_disposition": bool(
                level["leader_may_make_business_disposition"]
            ),
            "human_business_owner_required": risk_level in {"L3", "L4"},
            "human_dual_sign_required": dual_sign,
            "action_approver_roles": (
                ["human_business_owner", "independent_approver"] if dual_sign else []
            ),
            "independent_review_roles": list(route["independent_review_roles"]),
            "executor_role": "executor" if risk_level == "L3" else None,
        }
        role_controls = self._clone(self._role_controls)
        role_controls["tool_allowlist"] = list(specialist["tool_allowlist"])
        role_controls["data_allowlist"] = list(specialist["data_allowlist"])
        result = {
            "contract_id": CONTRACT_ID,
            "contract_version": str(self.registry["version"]),
            "registry_sha256": self.registry_sha256,
            "status": status,
            "task_ref": task_ref,
            "task_type": task_type,
            "scope": {
                "market": market,
                "platform": platform,
                "operating_mode": (
                    "russia_ozon_first_execution_theater"
                    if is_russia_ozon
                    else "global_research_only"
                ),
            },
            "risk_level": risk_level,
            "evidence_refs": list(evidence),
            "accountable_specialist": specialist["role_id"],
            "consulted_specialists": list(route["consulted_roles"]),
            "human_professional_review_roles": list(specialist["human_review_roles"]),
            "default_sla_hours": specialist["default_sla_hours"],
            "role_controls": role_controls,
            "decision_route": decision_route,
            "blockers": blockers,
            "control_envelope": {
                "proposal_only": True,
                "existing_gates_unchanged": True,
                "operating_task_created": False,
                "business_decision_recorded": False,
                "formal_fact_promoted": False,
                "finance_entry_created": False,
                "approval_created": False,
                "permit_issued": False,
                "external_write_allowed": False,
            },
        }
        result["task_contract_sha256"] = self._sha256(result)
        return result

    @staticmethod
    def _route_status(*, risk_level: str, is_russia_ozon: bool) -> str:
        if risk_level in {"L2", "L3", "L4"} and not is_russia_ozon:
            return "blocked_scope"
        return {
            "L0": "proposal_routable",
            "L1": "proposal_routable",
            "L2": "read_gate_required",
            "L3": "dual_sign_gate_required",
            "L4": "human_authority_required",
        }[risk_level]

    @classmethod
    def _evidence_refs(cls, values: Sequence[str]) -> tuple[str, ...]:
        if isinstance(values, (str, bytes)):
            raise GlobalExpertTeamRegistryError("evidence_refs must be a sequence")
        normalized = tuple(cls._identifier(item, "evidence_ref") for item in values)
        if len(normalized) > 100:
            raise GlobalExpertTeamRegistryError("evidence_refs exceeds the bounded limit")
        if len(normalized) != len(set(normalized)):
            raise GlobalExpertTeamRegistryError("evidence_refs must be unique")
        return normalized

    @staticmethod
    def _identifier(value: Any, field: str) -> str:
        result = str(value or "").strip()
        if not result or len(result) > 160 or not _IDENTIFIER.fullmatch(result):
            raise GlobalExpertTeamRegistryError(f"{field} is invalid")
        return result

    @staticmethod
    def _clone(value: Any) -> Any:
        return json.loads(json.dumps(value, ensure_ascii=False))

    @staticmethod
    def _sha256(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
