from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol
from urllib.parse import urlparse

CONTRACT_ID = "kjds-marketplace-research-workflow-v1"
RECEIPT_CONTRACT_ID = "kjds-marketplace-research-source-receipt-v1"
DEFAULT_REGISTRY_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "project"
    / "registries"
    / "marketplace_research_source_contracts.json"
)
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
_INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(all\s+)?previous", re.IGNORECASE),
    re.compile(r"system\s+prompt", re.IGNORECASE),
    re.compile(r"developer\s+message", re.IGNORECASE),
    re.compile(r"jailbreak", re.IGNORECASE),
    re.compile(r"tool[_ -]?call", re.IGNORECASE),
    re.compile(r"authorization\s*:", re.IGNORECASE),
    re.compile(r"secret-key", re.IGNORECASE),
    re.compile(r"<\|(?:system|assistant|tool)\|>", re.IGNORECASE),
    re.compile(r"忽略(?:以上|此前|之前).{0,12}(?:指令|要求|规则)"),
)
_GRADE_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}
_CANONICAL_SCHEMAS = {
    "product": {
        "site": "site_code",
        "asin": "asin",
        "title": "string",
        "currency": "currency",
        "price": "decimal",
        "monthly_sales": "integer",
        "monthly_revenue": "decimal",
        "review_count": "integer",
        "rating_bps": "basis_points",
        "seller_count": "integer",
    },
    "market": {
        "site": "site_code",
        "asin": "asin",
        "category": "string",
        "market_growth_bps": "signed_basis_points",
        "brand_concentration_bps": "basis_points",
    },
    "trend": {
        "site": "site_code",
        "asin": "asin",
        "trend_90d_bps": "signed_basis_points",
        "volatility_bps": "basis_points",
    },
    "traffic": {
        "site": "site_code",
        "asin": "asin",
        "keyword_count": "integer",
        "organic_keyword_count": "integer",
        "paid_keyword_count": "integer",
    },
    "reviews": {
        "site": "site_code",
        "asin": "asin",
        "review_sample_size": "integer",
        "pain_point_count": "integer",
        "positive_ratio_bps": "basis_points",
    },
    "trademark": {
        "site": "site_code",
        "asin": "asin",
        "trademark_state": "trademark_state",
    },
}


