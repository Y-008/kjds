from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

from .domain import (
    CM1_COSTS,
    CM2_COSTS,
    CM3_COSTS,
    PASSPORT_REQUIRED_FACTS,
    AgentMode,
    AgentTask,
    Approval,
    ApprovalStatus,
    Charge,
    ChargeType,
    Order,
    Passport,
    PassportType,
    Product,
    ProductStatus,
    ProfitSnapshot,
)
from .repository import Repository

HIGH_RISK_ACTIONS = {
    "listing.publish",
    "procurement.place_order",
    "advertising.increase_budget_large",
    "refund.issue_high_value",
    "settlement.change_bank_account",
}

AGENT_POLICIES: dict[str, set[AgentMode]] = {
    "market": {AgentMode.READ_ONLY},
    "product": {AgentMode.READ_ONLY, AgentMode.DRAFT},
    "listing": {AgentMode.READ_ONLY, AgentMode.DRAFT},
    "finance": {AgentMode.READ_ONLY},
    "operations": {AgentMode.READ_ONLY, AgentMode.DRAFT},
    "advertising": {AgentMode.READ_ONLY, AgentMode.DRAFT, AgentMode.LIMITED_EXECUTION},
    "procurement": {AgentMode.READ_ONLY, AgentMode.DRAFT},
}


