from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apps.control_plane.security import Principal
from apps.control_plane.strategic_capital_dashboard import (
    CONTRACT_ID,
    EXPECTED_REGISTRY_CONTENT_SHA256,
    SECTION_ORDER,
    AvailableSectionProjection,
    CurrentScopeAuthority,
    DashboardCitation,
    DashboardDisplayItem,
    DashboardNoData,
    DashboardReadContext,
    PrimarySourceCoverageReadPort,
    RuntimeCurrentScopeAuthority,
    ScopedDashboardCitationAuthority,
    StrategicBenchmarkReadPort,
    StrategicCapitalDashboardContractError,
    StrategicCapitalDashboardRegistry,
    StrategicCapitalDashboardService,
    UnavailableSectionProjection,
    seal_available_projection,
)
from tests.test_primary_source_intake import (
    admit as admit_primary_source,
)
from tests.test_primary_source_intake import (
    intake_runtime as _intake_runtime_fixture,
)
from tests.test_primary_source_intake import (
    principal as primary_principal,
)
from tests.test_primary_source_intake import (
    record as primary_record,
)
from tests.test_strategic_benchmark import (
    NOW as BENCHMARK_NOW,
)
from tests.test_strategic_benchmark import (
    benchmark_runtime as _benchmark_runtime_fixture,
)
from tests.test_strategic_benchmark import (
    build as build_benchmark,
)
from tests.test_strategic_benchmark import (
    group as benchmark_group,
)

FIXTURE_PATH = Path(
    "tests/fixtures/strategic_capital_dashboard/bas203_dashboard_v1.json"
)

AS_OF = datetime(2026, 8, 5, 0, 0, tzinfo=UTC)
CHECKED_AT = datetime(2026, 8, 5, 1, 0, tzinfo=UTC)
AUTHORITY_SHA = "a" * 64


class _Clock:
    def __init__(self, *values: datetime) -> None:
        self.values = list(values)
        self.calls = 0

    def __call__(self) -> datetime:
        self.calls += 1
        if len(self.values) > 1:
            return self.values.pop(0)
        return self.values[0]


class _ScopeAuthority:
    def __init__(self, *values: CurrentScopeAuthority | Exception) -> None:
        self.values = list(values)
        self.calls: list[dict[str, object]] = []

    def current(self, **values):
        self.calls.append(values)
        selected = self.values.pop(0) if len(self.values) > 1 else self.values[0]
        if isinstance(selected, Exception):
            raise selected
        return selected


class _Port:
    def __init__(self, value) -> None:
        self.value = value
        self.calls = []

    def read(self, *, principal, context):
        assert principal.tenant_ref == context.tenant_ref
        self.calls.append(context)
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


def _principal(**overrides) -> Principal:
    values = {
        "actor_id": "actor-fixture",
        "roles": frozenset({"reviewer"}),
        "tenant_ref": "tenant-fixture",
        "store_refs": frozenset({"store-fixture"}),
    }
    values.update(overrides)
    return Principal(**values)


def _scope(**overrides) -> CurrentScopeAuthority:
    values = {
        "tenant_ref": "tenant-fixture",
        "entity_ref": "entity-fixture",
        "store_ref": "store-fixture",
        "authority_sha256": AUTHORITY_SHA,
    }
    values.update(overrides)
    return CurrentScopeAuthority(**values)


def _context() -> DashboardReadContext:
    return DashboardReadContext(
        tenant_ref="tenant-fixture",
        entity_ref="entity-fixture",
        store_ref="store-fixture",
        scope_grant_authority_sha256=AUTHORITY_SHA,
        data_as_of=AS_OF,
        authority_checked_at=CHECKED_AT,
    )


def _projection(
    section_id="primary_source_coverage",
    *,
    status="ready",
    review_due_at=CHECKED_AT + timedelta(days=1),
) -> AvailableSectionProjection:
    contract = StrategicCapitalDashboardRegistry.load().payload["source_contracts"][
        section_id
    ]
    return seal_available_projection(
        section_id=section_id,
        context=_context(),
        source_contract_id=contract["contract_id"],
        source_contract_version=contract["contract_version"],
        source_contract_sha256=contract["contract_sha256"],
        status=status,
        reason_codes=("current_projection_available",),
        projection_ref=f"projection/{section_id}/v1",
        data_as_of=AS_OF,
        recorded_at=AS_OF,
        effective_at=AS_OF - timedelta(hours=1),
        review_due_at=review_due_at,
        citations=(
            DashboardCitation(
                token="psc_abcdefghijklmnopqrstuvwxyz012345",
                summary_sha256="b" * 64,
            ),
        ),
        display_items=(
            DashboardDisplayItem(
                item_ref="coverage-summary",
                label="Coverage",
                display_text="Server-authoritative observation is available.",
            ),
        ),
        invalidation_conditions=("authority_rotation", "review_due_expired"),
    )


