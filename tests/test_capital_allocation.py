from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from apps.control_plane.capital_allocation import (
    CapitalAllocationConflictError,
    CapitalAllocationContractError,
    CapitalAllocationContractRegistry,
    FrozenCapitalAllocationFixture,
    GovernedCapitalAllocationWorkspace,
)
from apps.control_plane.security import Principal

REGISTRY = Path("docs/project/registries/capital_allocation_contracts.json")
FIXTURE = Path("tests/fixtures/capital_allocation/bas201_capital_allocation_v1.json")
AUTHORITY_A = "a" * 64
AUTHORITY_B = "b" * 64
DATA_AS_OF = datetime(2026, 8, 1, tzinfo=UTC)
TRUSTED_NOW = datetime(2026, 8, 5, tzinfo=UTC)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _principal(
    *,
    actor_id: str = "operator-a",
    tenant_ref: str = "tenant-a",
    store_ref: str = "store-a",
    roles: frozenset[str] = frozenset({"operator"}),
) -> Principal:
    return Principal(
        actor_id=actor_id,
        roles=roles,
        tenant_ref=tenant_ref,
        store_refs=frozenset({store_ref}),
    )


class _Clock:
    def __init__(self, now: datetime = TRUSTED_NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class _ScopeGrants:
    def __init__(self) -> None:
        self.status = "ready"
        self.tenant_ref = "tenant-a"
        self.entity_ref = "entity-a"
        self.store_ref = "store-a"
        self.authority_sha256 = AUTHORITY_A
        self.calls: list[datetime] = []
        self.error: Exception | None = None

    def current(self, *, principal: Principal, store_ref: str, as_of: datetime):
        self.calls.append(as_of)
        if self.error is not None:
            raise self.error
        return {
            "status": self.status,
            "tenant_ref": self.tenant_ref,
            "entity_ref": self.entity_ref if self.status == "ready" else None,
            "store_ref": self.store_ref,
            "authority_sha256": self.authority_sha256,
        }


class _ReadAuthority:
    def __init__(self, bundle: dict[str, Any]) -> None:
        self.bundle = bundle
        self.calls = 0
        self.contexts: list[dict[str, Any]] = []
        self.error: Exception | None = None

    def read_bundle(self, **kwargs) -> dict[str, Any]:
        self.calls += 1
        self.contexts.append(deepcopy(kwargs))
        if self.error is not None:
            raise self.error
        return deepcopy(self.bundle)


class _CitationAuthority:
    def __init__(
        self,
        registry: CapitalAllocationContractRegistry,
        fixture: FrozenCapitalAllocationFixture,
    ) -> None:
        self.registry = registry
        self.fixture = fixture
        self.calls = 0
        self.contexts: list[dict[str, Any]] = []
        self.overrides: dict[str, dict[str, Any]] = {}
        self.errors: dict[str, Exception] = {}
        self._binding_by_ref = {
            item["evidence_binding"]["citation_ref"]: item["evidence_binding"]
            for item in fixture.payload["source_bindings"]
        }
        self._contract_by_id = {
            item["contract_id"]: item for item in registry.payload["source_contracts"]
        }

    def verify_citation(
        self,
        *,
        citation_ref: str,
        source_contract_id: str,
        **kwargs,
    ) -> dict[str, Any]:
        self.calls += 1
        self.contexts.append({"citation_ref": citation_ref, **deepcopy(kwargs)})
        if citation_ref in self.errors:
            raise self.errors[citation_ref]
        binding = self._binding_by_ref[citation_ref]
        contract = self._contract_by_id[source_contract_id]
        receipt = {
            "contract_id": self.registry.payload["citation_authority_contract_id"],
            "status": "ready",
            **deepcopy(binding),
            "source_contract_id": contract["contract_id"],
            "source_contract_version": contract["version"],
            "source_contract_sha256": contract["contract_sha256"],
            "scope": deepcopy(self.fixture.payload["scope"]),
            "integrity_status": "valid",
            "current": True,
            "grade": "A",
        }
        receipt.update(deepcopy(self.overrides.get(citation_ref, {})))
        return receipt


def _seal_projection(projection: dict[str, Any]) -> None:
    projection["projection_sha256"] = _hash(
        {key: value for key, value in projection.items() if key != "projection_sha256"}
    )


def _seal_bundle(bundle: dict[str, Any]) -> None:
    bundle["bundle_sha256"] = _hash(
        {key: value for key, value in bundle.items() if key != "bundle_sha256"}
    )


def _bundle(
    registry: CapitalAllocationContractRegistry,
    fixture: FrozenCapitalAllocationFixture,
) -> dict[str, Any]:
    projections = []
    for binding in fixture.payload["source_bindings"]:
        contract = registry.source_contracts[binding["source_id"]]
        projection = {
            "source_id": binding["source_id"],
            "contract_id": contract["contract_id"],
            "contract_version": contract["version"],
            "source_ref": binding["source_ref"],
            "status": "ready",
            "scope": deepcopy(binding["scope"]),
            "as_of": binding["data_as_of"],
            "payload": deepcopy(binding["synthetic_payload"]),
            "evidence_binding": deepcopy(binding["evidence_binding"]),
        }
        _seal_projection(projection)
        projections.append(projection)
    value = {
        "contract_id": registry.payload["read_bundle_contract_id"],
        "portfolio_ref": fixture.payload["portfolio_ref"],
        "allocation_contract_ref": fixture.ref,
        "scope": deepcopy(fixture.payload["scope"]),
        "as_of": fixture.payload["data_as_of"],
        "projections": projections,
    }
    _seal_bundle(value)
    return value


def _workspace(
    *,
    fixture_path: Path = FIXTURE,
) -> tuple[
    GovernedCapitalAllocationWorkspace,
    _ScopeGrants,
    _ReadAuthority,
    _CitationAuthority,
    _Clock,
]:
    registry = CapitalAllocationContractRegistry.load(REGISTRY)
    fixture = FrozenCapitalAllocationFixture.load(fixture_path, registry=registry)
    scope = _ScopeGrants()
    read = _ReadAuthority(_bundle(registry, fixture))
    citation = _CitationAuthority(registry, fixture)
    clock = _Clock()
    workspace = GovernedCapitalAllocationWorkspace(
        scope_grants=scope,
        read_authority=read,
        citation_authority=citation,
        registry_path=REGISTRY,
        fixture_path=fixture_path,
        clock=clock,
    )
    return workspace, scope, read, citation, clock


def _evaluate(
    workspace: GovernedCapitalAllocationWorkspace,
    *,
    principal: Principal | None = None,
    as_of: datetime = DATA_AS_OF,
    portfolio_ref: str | None = None,
    allocation_contract_ref: str | None = None,
) -> dict[str, Any]:
    return workspace.evaluate(
        principal=principal or _principal(),
        store_ref="store-a",
        as_of=as_of,
        portfolio_ref=portfolio_ref or workspace.fixture.payload["portfolio_ref"],
        allocation_contract_ref=allocation_contract_ref or workspace.fixture.ref,
    )


def _fixture_variant(
    tmp_path: Path,
    mutate: Callable[[dict[str, Any]], None],
) -> Path:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    mutate(payload)
    for binding in payload["source_bindings"]:
        binding["evidence_binding"]["claims_sha256"] = _hash(
            binding["synthetic_payload"]
        )
    for option in payload["option_specs"]:
        option["option_sha256"] = _hash(
            {key: value for key, value in option.items() if key != "option_sha256"}
        )
    payload["content_sha256"] = _hash(
        {key: value for key, value in payload.items() if key != "content_sha256"}
    )
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _source(payload: dict[str, Any], source_id: str) -> dict[str, Any]:
    return next(
        item for item in payload["source_bindings"] if item["source_id"] == source_id
    )


def _projection(bundle: dict[str, Any], source_id: str) -> dict[str, Any]:
    return next(item for item in bundle["projections"] if item["source_id"] == source_id)


def test_repository_registry_and_fixture_seals_are_exact() -> None:
    registry = CapitalAllocationContractRegistry.load(REGISTRY)
    fixture = FrozenCapitalAllocationFixture.load(FIXTURE, registry=registry)

    assert set(registry.source_contracts) == {
        "gap_graph",
        "strategic_benchmark",
        "capital_constraints",
        "profit_truth",
        "settlement_cash",
        "growth_outcome",
        "commercial_lifecycle",
    }
    assert [item["option_type"] for item in fixture.payload["option_specs"]] == [
        "build",
        "buy",
        "partner",
        "defer",
        "no_action",
    ]
    assert fixture.payload["policy"]["synthetic_fixture_proves_real_finance"] is False
    assert registry.payload["zero_authority_flags"]["proposal_only"] is True
    assert not any(
        value
        for key, value in registry.payload["zero_authority_flags"].items()
        if key != "proposal_only"
    )


def test_default_synthetic_projection_is_no_action_and_keeps_c0_blocked() -> None:
    workspace, scope, read, citation, _clock = _workspace()
    observation = _evaluate(workspace)

    assert observation["status"] == "blocked"
    assert observation["proposal_status"] == "not_admitted"
    assert observation["selected_option"] == "no_action"
    assert observation["best_feasible_for_kjds"] == "no_action"
    assert observation["production_admission"] is False
    assert observation["real_finance_status"] == "UNKNOWN"
    assert observation["fixture_authority"] == "repository_owned_synthetic_fixture"
    assert "acceptance" in observation["reason_codes"]
    assert "real_finance_authority" in observation["reason_codes"]
    assert observation["gate_results"]["acceptance"] == "blocked"
    assert scope.calls == [TRUSTED_NOW]
    assert read.calls == 1
    assert citation.calls == 7
    commercial = _projection(read.bundle, "commercial_lifecycle")["payload"]
    assert commercial["c0_status"] == "not_for_sale"
    assert commercial["external_blockers"] == [
        "hosted_target_and_rpo_rto_decision",
        "payment_invoice_tax_contract_inputs",
        "contract_dpa_sla_review_authority",
    ]


def test_synthetic_all_green_still_cannot_create_production_admission(tmp_path: Path) -> None:
    def mutate(payload: dict[str, Any]) -> None:
        commercial = _source(payload, "commercial_lifecycle")["synthetic_payload"]
        commercial["c0_status"] = "ready"
        commercial["external_blockers"] = []

    workspace, *_ = _workspace(fixture_path=_fixture_variant(tmp_path, mutate))
    observation = _evaluate(workspace)

    assert all(value == "passed" for value in observation["gate_results"].values())
    assert observation["synthetic_best_feasible"] == "build"
    assert observation["best_feasible_for_kjds"] == "no_action"
    assert observation["selected_option"] == "no_action"
    assert observation["proposal_status"] == "not_admitted"
    assert observation["production_admission"] is False
    assert observation["reason_codes"] == ["real_finance_authority"]


def test_no_action_participates_in_complete_five_option_comparison(
    tmp_path: Path,
) -> None:
    def mutate(payload: dict[str, Any]) -> None:
        commercial = _source(payload, "commercial_lifecycle")["synthetic_payload"]
        commercial["c0_status"] = "ready"
        commercial["external_blockers"] = []
        no_action = next(
            item for item in payload["option_specs"] if item["option_type"] == "no_action"
        )
        no_action["comparison_values"][
            "long_term_risk_adjusted_value"
        ]["amount_microunits"] = 99_000_000

    workspace, *_ = _workspace(fixture_path=_fixture_variant(tmp_path, mutate))
    observation = _evaluate(workspace)

    assert all(value == "passed" for value in observation["gate_results"].values())
    assert observation["synthetic_best_feasible"] == "no_action"
    assert observation["best_feasible_for_kjds"] == "no_action"
    assert observation["selected_option"] == "no_action"
    assert observation["proposal_status"] == "not_admitted"
    assert observation["production_admission"] is False


@pytest.mark.parametrize(
    ("kind", "field"),
    [
        ("missing", "currency"),
        ("missing", "occurred_at"),
        ("missing", "effective_at"),
        ("missing", "evidence_ref"),
        ("missing", "evidence_sha256"),
        ("currency", "currency"),
        ("future", "effective_at"),
        ("hash", "evidence_sha256"),
    ],
)
def test_option_money_contract_shape_and_currency_fail_closed(
    tmp_path: Path,
    kind: str,
    field: str,
) -> None:
    def mutate(payload: dict[str, Any]) -> None:
        money = payload["option_specs"][0]["budget_request"]
        if kind == "missing":
            money.pop(field)
        elif kind == "currency":
            money[field] = "USD"
        elif kind == "future":
            money[field] = "2026-08-02T00:00:00+00:00"
        else:
            money[field] = "not-a-sha"

    path = _fixture_variant(tmp_path, mutate)
    registry = CapitalAllocationContractRegistry.load(REGISTRY)
    with pytest.raises(CapitalAllocationContractError):
        FrozenCapitalAllocationFixture.load(path, registry=registry)


@pytest.mark.parametrize(
    "subject",
    ["policy", "option", "comparison"],
)
@pytest.mark.parametrize("drift", ["currency", "future", "missing_evidence"])
def test_every_fixture_money_family_uses_the_same_fail_closed_contract(
    tmp_path: Path,
    subject: str,
    drift: str,
) -> None:
    def mutate(payload: dict[str, Any]) -> None:
        if subject == "policy":
            money = payload["policy"]["minimum_downside_cm3"]
        elif subject == "option":
            money = payload["option_specs"][0]["maximum_loss"]
        else:
            money = payload["option_specs"][0]["comparison_values"][
                "total_cost_of_ownership"
            ]
        if drift == "currency":
            money["currency"] = "USD"
        elif drift == "future":
            money["occurred_at"] = "2026-08-02T00:00:00+00:00"
        else:
            money.pop("evidence_ref")

    path = _fixture_variant(tmp_path, mutate)
    registry = CapitalAllocationContractRegistry.load(REGISTRY)
    with pytest.raises(CapitalAllocationContractError):
        FrozenCapitalAllocationFixture.load(path, registry=registry)


@pytest.mark.parametrize(
    ("review_date", "empty_invalidation"),
    [
        ("2026-08-01T00:00:00+00:00", False),
        ("2026-09-02T00:00:00+00:00", False),
        ("2026-08-15T00:00:00+00:00", True),
    ],
)
def test_review_date_and_invalidation_contract_fail_closed(
    tmp_path: Path,
    review_date: str,
    empty_invalidation: bool,
) -> None:
    def mutate(payload: dict[str, Any]) -> None:
        payload["option_specs"][0]["review_date"] = review_date
        if empty_invalidation:
            payload["option_specs"][0]["invalidation_conditions"] = []

    path = _fixture_variant(tmp_path, mutate)
    registry = CapitalAllocationContractRegistry.load(REGISTRY)
    with pytest.raises(CapitalAllocationContractError):
        FrozenCapitalAllocationFixture.load(path, registry=registry)


def test_review_due_blocks_actions_and_bypasses_pre_review_cache(tmp_path: Path) -> None:
    def mutate(payload: dict[str, Any]) -> None:
        commercial = _source(payload, "commercial_lifecycle")["synthetic_payload"]
        commercial["c0_status"] = "ready"
        commercial["external_blockers"] = []
        for binding in payload["source_bindings"]:
            binding["evidence_binding"]["effective_until"] = (
                "2026-10-01T00:00:00+00:00"
            )

    workspace, scope, read, citation, clock = _workspace(
        fixture_path=_fixture_variant(tmp_path, mutate)
    )
    before = _evaluate(workspace)
    clock.now = datetime(2026, 9, 1, tzinfo=UTC)
    after = _evaluate(workspace)

    assert before["synthetic_best_feasible"] == "build"
    assert "review_due" not in before["reason_codes"]
    assert after["synthetic_best_feasible"] == "no_action"
    assert after["selected_option"] == "no_action"
    assert after["proposal_status"] == "not_admitted"
    assert "review_due" in after["reason_codes"]
    assert after["proposal_fields"]["review_status"] == "due"
    assert all(
        item["feasible"] is False
        for item in after["options"]
        if item["option_type"] != "no_action"
    )
    assert scope.calls == [TRUSTED_NOW, datetime(2026, 9, 1, tzinfo=UTC)]
    assert read.calls == 2
    assert citation.calls == 14


def test_entitlement_and_actual_cash_cm3_never_substitute_for_treasury_authority(
    tmp_path: Path,
) -> None:
    def mutate(payload: dict[str, Any]) -> None:
        capital = _source(payload, "capital_constraints")["synthetic_payload"]
        capital["board_approved_current"] = False
        capital["treasury_cash_balance"]["amount_microunits"] = 0
        profit = _source(payload, "profit_truth")["synthetic_payload"]
        profit["actual_cash_cm3"]["amount_microunits"] = 999_000_000
        commercial = _source(payload, "commercial_lifecycle")["synthetic_payload"]
        commercial["outstanding_total"]["amount_microunits"] = 0

    workspace, *_ = _workspace(fixture_path=_fixture_variant(tmp_path, mutate))
    observation = _evaluate(workspace)

    assert observation["gate_results"]["cash_floor"] == "blocked"
    assert observation["gate_results"]["maximum_loss"] == "blocked"
    assert observation["selected_option"] == "no_action"
    assert observation["proposal_status"] == "not_admitted"


def test_all_side_effect_and_authority_counts_are_zero() -> None:
    workspace, *_ = _workspace()
    observation = _evaluate(workspace)

    assert set(observation["write_counts"].values()) == {0}
    assert observation["governance"] == {
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
    assert observation["proposal_only"] is True
    assert observation["equal_weight_total_score_used"] is False
    assert observation["generated_or_inferred_satisfies_gate"] is False


def test_replay_is_deterministic_and_revalidates_current_scope() -> None:
    workspace, scope, read, citation, _clock = _workspace()
    values = [_evaluate(workspace) for _ in range(3)]

    assert values[0] == values[1] == values[2]
    assert len({item["observation_sha256"] for item in values}) == 1
    assert scope.calls == [TRUSTED_NOW, TRUSTED_NOW, TRUSTED_NOW]
    assert read.calls == 3
    assert citation.calls == 21


def test_actor_drift_conflicts_before_replacing_immutable_winner() -> None:
    workspace, *_ = _workspace()
    _evaluate(workspace)

    with pytest.raises(CapitalAllocationConflictError):
        _evaluate(workspace, principal=_principal(actor_id="reviewer-b"))


def test_authority_rotation_conflicts_and_historical_as_of_does_not_rewind() -> None:
    workspace, scope, read, _citation, _clock = _workspace()
    _evaluate(workspace)
    scope.authority_sha256 = AUTHORITY_B

    with pytest.raises(CapitalAllocationConflictError):
        _evaluate(workspace)
    assert read.calls == 1


def test_revoked_current_authority_blocks_without_reading_historical_data() -> None:
    workspace, scope, read, citation, clock = _workspace()
    clock.now = TRUSTED_NOW + timedelta(days=2)
    scope.status = "revoked"
    observation = _evaluate(workspace)

    assert observation["status"] == "not_visible"
    assert observation["selected_option"] == "no_action"
    assert observation["reason_codes"] == ["exact_current_scope_authority_required"]
    assert scope.calls == [clock.now]
    assert read.calls == 0
    assert citation.calls == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tenant_ref", "tenant-b"),
        ("entity_ref", "entity-b"),
        ("store_ref", "store-b"),
    ],
)
def test_scope_dimension_drift_is_not_visible_and_zero_read(
    field: str,
    value: str,
) -> None:
    workspace, scope, read, citation, _clock = _workspace()
    setattr(scope, field, value)
    observation = _evaluate(workspace)

    assert observation["status"] == "not_visible"
    assert observation["proposal_status"] == "not_admitted"
    assert read.calls == 0
    assert citation.calls == 0