class CommerceService:
    def __init__(self, repository: Repository, evidence_validator: Callable[[list[str]], None]) -> None:
        self.repo = repository
        self.evidence_validator = evidence_validator

    def create_product(self, *, sku: str, name: str) -> Product:
        product = self.repo.add_product(Product(sku=sku.strip(), name=name.strip()))
        self.repo.append_event("product.created", product.id, {"sku": product.sku})
        return product

    def add_passport(
        self,
        *,
        product_id: str,
        kind: PassportType,
        facts: dict,
        evidence: list[str],
        approved_by: str | None,
    ) -> Passport:
        self.repo.get_product(product_id)
        facts = dict(facts)
        evidence = [item.strip() for item in evidence if item.strip()]
        decision = facts.get("decision")
        if approved_by:
            if decision not in {"approved", "rejected", "blocked"}:
                raise ValueError("Reviewed passport decision must be approved, rejected, or blocked")
            if not evidence:
                raise ValueError("Reviewed passport requires evidence")
            self.evidence_validator(evidence)
        previous = self.repo.latest_passports(product_id).get(kind)
        passport = Passport(
            product_id=product_id,
            kind=kind,
            version=1 if previous is None else previous.version + 1,
            facts=facts,
            evidence=evidence,
            approved_by=approved_by,
        )
        if approved_by and decision == "approved" and passport.missing_required_facts:
            raise ValueError(
                f"Approved {kind.value} passport missing required facts: {', '.join(passport.missing_required_facts)}"
            )
        self.repo.add_passport(passport)
        self.repo.append_event("passport.recorded", product_id, {"kind": kind, "version": passport.version})
        return passport

    def list_products(self) -> list[Product]:
        return self.repo.list_products()

    def product_readiness(self, product_id: str) -> dict:
        product = self.repo.get_product(product_id)
        passports = self.repo.latest_passports(product_id)
        checks = []
        for kind in PassportType:
            passport = passports.get(kind)
            if passport is None:
                checks.append(
                    {
                        "kind": kind.value,
                        "status": "missing",
                        "version": None,
                        "missing_fields": sorted(PASSPORT_REQUIRED_FACTS[kind]),
                        "evidence_count": 0,
                        "approved_by": None,
                        "evidence_valid": None,
                        "evidence_error": None,
                    }
                )
                continue
            evidence_valid: bool | None = None
            evidence_error: str | None = None
            if passport.approved_by:
                try:
                    self.evidence_validator(passport.evidence)
                    evidence_valid = True
                except (KeyError, ValueError) as exc:
                    evidence_valid = False
                    evidence_error = str(exc)
            if passport.is_approved and evidence_valid:
                status = "approved"
            elif passport.approved_by and evidence_valid is False:
                status = "invalid_evidence"
            elif passport.is_blocked:
                status = "blocked"
            elif passport.facts.get("decision") == "approved" and not passport.approved_by:
                status = "awaiting_approval"
            else:
                status = "draft"
            checks.append(
                {
                    "kind": kind.value,
                    "status": status,
                    "version": passport.version,
                    "missing_fields": passport.missing_required_facts,
                    "evidence_count": len(passport.evidence),
                    "approved_by": passport.approved_by,
                    "evidence_valid": evidence_valid,
                    "evidence_error": evidence_error,
                }
            )
        return {
            "product": {
                "id": product.id,
                "sku": product.sku,
                "name": product.name,
                "status": product.status.value,
            },
            "passports": checks,
            "ready_for_validation": all(item["status"] == "approved" for item in checks),
        }

    def validate_product(self, product_id: str) -> Product:
        product = self.repo.get_product(product_id)
        readiness = self.product_readiness(product_id)
        missing = [item["kind"] for item in readiness["passports"] if item["status"] != "approved"]
        if missing:
            raise ValueError(f"Approved passports required: {', '.join(missing)}")
        product.status = ProductStatus.VALIDATED
        self.repo.save_product(product)
        self.repo.append_event("product.validated", product.id, {})
        return product

    def create_order(
        self,
        *,
        external_id: str,
        product_id: str,
        quantity: int,
        currency: str,
        gross_revenue: Decimal,
        booked_fx_rate: Decimal,
    ) -> Order:
        product = self.repo.get_product(product_id)
        if product.status not in {ProductStatus.VALIDATED, ProductStatus.APPROVED_FOR_LISTING, ProductStatus.ACTIVE}:
            raise ValueError("Product must pass all passports before an order can be recorded")
        if quantity <= 0 or gross_revenue < 0 or booked_fx_rate <= 0:
            raise ValueError("Invalid order quantity, revenue, or FX rate")
        order = Order(
            external_id=external_id,
            product_id=product_id,
            quantity=quantity,
            currency=currency,
            gross_revenue=gross_revenue,
            booked_fx_rate=booked_fx_rate,
        )
        self.repo.add_order(order)
        self.repo.append_event("order.created", order.id, {"external_id": external_id})
        return order

    def add_charge(
        self,
        *,
        order_id: str,
        kind: ChargeType,
        amount: Decimal,
        currency: str,
        fx_rate: Decimal,
        evidence_ref: str,
    ) -> Charge:
        self.repo.get_order(order_id)
        if amount < 0 or fx_rate <= 0 or not evidence_ref.strip():
            raise ValueError("Charge requires non-negative amount, positive FX rate, and evidence")
        charge = self.repo.add_charge(
            Charge(
                order_id=order_id,
                kind=kind,
                amount=amount,
                currency=currency,
                fx_rate=fx_rate,
                evidence_ref=evidence_ref,
            )
        )
        self.repo.append_event("charge.recorded", order_id, {"kind": kind, "amount": str(amount)})
        return charge

    def calculate_profit(self, order_id: str) -> ProfitSnapshot:
        order = self.repo.get_order(order_id)
        gross = order.gross_revenue * order.booked_fx_rate
        totals = {kind: Decimal("0") for kind in ChargeType}
        for charge in self.repo.charges_for_order(order_id):
            totals[charge.kind] += charge.amount_cny
        net = gross - totals[ChargeType.DISCOUNT] - totals[ChargeType.REFUND]
        cm1 = net - sum((totals[kind] for kind in CM1_COSTS), Decimal("0"))
        cm2 = cm1 - sum((totals[kind] for kind in CM2_COSTS), Decimal("0"))
        cm3 = cm2 - sum((totals[kind] for kind in CM3_COSTS), Decimal("0"))
        rate = Decimal("0") if net == 0 else cm3 / net
        return ProfitSnapshot(order.id, gross, net, cm1, cm2, cm3, rate)

    def request_approval(
        self, *, action: str, resource_type: str, resource_id: str, requested_by: str, payload: dict
    ) -> Approval:
        if action not in HIGH_RISK_ACTIONS:
            raise ValueError("Approval endpoint is reserved for registered high-risk actions")
        approval = self.repo.add_approval(
            Approval(
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                requested_by=requested_by,
                payload=payload,
            )
        )
        self.repo.append_event("approval.requested", approval.id, {"action": action})
        return approval

    def decide_approval(self, approval_id: str, *, approved: bool, decided_by: str, reason: str) -> Approval:
        approval = self.repo.get_approval(approval_id)
        if approval.status != ApprovalStatus.PENDING:
            raise ValueError("Approval has already been decided")
        if approval.requested_by == decided_by:
            raise ValueError("Requester cannot approve their own high-risk action")
        approval.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
        approval.decided_by = decided_by
        approval.decision_reason = reason
        self.repo.save_approval(approval)
        self.repo.append_event("approval.decided", approval.id, {"status": approval.status})
        return approval

    def submit_agent_task(
        self,
        *,
        agent: str,
        mode: AgentMode,
        task_type: str,
        input_data: dict,
        requested_by: str,
        idempotency_key: str,
    ) -> AgentTask:
        allowed_modes = AGENT_POLICIES.get(agent)
        if allowed_modes is None or mode not in allowed_modes:
            raise PermissionError(f"Agent {agent!r} is not permitted to run in {mode!r} mode")
        if not idempotency_key.strip():
            raise ValueError("Agent task requires an idempotency key")
        task = AgentTask(agent, mode, task_type, input_data, requested_by, idempotency_key)
        stored = self.repo.add_agent_task(task)
        if stored.id == task.id:
            self.repo.append_event("agent_task.submitted", task.id, {"agent": agent, "mode": mode})
        return stored