def _service(
    *,
    ports=None,
    authority=None,
    clock=None,
) -> StrategicCapitalDashboardService:
    return StrategicCapitalDashboardService(
        scope_authority=authority or _ScopeAuthority(_scope()),
        section_ports=ports or {},
        clock=clock or _Clock(CHECKED_AT, CHECKED_AT),
    )


def _canonical_hash_without(payload: dict, key: str) -> str:
    body = {name: value for name, value in payload.items() if name != key}
    raw = json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def test_registry_and_fixture_seals_are_frozen() -> None:
    registry = StrategicCapitalDashboardRegistry.load()
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    assert registry.content_sha256 == EXPECTED_REGISTRY_CONTENT_SHA256
    assert fixture["content_sha256"] == _canonical_hash_without(
        fixture, "content_sha256"
    )
    assert fixture["expected"]["section_order"] == list(SECTION_ORDER)
    assert fixture["expected"]["loads_by_production_runtime"] is False


def test_registry_rejects_upstream_source_contract_content_drift(monkeypatch) -> None:
    registry = StrategicCapitalDashboardRegistry.load()
    source_contract = registry.payload["source_contracts"][
        "primary_source_coverage"
    ]
    upstream_path = (
        Path(".").resolve() / str(source_contract["registry_path"])
    ).resolve()
    original_read_text = Path.read_text

    def drifted_read_text(path: Path, *args, **kwargs) -> str:
        raw = original_read_text(path, *args, **kwargs)
        if path.resolve() != upstream_path:
            return raw
        payload = json.loads(raw)
        payload["contract_id"] = "drifted-primary-source-contract"
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    monkeypatch.setattr(Path, "read_text", drifted_read_text)
    with pytest.raises(
        StrategicCapitalDashboardContractError,
        match="source registry content seal drift",
    ):
        StrategicCapitalDashboardRegistry.load()


def test_read_derives_server_owned_context_and_separates_current_authority_time() -> None:
    port = _Port(_projection())
    authority = _ScopeAuthority(_scope())
    service = _service(
        ports={"primary_source_coverage": port},
        authority=authority,
    )

    result = service.read(
        principal=_principal(),
        store_ref="store-fixture",
        as_of=AS_OF,
    )

    assert result["contract_id"] == CONTRACT_ID
    assert len(authority.calls) == 2
    assert all(call["checked_at"] == CHECKED_AT for call in authority.calls)
    context = port.calls[0]
    assert context.data_as_of == AS_OF
    assert context.authority_checked_at == CHECKED_AT
    assert context.tenant_ref == "tenant-fixture"
    assert context.entity_ref == "entity-fixture"
    assert context.scope_grant_authority_sha256 == AUTHORITY_SHA
    serialized = json.dumps(result)
    assert "tenant-fixture" not in serialized
    assert "entity-fixture" not in serialized
    assert AUTHORITY_SHA not in serialized


def test_read_always_returns_eight_ordered_sections_and_missing_ports_not_connected() -> None:
    result = _service().read(
        principal=_principal(), store_ref="store-fixture", as_of=AS_OF
    )

    assert [section["section_id"] for section in result["sections"]] == list(
        SECTION_ORDER
    )
    assert [section["display_order"] for section in result["sections"]] == list(
        range(8)
    )
    assert {section["status"] for section in result["sections"]} == {
        "not_connected"
    }
    assert result["overall_state"] == "no_data"