class MarketplaceResearchContractError(ValueError):
    """Safe contract failure carrying only a stable reason code."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class MarketplaceResearchScopeAuthority(Protocol):
    def current(
        self,
        *,
        tenant_ref: str,
        entity_ref: str,
        store_ref: str,
        checked_at: datetime,
    ) -> Mapping[str, Any]: ...


class MarketplaceResearchReceiptAuthority(Protocol):
    def claim(
        self,
        *,
        scope_binding_sha256: str,
        idempotency_key: str,
        receipt_content_sha256: str,
        registry_sha256: str,
    ) -> str: ...


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _required(value: Any, field: str, *, maximum: int = 300) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > maximum:
        raise MarketplaceResearchContractError(f"{field}_invalid")
    return normalized


def _identifier(value: Any, field: str) -> str:
    normalized = _required(value, field, maximum=160)
    if not _SAFE_IDENTIFIER.fullmatch(normalized):
        raise MarketplaceResearchContractError(f"{field}_invalid")
    return normalized


def _hash64(value: Any, field: str) -> str:
    normalized = _required(value, field, maximum=64).lower()
    if not _HEX64.fullmatch(normalized):
        raise MarketplaceResearchContractError(f"{field}_invalid")
    return normalized


def _instant(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise MarketplaceResearchContractError(f"{field}_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MarketplaceResearchContractError(f"{field}_invalid")
    return parsed.astimezone(UTC)


def _integer(value: Any, field: str, *, minimum: int = 0, maximum: int = 10**12) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise MarketplaceResearchContractError(f"{field}_invalid")
    return value


def _decimal(value: Any, field: str, *, minimum: str = "0", maximum: str = "1000000000000") -> Decimal:
    if isinstance(value, bool):
        raise MarketplaceResearchContractError(f"{field}_invalid")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise MarketplaceResearchContractError(f"{field}_invalid") from exc
    if not parsed.is_finite() or not Decimal(minimum) <= parsed <= Decimal(maximum):
        raise MarketplaceResearchContractError(f"{field}_invalid")
    return parsed


def _exact_keys(value: Any, expected: set[str], reason_code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise MarketplaceResearchContractError(reason_code)
    return value


def _sequence(value: Any, field: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise MarketplaceResearchContractError(f"{field}_invalid")
    return value


def _contains_injection(value: Any) -> bool:
    if isinstance(value, str):
        return any(pattern.search(value) for pattern in _INJECTION_PATTERNS)
    if isinstance(value, Mapping):
        return any(_contains_injection(key) or _contains_injection(item) for key, item in value.items())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_contains_injection(item) for item in value)
    return False


@dataclass(frozen=True, slots=True)
class MarketplaceResearchScopeContext:
    tenant_ref: str
    entity_ref: str
    store_ref: str
    scope_grant_authority_sha256: str
    data_as_of: datetime

    def normalized(self, *, trusted_now: datetime) -> dict[str, Any]:
        tenant = _identifier(self.tenant_ref, "tenant_ref")
        entity = _identifier(self.entity_ref, "entity_ref")
        store = _identifier(self.store_ref, "store_ref")
        authority = _hash64(
            self.scope_grant_authority_sha256,
            "scope_grant_authority_sha256",
        )
        data_as_of = _instant(self.data_as_of, "data_as_of")
        trusted_now = _instant(trusted_now, "trusted_now")
        if data_as_of > trusted_now:
            raise MarketplaceResearchContractError("data_as_of_in_future")
        scope = {
            "tenant_ref": tenant,
            "entity_ref": entity,
            "store_ref": store,
            "scope_grant_authority_sha256": authority,
        }
        return {
            "scope": scope,
            "scope_binding_sha256": _sha256(scope),
            "data_as_of": data_as_of,
            "authority_checked_at": trusted_now,
            "trusted_now": trusted_now,
        }


@dataclass(frozen=True, slots=True)
class MarketplaceResearchProposal(Mapping[str, Any]):
    _payload: Mapping[str, Any]

    def __getitem__(self, key: str) -> Any:
        return self._payload[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._payload)

    def __len__(self) -> int:
        return len(self._payload)

    @property
    def proposal_id(self) -> str:
        return str(self._payload["proposal_id"])

    @property
    def proposal_sha256(self) -> str:
        return str(self._payload["proposal_sha256"])

    def to_dict(self) -> dict[str, Any]:
        return _thaw(self._payload)


class MarketplaceResearchWorkflow:
    """Validate frozen marketplace research receipts and emit proposals only."""

    def __init__(
        self,
        registry_path: str | Path = DEFAULT_REGISTRY_PATH,
        *,
        scope_authority: MarketplaceResearchScopeAuthority | None = None,
        receipt_authority: MarketplaceResearchReceiptAuthority | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.registry_path = Path(registry_path)
        self.scope_authority = scope_authority
        self.receipt_authority = receipt_authority
        self.clock = clock or (lambda: datetime.now(UTC))
        self.registry = self._load_registry(self.registry_path)
        self.registry_sha256 = _sha256(self.registry)
        self.source_profiles = {
            profile["source_id"]: profile for profile in self.registry["source_profiles"]
        }
        self.tool_contracts = {
            contract["tool_id"]: contract for contract in self.registry["tool_contracts"]
        }

    def project(
        self,
        context: MarketplaceResearchScopeContext,
        receipt: Mapping[str, Any],
    ) -> MarketplaceResearchProposal:
        try:
            trusted_now = self._trusted_time()
        except MarketplaceResearchContractError:
            return self._blocked(
                context=None,
                reason_code="trusted_clock_unavailable",
                input_read=False,
            )
        try:
            normalized_context = context.normalized(trusted_now=trusted_now)
        except MarketplaceResearchContractError as exc:
            return self._blocked(context=None, reason_code=exc.reason_code, input_read=False)

        try:
            self._verify_current_authority(normalized_context, checked_at=trusted_now)
        except MarketplaceResearchContractError as exc:
            return self._blocked(
                context=normalized_context,
                reason_code=exc.reason_code,
                input_read=False,
            )
        try:
            validated = self._validate_receipt(normalized_context, receipt)
            records = self._normalize_records(validated)
            opportunities = [self._opportunity(record) for record in records]
            claim_checked_at = self._trusted_time()
            if claim_checked_at < normalized_context["trusted_now"]:
                raise MarketplaceResearchContractError("trusted_clock_regressed")
            self._verify_current_authority(
                normalized_context,
                checked_at=claim_checked_at,
            )
            self._claim_receipt(normalized_context, validated["receipt"])
        except MarketplaceResearchContractError as exc:
            return self._blocked(
                context=normalized_context,
                reason_code=exc.reason_code,
                input_read=True,
            )
        core = {
            "contract_id": CONTRACT_ID,
            "registry_sha256": self.registry_sha256,
            "status": "ready_for_review",
            "truth_status": "proposal_only",
            "reason_codes": ["fixture_only_source_not_production_admitted"],
            "scope_binding_sha256": normalized_context["scope_binding_sha256"],
            "data_as_of": normalized_context["data_as_of"].isoformat(),
            "authority_checked_at": validated["receipt_authority_checked_at"].isoformat(),
            "source": {
                "source_id": validated["profile"]["source_id"],
                "source_mode": validated["receipt"]["source_mode"],
                "source_grade": validated["receipt"]["declared_grade"],
                "live_adapter_configured": False,
                "production_admission": "not_admitted",
            },
            "receipt": {
                "receipt_id": validated["receipt"]["receipt_id"],
                "receipt_content_sha256": validated["receipt"]["receipt_content_sha256"],
                "idempotency_key_sha256": _sha256(validated["receipt"]["idempotency_key"]),
                "declared_page_count": validated["receipt"]["declared_page_count"],
                "declared_observation_count": validated["receipt"]["declared_observation_count"],
                "declared_unique_record_count": validated["receipt"]["declared_unique_record_count"],
            },
            "market_observations": records,
            "opportunity_proposals": opportunities,
            "citations": validated["citations"],
            "blockers": [
                {
                    "code": "live_mcp_admission_pending",
                    "owner": "marketplace-research-governance",
                    "required_evidence": [
                        "licensed_read_only_access",
                        "server_identity_receipt",
                        "tool_schema_reconciliation",
                        "rate_and_cost_contract",
                        "revocation_readback",
                        "real_sample_reconciliation",
                    ],
                }
            ],
            "control_envelope": self._control_envelope(input_read=True),
        }
        proposal_sha256 = _sha256(core)
        return MarketplaceResearchProposal(
            _freeze(
                {
                    **core,
                    "proposal_id": f"mrp_{proposal_sha256[:32]}",
                    "proposal_sha256": proposal_sha256,
                }
            )
        )

    def _claim_receipt(
        self,
        context: Mapping[str, Any],
        receipt: Mapping[str, Any],
    ) -> None:
        if self.receipt_authority is None:
            raise MarketplaceResearchContractError("receipt_authority_adapter_unconfigured")
        try:
            result = self.receipt_authority.claim(
                scope_binding_sha256=context["scope_binding_sha256"],
                idempotency_key=receipt["idempotency_key"],
                receipt_content_sha256=receipt["receipt_content_sha256"],
                registry_sha256=self.registry_sha256,
            )
        except (KeyError, RuntimeError, TypeError, ValueError) as exc:
            raise MarketplaceResearchContractError("receipt_authority_unavailable") from exc
        if result == "conflict":
            raise MarketplaceResearchContractError("idempotency_conflict")
        if result not in {"created", "replay"}:
            raise MarketplaceResearchContractError("receipt_authority_response_invalid")

    def _trusted_time(self) -> datetime:
        try:
            return _instant(self.clock(), "trusted_now")
        except (
            MarketplaceResearchContractError,
            OSError,
            OverflowError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as exc:
            raise MarketplaceResearchContractError("trusted_clock_unavailable") from exc

    def _verify_current_authority(
        self,
        context: Mapping[str, Any],
        *,
        checked_at: datetime,
    ) -> None:
        if self.scope_authority is None:
            raise MarketplaceResearchContractError("scope_authority_adapter_unconfigured")
        scope = context["scope"]
        try:
            raw_projection = self.scope_authority.current(
                tenant_ref=scope["tenant_ref"],
                entity_ref=scope["entity_ref"],
                store_ref=scope["store_ref"],
                checked_at=checked_at,
            )
        except (KeyError, RuntimeError, TypeError, ValueError) as exc:
            raise MarketplaceResearchContractError("scope_authority_unavailable") from exc
        projection = _exact_keys(
            raw_projection,
            {
                "status",
                "tenant_ref",
                "entity_ref",
                "store_ref",
                "scope_grant_authority_sha256",
                "checked_at",
            },
            "scope_authority_projection_invalid",
        )
        status = _required(projection["status"], "scope_authority_status", maximum=32).lower()
        if status not in {"ready", "missing", "revoked", "ambiguous", "expired"}:
            raise MarketplaceResearchContractError("scope_authority_projection_invalid")
        if status != "ready":
            raise MarketplaceResearchContractError(f"scope_authority_{status}")
        current = {
            "tenant_ref": _identifier(projection["tenant_ref"], "tenant_ref"),
            "entity_ref": _identifier(projection["entity_ref"], "entity_ref"),
            "store_ref": _identifier(projection["store_ref"], "store_ref"),
            "scope_grant_authority_sha256": _hash64(
                projection["scope_grant_authority_sha256"],
                "scope_grant_authority_sha256",
            ),
        }
        projection_checked_at = _instant(projection["checked_at"], "scope_authority_checked_at")
        if current != scope or projection_checked_at != checked_at:
            raise MarketplaceResearchContractError("scope_authority_drift")

    def _validate_receipt(
        self,
        context: Mapping[str, Any],
        raw_receipt: Mapping[str, Any],
    ) -> dict[str, Any]:
        receipt = _exact_keys(
            raw_receipt,
            {
                "receipt_contract_id",
                "receipt_contract_version",
                "receipt_id",
                "receipt_content_sha256",
                "idempotency_key",
                "source_id",
                "source_mode",
                "source_contract_sha256",
                "registry_sha256",
                "server_identity_sha256",
                "scope",
                "authority_checked_at",
                "data_as_of",
                "captured_at",
                "declared_grade",
                "license_status",
                "revocation_status",
                "cost_status",
                "rate_limit_status",
                "tool_receipts",
                "observations",
                "failed_pages",
                "terminal_checkpoint",
                "declared_page_count",
                "declared_observation_count",
                "declared_unique_record_count",
            },
            "receipt_shape_invalid",
        )
        if receipt["receipt_contract_id"] != RECEIPT_CONTRACT_ID or receipt["receipt_contract_version"] != 1:
            raise MarketplaceResearchContractError("receipt_contract_invalid")
        _identifier(receipt["idempotency_key"], "idempotency_key")
        if receipt["registry_sha256"] != self.registry_sha256:
            raise MarketplaceResearchContractError("registry_binding_drift")
        source_id = _identifier(receipt["source_id"], "source_id")
        profile = self.source_profiles.get(source_id)
        if profile is None:
            raise MarketplaceResearchContractError("source_not_registered")
        if receipt["source_mode"] != "synthetic_fixture":
            raise MarketplaceResearchContractError("source_mode_not_admitted")
        if profile["live_adapter_configured"] is not False:
            raise MarketplaceResearchContractError("live_adapter_state_invalid")
        if receipt["source_contract_sha256"] != self._source_contract_sha256(profile):
            raise MarketplaceResearchContractError("source_contract_drift")
        if receipt["server_identity_sha256"] != profile["server_identity_sha256"]:
            raise MarketplaceResearchContractError("server_identity_drift")
        if receipt["license_status"] != "fixture_only":
            raise MarketplaceResearchContractError("license_status_not_admitted")
        if receipt["revocation_status"] != "not_applicable_fixture":
            raise MarketplaceResearchContractError("revocation_status_invalid")
        if receipt["cost_status"] != "unknown" or receipt["rate_limit_status"] != "unknown":
            raise MarketplaceResearchContractError("commercial_contract_drift")
        grade = _required(receipt["declared_grade"], "declared_grade", maximum=1).upper()
        max_grade = profile["max_evidence_grade"]
        if grade not in _GRADE_ORDER or _GRADE_ORDER[grade] < _GRADE_ORDER[max_grade]:
            raise MarketplaceResearchContractError("evidence_grade_self_promotion")

        scope = _exact_keys(
            receipt["scope"],
            {"tenant_ref", "entity_ref", "store_ref", "scope_grant_authority_sha256"},
            "receipt_scope_shape_invalid",
        )
        normalized_scope = {
            "tenant_ref": _identifier(scope["tenant_ref"], "tenant_ref"),
            "entity_ref": _identifier(scope["entity_ref"], "entity_ref"),
            "store_ref": _identifier(scope["store_ref"], "store_ref"),
            "scope_grant_authority_sha256": _hash64(
                scope["scope_grant_authority_sha256"],
                "scope_grant_authority_sha256",
            ),
        }
        if normalized_scope != context["scope"]:
            raise MarketplaceResearchContractError("receipt_exact_scope_mismatch")
        authority_checked_at = _instant(receipt["authority_checked_at"], "authority_checked_at")
        data_as_of = _instant(receipt["data_as_of"], "data_as_of")
        captured_at = _instant(receipt["captured_at"], "captured_at")
        if data_as_of != context["data_as_of"]:
            raise MarketplaceResearchContractError("receipt_data_as_of_mismatch")
        if not data_as_of <= captured_at <= authority_checked_at <= context["trusted_now"]:
            raise MarketplaceResearchContractError("receipt_time_window_invalid")
        max_age = timedelta(hours=self.registry["normalization"]["max_fixture_age_hours"])
        if context["trusted_now"] - data_as_of > max_age:
            raise MarketplaceResearchContractError("receipt_stale")
        if receipt["failed_pages"] != []:
            raise MarketplaceResearchContractError("source_page_failed")
        if _contains_injection(receipt):
            raise MarketplaceResearchContractError("untrusted_instruction_detected")

        observations = self._validate_observations(
            receipt,
            source_id=source_id,
            data_as_of=data_as_of,
        )
        pages, citations = self._validate_pages(
            receipt,
            profile=profile,
            observations=observations,
        )
        record_ids = {item["record_id"] for item in observations}
        if receipt["declared_page_count"] != len(pages):
            raise MarketplaceResearchContractError("page_count_conservation_failed")
        if receipt["declared_observation_count"] != len(observations):
            raise MarketplaceResearchContractError("observation_count_conservation_failed")
        if receipt["declared_unique_record_count"] != len(record_ids):
            raise MarketplaceResearchContractError("record_count_conservation_failed")

        core = {key: value for key, value in receipt.items() if key not in {"receipt_id", "receipt_content_sha256"}}
        content_sha256 = _sha256(core)
        if receipt["receipt_content_sha256"] != content_sha256:
            raise MarketplaceResearchContractError("receipt_content_hash_mismatch")
        if receipt["receipt_id"] != f"mrsr_{content_sha256[:32]}":
            raise MarketplaceResearchContractError("receipt_id_not_content_addressed")
        return {
            "profile": profile,
            "receipt": receipt,
            "receipt_authority_checked_at": authority_checked_at,
            "observations": observations,
            "citations": citations,
        }

    def _validate_observations(
        self,
        receipt: Mapping[str, Any],
        *,
        source_id: str,
        data_as_of: datetime,
    ) -> list[dict[str, Any]]:
        raw_observations = _sequence(receipt["observations"], "observations")
        observations: list[dict[str, Any]] = []
        observation_ids: set[str] = set()
        for raw in raw_observations:
            observation = _exact_keys(
                raw,
                {
                    "observation_id",
                    "tool_id",
                    "tool_version",
                    "schema_sha256",
                    "record_id",
                    "observed_at",
                    "fields",
                },
                "observation_shape_invalid",
            )
            tool_id = _identifier(observation["tool_id"], "tool_id")
            contract = self.tool_contracts.get(tool_id)
            if contract is None or contract["source_id"] != source_id:
                raise MarketplaceResearchContractError("tool_not_allowlisted")
            if observation["tool_version"] != contract["tool_version"]:
                raise MarketplaceResearchContractError("tool_version_drift")
            schema_sha256 = _sha256(contract["schema"])
            if observation["schema_sha256"] != schema_sha256:
                raise MarketplaceResearchContractError("tool_schema_hash_drift")
            fields = self._validate_fields(contract, observation["fields"])
            record_id = _identifier(observation["record_id"], "record_id")
            expected_record_id = f"{fields['site']}:{fields['asin']}"
            if record_id != expected_record_id:
                raise MarketplaceResearchContractError("record_id_unstable")
            observed_at = _instant(observation["observed_at"], "observed_at")
            minimum_observed_at = data_as_of - timedelta(
                hours=self.registry["normalization"]["max_fixture_age_hours"]
            )
            if not minimum_observed_at <= observed_at <= data_as_of:
                raise MarketplaceResearchContractError("observation_outside_freshness_window")
            core = {
                "tool_id": tool_id,
                "tool_version": contract["tool_version"],
                "schema_sha256": schema_sha256,
                "record_id": record_id,
                "observed_at": observed_at.isoformat(),
                "fields": fields,
            }
            expected_id = f"mro_{_sha256(core)[:32]}"
            if observation["observation_id"] != expected_id:
                raise MarketplaceResearchContractError("observation_id_not_content_addressed")
            if expected_id in observation_ids:
                raise MarketplaceResearchContractError("duplicate_observation_id")
            observation_ids.add(expected_id)
            observations.append({**core, "observation_id": expected_id})
        return sorted(observations, key=lambda item: (item["tool_id"], item["record_id"]))

    def _validate_fields(
        self,
        contract: Mapping[str, Any],
        raw_fields: Mapping[str, Any],
    ) -> dict[str, Any]:
        fields = _exact_keys(
            raw_fields,
            set(contract["schema"]),
            "tool_field_shape_drift",
        )
        normalized: dict[str, Any] = {}
        for field, field_type in contract["schema"].items():
            value = fields[field]
            if field_type == "string":
                normalized[field] = _required(value, field, maximum=500)
            elif field_type == "site_code":
                site = _required(value, field, maximum=4).upper()
                if site not in self.registry["site_codes"]:
                    raise MarketplaceResearchContractError("site_not_allowlisted")
                normalized[field] = site
            elif field_type == "asin":
                asin = _required(value, field, maximum=16).upper()
                if not re.fullmatch(r"[A-Z0-9]{10}", asin):
                    raise MarketplaceResearchContractError("asin_invalid")
                normalized[field] = asin
            elif field_type == "integer":
                normalized[field] = _integer(value, field)
            elif field_type == "basis_points":
                normalized[field] = _integer(value, field, maximum=10_000)
            elif field_type == "signed_basis_points":
                normalized[field] = _integer(value, field, minimum=-10_000, maximum=10_000)
            elif field_type == "decimal":
                normalized[field] = format(_decimal(value, field), "f")
            elif field_type == "currency":
                currency = _required(value, field, maximum=3).upper()
                if not re.fullmatch(r"[A-Z]{3}", currency):
                    raise MarketplaceResearchContractError("currency_invalid")
                normalized[field] = currency
            elif field_type == "trademark_state":
                state = _required(value, field, maximum=16).lower()
                if state not in {"clear", "unknown", "hit"}:
                    raise MarketplaceResearchContractError("trademark_state_invalid")
                normalized[field] = state
            else:
                raise MarketplaceResearchContractError("registry_field_type_invalid")
        semantic_role = contract["semantic_role"]
        if semantic_role == "product":
            if normalized["rating_bps"] > 5_000 or normalized["seller_count"] < 1:
                raise MarketplaceResearchContractError("product_metric_relation_invalid")
        elif semantic_role == "traffic":
            if normalized["organic_keyword_count"] + normalized["paid_keyword_count"] != normalized["keyword_count"]:
                raise MarketplaceResearchContractError("traffic_metric_conservation_failed")
        elif semantic_role == "reviews" and (
            normalized["review_sample_size"] < 1
            or normalized["pain_point_count"] > normalized["review_sample_size"]
        ):
            raise MarketplaceResearchContractError("review_metric_conservation_failed")
        return normalized

    def _validate_pages(
        self,
        receipt: Mapping[str, Any],
        *,
        profile: Mapping[str, Any],
        observations: Sequence[Mapping[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        observed_ids = {item["observation_id"] for item in observations}
        covered_ids: list[str] = []
        pages: list[dict[str, Any]] = []
        citations: list[str] = []
        tool_receipts = _sequence(receipt["tool_receipts"], "tool_receipts")
        tool_ids: set[str] = set()
        terminal_checkpoint: dict[str, str] = {}
        for raw_tool in tool_receipts:
            tool = _exact_keys(
                raw_tool,
                {"tool_id", "tool_version", "schema_sha256", "pages"},
                "tool_receipt_shape_invalid",
            )
            tool_id = _identifier(tool["tool_id"], "tool_id")
            contract = self.tool_contracts.get(tool_id)
            if contract is None or contract["source_id"] != profile["source_id"] or tool_id in tool_ids:
                raise MarketplaceResearchContractError("tool_receipt_invalid")
            tool_ids.add(tool_id)
            if tool["tool_version"] != contract["tool_version"]:
                raise MarketplaceResearchContractError("tool_version_drift")
            if tool["schema_sha256"] != _sha256(contract["schema"]):
                raise MarketplaceResearchContractError("tool_schema_hash_drift")
            prior_checkpoint: str | None = None
            seen_checkpoints: set[str] = set()
            source_total: int | None = None
            exported_count = 0
            raw_pages = _sequence(tool["pages"], "pages")
            if not raw_pages:
                raise MarketplaceResearchContractError("tool_pages_missing")
            for expected_index, raw_page in enumerate(raw_pages, start=1):
                page = _exact_keys(
                    raw_page,
                    {
                        "page_index",
                        "status",
                        "checkpoint_before",
                        "checkpoint_after",
                        "has_more",
                        "source_total_observations",
                        "exported_observation_count",
                        "observation_ids",
                        "page_sha256",
                    },
                    "page_shape_invalid",
                )
                if page["page_index"] != expected_index or page["status"] != "complete":
                    raise MarketplaceResearchContractError("page_sequence_invalid")
                if page["checkpoint_before"] != prior_checkpoint:
                    raise MarketplaceResearchContractError("checkpoint_continuity_failed")
                checkpoint_after = _identifier(page["checkpoint_after"], "checkpoint_after")
                if checkpoint_after == prior_checkpoint or checkpoint_after in seen_checkpoints:
                    raise MarketplaceResearchContractError("checkpoint_progression_failed")
                seen_checkpoints.add(checkpoint_after)
                page_ids = list(_sequence(page["observation_ids"], "observation_ids"))
                if not page_ids or len(page_ids) != len(set(page_ids)):
                    raise MarketplaceResearchContractError("page_observation_ids_invalid")
                if not set(page_ids) <= observed_ids:
                    raise MarketplaceResearchContractError("page_observation_missing")
                for observation_id in page_ids:
                    matching = next(item for item in observations if item["observation_id"] == observation_id)
                    if matching["tool_id"] != tool_id:
                        raise MarketplaceResearchContractError("page_tool_binding_mismatch")
                if type(page["has_more"]) is not bool:
                    raise MarketplaceResearchContractError("page_terminal_state_invalid")
                declared_source_total = _integer(
                    page["source_total_observations"],
                    "source_total_observations",
                    minimum=1,
                )
                if source_total is None:
                    source_total = declared_source_total
                elif source_total != declared_source_total:
                    raise MarketplaceResearchContractError("source_total_drift")
                exported_count += len(page_ids)
                if page["exported_observation_count"] != exported_count:
                    raise MarketplaceResearchContractError("exported_count_conservation_failed")
                expected_has_more = expected_index < len(raw_pages)
                if page["has_more"] is not expected_has_more:
                    raise MarketplaceResearchContractError("page_terminal_state_invalid")
                page_core = {key: value for key, value in page.items() if key != "page_sha256"}
                if page["page_sha256"] != _sha256(page_core):
                    raise MarketplaceResearchContractError("page_hash_mismatch")
                covered_ids.extend(page_ids)
                prior_checkpoint = checkpoint_after
                pages.append(dict(page))
                citations.append(
                    f"market-research-citation:{receipt['receipt_id']}:{tool_id}:{expected_index}"
                )
            if source_total != exported_count:
                raise MarketplaceResearchContractError("source_exhaustion_not_proven")
            terminal_checkpoint[tool_id] = prior_checkpoint
        required_tools = set(profile["selected_tool_ids"])
        if tool_ids != required_tools:
            raise MarketplaceResearchContractError("required_tool_coverage_incomplete")
        if len(covered_ids) != len(set(covered_ids)) or set(covered_ids) != observed_ids:
            raise MarketplaceResearchContractError("observation_page_conservation_failed")
        if receipt["terminal_checkpoint"] != terminal_checkpoint:
            raise MarketplaceResearchContractError("terminal_checkpoint_mismatch")
        return pages, sorted(citations)

    def _normalize_records(self, validated: Mapping[str, Any]) -> list[dict[str, Any]]:
        by_record: dict[str, dict[str, Mapping[str, Any]]] = defaultdict(dict)
        for observation in validated["observations"]:
            record = by_record[observation["record_id"]]
            tool_id = observation["tool_id"]
            if tool_id in record:
                raise MarketplaceResearchContractError("duplicate_record_tool_observation")
            record[tool_id] = observation
        profile = validated["profile"]
        required_tools = set(profile["selected_tool_ids"])
        required_roles = set(self.registry["scoring_policy"]["required_semantic_roles"])
        records: list[dict[str, Any]] = []
        for record_id, tool_values in sorted(by_record.items()):
            if set(tool_values) != required_tools:
                raise MarketplaceResearchContractError("record_tool_coverage_incomplete")
            roles = {
                self.tool_contracts[tool_id]["semantic_role"]: value["fields"]
                for tool_id, value in tool_values.items()
            }
            if set(roles) != required_roles:
                raise MarketplaceResearchContractError("record_semantic_role_coverage_incomplete")
            fields = [value["fields"] for value in tool_values.values()]
            identity = {(value["site"], value["asin"]) for value in fields}
            if len(identity) != 1:
                raise MarketplaceResearchContractError("record_identity_conflict")
            observed_at = max(value["observed_at"] for value in tool_values.values())
            product = roles["product"]
            market = roles["market"]
            trend = roles["trend"]
            traffic = roles["traffic"]
            reviews = roles["reviews"]
            trademark = roles["trademark"]
            records.append(
                {
                    "record_id": record_id,
                    "site": product["site"],
                    "asin": product["asin"],
                    "category": market["category"],
                    "title": product["title"],
                    "currency": product["currency"],
                    "price": product["price"],
                    "monthly_sales": product["monthly_sales"],
                    "monthly_revenue": product["monthly_revenue"],
                    "review_count": product["review_count"],
                    "rating_bps": product["rating_bps"],
                    "seller_count": product["seller_count"],
                    "market_growth_bps": market["market_growth_bps"],
                    "brand_concentration_bps": market["brand_concentration_bps"],
                    "trend_90d_bps": trend["trend_90d_bps"],
                    "volatility_bps": trend["volatility_bps"],
                    "keyword_count": traffic["keyword_count"],
                    "organic_keyword_count": traffic["organic_keyword_count"],
                    "paid_keyword_count": traffic["paid_keyword_count"],
                    "review_sample_size": reviews["review_sample_size"],
                    "pain_point_count": reviews["pain_point_count"],
                    "positive_ratio_bps": reviews["positive_ratio_bps"],
                    "trademark_state": trademark["trademark_state"],
                    "observed_at": observed_at,
                    "source_tool_ids": sorted(tool_values),
                }
            )
        return records

    def _opportunity(self, record: Mapping[str, Any]) -> dict[str, Any]:
        keyword_count = max(record["keyword_count"], 1)
        review_sample = max(record["review_sample_size"], 1)
        scores = {
            "demand_bps": min(record["monthly_sales"], 10_000),
            "growth_bps": max(0, min(10_000, 5_000 + record["market_growth_bps"])),
            "competition_bps": max(
                0,
                10_000
                - min(
                    10_000,
                    record["brand_concentration_bps"] + min(record["seller_count"] * 100, 3_000),
                ),
            ),
            "traffic_health_bps": min(10_000, record["organic_keyword_count"] * 10_000 // keyword_count),
            "review_opportunity_bps": min(10_000, record["pain_point_count"] * 10_000 // review_sample),
            "trend_stability_bps": max(0, 10_000 - record["volatility_bps"]),
        }
        weights = self.registry["scoring_policy"]["dimension_weights_bps"]
        score = sum(scores[dimension] * weights[dimension] for dimension in scores) // 10_000
        blockers = []
        if record["trademark_state"] != "clear":
            blockers.append("trademark_clearance_required")
        return {
            "record_id": record["record_id"],
            "status": "blocked" if blockers else "ready_for_review",
            "heuristic_score_bps": None if blockers else score,
            "dimension_scores": scores,
            "blockers": blockers,
            "seller_presence_is_buyer_intent": False,
            "profit_claim": "UNKNOWN",
            "global_rank": None,
            "top1_claim": False,
        }

    def _blocked(
        self,
        *,
        context: Mapping[str, Any] | None,
        reason_code: str,
        input_read: bool,
    ) -> MarketplaceResearchProposal:
        core = {
            "contract_id": CONTRACT_ID,
            "registry_sha256": self.registry_sha256,
            "status": "no_data" if not input_read else "blocked",
            "truth_status": "proposal_only",
            "reason_codes": [reason_code],
            "scope_binding_sha256": context["scope_binding_sha256"] if context else None,
            "data_as_of": context["data_as_of"].isoformat() if context else None,
            "authority_checked_at": context["authority_checked_at"].isoformat() if context else None,
            "source": None,
            "receipt": None,
            "market_observations": [],
            "opportunity_proposals": [],
            "citations": [],
            "blockers": [{"code": reason_code, "owner": "marketplace-research-governance"}],
            "control_envelope": self._control_envelope(input_read=input_read),
        }
        proposal_sha256 = _sha256(core)
        return MarketplaceResearchProposal(
            _freeze(
                {
                    **core,
                    "proposal_id": f"mrp_{proposal_sha256[:32]}",
                    "proposal_sha256": proposal_sha256,
                }
            )
        )

    @staticmethod
    def _control_envelope(*, input_read: bool) -> dict[str, Any]:
        return {
            "input_read": input_read,
            "provider_invoked": False,
            "mcp_invoked": False,
            "model_invoked": False,
            "product_created": False,
            "fact_created": False,
            "finance_entry_created": False,
            "approval_created": False,
            "permit_created": False,
            "procurement_created": False,
            "listing_created": False,
            "outreach_created": False,
            "external_write_allowed": False,
        }

    @staticmethod
    def _source_contract_sha256(profile: Mapping[str, Any]) -> str:
        return _sha256(profile)

    @classmethod
    def _load_registry(cls, path: Path) -> dict[str, Any]:
        try:
            registry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MarketplaceResearchContractError("registry_unavailable") from exc
        _exact_keys(
            registry,
            {
                "contract_id",
                "version",
                "as_of",
                "official_sources",
                "source_profiles",
                "tool_contracts",
                "site_codes",
                "normalization",
                "scoring_policy",
                "control_envelope",
            },
            "registry_shape_invalid",
        )
        if registry["contract_id"] != "kjds-marketplace-research-source-contracts-v1":
            raise MarketplaceResearchContractError("registry_contract_invalid")
        if registry["version"] != 1:
            raise MarketplaceResearchContractError("registry_version_invalid")
        if registry["site_codes"] != ["US", "JP", "UK", "DE", "FR", "IT", "ES", "CA", "IN", "MX"]:
            raise MarketplaceResearchContractError("registry_site_codes_invalid")
        official_sources = _sequence(registry["official_sources"], "official_sources")
        if not official_sources or len(official_sources) != len(set(official_sources)):
            raise MarketplaceResearchContractError("registry_official_sources_invalid")
        for source_url in official_sources:
            parsed_source = urlparse(_required(source_url, "official_source_url", maximum=500))
            if parsed_source.scheme != "https" or not parsed_source.hostname or parsed_source.username:
                raise MarketplaceResearchContractError("registry_official_sources_invalid")
        profiles = _sequence(registry["source_profiles"], "source_profiles")
        tools = _sequence(registry["tool_contracts"], "tool_contracts")
        if not profiles:
            raise MarketplaceResearchContractError("registry_source_profiles_invalid")
        profile_by_id: dict[str, Mapping[str, Any]] = {}
        for raw_profile in profiles:
            profile = _exact_keys(
                raw_profile,
                {
                    "source_id",
                    "provider_name",
                    "source_contract_version",
                    "transport",
                    "endpoint",
                    "auth_header_name",
                    "server_identity_state",
                    "server_identity_sha256",
                    "allowed_ingestion_modes",
                    "selected_tool_ids",
                    "official_tool_count_observed",
                    "official_site_count_observed",
                    "max_evidence_grade",
                    "live_adapter_configured",
                    "production_admission",
                    "license_state",
                    "revocation_state",
                    "cost_state",
                    "rate_limit_state",
                    "external_write_allowed",
                },
                "registry_source_profile_shape_invalid",
            )
            source_id = _identifier(profile["source_id"], "source_id")
            if source_id in profile_by_id:
                raise MarketplaceResearchContractError("registry_source_profiles_invalid")
            endpoint = urlparse(_required(profile["endpoint"], "endpoint", maximum=500))
            selected_tool_ids = list(_sequence(profile["selected_tool_ids"], "selected_tool_ids"))
            if (
                not _required(profile["provider_name"], "provider_name", maximum=160)
                or not _identifier(profile["source_contract_version"], "source_contract_version")
                or profile["transport"] not in {"streamable_http", "manual_export"}
                or endpoint.scheme != "https"
                or not endpoint.hostname
                or endpoint.username is not None
                or not _required(profile["auth_header_name"], "auth_header_name", maximum=80)
                or profile["server_identity_state"] != "unverified"
                or profile["allowed_ingestion_modes"] != ["synthetic_fixture", "manual_export"]
                or not selected_tool_ids
                or len(selected_tool_ids) != len(set(selected_tool_ids))
                or type(profile["official_tool_count_observed"]) is not int
                or profile["official_tool_count_observed"] < len(selected_tool_ids)
                or profile["official_site_count_observed"] != len(registry["site_codes"])
                or profile["max_evidence_grade"] not in {"C", "D", "E"}
                or profile["live_adapter_configured"] is not False
                or profile["production_admission"] != "not_admitted"
                or profile["license_state"] != "official_terms_not_independently_verified"
                or profile["revocation_state"] != "unknown"
                or profile["cost_state"] != "unknown"
                or profile["rate_limit_state"] != "unknown"
                or profile["external_write_allowed"] is not False
            ):
                raise MarketplaceResearchContractError("registry_source_profile_invalid")
            _hash64(profile["server_identity_sha256"], "server_identity_sha256")
            profile_by_id[source_id] = profile
        tool_ids: list[str] = []
        source_tools: dict[str, list[str]] = defaultdict(list)
        source_roles: dict[str, list[str]] = defaultdict(list)
        for tool in tools:
            contract = _exact_keys(
                tool,
                {
                    "source_id",
                    "tool_id",
                    "tool_version",
                    "semantic_role",
                    "purpose",
                    "schema",
                },
                "registry_tool_contract_shape_invalid",
            )
            source_id = _identifier(contract["source_id"], "source_id")
            tool_id = _identifier(contract["tool_id"], "tool_id")
            semantic_role = _identifier(contract["semantic_role"], "semantic_role")
            if (
                source_id not in profile_by_id
                or contract["tool_version"] != "fixture-v1"
                or not contract["purpose"]
                or semantic_role not in _CANONICAL_SCHEMAS
            ):
                raise MarketplaceResearchContractError("registry_tool_contract_invalid")
            if contract["schema"] != _CANONICAL_SCHEMAS[semantic_role]:
                raise MarketplaceResearchContractError("registry_tool_schema_invalid")
            tool_ids.append(tool_id)
            source_tools[source_id].append(tool_id)
            source_roles[source_id].append(semantic_role)
        if len(tool_ids) != len(set(tool_ids)):
            raise MarketplaceResearchContractError("registry_tool_contracts_invalid")
        for source_id, profile in profile_by_id.items():
            if source_tools[source_id] != profile["selected_tool_ids"]:
                raise MarketplaceResearchContractError("registry_tool_contracts_invalid")
            if len(source_roles[source_id]) != len(set(source_roles[source_id])):
                raise MarketplaceResearchContractError("registry_semantic_roles_invalid")
        normalization = _exact_keys(
            registry["normalization"],
            {
                "record_id_fields",
                "max_fixture_age_hours",
                "seller_presence_is_buyer_intent",
                "contact_values_allowed",
                "contact_reference_must_be_opaque",
                "purpose_and_do_not_contact_required",
            },
            "registry_normalization_shape_invalid",
        )
        if normalization != {
            "record_id_fields": ["site", "asin"],
            "max_fixture_age_hours": 168,
            "seller_presence_is_buyer_intent": False,
            "contact_values_allowed": False,
            "contact_reference_must_be_opaque": True,
            "purpose_and_do_not_contact_required": True,
        }:
            raise MarketplaceResearchContractError("registry_normalization_invalid")
        scoring = _exact_keys(
            registry["scoring_policy"],
            {
                "policy_id",
                "required_semantic_roles",
                "dimension_weights_bps",
                "leader_allowed",
                "global_top1_allowed",
                "profit_claim_allowed",
            },
            "registry_scoring_policy_shape_invalid",
        )
        if (
            scoring["policy_id"] != "kjds-marketplace-opportunity-heuristic-v1"
            or scoring["leader_allowed"] is not False
            or scoring["global_top1_allowed"] is not False
            or scoring["profit_claim_allowed"] is not False
        ):
            raise MarketplaceResearchContractError("registry_scoring_policy_invalid")
        required_roles = registry["scoring_policy"]["required_semantic_roles"]
        if required_roles != list(_CANONICAL_SCHEMAS):
            raise MarketplaceResearchContractError("registry_required_semantic_roles_invalid")
        if any(source_roles[source_id] != required_roles for source_id in profile_by_id):
            raise MarketplaceResearchContractError("registry_semantic_roles_invalid")
        weights = registry["scoring_policy"]["dimension_weights_bps"]
        if weights != {
            "demand_bps": 2_000,
            "growth_bps": 1_500,
            "competition_bps": 2_000,
            "traffic_health_bps": 1_500,
            "review_opportunity_bps": 1_500,
            "trend_stability_bps": 1_500,
        }:
            raise MarketplaceResearchContractError("registry_scoring_weights_invalid")
        controls = _exact_keys(
            registry["control_envelope"],
            {
                "product_write",
                "fact_write",
                "finance_write",
                "approval_write",
                "permit_write",
                "procurement_write",
                "listing_write",
                "outreach_write",
                "external_write",
            },
            "registry_control_envelope_shape_invalid",
        )
        if any(value is not False for value in controls.values()):
            raise MarketplaceResearchContractError("registry_control_envelope_invalid")
        return registry


__all__ = [
    "MarketplaceResearchContractError",
    "MarketplaceResearchProposal",
    "MarketplaceResearchScopeContext",
    "MarketplaceResearchScopeAuthority",
    "MarketplaceResearchReceiptAuthority",
    "MarketplaceResearchWorkflow",
]
