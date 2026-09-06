from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from apps.control_plane.data_fabric_contracts import (
    DRILLDOWN_LEVEL_ORDER,
    LINEAGE_STAGE_ORDER,
    ActionEnvelope,
    AnalysisRecipe,
    DataEnvelope,
    DrilldownNode,
    DrilldownPath,
    FactDataContract,
    LineageChain,
    LineageNode,
    PeriodRef,
    QualitySummary,
    ScopeRef,
    canonical_scope_key,
)


def scope() -> ScopeRef:
    return ScopeRef(tenant_id="t1", entity_id="e1", store_ids=("s1",))


def test_ready_envelope_requires_fresh_quality_and_preserves_scope() -> None:
    envelope = DataEnvelope(
        dataset="profit.cm3.v1",
        scope=scope(),
        as_of=datetime(2026, 9, 6, tzinfo=UTC),
        fresh_until=datetime(2026, 9, 6, 1, tzinfo=UTC),
        status="ready",
        data=({"sku_id": "sku-1", "cm3": "26"},),
        quality=QualitySummary(completeness=1, freshness="fresh"),
        schema_version="1.0",
        authority_hash="authority-1",
    )

    assert envelope.scope.store_ids == ("s1",)
    assert envelope.data[0]["sku_id"] == "sku-1"


@pytest.mark.parametrize("status", ["no_data", "blocked", "unknown_outcome"])
def test_non_data_states_cannot_hide_rows(status: str) -> None:
    with pytest.raises(ValidationError, match="cannot contain data rows"):
        DataEnvelope(
            dataset="orders.v1",
            scope=scope(),
            as_of=datetime(2026, 9, 6, tzinfo=UTC),
            status=status,
            data=({"order_id": "o1"},),
            quality=QualitySummary(completeness=0, freshness="unknown"),
            schema_version="1.0",
            authority_hash="authority-1",
        )


def test_execute_action_requires_one_time_controls() -> None:
    with pytest.raises(ValidationError, match="missing: permit_ref"):
        ActionEnvelope(
            command_id="cmd-1",
            idempotency_key="idem-1",
            scope=scope(),
            input_snapshot_id="snap-1",
            mode="execute",
        )

    action = ActionEnvelope(
        command_id="cmd-1",
        idempotency_key="idem-1",
        scope=scope(),
        input_snapshot_id="snap-1",
        mode="execute",
        permit_ref="permit-1",
        budget_reservation_ref="budget-1",
        expected_readback="status=active",
        rollback_ref="rollback-1",
    )
    assert action.mode == "execute"


def test_period_requires_forward_window() -> None:
    with pytest.raises(ValidationError, match="end_at"):
        PeriodRef(
            period_type="month",
            start_at=datetime(2026, 9, 2, tzinfo=UTC),
            end_at=datetime(2026, 9, 1, tzinfo=UTC),
            timezone="Europe/Moscow",
            currency="RUB",
            as_of=datetime(2026, 9, 6, tzinfo=UTC),
        )


def test_analysis_recipe_rejects_duplicate_metrics() -> None:
    with pytest.raises(ValidationError, match="metrics must be unique"):
        AnalysisRecipe(
            recipe_id="r1",
            version="1",
            scope=scope(),
            period=PeriodRef(
                period_type="month",
                start_at=datetime(2026, 9, 1, tzinfo=UTC),
                end_at=datetime(2026, 10, 1, tzinfo=UTC),
                timezone="Europe/Moscow",
                currency="RUB",
                as_of=datetime(2026, 9, 6, tzinfo=UTC),
            ),
            dimensions=("sku",),
            metrics=("cm3", "cm3"),
        )


def test_scope_accepts_sku_alias_without_changing_legacy_scope_key() -> None:
    legacy = ScopeRef(tenant_id="t1", entity_id="e1", store="s1")
    sku_scope = ScopeRef(tenant_id="t1", entity_id="e1", store="s1", warehouse="w1", sku="sku-1")

    assert legacy.store_ids == ("s1",)
    assert legacy.model_dump() == {
        "tenant_id": "t1",
        "entity_id": "e1",
        "store_ids": ("s1",),
        "warehouse_ids": (),
    }
    assert canonical_scope_key(legacy) == "t1:e1:s1:"
    assert canonical_scope_key(sku_scope) == "t1:e1:s1:w1:sku-1"


def _complete_row(**overrides):
    values = {
        "tenant": "t1",
        "entity": "e1",
        "store": "s1",
        "warehouse": "w1",
        "sku": "sku-1",
        "source_system": "ozon",
        "source_record_id": "order-1",
        "source_version": "2026-09-06",
        "event_time": datetime(2026, 9, 1, tzinfo=UTC),
        "observed_time": datetime(2026, 9, 1, 1, tzinfo=UTC),
        "causation_id": "import-1",
        "correlation_id": "run-1",
        "idempotency_key": "idem-1",
        "quality_state": "VALID",
        "freshness": "fresh",
        "lineage_refs": ({"kind": "raw_file", "id": "file-1", "sha256": "a" * 64},),
        "permission_scope": "t1:e1:s1:w1:sku-1",
        "payload": {"quantity": 0},
    }
    values.update(overrides)
    return values


