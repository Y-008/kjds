from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from apps.control_plane.gap_graph import (
    FrozenGapGraphPortfolio,
    GapGraphConflictError,
    GapGraphContractError,
    GapGraphContractRegistry,
    GovernedGapGraphWorkspace,
)
from apps.control_plane.security import Principal

REGISTRY = Path("docs/project/registries/gap_graph_contracts.json")
PORTFOLIO = Path("tests/fixtures/gap_graph/bas200_gap_graph_v1.json")
AUTHORITY_A = "a" * 64
AUTHORITY_B = "b" * 64
DATA_AS_OF = datetime.fromisoformat("2026-08-01T08:00:00+08:00")
TRUSTED_NOW = datetime(2026, 8, 4, tzinfo=UTC)


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
    *, tenant_ref: str = "tenant-a", store_ref: str = "store-a", actor_id: str = "operator-a"
) -> Principal:
    return Principal(
        actor_id=actor_id,
        roles=frozenset({"operator"}),
        tenant_ref=tenant_ref,
        store_refs=frozenset({store_ref}),
    )


class _Clock:
    def __init__(self) -> None:
        self.now = TRUSTED_NOW

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

    def current(self, *, principal: Principal, store_ref: str, as_of: datetime):
        self.calls.append(as_of)
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

    def read_bundle(self, **_kwargs) -> dict[str, Any]:
        self.calls += 1
        return deepcopy(self.bundle)


class _CitationAuthority:
    def __init__(
        self,
        registry: GapGraphContractRegistry,
        portfolio: FrozenGapGraphPortfolio,
    ) -> None:
        self.registry = registry
        self.portfolio = portfolio
        self.overrides: dict[str, dict[str, Any]] = {}
        self.raises: dict[str, Exception] = {}
        self.calls = 0
        self.contexts: list[dict[str, Any]] = []
        self._root_by_ref = {
            binding["evidence_binding"]["citation_ref"]: binding["evidence_binding"]
            for binding in portfolio.payload["source_bindings"]
        }
        self._contract_by_id = {
            contract["contract_id"]: contract
            for contract in registry.payload["source_contracts"]
        }

    def verify_citation(
        self,
        *,
        citation_ref: str,
        evidence_sha256: str,
        claims_sha256: str,
        source_contract_id: str,
        source_contract_version: str,
        **_kwargs,
    ) -> dict[str, Any]:
        self.calls += 1
        self.contexts.append(deepcopy(_kwargs))
        if citation_ref in self.raises:
            raise self.raises[citation_ref]
        contract = self._contract_by_id[source_contract_id]
        root = self._root_by_ref.get(citation_ref)
        if root is None:
            root = {
                "citation_ref": citation_ref,
                "evidence_id": f"evd-{citation_ref}",
                "evidence_sha256": evidence_sha256,
                "source": contract["evidence_source"],
                "source_ref": f"{contract['evidence_source']}://{citation_ref}",
                "recorded_at": (DATA_AS_OF - timedelta(days=1)).isoformat(),
                "effective_at": (DATA_AS_OF - timedelta(days=30)).isoformat(),
                "effective_until": (DATA_AS_OF + timedelta(days=30)).isoformat(),
                "claims_sha256": claims_sha256,
            }
        receipt = {
            "contract_id": self.registry.payload["citation_authority_contract_id"],
            "status": "ready",
            **deepcopy(root),
            "source_contract_id": source_contract_id,
            "source_contract_version": source_contract_version,
            "source_contract_sha256": contract["contract_sha256"],
            "scope": {
                "tenant_ref": "tenant-a",
                "entity_ref": "entity-a",
                "store_ref": "store-a",
                "scope_grant_authority_sha256": AUTHORITY_A,
            },
            "integrity_status": "valid",
            "current": True,
            "grade": "A",
        }
        receipt.update(deepcopy(self.overrides.get(citation_ref, {})))
        return receipt


class _CausalAuthority:
    def __init__(self, authority: dict[str, Any]) -> None:
        self.authority = authority
        self.calls = 0
        self.override: dict[str, Any] = {}

    def verify_causal_authority(self, **_kwargs) -> dict[str, Any]:
        self.calls += 1
        receipt = {
            "contract_id": self.authority["contract_id"],
            "status": self.authority["status"],
            "version": self.authority["version"],
            "receipt_sha256": self.authority["receipt_sha256"],
            "claims_sha256": self.authority["claims_sha256"],
            "scope": {
                "tenant_ref": "tenant-a",
                "entity_ref": "entity-a",
                "store_ref": "store-a",
                "scope_grant_authority_sha256": AUTHORITY_A,
            },
            "recorded_at": (DATA_AS_OF - timedelta(days=1)).isoformat(),
            "effective_at": (DATA_AS_OF - timedelta(days=30)).isoformat(),
            "effective_until": (DATA_AS_OF + timedelta(days=30)).isoformat(),
            "integrity_status": "valid",
            "current": True,
            "citation_refs": deepcopy(self.authority["citation_refs"]),
        }
        receipt.update(deepcopy(self.override))
        return receipt


