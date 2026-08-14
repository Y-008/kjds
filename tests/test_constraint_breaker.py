from __future__ import annotations

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from apps.control_plane.constraint_breaker import (
    GOVERNANCE_FALSE_FLAGS,
    TECHNOLOGY_GATE_IDS,
    ConstraintBreakerAttackRegistry,
    ConstraintBreakerAttemptUnknown,
    ConstraintBreakerConflictError,
    ConstraintBreakerContractError,
    ConstraintBreakerRunClaimAuthorityError,
    ConstraintBreakerWorkspace,
    FrozenConstraintBreakerAttackSet,
)
from apps.control_plane.security import Principal

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "docs/project/registries/constraint_breaker_attack_registry.json"
ATTACK_SET_PATH = ROOT / "tests/fixtures/constraint_breaker/bas202_constraint_breaker_v1.json"
STRATEGIC_PATH = ROOT / "docs/project/registries/strategic_benchmark_contracts.json"
AS_OF = datetime(2026, 8, 4, 8, 0, tzinfo=UTC)
AUTHORITY_A = "a" * 64
_ATTACK_FIXTURE = json.loads(ATTACK_SET_PATH.read_text(encoding="utf-8"))
ATTACK_CASE_COUNT = len(_ATTACK_FIXTURE["attack_cases"])
UNKNOWN_CASE_ORDINAL = next(
    index
    for index, case in enumerate(_ATTACK_FIXTURE["attack_cases"], start=1)
    if case["case_id"] == "unknown-outcome-no-replay"
)


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha(value: Any) -> str:
    if isinstance(value, str):
        value = {"value": value}
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _seal_gate(gate: dict[str, Any]) -> None:
    gate.pop("receipt_sha256", None)
    gate["receipt_sha256"] = hashlib.sha256(_canonical(gate).encode()).hexdigest()


def _seal_candidate(candidate: dict[str, Any]) -> None:
    for gate in candidate["gates"]:
        _seal_gate(gate)
    candidate.pop("manifest_sha256", None)
    candidate["manifest_sha256"] = hashlib.sha256(
        _canonical(candidate).encode()
    ).hexdigest()


def _scope(authority: str = AUTHORITY_A) -> dict[str, Any]:
    return {
        "tenant_ref": "tenant-a",
        "entity_ref": "entity-a",
        "store_ref": "store-a",
        "scope_grant_authority_sha256": authority,
    }


def _entity_scope(authority: str = AUTHORITY_A) -> dict[str, Any]:
    return {
        "status": "ready",
        "tenant_ref": "tenant-a",
        "entity_ref": "entity-a",
        "store_ref": "store-a",
        "authority_sha256": authority,
    }


def _best_solution_claims() -> dict[str, Any]:
    options = ["build", "buy", "partner", "defer", "no_action"]
    hard_dimensions = [
        "evidence",
        "authority",
        "security",
        "privacy",
        "legal_and_license",
        "cash_floor",
        "maximum_loss",
        "rollback",
        "acceptance",
    ]
    return {
        "required_options": options,
        "selected_option": "build",
        "rejected_options": [
            {"option": option, "reason_code": f"{option}-dominated"}
            for option in options
            if option != "build"
        ],
        "hard_elimination": {dimension: True for dimension in hard_dimensions},
        "comparison_dimensions": [
            "long_term_risk_adjusted_value",
            "total_cost_of_ownership",
            "time_to_value",
            "operational_fit",
            "maintainability",
            "reversibility",
            "replacement_cost",
        ],
        "sensitivity_codes": ["cost-plus-20pct"],
        "invalidation_condition_codes": ["license-or-quality-drift"],
        "review_date": "2026-08-04",
        "approval_requirement": "bas177-independent-review",
        "independent_counterargument_code": "buy-may-reduce-time-to-value",
        "equal_weight_total_score_used": False,
    }


def _gate_claims(gate_id: str) -> dict[str, Any]:
    if gate_id == "best_solution":
        return _best_solution_claims()
    if gate_id == "license_provenance":
        return {
            "license_id": "apache-2.0",
            "license_sha256": _sha("license"),
            "provenance_sha256": _sha("provenance"),
            "license_allowed": True,
            "provenance_verified": True,
        }
    if gate_id == "data_boundary":
        return {
            "data_classification": "synthetic_public",
            "contains_customer_data": False,
            "contains_secrets": False,
            "contains_provider_ids": False,
            "boundary_verified": True,
        }
    if gate_id == "quality_cost":
        return {
            "quality_metric_id": "hard-gate-pass-rate",
            "quality_value": 1.0,
            "quality_floor": 1.0,
            "cost_microunits": 10,
            "cost_ceiling_microunits": 100,
            "maximum_loss_microunits": 0,
            "maximum_loss_ceiling_microunits": 1,
        }
    if gate_id == "rollback":
        return {
            "rollback_artifact_sha256": _sha("rollback"),
            "rollback_verified": True,
            "reversible": True,
        }
    return {
        "admission_receipt_sha256": _sha("admission"),
        "admission_mode": "explicitly_admitted_isolated_sample",
        "data_classification": "redacted_non_customer",
        "contains_customer_data": False,
        "admitted": True,
    }


@dataclass
class _EvidenceRecord:
    id: str
    sha256: str
    recorded_at: datetime
    effective_at: datetime
    effective_until: datetime | None
    source: str
    source_ref: str
    metadata: dict[str, Any]
    content_bytes: bytes
    grade: Any = "A"


class _EvidenceStore:
    def __init__(self) -> None:
        self.records: dict[str, _EvidenceRecord] = {}
        self.invalid: set[str] = set()

    def put(
        self,
        *,
        evidence_id: str,
        payload: dict[str, Any],
        source: str,
        source_ref: str,
        schema_id: str,
        recorded_at: datetime,
        effective_at: datetime,
        effective_until: datetime,
    ) -> str:
        content = _canonical(payload).encode()
        digest = hashlib.sha256(content).hexdigest()
        self.records[evidence_id] = _EvidenceRecord(
            id=evidence_id,
            sha256=digest,
            recorded_at=recorded_at,
            effective_at=effective_at,
            effective_until=effective_until,
            source=source,
            source_ref=source_ref,
            metadata={"schema_id": schema_id, "payload_sha256": digest},
            content_bytes=content,
        )
        return digest

    def inspect_integrity(self, evidence_id: str):
        record = self.records[evidence_id]
        return record, SimpleNamespace(
            valid=(
                evidence_id not in self.invalid
                and hashlib.sha256(record.content_bytes).hexdigest() == record.sha256
            )
        )

    def content(self, evidence_id: str):
        record = self.records[evidence_id]
        return record.content_bytes, record


class _ScopedEvidence:
    def __init__(self) -> None:
        self.evidence = _EvidenceStore()
        self.status = "ready"
        self.scope_binding_status = "ready"
        self.attack_status = "ready"
        self.attack_scope_binding_status = "ready"
        self.projected_sha_overrides: dict[str, str] = {}

    def project_targets(self, *, evidence_ids: list[str], **_: Any) -> dict[str, Any]:
        attack_projection = all(item.startswith("attack-") for item in evidence_ids)
        return {
            "status": self.attack_status if attack_projection else self.status,
            "records": [
                {
                    "evidence_id": evidence_id,
                    "sha256": self.projected_sha_overrides.get(
                        evidence_id, self.evidence.records[evidence_id].sha256
                    ),
                    "grade": "A",
                    "scope_binding": {
                        "status": (
                            self.attack_scope_binding_status
                            if attack_projection
                            else self.scope_binding_status
                        )
                    },
                }
                for evidence_id in evidence_ids
            ],
        }


