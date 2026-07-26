from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from apps.control_plane.operating_intelligence import (
    METRIC_REGISTRY,
    OperatingIntelligenceService,
)
from apps.control_plane.sql_repository import Base


class FakeProfitLedger:
    def __init__(self) -> None:
        self.read_count = 0

    def snapshot(self, **_) -> dict:
        self.read_count += 1
        return {
            "coverage_ratio": "0.5",
            "rows": [
                {
                    "gross_revenue": "100",
                    "actual_profit": "-5",
                    "accrual_contribution": "-5",
                    "settlement_contribution": "80",
                    "cash_contribution": "70",
                    "evidence_ids": ["evd-ledger"],
                    "erosion": {
                        "returns": "5",
                        "warehousing": "10",
                        "advertising": "20",
                    },
                }
            ],
        }


class FakeEvidence:
    def __init__(self) -> None:
        self.validated: list[list[str]] = []

    def require_valid(self, evidence_ids) -> None:
        self.validated.append(list(evidence_ids))


def service() -> tuple[OperatingIntelligenceService, FakeProfitLedger, FakeEvidence]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    ledger = FakeProfitLedger()
    evidence = FakeEvidence()
    return (
        OperatingIntelligenceService(
            engine=engine,
            profit_ledger=ledger,
            evidence=evidence,
        ),
        ledger,
        evidence,
    )


def test_registry_is_versioned_server_owned_and_enforces_minimum_samples():
    intelligence, _, _ = service()

    payload = intelligence.metrics()

    assert len(payload["metrics"]) == len(METRIC_REGISTRY) == 8
    assert payload["registry_version"] == "operating-metrics/1.0.0"
    assert payload["control_envelope"] == {
        "descriptive_not_causal": True,
        "client_can_change_thresholds": False,
        "external_write_allowed": False,
    }
    returns = next(
        item for item in payload["metrics"] if item["id"] == "return_rate_spike"
    )
    assert returns["minimum_sample"] == 30
    assert returns["data_status"] == "no_data"


def test_scan_deduplicates_inside_cooldown_and_creates_no_business_action():
    intelligence, ledger, _ = service()

    first = intelligence.scan(
        store_ref="ozon-primary",
        actor_id="monitor-1",
        as_of="2026-07-26T08:00:00+00:00",
    )
    second = intelligence.scan(
        store_ref="ozon-primary",
        actor_id="monitor-1",
        as_of="2026-07-26T08:01:00+00:00",
    )

    created = [item for item in first["results"] if item["status"] == "task_created"]
    deduplicated = [
        item for item in second["results"] if item["status"] == "deduplicated"
    ]
    assert created
    assert {item["task_id"] for item in deduplicated} == {
        item["task_id"] for item in created
    }
    assert len(intelligence.tasks()) == len(created)
    assert first["automatic_business_action"] is False
    assert first["external_write_allowed"] is False
    assert ledger.read_count == 2


def test_task_lifecycle_requires_reason_and_evidence_for_resolution():
    intelligence, _, evidence = service()
    scan = intelligence.scan(
        store_ref="ozon-primary",
        actor_id="monitor-1",
        as_of="2026-07-26T08:00:00+00:00",
    )
    task_id = next(
        item["task_id"]
        for item in scan["results"]
        if item["status"] == "task_created"
    )

    intelligence.append_task_event(
        task_id,
        event_type="acknowledge",
        reason="已确认指标与基线",
        evidence_ids=[],
        actor_id="operator-1",
    )
    intelligence.append_task_event(
        task_id,
        event_type="start",
        reason="开始核对订单与结算",
        evidence_ids=[],
        actor_id="operator-1",
    )
    with pytest.raises(ValueError, match="requires Evidence"):
        intelligence.append_task_event(
            task_id,
            event_type="resolve",
            reason="完成核对",
            evidence_ids=[],
            actor_id="operator-1",
        )
    result = intelligence.append_task_event(
        task_id,
        event_type="resolve",
        reason="完成核对并保留凭证",
        evidence_ids=["evd-resolution"],
        actor_id="operator-1",
    )

    events = intelligence.task_events(task_id)
    assert result["task"]["status"] == "resolved"
    assert [event["sequence"] for event in events] == list(
        range(1, len(events) + 1)
    )
    assert events[-1]["event_type"] == "resolve"
    assert evidence.validated[-1] == ["evd-resolution"]
    assert task_id not in {
        item["item_id"]
        for item in intelligence.queue_items(now=datetime.now(UTC))
    }
