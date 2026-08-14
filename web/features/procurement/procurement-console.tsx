"use client";

import {
  ArrowLeft,
  Bot,
  Boxes,
  ChevronRight,
  CircleAlert,
  ClipboardCheck,
  Factory,
  FileCheck2,
  Fingerprint,
  LockKeyhole,
  PackageCheck,
  RefreshCw,
  ScanLine,
  ShieldCheck,
  Store,
  Truck,
  WalletCards,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { fetchJson } from "../../lib/fetch-json";
import styles from "./procurement.module.css";

type WorkspaceStatus = "ready" | "partial" | "blocked" | "no_data";
type ViewState = WorkspaceStatus | "loading" | "error";
type Stage =
  | "approved_to_order"
  | "order_confirmed"
  | "shipped"
  | "received"
  | "inspected"
  | "golden_sample_approved"
  | "sample_rejected"
  | "rework_required"
  | "cancelled";

type TimelineEvent = {
  event_id: string;
  sequence: number;
  event_type: string;
  stage: Stage;
  effective_at: string;
  recorded_at: string;
  facts: Record<string, unknown>;
  evidence_id: string;
};

type ProcurementOrder = {
  purchase_order_id: string;
  product: {
    id: string;
    sku: string;
    name: string;
    market: string;
    channel: string;
    status: string;
    created_at: string;
    scope_as_of: string;
  };
  supplier_ref: string;
  quantity: number;
  currency: string;
  unit_price: string;
  order_value: string;
  created_at: string;
  stage: Stage;
  latest_effective_at: string;
  next_events: string[];
  timeline: TimelineEvent[];
  receipt: {
    ordered_quantity: number;
    received_quantity: number | null;
    damaged_quantity: number | null;
    inspected_quantity: number | null;
    passed_quantity: number | null;
    defect_count: number | null;
    quantity_conserved: true;
  };
  decision_basis: {
    approval_id: string;
    approval_status: string;
    independent_approval: boolean;
    offer_id: string;
    scenario_id: string;
    expected_cm3_cny: string;
    cost_evidence_complete: boolean;
    authority_evidence_id: string;
  };
  financial_authority: FinancialAuthority;
  owner: string;
  sla: string;
  next: string;
  next_workspace: string;
  readiness: {
    procurement_basis_verified: boolean;
    receiving_timeline_verified: boolean;
    ap_invoice_verified: false;
    supplier_payment_verified: false;
  };
};

type FinancialAuthority = {
  status: "gated";
  accounts_payable_invoice_authority_available: false;
  supplier_payment_authority_available: false;
  invoice_or_payment_claim_allowed: false;
  reason: string;
};

type Workspace = {
  contract_id: string;
  status: WorkspaceStatus;
  as_of: string;
  scope: {
    tenant_ref: string;
    entity_ref: string | null;
    store_ref: string;
    scope_grant_authority_sha256: string | null;
  };
  filters: {
    query: string | null;
    stage: Stage | null;
  };
  counts: Record<string, number>;
  pagination: {
    page_size: number;
    next_cursor: string | null;
  };
  orders: ProcurementOrder[];
  excluded: {
    count: number;
    reason_counts: Record<string, number>;
    business_values_exposed: false;
  };
  source_gaps: string[];
  blockers: {
    code: string;
    severity: string;
    owner: string;
    next_action: string;
    workspace: string;
  }[];
  financial_authority: FinancialAuthority;
  owner: string;
  sla: string;
  next: string;
  next_workspace: string;
  upstream: {
    source_snapshot_sha256: string | null;
  };
  agent_artifact: {
    contract_id: string;
    version: string;
    artifact_sha256: string;
    authority: string;
    self_approval_allowed: false;
    permit_issue_allowed: false;
    purchase_order_creation_allowed: false;
    receipt_confirmation_allowed: false;
    payment_allowed: false;
    external_write_allowed: false;
  };
  control_envelope: {
    read_only: true;
    scoped_input_read: boolean;
    client_recalculation_allowed: false;
    legacy_procurement_rows_admitted: false;
    product_created: false;
    supplier_contacted: false;
    purchase_order_created: false;
    receipt_confirmed: false;
    inspection_record_created: false;
    approval_created: false;
    permit_created: false;
    invoice_created: false;
    payment_initiated: false;
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

const stages: Stage[] = [
  "approved_to_order",
  "order_confirmed",
  "shipped",
  "received",
  "inspected",
  "golden_sample_approved",
  "sample_rejected",
  "rework_required",
  "cancelled",
];

const labels: Record<string, string> = {
  ready: "权威可用",
  partial: "部分可用",
  blocked: "失败关闭",
  no_data: "真实 no_data",
  loading: "读取中",
  error: "读取失败",
  approved_to_order: "已批准，待下单",
  order_confirmed: "供应商已确认",
  shipped: "已发货",
  received: "已收货",
  inspected: "已验货",
  golden_sample_approved: "金样通过",
  sample_rejected: "样品拒绝",
  rework_required: "要求返工",
  cancelled: "已取消",
  inspection_completed: "验货完成",
};

function label(value: string) {
  return labels[value] ?? value;
}

function shortHash(value: string | null) {
  return value ? `${value.slice(0, 10)}…${value.slice(-8)}` : "no_data";
}

function displayFact(value: unknown) {
  if (value === null || value === undefined || value === "") return "no_data";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function ProcurementConsole() {
  const [stores, setStores] = useState<string[]>([]);
  const [storeRef, setStoreRef] = useState("");
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [viewState, setViewState] = useState<ViewState>("loading");
  const [scopeBusy, setScopeBusy] = useState(true);
  const [workspaceBusy, setWorkspaceBusy] = useState(false);
  const [detail, setDetail] = useState("");
  const [queryDraft, setQueryDraft] = useState("");
  const [stageDraft, setStageDraft] = useState("");
  const [query, setQuery] = useState("");
  const [stage, setStage] = useState("");

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

  const loadScope = useCallback(
    async (signal?: AbortSignal) => {
      setScopeBusy(true);
      setDetail("");
      try {
        const response = await fetchJson<StrategyPacks | ErrorPayload>(
          "/backend/v1/seller-os/strategy-packs",
          { cache: "no-store", signal },
        );
        if (redirectForAuth(response.status)) return;
        const body = await response.json();
        if (!response.ok) {
          throw new Error(
            "detail" in body
              ? body.detail ?? `API ${response.status}`
              : `API ${response.status}`,
          );
        }
        const authorized = (body as StrategyPacks).authorized_scope.store_refs;
        setStores(authorized);
        setStoreRef((current) =>
          current && authorized.includes(current)
            ? current
            : authorized[0] ?? "",
        );
        if (authorized.length === 0) {
          setViewState("blocked");
          setDetail("当前身份没有授权店铺；采购控制不会回退读取 legacy 全局订单。");
        }
      } catch (reason) {
        if (signal?.aborted) return;
        setViewState("error");
        setDetail(
          reason instanceof Error ? reason.message : "授权作用域读取失败",
        );
      } finally {
        if (!signal?.aborted) setScopeBusy(false);
      }
    },
    [redirectForAuth],
  );

  const loadWorkspace = useCallback(
    async (
      store: string,
      cursor?: string | null,
      signal?: AbortSignal,
    ) => {
      if (!store) return;
      setWorkspaceBusy(true);
      setDetail("");
      try {
        const params = new URLSearchParams({
          store_ref: store,
          page_size: "25",
        });
        if (query) params.set("query", query);
        if (stage) params.set("stage", stage);
        if (cursor) params.set("cursor", cursor);
        const response = await fetchJson<Workspace | ErrorPayload>(
          `/backend/v1/procurement/workspace?${params.toString()}`,
          { cache: "no-store", signal },
        );
        if (redirectForAuth(response.status)) return;
        const body = await response.json();
        if (!response.ok) {
          setWorkspace(null);
          setViewState(
            response.status === 403 || response.status === 422
              ? "blocked"
              : "error",
          );
          setDetail(
            "detail" in body
              ? String(body.detail ?? `API ${response.status}`)
              : `API ${response.status}`,
          );
          return;
        }
        const next = body as Workspace;
        setWorkspace((current) =>
          cursor && current
            ? {
                ...next,
                orders: [...current.orders, ...next.orders],
              }
            : next,
        );
        setViewState(next.status);
      } catch (reason) {
        if (signal?.aborted) return;
        setWorkspace(null);
        setViewState("error");
        setDetail(
          reason instanceof Error
            ? reason.message
            : "采购与收货权威暂不可用",
        );
      } finally {
        if (!signal?.aborted) setWorkspaceBusy(false);
      }
    },
    [query, redirectForAuth, stage],
  );

  useEffect(() => {
    const controller = new AbortController();
    void loadScope(controller.signal);
    return () => controller.abort("procurement scope unmounted");
  }, [loadScope]);

  useEffect(() => {
    if (!storeRef) return;
    const controller = new AbortController();
    void loadWorkspace(storeRef, null, controller.signal);
    return () => controller.abort("procurement store changed");
  }, [loadWorkspace, storeRef]);

  function applyFilters() {
    setQuery(queryDraft.trim());
    setStage(stageDraft);
  }

  const busy = scopeBusy || workspaceBusy;

  return (
    <main className={styles.page}>
      <header className={styles.topbar}>
        <Link className={styles.backLink} href="/commerce-os">
          <ArrowLeft size={15} />
          Commerce OS
        </Link>
        <div className={styles.productMark}>
          <span>
            <Boxes size={18} />
          </span>
          <div>
            <strong>KJDS PROCUREMENT CONTROL</strong>
            <small>EXACT-SCOPE · EVIDENCE-BACKED · READ ONLY</small>
          </div>
        </div>
        <label className={styles.storePicker}>
          <Store size={14} />
          <select
            aria-label="授权店铺"
            disabled={scopeBusy}
            onChange={(event) => setStoreRef(event.target.value)}
            value={storeRef}
          >
            {stores.length ? (
              stores.map((store) => (
                <option key={store} value={store}>
                  {store}
                </option>
              ))
            ) : (
              <option value="">无授权店铺</option>
            )}
          </select>
        </label>
      </header>

      <section className={styles.hero}>
        <div>
          <span className={styles.eyebrow}>
            <ScanLine size={15} />
            DECISION → ORDER → RECEIVING → INSPECTION
          </span>
          <h1>
            采购与收货，
            <em>每一步都有证据。</em>
          </h1>
          <p>
            服务端归并 Canonical Product、Supplier Offer、完整 CM3、独立审批和收货事件。
            页面不重算订单金额、数量守恒或阶段，也不把缺失的应付与付款事实伪装成闭环。
          </p>
        </div>
        <aside>
          <ShieldCheck size={22} />
          <b>最新权威记录失败关闭</b>
          <p>坏 Evidence、跨作用域、跳步或数量不守恒会整单排除。</p>
          <small>{workspace?.contract_id ?? "workspace contract pending"}</small>
        </aside>
      </section>

      <section className={styles.boundary}>
        <div>
          <span>workspace</span>
          <strong data-state={viewState}>{label(viewState)}</strong>
        </div>
        <div>
          <span>scoped input</span>
          <b>{workspace?.control_envelope.scoped_input_read ? "true" : "false"}</b>
        </div>
        <div>
          <span>client recalculation</span>
          <b>false</b>
        </div>
        <div>
          <span>Approval / Permit</span>
          <b>false / false</b>
        </div>
        <div>
          <span>AP / payment</span>
          <b>gated / gated</b>
        </div>
        <div>
          <span>external write</span>
          <b>false</b>
        </div>
      </section>

      <section className={styles.flow} aria-label="采购与收货业务流">
        <article>
          <ClipboardCheck size={17} />
          <b>独立审批</b>
          <span>Offer + CM3 + quantity</span>
        </article>
        <ChevronRight size={15} />
        <article>
          <Factory size={17} />
          <b>供应商确认</b>
          <span>order reference + promise</span>
        </article>
        <ChevronRight size={15} />
        <article>
          <Truck size={17} />
          <b>发运与收货</b>
          <span>tracking + physical count</span>
        </article>
        <ChevronRight size={15} />
        <article>
          <PackageCheck size={17} />
          <b>验货与处置</b>
          <span>pass / defect / rework</span>
        </article>
        <ChevronRight size={15} />
        <article>
          <WalletCards size={17} />
          <b>AP / Payment</b>
          <span>明确 gated，不越权推断</span>
        </article>
      </section>

      <section className={styles.filters}>
        <label>
          精确搜索
          <input
            onChange={(event) => setQueryDraft(event.target.value)}
            placeholder="订单 / SKU / 商品 / supplier"
            value={queryDraft}
          />
        </label>
        <label>
          阶段
          <select
            onChange={(event) => setStageDraft(event.target.value)}
            value={stageDraft}
          >
            <option value="">全部阶段</option>
            {stages.map((item) => (
              <option key={item} value={item}>
                {label(item)}
              </option>
            ))}
          </select>
        </label>
        <button disabled={busy} onClick={applyFilters} type="button">
          {workspaceBusy ? "读取中…" : "应用服务端筛选"}
        </button>
      </section>

      {viewState === "loading" || busy ? (
        <section className={styles.notice} role="status">
          <RefreshCw className={styles.spin} size={20} />
          <div>
            <b>正在读取 exact-scope 采购投影</b>
            <p>只接受当前 entity / store / as_of 的服务端结果。</p>
          </div>
        </section>
      ) : null}

      {viewState === "error" ? (
        <section className={styles.error} role="alert">
          <CircleAlert size={21} />
          <div>
            <b>采购权威读取失败</b>
            <p>{detail || "请检查 API 与运行态。"}</p>
          </div>
          <button onClick={() => void loadScope()} type="button">
            重试
          </button>
        </section>
      ) : null}

      {viewState === "blocked" ? (
        <section className={styles.error} role="alert">
          <LockKeyhole size={21} />
          <div>
            <b>最新权威记录失败关闭</b>
            <p>
              {detail ||
                "业务值已隐藏；先修复 Evidence、作用域、时间线或数量守恒。"}
            </p>
          </div>
          <button
            disabled={!storeRef}
            onClick={() => void loadWorkspace(storeRef)}
            type="button"
          >
            重试
          </button>
        </section>
      ) : null}

      {workspace ? (
        <>
          <section className={styles.scopeBar}>
            <div>
              <span>tenant</span>
              <strong>{workspace.scope.tenant_ref ?? "no_data"}</strong>
            </div>
            <div>
              <span>entity</span>
              <strong>{workspace.scope.entity_ref ?? "no_data"}</strong>
            </div>
            <div>
              <span>store</span>
              <strong>{workspace.scope.store_ref}</strong>
            </div>
            <div>
              <span>as_of</span>
              <strong>{workspace.as_of}</strong>
            </div>
            <div>
              <span>snapshot</span>
              <code>{shortHash(workspace.snapshot_sha256)}</code>
            </div>
          </section>

          <section className={styles.metrics}>
            <article>
              <span>exact orders</span>
              <strong>{workspace.counts.total ?? 0}</strong>
              <small>legacy rows excluded</small>
            </article>
            <article>
              <span>in transit</span>
              <strong>{workspace.counts.shipped ?? 0}</strong>
              <small>server stage</small>
            </article>
            <article>
              <span>received</span>
              <strong>{workspace.counts.received ?? 0}</strong>
              <small>physical Evidence</small>
            </article>
            <article>
              <span>inspected</span>
              <strong>{workspace.counts.inspected ?? 0}</strong>
              <small>quantity conserved</small>
            </article>
            <article>
              <span>excluded</span>
              <strong>{workspace.excluded.count}</strong>
              <small>business values exposed · false</small>
            </article>
          </section>
        </>
      ) : null}

      {workspace && viewState === "no_data" ? (
        <section className={styles.empty}>
          <FileCheck2 size={22} />
          <div>
            <b>真实 no_data</b>
            <p>
              当前 exact tenant / entity / store / as_of 没有可验证采购订单。
              系统没有回退读取 legacy 样品单，也没有伪造订单、收货、应付或付款。
            </p>
          </div>
        </section>
      ) : null}

      {workspace && workspace.source_gaps.length ? (
        <section className={styles.gapPanel}>
          <header>
            <div>
              <CircleAlert size={18} />
              <b>Source gaps / gates</b>
            </div>
            <small>{workspace.source_gaps.length} 项</small>
          </header>
          <div>
            {workspace.source_gaps.map((gap) => (
              <span key={gap}>{gap}</span>
            ))}
          </div>
        </section>
      ) : null}

      {workspace?.orders.length ? (
        <section className={styles.orderList}>
          {workspace.orders.map((order) => (
            <article className={styles.order} key={order.purchase_order_id}>
              <header>
                <div>
                  <span className={styles.stage}>{label(order.stage)}</span>
                  <h2>{order.product.name}</h2>
                  <p>
                    {order.product.sku} · {order.supplier_ref}
                  </p>
                </div>
                <div className={styles.orderValue}>
                  <small>SERVER ORDER VALUE</small>
                  <strong>
                    {order.order_value} {order.currency}
                  </strong>
                  <span>
                    {order.quantity} × {order.unit_price} {order.currency}
                  </span>
                </div>
              </header>

              <div className={styles.orderGrid}>
                <section>
                  <span>ORDER ID</span>
                  <code>{order.purchase_order_id}</code>
                </section>
                <section>
                  <span>OWNER / SLA</span>
                  <strong>{order.owner}</strong>
                  <small>{order.sla}</small>
                </section>
                <section>
                  <span>APPROVAL</span>
                  <strong>
                    {order.decision_basis.approval_status} · independent{" "}
                    {String(order.decision_basis.independent_approval)}
                  </strong>
                  <small>{shortHash(order.decision_basis.approval_id)}</small>
                </section>
                <section>
                  <span>EXPECTED CM3</span>
                  <strong>{order.decision_basis.expected_cm3_cny} CNY</strong>
                  <small>
                    cost evidence complete ·{" "}
                    {String(order.decision_basis.cost_evidence_complete)}
                  </small>
                </section>
              </div>

              <div className={styles.receiptGrid}>
                {[
                  ["ordered", order.receipt.ordered_quantity],
                  ["received", order.receipt.received_quantity],
                  ["damaged", order.receipt.damaged_quantity],
                  ["inspected", order.receipt.inspected_quantity],
                  ["passed", order.receipt.passed_quantity],
                  ["defects", order.receipt.defect_count],
                ].map(([name, value]) => (
                  <div key={name}>
                    <span>{name}</span>
                    <strong>{value ?? "no_data"}</strong>
                  </div>
                ))}
              </div>

              <section className={styles.timeline}>
                <header>
                  <b>Evidence timeline</b>
                  <small>服务端确定性阶段；客户端不重算</small>
                </header>
                {order.timeline.length ? (
                  <ol>
                    {order.timeline.map((item) => (
                      <li key={item.event_id}>
                        <div className={styles.timelineMark}>
                          <span>{item.sequence}</span>
                        </div>
                        <div>
                          <header>
                            <strong>{label(item.event_type)}</strong>
                            <time>{item.effective_at}</time>
                          </header>
                          <div className={styles.factList}>
                            {Object.entries(item.facts).map(([key, value]) => (
                              <span key={key}>
                                {key}: <b>{displayFact(value)}</b>
                              </span>
                            ))}
                          </div>
                          <small>
                            Evidence · {shortHash(item.evidence_id)}
                          </small>
                        </div>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <p>尚无供应商确认事件；当前仍是已批准待下单。</p>
                )}
              </section>

              <footer>
                <div>
                  <span>NEXT</span>
                  <strong>{order.next}</strong>
                </div>
                <div>
                  <span>AP / PAYMENT</span>
                  <strong>gated / gated</strong>
                  <small>不能开票或付款</small>
                </div>
              </footer>
            </article>
          ))}
        </section>
      ) : null}

      {workspace?.pagination.next_cursor ? (
        <section className={styles.pagination}>
          <span>服务端 opaque cursor；保持作用域与排序确定性。</span>
          <button
            disabled={workspaceBusy}
            onClick={() =>
              void loadWorkspace(
                storeRef,
                workspace.pagination.next_cursor,
              )
            }
            type="button"
          >
            {workspaceBusy ? "读取中…" : "加载下一页"}
          </button>
        </section>
      ) : null}

      {workspace ? (
        <section className={styles.agent}>
          <div className={styles.agentIcon}>
            <Bot size={22} />
          </div>
          <div>
            <span>PROCUREMENT STEWARD ARTIFACT · v{workspace.agent_artifact.version}</span>
            <strong>只能建议与创建内部任务，不能下单、收货确认或付款。</strong>
            <p>
              self approval · false · Permit issue · false · external write ·
              false
            </p>
          </div>
          <code>{shortHash(workspace.agent_artifact.artifact_sha256)}</code>
        </section>
      ) : null}

      <footer className={styles.footer}>
        <div>
          <Fingerprint size={18} />
          <p>
            KJDS 保留 Canonical Product、Evidence、Decision 与收货结果；
            第三方 ERP 只能作为正式授权 Adapter，不能成为经营真相。
          </p>
        </div>
        <nav>
          <Link href="/sourcing-intelligence">供应研究</Link>
          <Link href="/pim">PIM</Link>
          <Link href="/inventory">库存履约</Link>
          <Link href="/accounts-payable">应付付款</Link>
          <Link href="/finance-control">结算现金</Link>
        </nav>
      </footer>
    </main>
  );
}