def _item(
    *,
    item_ref: str,
    item_kind: str,
    attributes: dict[str, Any],
    citation_ref: str,
    derivation: str = "observed",
    state: str = "ready",
) -> dict[str, Any]:
    item = {
        "item_ref": item_ref,
        "item_kind": item_kind,
        "state": state,
        "derivation": derivation,
        "attributes": attributes,
        "citations": [
            {
                "citation_ref": citation_ref,
                "evidence_sha256": _hash({"citation_ref": citation_ref}),
                "claims_sha256": _hash(attributes),
            }
        ],
    }
    item["item_sha256"] = _hash(item)
    return item


def _seal_item(item: dict[str, Any]) -> None:
    claims_sha256 = _hash(item["attributes"])
    for citation in item["citations"]:
        citation["claims_sha256"] = claims_sha256
    item["item_sha256"] = _hash(
        {key: value for key, value in item.items() if key != "item_sha256"}
    )


def _seal_source(source: dict[str, Any]) -> None:
    source["projection_sha256"] = _hash(
        {key: value for key, value in source.items() if key != "projection_sha256"}
    )


def _seal_bundle(bundle: dict[str, Any]) -> None:
    for source in bundle["sources"]:
        for item in source["items"]:
            _seal_item(item)
        _seal_source(source)
    bundle["bundle_sha256"] = _hash(
        {key: value for key, value in bundle.items() if key != "bundle_sha256"}
    )


def _build_bundle(
    registry: GapGraphContractRegistry,
    portfolio: FrozenGapGraphPortfolio,
) -> dict[str, Any]:
    opportunity = portfolio.payload["opportunity_specs"][0]
    benchmark = portfolio.payload["gap_specs"][0]
    decision = opportunity["decision_policy"]
    maximum_loss = opportunity["maximum_loss"]
    downside = opportunity["downside"]
    rollback = opportunity["rollback"]
    items_by_source = {
        "primary_sources": [
            _item(
                item_ref="primary-problem-checkout-latency",
                item_kind="customer_problem",
                attributes={"problem_code": "checkout-latency", "claim_state": "observed"},
                citation_ref="cit-primary-problem-checkout-latency",
            )
        ],
        "strategic_benchmark": [
            _item(
                item_ref="benchmark-routing-quality",
                item_kind="benchmark_group",
                attributes={
                    "source_node_spec_id": "node_capability_current_routing",
                    "target_node_spec_id": "node_capability_frontier_routing",
                    "relation": "compared_with",
                    "metric_id": benchmark["expected_metric_id"],
                    "cohort_ref": benchmark["expected_cohort_ref"],
                    "market": benchmark["expected_market"],
                    "window_start": benchmark["expected_window_start"],
                    "window_end": benchmark["expected_window_end"],
                    "comparison_state": benchmark["expected_comparison_state"],
                    "leader_label": benchmark["expected_leader_label"],
                    "global_top1_claim": False,
                },
                citation_ref="cit-benchmark-routing-quality",
            )
        ],
        "retrieval": [
            _item(
                item_ref="retrieval-problem-support",
                item_kind="retrieval_observation",
                attributes={
                    "source_node_spec_id": "node_problem_checkout_latency",
                    "target_node_spec_id": "node_capability_frontier_routing",
                    "relation": "supports",
                    "decision_status": decision["status"],
                    "decision_policy_id": decision["policy_id"],
                    "decision_policy_version": decision["policy_version"],
                    "decision_policy_sha256": decision["policy_sha256"],
                    "alternatives_sha256": _hash(opportunity["alternatives"]),
                    "invalidation_conditions_sha256": _hash(
                        opportunity["invalidation_conditions"]
                    ),
                    "proposed_action": opportunity["proposed_action"],
                },
                citation_ref="cit-retrieval-problem-support",
            )
        ],
        "canonical_graph": [
            _item(
                item_ref="graph-current-routing",
                item_kind="current_capability",
                attributes={"capability_code": "current-routing"},
                citation_ref="cit-graph-current-routing",
            ),
            _item(
                item_ref="graph-frontier-routing",
                item_kind="frontier_capability",
                attributes={"capability_code": "frontier-routing"},
                citation_ref="cit-graph-frontier-routing",
            ),
            _item(
                item_ref="graph-edge-problem-current",
                item_kind="graph_edge_observation",
                attributes={
                    "source_node_spec_id": "node_problem_checkout_latency",
                    "target_node_spec_id": "node_capability_current_routing",
                    "relation": "supports",
                },
                citation_ref="cit-graph-edge-problem-current",
            ),
        ],
        "profit_truth": [
            _item(
                item_ref="profit-return-cost",
                item_kind="unit_economics_constraint",
                attributes={
                    "maximum_loss_status": maximum_loss["status"],
                    "maximum_loss_value": maximum_loss["value"],
                    "maximum_loss_unit": maximum_loss["unit"],
                    "maximum_loss_policy_id": maximum_loss["policy_id"],
                    "maximum_loss_policy_version": maximum_loss["policy_version"],
                    "maximum_loss_policy_sha256": maximum_loss["policy_sha256"],
                    "downside_status": downside["status"],
                    "downside_value": downside["value"],
                    "downside_unit": downside["unit"],
                    "downside_policy_id": downside["policy_id"],
                    "downside_policy_version": downside["policy_version"],
                    "downside_policy_sha256": downside["policy_sha256"],
                    "rollback_status": rollback["status"],
                    "rollback_artifact_sha256": rollback["artifact_sha256"],
                    "rollback_policy_id": rollback["policy_id"],
                    "rollback_policy_version": rollback["policy_version"],
                    "rollback_policy_sha256": rollback["policy_sha256"],
                    "rollback_trigger_codes_sha256": _hash(
                        rollback["trigger_codes"]
                    ),
                },
                citation_ref="cit-profit-return-cost",
            )
        ],
    }
    sources = []
    for binding in portfolio.payload["source_bindings"]:
        contract = registry.source_contracts[binding["source_id"]]
        source = {
            "source_id": binding["source_id"],
            "contract_id": contract["contract_id"],
            "contract_version": contract["version"],
            "source_ref": binding["source_ref"],
            "status": "ready",
            "scope": deepcopy(binding["scope"]),
            "as_of": binding["data_as_of"],
            "items": items_by_source[binding["source_id"]],
            "evidence_binding": deepcopy(binding["evidence_binding"]),
        }
        _seal_source(source)
        sources.append(source)
    bundle = {
        "contract_id": registry.payload["read_bundle_contract_id"],
        "portfolio_ref": portfolio.ref,
        "scope": deepcopy(portfolio.payload["source_bindings"][0]["scope"]),
        "as_of": portfolio.payload["source_bindings"][0]["data_as_of"],
        "sources": sources,
    }
    _seal_bundle(bundle)
    return bundle