class _ScopeGrants:
    def __init__(self) -> None:
        self.value = _entity_scope()
        self.calls: list[datetime] = []

    def current(self, *, as_of: datetime, **_: Any) -> dict[str, Any]:
        self.calls.append(as_of)
        return deepcopy(self.value)


class _AgentRunReceiptAuthority:
    def __init__(self) -> None:
        self.invalid_purposes: set[str] = set()
        self.raise_purposes: set[str] = set()
        self.calls = 0

    def verify_receipt(
        self,
        *,
        receipt_sha256: str,
        scope: dict[str, Any],
        purpose: str,
        binding_sha256: str,
        **_: Any,
    ) -> dict[str, Any]:
        self.calls += 1
        if purpose in self.raise_purposes:
            raise KeyError("synthetic hidden receipt authority failure")
        return {
            "status": "blocked" if purpose in self.invalid_purposes else "ready",
            "receipt_sha256": receipt_sha256,
            "scope": deepcopy(scope),
            "proposal_only": True,
            "external_write": False,
            "hash_chain_valid": True,
            "purpose": purpose,
            "binding_sha256": binding_sha256,
        }


class _TechnologyAuthority:
    def __init__(self, scoped_evidence: _ScopedEvidence) -> None:
        self.scoped_evidence = scoped_evidence
        self.calls = 0
        self.mutator = None
        self.evidence_mutator = None
        self.raise_error = False

    def resolve_candidate(
        self,
        *,
        scope: dict[str, Any],
        as_of: datetime,
        **_: Any,
    ) -> dict[str, Any]:
        self.calls += 1
        if self.raise_error:
            raise RuntimeError("synthetic candidate authority unavailable")
        candidate = {
            "contract_id": "kjds-constraint-breaker-candidate-admission-v1",
            "candidate_id": "candidate-a",
            "candidate_version": "1.0.0",
            "artifact_sha256": _sha("artifact"),
            "license_id": "apache-2.0",
            "license_sha256": _sha("license"),
            "provenance_sha256": _sha("provenance"),
            "data_classification": "synthetic_public",
            "scope": deepcopy(scope),
            "recorded_at": (as_of - timedelta(days=1)).isoformat(),
            "effective_from": (as_of - timedelta(days=2)).isoformat(),
            "effective_until": (as_of + timedelta(days=2)).isoformat(),
            "environment_versions": {"runtime": "synthetic-v1"},
            "agent_run_receipt_sha256": _sha("agent-run-receipt"),
            "retrieval_observation_sha256": _sha("retrieval-observation"),
            "loop_registry_sha256": _sha("loop-registry"),
            "gates": [],
        }
        authority_tag = str(scope["scope_grant_authority_sha256"])[:8]
        for gate_id in TECHNOLOGY_GATE_IDS:
            claims = _gate_claims(gate_id)
            evidence_id = f"ev-{gate_id}-{authority_tag}"
            payload = {
                "contract_id": "kjds-constraint-breaker-technology-gate-evidence-v1",
                "policy_id": "kjds-constraint-breaker-technology-policy-v1",
                "policy_version": "1.0.0",
                "gate_id": gate_id,
                "candidate_id": "candidate-a",
                "candidate_version": "1.0.0",
                "artifact_sha256": candidate["artifact_sha256"],
                "scope": deepcopy(scope),
                "claims": deepcopy(claims),
            }
            evidence_sha = self.scoped_evidence.evidence.put(
                evidence_id=evidence_id,
                payload=payload,
                source="constraint-breaker-technology-gate",
                source_ref=f"constraint-breaker-gate://candidate-a/{gate_id}",
                schema_id="kjds-constraint-breaker-technology-gate-evidence-v1",
                recorded_at=as_of - timedelta(days=1),
                effective_at=as_of - timedelta(days=2),
                effective_until=as_of + timedelta(days=2),
            )
            gate = {
                "gate_id": gate_id,
                "status": "pass",
                "evidence_refs": [
                    {"evidence_id": evidence_id, "evidence_sha256": evidence_sha}
                ],
                "claims": claims,
            }
            _seal_gate(gate)
            candidate["gates"].append(gate)
        _seal_candidate(candidate)
        if self.mutator is not None:
            self.mutator(candidate)
        return candidate


class _DurableRunnerStore:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.claims: dict[str, dict[str, Any]] = {}
        self.attempts: dict[str, tuple[str, Any]] = {}
        self.execution_count = 0
        self.provider_attempts = 0
        self.case_calls: dict[str, int] = {}


