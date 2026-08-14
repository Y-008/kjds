"use client";

import {
  ArrowLeft,
  Bot,
  Boxes,
  ChevronRight,
  CircleAlert,
  Clock3,
  Fingerprint,
  LockKeyhole,
  RefreshCw,
  ShieldCheck,
  Store,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { fetchJson } from "../../lib/fetch-json";
import styles from "./oms.module.css";

type WorkspaceStatus = "ready" | "partial" | "blocked" | "no_data";
type ViewState = WorkspaceStatus | "loading" | "error";

type OmsEvent = {
  fact_id: string;
  fact_type: "ozon_order" | "ozon_return";
  external_id?: string;
  order_external_id: string;
  product_id?: string;
  sku?: string;
  quantity?: number;
  currency?: string | null;
  amount?: string | null;
  raw_status?: string | null;
  canonical_status?: string;
  effective_at: string;
  recorded_at: string;
  evidence_id: string;
  validation_status?: "blocked";
  blocker_code?: string;
};

type OmsOrder = {
  external_id: string;
  product_id: string | null;
  sku: string | null;
  current_state: string;
  projection_status: "ready" | "partial" | "blocked";
  current_event: OmsEvent;
  timeline: OmsEvent[];
  blocked_events: OmsEvent[];
  timeline_event_count: number;
  evidence_ids: string[];
  fact_ids: string[];
  owner: string;
  sla: string;
  next: string;
  next_workspace: string;
};

type Blocker = {
  code: string;
  severity: string;
  owner: string;
  sla: string;
  next: string;
  next_workspace: string;
};

type OmsWorkspace = {
  contract_id: string;
  status: WorkspaceStatus;
  as_of: string;
  scope: {
    tenant_ref: string;
    entity_ref: string | null;
    store_ref: string;
    scope_grant_authority_sha256: string | null;
  };
  query: {
    page_size: number;
    cursor: string | null;
    next_cursor: string | null;
    max_fact_rows: number;
  };
  counts: {
    raw_order_facts: number;
    raw_return_facts: number;
    valid_timeline_events: number;
    total_current_orders: number;
    page_current_orders: number;
    blocked_current_orders: number;
    invalid_facts: number;
    legacy_orders_read: 0;
  };
  orders: OmsOrder[];
  invalid_fact_ids: string[];
  source_gaps: string[];
  blockers: Blocker[];
  agent_support: {
    authority: "decision_support_only";
    input_snapshot_sha256: string | null;
    suggestions: Array<{
      order_external_id: string;
      current_state: string;
      owner: string;
      sla: string;
      next: string;
      next_workspace: string;
      external_action_allowed: false;
    }>;
    automatic_actions: [];
    self_approval_allowed: false;
    permit_issue_allowed: false;
  };
  control_envelope: {
    read_only: true;
    scoped_input_read: boolean;
    legacy_rows_inferred: false;
    client_recalculation_allowed: false;
    operating_task_created: false;
    supplier_order_created: false;
    payment_created: false;
    customer_message_sent: false;
    approval_created: false;
    permit_created: false;
    external_write_allowed: false;
  };
  snapshot_sha256: string;
};

type StrategyPacks = {
  authorized_scope: {
    tenant_ref: string;
    store_refs: string[];
  };
};

type ErrorPayload = { detail?: string };

const stateLabel: Record<string, string> = {
  created: "已创建",
  paid: "已付款",
  awaiting_packaging: "待备货",
  awaiting_handover: "待交运",
  in_transit: "运输中",
  delivered: "已签收",
  cancelled: "已取消",
  returned: "已退货",
  unknown: "状态待核验",
  ready: "权威可用",
  partial: "部分可用",
  blocked: "已阻断",
  no_data: "暂无正式订单",
};

function shortHash(value: string | null) {
  return value ? `${value.slice(0, 12)}…${value.slice(-8)}` : "no_data";
}

function label(value: string) {
  return stateLabel[value] ?? value;
}

export function OmsConsole() {
  const [stores, setStores] = useState<string[]>([]);
  const [storeRef, setStoreRef] = useState("");
  const [workspace, setWorkspace] = useState<OmsWorkspace | null>(null);
  const [viewState, setViewState] = useState<ViewState>("loading");
  const [scopeBusy, setScopeBusy] = useState(true);
  const [workspaceBusy, setWorkspaceBusy] = useState(false);
  const [detail, setDetail] = useState("");

  const redirectForAuth = useCallback((status: number) => {
    if (status === 401) {
      window.location.assign("/login");
      return true;
    }
    if (status === 428) {
      window.location.assign("/mfa");
      return true;
    }
    return false;
  }, []);

  const loadScope = useCallback(async (signal?: AbortSignal) => {
    setScopeBusy(true);
    setDetail("");
    try {
      const response = await fetchJson<StrategyPacks | ErrorPayload>(
        "/backend/v1/seller-os/strategy-packs",
        { cache: "no-store", signal },
      );
      if (redirectForAuth(response.status)) return;
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(
          "detail" in payload
            ? payload.detail ?? `API ${response.status}`
            : `API ${response.status}`,
        );
      }
      const authorized = (payload as StrategyPacks).authorized_scope.store_refs;
      setStores(authorized);
      setStoreRef((current) =>
        current && authorized.includes(current) ? current : authorized[0] ?? "",
      );
      setScopeBusy(false);
      if (authorized.length === 0) {
        setViewState("blocked");
        setDetail("当前身份没有授权店铺，OMS 不会回退到全局订单。");
      }
    } catch (error) {
      if (signal?.aborted) return;
      setScopeBusy(false);
      setViewState("error");
      setDetail(error instanceof Error ? error.message : "授权作用域读取失败");
    }
  }, [redirectForAuth]);

  const loadWorkspace = useCallback(
    async (store: string, cursor?: string | null, signal?: AbortSignal) => {
      if (!store) return;
      setWorkspaceBusy(true);
      setDetail("");
      try {
        const query = new URLSearchParams({
          store_ref: store,
          page_size: "100",
        });
        if (cursor) query.set("cursor", cursor);
        const response = await fetchJson<OmsWorkspace | ErrorPayload>(
          `/backend/v1/oms/workspace?${query.toString()}`,
          { cache: "no-store", signal },
        );
        if (redirectForAuth(response.status)) return;
        const payload = await response.json();
        if (!response.ok) {
          const message =
            "detail" in payload
              ? payload.detail ?? `API ${response.status}`
              : `API ${response.status}`;
          setViewState(response.status === 403 || response.status === 422 ? "blocked" : "error");
          setDetail(String(message));
          setWorkspace(null);
          setWorkspaceBusy(false);
          return;
        }
        const next = payload as OmsWorkspace;
        setWorkspace(next);
        setViewState(next.status);
        setWorkspaceBusy(false);
      } catch (error) {
        if (signal?.aborted) return;
        setWorkspaceBusy(false);
        setViewState("error");
        setDetail(
          error instanceof Error
            ? error.message
            : "OMS 权威暂不可用，请检查网络后重试。",
        );
      }
    },
    [redirectForAuth],
  );

  useEffect(() => {
    const controller = new AbortController();
    void loadScope(controller.signal);
    return () => controller.abort("OMS scope unmounted");
  }, [loadScope]);

  useEffect(() => {
    if (!storeRef) return;
    const controller = new AbortController();
    void loadWorkspace(storeRef, null, controller.signal);
    return () => controller.abort("OMS store changed");
  }, [loadWorkspace, storeRef]);

  return (
    <main className={styles.page}>
      <header className={styles.topbar}>
        <Link href="/commerce-os" className={styles.backLink}>
          <ArrowLeft size={16} />
          Commerce OS
        </Link>
        <div className={styles.productMark}>
          <span><Boxes size={18} /></span>
          <div><strong>原生 OMS</strong><small>KJDS AI ERP · EVIDENCE BOUND</small></div>
        </div>
        <label className={styles.storePicker}>
          <Store size={15} />
          <span>授权店铺</span>
          <select
            aria-label="选择授权店铺"
            value={storeRef}
            disabled={scopeBusy || stores.length === 0}
            onChange={(event) => setStoreRef(event.target.value)}
          >
            {stores.map((store) => <option key={store}>{store}</option>)}
          </select>
        </label>
      </header>

      <section className={styles.hero}>
        <div>
          <span className={styles.eyebrow}>
            <ShieldCheck size={14} />
            EXACT SCOPE · CURRENT FACT · IMMUTABLE TIMELINE
          </span>
          <h1>订单状态由事实决定，<em>Agent 只负责解释与推进</em></h1>
          <p>
            仅使用 tenant / entity / store / grant / Evidence 一致的 Ozon 正式
            Order 与 Return Fact。旧订单表、同行数据和客户端推算都不会进入当前状态。
          </p>
        </div>
        <aside>
          <LockKeyhole size={24} />
          <strong>所有外部动作关闭</strong>
          <p>未创建供应商订单、付款、客户消息、Approval 或一次性 Permit。</p>
          <small>{workspace ? shortHash(workspace.snapshot_sha256) : "等待服务端快照"}</small>
          <Link href="/procurement">进入采购与收货控制 →</Link>
          <Link href="/finance-control">进入结算与现金控制 →</Link>
          <Link href="/profit-ledger">进入十五项实际利润账 →</Link>
          <Link href="/delivery-exceptions">进入物流交付与异常权威 →</Link>
          <Link href="/warehouse-fulfillment">进入仓库执行与包裹交接权威 →</Link>
        </aside>
      </section>

      <section className={styles.boundary} aria-label="OMS 执行边界">
        <strong data-state={viewState}>{label(viewState)}</strong>
        <span>legacy inferred · false</span>
        <span>client recalculation · false</span>
        <span>supplier order / payment · false / false</span>
        <span>Approval / Permit · false / false</span>
        <b>external write · false</b>
      </section>

      {(scopeBusy || workspaceBusy) && !workspace ? (
        <section className={styles.notice} role="status">
          <RefreshCw size={20} />
          <div>
            <strong>正在量取 PostgreSQL 当前事实</strong>
            <p>真实结果返回前不填充订单、金额或完成状态。</p>
          </div>
        </section>
      ) : null}

      {viewState === "error" ? (
        <section className={styles.error} role="alert">
          <CircleAlert size={22} />
          <div><strong>OMS 权威暂不可用</strong><p>{detail}</p></div>
          <button type="button" onClick={() => (
            storeRef ? void loadWorkspace(storeRef) : void loadScope()
          )}>重试</button>
        </section>
      ) : null}

      {workspace ? (
        <>
          <section className={styles.scopeBar}>
            <div><span>Tenant</span><strong>{workspace.scope.tenant_ref}</strong></div>
            <div><span>Entity</span><strong>{workspace.scope.entity_ref ?? "no_data"}</strong></div>
            <div><span>Store</span><strong>{workspace.scope.store_ref}</strong></div>
            <div><span>Grant hash</span><code>{shortHash(workspace.scope.scope_grant_authority_sha256)}</code></div>
            <div><span>As of</span><strong>{workspace.as_of}</strong></div>
          </section>

          <section className={styles.metrics}>
            <article><span>当前订单</span><strong>{workspace.counts.total_current_orders}</strong><small>服务端 current projection</small></article>
            <article><span>正式订单 Facts</span><strong>{workspace.counts.raw_order_facts}</strong><small>exact scope</small></article>
            <article><span>退货 Facts</span><strong>{workspace.counts.raw_return_facts}</strong><small>explicit order link</small></article>
            <article data-alert={workspace.counts.invalid_facts > 0}><span>坏事实 / 当前阻断</span><strong>{workspace.counts.invalid_facts} / {workspace.counts.blocked_current_orders}</strong><small>fail closed</small></article>
          </section>

          {workspace.status === "no_data" ? (
            <section className={styles.empty}>
              <Fingerprint size={24} />
              <div>
                <strong>no_data · 当前作用域没有正式 Ozon Order Fact</strong>
                <p>不会读取 legacy orders，也不会用市场观察或评论数伪造订单。</p>
              </div>
            </section>
          ) : null}

          {workspace.blockers.length ? (
            <section className={styles.blockers}>
              <header><span>SOURCE GAPS</span><h2>先修事实，再做外部动作</h2></header>
              <div>
                {workspace.blockers.map((blocker) => (
                  <article key={blocker.code}>
                    <strong>{blocker.severity} · {blocker.code}</strong>
                    <p>{blocker.next}</p>
                    <small>{blocker.owner} · {blocker.sla}</small>
                    <Link href={blocker.next_workspace}>打开处理工作区 <ChevronRight size={14} /></Link>
                  </article>
                ))}
              </div>
            </section>
          ) : null}

          {workspace.orders.length ? (
            <section className={styles.orders}>
              <header>
                <div><span>CURRENT ORDERS</span><h2>订单当前态与不可变时间线</h2></div>
                <small>{workspace.contract_id}</small>
              </header>
              <div className={styles.orderGrid}>
                {workspace.orders.map((order) => (
                  <article key={order.external_id} data-state={order.projection_status}>
                    <div className={styles.orderHead}>
                      <div>
                        <span>{order.projection_status}</span>
                        <h3>{order.external_id}</h3>
                        <code>{order.sku ?? "SKU blocked by Fact validation"}</code>
                      </div>
                      <strong>{label(order.current_state)}</strong>
                    </div>
                    <div className={styles.nextAction}>
                      <Clock3 size={17} />
                      <div><strong>{order.owner} · {order.sla}</strong><p>{order.next}</p></div>
                    </div>
                    <ol className={styles.timeline}>
                      {order.timeline.map((event) => (
                        <li key={event.fact_id}>
                          <span />
                          <div>
                            <strong>{label(event.canonical_status ?? "unknown")}</strong>
                            <small>{event.effective_at}</small>
                            <code>Fact {event.fact_id} · Evidence {event.evidence_id}</code>
                          </div>
                        </li>
                      ))}
                      {order.blocked_events.map((event) => (
                        <li key={event.fact_id} data-blocked>
                          <span />
                          <div>
                            <strong>事实核验失败 · 不复用旧状态</strong>
                            <small>{event.effective_at}</small>
                            <code>{event.blocker_code} · Fact {event.fact_id}</code>
                          </div>
                        </li>
                      ))}
                    </ol>
                    <footer>
                      <Link href={order.next_workspace}>下一工作区 <ChevronRight size={14} /></Link>
                      <span>Evidence {order.evidence_ids.length} · Facts {order.fact_ids.length}</span>
                    </footer>
                  </article>
                ))}
              </div>
              {workspace.query.next_cursor ? (
                <button
                  className={styles.nextPage}
                  type="button"
                  disabled={workspaceBusy}
                  onClick={() => void loadWorkspace(
                    workspace.scope.store_ref,
                    workspace.query.next_cursor,
                  )}
                >
                  {workspaceBusy ? "读取中…" : "读取下一页正式订单"}
                </button>
              ) : null}
            </section>
          ) : null}

          <section className={styles.agent}>
            <Bot size={24} />
            <div>
              <span>AGENT AUTHORITY · {workspace.agent_support.authority}</span>
              <h2>模型可建议，不能自批、自发 Permit 或执行</h2>
              <p>
                输入快照 {shortHash(workspace.agent_support.input_snapshot_sha256)}；
                当前自动动作 {workspace.agent_support.automatic_actions.length}。
              </p>
            </div>
          </section>
        </>
      ) : null}
    </main>
  );
}
