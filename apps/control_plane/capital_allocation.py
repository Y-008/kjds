from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import threading
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from .security import Principal

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,159}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_SENSITIVE = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|"
    r"authorization\s*:\s*bearer|private[_-]?key|provider[_-]?request[_-]?id|"
    r"raw[_-]?(?:prompt|document|customer|payload))"
)
_EMAIL = re.compile(r"(?i)(?<![\w.+-])[\w.+-]+@[\w.-]+\.[a-z]{2,}(?![\w.-])")

_REGISTRY_FIELDS = {
    "schema_version",
    "contract_id",
    "version",
    "read_bundle_contract_id",
    "citation_authority_contract_id",
    "allowed_states",
    "required_options",
    "hard_elimination_dimensions",
    "comparison_dimensions",
    "required_proposal_fields",
    "authority_gate_ids",
    "source_contracts",
    "zero_authority_flags",
    "content_sha256",
}
_FIXTURE_FIELDS = {
    "contract_id",
    "fixture_id",
    "version",
    "registry_sha256",
    "license_class",
    "data_classification",
    "portfolio_ref",
    "scope",
    "data_as_of",
    "source_bindings",
    "option_specs",
    "policy",
    "content_sha256",
}
_SOURCE_CONTRACT_FIELDS = {
    "source_id",
    "contract_id",
    "version",
    "evidence_source",
    "minimum_grade",
    "contract_sha256",
}
_SOURCE_BINDING_FIELDS = {
    "source_id",
    "contract_id",
    "contract_version",
    "source_ref",
    "scope",
    "data_as_of",
    "synthetic_payload",
    "evidence_binding",
}
_EVIDENCE_BINDING_FIELDS = {
    "citation_ref",
    "evidence_id",
    "evidence_sha256",
    "claims_sha256",
    "source",
    "source_ref",
    "recorded_at",
    "effective_at",
    "effective_until",
}
_OPTION_FIELDS = {
    "option_id",
    "option_type",
    "opportunity_ref",
    "budget_request",
    "maximum_loss",
    "downside_cm3",
    "base_cm3",
    "upside_cm3",
    "timebox_days",
    "payback_days",
    "dependency_refs",
    "owner_ref",
    "primary_metric",
    "guardrails",
    "stop_conditions",
    "rollback_ref",
    "invalidation_conditions",
    "review_date",
    "no_action_comparison",
    "comparison_values",
    "option_sha256",
}
_COMPARISON_VALUE_FIELDS = {
    "long_term_risk_adjusted_value",
    "total_cost_of_ownership",
    "time_to_value_days",
    "operational_fit_basis_points",
    "maintainability_basis_points",
    "reversibility_basis_points",
    "replacement_cost",
}
_OPTION_MONEY_FIELDS = {
    "budget_request",
    "maximum_loss",
    "downside_cm3",
    "base_cm3",
    "upside_cm3",
}
_COMPARISON_MONEY_FIELDS = {
    "long_term_risk_adjusted_value",
    "total_cost_of_ownership",
    "replacement_cost",
}
_POLICY_FIELDS = {
    "currency",
    "minimum_runway_days",
    "maximum_timebox_days",
    "maximum_payback_days",
    "minimum_downside_cm3",
    "required_evidence_coverage_basis_points",
    "synthetic_fixture_proves_real_finance",
}
_SCOPE_FIELDS = {
    "tenant_ref",
    "entity_ref",
    "store_ref",
    "scope_grant_authority_sha256",
}
_BUNDLE_FIELDS = {
    "contract_id",
    "portfolio_ref",
    "allocation_contract_ref",
    "scope",
    "as_of",
    "projections",
    "bundle_sha256",
}
_PROJECTION_FIELDS = {
    "source_id",
    "contract_id",
    "contract_version",
    "source_ref",
    "status",
    "scope",
    "as_of",
    "payload",
    "evidence_binding",
    "projection_sha256",
}
_CITATION_RECEIPT_FIELDS = {
    "contract_id",
    "status",
    "citation_ref",
    "evidence_id",
    "evidence_sha256",
    "claims_sha256",
    "source",
    "source_ref",
    "source_contract_id",
    "source_contract_version",
    "source_contract_sha256",
    "scope",
    "recorded_at",
    "effective_at",
    "effective_until",
    "integrity_status",
    "current",
    "grade",
}
_MONEY_FIELDS = {
    "amount_microunits",
    "currency",
    "occurred_at",
    "effective_at",
    "evidence_ref",
    "evidence_sha256",
}
_PROJECTION_PAYLOAD_FIELDS = {
    "gap_graph": {
        "portfolio_ref",
        "portfolio_status",
        "opportunity_refs",
        "dependency_edges",
        "rollback_refs",
    },
    "strategic_benchmark": {
        "best_solution_profile_ref",
        "hard_elimination_dimensions",
        "comparison_dimensions",
        "equal_weight_total_score_allowed",
        "security_status",
        "privacy_status",
        "legal_and_license_status",
    },
    "capital_constraints": {
        "cash_floor",
        "treasury_cash_balance",
        "budget_cap",
        "maximum_loss_limit",
        "runway_days",
        "board_approved_current",
        "signed_thresholds_current",
        "thresholds_ref",
        "evidence_coverage_basis_points",
    },
    "profit_truth": {
        "actual_cash_cm3",
        "downside_cm3",
        "signed_profit_threshold_current",
        "profit_threshold_ref",
        "treasury_cash_authority",
    },
    "settlement_cash": {
        "settled_cash",
        "unsettled_included",
        "cash_status",
        "treasury_cash_authority",
    },
    "growth_outcome": {
        "acceptance_evidence_current",
        "causal_authority_status",
        "outcome_ref",
        "primary_metric_ref",
    },
    "commercial_lifecycle": {
        "settled_only",
        "entitlement_current",
        "c0_status",
        "external_blockers",
        "outstanding_total",
        "treasury_cash_authority",
    },
}
_MONEY_FIELDS_BY_SOURCE = {
    "capital_constraints": {
        "treasury_cash_balance",
        "cash_floor",
        "budget_cap",
        "maximum_loss_limit",
    },
    "profit_truth": {"actual_cash_cm3", "downside_cm3"},
    "settlement_cash": {"settled_cash"},
    "commercial_lifecycle": {"outstanding_total"},
}
_GRADE_ORDER = {"UNKNOWN": 0, "D": 1, "C": 2, "B": 3, "A": 4}


class CapitalAllocationContractError(ValueError):
    pass


class CapitalAllocationConflictError(RuntimeError):
    pass


class CapitalAllocationReadAuthority(Protocol):
    def read_bundle(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        portfolio_ref: str,
        allocation_contract_ref: str,
        source_bindings: list[dict[str, Any]],
    ) -> dict[str, Any]: ...