class _Runner:
    def __init__(
        self,
        scoped_evidence: _ScopedEvidence,
        *,
        durable: _DurableRunnerStore | None = None,
    ) -> None:
        self.scoped_evidence = scoped_evidence
        self.method_calls = 0
        self.mutator = None
        self.evidence_mutator = None
        self.unknown_behavior: dict[str, str] = {}
        self.envelope_mutator = None
        self.unknown_receipt_mutator = None
        self.durable = durable or _DurableRunnerStore()
        self.registry_sha256 = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))[
            "content_sha256"
        ]
        self.attack_set_sha256 = json.loads(ATTACK_SET_PATH.read_text(encoding="utf-8"))[
            "content_sha256"
        ]

    @property
    def calls(self) -> int:
        return self.durable.execution_count

    @property
    def provider_attempts(self) -> int:
        return self.durable.provider_attempts

    @property
    def case_calls(self) -> dict[str, int]:
        return self.durable.case_calls

    def claim_run(
        self,
        *,
        run_key_sha256: str,
        request_sha256: str,
        scope: dict[str, Any],
        checked_at: datetime,
    ) -> dict[str, Any]:
        with self.durable.lock:
            prior = self.durable.claims.get(run_key_sha256)
            if prior is not None:
                return deepcopy(prior)
            claim = {
                "contract_id": "kjds-constraint-breaker-durable-run-claim-v1",
                "run_key_sha256": run_key_sha256,
                "request_sha256": request_sha256,
                "scope": deepcopy(scope),
                "first_authority_checked_at": checked_at.isoformat(),
                "agent_run_receipt_sha256": _sha(f"run-claim-{run_key_sha256}"),
            }
            claim["receipt_sha256"] = hashlib.sha256(
                _canonical(claim).encode()
            ).hexdigest()
            self.durable.claims[run_key_sha256] = deepcopy(claim)
            return claim

    @staticmethod
    def _expected_counters(case: dict[str, Any]) -> dict[str, int]:
        return {
            "provider_call_count": case["expected_provider_calls"],
            "tool_call_count": case["expected_tool_calls"],
            "provider_replay_count": case["expected_provider_replay_calls"],
            "tool_replay_count": case["expected_tool_replay_calls"],
            "external_write_count": case["expected_external_writes"],
            "cross_scope_records_exposed": case[
                "expected_cross_scope_records_exposed"
            ],
        }

    def _attempt_receipt(
        self,
        *,
        case: dict[str, Any],
        candidate: dict[str, Any],
        scope: dict[str, Any],
        attempt: dict[str, Any],
        state: str,
        counters: dict[str, int],
        result_projection_sha256: str | None,
    ) -> dict[str, Any]:
        recorded_at = datetime.fromisoformat(attempt["authority_checked_at"])
        receipt = {
            "contract_id": "kjds-constraint-breaker-attempt-counter-v1",
            "attempt_sha256": attempt["attempt_sha256"],
            "run_key_sha256": attempt["run_key_sha256"],
            "request_sha256": attempt["request_sha256"],
            "case_sha256": case["case_sha256"],
            "candidate_manifest_sha256": candidate["manifest_sha256"],
            "scope": deepcopy(scope),
            "attempt_state": state,
            **counters,
            "result_projection_sha256": result_projection_sha256,
            "agent_run_receipt_sha256": _sha(
                f"attempt-{attempt['attempt_sha256']}-{state}"
            ),
            "recorded_at": recorded_at.isoformat(),
            "effective_until": (recorded_at + timedelta(days=1)).isoformat(),
        }
        receipt["receipt_sha256"] = hashlib.sha256(
            _canonical(receipt).encode()
        ).hexdigest()
        return receipt

    def execute_once(
        self,
        *,
        case: dict[str, Any],
        candidate: dict[str, Any],
        scope: dict[str, Any],
        attempt: dict[str, Any],
    ) -> dict[str, Any]:
        attempt_sha = attempt["attempt_sha256"]
        with self.durable.lock:
            self.method_calls += 1
            prior = self.durable.attempts.get(attempt_sha)
            if prior is not None:
                kind, value = prior
                if kind == "complete":
                    return deepcopy(value)
                if kind == "attempt_started":
                    raise RuntimeError("durable attempt outcome unknown")
                if value is None:
                    raise RuntimeError("durable unknown without receipt")
                raise ConstraintBreakerAttemptUnknown(deepcopy(value))
            self.durable.attempts[attempt_sha] = ("attempt_started", None)
            self.durable.execution_count += 1
            self.durable.case_calls[case["case_id"]] = (
                self.durable.case_calls.get(case["case_id"], 0) + 1
            )
            counters = self._expected_counters(case)
            behavior = self.unknown_behavior.get(case["case_id"])
            if behavior:
                actual = deepcopy(counters)
                if behavior == "before_provider":
                    actual["provider_call_count"] = 0
                elif behavior == "after_replay":
                    actual["provider_replay_count"] = 1
                if behavior in {"after_first", "after_replay", "tampered"}:
                    self.durable.provider_attempts += actual["provider_call_count"]
                receipt = None
                if behavior != "missing":
                    receipt = self._attempt_receipt(
                        case=case,
                        candidate=candidate,
                        scope=scope,
                        attempt=attempt,
                        state="unknown",
                        counters=actual,
                        result_projection_sha256=None,
                    )
                    if behavior == "tampered":
                        receipt["provider_call_count"] += 1
                    if self.unknown_receipt_mutator is not None:
                        self.unknown_receipt_mutator(case, receipt, attempt)
                self.durable.attempts[attempt_sha] = ("unknown", deepcopy(receipt))
                if receipt is None:
                    raise RuntimeError("unknown attempt")
                raise ConstraintBreakerAttemptUnknown(receipt)

            self.durable.provider_attempts += counters["provider_call_count"]
            result = {
                "case_id": case["case_id"],
                "case_sha256": case["case_sha256"],
                "attack_class": case["attack_class"],
                "outcome": "resisted",
                "reason_codes": list(case["expected_defense_codes"]),
                **counters,
                "latency_ms": 1,
                "cost_microunits": 1,
                "safe_output_sha256": _sha(f"output-{case['case_id']}"),
                "fix_reference": "fix://constraint-boundary-v1",
                "regression_result": "pass",
                "evidence_refs": [],
            }
            if self.mutator is not None:
                try:
                    result = self.mutator(case, result)
                except Exception:
                    raise
            result_projection = {
                key: value for key, value in result.items() if key != "evidence_refs"
            }
            evidence_id = f"attack-{attempt_sha[:32]}"
            payload = {
                "contract_id": "kjds-constraint-breaker-attack-receipt-v1",
                "registry_sha256": self.registry_sha256,
                "attack_set_sha256": self.attack_set_sha256,
                "case_sha256": case["case_sha256"],
                "candidate_manifest_sha256": candidate["manifest_sha256"],
                "scope": deepcopy(scope),
                "attempt_sha256": attempt_sha,
                "result_projection_sha256": hashlib.sha256(
                    _canonical(result_projection).encode()
                ).hexdigest(),
            }
            checked_at = datetime.fromisoformat(attempt["authority_checked_at"])
            evidence_sha = self.scoped_evidence.evidence.put(
                evidence_id=evidence_id,
                payload=payload,
                source="constraint-breaker-attack-receipt",
                source_ref=f"constraint-breaker-attack://{attempt_sha}",
                schema_id="kjds-constraint-breaker-attack-receipt-v1",
                recorded_at=checked_at,
                effective_at=checked_at,
                effective_until=checked_at + timedelta(days=1),
            )
            result["evidence_refs"] = [
                {"evidence_id": evidence_id, "evidence_sha256": evidence_sha}
            ]
            if self.evidence_mutator is not None:
                self.evidence_mutator(
                    self.scoped_evidence.evidence.records[evidence_id],
                    result,
                    payload,
                )
            receipt = self._attempt_receipt(
                case=case,
                candidate=candidate,
                scope=scope,
                attempt=attempt,
                state="completed",
                counters={field: result[field] for field in counters},
                result_projection_sha256=hashlib.sha256(
                    _canonical(result).encode()
                ).hexdigest(),
            )
            envelope = {"result": result, "attempt_receipt": receipt}
            if self.envelope_mutator is not None:
                envelope = self.envelope_mutator(case, envelope, attempt)
            self.durable.attempts[attempt_sha] = ("complete", deepcopy(envelope))
            return envelope


class _AdvancingClock:
    def __init__(self) -> None:
        self.value = AS_OF + timedelta(hours=1)

    def __call__(self) -> datetime:
        current = self.value
        self.value += timedelta(minutes=1)
        return current


@dataclass
class _Harness:
    workspace: ConstraintBreakerWorkspace
    scope_grants: _ScopeGrants
    scoped_evidence: _ScopedEvidence
    agent_runs: _AgentRunReceiptAuthority
    technology: _TechnologyAuthority
    runner: _Runner
    clock: _AdvancingClock


def _workspace(
    *,
    scope_grants: _ScopeGrants,
    scoped_evidence: _ScopedEvidence,
    agent_runs: _AgentRunReceiptAuthority,
    technology: _TechnologyAuthority,
    runner: _Runner,
    clock: _AdvancingClock,
) -> ConstraintBreakerWorkspace:
    return ConstraintBreakerWorkspace(
        scope_grants=scope_grants,
        scoped_evidence=scoped_evidence,
        agent_run_receipt_authority=agent_runs,
        technology_gate_authority=technology,
        attack_runner=runner,
        attack_registry_path=REGISTRY_PATH,
        attack_set_path=ATTACK_SET_PATH,
        strategic_contract_path=STRATEGIC_PATH,
        clock=clock,
    )


def _harness() -> _Harness:
    scope_grants = _ScopeGrants()
    scoped_evidence = _ScopedEvidence()
    agent_runs = _AgentRunReceiptAuthority()
    technology = _TechnologyAuthority(scoped_evidence)
    runner = _Runner(scoped_evidence)
    clock = _AdvancingClock()
    workspace = _workspace(
        scope_grants=scope_grants,
        scoped_evidence=scoped_evidence,
        agent_runs=agent_runs,
        technology=technology,
        runner=runner,
        clock=clock,
    )
    return _Harness(
        workspace,
        scope_grants,
        scoped_evidence,
        agent_runs,
        technology,
        runner,
        clock,
    )


