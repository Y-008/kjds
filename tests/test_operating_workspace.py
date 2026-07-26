from __future__ import annotations

import pytest

from apps.control_plane.cross_border_capability_atlas import (
    CrossBorderCapabilityAtlas,
)
from apps.control_plane.operating_workspace import (
    OperatingWorkspaceError,
    OperatingWorkspaceService,
)


class StubAnalytics:
    def snapshot(self, *, store_ref: str) -> dict:
        stages = [
            {
                "id": "catalog",
                "step": "01",
                "label": "Ozon 店铺同步",
                "workspace": "growth",
                "status": "verified",
                "current": 3,
                "target": 1,
                "progress_percent": 100,
                "facts": ["3 个目录商品"],
                "source_ids": ["evidence:catalog"],
                "next_action": "核对目录商品",
            },
            {
                "id": "sku-000",
                "step": "02",
                "label": "需求与市场证据",
                "workspace": "research",
                "status": "blocked",
                "current": 0,
                "target": 1,
                "progress_percent": 0,
                "facts": [],
                "source_ids": [],
                "next_action": "补齐需求 Evidence",
            },
            {
                "id": "sku-001",
                "step": "03",
                "label": "候选与商品立项",
                "workspace": "research",
                "status": "no_data",
                "current": 0,
                "target": 3,
                "progress_percent": 0,
                "facts": [],
                "source_ids": [],
                "next_action": "确认三个真实候选",
            },
            {
                "id": "sku-002",
                "step": "04",
                "label": "商品 / 合规 / 质量",
                "workspace": "products",
                "status": "in_progress",
                "current": 1,
                "target": 3,
                "progress_percent": 33,
                "facts": ["1 个 Product"],
                "source_ids": ["product:1"],
                "next_action": "补齐 Passport",
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
                "facts": ["0 份已核验报价"],
                "source_ids": [],
                "next_action": "取得三份权威报价",
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
                "facts": ["外部媒体均未核权"],
                "source_ids": [],
                "next_action": "补齐有权内容",
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
                "facts": ["自动改价与自动投放关闭"],
                "source_ids": [],
                "next_action": "保存增长快照",
            },
            {
                "id": "execution",
                "step": "08",
                "label": "审批与受控执行",
                "workspace": "governance",
                "status": "blocked",
                "current": 0,
                "target": 1,
                "progress_percent": 0,
                "facts": ["0 个执行计划"],
                "source_ids": [],
                "next_action": "等待批准与 Permit",
            },
            {
                "id": "ozn-002",
                "step": "09",
                "label": "订单 / 退货 / 结算",
                "workspace": "finance",
                "status": "no_data",
                "current": 0,
                "target": 1,
                "progress_percent": 0,
                "facts": [],
                "source_ids": [],
                "next_action": "补齐订单与结算数据",
            },
            {
                "id": "fin-001",
                "step": "10",
                "label": "利润 / FX / 对账",
                "workspace": "finance",
                "status": "in_progress",
                "current": 1,
                "target": 3,
                "progress_percent": 33,
                "facts": ["1 条正式财务分录"],
                "source_ids": ["finance:1"],
                "next_action": "完成费用与 FX 对账",
            },
        ]
        return {
            "status": "blocked",
            "store_ref": store_ref,
            "source_as_of": "2026-07-26T00:00:00Z",
            "summary": {"catalog_items": 3, "formal_finance_entries": 1},
            "focal_listing": {"offer_id": "offer-1", "name": "真实商品"},
            "stages": stages,
            "priority_items": [{"id": "SKU-000", "next_action": "补证"}],
            "data_gaps": ["缺少真实订单"],
            "snapshot_sha256": "a" * 64,
        }


@pytest.fixture
def service() -> OperatingWorkspaceService:
    return OperatingWorkspaceService(
        capability_atlas=CrossBorderCapabilityAtlas(),
        operating_analytics=StubAnalytics(),
    )


def test_operating_workspace_resolves_point_line_and_surface(service):
    point = service.snapshot(
        kind="points", item_id="market_signal_inbox", store_ref="ozon-primary"
    )
    line = service.snapshot(
        kind="lines", item_id="trend_to_opportunity", store_ref="ozon-primary"
    )
    surface = service.snapshot(
        kind="surfaces",
        item_id="store_operating_matrix",
        store_ref="ozon-primary",
    )

    assert point["context"]["type"] == "point"
    assert point["release_version"] == "0.57.1"
    assert point["registry_version"] == "0.57.1"
    assert point["stages"][0]["runtime_status"] == "blocked"
    assert point["stages"][0]["evidence_ids"] == []
    assert point["actions"][0]["href"] == "/#research"
    assert line["context"]["type"] == "line"
    assert len(line["stages"]) == 6
    assert line["context"]["entry_gate"]
    assert line["context"]["human_takeover"]
    assert surface["context"]["type"] == "surface"
    assert surface["context"]["truth_owner"]
    assert surface["navigation"]["related_lines"]
    assert all(
        snapshot["control_envelope"]["external_write_allowed"] is False
        for snapshot in (point, line, surface)
    )


def test_all_fourteen_business_lines_have_stages_actions_and_stable_hash(service):
    atlas = CrossBorderCapabilityAtlas().snapshot()
    lines = atlas["operating_graph"]["value_streams"]

    snapshots = [
        service.snapshot(
            kind="lines", item_id=line["id"], store_ref="ozon-primary"
        )
        for line in lines
    ]

    assert len(snapshots) == 14
    assert all(item["stages"] for item in snapshots)
    assert all(item["actions"] for item in snapshots)
    assert all(item["context"]["exceptions"] for item in snapshots)
    assert all(item["context"]["human_takeover"] for item in snapshots)
    assert all(len(item["workspace_sha256"]) == 64 for item in snapshots)
    repeated = service.snapshot(
        kind="lines", item_id=lines[0]["id"], store_ref="ozon-primary"
    )
    assert repeated["workspace_sha256"] == snapshots[0]["workspace_sha256"]


def test_contract_status_never_promotes_missing_runtime_fact(service):
    snapshot = service.snapshot(
        kind="points",
        item_id="inspiration_signal_capture",
        store_ref="ozon-primary",
    )

    assert snapshot["stages"][0]["contract_status"] == "implemented"
    assert snapshot["stages"][0]["runtime_status"] == "contract_only"
    assert snapshot["stages"][0]["facts"] == []
    assert snapshot["domain_signals"]


@pytest.mark.parametrize(
    ("kind", "item_id"),
    [
        ("unknown", "trend_to_opportunity"),
        ("lines", "missing"),
        ("points", "../unsafe"),
    ],
)
def test_operating_workspace_fails_closed_for_unknown_or_unsafe_route(
    service, kind, item_id
):
    with pytest.raises(OperatingWorkspaceError):
        service.snapshot(kind=kind, item_id=item_id, store_ref="ozon-primary")
