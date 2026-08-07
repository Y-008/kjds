from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

LOOP_MODULES = (
    "automations",
    "skills",
    "integrations",
    "subagents",
    "worktrees",
    "memory",
)
LoopModule = Literal[
    "automations",
    "skills",
    "integrations",
    "subagents",
    "worktrees",
    "memory",
]
LoopMode = Literal["proposal", "shadow", "active"]
EVOLUTION_CONTRACT_ID = "kjds-governed-team-agent-evolution-v1"

EVOLUTION_STATES = (
    "observation",
    "skill_candidate",
    "evaluation",
    "shadow",
    "independent_review",
    "promoted",
    "active",
    "rolled_back",
    "retired",
)
EVOLUTION_TRANSITIONS = (
    "observation->skill_candidate",
    "skill_candidate->evaluation",
    "evaluation->shadow",
    "evaluation->rolled_back",
    "shadow->independent_review",
    "shadow->rolled_back",
    "independent_review->promoted",
    "independent_review->rolled_back",
    "promoted->active",
    "promoted->rolled_back",
    "active->rolled_back",
    "active->retired",
    "rolled_back->retired",
)
FROZEN_EVAL_CONTRACT_ID = "kjds-team-agent-frozen-eval-set-v1"
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_EVAL_CASE_CATEGORIES = frozenset(
    {"quality", "negative_scope", "security", "cost", "latency"}
)
_EVAL_EXPECTED_STATUSES = frozenset({"succeeded", "denied", "failed"})
_FORBIDDEN_EVAL_KEYS = frozenset(
    {
        "tenant_ref",
        "entity_ref",
        "store_ref",
        "customer",
        "customer_id",
        "email",
        "phone",
        "prompt",
        "input_text",
        "output_text",
        "tool_args",
        "provider_request_id",
        "secret",
        "token",
        "credential",
    }
)


class LoopRegistryError(ValueError):
    """Raised when the machine-readable loop registry is invalid."""


@dataclass(frozen=True, slots=True)
class FrozenEvalSet:
    eval_set_id: str
    version: str
    sha256: str
    cases: tuple[dict[str, Any], ...]
    fixture_path: str

    def snapshot(self) -> dict[str, Any]:
        return {
            "contract_id": FROZEN_EVAL_CONTRACT_ID,
            "eval_set_id": self.eval_set_id,
            "version": self.version,
            "sha256": self.sha256,
            "case_count": len(self.cases),
            "categories": sorted({str(item["category"]) for item in self.cases}),
            "fixture_path": self.fixture_path,
            "contains_customer_data": False,
        }


@dataclass(frozen=True, slots=True)
class LoopValidation:
    module: str
    mode: str
    status: str
    missing_controls: tuple[str, ...]
    required_controls: tuple[str, ...]
    promotion_gate: str
    allowed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "mode": self.mode,
            "status": self.status,
            "missing_controls": list(self.missing_controls),
            "required_controls": list(self.required_controls),
            "promotion_gate": self.promotion_gate,
            "allowed": self.allowed,
        }