class CapitalAllocationCitationAuthority(Protocol):
    def verify_citation(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        data_as_of: datetime,
        authority_checked_at: datetime,
        citation_ref: str,
        evidence_sha256: str,
        claims_sha256: str,
        source_contract_id: str,
        source_contract_version: str,
    ) -> dict[str, Any]: ...


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return _timestamp(value, field="datetime").isoformat()
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            _json_value(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CapitalAllocationContractError("value is not canonical JSON") from exc


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _sha256(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise CapitalAllocationContractError(f"{field} must be a lowercase SHA-256")
    text = value.strip().lower()
    if not _HEX64.fullmatch(text):
        raise CapitalAllocationContractError(f"{field} must be a lowercase SHA-256")
    return text


def _token(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise CapitalAllocationContractError(f"{field} must be a safe token")
    text = value.strip()
    if not _TOKEN.fullmatch(text):
        raise CapitalAllocationContractError(f"{field} must be a safe token")
    return text


def _timestamp(value: Any, *, field: str) -> datetime:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise CapitalAllocationContractError(f"{field} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise CapitalAllocationContractError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def _exact_fields(value: Any, expected: set[str], *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise CapitalAllocationContractError(f"{field} fields do not match contract")
    return value


def _strict_int(
    value: Any,
    *,
    field: str,
    minimum: int = 0,
    maximum: int = 10**18,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CapitalAllocationContractError(f"{field} must be an integer")
    if value < minimum or value > maximum:
        raise CapitalAllocationContractError(f"{field} is outside admitted bounds")
    return value


def _money_contract(raw: Any, *, field: str, cutoff: datetime) -> dict[str, Any]:
    money = _exact_fields(raw, _MONEY_FIELDS, field=field)
    _strict_int(money["amount_microunits"], field=f"{field}.amount_microunits")
    if not isinstance(money["currency"], str) or not _CURRENCY.fullmatch(
        money["currency"]
    ):
        raise CapitalAllocationContractError(f"{field}.currency is invalid")
    occurred = _timestamp(money["occurred_at"], field=f"{field}.occurred_at")
    effective = _timestamp(money["effective_at"], field=f"{field}.effective_at")
    if occurred > cutoff or effective > cutoff:
        raise CapitalAllocationContractError(f"{field} contains hindsight")
    _token(money["evidence_ref"], field=f"{field}.evidence_ref")
    _sha256(money["evidence_sha256"], field=f"{field}.evidence_sha256")
    return money


def _unique_tokens(value: Any, *, field: str, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise CapitalAllocationContractError(f"{field} must be a list")
    tokens = [_token(item, field=field) for item in value]
    if len(tokens) != len(set(tokens)):
        raise CapitalAllocationContractError(f"{field} contains duplicates")
    return tokens


def _scope(value: Any, *, field: str) -> dict[str, str]:
    raw = _exact_fields(value, _SCOPE_FIELDS, field=field)
    return {
        "tenant_ref": _token(raw["tenant_ref"], field=f"{field}.tenant_ref"),
        "entity_ref": _token(raw["entity_ref"], field=f"{field}.entity_ref"),
        "store_ref": _token(raw["store_ref"], field=f"{field}.store_ref"),
        "scope_grant_authority_sha256": _sha256(
            raw["scope_grant_authority_sha256"],
            field=f"{field}.scope_grant_authority_sha256",
        ),
    }


def _safe_projection(value: Any, *, path: str = "projection", depth: int = 0) -> None:
    if depth > 12:
        raise CapitalAllocationContractError(f"{path} exceeds nesting limit")
    if isinstance(value, dict):
        if len(value) > 100:
            raise CapitalAllocationContractError(f"{path} exceeds object limit")
        for key, item in value.items():
            _token(key, field=f"{path}.key")
            if _SENSITIVE.search(key) or _EMAIL.search(key):
                raise CapitalAllocationContractError(f"{path}.key contains prohibited data")
            _safe_projection(item, path=f"{path}.{key}", depth=depth + 1)
        return
    if isinstance(value, list):
        if len(value) > 200:
            raise CapitalAllocationContractError(f"{path} exceeds list limit")
        for index, item in enumerate(value):
            _safe_projection(item, path=f"{path}[{index}]", depth=depth + 1)
        return
    if isinstance(value, str):
        if len(value) > 200 or _SENSITIVE.search(value) or _EMAIL.search(value):
            raise CapitalAllocationContractError(f"{path} contains prohibited data")
        return
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, int) and not isinstance(value, bool):
        _strict_int(value, field=path, minimum=-(10**18), maximum=10**18)
        return
    if isinstance(value, float) and math.isfinite(value):
        return
    raise CapitalAllocationContractError(f"{path} contains an unsupported value")


class CapitalAllocationContractRegistry:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.content_sha256 = payload["content_sha256"]
        self.source_contracts = {
            item["source_id"]: item for item in payload["source_contracts"]
        }

    @property
    def ref(self) -> str:
        return (
            f"{self.payload['contract_id']}:{self.payload['version']}:"
            f"{self.content_sha256}"
        )

    @classmethod
    def load(cls, path: str | Path) -> CapitalAllocationContractRegistry:
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CapitalAllocationContractError(
                "capital allocation registry is unreadable"
            ) from exc
        _exact_fields(payload, _REGISTRY_FIELDS, field="registry")
        expected_sha = _hash(
            {key: value for key, value in payload.items() if key != "content_sha256"}
        )
        if not hmac.compare_digest(
            _sha256(payload["content_sha256"], field="registry.content_sha256"),
            expected_sha,
        ):
            raise CapitalAllocationContractError("capital allocation registry hash drift")
        if payload["schema_version"] != "kjds-capital-allocation-contracts-v1":
            raise CapitalAllocationContractError("unknown capital allocation schema")
        if payload["contract_id"] != "kjds-capital-allocation-observation-v1":
            raise CapitalAllocationContractError("unknown capital allocation contract")
        if payload["read_bundle_contract_id"] != "kjds-capital-allocation-read-bundle-v1":
            raise CapitalAllocationContractError("unknown read bundle contract")
        if (
            payload["citation_authority_contract_id"]
            != "kjds-capital-allocation-citation-authority-v1"
        ):
            raise CapitalAllocationContractError("unknown citation authority contract")
        if set(payload["allowed_states"]) != {
            "ready",
            "no_data",
            "UNKNOWN",
            "blocked",
            "not_visible",
            "stale",
        }:
            raise CapitalAllocationContractError("capital allocation states are not frozen")
        if payload["required_options"] != [
            "build",
            "buy",
            "partner",
            "defer",
            "no_action",
        ]:
            raise CapitalAllocationContractError("five-option matrix is not frozen")
        if set(payload["hard_elimination_dimensions"]) != {
            "evidence",
            "authority",
            "security",
            "privacy",
            "legal_and_license",
            "cash_floor",
            "maximum_loss",
            "rollback",
            "acceptance",
        }:
            raise CapitalAllocationContractError("hard elimination dimensions drift")
        if payload["comparison_dimensions"] != [
            "long_term_risk_adjusted_value",
            "total_cost_of_ownership",
            "time_to_value",
            "operational_fit",
            "maintainability",
            "reversibility",
            "replacement_cost",
        ]:
            raise CapitalAllocationContractError("comparison dimensions drift")
        if "no_action_comparison" not in payload["required_proposal_fields"]:
            raise CapitalAllocationContractError("no_action comparison is required")
        _unique_tokens(payload["required_proposal_fields"], field="required_proposal_fields")
        _unique_tokens(payload["authority_gate_ids"], field="authority_gate_ids")
        cls._validate_sources(payload)
        cls._validate_zero_authority(payload)
        _safe_projection(payload, path="registry")
        return cls(payload)

    @staticmethod
    def _validate_sources(payload: dict[str, Any]) -> None:
        sources = payload["source_contracts"]
        if not isinstance(sources, list) or len(sources) != 7:
            raise CapitalAllocationContractError("seven read source contracts are required")
        expected_ids = set(_PROJECTION_PAYLOAD_FIELDS)
        found: set[str] = set()
        for raw in sources:
            source = _exact_fields(raw, _SOURCE_CONTRACT_FIELDS, field="source_contract")
            source_id = _token(source["source_id"], field="source_id")
            if source_id in found:
                raise CapitalAllocationContractError("duplicate source contract")
            found.add(source_id)
            _token(source["contract_id"], field="source.contract_id")
            _token(source["version"], field="source.version")
            _token(source["evidence_source"], field="source.evidence_source")
            if source["minimum_grade"] not in {"A", "B"}:
                raise CapitalAllocationContractError("source minimum grade is invalid")
            expected = _hash(
                {
                    "source_id": source_id,
                    "contract_id": source["contract_id"],
                    "version": source["version"],
                    "evidence_source": source["evidence_source"],
                    "minimum_grade": source["minimum_grade"],
                }
            )
            if not hmac.compare_digest(
                _sha256(source["contract_sha256"], field="source.contract_sha256"),
                expected,
            ):
                raise CapitalAllocationContractError("source contract hash drift")
        if found != expected_ids:
            raise CapitalAllocationContractError("source contract set drift")

    @staticmethod
    def _validate_zero_authority(payload: dict[str, Any]) -> None:
        expected = {
            "proposal_only": True,
            "self_approval": False,
            "payment": False,
            "securities_investment": False,
            "fact_write": False,
            "finance_entry_write": False,
            "approval_write": False,
            "permit_write": False,
            "pilot_write": False,
            "outbox_write": False,
            "canonical_graph_write": False,
            "network_write": False,
            "external_write": False,
        }
        if payload["zero_authority_flags"] != expected:
            raise CapitalAllocationContractError("zero-authority flags drift")


class FrozenCapitalAllocationFixture:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.content_sha256 = payload["content_sha256"]

    @property
    def ref(self) -> str:
        return (
            f"{self.payload['fixture_id']}:{self.payload['version']}:"
            f"{self.content_sha256}"
        )

    @classmethod
    def load(
        cls,
        path: str | Path,
        *,
        registry: CapitalAllocationContractRegistry,
    ) -> FrozenCapitalAllocationFixture:
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CapitalAllocationContractError(
                "capital allocation fixture is unreadable"
            ) from exc
        _exact_fields(payload, _FIXTURE_FIELDS, field="fixture")
        if payload["contract_id"] != "kjds-capital-allocation-synthetic-fixture-v1":
            raise CapitalAllocationContractError("unknown capital allocation fixture")
        if payload["registry_sha256"] != registry.content_sha256:
            raise CapitalAllocationContractError("fixture registry binding drift")
        if payload["license_class"] != "repository_owned_synthetic_contract_fixture":
            raise CapitalAllocationContractError("fixture license is not admitted")
        if payload["data_classification"] != "synthetic_public":
            raise CapitalAllocationContractError("fixture data classification drift")
        expected_sha = _hash(
            {key: value for key, value in payload.items() if key != "content_sha256"}
        )
        if not hmac.compare_digest(
            _sha256(payload["content_sha256"], field="fixture.content_sha256"),
            expected_sha,
        ):
            raise CapitalAllocationContractError("fixture content hash drift")
        _token(payload["portfolio_ref"], field="fixture.portfolio_ref")
        scope = _scope(payload["scope"], field="fixture.scope")
        data_as_of = _timestamp(payload["data_as_of"], field="fixture.data_as_of")
        cls._validate_policy(payload["policy"], data_as_of=data_as_of)
        cls._validate_bindings(
            payload["source_bindings"],
            registry=registry,
            scope=scope,
            data_as_of=data_as_of,
        )
        review_deadline = min(
            _timestamp(
                item["evidence_binding"]["effective_until"],
                field="source_binding.effective_until",
            )
            for item in payload["source_bindings"]
        )
        cls._validate_options(
            payload["option_specs"],
            registry=registry,
            data_as_of=data_as_of,
            review_deadline=review_deadline,
            expected_currency=payload["policy"]["currency"],
        )
        _safe_projection(payload, path="fixture")
        return cls(payload)

    @staticmethod
    def _validate_policy(raw: Any, *, data_as_of: datetime) -> None:
        policy = _exact_fields(raw, _POLICY_FIELDS, field="policy")
        if not isinstance(policy["currency"], str) or not _CURRENCY.fullmatch(
            policy["currency"]
        ):
            raise CapitalAllocationContractError("policy currency is invalid")
        for field in (
            "minimum_runway_days",
            "maximum_timebox_days",
            "maximum_payback_days",
            "required_evidence_coverage_basis_points",
        ):
            _strict_int(policy[field], field=f"policy.{field}")
        minimum_downside = _money_contract(
            policy["minimum_downside_cm3"],
            field="policy.minimum_downside_cm3",
            cutoff=data_as_of,
        )
        if minimum_downside["currency"] != policy["currency"]:
            raise CapitalAllocationContractError("policy money currency drift")
        if policy["required_evidence_coverage_basis_points"] > 10_000:
            raise CapitalAllocationContractError("evidence coverage exceeds 100 percent")
        if policy["synthetic_fixture_proves_real_finance"] is not False:
            raise CapitalAllocationContractError("synthetic fixture cannot prove finance")

    @staticmethod
    def _validate_bindings(
        raw: Any,
        *,
        registry: CapitalAllocationContractRegistry,
        scope: dict[str, str],
        data_as_of: datetime,
    ) -> None:
        if not isinstance(raw, list) or len(raw) != len(registry.source_contracts):
            raise CapitalAllocationContractError("source binding conservation failed")
        found: set[str] = set()
        for item in raw:
            binding = _exact_fields(item, _SOURCE_BINDING_FIELDS, field="source_binding")
            source_id = _token(binding["source_id"], field="source_binding.source_id")
            contract = registry.source_contracts.get(source_id)
            if contract is None or source_id in found:
                raise CapitalAllocationContractError("source binding identity drift")
            found.add(source_id)
            if (
                binding["contract_id"] != contract["contract_id"]
                or binding["contract_version"] != contract["version"]
            ):
                raise CapitalAllocationContractError("source binding contract drift")
            _token(binding["source_ref"], field="source_binding.source_ref")
            if _scope(binding["scope"], field="source_binding.scope") != scope:
                raise CapitalAllocationContractError("source binding scope drift")
            if _timestamp(binding["data_as_of"], field="source_binding.data_as_of") != data_as_of:
                raise CapitalAllocationContractError("source binding as_of drift")
            evidence = _exact_fields(
                binding["evidence_binding"],
                _EVIDENCE_BINDING_FIELDS,
                field="source_binding.evidence",
            )
            FrozenCapitalAllocationFixture._validate_evidence_binding(evidence)
            if evidence["source"] != contract["evidence_source"]:
                raise CapitalAllocationContractError("source Evidence authority drift")
            _safe_projection(
                binding["synthetic_payload"],
                path=f"source_binding.{source_id}.synthetic_payload",
            )
            if evidence["claims_sha256"] != _hash(binding["synthetic_payload"]):
                raise CapitalAllocationContractError(
                    "source synthetic payload Evidence binding drift"
                )
        if found != set(registry.source_contracts):
            raise CapitalAllocationContractError("source binding set drift")

    @staticmethod
    def _validate_evidence_binding(binding: dict[str, Any]) -> None:
        for field in ("citation_ref", "evidence_id", "source", "source_ref"):
            _token(binding[field], field=f"evidence.{field}")
        for field in ("evidence_sha256", "claims_sha256"):
            _sha256(binding[field], field=f"evidence.{field}")
        recorded = _timestamp(binding["recorded_at"], field="evidence.recorded_at")
        effective = _timestamp(binding["effective_at"], field="evidence.effective_at")
        until = _timestamp(binding["effective_until"], field="evidence.effective_until")
        if effective > recorded or recorded >= until:
            raise CapitalAllocationContractError("Evidence chronology is invalid")

    @staticmethod
    def _validate_options(
        raw: Any,
        *,
        registry: CapitalAllocationContractRegistry,
        data_as_of: datetime,
        review_deadline: datetime,
        expected_currency: str,
    ) -> None:
        if not isinstance(raw, list) or len(raw) != 5:
            raise CapitalAllocationContractError("exactly five option specs are required")
        found_ids: set[str] = set()
        found_types: list[str] = []
        graph: dict[str, list[str]] = {}
        for value in raw:
            option = _exact_fields(value, _OPTION_FIELDS, field="option")
            option_id = _token(option["option_id"], field="option.option_id")
            if option_id in found_ids:
                raise CapitalAllocationContractError("duplicate option id")
            found_ids.add(option_id)
            option_type = _token(option["option_type"], field="option.option_type")
            found_types.append(option_type)
            _token(option["opportunity_ref"], field="option.opportunity_ref")
            for field in _OPTION_MONEY_FIELDS:
                money = _money_contract(
                    option[field], field=f"option.{field}", cutoff=data_as_of
                )
                if money["currency"] != expected_currency:
                    raise CapitalAllocationContractError("option money currency drift")
            for field in ("timebox_days", "payback_days"):
                _strict_int(option[field], field=f"option.{field}")
            dependencies = _unique_tokens(
                option["dependency_refs"], field="option.dependency_refs", allow_empty=True
            )
            if option_type == "no_action" and dependencies:
                raise CapitalAllocationContractError("no_action cannot have dependencies")
            graph[option_id] = dependencies
            for field in (
                "owner_ref",
                "primary_metric",
                "rollback_ref",
                "no_action_comparison",
            ):
                _token(option[field], field=f"option.{field}")
            for field in ("guardrails", "stop_conditions", "invalidation_conditions"):
                _unique_tokens(option[field], field=f"option.{field}")
            review_date = _timestamp(option["review_date"], field="option.review_date")
            if review_date <= data_as_of:
                raise CapitalAllocationContractError(
                    "option review date must be after data_as_of"
                )
            if review_date > review_deadline:
                raise CapitalAllocationContractError(
                    "option review date exceeds current Evidence interval"
                )
            values = _exact_fields(
                option["comparison_values"],
                _COMPARISON_VALUE_FIELDS,
                field="comparison_values",
            )
            for field, item in values.items():
                if field in _COMPARISON_MONEY_FIELDS:
                    money = _money_contract(
                        item,
                        field=f"comparison_values.{field}",
                        cutoff=data_as_of,
                    )
                    if money["currency"] != expected_currency:
                        raise CapitalAllocationContractError(
                            "comparison money currency drift"
                        )
                else:
                    maximum = 10_000 if field.endswith("basis_points") else 10**18
                    _strict_int(
                        item, field=f"comparison_values.{field}", maximum=maximum
                    )
            expected_sha = _hash(
                {key: item for key, item in option.items() if key != "option_sha256"}
            )
            if not hmac.compare_digest(
                _sha256(option["option_sha256"], field="option.option_sha256"),
                expected_sha,
            ):
                raise CapitalAllocationContractError("option hash drift")
        if found_types != registry.payload["required_options"]:
            raise CapitalAllocationContractError("option type order or set drift")
        for option_id, dependencies in graph.items():
            if any(item not in found_ids or item == option_id for item in dependencies):
                raise CapitalAllocationContractError("option dependency is orphaned")
        FrozenCapitalAllocationFixture._require_acyclic(graph)

    @staticmethod
    def _require_acyclic(graph: dict[str, list[str]]) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> None:
            if node in visiting:
                raise CapitalAllocationContractError("option dependency cycle detected")
            if node in visited:
                return
            visiting.add(node)
            for dependency in graph[node]:
                visit(dependency)
            visiting.remove(node)
            visited.add(node)

        for node in graph:
            visit(node)


class GovernedCapitalAllocationWorkspace:
    """Read-only capital allocation proposal boundary with zero execution authority."""

    CONTRACT_ID = "kjds-capital-allocation-observation-v1"

    def __init__(
        self,
        *,
        scope_grants,
        read_authority: CapitalAllocationReadAuthority,
        citation_authority: CapitalAllocationCitationAuthority,
        registry_path: str | Path,
        fixture_path: str | Path,
        clock=None,
    ) -> None:
        self.scope_grants = scope_grants
        self.read_authority = read_authority
        self.citation_authority = citation_authority
        self.clock = clock or (lambda: datetime.now(UTC))
        self.registry = CapitalAllocationContractRegistry.load(registry_path)
        self.fixture = FrozenCapitalAllocationFixture.load(
            fixture_path, registry=self.registry
        )
        self._lock = threading.RLock()
        self._runs: dict[
            tuple[str, str, str, str, str], tuple[str, dict[str, Any]]
        ] = {}

    @property
    def allocation_contract_ref(self) -> str:
        return self.fixture.ref

    def evaluate(
        self,
        *,
        principal: Principal,
        store_ref: str,
        as_of: datetime,
        portfolio_ref: str,
        allocation_contract_ref: str,
    ) -> dict[str, Any]:
        if not principal.has_any_role("operator", "monitor", "reviewer", "risk", "admin"):
            raise PermissionError("capital allocation read role required")
        if not principal.can_access_store(store_ref):
            raise PermissionError("store is outside authorized scope")
        if portfolio_ref != self.fixture.payload["portfolio_ref"]:
            raise CapitalAllocationContractError("portfolio_ref hash drift detected")
        if allocation_contract_ref != self.fixture.ref:
            raise CapitalAllocationContractError("allocation_contract_ref hash drift detected")
        cutoff = _timestamp(as_of, field="as_of")
        try:
            checked_at = _timestamp(self.clock(), field="authority_checked_at")
        except Exception as exc:
            raise CapitalAllocationContractError("trusted clock unavailable") from exc
        if cutoff > checked_at:
            raise CapitalAllocationContractError("as_of cannot exceed trusted current time")
        try:
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
        except CapitalAllocationContractError:
            return self._blocked_observation(
                principal=principal,
                store_ref=store_ref,
                cutoff=cutoff,
                checked_at=checked_at,
                portfolio_ref=portfolio_ref,
                allocation_contract_ref=allocation_contract_ref,
                state="blocked",
                reasons=["current_scope_authority_contract_invalid"],
            )
        except Exception:
            return self._blocked_observation(
                principal=principal,
                store_ref=store_ref,
                cutoff=cutoff,
                checked_at=checked_at,
                portfolio_ref=portfolio_ref,
                allocation_contract_ref=allocation_contract_ref,
                state="UNKNOWN",
                reasons=["current_scope_authority_unavailable"],
            )
        if exact_scope is None:
            return self._blocked_observation(
                principal=principal,
                store_ref=store_ref,
                cutoff=cutoff,
                checked_at=checked_at,
                portfolio_ref=portfolio_ref,
                allocation_contract_ref=allocation_contract_ref,
                state="not_visible",
                reasons=["exact_current_scope_authority_required"],
            )
        fixture_scope = _scope(self.fixture.payload["scope"], field="fixture.scope")
        if exact_scope != fixture_scope:
            observation = self._blocked_observation(
                principal=principal,
                store_ref=store_ref,
                cutoff=cutoff,
                checked_at=checked_at,
                portfolio_ref=portfolio_ref,
                allocation_contract_ref=allocation_contract_ref,
                state="not_visible",
                reasons=["allocation_contract_exact_scope_binding_mismatch"],
                scope=exact_scope,
            )
            return self._cache_observation(
                principal=principal,
                scope=exact_scope,
                store_ref=store_ref,
                cutoff=cutoff,
                allocation_contract_ref=allocation_contract_ref,
                observation=observation,
            )
        if cutoff != _timestamp(self.fixture.payload["data_as_of"], field="data_as_of"):
            observation = self._blocked_observation(
                principal=principal,
                store_ref=store_ref,
                cutoff=cutoff,
                checked_at=checked_at,
                portfolio_ref=portfolio_ref,
                allocation_contract_ref=allocation_contract_ref,
                state="blocked",
                reasons=["allocation_contract_data_as_of_binding_mismatch"],
                scope=exact_scope,
            )
            return self._cache_observation(
                principal=principal,
                scope=exact_scope,
                store_ref=store_ref,
                cutoff=cutoff,
                allocation_contract_ref=allocation_contract_ref,
                observation=observation,
            )
        try:
            raw_bundle = self.read_authority.read_bundle(
                principal=principal,
                entity_scope=deepcopy(entity_scope),
                store_ref=store_ref,
                as_of=cutoff,
                portfolio_ref=portfolio_ref,
                allocation_contract_ref=allocation_contract_ref,
                source_bindings=deepcopy(self.fixture.payload["source_bindings"]),
            )
            _safe_projection(raw_bundle, path="read_bundle")
            projections, receipts = self._validate_bundle(
                raw_bundle,
                principal=principal,
                entity_scope=entity_scope,
                scope=exact_scope,
                cutoff=cutoff,
                checked_at=checked_at,
                portfolio_ref=portfolio_ref,
                allocation_contract_ref=allocation_contract_ref,
            )
            observation = self._build_observation(
                principal=principal,
                scope=exact_scope,
                cutoff=cutoff,
                checked_at=checked_at,
                portfolio_ref=portfolio_ref,
                allocation_contract_ref=allocation_contract_ref,
                raw_bundle=raw_bundle,
                projections=projections,
                receipts=receipts,
            )
        except CapitalAllocationContractError:
            observation = self._blocked_observation(
                principal=principal,
                store_ref=store_ref,
                cutoff=cutoff,
                checked_at=checked_at,
                portfolio_ref=portfolio_ref,
                allocation_contract_ref=allocation_contract_ref,
                state="blocked",
                reasons=["read_projection_contract_or_hash_invalid"],
                scope=exact_scope,
            )
        except Exception:
            observation = self._blocked_observation(
                principal=principal,
                store_ref=store_ref,
                cutoff=cutoff,
                checked_at=checked_at,
                portfolio_ref=portfolio_ref,
                allocation_contract_ref=allocation_contract_ref,
                state="UNKNOWN",
                reasons=["read_or_citation_authority_unavailable"],
                scope=exact_scope,
            )
        return self._cache_observation(
            principal=principal,
            scope=exact_scope,
            store_ref=store_ref,
            cutoff=cutoff,
            allocation_contract_ref=allocation_contract_ref,
            observation=observation,
        )

    def _cache_observation(
        self,
        *,
        principal: Principal,
        scope: dict[str, str],
        store_ref: str,
        cutoff: datetime,
        allocation_contract_ref: str,
        observation: dict[str, Any],
    ) -> dict[str, Any]:
        winner_key = (
            principal.tenant_ref,
            scope["entity_ref"],
            store_ref,
            cutoff.isoformat(),
            allocation_contract_ref,
        )
        request_sha256 = observation["request_sha256"]
        with self._lock:
            prior = self._runs.get(winner_key)
            if prior is not None:
                prior_sha256, prior_observation = prior
                if not hmac.compare_digest(prior_sha256, request_sha256):
                    raise CapitalAllocationConflictError(
                        "allocation request conflicts with immutable winner"
                    )
                if "review_due" in observation["reason_codes"]:
                    return deepcopy(observation)
                return deepcopy(prior_observation)
            self._runs[winner_key] = (request_sha256, deepcopy(observation))
        return deepcopy(observation)

    @staticmethod
    def _exact_scope(
        *,
        principal: Principal,
        store_ref: str,
        entity_scope: Any,
    ) -> dict[str, str] | None:
        if not isinstance(entity_scope, dict):
            return None
        authority = entity_scope.get("authority_sha256")
        entity_ref = entity_scope.get("entity_ref")
        if not (
            entity_scope.get("status") == "ready"
            and entity_scope.get("tenant_ref") == principal.tenant_ref
            and entity_scope.get("store_ref") == store_ref
            and isinstance(entity_ref, str)
            and _TOKEN.fullmatch(entity_ref)
            and isinstance(authority, str)
            and _HEX64.fullmatch(authority.lower())
        ):
            return None
        return {
            "tenant_ref": principal.tenant_ref,
            "entity_ref": entity_ref,
            "store_ref": store_ref,
            "scope_grant_authority_sha256": authority.lower(),
        }

    def _validate_bundle(
        self,
        raw: Any,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        scope: dict[str, str],
        cutoff: datetime,
        checked_at: datetime,
        portfolio_ref: str,
        allocation_contract_ref: str,
    ) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
        bundle = _exact_fields(raw, _BUNDLE_FIELDS, field="read_bundle")
        if bundle["contract_id"] != self.registry.payload["read_bundle_contract_id"]:
            raise CapitalAllocationContractError("read bundle contract drift")
        if bundle["portfolio_ref"] != portfolio_ref:
            raise CapitalAllocationContractError("read bundle portfolio drift")
        if bundle["allocation_contract_ref"] != allocation_contract_ref:
            raise CapitalAllocationContractError("read bundle allocation contract drift")
        if _scope(bundle["scope"], field="read_bundle.scope") != scope:
            raise CapitalAllocationContractError("read bundle exact scope mismatch")
        if _timestamp(bundle["as_of"], field="read_bundle.as_of") != cutoff:
            raise CapitalAllocationContractError("read bundle as_of drift")
        expected_sha = _hash(
            {key: value for key, value in bundle.items() if key != "bundle_sha256"}
        )
        if not hmac.compare_digest(
            _sha256(bundle["bundle_sha256"], field="read_bundle.bundle_sha256"),
            expected_sha,
        ):
            raise CapitalAllocationContractError("read bundle hash drift")
        raw_projections = bundle["projections"]
        if not isinstance(raw_projections, list) or len(raw_projections) != len(
            self.registry.source_contracts
        ):
            raise CapitalAllocationContractError("read projection conservation failed")
        bindings = {
            item["source_id"]: item for item in self.fixture.payload["source_bindings"]
        }
        projections: dict[str, dict[str, Any]] = {}
        receipts: dict[str, dict[str, Any]] = {}
        for raw_projection in raw_projections:
            projection = self._validate_projection(
                raw_projection,
                scope=scope,
                cutoff=cutoff,
                bindings=bindings,
            )
            source_id = projection["source_id"]
            if source_id in projections:
                raise CapitalAllocationContractError("duplicate read projection")
            receipt = self._verify_citation(
                principal=principal,
                entity_scope=entity_scope,
                scope=scope,
                cutoff=cutoff,
                checked_at=checked_at,
                projection=projection,
            )
            projections[source_id] = projection
            receipts[source_id] = receipt
        if set(projections) != set(self.registry.source_contracts):
            raise CapitalAllocationContractError("read projection set drift")
        return projections, receipts

    def _validate_projection(
        self,
        raw: Any,
        *,
        scope: dict[str, str],
        cutoff: datetime,
        bindings: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        projection = _exact_fields(raw, _PROJECTION_FIELDS, field="projection")
        source_id = _token(projection["source_id"], field="projection.source_id")
        contract = self.registry.source_contracts.get(source_id)
        binding = bindings.get(source_id)
        if contract is None or binding is None:
            raise CapitalAllocationContractError("projection source is not bound")
        if (
            projection["contract_id"] != contract["contract_id"]
            or projection["contract_version"] != contract["version"]
            or projection["source_ref"] != binding["source_ref"]
        ):
            raise CapitalAllocationContractError("projection identity drift")
        status = str(projection["status"])
        if status not in self.registry.payload["allowed_states"]:
            raise CapitalAllocationContractError("projection status is invalid")
        if _scope(projection["scope"], field="projection.scope") != scope:
            raise CapitalAllocationContractError("projection exact scope mismatch")
        if _timestamp(projection["as_of"], field="projection.as_of") != cutoff:
            raise CapitalAllocationContractError("projection as_of drift")
        if projection["evidence_binding"] != binding["evidence_binding"]:
            raise CapitalAllocationContractError("projection Evidence binding drift")
        payload = projection["payload"]
        if status == "ready":
            payload = self._validate_ready_payload(source_id, payload, cutoff=cutoff)
        elif payload != {}:
            raise CapitalAllocationContractError("non-ready projection payload must be empty")
        evidence = projection["evidence_binding"]
        if evidence["claims_sha256"] != _hash(payload):
            raise CapitalAllocationContractError("projection claims hash drift")
        expected_sha = _hash(
            {key: value for key, value in projection.items() if key != "projection_sha256"}
        )
        if not hmac.compare_digest(
            _sha256(projection["projection_sha256"], field="projection.projection_sha256"),
            expected_sha,
        ):
            raise CapitalAllocationContractError("projection hash drift")
        return {**projection, "payload": payload}

    def _validate_ready_payload(
        self,
        source_id: str,
        raw: Any,
        *,
        cutoff: datetime,
    ) -> dict[str, Any]:
        payload = _exact_fields(
            raw,
            _PROJECTION_PAYLOAD_FIELDS[source_id],
            field=f"{source_id}.payload",
        )
        _safe_projection(payload, path=f"{source_id}.payload")
        for field in _MONEY_FIELDS_BY_SOURCE.get(source_id, set()):
            self._money(payload[field], field=f"{source_id}.{field}", cutoff=cutoff)
        if source_id == "gap_graph":
            _token(payload["portfolio_ref"], field="gap_graph.portfolio_ref")
            if payload["portfolio_status"] not in {"admitted", "not_admitted"}:
                raise CapitalAllocationContractError("gap graph portfolio status is invalid")
            _unique_tokens(payload["opportunity_refs"], field="opportunity_refs")
            if not isinstance(payload["dependency_edges"], list):
                raise CapitalAllocationContractError("dependency edges must be a list")
            for edge in payload["dependency_edges"]:
                values = _exact_fields(edge, {"source", "target"}, field="dependency_edge")
                _token(values["source"], field="dependency_edge.source")
                _token(values["target"], field="dependency_edge.target")
            _unique_tokens(payload["rollback_refs"], field="rollback_refs")
        elif source_id == "strategic_benchmark":
            _token(payload["best_solution_profile_ref"], field="best_solution_profile_ref")
            if payload["hard_elimination_dimensions"] != self.registry.payload[
                "hard_elimination_dimensions"
            ]:
                raise CapitalAllocationContractError("hard elimination profile drift")
            if payload["comparison_dimensions"] != self.registry.payload[
                "comparison_dimensions"
            ]:
                raise CapitalAllocationContractError("comparison profile drift")
            if payload["equal_weight_total_score_allowed"] is not False:
                raise CapitalAllocationContractError("equal-weight score is prohibited")
            for field in ("security_status", "privacy_status", "legal_and_license_status"):
                if payload[field] not in {"passed", "blocked", "UNKNOWN"}:
                    raise CapitalAllocationContractError(f"{field} is invalid")
        elif source_id == "capital_constraints":
            _strict_int(payload["runway_days"], field="runway_days", maximum=100_000)
            if not isinstance(payload["board_approved_current"], bool) or not isinstance(
                payload["signed_thresholds_current"], bool
            ):
                raise CapitalAllocationContractError("signed thresholds status is invalid")
            _token(payload["thresholds_ref"], field="thresholds_ref")
            _strict_int(
                payload["evidence_coverage_basis_points"],
                field="evidence_coverage_basis_points",
                maximum=10_000,
            )
        elif source_id == "profit_truth":
            if not isinstance(payload["signed_profit_threshold_current"], bool):
                raise CapitalAllocationContractError("profit threshold status is invalid")
            _token(payload["profit_threshold_ref"], field="profit_threshold_ref")
            if payload["treasury_cash_authority"] is not False:
                raise CapitalAllocationContractError(
                    "actual_cash_cm3 cannot be treasury cash authority"
                )
        elif source_id == "settlement_cash":
            if payload["unsettled_included"] is not False:
                raise CapitalAllocationContractError("unsettled cash is prohibited")
            if payload["cash_status"] not in {"settled", "no_data", "UNKNOWN"}:
                raise CapitalAllocationContractError("cash status is invalid")
            if payload["treasury_cash_authority"] is not False:
                raise CapitalAllocationContractError(
                    "platform settlement cannot be treasury cash authority"
                )
        elif source_id == "growth_outcome":
            if not isinstance(payload["acceptance_evidence_current"], bool):
                raise CapitalAllocationContractError("acceptance status is invalid")
            if payload["causal_authority_status"] not in {"verified", "UNKNOWN", "blocked"}:
                raise CapitalAllocationContractError("causal authority status is invalid")
            _token(payload["outcome_ref"], field="outcome_ref")
            _token(payload["primary_metric_ref"], field="primary_metric_ref")
        elif source_id == "commercial_lifecycle":
            if not isinstance(payload["settled_only"], bool) or not isinstance(
                payload["entitlement_current"], bool
            ):
                raise CapitalAllocationContractError("commercial status is invalid")
            if payload["c0_status"] not in {"not_for_sale", "ready"}:
                raise CapitalAllocationContractError("C0 status is invalid")
            _unique_tokens(
                payload["external_blockers"],
                field="external_blockers",
                allow_empty=True,
            )
            if payload["treasury_cash_authority"] is not False:
                raise CapitalAllocationContractError(
                    "commercial entitlement cannot be treasury cash authority"
                )
        return payload

    @staticmethod
    def _money(raw: Any, *, field: str, cutoff: datetime) -> dict[str, Any]:
        return _money_contract(raw, field=field, cutoff=cutoff)

    def _verify_citation(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        scope: dict[str, str],
        cutoff: datetime,
        checked_at: datetime,
        projection: dict[str, Any],
    ) -> dict[str, Any]:
        binding = projection["evidence_binding"]
        contract = self.registry.source_contracts[projection["source_id"]]
        raw = self.citation_authority.verify_citation(
            principal=principal,
            entity_scope=deepcopy(entity_scope),
            store_ref=scope["store_ref"],
            data_as_of=cutoff,
            authority_checked_at=checked_at,
            citation_ref=binding["citation_ref"],
            evidence_sha256=binding["evidence_sha256"],
            claims_sha256=binding["claims_sha256"],
            source_contract_id=contract["contract_id"],
            source_contract_version=contract["version"],
        )
        receipt = _exact_fields(raw, _CITATION_RECEIPT_FIELDS, field="citation_receipt")
        if receipt["contract_id"] != self.registry.payload["citation_authority_contract_id"]:
            raise CapitalAllocationContractError("citation authority contract drift")
        if receipt["status"] != "ready":
            raise CapitalAllocationContractError("citation authority is not ready")
        expected_identity = {
            "citation_ref": binding["citation_ref"],
            "evidence_id": binding["evidence_id"],
            "evidence_sha256": binding["evidence_sha256"],
            "claims_sha256": binding["claims_sha256"],
            "source": binding["source"],
            "source_ref": binding["source_ref"],
            "recorded_at": binding["recorded_at"],
            "effective_at": binding["effective_at"],
            "effective_until": binding["effective_until"],
        }
        if any(receipt[key] != value for key, value in expected_identity.items()):
            raise CapitalAllocationContractError("citation Evidence identity drift")
        if (
            receipt["source_contract_id"] != contract["contract_id"]
            or receipt["source_contract_version"] != contract["version"]
            or receipt["source_contract_sha256"] != contract["contract_sha256"]
        ):
            raise CapitalAllocationContractError("citation source contract drift")
        if _scope(receipt["scope"], field="citation_receipt.scope") != scope:
            raise CapitalAllocationContractError("citation exact scope mismatch")
        recorded = _timestamp(receipt["recorded_at"], field="receipt.recorded_at")
        effective = _timestamp(receipt["effective_at"], field="receipt.effective_at")
        until = _timestamp(receipt["effective_until"], field="receipt.effective_until")
        if not (effective <= recorded <= cutoff < until and recorded <= checked_at):
            raise CapitalAllocationContractError("citation chronology or currentness failed")
        if receipt["integrity_status"] != "valid" or receipt["current"] is not True:
            raise CapitalAllocationContractError("citation integrity or currentness failed")
        if _GRADE_ORDER.get(str(receipt["grade"]), 0) < _GRADE_ORDER[contract["minimum_grade"]]:
            raise CapitalAllocationContractError("citation grade is below contract")
        return receipt

    def _build_observation(
        self,
        *,
        principal: Principal,
        scope: dict[str, str],
        cutoff: datetime,
        checked_at: datetime,
        portfolio_ref: str,
        allocation_contract_ref: str,
        raw_bundle: dict[str, Any],
        projections: dict[str, dict[str, Any]],
        receipts: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        request = {
            "contract_id": self.CONTRACT_ID,
            "registry_sha256": self.registry.content_sha256,
            "fixture_sha256": self.fixture.content_sha256,
            "portfolio_ref": portfolio_ref,
            "allocation_contract_ref": allocation_contract_ref,
            "scope": scope,
            "actor_id": principal.actor_id,
            "as_of": cutoff.isoformat(),
            "read_bundle_sha256": raw_bundle["bundle_sha256"],
            "citation_receipts_sha256": _hash(
                [receipts[key] for key in sorted(receipts)]
            ),
        }
        request_sha256 = _hash(request)
        source_statuses = [
            {
                "source_id": source_id,
                "status": projections[source_id]["status"],
                "projection_sha256": projections[source_id]["projection_sha256"],
            }
            for source_id in sorted(projections)
        ]
        gate_results = self._gate_results(projections)
        options = self._option_results(
            projections, gate_results=gate_results, checked_at=checked_at
        )
        blockers = sorted(
            gate_id for gate_id, status in gate_results.items() if status != "passed"
        )
        feasible = [item for item in options if item["feasible"]]
        best_feasible = self._best_feasible(feasible)
        synthetic_only = self.fixture.payload["data_classification"] == "synthetic_public"
        if synthetic_only:
            blockers.append("real_finance_authority")
        if any(item["review_status"] == "due" for item in options):
            blockers.append("review_due")
        blockers = sorted(set(blockers))
        selected_option = "no_action"
        proposal_status = "not_admitted"
        if best_feasible is not None and not blockers:
            selected_option = best_feasible["option_type"]
            proposal_status = "admitted"
        observation = {
            "contract_id": self.CONTRACT_ID,
            "status": "ready" if proposal_status == "admitted" else "blocked",
            "proposal_status": proposal_status,
            "selected_option": selected_option,
            "best_feasible_for_kjds": (
                best_feasible["option_type"]
                if best_feasible is not None and not blockers
                else "no_action"
            ),
            "synthetic_best_feasible": (
                best_feasible["option_type"] if best_feasible is not None else "no_action"
            ),
            "reason_codes": blockers,
            "run_id": f"cap_{request_sha256[:32]}",
            "request_sha256": request_sha256,
            "registry_ref": self.registry.ref,
            "portfolio_ref": portfolio_ref,
            "allocation_contract_ref": allocation_contract_ref,
            "scope": scope,
            "as_of": cutoff.isoformat(),
            "authority_checked_at": checked_at.isoformat(),
            "source_statuses": source_statuses,
            "gate_results": gate_results,
            "options": options,
            "proposal_fields": self._proposal_fields(
                projections, selected_option, checked_at=checked_at
            ),
            "fixture_authority": "repository_owned_synthetic_fixture",
            "real_finance_status": "UNKNOWN" if synthetic_only else "ready",
            "production_admission": False,
            "proposal_only": True,
            "equal_weight_total_score_used": False,
            "generated_or_inferred_satisfies_gate": False,
            "governance": deepcopy(self.registry.payload["zero_authority_flags"]),
            "write_counts": self._zero_write_counts(),
        }
        observation["observation_sha256"] = _hash(observation)
        return observation

    def _gate_results(self, projections: dict[str, dict[str, Any]]) -> dict[str, str]:
        ready = {key: value["status"] == "ready" for key, value in projections.items()}
        gates = {
            "evidence": "passed" if all(ready.values()) else "blocked",
            "authority": "passed" if all(ready.values()) else "blocked",
            "security": "blocked",
            "privacy": "blocked",
            "legal_and_license": "blocked",
            "cash_floor": "blocked",
            "maximum_loss": "blocked",
            "rollback": "blocked",
            "acceptance": "blocked",
        }
        if not all(ready.values()):
            return gates
        benchmark = projections["strategic_benchmark"]["payload"]
        capital = projections["capital_constraints"]["payload"]
        profit = projections["profit_truth"]["payload"]
        settlement = projections["settlement_cash"]["payload"]
        growth = projections["growth_outcome"]["payload"]
        commercial = projections["commercial_lifecycle"]["payload"]
        gap = projections["gap_graph"]["payload"]
        gates["security"] = benchmark["security_status"]
        gates["privacy"] = benchmark["privacy_status"]
        gates["legal_and_license"] = benchmark["legal_and_license_status"]
        policy_currency = self.fixture.payload["policy"]["currency"]
        comparable_monies = [
            capital[name]
            for name in (
                "treasury_cash_balance",
                "cash_floor",
                "budget_cap",
                "maximum_loss_limit",
            )
        ] + [
            profit["actual_cash_cm3"],
            profit["downside_cm3"],
            settlement["settled_cash"],
            commercial["outstanding_total"],
            self.fixture.payload["policy"]["minimum_downside_cm3"],
        ]
        currencies_match = all(
            item["currency"] == policy_currency for item in comparable_monies
        )
        treasury_cash = capital["treasury_cash_balance"]["amount_microunits"]
        cash_floor = capital["cash_floor"]["amount_microunits"]
        cash_current = (
            currencies_match
            and capital["board_approved_current"]
            and capital["signed_thresholds_current"]
            and capital["runway_days"]
            >= self.fixture.payload["policy"]["minimum_runway_days"]
            and capital["evidence_coverage_basis_points"]
            >= self.fixture.payload["policy"][
                "required_evidence_coverage_basis_points"
            ]
            and treasury_cash >= cash_floor
            and profit["signed_profit_threshold_current"]
            and settlement["cash_status"] == "settled"
            and commercial["settled_only"]
            and commercial["entitlement_current"]
            and profit["treasury_cash_authority"] is False
            and settlement["treasury_cash_authority"] is False
            and commercial["treasury_cash_authority"] is False
        )
        gates["cash_floor"] = "passed" if cash_current else "blocked"
        gates["maximum_loss"] = "passed" if cash_current else "blocked"
        gates["rollback"] = (
            "passed"
            if gap["portfolio_status"] == "admitted" and bool(gap["rollback_refs"])
            else "blocked"
        )
        gates["acceptance"] = (
            "passed"
            if growth["acceptance_evidence_current"]
            and growth["causal_authority_status"] == "verified"
            and commercial["c0_status"] == "ready"
            and not commercial["external_blockers"]
            else "blocked"
        )
        return gates

    def _option_results(
        self,
        projections: dict[str, dict[str, Any]],
        *,
        gate_results: dict[str, str],
        checked_at: datetime,
    ) -> list[dict[str, Any]]:
        all_ready = all(item["status"] == "ready" for item in projections.values())
        global_pass = all(status == "passed" for status in gate_results.values())
        capital = (
            projections.get("capital_constraints", {}).get("payload", {})
            if all_ready
            else {}
        )
        profit = projections.get("profit_truth", {}).get("payload", {}) if all_ready else {}
        gap = projections.get("gap_graph", {}).get("payload", {}) if all_ready else {}
        cash_capacity = 0
        budget_cap = 0
        loss_limit = 0
        if profit:
            cash_capacity = max(
                0,
                capital["treasury_cash_balance"]["amount_microunits"]
                - capital["cash_floor"]["amount_microunits"],
            )
            budget_cap = capital["budget_cap"]["amount_microunits"]
            loss_limit = capital["maximum_loss_limit"]["amount_microunits"]
        opportunity_refs = set(gap.get("opportunity_refs", []))
        rollback_refs = set(gap.get("rollback_refs", []))
        policy = self.fixture.payload["policy"]
        gap_dependency_edges = {
            (edge["source"], edge["target"]) for edge in gap.get("dependency_edges", [])
        }
        expected_dependency_edges = {
            (spec["option_id"], dependency)
            for spec in self.fixture.payload["option_specs"]
            for dependency in spec["dependency_refs"]
        }
        dependency_binding_matches = gap_dependency_edges == expected_dependency_edges
        results: list[dict[str, Any]] = []
        for spec in self.fixture.payload["option_specs"]:
            reasons: list[str] = []
            option_type = spec["option_type"]
            review_due = checked_at >= _timestamp(
                spec["review_date"], field="option.review_date"
            )
            if option_type == "no_action":
                feasible = True
                if review_due:
                    reasons.append("review_due")
            else:
                if not global_pass:
                    reasons.append("global_hard_gate_blocked")
                option_monies = [spec[field] for field in _OPTION_MONEY_FIELDS]
                comparison_monies = [
                    spec["comparison_values"][field]
                    for field in _COMPARISON_MONEY_FIELDS
                ]
                if any(
                    money["currency"] != policy["currency"]
                    for money in [*option_monies, *comparison_monies]
                ):
                    reasons.append("current_fx_authority_required")
                if spec["opportunity_ref"] not in opportunity_refs:
                    reasons.append("gap_graph_opportunity_not_admitted")
                if spec["rollback_ref"] not in rollback_refs:
                    reasons.append("rollback_not_admitted")
                if not dependency_binding_matches:
                    reasons.append("gap_graph_dependency_binding_mismatch")
                if spec["budget_request"]["amount_microunits"] > min(
                    cash_capacity, budget_cap
                ):
                    reasons.append("cash_or_budget_capacity_exceeded")
                if spec["maximum_loss"]["amount_microunits"] > min(
                    cash_capacity, loss_limit
                ):
                    reasons.append("maximum_loss_exceeded")
                if spec["downside_cm3"]["amount_microunits"] < max(
                    policy["minimum_downside_cm3"]["amount_microunits"],
                    profit["downside_cm3"]["amount_microunits"],
                ):
                    reasons.append("downside_cm3_below_signed_threshold")
                if spec["timebox_days"] > policy["maximum_timebox_days"]:
                    reasons.append("timebox_exceeded")
                if spec["payback_days"] > policy["maximum_payback_days"]:
                    reasons.append("payback_exceeded")
                if review_due:
                    reasons.append("review_due")
                feasible = not reasons
            results.append(
                {
                    "option_id": spec["option_id"],
                    "option_type": option_type,
                    "feasible": feasible,
                    "reason_codes": sorted(reasons),
                    "option_sha256": spec["option_sha256"],
                    "budget_request": deepcopy(spec["budget_request"]),
                    "maximum_loss": deepcopy(spec["maximum_loss"]),
                    "downside_cm3": deepcopy(spec["downside_cm3"]),
                    "base_cm3": deepcopy(spec["base_cm3"]),
                    "upside_cm3": deepcopy(spec["upside_cm3"]),
                    "timebox_days": spec["timebox_days"],
                    "payback_days": spec["payback_days"],
                    "dependency_refs": deepcopy(spec["dependency_refs"]),
                    "owner_ref": spec["owner_ref"],
                    "primary_metric": spec["primary_metric"],
                    "guardrails": deepcopy(spec["guardrails"]),
                    "stop_conditions": deepcopy(spec["stop_conditions"]),
                    "rollback_ref": spec["rollback_ref"],
                    "invalidation_conditions": deepcopy(
                        spec["invalidation_conditions"]
                    ),
                    "review_date": spec["review_date"],
                    "review_status": "due" if review_due else "current",
                    "no_action_comparison": spec["no_action_comparison"],
                    "comparison_values": deepcopy(spec["comparison_values"]),
                }
            )
        result_by_id = {item["option_id"]: item for item in results}
        changed = True
        while changed:
            changed = False
            for spec in self.fixture.payload["option_specs"]:
                result = result_by_id[spec["option_id"]]
                if result["option_type"] == "no_action":
                    continue
                dependency_blocked = any(
                    not result_by_id[dependency]["feasible"]
                    for dependency in spec["dependency_refs"]
                )
                if dependency_blocked and "dependency_not_feasible" not in result["reason_codes"]:
                    result["reason_codes"].append("dependency_not_feasible")
                    result["reason_codes"].sort()
                    result["feasible"] = False
                    changed = True
        return results

    @staticmethod
    def _best_feasible(options: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not options:
            return None

        def key(item: dict[str, Any]) -> tuple[int, int, int, int, int, int, int, str]:
            value = item["comparison_values"]
            return (
                -value["long_term_risk_adjusted_value"]["amount_microunits"],
                value["total_cost_of_ownership"]["amount_microunits"],
                value["time_to_value_days"],
                -value["operational_fit_basis_points"],
                -value["maintainability_basis_points"],
                -value["reversibility_basis_points"],
                value["replacement_cost"]["amount_microunits"],
                item["option_id"],
            )

        return min(options, key=key)

    def _proposal_fields(
        self,
        projections: dict[str, dict[str, Any]],
        selected_option: str,
        *,
        checked_at: datetime,
    ) -> dict[str, Any]:
        capital = projections.get("capital_constraints", {}).get("payload", {})
        fields = {
            "cash_floor": self._safe_money_projection(capital.get("cash_floor")),
            "runway": capital.get("runway_days"),
            "budget_cap": self._safe_money_projection(capital.get("budget_cap")),
            "maximum_loss_limit": self._safe_money_projection(
                capital.get("maximum_loss_limit")
            ),
            "budget_request": None,
            "maximum_loss": None,
            "timebox": None,
            "downside_base_upside": None,
            "payback_period": None,
            "evidence_coverage": capital.get("evidence_coverage_basis_points"),
            "dependencies": [],
            "owner": None,
            "primary_metric": None,
            "guardrails": [],
            "stop_conditions": [],
            "rollback": None,
            "invalidation_conditions": [],
            "review_date": None,
            "review_status": "UNKNOWN",
            "no_action_comparison": "no_action_retains_cash_and_external_blockers",
            "comparison_values": None,
        }
        spec = next(
            (
                item
                for item in self.fixture.payload["option_specs"]
                if item["option_type"] == selected_option
            ),
            None,
        )
        if spec is not None:
            fields.update(
                {
                    "budget_request": deepcopy(spec["budget_request"]),
                    "maximum_loss": deepcopy(spec["maximum_loss"]),
                    "timebox": spec["timebox_days"],
                    "downside_base_upside": {
                        "downside": deepcopy(spec["downside_cm3"]),
                        "base": deepcopy(spec["base_cm3"]),
                        "upside": deepcopy(spec["upside_cm3"]),
                    },
                    "payback_period": spec["payback_days"],
                    "dependencies": deepcopy(spec["dependency_refs"]),
                    "owner": spec["owner_ref"],
                    "primary_metric": spec["primary_metric"],
                    "guardrails": deepcopy(spec["guardrails"]),
                    "stop_conditions": deepcopy(spec["stop_conditions"]),
                    "rollback": spec["rollback_ref"],
                    "invalidation_conditions": deepcopy(
                        spec["invalidation_conditions"]
                    ),
                    "review_date": spec["review_date"],
                    "review_status": (
                        "due"
                        if checked_at
                        >= _timestamp(spec["review_date"], field="option.review_date")
                        else "current"
                    ),
                    "no_action_comparison": spec["no_action_comparison"],
                    "comparison_values": deepcopy(spec["comparison_values"]),
                }
            )
        if set(fields) != set(self.registry.payload["required_proposal_fields"]):
            raise CapitalAllocationContractError("proposal field set drift")
        return fields

    @staticmethod
    def _safe_money_projection(value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        return {
            "amount_microunits": value["amount_microunits"],
            "currency": value["currency"],
            "occurred_at": value["occurred_at"],
            "effective_at": value["effective_at"],
            "evidence_ref": value["evidence_ref"],
            "evidence_sha256": value["evidence_sha256"],
        }

    def _blocked_observation(
        self,
        *,
        principal: Principal,
        store_ref: str,
        cutoff: datetime,
        checked_at: datetime,
        portfolio_ref: str,
        allocation_contract_ref: str,
        state: str,
        reasons: list[str],
        scope: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        request = {
            "contract_id": self.CONTRACT_ID,
            "registry_sha256": self.registry.content_sha256,
            "fixture_sha256": self.fixture.content_sha256,
            "portfolio_ref": portfolio_ref,
            "allocation_contract_ref": allocation_contract_ref,
            "tenant_ref": principal.tenant_ref,
            "entity_ref": scope["entity_ref"] if scope else None,
            "store_ref": store_ref,
            "authority_sha256": (
                scope["scope_grant_authority_sha256"] if scope else None
            ),
            "actor_id": principal.actor_id,
            "as_of": cutoff.isoformat(),
            "failure_reasons": sorted(set(reasons)),
        }
        request_sha256 = _hash(request)
        gates = {
            item: "blocked" for item in self.registry.payload["hard_elimination_dimensions"]
        }
        observation = {
            "contract_id": self.CONTRACT_ID,
            "status": state,
            "proposal_status": "not_admitted",
            "selected_option": "no_action",
            "best_feasible_for_kjds": "no_action",
            "synthetic_best_feasible": "no_action",
            "reason_codes": sorted(set(reasons)),
            "run_id": f"cap_{request_sha256[:32]}",
            "request_sha256": request_sha256,
            "registry_ref": self.registry.ref,
            "portfolio_ref": portfolio_ref,
            "allocation_contract_ref": allocation_contract_ref,
            "scope": scope,
            "as_of": cutoff.isoformat(),
            "authority_checked_at": checked_at.isoformat(),
            "source_statuses": [],
            "gate_results": gates,
            "options": [
                {
                    "option_id": item["option_id"],
                    "option_type": item["option_type"],
                    "feasible": item["option_type"] == "no_action",
                    "reason_codes": []
                    if item["option_type"] == "no_action"
                    else ["global_hard_gate_blocked"],
                    "option_sha256": item["option_sha256"],
                    "budget_request": deepcopy(item["budget_request"]),
                    "maximum_loss": deepcopy(item["maximum_loss"]),
                    "downside_cm3": deepcopy(item["downside_cm3"]),
                    "base_cm3": deepcopy(item["base_cm3"]),
                    "upside_cm3": deepcopy(item["upside_cm3"]),
                    "timebox_days": item["timebox_days"],
                    "payback_days": item["payback_days"],
                    "dependency_refs": deepcopy(item["dependency_refs"]),
                    "owner_ref": item["owner_ref"],
                    "primary_metric": item["primary_metric"],
                    "guardrails": deepcopy(item["guardrails"]),
                    "stop_conditions": deepcopy(item["stop_conditions"]),
                    "rollback_ref": item["rollback_ref"],
                    "invalidation_conditions": deepcopy(
                        item["invalidation_conditions"]
                    ),
                    "review_date": item["review_date"],
                    "review_status": (
                        "due"
                        if checked_at
                        >= _timestamp(item["review_date"], field="option.review_date")
                        else "current"
                    ),
                    "no_action_comparison": item["no_action_comparison"],
                    "comparison_values": deepcopy(item["comparison_values"]),
                }
                for item in self.fixture.payload["option_specs"]
            ],
            "proposal_fields": {
                "cash_floor": None,
                "runway": None,
                "budget_cap": None,
                "maximum_loss_limit": None,
                "budget_request": None,
                "maximum_loss": None,
                "timebox": None,
                "downside_base_upside": None,
                "payback_period": None,
                "evidence_coverage": None,
                "dependencies": [],
                "owner": None,
                "primary_metric": None,
                "guardrails": [],
                "stop_conditions": [],
                "rollback": None,
                "invalidation_conditions": [],
                "review_date": None,
                "review_status": "UNKNOWN",
                "no_action_comparison": "no_action_retains_cash_and_external_blockers",
                "comparison_values": None,
            },
            "fixture_authority": "repository_owned_synthetic_fixture",
            "real_finance_status": "UNKNOWN",
            "production_admission": False,
            "proposal_only": True,
            "equal_weight_total_score_used": False,
            "generated_or_inferred_satisfies_gate": False,
            "governance": deepcopy(self.registry.payload["zero_authority_flags"]),
            "write_counts": self._zero_write_counts(),
        }
        observation["observation_sha256"] = _hash(observation)
        return observation

    @staticmethod
    def _zero_write_counts() -> dict[str, int]:
        return {
            "fact": 0,
            "finance_entry": 0,
            "approval": 0,
            "permit": 0,
            "pilot": 0,
            "outbox": 0,
            "canonical_graph": 0,
            "dependency_install": 0,
            "network": 0,
            "external_write": 0,
        }