def _causal_artifacts(
    tmp_path: Path, *, declare_authority: bool
) -> tuple[
    GapGraphContractRegistry,
    FrozenGapGraphPortfolio,
    Path,
    dict[str, Any],
    dict[str, Any] | None,
]:
    registry = GapGraphContractRegistry.load(REGISTRY)
    payload = json.loads(PORTFOLIO.read_text(encoding="utf-8"))
    edge = payload["edge_specs"][0]
    edge["relation"] = "causes"
    edge["derivation"] = "causal"
    edge["causal_claim"] = True
    attributes = {
        "source_node_spec_id": edge["source_node_spec_id"],
        "target_node_spec_id": edge["target_node_spec_id"],
        "relation": "causes",
    }
    authority: dict[str, Any] | None = None
    if declare_authority:
        authority = {
            "status": "verified",
            "contract_id": "kjds-independent-causal-edge-authority-v1",
            "version": "1",
            "claims_sha256": _hash(attributes),
            "citation_refs": ["cit-graph-edge-problem-current"],
        }
        authority["receipt_sha256"] = _hash(authority)
    edge["causal_authority"] = deepcopy(authority)
    payload["content_sha256"] = _hash(
        {key: value for key, value in payload.items() if key != "content_sha256"}
    )
    changed_path = tmp_path / "causal-portfolio.json"
    changed_path.write_text(json.dumps(payload), encoding="utf-8")
    portfolio = FrozenGapGraphPortfolio.load(changed_path, registry=registry)
    bundle = _build_bundle(registry, portfolio)
    graph_source = next(
        source
        for source in bundle["sources"]
        if source["source_id"] == "canonical_graph"
    )
    graph_edge = next(
        item
        for item in graph_source["items"]
        if item["item_ref"] == "graph-edge-problem-current"
    )
    graph_edge["derivation"] = "causal"
    graph_edge["attributes"] = attributes
    _seal_bundle(bundle)
    return registry, portfolio, changed_path, bundle, authority


class _Harness:
    def __init__(self) -> None:
        self.registry = GapGraphContractRegistry.load(REGISTRY)
        self.portfolio = FrozenGapGraphPortfolio.load(
            PORTFOLIO, registry=self.registry
        )
        self.scope = _ScopeGrants()
        self.clock = _Clock()
        self.read = _ReadAuthority(_build_bundle(self.registry, self.portfolio))
        self.citations = _CitationAuthority(self.registry, self.portfolio)
        self.workspace = GovernedGapGraphWorkspace(
            scope_grants=self.scope,
            read_authority=self.read,
            citation_authority=self.citations,
            registry_path=REGISTRY,
            portfolio_path=PORTFOLIO,
            clock=self.clock,
        )

    def evaluate(self, *, principal: Principal | None = None) -> dict[str, Any]:
        return self.workspace.evaluate(
            principal=principal or _principal(),
            store_ref="store-a",
            as_of=DATA_AS_OF,
            portfolio_ref=self.portfolio.ref,
        )

    def source(self, source_id: str) -> dict[str, Any]:
        return next(
            source for source in self.read.bundle["sources"] if source["source_id"] == source_id
        )

    def item(self, source_id: str, item_ref: str) -> dict[str, Any]:
        return next(
            item for item in self.source(source_id)["items"] if item["item_ref"] == item_ref
        )

    def reseal(self) -> None:
        _seal_bundle(self.read.bundle)