def test_missing_gap_capital_and_outcome_ports_never_load_synthetic_fixture() -> None:
    fixture_before = FIXTURE_PATH.read_bytes()
    result = _service(
        ports={
            "primary_source_coverage": _Port(_projection()),
            "strategic_benchmark": _Port(_projection("strategic_benchmark")),
        }
    ).read(principal=_principal(), store_ref="store-fixture", as_of=AS_OF)
    sections = {item["section_id"]: item for item in result["sections"]}

    assert sections["strategic_gaps"]["status"] == "not_connected"
    assert sections["capital_proposals"]["status"] == "not_connected"
    assert sections["verified_outcomes"]["status"] == "not_connected"
    assert sections["capital_proposals"]["display_items"] == []
    assert FIXTURE_PATH.read_bytes() == fixture_before


def test_connected_port_can_distinguish_no_data_from_unknown() -> None:
    result = _service(
        ports={
            "primary_source_coverage": _Port(DashboardNoData()),
            "strategic_benchmark": _Port(RuntimeError("private upstream detail")),
        }
    ).read(principal=_principal(), store_ref="store-fixture", as_of=AS_OF)
    sections = {item["section_id"]: item for item in result["sections"]}

    assert sections["primary_source_coverage"]["status"] == "no_data"
    assert sections["strategic_benchmark"]["status"] == "UNKNOWN"
    assert "private upstream detail" not in json.dumps(result)


def test_zero_authority_and_zero_write_projection_is_literal() -> None:
    result = _service(
        ports={"primary_source_coverage": _Port(_projection())}
    ).read(principal=_principal(), store_ref="store-fixture", as_of=AS_OF)

    assert result["global_top1_claim"] is False
    assert result["production_admission"] is False
    assert result["budget_authority"] is False
    assert set(result["side_effects"].values()) == {0}
    for section in result["sections"]:
        assert section["global_top1_claim"] is False
        assert section["production_admission"] is False
        assert section["actionable_proposal"] is False


@pytest.mark.parametrize(
    "scope",
    [
        _scope(tenant_ref="other-tenant"),
        _scope(entity_ref=""),
        _scope(store_ref="other-store"),
        _scope(authority_sha256="not-a-sha"),
    ],
)
def test_wrong_exact_scope_is_non_enumerable(scope) -> None:
    service = _service(authority=_ScopeAuthority(scope))
    with pytest.raises(KeyError, match="not found"):
        service.read(
            principal=_principal(), store_ref="store-fixture", as_of=AS_OF
        )


def test_revoked_or_missing_current_authority_is_non_enumerable() -> None:
    service = _service(authority=_ScopeAuthority(KeyError("revoked")))
    with pytest.raises(KeyError, match="not found"):
        service.read(
            principal=_principal(), store_ref="store-fixture", as_of=AS_OF
        )


def test_authority_rotation_during_aggregation_discards_every_section() -> None:
    port = _Port(_projection())
    authority = _ScopeAuthority(
        _scope(),
        _scope(authority_sha256="b" * 64),
    )
    service = _service(
        ports={"primary_source_coverage": port}, authority=authority
    )

    with pytest.raises(KeyError, match="not found"):
        service.read(
            principal=_principal(), store_ref="store-fixture", as_of=AS_OF
        )
    assert len(port.calls) == 1


def test_client_historical_as_of_never_rewinds_current_authority_check() -> None:
    historical = AS_OF - timedelta(days=90)
    authority = _ScopeAuthority(_scope())
    service = _service(authority=authority)

    service.read(
        principal=_principal(), store_ref="store-fixture", as_of=historical
    )

    assert all(call["checked_at"] == CHECKED_AT for call in authority.calls)
    assert all(call["checked_at"] != historical for call in authority.calls)


def test_future_client_as_of_fails_before_any_authoritative_read() -> None:
    authority = _ScopeAuthority(_scope())
    port = _Port(_projection())
    service = _service(
        ports={"primary_source_coverage": port}, authority=authority
    )

    with pytest.raises(StrategicCapitalDashboardContractError, match="trusted"):
        service.read(
            principal=_principal(),
            store_ref="store-fixture",
            as_of=CHECKED_AT + timedelta(seconds=1),
        )
    assert authority.calls == []
    assert port.calls == []