def test_future_as_of_and_contract_identity_drift_fail_before_authorities() -> None:
    workspace, scope, read, citation, _clock = _workspace()
    with pytest.raises(CapitalAllocationContractError):
        _evaluate(workspace, as_of=TRUSTED_NOW + timedelta(seconds=1))
    with pytest.raises(CapitalAllocationContractError):
        _evaluate(workspace, portfolio_ref="wrong-portfolio")
    with pytest.raises(CapitalAllocationContractError):
        _evaluate(workspace, allocation_contract_ref="wrong-allocation-contract")
    assert scope.calls == []
    assert read.calls == 0
    assert citation.calls == 0


@pytest.mark.parametrize(
    "roles",
    [
        frozenset(),
        frozenset({"approver"}),
        frozenset({"executor"}),
        frozenset({"pilot_reader"}),
    ],
)
def test_non_read_roles_have_zero_authority_calls(roles: frozenset[str]) -> None:
    workspace, scope, read, citation, _clock = _workspace()
    with pytest.raises(PermissionError):
        _evaluate(workspace, principal=_principal(roles=roles))
    assert scope.calls == []
    assert read.calls == 0
    assert citation.calls == 0


def test_store_outside_principal_scope_has_zero_authority_calls() -> None:
    workspace, scope, read, citation, _clock = _workspace()
    principal = Principal(
        actor_id="operator-a",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-a",
        store_refs=frozenset({"store-b"}),
    )
    with pytest.raises(PermissionError):
        _evaluate(workspace, principal=principal)
    assert scope.calls == []
    assert read.calls == 0
    assert citation.calls == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("contract_version", "2"),
        ("source_ref", "capital-source://drift"),
        ("as_of", "2026-07-31T00:00:00+00:00"),
    ],
)
def test_projection_identity_drift_is_blocked(field: str, value: str) -> None:
    workspace, _scope_grants, read, _citation, _clock = _workspace()
    projection = read.bundle["projections"][0]
    projection[field] = value
    _seal_projection(projection)
    _seal_bundle(read.bundle)

    observation = _evaluate(workspace)
    assert observation["status"] == "blocked"
    assert observation["reason_codes"] == ["read_projection_contract_or_hash_invalid"]
    assert observation["selected_option"] == "no_action"


