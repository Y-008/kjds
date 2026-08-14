import type {
  DemoAction,
  DemoTransition,
  DemoWorkspace,
  JsonValue,
  ScenarioPack,
} from "../domain/contracts.ts";

type MutableItem = Record<string, JsonValue>;

export interface WorkspaceReadModel {
  readonly workspace: DemoWorkspace;
  readonly items: readonly JsonValue[];
  readonly summary: JsonValue;
  readonly read_model_sha256_input: JsonValue;
}

function asItem(value: unknown): MutableItem {
  return structuredClone(value) as MutableItem;
}

function payloadOf(transition: DemoTransition): MutableItem {
  const payload = transition.canonical_payload;
  return typeof payload === "object" && payload !== null && !Array.isArray(payload)
    ? (payload as MutableItem)
    : {};
}

function setIfString(item: MutableItem, key: string, value: JsonValue | undefined): void {
  if (typeof value === "string") item[key] = value;
}

export function deriveWorkspaceReadModel(
  pack: ScenarioPack,
  transitions: readonly DemoTransition[],
  workspace: DemoWorkspace,
): WorkspaceReadModel {
  const skus = pack.workspace_projections.skus.map(asItem);
  const orders = pack.workspace_projections.orders.map(asItem);
  const stores = pack.workspace_projections.stores.map(asItem);
  const skuById = new Map(skus.map((item) => [String(item.sku_id), item]));
  const orderById = new Map(orders.map((item) => [String(item.order_id), item]));
  const storeById = new Map(stores.map((item) => [String(item.store_id), item]));
  const tickets = new Map<string, MutableItem>();
  const profits = new Map<string, MutableItem>();

  orders.forEach((order, index) => {
    const orderId = String(order.order_id);
    tickets.set(orderId, {
      order_id: orderId,
      ticket_id: `demo-ticket-${String(index + 1).padStart(3, "0")}`,
      ticket_state: "ready",
      reply_state: "not_started",
    });
    const defaultDecisions = ["stop", "fix", "continue", "no_data"] as const;
    profits.set(orderId, {
      order_id: orderId,
      currency: "RUB",
      synthetic_revenue_minor: order.synthetic_revenue_minor ?? 0,
      settlement_state: "unallocated",
      fee_minor: 0,
      cash_profit_minor: null,
      decision: defaultDecisions[index % defaultDecisions.length] ?? "no_data",
    });
  });

  for (const transition of transitions) {
    const payload = payloadOf(transition);
    const action = transition.action as DemoAction;
    const sku = skuById.get(transition.subject_ref);
    const order = orderById.get(transition.subject_ref);
    const store = storeById.get(transition.subject_ref);
    if (action === "refresh_dashboard" && store) {
      store.signal_state = "refreshed";
    } else if (action === "advance_sourcing" && sku) {
      setIfString(sku, "opportunity_state", payload.target);
      if (typeof payload.opportunity_score === "number") {
        sku.opportunity_score = payload.opportunity_score;
      }
    } else if (action === "prepare_product_content" && sku) {
      sku.content_state = "ready";
      setIfString(sku, "content_state", payload.target);
      if (typeof payload.completeness === "number") sku.content_completeness = payload.completeness;
    } else if (action === "generate_listing_preview" && sku) {
      sku.listing_state = "preview_ready";
      sku.preview_state = "generated";
      setIfString(sku, "preview_language", payload.language);
    } else if (action === "advance_order_timeline" && order) {
      setIfString(order, "state", payload.target);
      order.timeline_state = "advanced";
    } else if (action === "reserve_inventory" && sku) {
      sku.inventory_state = "reserved";
      if (typeof payload.stock_units_after === "number") {
        sku.stock_units = payload.stock_units_after;
      }
    } else if (action === "advance_fulfillment" && order) {
      order.fulfillment_state = "completed";
      setIfString(order, "state", payload.target);
    } else if (action === "simulate_return_exception" && order) {
      order.return_state = "exception";
      setIfString(order, "return_reason", payload.reason);
      const ticket = tickets.get(transition.subject_ref);
      if (ticket) ticket.ticket_state = "return_exception";
    } else if (action === "draft_customer_reply") {
      const ticket = tickets.get(transition.subject_ref);
      if (ticket) ticket.reply_state = "drafted";
    } else if (action === "simulate_campaign" && store) {
      store.campaign_state = "simulated";
      setIfString(store, "campaign_outcome", payload.target);
    } else if (action === "allocate_settlement") {
      const profit = profits.get(transition.subject_ref);
      if (profit) profit.settlement_state = "allocated";
    } else if (action === "assign_synthetic_fee") {
      const profit = profits.get(transition.subject_ref);
      if (profit && typeof payload.fee_minor === "number") profit.fee_minor = payload.fee_minor;
    } else if (action === "recalculate_synthetic_profit") {
      const profit = profits.get(transition.subject_ref);
      if (profit) {
        if (typeof payload.cash_profit_minor === "number") {
          profit.cash_profit_minor = payload.cash_profit_minor;
        }
        setIfString(profit, "decision", payload.decision);
      }
    }
  }

  const fulfillmentItems = orders.map((order) => {
    const sku = skuById.get(String(order.sku_id));
    return {
      ...order,
      inventory_state: sku?.inventory_state ?? "available",
      stock_units: sku?.stock_units ?? 0,
      return_state: order.return_state ?? "none",
    } satisfies MutableItem;
  });
  const decisionCounts: MutableItem = { stop: 0, fix: 0, continue: 0, no_data: 0 };
  for (const profit of profits.values()) {
    const decision = String(profit.decision);
    const current = decisionCounts[decision];
    if (typeof current === "number") decisionCounts[decision] = current + 1;
  }
  const itemsByWorkspace: Record<DemoWorkspace, readonly JsonValue[]> = {
    dashboard: stores,
    sourcing: skus,
    pim: skus,
    listings: skus,
    oms: orders,
    fulfillment: fulfillmentItems,
    customer_service: [...tickets.values()],
    growth: stores,
    profit: [...profits.values()],
  };
  const summary: MutableItem = {
    ...(structuredClone(pack.workspace_projections.summary) as unknown as MutableItem),
    transition_count: transitions.length,
    current_sequence: transitions.length,
    decision_counts: decisionCounts,
    last_action: transitions.at(-1)?.action ?? "none",
  };
  const items = itemsByWorkspace[workspace];
  return {
    workspace,
    items,
    summary,
    read_model_sha256_input: {
      workspace,
      items: structuredClone(items) as JsonValue[],
      summary,
    },
  };
}

export function latestActionForSubject(
  transitions: readonly DemoTransition[],
  subjectRef: string,
): string | null {
  return transitions.findLast((transition) => transition.subject_ref === subjectRef)?.action ?? null;
}