@pytest.mark.parametrize(
    "authority_result",
    [
        ValueError("raw-secret-ambiguity"),
        RuntimeError("raw-secret-integrity"),
        TypeError("raw-secret-shape"),
        {
            "status": "ready",
            "tenant_ref": "tenant-fixture",
            "entity_ref": None,
            "store_ref": "store-fixture",
            "authority_sha256": AUTHORITY_SHA,
        },
        {
            "status": "ready",
            "tenant_ref": "tenant-fixture",
            "entity_ref": ["entity-fixture"],
            "store_ref": "store-fixture",
            "authority_sha256": AUTHORITY_SHA,
        },
    ],
)
def test_runtime_scope_authority_errors_are_non_enumerable_and_pre_port(
    authority_result,
) -> None:
    class Grants:
        @staticmethod
        def current(**_kwargs):
            if isinstance(authority_result, Exception):
                raise authority_result
            return authority_result

    port = _Port(_projection())
    service = _service(
        ports={"primary_source_coverage": port},
        authority=RuntimeCurrentScopeAuthority(scope_grants=Grants()),
    )

    with pytest.raises(KeyError) as caught:
        service.read(
            principal=_principal(),
            store_ref="store-fixture",
            as_of=AS_OF,
        )
    assert "raw-secret" not in str(caught.value)
    assert port.calls == []


@pytest.mark.parametrize("field", ["data_as_of", "recorded_at", "effective_at"])
def test_future_or_backfilled_projection_is_unknown(field: str) -> None:
    projection = replace(_projection(), **{field: AS_OF + timedelta(seconds=1)})
    projection = replace(projection, projection_sha256="c" * 64)
    result = _service(
        ports={"primary_source_coverage": _Port(projection)}
    ).read(principal=_principal(), store_ref="store-fixture", as_of=AS_OF)

    section = result["sections"][0]
    assert section["status"] == "UNKNOWN"
    assert section["reason_codes"] == ["projection_contract_invalid"]
    assert section["display_items"] == []


def test_projection_hash_tamper_and_authority_escalation_fail_closed() -> None:
    tampered = replace(_projection(), projection_sha256="d" * 64)
    escalated = replace(_projection("strategic_benchmark"), global_top1_claim=True)
    result = _service(
        ports={
            "primary_source_coverage": _Port(tampered),
            "strategic_benchmark": _Port(escalated),
        }
    ).read(principal=_principal(), store_ref="store-fixture", as_of=AS_OF)

    assert [section["status"] for section in result["sections"][:2]] == [
        "UNKNOWN",
        "UNKNOWN",
    ]


@pytest.mark.parametrize(
    ("field", "drifted_value"),
    [
        ("source_contract_id", "drifted-contract"),
        ("source_contract_version", "drifted-version"),
        ("source_contract_sha256", "f" * 64),
    ],
)
def test_available_projection_source_contract_drift_is_unknown(
    field: str, drifted_value: str
) -> None:
    contract = _source_contract("primary_source_coverage")
    contract_values = {
        "source_contract_id": str(contract["contract_id"]),
        "source_contract_version": str(contract["contract_version"]),
        "source_contract_sha256": str(contract["contract_sha256"]),
    }
    contract_values[field] = drifted_value
    projection = seal_available_projection(
        section_id="primary_source_coverage",
        context=_context(),
        **contract_values,
        status="ready",
        reason_codes=("current_projection_available",),
        projection_ref="projection/primary-source/contract-drift",
        data_as_of=AS_OF,
        recorded_at=AS_OF,
        effective_at=AS_OF - timedelta(hours=1),
        review_due_at=CHECKED_AT + timedelta(days=1),
        citations=_projection().citations,
        display_items=_projection().display_items,
        invalidation_conditions=_projection().invalidation_conditions,
    )

    result = _service(
        ports={"primary_source_coverage": _Port(projection)}
    ).read(principal=_principal(), store_ref="store-fixture", as_of=AS_OF)

    assert result["sections"][0]["status"] == "UNKNOWN"
    assert result["sections"][0]["reason_codes"] == [
        "projection_contract_invalid"
    ]