def test_registry_fixture_and_positive_observation_are_frozen() -> None:
    harness = _Harness()

    observation = harness.evaluate()

    assert observation["status"] == "ready"
    assert observation["portfolio_status"] == "admitted"
    assert observation["counts"] == {
        "sources": 5,
        "citations": 12,
        "nodes": 4,
        "edges": 3,
        "gaps": 1,
        "opportunities": 1,
    }
    assert observation["opportunities"][0]["selected_action"] == "build"
    assert observation["global_top1_claim"] is False
    assert observation["correlation_is_causation"] is False
    assert all(value is False for value in observation["governance"].values())
    assert all(value == 0 for value in observation["write_counts"].values())
    assert harness.scope.calls == [TRUSTED_NOW]
    assert all(
        context["data_as_of"] == DATA_AS_OF
        and context["authority_checked_at"] == TRUSTED_NOW
        for context in harness.citations.contexts
    )


def test_deterministic_replay_and_content_drift_conflict() -> None:
    harness = _Harness()
    first = harness.evaluate()
    harness.clock.now += timedelta(minutes=1)
    replay = harness.evaluate()
    assert replay == first

    item = harness.item("primary_sources", "primary-problem-checkout-latency")
    item["attributes"]["claim_state"] = "changed"
    harness.reseal()
    with pytest.raises(GapGraphConflictError, match="immutable source projection"):
        harness.evaluate()


def test_cross_workspace_replay_is_byte_equivalent_after_trusted_clock_moves() -> None:
    first_harness = _Harness()
    first = first_harness.evaluate()
    second_harness = _Harness()
    second_harness.clock.now += timedelta(hours=1)

    second = second_harness.evaluate()

    assert second == first


def test_cached_ready_result_revalidates_citation_currentness() -> None:
    harness = _Harness()
    assert harness.evaluate()["status"] == "ready"
    harness.citations.overrides["cit-graph-current-routing"] = {"current": False}

    revoked = harness.evaluate()

    assert revoked["status"] == "blocked"
    assert revoked["portfolio_status"] == "not_admitted"
    assert revoked["nodes"] == []
    assert revoked["opportunities"][0]["selected_action"] == "no_action"
    assert harness.read.calls == 2


def test_actor_drift_conflicts_before_any_second_projection_is_admitted() -> None:
    harness = _Harness()
    harness.evaluate(principal=_principal(actor_id="operator-a"))

    with pytest.raises(GapGraphConflictError, match="immutable source projection"):
        harness.evaluate(principal=_principal(actor_id="operator-b"))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tenant_ref", "tenant-b"),
        ("entity_ref", "entity-b"),
        ("store_ref", "store-b"),
        ("authority_sha256", AUTHORITY_B),
    ],
)
def test_current_scope_or_authority_drift_is_not_visible_pre_read(
    field: str, value: str
) -> None:
    harness = _Harness()
    setattr(harness.scope, field, value)

    observation = harness.evaluate()

    assert observation["status"] == "not_visible"
    assert observation["portfolio_status"] == "not_admitted"
    assert harness.read.calls == 0
    assert observation["counts"]["nodes"] == 0


@pytest.mark.parametrize("status", ["no_data", "UNKNOWN", "blocked", "stale", "partial"])
def test_current_authority_nonready_state_fails_closed(status: str) -> None:
    harness = _Harness()
    harness.scope.status = status

    observation = harness.evaluate()

    assert observation["status"] == status
    assert observation["portfolio_status"] == "not_admitted"
    assert harness.read.calls == 0


def test_authority_rotation_cannot_rewind_with_historical_as_of() -> None:
    harness = _Harness()
    first = harness.evaluate()
    assert first["status"] == "ready"
    harness.scope.authority_sha256 = AUTHORITY_B

    rotated = harness.evaluate()

    assert rotated["status"] == "not_visible"
    assert rotated["scope"]["scope_grant_authority_sha256"] == AUTHORITY_B
    assert harness.read.calls == 1


def test_authority_revocation_after_ready_run_cannot_replay_cached_result() -> None:
    harness = _Harness()
    assert harness.evaluate()["status"] == "ready"
    harness.scope.status = "blocked"

    revoked = harness.evaluate()

    assert revoked["status"] == "blocked"
    assert revoked["portfolio_status"] == "not_admitted"
    assert revoked["nodes"] == []
    assert harness.read.calls == 1