def test_projection_scope_and_hash_drift_are_blocked() -> None:
    for kind in ("scope", "hash"):
        workspace, _scope_grants, read, _citation, _clock = _workspace()
        projection = read.bundle["projections"][0]
        if kind == "scope":
            projection["scope"]["tenant_ref"] = "tenant-b"
            _seal_projection(projection)
            _seal_bundle(read.bundle)
        else:
            projection["projection_sha256"] = "f" * 64
            _seal_bundle(read.bundle)
        observation = _evaluate(workspace)
        assert observation["status"] == "blocked"
        assert observation["selected_option"] == "no_action"


def test_bundle_duplicate_missing_and_extra_sources_are_blocked() -> None:
    for mutation in ("duplicate", "missing", "extra"):
        workspace, _scope_grants, read, _citation, _clock = _workspace()
        if mutation == "duplicate":
            read.bundle["projections"][-1] = deepcopy(read.bundle["projections"][0])
        elif mutation == "missing":
            read.bundle["projections"].pop()
        else:
            read.bundle["projections"].append(deepcopy(read.bundle["projections"][0]))
        _seal_bundle(read.bundle)
        observation = _evaluate(workspace)
        assert observation["status"] == "blocked"
        assert observation["proposal_status"] == "not_admitted"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("evidence_sha256", "b" * 64),
        ("claims_sha256", "b" * 64),
        ("source", "wrong-source"),
        ("source_ref", "wrong-source://ref"),
        ("recorded_at", "2026-08-02T00:00:00+00:00"),
        ("effective_at", "2026-08-02T00:00:00+00:00"),
        ("effective_until", "2026-08-01T00:00:00+00:00"),
        ("integrity_status", "invalid"),
        ("current", False),
        ("grade", "B"),
    ],
)
def test_citation_receipt_drift_or_hindsight_is_blocked(field: str, value: Any) -> None:
    workspace, _scope_grants, _read, citation, _clock = _workspace()
    citation_ref = workspace.fixture.payload["source_bindings"][0]["evidence_binding"][
        "citation_ref"
    ]
    citation.overrides[citation_ref] = {field: value}
    observation = _evaluate(workspace)

    assert observation["status"] == "blocked"
    assert observation["selected_option"] == "no_action"
    assert set(observation["write_counts"].values()) == {0}