@pytest.mark.parametrize(
    ("reason_codes", "citations", "display_items", "invalidation_conditions"),
    [
        ((), _projection().citations, _projection().display_items, _projection().invalidation_conditions),
        (("current_projection_available",), (), _projection().display_items, _projection().invalidation_conditions),
        (("current_projection_available",), _projection().citations, (), _projection().invalidation_conditions),
        (("current_projection_available",), _projection().citations, _projection().display_items, ()),
    ],
)
def test_available_projection_requires_evidence_display_and_invalidation(
    reason_codes, citations, display_items, invalidation_conditions
) -> None:
    contract = _source_contract("primary_source_coverage")
    projection = seal_available_projection(
        section_id="primary_source_coverage",
        context=_context(),
        source_contract_id=str(contract["contract_id"]),
        source_contract_version=str(contract["contract_version"]),
        source_contract_sha256=str(contract["contract_sha256"]),
        status="ready",
        reason_codes=reason_codes,
        projection_ref="projection/primary-source/empty-contract-field",
        data_as_of=AS_OF,
        recorded_at=AS_OF,
        effective_at=AS_OF - timedelta(hours=1),
        review_due_at=CHECKED_AT + timedelta(days=1),
        citations=citations,
        display_items=display_items,
        invalidation_conditions=invalidation_conditions,
    )
    result = _service(
        ports={"primary_source_coverage": _Port(projection)}
    ).read(principal=_principal(), store_ref="store-fixture", as_of=AS_OF)

    assert result["sections"][0]["status"] == "UNKNOWN"
    assert result["sections"][0]["reason_codes"] == [
        "projection_contract_invalid"
    ]


def test_review_due_is_evaluated_against_final_trusted_current_time() -> None:
    rechecked = CHECKED_AT + timedelta(hours=2)
    projection = _projection(review_due_at=CHECKED_AT + timedelta(hours=1))
    result = _service(
        ports={"primary_source_coverage": _Port(projection)},
        clock=_Clock(CHECKED_AT, rechecked),
    ).read(principal=_principal(), store_ref="store-fixture", as_of=AS_OF)

    section = result["sections"][0]
    assert section["status"] == "stale"
    assert section["reason_codes"] == ["review_due_expired"]
    assert section["display_items"] == []
    assert result["authority_checked_at"] == "2026-08-05T03:00:00Z"


def test_raw_evidence_identifier_is_not_an_opaque_citation_token() -> None:
    raw_id = "11111111-2222-3333-4444-555555555555"
    projection = replace(
        _projection(),
        citations=(DashboardCitation(token=raw_id, summary_sha256="b" * 64),),
    )
    projection = replace(
        projection,
        projection_sha256=hashlib.sha256(b"irrelevant").hexdigest(),
    )
    result = _service(
        ports={"primary_source_coverage": _Port(projection)}
    ).read(principal=_principal(), store_ref="store-fixture", as_of=AS_OF)

    assert result["sections"][0]["status"] == "UNKNOWN"
    assert raw_id not in json.dumps(result)


def test_unavailable_projection_has_no_value_or_projection_fields() -> None:
    result = _service(
        ports={
            "primary_source_coverage": _Port(
                UnavailableSectionProjection(
                    section_id="primary_source_coverage",
                    status="no_data",
                    reason_codes=("current_projection_no_data",),
                )
            )
        }
    ).read(principal=_principal(), store_ref="store-fixture", as_of=AS_OF)

    section = result["sections"][0]
    assert set(section) == {
        "section_id",
        "display_order",
        "scope_binding_sha256",
        "source_contract_id",
        "source_contract_version",
        "source_contract_sha256",
        "status",
        "reason_codes",
        "citations",
        "display_items",
        "invalidation_conditions",
        "global_top1_claim",
        "production_admission",
        "actionable_proposal",
    }


def test_unavailable_projection_requires_a_safe_reason() -> None:
    result = _service(
        ports={
            "primary_source_coverage": _Port(
                UnavailableSectionProjection(
                    section_id="primary_source_coverage",
                    status="no_data",
                    reason_codes=(),
                )
            )
        }
    ).read(principal=_principal(), store_ref="store-fixture", as_of=AS_OF)

    section = result["sections"][0]
    assert section["status"] == "UNKNOWN"
    assert section["reason_codes"] == ["projection_contract_invalid"]


def test_role_and_store_scope_are_enforced_before_ports() -> None:
    port = _Port(_projection())
    service = _service(ports={"primary_source_coverage": port})
    with pytest.raises(PermissionError):
        service.read(
            principal=_principal(roles=frozenset({"executor"})),
            store_ref="store-fixture",
            as_of=AS_OF,
        )
    with pytest.raises(KeyError):
        service.read(
            principal=_principal(store_refs=frozenset({"other-store"})),
            store_ref="store-fixture",
            as_of=AS_OF,
        )
    assert port.calls == []


