from copy import deepcopy

import pytest

from apps.control_plane.evidenceops_copilot import EvidenceOpsCopilot


class FakeOperatingAnalytics:
    def __init__(self) -> None:
        self.store_refs: list[str] = []

    def snapshot(self, *, store_ref: str):
        self.store_refs.append(store_ref)
        return {
            "snapshot_sha256": "a" * 64,
            "source_as_of": "2026-07-26T04:00:00+00:00",
            "summary": {
                "catalog_items": 1,
                "available_stock": 9,
                "formal_finance_entries": 0,
                "ready_execution_plans": 0,
            },
            "focal_listing": {
                "source_evidence_id": "evd-catalog-1",
            },
            "stages": [
                {
                    "id": "catalog",
                    "step": "01",
                    "label": "Ozon 店铺同步",
                    "workspace": "growth",
                    "status": "verified",
                    "current": 1,
                    "target": 1,
                    "progress_percent": 100,
                    "next_action": "核对目录",
                    "source_ids": ["evd-catalog-1"],
                    "facts": ["1 个目录商品"],
                },
                {
                    "id": "sku-003",
                    "step": "05",
                    "label": "三报价与供应链",
                    "workspace": "sourcing",
                    "status": "blocked",
                    "current": 0,
                    "target": 3,
                    "progress_percent": 0,
                    "next_action": "补齐三家真实报价",
                    "source_ids": ["SKU-003"],
                    "facts": [],
                },
                {
                    "id": "content",
                    "step": "06",
                    "label": "内容与俄语 Listing",
                    "workspace": "products",
                    "status": "no_data",
                    "current": 0,
                    "target": 7,
                    "progress_percent": 0,
                    "next_action": "补齐有权原图",
                    "source_ids": [],
                    "facts": ["外部媒体均未核权"],
                },
                {
                    "id": "growth",
                    "step": "07",
                    "label": "价格 / 内容 / 广告实验",
                    "workspace": "growth",
                    "status": "no_data",
                    "current": 0,
                    "target": 1,
                    "progress_percent": 0,
                    "next_action": "保存有证据增长快照",
                    "source_ids": [],
                    "facts": ["自动投放关闭"],
                },
                {
                    "id": "fin-001",
                    "step": "10",
                    "label": "利润 / FX / 对账",
                    "workspace": "finance",
                    "status": "blocked",
                    "current": 0,
                    "target": 1,
                    "progress_percent": 0,
                    "next_action": "导入财务原件",
                    "source_ids": ["FIN-001"],
                    "facts": [],
                },
            ],
            "coverage": [
                {
                    "id": "finance_truth",
                    "label": "财务与结算",
                    "current": 0,
                    "target": 2,
                    "percent": 0,
                    "unit": "五类事实 + FX",
                },
                {
                    "id": "official_catalog",
                    "label": "店铺目录",
                    "current": 1,
                    "target": 1,
                    "percent": 100,
                    "unit": "Ozon 目录原件",
                },
            ],
            "data_gaps": ["导入正式结算和银行原件"],
        }


class FakeOperatingWorkbench:
    def __init__(self) -> None:
        self.limits: list[int] = []

    def snapshot(self, *, limit: int):
        self.limits.append(limit)
        return {
            "snapshot_sha256": "b" * 64,
            "work_items": [
                {
                    "source_id": "SKU-003",
                    "agent_id": "product_sourcing",
                    "agent_name": "Product / Sourcing Agent",
                    "next_action": "独立核验三份供应商报价",
                    "evidence_ids": ["evd-quote-lead-1"],
                },
                {
                    "source_id": "FIN-001",
                    "agent_id": "finance_cash",
                    "agent_name": "Finance & Cash Agent",
                    "next_action": "录入结算、银行与 FX 原件",
                    "evidence_ids": [],
                },
            ],
            "agents": [
                {
                    "agent_id": "digital_ceo",
                    "name": "Digital CEO",
                    "status": "waiting_for_upstream",
                    "work_item_count": 0,
                    "current_focus": "等待有证据的上游输入",
                    "automatic_execution": False,
                },
                {
                    "agent_id": "product_sourcing",
                    "name": "Product / Sourcing Agent",
                    "status": "needs_attention",
                    "work_item_count": 1,
                    "current_focus": "三报价",
                    "automatic_execution": False,
                },
                {
                    "agent_id": "finance_cash",
                    "name": "Finance & Cash Agent",
                    "status": "needs_attention",
                    "work_item_count": 1,
                    "current_focus": "财务原件",
                    "automatic_execution": False,
                },
            ],
        }