def test_citation_scope_and_source_contract_drift_are_blocked() -> None:
    mutations = [
        {"scope": {"tenant_ref": "tenant-b", "entity_ref": "entity-a", "store_ref": "store-a", "scope_grant_authority_sha256": AUTHORITY_A}},
        {"source_contract_version": "2"},
        {"source_contract_sha256": "b" * 64},
    ]
    for override in mutations:
        workspace, _scope_grants, _read, citation, _clock = _workspace()
        citation_ref = workspace.fixture.payload["source_bindings"][0]["evidence_binding"][
            "citation_ref"
        ]
        citation.overrides[citation_ref] = override
        observation = _evaluate(workspace)
        assert observation["status"] == "blocked"
        assert observation["selected_option"] == "no_action"


@pytest.mark.parametrize(
    "error_type", [KeyError, RuntimeError, TypeError, ValueError, OSError, PermissionError]
)
def test_authority_adapter_errors_are_safely_projected(error_type: type[Exception]) -> None:
    workspace, _scope_grants, read, citation, _clock = _workspace()
    canary = "providerRequestId-secret-canary@example.com"
    if error_type is KeyError:
        read.error = error_type(canary)
    else:
        citation_ref = workspace.fixture.payload["source_bindings"][0]["evidence_binding"][
            "citation_ref"
        ]
        citation.errors[citation_ref] = error_type(canary)
    observation = _evaluate(workspace)
    serialized = json.dumps(observation, ensure_ascii=False)

    assert observation["status"] == "UNKNOWN"
    assert observation["reason_codes"] == ["read_or_citation_authority_unavailable"]
    assert canary not in serialized
    assert "example.com" not in serialized