def test_input_port_mapping_is_copied_and_unknown_port_is_rejected() -> None:
    ports = {"primary_source_coverage": _Port(_projection())}
    service = _service(ports=ports)
    ports.clear()
    result = service.read(
        principal=_principal(), store_ref="store-fixture", as_of=AS_OF
    )
    assert result["sections"][0]["status"] == "ready"

    with pytest.raises(StrategicCapitalDashboardContractError):
        StrategicCapitalDashboardService(
            scope_authority=_ScopeAuthority(_scope()),
            section_ports={"synthetic_fixture": _Port(_projection())},
            clock=_Clock(CHECKED_AT),
        )


def _source_contract(section_id: str) -> dict[str, object]:
    return dict(
        StrategicCapitalDashboardRegistry.load().payload["source_contracts"][
            section_id
        ]
    )


def _primary_item(
    *,
    intake_ref: str,
    created_at: datetime = AS_OF,
    source_pack_id: str = "operating_cash_truth",
    data_as_of: datetime = AS_OF,
    effective_at: datetime = AS_OF - timedelta(hours=1),
) -> dict:
    return {
        "intake_ref": intake_ref,
        "store_ref": "store-fixture",
        "scope_binding_sha256": AUTHORITY_SHA,
        "source_pack_id": source_pack_id,
        "as_of": data_as_of,
        "created_at": created_at,
        "effective_at": effective_at,
        "review_due_at": CHECKED_AT + timedelta(days=1),
        "status": "complete",
        "admission_grade": "B",
        "counts": {"accepted": 1},
        "pagination": {"failed_page_count": 0},
        "evidence": {"id": f"evd_{intake_ref}", "sha256": "e" * 64},
    }


class _PrimarySourceService:
    def __init__(self, items: list[dict], *, next_cursor=None) -> None:
        self.items = items
        self.next_cursor = next_cursor

    def list(self, **_kwargs):
        return {
            "contract_id": "kjds-primary-source-intake-v1",
            "items": self.items,
            "next_cursor": self.next_cursor,
        }


def test_primary_multi_pack_time_projection_is_conservative() -> None:
    authority = ScopedDashboardCitationAuthority(sealing_key=b"k" * 32)
    projection = PrimarySourceCoverageReadPort(
        service=_PrimarySourceService(
            [
                _primary_item(
                    intake_ref="psi_old_valid_time",
                    source_pack_id="operating_cash_truth",
                    data_as_of=AS_OF - timedelta(hours=2),
                    effective_at=AS_OF - timedelta(hours=3),
                ),
                _primary_item(
                    intake_ref="psi_new_valid_time",
                    source_pack_id="market_demand_truth",
                    data_as_of=AS_OF - timedelta(hours=1),
                    effective_at=AS_OF - timedelta(minutes=30),
                ),
            ]
        ),
        source_contract=_source_contract("primary_source_coverage"),
        citation_authority=authority,
    ).read(principal=_principal(), context=_context())

    assert projection.data_as_of == AS_OF - timedelta(hours=2)
    assert projection.effective_at == AS_OF - timedelta(minutes=30)


