from __future__ import annotations

import hashlib
import hmac
import json
import re
from base64 import urlsafe_b64encode
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from .security import Principal

CONTRACT_ID = "kjds-strategic-capital-dashboard-v1"
CONTRACT_VERSION = "1.0.0"
EXPECTED_REGISTRY_CONTENT_SHA256 = (
    "81dac7bdd13a3553df327cf0506324654bd1c2dce362f63c8d247618c8104df0"
)
REGISTRY_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "project"
    / "registries"
    / "strategic_capital_dashboard_contracts.json"
)

SECTION_ORDER = (
    "primary_source_coverage",
    "strategic_benchmark",
    "strategic_gaps",
    "opportunity_portfolio",
    "experiment_portfolio",
    "capital_proposals",
    "verified_outcomes",
    "invalidation_review",
)
SECTION_STATUSES = frozenset(
    {
        "ready",
        "partial",
        "no_data",
        "not_connected",
        "stale",
        "invalidated",
        "UNKNOWN",
    }
)
AVAILABLE_STATUSES = frozenset({"ready", "partial", "stale", "invalidated"})
UNAVAILABLE_STATUSES = frozenset({"no_data", "not_connected", "UNKNOWN"})
READ_ROLES = frozenset({"operator", "reviewer", "compliance", "monitor", "admin"})

type SectionId = Literal[
    "primary_source_coverage",
    "strategic_benchmark",
    "strategic_gaps",
    "opportunity_portfolio",
    "experiment_portfolio",
    "capital_proposals",
    "verified_outcomes",
    "invalidation_review",
]
type AvailableStatus = Literal["ready", "partial", "stale", "invalidated"]
type UnavailableStatus = Literal["no_data", "not_connected", "UNKNOWN"]

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_BOUNDED_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$")
_CITATION_TOKEN = re.compile(
    r"^(?:sbc|psc|gdc|gapc|capc|expc|outc|invc)_[A-Za-z0-9_-]{16,256}$"
)


class StrategicCapitalDashboardContractError(ValueError):
    """A frozen BAS-203 read contract was violated."""


class DashboardNoData(LookupError):
    """A connected production read port has no projection for the cutoff."""


@dataclass(frozen=True, slots=True)
class CurrentScopeAuthority:
    tenant_ref: str
    entity_ref: str
    store_ref: str
    authority_sha256: str


@dataclass(frozen=True, slots=True)
class DashboardReadContext:
    """Server-owned scope and time binding passed only to trusted read ports."""

    tenant_ref: str
    entity_ref: str
    store_ref: str
    scope_grant_authority_sha256: str
    data_as_of: datetime
    authority_checked_at: datetime

    @property
    def binding_sha256(self) -> str:
        return _hash_json(
            {
                "tenant_ref": self.tenant_ref,
                "entity_ref": self.entity_ref,
                "store_ref": self.store_ref,
                "scope_grant_authority_sha256": self.scope_grant_authority_sha256,
                "data_as_of": _iso(self.data_as_of),
                "authority_checked_at": _iso(self.authority_checked_at),
            }
        )


@dataclass(frozen=True, slots=True)
class DashboardDisplayItem:
    item_ref: str
    label: str
    display_text: str


@dataclass(frozen=True, slots=True)
class DashboardCitation:
    token: str
    summary_sha256: str


@dataclass(frozen=True, slots=True)
class AvailableSectionProjection:
    section_id: SectionId
    tenant_ref: str
    entity_ref: str
    store_ref: str
    scope_grant_authority_sha256: str
    source_contract_id: str
    source_contract_version: str
    source_contract_sha256: str
    status: AvailableStatus
    reason_codes: tuple[str, ...]
    projection_ref: str
    projection_sha256: str
    data_as_of: datetime
    recorded_at: datetime
    effective_at: datetime
    review_due_at: datetime
    citations: tuple[DashboardCitation, ...]
    display_items: tuple[DashboardDisplayItem, ...]
    invalidation_conditions: tuple[str, ...]
    global_top1_claim: bool = False
    production_admission: bool = False
    actionable_proposal: bool = False


@dataclass(frozen=True, slots=True)
class UnavailableSectionProjection:
    section_id: SectionId
    status: UnavailableStatus
    reason_codes: tuple[str, ...]


type SectionProjection = AvailableSectionProjection | UnavailableSectionProjection


class CurrentScopeAuthorityPort(Protocol):
    def current(
        self,
        *,
        principal: Principal,
        store_ref: str,
        checked_at: datetime,
    ) -> CurrentScopeAuthority: ...


class DashboardSectionReadPort(Protocol):
    def read(
        self, *, principal: Principal, context: DashboardReadContext
    ) -> SectionProjection: ...


class DashboardCitationAuthorityPort(Protocol):
    def issue(
        self,
        *,
        section_id: SectionId,
        context: DashboardReadContext,
        source_ref: str,
        source_sha256: str,
    ) -> DashboardCitation: ...


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=_json_default,
    ).encode("utf-8")


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return _iso(value)
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def _hash_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _aware(value: object, *, field: str) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise StrategicCapitalDashboardContractError(
                f"{field} must be timezone-aware"
            ) from exc
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise StrategicCapitalDashboardContractError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def _iso(value: datetime) -> str:
    return _aware(value, field="timestamp").isoformat().replace("+00:00", "Z")