@pytest.mark.parametrize(
    "error_type", [KeyError, RuntimeError, TypeError, ValueError, OSError, PermissionError]
)
def test_scope_authority_errors_are_safely_projected_before_read(
    error_type: type[Exception],
) -> None:
    workspace, scope, read, citation, _clock = _workspace()
    canary = "providerRequestId-secret-scope-canary@example.com"
    scope.error = error_type(canary)
    observation = _evaluate(workspace)
    serialized = json.dumps(observation, ensure_ascii=False)

    assert observation["status"] == "UNKNOWN"
    assert observation["reason_codes"] == ["current_scope_authority_unavailable"]
    assert observation["scope"] is None
    assert read.calls == 0
    assert citation.calls == 0
    assert set(observation["write_counts"].values()) == {0}
    assert canary not in serialized
    assert "example.com" not in serialized


def test_secret_canary_in_projection_is_blocked_and_not_projected() -> None:
    workspace, _scope_grants, read, _citation, _clock = _workspace()
    projection = _projection(read.bundle, "growth_outcome")
    projection["payload"]["outcome_ref"] = "api_key-secret-canary"
    projection["evidence_binding"]["claims_sha256"] = _hash(projection["payload"])
    _seal_projection(projection)
    _seal_bundle(read.bundle)
    observation = _evaluate(workspace)
    serialized = json.dumps(observation, ensure_ascii=False)

    assert observation["status"] == "blocked"
    assert "api_key-secret-canary" not in serialized