def test_real_primary_and_benchmark_services_compose_and_rotation_hides_old_rows(
    request,
) -> None:
    assert _intake_runtime_fixture is not None
    assert _benchmark_runtime_fixture is not None
    intake_value = request.getfixturevalue("_intake_runtime_fixture")
    benchmark_value = request.getfixturevalue("_benchmark_runtime_fixture")
    primary, _primary_engine, shared_scope, _primary_scoped = intake_value
    benchmark, _benchmark_engine, _benchmark_scope, _benchmark_scoped = (
        benchmark_value
    )
    benchmark.scope_grants = shared_scope
    admitted = admit_primary_source(primary, [primary_record()])
    primary.clock = lambda: BENCHMARK_NOW
    built = build_benchmark(benchmark, [benchmark_group()])
    registry = StrategicCapitalDashboardRegistry.load()
    service = StrategicCapitalDashboardService(
        scope_authority=RuntimeCurrentScopeAuthority(scope_grants=shared_scope),
        section_ports={
            "primary_source_coverage": PrimarySourceCoverageReadPort(
                service=primary,
                source_contract=registry.payload["source_contracts"][
                    "primary_source_coverage"
                ],
                citation_authority=ScopedDashboardCitationAuthority(
                    sealing_key=b"k" * 32
                ),
            ),
            "strategic_benchmark": StrategicBenchmarkReadPort(
                service=benchmark,
                source_contract=registry.payload["source_contracts"][
                    "strategic_benchmark"
                ],
            ),
        },
        clock=lambda: BENCHMARK_NOW,
    )

    current = service.read(
        principal=primary_principal(),
        store_ref="store-a",
        as_of=BENCHMARK_NOW,
    )
    assert [section["status"] for section in current["sections"][:2]] == [
        "ready",
        "ready",
    ]
    serialized = json.dumps(current, sort_keys=True)
    assert admitted["intake"]["evidence"]["id"] not in serialized
    assert admitted["intake"]["scope_binding_sha256"] not in serialized
    assert built["snapshot"]["snapshot_ref"] in serialized
    assert shared_scope.calls[-1] == BENCHMARK_NOW

    shared_scope.authority_suffix = "v2"
    rotated = service.read(
        principal=primary_principal(), store_ref="store-a", as_of=BENCHMARK_NOW
    )
    assert [section["status"] for section in rotated["sections"][:2]] == [
        "no_data",
        "no_data",
    ]
    rotated_serialized = json.dumps(rotated, sort_keys=True)
    assert admitted["intake"]["intake_ref"] not in rotated_serialized
    assert built["snapshot"]["snapshot_ref"] not in rotated_serialized


class _BenchmarkService:
    def __init__(
        self,
        items: list[dict],
        *,
        next_cursor=None,
        current_authority_sha256: str = AUTHORITY_SHA,
    ) -> None:
        self.items = items
        self.next_cursor = next_cursor
        self.current_authority_sha256 = current_authority_sha256
        self.get_calls = 0

    def list(self, **kwargs):
        if (
            kwargs.get("expected_scope_authority_sha256")
            != self.current_authority_sha256
        ):
            raise KeyError("Strategic benchmark not found in authorized scope")
        return {
            "contract_id": "kjds-strategic-benchmark-kernel-v1",
            "items": self.items,
            "next_cursor": self.next_cursor,
        }

    def get(self, **_kwargs):
        self.get_calls += 1
        raise AssertionError("ambiguous latest benchmark must not be read")


class _BenchmarkProjectionService:
    def __init__(self, states: list[str]) -> None:
        self.states = states

    def list(self, **kwargs):
        assert kwargs["expected_scope_authority_sha256"] == AUTHORITY_SHA
        return {
            "contract_id": "kjds-strategic-benchmark-kernel-v1",
            "items": [
                {
                    "snapshot_ref": "sbs_projection",
                    "store_ref": "store-fixture",
                    "created_at": AS_OF,
                }
            ],
            "next_cursor": None,
        }

    def get(self, **kwargs):
        assert kwargs["expected_scope_authority_sha256"] == AUTHORITY_SHA
        return {
            "contract_id": "kjds-strategic-benchmark-kernel-v1",
            "snapshot": {
                "snapshot_ref": "sbs_projection",
                "store_ref": "store-fixture",
                "global_top1_claim": False,
                "as_of": AS_OF,
                "created_at": AS_OF,
                "snapshot_citation": {
                    "token": "sbc_abcdefghijklmnopqrstuvwxyz012345",
                    "sha256": "e" * 64,
                },
            },
            "groups": [
                {
                    "group_ref": f"sbg_{index}",
                    "domain": "product_experience",
                    "metric_id": f"metric_{index}",
                    "cohort_ref": "cohort-global",
                    "comparison_state": state,
                    "leader_label": "metric_leader" if state == "comparable" else None,
                    "global_top1_claim": False,
                    "observations": [
                        {"freshness_due_at": CHECKED_AT + timedelta(days=1)}
                    ],
                }
                for index, state in enumerate(self.states)
            ],
        }


