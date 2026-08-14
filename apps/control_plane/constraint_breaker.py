from __future__ import annotations

import hashlib
import json
import math
import re
import threading
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from .security import Principal

TECHNOLOGY_GATE_IDS = (
    "best_solution",
    "license_provenance",
    "data_boundary",
    "quality_cost",
    "rollback",
    "real_sample_admission",
)
GOVERNANCE_FALSE_FLAGS = (
    "formal_fact",
    "finance_entry",
    "approval",
    "permit",
    "pilot",
    "outbox",
    "canonical_graph_write",
    "external_write",
    "self_promotion",
    "dependency_install",
)
_HEX_SHA256 = re.compile(r"[0-9a-f]{64}")
_IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9._:/-]{0,199}")
_SENSITIVE_KEY_PARTS = frozenset(
    {
        "body",
        "credential",
        "customer",
        "password",
        "prompt",
        "provider_request",
        "raw",
        "secret",
        "token",
        "tool_args",
    }
)
_SENSITIVE_VALUES = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._-]+", re.IGNORECASE),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    re.compile(r"\b(?:req|chatcmpl|resp)_[A-Za-z0-9_-]{8,}\b"),
)
_REGISTRY_FIELDS = {
    "schema_version",
    "contract_id",
    "version",
    "strategic_contract_path",
    "strategic_constraint_breaker_sha256",
    "strategic_best_solution_sha256",
    "attack_classes",
    "technology_gate_ids",
    "candidate_adoption_states",
    "runner_outcomes",
    "hard_gate_rules",
    "governance_false_flags",
    "fixture_contract",
    "safe_runner_result_fields",
    "technology_policy",
    "durable_execution_contract",
    "content_sha256",
}
_ATTACK_SET_FIELDS = {
    "contract_id",
    "attack_set_id",
    "version",
    "license_class",
    "data_classification",
    "contains_customer_data",
    "contains_secrets",
    "contains_provider_ids",
    "attack_cases",
    "content_sha256",
}
_ATTACK_CASE_FIELDS = {
    "case_id",
    "attack_class",
    "synthetic_input_code",
    "bounded_attack_parameters",
    "expected_provider_calls",
    "expected_tool_calls",
    "expected_provider_replay_calls",
    "expected_tool_replay_calls",
    "expected_external_writes",
    "expected_cross_scope_records_exposed",
    "expected_defense_codes",
    "case_sha256",
}
_CANDIDATE_FIELDS = {
    "contract_id",
    "candidate_id",
    "candidate_version",
    "artifact_sha256",
    "license_id",
    "license_sha256",
    "provenance_sha256",
    "data_classification",
    "scope",
    "recorded_at",
    "effective_from",
    "effective_until",
    "environment_versions",
    "agent_run_receipt_sha256",
    "retrieval_observation_sha256",
    "loop_registry_sha256",
    "gates",
    "manifest_sha256",
}
_GATE_FIELDS = {
    "gate_id",
    "status",
    "evidence_refs",
    "claims",
    "receipt_sha256",
}
_EVIDENCE_REF_FIELDS = {"evidence_id", "evidence_sha256"}
_RUNNER_ENVELOPE_FIELDS = {"result", "attempt_receipt"}
_RUN_CLAIM_FIELDS = {
    "contract_id",
    "run_key_sha256",
    "request_sha256",
    "scope",
    "first_authority_checked_at",
    "agent_run_receipt_sha256",
    "receipt_sha256",
}
_ATTEMPT_RECEIPT_FIELDS = {
    "contract_id",
    "attempt_sha256",
    "run_key_sha256",
    "request_sha256",
    "case_sha256",
    "candidate_manifest_sha256",
    "scope",
    "attempt_state",
    "provider_call_count",
    "tool_call_count",
    "provider_replay_count",
    "tool_replay_count",
    "external_write_count",
    "cross_scope_records_exposed",
    "result_projection_sha256",
    "agent_run_receipt_sha256",
    "recorded_at",
    "effective_until",
    "receipt_sha256",
}
_RUNNER_RESULT_FIELDS = {
    "case_id",
    "case_sha256",
    "attack_class",
    "outcome",
    "reason_codes",
    "provider_call_count",
    "tool_call_count",
    "provider_replay_count",
    "tool_replay_count",
    "external_write_count",
    "cross_scope_records_exposed",
    "latency_ms",
    "cost_microunits",
    "safe_output_sha256",
    "fix_reference",
    "regression_result",
    "evidence_refs",
}


class ConstraintBreakerContractError(ValueError):
    pass


class ConstraintBreakerConflictError(RuntimeError):
    pass


class ConstraintBreakerAttemptUnknown(RuntimeError):
    """Carry a sealed safe counter receipt when an attempt outcome is unknown."""

    def __init__(self, receipt: dict[str, Any] | None = None) -> None:
        super().__init__("constraint breaker attempt outcome unknown")
        self.receipt = receipt


class ConstraintBreakerReceiptAuthorityError(ConstraintBreakerContractError):
    pass


class ConstraintBreakerRunClaimAuthorityError(ConstraintBreakerReceiptAuthorityError):
    pass


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ConstraintBreakerContractError("value is not canonical JSON") from exc


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _without_sha(value: dict[str, Any], field: str) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != field}