@pytest.mark.parametrize(
    ("source_id", "mutate", "gate"),
    [
        ("capital_constraints", lambda p: p.update(board_approved_current=False), "cash_floor"),
        ("capital_constraints", lambda p: p.update(signed_thresholds_current=False), "cash_floor"),
        ("capital_constraints", lambda p: p.update(runway_days=30), "cash_floor"),
        ("capital_constraints", lambda p: p.update(evidence_coverage_basis_points=9000), "cash_floor"),
        ("profit_truth", lambda p: p.update(signed_profit_threshold_current=False), "cash_floor"),
        ("strategic_benchmark", lambda p: p.update(security_status="blocked"), "security"),
        ("strategic_benchmark", lambda p: p.update(privacy_status="blocked"), "privacy"),
        ("strategic_benchmark", lambda p: p.update(legal_and_license_status="blocked"), "legal_and_license"),
        ("growth_outcome", lambda p: p.update(acceptance_evidence_current=False), "acceptance"),
        ("growth_outcome", lambda p: p.update(causal_authority_status="UNKNOWN"), "acceptance"),
        ("gap_graph", lambda p: p.update(portfolio_status="not_admitted"), "rollback"),
    ],
)
def test_each_noncompensatory_gate_blocks_no_action_only(
    tmp_path: Path,
    source_id: str,
    mutate: Callable[[dict[str, Any]], None],
    gate: str,
) -> None:
    def apply(payload: dict[str, Any]) -> None:
        mutate(_source(payload, source_id)["synthetic_payload"])

    workspace, *_ = _workspace(fixture_path=_fixture_variant(tmp_path, apply))
    observation = _evaluate(workspace)
    assert observation["gate_results"][gate] == "blocked"
    assert observation["selected_option"] == "no_action"
    assert observation["proposal_status"] == "not_admitted"