def test_fact_data_contract_keeps_zero_separate_from_quality() -> None:
    row = FactDataContract.model_validate(_complete_row())
    assert row.payload["quantity"] == 0
    assert row.quality_state == "VALID"
    assert row.freshness == "fresh"
    assert row.model_dump()["lineage_refs"][0]["id"] == "file-1"

    with pytest.raises(ValidationError, match="permission_scope"):
        FactDataContract.model_validate(_complete_row(permission_scope="t1:e1:s1:w1"))
    with pytest.raises(ValidationError, match="UNKNOWN_OUTCOME row cannot contain"):
        FactDataContract.model_validate(
            _complete_row(quality_state="UNKNOWN_OUTCOME", freshness="unknown", payload={"quantity": 0})
        )


def test_data_envelope_can_attach_strict_records_without_breaking_legacy_rows() -> None:
    record = FactDataContract.model_validate(_complete_row())
    envelope = DataEnvelope(
        dataset="orders.v1",
        scope=ScopeRef(tenant_id="t1", entity_id="e1", store="s1", warehouse="w1", sku="sku-1"),
        as_of=datetime(2026, 9, 6, tzinfo=UTC),
        status="ready",
        data=(record.payload,),
        records=(record,),
        quality=QualitySummary(completeness=1, freshness="fresh"),
        schema_version="1.0",
        authority_hash="authority-1",
    )
    assert envelope.validate_records(require_complete=True) == (record,)
    assert envelope.lineage_audit()["record_contract_complete"] is True

    legacy = DataEnvelope(
        dataset="orders.v1",
        scope=scope(),
        as_of=datetime(2026, 9, 6, tzinfo=UTC),
        status="ready",
        data=({"quantity": 0},),
        quality=QualitySummary(completeness=1, freshness="fresh"),
        schema_version="1.0",
        authority_hash="authority-1",
    )
    assert legacy.validate_records() == ()
    with pytest.raises(ValueError, match="no complete provenance"):
        legacy.validate_records(require_complete=True)


def test_lineage_chain_and_six_level_path_report_missing_nodes() -> None:
    chain = LineageChain(
        nodes=(
            LineageNode(stage="metric", id="metric-1"),
            LineageNode(stage="dataset", id="orders.v1"),
            LineageNode(stage="fact_revision", id="fact-1"),
        ),
    )
    assert chain.present_stages == ("metric", "data_product", "canonical_fact")
    assert chain.complete is False
    assert chain.coverage == 3 / len(LINEAGE_STAGE_ORDER)
    assert "raw_file" in chain.missing_stages

    path = DrilldownPath(
        nodes=(
            DrilldownNode(level="entity", id="e1"),
            DrilldownNode(level="store", id="s1", parent_id="e1"),
            DrilldownNode(level="warehouse", id="w1", parent_id="s1"),
            DrilldownNode(level="sku", id="sku-1", parent_id="w1"),
            DrilldownNode(level="order", id="o1", parent_id="sku-1"),
            DrilldownNode(level="evidence", id="ev-1", parent_id="o1"),
        )
    )
    assert path.complete is True
    assert path.missing_levels == ()
    assert tuple(node.level for node in path.nodes) == DRILLDOWN_LEVEL_ORDER

    with pytest.raises(ValidationError, match="ordered"):
        DrilldownPath(nodes=(DrilldownNode(level="sku", id="sku-1"), DrilldownNode(level="store", id="s1")))


def test_lineage_chain_requires_connected_ordered_edges_for_strict_replay() -> None:
    nodes = tuple(LineageNode(stage=stage, id=f"{stage}-1") for stage in LINEAGE_STAGE_ORDER)
    edges = tuple(
        {
            "from_type": left.stage,
            "from_id": left.id,
            "to_type": right.stage,
            "to_id": right.id,
            "relationship": "derives",
        }
        for left, right in zip(nodes, nodes[1:], strict=False)
    )
    chain = LineageChain(nodes=nodes, edges=edges)
    assert chain.complete is True
    assert chain.structurally_complete is True
    assert chain.continuity_errors == ()
    assert chain.structure_audit()["edge_count"] == len(LINEAGE_STAGE_ORDER) - 1

    broken = LineageChain(nodes=nodes, edges=edges[:-1])
    assert broken.complete is True
    assert broken.structurally_complete is False
    assert any(item.startswith("adjacent_edge_missing:") for item in broken.continuity_errors)


def test_lineage_chain_rejects_or_reports_edges_outside_node_set() -> None:
    chain = LineageChain(
        nodes=(LineageNode(stage="metric", id="metric-1"),),
        edges=(
            {
                "from_type": "metric",
                "from_id": "metric-1",
                "to_type": "raw_file",
                "to_id": "missing-file",
                "relationship": "derives",
            },
        ),
        required_stages=("metric",),
    )
    assert chain.complete is True
    assert chain.structurally_complete is False
    assert "edge_target_missing:raw_file:missing-file" in chain.continuity_errors
