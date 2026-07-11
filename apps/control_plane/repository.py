from __future__ import annotations

from collections.abc import Iterable

from .domain import (
    AgentTask,
    Approval,
    Charge,
    ContentAsset,
    GrowthExperiment,
    MarketObservation,
    OpportunityInsight,
    Order,
    Passport,
    PassportType,
    Product,
)


class InMemoryRepository:
    """Deterministic repository for domain tests and the initial vertical slice."""

    def __init__(self) -> None:
        self.products: dict[str, Product] = {}
        self.passports: dict[str, Passport] = {}
        self.orders: dict[str, Order] = {}
        self.charges: dict[str, Charge] = {}
        self.approvals: dict[str, Approval] = {}
        self.agent_tasks: dict[str, AgentTask] = {}
        self.agent_tasks_by_key: dict[str, str] = {}
        self.market_observations: dict[str, MarketObservation] = {}
        self.opportunities: dict[str, OpportunityInsight] = {}
        self.content_assets: dict[str, ContentAsset] = {}
        self.experiments: dict[str, GrowthExperiment] = {}
        self.events: list[dict] = []

    def add_product(self, product: Product) -> Product:
        if any(item.sku == product.sku for item in self.products.values()):
            raise ValueError(f"SKU already exists: {product.sku}")
        self.products[product.id] = product
        return product

    def get_product(self, product_id: str) -> Product:
        try:
            return self.products[product_id]
        except KeyError as exc:
            raise KeyError(f"Unknown product: {product_id}") from exc

    def add_passport(self, passport: Passport) -> Passport:
        self.passports[passport.id] = passport
        return passport

    def latest_passports(self, product_id: str) -> dict[PassportType, Passport]:
        result: dict[PassportType, Passport] = {}
        for passport in self.passports.values():
            if passport.product_id != product_id:
                continue
            current = result.get(passport.kind)
            if current is None or passport.version > current.version:
                result[passport.kind] = passport
        return result

    def add_order(self, order: Order) -> Order:
        if any(item.external_id == order.external_id for item in self.orders.values()):
            raise ValueError(f"External order already exists: {order.external_id}")
        self.orders[order.id] = order
        return order

    def get_order(self, order_id: str) -> Order:
        try:
            return self.orders[order_id]
        except KeyError as exc:
            raise KeyError(f"Unknown order: {order_id}") from exc

    def add_charge(self, charge: Charge) -> Charge:
        self.charges[charge.id] = charge
        return charge

    def charges_for_order(self, order_id: str) -> Iterable[Charge]:
        return (item for item in self.charges.values() if item.order_id == order_id)

    def add_approval(self, approval: Approval) -> Approval:
        self.approvals[approval.id] = approval
        return approval

    def get_approval(self, approval_id: str) -> Approval:
        try:
            return self.approvals[approval_id]
        except KeyError as exc:
            raise KeyError(f"Unknown approval: {approval_id}") from exc

    def add_agent_task(self, task: AgentTask) -> AgentTask:
        existing_id = self.agent_tasks_by_key.get(task.idempotency_key)
        if existing_id:
            return self.agent_tasks[existing_id]
        self.agent_tasks[task.id] = task
        self.agent_tasks_by_key[task.idempotency_key] = task.id
        return task

    def append_event(self, event_type: str, aggregate_id: str, payload: dict) -> None:
        self.events.append(
            {"sequence": len(self.events) + 1, "type": event_type, "aggregate_id": aggregate_id, "payload": payload}
        )

    def add_observation(self, observation: MarketObservation) -> MarketObservation:
        self.market_observations[observation.id] = observation
        return observation

    def observations_for(self, market: str, category: str, metric: str | None = None) -> list[MarketObservation]:
        return [
            item
            for item in self.market_observations.values()
            if item.market == market and item.category == category and (metric is None or item.metric == metric)
        ]

    def add_opportunity(self, opportunity: OpportunityInsight) -> OpportunityInsight:
        self.opportunities[opportunity.id] = opportunity
        return opportunity

    def add_content_asset(self, asset: ContentAsset) -> ContentAsset:
        self.content_assets[asset.id] = asset
        return asset

    def get_content_asset(self, asset_id: str) -> ContentAsset:
        try:
            return self.content_assets[asset_id]
        except KeyError as exc:
            raise KeyError(f"Unknown content asset: {asset_id}") from exc

    def add_experiment(self, experiment: GrowthExperiment) -> GrowthExperiment:
        self.experiments[experiment.id] = experiment
        return experiment

    def get_experiment(self, experiment_id: str) -> GrowthExperiment:
        try:
            return self.experiments[experiment_id]
        except KeyError as exc:
            raise KeyError(f"Unknown experiment: {experiment_id}") from exc