@pytest.mark.parametrize(
    ("source_id", "money_field"),
    [
        ("capital_constraints", "cash_floor"),
        ("profit_truth", "downside_cm3"),
        ("profit_truth", "actual_cash_cm3"),
        ("settlement_cash", "settled_cash"),
        ("commercial_lifecycle", "outstanding_total"),
    ],
)
def test_currency_mismatch_without_current_fx_is_blocked(
    tmp_path: Path,
    source_id: str,
    money_field: str,
) -> None:
    def mutate(payload: dict[str, Any]) -> None:
        source = _source(payload, source_id)["synthetic_payload"]
        source[money_field]["currency"] = "USD"
        commercial = _source(payload, "commercial_lifecycle")["synthetic_payload"]
        commercial["c0_status"] = "ready"
        commercial["external_blockers"] = []

    workspace, *_ = _workspace(fixture_path=_fixture_variant(tmp_path, mutate))
    observation = _evaluate(workspace)
    assert observation["gate_results"]["cash_floor"] == "blocked"
    assert observation["selected_option"] == "no_action"


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("budget_request", 90_000_000, "cash_or_budget_capacity_exceeded"),
        ("maximum_loss", 20_000_000, "maximum_loss_exceeded"),
        ("downside_cm3", 1, "downside_cm3_below_signed_threshold"),
        ("timebox_days", 91, "timebox_exceeded"),
        ("payback_days", 366, "payback_exceeded"),
    ],
)
def test_option_financial_and_time_hard_gates_are_not_averaged(
    tmp_path: Path,
    field: str,
    value: int,
    reason: str,
) -> None:
    def mutate(payload: dict[str, Any]) -> None:
        commercial = _source(payload, "commercial_lifecycle")["synthetic_payload"]
        commercial["c0_status"] = "ready"
        commercial["external_blockers"] = []
        if field in {"budget_request", "maximum_loss", "downside_cm3"}:
            payload["option_specs"][0][field]["amount_microunits"] = value
        else:
            payload["option_specs"][0][field] = value

    workspace, *_ = _workspace(fixture_path=_fixture_variant(tmp_path, mutate))
    observation = _evaluate(workspace)
    build = next(item for item in observation["options"] if item["option_type"] == "build")
    assert build["feasible"] is False
    assert reason in build["reason_codes"]
    assert observation["equal_weight_total_score_used"] is False
    assert observation["production_admission"] is False


@pytest.mark.parametrize("kind", ["orphan", "cycle", "duplicate_id", "duplicate_type"])
def test_option_identity_and_dependency_graph_fail_closed(tmp_path: Path, kind: str) -> None:
    def mutate(payload: dict[str, Any]) -> None:
        if kind == "orphan":
            payload["option_specs"][0]["dependency_refs"] = ["missing-option"]
        elif kind == "cycle":
            payload["option_specs"][0]["dependency_refs"] = ["option-buy"]
            payload["option_specs"][1]["dependency_refs"] = ["option-build"]
        elif kind == "duplicate_id":
            payload["option_specs"][1]["option_id"] = "option-build"
        else:
            payload["option_specs"][1]["option_type"] = "build"

    path = _fixture_variant(tmp_path, mutate)
    registry = CapitalAllocationContractRegistry.load(REGISTRY)
    with pytest.raises(CapitalAllocationContractError):
        FrozenCapitalAllocationFixture.load(path, registry=registry)


def test_infeasible_option_dependency_blocks_dependent_option(tmp_path: Path) -> None:
    def mutate(payload: dict[str, Any]) -> None:
        build = payload["option_specs"][0]
        buy = payload["option_specs"][1]
        build["dependency_refs"] = [buy["option_id"]]
        buy["budget_request"]["amount_microunits"] = 90_000_000
        gap = _source(payload, "gap_graph")["synthetic_payload"]
        gap["dependency_edges"] = [
            {"source": build["option_id"], "target": buy["option_id"]}
        ]
        commercial = _source(payload, "commercial_lifecycle")["synthetic_payload"]
        commercial["c0_status"] = "ready"
        commercial["external_blockers"] = []

    workspace, *_ = _workspace(fixture_path=_fixture_variant(tmp_path, mutate))
    observation = _evaluate(workspace)
    by_type = {item["option_type"]: item for item in observation["options"]}

    assert by_type["buy"]["feasible"] is False
    assert "cash_or_budget_capacity_exceeded" in by_type["buy"]["reason_codes"]
    assert by_type["build"]["feasible"] is False
    assert "dependency_not_feasible" in by_type["build"]["reason_codes"]
    assert observation["synthetic_best_feasible"] not in {"build", "buy"}
    assert observation["selected_option"] == "no_action"


def test_gap_graph_dependency_binding_drift_blocks_actionable_options(
    tmp_path: Path,
) -> None:
    def mutate(payload: dict[str, Any]) -> None:
        payload["option_specs"][0]["dependency_refs"] = ["option-buy"]
        commercial = _source(payload, "commercial_lifecycle")["synthetic_payload"]
        commercial["c0_status"] = "ready"
        commercial["external_blockers"] = []

    workspace, *_ = _workspace(fixture_path=_fixture_variant(tmp_path, mutate))
    observation = _evaluate(workspace)

    actionable = [
        item for item in observation["options"] if item["option_type"] != "no_action"
    ]
    assert all(item["feasible"] is False for item in actionable)
    assert all(
        "gap_graph_dependency_binding_mismatch" in item["reason_codes"]
        for item in actionable
    )
    assert observation["selected_option"] == "no_action"


