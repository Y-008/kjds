from apps.control_plane.source_acquisition import SkuWorkbenchService
from apps.control_plane.source_connector_adapters import SOURCE_LISTING_CONTRACT


class FakeRepository:
    def list_products(self):
        return []

    def events_after(self, sequence):
        return []

    def list_approvals(self):
        return []


class FakeResearchInbox:
    def list(self, *, candidate_ref, limit):
        assert candidate_ref == "candidate://compression-main"
        return [
            {
                "evidence": {
                    "id": "evd-source-1",
                    "sha256": "a" * 64,
                    "effective_at": "2026-07-25T00:00:00+00:00",
                    "metadata": {
                        "provider": "opencli-1688",
                        "provider_record_id": "source-listing-snapshot-v1:900000000001",
                        "source_url": "https://detail.1688.com/offer/900000000001.html",
                        "captured_at": "2026-07-25T00:01:00+00:00",
                        "license_status": "requires_review",
                        "review_status": "pending_authority_review",
                        "raw_fields": {
                            "contract_id": SOURCE_LISTING_CONTRACT,
                            "listing_id": "900000000001",
                            "title": "脱敏压缩收纳候选样品",
                            "fact_status": "research_signal",
                        },
                    },
                },
                "integrity_valid": True,
                "decision_use": "auxiliary_only_pending_independent_authority_review",
            }
        ]


class FakeReadiness:
    def report(self):
        return {
            "products": [],
            "decision_scope_readiness": {
                "real_execution": {
                    "ready": False,
                }
            },
        }


class FakeSourcingStore:
    def list_offers(self, limit):
        return []

    def list_scenarios(self, limit):
        return []

    def list_listing_drafts(self, limit):
        return []


class FakeProcurement:
    def list_orders(self, limit):
        return []


def test_sku_workbench_keeps_unverified_listing_as_research_and_unknowns():
    service = SkuWorkbenchService(
        repository=FakeRepository(),
        research_inbox=FakeResearchInbox(),
        readiness=FakeReadiness(),
        sourcing_store=FakeSourcingStore(),
        procurement=FakeProcurement(),
    )

    result = service.snapshot("candidate://compression-main")

    assert result["contract_id"] == "kjds-sku-workbench-v1"
    assert result["product"] is None
    assert len(result["research"]["source_listings"]) == 1
    assert result["research"]["source_listings"][0]["decision_use"].startswith("auxiliary_only")
    assert result["formal_offers"] == []
    assert {
        "candidate_product",
        "three_comparable_formal_quotes",
        "ozon_ru_full_cost_scenario",
        "ozon_28_day_real_execution_demand_evidence",
        "approved_product_compliance_quality_passports",
    } <= set(result["unknowns"])
    assert result["guardrails"]["automatic_supplier_contact"] is False
    assert result["guardrails"]["automatic_payment"] is False
