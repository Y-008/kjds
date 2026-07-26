from types import SimpleNamespace

import pytest

from apps.control_plane.operating_analytics import OperatingAnalyticsService


class FakeReadiness:
    def report(self):
        requirements = [
            {
                "id": "SKU-000",
                "title": "需求",
                "ready": False,
                "current": 0,
                "target": 1,
                "next_action": "补需求报告",
            },
            {
                "id": "SKU-001",
                "title": "候选",
                "ready": False,
                "current": 1,
                "target": 3,
                "next_action": "补两个候选",
            },
            {
                "id": "SKU-002",
                "title": "Passport",
                "ready": False,
                "current": 0,
                "target": 3,
                "next_action": "补 Passport",
            },
            {
                "id": "SKU-003",
                "title": "供应链",
                "ready": False,
                "current": 1,
                "target": 3,
                "next_action": "补报价和 CM3",
            },
            {
                "id": "OZN-001",
                "title": "账户",
                "ready": False,
                "current": 0,
                "target": 1,
                "next_action": "补账户证据",
            },
            {
                "id": "OZN-002",
                "title": "Ozon 正式事实",
                "ready": False,
                "current": 1,
                "target": 5,
                "next_action": "补订单、费用、退货和结算",
            },
            {
                "id": "FIN-001",
                "title": "财务",
                "ready": False,
                "current": 1,
                "target": 2,
                "next_action": "补 FX",
            },
        ]
        return {
            "status": "needs_input",
            "requirements": requirements,
            "products": [
                {
                    "product": {
                        "id": "prd-1",
                        "sku": "ozon:store-1:offer-1",
                        "name": "Test product",
                    },
                    "passports_ready": False,
                    "supplier_count": 1,
                    "complete_profit_scenario_count": 0,
                }
            ],
            "exception_workspace": {
                "blocked_count": 7,
                "items": [
                    {"next_action": item["next_action"]}
                    for item in requirements
                ],
            },
        }


class FakeWorkbench:
    def snapshot(self, *, limit):
        assert limit == 100
        return {
            "work_items": [
                {
                    "id": "gate_requirement:SKU-000",
                    "title": "需求证据",
                    "next_action": "补需求报告",
                    "source_id": "SKU-000",
                    "item_type": "gate_blocker",
                }
            ]
        }


class FakeCatalog:
    def latest_items(self, *, store_ref, limit):
        assert store_ref == "store-1"
        assert limit == 100
        return [
            {
                "offer_id": "offer-1",
                "marketplace_sku": "sku-1",
                "canonical_product_id": "prd-1",
                "name": "Test product",
                "currency_code": "RUB",
                "prices": {
                    "price": "2291.00",
                    "min_price": "1900.00",
                    "old_price": "2600.00",
                },
                "available_stock": 9,
                "statuses": {
                    "statuses": {
                        "status": "price_sent",
                        "status_name": "Продается",
                        "moderate_status": "approved",
                    }
                },
                "observed_at": "2026-07-25T01:00:00+00:00",
                "source_evidence_id": "evd-catalog",
                "item_hash": "item-hash",
                "image_references": ["https://example.test/image-1.jpg"],
                "video_references": ["https://example.test/video-1.mp4"],
                "document_references": [],
                "media_rights_status": "unverified_external_reference",
            }
        ]


class FakeGrowth:
    def latest_observations(self, *, limit):
        assert limit == 500
        return [
            {
                "marketplace_sku": "sku-1",
                "content_score": "87",
                "rating": "4.8",
                "review_count": 12,
                "orders_14d": 4,
                "conversion_rate": "0.041",
                "competitor_prices_rub": ["2100", "2300", "2500"],
                "observed_at": "2026-07-26T01:00:00+00:00",
                "evidence_ids": ["evd-growth"],
            }
        ]


class FakeRfq:
    def list(self, *, limit):
        assert limit == 500
        return [{"evidence": SimpleNamespace(id="evd-rfq")}]


