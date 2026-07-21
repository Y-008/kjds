from decimal import Decimal
from types import SimpleNamespace

from apps.control_plane.ozon_contracts import OzonRecordType
from apps.control_plane.readiness import GateReadinessService


class FakeCommerce:
    def __init__(self, products, ready=True, candidate_handoffs=True):
        self.products = products
        self.ready = ready
        self.repo = SimpleNamespace(
            events_after=lambda _sequence: [
                {
                    "type": "product.candidate_sourcing_workspace_created",
                    "aggregate_id": product.id,
                }
                for product in products
            ]
            if candidate_handoffs
            else []
        )

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
    def __init__(self, requirements, candidate_product_ids, demand_report_id):
        self.requirements = requirements
        self.candidate_product_ids = candidate_product_ids
        self.demand_report_id = demand_report_id

    def target_evidence_ids(self, *, target_type, target_id, relationship=None):
        if target_type == "gate_requirement":
            return self.requirements.get(target_id, [])
        assert target_type == "product"
        if relationship == "candidate_basis":
            return [f"evd_candidate_{target_id}"] if target_id in self.candidate_product_ids else []
        assert relationship == "demand_report_basis"
        return [self.demand_report_id] if target_id in self.candidate_product_ids and self.demand_report_id else []

    def require_valid(self, evidence_ids):
        if any(item.startswith("invalid") for item in evidence_ids):
            raise ValueError("invalid")

    def get(self, evidence_id):
        if evidence_id == "evd_demand":
            return SimpleNamespace(metadata={"source_system": "ozon_data", "report_window_days": 28})
        if evidence_id == "evd_public_sample":
            return SimpleNamespace(metadata={"source_system": "public_sample", "report_window_days": 28})
        if evidence_id == "evd_fixed":
            return SimpleNamespace(metadata={"source_system": "fixed_test_data", "report_window_days": 28})
        raise KeyError(evidence_id)


class FakeDemandReports:
    def __init__(self, evidence_id):
        self.evidence_id = evidence_id

    def status(self):
        accepted = (
            [self.evidence_id]
            if self.evidence_id in {"evd_demand", "evd_fixed"}
            else []
        )
        real_accepted = [self.evidence_id] if self.evidence_id == "evd_demand" else []
        invalid = [self.evidence_id] if self.evidence_id and not accepted else []
        scope_status = {
            "research": {
                "ready": bool(accepted),
                "accepted_report_ids": accepted,
                "blocking_reasons": [] if accepted else ["RESEARCH_EVIDENCE_REQUIRED"],
            },
            "real_execution": {
                "ready": bool(real_accepted),
                "accepted_report_ids": real_accepted,
                "ozon_data_report_ids": real_accepted,
                "independent_official_source_systems": [],
                "blocking_reasons": []
                if real_accepted
                else ["REAL_EXECUTION_DEMAND_EVIDENCE_REQUIRED"],
            },
        }
        return {
            "ready": bool(real_accepted),
            "research_ready": bool(accepted),
            "real_execution_ready": bool(real_accepted),
            "readiness": scope_status,
            "accepted_report_ids": accepted,
            "pending_report_ids": [],
            "rejected_report_ids": [],
            "invalid_report_ids": invalid,
            "source_report_count": 1 if self.evidence_id else 0,
        }

    def require_accepted(self, evidence_id, *, scope="real_execution"):
        assert scope in {"research", "real_execution"}
        if evidence_id == "evd_fixed" and scope == "research":
            return
        if evidence_id != "evd_demand":
            raise ValueError("Demand report is not currently accepted")


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


class FakeGovernance:
    def __init__(self, reviews):
        self.reviews = reviews

    def list(self, *, gate_id):
        assert gate_id == "G0"
        return self.reviews


def build_report(
    *,
    duplicate_supplier=False,
    complete_facts=True,
    finance_ready=True,
    governance=None,
    candidate_handoffs=True,
    demand_evidence="evd_demand",
    cm3_by_product=None,
    scenario_release_validator=None,
):
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
            scenarios.append(
                SimpleNamespace(
                    id=f"scn_{product_index}_{supplier_index}",
                    offer_id=offer.id,
                    cm3_cny=Decimal(str((cm3_by_product or {}).get(product.id, 10))),
                    cm3_rate=Decimal("0.10"),
                    break_even_price_rub=Decimal("1000"),
                    template_id="ozon-ru-full-cost-v1",
                    unknown_costs=[],
                    evidence=[f"evd_{product_index}_{supplier_index}"],
                    cost_complete=True,
                )
            )
    service = GateReadinessService(
        commerce=FakeCommerce(products, candidate_handoffs=candidate_handoffs),
        sourcing_store=FakeSourcingStore(offers, scenarios),
        evidence=FakeEvidence(
            {
                "GOV-001": ["evd_gov"],
                "OZN-001": ["evd_ozon"],
                "SKU-000": [demand_evidence] if demand_evidence else [],
            },
            {product.id for product in products},
            demand_evidence,
        ),
        facts=FakeFacts({item.value for item in OzonRecordType} if complete_facts else set()),
        finance=FakeFinance(ready=finance_ready),
        governance=governance,
        demand_reports=FakeDemandReports(demand_evidence),
        scenario_release_validator=scenario_release_validator,
    )
    return service.report()