def _principal(**changes: Any) -> Principal:
    values = {
        "actor_id": "operator-a",
        "roles": frozenset({"operator"}),
        "tenant_ref": "tenant-a",
        "store_refs": frozenset({"store-a"}),
    }
    values.update(changes)
    return Principal(**values)


def _evaluate(harness: _Harness, **changes: Any) -> dict[str, Any]:
    values = {
        "principal": _principal(),
        "store_ref": "store-a",
        "as_of": AS_OF,
        "candidate_id": "candidate-a",
        "attack_set_ref": harness.workspace.attack_set.ref,
        "idempotency_key": "bas202-run-a",
    }
    values.update(changes)
    return harness.workspace.evaluate(**values)


def _rewrite_gate_evidence(
    harness: _Harness,
    candidate: dict[str, Any],
    gate_id: str,
    mutate_claim,
) -> None:
    gate = next(item for item in candidate["gates"] if item["gate_id"] == gate_id)
    evidence_id = gate["evidence_refs"][0]["evidence_id"]
    record = harness.scoped_evidence.evidence.records[evidence_id]
    payload = json.loads(record.content_bytes.decode())
    mutate_claim(payload["claims"])
    evidence_sha = harness.scoped_evidence.evidence.put(
        evidence_id=evidence_id,
        payload=payload,
        source=record.source,
        source_ref=record.source_ref,
        schema_id=record.metadata["schema_id"],
        recorded_at=record.recorded_at,
        effective_at=record.effective_at,
        effective_until=record.effective_until or AS_OF + timedelta(days=1),
    )
    gate["claims"] = deepcopy(payload["claims"])
    gate["evidence_refs"][0]["evidence_sha256"] = evidence_sha
    _seal_candidate(candidate)


def test_registry_and_fixture_are_content_addressed_and_cover_all_classes() -> None:
    registry = ConstraintBreakerAttackRegistry.load(
        REGISTRY_PATH,
        strategic_contract_path=STRATEGIC_PATH,
    )
    attack_set = FrozenConstraintBreakerAttackSet.load(
        ATTACK_SET_PATH,
        registry=registry,
    )

    assert len(attack_set.cases) == ATTACK_CASE_COUNT == 15
    assert {case["attack_class"] for case in attack_set.cases} == set(
        registry.attack_classes
    )
    assert registry.payload["hard_gate_rules"][
        "eligible_iff_all_required_cases_resisted"
    ]
    assert registry.payload["hard_gate_rules"][
        "unknown_blocked_or_not_executed_not_admitted"
    ]
    assert all(
        case["expected_external_writes"] == 0
        and case["expected_cross_scope_records_exposed"] == 0
        and case["expected_provider_replay_calls"] == 0
        and case["expected_tool_replay_calls"] == 0
        for case in attack_set.cases
    )


def test_all_resisted_and_all_technology_gates_pass_only_admits_to_bas177_candidate() -> None:
    harness = _harness()

    observation = _evaluate(harness)

    assert observation["status"] == "ready"
    assert observation["adoption_status"] == "eligible_for_bas177_candidate"
    assert observation["hard_gate_passed"] is True
    assert len(observation["attack_results"]) == ATTACK_CASE_COUNT
    assert all(item["gate_status"] == "pass" for item in observation["attack_results"])
    assert all(item["status"] == "pass" for item in observation["technology_gates"])
    assert observation["bas177_controls_promotion"] is True
    assert observation["attack_failures_averaged"] is False
    assert observation["governance"] == {flag: False for flag in GOVERNANCE_FALSE_FLAGS}
    expected_sha = hashlib.sha256(
        _canonical(
            {key: value for key, value in observation.items() if key != "observation_sha256"}
        ).encode()
    ).hexdigest()
    assert observation["observation_sha256"] == expected_sha


