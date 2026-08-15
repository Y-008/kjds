from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane import ai_listing as _ai_listing  # noqa: F401
from apps.control_plane import browser_capture_inbox as _browser_capture_inbox  # noqa: F401
from apps.control_plane.evidence import EvidenceService
from apps.control_plane.market_recon_bundle import MarketReconBundleIngestion
from apps.control_plane.profit_command import (
    ProfitCommandConflict,
    ProfitCommandWorkspace,
    ProfitDecisionSnapshotRow,
    ProfitPilotProposalRow,
)
from apps.control_plane.profit_data_remediation import ProfitDataRemediationWorkspace
from apps.control_plane.security import Principal
from apps.control_plane.sql_repository import Base
from apps.control_plane.store_profile_intake import StoreProfileIntake
from scripts.package_market_recon_bundle import DEFAULT_OUTPUT, package_bundle

AS_OF = datetime(2026, 8, 2, 7, tzinfo=UTC)


def database():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    return engine


def principal(*, tenant_ref: str = "tenant-a") -> Principal:
    return Principal(
        actor_id="operator-a",
        roles=frozenset({"operator"}),
        tenant_ref=tenant_ref,
        store_refs=frozenset({"store-a"}),
    )


def entity_scope(*, entity_ref: str = "entity-a", authority: str = "a") -> dict:
    return {
        "status": "ready",
        "entity_ref": entity_ref,
        "authority_sha256": authority * 64,
    }


def workspace_with_bundle() -> tuple[ProfitCommandWorkspace, object]:
    engine = database()
    evidence = EvidenceService(engine)
    bundle = package_bundle(DEFAULT_OUTPUT).read_bytes()
    MarketReconBundleIngestion(engine=engine, evidence=evidence).ingest(
        bundle,
        filename="market_recon_bundle.zip",
        idempotency_key="profit-command-source",
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )
    return ProfitCommandWorkspace(engine=engine, evidence=evidence), engine


def test_workspace_exposes_all_profit_bases_and_drillthrough_without_guessing() -> None:
    workspace, _ = workspace_with_bundle()

    result = workspace.project(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
        display_currency="CNY",
    )

    assert result["status"] == "ready_with_constraints"
    assert result["counts"]["candidates"] == 18
    assert result["counts"]["pilot"] == 0
    assert result["counts"]["needs_data"] == 18
    assert result["summary"]["actual_cash_profit"]["amount"] is None
    assert result["drillthrough"]["scope_path"].endswith("order/fee/settlement/evidence")
    assert result["control_envelope"]["external_write_allowed"] is False
    first = next(item for item in result["candidates"] if item["offer_id"] == "1982483707WZ")
    assert first["raw_money"]["own_price"]["currency"] == "CNY"
    assert first["raw_money"]["market_reference_price"]["currency"] == "RUB"
    assert first["raw_money"]["fx_basis"] is None
    assert first["cost_coverage"]["required"] == 15
    assert first["cost_coverage"]["evidenced"] == 0
    assert first["profit"]["scenario_profit"]["status"] == "no_data"
    assert first["profit"]["accrual_profit"]["status"] == "no_data"
    assert first["profit"]["settlement_profit"]["status"] == "no_data"
    assert first["profit"]["cash_profit"]["status"] == "no_data"
    assert first["profit"]["risk_adjusted_profit"]["status"] == "no_data"
    assert "fx_basis_missing" in first["reason_codes"]


def test_candidate_detail_and_cross_tenant_read_are_fail_closed() -> None:
    workspace, _ = workspace_with_bundle()

    detail = workspace.candidate(
        "ozon:1982483707WZ",
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )
    assert detail["candidate"]["offer_id"] == "1982483707WZ"
    assert detail["control_envelope"]["automatic_purchase_allowed"] is False

    with pytest.raises(KeyError, match="authorized scope"):
        workspace.candidate(
            "ozon:1982483707WZ",
            principal=principal(tenant_ref="tenant-b"),
            entity_scope=entity_scope(entity_ref="entity-b"),
            store_ref="store-a",
            as_of=AS_OF,
        )


