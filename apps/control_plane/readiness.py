from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any

from .demand_report_gate import DemandReportGateService
from .ozon_contracts import OzonRecordType


class GateReadinessService:
    target_product_count = 3
    target_suppliers_per_product = 3
    requirement_owners = {
        "GOV-001": "经营负责人",
        "SKU-000": "账户/商品",
        "SKU-001": "商品",
        "OZN-001": "账户/经营",
        "SKU-002": "商品/合规",
        "SKU-003": "商品/供应链",
        "OZN-002": "账户/财务",
        "FIN-001": "财务",
    }

    def __init__(
        self,
        *,
        commerce,
        sourcing_store,
        evidence,
        facts,
        finance,
        governance=None,
        demand_reports=None,
        scenario_release_validator=None,
    ) -> None:
        self.commerce = commerce
        self.sourcing_store = sourcing_store
        self.evidence = evidence
        self.facts = facts
        self.finance = finance
        self.governance = governance
        self.demand_reports = demand_reports or DemandReportGateService(evidence=evidence)
        self.scenario_release_validator = scenario_release_validator

    def report(self) -> dict[str, Any]:
        products = self.commerce.list_products()
        candidate_product_ids = self._qualified_candidate_product_ids(products)
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
        qualified_product_rows = [
            item for item in product_rows if item["product"]["id"] in candidate_product_ids
        ]
        for item in product_rows:
            item["qualified_candidate"] = item["product"]["id"] in candidate_product_ids
        portfolio_rows = sorted(
            qualified_product_rows,
            key=lambda item: (
                not item["ready_for_g1_review"],
                -Decimal(item["best_scenario"]["cm3_cny"])
                if item["best_scenario"]
                else Decimal("Infinity"),
                item["product"]["sku"],
            ),
        )
        candidate_ready = len(candidate_product_ids) >= self.target_product_count
        passport_ready_count = sum(1 for item in qualified_product_rows if item["passports_ready"])
        sourcing_ready_count = sum(1 for item in qualified_product_rows if item["sourcing_ready"])
        passports_ready = passport_ready_count >= self.target_product_count
        sourcing_ready = sourcing_ready_count >= self.target_product_count

        governance_evidence = self._valid_requirement_evidence("GOV-001")
        governance_reviews = self.governance.list(gate_id="G0") if self.governance else []
        approved_governance_reviews = [
            item
            for item in governance_reviews
            if item["status"] == "decided"
            and item["decision"] in {"PASS", "CONDITIONAL"}
            and item["evidence_ids"]
        ]
        governance_ready = (
            bool(approved_governance_reviews) if self.governance is not None else bool(governance_evidence)
        )
        ozon_account_evidence = self._valid_requirement_evidence("OZN-001")
        demand_report_status = self.demand_reports.status()
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
                governance_ready,
                "提交并批准结构化 G0 Gate Review（含独立 approver、风险预算、最大损失与回滚）",
                len(approved_governance_reviews) if self.governance is not None else len(governance_evidence),
                gate="G0",
                details={
                    "legacy_evidence_count": len(governance_evidence),
                    "approved_gate_reviews": [item["id"] for item in approved_governance_reviews],
                },
            ),
            self._requirement(
                "SKU-000",
                "Ozon 需求研究依据",
                demand_report_status["research_ready"],
                "上传至少 28 天的合格研究原件并由不同身份接受；真实付款、发布和投放仍单独要求 real_execution 放行",
                len(
                    demand_report_status["readiness"]["research"][
                        "accepted_report_ids"
                    ]
                ),
                gate="G0",
                details=demand_report_status,
            ),
            self._requirement(
                "SKU-001",
                "三个真实候选 SKU",
                candidate_ready,
                f"还需完成 {max(0, self.target_product_count - len(candidate_product_ids))} 个候选的五指标预检与人工报价交接",
                len(candidate_product_ids),
                self.target_product_count,
                gate="G0",
                details={
                    "qualified_candidate_product_ids": sorted(candidate_product_ids),
                    "historical_or_unqualified_product_count": len(products) - len(candidate_product_ids),
                },
            ),
            self._requirement(
                "OZN-001",
                "Ozon 账户、权限与收款路径",
                bool(ozon_account_evidence),
                "上传官方后台、合同或权限证据，并链接到 gate_requirement/OZN-001",
                len(ozon_account_evidence),
                gate="G0",
            ),
            self._requirement(
                "SKU-002",
                "三类 Passport 与有效证据",
                passports_ready,
                "逐 SKU 补齐商品、合规、质量 Passport 并由授权人员批准",
                passport_ready_count,
                self.target_product_count,
                gate="G1",
                details={
                    "blocked_products": [
                        {
                            "product_id": item["product"]["id"],
                            "sku": item["product"]["sku"],
                            "blockers": [
                                blocker
                                for blocker in item["blockers"]
                                if blocker.startswith("Passport")
                            ],
                        }
                        for item in qualified_product_rows
                        if not item["passports_ready"]
                    ]
                },
            ),
            self._requirement(
                "SKU-003",
                "每 SKU 三家报价与正 CM3 场景",
                sourcing_ready,
                "逐 SKU 补齐三家不同供应商报价、实测证据和正 CM3 场景",
                sourcing_ready_count,
                self.target_product_count,
                gate="G1",
                details={
                    "blocked_products": [
                        {
                            "product_id": item["product"]["id"],
                            "sku": item["product"]["sku"],
                            "blockers": [
                                blocker
                                for blocker in item["blockers"]
                                if not blocker.startswith("Passport")
                            ],
                        }
                        for item in qualified_product_rows
                        if not item["sourcing_ready"]
                    ]
                },
            ),
            self._requirement(
                "OZN-002",
                "Ozon 四类一手数据样本",
                not missing_fact_types,
                "仍缺正式事实类型：" + ", ".join(missing_fact_types) if missing_fact_types else "",
                len(required_fact_types - set(missing_fact_types)),
                len(required_fact_types),
                gate="G4",
            ),
            self._requirement(
                "FIN-001",
                "费用字典、RUB/CNY FX 与未知费用隔离",
                fee_mapping_count > 0 and fx_rate_count > 0 and unknown_fee_count == 0,
                "至少需要一条已审批 Ozon 费用映射和一条有证据的 RUB/CNY 汇率",
                min(fee_mapping_count, 1) + min(fx_rate_count, 1),
                2,
                gate="G4",
                details={"fee_mappings": fee_mapping_count, "fx_rates": fx_rate_count, "unknown_fees": unknown_fee_count},
            ),
        ]

        g0_ids = {"GOV-001", "SKU-000", "SKU-001", "OZN-001"}
        g1_ids = g0_ids | {"SKU-002", "SKU-003"}
        g4_ids = {"OZN-002", "FIN-001"}
        g0_ready = all(item["ready"] for item in requirements if item["id"] in g0_ids)
        g1_ready = all(item["ready"] for item in requirements if item["id"] in g1_ids)
        g4_ready = all(item["ready"] for item in requirements if item["id"] in g4_ids)
        gate_blockers = self._gate_blockers(requirements)
        return {
            "gate": "G0-G1",
            "status": "ready_for_review" if g1_ready else "needs_input",
            "g0": "ready_for_review" if g0_ready else "blocked",
            "g1": "ready_for_review" if g1_ready else "blocked",
            "g4": "ready_for_review" if g4_ready else "blocked",
            "products": product_rows,
            "candidate_portfolio": {
                "target_count": self.target_product_count,
                "candidate_count": len(portfolio_rows),
                "selection_ready_count": sum(
                    1 for item in portfolio_rows if item["ready_for_g1_review"]
                ),
                "rows": portfolio_rows,
                "advisory_only": True,
                "automatic_product_selection": False,
                "automatic_procurement": False,
                "automatic_pricing": False,
                "automatic_listing": False,
            },
            "decision_scope_readiness": demand_report_status["readiness"],
            "exception_workspace": {
                "items": gate_blockers,
                "blocked_count": len(gate_blockers),
                "counts_by_gate": {
                    gate: sum(item["gate"] == gate for item in gate_blockers)
                    for gate in ("G0", "G1", "G4")
                },
                "advisory_only": True,
                "automatic_resolution": False,
                "platform_write_allowed": False,
            },
            "requirements": requirements,
            "counts": {
                "products": len(products),
                "qualified_candidate_products": len(candidate_product_ids),
                "bound_offers": len(offer_product),
                "unbound_legacy_offers": sum(1 for item in offers if not item.product_id),
                "profit_scenarios": len(scenarios),
            },
            "next_actions": [item["next_action"] for item in requirements if not item["ready"]],
        }

    def _gate_blockers(self, requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
        gate_rank = {"G0": 0, "G1": 1, "G4": 2}
        return sorted(
            [
                {
                    "queue_key": f"gate_requirement:{item['id']}",
                    "item_type": "gate_blocker",
                    "source_type": "gate_requirement",
                    "source_id": item["id"],
                    "gate": item["gate"],
                    "title": item["title"],
                    "status": "blocked",
                    "attention": "current_gate" if item["gate"] in {"G0", "G1"} else "downstream",
                    "owner_role": self.requirement_owners[item["id"]],
                    "current": item["current"],
                    "target": item["target"],
                    "next_action": item["next_action"],
                    "details": item["details"],
                }
                for item in requirements
                if not item["ready"]
            ],
            key=lambda item: (gate_rank[item["gate"]], item["source_id"]),
        )

    def _qualified_candidate_product_ids(self, products: list) -> set[str]:
        product_ids = {product.id for product in products}
        handoff_ids = {
            event["aggregate_id"]
            for event in self.commerce.repo.events_after(0)
            if event["type"] == "product.candidate_sourcing_workspace_created"
            and event["aggregate_id"] in product_ids
        }
        qualified: set[str] = set()
        for product_id in handoff_ids:
            evidence_ids = self.evidence.target_evidence_ids(
                target_type="product",
                target_id=product_id,
                relationship="candidate_basis",
            )
            if not evidence_ids:
                continue
            demand_report_ids = self.evidence.target_evidence_ids(
                target_type="product",
                target_id=product_id,
                relationship="demand_report_basis",
            )
            if len(demand_report_ids) != 1:
                continue
            try:
                self.evidence.require_valid(evidence_ids)
                self.demand_reports.require_accepted(
                    demand_report_ids[0],
                    scope="research",
                )
            except (KeyError, ValueError):
                continue
            qualified.add(product_id)
        return qualified

    def _product_row(self, product, offers: list, scenarios: list) -> dict[str, Any]:
        passport = self.commerce.product_readiness(product.id)
        latest_offer_by_supplier = {}
        for offer in offers:
            if offer.supplier_ref:
                current = latest_offer_by_supplier.get(offer.supplier_ref)
                if current is None or getattr(offer, "captured_at", "") > getattr(
                    current, "captured_at", ""
                ):
                    latest_offer_by_supplier[offer.supplier_ref] = offer
        current_offers = list(latest_offer_by_supplier.values())
        latest_scenario_by_offer = {}
        for scenario in scenarios:
            current = latest_scenario_by_offer.get(scenario.offer_id)
            if current is None or getattr(scenario, "created_at", "") > getattr(
                current, "created_at", ""
            ):
                latest_scenario_by_offer[scenario.offer_id] = scenario
        current_scenarios = [
            latest_scenario_by_offer[offer.id]
            for offer in current_offers
            if offer.id in latest_scenario_by_offer
        ]
        suppliers = sorted(latest_offer_by_supplier)
        positive_scenarios = [scenario for scenario in current_scenarios if scenario.cm3_cny > 0]
        complete_scenarios = [scenario for scenario in positive_scenarios if self._release_ready(scenario)]
        best_scenario = max(
            complete_scenarios or current_scenarios,
            key=lambda scenario: scenario.cm3_cny,
            default=None,
        )
        best_offer = next(
            (offer for offer in current_offers if best_scenario and offer.id == best_scenario.offer_id),
            None,
        )
        passports_ready = passport["ready_for_validation"]
        sourcing_ready = len(suppliers) >= self.target_suppliers_per_product and bool(complete_scenarios)
        blockers: list[str] = []
        if not passports_ready:
            blockers.append("Passport 未全部通过")
        if len(suppliers) < self.target_suppliers_per_product:
            blockers.append(f"还缺 {self.target_suppliers_per_product - len(suppliers)} 家不同供应商报价")
        if not complete_scenarios:
            blockers.append("缺少证据完整且 CM3 为正的利润场景")
        return {
            "product": passport["product"],
            "passports": passport["passports"],
            "passports_ready": passports_ready,
            "supplier_count": len(suppliers),
            "supplier_refs": suppliers,
            "offer_count": len(current_offers),
            "offer_snapshot_count": len(offers),
            "profit_scenario_count": len(current_scenarios),
            "profit_scenario_snapshot_count": len(scenarios),
            "positive_profit_scenario_count": len(positive_scenarios),
            "complete_profit_scenario_count": len(complete_scenarios),
            "best_scenario": (
                {
                    "id": getattr(best_scenario, "id", None),
                    "offer_id": best_scenario.offer_id,
                    "supplier_ref": best_offer.supplier_ref if best_offer else None,
                    "cm3_cny": str(best_scenario.cm3_cny),
                    "cm3_rate": str(getattr(best_scenario, "cm3_rate", "")),
                    "break_even_price_rub": str(
                        getattr(best_scenario, "break_even_price_rub", "")
                    ),
                    "template_id": getattr(best_scenario, "template_id", None),
                    "unknown_costs": list(getattr(best_scenario, "unknown_costs", [])),
                    "evidence_count": len(getattr(best_scenario, "evidence", [])),
                    "release_ready": bool(best_scenario.cm3_cny > 0 and self._release_ready(best_scenario)),
                }
                if best_scenario
                else None
            ),
            "sourcing_ready": sourcing_ready,
            "ready_for_g1_review": passports_ready and sourcing_ready,
            "blockers": blockers,
        }

    def _release_ready(self, scenario) -> bool:
        if not scenario.cost_complete:
            return False
        if self.scenario_release_validator is None:
            return True
        try:
            self.scenario_release_validator(scenario)
        except (KeyError, RuntimeError, ValueError):
            return False
        return True

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
        gate: str = "G0",
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "id": requirement_id,
            "gate": gate,
            "title": title,
            "ready": ready,
            "status": "ready_for_review" if ready else "needs_input",
            "current": current,
            "target": target,
            "next_action": "" if ready else next_action,
            "details": details or {},
        }