def test_gate_report_reaches_review_only_with_complete_evidence_chain():
    report = build_report()
    assert report["status"] == "ready_for_review"
    assert report["g0"] == "ready_for_review"
    assert report["g1"] == "ready_for_review"
    assert all(item["ready_for_g1_review"] for item in report["products"])
    assert report["exception_workspace"]["items"] == []
    assert report["exception_workspace"]["automatic_resolution"] is False


def test_candidate_portfolio_ranks_only_qualified_current_decisions():
    report = build_report(
        cm3_by_product={"prd_0": 20, "prd_1": -1, "prd_2": 30},
    )

    portfolio = report["candidate_portfolio"]
    assert [item["product"]["id"] for item in portfolio["rows"]] == [
        "prd_2",
        "prd_0",
        "prd_1",
    ]
    assert portfolio["selection_ready_count"] == 2
    assert portfolio["rows"][0]["best_scenario"]["supplier_ref"] == "supplier-0"
    assert portfolio["rows"][2]["best_scenario"]["release_ready"] is False
    assert portfolio["automatic_product_selection"] is False
    assert portfolio["automatic_procurement"] is False


def test_gate_report_counts_distinct_suppliers_not_offer_rows():
    report = build_report(duplicate_supplier=True)
    sku_requirement = next(item for item in report["requirements"] if item["id"] == "SKU-003")
    assert report["status"] == "needs_input"
    assert sku_requirement["ready"] is False
    assert report["products"][0]["supplier_count"] == 1


def test_gate_report_fails_closed_when_profit_evidence_no_longer_releases():
    def reject(_scenario):
        raise ValueError("actual authority withdrawn")

    report = build_report(scenario_release_validator=reject)
    sku_requirement = next(item for item in report["requirements"] if item["id"] == "SKU-003")
    assert sku_requirement["ready"] is False
    assert all(item["complete_profit_scenario_count"] == 0 for item in report["products"])
    assert all(item["best_scenario"]["release_ready"] is False for item in report["products"])


def test_g1_sku_review_is_not_blocked_by_g4_finance_inputs():
    report = build_report(complete_facts=False, finance_ready=False)

    assert report["status"] == "ready_for_review"
    assert report["g0"] == "ready_for_review"
    assert report["g1"] == "ready_for_review"
    assert report["g4"] == "blocked"
    assert next(item for item in report["requirements"] if item["id"] == "OZN-002")["gate"] == "G4"
    workspace = report["exception_workspace"]
    assert [item["source_id"] for item in workspace["items"]] == ["FIN-001", "OZN-002"]
    assert workspace["counts_by_gate"] == {"G0": 0, "G1": 0, "G4": 2}
    assert all(item["attention"] == "downstream" for item in workspace["items"])
    assert workspace["platform_write_allowed"] is False


def test_structured_governance_review_replaces_legacy_single_evidence_gate():
    blocked = build_report(governance=FakeGovernance([]))
    assert blocked["g0"] == "blocked"
    assert blocked["status"] == "needs_input"
    approved = build_report(
        governance=FakeGovernance(
            [
                {
                    "id": "gate_1",
                    "status": "decided",
                    "decision": "CONDITIONAL",
                    "evidence_ids": ["evd_gov"],
                }
            ]
        )
    )
    assert approved["g0"] == "ready_for_review"
    gov = next(item for item in approved["requirements"] if item["id"] == "GOV-001")
    assert gov["details"]["approved_gate_reviews"] == ["gate_1"]


def test_historical_products_without_candidate_handoff_do_not_satisfy_sku_001():
    report = build_report(candidate_handoffs=False)

    candidate = next(item for item in report["requirements"] if item["id"] == "SKU-001")
    assert candidate["ready"] is False
    assert candidate["current"] == 0
    assert candidate["details"]["historical_or_unqualified_product_count"] == 3
    assert report["g0"] == "blocked"
    assert report["g1"] == "blocked"
    blocker = next(
        item for item in report["exception_workspace"]["items"] if item["source_id"] == "SKU-001"
    )
    assert blocker["source_type"] == "gate_requirement"
    assert blocker["owner_role"] == "商品"
    assert blocker["current"] == 0
    assert blocker["target"] == 3


def test_public_sample_or_missing_demand_report_does_not_satisfy_sku_000():
    report = build_report(demand_evidence="evd_public_sample")

    demand = next(item for item in report["requirements"] if item["id"] == "SKU-000")
    candidate = next(item for item in report["requirements"] if item["id"] == "SKU-001")
    assert demand["ready"] is False
    assert demand["current"] == 0
    assert candidate["ready"] is False
    assert candidate["current"] == 0
    assert report["counts"]["qualified_candidate_products"] == 0
    assert report["candidate_portfolio"]["rows"] == []
    assert report["g0"] == "blocked"


def test_fixed_data_allows_research_portfolio_but_keeps_real_execution_blocked():
    report = build_report(demand_evidence="evd_fixed")

    demand = next(item for item in report["requirements"] if item["id"] == "SKU-000")
    assert demand["ready"] is True
    assert report["g0"] == "ready_for_review"
    assert report["counts"]["qualified_candidate_products"] == 3
    assert report["decision_scope_readiness"]["research"]["ready"] is True
    assert report["decision_scope_readiness"]["real_execution"]["ready"] is False