def test_candidate_collection_is_server_filtered_and_cursor_paginated() -> None:
    workspace, _ = workspace_with_bundle()

    first = workspace.candidates(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
        decision_class="needs_data",
        page_size=5,
    )
    second = workspace.candidates(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
        decision_class="needs_data",
        page_size=5,
        cursor=first["pagination"]["next_cursor"],
    )

    assert first["count"] == 5
    assert first["pagination"]["next_cursor"] is not None
    assert {item["candidate_id"] for item in first["candidates"]}.isdisjoint(
        item["candidate_id"] for item in second["candidates"]
    )
    assert all(
        item["decision_class"] == "needs_data" for item in first["candidates"]
    )


def test_analytics_uses_real_server_projections_and_never_fabricates_history() -> None:
    workspace, _ = workspace_with_bundle()

    result = workspace.analytics(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )

    assert result["counts"]["candidates"] == 18
    assert result["decision_distribution"] == [
        {"key": "needs_data", "count": 18}
    ]
    assert len(result["cost_state_matrix"]) == 15
    assert result["profit_metrics"]["cash_profit"]["status"] == "no_data"
    assert result["time_series"] == {
        "status": "no_data",
        "points": [],
        "reason": "replayable_profit_time_series_missing",
        "synthetic_points_created": False,
    }
    assert result["control_envelope"]["client_profit_recalculation"] is False


def test_remediation_projects_every_retained_source_and_candidate_blocker() -> None:
    workspace, _ = workspace_with_bundle()
    workspace.data_remediation = ProfitDataRemediationWorkspace()

    result = workspace.remediation(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )

    assert result["contract_id"] == "kjds-profit-data-remediation-v1"
    assert result["reconciliation"]["source_total"] >= 374
    assert result["reconciliation"]["accepted"] == (
        result["reconciliation"]["source_total"] - 325
    )
    assert result["reconciliation"]["quarantined"] == 325
    assert result["reconciliation"]["conservation_passed"] is True
    assert result["summary"]["candidates"] == 18
    assert result["summary"]["remediation_items"] > 325
    assert result["groups"]["by_error_code"]
    assert result["drillthrough"]["bundle_quality"].endswith("/quality")
    assert result["control_envelope"]["missing_values_guessed"] is False
    assert result["control_envelope"]["external_write_allowed"] is False


def test_remediation_reads_historical_bundle_after_same_scope_grant_rotation() -> None:
    workspace, _ = workspace_with_bundle()
    workspace.data_remediation = ProfitDataRemediationWorkspace()

    result = workspace.remediation(
        principal=principal(),
        entity_scope=entity_scope(authority="b"),
        store_ref="store-a",
        as_of=AS_OF,
    )

    assert result["reconciliation"]["source_total"] >= 374
    assert result["scope"]["scope_grant_authority_sha256"] == "a" * 64
    assert result["access_authority"] == {
        "current_scope_grant_authority_sha256": "b" * 64,
        "source_scope_grant_authority_sha256": "a" * 64,
        "grant_rotated": True,
    }


def test_remediation_queue_is_server_paginated_without_changing_full_totals() -> None:
    workspace, _ = workspace_with_bundle()
    workspace.data_remediation = ProfitDataRemediationWorkspace()

    first = workspace.remediation(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
        queue_page_size=50,
    )
    second = workspace.remediation(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
        queue_page_size=50,
        queue_offset=50,
    )

    expected_total = 776 + first["reconciliation"]["source_total"] - 374
    assert first["summary"]["remediation_items"] == expected_total
    assert first["pagination"] == {
        "page_size": 50,
        "offset": 0,
        "previous_offset": None,
        "next_offset": 50,
        "page_count": 50,
        "total_count": expected_total,
    }
    assert second["pagination"]["previous_offset"] == 0
    assert len(second["remediation_queue"]) == 50
    assert {
        item["remediation_item_id"] for item in first["remediation_queue"]
    }.isdisjoint(item["remediation_item_id"] for item in second["remediation_queue"])
    assert first["source_snapshot_sha256"] == second["source_snapshot_sha256"]


