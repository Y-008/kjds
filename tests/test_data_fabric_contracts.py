from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from apps.control_plane.data_fabric_contracts import (
    ActionEnvelope,
    AnalysisRecipe,
    DataEnvelope,
    PeriodRef,
    QualitySummary,
    ScopeRef,
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