class LoopEngineeringService:
    """Loads and validates the six-module loop contract without side effects.

    This is deliberately a pure control-plane boundary. It does not execute a
    task or promote a skill; it only makes the preconditions explicit so that
    workers, API routes, and future schedulers cannot invent their own gates.
    """

    def __init__(self, registry_path: str | Path | None = None) -> None:
        configured = registry_path or os.getenv("KJDS_LOOP_REGISTRY_PATH")
        self.registry_path = Path(configured) if configured else self._default_path()
        self.registry = self._load()
        self._modules = self._index_modules(self.registry)
        self._evolution = self._validate_evolution(self.registry)
        self.registry_sha256 = self._sha256(self.registry)

    @staticmethod
    def _default_path() -> Path:
        return (
            Path(__file__).resolve().parents[2]
            / "docs"
            / "project"
            / "registries"
            / "loop_engineering_registry.json"
        )

    def _load(self) -> dict[str, Any]:
        try:
            registry = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LoopRegistryError(f"Unable to load loop registry: {self.registry_path}") from exc
        if not isinstance(registry, dict) or registry.get("status") != "active":
            raise LoopRegistryError("Loop registry must be an active object")
        if tuple(item.get("id") for item in registry.get("modules", [])) != LOOP_MODULES:
            raise LoopRegistryError("Loop registry must define the six modules in canonical order")
        if not isinstance(registry.get("loop_contract"), list) or not registry["loop_contract"]:
            raise LoopRegistryError("Loop registry must define a non-empty loop contract")
        self._validate_team_agent_contract(registry)
        self._validate_evolution_contract(registry)
        return registry

    @staticmethod
    def _validate_team_agent_contract(registry: dict[str, Any]) -> None:
        team = registry.get("team_agent_contract")
        if not isinstance(team, dict):
            raise LoopRegistryError("Loop registry must define team_agent_contract")
        expected = {
            "operating_registry": "docs/project/registries/global_expert_team_registry.json",
            "operating_model": "ai_core_human_professional_review",
            "portfolio_scope": "global_research_russia_ozon_execution_first",
            "leader_authority": "business_decision_high_risk_dual_sign",
            "leader_role": "global_chief_commerce_officer",
            "specialist_role_count": 12,
        }
        if any(team.get(key) != expected_value for key, expected_value in expected.items()):
            raise LoopRegistryError("Global expert team operating contract drift")
        if team.get("architecture") != (
            "coordinator_plus_bounded_specialists_plus_independent_verifier"
        ):
            raise LoopRegistryError("TeamAgent architecture drift")
        roles = team.get("roles")
        if not isinstance(roles, list) or len(roles) != len(set(roles)):
            raise LoopRegistryError("TeamAgent runtime roles must be unique")
        separation = team.get("separation_of_duties")
        if not isinstance(separation, dict) or not separation:
            raise LoopRegistryError("TeamAgent separation of duties is required")
        if any(value is not False for value in separation.values()):
            raise LoopRegistryError("TeamAgent separation of duties must fail closed")

    @staticmethod
    def _validate_evolution_contract(registry: dict[str, Any]) -> None:
        evolution = registry.get("evolution_loop")
        if not isinstance(evolution, dict):
            raise LoopRegistryError("Loop registry must define evolution_loop")
        if evolution.get("contract_id") != EVOLUTION_CONTRACT_ID:
            raise LoopRegistryError("Evolution contract identifier drift")
        states = evolution.get("states")
        if not isinstance(states, list) or len(states) != len(set(states)):
            raise LoopRegistryError("Evolution states must be unique")
        transitions = evolution.get("allowed_transitions")
        if tuple(transitions or ()) != EVOLUTION_TRANSITIONS:
            raise LoopRegistryError(
                "Evolution transitions do not match the frozen contract"
            )
        state_set = set(states)
        for transition in transitions:
            if not isinstance(transition, str) or transition.count("->") != 1:
                raise LoopRegistryError("Evolution transition is malformed")
            from_state, to_state = transition.split("->")
            if from_state not in state_set or to_state not in state_set:
                raise LoopRegistryError("Evolution transition references unknown state")
        controls = evolution.get("transition_controls")
        required_controls = {
            "append_only_audit_required",
            "atomic_transition_required",
            "idempotency_key_required",
            "expected_previous_state_required",
            "evidence_reference_required",
            "candidate_author_may_review",
            "candidate_author_may_promote",
            "reviewer_must_differ_from_candidate_author",
            "active_requires_human_owner_and_risk_authority",
        }
        if not isinstance(controls, dict) or not required_controls <= set(controls):
            raise LoopRegistryError("Evolution transition controls are incomplete")
        if any(controls[item] is not True for item in required_controls - {
            "candidate_author_may_review",
            "candidate_author_may_promote",
        }):
            raise LoopRegistryError("Evolution mandatory controls must fail closed")
        if controls["candidate_author_may_review"] is not False:
            raise LoopRegistryError("Candidate author review must remain prohibited")
        if controls["candidate_author_may_promote"] is not False:
            raise LoopRegistryError("Candidate author promotion must remain prohibited")
        evidence_source = evolution.get("evidence_source")
        if evidence_source is not None and evidence_source != "governed-team-agent-evolution":
            raise LoopRegistryError("Evolution Evidence source drift")
        cross_tenant = evolution.get("cross_tenant_contract")
        if cross_tenant is not None:
            if not isinstance(cross_tenant, dict):
                raise LoopRegistryError("Evolution cross-tenant contract must be an object")
            if cross_tenant.get("default_mode") != "same_tenant":
                raise LoopRegistryError("Cross-tenant learning must default to same tenant")
            if cross_tenant.get("raw_cross_tenant_allowed") is not False:
                raise LoopRegistryError("Raw cross-tenant learning must remain prohibited")

    @staticmethod
    def _index_modules(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
        indexed: dict[str, dict[str, Any]] = {}
        for item in registry["modules"]:
            controls = item.get("required_controls")
            if (
                not isinstance(controls, list)
                or not controls
                or any(not str(control).strip() for control in controls)
            ):
                raise LoopRegistryError(f"Module {item.get('id')} must define required controls")
            if item.get("state") not in {"partial", "design_only", "process_only", "ready"}:
                raise LoopRegistryError(f"Module {item.get('id')} has an unknown state")
            indexed[item["id"]] = item
        return indexed

    def registry_snapshot(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.registry, ensure_ascii=False))

    def evolution_snapshot(self) -> dict[str, Any]:
        result = json.loads(json.dumps(self._evolution, ensure_ascii=False))
        result["registry_version"] = str(self.registry["version"])
        result["registry_sha256"] = self.registry_sha256
        return result

    def require_evolution_transition(
        self,
        *,
        expected_previous_state: str,
        next_state: str,
    ) -> None:
        transition = f"{expected_previous_state}->{next_state}"
        if transition not in self._evolution["allowed_transitions"]:
            raise LoopRegistryError(f"Evolution transition is not admitted: {transition}")

    def load_frozen_eval_set(self, path: str | Path) -> FrozenEvalSet:
        fixture_path = Path(path)
        try:
            payload = json.loads(fixture_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LoopRegistryError(f"Unable to load frozen eval set: {fixture_path}") from exc
        if not isinstance(payload, dict):
            raise LoopRegistryError("Frozen eval set must be an object")
        expected_fields = {
            "contract_id",
            "eval_set_id",
            "version",
            "classification",
            "license",
            "cases",
            "sha256",
        }
        if set(payload) != expected_fields:
            raise LoopRegistryError("Frozen eval set fields do not match the contract")
        if payload["contract_id"] != FROZEN_EVAL_CONTRACT_ID:
            raise LoopRegistryError("Frozen eval set contract_id is invalid")
        if payload["classification"] != "repo_owned_synthetic":
            raise LoopRegistryError("Frozen eval set must be repo-owned synthetic data")
        self._reject_eval_customer_data(payload)
        license_payload = payload.get("license")
        if license_payload != {
            "license_id": "kjds-repo-synthetic-v1",
            "customer_data": False,
            "cross_tenant_data": False,
        }:
            raise LoopRegistryError("Frozen eval set license contract is invalid")
        eval_set_id = self._identifier(payload.get("eval_set_id"), "eval_set_id")
        version = self._identifier(payload.get("version"), "version")
        cases = payload.get("cases")
        if not isinstance(cases, list) or not cases:
            raise LoopRegistryError("Frozen eval set requires cases")
        normalized: list[dict[str, Any]] = []
        case_ids: set[str] = set()
        input_hashes: set[str] = set()
        for case in cases:
            normalized_case = self._eval_case(case)
            case_id = normalized_case["case_id"]
            input_sha256 = normalized_case["input_sha256"]
            if case_id in case_ids:
                raise LoopRegistryError("Frozen eval set case_id values must be unique")
            if input_sha256 in input_hashes:
                raise LoopRegistryError("Frozen eval set input references must be unique")
            case_ids.add(case_id)
            input_hashes.add(input_sha256)
            normalized.append(normalized_case)
        categories = {item["category"] for item in normalized}
        if not {"quality", "negative_scope", "security"}.issubset(categories):
            raise LoopRegistryError("Frozen eval set lacks quality/scope/security cases")
        sealed = dict(payload)
        supplied_sha256 = str(sealed.pop("sha256", ""))
        computed_sha256 = self._sha256(sealed)
        if not _SHA256_RE.fullmatch(supplied_sha256) or supplied_sha256 != computed_sha256:
            raise LoopRegistryError("Frozen eval set hash drift detected")
        return FrozenEvalSet(
            eval_set_id=eval_set_id,
            version=version,
            sha256=computed_sha256,
            cases=tuple(normalized),
            fixture_path=str(fixture_path.resolve()),
        )

    def validate(
        self,
        *,
        module: str,
        mode: LoopMode,
        controls: dict[str, Any],
    ) -> LoopValidation:
        if module not in self._modules:
            raise LoopRegistryError(f"Unknown loop module: {module}")
        if mode not in {"proposal", "shadow", "active"}:
            raise LoopRegistryError(f"Unknown loop mode: {mode}")
        if not isinstance(controls, dict):
            raise LoopRegistryError("Loop controls must be an object")
        definition = self._modules[module]
        required = tuple(str(item) for item in definition["required_controls"])
        missing = tuple(
            control
            for control in required
            if control not in controls or not self._provided(controls[control])
        )
        state = str(definition["state"])
        if missing:
            status = "missing_controls"
        elif mode == "active" and state != "ready":
            status = "promotion_gate_required"
        elif mode == "shadow":
            status = "shadow_ready"
        else:
            status = "proposal_ready"
        return LoopValidation(
            module=module,
            mode=mode,
            status=status,
            missing_controls=missing,
            required_controls=required,
            promotion_gate=str(definition["promotion_gate"]),
            allowed=not missing and not (mode == "active" and state != "ready"),
        )

    @staticmethod
    def _provided(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (list, tuple, set, dict)):
            return bool(value)
        return True

    @staticmethod
    def _validate_evolution(registry: dict[str, Any]) -> dict[str, Any]:
        evolution = registry.get("evolution_loop")
        if not isinstance(evolution, dict):
            raise LoopRegistryError("Loop registry must define evolution_loop")
        states = evolution.get("states")
        if tuple(states or ()) != EVOLUTION_STATES:
            raise LoopRegistryError("Evolution states do not match the frozen contract")
        transitions = evolution.get("allowed_transitions")
        if tuple(transitions or ()) != EVOLUTION_TRANSITIONS:
            raise LoopRegistryError(
                "Evolution transitions do not match the frozen contract"
            )
        known = set(EVOLUTION_STATES)
        for transition in transitions:
            if not isinstance(transition, str) or transition.count("->") != 1:
                raise LoopRegistryError("Evolution transition is malformed")
            previous, next_state = transition.split("->")
            if previous not in known or next_state not in known:
                raise LoopRegistryError("Evolution transition references an unknown state")
        controls = evolution.get("transition_controls")
        required_controls = {
            "append_only_audit_required": True,
            "atomic_transition_required": True,
            "idempotency_key_required": True,
            "expected_previous_state_required": True,
            "evidence_reference_required": True,
            "candidate_author_may_review": False,
            "candidate_author_may_promote": False,
            "reviewer_must_differ_from_candidate_author": True,
            "active_requires_human_owner_and_risk_authority": True,
        }
        if controls != required_controls:
            raise LoopRegistryError("Evolution transition controls drifted")
        return evolution

    @classmethod
    def _eval_case(cls, value: Any) -> dict[str, Any]:
        expected = {
            "case_id",
            "category",
            "task_type",
            "input_sha256",
            "expected_status",
            "expected_output_sha256",
            "hard_gate",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise LoopRegistryError("Frozen eval case fields do not match the contract")
        case_id = cls._identifier(value.get("case_id"), "case_id")
        category = str(value.get("category", ""))
        if category not in _EVAL_CASE_CATEGORIES:
            raise LoopRegistryError("Frozen eval case category is invalid")
        task_type = cls._identifier(value.get("task_type"), "task_type")
        input_sha256 = str(value.get("input_sha256", ""))
        if not _SHA256_RE.fullmatch(input_sha256):
            raise LoopRegistryError("Frozen eval input_sha256 is invalid")
        status = str(value.get("expected_status", ""))
        if status not in _EVAL_EXPECTED_STATUSES:
            raise LoopRegistryError("Frozen eval expected_status is invalid")
        output_sha256 = value.get("expected_output_sha256")
        if output_sha256 is not None and not _SHA256_RE.fullmatch(str(output_sha256)):
            raise LoopRegistryError("Frozen eval expected_output_sha256 is invalid")
        hard_gate = value.get("hard_gate")
        if not isinstance(hard_gate, bool):
            raise LoopRegistryError("Frozen eval hard_gate must be boolean")
        if category in {"negative_scope", "security"} and not hard_gate:
            raise LoopRegistryError("Scope/security cases must be hard gates")
        return {
            "case_id": case_id,
            "category": category,
            "task_type": task_type,
            "input_sha256": input_sha256,
            "expected_status": status,
            "expected_output_sha256": output_sha256,
            "hard_gate": hard_gate,
        }

    @classmethod
    def _reject_eval_customer_data(cls, value: Any, path: str = "eval_set") -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                normalized = str(key).strip().lower()
                if normalized in _FORBIDDEN_EVAL_KEYS:
                    raise LoopRegistryError(f"Frozen eval set contains forbidden field: {path}.{key}")
                cls._reject_eval_customer_data(item, f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                cls._reject_eval_customer_data(item, f"{path}[{index}]")

    @staticmethod
    def _identifier(value: Any, field: str) -> str:
        result = str(value or "").strip()
        if not result or len(result) > 160 or not re.fullmatch(r"[A-Za-z0-9_.:-]+", result):
            raise LoopRegistryError(f"Frozen eval {field} is invalid")
        return result

    @staticmethod
    def _sha256(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()