def test_primary_and_benchmark_latest_ties_fail_closed() -> None:
    authority = ScopedDashboardCitationAuthority(sealing_key=b"k" * 32)
    primary = PrimarySourceCoverageReadPort(
        service=_PrimarySourceService(
            [_primary_item(intake_ref="psi_a"), _primary_item(intake_ref="psi_b")]
        ),
        source_contract=_source_contract("primary_source_coverage"),
        citation_authority=authority,
    )
    benchmark_service = _BenchmarkService(
        [
            {
                "snapshot_ref": "sbs_a",
                "store_ref": "store-fixture",
                "created_at": AS_OF,
            },
            {
                "snapshot_ref": "sbs_b",
                "store_ref": "store-fixture",
                "created_at": AS_OF,
            },
        ]
    )
    benchmark = StrategicBenchmarkReadPort(
        service=benchmark_service,
        source_contract=_source_contract("strategic_benchmark"),
    )

    with pytest.raises(StrategicCapitalDashboardContractError, match="tie"):
        primary.read(principal=_principal(), context=_context())
    with pytest.raises(StrategicCapitalDashboardContractError, match="tie"):
        benchmark.read(principal=_principal(), context=_context())
    assert benchmark_service.get_calls == 0


def test_bounded_nonterminal_pages_never_claim_current_projection() -> None:
    authority = ScopedDashboardCitationAuthority(sealing_key=b"k" * 32)
    primary = PrimarySourceCoverageReadPort(
        service=_PrimarySourceService(
            [_primary_item(intake_ref="psi_old")], next_cursor="psi_more"
        ),
        source_contract=_source_contract("primary_source_coverage"),
        citation_authority=authority,
    )
    benchmark = StrategicBenchmarkReadPort(
        service=_BenchmarkService(
            [
                {
                    "snapshot_ref": "sbs_old",
                    "store_ref": "store-fixture",
                    "created_at": AS_OF,
                }
            ],
            next_cursor="sbcursor_v2.more",
        ),
        source_contract=_source_contract("strategic_benchmark"),
    )

    for projection in (
        primary.read(principal=_principal(), context=_context()),
        benchmark.read(principal=_principal(), context=_context()),
    ):
        assert projection.status == "UNKNOWN"
        assert projection.reason_codes == ("bounded_page_not_current",)


def test_benchmark_adapter_rejects_wrong_current_authority_before_get() -> None:
    benchmark_service = _BenchmarkService(
        [
            {
                "snapshot_ref": "sbs_wrong_authority",
                "store_ref": "store-fixture",
                "created_at": AS_OF,
            }
        ],
        current_authority_sha256="f" * 64,
    )
    benchmark = StrategicBenchmarkReadPort(
        service=benchmark_service,
        source_contract=_source_contract("strategic_benchmark"),
    )

    with pytest.raises(KeyError, match="authorized scope"):
        benchmark.read(principal=_principal(), context=_context())
    assert benchmark_service.get_calls == 0


@pytest.mark.parametrize(
    ("states", "expected_status", "display_count"),
    [
        (["invalidated", "comparable"], "invalidated", 0),
        (["stale", "comparable"], "stale", 0),
        (["no_data", "no_data"], "no_data", 0),
        (["not_comparable", "comparable"], "partial", 2),
        (["comparable", "comparable"], "ready", 2),
    ],
)
def test_benchmark_state_conservation_matrix(
    states: list[str], expected_status: str, display_count: int
) -> None:
    projection = StrategicBenchmarkReadPort(
        service=_BenchmarkProjectionService(states),
        source_contract=_source_contract("strategic_benchmark"),
    ).read(principal=_principal(), context=_context())

    assert projection.status == expected_status
    assert len(getattr(projection, "display_items", ())) == display_count


def test_citation_authority_binds_scope_authority_and_source_hash() -> None:
    authority = ScopedDashboardCitationAuthority(sealing_key=b"k" * 32)
    first = authority.issue(
        section_id="primary_source_coverage",
        context=_context(),
        source_ref="evd_raw-identifier",
        source_sha256="e" * 64,
    )
    rotated = authority.issue(
        section_id="primary_source_coverage",
        context=replace(_context(), scope_grant_authority_sha256="f" * 64),
        source_ref="evd_raw-identifier",
        source_sha256="e" * 64,
    )
    other_source = authority.issue(
        section_id="primary_source_coverage",
        context=_context(),
        source_ref="evd_other-identifier",
        source_sha256="d" * 64,
    )

    assert first.token.startswith("psc_")
    assert len({first.token, rotated.token, other_source.token}) == 3
    assert "evd_raw-identifier" not in first.token
    assert first.summary_sha256 == "e" * 64