def build_copilot():
    analytics = FakeOperatingAnalytics()
    workbench = FakeOperatingWorkbench()
    return (
        EvidenceOpsCopilot(
            operating_analytics=analytics,
            operating_workbench=workbench,
        ),
        analytics,
        workbench,
    )


def test_plan_compiles_objective_into_evidence_backed_missions() -> None:
    copilot, analytics, workbench = build_copilot()

    plan = copilot.plan(
        objective="  提升利润并完成结算回款  ",
        store_ref="ozon-primary",
    )

    assert plan["contract_id"] == "kjds-evidenceops-copilot-plan-v1"
    assert plan["product"]["version"] == "0.54.0"
    assert plan["objective"] == {
        "text": "提升利润并完成结算回款",
        "type": "user_intent",
        "is_business_fact": False,
        "is_approval": False,
        "is_execution_permit": False,
    }
    assert plan["intent"]["id"] == "profit_cash"
    assert plan["intent"]["inference_only"] is True
    assert plan["missions"][0]["stage_id"] == "sku-003"
    assert plan["missions"][0]["agent"]["id"] == "product_sourcing"
    assert plan["missions"][0]["source_ids"] == [
        "SKU-003",
        "evd-quote-lead-1",
    ]
    assert all(item["human_required"] is True for item in plan["missions"])
    assert all(item["automatic_execution"] is False for item in plan["missions"])
    assert all(item["platform_write_allowed"] is False for item in plan["missions"])
    assert plan["truth_ledger"]["synthetic_business_data_allowed"] is False
    assert plan["control_envelope"]["external_write_allowed"] is False
    assert len(plan["control_envelope"]["forbidden_actions"]) == 8
    assert len(plan["plan_sha256"]) == 64
    assert analytics.store_refs == ["ozon-primary"]
    assert workbench.limits == [100]


def test_goal_changes_intent_and_priority_without_changing_facts() -> None:
    copilot, _, _ = build_copilot()

    profit = copilot.plan(objective="提升利润和现金回款")
    content = copilot.plan(objective="补齐俄语 Listing 图片和视频素材")

    assert profit["intent"]["id"] == "profit_cash"
    assert content["intent"]["id"] == "content_listing"
    assert content["missions"][0]["stage_id"] == "content"
    assert (
        profit["truth_ledger"]["verified_facts"]
        == content["truth_ledger"]["verified_facts"]
    )
    assert profit["plan_sha256"] != content["plan_sha256"]


def test_identical_sources_and_objective_produce_a_stable_plan() -> None:
    first, _, _ = build_copilot()
    second, _, _ = build_copilot()

    first_plan = first.plan(objective="完成三家供应商报价")
    second_plan = second.plan(objective="完成三家供应商报价")

    assert first_plan == second_plan
    assert deepcopy(first_plan)["plan_sha256"] == second_plan["plan_sha256"]


def test_unknowns_remain_explicit_and_are_never_synthetically_filled() -> None:
    copilot, _, _ = build_copilot()

    plan = copilot.plan(objective="完成利润对账")

    assert plan["truth_ledger"]["unknowns"]
    assert all(
        item["synthetic_fill_allowed"] is False
        for item in plan["truth_ledger"]["unknowns"]
    )
    assert any(
        "unknown" in item["reason"]
        for item in plan["truth_ledger"]["unknowns"]
    )


@pytest.mark.parametrize(
    ("objective", "store_ref"),
    [
        ("", "ozon-primary"),
        ("ab", "ozon-primary"),
        ("x" * 1001, "ozon-primary"),
        ("完成利润对账", ""),
        ("完成利润对账", "x" * 161),
    ],
)
def test_plan_rejects_unbounded_input(objective: str, store_ref: str) -> None:
    copilot, _, _ = build_copilot()

    with pytest.raises(ValueError, match="EvidenceOps"):
        copilot.plan(objective=objective, store_ref=store_ref)
