from decimal import Decimal
from types import SimpleNamespace

from apps.control_plane.ozon_contracts import OzonRecordType
from apps.control_plane.readiness import GateReadinessService


class FakeCommerce:
    def __init__(self, products, ready=True):
        self.products = products
        self.ready = ready

    def list_products(self):
        return self.products

    def product_readiness(self, product_id):
        product = next(item for item in self.products if item.id == product_id)
        return {
            "product": {"id": product.id, "sku": product.sku, "name": product.name, "status": "candidate"},
            "passports": [],
            "ready_for_validation": self.ready,
        }


class FakeSourcingStore:
    def __init__(self, offers, scenarios):
        self.offers = offers
        self.scenarios = scenarios

    def list_offers(self, limit=5000):
        return self.offers[:limit]

    def list_scenarios(self, limit=5000):
        return self.scenarios[:limit]


class FakeEvidence:
    def __init__(self, requirements):
        self.requirements = requirements

    def target_evidence_ids(self, *, target_type, target_id):
        assert target_type == "gate_requirement"
        return self.requirements.get(target_id, [])

    def require_valid(self, evidence_ids):
        if any(item.startswith("invalid") for item in evidence_ids):
            raise ValueError("invalid")


class FakeFacts:
    def __init__(self, fact_types):
        self.fact_types = fact_types

    def list(self, limit=5000):
        return [SimpleNamespace(fact_type=item) for item in self.fact_types][:limit]


class FakeFinance:
    def __init__(self, ready=True):
        self.ready = ready

    def list_fee_mappings(self, *, provider):
        return [object()] if self.ready and provider == "ozon" else []

    def list_fx_rates(self, *, base_currency):
        return [object()] if self.ready and base_currency == "RUB" else []

    def unknown_fee_entries(self, *, provider):
        return []


def build_report(*, duplicate_supplier=False):
    products = [SimpleNamespace(id=f"prd_{index}", sku=f"SKU-{index}", name=f"Product {index}") for index in range(3)]
    offers = []
    scenarios = []
    for product_index, product in enumerate(products):
        for supplier_index in range(3):
            supplier_ref = "same-supplier" if duplicate_supplier and product_index == 0 else f"supplier-{supplier_index}"
            offer = SimpleNamespace(
                id=f"off_{product_index}_{supplier_index}",
                product_id=product.id,
                supplier_ref=supplier_ref,
            )
            offers.append(offer)
            scenarios.append(SimpleNamespace(offer_id=offer.id, cm3_cny=Decimal("10")))
    service = GateReadinessService(
        commerce=FakeCommerce(products),
        sourcing_store=FakeSourcingStore(offers, scenarios),
        evidence=FakeEvidence({"GOV-001": ["evd_gov"], "OZN-001": ["evd_ozon"]}),
        facts=FakeFacts({item.value for item in OzonRecordType}),
        finance=FakeFinance(),
    )
    return service.report()


def test_gate_report_reaches_review_only_with_complete_evidence_chain():
    report = build_report()
    assert report["status"] == "ready_for_review"
    assert report["g0"] == "ready_for_review"
    assert report["g1"] == "ready_for_review"
    assert all(item["ready_for_g1_review"] for item in report["products"])


def test_gate_report_counts_distinct_suppliers_not_offer_rows():
    report = build_report(duplicate_supplier=True)
    sku_requirement = next(item for item in report["requirements"] if item["id"] == "SKU-003")
    assert report["status"] == "needs_input"
    assert sku_requirement["ready"] is False
    assert report["products"][0]["supplier_count"] == 1