def test_store_profile_proposal_uses_only_observed_category_listing_evidence() -> None:
    workspace, _ = workspace_with_bundle()
    workspace.store_profile_intake = StoreProfileIntake()

    result = workspace.store_profile_proposal(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        seller_tier="beginner",
        as_of=AS_OF,
    )

    assert result["contract_id"] == "kjds-evidence-backed-store-profile-proposal-v1"
    assert result["truth_status"] == "proposal_only"
    assert result["seller_tier"] == "novice"
    assert result["source_observation_count"] == 36
    assert result["quality"]["evidence_type_coverage"] == ["category", "listing"]
    assert result["quality"]["variant_quality"] == "ambiguous"
    assert result["category_role_assignments"]
    assert "evidence_type_coverage_incomplete" in result["source_gaps"]
    assert "exact_variant_identity_missing" in result["source_gaps"]
    assert result["control_envelope"]["automatic_publish_allowed"] is False
    assert result["control_envelope"]["external_write_allowed"] is False


def test_lineage_preserves_all_governance_stages_and_source_evidence() -> None:
    workspace, _ = workspace_with_bundle()

    result = workspace.lineage(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
        candidate_id="ozon:1982483707WZ",
    )

    assert [node["stage"] for node in result["nodes"]] == [
        "raw_evidence",
        "normalized_observation",
        "reviewed_observation",
        "formal_fact",
        "decision_snapshot",
    ]
    assert result["candidate_lineage"][0]["evidence_ids"]
    assert result["quarantine"]["raw_data_deleted"] is False
    assert result["control_envelope"]["automatic_fact_promotion"] is False


def test_portfolio_does_not_sum_cash_profit_across_store_snapshots() -> None:
    workspace, _ = workspace_with_bundle()
    store_workspace = workspace.project(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )

    result = ProfitCommandWorkspace.portfolio(
        [store_workspace],
        tenant_ref="tenant-a",
        as_of=AS_OF,
        display_currency="CNY",
        store_coverage=[{"store_ref": "store-a", "status": "ready"}],
    )

    actual = result["summary"]["actual_cash_profit"]
    assert actual["status"] == "available_by_store_not_aggregated"
    assert actual["amount"] is None
    assert result["control_envelope"]["cross_store_amount_aggregation"] is False


def test_blocked_pilot_is_immutable_evidenced_and_idempotent() -> None:
    workspace, engine = workspace_with_bundle()
    request = {
        "idempotency_key": "pilot-1982483707WZ-v1",
        "max_budget_amount": "300.00",
        "stop_loss_amount": "80.00",
    }

    first = workspace.propose_pilot(
        "ozon:1982483707WZ",
        request=request,
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )
    replay = workspace.propose_pilot(
        "ozon:1982483707WZ",
        request=request,
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )

    assert first["status"] == "blocked"
    assert "positive_downside_cm3_missing" in first["proposal"]["reason_codes"]
    assert first["proposal"]["budget_limit"]["currency"] == "CNY"
    assert first["proposal"]["budget_limit"]["evidence_id"] == first["request_evidence_id"]
    assert first["external_write_allowed"] is False
    assert replay["proposal_id"] == first["proposal_id"]
    assert replay["idempotent"] is True
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ProfitDecisionSnapshotRow)) == 1
        assert session.scalar(select(func.count()).select_from(ProfitPilotProposalRow)) == 1

    with pytest.raises(ProfitCommandConflict, match="different immutable content"):
        workspace.propose_pilot(
            "ozon:1982483707WZ",
            request={**request, "max_budget_amount": "301.00"},
            principal=principal(),
            entity_scope=entity_scope(),
            store_ref="store-a",
            as_of=AS_OF,
        )