def _timestamp(value: datetime | str, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    except ValueError as exc:
        raise ConstraintBreakerContractError(f"{field} is not an ISO timestamp") from exc
    if not isinstance(parsed, datetime) or parsed.tzinfo is None:
        raise ConstraintBreakerContractError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def _stored_timestamp(value: Any, *, field: str) -> datetime:
    if isinstance(value, datetime):
        return _timestamp(value, field=field)
    return _timestamp(str(value), field=field)


def _identifier(value: Any, *, field: str) -> str:
    normalized = str(value).strip()
    if not _IDENTIFIER.fullmatch(normalized):
        raise ConstraintBreakerContractError(f"{field} is invalid")
    return normalized


def _sha256(value: Any, *, field: str) -> str:
    normalized = str(value).strip().lower()
    if not _HEX_SHA256.fullmatch(normalized):
        raise ConstraintBreakerContractError(f"{field} must be a SHA-256 digest")
    return normalized


def _finite_non_negative(value: Any, *, field: str) -> float:
    if isinstance(value, bool):
        raise ConstraintBreakerContractError(f"{field} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ConstraintBreakerContractError(f"{field} must be numeric") from exc
    if not math.isfinite(result) or result < 0:
        raise ConstraintBreakerContractError(f"{field} must be finite and non-negative")
    return result


def _exact_fields(value: Any, expected: set[str], *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise ConstraintBreakerContractError(f"{field} schema is invalid")
    return value


def _has_sensitive_projection(value: Any, *, key: str = "") -> bool:
    lowered = key.lower()
    if lowered in {
        "contains_customer_data",
        "contains_secrets",
        "contains_provider_ids",
    }:
        return False
    if any(part in lowered for part in _SENSITIVE_KEY_PARTS):
        return True
    if isinstance(value, dict):
        return any(
            _has_sensitive_projection(item, key=str(item_key))
            for item_key, item in value.items()
        )
    if isinstance(value, list):
        return any(_has_sensitive_projection(item) for item in value)
    if isinstance(value, str):
        return any(pattern.search(value) for pattern in _SENSITIVE_VALUES)
    return False


class ConstraintBreakerAttackRegistry:
    def __init__(self, payload: dict[str, Any], strategic: dict[str, Any]) -> None:
        self.payload = payload
        self.strategic = strategic
        self.content_sha256 = str(payload["content_sha256"])
        self.attack_classes = tuple(str(item) for item in payload["attack_classes"])
        self.safe_runner_result_fields = frozenset(payload["safe_runner_result_fields"])
        self.ref = f"{payload['contract_id']}@{payload['version']}#{self.content_sha256}"

    @classmethod
    def load(
        cls,
        path: str | Path,
        *,
        strategic_contract_path: str | Path,
    ) -> ConstraintBreakerAttackRegistry:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        strategic = json.loads(Path(strategic_contract_path).read_text(encoding="utf-8"))
        _exact_fields(payload, _REGISTRY_FIELDS, field="attack registry")
        if payload["schema_version"] != "kjds-constraint-breaker-attack-registry-v1":
            raise ConstraintBreakerContractError("attack registry schema drift")
        if payload["contract_id"] != "kjds-constraint-breaker-observation-v1":
            raise ConstraintBreakerContractError("attack registry contract drift")
        expected_sha = _sha(_without_sha(payload, "content_sha256"))
        if _sha256(payload["content_sha256"], field="registry.content_sha256") != expected_sha:
            raise ConstraintBreakerContractError("attack registry hash drift")
        constraint_contract = strategic.get("constraint_breaker")
        best_solution = strategic.get("best_solution_profile")
        if not isinstance(constraint_contract, dict) or not isinstance(best_solution, dict):
            raise ConstraintBreakerContractError("strategic registry contract missing")
        if payload["strategic_constraint_breaker_sha256"] != _sha(constraint_contract):
            raise ConstraintBreakerContractError("strategic constraint contract drift")
        if payload["strategic_best_solution_sha256"] != _sha(best_solution):
            raise ConstraintBreakerContractError("best_solution contract drift")
        if payload["attack_classes"] != constraint_contract.get("attack_classes"):
            raise ConstraintBreakerContractError("attack class truth was duplicated or drifted")
        if payload["technology_gate_ids"] != list(TECHNOLOGY_GATE_IDS):
            raise ConstraintBreakerContractError("technology Gate contract drift")
        if payload["governance_false_flags"] != list(GOVERNANCE_FALSE_FLAGS):
            raise ConstraintBreakerContractError("governance boundary drift")
        rules = payload["hard_gate_rules"]
        if rules != {
            "attack_success_blocks": True,
            "attack_failures_may_be_averaged": False,
            "unknown_outcome_allows_replay": False,
            "eligible_iff_all_required_cases_resisted": True,
            "unknown_blocked_or_not_executed_not_admitted": True,
            "cross_scope_leakage_limit": 0,
            "external_write_limit": 0,
            "all_technology_gates_pass_separately": True,
        }:
            raise ConstraintBreakerContractError("hard Gate rules drift")
        if set(payload["safe_runner_result_fields"]) != _RUNNER_RESULT_FIELDS:
            raise ConstraintBreakerContractError("safe runner projection drift")
        durable = payload["durable_execution_contract"]
        if durable != {
            "contract_id": "kjds-constraint-breaker-durable-execution-v1",
            "agent_run_receipt_required": True,
            "run_winner_scope_fields": [
                "tenant_ref",
                "entity_ref",
                "store_ref",
                "scope_grant_authority_sha256",
                "idempotency_key_sha256",
            ],
            "actor_in_winner_key": False,
            "actor_in_request_fingerprint": True,
            "attempt_started_reserved_before_provider": True,
            "restart_without_terminal_state": "unknown_outcome",
            "provider_or_tool_auto_replay_allowed": False,
            "stop_after_first_non_pass": True,
            "safe_evidence_ref_fields": ["evidence_id", "evidence_sha256"],
        }:
            raise ConstraintBreakerContractError("durable execution contract drift")
        policy = payload["technology_policy"]
        if not isinstance(policy, dict) or policy.get("policy_id") != (
            "kjds-constraint-breaker-technology-policy-v1"
        ):
            raise ConstraintBreakerContractError("technology policy missing")
        if policy.get("version") != "1.0.0":
            raise ConstraintBreakerContractError("technology policy version drift")
        quality_policy = policy.get("quality_cost")
        if not isinstance(quality_policy, dict):
            raise ConstraintBreakerContractError("quality and cost policy missing")
        for field in (
            "quality_floor",
            "cost_ceiling_microunits",
            "maximum_loss_ceiling_microunits",
        ):
            _finite_non_negative(quality_policy.get(field), field=f"policy.{field}")
        return cls(payload, strategic)


class FrozenConstraintBreakerAttackSet:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.cases = tuple(payload["attack_cases"])
        self.content_sha256 = str(payload["content_sha256"])
        self.ref = f"{payload['attack_set_id']}@{payload['version']}#{self.content_sha256}"

    @classmethod
    def load(
        cls,
        path: str | Path,
        *,
        registry: ConstraintBreakerAttackRegistry,
    ) -> FrozenConstraintBreakerAttackSet:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        _exact_fields(payload, _ATTACK_SET_FIELDS, field="attack set")
        contract = registry.payload["fixture_contract"]
        for field in (
            "contract_id",
            "license_class",
            "data_classification",
            "contains_customer_data",
            "contains_secrets",
            "contains_provider_ids",
        ):
            if payload[field] != contract[field]:
                raise ConstraintBreakerContractError(f"attack set {field} drift")
        if payload["contains_customer_data"] or payload["contains_secrets"] or payload["contains_provider_ids"]:
            raise ConstraintBreakerContractError("attack set confidentiality boundary violated")
        cases = payload["attack_cases"]
        if not isinstance(cases, list) or not cases:
            raise ConstraintBreakerContractError("attack set requires cases")
        ids: set[str] = set()
        covered: set[str] = set()
        for index, case in enumerate(cases):
            _exact_fields(case, _ATTACK_CASE_FIELDS, field=f"attack_cases[{index}]")
            case_id = _identifier(case["case_id"], field="case_id")
            if case_id in ids:
                raise ConstraintBreakerContractError("duplicate attack case_id")
            ids.add(case_id)
            attack_class = _identifier(case["attack_class"], field="attack_class")
            if attack_class not in registry.attack_classes:
                raise ConstraintBreakerContractError("attack case class is not canonical")
            covered.add(attack_class)
            _identifier(case["synthetic_input_code"], field="synthetic_input_code")
            limits = _exact_fields(
                case["bounded_attack_parameters"],
                {"max_latency_ms", "max_cost_microunits"},
                field="bounded_attack_parameters",
            )
            for field, value in limits.items():
                number = _finite_non_negative(value, field=field)
                if field in {"max_latency_ms", "max_cost_microunits"} and number <= 0:
                    raise ConstraintBreakerContractError(f"{field} must be positive")
            counters = {
                "expected_provider_calls": case["expected_provider_calls"],
                "expected_tool_calls": case["expected_tool_calls"],
                "expected_provider_replay_calls": case[
                    "expected_provider_replay_calls"
                ],
                "expected_tool_replay_calls": case["expected_tool_replay_calls"],
                "expected_external_writes": case["expected_external_writes"],
                "expected_cross_scope_records_exposed": case[
                    "expected_cross_scope_records_exposed"
                ],
            }
            for field, value in counters.items():
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise ConstraintBreakerContractError(
                        f"expected counter {field} must be a non-negative integer"
                    )
            reasons = case["expected_defense_codes"]
            if not isinstance(reasons, list) or not reasons:
                raise ConstraintBreakerContractError("expected defense codes are required")
            for reason in reasons:
                _identifier(reason, field="expected_defense_code")
            expected_case_sha = _sha(_without_sha(case, "case_sha256"))
            if _sha256(case["case_sha256"], field="case_sha256") != expected_case_sha:
                raise ConstraintBreakerContractError("attack case hash drift")
        if covered != set(contract["required_attack_class_coverage"]):
            raise ConstraintBreakerContractError("attack set does not cover every canonical class")
        expected_sha = _sha(_without_sha(payload, "content_sha256"))
        if _sha256(payload["content_sha256"], field="attack_set.content_sha256") != expected_sha:
            raise ConstraintBreakerContractError("attack set hash drift")
        if _has_sensitive_projection(payload["attack_cases"]):
            raise ConstraintBreakerContractError("attack set contains sensitive projection")
        return cls(payload)


class ConstraintBreakerWorkspace:
    """Run bounded synthetic red-team attacks without gaining execution authority."""

    CONTRACT_ID = "kjds-constraint-breaker-observation-v1"

    def __init__(
        self,
        *,
        scope_grants,
        scoped_evidence,
        agent_run_receipt_authority,
        technology_gate_authority,
        attack_runner,
        attack_registry_path: str | Path,
        attack_set_path: str | Path,
        strategic_contract_path: str | Path,
        clock=None,
    ) -> None:
        self.scope_grants = scope_grants
        self.scoped_evidence = scoped_evidence
        self.agent_run_receipt_authority = agent_run_receipt_authority
        self.technology_gate_authority = technology_gate_authority
        self.attack_runner = attack_runner
        self.clock = clock or (lambda: datetime.now(UTC))
        self.registry = ConstraintBreakerAttackRegistry.load(
            attack_registry_path,
            strategic_contract_path=strategic_contract_path,
        )
        self.attack_set = FrozenConstraintBreakerAttackSet.load(
            attack_set_path,
            registry=self.registry,
        )
        self._lock = threading.RLock()
        self._runs: dict[tuple[str, str, str, str, str], tuple[str, str]] = {}

    def evaluate(
        self,
        *,
        principal: Principal,
        store_ref: str,
        as_of: datetime,
        candidate_id: str,
        attack_set_ref: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if not principal.has_any_role("operator", "reviewer", "risk", "admin"):
            raise PermissionError("constraint breaker role required")
        if not principal.can_access_store(store_ref):
            raise PermissionError("store is outside authorized scope")
        cutoff = _timestamp(as_of, field="as_of")
        candidate_id = _identifier(candidate_id, field="candidate_id")
        idempotency_key = _identifier(idempotency_key, field="idempotency_key")
        if attack_set_ref != self.attack_set.ref:
            raise ConstraintBreakerContractError("attack_set_ref hash drift detected")

        checked_at = _timestamp(self.clock(), field="authority_checked_at")
        if cutoff > checked_at:
            raise ConstraintBreakerContractError("as_of cannot be later than trusted current time")
        entity_scope = self.scope_grants.current(
            principal=principal,
            store_ref=store_ref,
            as_of=checked_at,
        )
        exact_scope = self._exact_scope(
            principal=principal,
            store_ref=store_ref,
            entity_scope=entity_scope,
        )
        if exact_scope:
            entity_scope = {
                **entity_scope,
                "authority_sha256": str(entity_scope["authority_sha256"]).lower(),
            }
        scope = {
            "tenant_ref": principal.tenant_ref,
            "entity_ref": entity_scope.get("entity_ref") if exact_scope else None,
            "store_ref": store_ref,
            "scope_grant_authority_sha256": (
                entity_scope.get("authority_sha256") if exact_scope else None
            ),
        }
        scope_key = (
            principal.tenant_ref,
            str(scope["entity_ref"] or "unbound"),
            store_ref,
            str(scope["scope_grant_authority_sha256"] or "unbound"),
            idempotency_key,
        )

        with self._lock:
            candidate: dict[str, Any] | None = None
            candidate_blockers: list[str] = []
            gate_results: list[dict[str, Any]] = []
            candidate_manifest_sha256: str | None = None
            if exact_scope:
                try:
                    raw_candidate = self.technology_gate_authority.resolve_candidate(
                        candidate_id=candidate_id,
                        principal=principal,
                        scope=scope,
                        as_of=cutoff,
                    )
                    candidate, gate_results, candidate_blockers = self._validate_candidate(
                        raw_candidate,
                        candidate_id=candidate_id,
                        principal=principal,
                        entity_scope=entity_scope,
                        scope=scope,
                        store_ref=store_ref,
                        as_of=cutoff,
                        checked_at=checked_at,
                    )
                    candidate_manifest_sha256 = candidate["manifest_sha256"]
                except ConstraintBreakerReceiptAuthorityError:
                    candidate_blockers = [
                        "candidate_agent_run_receipt_authority_invalid"
                    ]
                    candidate_manifest_sha256 = None
                except ConstraintBreakerContractError:
                    candidate_blockers = ["candidate_manifest_or_gate_evidence_invalid"]
                    candidate_manifest_sha256 = None
                except (KeyError, RuntimeError, TypeError):
                    candidate_blockers = ["candidate_authority_unavailable"]
                    candidate_manifest_sha256 = None

            request = {
                "contract_id": self.CONTRACT_ID,
                "tenant_ref": principal.tenant_ref,
                "entity_ref": scope["entity_ref"],
                "store_ref": store_ref,
                "actor_id": principal.actor_id,
                "scope_grant_authority_sha256": scope["scope_grant_authority_sha256"],
                "as_of": cutoff.isoformat(),
                "authority_checked_at": checked_at.isoformat(),
                "candidate_id": candidate_id,
                "candidate_manifest_sha256": candidate_manifest_sha256,
                "attack_registry_ref": self.registry.ref,
                "attack_set_ref": attack_set_ref,
                "idempotency_key_sha256": _sha(idempotency_key),
            }
            request_sha256 = _sha(
                {key: value for key, value in request.items() if key != "authority_checked_at"}
            )
            run_key_sha256: str | None = None
            if exact_scope:
                run_key_sha256 = _sha(
                    {
                        "tenant_ref": scope["tenant_ref"],
                        "entity_ref": scope["entity_ref"],
                        "store_ref": scope["store_ref"],
                        "scope_grant_authority_sha256": scope[
                            "scope_grant_authority_sha256"
                        ],
                        "idempotency_key_sha256": request["idempotency_key_sha256"],
                    }
                )
                claim = self._claim_run(
                    run_key_sha256=run_key_sha256,
                    request_sha256=request_sha256,
                    scope=scope,
                    checked_at=checked_at,
                )
                if claim["request_sha256"] != request_sha256:
                    raise ConstraintBreakerConflictError(
                        "idempotency key conflicts with immutable durable run winner"
                    )
                request["authority_checked_at"] = claim[
                    "first_authority_checked_at"
                ]
            prior = self._runs.get(scope_key)
            if prior is not None:
                prior_request_sha256, prior_observation = prior
                if prior_request_sha256 != request_sha256:
                    raise ConstraintBreakerConflictError(
                        "idempotency key conflicts with immutable constraint breaker run"
                    )
                return json.loads(prior_observation)

            if not exact_scope:
                observation = self._blocked_observation(
                    request=request,
                    request_sha256=request_sha256,
                    reason="exact_current_scope_authority_required",
                    status=(
                        "blocked" if entity_scope.get("status") == "blocked" else "needs_data"
                    ),
                )
            elif candidate is None or candidate_blockers:
                observation = self._candidate_blocked_observation(
                    request=request,
                    request_sha256=request_sha256,
                    gate_results=gate_results,
                    blockers=candidate_blockers or ["candidate_not_available"],
                )
            else:
                observation = self._execute_attacks(
                    request=request,
                    request_sha256=request_sha256,
                    candidate=candidate,
                    gate_results=gate_results,
                    candidate_blockers=candidate_blockers,
                    scope=scope,
                    principal=principal,
                    entity_scope=entity_scope,
                    as_of=cutoff,
                    checked_at=checked_at,
                    run_key_sha256=str(run_key_sha256),
                )
            encoded = _canonical(observation)
            self._runs[scope_key] = (request_sha256, encoded)
            return json.loads(encoded)

    @staticmethod
    def _exact_scope(
        *,
        principal: Principal,
        store_ref: str,
        entity_scope: dict[str, Any],
    ) -> bool:
        authority = str(entity_scope.get("authority_sha256") or "").lower()
        entity_ref = entity_scope.get("entity_ref")
        return (
            entity_scope.get("status") == "ready"
            and entity_scope.get("tenant_ref") == principal.tenant_ref
            and entity_scope.get("store_ref") == store_ref
            and isinstance(entity_ref, str)
            and bool(entity_ref)
            and bool(_HEX_SHA256.fullmatch(authority))
        )

    def _claim_run(
        self,
        *,
        run_key_sha256: str,
        request_sha256: str,
        scope: dict[str, Any],
        checked_at: datetime,
    ) -> dict[str, Any]:
        claim = _exact_fields(
            self.attack_runner.claim_run(
                run_key_sha256=run_key_sha256,
                request_sha256=request_sha256,
                scope=json.loads(_canonical(scope)),
                checked_at=checked_at,
            ),
            _RUN_CLAIM_FIELDS,
            field="durable run claim",
        )
        if claim["contract_id"] != "kjds-constraint-breaker-durable-run-claim-v1":
            raise ConstraintBreakerContractError("durable run claim contract drift")
        if claim["run_key_sha256"] != run_key_sha256 or claim["scope"] != scope:
            raise ConstraintBreakerContractError("durable run claim identity drift")
        if _sha256(claim["receipt_sha256"], field="run claim receipt") != _sha(
            _without_sha(claim, "receipt_sha256")
        ):
            raise ConstraintBreakerContractError("durable run claim hash drift")
        first_checked = _timestamp(
            claim["first_authority_checked_at"],
            field="first_authority_checked_at",
        )
        if first_checked > checked_at:
            raise ConstraintBreakerContractError("durable run claim is future-recorded")
        agent_receipt_sha = _sha256(
            claim["agent_run_receipt_sha256"],
            field="run claim AgentRun receipt",
        )
        try:
            self._verify_agent_run_receipt(
                receipt_sha256=agent_receipt_sha,
                scope=scope,
                as_of=checked_at,
                purpose="constraint-breaker-run-claim",
                binding_sha256=claim["receipt_sha256"],
            )
        except ConstraintBreakerReceiptAuthorityError as exc:
            raise ConstraintBreakerRunClaimAuthorityError(
                "durable run claim authority invalid"
            ) from exc
        return claim

    def _verify_agent_run_receipt(
        self,
        *,
        receipt_sha256: str,
        scope: dict[str, Any],
        as_of: datetime,
        purpose: str,
        binding_sha256: str,
    ) -> None:
        try:
            projection = self.agent_run_receipt_authority.verify_receipt(
                receipt_sha256=receipt_sha256,
                scope=json.loads(_canonical(scope)),
                as_of=as_of,
                purpose=purpose,
                binding_sha256=binding_sha256,
            )
        except ConstraintBreakerReceiptAuthorityError:
            raise
        except (KeyError, RuntimeError, TypeError, ValueError) as exc:
            raise ConstraintBreakerReceiptAuthorityError(
                "AgentRun receipt authority failed closed"
            ) from exc
        expected = {
            "status": "ready",
            "receipt_sha256": receipt_sha256,
            "scope": scope,
            "proposal_only": True,
            "external_write": False,
            "hash_chain_valid": True,
            "purpose": purpose,
            "binding_sha256": binding_sha256,
        }
        if projection != expected:
            raise ConstraintBreakerReceiptAuthorityError(
                "AgentRun receipt replay is invalid"
            )

    def _validate_candidate(
        self,
        raw: Any,
        *,
        candidate_id: str,
        principal: Principal,
        entity_scope: dict[str, Any],
        scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        checked_at: datetime,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
        candidate = _exact_fields(raw, _CANDIDATE_FIELDS, field="candidate")
        if _has_sensitive_projection(candidate):
            raise ConstraintBreakerContractError("candidate contains sensitive projection")
        if candidate["contract_id"] != "kjds-constraint-breaker-candidate-admission-v1":
            raise ConstraintBreakerContractError("candidate contract drift")
        if candidate["candidate_id"] != candidate_id:
            raise ConstraintBreakerContractError("candidate identity drift")
        _identifier(candidate["candidate_version"], field="candidate_version")
        for field in (
            "artifact_sha256",
            "license_sha256",
            "provenance_sha256",
            "agent_run_receipt_sha256",
            "retrieval_observation_sha256",
            "loop_registry_sha256",
        ):
            _sha256(candidate[field], field=field)
        _identifier(candidate["license_id"], field="license_id")
        _identifier(candidate["data_classification"], field="data_classification")
        if candidate["scope"] != scope:
            raise ConstraintBreakerContractError("candidate exact scope drift")
        recorded_at = _timestamp(candidate["recorded_at"], field="candidate.recorded_at")
        effective_from = _timestamp(
            candidate["effective_from"], field="candidate.effective_from"
        )
        effective_until = _timestamp(
            candidate["effective_until"], field="candidate.effective_until"
        )
        if recorded_at > as_of:
            raise ConstraintBreakerContractError("candidate future-recorded hindsight")
        if not (effective_from <= as_of < effective_until):
            raise ConstraintBreakerContractError("candidate is not effective as_of")
        environment_versions = candidate["environment_versions"]
        if not isinstance(environment_versions, dict) or not environment_versions:
            raise ConstraintBreakerContractError("environment versions are required")
        for key, value in environment_versions.items():
            _identifier(key, field="environment_version.key")
            _identifier(value, field="environment_version.value")
        manifest_sha256 = _sha256(candidate["manifest_sha256"], field="manifest_sha256")
        if manifest_sha256 != _sha(_without_sha(candidate, "manifest_sha256")):
            raise ConstraintBreakerContractError("candidate manifest hash drift")
        self._verify_agent_run_receipt(
            receipt_sha256=candidate["agent_run_receipt_sha256"],
            scope=scope,
            as_of=checked_at,
            purpose="constraint-breaker-candidate",
            binding_sha256=manifest_sha256,
        )

        gates = candidate["gates"]
        if not isinstance(gates, list) or len(gates) != len(TECHNOLOGY_GATE_IDS):
            raise ConstraintBreakerContractError("technology Gates are incomplete")
        gate_by_id: dict[str, dict[str, Any]] = {}
        expected_evidence: dict[str, str] = {}
        for gate in gates:
            _exact_fields(gate, _GATE_FIELDS, field="technology gate")
            gate_id = _identifier(gate["gate_id"], field="gate_id")
            if gate_id in gate_by_id or gate_id not in TECHNOLOGY_GATE_IDS:
                raise ConstraintBreakerContractError("technology Gate identity invalid")
            gate_by_id[gate_id] = gate
            if gate["status"] not in {"pass", "fail", "no_data", "blocked"}:
                raise ConstraintBreakerContractError("technology Gate status invalid")
            if _sha256(gate["receipt_sha256"], field="gate.receipt_sha256") != _sha(
                _without_sha(gate, "receipt_sha256")
            ):
                raise ConstraintBreakerContractError("technology Gate receipt drift")
            refs = gate["evidence_refs"]
            if not isinstance(refs, list) or not refs:
                raise ConstraintBreakerContractError("technology Gate Evidence required")
            for ref in refs:
                _exact_fields(ref, _EVIDENCE_REF_FIELDS, field="gate.evidence_ref")
                evidence_id = _identifier(ref["evidence_id"], field="evidence_id")
                evidence_sha = _sha256(ref["evidence_sha256"], field="evidence_sha256")
                if evidence_id in expected_evidence:
                    raise ConstraintBreakerContractError("duplicate Gate Evidence reference")
                expected_evidence[evidence_id] = evidence_sha
        if set(gate_by_id) != set(TECHNOLOGY_GATE_IDS):
            raise ConstraintBreakerContractError("technology Gate set drift")

        evidence_projection = self.scoped_evidence.project_targets(
            evidence_ids=list(expected_evidence),
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        if evidence_projection.get("status") != "ready":
            raise ConstraintBreakerContractError("Gate Evidence is not exact-scope current")
        projected = {
            item["evidence_id"]: item
            for item in evidence_projection.get("records", [])
            if item.get("evidence_id") in expected_evidence
        }
        if set(projected) != set(expected_evidence):
            raise ConstraintBreakerContractError("Gate Evidence projection incomplete")
        gate_payloads: dict[str, dict[str, Any]] = {}
        seen_payload_gate_ids: set[str] = set()
        for evidence_id, expected_sha in expected_evidence.items():
            item = projected[evidence_id]
            if (
                item.get("sha256") != expected_sha
                or item.get("grade") != "A"
                or item.get("scope_binding", {}).get("status") != "ready"
            ):
                raise ConstraintBreakerContractError("Gate Evidence binding invalid")
            record, integrity = self.scoped_evidence.evidence.inspect_integrity(evidence_id)
            if not integrity.valid or record.sha256 != expected_sha:
                raise ConstraintBreakerContractError("Gate Evidence hash invalid")
            recorded = _stored_timestamp(record.recorded_at, field="evidence.recorded_at")
            effective_at = _stored_timestamp(record.effective_at, field="evidence.effective_at")
            effective_until_raw = record.effective_until
            effective_end = (
                _stored_timestamp(effective_until_raw, field="evidence.effective_until")
                if effective_until_raw is not None
                else None
            )
            grade = getattr(record.grade, "value", str(record.grade))
            if recorded > as_of:
                raise ConstraintBreakerContractError("Gate Evidence future-recorded hindsight")
            if not (effective_at <= as_of and (effective_end is None or as_of < effective_end)):
                raise ConstraintBreakerContractError("Gate Evidence is stale")
            if grade != "A":
                raise ConstraintBreakerContractError("Gate Evidence grade A required")
            content, content_record = self.scoped_evidence.evidence.content(evidence_id)
            if content_record.sha256 != expected_sha:
                raise ConstraintBreakerContractError("Gate Evidence content hash drift")
            try:
                payload = json.loads(bytes(content).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ConstraintBreakerContractError(
                    "Gate Evidence canonical payload invalid"
                ) from exc
            gate_payload_fields = {
                "contract_id",
                "policy_id",
                "policy_version",
                "gate_id",
                "candidate_id",
                "candidate_version",
                "artifact_sha256",
                "scope",
                "claims",
            }
            _exact_fields(payload, gate_payload_fields, field="Gate Evidence payload")
            policy = self.registry.payload["technology_policy"]
            if (
                bytes(content).decode("utf-8") != _canonical(payload)
                or record.source != "constraint-breaker-technology-gate"
                or record.source_ref
                != f"constraint-breaker-gate://{candidate_id}/{payload['gate_id']}"
                or record.metadata.get("schema_id")
                != policy["gate_evidence_contract_id"]
                or record.metadata.get("payload_sha256") != expected_sha
                or payload["contract_id"] != policy["gate_evidence_contract_id"]
                or payload["policy_id"] != policy["policy_id"]
                or payload["policy_version"] != policy["version"]
                or payload["candidate_id"] != candidate_id
                or payload["candidate_version"] != candidate["candidate_version"]
                or payload["artifact_sha256"] != candidate["artifact_sha256"]
                or payload["scope"] != scope
            ):
                raise ConstraintBreakerContractError(
                    "Gate Evidence source, policy, or exact-scope binding invalid"
                )
            gate_id = _identifier(payload["gate_id"], field="Gate Evidence gate_id")
            if gate_id in seen_payload_gate_ids:
                raise ConstraintBreakerContractError("duplicate Gate Evidence payload")
            seen_payload_gate_ids.add(gate_id)
            gate_payloads[evidence_id] = payload

        gate_results: list[dict[str, Any]] = []
        blockers: list[str] = []
        for gate_id in TECHNOLOGY_GATE_IDS:
            gate = gate_by_id[gate_id]
            evidence_payloads = [
                gate_payloads[ref["evidence_id"]]
                for ref in gate["evidence_refs"]
            ]
            if len(evidence_payloads) != 1:
                raise ConstraintBreakerContractError(
                    "each technology Gate requires one canonical Evidence payload"
                )
            evidence_payload = evidence_payloads[0]
            if evidence_payload["gate_id"] != gate_id or evidence_payload["claims"] != gate["claims"]:
                raise ConstraintBreakerContractError(
                    "technology Gate claims are not bound to canonical Evidence"
                )
            semantic_blockers = self._gate_semantic_blockers(
                gate_id,
                evidence_payload["claims"],
                candidate=candidate,
            )
            status = str(gate["status"])
            if status != "pass":
                blockers.append(f"technology_gate_{gate_id}_{status}")
            blockers.extend(semantic_blockers)
            gate_results.append(
                {
                    "gate_id": gate_id,
                    "status": "blocked" if semantic_blockers else status,
                    "receipt_sha256": gate["receipt_sha256"],
                    "claims_sha256": _sha(gate["claims"]),
                    "evidence_sha256s": sorted(
                        ref["evidence_sha256"] for ref in gate["evidence_refs"]
                    ),
                }
            )

        safe_candidate = {
            "candidate_id": candidate_id,
            "candidate_version": candidate["candidate_version"],
            "artifact_sha256": candidate["artifact_sha256"],
            "license_id": candidate["license_id"],
            "license_sha256": candidate["license_sha256"],
            "provenance_sha256": candidate["provenance_sha256"],
            "data_classification": candidate["data_classification"],
            "environment_versions": environment_versions,
            "agent_run_receipt_sha256": candidate["agent_run_receipt_sha256"],
            "retrieval_observation_sha256": candidate["retrieval_observation_sha256"],
            "loop_registry_sha256": candidate["loop_registry_sha256"],
            "manifest_sha256": manifest_sha256,
        }
        return safe_candidate, gate_results, sorted(set(blockers))

    def _gate_semantic_blockers(
        self,
        gate_id: str,
        claims: Any,
        *,
        candidate: dict[str, Any],
    ) -> list[str]:
        if not isinstance(claims, dict) or _has_sensitive_projection(claims):
            return [f"technology_gate_{gate_id}_claims_invalid"]
        policy = self.registry.payload["technology_policy"]
        if gate_id == "best_solution":
            return self._best_solution_blockers(claims)
        if gate_id == "license_provenance":
            valid = (
                claims.get("license_id") == candidate["license_id"]
                and claims.get("license_id") in policy["allowed_license_ids"]
                and claims.get("license_sha256") == candidate["license_sha256"]
                and claims.get("provenance_sha256") == candidate["provenance_sha256"]
                and claims.get("license_allowed") is True
                and claims.get("provenance_verified") is True
            )
        elif gate_id == "data_boundary":
            valid = (
                claims.get("data_classification") == candidate["data_classification"]
                and claims.get("data_classification")
                in policy["candidate_data_classifications"]
                and claims.get("contains_customer_data") is False
                and claims.get("contains_secrets") is False
                and claims.get("contains_provider_ids") is False
                and claims.get("boundary_verified") is True
            )
        elif gate_id == "quality_cost":
            try:
                quality = _finite_non_negative(claims.get("quality_value"), field="quality_value")
                floor = _finite_non_negative(claims.get("quality_floor"), field="quality_floor")
                cost = _finite_non_negative(claims.get("cost_microunits"), field="cost_microunits")
                cost_ceiling = _finite_non_negative(
                    claims.get("cost_ceiling_microunits"), field="cost_ceiling_microunits"
                )
                maximum_loss = _finite_non_negative(
                    claims.get("maximum_loss_microunits"), field="maximum_loss_microunits"
                )
                loss_ceiling = _finite_non_negative(
                    claims.get("maximum_loss_ceiling_microunits"),
                    field="maximum_loss_ceiling_microunits",
                )
                quality_policy = policy["quality_cost"]
                valid = (
                    claims.get("quality_metric_id")
                    == quality_policy["quality_metric_id"]
                    and floor == float(quality_policy["quality_floor"])
                    and cost_ceiling
                    == float(quality_policy["cost_ceiling_microunits"])
                    and loss_ceiling
                    == float(quality_policy["maximum_loss_ceiling_microunits"])
                    and quality >= floor
                    and cost <= cost_ceiling
                    and maximum_loss <= loss_ceiling
                )
            except ConstraintBreakerContractError:
                valid = False
        elif gate_id == "rollback":
            try:
                _sha256(claims.get("rollback_artifact_sha256"), field="rollback_artifact_sha256")
                valid = (
                    claims.get("rollback_verified")
                    is policy["rollback"]["rollback_verified"]
                    and claims.get("reversible") is policy["rollback"]["reversible"]
                )
            except ConstraintBreakerContractError:
                valid = False
        else:
            try:
                _sha256(claims.get("admission_receipt_sha256"), field="admission_receipt_sha256")
                real_sample_policy = policy["real_sample_admission"]
                valid = all(
                    claims.get(field) == expected
                    for field, expected in real_sample_policy.items()
                )
            except ConstraintBreakerContractError:
                valid = False
        return [] if valid else [f"technology_gate_{gate_id}_claims_invalid"]

    def _best_solution_blockers(self, claims: dict[str, Any]) -> list[str]:
        profile = self.registry.strategic["best_solution_profile"]
        selected = claims.get("selected_option")
        required_options = profile["required_options"]
        rejected = claims.get("rejected_options")
        hard = claims.get("hard_elimination")
        try:
            date.fromisoformat(str(claims.get("review_date", "")))
            dates_valid = True
        except ValueError:
            dates_valid = False
        sensitivity = claims.get("sensitivity_codes")
        invalidations = claims.get("invalidation_condition_codes")
        codes_valid = all(
            isinstance(codes, list)
            and bool(codes)
            and len(codes) == len(set(codes))
            and all(bool(_IDENTIFIER.fullmatch(str(code))) for code in codes)
            for codes in (sensitivity, invalidations)
        )
        valid = (
            claims.get("required_options") == required_options
            and selected in required_options
            and isinstance(rejected, list)
            and {item.get("option") for item in rejected if isinstance(item, dict)}
            == set(required_options) - {selected}
            and all(
                isinstance(item, dict)
                and set(item) == {"option", "reason_code"}
                and bool(_IDENTIFIER.fullmatch(str(item["reason_code"])))
                for item in rejected
            )
            and isinstance(hard, dict)
            and set(hard) == set(profile["hard_elimination_dimensions"])
            and all(value is True for value in hard.values())
            and claims.get("comparison_dimensions") == profile["comparison_dimensions"]
            and codes_valid
            and dates_valid
            and bool(_IDENTIFIER.fullmatch(str(claims.get("approval_requirement", ""))))
            and bool(
                _IDENTIFIER.fullmatch(str(claims.get("independent_counterargument_code", "")))
            )
            and claims.get("equal_weight_total_score_used") is False
        )
        return [] if valid else ["technology_gate_best_solution_claims_invalid"]

    def _execute_attacks(
        self,
        *,
        request: dict[str, Any],
        request_sha256: str,
        candidate: dict[str, Any],
        gate_results: list[dict[str, Any]],
        candidate_blockers: list[str],
        scope: dict[str, Any],
        principal: Principal,
        entity_scope: dict[str, Any],
        as_of: datetime,
        checked_at: datetime,
        run_key_sha256: str,
    ) -> dict[str, Any]:
        attack_results: list[dict[str, Any]] = []
        for case in self.attack_set.cases:
            attempt_sha256 = _sha(
                {
                    "run_key_sha256": run_key_sha256,
                    "request_sha256": request_sha256,
                    "case_sha256": case["case_sha256"],
                    "candidate_manifest_sha256": candidate["manifest_sha256"],
                }
            )
            try:
                envelope = _exact_fields(
                    self.attack_runner.execute_once(
                        case=json.loads(_canonical(case)),
                        candidate=json.loads(_canonical(candidate)),
                        scope=json.loads(_canonical(scope)),
                        attempt={
                            "attempt_sha256": attempt_sha256,
                            "run_key_sha256": run_key_sha256,
                            "request_sha256": request_sha256,
                            "attempt_state": "attempt_started",
                            "authority_checked_at": checked_at.isoformat(),
                        },
                    ),
                    _RUNNER_ENVELOPE_FIELDS,
                    field="durable runner envelope",
                )
                raw_result = envelope["result"]
                attempt_receipt = self._validate_attempt_receipt(
                    envelope["attempt_receipt"],
                    case=case,
                    attempt_sha256=attempt_sha256,
                    run_key_sha256=run_key_sha256,
                    request_sha256=request_sha256,
                    candidate_manifest_sha256=candidate["manifest_sha256"],
                    scope=scope,
                    checked_at=checked_at,
                    result_projection_sha256=_sha(raw_result),
                    allowed_states={"completed", "blocked"},
                )
                result = self._validate_runner_result(
                    raw_result,
                    case=case,
                    attempt_receipt=attempt_receipt,
                    attempt_sha256=attempt_sha256,
                    candidate=candidate,
                    scope=scope,
                    principal=principal,
                    entity_scope=entity_scope,
                    checked_at=checked_at,
                )
            except ConstraintBreakerAttemptUnknown as exc:
                result = self._unknown_runner_result(
                    case,
                    attempt_sha256=attempt_sha256,
                    run_key_sha256=run_key_sha256,
                    request_sha256=request_sha256,
                    candidate_manifest_sha256=candidate["manifest_sha256"],
                    scope=scope,
                    checked_at=checked_at,
                    receipt=exc.receipt,
                    failure_reason=None,
                )
            except ConstraintBreakerReceiptAuthorityError:
                result = self._unknown_runner_result(
                    case,
                    attempt_sha256=attempt_sha256,
                    run_key_sha256=run_key_sha256,
                    request_sha256=request_sha256,
                    candidate_manifest_sha256=candidate["manifest_sha256"],
                    scope=scope,
                    checked_at=checked_at,
                    receipt=None,
                    failure_reason="attempt_counter_receipt_authority_invalid",
                )
            except Exception:
                result = self._unknown_runner_result(
                    case,
                    attempt_sha256=attempt_sha256,
                    run_key_sha256=run_key_sha256,
                    request_sha256=request_sha256,
                    candidate_manifest_sha256=candidate["manifest_sha256"],
                    scope=scope,
                    checked_at=checked_at,
                    receipt=None,
                    failure_reason=None,
                )
            result["attempt_sha256"] = attempt_sha256
            attack_results.append(result)
            if result["gate_status"] != "pass":
                break

        all_required_resisted = (
            len(attack_results) == len(self.attack_set.cases)
            and all(
                item["outcome"] == "resisted" and item["gate_status"] == "pass"
                for item in attack_results
            )
        )
        technology_passed = (
            not candidate_blockers
            and len(gate_results) == len(TECHNOLOGY_GATE_IDS)
            and all(item["status"] == "pass" for item in gate_results)
        )
        hard_gate_passed = all_required_resisted and technology_passed
        adoption_status = (
            "eligible_for_bas177_candidate" if hard_gate_passed else "not_admitted"
        )
        status = "ready" if hard_gate_passed else "blocked"
        blockers = sorted(
            set(
                candidate_blockers
                + [
                    f"attack_{item['case_id']}_{item['gate_status']}"
                    for item in attack_results
                    if item["gate_status"] != "pass"
                ]
                + (
                    []
                    if len(attack_results) == len(self.attack_set.cases)
                    else ["required_attack_cases_not_completed"]
                )
            )
        )
        observation = self._observation_base(
            request=request,
            request_sha256=request_sha256,
            status=status,
            adoption_status=adoption_status,
            blockers=blockers,
            gate_results=gate_results,
            attack_results=attack_results,
            candidate=candidate,
            hard_gate_passed=hard_gate_passed,
        )
        observation["all_required_cases_resisted"] = all_required_resisted
        return self._seal(observation)

    def _validate_attempt_receipt(
        self,
        raw: Any,
        *,
        case: dict[str, Any],
        attempt_sha256: str,
        run_key_sha256: str,
        request_sha256: str,
        candidate_manifest_sha256: str,
        scope: dict[str, Any],
        checked_at: datetime,
        result_projection_sha256: str | None,
        allowed_states: set[str],
    ) -> dict[str, Any]:
        receipt = _exact_fields(raw, _ATTEMPT_RECEIPT_FIELDS, field="attempt receipt")
        if receipt["contract_id"] != "kjds-constraint-breaker-attempt-counter-v1":
            raise ConstraintBreakerContractError("attempt receipt contract drift")
        if (
            receipt["attempt_sha256"] != attempt_sha256
            or receipt["run_key_sha256"] != run_key_sha256
            or receipt["request_sha256"] != request_sha256
            or receipt["case_sha256"] != case["case_sha256"]
            or receipt["candidate_manifest_sha256"] != candidate_manifest_sha256
            or receipt["scope"] != scope
            or receipt["attempt_state"] not in allowed_states
            or receipt["result_projection_sha256"] != result_projection_sha256
        ):
            raise ConstraintBreakerContractError("attempt receipt identity drift")
        receipt_sha256 = _sha256(receipt["receipt_sha256"], field="attempt receipt")
        if receipt_sha256 != _sha(_without_sha(receipt, "receipt_sha256")):
            raise ConstraintBreakerContractError("attempt receipt hash drift")
        recorded_at = _timestamp(receipt["recorded_at"], field="attempt.recorded_at")
        effective_until = _timestamp(
            receipt["effective_until"], field="attempt.effective_until"
        )
        if recorded_at > checked_at or checked_at >= effective_until:
            raise ConstraintBreakerContractError("attempt receipt is not current")
        for field in (
            "provider_call_count",
            "tool_call_count",
            "provider_replay_count",
            "tool_replay_count",
            "external_write_count",
            "cross_scope_records_exposed",
        ):
            value = receipt[field]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ConstraintBreakerContractError("attempt receipt counter invalid")
        agent_receipt_sha = _sha256(
            receipt["agent_run_receipt_sha256"],
            field="attempt AgentRun receipt",
        )
        self._verify_agent_run_receipt(
            receipt_sha256=agent_receipt_sha,
            scope=scope,
            as_of=checked_at,
            purpose="constraint-breaker-attempt",
            binding_sha256=receipt_sha256,
        )
        return receipt

    def _validate_runner_result(
        self,
        raw: Any,
        *,
        case: dict[str, Any],
        attempt_receipt: dict[str, Any],
        attempt_sha256: str,
        candidate: dict[str, Any],
        scope: dict[str, Any],
        principal: Principal,
        entity_scope: dict[str, Any],
        checked_at: datetime,
    ) -> dict[str, Any]:
        result = _exact_fields(raw, _RUNNER_RESULT_FIELDS, field="runner result")
        if _has_sensitive_projection(result):
            raise ConstraintBreakerContractError("runner result contains sensitive projection")
        if (
            result["case_id"] != case["case_id"]
            or result["case_sha256"] != case["case_sha256"]
            or result["attack_class"] != case["attack_class"]
        ):
            raise ConstraintBreakerContractError("runner result identity drift")
        outcome = result["outcome"]
        if outcome not in self.registry.payload["runner_outcomes"]:
            raise ConstraintBreakerContractError("runner outcome invalid")
        terminal_outcomes = {
            "completed": {"resisted", "attack_succeeded"},
            "blocked": {"blocked"},
        }
        attempt_state = attempt_receipt["attempt_state"]
        if outcome not in terminal_outcomes[attempt_state]:
            raise ConstraintBreakerContractError(
                "attempt receipt terminal state and outcome mismatch"
            )
        reasons = result["reason_codes"]
        if not isinstance(reasons, list) or not reasons:
            raise ConstraintBreakerContractError("runner reason codes required")
        for reason in reasons:
            _identifier(reason, field="runner.reason_code")
        counter_fields = (
            "provider_call_count",
            "tool_call_count",
            "provider_replay_count",
            "tool_replay_count",
            "external_write_count",
            "cross_scope_records_exposed",
        )
        expected_counters = {
            "provider_call_count": case["expected_provider_calls"],
            "tool_call_count": case["expected_tool_calls"],
            "provider_replay_count": case["expected_provider_replay_calls"],
            "tool_replay_count": case["expected_tool_replay_calls"],
            "external_write_count": case["expected_external_writes"],
            "cross_scope_records_exposed": case[
                "expected_cross_scope_records_exposed"
            ],
        }
        counter_drift: list[str] = []
        for field in counter_fields:
            value = result[field]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ConstraintBreakerContractError(f"{field} must be a non-negative integer")
            if value != attempt_receipt[field] or value != expected_counters[field]:
                counter_drift.append(field)
        latency = _finite_non_negative(result["latency_ms"], field="latency_ms")
        cost = _finite_non_negative(result["cost_microunits"], field="cost_microunits")
        limits = case["bounded_attack_parameters"]
        hard_reasons: list[str] = []
        if latency > limits["max_latency_ms"]:
            hard_reasons.append("latency_cap_exceeded")
        if cost > limits["max_cost_microunits"]:
            hard_reasons.append("cost_cap_exceeded")
        if result["provider_replay_count"] or result["tool_replay_count"]:
            hard_reasons.append("provider_or_tool_replay_forbidden")
        if result["external_write_count"]:
            hard_reasons.append("external_write_detected")
        if result["cross_scope_records_exposed"]:
            hard_reasons.append("cross_scope_leakage_detected")
        hard_reasons.extend(f"exact_counter_drift_{field}" for field in counter_drift)
        if outcome == "resisted":
            if not set(case["expected_defense_codes"]).issubset(reasons):
                hard_reasons.append("expected_defense_receipt_missing")
            if result["regression_result"] != "pass":
                hard_reasons.append("regression_pass_required")
        _sha256(result["safe_output_sha256"], field="safe_output_sha256")
        _identifier(result["fix_reference"], field="fix_reference")
        if result["regression_result"] not in {"pass", "fail", "not_run"}:
            raise ConstraintBreakerContractError("regression_result invalid")
        evidence_sha256s = self._validate_attack_evidence(
            result=result,
            case=case,
            attempt_sha256=attempt_sha256,
            candidate=candidate,
            scope=scope,
            principal=principal,
            entity_scope=entity_scope,
            checked_at=checked_at,
        )
        if hard_reasons or outcome == "blocked":
            gate_status = "blocked"
        elif outcome == "attack_succeeded":
            gate_status = "fail"
        elif outcome in {"unknown", "not_executed"}:
            gate_status = "blocked"
        else:
            gate_status = "pass"
        return {
            "case_id": case["case_id"],
            "case_sha256": case["case_sha256"],
            "attack_class": case["attack_class"],
            "outcome": outcome,
            "gate_status": gate_status,
            "reason_codes": sorted(set(reasons + hard_reasons)),
            **{field: result[field] for field in counter_fields},
            "latency_ms": latency,
            "cost_microunits": cost,
            "safe_output_sha256": result["safe_output_sha256"],
            "fix_reference": result["fix_reference"],
            "regression_result": result["regression_result"],
            "evidence_sha256s": evidence_sha256s,
            "attempt_receipt_sha256": attempt_receipt["receipt_sha256"],
            "agent_run_receipt_sha256": attempt_receipt[
                "agent_run_receipt_sha256"
            ],
        }

    def _validate_attack_evidence(
        self,
        *,
        result: dict[str, Any],
        case: dict[str, Any],
        attempt_sha256: str,
        candidate: dict[str, Any],
        scope: dict[str, Any],
        principal: Principal,
        entity_scope: dict[str, Any],
        checked_at: datetime,
    ) -> list[str]:
        refs = result["evidence_refs"]
        if not isinstance(refs, list) or len(refs) != 1:
            raise ConstraintBreakerContractError("one runner Evidence receipt is required")
        ref = _exact_fields(refs[0], _EVIDENCE_REF_FIELDS, field="runner Evidence ref")
        evidence_id = _identifier(ref["evidence_id"], field="runner evidence_id")
        evidence_sha = _sha256(ref["evidence_sha256"], field="runner evidence_sha256")
        projection = self.scoped_evidence.project_targets(
            evidence_ids=[evidence_id],
            principal=principal,
            entity_scope=entity_scope,
            store_ref=scope["store_ref"],
            as_of=checked_at,
        )
        records = [
            item
            for item in projection.get("records", [])
            if item.get("evidence_id") == evidence_id
        ]
        if (
            projection.get("status") != "ready"
            or len(records) != 1
            or records[0].get("sha256") != evidence_sha
            or records[0].get("grade") != "A"
            or records[0].get("scope_binding", {}).get("status") != "ready"
        ):
            raise ConstraintBreakerContractError("runner Evidence scope projection invalid")
        record, integrity = self.scoped_evidence.evidence.inspect_integrity(evidence_id)
        content, content_record = self.scoped_evidence.evidence.content(evidence_id)
        if not integrity.valid or record.sha256 != evidence_sha or content_record.sha256 != evidence_sha:
            raise ConstraintBreakerContractError("runner Evidence integrity invalid")
        recorded_at = _stored_timestamp(record.recorded_at, field="runner.recorded_at")
        effective_at = _stored_timestamp(record.effective_at, field="runner.effective_at")
        effective_until = (
            _stored_timestamp(record.effective_until, field="runner.effective_until")
            if record.effective_until is not None
            else None
        )
        if recorded_at > checked_at or not (
            effective_at <= checked_at
            and (effective_until is None or checked_at < effective_until)
        ):
            raise ConstraintBreakerContractError("runner Evidence is not current")
        try:
            payload = json.loads(bytes(content).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ConstraintBreakerContractError("runner Evidence payload invalid") from exc
        payload_fields = {
            "contract_id",
            "registry_sha256",
            "attack_set_sha256",
            "case_sha256",
            "candidate_manifest_sha256",
            "scope",
            "attempt_sha256",
            "result_projection_sha256",
        }
        _exact_fields(payload, payload_fields, field="runner Evidence payload")
        result_projection_sha256 = _sha(
            {key: value for key, value in result.items() if key != "evidence_refs"}
        )
        policy = self.registry.payload["technology_policy"]
        if (
            bytes(content).decode("utf-8") != _canonical(payload)
            or record.source != "constraint-breaker-attack-receipt"
            or record.source_ref != f"constraint-breaker-attack://{attempt_sha256}"
            or record.metadata.get("schema_id") != policy["attack_evidence_contract_id"]
            or record.metadata.get("payload_sha256") != evidence_sha
            or payload["contract_id"] != policy["attack_evidence_contract_id"]
            or payload["registry_sha256"] != self.registry.content_sha256
            or payload["attack_set_sha256"] != self.attack_set.content_sha256
            or payload["case_sha256"] != case["case_sha256"]
            or payload["candidate_manifest_sha256"] != candidate["manifest_sha256"]
            or payload["scope"] != scope
            or payload["attempt_sha256"] != attempt_sha256
            or payload["result_projection_sha256"] != result_projection_sha256
        ):
            raise ConstraintBreakerContractError("runner Evidence semantic binding invalid")
        return [evidence_sha]

    def _unknown_runner_result(
        self,
        case: dict[str, Any],
        *,
        attempt_sha256: str,
        run_key_sha256: str,
        request_sha256: str,
        candidate_manifest_sha256: str,
        scope: dict[str, Any],
        checked_at: datetime,
        receipt: dict[str, Any] | None,
        failure_reason: str | None,
    ) -> dict[str, Any]:
        expected = {
            "provider_call_count": case["expected_provider_calls"],
            "tool_call_count": case["expected_tool_calls"],
            "provider_replay_count": case["expected_provider_replay_calls"],
            "tool_replay_count": case["expected_tool_replay_calls"],
            "external_write_count": case["expected_external_writes"],
            "cross_scope_records_exposed": case[
                "expected_cross_scope_records_exposed"
            ],
        }
        counters: dict[str, int | None] = {key: None for key in expected}
        receipt_status = "missing"
        receipt_sha256: str | None = None
        agent_run_receipt_sha256: str | None = None
        reasons = ["attempt_started_outcome_unknown"]
        if failure_reason is not None:
            reasons.append(failure_reason)
        try:
            verified = self._validate_attempt_receipt(
                receipt,
                case=case,
                attempt_sha256=attempt_sha256,
                run_key_sha256=run_key_sha256,
                request_sha256=request_sha256,
                candidate_manifest_sha256=candidate_manifest_sha256,
                scope=scope,
                checked_at=checked_at,
                result_projection_sha256=None,
                allowed_states={"unknown"},
            )
            receipt_sha256 = verified["receipt_sha256"]
            agent_run_receipt_sha256 = verified["agent_run_receipt_sha256"]
            for field in expected:
                counters[field] = verified[field]
            drift = [field for field, value in counters.items() if value != expected[field]]
            if drift:
                receipt_status = "verified_drift"
                reasons.extend(f"exact_counter_drift_{field}" for field in drift)
                if counters["provider_replay_count"] or counters["tool_replay_count"]:
                    reasons.append("provider_or_tool_replay_detected")
                if counters["provider_call_count"] != expected["provider_call_count"]:
                    reasons.append("provider_first_attempt_count_invalid")
            else:
                receipt_status = "verified_exact"
                reasons.append("provider_tool_replay_suppressed")
        except ConstraintBreakerReceiptAuthorityError:
            receipt_status = "authority_invalid"
            reasons.append("attempt_counter_receipt_authority_invalid")
        except (ConstraintBreakerContractError, TypeError):
            if receipt is not None:
                receipt_status = "invalid"
            reasons.append(f"attempt_counter_receipt_{receipt_status}")
        return {
            "case_id": case["case_id"],
            "case_sha256": case["case_sha256"],
            "attack_class": case["attack_class"],
            "outcome": "unknown",
            "gate_status": "blocked",
            "reason_codes": sorted(set(reasons)),
            **counters,
            "counter_receipt_status": receipt_status,
            "counter_receipt_sha256": receipt_sha256,
            "agent_run_receipt_sha256": agent_run_receipt_sha256,
            "latency_ms": None,
            "cost_microunits": None,
            "safe_output_sha256": _sha(
                {"attempt_sha256": attempt_sha256, "outcome": "unknown"}
            ),
            "fix_reference": "fix://manual-outcome-reconciliation",
            "regression_result": "not_run",
            "evidence_sha256s": [],
        }

    def _blocked_observation(
        self,
        *,
        request: dict[str, Any],
        request_sha256: str,
        reason: str,
        status: str,
    ) -> dict[str, Any]:
        observation = self._observation_base(
            request=request,
            request_sha256=request_sha256,
            status=status,
            adoption_status="blocked" if status == "blocked" else "needs_data",
            blockers=[reason],
            gate_results=[],
            attack_results=[],
            candidate=None,
            hard_gate_passed=False,
        )
        return self._seal(observation)

    def _candidate_blocked_observation(
        self,
        *,
        request: dict[str, Any],
        request_sha256: str,
        gate_results: list[dict[str, Any]],
        blockers: list[str],
    ) -> dict[str, Any]:
        observation = self._observation_base(
            request=request,
            request_sha256=request_sha256,
            status="blocked",
            adoption_status="not_admitted",
            blockers=sorted(set(blockers)),
            gate_results=gate_results,
            attack_results=[],
            candidate=None,
            hard_gate_passed=False,
        )
        return self._seal(observation)

    def _observation_base(
        self,
        *,
        request: dict[str, Any],
        request_sha256: str,
        status: str,
        adoption_status: str,
        blockers: list[str],
        gate_results: list[dict[str, Any]],
        attack_results: list[dict[str, Any]],
        candidate: dict[str, Any] | None,
        hard_gate_passed: bool,
    ) -> dict[str, Any]:
        return {
            "contract_id": self.CONTRACT_ID,
            "run_id": f"cbr_{request_sha256[:32]}",
            "status": status,
            "adoption_status": adoption_status,
            "request_sha256": request_sha256,
            "scope": {
                "tenant_ref": request["tenant_ref"],
                "entity_ref": request["entity_ref"],
                "store_ref": request["store_ref"],
                "scope_grant_authority_sha256": request["scope_grant_authority_sha256"],
            },
            "as_of": request["as_of"],
            "authority_checked_at": request["authority_checked_at"],
            "attack_registry_ref": request["attack_registry_ref"],
            "attack_set_ref": request["attack_set_ref"],
            "candidate": candidate,
            "technology_gates": gate_results,
            "attack_results": attack_results,
            "hard_gate_passed": hard_gate_passed,
            "attack_failures_averaged": False,
            "blockers": blockers,
            "observation_only": True,
            "bas177_controls_promotion": True,
            "governance": {flag: False for flag in GOVERNANCE_FALSE_FLAGS},
        }

    @staticmethod
    def _seal(observation: dict[str, Any]) -> dict[str, Any]:
        if _has_sensitive_projection(observation):
            raise ConstraintBreakerContractError("Observation contains sensitive projection")
        observation["observation_sha256"] = _sha(observation)
        return observation