@pytest.mark.parametrize(
    "attack_class",
    [
        "prompt_injection",
        "indirect_document_or_web_injection",
        "cross_tenant_or_session_scope",
        "idempotency_drift",
        "toolchain_poisoning",
        "data_poisoning",
        "budget_escape",
        "unknown_outcome_replay",
        "authority_claim_forgery",
        "metric_gaming",
    ],
)
def test_each_attack_success_is_a_non_averageable_hard_failure(attack_class: str) -> None:
    harness = _harness()

    def succeed(case: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        if case["attack_class"] == attack_class:
            result["outcome"] = "attack_succeeded"
        return result

    harness.runner.mutator = succeed
    observation = _evaluate(harness)

    assert observation["status"] == "blocked"
    assert observation["adoption_status"] == "not_admitted"
    assert observation["hard_gate_passed"] is False
    assert observation["attack_failures_averaged"] is False
    assert any(item["gate_status"] == "fail" for item in observation["attack_results"])
    assert observation["governance"]["self_promotion"] is False


@pytest.mark.parametrize("outcome", ["unknown", "blocked", "not_executed"])
def test_unknown_blocked_or_not_executed_is_not_admitted(outcome: str) -> None:
    harness = _harness()

    def uncertain(case: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        if case["case_id"] == "unknown-outcome-no-replay":
            result["outcome"] = outcome
        return result

    harness.runner.mutator = uncertain
    if outcome == "blocked":
        def bind_blocked_terminal(
            case: dict[str, Any],
            envelope: dict[str, Any],
            attempt: dict[str, Any],
        ) -> dict[str, Any]:
            del attempt
            if case["case_id"] != "unknown-outcome-no-replay":
                return envelope
            receipt = envelope["attempt_receipt"]
            receipt["attempt_state"] = "blocked"
            receipt.pop("receipt_sha256", None)
            receipt["receipt_sha256"] = hashlib.sha256(
                _canonical(receipt).encode()
            ).hexdigest()
            return envelope

        harness.runner.envelope_mutator = bind_blocked_terminal
    observation = _evaluate(harness)

    assert observation["status"] == "blocked"
    assert observation["adoption_status"] == "not_admitted"
    assert observation["hard_gate_passed"] is False
    target = next(
        item for item in observation["attack_results"] if item["case_id"] == "unknown-outcome-no-replay"
    )
    expected_replay_count = 0 if outcome == "blocked" else None
    assert target["provider_replay_count"] == expected_replay_count
    assert target["tool_replay_count"] == expected_replay_count


@pytest.mark.parametrize(
    "case_id,counter",
    [
        ("direct-injection-override", "provider_call_count"),
        ("indirect-document-injection", "tool_call_count"),
        ("cross-scope-reference", "provider_call_count"),
        ("idempotency-fingerprint-drift", "tool_call_count"),
        ("tool-manifest-poisoning", "provider_call_count"),
        ("tool-confusable-alias", "tool_call_count"),
        ("authority-claim-forgery", "provider_call_count"),
    ],
)
def test_precall_attack_classes_require_exact_zero_invocation_counters(
    case_id: str,
    counter: str,
) -> None:
    harness = _harness()

    def invoke(case: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        if case["case_id"] == case_id:
            result[counter] = 1
        return result

    harness.runner.mutator = invoke
    observation = _evaluate(harness)
    target = next(item for item in observation["attack_results"] if item["case_id"] == case_id)

    assert observation["adoption_status"] == "not_admitted"
    assert target["gate_status"] == "blocked"
    assert f"exact_counter_drift_{counter}" in target["reason_codes"]


def test_crash_after_attempt_started_is_cached_and_never_replays_runner() -> None:
    harness = _harness()

    def crash(case: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        if case["case_id"] == "unknown-outcome-no-replay":
            raise RuntimeError("synthetic crash after attempt_started")
        return result

    harness.runner.mutator = crash
    first = _evaluate(harness)
    call_count = harness.runner.calls
    provider_attempts = harness.runner.provider_attempts
    second = _evaluate(harness)

    assert first == second
    assert harness.runner.calls == call_count
    assert first["adoption_status"] == "not_admitted"
    target = next(
        item for item in first["attack_results"] if item["case_id"] == "unknown-outcome-no-replay"
    )
    assert target["outcome"] == "unknown"
    assert target["provider_call_count"] is None
    assert target["provider_replay_count"] is None
    assert target["counter_receipt_status"] == "missing"
    assert "provider_tool_replay_suppressed" not in target["reason_codes"]
    assert "synthetic crash" not in _canonical(first)
    restarted_runner = _Runner(
        harness.scoped_evidence,
        durable=harness.runner.durable,
    )
    harness.runner = restarted_runner
    harness.workspace = _workspace(
        scope_grants=harness.scope_grants,
        scoped_evidence=harness.scoped_evidence,
        agent_runs=harness.agent_runs,
        technology=harness.technology,
        runner=restarted_runner,
        clock=harness.clock,
    )
    restarted = _evaluate(harness)
    assert restarted == first
    assert harness.runner.calls == call_count
    assert harness.runner.provider_attempts == provider_attempts == 1
    assert "authority-claim-forgery" not in harness.runner.case_calls


@pytest.mark.parametrize(
    "behavior,receipt_status,provider_calls,provider_replays,required_reason,forbidden_reason",
    [
        ("before_provider", "verified_drift", 0, 0, "provider_first_attempt_count_invalid", "provider_tool_replay_suppressed"),
        ("after_first", "verified_exact", 1, 0, "provider_tool_replay_suppressed", "provider_or_tool_replay_detected"),
        ("after_replay", "verified_drift", 1, 1, "provider_or_tool_replay_detected", "provider_tool_replay_suppressed"),
        ("missing", "missing", None, None, "attempt_counter_receipt_missing", "provider_tool_replay_suppressed"),
        ("tampered", "invalid", None, None, "attempt_counter_receipt_invalid", "provider_tool_replay_suppressed"),
    ],
)
def test_unknown_attempt_requires_independent_sealed_actual_counter_receipt(
    behavior: str,
    receipt_status: str,
    provider_calls: int | None,
    provider_replays: int | None,
    required_reason: str,
    forbidden_reason: str,
) -> None:
    harness = _harness()
    harness.runner.unknown_behavior["unknown-outcome-no-replay"] = behavior

    observation = _evaluate(harness)
    target = observation["attack_results"][-1]

    assert target["case_id"] == "unknown-outcome-no-replay"
    assert target["counter_receipt_status"] == receipt_status
    assert target["provider_call_count"] == provider_calls
    assert target["provider_replay_count"] == provider_replays
    assert required_reason in target["reason_codes"]
    assert forbidden_reason not in target["reason_codes"]
    assert observation["adoption_status"] == "not_admitted"
    assert "required_attack_cases_not_completed" in observation["blockers"]
    assert "authority-claim-forgery" not in harness.runner.case_calls


def test_unknown_attempt_restart_uses_durable_agent_run_receipt_without_spend_replay() -> None:
    harness = _harness()
    harness.runner.unknown_behavior["unknown-outcome-no-replay"] = "after_first"
    first = _evaluate(harness)
    first_calls = harness.runner.calls
    first_provider_attempts = harness.runner.provider_attempts
    restarted_runner = _Runner(
        harness.scoped_evidence,
        durable=harness.runner.durable,
    )
    restarted = _workspace(
        scope_grants=harness.scope_grants,
        scoped_evidence=harness.scoped_evidence,
        agent_runs=harness.agent_runs,
        technology=harness.technology,
        runner=restarted_runner,
        clock=harness.clock,
    )
    harness.runner = restarted_runner
    harness.workspace = restarted

    replay = _evaluate(harness)

    assert replay == first
    assert harness.runner.calls == first_calls == UNKNOWN_CASE_ORDINAL
    assert harness.runner.provider_attempts == first_provider_attempts == 1
    assert replay["attack_results"][-1]["counter_receipt_status"] == "verified_exact"
    assert "authority-claim-forgery" not in harness.runner.case_calls


def test_independent_agent_run_authority_rejects_runner_self_signed_counter_receipt() -> None:
    harness = _harness()
    harness.agent_runs.invalid_purposes.add("constraint-breaker-attempt")

    observation = _evaluate(harness)

    assert observation["adoption_status"] == "not_admitted"
    assert observation["attack_results"][0]["counter_receipt_status"] == "missing"
    assert "attempt_counter_receipt_authority_invalid" in observation[
        "attack_results"
    ][0]["reason_codes"]
    assert harness.runner.calls == 1


def test_candidate_receipt_authority_exception_is_classified_without_attack_or_leak() -> None:
    harness = _harness()
    harness.agent_runs.raise_purposes.add("constraint-breaker-candidate")

    observation = _evaluate(harness)

    assert observation["blockers"] == [
        "candidate_agent_run_receipt_authority_invalid"
    ]
    assert observation["attack_results"] == []
    assert harness.runner.calls == 0
    assert harness.runner.provider_attempts == 0
    assert "synthetic hidden" not in json.dumps(observation)


def test_run_claim_receipt_authority_exception_is_typed_without_attack_or_leak() -> None:
    harness = _harness()
    harness.agent_runs.raise_purposes.add("constraint-breaker-run-claim")

    with pytest.raises(ConstraintBreakerRunClaimAuthorityError) as exc_info:
        _evaluate(harness)

    assert str(exc_info.value) == "durable run claim authority invalid"
    assert harness.runner.calls == 0
    assert harness.runner.provider_attempts == 0
    assert "synthetic hidden" not in str(exc_info.value)


def test_attempt_receipt_authority_exception_is_unknown_without_counter_claim_or_leak() -> None:
    harness = _harness()
    harness.agent_runs.raise_purposes.add("constraint-breaker-attempt")

    observation = _evaluate(harness)

    first = observation["attack_results"][0]
    assert observation["adoption_status"] == "not_admitted"
    assert first["counter_receipt_status"] == "missing"
    assert "attempt_counter_receipt_authority_invalid" in first["reason_codes"]
    assert first["provider_call_count"] is None
    assert first["tool_call_count"] is None
    assert first["provider_replay_count"] is None
    assert first["tool_replay_count"] is None
    assert "provider_tool_replay_suppressed" not in first["reason_codes"]
    assert harness.runner.calls == 1
    assert harness.runner.provider_attempts == 0
    assert "synthetic hidden" not in json.dumps(observation)


@pytest.mark.parametrize(
    "fault,reason",
    [
        ("authority_unavailable", "candidate_authority_unavailable"),
        ("manifest_hash", "candidate_manifest_or_gate_evidence_invalid"),
        ("gate_evidence", "candidate_manifest_or_gate_evidence_invalid"),
        ("candidate_agent_run", "candidate_agent_run_receipt_authority_invalid"),
    ],
)
def test_candidate_failure_reasons_distinguish_authority_manifest_and_evidence(
    fault: str,
    reason: str,
) -> None:
    harness = _harness()
    if fault == "authority_unavailable":
        harness.technology.raise_error = True
    elif fault == "candidate_agent_run":
        harness.agent_runs.invalid_purposes.add("constraint-breaker-candidate")
    else:
        def mutate(candidate: dict[str, Any]) -> None:
            if fault == "manifest_hash":
                candidate["manifest_sha256"] = "f" * 64
            else:
                gate = candidate["gates"][0]
                evidence_id = gate["evidence_refs"][0]["evidence_id"]
                harness.scoped_evidence.evidence.records[evidence_id].source = (
                    "unrelated-grade-a-evidence"
                )

        harness.technology.mutator = mutate

    observation = _evaluate(harness)

    assert observation["blockers"] == [reason]
    assert observation["attack_results"] == []


def test_run_claim_authority_failure_has_a_distinct_fail_closed_exception() -> None:
    harness = _harness()
    harness.agent_runs.invalid_purposes.add("constraint-breaker-run-claim")

    with pytest.raises(ConstraintBreakerRunClaimAuthorityError):
        _evaluate(harness)

    assert harness.runner.calls == 0


@pytest.mark.parametrize(
    "drift",
    ["state_swap", "case", "run", "scope", "authority", "result_hash"],
)
def test_completed_attempt_receipt_rehash_cannot_cross_bind_identity(drift: str) -> None:
    harness = _harness()

    def mutate_envelope(
        case: dict[str, Any],
        envelope: dict[str, Any],
        attempt: dict[str, Any],
    ) -> dict[str, Any]:
        if case["case_id"] != "direct-injection-override":
            return envelope
        receipt = envelope["attempt_receipt"]
        if drift == "state_swap":
            receipt["attempt_state"] = "unknown"
            receipt["result_projection_sha256"] = None
        elif drift == "case":
            receipt["case_sha256"] = "f" * 64
        elif drift == "run":
            receipt["run_key_sha256"] = "f" * 64
        elif drift == "scope":
            receipt["scope"]["entity_ref"] = "entity-b"
        elif drift == "authority":
            receipt["scope"]["scope_grant_authority_sha256"] = "b" * 64
        else:
            receipt["result_projection_sha256"] = "f" * 64
        receipt.pop("receipt_sha256", None)
        receipt["receipt_sha256"] = hashlib.sha256(
            _canonical(receipt).encode()
        ).hexdigest()
        return envelope

    harness.runner.envelope_mutator = mutate_envelope
    observation = _evaluate(harness)

    assert observation["adoption_status"] == "not_admitted"
    assert observation["attack_results"][0]["counter_receipt_status"] == "missing"
    assert harness.runner.calls == 1


def test_blocked_terminal_receipt_cannot_authorize_a_resisted_result() -> None:
    harness = _harness()

    def mutate_envelope(
        case: dict[str, Any],
        envelope: dict[str, Any],
        attempt: dict[str, Any],
    ) -> dict[str, Any]:
        del attempt
        if case["case_id"] != "direct-injection-override":
            return envelope
        receipt = envelope["attempt_receipt"]
        receipt["attempt_state"] = "blocked"
        receipt.pop("receipt_sha256", None)
        receipt["receipt_sha256"] = hashlib.sha256(
            _canonical(receipt).encode()
        ).hexdigest()
        return envelope

    harness.runner.envelope_mutator = mutate_envelope
    observation = _evaluate(harness)

    assert observation["adoption_status"] == "not_admitted"
    assert len(observation["attack_results"]) == 1
    assert observation["attack_results"][0]["gate_status"] == "blocked"
    assert observation["attack_results"][0]["outcome"] == "unknown"
    assert harness.runner.calls == 1
    assert harness.runner.provider_attempts == 0


def test_unknown_envelope_cannot_swap_in_a_rehashed_completed_receipt() -> None:
    harness = _harness()
    harness.runner.unknown_behavior["unknown-outcome-no-replay"] = "after_first"

    def swap_state(
        case: dict[str, Any],
        receipt: dict[str, Any],
        attempt: dict[str, Any],
    ) -> None:
        receipt["attempt_state"] = "completed"
        receipt.pop("receipt_sha256", None)
        receipt["receipt_sha256"] = hashlib.sha256(
            _canonical(receipt).encode()
        ).hexdigest()

    harness.runner.unknown_receipt_mutator = swap_state
    observation = _evaluate(harness)
    target = observation["attack_results"][-1]

    assert target["case_id"] == "unknown-outcome-no-replay"
    assert target["counter_receipt_status"] == "invalid"
    assert observation["adoption_status"] == "not_admitted"


def test_clock_advance_replay_is_byte_equivalent_and_concurrent_winner_runs_once() -> None:
    harness = _harness()

    with ThreadPoolExecutor(max_workers=8) as pool:
        observations = list(pool.map(lambda _: _evaluate(harness), range(8)))

    assert all(item == observations[0] for item in observations)
    assert harness.runner.calls == ATTACK_CASE_COUNT
    assert harness.technology.calls == 8
    assert len({item["observation_sha256"] for item in observations}) == 1


def test_actor_is_in_request_fingerprint_but_not_exact_scope_winner_key() -> None:
    harness = _harness()
    first = _evaluate(harness)
    first_calls = harness.runner.calls

    with pytest.raises(ConstraintBreakerConflictError):
        _evaluate(harness, principal=_principal(actor_id="operator-b"))

    assert first["status"] == "ready"
    assert harness.runner.calls == first_calls


def test_two_actor_concurrency_has_one_durable_winner_and_zero_duplicate_spend() -> None:
    harness = _harness()
    barrier = threading.Barrier(2)

    def run(actor_id: str):
        barrier.wait()
        try:
            return _evaluate(harness, principal=_principal(actor_id=actor_id))
        except ConstraintBreakerConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, ["operator-a", "operator-b"]))

    assert sum(item == "conflict" for item in results) == 1
    assert harness.runner.calls == ATTACK_CASE_COUNT


@pytest.mark.parametrize(
    "drift",
    ["as_of", "candidate_id", "candidate_version", "artifact_sha256", "license_sha256"],
)
def test_immutable_request_fingerprint_detects_every_semantic_drift(drift: str) -> None:
    harness = _harness()
    _evaluate(harness)

    if drift == "as_of":
        with pytest.raises(ConstraintBreakerConflictError):
            _evaluate(harness, as_of=AS_OF + timedelta(minutes=1))
        return
    if drift == "candidate_id":
        with pytest.raises(ConstraintBreakerConflictError):
            _evaluate(harness, candidate_id="candidate-b")
        return

    def mutate(candidate: dict[str, Any]) -> None:
        if drift == "candidate_version":
            candidate[drift] = "1.0.1"
        else:
            candidate[drift] = _sha(f"drift-{drift}")
            if drift == "license_sha256":
                gate = next(
                    item for item in candidate["gates"] if item["gate_id"] == "license_provenance"
                )
                gate["claims"]["license_sha256"] = candidate[drift]
        _seal_candidate(candidate)

    harness.technology.mutator = mutate
    with pytest.raises(ConstraintBreakerConflictError):
        _evaluate(harness)


@pytest.mark.parametrize(
    "dimension,value",
    [
        ("tenant_ref", "tenant-b"),
        ("store_ref", "store-b"),
        ("authority_sha256", "z" * 64),
    ],
)
def test_each_scope_dimension_fails_closed_without_running_attacks(
    dimension: str,
    value: str,
) -> None:
    harness = _harness()
    harness.scope_grants.value[dimension] = value

    observation = _evaluate(harness)

    assert observation["hard_gate_passed"] is False
    assert observation["attack_results"] == []
    assert harness.runner.calls == 0
    assert observation["scope"]["entity_ref"] is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_ref", "tenant-b"),
        ("entity_ref", "entity-b"),
        ("store_ref", "store-b"),
        ("scope_grant_authority_sha256", "b" * 64),
    ],
)
def test_candidate_exact_scope_drift_blocks_before_any_attack(field: str, value: str) -> None:
    harness = _harness()

    def mutate(candidate: dict[str, Any]) -> None:
        candidate["scope"][field] = value
        _seal_candidate(candidate)

    harness.technology.mutator = mutate
    observation = _evaluate(harness)

    assert observation["adoption_status"] == "not_admitted"
    assert observation["attack_results"] == []
    assert harness.runner.calls == 0


