from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.control_plane.economic_guard_service import (
    EconomicGuardInput,
    evaluate_economic_guard,
)
from apps.control_plane.ozon_price_stock_quality import (
    assert_shadow_idempotent,
    build_price_stock_shadow,
    check_shadow_idempotency,
    validate_catalog_price_stock,
)

NOW = datetime(2026, 9, 7, 12, tzinfo=UTC)
SCOPE = {
    "tenant_ref": "tenant-a",
    "entity_ref": "entity-a",
    "store_ref": "ozon-primary",
}


def item(**overrides):
    value = {
        "offer_id": "offer-1",
        "marketplace_sku": "sku-1",
        "currency_code": "RUB",
        "prices": {
            "price": "100.00",
            "old_price": "120.00",
            "min_price": "90.00",
        },
        "stocks": [
            {"warehouse_ref": "warehouse-1", "present": 5, "reserved": 1},
        ],
        "available_stock": 5,
        "source_evidence_id": "evd-1",
        "source_evidence_sha256": "b" * 64,
        "item_hash": "a" * 64,
        "observed_at": NOW - timedelta(minutes=1),
    }
    value.update(overrides)
    return value


def guard(*, cash: str = "100"):
    return evaluate_economic_guard(
        EconomicGuardInput(
            cash_available=Decimal(cash),
            min_cash=Decimal("10"),
            budget_remaining=Decimal("100"),
        )
    )


def test_valid_price_and_stock_are_normalized_without_losing_zero_stock_semantics():
    result = validate_catalog_price_stock(
        item(
            prices={"price": "100.00"},
            stocks=[{"warehouse_id": "warehouse-1", "present": "0"}],
            available_stock="0",
        ),
        now=NOW,
    )

    assert result.price_state == "VALID"
    assert result.stock_state == "VALID"
    assert result.quality_state == "VALID"
    assert result.price == Decimal("100.00")
    assert result.stock_total == 0
    assert result.stocks[0].present == 0
    assert result.freshness == "fresh"
    assert result.model_dump()["price"] == "100"


def test_missing_price_and_ambiguous_stock_are_explicit_quality_failures():
    result = validate_catalog_price_stock(
        item(
            prices={"old_price": "120"},
            stocks=[
                {
                    "warehouse_ref": "warehouse-1",
                    "warehouse_id": "warehouse-2",
                    "present": 3,
                }
            ],
        ),
        now=NOW,
    )

    assert result.price_state == "NO_DATA"
    assert result.stock_state == "BLOCKED"
    assert result.quality_state == "BLOCKED"
    assert "price_missing" in result.blockers
    assert "stock_warehouse_ambiguous:0" in result.blockers


@pytest.mark.parametrize(
    ("prices", "currency", "expected"),
    [
        ({"price": "NaN"}, "RUB", "price_invalid:price_must_be_positive_and_finite"),
        ({"price": "-1"}, "RUB", "price_invalid:price_must_be_positive_and_finite"),
        ({"price": "100", "min_price": "101"}, "RUB", "price_min_above_current"),
        ({"price": "100"}, "RUBBLE", "price_currency_invalid"),
    ],
)
def test_price_semantic_conflicts_block_the_projection(prices, currency, expected):
    result = validate_catalog_price_stock(
        item(prices=prices, currency_code=currency),
        now=NOW,
    )

    assert result.price_state == "BLOCKED"
    assert result.quality_state == "BLOCKED"
    assert expected in result.blockers


def test_stale_and_unknown_outcome_never_become_valid():
    stale = validate_catalog_price_stock(
        item(observed_at=NOW - timedelta(hours=2)),
        now=NOW,
        max_age=timedelta(minutes=15),
    )
    unknown = validate_catalog_price_stock(
        item(quality_state="UNKNOWN_OUTCOME"),
        now=NOW,
    )

    assert stale.freshness == "stale"
    assert stale.quality_state == "STALE"
    assert unknown.quality_state == "UNKNOWN_OUTCOME"
    assert unknown.price_state == "UNKNOWN_OUTCOME"
    assert unknown.stock_state == "UNKNOWN_OUTCOME"


