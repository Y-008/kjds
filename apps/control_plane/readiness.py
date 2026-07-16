from __future__ import annotations

from collections import defaultdict
from typing import Any

from .ozon_contracts import OzonRecordType


class GateReadinessService:
    target_product_count = 3
    target_suppliers_per_product = 3

    def __init__(self, *, commerce, sourcing_store, evidence, facts, finance) -> None:
        self.commerce = commerce
        self.sourcing_store = sourcing_store
        self.evidence = evidence
        self.facts = facts
        self.finance = finance

    def report(self) -> dict[str, Any]:
        products = self.commerce.list_products()
        offers = self.sourcing_store.list_offers(limit=5000)
        scenarios = self.sourcing_store.list_scenarios(limit=5000)
        offers_by_product: dict[str, list] = defaultdict(list)
        offer_product: dict[str, str] = {}
        for offer in offers:
            if offer.product_id:
                offers_by_product[offer.product_id].append(offer)
                offer_product[offer.id] = offer.product_id
        scenarios_by_product: dict[str, list] = defaultdict(list)
        for scenario in scenarios:
            product_id = offer_product.get(scenario.offer_id)
            if product_id:
                scenarios_by_product[product_id].append(scenario)

        product_rows = [
            self._product_row(product, offers_by_product[product.id], scenarios_by_product[product.id])
            for product in products
        ]
        candidate_ready = len(products) >= self.target_product_count
        passport_ready_count = sum(1 for item in product_rows if item["passports_ready"])
        sourcing_ready_count = sum(1 for item in product_rows if item["sourcing_ready"])
        passports_ready = passport_ready_count >= self.target_product_count
        sourcing_ready = sourcing_ready_count >= self.target_product_count

        governance_evidence = self._valid_requirement_evidence("GOV-001")
        ozon_account_evidence = self._valid_requirement_evidence("OZN-001")
        formal_fact_types = {item.fact_type for item in self.facts.list(limit=5000)}
        required_fact_types = {item.value for item in OzonRecordType}
        missing_fact_types = sorted(required_fact_types - formal_fact_types)
        fee_mapping_count = len(self.finance.list_fee_mappings(provider="ozon"))
        fx_rate_count = len(self.finance.list_fx_rates(base_currency="RUB"))
        unknown_fee_count = len(self.finance.unknown_fee_entries(provider="ozon"))

        requirements = [
            self._requirement(
                "GOV-001",
                "负责人、审批人与风险预算",
                bool(governance_evidence),
                "上传签字或批准记录，并把证据链接到 gate_requirement/GOV-001",
                len(governance_evidence),
            ),
            self._requirement(
                "SKU-001",
                "三个真实候选 SKU",
                candidate_ready,
                f"还需录入 {max(0, self.target_product_count - len(products))} 个候选 SKU",
                len(products),
                self.target_product_count,
            ),
            self._requirement(
                "OZN-001",
                "Ozon 账户、权限与收款路径",
                bool(ozon_account_evidence),
                "上传官方后台、合同或权限证据，并链接到 gate_requirement/OZN-001",
                len(ozon_account_evidence),
            ),
            self._requirement(
                "SKU-002",
                "三类 Passport 与有效证据",
                passports_ready,
                "逐 SKU 补齐商品、合规、质量 Passport 并由授权人员批准",
                passport_ready_count,
                self.target_product_count,
            ),
            self._requirement(
                "SKU-003",
                "每 SKU 三家报价与正 CM3 场景",
                sourcing_ready,
                "逐 SKU 补齐三家不同供应商报价、实测证据和正 CM3 场景",
                sourcing_ready_count,
                self.target_product_count,
            ),
            self._requirement(
                "OZN-002",
                "Ozon 四类一手数据样本",
                not missing_fact_types,
                "仍缺正式事实类型：" + ", ".join(missing_fact_types) if missing_fact_types else "",
                len(required_fact_types - set(missing_fact_types)),
                len(required_fact_types),
            ),
            self._requirement(
                "FIN-001",
                "费用字典、RUB/CNY FX 与未知费用隔离",
                fee_mapping_count > 0 and fx_rate_count > 0 and unknown_fee_count == 0,
                "至少需要一条已审批 Ozon 费用映射和一条有证据的 RUB/CNY 汇率",
                min(fee_mapping_count, 1) + min(fx_rate_count, 1),
                2,
                details={"fee_mappings": fee_mapping_count, "fx_rates": fx_rate_count, "unknown_fees": unknown_fee_count},
            ),
        ]

        g0_ids = {"GOV-001", "SKU-001", "OZN-001"}
        g0_ready = all(item["ready"] for item in requirements if item["id"] in g0_ids)
        g1_ready = g0_ready and all(item["ready"] for item in requirements)
        return {
            "gate": "G0-G1",
            "status": "ready_for_review" if g1_ready else "needs_input",
            "g0": "ready_for_review" if g0_ready else "blocked",
            "g1": "ready_for_review" if g1_ready else "blocked",
            "products": product_rows,
            "requirements": requirements,
            "counts": {
                "products": len(products),
                "bound_offers": len(offer_product),
                "unbound_legacy_offers": sum(1 for item in offers if not item.product_id),
                "profit_scenarios": len(scenarios),
            },
            "next_actions": [item["next_action"] for item in requirements if not item["ready"]],
        }

    def _product_row(self, product, offers: list, scenarios: list) -> dict[str, Any]:
        passport = self.commerce.product_readiness(product.id)
        suppliers = sorted({offer.supplier_ref for offer in offers if offer.supplier_ref})
        positive_scenarios = [scenario for scenario in scenarios if scenario.cm3_cny > 0]
        passports_ready = passport["ready_for_validation"]
        sourcing_ready = len(suppliers) >= self.target_suppliers_per_product and bool(positive_scenarios)
        blockers: list[str] = []
        if not passports_ready:
            blockers.append("Passport 未全部通过")
        if len(suppliers) < self.target_suppliers_per_product:
            blockers.append(f"还缺 {self.target_suppliers_per_product - len(suppliers)} 家不同供应商报价")
        if not positive_scenarios:
            blockers.append("缺少证据完整且 CM3 为正的利润场景")
        return {
            "product": passport["product"],
            "passports": passport["passports"],
            "passports_ready": passports_ready,
            "supplier_count": len(suppliers),
            "supplier_refs": suppliers,
            "offer_count": len(offers),
            "profit_scenario_count": len(scenarios),
            "positive_profit_scenario_count": len(positive_scenarios),
            "sourcing_ready": sourcing_ready,
            "ready_for_g1_review": passports_ready and sourcing_ready,
            "blockers": blockers,
        }

    def _valid_requirement_evidence(self, requirement_id: str) -> list[str]:
        evidence_ids = self.evidence.target_evidence_ids(
            target_type="gate_requirement",
            target_id=requirement_id,
        )
        valid: list[str] = []
        for evidence_id in evidence_ids:
            try:
                self.evidence.require_valid([evidence_id])
            except (KeyError, ValueError):
                continue
            valid.append(evidence_id)
        return valid

    @staticmethod
    def _requirement(
        requirement_id: str,
        title: str,
        ready: bool,
        next_action: str,
        current: int,
        target: int = 1,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "id": requirement_id,
            "title": title,
            "ready": ready,
            "status": "ready_for_review" if ready else "needs_input",
            "current": current,
            "target": target,
            "next_action": "" if ready else next_action,
            "details": details or {},
        }