def test_future_as_of_and_portfolio_hash_drift_are_rejected() -> None:
    harness = _Harness()
    with pytest.raises(GapGraphContractError, match="trusted current time"):
        harness.workspace.evaluate(
            principal=_principal(),
            store_ref="store-a",
            as_of=TRUSTED_NOW + timedelta(seconds=1),
            portfolio_ref=harness.portfolio.ref,
        )
    with pytest.raises(GapGraphContractError, match="portfolio_ref hash drift"):
        harness.workspace.evaluate(
            principal=_principal(),
            store_ref="store-a",
            as_of=DATA_AS_OF,
            portfolio_ref="bas200-gap-graph:1.1.0:" + "0" * 64,
        )


@pytest.mark.parametrize(
    ("override", "status"),
    [
        ({"scope": {"tenant_ref": "tenant-b", "entity_ref": "entity-a", "store_ref": "store-a", "scope_grant_authority_sha256": AUTHORITY_A}}, "not_visible"),
        ({"evidence_sha256": "0" * 64}, "blocked"),
        ({"source_contract_version": "2"}, "blocked"),
        ({"source": "unrelated-evidence-source"}, "blocked"),
        ({"source_ref": "unrelated://citation"}, "blocked"),
        ({"claims_sha256": "0" * 64}, "blocked"),
        ({"recorded_at": (DATA_AS_OF + timedelta(seconds=1)).isoformat()}, "blocked"),
        ({"effective_until": DATA_AS_OF.isoformat()}, "stale"),
        ({"integrity_status": "tampered"}, "blocked"),
        ({"current": False}, "blocked"),
        ({"grade": "D"}, "blocked"),
    ],
)
def test_citation_scope_hash_contract_time_and_integrity_fail_closed(
    override: dict[str, Any], status: str
) -> None:
    harness = _Harness()
    harness.citations.overrides["cit-graph-current-routing"] = override

    observation = harness.evaluate()

    assert observation["status"] == status
    assert observation["portfolio_status"] == "not_admitted"
    assert observation["counts"]["nodes"] == 0


def test_distinct_authority_failures_have_distinct_blocked_run_identities() -> None:
    stale = _Harness()
    stale.citations.overrides["cit-graph-current-routing"] = {
        "effective_until": DATA_AS_OF.isoformat()
    }
    stale_result = stale.evaluate()
    revoked = _Harness()
    revoked.citations.overrides["cit-graph-current-routing"] = {"current": False}
    revoked_result = revoked.evaluate()
    low_grade = _Harness()
    low_grade.citations.overrides["cit-graph-current-routing"] = {"grade": "D"}
    low_grade_result = low_grade.evaluate()

    identities = {
        (result["run_id"], result["request_sha256"])
        for result in (stale_result, revoked_result, low_grade_result)
    }
    assert len(identities) == 3
    assert {stale_result["status"], revoked_result["status"], low_grade_result["status"]} == {
        "stale",
        "blocked",
    }


def test_same_class_citation_failures_bind_subject_and_failure_kind() -> None:
    first_revoked = _Harness()
    first_revoked.citations.overrides["cit-graph-current-routing"] = {
        "current": False
    }
    first_result = first_revoked.evaluate()
    second_revoked = _Harness()
    second_revoked.citations.overrides["cit-graph-frontier-routing"] = {
        "current": False
    }
    second_result = second_revoked.evaluate()
    tampered = _Harness()
    tampered.citations.overrides["cit-graph-current-routing"] = {
        "integrity_status": "tampered"
    }
    tampered_result = tampered.evaluate()

    identities = {
        (result["run_id"], result["request_sha256"])
        for result in (first_result, second_result, tampered_result)
    }
    assert len(identities) == 3
    assert first_result["reason_codes"] == ["citation_currentness_invalid"]
    assert second_result["reason_codes"] == ["citation_currentness_invalid"]
    assert tampered_result["reason_codes"] == ["citation_integrity_invalid"]


@pytest.mark.parametrize("status", ["no_data", "partial", "stale"])
def test_source_coverage_state_never_selects_an_action(status: str) -> None:
    harness = _Harness()
    source = harness.source("strategic_benchmark")
    source["status"] = status
    harness.reseal()

    observation = harness.evaluate()

    assert observation["status"] == status
    assert observation["portfolio_status"] == "not_admitted"
    assert observation["opportunities"][0]["selected_action"] == "no_action"
    assert observation["opportunities"][0]["admission_status"] == "not_admitted"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cohort_ref", "global-all-sellers"),
        ("window_end", "2026-09-01T08:00:00+08:00"),
        ("global_top1_claim", True),
    ],
)
def test_benchmark_cohort_window_and_global_top1_drift_block_selection(
    field: str, value: Any
) -> None:
    harness = _Harness()
    item = harness.item("strategic_benchmark", "benchmark-routing-quality")
    item["attributes"][field] = value
    harness.reseal()

    observation = harness.evaluate()

    opportunity = observation["opportunities"][0]
    assert observation["portfolio_status"] == "not_admitted"
    assert opportunity["selected_action"] == "no_action"
    assert "opportunity_gap_not_ready" in opportunity["blockers"]