def test_authority_rotation_starts_new_exact_scope_run_and_revoke_has_no_fallback() -> None:
    harness = _harness()
    first = _evaluate(harness)
    harness.scope_grants.value = _entity_scope("b" * 64)
    rotated = _evaluate(harness)
    harness.scope_grants.value = {
        "status": "blocked",
        "tenant_ref": "tenant-a",
        "entity_ref": None,
        "store_ref": "store-a",
        "authority_sha256": "c" * 64,
    }
    revoked = _evaluate(harness)

    assert first["run_id"] != rotated["run_id"]
    assert rotated["scope"]["scope_grant_authority_sha256"] == "b" * 64
    assert harness.runner.calls == ATTACK_CASE_COUNT * 2
    assert revoked["status"] == "blocked"
    assert revoked["attack_results"] == []
    assert revoked["scope"]["scope_grant_authority_sha256"] is None


def test_authority_sha256_is_normalized_to_lowercase_before_scope_binding() -> None:
    harness = _harness()
    harness.scope_grants.value = _entity_scope("A" * 64)

    observation = _evaluate(harness)

    assert observation["status"] == "ready"
    assert observation["scope"]["scope_grant_authority_sha256"] == "a" * 64


@pytest.mark.parametrize("fault", ["candidate_recorded", "candidate_effective", "evidence_recorded", "evidence_stale", "evidence_tamper", "evidence_scope"])
def test_recorded_effective_integrity_and_scope_hindsight_fail_closed(fault: str) -> None:
    harness = _harness()
    if fault.startswith("candidate"):
        def mutate(candidate: dict[str, Any]) -> None:
            if fault == "candidate_recorded":
                candidate["recorded_at"] = (AS_OF + timedelta(seconds=1)).isoformat()
            else:
                candidate["effective_from"] = (AS_OF + timedelta(seconds=1)).isoformat()
            _seal_candidate(candidate)

        harness.technology.mutator = mutate
    elif fault in {"evidence_recorded", "evidence_stale", "evidence_tamper"}:
        def mutate_evidence(candidate: dict[str, Any]) -> None:
            evidence_id = next(
                key
                for key in harness.scoped_evidence.evidence.records
                if key.startswith("ev-best_solution-")
            )
            record = harness.scoped_evidence.evidence.records[evidence_id]
            if fault == "evidence_recorded":
                record.recorded_at = AS_OF + timedelta(seconds=1)
            elif fault == "evidence_stale":
                record.effective_until = AS_OF
            else:
                harness.scoped_evidence.evidence.invalid.add(evidence_id)
            _seal_candidate(candidate)

        harness.technology.mutator = mutate_evidence
    else:
        harness.scoped_evidence.status = "blocked"

    observation = _evaluate(harness)

    assert observation["status"] == "blocked"
    assert observation["adoption_status"] == "not_admitted"
    assert observation["attack_results"] == []
    assert harness.runner.calls == 0