def _bounded_token(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _BOUNDED_TOKEN.fullmatch(value) is None:
        raise StrategicCapitalDashboardContractError(f"{field} must be a bounded token")
    return value


def _sha256(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise StrategicCapitalDashboardContractError(f"{field} must be lowercase SHA-256")
    return value


def _projection_hash_input(projection: AvailableSectionProjection) -> dict[str, object]:
    return {
        "section_id": projection.section_id,
        "tenant_ref": projection.tenant_ref,
        "entity_ref": projection.entity_ref,
        "store_ref": projection.store_ref,
        "scope_grant_authority_sha256": projection.scope_grant_authority_sha256,
        "source_contract_id": projection.source_contract_id,
        "source_contract_version": projection.source_contract_version,
        "source_contract_sha256": projection.source_contract_sha256,
        "status": projection.status,
        "reason_codes": list(projection.reason_codes),
        "projection_ref": projection.projection_ref,
        "data_as_of": _iso(projection.data_as_of),
        "recorded_at": _iso(projection.recorded_at),
        "effective_at": _iso(projection.effective_at),
        "review_due_at": _iso(projection.review_due_at),
        "citations": [asdict(citation) for citation in projection.citations],
        "display_items": [asdict(item) for item in projection.display_items],
        "invalidation_conditions": list(projection.invalidation_conditions),
        "global_top1_claim": projection.global_top1_claim,
        "production_admission": projection.production_admission,
        "actionable_proposal": projection.actionable_proposal,
    }


def seal_available_projection(
    *,
    section_id: SectionId,
    context: DashboardReadContext,
    source_contract_id: str,
    source_contract_version: str,
    source_contract_sha256: str,
    status: AvailableStatus,
    reason_codes: Sequence[str],
    projection_ref: str,
    data_as_of: datetime,
    recorded_at: datetime,
    effective_at: datetime,
    review_due_at: datetime,
    citations: Sequence[DashboardCitation],
    display_items: Sequence[DashboardDisplayItem],
    invalidation_conditions: Sequence[str],
) -> AvailableSectionProjection:
    """Test/adapter helper; the service still revalidates every field and the seal."""

    projection = AvailableSectionProjection(
        section_id=section_id,
        tenant_ref=context.tenant_ref,
        entity_ref=context.entity_ref,
        store_ref=context.store_ref,
        scope_grant_authority_sha256=context.scope_grant_authority_sha256,
        source_contract_id=source_contract_id,
        source_contract_version=source_contract_version,
        source_contract_sha256=source_contract_sha256,
        status=status,
        reason_codes=tuple(reason_codes),
        projection_ref=projection_ref,
        projection_sha256="0" * 64,
        data_as_of=data_as_of,
        recorded_at=recorded_at,
        effective_at=effective_at,
        review_due_at=review_due_at,
        citations=tuple(citations),
        display_items=tuple(display_items),
        invalidation_conditions=tuple(invalidation_conditions),
    )
    return replace(projection, projection_sha256=_hash_json(_projection_hash_input(projection)))


class StrategicCapitalDashboardRegistry:
    def __init__(self, payload: Mapping[str, object]) -> None:
        self.payload = dict(payload)

    @classmethod
    def load(
        cls, path: str | Path = REGISTRY_PATH
    ) -> StrategicCapitalDashboardRegistry:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise StrategicCapitalDashboardContractError("registry must be an object")
        expected_keys = {
            "schema",
            "contract_id",
            "version",
            "content_sha256",
            "section_order",
            "section_statuses",
            "read_roles",
            "source_contracts",
            "limits",
            "client_contract",
            "zero_authority",
        }
        if set(payload) != expected_keys:
            raise StrategicCapitalDashboardContractError("registry fields drift")
        body = {key: value for key, value in payload.items() if key != "content_sha256"}
        content_sha256 = _hash_json(body)
        if (
            payload["content_sha256"] != content_sha256
            or content_sha256 != EXPECTED_REGISTRY_CONTENT_SHA256
        ):
            raise StrategicCapitalDashboardContractError("registry content seal drift")
        if payload["schema"] != "kjds-strategic-capital-dashboard-contracts-v1":
            raise StrategicCapitalDashboardContractError("registry schema drift")
        if payload["contract_id"] != CONTRACT_ID or payload["version"] != CONTRACT_VERSION:
            raise StrategicCapitalDashboardContractError("registry identity drift")
        if payload["section_order"] != list(SECTION_ORDER):
            raise StrategicCapitalDashboardContractError("section order drift")
        if set(payload["section_statuses"]) != SECTION_STATUSES:
            raise StrategicCapitalDashboardContractError("section status drift")
        if set(payload["read_roles"]) != READ_ROLES:
            raise StrategicCapitalDashboardContractError("read role drift")
        source_contracts = payload["source_contracts"]
        if not isinstance(source_contracts, dict) or set(source_contracts) != set(
            SECTION_ORDER
        ):
            raise StrategicCapitalDashboardContractError("source contract set drift")
        for contract in source_contracts.values():
            if not isinstance(contract, dict) or set(contract) != {
                "contract_id",
                "contract_version",
                "contract_sha256",
                "registry_path",
            }:
                raise StrategicCapitalDashboardContractError(
                    "source contract fields drift"
                )
            _bounded_token(
                str(contract["contract_id"]), field="source contract id"
            )
            _bounded_token(
                str(contract["contract_version"]), field="source contract version"
            )
            contract_sha256 = _sha256(
                str(contract["contract_sha256"]), field="source contract sha256"
            )
            registry_ref = _bounded_token(
                str(contract["registry_path"]), field="source registry path"
            )
            upstream_path = (REGISTRY_PATH.parents[3] / registry_ref).resolve()
            registry_root = (REGISTRY_PATH.parents[3] / "docs/project/registries").resolve()
            if upstream_path.parent != registry_root:
                raise StrategicCapitalDashboardContractError(
                    "source registry path drift"
                )
            try:
                upstream_payload = json.loads(upstream_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise StrategicCapitalDashboardContractError(
                    "source registry unavailable"
                ) from exc
            if contract_sha256 != _hash_json(upstream_payload):
                raise StrategicCapitalDashboardContractError(
                    "source registry content seal drift"
                )
        if payload["limits"] != {
            "max_display_items_per_section": 32,
            "max_citations_per_section": 32,
            "max_reason_codes_per_section": 16,
            "max_invalidation_conditions_per_section": 16,
            "max_display_text_length": 512,
        }:
            raise StrategicCapitalDashboardContractError("registry limits drift")
        client_contract = payload["client_contract"]
        if not isinstance(client_contract, dict) or client_contract != {
            "method": "GET",
            "query_fields": ["store_ref", "as_of"],
            "read_only": True,
            "loads_synthetic_fixtures": False,
            "recomputes_facts": False,
            "recomputes_rankings": False,
            "recomputes_gates": False,
            "recomputes_budget_authority": False,
        }:
            raise StrategicCapitalDashboardContractError("client contract drift")
        zero_authority = payload["zero_authority"]
        if not isinstance(zero_authority, dict) or any(zero_authority.values()):
            raise StrategicCapitalDashboardContractError("zero-authority drift")
        return cls(payload)

    @property
    def content_sha256(self) -> str:
        return str(self.payload["content_sha256"])


class StrategicCapitalDashboardService:
    """Composes already-authoritative observations without creating a new truth."""

    def __init__(
        self,
        *,
        scope_authority: CurrentScopeAuthorityPort,
        section_ports: Mapping[SectionId, DashboardSectionReadPort],
        clock: Callable[[], datetime],
        registry_path: str | Path = REGISTRY_PATH,
    ) -> None:
        unknown_sections = set(section_ports) - set(SECTION_ORDER)
        if unknown_sections:
            raise StrategicCapitalDashboardContractError("unregistered section port")
        self._scope_authority = scope_authority
        self._section_ports = dict(section_ports)
        self._clock = clock
        self._registry = StrategicCapitalDashboardRegistry.load(registry_path)

    def read(
        self,
        *,
        principal: Principal,
        store_ref: str,
        as_of: datetime | None,
    ) -> dict[str, object]:
        store = _bounded_token(store_ref, field="store_ref")
        if not principal.has_any_role(*READ_ROLES):
            raise PermissionError("strategic dashboard read role required")
        if not principal.can_access_store(store):
            raise KeyError("strategic dashboard not found")
        checked_at = self._trusted_now()
        data_as_of = checked_at if as_of is None else _aware(as_of, field="as_of")
        if data_as_of > checked_at:
            raise StrategicCapitalDashboardContractError("as_of exceeds trusted current time")
        scope = self._resolve_scope(
            principal=principal,
            store_ref=store,
            checked_at=checked_at,
        )
        context = DashboardReadContext(
            tenant_ref=scope.tenant_ref,
            entity_ref=scope.entity_ref,
            store_ref=scope.store_ref,
            scope_grant_authority_sha256=scope.authority_sha256,
            data_as_of=data_as_of,
            authority_checked_at=checked_at,
        )
        sections = [
            self._read_section(
                section_id=section_id, principal=principal, context=context
            )
            for section_id in SECTION_ORDER
        ]

        rechecked_at = self._trusted_now()
        if rechecked_at < checked_at:
            raise RuntimeError("trusted clock moved backwards")
        current = self._resolve_scope(
            principal=principal,
            store_ref=store,
            checked_at=rechecked_at,
        )
        if current != scope:
            raise KeyError("strategic dashboard not found")
        sections = [self._apply_currentness(section, rechecked_at) for section in sections]
        overall_state = self._overall_state(sections)
        reason_codes = sorted(
            {
                reason
                for section in sections
                for reason in section["reason_codes"]
                if reason != "current_projection_available"
            }
        )
        dashboard_ref = "dash_" + _hash_json(
            {
                "context_binding_sha256": context.binding_sha256,
                "authority_rechecked_at": _iso(rechecked_at),
                "sections": [
                    {
                        "section_id": section["section_id"],
                        "status": section["status"],
                        "projection_sha256": section.get("projection_sha256"),
                    }
                    for section in sections
                ],
            }
        )
        body: dict[str, object] = {
            "contract_id": CONTRACT_ID,
            "contract_version": CONTRACT_VERSION,
            "registry_content_sha256": self._registry.content_sha256,
            "dashboard_ref": dashboard_ref,
            "scope_binding_sha256": context.binding_sha256,
            "store_ref": store,
            "data_as_of": _iso(data_as_of),
            "authority_checked_at": _iso(rechecked_at),
            "overall_state": overall_state,
            "reason_codes": reason_codes,
            "sections": sections,
            "global_top1_claim": False,
            "production_admission": False,
            "budget_authority": False,
            "side_effects": {
                "evidence_writes": 0,
                "fact_writes": 0,
                "finance_entry_writes": 0,
                "graph_writes": 0,
                "approval_writes": 0,
                "permit_writes": 0,
                "pilot_writes": 0,
                "outbox_writes": 0,
                "external_writes": 0,
                "network_writes": 0,
            },
        }
        return {**body, "observation_sha256": _hash_json(body)}

    def _trusted_now(self) -> datetime:
        try:
            return _aware(self._clock(), field="trusted clock")
        except StrategicCapitalDashboardContractError:
            raise
        except Exception as exc:
            raise RuntimeError("trusted clock unavailable") from exc

    def _resolve_scope(
        self,
        *,
        principal: Principal,
        store_ref: str,
        checked_at: datetime,
    ) -> CurrentScopeAuthority:
        try:
            scope = self._scope_authority.current(
                principal=principal,
                store_ref=store_ref,
                checked_at=checked_at,
            )
        except (KeyError, PermissionError) as exc:
            raise KeyError("strategic dashboard not found") from exc
        if not isinstance(scope, CurrentScopeAuthority):
            raise KeyError("strategic dashboard not found")
        if (
            scope.tenant_ref != principal.tenant_ref
            or scope.store_ref != store_ref
            or not scope.entity_ref
        ):
            raise KeyError("strategic dashboard not found")
        try:
            _bounded_token(scope.tenant_ref, field="scope tenant")
            _bounded_token(scope.entity_ref, field="scope entity")
            _bounded_token(scope.store_ref, field="scope store")
            _sha256(scope.authority_sha256, field="scope authority")
        except StrategicCapitalDashboardContractError as exc:
            raise KeyError("strategic dashboard not found") from exc
        return scope

    def _read_section(
        self,
        *,
        section_id: SectionId,
        principal: Principal,
        context: DashboardReadContext,
    ) -> dict[str, object]:
        port = self._section_ports.get(section_id)
        if port is None:
            return self._unavailable_section(
                section_id=section_id,
                status="not_connected",
                reason="production_projection_not_connected",
                context=context,
            )
        try:
            projection = port.read(principal=principal, context=context)
        except DashboardNoData:
            return self._unavailable_section(
                section_id=section_id,
                status="no_data",
                reason="current_projection_no_data",
                context=context,
            )
        except Exception:
            return self._unavailable_section(
                section_id=section_id,
                status="UNKNOWN",
                reason="projection_authority_unavailable",
                context=context,
            )
        if isinstance(projection, UnavailableSectionProjection):
            return self._validate_unavailable(
                projection, section_id=section_id, context=context
            )
        if not isinstance(projection, AvailableSectionProjection):
            return self._unavailable_section(
                section_id=section_id,
                status="UNKNOWN",
                reason="projection_contract_invalid",
                context=context,
            )
        try:
            return self._validate_available(
                projection,
                section_id=section_id,
                context=context,
            )
        except StrategicCapitalDashboardContractError:
            return self._unavailable_section(
                section_id=section_id,
                status="UNKNOWN",
                reason="projection_contract_invalid",
                context=context,
            )

    def _validate_available(
        self,
        projection: AvailableSectionProjection,
        *,
        section_id: SectionId,
        context: DashboardReadContext,
    ) -> dict[str, object]:
        if projection.section_id != section_id or projection.status not in AVAILABLE_STATUSES:
            raise StrategicCapitalDashboardContractError("section identity drift")
        if (
            projection.tenant_ref != context.tenant_ref
            or projection.entity_ref != context.entity_ref
            or projection.store_ref != context.store_ref
            or projection.scope_grant_authority_sha256
            != context.scope_grant_authority_sha256
        ):
            raise StrategicCapitalDashboardContractError("section scope drift")
        contract = self._registry.payload["source_contracts"][section_id]
        if (
            projection.source_contract_id != contract["contract_id"]
            or projection.source_contract_version != contract["contract_version"]
            or projection.source_contract_sha256 != contract["contract_sha256"]
        ):
            raise StrategicCapitalDashboardContractError("section contract drift")
        if (
            projection.global_top1_claim
            or projection.production_admission
            or projection.actionable_proposal
        ):
            raise StrategicCapitalDashboardContractError("section authority escalation")
        projection_ref = _bounded_token(projection.projection_ref, field="projection_ref")
        projection_sha256 = _sha256(
            projection.projection_sha256, field="projection_sha256"
        )
        if projection_sha256 != _hash_json(_projection_hash_input(projection)):
            raise StrategicCapitalDashboardContractError("projection seal drift")
        data_as_of = _aware(projection.data_as_of, field="section data_as_of")
        recorded_at = _aware(projection.recorded_at, field="section recorded_at")
        effective_at = _aware(projection.effective_at, field="section effective_at")
        review_due_at = _aware(projection.review_due_at, field="section review_due_at")
        if any(value > context.data_as_of for value in (data_as_of, recorded_at, effective_at)):
            raise StrategicCapitalDashboardContractError("future or backfilled projection")
        if review_due_at <= effective_at:
            raise StrategicCapitalDashboardContractError("invalid review window")
        reason_codes = self._reason_codes(projection.reason_codes)
        citations = self._citations(projection.citations)
        display_items = self._display_items(projection.display_items)
        invalidation_conditions = self._invalidation_conditions(
            projection.invalidation_conditions
        )
        if not citations:
            raise StrategicCapitalDashboardContractError(
                "available section requires a citation"
            )
        if not invalidation_conditions:
            raise StrategicCapitalDashboardContractError(
                "available section requires an invalidation condition"
            )
        if projection.status in {"ready", "partial"} and not display_items:
            raise StrategicCapitalDashboardContractError(
                "current section requires a display item"
            )
        if projection.status in {"stale", "invalidated"} and display_items:
            raise StrategicCapitalDashboardContractError(
                "non-current section cannot display data"
            )
        return {
            "section_id": section_id,
            "display_order": SECTION_ORDER.index(section_id),
            "scope_binding_sha256": context.binding_sha256,
            "source_contract_id": projection.source_contract_id,
            "source_contract_version": projection.source_contract_version,
            "source_contract_sha256": projection.source_contract_sha256,
            "status": projection.status,
            "reason_codes": reason_codes,
            "projection_ref": projection_ref,
            "projection_sha256": projection_sha256,
            "data_as_of": _iso(data_as_of),
            "recorded_at": _iso(recorded_at),
            "effective_at": _iso(effective_at),
            "review_due_at": _iso(review_due_at),
            "citations": citations,
            "display_items": display_items,
            "invalidation_conditions": invalidation_conditions,
            "global_top1_claim": False,
            "production_admission": False,
            "actionable_proposal": False,
        }

    def _validate_unavailable(
        self,
        projection: UnavailableSectionProjection,
        *,
        section_id: SectionId,
        context: DashboardReadContext,
    ) -> dict[str, object]:
        if projection.section_id != section_id or projection.status not in UNAVAILABLE_STATUSES:
            return self._unavailable_section(
                section_id=section_id,
                status="UNKNOWN",
                reason="projection_contract_invalid",
                context=context,
            )
        try:
            reasons = self._reason_codes(projection.reason_codes)
        except StrategicCapitalDashboardContractError:
            return self._unavailable_section(
                section_id=section_id,
                status="UNKNOWN",
                reason="projection_contract_invalid",
                context=context,
            )
        contract = self._registry.payload["source_contracts"][section_id]
        return {
            "section_id": section_id,
            "display_order": SECTION_ORDER.index(section_id),
            "scope_binding_sha256": context.binding_sha256,
            "source_contract_id": contract["contract_id"],
            "source_contract_version": contract["contract_version"],
            "source_contract_sha256": contract["contract_sha256"],
            "status": projection.status,
            "reason_codes": reasons,
            "citations": [],
            "display_items": [],
            "invalidation_conditions": [],
            "global_top1_claim": False,
            "production_admission": False,
            "actionable_proposal": False,
        }

    def _unavailable_section(
        self,
        *,
        section_id: SectionId,
        status: UnavailableStatus,
        reason: str,
        context: DashboardReadContext,
    ) -> dict[str, object]:
        return self._validate_unavailable(
            UnavailableSectionProjection(
                section_id=section_id,
                status=status,
                reason_codes=(reason,),
            ),
            section_id=section_id,
            context=context,
        )

    def _reason_codes(self, values: Sequence[str]) -> list[str]:
        limit = int(self._registry.payload["limits"]["max_reason_codes_per_section"])
        if not values or len(values) > limit:
            raise StrategicCapitalDashboardContractError("reason code count invalid")
        projected = [_bounded_token(value, field="reason_code") for value in values]
        if len(projected) != len(set(projected)):
            raise StrategicCapitalDashboardContractError("duplicate reason code")
        return projected

    def _citations(
        self, values: Sequence[DashboardCitation]
    ) -> list[dict[str, str]]:
        limit = int(self._registry.payload["limits"]["max_citations_per_section"])
        if not values or len(values) > limit:
            raise StrategicCapitalDashboardContractError("citation count invalid")
        projected: list[dict[str, str]] = []
        tokens: set[str] = set()
        for value in values:
            if not isinstance(value, DashboardCitation):
                raise StrategicCapitalDashboardContractError("citation type invalid")
            if _CITATION_TOKEN.fullmatch(value.token) is None:
                raise StrategicCapitalDashboardContractError("citation must be opaque")
            if value.token in tokens:
                raise StrategicCapitalDashboardContractError("duplicate citation token")
            tokens.add(value.token)
            projected.append(
                {
                    "token": value.token,
                    "summary_sha256": _sha256(
                        value.summary_sha256, field="citation summary sha256"
                    ),
                }
            )
        return projected

    def _display_items(self, values: Sequence[DashboardDisplayItem]) -> list[dict[str, str]]:
        limits = self._registry.payload["limits"]
        if len(values) > int(limits["max_display_items_per_section"]):
            raise StrategicCapitalDashboardContractError("display item count invalid")
        projected: list[dict[str, str]] = []
        refs: set[str] = set()
        for item in values:
            if not isinstance(item, DashboardDisplayItem):
                raise StrategicCapitalDashboardContractError("display item type invalid")
            item_ref = _bounded_token(item.item_ref, field="display item ref")
            if item_ref in refs:
                raise StrategicCapitalDashboardContractError("duplicate display item")
            refs.add(item_ref)
            if not item.label.strip() or len(item.label) > 120:
                raise StrategicCapitalDashboardContractError("display label invalid")
            if (
                not item.display_text.strip()
                or len(item.display_text) > int(limits["max_display_text_length"])
            ):
                raise StrategicCapitalDashboardContractError("display text invalid")
            projected.append(
                {
                    "item_ref": item_ref,
                    "label": item.label,
                    "display_text": item.display_text,
                }
            )
        return projected

    def _invalidation_conditions(self, values: Sequence[str]) -> list[str]:
        limit = int(
            self._registry.payload["limits"]["max_invalidation_conditions_per_section"]
        )
        if len(values) > limit:
            raise StrategicCapitalDashboardContractError("invalidation count invalid")
        projected = [_bounded_token(value, field="invalidation condition") for value in values]
        if len(projected) != len(set(projected)):
            raise StrategicCapitalDashboardContractError("duplicate invalidation condition")
        return projected

    @staticmethod
    def _apply_currentness(section: dict[str, object], checked_at: datetime) -> dict[str, object]:
        if section["status"] not in AVAILABLE_STATUSES:
            return section
        if section["status"] in {"invalidated", "stale"}:
            projected = dict(section)
            projected["display_items"] = []
            projected["actionable_proposal"] = False
            return projected
        review_due_at = datetime.fromisoformat(str(section["review_due_at"]).replace("Z", "+00:00"))
        if review_due_at > checked_at:
            return section
        projected = dict(section)
        projected["status"] = "stale"
        reasons = [reason for reason in section["reason_codes"] if reason != "current_projection_available"]
        projected["reason_codes"] = sorted({*reasons, "review_due_expired"})
        projected["display_items"] = []
        projected["actionable_proposal"] = False
        return projected

    @staticmethod
    def _overall_state(sections: Sequence[Mapping[str, object]]) -> str:
        statuses = [str(section["status"]) for section in sections]
        if "UNKNOWN" in statuses:
            return "UNKNOWN"
        if "invalidated" in statuses:
            return "invalidated"
        if "stale" in statuses:
            return "stale"
        if all(status == "ready" for status in statuses):
            return "ready"
        if all(status in {"no_data", "not_connected"} for status in statuses):
            return "no_data"
        return "partial"


class RuntimeCurrentScopeAuthority:
    """Adapts the production scope grant service to a trusted-current read port."""

    def __init__(self, *, scope_grants: Any) -> None:
        self._scope_grants = scope_grants

    def current(
        self,
        *,
        principal: Principal,
        store_ref: str,
        checked_at: datetime,
    ) -> CurrentScopeAuthority:
        try:
            projection = self._scope_grants.current(
                principal=principal,
                store_ref=store_ref,
                as_of=checked_at,
            )
        except (KeyError, PermissionError, TypeError, ValueError, RuntimeError):
            raise KeyError("current exact-scope authority unavailable") from None
        if not isinstance(projection, Mapping) or projection.get("status") != "ready":
            raise KeyError("current exact-scope authority unavailable")
        raw_fields = {
            "tenant_ref": projection.get("tenant_ref"),
            "entity_ref": projection.get("entity_ref"),
            "store_ref": projection.get("store_ref"),
            "authority_sha256": projection.get("authority_sha256"),
        }
        if any(not isinstance(value, str) for value in raw_fields.values()):
            raise KeyError("current exact-scope authority unavailable")
        try:
            tenant_ref = _bounded_token(raw_fields["tenant_ref"], field="tenant_ref")
            entity_ref = _bounded_token(raw_fields["entity_ref"], field="entity_ref")
            authority_store = _bounded_token(
                raw_fields["store_ref"], field="store_ref"
            )
            authority_sha256 = _sha256(
                raw_fields["authority_sha256"], field="authority_sha256"
            )
        except StrategicCapitalDashboardContractError:
            raise KeyError("current exact-scope authority unavailable") from None
        if tenant_ref != principal.tenant_ref or authority_store != store_ref:
            raise KeyError("current exact-scope authority unavailable")
        return CurrentScopeAuthority(
            tenant_ref=tenant_ref,
            entity_ref=entity_ref,
            store_ref=authority_store,
            authority_sha256=authority_sha256,
        )


class ScopedDashboardCitationAuthority:
    """Issues non-reversible citation tokens bound to exact scope and source hash."""

    def __init__(self, *, sealing_key: bytes) -> None:
        if not isinstance(sealing_key, bytes) or len(sealing_key) < 32:
            raise RuntimeError("dashboard citation sealing key must contain 32 bytes")
        self._key = hmac.new(
            sealing_key,
            b"strategic-capital-dashboard-citation-v1",
            hashlib.sha256,
        ).digest()

    def issue(
        self,
        *,
        section_id: SectionId,
        context: DashboardReadContext,
        source_ref: str,
        source_sha256: str,
    ) -> DashboardCitation:
        prefixes = {
            "primary_source_coverage": "psc",
            "strategic_benchmark": "sbc",
        }
        prefix = prefixes.get(section_id)
        if prefix is None:
            raise StrategicCapitalDashboardContractError(
                "citation section is not authority-enabled"
            )
        source = _bounded_token(source_ref, field="citation source ref")
        summary_sha256 = _sha256(source_sha256, field="citation source sha256")
        payload = _canonical_json(
            {
                "section_id": section_id,
                "tenant_ref": context.tenant_ref,
                "entity_ref": context.entity_ref,
                "store_ref": context.store_ref,
                "scope_grant_authority_sha256": (
                    context.scope_grant_authority_sha256
                ),
                "source_ref": source,
                "source_sha256": summary_sha256,
            }
        )
        token = urlsafe_b64encode(
            hmac.new(self._key, payload, hashlib.sha256).digest()
        ).rstrip(b"=").decode("ascii")
        return DashboardCitation(
            token=f"{prefix}_{token}", summary_sha256=summary_sha256
        )


class PrimarySourceCoverageReadPort:
    """Projects persisted Primary Source Intake coverage without raw source records."""

    def __init__(
        self,
        *,
        service: Any,
        source_contract: Mapping[str, object],
        citation_authority: DashboardCitationAuthorityPort,
    ) -> None:
        self._service = service
        self._source_contract = dict(source_contract)
        self._citation_authority = citation_authority

    def read(
        self, *, principal: Principal, context: DashboardReadContext
    ) -> SectionProjection:
        listed = self._service.list(
            principal=principal,
            store_ref=context.store_ref,
            as_of=context.data_as_of,
            limit=100,
            expected_scope_authority_sha256=(
                context.scope_grant_authority_sha256
            ),
        )
        items = listed.get("items") if isinstance(listed, Mapping) else None
        if listed.get("contract_id") != self._source_contract["contract_id"]:
            raise StrategicCapitalDashboardContractError(
                "primary source contract drift"
            )
        if not isinstance(items, list):
            raise StrategicCapitalDashboardContractError("primary source list invalid")
        if not items:
            raise DashboardNoData("primary source coverage has no current data")
        if listed.get("next_cursor") is not None:
            return UnavailableSectionProjection(
                section_id="primary_source_coverage",
                status="UNKNOWN",
                reason_codes=("bounded_page_not_current",),
            )
        latest_by_pack: dict[str, Mapping[str, Any]] = {}
        for item in items:
            if not isinstance(item, Mapping):
                raise StrategicCapitalDashboardContractError(
                    "primary source item invalid"
                )
            if item.get("scope_binding_sha256") != context.scope_grant_authority_sha256:
                raise StrategicCapitalDashboardContractError(
                    "primary source scope binding drift"
                )
            if item.get("store_ref") != context.store_ref:
                raise StrategicCapitalDashboardContractError(
                    "primary source store binding drift"
                )
            source_pack_id = _bounded_token(
                str(item.get("source_pack_id")), field="source_pack_id"
            )
            prior = latest_by_pack.get(source_pack_id)
            created_at = _aware(item.get("created_at"), field="created_at")
            if prior is not None and created_at == _aware(
                prior.get("created_at"), field="created_at"
            ):
                raise StrategicCapitalDashboardContractError(
                    "primary source latest projection tie"
                )
            if prior is None or created_at > _aware(
                prior.get("created_at"), field="created_at"
            ):
                latest_by_pack[source_pack_id] = item
        selected = [latest_by_pack[key] for key in sorted(latest_by_pack)]
        if len(selected) > 32:
            raise StrategicCapitalDashboardContractError(
                "primary source display bound exceeded"
            )
        data_as_of = min(_aware(item.get("as_of"), field="as_of") for item in selected)
        recorded_at = max(
            _aware(item.get("created_at"), field="created_at") for item in selected
        )
        effective_at = max(
            _aware(item.get("effective_at"), field="effective_at")
            for item in selected
        )
        review_due_at = min(
            _aware(item.get("review_due_at"), field="review_due_at")
            for item in selected
        )
        partial = any(
            item.get("status") == "partial" or item.get("admission_grade") == "C"
            for item in selected
        )
        reason_codes = [
            "current_projection_available",
            *( ["bounded_page_or_lower_grade"] if partial else [] ),
        ]
        display_items = []
        citations = []
        projection_refs = []
        for item in selected:
            counts = item.get("counts")
            pagination = item.get("pagination")
            evidence = item.get("evidence")
            if not all(isinstance(value, Mapping) for value in (counts, pagination, evidence)):
                raise StrategicCapitalDashboardContractError(
                    "primary source projection shape invalid"
                )
            display_items.append(
                DashboardDisplayItem(
                    item_ref=_bounded_token(
                        str(item.get("intake_ref")), field="intake_ref"
                    ),
                    label=_bounded_token(
                        str(item.get("source_pack_id")), field="source_pack_id"
                    ),
                    display_text=(
                        f"{item.get('status')} · accepted {counts.get('accepted')} · "
                        f"failed pages {pagination.get('failed_page_count')}"
                    ),
                )
            )
            citations.append(
                self._citation_authority.issue(
                    section_id="primary_source_coverage",
                    context=context,
                    source_ref=str(evidence.get("id")),
                    source_sha256=str(evidence.get("sha256")),
                )
            )
            projection_refs.append(str(item.get("intake_ref")))
        return seal_available_projection(
            section_id="primary_source_coverage",
            context=context,
            source_contract_id=str(self._source_contract["contract_id"]),
            source_contract_version=str(self._source_contract["contract_version"]),
            source_contract_sha256=str(self._source_contract["contract_sha256"]),
            status="partial" if partial else "ready",
            reason_codes=reason_codes,
            projection_ref="coverage_" + _hash_json(projection_refs)[:40],
            data_as_of=data_as_of,
            recorded_at=recorded_at,
            effective_at=effective_at,
            review_due_at=review_due_at,
            citations=citations,
            display_items=display_items,
            invalidation_conditions=(
                "scope_authority_rotation",
                "source_contract_drift",
                "source_review_due",
            ),
        )


class StrategicBenchmarkReadPort:
    """Projects persisted dimension-specific benchmark results without re-ranking."""

    def __init__(self, *, service: Any, source_contract: Mapping[str, object]) -> None:
        self._service = service
        self._source_contract = dict(source_contract)

    def read(
        self, *, principal: Principal, context: DashboardReadContext
    ) -> SectionProjection:
        listed = self._service.list(
            principal=principal,
            store_ref=context.store_ref,
            as_of=context.data_as_of,
            limit=100,
            expected_scope_authority_sha256=(
                context.scope_grant_authority_sha256
            ),
        )
        items = listed.get("items") if isinstance(listed, Mapping) else None
        if listed.get("contract_id") != self._source_contract["contract_id"]:
            raise StrategicCapitalDashboardContractError(
                "benchmark source contract drift"
            )
        if not isinstance(items, list):
            raise StrategicCapitalDashboardContractError("benchmark list invalid")
        if not items:
            raise DashboardNoData("strategic benchmark has no current data")
        if listed.get("next_cursor") is not None:
            return UnavailableSectionProjection(
                section_id="strategic_benchmark",
                status="UNKNOWN",
                reason_codes=("bounded_page_not_current",),
            )
        if any(not isinstance(item, Mapping) for item in items):
            raise StrategicCapitalDashboardContractError("benchmark item invalid")
        latest_created_at = max(
            _aware(item.get("created_at"), field="created_at") for item in items
        )
        latest_candidates = [
            item
            for item in items
            if _aware(item.get("created_at"), field="created_at")
            == latest_created_at
        ]
        if len(latest_candidates) != 1:
            raise StrategicCapitalDashboardContractError(
                "benchmark latest projection tie"
            )
        latest = latest_candidates[0]
        if (
            latest.get("store_ref") != context.store_ref
        ):
            raise StrategicCapitalDashboardContractError(
                "benchmark scope binding drift"
            )
        result = self._service.get(
            principal=principal,
            store_ref=context.store_ref,
            as_of=context.data_as_of,
            snapshot_ref=latest.get("snapshot_ref"),
            expected_scope_authority_sha256=(
                context.scope_grant_authority_sha256
            ),
        )
        if not isinstance(result, Mapping):
            raise StrategicCapitalDashboardContractError("benchmark projection invalid")
        if result.get("contract_id") != self._source_contract["contract_id"]:
            raise StrategicCapitalDashboardContractError(
                "benchmark source contract drift"
            )
        snapshot = result.get("snapshot")
        groups = result.get("groups")
        if not isinstance(snapshot, Mapping) or not isinstance(groups, list):
            raise StrategicCapitalDashboardContractError("benchmark projection invalid")
        if (
            snapshot.get("store_ref") != context.store_ref
            or snapshot.get("global_top1_claim") is not False
        ):
            raise StrategicCapitalDashboardContractError(
                "benchmark snapshot binding drift"
            )
        if len(groups) > 32:
            raise StrategicCapitalDashboardContractError("benchmark display bound exceeded")
        freshness_due = [
            _aware(observation.get("freshness_due_at"), field="freshness_due_at")
            for group in groups
            if isinstance(group, Mapping)
            for observation in group.get("observations", [])
            if isinstance(observation, Mapping)
        ]
        if not freshness_due:
            raise DashboardNoData("strategic benchmark has no current observations")
        display_items: list[DashboardDisplayItem] = []
        states: list[str] = []
        for group in groups:
            if not isinstance(group, Mapping) or group.get("global_top1_claim") is not False:
                raise StrategicCapitalDashboardContractError(
                    "benchmark global Top1 or group shape drift"
                )
            state = _bounded_token(
                str(group.get("comparison_state")), field="comparison_state"
            )
            states.append(state)
            leader = group.get("leader_label") or "no leader"
            display_items.append(
                DashboardDisplayItem(
                    item_ref=_bounded_token(
                        str(group.get("group_ref")), field="group_ref"
                    ),
                    label=(
                        f"{group.get('domain')} · {group.get('metric_id')} · "
                        f"{group.get('cohort_ref')}"
                    ),
                    display_text=f"{state} · {leader}",
                )
            )
        citation = snapshot.get("snapshot_citation")
        if not isinstance(citation, Mapping):
            raise StrategicCapitalDashboardContractError("benchmark citation invalid")
        if all(state == "no_data" for state in states):
            return UnavailableSectionProjection(
                section_id="strategic_benchmark",
                status="no_data",
                reason_codes=("upstream_projection_no_data",),
            )
        if "invalidated" in states:
            section_status: AvailableStatus = "invalidated"
            state_reason = "upstream_projection_invalidated"
        elif "stale" in states:
            section_status = "stale"
            state_reason = "upstream_projection_stale"
        elif any(state != "comparable" for state in states):
            section_status = "partial"
            state_reason = "dimension_not_comparable"
        else:
            section_status = "ready"
            state_reason = "current_projection_available"
        projected_items = (
            ()
            if section_status in {"invalidated", "stale"}
            else tuple(display_items)
        )
        return seal_available_projection(
            section_id="strategic_benchmark",
            context=context,
            source_contract_id=str(self._source_contract["contract_id"]),
            source_contract_version=str(self._source_contract["contract_version"]),
            source_contract_sha256=str(self._source_contract["contract_sha256"]),
            status=section_status,
            reason_codes=(state_reason,),
            projection_ref=_bounded_token(
                str(snapshot.get("snapshot_ref")), field="snapshot_ref"
            ),
            data_as_of=_aware(snapshot.get("as_of"), field="snapshot.as_of"),
            recorded_at=_aware(snapshot.get("created_at"), field="snapshot.created_at"),
            effective_at=_aware(snapshot.get("as_of"), field="snapshot.as_of"),
            review_due_at=min(freshness_due),
            citations=(
                DashboardCitation(
                    token=str(citation.get("token")),
                    summary_sha256=str(citation.get("sha256")),
                ),
            ),
            display_items=projected_items,
            invalidation_conditions=(
                "scope_authority_rotation",
                "benchmark_contract_drift",
                "benchmark_review_due",
            ),
        )


__all__ = [
    "CONTRACT_ID",
    "CONTRACT_VERSION",
    "SECTION_ORDER",
    "AvailableSectionProjection",
    "CurrentScopeAuthority",
    "CurrentScopeAuthorityPort",
    "DashboardCitation",
    "DashboardCitationAuthorityPort",
    "DashboardDisplayItem",
    "DashboardNoData",
    "DashboardReadContext",
    "DashboardSectionReadPort",
    "PrimarySourceCoverageReadPort",
    "RuntimeCurrentScopeAuthority",
    "ScopedDashboardCitationAuthority",
    "StrategicBenchmarkReadPort",
    "StrategicCapitalDashboardContractError",
    "StrategicCapitalDashboardRegistry",
    "StrategicCapitalDashboardService",
    "UnavailableSectionProjection",
    "seal_available_projection",
]