def test_inferred_edge_is_observation_only_and_cannot_satisfy_gate() -> None:
    harness = _Harness()
    item = harness.item("retrieval", "retrieval-problem-support")
    item["derivation"] = "inferred"
    harness.reseal()

    observation = harness.evaluate()

    edge = next(edge for edge in observation["edges"] if edge["source_id"] == "retrieval")
    assert edge["observation_only"] is True
    assert edge["canonical_graph_write"] is False
    assert edge["eligible_for_gate"] is False
    assert observation["opportunities"][0]["selected_action"] == "no_action"


def test_causal_edge_without_independent_authority_is_observation_only(
    tmp_path: Path,
) -> None:
    registry, portfolio, changed_path, bundle, _authority = _causal_artifacts(
        tmp_path, declare_authority=False
    )
    scope = _ScopeGrants()
    workspace = GovernedGapGraphWorkspace(
        scope_grants=scope,
        read_authority=_ReadAuthority(bundle),
        citation_authority=_CitationAuthority(registry, portfolio),
        registry_path=REGISTRY,
        portfolio_path=changed_path,
        clock=_Clock(),
    )

    observation = workspace.evaluate(
        principal=_principal(),
        store_ref="store-a",
        as_of=DATA_AS_OF,
        portfolio_ref=portfolio.ref,
    )

    causal_edge = observation["edges"][0]
    assert causal_edge["causal_authority_status"] == "UNKNOWN"
    assert "independent_causal_authority_UNKNOWN" in causal_edge["blockers"]
    assert causal_edge["eligible_for_gate"] is False
    assert observation["opportunities"][0]["selected_action"] == "no_action"


def test_declared_causal_receipt_needs_independent_authority_adapter(
    tmp_path: Path,
) -> None:
    registry, portfolio, changed_path, bundle, _authority = _causal_artifacts(
        tmp_path, declare_authority=True
    )
    workspace = GovernedGapGraphWorkspace(
        scope_grants=_ScopeGrants(),
        read_authority=_ReadAuthority(bundle),
        citation_authority=_CitationAuthority(registry, portfolio),
        registry_path=REGISTRY,
        portfolio_path=changed_path,
        clock=_Clock(),
    )

    observation = workspace.evaluate(
        principal=_principal(),
        store_ref="store-a",
        as_of=DATA_AS_OF,
        portfolio_ref=portfolio.ref,
    )

    assert observation["status"] == "blocked"
    assert "independent_causal_authority_unavailable" in observation["reason_codes"]
    assert observation["edges"] == []
    assert observation["opportunities"][0]["selected_action"] == "no_action"


def test_independently_verified_causal_receipt_can_satisfy_synthetic_gate(
    tmp_path: Path,
) -> None:
    registry, portfolio, changed_path, bundle, authority = _causal_artifacts(
        tmp_path, declare_authority=True
    )
    assert authority is not None
    causal_authority = _CausalAuthority(authority)
    workspace = GovernedGapGraphWorkspace(
        scope_grants=_ScopeGrants(),
        read_authority=_ReadAuthority(bundle),
        citation_authority=_CitationAuthority(registry, portfolio),
        causal_authority=causal_authority,
        registry_path=REGISTRY,
        portfolio_path=changed_path,
        clock=_Clock(),
    )

    observation = workspace.evaluate(
        principal=_principal(),
        store_ref="store-a",
        as_of=DATA_AS_OF,
        portfolio_ref=portfolio.ref,
    )

    assert observation["status"] == "ready"
    assert observation["edges"][0]["causal_authority_status"] == "verified"
    assert causal_authority.calls == 1


def test_cached_causal_receipt_revocation_never_returns_prior_ready(
    tmp_path: Path,
) -> None:
    registry, portfolio, changed_path, bundle, authority = _causal_artifacts(
        tmp_path, declare_authority=True
    )
    assert authority is not None
    causal_authority = _CausalAuthority(authority)
    workspace = GovernedGapGraphWorkspace(
        scope_grants=_ScopeGrants(),
        read_authority=_ReadAuthority(bundle),
        citation_authority=_CitationAuthority(registry, portfolio),
        causal_authority=causal_authority,
        registry_path=REGISTRY,
        portfolio_path=changed_path,
        clock=_Clock(),
    )
    request = {
        "principal": _principal(),
        "store_ref": "store-a",
        "as_of": DATA_AS_OF,
        "portfolio_ref": portfolio.ref,
    }
    assert workspace.evaluate(**request)["status"] == "ready"
    causal_authority.override = {"current": False}

    revoked = workspace.evaluate(**request)

    assert revoked["status"] == "blocked"
    assert revoked["portfolio_status"] == "not_admitted"
    assert revoked["nodes"] == []
    assert revoked["opportunities"][0]["selected_action"] == "no_action"
    assert "causal_authority_currentness_invalid" in revoked["reason_codes"]
    assert causal_authority.calls == 2