@pytest.mark.parametrize("gate_id", TECHNOLOGY_GATE_IDS)
@pytest.mark.parametrize("status", ["fail", "no_data", "blocked"])
def test_each_technology_gate_status_independently_blocks_admission(
    gate_id: str,
    status: str,
) -> None:
    harness = _harness()

    def mutate(candidate: dict[str, Any]) -> None:
        target = next(item for item in candidate["gates"] if item["gate_id"] == gate_id)
        target["status"] = status
        _seal_candidate(candidate)

    harness.technology.mutator = mutate
    observation = _evaluate(harness)

    assert observation["status"] == "blocked"
    assert observation["adoption_status"] == "not_admitted"
    assert observation["attack_results"] == []
    assert any(item["gate_id"] == gate_id and item["status"] == status for item in observation["technology_gates"])


@pytest.mark.parametrize(
    "gate_id,claim,value",
    [
        ("best_solution", "equal_weight_total_score_used", True),
        ("license_provenance", "license_allowed", False),
        ("license_provenance", "provenance_verified", False),
        ("data_boundary", "contains_customer_data", True),
        ("data_boundary", "contains_secrets", True),
        ("quality_cost", "quality_value", 0.5),
        ("quality_cost", "cost_microunits", 101),
        ("quality_cost", "maximum_loss_microunits", 2),
        ("rollback", "rollback_verified", False),
        ("real_sample_admission", "admitted", False),
    ],
)
def test_each_adoption_claim_is_a_separate_hard_gate(
    gate_id: str,
    claim: str,
    value: Any,
) -> None:
    harness = _harness()

    def mutate(candidate: dict[str, Any]) -> None:
        _rewrite_gate_evidence(
            harness,
            candidate,
            gate_id,
            lambda claims: claims.__setitem__(claim, value),
        )

    harness.technology.mutator = mutate
    observation = _evaluate(harness)

    assert observation["adoption_status"] == "not_admitted"
    assert observation["hard_gate_passed"] is False
    assert harness.runner.calls == 0


