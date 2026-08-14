from copy import deepcopy
from decimal import Decimal

import pytest

from apps.control_plane.operating_workbench import OperatingWorkbenchService
from apps.control_plane.security import Principal


class FakeReadiness:
    def report(self):
        return {
            "status": "needs_input",
            "candidate_portfolio": {
                "candidate_count": 1,
                "selection_ready_count": 0,
                "rows": [{"product": {"id": "prd-1", "sku": "RU-001"}}],
                "advisory_only": True,
                "automatic_product_selection": False,
                "automatic_procurement": False,
                "automatic_pricing": False,
                "automatic_listing": False,
            },
            "exception_workspace": {
                "items": [
                    {
                        "queue_key": "gate_requirement:SKU-003",
                        "source_type": "gate_requirement",
                        "source_id": "SKU-003",
                        "gate": "G1",
                        "title": "每 SKU 三家报价与正 CM3 场景",
                        "status": "blocked",
                        "attention": "current_gate",
                        "owner_role": "商品/供应链",
                        "current": 0,
                        "target": 3,
                        "next_action": "补齐真实报价和成本证据",
                        "details": {},
                    }
                ]
            },
        }


class FakeOperationsQueue:
    def queue(self):
        return [
            {
                "queue_key": "incident:inc-1",
                "item_type": "incident",
                "item_id": "inc-1",
                "title": "核对平台状态",
                "status": "open",
                "priority": "critical",
                "due_at": "2026-07-25T00:15:00+00:00",
                "overdue": True,
                "escalation_level": 2,
                "next_action": "人工核对远端状态",
            }
        ]


class FakeRecommendation:
    def to_dict(self):
        return {
            "id": "rec-1",
            "product_id": "prd-1",
            "agent": "Market / Content Agent",
            "action": "补充竞品证据",
            "rationale": "当前来源不足",
            "evidence": ["evd-1"],
            "expected_cm3_delta": Decimal("12.50"),
            "risk": "medium",
            "status": "observing",
            "shadow_mode": True,
            "created_at": "2026-07-25T00:00:00+00:00",
        }


class FakeAutomation:
    def list_recommendations(self):
        return [FakeRecommendation()]


def build_service():
    return OperatingWorkbenchService(
        readiness=FakeReadiness(),
        operations_queue=FakeOperationsQueue(),
        automation=FakeAutomation(),
    )


def test_snapshot_unifies_existing_sources_without_granting_execution():
    snapshot = build_service().snapshot()

    assert snapshot["contract_id"] == "kjds-operating-workbench-briefing-v1"
    assert snapshot["summary"] == {
        "gate_blockers": 1,
        "runtime_items": 1,
        "recommendations": 1,
        "visible_items": 3,
        "candidate_count": 1,
        "selection_ready_count": 0,
    }
    assert [item["item_type"] for item in snapshot["work_items"]] == [
        "runtime_operation",
        "gate_blocker",
        "recommendation",
    ]
    assert all(item["automatic_execution"] is False for item in snapshot["work_items"])
    assert all(item["platform_write_allowed"] is False for item in snapshot["work_items"])
    assert snapshot["guardrails"]["third_party_fact_promotion_allowed"] is False
    assert len(snapshot["snapshot_sha256"]) == 64


def test_gate_blocker_does_not_invent_sla_or_occurrence_time():
    blocker = next(
        item for item in build_service().snapshot()["work_items"]
        if item["item_type"] == "gate_blocker"
    )

    assert blocker["agent_id"] == "product_sourcing"
    assert blocker["due_at"] is None
    assert blocker["overdue"] is None
    assert blocker["escalation_level"] is None
    assert blocker["progress"] == {"current": 0, "target": 3}


def test_snapshot_is_stable_for_identical_source_projection():
    first = build_service().snapshot()
    second = build_service().snapshot()

    assert first == second
    assert deepcopy(first)["snapshot_sha256"] == second["snapshot_sha256"]


def test_limit_is_bounded_and_does_not_change_total_source_counts():
    snapshot = build_service().snapshot(limit=1)

    assert len(snapshot["work_items"]) == 1
    assert snapshot["summary"]["visible_items"] == 1
    assert snapshot["summary"]["gate_blockers"] == 1
    assert snapshot["summary"]["runtime_items"] == 1
    assert snapshot["summary"]["recommendations"] == 1

    with pytest.raises(ValueError, match="between 1 and 100"):
        build_service().snapshot(limit=0)


def test_scoped_snapshot_reads_only_scoped_queue():
    class MustNotRead:
        def report(self):
            raise AssertionError("global readiness must not be read")

        def list_recommendations(self):
            raise AssertionError(
                "global recommendations must not be read"
            )

    class ScopedQueue:
        def projection(self, **values):
            assert values["store_ref"] == "store-a"
            return {
                "status": "no_data",
                "scope": {
                    "tenant_ref": "tenant-a",
                    "entity_ref": None,
                    "store_ref": "store-a",
                    "scope_authority_sha256": None,
                },
                "as_of": "2026-07-28T01:00:00+00:00",
                "items": [],
                "source_gaps": ["entity_scope_authority_missing"],
                "excluded_sources": ["legacy_unscoped_incidents"],
            }

    service = OperatingWorkbenchService(
        readiness=MustNotRead(),
        operations_queue=ScopedQueue(),
        automation=MustNotRead(),
    )
    result = service.snapshot(
        principal=Principal(
            actor_id="operator-a",
            roles=frozenset({"operator"}),
            tenant_ref="tenant-a",
            store_refs=frozenset({"store-a"}),
        ),
        entity_scope={
            "status": "no_data",
            "entity_ref": None,
            "authority_sha256": None,
        },
        store_ref="store-a",
        as_of="2026-07-28T01:00:00+00:00",
    )

    assert result["status"] == "no_data"
    assert result["work_items"] == []
    assert result["summary"]["gate_blockers"] == 0
    assert "legacy_global_gate_readiness" in result["excluded_sources"]
    assert result["guardrails"]["platform_write_allowed"] is False
