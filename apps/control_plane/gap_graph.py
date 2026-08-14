from __future__ import annotations

import hashlib
import json
import math
import re
import threading
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Protocol

from .security import Principal

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,159}$")
_SENSITIVE = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|"
    r"authorization\s*:\s*bearer|private[_-]?key|provider[_-]?request[_-]?id)"
)
_EMAIL = re.compile(r"(?i)(?<![\w.+-])[\w.+-]+@[\w.-]+\.[a-z]{2,}(?![\w.-])")
_GRADE_ORDER = {"UNKNOWN": 0, "D": 1, "C": 2, "B": 3, "A": 4}

_REGISTRY_FIELDS = {
    "schema_version",
    "contract_id",
    "version",
    "read_bundle_contract_id",
    "citation_authority_contract_id",
    "allowed_states",
    "eligible_derivations",
    "observation_only_derivations",
    "node_kinds",
    "edge_relations",
    "causal_relations",
    "opportunity_actions",
    "hard_gate_ids",
    "source_contracts",
    "derivation_eligibility_matrix",
    "zero_authority_flags",
    "content_sha256",
}
_PORTFOLIO_FIELDS = {
    "contract_id",
    "fixture_id",
    "version",
    "registry_sha256",
    "license_class",
    "data_classification",
    "source_bindings",
    "node_specs",
    "edge_specs",
    "gap_specs",
    "opportunity_specs",
    "content_sha256",
}
_BUNDLE_FIELDS = {
    "contract_id",
    "portfolio_ref",
    "scope",
    "as_of",
    "sources",
    "bundle_sha256",
}
_SOURCE_FIELDS = {
    "source_id",
    "contract_id",
    "contract_version",
    "source_ref",
    "status",
    "scope",
    "as_of",
    "items",
    "evidence_binding",
    "projection_sha256",
}
_ITEM_FIELDS = {
    "item_ref",
    "item_kind",
    "state",
    "derivation",
    "attributes",
    "citations",
    "item_sha256",
}
_CITATION_BINDING_FIELDS = {
    "citation_ref",
    "evidence_sha256",
    "claims_sha256",
}
_SOURCE_EVIDENCE_BINDING_FIELDS = {
    "citation_ref",
    "evidence_id",
    "evidence_sha256",
    "source",
    "source_ref",
    "recorded_at",
    "effective_at",
    "effective_until",
    "claims_sha256",
}
_CITATION_RECEIPT_FIELDS = {
    "contract_id",
    "status",
    "citation_ref",
    "evidence_id",
    "evidence_sha256",
    "source",
    "source_ref",
    "claims_sha256",
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
_CAUSAL_AUTHORITY_RECEIPT_FIELDS = {
    "contract_id",
    "status",
    "version",
    "receipt_sha256",
    "claims_sha256",
    "scope",
    "recorded_at",
    "effective_at",
    "effective_until",
    "integrity_status",
    "current",
    "citation_refs",
}
_SCOPE_FIELDS = {
    "tenant_ref",
    "entity_ref",
    "store_ref",
    "scope_grant_authority_sha256",
}


class GapGraphContractError(ValueError):
    pass


class GapGraphConflictError(RuntimeError):
    pass


class GapGraphReadAuthority(Protocol):
    def read_bundle(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        portfolio_ref: str,
        source_bindings: list[dict[str, Any]],
    ) -> dict[str, Any]: ...


class GapGraphCitationAuthority(Protocol):
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


class GapGraphCausalAuthority(Protocol):
    def verify_causal_authority(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        data_as_of: datetime,
        authority_checked_at: datetime,
        relation: str,
        source_node_spec_id: str,
        target_node_spec_id: str,
        claims_sha256: str,
        receipt_sha256: str,
    ) -> dict[str, Any]: ...


class _GateFailure(Exception):
    def __init__(
        self,
        status: str,
        reason: str,
        *,
        subject_sha256: str | None = None,
    ) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason
        self.subject_sha256 = subject_sha256


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
        raise GapGraphContractError("value is not canonical JSON") from exc


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _sha256(value: Any, *, field: str) -> str:
    text = str(value).strip().lower()
    if not _HEX64.fullmatch(text):
        raise GapGraphContractError(f"{field} must be a lowercase SHA-256")
    return text


def _token(value: Any, *, field: str) -> str:
    text = str(value).strip()
    if not _TOKEN.fullmatch(text):
        raise GapGraphContractError(f"{field} must be a safe token")
    return text


def _timestamp(value: Any, *, field: str) -> datetime:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise GapGraphContractError(f"{field} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise GapGraphContractError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def _exact_fields(value: Any, expected: set[str], *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise GapGraphContractError(f"{field} fields do not match contract")
    return value


def _unique_tokens(value: Any, *, field: str, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise GapGraphContractError(f"{field} must be a non-empty list")
    tokens = [_token(item, field=field) for item in value]
    if len(tokens) != len(set(tokens)):
        raise GapGraphContractError(f"{field} contains duplicates")
    return tokens


def _safe_projection(value: Any, *, path: str = "projection") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            _token(key, field=f"{path}.key")
            if _SENSITIVE.search(key) or _EMAIL.search(key):
                raise GapGraphContractError(f"{path}.key contains prohibited data")
            _safe_projection(item, path=f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _safe_projection(item, path=f"{path}[{index}]")
        return
    if isinstance(value, str):
        if len(value) > 160 or _SENSITIVE.search(value) or _EMAIL.search(value):
            raise GapGraphContractError(f"{path} contains prohibited data")
        if not _TOKEN.fullmatch(value):
            try:
                _timestamp(value, field=path)
            except GapGraphContractError as exc:
                raise GapGraphContractError(
                    f"{path} must be a token, hash, or timestamp"
                ) from exc
        return
    if value is None or isinstance(value, (bool, int)):
        return
    if isinstance(value, float) and math.isfinite(value):
        return
    raise GapGraphContractError(f"{path} contains an unsupported value")


class GapGraphContractRegistry:
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
    def load(cls, path: str | Path) -> GapGraphContractRegistry:
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GapGraphContractError("gap graph registry is unreadable") from exc
        _exact_fields(payload, _REGISTRY_FIELDS, field="registry")
        expected_sha = _hash(
            {key: value for key, value in payload.items() if key != "content_sha256"}
        )
        if _sha256(payload["content_sha256"], field="registry.content_sha256") != expected_sha:
            raise GapGraphContractError("gap graph registry hash drift")
        if payload["schema_version"] != "kjds-gap-graph-contracts-v1":
            raise GapGraphContractError("unknown gap graph registry schema")
        if payload["contract_id"] != "kjds-governed-gap-graph-observation-v1":
            raise GapGraphContractError("unknown gap graph observation contract")
        if payload["read_bundle_contract_id"] != "kjds-gap-graph-read-bundle-v1":
            raise GapGraphContractError("unknown gap graph read contract")
        if payload["citation_authority_contract_id"] != "kjds-gap-graph-citation-authority-v1":
            raise GapGraphContractError("unknown gap graph citation contract")
        for field in (
            "allowed_states",
            "eligible_derivations",
            "observation_only_derivations",
            "node_kinds",
            "edge_relations",
            "causal_relations",
            "opportunity_actions",
            "hard_gate_ids",
        ):
            _unique_tokens(payload[field], field=f"registry.{field}")
        if set(payload["allowed_states"]) != {
            "ready",
            "no_data",
            "UNKNOWN",
            "blocked",
            "not_visible",
            "stale",
            "partial",
        }:
            raise GapGraphContractError("gap graph states are not frozen")
        if set(payload["opportunity_actions"]) != {
            "build",
            "buy",
            "partner",
            "defer",
            "no_action",
        }:
            raise GapGraphContractError("opportunity actions are not frozen")
        sources = payload["source_contracts"]
        if not isinstance(sources, list) or len(sources) != 5:
            raise GapGraphContractError("five upstream source contracts are required")
        source_ids: set[str] = set()
        for item in sources:
            _exact_fields(
                item,
                {
                    "source_id",
                    "contract_id",
                    "version",
                    "evidence_source",
                    "contract_sha256",
                },
                field="registry.source_contract",
            )
            source_id = _token(item["source_id"], field="source_id")
            if source_id in source_ids:
                raise GapGraphContractError("duplicate source contract")
            source_ids.add(source_id)
            contract_id = _token(item["contract_id"], field="source.contract_id")
            version = _token(item["version"], field="source.version")
            _token(item["evidence_source"], field="source.evidence_source")
            expected_contract_sha = _hash(
                {"contract_id": contract_id, "version": version}
            )
            if _sha256(item["contract_sha256"], field="source.contract_sha256") != expected_contract_sha:
                raise GapGraphContractError("source contract hash drift")
        cls._validate_derivation_matrix(payload, source_ids=source_ids)
        zero_flags = payload["zero_authority_flags"]
        expected_zero_flags = {
            "formal_fact",
            "finance_entry",
            "approval",
            "permit",
            "pilot",
            "outbox",
            "canonical_graph_write",
            "dependency_install",
            "network",
            "external_write",
        }
        if not isinstance(zero_flags, dict) or set(zero_flags) != expected_zero_flags:
            raise GapGraphContractError("zero-authority flags do not match")
        if any(value is not False for value in zero_flags.values()):
            raise GapGraphContractError("gap graph registry cannot grant authority")
        return cls(payload)

    @staticmethod
    def _validate_derivation_matrix(
        payload: dict[str, Any], *, source_ids: set[str]
    ) -> None:
        matrix = payload["derivation_eligibility_matrix"]
        if not isinstance(matrix, list) or not matrix:
            raise GapGraphContractError("derivation eligibility matrix is required")
        identities: set[tuple[str, str]] = set()
        for item in matrix:
            _exact_fields(
                item,
                {
                    "relation",
                    "derivation",
                    "source_ids",
                    "required_authority_contract_id",
                    "gate_eligible",
                },
                field="derivation_eligibility",
            )
            relation = _token(item["relation"], field="matrix.relation")
            derivation = _token(item["derivation"], field="matrix.derivation")
            identity = (relation, derivation)
            if identity in identities:
                raise GapGraphContractError("duplicate derivation eligibility row")
            identities.add(identity)
            if relation not in payload["edge_relations"]:
                raise GapGraphContractError("matrix relation is not registered")
            if derivation not in (
                set(payload["eligible_derivations"])
                | set(payload["observation_only_derivations"])
            ):
                raise GapGraphContractError("matrix derivation is not registered")
            admitted_sources = set(
                _unique_tokens(item["source_ids"], field="matrix.source_ids")
            )
            if not admitted_sources.issubset(source_ids):
                raise GapGraphContractError("matrix source is not registered")
            authority = item["required_authority_contract_id"]
            if authority is not None:
                _token(authority, field="matrix.required_authority_contract_id")
            if item["gate_eligible"] is not True:
                raise GapGraphContractError("matrix row must explicitly admit its path")
            if relation in payload["causal_relations"] and authority is None:
                raise GapGraphContractError(
                    "causal relation requires an independent authority contract"
                )


class FrozenGapGraphPortfolio:
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
        registry: GapGraphContractRegistry,
    ) -> FrozenGapGraphPortfolio:
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GapGraphContractError("gap graph portfolio is unreadable") from exc
        _exact_fields(payload, _PORTFOLIO_FIELDS, field="portfolio")
        if payload["contract_id"] != "kjds-gap-graph-portfolio-fixture-v1":
            raise GapGraphContractError("unknown gap graph portfolio contract")
        if payload["license_class"] != "repository_owned_synthetic_contract_fixture":
            raise GapGraphContractError("portfolio fixture license is not admitted")
        if payload["data_classification"] != "synthetic_public":
            raise GapGraphContractError("portfolio fixture data class is not admitted")
        if payload["registry_sha256"] != registry.content_sha256:
            raise GapGraphContractError("portfolio registry binding drift")
        expected_sha = _hash(
            {key: value for key, value in payload.items() if key != "content_sha256"}
        )
        if _sha256(payload["content_sha256"], field="portfolio.content_sha256") != expected_sha:
            raise GapGraphContractError("portfolio content hash drift")
        _safe_projection(payload)
        cls._validate_sources(payload, registry=registry)
        node_ids = cls._validate_nodes(payload, registry=registry)
        edge_ids = cls._validate_edges(payload, registry=registry, node_ids=node_ids)
        gap_ids = cls._validate_gaps(
            payload,
            source_ids=set(registry.source_contracts),
            node_ids=node_ids,
            edge_ids=edge_ids,
        )
        cls._validate_opportunities(payload, registry=registry, gap_ids=gap_ids)
        return cls(payload)

    @staticmethod
    def _validate_sources(
        payload: dict[str, Any], *, registry: GapGraphContractRegistry
    ) -> None:
        values = payload["source_bindings"]
        if not isinstance(values, list):
            raise GapGraphContractError("source_bindings must be a list")
        found: set[str] = set()
        for item in values:
            _exact_fields(
                item,
                {
                    "source_id",
                    "contract_id",
                    "contract_version",
                    "source_ref",
                    "scope",
                    "data_as_of",
                    "evidence_binding",
                },
                field="source_binding",
            )
            source_id = _token(item["source_id"], field="source_binding.source_id")
            if source_id in found:
                raise GapGraphContractError("duplicate source binding")
            found.add(source_id)
            contract = registry.source_contracts.get(source_id)
            if contract is None:
                raise GapGraphContractError("source binding is not registered")
            if (
                item["contract_id"] != contract["contract_id"]
                or item["contract_version"] != contract["version"]
            ):
                raise GapGraphContractError("source binding contract drift")
            _token(item["source_ref"], field="source_binding.source_ref")
            scope = _exact_fields(
                item["scope"], _SCOPE_FIELDS, field="source_binding.scope"
            )
            _token(scope["tenant_ref"], field="source_binding.tenant_ref")
            _token(scope["entity_ref"], field="source_binding.entity_ref")
            _token(scope["store_ref"], field="source_binding.store_ref")
            _sha256(
                scope["scope_grant_authority_sha256"],
                field="source_binding.scope_authority",
            )
            data_as_of = _timestamp(
                item["data_as_of"], field="source_binding.data_as_of"
            )
            FrozenGapGraphPortfolio._validate_source_evidence_binding(
                item["evidence_binding"],
                source_id=source_id,
                source_ref=item["source_ref"],
                evidence_source=contract["evidence_source"],
                data_as_of=data_as_of,
            )
        if found != set(registry.source_contracts):
            raise GapGraphContractError("portfolio must bind every registered source")
        scopes = {_canonical(item["scope"]) for item in values}
        cutoffs = {item["data_as_of"] for item in values}
        if len(scopes) != 1 or len(cutoffs) != 1:
            raise GapGraphContractError(
                "all source bindings must share exact scope and data as_of"
            )

    @staticmethod
    def _validate_source_evidence_binding(
        value: Any,
        *,
        source_id: str,
        source_ref: str,
        evidence_source: str,
        data_as_of: datetime,
    ) -> None:
        binding = _exact_fields(
            value,
            _SOURCE_EVIDENCE_BINDING_FIELDS,
            field="source_binding.evidence_binding",
        )
        for field in ("citation_ref", "evidence_id", "source", "source_ref"):
            _token(binding[field], field=f"source_evidence.{field}")
        if binding["source"] != evidence_source:
            raise GapGraphContractError("source Evidence issuer drift")
        expected_source_ref = f"{evidence_source}://{source_ref}"
        if binding["source_ref"] != expected_source_ref:
            raise GapGraphContractError("source Evidence ref drift")
        _sha256(binding["evidence_sha256"], field="source_evidence.evidence_sha256")
        expected_claims = _hash({"source_id": source_id, "source_ref": source_ref})
        if _sha256(binding["claims_sha256"], field="source_evidence.claims_sha256") != expected_claims:
            raise GapGraphContractError("source Evidence claims hash drift")
        recorded_at = _timestamp(
            binding["recorded_at"], field="source_evidence.recorded_at"
        )
        effective_at = _timestamp(
            binding["effective_at"], field="source_evidence.effective_at"
        )
        effective_until = _timestamp(
            binding["effective_until"], field="source_evidence.effective_until"
        )
        if recorded_at > data_as_of:
            raise GapGraphContractError("source Evidence is hindsight backfill")
        if not effective_at <= data_as_of < effective_until:
            raise GapGraphContractError("source Evidence is not effective at data as_of")

    @staticmethod
    def _validate_nodes(
        payload: dict[str, Any], *, registry: GapGraphContractRegistry
    ) -> set[str]:
        values = payload["node_specs"]
        if not isinstance(values, list) or not values:
            raise GapGraphContractError("node_specs are required")
        found: set[str] = set()
        for item in values:
            _exact_fields(
                item,
                {"node_spec_id", "node_kind", "source_id", "source_item_ref"},
                field="node_spec",
            )
            node_id = _token(item["node_spec_id"], field="node_spec_id")
            if node_id in found:
                raise GapGraphContractError("duplicate node_spec_id")
            found.add(node_id)
            if item["node_kind"] not in registry.payload["node_kinds"]:
                raise GapGraphContractError("unknown node kind")
            if item["source_id"] not in registry.source_contracts:
                raise GapGraphContractError("node source is not registered")
            _token(item["source_item_ref"], field="node.source_item_ref")
        return found

    @staticmethod
    def _validate_edges(
        payload: dict[str, Any],
        *,
        registry: GapGraphContractRegistry,
        node_ids: set[str],
    ) -> set[str]:
        values = payload["edge_specs"]
        if not isinstance(values, list) or not values:
            raise GapGraphContractError("edge_specs are required")
        found: set[str] = set()
        for item in values:
            _exact_fields(
                item,
                {
                    "edge_spec_id",
                    "source_node_spec_id",
                    "target_node_spec_id",
                    "relation",
                    "derivation",
                    "source_id",
                    "source_item_ref",
                    "causal_claim",
                    "causal_authority",
                },
                field="edge_spec",
            )
            edge_id = _token(item["edge_spec_id"], field="edge_spec_id")
            if edge_id in found:
                raise GapGraphContractError("duplicate edge_spec_id")
            found.add(edge_id)
            if (
                item["source_node_spec_id"] not in node_ids
                or item["target_node_spec_id"] not in node_ids
            ):
                raise GapGraphContractError("edge endpoint is orphaned")
            if item["relation"] not in registry.payload["edge_relations"]:
                raise GapGraphContractError("unknown edge relation")
            derivations = set(registry.payload["eligible_derivations"]) | set(
                registry.payload["observation_only_derivations"]
            )
            if item["derivation"] not in derivations:
                raise GapGraphContractError("unknown edge derivation")
            if not isinstance(item["causal_claim"], bool):
                raise GapGraphContractError("causal_claim must be boolean")
            if item["causal_claim"] and item["relation"] not in registry.payload["causal_relations"]:
                raise GapGraphContractError("correlation cannot be declared causal")
            if item["source_id"] not in registry.source_contracts:
                raise GapGraphContractError("edge source is not registered")
            _token(item["source_item_ref"], field="edge.source_item_ref")
            matrix = next(
                (
                    row
                    for row in registry.payload["derivation_eligibility_matrix"]
                    if row["relation"] == item["relation"]
                    and row["derivation"] == item["derivation"]
                ),
                None,
            )
            if matrix is None or item["source_id"] not in matrix["source_ids"]:
                raise GapGraphContractError("edge relation/source/derivation is not admitted")
            authority = item["causal_authority"]
            required_authority = matrix["required_authority_contract_id"]
            if authority is not None:
                authority = _exact_fields(
                    authority,
                    {
                        "status",
                        "contract_id",
                        "version",
                        "claims_sha256",
                        "receipt_sha256",
                        "citation_refs",
                    },
                    field="edge.causal_authority",
                )
                if authority["status"] not in {
                    "verified",
                    "UNKNOWN",
                    "no_data",
                    "stale",
                    "blocked",
                }:
                    raise GapGraphContractError("causal authority status is invalid")
                _token(authority["contract_id"], field="causal_authority.contract_id")
                _token(authority["version"], field="causal_authority.version")
                _sha256(
                    authority["claims_sha256"],
                    field="causal_authority.claims_sha256",
                )
                _unique_tokens(
                    authority["citation_refs"],
                    field="causal_authority.citation_refs",
                )
                expected_receipt_sha256 = _hash(
                    {
                        key: value
                        for key, value in authority.items()
                        if key != "receipt_sha256"
                    }
                )
                if (
                    _sha256(
                        authority["receipt_sha256"],
                        field="causal_authority.receipt_sha256",
                    )
                    != expected_receipt_sha256
                ):
                    raise GapGraphContractError("causal authority receipt hash drift")
                if (
                    required_authority is not None
                    and authority["contract_id"] != required_authority
                ):
                    raise GapGraphContractError(
                        "causal authority contract does not match eligibility matrix"
                    )
            if required_authority is None and authority is not None:
                raise GapGraphContractError(
                    "non-causal edge cannot carry causal authority"
                )
        return found

    @staticmethod
    def _validate_gaps(
        payload: dict[str, Any],
        *,
        source_ids: set[str],
        node_ids: set[str],
        edge_ids: set[str],
    ) -> set[str]:
        values = payload["gap_specs"]
        if not isinstance(values, list) or not values:
            raise GapGraphContractError("gap_specs are required")
        expected_fields = {
            "gap_spec_id",
            "gap_kind",
            "benchmark_source_id",
            "benchmark_item_ref",
            "current_node_spec_id",
            "target_node_spec_id",
            "problem_node_spec_id",
            "required_edge_spec_ids",
            "expected_metric_id",
            "expected_cohort_ref",
            "expected_market",
            "expected_window_start",
            "expected_window_end",
            "expected_comparison_state",
            "expected_leader_label",
        }
        found: set[str] = set()
        for item in values:
            _exact_fields(item, expected_fields, field="gap_spec")
            gap_id = _token(item["gap_spec_id"], field="gap_spec_id")
            if gap_id in found:
                raise GapGraphContractError("duplicate gap_spec_id")
            found.add(gap_id)
            _token(item["gap_kind"], field="gap_kind")
            if item["benchmark_source_id"] != "strategic_benchmark":
                raise GapGraphContractError("gap benchmark source must be strategic benchmark")
            if item["benchmark_source_id"] not in source_ids:
                raise GapGraphContractError("gap benchmark source is not registered")
            for field in (
                "current_node_spec_id",
                "target_node_spec_id",
                "problem_node_spec_id",
            ):
                if item[field] not in node_ids:
                    raise GapGraphContractError("gap node reference is orphaned")
            required_edges = _unique_tokens(
                item["required_edge_spec_ids"], field="gap.required_edges"
            )
            if not set(required_edges).issubset(edge_ids):
                raise GapGraphContractError("gap edge reference is orphaned")
            for field in (
                "benchmark_item_ref",
                "expected_metric_id",
                "expected_cohort_ref",
                "expected_market",
                "expected_comparison_state",
                "expected_leader_label",
            ):
                _token(item[field], field=f"gap.{field}")
            start = _timestamp(item["expected_window_start"], field="gap.window_start")
            end = _timestamp(item["expected_window_end"], field="gap.window_end")
            if start >= end:
                raise GapGraphContractError("gap benchmark window is invalid")
        return found

    @staticmethod
    def _validate_opportunities(
        payload: dict[str, Any],
        *,
        registry: GapGraphContractRegistry,
        gap_ids: set[str],
    ) -> None:
        values = payload["opportunity_specs"]
        if not isinstance(values, list) or not values:
            raise GapGraphContractError("opportunity_specs are required")
        expected_fields = {
            "opportunity_spec_id",
            "proposed_action",
            "gap_spec_ids",
            "dependency_opportunity_ids",
            "alternatives",
            "decision_policy",
            "maximum_loss",
            "downside",
            "invalidation_conditions",
            "rollback",
        }
        ids: list[str] = []
        for item in values:
            _exact_fields(item, expected_fields, field="opportunity_spec")
            opportunity_id = _token(
                item["opportunity_spec_id"], field="opportunity_spec_id"
            )
            if opportunity_id in ids:
                raise GapGraphContractError("duplicate opportunity_spec_id")
            ids.append(opportunity_id)
            if item["proposed_action"] not in registry.payload["opportunity_actions"]:
                raise GapGraphContractError("unknown proposed action")
            if not set(
                _unique_tokens(item["gap_spec_ids"], field="opportunity.gaps")
            ).issubset(gap_ids):
                raise GapGraphContractError("opportunity gap is orphaned")
            _unique_tokens(
                item["dependency_opportunity_ids"],
                field="opportunity.dependencies",
                allow_empty=True,
            )
            FrozenGapGraphPortfolio._validate_alternatives(item, registry=registry)
            FrozenGapGraphPortfolio._validate_decision_policy(
                item["decision_policy"], registry=registry
            )
            for field in ("maximum_loss", "downside"):
                value = _exact_fields(
                    item[field],
                    {
                        "status",
                        "value",
                        "unit",
                        "policy_id",
                        "policy_version",
                        "policy_sha256",
                        "source_id",
                        "source_item_ref",
                        "citation_refs",
                    },
                    field=f"opportunity.{field}",
                )
                if value["status"] not in {"bounded", "UNKNOWN", "no_data", "stale"}:
                    raise GapGraphContractError(f"{field} status is invalid")
                FrozenGapGraphPortfolio._non_negative_decimal(
                    value["value"], field=f"{field}.value"
                )
                _token(value["unit"], field=f"{field}.unit")
                FrozenGapGraphPortfolio._validate_policy_identity(
                    value, field=field
                )
                source_id = _token(value["source_id"], field=f"{field}.source_id")
                if source_id not in registry.source_contracts:
                    raise GapGraphContractError(f"{field} source is not registered")
                _token(
                    value["source_item_ref"], field=f"{field}.source_item_ref"
                )
                _unique_tokens(value["citation_refs"], field=f"{field}.citation_refs")
            _unique_tokens(
                item["invalidation_conditions"],
                field="opportunity.invalidation_conditions",
            )
            rollback = _exact_fields(
                item["rollback"],
                {
                    "status",
                    "artifact_sha256",
                    "policy_id",
                    "policy_version",
                    "policy_sha256",
                    "source_id",
                    "source_item_ref",
                    "citation_refs",
                    "trigger_codes",
                },
                field="opportunity.rollback",
            )
            if rollback["status"] not in {"verified", "UNKNOWN", "no_data", "stale"}:
                raise GapGraphContractError("rollback status is invalid")
            _sha256(rollback["artifact_sha256"], field="rollback.artifact_sha256")
            FrozenGapGraphPortfolio._validate_policy_identity(
                rollback, field="rollback"
            )
            rollback_source_id = _token(
                rollback["source_id"], field="rollback.source_id"
            )
            if rollback_source_id not in registry.source_contracts:
                raise GapGraphContractError("rollback source is not registered")
            _token(
                rollback["source_item_ref"], field="rollback.source_item_ref"
            )
            _unique_tokens(rollback["citation_refs"], field="rollback.citation_refs")
            _unique_tokens(rollback["trigger_codes"], field="rollback.trigger_codes")
        id_set = set(ids)
        graph: dict[str, list[str]] = {}
        for item in values:
            dependencies = list(item["dependency_opportunity_ids"])
            if item["opportunity_spec_id"] in dependencies:
                raise GapGraphContractError("opportunity cannot depend on itself")
            if not set(dependencies).issubset(id_set):
                raise GapGraphContractError("opportunity dependency is orphaned")
            graph[item["opportunity_spec_id"]] = dependencies
        FrozenGapGraphPortfolio._require_acyclic(graph)

    @staticmethod
    def _validate_alternatives(
        item: dict[str, Any], *, registry: GapGraphContractRegistry
    ) -> None:
        alternatives = item["alternatives"]
        if not isinstance(alternatives, list):
            raise GapGraphContractError("alternatives must be a list")
        actions: set[str] = set()
        selected: list[str] = []
        for alternative in alternatives:
            _exact_fields(
                alternative,
                {"action", "status", "disposition", "reason_code"},
                field="alternative",
            )
            action = _token(alternative["action"], field="alternative.action")
            if action in actions:
                raise GapGraphContractError("duplicate alternative action")
            actions.add(action)
            if alternative["disposition"] not in {"selected", "rejected"}:
                raise GapGraphContractError("alternative disposition is invalid")
            if alternative["disposition"] == "selected":
                selected.append(action)
            if alternative["status"] not in {
                "ready",
                "UNKNOWN",
                "no_data",
                "stale",
                "blocked",
            }:
                raise GapGraphContractError("alternative status is invalid")
            _token(alternative["reason_code"], field="alternative.reason_code")
        if actions != set(registry.payload["opportunity_actions"]):
            raise GapGraphContractError("all five strategic alternatives are required")
        if selected != [item["proposed_action"]]:
            raise GapGraphContractError("selected alternative does not match action")

    @staticmethod
    def _validate_decision_policy(
        value: Any, *, registry: GapGraphContractRegistry
    ) -> None:
        policy = _exact_fields(
            value,
            {
                "status",
                "policy_id",
                "policy_version",
                "policy_sha256",
                "source_id",
                "source_item_ref",
                "citation_refs",
            },
            field="decision_policy",
        )
        if policy["status"] not in {
            "verified",
            "UNKNOWN",
            "no_data",
            "stale",
            "blocked",
        }:
            raise GapGraphContractError("decision policy status is invalid")
        FrozenGapGraphPortfolio._validate_policy_identity(
            policy, field="decision_policy"
        )
        source_id = _token(
            policy["source_id"], field="decision_policy.source_id"
        )
        if source_id not in registry.source_contracts:
            raise GapGraphContractError("decision policy source is not registered")
        _token(
            policy["source_item_ref"], field="decision_policy.source_item_ref"
        )
        _unique_tokens(
            policy["citation_refs"], field="decision_policy.citation_refs"
        )

    @staticmethod
    def _validate_policy_identity(value: dict[str, Any], *, field: str) -> None:
        policy_id = _token(value["policy_id"], field=f"{field}.policy_id")
        version = _token(
            value["policy_version"], field=f"{field}.policy_version"
        )
        expected = _hash({"policy_id": policy_id, "version": version})
        if _sha256(value["policy_sha256"], field=f"{field}.policy_sha256") != expected:
            raise GapGraphContractError(f"{field} policy hash drift")

    @staticmethod
    def _non_negative_decimal(value: Any, *, field: str) -> Decimal:
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise GapGraphContractError(f"{field} must be decimal") from exc
        if not parsed.is_finite() or parsed < 0:
            raise GapGraphContractError(f"{field} must be finite and non-negative")
        return parsed

    @staticmethod
    def _require_acyclic(graph: dict[str, list[str]]) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> None:
            if node in visiting:
                raise GapGraphContractError("opportunity dependency cycle detected")
            if node in visited:
                return
            visiting.add(node)
            for dependency in graph[node]:
                visit(dependency)
            visiting.remove(node)
            visited.add(node)

        for node in graph:
            visit(node)


class GovernedGapGraphWorkspace:
    """Read-only GapGraph and strategic opportunity admission boundary."""

    CONTRACT_ID = "kjds-governed-gap-graph-observation-v1"

    def __init__(
        self,
        *,
        scope_grants,
        read_authority: GapGraphReadAuthority,
        citation_authority: GapGraphCitationAuthority,
        causal_authority: GapGraphCausalAuthority | None = None,
        registry_path: str | Path,
        portfolio_path: str | Path,
        clock=None,
    ) -> None:
        self.scope_grants = scope_grants
        self.read_authority = read_authority
        self.citation_authority = citation_authority
        self.causal_authority = causal_authority
        self.clock = clock or (lambda: datetime.now(UTC))
        self.registry = GapGraphContractRegistry.load(registry_path)
        self.portfolio = FrozenGapGraphPortfolio.load(
            portfolio_path, registry=self.registry
        )
        self._lock = threading.RLock()
        self._runs: dict[
            tuple[str, str, str, str, str, str], tuple[str, dict[str, Any]]
        ] = {}

    @property
    def portfolio_ref(self) -> str:
        return self.portfolio.ref

    def evaluate(
        self,
        *,
        principal: Principal,
        store_ref: str,
        as_of: datetime,
        portfolio_ref: str,
    ) -> dict[str, Any]:
        if not principal.has_any_role("operator", "monitor", "reviewer", "risk", "admin"):
            raise PermissionError("gap graph read role required")
        if not principal.can_access_store(store_ref):
            raise PermissionError("store is outside authorized scope")
        if portfolio_ref != self.portfolio.ref:
            raise GapGraphContractError("portfolio_ref hash drift detected")
        cutoff = _timestamp(as_of, field="as_of")
        checked_at = _timestamp(self.clock(), field="authority_checked_at")
        if cutoff > checked_at:
            raise GapGraphContractError("as_of cannot be later than trusted current time")
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
        if not exact_scope:
            raw_status = str(entity_scope.get("status", "no_data"))
            status = (
                raw_status
                if raw_status in self.registry.payload["allowed_states"]
                else "blocked"
            )
            if raw_status == "ready":
                status = "not_visible"
            return self._blocked_observation(
                principal=principal,
                store_ref=store_ref,
                cutoff=cutoff,
                checked_at=checked_at,
                portfolio_ref=portfolio_ref,
                status=status,
                reasons=["exact_current_scope_authority_required"],
                source_statuses=[],
            )
        authority_sha256 = _sha256(
            entity_scope["authority_sha256"], field="scope.authority_sha256"
        )
        entity_scope = {**entity_scope, "authority_sha256": authority_sha256}
        scope = {
            "tenant_ref": principal.tenant_ref,
            "entity_ref": _token(entity_scope["entity_ref"], field="entity_ref"),
            "store_ref": store_ref,
            "scope_grant_authority_sha256": authority_sha256,
        }
        frozen_binding = self.portfolio.payload["source_bindings"][0]
        if scope != frozen_binding["scope"]:
            return self._blocked_observation(
                principal=principal,
                store_ref=store_ref,
                cutoff=cutoff,
                checked_at=checked_at,
                portfolio_ref=portfolio_ref,
                status="not_visible",
                reasons=["portfolio_exact_scope_authority_binding_mismatch"],
                source_statuses=[],
                scope=scope,
            )
        if cutoff != _timestamp(
            frozen_binding["data_as_of"], field="portfolio.data_as_of"
        ):
            return self._blocked_observation(
                principal=principal,
                store_ref=store_ref,
                cutoff=cutoff,
                checked_at=checked_at,
                portfolio_ref=portfolio_ref,
                status="blocked",
                reasons=["portfolio_data_as_of_binding_mismatch"],
                source_statuses=[],
                scope=scope,
            )
        try:
            raw_bundle = self.read_authority.read_bundle(
                principal=principal,
                entity_scope=deepcopy(entity_scope),
                store_ref=store_ref,
                as_of=cutoff,
                portfolio_ref=portfolio_ref,
                source_bindings=deepcopy(self.portfolio.payload["source_bindings"]),
            )
            _safe_projection(raw_bundle, path="read_bundle")
        except (GapGraphContractError, KeyError, RuntimeError, TypeError, ValueError):
            return self._blocked_observation(
                principal=principal,
                store_ref=store_ref,
                cutoff=cutoff,
                checked_at=checked_at,
                portfolio_ref=portfolio_ref,
                status="UNKNOWN",
                reasons=["read_authority_unavailable_or_unsafe"],
                source_statuses=[],
                scope=scope,
                include_no_action_stubs=True,
            )
        request = {
            "contract_id": self.CONTRACT_ID,
            "registry_sha256": self.registry.content_sha256,
            "portfolio_ref": portfolio_ref,
            "scope": scope,
            "actor_id": principal.actor_id,
            "as_of": cutoff.isoformat(),
            "read_bundle_fingerprint_sha256": _hash(raw_bundle),
        }
        provisional_request_sha256 = _hash(request)
        scope_key = (
            principal.tenant_ref,
            scope["entity_ref"],
            store_ref,
            authority_sha256,
            cutoff.isoformat(),
            portfolio_ref,
        )
        try:
            observation = self._evaluate_ready(
                principal=principal,
                entity_scope=entity_scope,
                scope=scope,
                cutoff=cutoff,
                checked_at=checked_at,
                portfolio_ref=portfolio_ref,
                request=request,
                raw_bundle=raw_bundle,
            )
        except _GateFailure as exc:
            return self._blocked_observation(
                principal=principal,
                store_ref=store_ref,
                cutoff=cutoff,
                checked_at=checked_at,
                portfolio_ref=portfolio_ref,
                status=exc.status,
                reasons=[exc.reason],
                source_statuses=self._source_statuses(raw_bundle),
                scope=scope,
                request_sha256=provisional_request_sha256,
                failure_subject_sha256=exc.subject_sha256,
                include_no_action_stubs=True,
            )
        except GapGraphContractError:
            return self._blocked_observation(
                principal=principal,
                store_ref=store_ref,
                cutoff=cutoff,
                checked_at=checked_at,
                portfolio_ref=portfolio_ref,
                status="blocked",
                reasons=["read_projection_contract_or_hash_invalid"],
                source_statuses=[],
                scope=scope,
                request_sha256=provisional_request_sha256,
                include_no_action_stubs=True,
            )
        request_sha256 = observation["request_sha256"]
        with self._lock:
            prior = self._runs.get(scope_key)
            if prior is not None:
                prior_sha256, prior_observation = prior
                if prior_sha256 != request_sha256:
                    raise GapGraphConflictError(
                        "portfolio_ref conflicts with immutable source projection"
                    )
                return deepcopy(prior_observation)
            self._runs[scope_key] = (request_sha256, deepcopy(observation))
        return deepcopy(observation)

    @staticmethod
    def _exact_scope(
        *,
        principal: Principal,
        store_ref: str,
        entity_scope: dict[str, Any],
    ) -> bool:
        authority = entity_scope.get("authority_sha256")
        entity_ref = entity_scope.get("entity_ref")
        return (
            entity_scope.get("status") == "ready"
            and entity_scope.get("tenant_ref") == principal.tenant_ref
            and entity_scope.get("store_ref") == store_ref
            and isinstance(entity_ref, str)
            and bool(entity_ref)
            and isinstance(authority, str)
            and bool(_HEX64.fullmatch(authority.lower()))
        )

    def _evaluate_ready(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        scope: dict[str, str],
        cutoff: datetime,
        checked_at: datetime,
        portfolio_ref: str,
        request: dict[str, Any],
        raw_bundle: Any,
    ) -> dict[str, Any]:
        sources, citations = self._validate_bundle(
            raw_bundle,
            principal=principal,
            entity_scope=entity_scope,
            scope=scope,
            cutoff=cutoff,
            checked_at=checked_at,
            portfolio_ref=portfolio_ref,
        )
        item_index = {
            (source_id, item["item_ref"]): item
            for source_id, source in sources.items()
            for item in source["items"]
        }
        nodes = self._build_nodes(
            item_index=item_index,
            sources=sources,
            citations=citations,
            scope=scope,
            portfolio_ref=portfolio_ref,
        )
        edges = self._build_edges(
            item_index=item_index,
            nodes=nodes,
            citations=citations,
            scope=scope,
            principal=principal,
            entity_scope=entity_scope,
            cutoff=cutoff,
            checked_at=checked_at,
            portfolio_ref=portfolio_ref,
        )
        verified_request = {
            **request,
            "citation_receipts_sha256": _hash(
                [citations[key] for key in sorted(citations)]
            ),
            "causal_authority_receipts_sha256": _hash(
                [
                    edge["causal_authority_receipt"]
                    for edge in edges
                    if edge["causal_authority_receipt"] is not None
                ]
            ),
        }
        request_sha256 = _hash(verified_request)
        gaps = self._build_gaps(
            item_index=item_index,
            nodes=nodes,
            edges=edges,
            citations=citations,
            scope=scope,
            portfolio_ref=portfolio_ref,
        )
        opportunities = self._build_opportunities(
            item_index=item_index,
            gaps=gaps,
            citations=citations,
            scope=scope,
            portfolio_ref=portfolio_ref,
        )
        blockers = sorted(
            {
                reason
                for collection in (nodes, edges, gaps, opportunities)
                for item in collection
                for reason in item["blockers"]
            }
        )
        admitted = (
            not blockers
            and all(item["eligible_for_gate"] for item in nodes)
            and all(item["eligible_for_gate"] for item in edges)
            and all(item["status"] == "ready" for item in gaps)
            and all(item["admission_status"] == "admitted" for item in opportunities)
        )
        observation = {
            "contract_id": self.CONTRACT_ID,
            "status": "ready" if admitted else "blocked",
            "portfolio_status": "admitted" if admitted else "not_admitted",
            "reason_codes": blockers,
            "run_id": f"ggr_{request_sha256[:32]}",
            "request_sha256": request_sha256,
            "registry_ref": self.registry.ref,
            "portfolio_ref": portfolio_ref,
            "scope": scope,
            "as_of": cutoff.isoformat(),
            "source_statuses": [
                {
                    "source_id": source_id,
                    "status": source["status"],
                    "source_ref": source["source_ref"],
                    "projection_sha256": source["projection_sha256"],
                }
                for source_id, source in sorted(sources.items())
            ],
            "nodes": nodes,
            "edges": edges,
            "gaps": gaps,
            "opportunities": opportunities,
            "counts": {
                "sources": len(sources),
                "citations": len(citations),
                "nodes": len(nodes),
                "edges": len(edges),
                "gaps": len(gaps),
                "opportunities": len(opportunities),
            },
            "global_top1_claim": False,
            "correlation_is_causation": False,
            "generated_and_inferred_are_observation_only": True,
            "observation_only": True,
            "governance": deepcopy(self.registry.payload["zero_authority_flags"]),
            "write_counts": self._zero_write_counts(),
        }
        observation["observation_sha256"] = _hash(observation)
        return observation

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
    ) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
        bundle = _exact_fields(raw, _BUNDLE_FIELDS, field="read_bundle")
        if bundle["contract_id"] != self.registry.payload["read_bundle_contract_id"]:
            raise GapGraphContractError("read bundle contract drift")
        if bundle["portfolio_ref"] != portfolio_ref:
            raise GapGraphContractError("read bundle portfolio drift")
        if self._scope(bundle["scope"], field="read_bundle.scope") != scope:
            raise _GateFailure("not_visible", "read_bundle_exact_scope_mismatch")
        if _timestamp(bundle["as_of"], field="read_bundle.as_of") != cutoff:
            raise GapGraphContractError("read bundle as_of drift")
        expected_bundle_sha = _hash(
            {key: value for key, value in bundle.items() if key != "bundle_sha256"}
        )
        if _sha256(bundle["bundle_sha256"], field="bundle_sha256") != expected_bundle_sha:
            raise GapGraphContractError("read bundle hash drift")
        bindings = {
            item["source_id"]: item
            for item in self.portfolio.payload["source_bindings"]
        }
        raw_sources = bundle["sources"]
        if not isinstance(raw_sources, list) or len(raw_sources) != len(bindings):
            raise GapGraphContractError("read bundle source conservation failed")
        sources: dict[str, dict[str, Any]] = {}
        citations: dict[str, dict[str, Any]] = {}
        for raw_source in raw_sources:
            source = self._validate_source(
                raw_source,
                scope=scope,
                cutoff=cutoff,
                bindings=bindings,
            )
            source_id = source["source_id"]
            if source_id in sources:
                raise GapGraphContractError("duplicate source projection")
            sources[source_id] = source
            if source["status"] != "ready":
                raise _GateFailure(
                    source["status"], f"source_{source_id}_{source['status']}"
                )
            root_binding = source["evidence_binding"]
            root_citation_binding = {
                "citation_ref": root_binding["citation_ref"],
                "evidence_sha256": root_binding["evidence_sha256"],
                "claims_sha256": root_binding["claims_sha256"],
            }
            try:
                root_receipt = self._verify_citation(
                    principal=principal,
                    entity_scope=entity_scope,
                    scope=scope,
                    cutoff=cutoff,
                    checked_at=checked_at,
                    binding=root_citation_binding,
                    source=source,
                    expected_evidence_binding=root_binding,
                )
            except _GateFailure as exc:
                raise self._citation_gate_failure(
                    exc,
                    source_id=source_id,
                    binding=root_citation_binding,
                ) from exc
            citations[root_receipt["citation_ref"]] = root_receipt
            for item in source["items"]:
                if item["state"] != "ready":
                    raise _GateFailure(
                        item["state"], f"source_item_{item['item_ref']}_{item['state']}"
                    )
                for binding in item["citations"]:
                    try:
                        receipt = self._verify_citation(
                            principal=principal,
                            entity_scope=entity_scope,
                            scope=scope,
                            cutoff=cutoff,
                            checked_at=checked_at,
                            binding=binding,
                            source=source,
                            expected_evidence_binding=None,
                        )
                    except _GateFailure as exc:
                        raise self._citation_gate_failure(
                            exc,
                            source_id=source_id,
                            binding=binding,
                        ) from exc
                    prior = citations.get(receipt["citation_ref"])
                    if prior is not None and prior != receipt:
                        raise _GateFailure(
                            "blocked", "duplicate_citation_binding_conflict"
                        )
                    citations[receipt["citation_ref"]] = receipt
        if set(sources) != set(bindings):
            raise GapGraphContractError("read bundle source set drift")
        return sources, citations

    @staticmethod
    def _citation_gate_failure(
        failure: _GateFailure,
        *,
        source_id: str,
        binding: dict[str, str],
    ) -> _GateFailure:
        return _GateFailure(
            failure.status,
            failure.reason,
            subject_sha256=_hash(
                {
                    "source_id": source_id,
                    "citation_ref": binding["citation_ref"],
                    "evidence_sha256": binding["evidence_sha256"],
                    "claims_sha256": binding["claims_sha256"],
                }
            ),
        )

    def _validate_source(
        self,
        raw: Any,
        *,
        scope: dict[str, str],
        cutoff: datetime,
        bindings: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        source = _exact_fields(raw, _SOURCE_FIELDS, field="source_projection")
        source_id = _token(source["source_id"], field="source_id")
        binding = bindings.get(source_id)
        if binding is None:
            raise GapGraphContractError("source projection is not bound")
        if (
            source["contract_id"] != binding["contract_id"]
            or source["contract_version"] != binding["contract_version"]
            or source["source_ref"] != binding["source_ref"]
        ):
            raise GapGraphContractError("source projection contract or ref drift")
        if source["evidence_binding"] != binding["evidence_binding"]:
            raise GapGraphContractError("source projection Evidence binding drift")
        status = str(source["status"])
        if status not in self.registry.payload["allowed_states"]:
            raise GapGraphContractError("source status is invalid")
        if self._scope(source["scope"], field="source.scope") != scope:
            raise _GateFailure("not_visible", "source_projection_exact_scope_mismatch")
        if _timestamp(source["as_of"], field="source.as_of") != cutoff:
            raise GapGraphContractError("source projection as_of drift")
        expected_sha = _hash(
            {key: value for key, value in source.items() if key != "projection_sha256"}
        )
        if _sha256(source["projection_sha256"], field="source.projection_sha256") != expected_sha:
            raise GapGraphContractError("source projection hash drift")
        items = source["items"]
        if not isinstance(items, list):
            raise GapGraphContractError("source items must be a list")
        refs: set[str] = set()
        normalized_items: list[dict[str, Any]] = []
        for raw_item in items:
            item = self._validate_item(raw_item)
            if item["item_ref"] in refs:
                raise GapGraphContractError("duplicate source item")
            refs.add(item["item_ref"])
            normalized_items.append(item)
        return {**source, "items": normalized_items}

    def _validate_item(self, raw: Any) -> dict[str, Any]:
        item = _exact_fields(raw, _ITEM_FIELDS, field="source_item")
        _token(item["item_ref"], field="item_ref")
        _token(item["item_kind"], field="item_kind")
        if item["state"] not in self.registry.payload["allowed_states"]:
            raise GapGraphContractError("item state is invalid")
        derivations = set(self.registry.payload["eligible_derivations"]) | set(
            self.registry.payload["observation_only_derivations"]
        )
        if item["derivation"] not in derivations:
            raise GapGraphContractError("item derivation is invalid")
        if not isinstance(item["attributes"], dict):
            raise GapGraphContractError("item attributes must be an object")
        _safe_projection(item["attributes"], path="item.attributes")
        raw_citations = item["citations"]
        if not isinstance(raw_citations, list) or not raw_citations:
            raise GapGraphContractError("item citations are required")
        citations: list[dict[str, str]] = []
        refs: set[str] = set()
        for raw_binding in raw_citations:
            binding = _exact_fields(
                raw_binding, _CITATION_BINDING_FIELDS, field="citation_binding"
            )
            citation_ref = _token(binding["citation_ref"], field="citation_ref")
            if citation_ref in refs:
                raise GapGraphContractError("duplicate item citation")
            refs.add(citation_ref)
            citations.append(
                {
                    "citation_ref": citation_ref,
                    "evidence_sha256": _sha256(
                        binding["evidence_sha256"], field="citation.evidence_sha256"
                    ),
                    "claims_sha256": _sha256(
                        binding["claims_sha256"], field="citation.claims_sha256"
                    ),
                }
            )
        claims_sha256 = _hash(item["attributes"])
        if any(
            binding["claims_sha256"] != claims_sha256 for binding in citations
        ):
            raise GapGraphContractError("item citation does not bind canonical claims")
        expected_sha = _hash(
            {key: value for key, value in item.items() if key != "item_sha256"}
        )
        if _sha256(item["item_sha256"], field="item_sha256") != expected_sha:
            raise GapGraphContractError("source item hash drift")
        return {**item, "citations": citations}

    def _verify_citation(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        scope: dict[str, str],
        cutoff: datetime,
        checked_at: datetime,
        binding: dict[str, str],
        source: dict[str, Any],
        expected_evidence_binding: dict[str, Any] | None,
    ) -> dict[str, Any]:
        try:
            raw = self.citation_authority.verify_citation(
                principal=principal,
                entity_scope=deepcopy(entity_scope),
                store_ref=scope["store_ref"],
                data_as_of=cutoff,
                authority_checked_at=checked_at,
                citation_ref=binding["citation_ref"],
                evidence_sha256=binding["evidence_sha256"],
                claims_sha256=binding["claims_sha256"],
                source_contract_id=source["contract_id"],
                source_contract_version=source["contract_version"],
            )
        except (KeyError, RuntimeError, TypeError, ValueError) as exc:
            raise _GateFailure("blocked", "citation_authority_invalid") from exc
        receipt = _exact_fields(raw, _CITATION_RECEIPT_FIELDS, field="citation_receipt")
        if receipt["contract_id"] != self.registry.payload["citation_authority_contract_id"]:
            raise _GateFailure("blocked", "citation_authority_contract_drift")
        status = str(receipt["status"])
        if status != "ready":
            if status not in self.registry.payload["allowed_states"]:
                status = "blocked"
            raise _GateFailure(status, f"citation_{status}")
        if (
            receipt["citation_ref"] != binding["citation_ref"]
            or _sha256(receipt["evidence_sha256"], field="receipt.evidence_sha256")
            != binding["evidence_sha256"]
            or _sha256(receipt["claims_sha256"], field="receipt.claims_sha256")
            != binding["claims_sha256"]
        ):
            raise _GateFailure("blocked", "citation_identity_or_hash_drift")
        source_contract = self.registry.source_contracts[source["source_id"]]
        if (
            receipt["source_contract_id"] != source_contract["contract_id"]
            or receipt["source_contract_version"] != source_contract["version"]
            or _sha256(
                receipt["source_contract_sha256"], field="source_contract_sha256"
            )
            != source_contract["contract_sha256"]
        ):
            raise _GateFailure("blocked", "citation_source_contract_drift")
        if self._scope(receipt["scope"], field="citation.scope") != scope:
            raise _GateFailure("not_visible", "citation_exact_scope_mismatch")
        for field in ("evidence_id", "source", "source_ref"):
            _token(receipt[field], field=f"citation.{field}")
        if receipt["source"] != source_contract["evidence_source"]:
            raise _GateFailure("blocked", "citation_evidence_source_drift")
        expected_source_ref = (
            f"{source_contract['evidence_source']}://{binding['citation_ref']}"
        )
        if (
            expected_evidence_binding is None
            and receipt["source_ref"] != expected_source_ref
        ):
            raise _GateFailure("blocked", "citation_evidence_ref_drift")
        recorded_at = _timestamp(receipt["recorded_at"], field="citation.recorded_at")
        effective_at = _timestamp(receipt["effective_at"], field="citation.effective_at")
        effective_until = _timestamp(
            receipt["effective_until"], field="citation.effective_until"
        )
        if recorded_at > cutoff:
            raise _GateFailure("blocked", "citation_recorded_after_as_of")
        if not effective_at <= cutoff < effective_until:
            raise _GateFailure("stale", "citation_not_effective_as_of")
        if receipt["integrity_status"] != "valid":
            raise _GateFailure("blocked", "citation_integrity_invalid")
        if receipt["current"] is not True:
            raise _GateFailure("blocked", "citation_currentness_invalid")
        grade = str(receipt["grade"])
        if _GRADE_ORDER.get(grade, -1) < _GRADE_ORDER["B"]:
            raise _GateFailure("blocked", "citation_grade_below_required")
        if expected_evidence_binding is not None:
            expected = {
                key: expected_evidence_binding[key]
                for key in _SOURCE_EVIDENCE_BINDING_FIELDS
            }
            actual = {
                "citation_ref": receipt["citation_ref"],
                "evidence_id": receipt["evidence_id"],
                "evidence_sha256": receipt["evidence_sha256"],
                "source": receipt["source"],
                "source_ref": receipt["source_ref"],
                "recorded_at": recorded_at.isoformat(),
                "effective_at": effective_at.isoformat(),
                "effective_until": effective_until.isoformat(),
                "claims_sha256": receipt["claims_sha256"],
            }
            if actual != expected:
                raise _GateFailure("blocked", "source_evidence_binding_drift")
        return {
            "contract_id": receipt["contract_id"],
            "status": receipt["status"],
            "citation_ref": receipt["citation_ref"],
            "evidence_id": receipt["evidence_id"],
            "evidence_sha256": receipt["evidence_sha256"],
            "source": receipt["source"],
            "source_ref": receipt["source_ref"],
            "claims_sha256": receipt["claims_sha256"],
            "source_contract_id": receipt["source_contract_id"],
            "source_contract_version": receipt["source_contract_version"],
            "source_contract_sha256": receipt["source_contract_sha256"],
            "scope": deepcopy(scope),
            "recorded_at": recorded_at.isoformat(),
            "effective_at": effective_at.isoformat(),
            "effective_until": effective_until.isoformat(),
            "integrity_status": receipt["integrity_status"],
            "current": receipt["current"],
            "grade": grade,
        }

    def _build_nodes(
        self,
        *,
        item_index: dict[tuple[str, str], dict[str, Any]],
        sources: dict[str, dict[str, Any]],
        citations: dict[str, dict[str, Any]],
        scope: dict[str, str],
        portfolio_ref: str,
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for spec in self.portfolio.payload["node_specs"]:
            item = self._item(item_index, spec["source_id"], spec["source_item_ref"])
            blockers: list[str] = []
            if item["item_kind"] != spec["node_kind"]:
                blockers.append("node_kind_drift")
            if item["derivation"] in self.registry.payload["observation_only_derivations"]:
                blockers.append("generated_or_inferred_node_observation_only")
            if item["state"] != "ready":
                blockers.append(f"node_state_{item['state']}")
            node_id = f"ggn_{_hash({'scope': scope, 'portfolio': portfolio_ref, 'spec': spec['node_spec_id'], 'item': item['item_sha256']})[:32]}"
            result.append(
                {
                    "node_id": node_id,
                    "node_spec_id": spec["node_spec_id"],
                    "node_kind": spec["node_kind"],
                    "source_id": spec["source_id"],
                    "source_ref": sources[spec["source_id"]]["source_ref"],
                    "source_item_ref": item["item_ref"],
                    "source_item_sha256": item["item_sha256"],
                    "state": item["state"],
                    "derivation": item["derivation"],
                    "citations": self._citation_projection(item, citations=citations),
                    "eligible_for_gate": not blockers,
                    "blockers": blockers,
                    "observation_only": True,
                }
            )
        return result

    def _build_edges(
        self,
        *,
        item_index: dict[tuple[str, str], dict[str, Any]],
        nodes: list[dict[str, Any]],
        citations: dict[str, dict[str, Any]],
        scope: dict[str, str],
        principal: Principal,
        entity_scope: dict[str, Any],
        cutoff: datetime,
        checked_at: datetime,
        portfolio_ref: str,
    ) -> list[dict[str, Any]]:
        node_by_spec = {item["node_spec_id"]: item for item in nodes}
        result: list[dict[str, Any]] = []
        for spec in self.portfolio.payload["edge_specs"]:
            source_node = node_by_spec.get(spec["source_node_spec_id"])
            target_node = node_by_spec.get(spec["target_node_spec_id"])
            if source_node is None or target_node is None:
                raise GapGraphContractError("edge endpoint is missing")
            item = self._item(item_index, spec["source_id"], spec["source_item_ref"])
            attributes = item["attributes"]
            blockers: list[str] = []
            expected_attributes = {
                "source_node_spec_id": spec["source_node_spec_id"],
                "target_node_spec_id": spec["target_node_spec_id"],
                "relation": spec["relation"],
            }
            if any(attributes.get(key) != value for key, value in expected_attributes.items()):
                blockers.append("edge_endpoint_or_relation_drift")
            if item["derivation"] != spec["derivation"]:
                blockers.append("edge_derivation_drift")
            if item["derivation"] in self.registry.payload["observation_only_derivations"]:
                blockers.append("generated_or_inferred_edge_observation_only")
            matrix = next(
                (
                    row
                    for row in self.registry.payload["derivation_eligibility_matrix"]
                    if row["relation"] == spec["relation"]
                    and row["derivation"] == item["derivation"]
                ),
                None,
            )
            if (
                matrix is None
                or spec["source_id"] not in matrix["source_ids"]
                or matrix["gate_eligible"] is not True
            ):
                blockers.append("edge_relation_source_authority_path_not_admitted")
            causal_relation = spec["relation"] in self.registry.payload["causal_relations"]
            if spec["causal_claim"]:
                if (
                    not causal_relation
                    or item["derivation"] != "causal"
                ):
                    blockers.append("causal_claim_not_verified")
            elif causal_relation:
                blockers.append("causal_relation_requires_explicit_claim")
            authority = spec["causal_authority"]
            required_authority = (
                matrix["required_authority_contract_id"] if matrix else None
            )
            causal_authority_status = (
                "not_required" if required_authority is None else "UNKNOWN"
            )
            causal_authority_receipt: dict[str, Any] | None = None
            if required_authority is not None:
                if authority is None:
                    blockers.append("independent_causal_authority_UNKNOWN")
                else:
                    if (
                        authority["status"] != "verified"
                        or authority["contract_id"] != required_authority
                    ):
                        blockers.append("independent_causal_authority_not_verified")
                    authority_citations = [
                        citations.get(citation_ref)
                        for citation_ref in authority["citation_refs"]
                    ]
                    if any(citation is None for citation in authority_citations):
                        blockers.append("causal_authority_citation_missing")
                    expected_claims_sha256 = _hash(attributes)
                    if authority["claims_sha256"] != expected_claims_sha256:
                        blockers.append("causal_authority_claims_hash_drift")
                    if any(
                        citation is not None
                        and citation["claims_sha256"] != authority["claims_sha256"]
                        for citation in authority_citations
                    ):
                        blockers.append("causal_authority_Evidence_claims_mismatch")
                    try:
                        causal_authority_receipt = (
                            self._verify_independent_causal_authority(
                                principal=principal,
                                entity_scope=entity_scope,
                                scope=scope,
                                cutoff=cutoff,
                                checked_at=checked_at,
                                spec=spec,
                                authority=authority,
                                expected_contract_id=required_authority,
                            )
                        )
                    except _GateFailure as exc:
                        raise _GateFailure(
                            exc.status,
                            exc.reason,
                            subject_sha256=_hash(
                                {
                                    "edge_spec_id": spec["edge_spec_id"],
                                    "authority_contract_id": authority[
                                        "contract_id"
                                    ],
                                    "authority_receipt_sha256": authority[
                                        "receipt_sha256"
                                    ],
                                    "authority_claims_sha256": authority[
                                        "claims_sha256"
                                    ],
                                }
                            ),
                        ) from exc
                    causal_authority_status = "verified"
            if not source_node["eligible_for_gate"] or not target_node["eligible_for_gate"]:
                blockers.append("edge_endpoint_not_eligible")
            edge_id = f"gge_{_hash({'scope': scope, 'portfolio': portfolio_ref, 'spec': spec['edge_spec_id'], 'item': item['item_sha256']})[:32]}"
            result.append(
                {
                    "edge_id": edge_id,
                    "edge_spec_id": spec["edge_spec_id"],
                    "source_node_id": source_node["node_id"],
                    "target_node_id": target_node["node_id"],
                    "relation": spec["relation"],
                    "derivation": item["derivation"],
                    "causal_claim": spec["causal_claim"],
                    "causal_authority_status": causal_authority_status,
                    "causal_authority_receipt": causal_authority_receipt,
                    "source_id": spec["source_id"],
                    "source_item_ref": item["item_ref"],
                    "source_item_sha256": item["item_sha256"],
                    "citations": self._citation_projection(item, citations=citations),
                    "eligible_for_gate": not blockers,
                    "blockers": sorted(set(blockers)),
                    "canonical_graph_write": False,
                    "observation_only": True,
                }
            )
        return result

    def _verify_independent_causal_authority(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        scope: dict[str, str],
        cutoff: datetime,
        checked_at: datetime,
        spec: dict[str, Any],
        authority: dict[str, Any],
        expected_contract_id: str,
    ) -> dict[str, Any]:
        if self.causal_authority is None:
            raise _GateFailure("blocked", "independent_causal_authority_unavailable")
        try:
            raw = self.causal_authority.verify_causal_authority(
                principal=principal,
                entity_scope=deepcopy(entity_scope),
                store_ref=scope["store_ref"],
                data_as_of=cutoff,
                authority_checked_at=checked_at,
                relation=spec["relation"],
                source_node_spec_id=spec["source_node_spec_id"],
                target_node_spec_id=spec["target_node_spec_id"],
                claims_sha256=authority["claims_sha256"],
                receipt_sha256=authority["receipt_sha256"],
            )
            _safe_projection(raw, path="causal_authority_receipt")
        except (GapGraphContractError, KeyError, RuntimeError, TypeError, ValueError) as exc:
            raise _GateFailure(
                "blocked", "independent_causal_authority_invalid"
            ) from exc
        receipt = _exact_fields(
            raw,
            _CAUSAL_AUTHORITY_RECEIPT_FIELDS,
            field="causal_authority_receipt",
        )
        if (
            receipt["status"] != "verified"
            or receipt["contract_id"] != expected_contract_id
            or receipt["version"] != authority["version"]
            or _sha256(
                receipt["receipt_sha256"], field="causal_receipt.receipt_sha256"
            )
            != authority["receipt_sha256"]
            or _sha256(
                receipt["claims_sha256"], field="causal_receipt.claims_sha256"
            )
            != authority["claims_sha256"]
            or receipt["citation_refs"] != authority["citation_refs"]
        ):
            raise _GateFailure(
                "blocked", "independent_causal_authority_projection_drift"
            )
        if self._scope(receipt["scope"], field="causal_receipt.scope") != scope:
            raise _GateFailure("not_visible", "causal_authority_exact_scope_mismatch")
        recorded_at = _timestamp(
            receipt["recorded_at"], field="causal_receipt.recorded_at"
        )
        effective_at = _timestamp(
            receipt["effective_at"], field="causal_receipt.effective_at"
        )
        effective_until = _timestamp(
            receipt["effective_until"], field="causal_receipt.effective_until"
        )
        if recorded_at > cutoff:
            raise _GateFailure("blocked", "causal_authority_recorded_after_as_of")
        if not effective_at <= cutoff < effective_until:
            raise _GateFailure("stale", "causal_authority_not_effective_as_of")
        if receipt["integrity_status"] != "valid":
            raise _GateFailure("blocked", "causal_authority_integrity_invalid")
        if receipt["current"] is not True:
            raise _GateFailure("blocked", "causal_authority_currentness_invalid")
        return {
            "contract_id": receipt["contract_id"],
            "status": receipt["status"],
            "version": receipt["version"],
            "receipt_sha256": receipt["receipt_sha256"],
            "claims_sha256": receipt["claims_sha256"],
            "scope": deepcopy(scope),
            "recorded_at": recorded_at.isoformat(),
            "effective_at": effective_at.isoformat(),
            "effective_until": effective_until.isoformat(),
            "integrity_status": receipt["integrity_status"],
            "current": receipt["current"],
            "citation_refs": deepcopy(receipt["citation_refs"]),
        }

    def _build_gaps(
        self,
        *,
        item_index: dict[tuple[str, str], dict[str, Any]],
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        citations: dict[str, dict[str, Any]],
        scope: dict[str, str],
        portfolio_ref: str,
    ) -> list[dict[str, Any]]:
        node_by_spec = {item["node_spec_id"]: item for item in nodes}
        edge_by_spec = {item["edge_spec_id"]: item for item in edges}
        result: list[dict[str, Any]] = []
        for spec in self.portfolio.payload["gap_specs"]:
            item = self._item(
                item_index, spec["benchmark_source_id"], spec["benchmark_item_ref"]
            )
            attributes = item["attributes"]
            expected = {
                "metric_id": spec["expected_metric_id"],
                "cohort_ref": spec["expected_cohort_ref"],
                "market": spec["expected_market"],
                "window_start": spec["expected_window_start"],
                "window_end": spec["expected_window_end"],
                "comparison_state": spec["expected_comparison_state"],
                "leader_label": spec["expected_leader_label"],
                "global_top1_claim": False,
            }
            blockers: list[str] = []
            if item["item_kind"] != "benchmark_group":
                blockers.append("benchmark_item_kind_drift")
            if any(attributes.get(key) != value for key, value in expected.items()):
                blockers.append("benchmark_cohort_window_or_contract_drift")
            if attributes.get("global_top1_claim") is not False:
                blockers.append("global_top1_claim_forbidden")
            required_nodes = [
                node_by_spec[spec["current_node_spec_id"]],
                node_by_spec[spec["target_node_spec_id"]],
                node_by_spec[spec["problem_node_spec_id"]],
            ]
            required_edges = [
                edge_by_spec[edge_id] for edge_id in spec["required_edge_spec_ids"]
            ]
            if any(not node["eligible_for_gate"] for node in required_nodes):
                blockers.append("gap_node_not_eligible")
            if any(not edge["eligible_for_gate"] for edge in required_edges):
                blockers.append("gap_edge_not_eligible")
            citation_values = self._merge_citations(
                self._citation_projection(item, citations=citations),
                *(node["citations"] for node in required_nodes),
                *(edge["citations"] for edge in required_edges),
            )
            gap_id = f"ggg_{_hash({'scope': scope, 'portfolio': portfolio_ref, 'spec': spec['gap_spec_id'], 'benchmark': item['item_sha256']})[:32]}"
            result.append(
                {
                    "gap_id": gap_id,
                    "gap_spec_id": spec["gap_spec_id"],
                    "gap_kind": spec["gap_kind"],
                    "metric_id": spec["expected_metric_id"],
                    "cohort_ref": spec["expected_cohort_ref"],
                    "market": spec["expected_market"],
                    "window": {
                        "start": spec["expected_window_start"],
                        "end": spec["expected_window_end"],
                    },
                    "benchmark_group_ref": item["item_ref"],
                    "benchmark_group_sha256": item["item_sha256"],
                    "current_node_id": required_nodes[0]["node_id"],
                    "target_node_id": required_nodes[1]["node_id"],
                    "problem_node_id": required_nodes[2]["node_id"],
                    "required_edge_ids": [edge["edge_id"] for edge in required_edges],
                    "gap_signal": "verified_dimension_gap",
                    "global_top1_claim": False,
                    "status": "ready" if not blockers else "blocked",
                    "blockers": sorted(set(blockers)),
                    "citations": citation_values,
                    "observation_only": True,
                }
            )
        return result

    def _build_opportunities(
        self,
        *,
        item_index: dict[tuple[str, str], dict[str, Any]],
        gaps: list[dict[str, Any]],
        citations: dict[str, dict[str, Any]],
        scope: dict[str, str],
        portfolio_ref: str,
    ) -> list[dict[str, Any]]:
        gap_by_spec = {item["gap_spec_id"]: item for item in gaps}
        admitted: dict[str, bool] = {}
        result: list[dict[str, Any]] = []
        for spec in self._topological_opportunity_specs():
            selected_gaps = [gap_by_spec[gap_id] for gap_id in spec["gap_spec_ids"]]
            blockers: list[str] = []
            if any(gap["status"] != "ready" for gap in selected_gaps):
                blockers.append("opportunity_gap_not_ready")
            if any(
                not admitted.get(dependency, False)
                for dependency in spec["dependency_opportunity_ids"]
            ):
                blockers.append("opportunity_dependency_not_admitted")
            if any(
                alternative["status"] != "ready"
                for alternative in spec["alternatives"]
            ):
                blockers.append("strategic_alternative_UNKNOWN")
            if spec["decision_policy"]["status"] != "verified":
                blockers.append("decision_policy_not_verified")
            if spec["maximum_loss"]["status"] != "bounded":
                blockers.append("maximum_loss_unknown_or_unbounded")
            if spec["downside"]["status"] != "bounded":
                blockers.append("downside_unknown_or_unbounded")
            if spec["rollback"]["status"] != "verified":
                blockers.append("rollback_not_verified")
            if not spec["invalidation_conditions"]:
                blockers.append("invalidation_conditions_missing")
            direct_citation_refs = (
                spec["decision_policy"]["citation_refs"]
                + spec["maximum_loss"]["citation_refs"]
                + spec["downside"]["citation_refs"]
                + spec["rollback"]["citation_refs"]
            )
            missing = [ref for ref in direct_citation_refs if ref not in citations]
            if missing:
                blockers.append("opportunity_citation_missing")
            direct_citations = [
                citations[ref] for ref in direct_citation_refs if ref in citations
            ]
            policy_specs = {
                "decision_policy": spec["decision_policy"],
                "maximum_loss": spec["maximum_loss"],
                "downside": spec["downside"],
                "rollback": spec["rollback"],
            }
            policy_items = {
                gate_id: self._item(
                    item_index,
                    policy_spec["source_id"],
                    policy_spec["source_item_ref"],
                )
                for gate_id, policy_spec in policy_specs.items()
            }
            for gate_id, source_item in policy_items.items():
                if (
                    source_item["state"] != "ready"
                    or source_item["derivation"] != "observed"
                ):
                    blockers.append(f"{gate_id}_authoritative_projection_not_ready")
                bound_refs = {
                    binding["citation_ref"] for binding in source_item["citations"]
                }
                if not set(policy_specs[gate_id]["citation_refs"]).issubset(
                    bound_refs
                ):
                    blockers.append(f"{gate_id}_citation_not_bound_to_claims")

            decision_item = policy_items["decision_policy"]
            expected_decision = {
                "decision_status": spec["decision_policy"]["status"],
                "decision_policy_id": spec["decision_policy"]["policy_id"],
                "decision_policy_version": spec["decision_policy"]["policy_version"],
                "decision_policy_sha256": spec["decision_policy"]["policy_sha256"],
                "alternatives_sha256": _hash(spec["alternatives"]),
                "invalidation_conditions_sha256": _hash(
                    spec["invalidation_conditions"]
                ),
                "proposed_action": spec["proposed_action"],
            }
            if any(
                decision_item["attributes"].get(key) != value
                for key, value in expected_decision.items()
            ):
                blockers.append("decision_policy_claim_projection_drift")

            claim_prefix_by_gate = {
                "maximum_loss": "maximum_loss",
                "downside": "downside",
                "rollback": "rollback",
            }
            for gate_id, prefix in claim_prefix_by_gate.items():
                policy_spec = policy_specs[gate_id]
                expected_claims = {
                    f"{prefix}_status": policy_spec["status"],
                    f"{prefix}_policy_id": policy_spec["policy_id"],
                    f"{prefix}_policy_version": policy_spec["policy_version"],
                    f"{prefix}_policy_sha256": policy_spec["policy_sha256"],
                }
                if gate_id == "rollback":
                    expected_claims["rollback_artifact_sha256"] = policy_spec[
                        "artifact_sha256"
                    ]
                    expected_claims["rollback_trigger_codes_sha256"] = _hash(
                        policy_spec["trigger_codes"]
                    )
                else:
                    expected_claims[f"{prefix}_value"] = policy_spec["value"]
                    expected_claims[f"{prefix}_unit"] = policy_spec["unit"]
                source_item = policy_items[gate_id]
                if any(
                    source_item["attributes"].get(key) != value
                    for key, value in expected_claims.items()
                ):
                    blockers.append(f"{gate_id}_claim_projection_drift")
            citation_values = self._merge_citations(
                *(gap["citations"] for gap in selected_gaps), direct_citations
            )
            is_admitted = not blockers
            admitted[spec["opportunity_spec_id"]] = is_admitted
            opportunity_id = f"ggo_{_hash({'scope': scope, 'portfolio': portfolio_ref, 'spec': spec})[:32]}"
            result.append(
                {
                    "opportunity_id": opportunity_id,
                    "opportunity_spec_id": spec["opportunity_spec_id"],
                    "proposed_action": spec["proposed_action"],
                    "selected_action": (
                        spec["proposed_action"] if is_admitted else "no_action"
                    ),
                    "gap_ids": [gap["gap_id"] for gap in selected_gaps],
                    "dependency_opportunity_ids": list(
                        spec["dependency_opportunity_ids"]
                    ),
                    "alternatives": deepcopy(spec["alternatives"]),
                    "decision_policy": deepcopy(spec["decision_policy"]),
                    "maximum_loss": deepcopy(spec["maximum_loss"]),
                    "downside": deepcopy(spec["downside"]),
                    "invalidation_conditions": list(
                        spec["invalidation_conditions"]
                    ),
                    "rollback": deepcopy(spec["rollback"]),
                    "admission_status": "admitted" if is_admitted else "not_admitted",
                    "blockers": sorted(set(blockers)),
                    "citations": citation_values,
                    "self_approval": False,
                    "external_write": False,
                    "observation_only": True,
                }
            )
        return result

    def _topological_opportunity_specs(self) -> list[dict[str, Any]]:
        by_id = {
            spec["opportunity_spec_id"]: spec
            for spec in self.portfolio.payload["opportunity_specs"]
        }
        visited: set[str] = set()
        ordered: list[dict[str, Any]] = []

        def visit(opportunity_id: str) -> None:
            if opportunity_id in visited:
                return
            spec = by_id[opportunity_id]
            for dependency in sorted(spec["dependency_opportunity_ids"]):
                visit(dependency)
            visited.add(opportunity_id)
            ordered.append(spec)

        for opportunity_id in sorted(by_id):
            visit(opportunity_id)
        return ordered

    @staticmethod
    def _item(
        item_index: dict[tuple[str, str], dict[str, Any]],
        source_id: str,
        item_ref: str,
    ) -> dict[str, Any]:
        item = item_index.get((source_id, item_ref))
        if item is None:
            raise _GateFailure("no_data", "required_source_item_missing")
        return item

    @staticmethod
    def _citation_projection(
        item: dict[str, Any], *, citations: dict[str, dict[str, Any]]
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for binding in item["citations"]:
            receipt = citations.get(binding["citation_ref"])
            if (
                receipt is None
                or receipt["evidence_sha256"] != binding["evidence_sha256"]
                or receipt["claims_sha256"] != binding["claims_sha256"]
            ):
                raise _GateFailure("blocked", "verified_citation_binding_missing")
            result.append(deepcopy(receipt))
        return result

    @staticmethod
    def _merge_citations(*collections: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_ref: dict[str, dict[str, Any]] = {}
        for collection in collections:
            for citation in collection:
                prior = by_ref.get(citation["citation_ref"])
                if prior is not None and prior != citation:
                    raise _GateFailure("blocked", "citation_merge_conflict")
                by_ref[citation["citation_ref"]] = citation
        return [by_ref[key] for key in sorted(by_ref)]

    @staticmethod
    def _scope(value: Any, *, field: str) -> dict[str, str]:
        scope = _exact_fields(value, _SCOPE_FIELDS, field=field)
        return {
            "tenant_ref": _token(scope["tenant_ref"], field=f"{field}.tenant_ref"),
            "entity_ref": _token(scope["entity_ref"], field=f"{field}.entity_ref"),
            "store_ref": _token(scope["store_ref"], field=f"{field}.store_ref"),
            "scope_grant_authority_sha256": _sha256(
                scope["scope_grant_authority_sha256"],
                field=f"{field}.scope_grant_authority_sha256",
            ),
        }

    @staticmethod
    def _source_statuses(raw_bundle: Any) -> list[dict[str, str]]:
        if not isinstance(raw_bundle, dict) or not isinstance(raw_bundle.get("sources"), list):
            return []
        result: list[dict[str, str]] = []
        for value in raw_bundle["sources"]:
            if not isinstance(value, dict):
                continue
            source_id = value.get("source_id")
            status = value.get("status")
            if (
                isinstance(source_id, str)
                and _TOKEN.fullmatch(source_id)
                and isinstance(status, str)
                and _TOKEN.fullmatch(status)
            ):
                result.append({"source_id": source_id, "status": status})
        return sorted(result, key=lambda item: item["source_id"])

    def _blocked_observation(
        self,
        *,
        principal: Principal,
        store_ref: str,
        cutoff: datetime,
        checked_at: datetime,
        portfolio_ref: str,
        status: str,
        reasons: list[str],
        source_statuses: list[dict[str, str]],
        scope: dict[str, str] | None = None,
        request_sha256: str | None = None,
        failure_subject_sha256: str | None = None,
        include_no_action_stubs: bool = False,
    ) -> dict[str, Any]:
        if status not in self.registry.payload["allowed_states"]:
            status = "blocked"
        visible_scope = scope or {
            "tenant_ref": principal.tenant_ref,
            "entity_ref": None,
            "store_ref": store_ref,
            "scope_grant_authority_sha256": None,
        }
        provisional_digest = request_sha256 or _hash(
            {
                "contract_id": self.CONTRACT_ID,
                "registry_sha256": self.registry.content_sha256,
                "portfolio_ref": portfolio_ref,
                "scope": visible_scope,
                "actor_id": principal.actor_id,
                "as_of": cutoff.isoformat(),
            }
        )
        normalized_reasons = sorted(set(reasons))
        normalized_source_statuses = sorted(
            deepcopy(source_statuses),
            key=lambda item: (item.get("source_id", ""), item.get("status", "")),
        )
        digest = _hash(
            {
                "provisional_request_sha256": provisional_digest,
                "status": status,
                "reason_codes": normalized_reasons,
                "source_statuses": normalized_source_statuses,
                "failure_subject_sha256": failure_subject_sha256,
            }
        )
        opportunity_stubs = (
            self._no_action_opportunity_stubs(
                scope=visible_scope,
                portfolio_ref=portfolio_ref,
                reasons=reasons,
            )
            if include_no_action_stubs
            else []
        )
        observation = {
            "contract_id": self.CONTRACT_ID,
            "status": status,
            "portfolio_status": "not_admitted",
            "reason_codes": normalized_reasons,
            "run_id": f"ggr_{digest[:32]}",
            "request_sha256": digest,
            "registry_ref": self.registry.ref,
            "portfolio_ref": portfolio_ref,
            "scope": visible_scope,
            "as_of": cutoff.isoformat(),
            "source_statuses": normalized_source_statuses,
            "nodes": [],
            "edges": [],
            "gaps": [],
            "opportunities": opportunity_stubs,
            "counts": {
                "sources": len(source_statuses),
                "citations": 0,
                "nodes": 0,
                "edges": 0,
                "gaps": 0,
                "opportunities": len(opportunity_stubs),
            },
            "global_top1_claim": False,
            "correlation_is_causation": False,
            "generated_and_inferred_are_observation_only": True,
            "observation_only": True,
            "governance": deepcopy(self.registry.payload["zero_authority_flags"]),
            "write_counts": self._zero_write_counts(),
        }
        observation["observation_sha256"] = _hash(observation)
        return observation

    def _no_action_opportunity_stubs(
        self,
        *,
        scope: dict[str, Any],
        portfolio_ref: str,
        reasons: list[str],
    ) -> list[dict[str, Any]]:
        return [
            {
                "opportunity_id": f"ggo_{_hash({'scope': scope, 'portfolio': portfolio_ref, 'spec': spec['opportunity_spec_id'], 'blocked': True})[:32]}",
                "opportunity_spec_id": spec["opportunity_spec_id"],
                "proposed_action": spec["proposed_action"],
                "selected_action": "no_action",
                "admission_status": "not_admitted",
                "blockers": sorted(set(reasons)),
                "citations": [],
                "self_approval": False,
                "external_write": False,
                "observation_only": True,
            }
            for spec in self._topological_opportunity_specs()
        ]

    @staticmethod
    def _zero_write_counts() -> dict[str, int]:
        return {
            "formal_fact": 0,
            "finance_entry": 0,
            "approval": 0,
            "permit": 0,
            "pilot": 0,
            "outbox": 0,
            "canonical_graph_write": 0,
            "dependency_install": 0,
            "network": 0,
            "external_write": 0,
        }


__all__ = [
    "FrozenGapGraphPortfolio",
    "GapGraphCausalAuthority",
    "GapGraphCitationAuthority",
    "GapGraphConflictError",
    "GapGraphContractError",
    "GapGraphContractRegistry",
    "GapGraphReadAuthority",
    "GovernedGapGraphWorkspace",
]
