"use client";

import {
  ArrowLeft,
  Bot,
  Boxes,
  ChevronRight,
  CircleAlert,
  Fingerprint,
  LockKeyhole,
  RefreshCw,
  ShieldCheck,
  Store,
  Warehouse,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { fetchJson } from "../../lib/fetch-json";
import styles from "./inventory.module.css";

type WorkspaceStatus = "ready" | "partial" | "blocked" | "no_data";
type ViewState = WorkspaceStatus | "loading" | "error";

type Blocker = {
  code: string;
  severity: string;
  owner: string;
  sla: string;
  next: string;
  next_workspace: string;
};

type Snapshot = {
  fact_id: string;
  evidence_id: string;
  sku?: string;
  warehouse_ref?: string;
  cluster_ref?: string | null;
  fulfillment_mode?: "FBP" | "realFBS";
  quantities?: {
    available_quantity: number;
    reserved_quantity: number;
    in_transit_quantity: number;
    damaged_quantity: number;
    quarantine_quantity: number;
  };
  effective_at: string;
  blocker_code?: string;
};

type InventoryCell = {
  cell_key: string;
  projection_status: "ready" | "blocked";
  current_snapshot: Snapshot;
  last_valid_snapshot: Snapshot | null;
  timeline: Snapshot[];
  blocked_events: Snapshot[];
  fact_ids: string[];
  evidence_ids: string[];
  owner: string;
  sla: string;
  next: string;
  next_workspace: string;
};

type SkuSummary = {
  sku: string;
  available_quantity: number;
  reserved_quantity: number;
  open_order_demand_quantity: number | null;
  shortage_quantity: number | null;
  coverage_status: "covered" | "shortage" | "blocked";
  fulfillment_modes: string[];
  warehouse_refs: string[];
  fact_ids: string[];
  evidence_ids: string[];
  owner: string;
  sla: string;
  next: string;
  next_workspace: string;
};

type InventoryWorkspace = {
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
  };
  counts: {
    raw_inventory_facts: number;
    total_current_cells: number;
    page_current_cells: number;
    blocked_current_cells: number;
    invalid_facts: number;
    sku_summaries: number;
    open_demand_orders: number;
    legacy_inventory_rows_read: 0;
    marketplace_observations_inferred: 0;
  };
  inventory_cells: InventoryCell[];
  sku_summaries: SkuSummary[];
  order_demand: {
    status: WorkspaceStatus;
    oms_snapshot_sha256: string | null;
    open_order_count: number;
    demand_by_sku: Record<string, number>;
    source_gaps: string[];
    legacy_orders_inferred: false;
  };
  source_gaps: string[];
  blockers: Blocker[];
  agent_support: {
    authority: "decision_support_only";
    input_snapshot_sha256: string | null;
    suggestions: Array<{
      sku: string;
      coverage_status: string;
      owner: string;
      next: string;
      external_action_allowed: false;
    }>;
    automatic_actions: [];
    self_approval_allowed: false;
    permit_issue_allowed: false;
  };
  control_envelope: {
    read_only: true;
    client_recalculation_allowed: false;
    inventory_adjustment_created: false;
    reservation_created: false;
    fulfillment_command_created: false;
    supplier_order_created: false;
    payment_created: false;
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

const labels: Record<string, string> = {
  ready: "权威可用",
  partial: "部分可用",
  blocked: "已阻断",
  no_data: "暂无正式库存",
  covered: "库存覆盖",
  shortage: "存在短缺",
  loading: "读取中",
  error: "读取失败",
};

function label(value: string) {
  return labels[value] ?? value;
}

function shortHash(value: string | null) {
  return value ? `${value.slice(0, 12)}…${value.slice(-8)}` : "no_data";
}

export function InventoryConsole() {
  const [stores, setStores] = useState<string[]>([]);
  const [storeRef, setStoreRef] = useState("");
  const [workspace, setWorkspace] = useState<InventoryWorkspace | null>(null);
  const [viewState, setViewState] = useState<ViewState>("loading");
  const [busy, setBusy] = useState(true);
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
    setBusy(true);
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
      setBusy(false);
      if (authorized.length === 0) {
        setViewState("blocked");
        setDetail("当前身份没有授权店铺；库存不会回退到全局或页面观察。");
      }
    } catch (error) {
      if (signal?.aborted) return;
      setBusy(false);
      setViewState("error");
      setDetail(error instanceof Error ? error.message : "授权作用域读取失败");
    }
  }, [redirectForAuth]);

  const loadWorkspace = useCallback(
    async (store: string, cursor?: string | null, signal?: AbortSignal) => {
      if (!store) return;
      setBusy(true);
      setDetail("");
      try {
        const query = new URLSearchParams({
          store_ref: store,
          page_size: "100",
        });
        if (cursor) query.set("cursor", cursor);
        const response = await fetchJson<InventoryWorkspace | ErrorPayload>(
          `/backend/v1/inventory/workspace?${query.toString()}`,
          { cache: "no-store", signal },
        );
        if (redirectForAuth(response.status)) return;
        const payload = await response.json();
        if (!response.ok) {
          const message =
            "detail" in payload
              ? payload.detail ?? `API ${response.status}`
              : `API ${response.status}`;
          setViewState(
            response.status === 403 || response.status === 422
              ? "blocked"
              : "error",
          );
          setWorkspace(null);
          setDetail(String(message));
          setBusy(false);
          return;
        }
        const next = payload as InventoryWorkspace;
        setWorkspace(next);
        setViewState(next.status);
        setBusy(false);
      } catch (error) {
        if (signal?.aborted) return;
        setBusy(false);
        setViewState("error");
        setDetail(
          error instanceof Error
            ? error.message
            : "库存权威暂不可用，请检查网络后重试。",
        );
      }
    },
    [redirectForAuth],
  );

  useEffect(() => {
    const controller = new AbortController();
    void loadScope(controller.signal);
    return () => controller.abort("inventory scope unmounted");
  }, [loadScope]);

  useEffect(() => {
    if (!storeRef) return;
    const controller = new AbortController();
    void loadWorkspace(storeRef, null, controller.signal);
    return () => controller.abort("inventory store changed");
  }, [loadWorkspace, storeRef]);

  return (
    <main className={styles.page}>
      <header className={styles.topbar}>
        <Link href="/commerce-os" className={styles.backLink}>
          <ArrowLeft size={16} />
          Commerce OS
        </Link>
        <div className={styles.productMark}>
          <span><Warehouse size={18} /></span>
          <div>
            <strong>库存与履约</strong>
            <small>KJDS AI ERP · OFFICIAL FACTS ONLY</small>
          </div>
        </div>
        <label className={styles.storePicker}>
          <Store size={15} />
          <span>授权店铺</span>
          <select
            aria-label="选择授权店铺"
            value={storeRef}
            disabled={busy || stores.length === 0}
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
            EXACT SKU · WAREHOUSE · FBP / realFBS · OMS DEMAND
          </span>
          <h1>库存由正式快照证明，<em>履约建议由真实订单驱动</em></h1>
          <p>
            只读取 exact tenant / entity / store / grant 下的 Ozon Inventory
            Fact，并与同一时点的 Native OMS 当前态组合。页面观察、静态费用表和
            Agent 猜测都不能变成库存。
          </p>
        </div>
        <aside>
          <LockKeyhole size={24} />
          <strong>所有写动作关闭</strong>
          <p>库存调整、预占、履约、采购、付款、Approval 与 Permit 均未创建。</p>
          <small>{workspace ? shortHash(workspace.snapshot_sha256) : "等待事实快照"}</small>
          <Link href="/procurement">进入采购与收货控制 →</Link>
          <Link href="/finance-control">进入结算与现金控制 →</Link>
          <Link href="/delivery-exceptions">进入物流交付与异常权威 →</Link>
          <Link href="/warehouse-fulfillment">进入仓库执行与包裹交接权威 →</Link>
        </aside>
      </section>

      <section className={styles.boundary} aria-label="库存执行边界">
        <strong data-state={viewState}>{label(viewState)}</strong>
        <span>legacy / market inferred · false / false</span>
        <span>client recalculation · false</span>
        <span>adjust / reserve / fulfill · false / false / false</span>
        <span>Approval / Permit · false / false</span>
        <b>external write · false</b>
      </section>

      {busy && !workspace ? (
        <section className={styles.notice} role="status">
          <RefreshCw size={20} />
          <div>
            <strong>正在量取 PostgreSQL 正式库存和 OMS 需求</strong>
            <p>真实结果返回前不填充库存、缺货或履约状态。</p>
          </div>
        </section>
      ) : null}

      {viewState === "error" ? (
        <section className={styles.error} role="alert">
          <CircleAlert size={22} />
          <div><strong>库存权威暂不可用</strong><p>{detail}</p></div>
          <button
            type="button"
            onClick={() => (
              storeRef ? void loadWorkspace(storeRef) : void loadScope()
            )}
          >
            重试
          </button>
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
            <article><span>当前库存单元</span><strong>{workspace.counts.total_current_cells}</strong><small>exact warehouse cells</small></article>
            <article><span>库存 Facts</span><strong>{workspace.counts.raw_inventory_facts}</strong><small>official snapshots</small></article>
            <article><span>待履约订单</span><strong>{workspace.counts.open_demand_orders}</strong><small>Native OMS current state</small></article>
            <article data-alert={workspace.counts.invalid_facts > 0}><span>坏事实 / 阻断单元</span><strong>{workspace.counts.invalid_facts} / {workspace.counts.blocked_current_cells}</strong><small>latest invalid fails closed</small></article>
          </section>

          {workspace.status === "no_data" ? (
            <section className={styles.empty}>
              <Fingerprint size={24} />
              <div>
                <strong>no_data · 当前作用域没有正式 Ozon Inventory Fact</strong>
                <p>不会读取旧库存表、商品页库存或毛子/荔枝静态数据。</p>
              </div>
            </section>
          ) : null}

          {workspace.blockers.length ? (
            <section className={styles.panel}>
              <header><span>SOURCE GAPS</span><h2>缺什么、谁负责、下一步在哪里</h2></header>
              <div className={styles.blockerGrid}>
                {workspace.blockers.map((blocker) => (
                  <article key={blocker.code} data-alert>
                    <strong>{blocker.severity} · {blocker.code}</strong>
                    <p>{blocker.next}</p>
                    <small>{blocker.owner} · {blocker.sla}</small>
                    <Link href={blocker.next_workspace}>
                      打开工作区 <ChevronRight size={14} />
                    </Link>
                  </article>
                ))}
              </div>
            </section>
          ) : null}

          {workspace.sku_summaries.length ? (
            <section className={styles.panel}>
              <header><span>SERVER COVERAGE</span><h2>SKU 库存×待履约需求</h2></header>
              <div className={styles.summaryGrid}>
                {workspace.sku_summaries.map((summary) => (
                  <article key={summary.sku} data-state={summary.coverage_status}>
                    <div>
                      <span>{label(summary.coverage_status)}</span>
                      <h3>{summary.sku}</h3>
                      <small>{summary.fulfillment_modes.join(" · ")} · {summary.warehouse_refs.join(" · ")}</small>
                    </div>
                    <dl>
                      <div><dt>可用</dt><dd>{summary.available_quantity}</dd></div>
                      <div><dt>已预留</dt><dd>{summary.reserved_quantity}</dd></div>
                      <div><dt>待履约</dt><dd>{summary.open_order_demand_quantity ?? "no_data"}</dd></div>
                      <div><dt>短缺</dt><dd>{summary.shortage_quantity ?? "no_data"}</dd></div>
                    </dl>
                    <p>{summary.next}</p>
                    <footer>
                      <Link href={summary.next_workspace}>下一工作区 <ChevronRight size={14} /></Link>
                      <span>{summary.owner} · {summary.sla}</span>
                    </footer>
                  </article>
                ))}
              </div>
            </section>
          ) : null}

          {workspace.inventory_cells.length ? (
            <section className={styles.panel}>
              <header><span>IMMUTABLE CELLS</span><h2>仓库快照与坏最新事实</h2></header>
              <div className={styles.cellGrid}>
                {workspace.inventory_cells.map((cell) => {
                  const current = cell.current_snapshot;
                  return (
                    <article key={cell.cell_key} data-state={cell.projection_status}>
                      <div className={styles.cellHead}>
                        <div>
                          <span>{cell.projection_status}</span>
                          <h3>{current.sku ?? cell.cell_key}</h3>
                          <code>{cell.cell_key}</code>
                        </div>
                        <strong>{current.fulfillment_mode ?? "blocked"}</strong>
                      </div>
                      {current.quantities ? (
                        <p>
                          可用 {current.quantities.available_quantity} ·
                          预留 {current.quantities.reserved_quantity} ·
                          在途 {current.quantities.in_transit_quantity}
                        </p>
                      ) : (
                        <p>最新快照核验失败；旧库存未复用为 current。</p>
                      )}
                      <small>Fact {current.fact_id} · Evidence {current.evidence_id}</small>
                    </article>
                  );
                })}
              </div>
              {workspace.query.next_cursor ? (
                <button
                  className={styles.nextPage}
                  type="button"
                  disabled={busy}
                  onClick={() => void loadWorkspace(
                    workspace.scope.store_ref,
                    workspace.query.next_cursor,
                  )}
                >
                  {busy ? "读取中…" : "读取下一页库存单元"}
                </button>
              ) : null}
            </section>
          ) : null}

          <section className={styles.agent}>
            <Bot size={24} />
            <div>
              <span>AGENT AUTHORITY · {workspace.agent_support.authority}</span>
              <h2>Agent 能解释缺货，不能自己改库存或下采购单</h2>
              <p>
                输入快照 {shortHash(workspace.agent_support.input_snapshot_sha256)}；
                当前建议 {workspace.agent_support.suggestions.length}，
                自动动作 {workspace.agent_support.automatic_actions.length}。
              </p>
            </div>
            <Boxes size={22} />
          </section>
        </>
      ) : null}
    </main>
  );
}