class FakeDispatch:
    def list(self, *, limit):
        assert limit == 500
        return [
            {
                "evidence": SimpleNamespace(id="evd-dispatch"),
                "status": "accepted",
            }
        ]


class FakeProcurement:
    def list_orders(self, *, limit):
        assert limit == 500
        return [{"id": "sample-1"}]


class FakeExecutionPlans:
    def list(self):
        return [
            {
                "id": "plan-1",
                "ready_for_executor": True,
                "evidence_ids": ["evd-plan"],
            }
        ]


class FakePostExecution:
    def list_windows(self):
        return [{"id": "window-1"}]


class FakeFinance:
    def list_entries(self):
        return [SimpleNamespace(id="fin-1")]


class FakeProductMedia:
    def readiness(self, product_id):
        assert product_id == "prd-1"
        return {
            "approved_role_count": 2,
            "required_roles": [
                "front_main",
                "back",
                "side",
                "detail",
                "accessories",
                "packaging",
                "scale_reference",
            ],
        }


def build_service():
    return OperatingAnalyticsService(
        readiness=FakeReadiness(),
        operating_workbench=FakeWorkbench(),
        marketplace_catalog=FakeCatalog(),
        marketplace_growth=FakeGrowth(),
        supplier_rfq=FakeRfq(),
        supplier_rfq_dispatch=FakeDispatch(),
        procurement=FakeProcurement(),
        execution_plans=FakeExecutionPlans(),
        post_execution=FakePostExecution(),
        finance=FakeFinance(),
        product_media=FakeProductMedia(),
    )


def test_snapshot_exposes_traceable_chart_data_without_write_authority():
    snapshot = build_service().snapshot(store_ref="store-1")

    assert snapshot["contract_id"] == "kjds-operating-flow-analytics-v1"
    assert snapshot["source_as_of"] == "2026-07-26T01:00:00+00:00"
    assert snapshot["summary"] == {
        "catalog_items": 1,
        "bound_listings": 1,
        "available_stock": 9,
        "external_image_references": 1,
        "external_video_references": 1,
        "gate_blockers": 7,
        "growth_snapshot_skus": 1,
        "rfq_packages": 1,
        "verified_dispatch_proofs": 1,
        "formal_finance_entries": 1,
        "ready_execution_plans": 1,
    }
    assert snapshot["recommended_playbook"]["id"] == "existing_listing_refinement"
    assert snapshot["focal_listing"]["source_evidence_id"] == "evd-catalog"
    assert snapshot["focal_listing"]["media_rights_status"] == "unverified_external_reference"
    assert snapshot["focal_listing"]["growth_observation"]["competitor_count"] == 3
    assert [item["step"] for item in snapshot["stages"]] == [
        "01",
        "02",
        "03",
        "04",
        "05",
        "06",
        "07",
        "08",
        "09",
        "10",
    ]
    assert snapshot["stages"][4]["source_ids"] == [
        "SKU-003",
        "evd-rfq",
        "evd-dispatch",
    ]
    assert snapshot["coverage"][4]["percent"] == 29
    assert snapshot["guardrails"]["synthetic_business_data_allowed"] is False
    assert snapshot["guardrails"]["platform_write_allowed"] is False
    assert len(snapshot["snapshot_sha256"]) == 64


def test_snapshot_is_stable_and_percentages_never_exceed_one_hundred():
    first = build_service().snapshot(store_ref="store-1")
    second = build_service().snapshot(store_ref="store-1")

    assert first == second
    assert all(0 <= item["percent"] <= 100 for item in first["coverage"])
    assert all(
        0 <= item["progress_percent"] <= 100 for item in first["stages"]
    )


def test_store_scope_is_required_and_bounded():
    with pytest.raises(ValueError, match="1 to 160"):
        build_service().snapshot(store_ref=" ")

    with pytest.raises(ValueError, match="1 to 160"):
        build_service().snapshot(store_ref="x" * 161)