@pytest.mark.parametrize(
    ("source_id", "item_ref", "field", "value", "blocker"),
    [
        (
            "retrieval",
            "retrieval-problem-support",
            "proposed_action",
            "buy",
            "decision_policy_claim_projection_drift",
        ),
        (
            "profit_truth",
            "profit-return-cost",
            "maximum_loss_value",
            "999.000000",
            "maximum_loss_claim_projection_drift",
        ),
        (
            "profit_truth",
            "profit-return-cost",
            "downside_policy_sha256",
            "0" * 64,
            "downside_claim_projection_drift",
        ),
        (
            "profit_truth",
            "profit-return-cost",
            "rollback_artifact_sha256",
            "0" * 64,
            "rollback_claim_projection_drift",
        ),
    ],
)
def test_authoritative_policy_claim_drift_never_selects_action(
    source_id: str,
    item_ref: str,
    field: str,
    value: str,
    blocker: str,
) -> None:
    harness = _Harness()
    item = harness.item(source_id, item_ref)
    item["attributes"][field] = value
    harness.reseal()

    observation = harness.evaluate()

    opportunity = observation["opportunities"][0]
    assert opportunity["selected_action"] == "no_action"
    assert blocker in opportunity["blockers"]


@pytest.mark.parametrize(
    ("field", "expected_blocker"),
    [
        ("invalidation_conditions", "decision_policy_claim_projection_drift"),
        ("rollback_trigger_codes", "rollback_claim_projection_drift"),
    ],
)
def test_invalidation_and_rollback_triggers_are_evidence_bound(
    tmp_path: Path, field: str, expected_blocker: str
) -> None:
    registry = GapGraphContractRegistry.load(REGISTRY)
    original_portfolio = FrozenGapGraphPortfolio.load(PORTFOLIO, registry=registry)
    old_bundle = _build_bundle(registry, original_portfolio)
    payload = json.loads(PORTFOLIO.read_text(encoding="utf-8"))
    opportunity = payload["opportunity_specs"][0]
    if field == "invalidation_conditions":
        opportunity["invalidation_conditions"] = ["changed-invalidation"]
    else:
        opportunity["rollback"]["trigger_codes"] = ["changed-rollback-trigger"]
    payload["content_sha256"] = _hash(
        {key: value for key, value in payload.items() if key != "content_sha256"}
    )
    changed_path = tmp_path / "policy-control-portfolio.json"
    changed_path.write_text(json.dumps(payload), encoding="utf-8")
    changed_portfolio = FrozenGapGraphPortfolio.load(changed_path, registry=registry)
    old_bundle["portfolio_ref"] = changed_portfolio.ref
    _seal_bundle(old_bundle)
    workspace = GovernedGapGraphWorkspace(
        scope_grants=_ScopeGrants(),
        read_authority=_ReadAuthority(old_bundle),
        citation_authority=_CitationAuthority(registry, changed_portfolio),
        registry_path=REGISTRY,
        portfolio_path=changed_path,
        clock=_Clock(),
    )

    observation = workspace.evaluate(
        principal=_principal(),
        store_ref="store-a",
        as_of=DATA_AS_OF,
        portfolio_ref=changed_portfolio.ref,
    )

    opportunity_result = observation["opportunities"][0]
    assert opportunity_result["selected_action"] == "no_action"
    assert expected_blocker in opportunity_result["blockers"]