def test_builder_creates_deterministic_shadow_with_rollback_and_closed_controls():
    source = item()
    patch = {"price": "110.00", "currency_code": "RUB"}
    first = build_price_stock_shadow(
        source,
        scope=SCOPE,
        before_state_hash="a" * 64,
        economic_guard=guard(),
        requested_patch=patch,
        now=NOW,
    )
    replay = build_price_stock_shadow(
        source,
        scope=SCOPE,
        before_state_hash="a" * 64,
        economic_guard=guard(),
        requested_patch=patch,
        now=NOW + timedelta(minutes=1),
    )

    assert first.status == "shadow_ready"
    assert first.patch == {"price": "110", "currency_code": "RUB"}
    assert first.rollback_patch == {"price": "100", "currency_code": "RUB"}
    assert first.rollback_ref
    assert first.idempotency_key == replay.idempotency_key
    assert first.fingerprint == replay.fingerprint
    assert first.external_write_allowed is False
    assert first.permit_issued is False
    assert first.approval_created is False
    assert first.readback_required is True
    assert first.readback_observed is False
    assert first.execution_eligible is False
    assert first.model_dump()["lineage_refs"][0]["id"] == "evd-1"


def test_builder_blocks_before_hash_mismatch_and_missing_rollback_state():
    mismatch = build_price_stock_shadow(
        item(),
        scope=SCOPE,
        before_state_hash="c" * 64,
        economic_guard=guard(),
        requested_patch={"price": "110"},
        now=NOW,
    )
    missing_stock_rollback = build_price_stock_shadow(
        item(stocks=[]),
        scope=SCOPE,
        before_state_hash="a" * 64,
        economic_guard=guard(),
        requested_patch={"stock": {"warehouse_ref": "warehouse-1", "present": 2}},
        now=NOW,
    )

    assert mismatch.status == "blocked"
    assert "before_state_hash_mismatch" in mismatch.blockers
    assert missing_stock_rollback.status == "blocked"
    assert "rollback_stock_state_missing" in missing_stock_rollback.blockers
    assert missing_stock_rollback.rollback_patch is None


def test_economic_guard_block_and_experiment_contamination_propagate():
    blocked_guard = guard(cash="1")
    contaminated = {
        "experiments": [
            {
                "id": "price-a",
                "population": ["sku-1"],
                "treatment": "a",
                "start_at": "2026-09-01T00:00:00Z",
                "end_at": "2026-09-10T00:00:00Z",
            },
            {
                "id": "stock-b",
                "population": ["sku-1"],
                "treatment": "b",
                "start_at": "2026-09-05T00:00:00Z",
                "end_at": "2026-09-12T00:00:00Z",
            },
        ]
    }
    result = build_price_stock_shadow(
        item(),
        scope=SCOPE,
        before_state_hash="a" * 64,
        economic_guard=blocked_guard,
        experiment_context=contaminated,
        requested_patch={"price": "110"},
        now=NOW,
    )

    assert result.status == "blocked"
    assert "economic_guard_blocked" in result.blockers
    assert "economic_guard:cash_below_floor" in result.blockers
    assert "experiment_blocked" in result.blockers
    assert "experiment:population_exposure_overlap" in result.blockers
    assert result.experiment["status"] == "blocked"


def test_direct_experiment_context_requires_review_evidence_and_stop_rule():
    result = build_price_stock_shadow(
        item(),
        scope=SCOPE,
        before_state_hash="a" * 64,
        economic_guard=guard(),
        experiment_context={
            "experiment_id": "price-a",
            "review_eligible": False,
            "causal_evidence": [],
            "stop_rule": None,
        },
        requested_patch={"price": "110"},
        now=NOW,
    )

    assert result.status == "blocked"
    assert result.experiment["status"] == "blocked"
    assert "experiment:experiment_causal_evidence_missing" in result.blockers
    assert "experiment:experiment_stop_rule_missing" in result.blockers


def test_noop_patch_and_idempotency_conflict_are_fail_closed():
    no_op = build_price_stock_shadow(
        item(),
        scope=SCOPE,
        before_state_hash="a" * 64,
        economic_guard=guard(),
        requested_patch={"price": "100.00"},
        now=NOW,
    )
    changed = build_price_stock_shadow(
        item(),
        scope=SCOPE,
        before_state_hash="a" * 64,
        economic_guard=guard(),
        requested_patch={"price": "101.00"},
        now=NOW,
    )

    assert no_op.status == "blocked"
    assert "no_effective_change" in no_op.blockers
    assert no_op.idempotency_key != changed.idempotency_key
    assert check_shadow_idempotency(no_op, no_op) is True
    with pytest.raises(ValueError, match="idempotency conflict"):
        assert_shadow_idempotent(no_op, changed)


def test_unknown_result_and_missing_guard_cannot_be_upgraded_by_a_valid_patch():
    result = build_price_stock_shadow(
        item(quality_state="UNKNOWN_OUTCOME"),
        scope=SCOPE,
        before_state_hash="a" * 64,
        economic_guard=None,
        requested_patch={"price": "110"},
        now=NOW,
    )

    assert result.status == "blocked"
    assert result.quality.quality_state == "UNKNOWN_OUTCOME"
    assert "economic_guard_missing" in result.blockers
    assert result.external_write_allowed is False