@pytest.mark.parametrize(
    ("source_id", "field", "value"),
    [
        ("profit_truth", "treasury_cash_authority", True),
        ("settlement_cash", "treasury_cash_authority", True),
        ("commercial_lifecycle", "treasury_cash_authority", True),
    ],
)
def test_non_treasury_sources_cannot_claim_cash_authority(
    tmp_path: Path,
    source_id: str,
    field: str,
    value: bool,
) -> None:
    def mutate(payload: dict[str, Any]) -> None:
        _source(payload, source_id)["synthetic_payload"][field] = value

    workspace, *_ = _workspace(fixture_path=_fixture_variant(tmp_path, mutate))
    observation = _evaluate(workspace)
    assert observation["status"] == "blocked"
    assert observation["selected_option"] == "no_action"


def test_proposal_money_fields_bind_policy_limit_and_selected_no_action_spec() -> None:
    workspace, *_ = _workspace()
    observation = _evaluate(workspace)
    capital = next(
        item
        for item in workspace.fixture.payload["source_bindings"]
        if item["source_id"] == "capital_constraints"
    )["synthetic_payload"]

    assert observation["proposal_fields"]["cash_floor"] == capital["cash_floor"]
    assert observation["proposal_fields"]["budget_cap"] == capital["budget_cap"]
    no_action = next(
        item
        for item in workspace.fixture.payload["option_specs"]
        if item["option_type"] == "no_action"
    )
    assert observation["proposal_fields"]["maximum_loss_limit"] == capital[
        "maximum_loss_limit"
    ]
    assert observation["proposal_fields"]["budget_request"] == no_action[
        "budget_request"
    ]
    assert observation["proposal_fields"]["maximum_loss"] == no_action["maximum_loss"]
    assert observation["proposal_fields"]["runway"] == capital["runway_days"]
    assert observation["proposal_fields"]["downside_base_upside"] == {
        "downside": no_action["downside_cm3"],
        "base": no_action["base_cm3"],
        "upside": no_action["upside_cm3"],
    }
    assert observation["proposal_fields"]["owner"] == no_action["owner_ref"]
    assert observation["proposal_fields"]["primary_metric"] == no_action[
        "primary_metric"
    ]
    assert observation["proposal_fields"]["guardrails"]
    assert observation["proposal_fields"]["stop_conditions"]
    assert observation["proposal_fields"]["invalidation_conditions"]
    assert observation["proposal_fields"]["review_date"] == no_action["review_date"]
    assert observation["proposal_fields"]["review_status"] == "current"
    assert observation["proposal_fields"]["comparison_values"] == no_action[
        "comparison_values"
    ]
    registry = CapitalAllocationContractRegistry.load(REGISTRY)
    assert set(observation["proposal_fields"]) == set(
        registry.payload["required_proposal_fields"]
    )
    for option in observation["options"]:
        assert option["invalidation_conditions"]
        assert option["review_date"]
        assert option["review_status"] == "current"
        for field in (
            "budget_request",
            "maximum_loss",
            "downside_cm3",
            "base_cm3",
            "upside_cm3",
        ):
            assert set(option[field]) == {
                "amount_microunits",
                "currency",
                "occurred_at",
                "effective_at",
                "evidence_ref",
                "evidence_sha256",
            }


def test_read_authority_receives_server_derived_scope_and_frozen_bindings() -> None:
    workspace, _scope_grants, read, citation, _clock = _workspace()
    _evaluate(workspace)
    context = read.contexts[0]

    assert context["principal"] == _principal()
    assert context["entity_scope"]["entity_ref"] == "entity-a"
    assert context["as_of"] == DATA_AS_OF
    assert context["portfolio_ref"] == workspace.fixture.payload["portfolio_ref"]
    assert context["allocation_contract_ref"] == workspace.fixture.ref
    assert len(context["source_bindings"]) == 7
    assert all(item["data_as_of"] == DATA_AS_OF.isoformat() for item in context["source_bindings"])
    assert all(item["data_as_of"] == DATA_AS_OF for item in citation.contexts)
    assert all(item["authority_checked_at"] == TRUSTED_NOW for item in citation.contexts)


def test_observation_contains_only_hashes_counts_safe_codes_and_contract_fields() -> None:
    workspace, *_ = _workspace()
    observation = _evaluate(workspace)
    serialized = json.dumps(observation, ensure_ascii=False)

    assert "raw_prompt" not in serialized
    assert "raw_customer" not in serialized
    assert "providerRequestId" not in serialized
    assert "@" not in serialized
    assert observation["observation_sha256"] == _hash(
        {key: value for key, value in observation.items() if key != "observation_sha256"}
    )