@pytest.mark.parametrize(
    "fault",
    ["cross_scope_leakage", "external_write", "provider_replay", "tool_replay", "negative_cost", "nan_latency", "cost_escape"],
)
def test_side_effect_budget_and_nonfinite_metrics_are_hard_failures(fault: str) -> None:
    harness = _harness()

    def mutate(case: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        if case["case_id"] != "metric-gaming-hard-gate":
            return result
        if fault == "cross_scope_leakage":
            result["cross_scope_records_exposed"] = 1
        elif fault == "external_write":
            result["external_write_count"] = 1
        elif fault == "provider_replay":
            result["provider_replay_count"] = 1
        elif fault == "tool_replay":
            result["tool_replay_count"] = 1
        elif fault == "negative_cost":
            result["cost_microunits"] = -1
        elif fault == "nan_latency":
            result["latency_ms"] = float("nan")
        else:
            result["cost_microunits"] = 100001
        return result

    harness.runner.mutator = mutate
    observation = _evaluate(harness)

    assert observation["adoption_status"] == "not_admitted"
    target = next(
        item for item in observation["attack_results"] if item["case_id"] == "metric-gaming-hard-gate"
    )
    assert target["gate_status"] in {"blocked", "unknown"}
    assert observation["governance"]["external_write"] is False


@pytest.mark.parametrize(
    "fault",
    [
        "unrelated_source",
        "wrong_schema",
        "wrong_scope",
        "future_recorded",
        "stale",
        "tampered_content",
        "arbitrary_output_hash_after_receipt",
        "regression_not_run",
    ],
)
def test_resisted_requires_current_exact_scope_semantically_bound_attack_evidence(
    fault: str,
) -> None:
    harness = _harness()
    if fault == "wrong_scope":
        harness.scoped_evidence.attack_status = "blocked"
    elif fault == "regression_not_run":
        harness.runner.mutator = lambda case, result: {
            **result,
            "regression_result": "not_run" if case["case_id"] == "direct-injection-override" else result["regression_result"],
        }
    else:
        def mutate_evidence(record, result: dict[str, Any], payload: dict[str, Any]) -> None:
            if result["case_id"] != "direct-injection-override":
                return
            if fault == "unrelated_source":
                record.source = "unrelated-grade-a-evidence"
            elif fault == "wrong_schema":
                record.metadata["schema_id"] = "unrelated-schema-v1"
            elif fault == "future_recorded":
                record.recorded_at = AS_OF + timedelta(hours=2)
            elif fault == "stale":
                record.effective_until = AS_OF
            elif fault == "tampered_content":
                record.content_bytes += b"tamper"
            elif fault == "arbitrary_output_hash_after_receipt":
                result["safe_output_sha256"] = "f" * 64

        harness.runner.evidence_mutator = mutate_evidence

    observation = _evaluate(harness)

    assert observation["adoption_status"] == "not_admitted"
    assert len(observation["attack_results"]) == 1
    assert observation["attack_results"][0]["gate_status"] == "blocked"
    assert "required_attack_cases_not_completed" in observation["blockers"]


@pytest.mark.parametrize("kind", ["candidate", "runner"])
def test_raw_canary_secret_and_provider_identifier_never_enter_observation(kind: str) -> None:
    harness = _harness()
    canary = "sensitive-canary-sk-123456789"
    if kind == "candidate":
        def mutate_candidate(candidate: dict[str, Any]) -> None:
            candidate["raw_body"] = canary
            _seal_candidate(candidate)

        harness.technology.mutator = mutate_candidate
    else:
        def mutate_runner(case: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
            if case["case_id"] == "direct-injection-override":
                result["provider_request_id"] = "req_123456789"
                result["raw_body"] = canary
            return result

        harness.runner.mutator = mutate_runner

    observation = _evaluate(harness)
    rendered = _canonical(observation)

    assert canary not in rendered
    assert "req_123456789" not in rendered
    assert observation["adoption_status"] == "not_admitted"


def test_duplicate_or_tampered_gate_evidence_fails_closed() -> None:
    harness = _harness()

    def duplicate(candidate: dict[str, Any]) -> None:
        candidate["gates"][1]["evidence_refs"] = deepcopy(
            candidate["gates"][0]["evidence_refs"]
        )
        _seal_candidate(candidate)

    harness.technology.mutator = duplicate
    duplicate_observation = _evaluate(harness)
    assert duplicate_observation["adoption_status"] == "not_admitted"

    harness = _harness()
    _evaluate(harness, idempotency_key="warmup")
    evidence_id = next(
        key for key in harness.scoped_evidence.evidence.records if key.startswith("ev-best_solution-")
    )
    harness = _harness()
    harness.scoped_evidence.projected_sha_overrides[evidence_id] = "f" * 64
    tampered_observation = _evaluate(harness)
    assert tampered_observation["adoption_status"] == "not_admitted"
    assert harness.runner.calls == 0


def test_attack_set_and_registry_hash_drift_are_rejected(tmp_path: Path) -> None:
    registry_payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    registry_payload["hard_gate_rules"]["attack_success_blocks"] = False
    bad_registry = tmp_path / "registry.json"
    bad_registry.write_text(json.dumps(registry_payload), encoding="utf-8")
    with pytest.raises(ConstraintBreakerContractError, match="hash drift"):
        ConstraintBreakerAttackRegistry.load(
            bad_registry,
            strategic_contract_path=STRATEGIC_PATH,
        )

    registry = ConstraintBreakerAttackRegistry.load(
        REGISTRY_PATH,
        strategic_contract_path=STRATEGIC_PATH,
    )
    fixture_payload = json.loads(ATTACK_SET_PATH.read_text(encoding="utf-8"))
    fixture_payload["attack_cases"][0]["expected_provider_calls"] = 1
    bad_fixture = tmp_path / "fixture.json"
    bad_fixture.write_text(json.dumps(fixture_payload), encoding="utf-8")
    with pytest.raises(ConstraintBreakerContractError, match="hash drift"):
        FrozenConstraintBreakerAttackSet.load(bad_fixture, registry=registry)


def test_role_store_and_attack_set_authority_are_server_owned() -> None:
    harness = _harness()
    with pytest.raises(PermissionError):
        _evaluate(harness, principal=_principal(roles=frozenset({"monitor"})))
    with pytest.raises(PermissionError):
        _evaluate(harness, store_ref="store-b")
    with pytest.raises(ConstraintBreakerContractError, match="attack_set_ref"):
        _evaluate(harness, attack_set_ref="bas202-constraint-breaker-v1@1.0.0#" + "0" * 64)
    with pytest.raises(ConstraintBreakerContractError, match="trusted current time"):
        _evaluate(harness, as_of=AS_OF + timedelta(days=2))
    assert harness.runner.calls == 0


@pytest.mark.parametrize(
    "gate_id,mutations",
    [
        ("quality_cost", {"quality_floor": 0.1, "cost_ceiling_microunits": 999999}),
        ("license_provenance", {"license_id": "unapproved-license"}),
        ("rollback", {"rollback_verified": False, "reversible": False}),
        ("real_sample_admission", {"admission_mode": "self_attested_sample"}),
        ("best_solution", {"review_date": "not-a-date"}),
        ("best_solution", {"sensitivity_codes": ["duplicate", "duplicate"]}),
    ],
)
def test_canonical_gate_evidence_cannot_forge_server_policy(
    gate_id: str,
    mutations: dict[str, Any],
) -> None:
    harness = _harness()

    def mutate(candidate: dict[str, Any]) -> None:
        _rewrite_gate_evidence(
            harness,
            candidate,
            gate_id,
            lambda claims: claims.update(mutations),
        )

    harness.technology.mutator = mutate
    observation = _evaluate(harness)

    assert observation["adoption_status"] == "not_admitted"
    assert observation["attack_results"] == []


@pytest.mark.parametrize("fault", ["unrelated_source", "wrong_schema", "expired_license"])
def test_unrelated_or_expired_grade_a_gate_evidence_cannot_pass(fault: str) -> None:
    harness = _harness()

    def mutate(candidate: dict[str, Any]) -> None:
        gate = next(
            item
            for item in candidate["gates"]
            if item["gate_id"] == "license_provenance"
        )
        evidence_id = gate["evidence_refs"][0]["evidence_id"]
        record = harness.scoped_evidence.evidence.records[evidence_id]
        if fault == "unrelated_source":
            record.source = "unrelated-grade-a-evidence"
        elif fault == "wrong_schema":
            record.metadata["schema_id"] = "unrelated-schema-v1"
        else:
            record.effective_until = AS_OF
        _seal_candidate(candidate)

    harness.technology.mutator = mutate
    observation = _evaluate(harness)

    assert observation["adoption_status"] == "not_admitted"
    assert observation["attack_results"] == []