@pytest.mark.parametrize(
    ("selector", "status"),
    [
        (("alternatives", 0), "UNKNOWN"),
        (("decision_policy", None), "UNKNOWN"),
        (("maximum_loss", None), "UNKNOWN"),
        (("downside", None), "UNKNOWN"),
        (("rollback", None), "UNKNOWN"),
    ],
)
def test_any_unknown_strategic_gate_forces_no_action(
    tmp_path: Path, selector: tuple[str, int | None], status: str
) -> None:
    payload = json.loads(PORTFOLIO.read_text(encoding="utf-8"))
    opportunity = payload["opportunity_specs"][0]
    field, index = selector
    if index is None:
        opportunity[field]["status"] = status
    else:
        opportunity[field][index]["status"] = status
    payload["content_sha256"] = _hash(
        {key: value for key, value in payload.items() if key != "content_sha256"}
    )
    changed = tmp_path / "portfolio.json"
    changed.write_text(json.dumps(payload), encoding="utf-8")

    harness = _Harness()
    harness.workspace = GovernedGapGraphWorkspace(
        scope_grants=harness.scope,
        read_authority=harness.read,
        citation_authority=harness.citations,
        registry_path=REGISTRY,
        portfolio_path=changed,
        clock=harness.clock,
    )
    harness.portfolio = harness.workspace.portfolio
    harness.read.bundle["portfolio_ref"] = harness.portfolio.ref
    harness.read.bundle["bundle_sha256"] = _hash(
        {key: value for key, value in harness.read.bundle.items() if key != "bundle_sha256"}
    )

    observation = harness.evaluate()

    assert observation["portfolio_status"] == "not_admitted"
    assert observation["opportunities"][0]["selected_action"] == "no_action"


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate_node",
        "orphan_edge",
        "dependency_cycle",
        "future_source_evidence",
        "stale_source_evidence",
        "source_scope_drift",
        "source_claim_hash_drift",
    ],
)
def test_fixture_identity_and_graph_structure_fail_closed(
    tmp_path: Path, mutation: str
) -> None:
    registry = GapGraphContractRegistry.load(REGISTRY)
    payload = json.loads(PORTFOLIO.read_text(encoding="utf-8"))
    if mutation == "duplicate_node":
        payload["node_specs"].append(deepcopy(payload["node_specs"][0]))
    elif mutation == "orphan_edge":
        payload["edge_specs"][0]["source_node_spec_id"] = "missing-node"
    elif mutation == "dependency_cycle":
        original = payload["opportunity_specs"][0]
        second = deepcopy(original)
        second["opportunity_spec_id"] = "opportunity-second"
        original["dependency_opportunity_ids"] = ["opportunity-second"]
        second["dependency_opportunity_ids"] = [original["opportunity_spec_id"]]
        payload["opportunity_specs"].append(second)
    elif mutation == "future_source_evidence":
        payload["source_bindings"][0]["evidence_binding"]["recorded_at"] = (
            DATA_AS_OF + timedelta(seconds=1)
        ).isoformat()
    elif mutation == "stale_source_evidence":
        payload["source_bindings"][0]["evidence_binding"][
            "effective_until"
        ] = DATA_AS_OF.isoformat()
    elif mutation == "source_scope_drift":
        payload["source_bindings"][0]["scope"]["entity_ref"] = "entity-b"
    else:
        payload["source_bindings"][0]["evidence_binding"][
            "claims_sha256"
        ] = "0" * 64
    payload["content_sha256"] = _hash(
        {key: value for key, value in payload.items() if key != "content_sha256"}
    )
    changed = tmp_path / "portfolio.json"
    changed.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(GapGraphContractError):
        FrozenGapGraphPortfolio.load(changed, registry=registry)


def test_forward_dependency_dag_is_evaluated_in_stable_topological_order(
    tmp_path: Path,
) -> None:
    registry = GapGraphContractRegistry.load(REGISTRY)
    payload = json.loads(PORTFOLIO.read_text(encoding="utf-8"))
    dependent = payload["opportunity_specs"][0]
    prerequisite = deepcopy(dependent)
    prerequisite["opportunity_spec_id"] = "opportunity-base-prerequisite"
    prerequisite["dependency_opportunity_ids"] = []
    dependent["dependency_opportunity_ids"] = [
        prerequisite["opportunity_spec_id"]
    ]
    payload["opportunity_specs"].append(prerequisite)
    payload["content_sha256"] = _hash(
        {key: value for key, value in payload.items() if key != "content_sha256"}
    )
    changed_path = tmp_path / "forward-dag-portfolio.json"
    changed_path.write_text(json.dumps(payload), encoding="utf-8")
    portfolio = FrozenGapGraphPortfolio.load(changed_path, registry=registry)
    bundle = _build_bundle(registry, portfolio)
    workspace = GovernedGapGraphWorkspace(
        scope_grants=_ScopeGrants(),
        read_authority=_ReadAuthority(bundle),
        citation_authority=_CitationAuthority(registry, portfolio),
        registry_path=REGISTRY,
        portfolio_path=changed_path,
        clock=_Clock(),
    )

    observation = workspace.evaluate(
        principal=_principal(),
        store_ref="store-a",
        as_of=DATA_AS_OF,
        portfolio_ref=portfolio.ref,
    )

    assert observation["portfolio_status"] == "admitted"
    assert [
        item["opportunity_spec_id"] for item in observation["opportunities"]
    ] == [
        "opportunity-base-prerequisite",
        "opportunity-build-routing-guard",
    ]


def test_authority_adapter_failure_and_sensitive_projection_fail_closed() -> None:
    harness = _Harness()
    harness.citations.raises["cit-retrieval-problem-support"] = RuntimeError(
        "provider-secret-body"
    )

    observation = harness.evaluate()

    serialized = json.dumps(observation, sort_keys=True)
    assert observation["status"] == "blocked"
    assert "provider-secret-body" not in serialized
    assert observation["portfolio_status"] == "not_admitted"


def test_raw_sensitive_data_is_rejected_without_persistence() -> None:
    harness = _Harness()
    item = harness.item("primary_sources", "primary-problem-checkout-latency")
    item["attributes"]["provider_request_id"] = "raw-identifier"
    harness.reseal()

    observation = harness.evaluate()

    assert observation["status"] == "UNKNOWN"
    assert observation["portfolio_status"] == "not_admitted"
    assert "raw-identifier" not in json.dumps(observation)


def test_read_projection_source_binding_drift_is_blocked() -> None:
    harness = _Harness()
    source = harness.source("primary_sources")
    source["evidence_binding"]["evidence_sha256"] = "0" * 64
    harness.reseal()

    observation = harness.evaluate()

    assert observation["status"] == "blocked"
    assert "read_projection_contract_or_hash_invalid" in observation["reason_codes"]
